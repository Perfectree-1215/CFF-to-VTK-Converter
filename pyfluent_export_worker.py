"""
CFF → VTK 변환 워커 (PyFluent 라이브 Fluent 솔버 세션)
Author: 퍼팩트리

GUI(pv_export_gui.py 의 "PyFluent 변환기" 탭)가 QProcess 로 호출하는 백엔드 워커입니다. 직접 실행도 가능합니다.
PyVista 전용 워커는 cff_export_worker.py, ParaView(pvpython) 전용 워커는 pv_export_worker.py 입니다.

동작 (결정 004, docs/decisions/004-pyfluent-tab.md):
  - ansys-fluent-core 로 헤드리스 Fluent 솔버를 띄워 케이스(+데이터)를 읽는다 (Fluent 설치 + 라이선스 필요)
  - VTU: 셀 존마다 field_data.get_mesh() 로 격자를 받아 파이썬에서 vtkUnstructuredGrid 로 조립
         (hex/tet/pyramid/wedge/polyhedron, 노드 순서 보정, SV_VOLUME 대조 — pyfluent_mesh.py),
         변수는 solution_variable_data 의 SVAR(SV_*, Cell Data). 여러 존은 절점 병합 없이 합친다
  - VTP: 경계 면 존(interior 제외)을 한 장으로 합친 Results.vtp. 값은 면 존 SVAR(면 중심, Cell Data),
         cell data `boundary_id` + field data `boundary_names` 로 경계 구분
  - --vars 에 SV_U,SV_V,SV_W 가 모두 있으면 벡터 `velocity`(3) 를 추가한다
  - --rename → Fluent 표시명 (SV_P→pressure …, cff_common.FLUENT_DISPLAY_NAMES)
  - 데이터 파일: cff_common.resolve_data_file 로 고른 경로를 read_data 에 직접 지정 (Workbench 이름 OK). dat 없으면 오류
  - 중단: stdin 으로 "CANCEL" 한 줄을 받으면 Fluent 세션을 종료하고 [ERROR] 사용자 중단 + 종료코드 1
  - --jobs <json> (결정 005, v2.1): 케이스 목록 [{index, case, output, format}] 을 받아 **Fluent 를 한 번만 띄우고**
    케이스마다 read_case/read_data → 변환. 차원(2D/3D)이 바뀌거나 Fluent 호출 중 예외가 나면 세션을 닫고 다음 케이스에서 다시 띄운다.
    케이스 하나의 실패(dat 없음 등)는 그 케이스만 실패로 보고하고 계속한다.

stdout 프로토콜 (다른 워커와 동일 + [FLUENT_PID]):
  [PROGRESS] n · [SUCCESS] · [ERROR] … · [WARN] … · ###JSON_START### … ###JSON_END### · 종료코드 0/1
  [FLUENT_PID] fluent=<pid> cortex=<pid>   ← 기동할 때마다 1줄 (jobs 모드는 보통 배치당 1회). GUI 가 kill 폴백 때 쓴다
  jobs 모드 추가 줄: [FILE_START] i/n <case 경로> … [FILE_DONE] i/n ok | [FILE_DONE] i/n fail <사유 한 줄>
  jobs 모드 종료: 전부 성공 → [PROGRESS] 100 + [SUCCESS] + 0, 하나라도 실패 → [ERROR] k건 실패 (성공 m건) + 1, 중단 → [ERROR] 사용자 중단 + 1

실행 예시:
    python pyfluent_export_worker.py --case box.cas.h5 --list-json
    python pyfluent_export_worker.py --case box.cas.h5 --output Design_001/Results.vtu --vars SV_P,SV_T,SV_U,SV_V,SV_W --rename
    python pyfluent_export_worker.py --case box.cas.h5 --output Design_001/Results.vtp --vars SV_P,SV_WALL_SHEAR --rename
    python pyfluent_export_worker.py --jobs jobs.json --vars SV_P,SV_T --rename      # GUI 배치 (Fluent 1회 기동)
"""
import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import warnings
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

warnings.filterwarnings("ignore")
logging.getLogger("pyfluent").setLevel(logging.ERROR)

import numpy as np  # noqa: E402

from cff_common import case_base, is_hidden_svar, plan_renames, resolve_data_file  # noqa: E402
import pyfluent_mesh as pm  # noqa: E402

ENGINE = "pyfluent"
DOMAIN = "mixture"
VELOCITY_COMPONENTS = ("SV_U", "SV_V", "SV_W")
VELOCITY_NAME = "velocity"
BOUNDARY_ID = "boundary_id"
PROTECTED_NAMES = (VELOCITY_NAME, BOUNDARY_ID)
WORKDIR_PREFIX = "cff_pyfluent_"

_CANCEL = threading.Event()
_STATE = {"solver": None, "exited": False, "dimension": None}   # dimension: 살아 있는 세션의 차원 (재사용 판단)
_EXIT_LOCK = threading.Lock()
_EXIT_DONE = threading.Event()     # solver.exit() 가 실제로 끝났음 (다른 스레드가 종료 중이면 기다리는 용도)


class CaseFailed(Exception):
    """케이스 하나의 실패. 단일 모드에서는 [ERROR] + 종료코드 1, jobs 모드에서는 [FILE_DONE] fail 뒤 다음 케이스로."""


class Cancelled(Exception):
    """사용자 중단 (stdin CANCEL)."""


# =============================================================================
# 공통 출력
# =============================================================================
def say(msg):
    print(msg, flush=True)


def progress(n):
    say("[PROGRESS] %d" % n)


def fail(msg):
    """케이스 실패를 알린다. 호출한 쪽(main / run_jobs)이 [ERROR] 출력과 종료코드를 결정한다."""
    raise CaseFailed(msg)


def emit_json(obj):
    say("###JSON_START###")
    say(json.dumps(obj))
    say("###JSON_END###")


def remove_stale(path):
    if path.exists():
        try:
            path.unlink()
        except OSError as e:
            say("[WARN] 기존 출력 파일 삭제 실패: %s" % str(e)[:60])


def peak_memory_mb():
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


def remove_stale_workdirs(min_age_sec=600):
    """%TEMP% 에 남은 cff_pyfluent_* (kill 되었거나 Fluent 가 .trn 을 잡고 있어 못 지운 것) 중 오래된 것 정리."""
    root = tempfile.gettempdir()
    now = time.time()
    try:
        names = os.listdir(root)
    except OSError:
        return
    for fn in names:
        p = os.path.join(root, fn)
        if fn.startswith(WORKDIR_PREFIX) and os.path.isdir(p):
            try:
                if now - os.path.getmtime(p) > min_age_sec:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass


def remove_workdir(work_dir, wait_sec=20):
    """임시 작업 폴더 삭제. Fluent 가 끝난 뒤에도 .trn 이 잠시 잠겨 있을 수 있어 최대 wait_sec 재시도.
    그래도 남으면 GUI([WORKDIR] 줄로 경로를 안다)가 나중에 지우고, CLI 는 다음 실행의 remove_stale_workdirs(10분) 가 지운다."""
    t0 = time.time()
    while True:
        try:
            shutil.rmtree(work_dir)
            return True
        except OSError:
            if time.time() - t0 > wait_sec:
                say("  임시 폴더 삭제 보류 (파일 잠김, 나중에 자동 정리): %s" % work_dir)
                return False
            time.sleep(0.5)


def check_cancel():
    if _CANCEL.is_set():
        raise Cancelled()


# =============================================================================
# 중단 수신 (stdin "CANCEL")
# =============================================================================
def _cancel_listener():
    try:
        for line in sys.stdin:
            if line.strip().upper() == "CANCEL":
                _CANCEL.set()
                say("[WARN] 중단 요청을 받았습니다. Fluent 세션을 종료합니다...")
                close_session(timeout=20)
                break
    except Exception:
        pass


def start_cancel_listener():
    if sys.stdin is None:
        return
    threading.Thread(target=_cancel_listener, daemon=True).start()


# =============================================================================
# Fluent 세션
# =============================================================================
def detect_dimension(case_path):
    """CFF 의 meshes/*/dimension 속성으로 2/3 을 읽는다. 실패하면 3."""
    try:
        import h5py
        with h5py.File(str(case_path), "r") as h:
            for mesh in h["meshes"].values():
                dim = mesh.attrs.get("dimension")
                if dim is not None:
                    return int(np.atleast_1d(dim)[0])
    except Exception:
        pass
    return 3


def launch(args, dimension, work_dir):
    import ansys.fluent.core as pyfluent
    kw = dict(mode="solver", precision="double", processor_count=args.processors, dimension=dimension,
              ui_mode="no_gui_or_graphics", start_transcript=False, cleanup_on_exit=True,
              start_timeout=args.start_timeout, cwd=str(work_dir))
    if args.fluent_version:
        kw["product_version"] = args.fluent_version
    t = time.time()
    try:
        solver = pyfluent.launch_fluent(start_watchdog=False, **kw)
    except TypeError:
        solver = pyfluent.launch_fluent(**kw)
    _STATE["solver"] = solver
    _STATE["exited"] = False
    _STATE["dimension"] = dimension
    cp = solver.connection_properties
    _STATE["pids"] = [x for x in (getattr(cp, "cortex_pid", None), getattr(cp, "fluent_host_pid", None)) if isinstance(x, int)]
    say("[FLUENT_PID] fluent=%s cortex=%s" % (getattr(cp, "fluent_host_pid", "?"), getattr(cp, "cortex_pid", "?")))
    say("  [OK] Fluent 기동 (%.1f초): %s, %dD, 프로세스 %d개, pyfluent %s" % (
        time.time() - t, solver.get_fluent_version(), dimension, args.processors, pyfluent.__version__))
    return solver


def close_session(timeout=30):
    """세션 종료 (한 번만). 중단 스레드와 메인 finally 가 동시에 불러도 안전.

    다른 스레드(stdin CANCEL 리스너)가 이미 종료 중이면 그 종료가 **끝날 때까지 기다린다** — 안 그러면 메인 스레드가
    먼저 끝나 데몬 스레드의 solver.exit() 가 중간에 끊기고, Fluent 가 반쯤 닫힌 채 수십 초 남는다 (실측: 로더 shutdown 시험)."""
    with _EXIT_LOCK:
        solver = _STATE.get("solver")
        if solver is None:
            return
        already = bool(_STATE.get("exited"))
        if not already:
            _STATE["exited"] = True
            _EXIT_DONE.clear()
    if already:
        _EXIT_DONE.wait(timeout + 25)
        return
    try:
        # wait=20: 종료 요청 뒤 Fluent 프로세스가 실제로 사라질 때까지 최대 20초 기다린다
        # (워커 종료 = Fluent 종료 가 되도록. GUI 는 워커가 끝난 뒤 pid 를 한 번 더 확인한다)
        solver.exit(timeout=timeout, wait=20)
    except TypeError:
        solver.exit(timeout=timeout)
    except Exception as e:
        say("[WARN] Fluent 종료 요청 실패: %s" % str(e)[:80])
    finally:
        _ensure_pids_gone(_STATE.get("pids") or [])
        _EXIT_DONE.set()


def _pid_alive(pid):
    import subprocess
    try:
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)
        return str(pid) in r.stdout
    except Exception:
        return False


def _ensure_pids_gone(pids, wait_sec=15):
    """solver.exit() 가 돌아온 뒤에도 Fluent 프로세스(cortex·host)가 남아 있으면 잠시 기다렸다가 워커가 직접 강제 종료한다.
    (실측: exit 가 '완료'를 돌려줘도 프로세스가 수십 초 남는 경우가 있었다.) 워커가 끝나면 Fluent 도 없다는 계약을 지키기 위한 마지막 방어선."""
    import subprocess
    if not pids or os.name != "nt":
        return
    t0 = time.time()
    while time.time() - t0 < wait_sec:
        if not any(_pid_alive(x) for x in pids):
            return
        time.sleep(0.5)
    left = [x for x in pids if _pid_alive(x)]
    if left:
        say("[WARN] Fluent 프로세스가 종료 뒤에도 남아 강제 종료합니다: pid %s" % ", ".join(str(x) for x in left))
        for x in left:
            try:
                subprocess.run(["taskkill", "/PID", str(x), "/T", "/F"], capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
            except Exception:
                pass


def ascii_alias(case_path, data_file, alias_dir):
    """Fluent(2026 R1 실측) 는 한글 등 비ASCII 가 든 경로의 파일을 'File not found' 로 거부한다.
    경로가 전부 ASCII 면 그대로. 아니면 alias_dir(ASCII, %TEMP% 아래) 안에 케이스 폴더로 가는 **정션**(폴더 별칭)을 만들어
    ASCII 경로로 바꾼다. 파일명 자체가 비ASCII 면 alias_dir 로 복사한다. jobs 모드는 케이스마다 다른 alias_dir 을 쓴다
    (같은 이름을 다시 만들면 정션 생성이 실패해 조용히 복사로 빠지기 때문). 반환 (case_to_open, data_to_open, 설명)."""
    case_path, data_file, alias_dir = Path(case_path), Path(data_file), Path(alias_dir)
    if str(case_path).isascii() and str(data_file).isascii():
        return str(case_path), str(data_file), None
    if not str(alias_dir).isascii():
        say("[WARN] 경로에 비ASCII 문자가 있고 임시 폴더(%s)도 비ASCII 라 별칭을 만들 수 없습니다. Fluent 가 파일을 못 열 수 있습니다" % alias_dir)
        return str(case_path), str(data_file), None
    alias_dir.mkdir(parents=True, exist_ok=True)
    link = alias_dir / "case_dir"
    how = []
    c = d = None
    try:
        import _winapi
        _winapi.CreateJunction(str(case_path.parent), str(link))
        how.append("폴더 정션")
        c = link / case_path.name
        d = link / data_file.name if data_file.parent == case_path.parent else None
    except Exception as e:
        how.append("정션 실패(%s)" % str(e)[:40])
    if c is None or not case_path.name.isascii():
        c = alias_dir / ("case" + ".cas.h5")
        shutil.copy2(case_path, c)
        how.append("케이스 복사")
    if d is None or not data_file.name.isascii():
        d = alias_dir / ("case" + ".dat.h5")
        shutil.copy2(data_file, d)
        how.append("데이터 복사")
    return str(c), str(d), "경로에 비ASCII 문자 → Fluent 용 ASCII 별칭 사용 (%s)" % ", ".join(how)


def cleanup_alias(alias_dir):
    """케이스별 별칭 폴더 정리. 정션은 rmdir 로 **링크만** 지운다 (원본 케이스 폴더는 건드리지 않는다)."""
    p = Path(alias_dir)
    if not p.exists():
        return
    link = p / "case_dir"
    try:
        if link.exists() or link.is_symlink():
            os.rmdir(link)
    except OSError:
        pass
    for f in p.glob("case.*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        p.rmdir()
    except OSError:
        pass


def ensure_session(args, dimension, work_dir):
    """살아 있는 세션이 같은 차원이면 재사용, 아니면 (닫고) 새로 띄운다. 반환 (solver, 새로 띄웠는가)."""
    solver = _STATE.get("solver")
    if solver is not None and not _STATE.get("exited"):
        if _STATE.get("dimension") == dimension:
            return solver, False
        say("[WARN] 케이스 차원이 %dD 로 바뀌어 Fluent 를 다시 띄웁니다" % dimension)
        close_session(timeout=20)
    check_cancel()
    say("[2] Fluent 기동 중 (%dD)..." % dimension)
    solver = launch(args, dimension, work_dir)
    check_cancel()
    return solver, True


def load_case(args, case_path, data_file, work_dir, alias_dir=None):
    """세션을 확보한 뒤 케이스·데이터를 읽는다. 차원이 틀리면 한 번 바꿔 재시도. 반환 (solver, dimension)."""
    dimension = detect_dimension(case_path)
    case_to_open, data_to_open, note = ascii_alias(case_path, data_file, alias_dir or work_dir)
    if note:
        say("  " + note)
    for attempt in range(2):
        solver, _ = ensure_session(args, dimension, work_dir)
        try:
            t = time.time()
            solver.settings.file.read_case(file_name=case_to_open)
            say("  [OK] 케이스 읽기 (%.1f초)" % (time.time() - t))
            break
        except Exception as e:
            msg = str(e)
            if attempt == 0 and "dimension" in msg.lower():
                say("[WARN] 차원 불일치 → %dD 로 다시 띄웁니다" % (5 - dimension))
                close_session(timeout=20)
                dimension = 5 - dimension
                continue
            raise
    check_cancel()
    t = time.time()
    solver.settings.file.read_data(file_name=data_to_open)
    say("  [OK] 데이터 읽기 (%.1f초)" % (time.time() - t))
    return solver, dimension


def resolve_or_fail(case_path):
    data_file, matches = resolve_data_file(case_path)
    if data_file is not None:
        data_file = str(Path(data_file).resolve())
    base = case_base(case_path) or Path(case_path).name
    if data_file is None:
        fail("데이터 파일(.dat.h5)을 찾지 못했습니다: %s.dat.h5 또는 %s-<반복횟수>.dat.h5 가 같은 폴더에 있어야 합니다 "
             "(PyFluent 탭은 초기화된 값을 내보내지 않습니다)" % (base, base))
    say("  데이터 파일: %s%s" % (Path(data_file).name, "" if matches else " (이름이 달라 PyFluent 에 직접 지정)"))
    return data_file, matches


# =============================================================================
# 존·변수 조회
# =============================================================================
def zone_lists(solver):
    """(셀 존 [(id, name)], 경계 면 존 [(id, name)]) — 둘 다 존 id 오름차순."""
    fd = solver.fields.field_data
    zones = fd.get_zones_info()
    cell = [(int(z._id), z.name) for z in zones if str(z.zone_type).upper().endswith("CELL")]
    face = [(int(z._id), z.name) for z in zones if str(z.zone_type).upper().endswith("FACE")]
    try:
        allowed = set(fd.surfaces.allowed_values())
    except Exception:
        allowed = {nm for _, nm in face}
    boundary = [(zid, nm) for zid, nm in face if nm in allowed and not nm.lower().startswith("interior")]
    return sorted(cell), sorted(boundary)


def svar_names(solver, zone_names):
    try:
        info = solver.fields.solution_variable_info.get_variables_info(zone_names=list(zone_names), domain_name=DOMAIN)
        return list(info.solution_variables)
    except Exception:
        return []


def svar_data(solver, name, zone_names):
    """{zone: ndarray(float64)} — 없으면 빈 dict."""
    try:
        data = solver.fields.solution_variable_data.get_data(variable_name=name, zone_names=list(zone_names),
                                                             domain_name=DOMAIN).data
    except Exception:
        return {}
    return {k: np.asarray(v, dtype=np.float64) for k, v in data.items()}


def union_names(solver, zones):
    seen = {}
    for _, nm in zones:
        for v in svar_names(solver, [nm]):
            seen.setdefault(v, None)
    return list(seen)


def visible(names, show_all):
    return names if show_all else [n for n in names if not is_hidden_svar(n)]


def shape_array(arr, n, name):
    """평탄 SVAR 를 (n,) 또는 (n, k) 로. 길이가 안 맞으면 None."""
    if arr is None:
        return None
    if arr.size == n:
        return arr.reshape(n)
    if n > 0 and arr.size % n == 0:
        return arr.reshape(n, arr.size // n)
    say("[WARN] %s: 길이 %d 가 요소 수 %d 와 맞지 않아 건너뜀" % (name, arr.size, n))
    return None


def add_velocity(cell_data, n):
    comps = [cell_data.get(c) for c in VELOCITY_COMPONENTS]
    if all(c is not None and c.ndim == 1 and len(c) == n for c in comps):
        cell_data[VELOCITY_NAME] = np.column_stack(comps)
        return True
    return False


def boundary_face_counts(solver, boundary):
    """경계 면 존별 면 수 (기하 요청 1회). 실패하면 {}."""
    try:
        from ansys.fluent.core.fields.field_data_interfaces import SurfaceDataType, SurfaceFieldDataRequest
        names = [nm for _, nm in boundary]
        if not names:
            return {}
        geo = solver.fields.field_data.get_field_data(
            SurfaceFieldDataRequest(surfaces=names, data_types=[SurfaceDataType.FacesCentroid]))
        return {nm: int(len(geo[nm].face_centroids)) for nm in names if nm in geo}
    except Exception as e:
        say("[WARN] 경계 면 수 조회 실패: %s" % str(e)[:80])
        return {}


# =============================================================================
# --list-json
# =============================================================================
def list_json(args, case_path, work_dir):
    data_file, matches = resolve_or_fail(case_path)
    solver, dimension = load_case(args, case_path, data_file, work_dir)
    cell_zones, boundary = zone_lists(solver)
    if not cell_zones:
        emit_json({"error": "셀 존이 없습니다", "engine": ENGINE})
        sys.exit(1)
    cell_all = union_names(solver, cell_zones)
    face_all = union_names(solver, boundary)
    n_cells = 0
    for _, zn in cell_zones:
        v = svar_data(solver, "SV_VOLUME", [zn]).get(zn)
        n_cells += 0 if v is None else int(v.size)
    counts = boundary_face_counts(solver, boundary)
    emit_json({
        "engine": ENGINE,
        "cell_arrays": visible(cell_all, args.all),
        "face_arrays": visible(face_all, args.all),
        "hidden_cell_arrays": [n for n in cell_all if is_hidden_svar(n)],
        "point_arrays": [],
        "vector_fields": [VELOCITY_NAME] if all(c in cell_all for c in VELOCITY_COMPONENTS) else [],
        "cell_zones": [nm for _, nm in cell_zones],
        "boundaries": [{"name": nm, "zone_id": zid, "n_faces": counts.get(nm)} for zid, nm in boundary],
        "dimension": dimension,
        "fluent_version": str(solver.get_fluent_version()),
        "case_file": str(case_path),
        "data_file": str(data_file),
        "data_name_matches": bool(matches),
        "case_size_mb": round(Path(case_path).stat().st_size / 1024**2, 2),
        "n_cells": n_cells,
    })


# =============================================================================
# 변환
# =============================================================================
def build_volume(solver, cell_zones, selected, check, is_2d, p0, p1):
    """셀 존들 → vtkUnstructuredGrid (절점 병합 없음)."""
    fd = solver.fields.field_data
    grids = []
    attached = None
    for i, (zid, zn) in enumerate(cell_zones):
        check_cancel()
        t = time.time()
        mesh = fd.get_mesh(zn)
        say("  get_mesh(%s): nodes=%d, cells=%d (%.1f초)" % (zn, len(mesh.nodes), len(mesh.elements), time.time() - t))
        t = time.time()
        zm = pm.build_zone_mesh(zid, zn, mesh.nodes, mesh.elements, is_2d, log=say)
        del mesh
        say("  VTK 배치 변환 (%.1f초): 셀 %d개, 폴리헤드론 facet %d개" % (time.time() - t, zm.n_cells, zm.n_faces))
        progress(p0 + (p1 - p0) * (i + 0.4) / len(cell_zones))
        check_cancel()

        sv_vol = shape_array(svar_data(solver, "SV_VOLUME", [zn]).get(zn), zm.n_cells, "SV_VOLUME")
        sv_cen = svar_data(solver, "SV_CENTROID", [zn]).get(zn)
        if sv_cen is not None and zm.n_cells and sv_cen.size % zm.n_cells == 0:
            sv_cen = sv_cen.reshape(zm.n_cells, -1)
            if sv_cen.shape[1] == 2:
                sv_cen = np.column_stack([sv_cen, np.zeros(zm.n_cells)])
            elif sv_cen.shape[1] != 3:
                sv_cen = None
        else:
            sv_cen = None
        if zm.n_faces:
            n_flip = pm.orient_polyhedra(zm, sv_cen)
            say("  폴리헤드론 facet 방향 보정: %d개 뒤집음" % n_flip)
        pm.orient_linear_cells(zm, log=say)
        if check:
            m = pm.verify_zone(zm, sv_vol, sv_cen)
            if m["total_rel"] is not None:
                say("  [VERIFY] 존 %s: 부피 %.6e, SV_VOLUME 대비 상대오차 %.1e (셀 최대 %.1e), 음수 부피 %d개, 중심 편차 %s" % (
                    zn, m["volume"], m["total_rel"], m["max_cell_rel"], m["n_neg"],
                    "%.2f셀" % m["centroid_dev"] if m["centroid_dev"] is not None else "-"))
            else:
                say("  [VERIFY] 존 %s: 부피 %.6e (SV_VOLUME 없음), 음수 부피 %d개" % (zn, m["volume"], m["n_neg"]))
            if not m["ok"]:
                say("[WARN] 존 %s 의 기하 검증이 Fluent 와 맞지 않습니다. 출력을 확인하세요" % zn)

        zone_vars = set(svar_names(solver, [zn]))
        for v in selected:
            if v not in zone_vars:
                say("[WARN] %s: 존 %s 에 없음 → NaN" % (v, zn))
                zm.cell_data[v] = np.full(zm.n_cells, np.nan)
                continue
            arr = shape_array(svar_data(solver, v, [zn]).get(zn), zm.n_cells, v)
            if arr is not None:
                zm.cell_data[v] = arr
        add_velocity(zm.cell_data, zm.n_cells)
        attached = list(zm.cell_data.keys())
        grids.append(pm.to_vtk_grid(zm))
        del zm
        progress(p0 + (p1 - p0) * (i + 1) / len(cell_zones))
    return pm.merge_grids(grids), attached or []


def build_boundaries(solver, boundary, selected, p0, p1):
    """경계 면 존들 → vtkPolyData 1장 (boundary_id + boundary_names)."""
    from ansys.fluent.core.fields.field_data_interfaces import SurfaceDataType, SurfaceFieldDataRequest
    fd = solver.fields.field_data
    names = [nm for _, nm in boundary]
    t = time.time()
    geo = fd.get_field_data(SurfaceFieldDataRequest(
        surfaces=names, flatten_connectivity=True,
        data_types=[SurfaceDataType.Vertices, SurfaceDataType.FacesConnectivity, SurfaceDataType.FacesCentroid]))
    say("  경계 기하 수신 %d개 (%.1f초)" % (len(geo), time.time() - t))
    progress(p0 + (p1 - p0) * 0.2)
    check_cancel()

    # 1차: 존별 SVAR 수집 + 변수별 성분 수 (존마다 없는 변수는 2차에서 NaN 으로 채워 배열 구성을 맞춘다)
    per_zone = {}
    dims = {}
    n_faces_of = {nm: int(len(geo[nm].face_centroids)) for nm in names
                  if nm in geo and geo[nm].face_centroids is not None}
    for zid, nm in boundary:
        zone_vars = set(svar_names(solver, [nm]))
        per_zone[nm] = {}
        n = n_faces_of.get(nm, 0)
        for v in selected + ["SV_CENTROID"]:
            if v in zone_vars:
                arr = svar_data(solver, v, [nm]).get(nm)
                if arr is None:
                    continue
                per_zone[nm][v] = arr
                if v in selected and v not in dims and n and arr.size % n == 0:
                    dims[v] = () if arr.size == n else (arr.size // n,)
    missing = [v for v in selected if not any(v in d for d in per_zone.values())]
    if missing:
        say("[WARN] 어느 경계에도 없는 변수(건너뜀): %s" % missing)
        selected = [v for v in selected if v not in missing]
    progress(p0 + (p1 - p0) * 0.5)
    check_cancel()

    polys, used, max_diff, max_dev = [], [], 0.0, 0.0
    for zid, nm in boundary:
        g = geo.get(nm)
        if g is None or g.vertices is None or len(g.vertices) == 0:
            say("[WARN] 경계 %s: 기하 없음 → 건너뜀" % nm)
            continue
        sm = pm.build_surface_mesh(zid, nm, g.vertices, g.connectivity, g.face_centroids)
        n = sm.n_faces
        for v in selected:
            arr = per_zone[nm].get(v)
            shaped = shape_array(arr, n, "%s@%s" % (v, nm)) if arr is not None else None
            if shaped is None:
                shaped = np.full((n,) + tuple(dims.get(v, ())), np.nan)
            sm.cell_data[v] = shaped
        add_velocity(sm.cell_data, n)
        sm.cell_data[BOUNDARY_ID] = np.full(n, zid, dtype=np.int32)
        dev, diff = pm.verify_surface(sm, per_zone[nm].get("SV_CENTROID"))
        max_dev = max(max_dev, dev)
        if diff is not None:
            max_diff = max(max_diff, diff)
        say("  경계 %s (id %d): 면 %d, 점 %d, 꼭짓점평균-중심 편차 %.2f면크기, SV_CENTROID 차 %s" % (
            nm, zid, n, sm.n_points, dev, "%.1e m" % diff if diff is not None else "-"))
        if dev > 1.0:
            say("[WARN] 경계 %s: 면 연결이 Fluent 중심과 맞지 않습니다" % nm)
        polys.append(pm.to_vtk_polydata(sm))
        used.append(nm)
    if not polys:
        fail("내보낼 경계 면 존이 없습니다")
    say("  [VERIFY] 면 중심 최대차 %.1e m (SV_CENTROID vs FacesCentroid), 꼭짓점평균 편차 최대 %.2f" % (max_diff, max_dev))
    # 벡터가 일부 존에만 있으면 NaN 채움 (vtkAppendPolyData 는 모든 조각에 같은 배열이 있어야 유지)
    arrays = sorted({k for p in polys for k in (p.GetCellData().GetArrayName(i) for i in range(p.GetCellData().GetNumberOfArrays()))})
    for p in polys:
        have = {p.GetCellData().GetArrayName(i) for i in range(p.GetCellData().GetNumberOfArrays())}
        for k in arrays:
            if k not in have:
                ref = next(q.GetCellData().GetArray(k) for q in polys if q.GetCellData().GetArray(k) is not None)
                pm._add_arrays(p.GetCellData(), {k: np.full((p.GetNumberOfCells(), ref.GetNumberOfComponents()), np.nan).squeeze()})
    progress(p0 + (p1 - p0) * 0.9)
    return pm.merge_polydata(polys, names=used), arrays


def apply_display_names(dataset, enabled):
    if not enabled:
        return {}
    cd = dataset.GetCellData()
    names = [cd.GetArrayName(i) for i in range(cd.GetNumberOfArrays())]
    renames, unmapped = plan_renames(names, protected=PROTECTED_NAMES)
    pm.rename_arrays(dataset, renames)
    if renames:
        say("  [RENAME] %s" % ", ".join("%s→%s" % kv for kv in renames.items()))
    unmapped = [u for u in unmapped if u not in PROTECTED_NAMES]
    if unmapped:
        say("[WARN] 표시명 없음(원본 유지): %s" % unmapped)
    return renames


def convert(args, case_path, out_path, out_format, work_dir, alias_dir=None):
    start = time.time()
    binary = not args.ascii
    requested = [v.strip() for v in (args.vars or "").split(",") if v.strip()]
    if not requested and not args.all:
        fail("--vars 또는 --all 이 필요합니다.")

    data_file, _ = resolve_or_fail(case_path)
    progress(10)
    solver, dimension = load_case(args, case_path, data_file, work_dir, alias_dir)
    is_2d = dimension == 2
    progress(35)
    check_cancel()

    cell_zones, boundary = zone_lists(solver)
    say("[3] 존: 셀 %s, 경계 %s" % ([nm for _, nm in cell_zones], [nm for _, nm in boundary]))
    if not cell_zones:
        fail("셀 존이 없습니다")
    if out_format == "vtu":
        available = union_names(solver, cell_zones)
    else:
        if args.surfaces:
            wanted = [s.strip() for s in args.surfaces.split(",") if s.strip()]
            boundary = [(zid, nm) for zid, nm in boundary if nm in wanted]
            missing = [w for w in wanted if w not in [nm for _, nm in boundary]]
            if missing:
                say("[WARN] 없는 경계(건너뜀): %s" % missing)
        if not boundary:
            fail("경계 면 존이 없습니다 (interior 제외)")
        available = union_names(solver, boundary)
    if args.all:
        selected = visible(available, False)
        say("[4] 모든 변수 %d개 선택 (숨김 제외)" % len(selected))
    else:
        selected = [v for v in requested if v in available]
        invalid = [v for v in requested if v not in available]
        say("[4] 선택 변수: %s" % selected)
        if invalid:
            say("[WARN] 없는 변수(건너뜀): %s" % invalid)
        if not selected:
            fail("유효한 변수가 없습니다. 사용 가능: %s" % visible(available, False))
    progress(40)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    remove_stale(out_path)
    if out_format == "vtu":
        say("[5] 체적 격자 조립 중 (셀 존 %d개)..." % len(cell_zones))
        dataset, attached = build_volume(solver, cell_zones, selected, not args.no_check, is_2d, 40, 80)
        expect = "UnstructuredGrid"
    else:
        say("[5] 경계 면 존 %d개 → PolyData 1장..." % len(boundary))
        dataset, attached = build_boundaries(solver, boundary, selected, 40, 80)
        expect = "PolyData"
    check_cancel()
    apply_display_names(dataset, args.rename)
    progress(85)

    say("[6] 저장 중: %s" % out_path.name)
    t = time.time()
    if out_format == "vtu":
        pm.write_grid(dataset, out_path, binary)
    else:
        pm.write_polydata(dataset, out_path, binary)
    say("  [OK] 저장 (%.2f초)" % (time.time() - t))
    verify_saved(out_path, expect)
    progress(95)
    return out_path, attached, start


# =============================================================================
# 실행 단위: 케이스 하나 / 케이스 목록
# =============================================================================
def resolve_format(out_path, fmt):
    out_format = ("vtp" if out_path.suffix.lower() == ".vtp" else "vtu") if (fmt or "auto") == "auto" else fmt
    if out_path.suffix.lower() not in (".vtu", ".vtp"):
        out_path = out_path.with_suffix("." + out_format)
    return out_path, out_format


def run_case(args, case_path, out_path, out_format, work_dir, alias_dir=None, header="[1] 입력 파일 검증"):
    """케이스 하나를 변환하고 [완료] 블록을 출력한다. 실패는 CaseFailed, 중단은 Cancelled 로 올린다."""
    if not case_path.exists():
        fail("case 파일 없음: %s" % case_path)
    say("%s (엔진: pyfluent, 포맷: %s)" % (header, out_format.upper()))
    say("  [OK] %s (%.2f MB)" % (case_path.name, case_path.stat().st_size / 1024**2))
    progress(5)
    written, attached, start = convert(args, case_path, out_path, out_format, work_dir, alias_dir)
    if not written.exists():
        fail("파일 생성 실패: %s" % written)
    say("[완료] 변환 성공")
    say("  엔진: pyfluent")
    say("  파일: %s" % written.name)
    say("  크기: %.2f MB" % (written.stat().st_size / 1024**2))
    say("  포맷: %s" % out_format.upper())
    say("  변수: %d개 (Cell Data: %s)" % (len(attached), ", ".join(attached)))
    say("  케이스 시간: %.2f초" % (time.time() - start))
    say("  위치: %s" % written.parent.resolve())


def run_jobs(args, jobs, work_dir):
    """케이스 목록을 한 세션으로 처리. 반환 (성공 수, 실패 수, 중단 여부)."""
    n = len(jobs)
    ok = failed = 0
    cancelled = False
    say("[1] 배치: 케이스 %d개 — Fluent 는 한 번만 띄우고 케이스마다 읽어 변환합니다 (차원이 바뀌면 재기동)" % n)
    for k, job in enumerate(jobs, 1):
        idx = int(job.get("index", k))
        case_path = Path(str(job["case"])).resolve()
        out_path, out_format = resolve_format(Path(str(job["output"])).resolve(), job.get("format"))
        say("[FILE_START] %d/%d %s" % (idx, n, case_path))
        if _CANCEL.is_set():
            say("[FILE_DONE] %d/%d fail 사용자 중단" % (idx, n))
            cancelled = True
            break
        alias_dir = work_dir / ("c%d" % idx)
        try:
            os.utime(work_dir)       # 긴 배치에서 다른 워커의 remove_stale_workdirs(10분 규칙)로부터 보호
        except OSError:
            pass
        try:
            run_case(args, case_path, out_path, out_format, work_dir, alias_dir, header="[1] 케이스 %d/%d" % (idx, n))
            ok += 1
            say("[FILE_DONE] %d/%d ok" % (idx, n))
        except Cancelled:
            say("[FILE_DONE] %d/%d fail 사용자 중단" % (idx, n))
            cancelled = True
            break
        except CaseFailed as e:
            failed += 1
            say("[WARN] 케이스 실패: %s" % e)
            say("[FILE_DONE] %d/%d fail %s" % (idx, n, str(e).replace("\n", " ")[:300]))
        except Exception as e:
            if _CANCEL.is_set():
                say("[FILE_DONE] %d/%d fail 사용자 중단" % (idx, n))
                cancelled = True
                break
            failed += 1
            msg = "%s: %s" % (type(e).__name__, str(e).replace("\n", " ")[:300])
            say("[WARN] 케이스 실패: %s" % msg)
            say("[FILE_DONE] %d/%d fail %s" % (idx, n, msg))
            # Fluent 호출 중 난 예외일 수 있다 → 세션을 버리고 다음 케이스에서 새로 띄운다 (상태 오염 방지)
            say("[WARN] 안전을 위해 Fluent 세션을 닫고 다음 케이스에서 다시 띄웁니다")
            close_session(timeout=20)
        finally:
            cleanup_alias(alias_dir)
    say("[완료] 배치: 성공 %d / 실패 %d / 미처리 %d (총 %d)" % (ok, failed, n - ok - failed, n))
    return ok, failed, cancelled


# =============================================================================
# main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="CFF -> VTU/VTP 변환 워커 (PyFluent 라이브 Fluent 세션)")
    parser.add_argument("--case", "-c", default=None, help="CFF case 파일 (.cas.h5). 같은 폴더의 <base>.dat.h5 또는 <base>-<n>.dat.h5 를 읽는다")
    parser.add_argument("--jobs", default=None, help="케이스 목록 JSON 파일 [{index, case, output, format}] — Fluent 1회 기동으로 순차 변환 (GUI 배치)")
    parser.add_argument("--output", "-o", default=None, help="출력 경로 (.vtu / .vtp)")
    parser.add_argument("--format", "-f", choices=["auto", "vtu", "vtp"], default="auto", help="출력 포맷 (auto=확장자)")
    parser.add_argument("--vars", "-v", default=None, help="저장할 변수 (쉼표 구분, SVAR 이름 SV_*)")
    parser.add_argument("--all", "-a", action="store_true", help="모든 변수 (list-json: 숨김 포함 목록)")
    parser.add_argument("--list-json", action="store_true", help="변수·경계 목록을 JSON 으로 출력 (GUI 용)")
    parser.add_argument("--ascii", action="store_true", help="ASCII 저장")
    parser.add_argument("--rename", action="store_true", help="저장 시 Fluent 표시명으로 이름 변경 (cff_common.py 표)")
    parser.add_argument("--surfaces", default=None, help="[vtp] 포함할 경계 이름 (쉼표). 기본 = interior 제외 전부")
    parser.add_argument("--no-check", action="store_true", help="SV_VOLUME/SV_CENTROID 기하 검증 생략")
    parser.add_argument("--processors", type=int, default=1, help="Fluent 프로세스 수 (기본 1. 2 이상이면 셀 순서가 바뀐다)")
    parser.add_argument("--fluent-version", default=None, help="Fluent 제품 버전 (예 26.1.0). 기본 = 설치된 최신")
    parser.add_argument("--start-timeout", type=int, default=240, help="Fluent 기동 대기 초 (기본 240)")
    args = parser.parse_args()
    if not args.case and not args.jobs:
        parser.error("--case 또는 --jobs 가 필요합니다")

    # ---- jobs 모드 (결정 005)
    if args.jobs:
        jobs_path = Path(args.jobs).resolve()
        try:
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            assert isinstance(jobs, list) and jobs
        except Exception as e:
            say("[ERROR] jobs 파일을 읽지 못했습니다: %s (%s)" % (jobs_path, str(e)[:120]))
            sys.exit(1)
        if not (args.vars or args.all):
            say("[ERROR] --vars 또는 --all 이 필요합니다.")
            sys.exit(1)
        start_cancel_listener()
        remove_stale_workdirs()
        work_dir = Path(tempfile.mkdtemp(prefix=WORKDIR_PREFIX))
        say("[WORKDIR] %s" % work_dir)      # GUI 가 기억해 두었다가 워커가 끝난 뒤 (잠금이 풀리면) 지운다
        t_all = time.time()
        ok = failed = 0
        cancelled = False
        try:
            ok, failed, cancelled = run_jobs(args, jobs, work_dir)
        except Cancelled:
            cancelled = True
        finally:
            close_session(timeout=30)
            remove_workdir(work_dir)
        mem = peak_memory_mb()
        say("  배치 시간: %.1f초%s" % (time.time() - t_all, ("  최대 메모리: %.0f MB" % mem) if mem is not None else ""))
        if cancelled:
            say("[ERROR] 사용자 중단")
            sys.exit(1)
        if failed:
            say("[ERROR] %d건 실패 (성공 %d건)" % (failed, ok))
            sys.exit(1)
        progress(100)
        say("[SUCCESS]")
        return

    # ---- 단일 케이스 모드
    case_path = Path(args.case).resolve()      # Fluent 는 임시 cwd 에서 돌므로 절대 경로가 필요하다
    if not case_path.exists():
        if args.list_json:
            emit_json({"error": "case 파일 없음: %s" % case_path, "engine": ENGINE})
            sys.exit(1)
        say("[ERROR] case 파일 없음: %s" % case_path)
        sys.exit(1)

    start_cancel_listener()
    remove_stale_workdirs()
    work_dir = Path(tempfile.mkdtemp(prefix=WORKDIR_PREFIX))
    say("[WORKDIR] %s" % work_dir)
    rc = 0
    try:
        if args.list_json:
            try:
                list_json(args, case_path, work_dir)
            except SystemExit:
                raise
            except Exception as e:
                if _CANCEL.is_set() or isinstance(e, Cancelled):
                    emit_json({"error": "사용자 중단", "engine": ENGINE})
                elif isinstance(e, CaseFailed):
                    emit_json({"error": str(e), "engine": ENGINE})
                else:
                    emit_json({"error": "%s: %s" % (type(e).__name__, str(e)[:300]), "engine": ENGINE})
                sys.exit(1)
            return
        if args.output is None:
            say("[ERROR] --output 이 필요합니다.")
            sys.exit(1)
        out_path, out_format = resolve_format(Path(args.output).resolve(), args.format)
        t_all = time.time()
        try:
            run_case(args, case_path, out_path, out_format, work_dir)
            say("  전체 시간: %.2f초" % (time.time() - t_all))
            mem = peak_memory_mb()
            if mem is not None:
                say("  최대 메모리: %.0f MB" % mem)
        except Cancelled:
            say("[ERROR] 사용자 중단")
            rc = 1
        except CaseFailed as e:
            say("[ERROR] %s" % e)
            rc = 1
        except Exception as e:
            if _CANCEL.is_set():
                say("[ERROR] 사용자 중단")
            else:
                say("[ERROR] %s: %s" % (type(e).__name__, str(e)[:300]))
            rc = 1
    finally:
        close_session(timeout=30)
        remove_workdir(work_dir)
    if rc:
        sys.exit(rc)
    progress(100)
    say("[SUCCESS]")


if __name__ == "__main__":
    main()
