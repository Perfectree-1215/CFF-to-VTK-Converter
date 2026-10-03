"""
PyFluent 라이브 세션이 돌려준 격자(field_data.get_mesh / SurfaceFieldDataRequest)를 VTK 데이터셋으로 조립한다.
numpy 와 vtk 만 쓴다 (pyfluent 를 import 하지 않으므로 오프라인 단위 시험이 가능).

출처: 사용자 참조 스크립트 cas2vtu.py(정독 기록 docs/probe/pyfluent-examples.md) 의 노드 순열·폴리헤드론 재감김·부피 검증 코드를 이식
(결정 004 축 1 A, docs/decisions/004-pyfluent-tab.md). 로그는 콜백 log(msg) 로 받는다.

Fluent → VTK 노드 순서: hex/tet/pyramid 는 밑면 감김이 VTK 와 반대라 뒤집고, wedge 는 그대로.
폴리헤드론 facet 은 Fluent 저장 방향(안팎 혼재)이라 셀 중심 기준으로 바깥을 향하게 다시 감는다.
부피는 Fluent 식(면 팬)으로 다시 계산해 SV_VOLUME 과 비교할 수 있다.
"""
from dataclasses import dataclass, field

import numpy as np

# Fluent 요소 타입 (ansys.fluent.core.fields.live_field_data.CellElementType 의 value)
FL_TRIANGLE, FL_TETRAHEDRON, FL_QUADRILATERAL, FL_HEXAHEDRON = 1, 2, 3, 4
FL_PYRAMID, FL_WEDGE, FL_POLYHEDRON, FL_GHOST = 5, 6, 7, 8
FL_QUAD_TET, FL_QUAD_HEX, FL_QUAD_PYR, FL_QUAD_WEDGE = 9, 10, 11, 12

# VTK 셀 타입 (vtkCellType.h)
VTK_TRIANGLE, VTK_POLYGON, VTK_QUAD, VTK_TETRA = 5, 7, 9, 10
VTK_HEXAHEDRON, VTK_WEDGE, VTK_PYRAMID = 12, 13, 14
VTK_QUADRATIC_TETRA, VTK_QUADRATIC_HEXAHEDRON = 24, 25
VTK_QUADRATIC_WEDGE, VTK_QUADRATIC_PYRAMID, VTK_POLYHEDRON = 26, 27, 42

# Fluent 요소 타입 → (VTK 타입, 노드 순열)
FLUENT_TO_VTK = {
    FL_TRIANGLE: (VTK_TRIANGLE, (0, 1, 2)),
    FL_QUADRILATERAL: (VTK_QUAD, (0, 1, 2, 3)),
    FL_TETRAHEDRON: (VTK_TETRA, (0, 2, 1, 3)),
    FL_HEXAHEDRON: (VTK_HEXAHEDRON, (0, 3, 2, 1, 4, 7, 6, 5)),
    FL_PYRAMID: (VTK_PYRAMID, (0, 3, 2, 1, 4)),
    FL_WEDGE: (VTK_WEDGE, (0, 1, 2, 3, 4, 5)),
    FL_QUAD_TET: (VTK_QUADRATIC_TETRA, tuple(range(10))),
    FL_QUAD_HEX: (VTK_QUADRATIC_HEXAHEDRON, tuple(range(20))),
    FL_QUAD_PYR: (VTK_QUADRATIC_PYRAMID, tuple(range(13))),
    FL_QUAD_WEDGE: (VTK_QUADRATIC_WEDGE, tuple(range(15))),
}

# VTK 셀의 방향을 뒤집는 순열
VTK_FLIP = {
    VTK_TETRA: (0, 2, 1, 3),
    VTK_HEXAHEDRON: (0, 3, 2, 1, 4, 7, 6, 5),
    VTK_PYRAMID: (0, 3, 2, 1, 4),
    VTK_WEDGE: (0, 2, 1, 3, 5, 4),
}

# 선형 3D 셀의 바깥 방향 면 (면 팬 부피 계산용). 부호 기준은 VTK 자체(vtkCellSizeFilter)와 같다 — 즉 VTK 가
# 유효하다고 보는 셀이면 여기서도 부피가 양수다. 2026-10-03 실측: hex·tet·pyramid·wedge 모두 VTK 와 부호 일치.
# (참조 스크립트 cas2vtu 의 wedge 면 정의는 VTK 와 부호가 반대였다 → (0,2,1),(3,4,5),… 로 바꿈.
#  Fluent 의 wedge 노드 순서는 샘플이 없어 미검증이며, 어느 쪽이든 orient_linear_cells 의 다수결 보정이 VTK 기준으로 맞춘다.)
VTK_FACES = {
    VTK_TETRA: ((0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)),
    VTK_PYRAMID: ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
    VTK_WEDGE: ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
    VTK_HEXAHEDRON: ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
}


def _noop(msg):
    pass


# =============================================================================
# 자료 구조
# =============================================================================
@dataclass
class ZoneMesh:
    """셀 존 하나의 체적 격자 (VTK 배치). cell_conn[cell_offsets[i]:cell_offsets[i+1]] = 셀 i 의 점 id.
    폴리헤드론 facet 은 face_offsets/face_conn 에 평탄하게, face_cell 이 소유 셀 index."""
    zone_id: int
    zone_name: str
    points: np.ndarray            # (n_points, 3) float64
    cell_types: np.ndarray        # (n_cells,) uint8
    cell_offsets: np.ndarray      # (n_cells + 1,) int64
    cell_conn: np.ndarray         # int64
    face_offsets: np.ndarray      # (n_faces + 1,) int64  (폴리헤드론 facet 만)
    face_conn: np.ndarray         # int64
    face_cell: np.ndarray         # (n_faces,) int64
    is_2d: bool = False
    cell_data: dict = field(default_factory=dict)

    @property
    def n_cells(self):
        return len(self.cell_types)

    @property
    def n_faces(self):
        return len(self.face_cell)

    def cell_nodes(self, vtk_type):
        """(해당 타입 셀 index, (n, k) 노드 행렬)."""
        idx = np.flatnonzero(self.cell_types == vtk_type)
        if len(idx) == 0:
            return idx, np.empty((0, 0), dtype=np.int64)
        k = int(self.cell_offsets[idx[0] + 1] - self.cell_offsets[idx[0]])
        return idx, self.cell_conn[self.cell_offsets[idx][:, None] + np.arange(k)]

    def point_mean_centroids(self):
        counts = np.diff(self.cell_offsets)
        cell_of_entry = np.repeat(np.arange(self.n_cells), counts)
        acc = np.zeros((self.n_cells, 3))
        np.add.at(acc, cell_of_entry, self.points[self.cell_conn])
        return acc / np.maximum(counts, 1)[:, None]


@dataclass
class SurfaceMesh:
    """경계 면 존 하나 (VTK PolyData 배치). 2점 면은 2D 의 선분."""
    zone_id: int
    name: str
    points: np.ndarray            # (n_points, 3)
    face_offsets: np.ndarray      # (n_faces + 1,)
    face_conn: np.ndarray         # 평탄, 로컬 점 id
    face_centroids: np.ndarray    # (n_faces, 3) Fluent 가 준 값 (검증용) 또는 None
    cell_data: dict = field(default_factory=dict)

    @property
    def n_faces(self):
        return len(self.face_offsets) - 1

    @property
    def n_points(self):
        return len(self.points)


# =============================================================================
# 체적 격자 조립
# =============================================================================
def build_zone_mesh(zone_id, zone_name, nodes, elements, is_2d=False, log=_noop):
    """PyFluent Mesh.nodes / Mesh.elements → ZoneMesh.
    nodes: x,y,z 속성 객체 반복자. elements: element_type(.value), node_indices, facets(각각 node_indices) 객체."""
    points = np.fromiter((c for n in nodes for c in (n.x, n.y, n.z)), dtype=np.float64).reshape(-1, 3)

    cell_types, cell_sizes, cell_conn = [], [], []
    face_sizes, face_conn, face_cell = [], [], []
    n_ghost = 0
    for el in elements:
        et = el.element_type.value if hasattr(el.element_type, "value") else int(el.element_type)
        if et == FL_GHOST:
            n_ghost += 1
            continue
        ci = len(cell_types)
        if et == FL_POLYHEDRON:
            uniq = {}
            for f in el.facets:
                ni = getattr(f, "node_indices", f)
                face_sizes.append(len(ni))
                face_conn.extend(ni)
                face_cell.append(ci)
                for p in ni:
                    uniq.setdefault(p, None)
            cell_types.append(VTK_POLYHEDRON)
            cell_sizes.append(len(uniq))
            cell_conn.extend(uniq)
        else:
            try:
                vtk_type, perm = FLUENT_TO_VTK[et]
            except KeyError:
                raise RuntimeError("지원하지 않는 Fluent 요소 타입 %s (존 %s)" % (et, zone_name))
            ni = el.node_indices
            if len(ni) != len(perm):
                raise RuntimeError("요소 노드 수 불일치: 타입 %s, %d개 (기대 %d)" % (et, len(ni), len(perm)))
            cell_types.append(vtk_type)
            cell_sizes.append(len(perm))
            cell_conn.extend(ni[p] for p in perm)
    if n_ghost:
        log("  고스트 셀 %d개 제거 (2D)" % n_ghost)

    def offsets(sizes):
        off = np.zeros(len(sizes) + 1, dtype=np.int64)
        if sizes:
            np.cumsum(sizes, out=off[1:])
        return off

    return ZoneMesh(zone_id, zone_name, points,
                    np.asarray(cell_types, dtype=np.uint8), offsets(cell_sizes), np.asarray(cell_conn, dtype=np.int64),
                    offsets(face_sizes), np.asarray(face_conn, dtype=np.int64), np.asarray(face_cell, dtype=np.int64),
                    is_2d)


def _facet_groups(face_offsets):
    sizes = np.diff(face_offsets)
    for k in np.unique(sizes):
        idx = np.flatnonzero(sizes == k)
        yield idx, face_offsets[idx][:, None] + np.arange(int(k))


def _face_geometry(P):
    """다각형 P (n, k, 3) 의 Fluent 식 기하: 노드 평균에서 부채꼴 삼각형으로 나눠 (면적 벡터, 면적 가중 중심, 노드 평균)."""
    cm = P.mean(axis=1)
    a = P - cm[:, None, :]
    b = np.roll(P, -1, axis=1) - cm[:, None, :]
    tri_area = 0.5 * np.cross(a, b)
    area = tri_area.sum(axis=1)
    w = np.linalg.norm(tri_area, axis=2)
    tri_centre = (cm[:, None, :] + P + np.roll(P, -1, axis=1)) / 3.0
    wsum = w.sum(axis=1)
    centroid = np.where(wsum[:, None] > 0.0,
                        (w[:, :, None] * tri_centre).sum(axis=1) / np.maximum(wsum, 1e-300)[:, None], cm)
    return area, centroid, cm


def _face_volume_contrib(P):
    area, centroid, _ = _face_geometry(P)
    return np.einsum("ij,ij->i", area, centroid) / 3.0, area, centroid


def orient_polyhedra(zm, centroids=None):
    """폴리헤드론 facet 을 셀 중심 기준 바깥 방향으로 다시 감는다. 뒤집은 facet 수 반환."""
    if zm.n_faces == 0:
        return 0
    if centroids is None:
        centroids = zm.point_mean_centroids()
    flipped = 0
    for idx, mat in _facet_groups(zm.face_offsets):
        _, normal, fc = _face_volume_contrib(zm.points[zm.face_conn[mat]])
        inward = np.einsum("ij,ij->i", normal, fc - centroids[zm.face_cell[idx]]) < 0.0
        if inward.any():
            sel = mat[inward]
            zm.face_conn[sel] = zm.face_conn[sel[:, ::-1]]
            flipped += int(inward.sum())
    return flipped


def polyhedron_volumes(zm):
    vol = np.zeros(zm.n_cells)
    for idx, mat in _facet_groups(zm.face_offsets):
        v, _, _ = _face_volume_contrib(zm.points[zm.face_conn[mat]])
        np.add.at(vol, zm.face_cell[idx], v)
    return vol


def linear_cell_volumes(points, conn, vtk_type):
    vol = np.zeros(len(conn))
    for face in VTK_FACES[vtk_type]:
        vol += _face_volume_contrib(points[conn[:, list(face)]])[0]
    return vol


def cell_volumes(zm):
    """부호 있는 부피(3D) 또는 xy 면적(2D)."""
    vol = polyhedron_volumes(zm)
    for vtk_type in VTK_FACES:
        idx, conn = zm.cell_nodes(vtk_type)
        if len(idx):
            vol[idx] = linear_cell_volumes(zm.points, conn, vtk_type)
    for vtk_type in (VTK_TRIANGLE, VTK_QUAD):
        idx, conn = zm.cell_nodes(vtk_type)
        if len(idx):
            area, _, _ = _face_geometry(zm.points[conn])
            vol[idx] = area[:, 2]
    return vol


def orient_linear_cells(zm, log=_noop):
    """타입별 다수결로 뒤집힌(음수 부피) 선형 셀을 바로잡는다. {vtk_type: 뒤집은 수}."""
    flipped = {}
    for vtk_type, flip_perm in VTK_FLIP.items():
        idx, conn = zm.cell_nodes(vtk_type)
        if len(idx) == 0:
            continue
        sv = linear_cell_volumes(zm.points, conn, vtk_type)
        n_neg = int((sv < 0).sum())
        if n_neg > len(idx) // 2:
            log("[WARN] VTK 타입 %d 셀 %d/%d 이 뒤집혀 있어 노드 순서를 반전합니다" % (vtk_type, n_neg, len(idx)))
            conn = conn[:, list(flip_perm)]
            k = conn.shape[1]
            zm.cell_conn[zm.cell_offsets[idx][:, None] + np.arange(k)] = conn
            flipped[vtk_type] = n_neg
        elif n_neg:
            log("[WARN] VTK 타입 %d 셀 %d/%d 의 부피가 음수입니다 (그대로 둠)" % (vtk_type, n_neg, len(idx)))
    return flipped


def verify_zone(zm, sv_volume=None, sv_centroid=None):
    """재계산 부피·중심을 Fluent SV_VOLUME/SV_CENTROID 와 비교. 지표 dict 반환 (ok 포함)."""
    out = {"ok": True, "n_neg": 0, "total_rel": None, "max_cell_rel": None, "centroid_dev": None,
           "volume": None, "sv_volume": None}
    vol = cell_volumes(zm)
    out["volume"] = float(vol.sum())
    out["n_neg"] = int((vol < 0).sum())
    if out["n_neg"]:
        out["ok"] = False
    if sv_volume is not None and not zm.is_2d and len(sv_volume) == zm.n_cells:
        sv_volume = np.asarray(sv_volume, dtype=np.float64)
        rel = np.abs(vol - sv_volume) / np.maximum(np.abs(sv_volume), 1e-300)
        out["sv_volume"] = float(sv_volume.sum())
        out["total_rel"] = float(abs(vol.sum() - sv_volume.sum()) / max(abs(sv_volume.sum()), 1e-300))
        out["max_cell_rel"] = float(rel.max()) if len(rel) else 0.0
        if int((rel > 0.1).sum()) or out["total_rel"] > 1e-6:
            out["ok"] = False
    if sv_centroid is not None and len(sv_centroid) == zm.n_cells:
        pm = zm.point_mean_centroids()
        dist = np.linalg.norm(pm - np.asarray(sv_centroid, dtype=np.float64), axis=1)
        if sv_volume is not None and not zm.is_2d and len(sv_volume) == zm.n_cells:
            size = np.cbrt(np.abs(np.asarray(sv_volume)))
        else:
            size = np.sqrt(np.abs(vol))
        rel = dist / np.maximum(size, 1e-300)
        out["centroid_dev"] = float(rel.max()) if len(rel) else 0.0
        if out["centroid_dev"] > 1.0:
            out["ok"] = False
    return out


def _vtk_cell_array(offsets, conn):
    import vtk
    from vtkmodules.util.numpy_support import numpy_to_vtkIdTypeArray
    ca = vtk.vtkCellArray()
    ca.SetData(numpy_to_vtkIdTypeArray(np.ascontiguousarray(offsets, dtype=np.int64), deep=True),
               numpy_to_vtkIdTypeArray(np.ascontiguousarray(conn, dtype=np.int64), deep=True))
    return ca


def _add_arrays(data_attr, arrays):
    from vtkmodules.util.numpy_support import numpy_to_vtk
    for name, arr in arrays.items():
        va = numpy_to_vtk(np.ascontiguousarray(arr), deep=True)
        va.SetName(name)
        data_attr.AddArray(va)


def to_vtk_grid(zm):
    """ZoneMesh → vtkUnstructuredGrid (폴리헤드론은 VTK ≥ 9.4 의 SetPolyhedralCells)."""
    import vtk
    from vtkmodules.util.numpy_support import numpy_to_vtk
    grid = vtk.vtkUnstructuredGrid()
    pts = vtk.vtkPoints()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(zm.points, dtype=np.float64), deep=True))
    grid.SetPoints(pts)
    types = numpy_to_vtk(zm.cell_types, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
    cells = _vtk_cell_array(zm.cell_offsets, zm.cell_conn)
    if zm.n_faces:
        if not hasattr(grid, "SetPolyhedralCells"):
            raise RuntimeError("폴리헤드론 격자에는 VTK 9.4 이상이 필요합니다 (SetPolyhedralCells 없음)")
        faces_per_cell = np.bincount(zm.face_cell, minlength=zm.n_cells)
        loc_offsets = np.zeros(zm.n_cells + 1, dtype=np.int64)
        np.cumsum(faces_per_cell, out=loc_offsets[1:])
        order = np.argsort(zm.face_cell, kind="stable")
        grid.SetPolyhedralCells(types, cells, _vtk_cell_array(loc_offsets, order),
                                _vtk_cell_array(zm.face_offsets, zm.face_conn))
    else:
        grid.SetCells(types, cells)
    _add_arrays(grid.GetCellData(), zm.cell_data)
    return grid


def merge_grids(grids):
    """여러 존 격자를 하나로 (절점 병합 없음 — PyVista 엔진 combine() 과 같은 동작, 결정 004 축 4)."""
    import vtk
    if len(grids) == 1:
        return grids[0]
    app = vtk.vtkAppendFilter()
    app.MergePointsOff()
    for g in grids:
        app.AddInputData(g)
    app.Update()
    return app.GetOutput()


def _write_xml(writer, data, path, binary):
    writer.SetFileName(str(path))
    writer.SetInputData(data)
    if binary:
        writer.SetDataModeToAppended()
        writer.EncodeAppendedDataOff()
        writer.SetCompressorTypeToZLib()
    else:
        writer.SetDataModeToAscii()
    if not writer.Write():
        raise RuntimeError("파일 쓰기 실패: %s" % path)


def write_grid(grid, path, binary=True):
    import vtk
    _write_xml(vtk.vtkXMLUnstructuredGridWriter(), grid, path, binary)


# =============================================================================
# 경계 면 존 → PolyData
# =============================================================================
def parse_flat_faces(flat):
    """VTK 레거시 식 평탄 배열 [n, i0..i(n-1), n, ...] → (offsets, connectivity)."""
    flat = np.asarray(flat, dtype=np.int64).ravel()
    if flat.size == 0:
        return np.zeros(1, dtype=np.int64), flat
    k = int(flat[0])
    if flat.size % (k + 1) == 0 and (flat.reshape(-1, k + 1)[:, 0] == k).all():
        conn = flat.reshape(-1, k + 1)[:, 1:].ravel()
        return np.arange(0, conn.size + 1, k, dtype=np.int64), conn
    sizes = []
    pos = 0
    while pos < flat.size:
        n = int(flat[pos])
        sizes.append(n)
        pos += n + 1
    offsets = np.zeros(len(sizes) + 1, dtype=np.int64)
    np.cumsum(sizes, out=offsets[1:])
    mask = np.ones(flat.size, dtype=bool)
    mask[offsets[:-1] + np.arange(len(sizes))] = False
    return offsets, flat[mask]


def build_surface_mesh(zone_id, name, vertices, connectivity, face_centroids=None):
    """SurfaceFieldDataRequest(flatten_connectivity=True) 결과 → SurfaceMesh.
    connectivity 가 (m, k) 2차원이면 구조형 결과로 보고 그대로 쓴다."""
    points = np.ascontiguousarray(np.asarray(vertices, dtype=np.float64).reshape(-1, 3))
    conn_in = np.asarray(connectivity)
    if conn_in.ndim == 2:
        k = conn_in.shape[1]
        conn = conn_in.astype(np.int64).ravel()
        offsets = np.arange(0, conn.size + 1, k, dtype=np.int64)
    else:
        offsets, conn = parse_flat_faces(conn_in)
    fc = None
    if face_centroids is not None and len(face_centroids):
        fc = np.asarray(face_centroids, dtype=np.float64).reshape(-1, 3)
    # Fluent 저장 순서의 오른손 법선은 영역 **안쪽**을 향한다 (box 3개 경계 6,250면 전부 안쪽 — 2026-10-03 실측).
    # ParaView 관례(경계 법선 바깥)에 맞춰 다각형(3점 이상)의 노드 순서를 전부 뒤집는다. 선분(2점)은 그대로.
    sizes = np.diff(offsets)
    for k in np.unique(sizes):
        if k < 3:
            continue
        idx = np.flatnonzero(sizes == k)
        mat = offsets[idx][:, None] + np.arange(int(k))
        conn[mat] = conn[mat[:, ::-1]]
    return SurfaceMesh(zone_id, name, points, offsets, conn, fc)


def face_vertex_means(sm):
    sizes = np.diff(sm.face_offsets)
    face_of_entry = np.repeat(np.arange(sm.n_faces), sizes)
    acc = np.zeros((sm.n_faces, 3))
    np.add.at(acc, face_of_entry, sm.points[sm.face_conn])
    return acc / np.maximum(sizes, 1)[:, None]


def verify_surface(sm, sv_centroid=None):
    """꼭짓점 평균 vs Fluent 면 중심(FacesCentroid, 그리고 있으면 면 존 SVAR SV_CENTROID).
    반환 (면 크기 단위 최대 편차, SV_CENTROID 와 FacesCentroid 의 최대 절대차[m] 또는 None)."""
    if sm.n_faces == 0:
        return 0.0, None
    mean = face_vertex_means(sm)
    sizes = np.diff(sm.face_offsets)
    face_of_entry = np.repeat(np.arange(sm.n_faces), sizes)
    d = np.linalg.norm(sm.points[sm.face_conn] - mean[face_of_entry], axis=1)
    size = np.zeros(sm.n_faces)
    np.maximum.at(size, face_of_entry, d)
    dev = 0.0
    if sm.face_centroids is not None and len(sm.face_centroids) == sm.n_faces:
        dev = float((np.linalg.norm(mean - sm.face_centroids, axis=1) / np.maximum(size, 1e-300)).max())
    diff = None
    if sv_centroid is not None and sm.face_centroids is not None:
        svc = np.asarray(sv_centroid, dtype=np.float64).reshape(-1, 3)
        if svc.shape == sm.face_centroids.shape:
            diff = float(np.abs(svc - sm.face_centroids).max())
    return dev, diff


def to_vtk_polydata(sm):
    """SurfaceMesh → vtkPolyData (다각형. 2점 면은 선분으로, 선분이 앞에 오도록 셀 데이터도 재배열)."""
    import vtk
    from vtkmodules.util.numpy_support import numpy_to_vtk
    pd = vtk.vtkPolyData()
    pts = vtk.vtkPoints()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(sm.points, dtype=np.float64), deep=True))
    pd.SetPoints(pts)
    sizes = np.diff(sm.face_offsets)
    is_line = sizes == 2
    order = np.arange(sm.n_faces)
    if is_line.any() and (~is_line).any():
        order = np.concatenate([np.flatnonzero(is_line), np.flatnonzero(~is_line)])

    def subset(idx):
        off = np.zeros(len(idx) + 1, dtype=np.int64)
        np.cumsum(sizes[idx], out=off[1:])
        if len(idx) == 0:
            return off, np.empty(0, dtype=np.int64)
        conn = np.concatenate([sm.face_conn[sm.face_offsets[i]:sm.face_offsets[i + 1]] for i in idx])
        return off, conn

    if is_line.any():
        pd.SetLines(_vtk_cell_array(*subset(np.flatnonzero(is_line))))
    if (~is_line).any():
        if is_line.any():
            pd.SetPolys(_vtk_cell_array(*subset(np.flatnonzero(~is_line))))
        else:
            pd.SetPolys(_vtk_cell_array(sm.face_offsets, sm.face_conn))
    _add_arrays(pd.GetCellData(), {k: np.asarray(v)[order] for k, v in sm.cell_data.items()})
    return pd


def merge_polydata(polys, names=None):
    """경계 PolyData 여러 장을 한 장으로 (절점 병합 없음). names 를 주면 field data 'boundary_names' 로 넣는다."""
    import vtk
    if len(polys) == 1:
        out = polys[0]
    else:
        app = vtk.vtkAppendPolyData()
        for p in polys:
            app.AddInputData(p)
        app.Update()
        out = app.GetOutput()
    if names:
        sa = vtk.vtkStringArray()
        sa.SetName("boundary_names")
        for n in names:
            sa.InsertNextValue(str(n))
        out.GetFieldData().AddArray(sa)
    return out


def write_polydata(pd, path, binary=True):
    import vtk
    _write_xml(vtk.vtkXMLPolyDataWriter(), pd, path, binary)


def rename_arrays(dataset, renames):
    """vtk 데이터셋의 cell data 배열 이름 변경 {old: new}."""
    cd = dataset.GetCellData()
    for old, new in renames.items():
        arr = cd.GetArray(old)
        if arr is not None:
            arr.SetName(new)
