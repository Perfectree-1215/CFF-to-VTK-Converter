"""
두 워커(pv_export_worker.py / cff_export_worker.py)가 함께 쓰는 공용 모듈. 표준 라이브러리만 사용.
pvpython 도 스크립트 폴더를 sys.path 에 넣으므로 같은 폴더에 두면 된다.

1. Fluent HDF5 변수명(SV_*) → Fluent 표시명 매핑 (결정 002 R1)
2. 데이터 파일(.dat.h5) 이름 해석과 임시 하드링크 (Workbench 원본 대응)
   - vtkFLUENTCFFReader 는 <base>.cas.h5 와 **같은 이름**의 <base>.dat.h5 만 자동으로 읽는다.
   - Workbench 가 남긴 FFF.3-2.cas.h5 + FFF.3-2-11200.dat.h5 (반복 횟수 접미사) 는 못 찾아 격자만 읽힌다.
   - 그래서 케이스 폴더 안 임시 하위 폴더에 이름을 맞춘 하드링크(실패 시 복사)를 만들어 그걸 읽고, 리더 해제 후 지운다.
"""
import atexit
import gc
import os
import re
import shutil
import tempfile
import time

# =============================================================================
# 1. 변수명 매핑
# =============================================================================
FLUENT_DISPLAY_NAMES = {
    "SV_P": "pressure",
    "SV_T": "temperature",
    "SV_U": "x-velocity",
    "SV_V": "y-velocity",
    "SV_W": "z-velocity",
    "SV_BF_V": "velocity",            # 체적 벡터 (CFF 리더)
    "SV_DENSITY": "density",
    "SV_K": "turb-kinetic-energy",
    "SV_D": "turb-diss-rate",
    "SV_O": "specific-diss-rate",
    "SV_MU_LAM": "viscosity-lam",
    "SV_MU_T": "viscosity-turb",
    "SV_H": "enthalpy",
    "SV_MACH": "mach-number",
    "SV_FLUX": "mass-flux",
    "SV_WALL_SHEAR": "wall-shear",
    "SV_HEAT_FLUX": "heat-flux",
    "SV_HEAT_FLUX_SENSIBLE": "heat-flux-sensible",
    "SV_RAD_HEAT_FLUX": "rad-heat-flux",
    "SV_RAD_HEAT_FLUX_EXTERIOR": "rad-heat-flux-exterior",
    "SV_WALL_YPLUS": "y-plus",
    "SV_WALL_YPLUS_UTAU": "y-plus-utau",
    "SV_WALL_T_INNER": "wall-temp-inner",
    "SV_WALL_V": "wall-velocity",
}

_STAT_SUFFIXES = (("_MEAN", "-mean"), ("_RMS", "-rms"))


def display_name(name):
    """표시명. 매핑이 없으면 None."""
    if name in FLUENT_DISPLAY_NAMES:
        return FLUENT_DISPLAY_NAMES[name]
    for suf, tag in _STAT_SUFFIXES:
        if name.endswith(suf):
            base = name[:-len(suf)]
            if base in FLUENT_DISPLAY_NAMES:
                return FLUENT_DISPLAY_NAMES[base] + tag
    return None


def plan_renames(names, protected=()):
    """이름 목록 → (바꿀 {old: new}, 미매핑 목록). 충돌(결과 이름이 이미 존재)은 원본 유지로 처리."""
    names = list(names)
    renames = {}
    unmapped = []
    taken = set(names)
    for old in names:
        if old in protected:
            continue
        new = display_name(old)
        if new is None:
            unmapped.append(old)
            continue
        if new == old:
            continue
        if new in taken:
            unmapped.append(old)      # 충돌: 원본 유지 (호출자가 WARN)
            continue
        renames[old] = new
        taken.discard(old)
        taken.add(new)
    return renames, unmapped


# -----------------------------------------------------------------------------
# 1b. PyFluent 라이브 세션이 돌려주는 솔버 내부 SVAR 숨김 규칙 (결정 004 축 3)
#     CFF 리더(PyVista 엔진)는 이런 배열을 애초에 주지 않는다. --all 이면 숨김 없이 전부.
# -----------------------------------------------------------------------------
HIDDEN_SVAR_EXACT = {
    "SV_C_INDEX", "SV_PARTITION", "SV_CENTROID", "SV_VOLUME", "SV_AREA", "SV_C0", "SV_C1",
    "SV_F_GHOSTLINK", "SV_BFP_V", "SV_BF_MARANGONI", "SV_BF_V", "SV_MASS_IMBALANCE", "SV_PRODUCTION",
    "SV_FLUX_LIMIT", "SV_FP_COEFF", "SV_PP_COEFF", "SV_DT_BC_SOURCE", "SV_ARTIFICIAL_WALL_FLAG",
    "SV_WALL_FACE_FORCE", "SV_WALL_KCON", "SV_WALL_KS", "SV_WALL_VV",
}
HIDDEN_SVAR_PREFIXES = ("SV_ADS_", "SV_F_A", "SV_FACE_", "SV_LSQ_", "SV_LSF_", "SV_MOM_AP_", "SV_PROFILE_",
                        "SV_WALL_PRORUS_", "SV_WALL_DIFFUSIVE_")
HIDDEN_SVAR_SUFFIXES = ("_G", "_RG", "_RG_AUX")


def is_hidden_svar(name):
    """솔버 내부·기하 배열이면 True (GUI 기본 목록에서 숨긴다)."""
    if name in HIDDEN_SVAR_EXACT:
        return True
    if name.startswith(HIDDEN_SVAR_PREFIXES):
        return True
    for suf in HIDDEN_SVAR_SUFFIXES:
        if name.endswith(suf) and name != "SV_" + suf.lstrip("_"):
            return True
    return False


# =============================================================================
# 2. 데이터 파일 해석
# =============================================================================
CASE_SUFFIX = ".cas.h5"
DATA_SUFFIX = ".dat.h5"
LINK_DIR_PREFIX = ".cff_link_"      # 임시 폴더 접두사. GUI 스캔은 이 폴더를 건너뛴다
_ITER_RE = re.compile(r"^-(\d+)$")


def case_base(case_path):
    """'FFF.3-2.cas.h5' → 'FFF.3-2'. .cas.h5 가 아니면 None."""
    name = os.path.basename(str(case_path))
    if name.lower().endswith(CASE_SUFFIX):
        return name[:-len(CASE_SUFFIX)]
    return None


def resolve_data_file(case_path):
    """케이스에 맞는 데이터 파일을 찾는다.

    반환: (dat 경로 또는 None, 이름이 맞는지 여부)
      - <base>.dat.h5 가 있으면 그것 (True)
      - 없으면 <base>-<n>.dat.h5 중 n 이 가장 큰 것 (False, 리더가 자동으로 못 찾으므로 링크 필요)
      - 둘 다 없으면 (None, False)
    """
    case_path = str(case_path)
    base = case_base(case_path)
    if base is None:
        return None, False
    folder = os.path.dirname(case_path) or "."
    exact = os.path.join(folder, base + DATA_SUFFIX)
    if os.path.isfile(exact):
        return exact, True
    best = None
    best_iter = -1
    try:
        entries = os.listdir(folder)
    except OSError:
        entries = []
    for fn in entries:
        if not (fn.startswith(base) and fn.lower().endswith(DATA_SUFFIX)):
            continue
        mid = fn[len(base):-len(DATA_SUFFIX)]
        m = _ITER_RE.match(mid)
        if not m:
            continue
        # 형제 케이스 보호: A.cas.h5 의 후보로 A-2.dat.h5 가 잡혀도 A-2.cas.h5 가 있으면 그 케이스의 dat 다
        if os.path.isfile(os.path.join(folder, base + mid + CASE_SUFFIX)):
            continue
        if int(m.group(1)) > best_iter:
            best_iter = int(m.group(1))
            best = os.path.join(folder, fn)
    return best, False


class PreparedCase:
    """리더에 넘길 케이스 경로. 이름이 안 맞는 dat 가 있으면 임시 링크 폴더를 만든다.

    사용:
        pc = PreparedCase(case_path)      # pc.case_to_open, pc.data_file, pc.linked, pc.copied
        ... 리더로 pc.case_to_open 읽기 ...
        pc.cleanup(release=lambda: None)  # 리더 참조를 끊은 뒤 호출
    """

    def __init__(self, case_path, log=None):
        self.case_path = str(case_path)
        self.log = log or (lambda msg: None)
        self.data_file, self.name_matches = resolve_data_file(self.case_path)
        self.case_to_open = self.case_path
        self.tmp_dir = None
        self.linked = False
        self.copied = False
        if self.data_file is not None and not self.name_matches:
            self._make_link_dir()

    def _make_link_dir(self):
        folder = os.path.dirname(self.case_path) or "."
        # 접미사 "_tmp": 폴더명이 숫자로 끝나면 bc_json_gen 이 설계 번호로 오인할 수 있다 (impact-scan)
        self.tmp_dir = tempfile.mkdtemp(prefix=LINK_DIR_PREFIX, suffix="_tmp", dir=folder)
        # 안쪽 파일명은 짧게 고정 (MAX_PATH 여유, base 에 점이 있어도 리더가 dat 를 찾는 것은 실측 확인)
        pairs = [
            (self.case_path, os.path.join(self.tmp_dir, "case" + CASE_SUFFIX)),
            (self.data_file, os.path.join(self.tmp_dir, "case" + DATA_SUFFIX)),
        ]
        try:
            for src, dst in pairs:
                os.link(src, dst)
            self.linked = True
        except OSError as e:
            # 하드링크 불가(다른 볼륨, 일부 동기화 폴더) → 복사 (대용량이면 느림)
            self.log("[WARN] 하드링크 실패(%s) → 복사로 대체합니다 (%.0f MB)" % (
                str(e)[:60], sum(os.path.getsize(s) for s, _ in pairs) / 1024**2))
            for src, dst in pairs:
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.copy2(src, dst)
            self.copied = True
        self.case_to_open = pairs[0][1]

    def describe(self):
        if self.data_file is None:
            return "데이터 파일(.dat.h5) 없음"
        if self.name_matches:
            return os.path.basename(self.data_file)
        how = "복사" if self.copied else "하드링크"
        return "%s (이름이 달라 임시 %s로 연결)" % (os.path.basename(self.data_file), how)

    def cleanup(self, retries=10, delay=0.3):
        """임시 폴더 삭제. 리더가 아직 파일을 잡고 있으면 잠시 기다렸다 재시도. 실패하면 경로를 반환."""
        if not self.tmp_dir:
            return None
        gc.collect()
        for _ in range(retries):
            try:
                for fn in os.listdir(self.tmp_dir):
                    os.remove(os.path.join(self.tmp_dir, fn))
                os.rmdir(self.tmp_dir)
                self.tmp_dir = None
                return None
            except OSError:
                time.sleep(delay)
        return self.tmp_dir

    def cleanup_at_exit(self):
        """즉시 삭제가 실패했을 때: 인터프리터 종료 시(리더 객체가 모두 사라진 뒤) 한 번 더 시도한다.
        그래도 남으면 GUI 가 워커 프로세스 종료 뒤 remove_stale_link_dirs 로 정리한다."""
        if not self.tmp_dir:
            return
        atexit.register(lambda: self.cleanup(retries=3, delay=0.2))


def remove_stale_link_dirs(folder, log=None, min_age_sec=0, retries=1, delay=0.3):
    """이전 실행이 남긴 .cff_link_* 폴더 정리 (취소·크래시 대비). 삭제한 폴더 수 반환.

    min_age_sec > 0 이면 그보다 오래된 폴더만 지운다 (다른 워커가 지금 쓰는 폴더 보호 — CLI 동시 실행 대비).
    GUI 는 워커 프로세스가 끝난 직후 0 으로 호출한다 (한 번에 워커 하나만 돌리므로 안전).
    retries > 1 이면 잠금(막 종료된 자식 프로세스가 핸들을 놓는 중)일 때 delay 간격으로 재시도한다.
    """
    n = 0
    try:
        entries = os.listdir(folder)
    except OSError:
        return 0
    now = time.time()
    for fn in entries:
        p = os.path.join(folder, fn)
        if not (fn.startswith(LINK_DIR_PREFIX) and os.path.isdir(p)):
            continue
        try:
            if min_age_sec > 0 and now - os.path.getmtime(p) < min_age_sec:
                continue
        except OSError:
            continue
        last = None
        for attempt in range(max(1, retries)):
            try:
                shutil.rmtree(p)
                n += 1
                last = None
                break
            except OSError as e:
                last = e
                if attempt + 1 < retries:
                    time.sleep(delay)
        if last is not None and log:
            log("[WARN] 임시 링크 폴더 삭제 실패: %s (%s)" % (p, str(last)[:50]))
    return n
