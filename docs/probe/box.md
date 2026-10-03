# probe: samples/box (.cas.h5 1.7 MB + .dat.h5 1.9 MB)

- 날짜: 2026-10-03 · pyvista 0.47.3 / vtk 9.6.1 / ansys-fluent-core 0.42.1 / h5py 3.16.0(스크래치 설치)
- 기준(pvpython CFF reader): cell arrays 12개 `SV_BF_V, SV_D, SV_DENSITY, SV_H, SV_K, SV_MU_LAM, SV_MU_T, SV_P, SV_T, SV_U, SV_V, SV_W`, point arrays 없음

## PyVista (`pv.get_reader` → `FLUENTCFFReader`)

| 항목 | 결과 |
|---|---|
| 리더 wrapper 속성 | `path, read, reader, extensions, show_progress, hide_progress` — 배열 enable/disable 없음. raw `reader.reader`(vtkFLUENTCFFReader)에 `EnableAllCellArrays / SetCellArrayStatus / GetCellArrayName / GetNumberOfCellArrays` 있음 |
| `read()` | MultiBlock, 블록 1개(이름 None), 중첩 없음, 경계 블록 없음 |
| 블록 | UnstructuredGrid · 31,250 cells · 34,476 points |
| cell_data | 12개 전부(.dat.h5 자동 로드). `SV_BF_V` (N,3), 나머지 (N,) |
| point_data | 없음 |
| `combine()` / `combine(merge_points=True)` | 둘 다 31,250 / 34,476 (블록 1개라 차이 없음) |
| `extract_surface(pass_pointid=False, pass_cellid=False)` | 6,250 cells (= inlet 625 + outlet 625 + wall 5,000), cell arrays 12개 유지. 0.47.3에서 `PyVistaFutureWarning`(`algorithm` 기본값 변경 예정) |
| zone id 류 정수 배열 | 없음 (정수형 배열 자체가 없음) |

## PyFluent 오프라인 (`ansys.fluent.core.file_session.FileSession`)

- h5py 없으면 `ModuleNotFoundError: Missing dependencies, use 'pip install ansys-fluent-core[reader]'`
- `FileSession(); read_case(); read_data()` 성공. 라이선스·Fluent 프로세스 불필요

| surface | id | faces(quad) | vertices | zone_type 보고값 |
|---|---|---|---|---|
| interior-fluid | 1 | 90,625 | 34,468 | wall (오표기) |
| inlet | 5 | 625 | 676 | wall (오표기) |
| outlet | 6 | 625 | 676 | wall (오표기) |
| wall | 7 | 5,000 | 5,100 | wall |

- scalar fields 24개(면 변수): `SV_ARTIFICIAL_WALL_FLAG, SV_D, SV_DENSITY, SV_DT_BC_SOURCE, SV_FLUX, SV_H, SV_HEAT_FLUX, SV_HEAT_FLUX_SENSIBLE, SV_K, SV_MACH, SV_P, SV_RAD_HEAT_FLUX, SV_RAD_HEAT_FLUX_EXTERIOR, SV_T, SV_U, SV_V, SV_W, SV_WALL_DIFFUSIVE_BC_MFLUX, SV_WALL_SHEAR, SV_WALL_T_INNER, SV_WALL_V, SV_WALL_VV, SV_WALL_YPLUS, SV_WALL_YPLUS_UTAU`
- **없는 것**: `SV_BF_V, SV_MU_LAM, SV_MU_T` (요청하면 KeyError)
- vector fields: `velocity` = (SV_U, SV_V, SV_W) 하나뿐
- 값은 **면 중심값**. `node_value=True/False` 결과 동일(절점 평균 없음). interior-fluid의 SV_P는 셀 SV_P와 다른 값(면 변수)
- API(0.42.1): `fields.field_data.get_surface_data(data_types, surfaces, flatten_connectivity)` → `{id: SurfaceData(.vertices (N,3), .connectivity flat [4,a,b,c,d,…])}`; `get_scalar_field_data`, `get_vector_field_data`; 요청 객체식 `get_field_data(ScalarFieldDataRequest…)` 도 동작. 클래스는 `ansys.fluent.core.fields.field_data_interfaces` 에서 import
- `CaseFile.get_mesh()`: surface id/name/connectivity/vertices(평탄화)만. `DataFile.get_cell_variables()`는 이름 목록만, 셀 값 API 없음
- `ansys.fluent.visualization`: FileSession 받지만 같은 surface 데이터. pyvista dataset 꺼내는 API 없음

## HANDOFF 가정과 다른 점
| HANDOFF 항목 | 판정 |
|---|---|
| §4-1 경계별 블록 분리 | **다름** — PyVista 리더는 블록 1개. 경계 분리는 PyFluent 경로로 |
| §4-2 존 경계면 중복 | 이 샘플은 셀 존 1개라 판정 불가. 다중 존 샘플 필요 |
| §4-3 Cell vs Point | **맞음** — 전부 Cell Data, Point Data 없음 |
| §4-4 벡터 | 성분 `SV_U/V/W` + 벡터 `SV_BF_V` 공존. `velocity` 벡터는 직접 조합 필요 |
| §4-5 리더 옵션 | wrapper엔 없고 raw VTK 리더에 있음 |
| §2.2 `extract_surface` 경고 | 맞음 (0.47.3도 동일) |
