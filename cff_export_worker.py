"""
CFF → VTK 변환 워커 (일반 Python, PyVista 엔진)
Author: 퍼팩트리

GUI(pv_export_gui.py)가 QProcess로 호출하는 백엔드 워커입니다. 직접 실행도 가능합니다.
ParaView(pvpython) 전용 워커는 pv_export_worker.py 입니다.

기능 (결정 001·002, docs/decisions/):
  - 체적 UnstructuredGrid → Results.vtu (Cell Data, 선택 변수만 읽기 단계에서 로드)
  - --format vtp → 외곽 표면 1장 Results.vtp (경계 구분 없음)
  - --surface (vtu 와 함께) → <stem>_surface.vtp,  --slice nx,ny,nz[,ox,oy,oz] → <stem>_slice.vtp
  - --rename → Fluent 표시명으로 저장 (SV_P→pressure …, 매핑표 cff_common.py)
  - 데이터 파일 이름 해석: <base>.dat.h5 가 없고 <base>-<n>.dat.h5 (Workbench 반복 횟수 접미사) 만 있으면
    케이스 폴더 안 임시 하드링크 폴더로 이름을 맞춰 읽는다. dat 가 전혀 없으면 오류.

stdout 프로토콜 (pv_export_worker.py 와 동일):
  [PROGRESS] n · [SUCCESS] · [ERROR] … · ###JSON_START### … ###JSON_END###, 종료코드 0/1

실행 예시:
    python cff_export_worker.py --case box.cas.h5 --list-json
    python cff_export_worker.py --case box.cas.h5 --output Design_001/Results.vtu --vars SV_P,SV_T,SV_BF_V --rename
    python cff_export_worker.py --case box.cas.h5 --output Design_001/Results.vtp --all
"""
import argparse
import json
import sys
import time
import warnings
from pathlib import Path

# 한글 로그·경로 깨짐 방지 (GUI는 PYTHONIOENCODING=utf-8 도 함께 설정한다)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# pyvista 의 deprecation/future 경고가 GUI 콘솔(MergedChannels)에 섞이지 않도록
warnings.filterwarnings("ignore")

from cff_common import PreparedCase, plan_renames, remove_stale_link_dirs  # noqa: E402  (같은 폴더)

SURFACE_SUFFIX = "surface"            # --surface: <stem>_surface.vtp
SLICE_SUFFIX = "slice"                # --slice:   <stem>_slice.vtp


def say(msg):
    print(msg, flush=True)


def progress(n):
    say("[PROGRESS] %d" % n)


def fail(msg):
    say("[ERROR] %s" % msg)
    sys.exit(1)


def emit_json(obj):
    say("###JSON_START###")
    say(json.dumps(obj))
    say("###JSON_END###")


def remove_stale(path):
    """이전 실행의 같은 이름 파일 제거 (마지막 exists() 판정이 이번 실행만 반영하도록)."""
    if path.exists():
        try:
            path.unlink()
        except OSError as e:
            say("[WARN] 기존 출력 파일 삭제 실패: %s" % str(e)[:60])


def peak_memory_mb():
    """현재 프로세스의 최대 작업 집합(MB). Windows 전용, 실패하면 None."""
    try:
        import ctypes
        import ctypes.wintypes as w

        class PMC(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), w.DWORD]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return pmc.PeakWorkingSetSize / 1024**2
    except Exception:
        pass
    return None


def verify_saved(path, expect_type=None):
    """저장 후 자기 검증: 다시 열어 타입·셀 수·배열을 출력. 실패하면 False."""
    import pyvista as pv
    try:
        ds = pv.read(str(path))
    except Exception as e:
        say("  [WARN] 자기 검증 실패(다시 열기): %s" % str(e)[:80])
        return False
    tname = type(ds).__name__
    arrays = ", ".join("%s(%d)" % (k, ds.cell_data[k].shape[1] if ds.cell_data[k].ndim > 1 else 1)
                       for k in ds.cell_data.keys())
    say("  [VERIFY] %s: %s, cells=%d, points=%d, cell_data=[%s], point_data=%d" % (
        path.name, tname, ds.n_cells, ds.n_points, arrays, len(ds.point_data.keys())))
    if expect_type and tname != expect_type:
        say("  [WARN] 타입 불일치: 기대 %s, 실제 %s" % (expect_type, tname))
        return False
    return True


def split_selection(requested, available, label):
    """요청 변수 중 있는 것/없는 것 분리. 없는 것은 [WARN] 1줄로 알리고 건너뛴다 (결정 001)."""
    selected = [v for v in requested if v in available]
    invalid = [v for v in requested if v not in available]
    say("[4] 선택 %s: %s" % (label, selected))
    if invalid:
        say("[WARN] 없는 변수(건너뜀): %s" % invalid)
    return selected


def apply_display_names(ds, enabled):
    """결정 002 R1: cell_data 이름을 Fluent 표시명으로 바꾼다 (저장 직전 한 번).
    매핑 없는 이름은 원본 유지 + [WARN]. 반환: 바뀐 {old: new}.
    """
    if not enabled:
        return {}
    renames, unmapped = plan_renames(list(ds.cell_data.keys()))
    for old, new in renames.items():
        ds.rename_array(old, new, preference="cell")
    if renames:
        say("  [RENAME] %s" % ", ".join("%s→%s" % kv for kv in renames.items()))
    if unmapped:
        say("[WARN] 표시명 없음(원본 유지): %s" % unmapped)
    return renames


# =============================================================================
# 읽기
# =============================================================================
def pv_open(case_path, keep=None, require_data=True):
    """FLUENTCFFReader 로 읽는다. keep 이 주어지면 raw vtkFLUENTCFFReader 의
    SetCellArrayStatus 로 읽기 단계에서 나머지 배열을 끈다 (실측: 값은 전체 읽기와 동일).
    데이터 파일 이름이 다르면(FFF.3-2-11200.dat.h5) 임시 하드링크로 맞춰 읽는다.
    반환: (UnstructuredGrid, 전체 cell array 이름 목록, PreparedCase)
    """
    import pyvista as pv
    import os
    # 이전 실행이 남긴 임시 링크 폴더 정리. 10분 넘은 것만 (CLI 동시 실행 보호. GUI 는 워커 종료 직후 전부 정리)
    remove_stale_link_dirs(os.path.dirname(str(case_path)) or ".", log=say, min_age_sec=600)
    pc = PreparedCase(case_path, log=say)
    say("  데이터 파일: %s" % pc.describe())
    if pc.data_file is None and require_data:
        pc.cleanup()
        fail("데이터 파일(.dat.h5)을 찾지 못했습니다: %s.dat.h5 또는 %s-<반복횟수>.dat.h5 가 같은 폴더에 있어야 합니다"
             % (Path(case_path).name[:-len(".cas.h5")], Path(case_path).name[:-len(".cas.h5")]))
    reader = pv.get_reader(str(pc.case_to_open))
    raw = getattr(reader, "reader", None)
    all_names = []
    read_time_filter = False
    if raw is not None and hasattr(raw, "GetNumberOfCellArrays"):
        try:
            raw.UpdateInformation()
            all_names = [raw.GetCellArrayName(i) for i in range(raw.GetNumberOfCellArrays())]
            if keep is not None:
                for nm in all_names:
                    raw.SetCellArrayStatus(nm, 1 if nm in keep else 0)
                read_time_filter = True
        except Exception as e:
            say("  [WARN] 읽기 단계 변수 필터 실패, 읽은 뒤 제거합니다: %s" % str(e)[:60])
            read_time_filter = False
    mb = reader.read()
    if isinstance(mb, pv.MultiBlock):
        n_blocks = mb.n_blocks
        grid = mb.combine()          # 결정 001: combine() 기본값. 다중 존은 결정 D8 보류
        say("  [OK] 블록 %d개 → combine" % n_blocks)
    else:
        grid = mb
    # 리더가 HDF5 핸들을 잡고 있어 임시 링크 폴더를 못 지운다 → SetFileName("") 이 핸들을 놓는다 (실측)
    try:
        if raw is not None:
            raw.SetFileName("")
    except Exception:
        pass
    del reader, raw, mb
    left = pc.cleanup(retries=3, delay=0.2)
    if left:
        # 실측: 프로세스의 첫 vtkFLUENTCFFReader 는 프로세스가 끝날 때까지 HDF5 핸들을 놓지 않는다.
        # → GUI 가 워커 종료 직후 remove_stale_link_dirs 로 지운다. CLI 는 다음 실행이 10분 지난 폴더를 지운다.
        say("  임시 링크 폴더(%s)는 프로세스 종료 후 정리됩니다 (하드링크라 용량 차지 없음)" % os.path.basename(left))
        pc.cleanup_at_exit()
    if not all_names:
        all_names = list(grid.cell_data.keys())
    # 폴백/보강: 읽기 단계 필터가 안 먹었거나 못 썼으면 저장 전 제거
    if keep is not None:
        extra = [k for k in grid.cell_data.keys() if k not in keep]
        if extra:
            if read_time_filter:
                say("  [WARN] 읽기 단계 필터 뒤에도 남은 배열 제거: %s" % extra)
            for k in extra:
                grid.cell_data.pop(k, None)
    return grid, all_names, pc


def pv_list_json(case_path):
    pc = PreparedCase(case_path, log=say)
    if pc.data_file is None:
        pc.cleanup()
        base = Path(case_path).name[:-len(".cas.h5")]
        emit_json({"error": "데이터 파일(.dat.h5) 없음: %s.dat.h5 또는 %s-<반복횟수>.dat.h5 가 같은 폴더에 있어야 합니다"
                   % (base, base), "engine": "pyvista"})
        sys.exit(1)
    pc.cleanup()
    grid, names, pc = pv_open(case_path)
    vector_fields = [k for k in grid.cell_data.keys()
                     if getattr(grid.cell_data[k], "ndim", 1) > 1 and grid.cell_data[k].shape[1] == 3]
    emit_json({
        "engine": "pyvista",
        "cell_arrays": names,
        "point_arrays": list(grid.point_data.keys()),
        "vector_fields": vector_fields,
        "case_file": str(case_path),
        "data_file": str(pc.data_file),
        "data_name_matches": bool(pc.name_matches),
        "case_size_mb": round(Path(case_path).stat().st_size / 1024**2, 2),
        "n_cells": int(grid.n_cells),
        "n_points": int(grid.n_points),
    })


# =============================================================================
# 변환
# =============================================================================
def pv_convert(args, case_path, out_path, out_format):
    import pyvista as pv
    start = time.time()
    binary = not args.ascii

    # 변수 결정은 읽기 전에: 읽기 단계 필터용 이름 목록 필요
    say("[2] CFF 파일 로딩 중 (pyvista %s)..." % pv.__version__)
    if args.all:
        keep = None
        requested = []
    else:
        requested = [v.strip() for v in (args.vars or "").split(",") if v.strip()]
        if not requested:
            fail("--vars 또는 --all이 필요합니다.")
        keep = set(requested)
    grid, all_names, _ = pv_open(case_path, keep=keep)
    say("  [OK] 로딩 완료 (%.2f초): cells=%d, points=%d" % (time.time() - start, grid.n_cells, grid.n_points))
    progress(40)

    if args.all:
        selected = list(grid.cell_data.keys())
        say("[4] 모든 Cell Data %d개 선택" % len(selected))
    else:
        selected = split_selection(requested, all_names, "변수")
        if not selected:
            fail("유효한 변수가 없습니다. 사용 가능: %s" % all_names)
    if not grid.cell_data.keys():
        say("[WARN] Cell Data가 없습니다.")
    if args.point_data:
        say("[WARN] --point-data는 아직 지원하지 않습니다 (결정 001 D7). Cell Data만 저장합니다.")
    # 결정 002 R1: 표시명 변경은 저장 전 grid 에서 한 번 → vtu / 외곽 표면 / 단면에 모두 적용
    apply_display_names(grid, args.rename)
    progress(60)

    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_path.stem
    written = []

    if out_format == "vtu":
        remove_stale(out_path)
        say("[5] VTU 저장 중: %s" % out_path.name)
        t = time.time()
        grid.save(str(out_path), binary=binary)
        say("  [OK] 저장 (%.2f초)" % (time.time() - t))
        verify_saved(out_path, "UnstructuredGrid")
        written.append(out_path)
    progress(75)

    if out_format == "vtp" or args.surface:
        # VTP 포맷이면 <stem>.vtp (Results.vtp). VTU 와 함께 --surface 를 준 CLI 경우만 <stem>_surface.vtp
        surf_path = out_path if out_format == "vtp" else out_dir / ("%s_%s.vtp" % (stem, SURFACE_SUFFIX))
        remove_stale(surf_path)
        say("[5] 외곽 표면 추출 → %s (경계 구분 없음)" % surf_path.name)
        surf = grid.extract_surface(pass_pointid=False, pass_cellid=False, algorithm="dataset_surface")
        surf.save(str(surf_path), binary=binary)
        verify_saved(surf_path, "PolyData")
        written.append(surf_path)
    progress(85)

    if args.slice:
        try:
            vals = [float(x) for x in args.slice.split(",")]
            if len(vals) == 3:
                normal, origin = vals, None
            elif len(vals) == 6:
                normal, origin = vals[:3], vals[3:]
            else:
                raise ValueError
        except ValueError:
            fail("--slice 형식: nx,ny,nz 또는 nx,ny,nz,ox,oy,oz")
        slice_path = out_dir / ("%s_%s.vtp" % (stem, SLICE_SUFFIX))
        remove_stale(slice_path)
        say("[5] 단면 추출 normal=%s origin=%s → %s" % (normal, origin or "중심", slice_path.name))
        sl = grid.slice(normal=normal, origin=origin)
        sl.save(str(slice_path), binary=binary)
        verify_saved(slice_path, "PolyData")
        written.append(slice_path)
    progress(95)

    return written, selected, start


# =============================================================================
# main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="CFF -> VTU/VTP 변환 워커 (PyVista)")
    parser.add_argument("--case", "-c", required=True, help="CFF case 파일 (.cas.h5). 같은 폴더의 <base>.dat.h5 또는 <base>-<n>.dat.h5 를 함께 읽는다")
    parser.add_argument("--output", "-o", default=None, help="출력 경로 (.vtu / .vtp)")
    parser.add_argument("--format", "-f", choices=["auto", "vtu", "vtp"], default="auto", help="출력 포맷 (auto=확장자)")
    parser.add_argument("--vars", "-v", default=None, help="저장할 변수 (쉼표 구분, Fluent 원본 이름 SV_*)")
    parser.add_argument("--all", "-a", action="store_true", help="모든 변수 저장")
    parser.add_argument("--list-json", action="store_true", help="변수 목록을 JSON 으로 출력 (GUI 용)")
    parser.add_argument("--ascii", action="store_true", help="ASCII 저장")
    parser.add_argument("--rename", action="store_true",
                        help="저장 시 Fluent 표시명으로 이름 변경 (SV_P→pressure …, cff_common.py 표. 없는 이름은 원본 유지)")
    parser.add_argument("--surface", action="store_true", help=".vtu 와 함께 외곽 표면 <stem>_surface.vtp 저장")
    parser.add_argument("--slice", default=None, help="단면 nx,ny,nz[,ox,oy,oz] → <stem>_slice.vtp")
    # 예약
    parser.add_argument("--point-data", action="store_true", help="(예약) Point Data 추가. 아직 미지원")
    args = parser.parse_args()

    case_path = Path(args.case)
    if not case_path.exists():
        fail("case 파일 없음: %s" % case_path)

    # ---------------- --list-json ----------------
    if args.list_json:
        try:
            pv_list_json(case_path)
        except SystemExit:
            raise
        except Exception as e:
            emit_json({"error": "%s: %s" % (type(e).__name__, str(e)[:200]), "engine": "pyvista"})
            sys.exit(1)
        sys.exit(0)

    # ---------------- 변환 ----------------
    if args.output is None:
        fail("--output이 필요합니다.")
    out_path = Path(args.output)
    if args.format == "auto":
        out_format = "vtp" if out_path.suffix.lower() == ".vtp" else "vtu"
    else:
        out_format = args.format
    if out_path.suffix.lower() not in (".vtu", ".vtp"):
        out_path = out_path.with_suffix("." + out_format)

    say("[1] 입력 파일 검증 (엔진: pyvista, 포맷: %s)" % out_format.upper())
    say("  [OK] %s (%.2f MB)" % (case_path.name, case_path.stat().st_size / 1024**2))
    progress(10)

    try:
        written, selected, start = pv_convert(args, case_path, out_path, out_format)
    except SystemExit:
        raise
    except Exception as e:
        fail("%s: %s" % (type(e).__name__, str(e)[:300]))

    missing = [p for p in written if not p.exists()]
    if not written or missing:
        fail("파일 생성 실패: %s" % (missing or out_path))

    total_mb = sum(p.stat().st_size for p in written) / 1024**2
    say("[완료] 변환 성공")
    say("  엔진: pyvista")
    say("  파일: %s" % ", ".join(p.name for p in written))
    say("  크기: %.2f MB (합계 %d개)" % (total_mb, len(written)))
    say("  포맷: %s" % out_format.upper())
    say("  변수: %d개 (Cell Data)" % len(selected))
    say("  전체 시간: %.2f초" % (time.time() - start))
    mem = peak_memory_mb()
    if mem is not None:
        say("  최대 메모리: %.0f MB" % mem)
    say("  위치: %s" % written[0].parent.resolve())
    progress(100)
    say("[SUCCESS]")


if __name__ == "__main__":
    main()
