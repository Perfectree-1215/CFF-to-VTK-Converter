"""
Fluent CFF 유틸리티 — GUI (v2.0)
Author: 퍼팩트리

PySide6 데스크톱 앱. 탭 4개를 한 창에 묶는다 (MainWindow):
  1. Workbench DP 정리  (dp_collect_tab.DPCollectTab)  — DP 폴더의 Case/Data 를 dp_001.cas.h5 식으로 복사·이름 통일
  2. PyVista 변환기     (ConverterTab)                 — CFF(.cas.h5/.dat.h5) → VTU/VTP 일괄 변환. 엔진 PyVista(기본)·ParaView
  3. PyFluent 변환기    (PyFluentTab)                  — 헤드리스 Fluent 세션으로 VTU(셀 존 재구성)/VTP(경계 병합). Fluent 필요
  4. JSON 생성기        (BCJsonTab)                    — 설계 테이블 CSV → 설계 폴더별 boundary_conditions.json (Stochos)

변환은 별도 워커 프로세스가 수행한다 (GUI 는 QProcess 로 호출, stdout 프로토콜은 docs/worker-protocol.md):
  - cff_export_worker.py      PyVista 워커 (이 Python)
  - pv_export_worker.py       ParaView 워커 (pvpython)
  - pyfluent_export_worker.py PyFluent 워커 (이 Python + ansys-fluent-core, 격자 조립은 pyfluent_mesh.py)
공용 모듈: cff_common.py(표시명 매핑·dat 이름 해석), app_theme.py(Solarized Light 테마), session_log.py(세션 로그).

출력 규칙: 설계 폴더 <접두사>_NNN/Results.vtu|Results.vtp (파일명에 dp 번호가 있으면 그 번호, 없으면 순번. 3자리).
실행: setup_and_run.bat (venv 생성·의존성 설치 뒤 GUI 실행) 또는 python pv_export_gui.py
"""
import sys
import os
import re
import json
import logging
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit, QProgressBar,
    QGroupBox, QScrollArea, QCheckBox, QRadioButton, QButtonGroup,
    QMessageBox, QListWidget, QListWidgetItem, QComboBox, QTabWidget, QSpinBox,
)

from dp_collect_tab import DPCollectTab
from app_theme import APP_QSS, BASE_FONT_PT, COLOR_ACCENT_TEXT, COLOR_TEXT, ConsoleEdit, append_log, apply_palette, set_role   # Solarized Light 테마 (v2.0)
import bc_json_gen
import session_log
from cff_common import resolve_data_file, remove_stale_link_dirs, LINK_DIR_PREFIX   # 표준 라이브러리만 사용

# 앱 버전은 이 상수 하나로 관리 (윈도우 타이틀에 표시)
APP_TITLE = "CFF To VTK 변환기 v2.1"


# ============================================================
# logging → Qt 콘솔 브리지 (bc_json_gen 등 모듈 로그를 콘솔로 전달)
# ============================================================
class _QtLogHandler(logging.Handler):
    """logging 레코드를 콜백(예: 콘솔 append)으로 흘려보내는 핸들러."""
    def __init__(self, emit_fn):
        super().__init__()
        self._emit = emit_fn

    def emit(self, record):
        try:
            self._emit(self.format(record))
        except Exception:
            pass

# 탭 바 다크 스타일 (변환기 탭의 스타일시트에 이어붙여 앱 전체에 적용)
# 테마(QSS·팔레트)는 app_theme.py 한 곳에서 관리한다 (v2.0, Solarized Light)

# 워커 스크립트 경로 (같은 폴더)
WORKER_SCRIPT = str(Path(__file__).parent / "pv_export_worker.py")       # ParaView(pvpython) 전용
CFF_WORKER_SCRIPT = str(Path(__file__).parent / "cff_export_worker.py")  # PyVista (일반 python)

# 변환 엔진 (결정 001 D1·D2·D5)
ENGINE_PARAVIEW = "paraview"
ENGINE_PYVISTA = "pyvista"
ENGINE_LABELS = {
    ENGINE_PARAVIEW: "ParaView (pvpython)",
    ENGINE_PYVISTA: "PyVista",
}
# 엔진별 허용 포맷. 첫 항목이 그 엔진의 기본 포맷. (VTM 은 pv_export_worker.py CLI 전용)
ENGINE_FORMATS = {
    ENGINE_PARAVIEW: ("vtu",),
    ENGINE_PYVISTA: ("vtu", "vtp"),
}
FORMAT_HINTS = {
    "vtu": "VTU: 체적 단일 grid → Design_NNN/Results.vtu",
    "vtp": "VTP: 외곽 표면 1장 → Design_NNN/Results.vtp (경계 구분 없음, PyVista 엔진)",
}


def detect_engine_modules():
    """PyVista 엔진에 필요한 모듈이 이 Python에 있는지 확인 (무거운 import 없이 메타데이터만).

    반환: {engine: (사용 가능 여부, 상태 문구)}
    """
    import importlib.util
    try:
        from importlib.metadata import version as _ver
    except ImportError:  # pragma: no cover
        _ver = lambda name: "?"

    def ver(dist):
        try:
            return _ver(dist)
        except Exception:
            return "?"

    result = {}
    if importlib.util.find_spec("pyvista") is not None:
        result[ENGINE_PYVISTA] = (True, "pyvista %s 감지됨" % ver("pyvista"))
    else:
        result[ENGINE_PYVISTA] = (False, "pyvista 없음 → pip install pyvista")
    return result


def python_interpreter():
    """워커를 실행할 일반 Python. pythonw.exe(콘솔 없음)로 GUI가 떠 있으면 python.exe로 바꾼다."""
    exe = sys.executable or ""
    base = os.path.basename(exe).lower()
    if base == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(cand):
            return cand
    return exe


# 출력 구조 규칙
#   폴더명 접두사(prefix)를 지정하면 변환 순서대로 번호가 붙는다.
#   - VTU: <prefix>_001/Results.vtu
#   - VTP: <prefix>_001/Results.vtp (외곽 표면 1장, PyVista 엔진)
#   (VTM 은 GUI 에서 제외. pv_export_worker.py CLI 로만 가능)
#   접두사를 비우면 입력 파일명 기반(<base>_export)으로 폴백.
DEFAULT_FOLDER_PREFIX = "Design"  # 폴더명 접두사 기본값
# 번호 자릿수 (001, 002 …). dp_collect_tab.DP_NUM_WIDTH와 자릿수를 맞춰 사용.
# 변환탭 순번은 1부터 부여하고, 파일명에 dp 번호가 있으면 그 번호를 그대로 사용.
FOLDER_NUM_WIDTH = 3
EXPORT_SUFFIX = "_export"        # 접두사 미지정 시 폴백 접미사
UNIFIED_VTU_NAME = "Results"     # 내부 .vtu 통일 파일명

# 입력 파일명에서 DP 번호 자동 감지 (예: dp_016 → 16). DP 정리 탭 결과와 번호 연계.
# 'dp'가 문자열 시작 또는 비영숫자 뒤에 올 때만 매칭해 오탐(add**p**...) 방지.
DP_NUM_IN_NAME_RE = re.compile(r"(?:^|[^A-Za-z0-9])dp[_-]?(\d+)", re.IGNORECASE)


# ============================================================
# ParaView pvpython 자동 탐지
# ============================================================
def find_pvpython():
    """시스템에서 pvpython 실행 파일을 자동 탐지."""
    import glob
    candidates = []
    program_files = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for pf in program_files:
        if pf and os.path.isdir(pf):
            pattern = os.path.join(pf, "ParaView*", "bin", "pvpython.exe")
            candidates.extend(glob.glob(pattern))
    for path in ["/usr/bin/pvpython", "/usr/local/bin/pvpython",
                 "/opt/paraview/bin/pvpython"]:
        if os.path.exists(path):
            candidates.append(path)
    def _version_key(path):
        # 경로 속 숫자들을 정수 튜플로 뽑아 자연 버전 정렬 (5.11 > 5.9 보장).
        # 숫자가 완전히 같으면 문자열 비교로 폴백.
        nums = [int(x) for x in re.findall(r"\d+", path)]
        return (nums, path)
    candidates = sorted(set(candidates), key=_version_key, reverse=True)
    return candidates[0] if candidates else ""


# ============================================================
# 변수 목록 로딩 스레드 (첫 파일로 --list-json 호출)
# ============================================================
class VariableLoader(QThread):
    finished_ok = Signal(dict)
    finished_err = Signal(str)

    LOAD_TIMEOUT_SEC = 300   # 대용량 케이스(수백 MB dat)의 로딩 여유

    def __init__(self, interpreter, worker_script, case_file, engine=ENGINE_PARAVIEW):
        super().__init__()
        self.interpreter = interpreter
        self.worker_script = worker_script
        self.case_file = case_file
        self.engine = engine
        self.proc = None          # 실행 중인 subprocess (취소 시 kill 대상)
        self._cancelled = False   # True면 어떤 시그널도 emit하지 않음

    def run(self):
        import subprocess
        try:
            # Popen으로 실행해 프로세스 핸들(self.proc)을 보관 → 로딩 중 종료 시 kill 가능.
            # 한글 로그 깨짐 방지를 위해 PYTHONIOENCODING=utf-8 환경변수 주입.
            cmd = [self.interpreter, self.worker_script, "--case", self.case_file, "--list-json"]
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            try:
                out, _ = self.proc.communicate(timeout=self.LOAD_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                if not self._cancelled:
                    self.finished_err.emit("시간 초과 (%d초)." % self.LOAD_TIMEOUT_SEC)
                return

            # 취소되었으면 파싱/emit 없이 조용히 종료
            if self._cancelled:
                return

            if "###JSON_START###" in out and "###JSON_END###" in out:
                json_str = out.split("###JSON_START###")[1].split("###JSON_END###")[0].strip()
                data = json.loads(json_str)
                if "error" in data:
                    self.finished_err.emit(data["error"])
                else:
                    data.setdefault("engine", self.engine)   # ParaView 워커는 engine 키가 없다
                    self.finished_ok.emit(data)
            else:
                # 마커가 없으면 임포트 실패·크래시 스택이 섞여 있을 수 있다 (stderr 병합) → 끝부분을 보여 준다
                self.finished_err.emit("변수 목록 파싱 실패.\n출력:\n" + out[-800:])
        except Exception as e:
            if not self._cancelled:
                self.finished_err.emit(repr(e))

    def cancel(self):
        """로딩 중 취소: 플래그를 세우고 프로세스를 종료 (예외 무시)."""
        self._cancelled = True
        try:
            if self.proc is not None:
                self.proc.kill()
        except Exception:
            pass


# ============================================================
# 변환기 탭 (CFF → VTM/VTU)
# ============================================================
class ConverterTab(QWidget):
    def __init__(self):
        super().__init__()

        self.var_checkboxes = []      # 변수 체크박스 리스트
        self.cff_files = []           # 탐색된 CFF 파일 경로 리스트
        self.process = None           # 현재 변환 QProcess
        self.batch_queue = []         # 배치 처리 대기열
        self.batch_index = 0          # 현재 처리 중인 인덱스
        self.batch_total = 0          # 전체 파일 수
        self.batch_success = 0        # 성공 개수
        self.batch_failed = 0         # 실패 개수
        self.selected_vars = []       # 변환에 사용할 변수
        self.out_format = "vtu"       # 출력 포맷 (배치 시작 시 캡처)
        self.engine = ENGINE_PYVISTA  # 현재 선택 엔진 (라디오와 동기화)
        self.engine_status = detect_engine_modules()   # {engine: (사용 가능, 상태 문구)}
        self.vars_engine = None       # 변수 목록을 불러온 엔진 (엔진이 바뀌면 목록 무효)
        self.vars_cell = []           # --list-json 의 cell_arrays (체적 셀 배열)
        self.batch_rename = True      # 배치 시작 시 캡처: Fluent 표시명으로 저장 (--rename, 결정 002 R1)
        self.batch_engine = ENGINE_PYVISTA   # 배치 시작 시 캡처 (중간 변경 무시)
        self.batch_interpreter = ""   # 배치 시작 시 캡처한 인터프리터 (pvpython 또는 python)
        self.batch_worker = ""        # 배치 시작 시 캡처한 워커 스크립트
        self.output_dir_override = "" # 출력 폴더 (선택)
        self.folder_prefix = ""       # 폴더명 접두사 (배치 시작 시 캡처)
        self._batch_folders = set()   # 배치 내 폴더명 충돌 감지용
        self._out_buf = ""            # QProcess 출력의 미완성 줄 버퍼 (청크 경계 보호)
        self._current_case_dir = ""   # 현재 워커가 읽는 케이스 폴더 (종료 뒤 임시 링크 폴더 정리)

        self._build_ui()
        self._auto_detect_pvpython()
        self._init_engine_selection()

    # --------------------------------------------------------
    # UI 구성
    # --------------------------------------------------------
    def _build_ui(self):
        """2단 레이아웃 (v2.0, 수정사항-01.pptx 슬라이드 2):
        왼쪽 = 1.엔진 · 2.입력 폴더 · 4.출력 설정, 오른쪽 = 3.변수 선택(세로로 늘어남) · 실행 · 중단 · 진행바, 아래 전폭 = 콘솔.
        위젯 속성명은 바꾸지 않는다 (PyFluent 탭이 빌려 쓰는 메서드·헤드리스 시험이 참조)."""
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 12, 14, 12)

        # --- 제목 줄: 제목 + 한 줄 설명 ---
        head = QHBoxLayout()
        title = QLabel("PyVista 변환기")
        set_role(title, "title")
        subtitle = QLabel("폴더 안의 모든 CFF(.cas.h5)를 찾아 VTU/VTP 로 일괄 변환  ·  엔진: PyVista(기본) 또는 ParaView")
        set_role(subtitle, "subtitle")
        subtitle.setWordWrap(True)
        head.addWidget(title)
        head.addSpacing(14)
        head.addWidget(subtitle, 1)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(10)
        right = QVBoxLayout()
        right.setSpacing(10)

        # --- 1. 변환 엔진 (왼쪽) ---
        eng_group = QGroupBox("1. 변환 엔진")
        eng_outer = QVBoxLayout(eng_group)
        eng_outer.setSpacing(6)
        eng_row = QHBoxLayout()
        self.engine_group = QButtonGroup(self)
        self.engine_radios = {}
        for eng in (ENGINE_PYVISTA, ENGINE_PARAVIEW):
            rb = QRadioButton(ENGINE_LABELS[eng])
            rb.toggled.connect(lambda checked, e=eng: checked and self._on_engine_changed(e))
            self.engine_group.addButton(rb)
            self.engine_radios[eng] = rb
            eng_row.addWidget(rb)
        eng_row.addStretch()
        eng_outer.addLayout(eng_row)
        # 엔진 상태 줄 (모듈 감지 결과 / pvpython 경로)
        self.engine_status_label = QLabel("")
        set_role(self.engine_status_label, "hint")
        self.engine_status_label.setWordWrap(True)
        eng_outer.addWidget(self.engine_status_label)
        # pvpython 경로 행 — ParaView 를 고를 때만 보인다 (_on_engine_changed)
        self.pv_row_widget = QWidget()
        pv_row = QHBoxLayout(self.pv_row_widget)
        pv_row.setContentsMargins(0, 0, 0, 0)
        self.pvpython_label = QLabel("pvpython:")
        set_role(self.pvpython_label, "field")
        self.pvpython_edit = QLineEdit()
        self.pvpython_edit.setPlaceholderText("pvpython.exe 경로 (자동 탐지됨)")
        self.pv_detect_btn = QPushButton("자동 탐지")
        self.pv_detect_btn.clicked.connect(self._auto_detect_pvpython)
        self.pv_browse_btn = QPushButton("찾아보기")
        self.pv_browse_btn.clicked.connect(self._browse_pvpython)
        pv_row.addWidget(self.pvpython_label)
        pv_row.addWidget(self.pvpython_edit, 1)
        pv_row.addWidget(self.pv_detect_btn)
        pv_row.addWidget(self.pv_browse_btn)
        eng_outer.addWidget(self.pv_row_widget)
        left.addWidget(eng_group)

        # --- 2. 입력 폴더 (왼쪽) ---
        in_group = QGroupBox("2. 입력 폴더 (하위 폴더까지 재귀 탐색)")
        in_outer = QVBoxLayout(in_group)
        in_outer.setSpacing(6)
        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("CFF 파일(.cas.h5)이 있는 폴더를 선택하세요")
        folder_btn = QPushButton("폴더 선택")
        folder_btn.clicked.connect(self._browse_folder)
        self.scan_btn = QPushButton("파일 스캔")
        self.scan_btn.clicked.connect(self._scan_folder)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(folder_btn)
        folder_layout.addWidget(self.scan_btn)
        in_outer.addLayout(folder_layout)
        self.file_count_label = QLabel("폴더를 선택하고 스캔하세요")
        set_role(self.file_count_label, "hint")
        self.file_count_label.setWordWrap(True)
        in_outer.addWidget(self.file_count_label)
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(56)
        self.file_list.setMaximumHeight(120)
        self.file_list.setAlternatingRowColors(True)
        in_outer.addWidget(self.file_list, 1)
        left.addWidget(in_group, 1)

        # --- 4. 출력 설정 (왼쪽) ---
        # 생성 순서 주의: 힌트 라벨·rename_cb 는 라디오 시그널이 참조하므로 시그널 연결·setChecked 보다 먼저 만든다
        out_group = QGroupBox("4. 출력 설정")
        out_layout = QGridLayout(out_group)
        out_layout.setHorizontalSpacing(10)
        out_layout.setVerticalSpacing(6)
        out_layout.setColumnStretch(1, 1)
        out_layout.setColumnStretch(3, 1)
        fmt_label = QLabel("포맷:")
        set_role(fmt_label, "field")
        out_layout.addWidget(fmt_label, 0, 0)
        fmt_widget = QWidget()
        fmt_layout = QHBoxLayout(fmt_widget)
        fmt_layout.setContentsMargins(0, 0, 0, 0)
        self.fmt_group = QButtonGroup(self)
        self.radio_vtu = QRadioButton("VTU (체적 단일 grid)")
        self.radio_vtp = QRadioButton("VTP (외곽 표면 1장 · PyVista)")
        self.format_radios = {"vtu": self.radio_vtu, "vtp": self.radio_vtp}
        self.format_hint_label = QLabel("")
        set_role(self.format_hint_label, "hint")
        self.format_hint_label.setWordWrap(True)
        self.rename_cb = QCheckBox("Fluent 표시명으로 저장 (SV_P→pressure, SV_T→temperature …)")
        self.rename_cb.setChecked(True)
        self.rename_cb.setToolTip(
            "체크박스의 변수 이름은 Fluent 원본(SV_*)이고, 저장 시 표시명으로 바뀝니다. 매핑표: cff_common.py.\n"
            "매핑이 없는 변수(SV_RUU, *_RG_AUX …)는 원본 이름 그대로 저장됩니다.\n"
            "⚠ 이미 SV_* 이름으로 변환해 둔 세트와 한 학습에 섞지 마세요 (Stochos 설정의 배열 이름이 달라집니다).")
        for fmt, rb in self.format_radios.items():
            self.fmt_group.addButton(rb)
            fmt_layout.addWidget(rb)
            rb.toggled.connect(lambda checked, f=fmt: checked and self._on_format_changed(f))
        self.radio_vtu.setChecked(True)   # 기본값: VTU (엔진 기본값 PyVista 와 짝)
        fmt_layout.addStretch()
        out_layout.addWidget(fmt_widget, 0, 1, 1, 4)
        out_layout.addWidget(self.format_hint_label, 1, 1, 1, 4)

        prefix_label = QLabel("폴더명:")
        set_role(prefix_label, "field")
        out_layout.addWidget(prefix_label, 2, 0)
        self.folder_prefix_edit = QLineEdit()
        self.folder_prefix_edit.setText(DEFAULT_FOLDER_PREFIX)
        self.folder_prefix_edit.setPlaceholderText("예: Design → Design_001, Design_002 … (비우면 입력 파일명 기반)")
        out_layout.addWidget(self.folder_prefix_edit, 2, 1)

        mode_label = QLabel("출력 위치:")
        set_role(mode_label, "field")
        out_layout.addWidget(mode_label, 2, 2)   # 폴더명과 같은 행 (v2.0: 세로 공간 절약)
        self.output_mode = QComboBox()
        self.output_mode.addItems([
            "입력 파일과 같은 폴더",
            "지정 폴더에 모아서 저장",
        ])
        self.output_mode.currentIndexChanged.connect(self._on_output_mode_changed)
        out_layout.addWidget(self.output_mode, 2, 3, 1, 2)

        self.outdir_label = QLabel("출력 폴더:")
        set_role(self.outdir_label, "field")
        self.outdir_edit = QLineEdit()
        self.outdir_edit.setPlaceholderText("모아서 저장할 폴더 (지정 모드에서만)")
        self.outdir_btn = QPushButton("찾아보기")
        self.outdir_btn.clicked.connect(self._browse_outdir)
        out_layout.addWidget(self.outdir_label, 3, 0)
        out_layout.addWidget(self.outdir_edit, 3, 1, 1, 3)
        out_layout.addWidget(self.outdir_btn, 3, 4)

        name_label = QLabel("변수명:")
        set_role(name_label, "field")
        out_layout.addWidget(name_label, 4, 0)
        out_layout.addWidget(self.rename_cb, 4, 1, 1, 4)
        self._set_outdir_enabled(False)   # 같은 폴더 모드가 기본
        left.addWidget(out_group)

        # --- 3. 변수 선택 (오른쪽, 세로로 늘어남) ---
        var_group = QGroupBox("3. 저장할 변수 선택 (첫 파일 기준, 모든 파일에 동일 적용)")
        var_outer = QVBoxLayout(var_group)
        var_outer.setSpacing(6)
        self.load_vars_btn = QPushButton("첫 파일로 변수 불러오기")
        self.load_vars_btn.clicked.connect(self._load_variables)
        var_outer.addWidget(self.load_vars_btn)
        var_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("전체 선택")
        self.select_all_btn.clicked.connect(lambda: self._set_all_vars(True))
        self.deselect_all_btn = QPushButton("전체 해제")
        self.deselect_all_btn.clicked.connect(lambda: self._set_all_vars(False))
        var_btns.addWidget(self.select_all_btn)
        var_btns.addWidget(self.deselect_all_btn)
        var_btns.addStretch()
        var_outer.addLayout(var_btns)
        self.var_count_label = QLabel("변수를 불러오세요")
        set_role(self.var_count_label, "hint")
        self.var_count_label.setWordWrap(True)
        var_outer.addWidget(self.var_count_label)
        self.var_scroll = QScrollArea()
        self.var_scroll.setWidgetResizable(True)
        self.var_scroll.setMinimumHeight(100)
        self.var_container = QWidget()
        self.var_grid = QGridLayout(self.var_container)
        self.var_grid.setSpacing(6)
        self.var_grid.setContentsMargins(10, 10, 10, 10)
        self.var_scroll.setWidget(self.var_container)
        var_outer.addWidget(self.var_scroll, 1)
        right.addWidget(var_group, 1)

        # --- 5. 실행 · 중단 · 전체 진행 (오른쪽 아래) ---
        self.run_btn = QPushButton("변환 실행")
        set_role(self.run_btn, "primary")
        self.run_btn.setMinimumHeight(44)
        self.run_btn.clicked.connect(self._run_batch)
        self.cancel_btn = QPushButton("중단")
        set_role(self.cancel_btn, "danger")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        right.addWidget(self.run_btn)
        right.addWidget(self.cancel_btn)
        self.overall_label = QLabel("전체 진행: 대기 중")
        set_role(self.overall_label, "status")
        self.overall_label.setWordWrap(True)
        right.addWidget(self.overall_label)
        self.overall_progress = QProgressBar()
        self.overall_progress.setValue(0)
        right.addWidget(self.overall_progress)

        body.addLayout(left, 11)
        body.addLayout(right, 9)
        root.addLayout(body)

        # --- 6. 콘솔 (전폭) ---
        console_group = QGroupBox("콘솔 출력 (동일 내용이 로그 파일에 실시간 기록됨)")
        console_layout = QVBoxLayout(console_group)
        console_layout.setSpacing(6)
        log_row = QHBoxLayout()
        log_label = QLabel("로그 파일:")
        set_role(log_label, "field")
        log_row.addWidget(log_label)
        self.log_path_edit = QLineEdit()
        self.log_path_edit.setReadOnly(True)
        self.log_path_edit.setText(session_log.get_log_path() or "(세션 시작 시 생성)")
        log_row.addWidget(self.log_path_edit, 1)
        self.open_log_btn = QPushButton("로그 열기")
        self.open_log_btn.clicked.connect(self._open_log_file)
        log_row.addWidget(self.open_log_btn)
        self.open_logdir_btn = QPushButton("폴더 열기")
        self.open_logdir_btn.clicked.connect(self._open_log_dir)
        log_row.addWidget(self.open_logdir_btn)
        console_layout.addLayout(log_row)
        self.console = ConsoleEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(90)
        set_role(self.console, "console")
        console_layout.addWidget(self.console, 1)
        root.addWidget(console_group, 1)

    # --------------------------------------------------------
    # ParaView 경로
    # --------------------------------------------------------
    def _auto_detect_pvpython(self):
        path = find_pvpython()
        if path:
            self.pvpython_edit.setText(path)
            self._log("[GUI] pvpython 자동 탐지: %s" % path)
            if hasattr(self, "engine_status_label") and self.engine == ENGINE_PARAVIEW:
                self._update_engine_status_line()
        else:
            self._log("[GUI] pvpython을 찾지 못했습니다. 수동으로 지정하세요.")

    def _browse_pvpython(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "pvpython 실행 파일 선택", "",
            "실행 파일 (pvpython.exe pvpython);;모든 파일 (*)"
        )
        if path:
            self.pvpython_edit.setText(path)
            self._update_engine_status_line()

    # --------------------------------------------------------
    # 변환 엔진 선택 (결정 001 D1·D2·D5)
    # --------------------------------------------------------
    def _init_engine_selection(self):
        """시작 기본값: PyVista(+VTU). 모듈이 없으면 라디오 비활성, 폴백은 ParaView."""
        for eng, (ok, status) in self.engine_status.items():
            rb = self.engine_radios[eng]
            rb.setEnabled(ok)
            rb.setToolTip(status)
            self._log("[GUI] 엔진 %s: %s" % (ENGINE_LABELS[eng], status))
        default = ENGINE_PYVISTA if self.engine_status[ENGINE_PYVISTA][0] else ENGINE_PARAVIEW
        self.engine_radios[default].setChecked(True)
        self._on_engine_changed(default)   # 라디오가 이미 체크 상태면 toggled 가 안 올 수 있어 직접 호출

    def _on_engine_changed(self, engine):
        """엔진 라디오 변경: 포맷 라디오 갱신, pvpython 행 활성, 변수 목록 무효화."""
        prev = self.engine
        self.engine = engine
        is_pv = engine == ENGINE_PARAVIEW
        self.pv_row_widget.setVisible(is_pv)   # pvpython 경로 행은 ParaView 를 고를 때만 보인다 (v2.0)
        for w in (self.pvpython_label, self.pvpython_edit, self.pv_detect_btn, self.pv_browse_btn):
            w.setEnabled(is_pv)
        self._update_format_radios()
        self._update_engine_status_line()
        # 엔진이 바뀌면 변수 목록은 다른 엔진 것 → 비우고 다시 불러오게 한다 (impact-scan R2)
        if prev != engine and self.vars_engine is not None and self.vars_engine != engine:
            loader = getattr(self, "loader", None)
            if loader is not None and loader.isRunning():
                loader.cancel()
            self._populate_variables([])
            self.vars_engine = None
            self.vars_cell = []
            self.var_count_label.setText("엔진이 바뀌었습니다 — 변수를 다시 불러오세요")
            set_role(self.var_count_label, "warn")
            self.load_vars_btn.setEnabled(True)
            self.load_vars_btn.setText("첫 파일로 변수 불러오기")

    def _refresh_variable_list(self):
        """불러온 체적 셀 배열을 체크박스로 (체크 상태 초기화). 포맷 전환과 무관 — 로드 직후에만 호출."""
        if self.vars_engine is None:
            return
        self._populate_variables(self.vars_cell)
        self.var_count_label.setText("%d개 변수 (체적 셀 배열)" % len(self.vars_cell))
        set_role(self.var_count_label, "hint")

    def _update_engine_status_line(self):
        eng = self.engine
        if eng == ENGINE_PARAVIEW:
            pv = self.pvpython_edit.text().strip()
            txt = "pvpython: %s" % (pv if pv else "경로를 지정하세요")
        else:
            txt = self.engine_status[eng][1] + "  ·  인터프리터: %s" % python_interpreter()
        self.engine_status_label.setText(txt)

    def _allowed_formats(self):
        return ENGINE_FORMATS.get(self.engine, ("vtu",))

    def _current_format(self):
        for fmt, rb in self.format_radios.items():
            if rb.isChecked():
                return fmt
        return self._allowed_formats()[0]

    def _update_format_radios(self):
        """엔진에 맞지 않는 포맷 라디오는 비활성. 비활성인데 체크돼 있으면 엔진 기본 포맷으로 옮긴다."""
        allowed = self._allowed_formats()
        for fmt, rb in self.format_radios.items():
            rb.setEnabled(fmt in allowed)
            if fmt not in allowed:
                rb.setToolTip("%s 엔진에서는 %s 를 쓸 수 없습니다" % (ENGINE_LABELS[self.engine], fmt.upper()))
            else:
                rb.setToolTip(FORMAT_HINTS[fmt])
        cur = self._current_format()
        if cur not in allowed:
            self.format_radios[allowed[0]].setChecked(True)
            self._log("[GUI] %s 엔진은 %s 를 지원하지 않아 포맷을 %s 로 바꿨습니다." % (
                ENGINE_LABELS[self.engine], cur.upper(), allowed[0].upper()))
        self._on_format_changed(self._current_format())

    def _on_format_changed(self, fmt):
        # 포맷 전환은 체크박스를 건드리지 않는다 (사용자 선택 유지)
        self.format_hint_label.setText(FORMAT_HINTS.get(fmt, ""))

    def _set_batch_widgets_enabled(self, enabled):
        """배치 중에는 엔진·포맷·변수·변수명 선택을 잠근다 (impact-scan R1)."""
        for eng, rb in self.engine_radios.items():
            rb.setEnabled(enabled and self.engine_status.get(eng, (True, ""))[0])
        for fmt, rb in self.format_radios.items():
            rb.setEnabled(enabled and fmt in self._allowed_formats())
        for w in (self.load_vars_btn, self.select_all_btn, self.deselect_all_btn, self.rename_cb):
            w.setEnabled(enabled)

    # --------------------------------------------------------
    # 입력 폴더 + 스캔
    # --------------------------------------------------------
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "CFF 파일이 있는 폴더 선택")
        if folder:
            self.folder_edit.setText(folder)
            self._scan_folder()

    def _scan_folder(self):
        """폴더를 재귀 탐색하여 모든 .cas.h5 파일을 리스트업."""
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "경고", "올바른 폴더를 선택하세요.")
            return

        self._log("[GUI] 폴더 스캔 중 (재귀): %s" % folder)
        # 재귀 탐색: .cas.h5 파일 찾기
        cff_files = []
        for path in Path(folder).rglob("*.cas.h5"):
            if not path.is_file():
                continue
            # 워커가 만든 임시 링크 폴더(.cff_link_*_tmp) 안의 링크는 중복 변환 대상이 아니다
            if any(part.startswith(LINK_DIR_PREFIX) for part in path.parts):
                continue
            cff_files.append(str(path))
        cff_files.sort()

        self.cff_files = cff_files
        self.file_list.clear()

        if not cff_files:
            self.file_count_label.setText("⚠️  .cas.h5 파일을 찾지 못했습니다")
            set_role(self.file_count_label, "warn")
            self._log("[GUI] .cas.h5 파일이 없습니다.")
            return

        # 목록에 추가 (상대 경로로 표시)
        base = Path(folder)
        for f in cff_files:
            try:
                rel = str(Path(f).relative_to(base))
            except ValueError:
                rel = f
            item = QListWidgetItem(rel)
            self.file_list.addItem(item)

        self.file_count_label.setText("✅ %d개의 CFF 파일 발견" % len(cff_files))
        set_role(self.file_count_label, "ok")
        self._log("[GUI] %d개의 .cas.h5 파일 발견" % len(cff_files))

    # --------------------------------------------------------
    # 출력 모드
    # --------------------------------------------------------
    def _on_output_mode_changed(self, index):
        # index 1 = 지정 폴더 모드
        self._set_outdir_enabled(index == 1)

    def _set_outdir_enabled(self, enabled):
        self.outdir_label.setEnabled(enabled)
        self.outdir_edit.setEnabled(enabled)
        self.outdir_btn.setEnabled(enabled)

    def _browse_outdir(self):
        folder = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if folder:
            self.outdir_edit.setText(folder)

    # --------------------------------------------------------
    # 변수 불러오기 (첫 파일 기준)
    # --------------------------------------------------------
    def _resolve_interpreter(self):
        """현재 엔진의 (인터프리터, 워커 스크립트). 문제가 있으면 (None, 사유)."""
        if self.engine == ENGINE_PARAVIEW:
            pvpython = self.pvpython_edit.text().strip()
            if not pvpython or not os.path.exists(pvpython):
                return None, "pvpython 경로가 올바르지 않습니다. (ParaView 엔진)"
            return pvpython, WORKER_SCRIPT
        ok, status = self.engine_status.get(self.engine, (False, "알 수 없는 엔진"))
        if not ok:
            return None, "%s 엔진을 쓸 수 없습니다: %s" % (ENGINE_LABELS[self.engine], status)
        interp = python_interpreter()
        if not interp or not os.path.exists(interp):
            return None, "Python 인터프리터를 찾지 못했습니다: %s" % interp
        if not os.path.exists(CFF_WORKER_SCRIPT):
            return None, "워커 스크립트가 없습니다: %s" % CFF_WORKER_SCRIPT
        return interp, CFF_WORKER_SCRIPT

    def _load_variables(self):
        interp, worker = self._resolve_interpreter()
        if interp is None:
            QMessageBox.warning(self, "경고", worker)
            return
        if not self.cff_files:
            QMessageBox.warning(self, "경고", "먼저 폴더를 스캔하여 CFF 파일을 찾으세요.")
            return

        first_file = self.cff_files[0]
        self._log("[GUI] 첫 파일로 변수 불러오는 중 (%s): %s" % (ENGINE_LABELS[self.engine], Path(first_file).name))
        self.load_vars_btn.setEnabled(False)
        self.load_vars_btn.setText("불러오는 중...")

        self.loader = VariableLoader(interp, worker, first_file, self.engine)
        self.loader.finished_ok.connect(self._on_vars_loaded)
        self.loader.finished_err.connect(self._on_vars_error)
        self.loader.start()

    def _on_vars_loaded(self, data):
        self.load_vars_btn.setEnabled(True)
        self.load_vars_btn.setText("첫 파일로 변수 불러오기")
        if self.cff_files:
            self._cleanup_link_dirs(str(Path(self.cff_files[0]).parent))   # --list-json 워커가 남긴 임시 링크 폴더
        engine = data.get("engine", ENGINE_PARAVIEW)
        if engine != self.engine:
            # 로딩 중에 엔진이 바뀐 경우: 다른 엔진의 목록은 버린다 (impact-scan R2)
            self._log("[GUI] %s 엔진 변수 목록이 도착했지만 현재 엔진은 %s 입니다. 다시 불러오세요." % (
                ENGINE_LABELS.get(engine, engine), ENGINE_LABELS[self.engine]))
            return
        self.vars_cell = list(data.get("cell_arrays", []))
        self.vars_engine = engine
        self._refresh_variable_list()
        dat = data.get("data_file")
        if dat and data.get("data_name_matches") is False:
            self._log("[GUI] 데이터 파일 이름이 케이스와 달라 임시 링크로 읽었습니다: %s" % Path(dat).name)
        self._log("[GUI] 변수 %d개 로드 완료 (Cell Data, %s)" % (len(self.vars_cell), ENGINE_LABELS[engine]))
        if not self.vars_cell:
            # dat 는 열렸는데 셀 배열이 없는 경우 (dat 가 없으면 워커가 error JSON 으로 보내 _on_vars_error 로 간다)
            self.var_count_label.setText("변수 0개 — 데이터 파일을 확인하세요")
            set_role(self.var_count_label, "warn")
            QMessageBox.warning(self, "경고",
                                "변수를 찾지 못했습니다 (0개).\n데이터 파일(.dat.h5)이 결과를 담고 있는지 확인하세요.\n"
                                "케이스: %s" % Path(self.cff_files[0]).name if self.cff_files else "")

    def _on_vars_error(self, msg):
        self.load_vars_btn.setEnabled(True)
        self.load_vars_btn.setText("첫 파일로 변수 불러오기")
        if self.cff_files:
            self._cleanup_link_dirs(str(Path(self.cff_files[0]).parent))
        self._log("[ERROR] 변수 로딩 실패 (%s): %s" % (ENGINE_LABELS[self.engine], msg))
        QMessageBox.critical(self, "오류", "변수 로딩 실패 (%s):\n%s" % (ENGINE_LABELS[self.engine], msg))

    def _populate_variables(self, arrays):
        """체크박스 동적 생성 (2열 — 오른쪽 열 폭에 맞춤, v2.0). 선택 시 파란색 강조."""
        for cb in self.var_checkboxes:
            cb.deleteLater()
        self.var_checkboxes = []
        cols = 2
        for i, name in enumerate(arrays):
            cb = QCheckBox(name)
            cb.toggled.connect(lambda checked, c=cb: self._update_checkbox_style(c, checked))
            self._update_checkbox_style(cb, False)
            row, col = divmod(i, cols)
            self.var_grid.addWidget(cb, row, col)
            self.var_checkboxes.append(cb)
        self.var_count_label.setText("%d개 변수" % len(arrays))

    @staticmethod
    def _update_checkbox_style(checkbox, checked):
        if checked:
            checkbox.setStyleSheet("QCheckBox { color: %s; font-weight: 700; }" % COLOR_ACCENT_TEXT)
        else:
            checkbox.setStyleSheet("QCheckBox { color: %s; font-weight: 400; }" % COLOR_TEXT)

    def _set_all_vars(self, checked):
        for cb in self.var_checkboxes:
            cb.setChecked(checked)

    def _selected_variables(self):
        return [cb.text() for cb in self.var_checkboxes if cb.isChecked()]

    # --------------------------------------------------------
    # 배치 변환 실행
    # --------------------------------------------------------
    def _run_batch(self):
        engine = self.engine
        interp, worker = self._resolve_interpreter()
        selected = self._selected_variables()

        # 검증
        if interp is None:
            QMessageBox.warning(self, "경고", worker)
            return
        if not self.cff_files:
            QMessageBox.warning(self, "경고", "변환할 CFF 파일이 없습니다. 폴더를 스캔하세요.")
            return
        if not selected:
            QMessageBox.warning(self, "경고", "저장할 변수를 하나 이상 선택하세요.")
            return
        if self.vars_engine != engine:
            QMessageBox.warning(self, "경고", "변수 목록이 %s 엔진 것이 아닙니다. '첫 파일로 변수 불러오기'를 다시 실행하세요." % ENGINE_LABELS[engine])
            return
        out_format = self._current_format()
        if out_format not in ENGINE_FORMATS[engine]:
            QMessageBox.warning(self, "경고", "%s 엔진은 %s 포맷을 지원하지 않습니다. (가능: %s)" % (
                ENGINE_LABELS[engine], out_format.upper(), ", ".join(f.upper() for f in ENGINE_FORMATS[engine])))
            return
        rename = self.rename_cb.isChecked()

        # 지정 폴더 모드면 출력 폴더 확인 (없으면 생성 시도)
        if self.output_mode.currentIndex() == 1:
            outdir = self.outdir_edit.text().strip()
            if not outdir:
                QMessageBox.warning(self, "경고", "출력 폴더를 지정하세요.")
                return
            try:
                os.makedirs(outdir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(
                    self, "경고", "출력 폴더를 만들 수 없습니다:\n%s\n%s" % (outdir, e))
                return
            if not os.path.isdir(outdir):
                QMessageBox.warning(self, "경고", "출력 폴더가 올바르지 않습니다:\n%s" % outdir)
                return
            self.output_dir_override = outdir
        else:
            self.output_dir_override = ""

        # 폴더명 접두사 (미입력 시 파일명 기반으로 폴백)
        prefix = self.folder_prefix_edit.text().strip()
        # Windows 파일명 금지 문자가 접두사에 있으면 폴더 생성이 실패하므로 사전 차단
        bad_chars = set('<>:"/\\|?*')
        used_bad = [c for c in prefix if c in bad_chars]
        if used_bad:
            QMessageBox.warning(
                self, "경고",
                "폴더명 접두사에 사용할 수 없는 문자가 있습니다: %s" % " ".join(sorted(set(used_bad))))
            return
        # 드라이런: 실제 실행과 동일한 규칙으로 출력 경로를 미리 계산해
        # 디스크에 이미 존재하는 대상(덮어쓰기 대상)의 개수를 센다. (로그/self 상태 미변경)
        overwrite_count = 0
        dry_folders = set()
        for i, cf in enumerate(self.cff_files, start=1):
            try:
                out_path = self._compute_output_path(
                    cf, i, dry_folders, prefix, out_format,
                    self.output_dir_override, log=False)
            except Exception:
                continue
            if self._output_exists(out_path, out_format):
                overwrite_count += 1

        # 확인 다이얼로그 (폴더명 예시 포함)
        inner = self._inner_file_desc(out_format, engine)
        if prefix:
            example = "%s_%s" % (prefix, "1".zfill(FOLDER_NUM_WIDTH))
            dp_ex = "%s_%s" % (prefix, "016")
            naming = ("폴더명: %s, %s … (내부 파일: %s)\n"
                      "  · 파일명에 DP 번호가 있으면 그 번호 사용 (dp_016 → %s)") % (
                example, "%s_%s" % (prefix, "2".zfill(FOLDER_NUM_WIDTH)),
                inner, dp_ex)
        else:
            naming = "폴더명: 입력 파일명 기반(<파일명>%s), 내부 파일: %s" % (
                EXPORT_SUFFIX, inner)
        overwrite_line = ""
        if overwrite_count > 0:
            overwrite_line = "\n⚠ 기존 출력 %d개를 덮어씁니다." % overwrite_count
        # 데이터 파일 사전 점검: 없음 → 그 파일은 워커가 [ERROR] 로 실패. 이름 불일치 → 워커가 임시 링크로 읽음
        n_no_dat, n_linked = 0, 0
        for cf in self.cff_files:
            dat, matches = resolve_data_file(cf)
            if dat is None:
                n_no_dat += 1
            elif not matches:
                n_linked += 1
        dat_line = ""
        if n_no_dat:
            dat_line += "\n⚠ 데이터 파일(.dat.h5)이 없는 케이스 %d개 → 실패 처리됩니다" % n_no_dat
        if n_linked:
            dat_line += "\n데이터 파일 이름이 다른 케이스 %d개 (예: FFF.3-2-11200.dat.h5) → 임시 링크로 읽습니다" % n_linked
        rename_line = "\n변수명: %s" % ("Fluent 표시명 (pressure, temperature …)" if rename else "Fluent 원본 (SV_P, SV_T …)")
        reply = QMessageBox.question(
            self, "배치 변환 확인",
            "%d개 파일을 변환합니다.\n엔진: %s\n변수: %d개, 포맷: %s%s%s\n%s%s\n\n계속하시겠습니까?" % (
                len(self.cff_files), ENGINE_LABELS[engine], len(selected),
                out_format.upper(), rename_line, dat_line, naming, overwrite_line
            ),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 배치 상태 초기화 (배치 동안 쓸 값은 여기서 전부 캡처 — 중간에 위젯을 바꿔도 영향 없음)
        self.selected_vars = selected
        self.out_format = out_format
        self.batch_engine = engine
        self.batch_interpreter = interp
        self.batch_worker = worker
        self.batch_rename = rename
        self.folder_prefix = prefix
        self.batch_queue = list(self.cff_files)
        self.batch_total = len(self.batch_queue)
        self.batch_index = 0
        self.batch_success = 0
        self.batch_failed = 0
        self._batch_folders = set()

        self.run_btn.setEnabled(False)
        self.run_btn.setText("변환 중...")
        self.cancel_btn.setEnabled(True)
        self._set_batch_widgets_enabled(False)
        self.overall_progress.setMaximum(self.batch_total)
        self.overall_progress.setValue(0)

        self._log("\n" + "=" * 60)
        self._log("[GUI] 배치 변환 시작: %d개 파일, 엔진 %s, %s 포맷, 변수 %d개" % (
            self.batch_total, ENGINE_LABELS[engine], self.out_format.upper(), len(selected)))
        self._log("[GUI] 인터프리터: %s" % interp)
        self._log("[GUI] 워커: %s" % worker)
        self._log("=" * 60)

        # 첫 파일부터 처리 시작
        self._process_next()

    def _build_output_path(self, case_file, number, folders):
        """출력 경로 생성 (배치 실행용). self의 배치 설정으로 순수 계산 헬퍼를 호출.

        folders는 폴더명 충돌 감지용 집합(실행 시 self._batch_folders 전달).
        """
        return self._compute_output_path(
            case_file, number, folders,
            self.folder_prefix, self.out_format, self.output_dir_override, log=True)

    def _compute_output_path(self, case_file, number, folders,
                             prefix, out_format, output_dir_override, log=True):
        """출력 경로 순수 계산. 실제 실행과 드라이런(수정 6b)이 공유한다.

        prefix/out_format/output_dir_override를 인자로 받아 self 상태에 의존하지
        않으므로, 배치 설정이 self에 반영되기 전(드라이런)에도 안전하게 호출 가능.
        number는 변환 순서(1부터, 폴백/충돌 유일화용).

        폴더명 규칙:
        - 접두사가 있으면 <prefix>_NNN. 번호는 입력 파일명에서 DP 번호가
          자동 감지되면 그 번호(dp_016 → 016), 없으면 변환 순번을 사용.
        - 접두사가 비면 입력 파일명 기반 <base>_export.
        같은 배치 안에서 폴더명이 겹치면 순번을 붙여 유일화(덮어쓰기 방지).
        - VTU: <parent>/<folder>/Results.vtu
        - VTP: <parent>/<folder>/Results.vtp (외곽 표면 1장, PyVista)
        parent = 지정 폴더(모아서 저장) 또는 입력 파일과 같은 폴더
        (알 수 없는 포맷은 ValueError)
        """
        p = Path(case_file)
        parent = Path(output_dir_override) if output_dir_override else p.parent
        base = p.name.replace(".cas.h5", "")

        if prefix:
            m = DP_NUM_IN_NAME_RE.search(base)
            eff = int(m.group(1)) if m else number  # DP 번호 자동 감지, 없으면 순번
            folder = "%s_%s" % (prefix, str(eff).zfill(FOLDER_NUM_WIDTH))
        else:
            folder = "%s%s" % (base, EXPORT_SUFFIX)

        folder = self._unique_folder(folder, number, folders, log=log)

        if out_format == "vtu":
            return str(parent / folder / ("%s.vtu" % UNIFIED_VTU_NAME))
        elif out_format == "vtp":
            return str(parent / folder / ("%s.vtp" % UNIFIED_VTU_NAME))
        raise ValueError("지원하지 않는 포맷: %s" % out_format)

    @staticmethod
    def _output_exists(out_path, out_format):
        """덮어쓰기 판정. VTU/VTP 모두 단일 파일 (결정 002)."""
        return os.path.exists(out_path)

    @staticmethod
    def _inner_file_desc(out_format, engine):
        if out_format == "vtp":
            return "%s.vtp (외곽 전체 1장)" % UNIFIED_VTU_NAME
        return "%s.vtu" % UNIFIED_VTU_NAME

    @staticmethod
    def _target_display(out_path, out_format):
        op = Path(out_path)
        return "%s/%s" % (op.parent.name, op.name)

    def _unique_folder(self, folder, seq, folders, log=True):
        """배치 내 폴더명 충돌 시 순번을 붙여 유일화 (자동 감지로 같은 번호가 나올 때 방지).

        folders: 충돌 감지용 집합. log=False면 드라이런처럼 로그를 남기지 않음.
        """
        if folder in folders:
            new = "%s_%d" % (folder, seq)
            if log:
                self._log("    [주의] 폴더명 충돌 방지: %s → %s" % (folder, new))
            folder = new
        folders.add(folder)
        return folder

    def _process_next(self):
        """대기열에서 다음 파일을 처리."""
        if self.batch_index >= self.batch_total:
            self._batch_finished()
            return

        case_file = self.batch_queue[self.batch_index]
        n = self.batch_index + 1
        interp = self.batch_interpreter  # 배치 시작 시 캡처한 값 사용 (중간 변경 무시)

        self.overall_label.setText(
            "전체 진행: %d / %d  (성공 %d, 실패 %d)  —  현재: %s" % (
                n, self.batch_total, self.batch_success, self.batch_failed,
                Path(case_file).name))

        # 출력 경로 계산 + 폴더 생성 (실패 시 이 파일만 건너뛰고 다음으로 진행)
        try:
            output_path = self._build_output_path(case_file, n, self._batch_folders)
            self._log("\n[%d/%d] %s → %s" % (
                n, self.batch_total, Path(case_file).name,
                self._target_display(output_path, self.out_format)))
            # 출력 폴더 생성
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._log("\n[%d/%d] %s" % (n, self.batch_total, Path(case_file).name))
            self._log("    [GUI] ✗ 출력 경로 준비 실패: %s" % e)
            self.batch_failed += 1
            self.batch_index += 1
            self.overall_progress.setValue(self.batch_index)
            QTimer.singleShot(0, self._process_next)
            return

        args = [
            self.batch_worker,
            "--case", case_file,
            "--output", output_path,
            "--format", self.out_format,
            "--vars", ",".join(self.selected_vars),
        ]
        if self.batch_rename:
            args += ["--rename"]                 # 두 워커 공통 (결정 002 R1)
        # GUI 가 쓰는 인자만 보낸다: ParaView 워커에 --format vtm / --inner-name 없음, PyVista 워커에 --engine 없음
        self._current_case_dir = str(Path(case_file).parent)   # 워커 종료 뒤 임시 링크 폴더 정리용

        self._out_buf = ""
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        # 한글 로그 깨짐 방지: 워커의 stdout 인코딩을 utf-8로 강제
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.errorOccurred.connect(self._on_process_error)
        self.process.finished.connect(self._on_file_finished)
        self.process.start(interp, args)

    def _on_process_error(self, error):
        """QProcess 시작 실패(FailedToStart) 처리. 그 외 에러는 finished가 처리."""
        if error != QProcess.FailedToStart:
            return
        # finished와의 이중 처리 방지 (이미 정리되었으면 무시)
        if self.process is None:
            return
        self._log("[GUI] ✗ 프로세스 시작 실패: 인터프리터 또는 워커 스크립트를 확인하세요")
        self._log("    인터프리터: %s" % self.batch_interpreter)
        self._log("    워커: %s" % self.batch_worker)
        self.batch_failed += 1
        self.process = None
        self.batch_index += 1
        self.overall_progress.setValue(self.batch_index)
        QTimer.singleShot(0, self._process_next)

    def _on_process_output(self):
        if self.process is None:
            return
        data = self.process.readAllStandardOutput()
        text = self._out_buf + bytes(data).decode("utf-8", errors="replace")
        # 청크 경계에서 잘린 마지막 줄은 다음 readyRead 까지 보관 (마커가 반으로 갈리는 것 방지)
        lines = text.split("\n")
        self._out_buf = lines.pop()
        self._emit_worker_lines(lines)

    def _emit_worker_lines(self, lines):
        for line in lines:
            line = line.rstrip()
            if not line:
                continue
            # 진행률 마커는 무시 (배치에서는 전체 진행률 사용)
            if line.startswith("[PROGRESS]"):
                continue
            elif line == "[SUCCESS]":
                continue
            else:
                # 워커 로그는 들여쓰기해서 표시
                self._log("    " + line)

    def _cleanup_link_dirs(self, folder):
        """워커 프로세스가 끝난 뒤 케이스 폴더의 임시 링크 폴더(.cff_link_*_tmp) 삭제.
        워커 안에서는 첫 CFF 리더가 HDF5 핸들을 종료까지 잡고 있어 못 지운다(실측) → 프로세스 종료 후 GUI 가 지운다."""
        if not folder:
            return
        try:
            # 중단 직후엔 자식 인터프리터가 핸들을 놓는 데 잠깐 걸린다 → 최대 3초 재시도
            n = remove_stale_link_dirs(folder, log=self._log, min_age_sec=0, retries=10, delay=0.3)
            if n:
                self._log("    [GUI] 임시 링크 폴더 %d개 정리" % n)
        except Exception as e:
            self._log("    [GUI] 임시 링크 폴더 정리 실패: %s" % str(e)[:60])

    def _on_file_finished(self, exit_code, exit_status):
        # 남은 미완성 줄 비우기
        if self._out_buf.strip():
            self._emit_worker_lines([self._out_buf])
        self._out_buf = ""
        self._cleanup_link_dirs(self._current_case_dir)
        if exit_status == QProcess.CrashExit:
            # 강제 종료·크래시: exit_code 와 무관하게 실패로 센다
            self.batch_failed += 1
            self._log("    [GUI] ✗ 실패 (워커가 비정상 종료됨)")
        elif exit_code == 0:
            self.batch_success += 1
            self._log("    [GUI] ✓ 완료")
        else:
            self.batch_failed += 1
            self._log("    [GUI] ✗ 실패 (exit code: %d)" % exit_code)

        self.process = None
        self.batch_index += 1
        self.overall_progress.setValue(self.batch_index)

        # 다음 파일 처리 (이벤트 루프에 양보)
        QTimer.singleShot(0, self._process_next)

    def _batch_finished(self):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("변환 실행")
        self.cancel_btn.setEnabled(False)
        self._set_batch_widgets_enabled(True)
        self.overall_label.setText(
            "완료: 총 %d개  (성공 %d, 실패 %d)" % (
                self.batch_total, self.batch_success, self.batch_failed))
        self._log("\n" + "=" * 60)
        self._log("[GUI] 배치 변환 완료: 성공 %d / 실패 %d (총 %d)" % (
            self.batch_success, self.batch_failed, self.batch_total))
        self._log("=" * 60)
        QMessageBox.information(
            self, "배치 완료",
            "변환 완료!\n\n총 %d개\n성공: %d개\n실패: %d개" % (
                self.batch_total, self.batch_success, self.batch_failed))

    def _cancel_batch(self):
        """배치 처리 중단."""
        reply = QMessageBox.question(
            self, "중단 확인", "배치 변환을 중단하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 확인창을 띄운 사이 배치가 이미 끝났으면 완료 상태를 '중단됨'으로 덮지 않음
        if self.process is None and self.batch_index >= self.batch_total:
            self._log("[GUI] 배치가 이미 완료되어 중단할 것이 없습니다.")
            return
        # 진행 중인 프로세스 종료 (venv 런처 python.exe 는 자식 인터프리터를 Job 으로 묶고 있어 함께 죽는다 — 실측)
        if self.process is not None:
            self.process.finished.disconnect()
            self.process.kill()
            self.process.waitForFinished(3000)
            self.process = None
            self._out_buf = ""
            self._cleanup_link_dirs(self._current_case_dir)
        # 대기열 비우기
        self.batch_index = self.batch_total
        self.run_btn.setEnabled(True)
        self.run_btn.setText("변환 실행")
        self.cancel_btn.setEnabled(False)
        self._set_batch_widgets_enabled(True)
        self._log("\n[GUI] 사용자가 배치 변환을 중단했습니다.")
        self.overall_label.setText("중단됨 (성공 %d, 실패 %d)" % (
            self.batch_success, self.batch_failed))

    # --------------------------------------------------------
    # 콘솔 로그
    # --------------------------------------------------------
    def _log(self, msg):
        append_log(self.console, msg)
        session_log.write(msg, tag="변환")

    def _open_log_file(self):
        path = session_log.get_log_path()
        if path and os.path.isfile(path):
            self._open_path(path)
        else:
            QMessageBox.information(self, "로그", "로그 파일이 아직 없습니다.")

    def _open_log_dir(self):
        path = session_log.get_log_path()
        target = os.path.dirname(path) if path else None
        if target and os.path.isdir(target):
            self._open_path(target)
        else:
            QMessageBox.information(self, "로그", "로그 폴더가 아직 없습니다.")

    @staticmethod
    def _open_path(path):
        try:
            os.startfile(path)  # Windows
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    # --------------------------------------------------------
    # 종료 정리 (앱 종료 시 백그라운드 작업 안전 중단)
    # --------------------------------------------------------
    def shutdown(self):
        """실행 중인 로더 스레드와 변환 프로세스를 정리. 예외는 전부 무시."""
        loader = getattr(self, "loader", None)
        if loader is not None:
            try:
                if loader.isRunning():
                    loader.cancel()
                    loader.wait(3000)
            except Exception:
                pass
        if self.process is not None:
            try:
                self.process.finished.disconnect()
            except Exception:
                pass
            try:
                self.process.kill()
                self.process.waitForFinished(2000)
            except Exception:
                pass
            try:
                remove_stale_link_dirs(self._current_case_dir, min_age_sec=0)
            except Exception:
                pass


# ============================================================
# JSON 생성기 탭 (boundary_conditions.json, Stochos DIM-GP)
# ============================================================
class BCJsonTab(QWidget):
    """JSON 생성기 탭 (v2.0 개명, 구 "boundary_conditions.json"): 설계 테이블 CSV → 설계 폴더별 boundary_conditions.json.
    동기 실행(스레드·프로세스 없음). CSV 형식은 bc_json_gen.CSV_FORMAT_HELP (Parameters.csv 형식, 열 이름 = JSON 키).
    v2.0: 파라미터 매핑은 선택(비우면 CSV 열 그대로), 누락 기준설계 직접 입력 UI 제거, 예시 CSV 저장·작성 방법 버튼 추가.

    start_dir_provider: 설계 폴더 루트 찾아보기의 시작 폴더를 주는 콜백 (변환 탭의 출력 폴더).
    """
    def __init__(self, start_dir_provider=None):
        super().__init__()
        self._start_dir_provider = start_dir_provider
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)
        head = QHBoxLayout()
        title = QLabel("JSON 생성기")
        set_role(title, "title")
        subtitle = QLabel("설계 테이블 CSV(Parameters.csv 형식) → 설계 폴더(Design_NNN)마다 boundary_conditions.json 생성 (Stochos DIM-GP 학습용)")
        set_role(subtitle, "subtitle")
        subtitle.setWordWrap(True)
        head.addWidget(title)
        head.addSpacing(14)
        head.addWidget(subtitle, 1)
        root.addLayout(head)

        # --- CSV 작성 방법 (초보자용 안내 + 예시 파일) ---
        help_group = QGroupBox("1. 설계 테이블 CSV 준비")
        hl = QVBoxLayout(help_group)
        hl.setSpacing(6)
        help_label = QLabel(
            "첫 행은 열 이름, 첫 열은 설계 번호(열 이름 Name 또는 #, 값 DP 0 / DP 1 … 또는 0 / 1 …), 나머지 열은 파라미터입니다. "
            "열 이름이 그대로 JSON 키가 되고 열 순서가 키 순서가 됩니다. 값은 숫자만. "
            "예: Name,inlet_length,cone_length,vortex_finder_length / DP 0,150,0.36,280")
        set_role(help_label, "hint")
        help_label.setWordWrap(True)
        hl.addWidget(help_label)
        help_btns = QHBoxLayout()
        self.bc_help_btn = QPushButton("작성 방법 자세히")
        self.bc_help_btn.clicked.connect(self._show_csv_help)
        self.bc_example_btn = QPushButton("예시 CSV 저장…")
        self.bc_example_btn.setToolTip("Parameters_example.csv 를 저장합니다. 엑셀로 열어 설계 번호와 값을 채운 뒤 아래 '설계 테이블 CSV' 에 지정하세요.")
        self.bc_example_btn.clicked.connect(self._save_example_csv)
        help_btns.addWidget(self.bc_help_btn)
        help_btns.addWidget(self.bc_example_btn)
        help_btns.addStretch()
        hl.addLayout(help_btns)
        root.addWidget(help_group)

        bc_group = QGroupBox("2. 설정")
        g = QGridLayout(bc_group)

        # 설계 테이블 CSV
        g.addWidget(QLabel("설계 테이블 CSV:"), 0, 0)
        self.bc_csv_edit = QLineEdit()
        self.bc_csv_edit.setPlaceholderText("설계 테이블 CSV (예: Parameters.csv — 구분자·설계 열 자동 감지)")
        bc_csv_btn = QPushButton("찾아보기")
        bc_csv_btn.clicked.connect(self._browse_bc_csv)
        g.addWidget(self.bc_csv_edit, 0, 1)
        g.addWidget(bc_csv_btn, 0, 2)

        # 설계 폴더 루트
        g.addWidget(QLabel("설계 폴더 루트:"), 1, 0)
        self.bc_root_edit = QLineEdit()
        self.bc_root_edit.setPlaceholderText(
            "설계 폴더(Design_001 등)들의 부모 폴더 — 보통 변환 출력 폴더")
        bc_root_btn = QPushButton("찾아보기")
        bc_root_btn.clicked.connect(self._browse_bc_root)
        g.addWidget(self.bc_root_edit, 1, 1)
        g.addWidget(bc_root_btn, 1, 2)

        # 옵션: 설계번호 열 / 오프셋 / 사이드카
        opt_widget = QWidget()
        opt = QHBoxLayout(opt_widget); opt.setContentsMargins(0, 0, 0, 0)
        opt.addWidget(QLabel("JSON 파일명:"))
        self.bc_json_name_edit = QLineEdit(bc_json_gen.DEFAULT_JSON_NAME)
        _f = QFont(); _f.setPointSizeF(BASE_FONT_PT)   # 테마 글자 크기에서 기본 파일명이 다 보이는 폭 (QSS 글꼴은 아직 적용 전이라 직접 계산)
        self.bc_json_name_edit.setFixedWidth(QFontMetrics(_f).horizontalAdvance(bc_json_gen.DEFAULT_JSON_NAME) + 40)
        self.bc_json_name_edit.setToolTip(
            "기본 %s. Stochos 학습 파이프라인은 이 이름을 고정으로 읽으므로 바꾸면 그쪽 설정도 맞춰야 합니다." % bc_json_gen.DEFAULT_JSON_NAME)
        opt.addWidget(self.bc_json_name_edit)
        opt.addSpacing(12)
        opt.addWidget(QLabel("설계번호 열:"))
        self.bc_designcol_edit = QLineEdit(bc_json_gen.DEFAULT_DESIGN_COL_HINT)
        self.bc_designcol_edit.setFixedWidth(QFontMetrics(_f).horizontalAdvance("WWWW") + 24)
        opt.addWidget(self.bc_designcol_edit)
        opt.addSpacing(12)
        opt.addWidget(QLabel("구분자:"))
        self.bc_delim_combo = QComboBox()
        self.bc_delim_combo.addItem("자동 감지", "auto")
        self.bc_delim_combo.addItem("탭 (\\t)", "\t")
        self.bc_delim_combo.addItem("세미콜론 (;)", ";")
        self.bc_delim_combo.addItem("콤마 (,)", ",")
        self.bc_delim_combo.setToolTip(
            "자동 감지 실패 시(헤더에서 구분자를 찾지 못함) 직접 지정하세요.")
        opt.addWidget(self.bc_delim_combo)
        opt.addSpacing(12)
        opt.addWidget(QLabel("오프셋:"))
        self.bc_offset_spin = QSpinBox()
        self.bc_offset_spin.setRange(-100000, 100000)
        self.bc_offset_spin.setValue(0)
        opt.addWidget(self.bc_offset_spin)
        opt.addSpacing(12)
        self.bc_sidecar_cb = QCheckBox("design_info.json 사이드카 생성")
        self.bc_sidecar_cb.setChecked(True)
        opt.addWidget(self.bc_sidecar_cb)
        opt.addStretch()
        g.addWidget(QLabel("옵션:"), 2, 0)
        g.addWidget(opt_widget, 2, 1, 1, 2)

        # 파라미터 매핑 (순서 = X_global_feat 열 순서)
        params_label = QLabel("파라미터 매핑 (선택):")
        params_label.setToolTip("비워 두면 설계번호 열을 뺀 모든 CSV 열을 그 순서대로 JSON 키로 씁니다.")
        g.addWidget(params_label, 3, 0)
        self.bc_params_edit = QPlainTextEdit()
        self.bc_params_edit.setPlaceholderText(
            "비워 두면 CSV 열 이름을 그대로 JSON 키로 씁니다 (설계번호 열 제외, CSV 열 순서).\n"
            "열 이름과 다른 키를 쓰거나 일부 열만 내보낼 때만 한 줄에 하나:  json_key = CSV열   (위→아래 순서 = X_global_feat 열 순서)")
        self.bc_params_edit.setPlainText("")
        self.bc_params_edit.setFixedHeight(88)
        cf = QFont("Consolas"); cf.setStyleHint(QFont.Monospace)
        self.bc_params_edit.setFont(cf)
        set_role(self.bc_params_edit, "mono")
        g.addWidget(self.bc_params_edit, 3, 1, 1, 2)

        # 실행 버튼 (미리보기 → 생성)
        btns = QWidget(); b = QHBoxLayout(btns); b.setContentsMargins(0, 0, 0, 0)
        self.bc_preview_btn = QPushButton("미리보기 (DRY-RUN)")
        self.bc_preview_btn.clicked.connect(lambda: self._run_bc_generation(True))
        self.bc_generate_btn = QPushButton("JSON 생성")
        self.bc_generate_btn.clicked.connect(lambda: self._run_bc_generation(False))
        b.addWidget(self.bc_preview_btn)
        b.addWidget(self.bc_generate_btn)
        b.addStretch()
        g.addWidget(btns, 6, 0, 1, 3)

        root.addWidget(bc_group)

        # 콘솔 (DP 정리 탭과 같은 관례: 탭 자체 콘솔 + 세션 로그 태그)
        console_group = QGroupBox("콘솔 출력 (동일 내용이 로그 파일에 실시간 기록됨)")
        console_layout = QVBoxLayout(console_group)
        self.console = ConsoleEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(90)
        set_role(self.console, "console")
        console_layout.addWidget(self.console)
        root.addWidget(console_group, 1)

    def _log(self, msg):
        append_log(self.console, msg)
        session_log.write(msg, tag="BC-JSON")

    def _json_name(self):
        return self.bc_json_name_edit.text().strip() or bc_json_gen.DEFAULT_JSON_NAME

    def shutdown(self):
        """동기 실행이라 정리할 백그라운드 작업이 없다."""
        return

    def _show_csv_help(self):
        box = QMessageBox(self)
        box.setWindowTitle("설계 테이블 CSV 작성 방법")
        box.setIcon(QMessageBox.Information)
        box.setText(bc_json_gen.CSV_FORMAT_HELP)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.exec()

    def _save_example_csv(self):
        start = ""
        cur = self.bc_csv_edit.text().strip()
        if cur:
            start = os.path.dirname(cur)
        elif self._start_dir_provider:
            start = self._start_dir_provider() or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "예시 CSV 저장", os.path.join(start, bc_json_gen.EXAMPLE_CSV_NAME), "CSV 파일 (*.csv)")
        if not path:
            return
        try:
            bc_json_gen.write_example_csv(path)
        except OSError as e:
            QMessageBox.critical(self, "저장 실패", str(e))
            return
        self._log("[BC-JSON] 예시 CSV 저장: %s" % path)
        QMessageBox.information(
            self, "예시 CSV 저장",
            "%s\n\n엑셀에서 열어 설계 번호(DP 0, DP 1 …)와 파라미터 값을 채운 뒤 'CSV UTF-8' 로 저장하고,\n"
            "'설계 테이블 CSV' 에 그 파일을 지정하세요. 열 이름이 그대로 JSON 키가 됩니다." % path)

    def _browse_bc_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "설계 테이블 CSV 선택", "", "CSV 파일 (*.csv);;모든 파일 (*)")
        if path:
            self.bc_csv_edit.setText(path)

    def _browse_bc_root(self):
        start = self._start_dir_provider() if self._start_dir_provider else ""
        folder = QFileDialog.getExistingDirectory(self, "설계 폴더 루트 선택", start)
        if folder:
            self.bc_root_edit.setText(folder)

    def _parse_bc_params(self):
        """파라미터 매핑 텍스트 → 순서 보존 dict. 형식 오류 시 ValueError."""
        params = {}
        for lineno, raw in enumerate(self.bc_params_edit.toPlainText().splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("%d번째 줄 형식 오류('json_key = CSV열' 필요): %s" % (lineno, raw))
            key, col = line.split("=", 1)
            key, col = key.strip(), col.strip()
            if not key or not col:
                raise ValueError("%d번째 줄에 빈 값이 있습니다: %s" % (lineno, raw))
            if key in params:
                raise ValueError("중복된 json_key: %s" % key)
            params[key] = col
        return params   # 비어 있으면 자동 모드 (bc_json_gen 이 CSV 열을 그대로 키로 씀)

    def _run_bc_generation(self, dry_run):
        csv_path = self.bc_csv_edit.text().strip()
        root_dir = self.bc_root_edit.text().strip()
        if not csv_path or not os.path.isfile(csv_path):
            QMessageBox.warning(self, "경고", "올바른 설계 테이블 CSV를 선택하세요.")
            return
        if not root_dir or not os.path.isdir(root_dir):
            QMessageBox.warning(self, "경고", "올바른 설계 폴더 루트를 선택하세요.")
            return
        try:
            param_cols = self._parse_bc_params()
        except ValueError as e:
            QMessageBox.warning(self, "경고", "파라미터 매핑 오류:\n%s" % e)
            return

        json_name = self._json_name()
        bad = [c for c in json_name if c in '<>:"/\\|?*']
        if bad or not json_name.lower().endswith(".json"):
            QMessageBox.warning(self, "경고", "JSON 파일명이 올바르지 않습니다 (확장자 .json, 금지 문자 제외): %s" % json_name)
            return
        name_note = ""
        if json_name != bc_json_gen.DEFAULT_JSON_NAME:
            name_note = "\n⚠ 기본 이름(%s)이 아닙니다. Stochos 쪽 읽기 설정도 같은 이름으로 맞추세요." % bc_json_gen.DEFAULT_JSON_NAME
        if not dry_run:
            reply = QMessageBox.question(
                self, "JSON 생성 확인",
                "설계 폴더에 %s%s을 생성합니다.\n"
                "기존 파일은 덮어써집니다.%s\n\n계속하시겠습니까?" % (
                    json_name,
                    " + design_info.json" if self.bc_sidecar_cb.isChecked() else "", name_note),
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        cfg = bc_json_gen.BCGenConfig(
            csv_path=csv_path,
            data_roots=[root_dir],
            delimiter=self.bc_delim_combo.currentData(),
            design_col_hint=(self.bc_designcol_edit.text().strip()
                             or bc_json_gen.DEFAULT_DESIGN_COL_HINT),
            design_number_offset=self.bc_offset_spin.value(),
            param_cols=param_cols,
            sidecar_name=(bc_json_gen.DEFAULT_SIDECAR_NAME
                          if self.bc_sidecar_cb.isChecked() else None),
            dry_run=dry_run,
            json_name=json_name,
        )

        self._log("\n" + "=" * 60)
        self._log("[BC-JSON] %s 시작" % ("미리보기(DRY-RUN)" if dry_run else "생성"))
        self._log("=" * 60)
        if not param_cols:
            self._log("    파라미터 매핑 없음 → CSV 의 열 이름을 그대로 JSON 키로 씁니다 (설계번호 열 제외)")

        # bc_json_gen 모듈 로그를 콘솔로 브리지
        logger = logging.getLogger("bc_json_gen")
        handler = _QtLogHandler(lambda m: self._log("    " + m))
        handler.setLevel(logging.INFO)
        prev_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        self.bc_preview_btn.setEnabled(False)
        self.bc_generate_btn.setEnabled(False)
        report = None
        try:
            report = bc_json_gen.generate_bc_jsons(cfg)
        except bc_json_gen.BCGenError as e:
            self._log("    [오류] %s" % e)
            QMessageBox.critical(self, "BC-JSON 오류", str(e))
        except Exception as e:
            self._log("    [예외] %r" % e)
            QMessageBox.critical(self, "BC-JSON 오류", repr(e))
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev_level)
            self.bc_preview_btn.setEnabled(True)
            self.bc_generate_btn.setEnabled(True)
        if report is None:
            return

        for line in bc_json_gen.report_to_lines(report):
            self._log("    " + line)
        for pv in report.previews:
            self._log("    예) " + pv)

        action = "미리보기" if dry_run else "생성 완료"
        summary = ("%s %s\n\n"
                   "생성 대상: %d개\n"
                   "폴더 없음(CSV에만): %d개\n"
                   "CSV 없음(폴더에만): %d개\n"
                   "값 변환 실패: %d개\n"
                   "쓰기 실패: %d개\n"
                   "키 순서 일관성: %s\n"
                   "구분자: %r") % (
            json_name, action, len(report.written), len(report.no_folder),
            len(report.folder_only), len(report.bad_value),
            len(report.write_failed),
            "통과" if report.key_order_ok else "불일치", report.delimiter)
        if report.matched_columns:
            summary += "\nJSON 키 (%s): %s" % ("CSV 열 그대로" if report.auto_params else "매핑", ", ".join(report.matched_columns))
        if dry_run and report.written:
            summary += "\n\n※ DRY-RUN이라 파일은 생성되지 않았습니다. [JSON 생성]으로 실제 생성하세요."
        if report.write_failed:
            # 일부 폴더만 JSON 생성 → 학습 루트에 키집합 불일치 위험. 반드시 경고로 노출.
            summary += ("\n\n⚠ 일부 폴더 쓰기에 실패해 데이터셋이 부분 생성되었습니다.\n"
                        "학습 전 콘솔 로그의 '쓰기 실패' 목록을 확인하고 재생성하세요.")
            QMessageBox.warning(self, action + " (부분 생성)", summary)
        else:
            QMessageBox.information(self, action, summary)


# ============================================================
# PyFluent 변환기 탭 (결정 004) — 라이브 Fluent 솔버 세션으로 VTU/VTP
# ============================================================
PYFLUENT_WORKER_SCRIPT = str(Path(__file__).parent / "pyfluent_export_worker.py")
PYFLUENT_ENGINE = "pyfluent"          # --list-json 응답의 engine 키 값 (변환기 탭 엔진 라디오와 무관)
PYFLUENT_FORMAT_HINTS = {
    "vtu": "VTU: 셀 존 격자를 재구성한 체적 grid → Design_NNN/Results.vtu (Cell Data, SV_* 또는 표시명)",
    "vtp": "VTP: 경계 면 존(interior 제외) 병합 1장 → Design_NNN/Results.vtp (cell data boundary_id 로 경계 구분)",
}
PYFLUENT_LOAD_TIMEOUT_SEC = 600      # Fluent 기동(30–45 s) + 케이스 읽기(10–40 s) 여유
PYFLUENT_CANCEL_WAIT_MS = 30000      # CANCEL 송신 뒤 워커가 Fluent 를 닫고 끝나길 기다리는 시간. 넘기면 kill + taskkill
FLUENT_PID_RE = re.compile(r"^\[FLUENT_PID\]\s+fluent=(\d+)\s+cortex=(\d+)")
# jobs 모드(결정 005): 워커가 케이스 경계를 알려 주는 줄. GUI 는 이것으로 성공/실패를 집계한다 (종료코드는 보조)
FILE_START_RE = re.compile(r"^\[FILE_START\]\s+(\d+)/(\d+)\s+(.*)$")
FILE_DONE_RE = re.compile(r"^\[FILE_DONE\]\s+(\d+)/(\d+)\s+(ok|fail)(?:\s+(.*))?$")
WORKDIR_RE = re.compile(r"^\[WORKDIR\]\s+(.*)$")          # 워커의 임시 작업 폴더. 워커가 끝난 뒤 GUI 가 (잠금이 풀리면) 지운다
WORKDIR_SWEEP_MS = 60000


def remove_dir_quiet(path):
    """폴더 삭제 시도. 성공 또는 이미 없으면 True, 잠겨 있으면 False."""
    try:
        if not os.path.isdir(path):
            return True
        shutil.rmtree(path)
        return True
    except OSError:
        return False


def detect_pyfluent():
    """ansys-fluent-core 모듈과 Fluent 설치(AWP_ROOTnnn)를 가볍게 확인. 반환 (사용 가능, 상태 문구)."""
    import importlib.util
    try:
        from importlib.metadata import version as _ver
        pf_ver = _ver("ansys-fluent-core")
    except Exception:
        pf_ver = None
    if importlib.util.find_spec("ansys.fluent.core") is None:
        return False, "ansys-fluent-core 없음 → pip install ansys-fluent-core"
    roots = sorted((k for k in os.environ if re.fullmatch(r"AWP_ROOT\d{3}", k)), reverse=True)
    if roots:
        fl = "Fluent %s (%s)" % (", ".join("v" + r[-3:] for r in roots), os.environ.get(roots[0], ""))
    else:
        fl = "Fluent 설치를 찾지 못함 (AWP_ROOTnnn 환경변수 없음 — 기동이 실패할 수 있음)"
    return True, "ansys-fluent-core %s 감지됨 · %s" % (pf_ver or "?", fl)


def kill_fluent_pids(pids, log=None):
    """워커가 알려준 Fluent pid(cortex, fluent host)를 트리째 강제 종료. 이미 없는 pid 는 조용히 넘어간다.
    실측(docs/probe/pyfluent-live.md §4): 워커를 kill 해도 Fluent 8개 프로세스는 남는다 → GUI 가 직접 정리한다."""
    import subprocess
    import time as _time
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def alive(pid):
        try:
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH"], capture_output=True, text=True,
                               creationflags=flags, timeout=15)
            return str(pid) in r.stdout
        except Exception:
            return False

    killed = []
    for pid in pids or []:
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
                               creationflags=flags, timeout=30)
            if r.returncode == 0:
                killed.append(pid)
        except Exception:
            pass
    # 종료 중인 프로세스에 taskkill 이 먹지 않는 경우가 있어(실측: 로더 shutdown 뒤 12초 생존) 사라질 때까지 잠시 확인하고 한 번 더 시도한다
    for _ in range(16):
        left = [pid for pid in (pids or []) if alive(pid)]
        if not left:
            break
        _time.sleep(0.5)
        for pid in left:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
                               creationflags=flags, timeout=30)
            except Exception:
                pass
    if killed and log:
        log("    [GUI] Fluent 프로세스 강제 종료: pid %s" % ", ".join(str(p) for p in killed))
    return killed


class PyFluentVariableLoader(VariableLoader):
    """--list-json 로더의 PyFluent 판. Fluent 를 띄우므로 오래 걸리고, 취소는 stdin CANCEL → kill → taskkill 순."""
    LOAD_TIMEOUT_SEC = PYFLUENT_LOAD_TIMEOUT_SEC

    def __init__(self, interpreter, worker_script, case_file):
        super().__init__(interpreter, worker_script, case_file, PYFLUENT_ENGINE)
        self.fluent_pids = []
        self.workdir = ""

    def run(self):
        import subprocess
        import threading
        try:
            cmd = [self.interpreter, self.worker_script, "--case", self.case_file, "--list-json"]
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            timed_out = {"v": False}

            def _timeout():
                timed_out["v"] = True
                self._terminate()
            timer = threading.Timer(self.LOAD_TIMEOUT_SEC, _timeout)
            timer.daemon = True
            timer.start()
            chunks = []
            for line in self.proc.stdout:          # 줄 단위로 읽어 [FLUENT_PID] 를 바로 기억한다
                chunks.append(line)
                m = FLUENT_PID_RE.match(line)
                if m:
                    self.fluent_pids = [int(m.group(2)), int(m.group(1))]   # cortex 먼저 (트리 루트)
                m = WORKDIR_RE.match(line)
                if m:
                    self.workdir = m.group(1).strip()
            self.proc.wait()
            timer.cancel()
            out = "".join(chunks)
            if self._cancelled:
                return
            if timed_out["v"]:
                self.finished_err.emit("시간 초과 (%d초). Fluent 기동 또는 케이스 읽기가 끝나지 않았습니다." % self.LOAD_TIMEOUT_SEC)
                return
            if "###JSON_START###" in out and "###JSON_END###" in out:
                json_str = out.split("###JSON_START###")[1].split("###JSON_END###")[0].strip()
                data = json.loads(json_str)
                if "error" in data:
                    self.finished_err.emit(data["error"])
                else:
                    data.setdefault("engine", self.engine)
                    self.finished_ok.emit(data)
            else:
                self.finished_err.emit("변수 목록 파싱 실패.\n출력:\n" + out[-800:])
        except Exception as e:
            if not self._cancelled:
                self.finished_err.emit(repr(e))

    def _terminate(self):
        """CANCEL → 최대 20초 대기 → kill → Fluent pid 정리(소멸 확인). 로더 스레드/타이머/GUI 스레드 어디서 불려도 안전."""
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.write("CANCEL\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(20)          # 워커는 Fluent 가 실제로 내려간 뒤에야 끝난다 (최대 ~20 s). 그 안에 안 끝나면 강제
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        kill_fluent_pids(self.fluent_pids)   # 보통 이미 없다. 남아 있으면 taskkill + 소멸 확인

    def cancel(self):
        self._cancelled = True
        self._terminate()


class PyFluentTab(QWidget):
    """PyFluent(라이브 Fluent 솔버) 로 VTU/VTP 변환. 변환기 탭과 같은 폴더 규칙·프로토콜을 쓰되 엔진은 Fluent 하나.

    변환기 탭(ConverterTab)의 순수 헬퍼는 그대로 빌려 쓴다 (출력 경로·스캔·체크박스·출력 모드).
    다른 점: Fluent 를 띄우므로 (1) 변수 로딩에 1–2분, (2) 중단은 stdin CANCEL → 워커가 Fluent 를 닫음 →
    30 s 안에 안 끝나면 kill + taskkill(pid 는 워커의 [FLUENT_PID] 줄), (3) 포맷(VTU/VTP)에 따라 변수 목록이 다르다,
    (4) 배치는 워커 **1개**가 `--jobs` 목록을 받아 Fluent 를 한 번만 띄우고 케이스를 차례로 처리한다 (결정 005).
        GUI 는 `[FILE_START] i/n` / `[FILE_DONE] i/n ok|fail` 줄로 집계하고, 워커가 먼저 끝나면 남은 케이스를 실패로 센다.
    """
    # ConverterTab 의 self 비의존 헬퍼 재사용 (impact-scan 권고: 추출 대신 빌려 쓰기 — 변환기 탭 불변)
    _scan_folder = ConverterTab._scan_folder
    _browse_folder = ConverterTab._browse_folder
    _on_output_mode_changed = ConverterTab._on_output_mode_changed
    _set_outdir_enabled = ConverterTab._set_outdir_enabled
    _browse_outdir = ConverterTab._browse_outdir
    _populate_variables = ConverterTab._populate_variables
    _set_all_vars = ConverterTab._set_all_vars
    _selected_variables = ConverterTab._selected_variables
    _compute_output_path = ConverterTab._compute_output_path
    _unique_folder = ConverterTab._unique_folder
    _on_process_output = ConverterTab._on_process_output
    _open_log_file = ConverterTab._open_log_file
    _open_log_dir = ConverterTab._open_log_dir
    # staticmethod 는 클래스에서 꺼내면 맨 함수가 되므로 다시 staticmethod 로 감싼다 (안 그러면 self 가 끼어든다)
    _update_checkbox_style = staticmethod(ConverterTab._update_checkbox_style)
    _output_exists = staticmethod(ConverterTab._output_exists)
    _target_display = staticmethod(ConverterTab._target_display)
    _open_path = staticmethod(ConverterTab._open_path)

    def __init__(self):
        super().__init__()
        self.var_checkboxes = []
        self.cff_files = []
        self.process = None
        self.loader = None
        self.batch_queue = []
        self.batch_index = 0
        self.batch_total = 0
        self.batch_success = 0
        self.batch_failed = 0
        self.selected_vars = []
        self.out_format = "vtu"
        self.batch_rename = True
        self.batch_interpreter = ""
        self.batch_worker = ""
        self.batch_processors = 1
        self.output_dir_override = ""
        self.folder_prefix = ""
        self._batch_folders = set()
        self._out_buf = ""
        self._fluent_pids = []          # 현재 워커가 알려준 [cortex, fluent] pid
        self._cancelling = False
        self._jobs = {}                 # index → {case, output, format} (배치 시작 때 선계산)
        self._jobs_file = ""            # 워커에 넘긴 jobs JSON (배치가 끝나면 삭제)
        self._workdir = ""              # 현재 배치 워커의 임시 폴더 ([WORKDIR] 줄)
        self._pending_workdirs = []     # 끝난 워커·로더의 임시 폴더 중 아직 못 지운 것 (잠금 해제 뒤 재시도)
        self.vars_loaded = False
        self.vars_cell = []             # --list-json cell_arrays (VTU 용)
        self.vars_face = []             # --list-json face_arrays (VTP 용)
        self.boundaries = []            # [{name, zone_id, n_faces}]
        self.pyfluent_ok, self.pyfluent_status = detect_pyfluent()
        self._build_ui()
        self._log("[GUI] PyFluent: %s" % self.pyfluent_status)
        self._log("[GUI] 인터프리터: %s" % python_interpreter())

    # --------------------------------------------------------
    def _build_ui(self):
        """2단 레이아웃 (v2.0, 수정사항-01.pptx 슬라이드 3): 왼쪽 = 1.Fluent 환경 · 2.입력 폴더 · 4.출력 설정,
        오른쪽 = 3.변수 선택(세로로 늘어남) · 실행 · 중단 · 진행바, 아래 전폭 = 콘솔. 위젯 속성명은 바꾸지 않는다 (ConverterTab 의 메서드를 빌려 쓰고 헤드리스 시험이 참조)."""
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 12, 14, 12)

        head = QHBoxLayout()
        title = QLabel("PyFluent 변환기")
        set_role(title, "title")
        subtitle = QLabel("Fluent 솔버 세션(PyFluent)으로 CFF → VTU(체적) / VTP(경계 병합 1장)  ·  Fluent 설치·라이선스 필요, 케이스당 1–2분")
        set_role(subtitle, "subtitle")
        subtitle.setWordWrap(True)
        head.addWidget(title)
        head.addSpacing(14)
        head.addWidget(subtitle, 1)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(10)
        right = QVBoxLayout()
        right.setSpacing(10)

        # --- 1. Fluent 환경 (왼쪽) ---
        env_group = QGroupBox("1. Fluent 환경")
        env_layout = QGridLayout(env_group)
        env_layout.setHorizontalSpacing(10)
        env_layout.setVerticalSpacing(6)
        self.env_status_label = QLabel(self.pyfluent_status)
        set_role(self.env_status_label, "ok" if self.pyfluent_ok else "warn")
        self.env_status_label.setWordWrap(True)
        env_layout.addWidget(self.env_status_label, 0, 0, 1, 3)
        proc_label = QLabel("Fluent 프로세스 수:")
        set_role(proc_label, "field")
        env_layout.addWidget(proc_label, 1, 0)
        self.proc_spin = QSpinBox()
        self.proc_spin.setRange(1, 64)
        self.proc_spin.setValue(1)
        self.proc_spin.setToolTip("Fluent 솔버 프로세스 수. 격자 추출은 1개로 충분하고, 2개 이상이면 셀 순서가 바뀝니다 (라이선스·메모리도 고려)")
        env_layout.addWidget(self.proc_spin, 1, 1)
        note = QLabel("Fluent 를 한 번 띄워 케이스를 차례로 변환합니다 (2D/3D 가 바뀌면 다시 띄움). 중단하면 Fluent 도 함께 종료됩니다.")
        set_role(note, "hint")
        note.setWordWrap(True)
        env_layout.addWidget(note, 1, 2)
        env_layout.setColumnStretch(2, 1)
        left.addWidget(env_group)

        # --- 2. 입력 폴더 (왼쪽) ---
        in_group = QGroupBox("2. 입력 폴더 (하위 폴더까지 재귀 탐색)")
        in_outer = QVBoxLayout(in_group)
        in_outer.setSpacing(6)
        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("CFF 파일(.cas.h5)이 있는 폴더를 선택하세요")
        folder_btn = QPushButton("폴더 선택")
        folder_btn.clicked.connect(self._browse_folder)
        self.scan_btn = QPushButton("파일 스캔")
        self.scan_btn.clicked.connect(self._scan_folder)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(folder_btn)
        folder_layout.addWidget(self.scan_btn)
        in_outer.addLayout(folder_layout)
        self.file_count_label = QLabel("폴더를 선택하고 스캔하세요")
        set_role(self.file_count_label, "hint")
        self.file_count_label.setWordWrap(True)
        in_outer.addWidget(self.file_count_label)
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(56)
        self.file_list.setMaximumHeight(120)
        self.file_list.setAlternatingRowColors(True)
        in_outer.addWidget(self.file_list, 1)
        left.addWidget(in_group, 1)

        # --- 4. 출력 설정 (왼쪽) ---
        out_group = QGroupBox("4. 출력 설정")
        out_layout = QGridLayout(out_group)
        out_layout.setHorizontalSpacing(10)
        out_layout.setVerticalSpacing(6)
        out_layout.setColumnStretch(1, 1)
        out_layout.setColumnStretch(3, 1)
        fmt_label = QLabel("포맷:")
        set_role(fmt_label, "field")
        out_layout.addWidget(fmt_label, 0, 0)
        fmt_widget = QWidget()
        fmt_layout = QHBoxLayout(fmt_widget)
        fmt_layout.setContentsMargins(0, 0, 0, 0)
        self.fmt_group = QButtonGroup(self)
        self.radio_vtu = QRadioButton("VTU (체적, 셀 존 SVAR)")
        self.radio_vtp = QRadioButton("VTP (경계 면 존 병합 1장)")
        self.format_radios = {"vtu": self.radio_vtu, "vtp": self.radio_vtp}
        self.format_hint_label = QLabel("")
        set_role(self.format_hint_label, "hint")
        self.format_hint_label.setWordWrap(True)
        self.rename_cb = QCheckBox("Fluent 표시명으로 저장 (SV_P→pressure, SV_U→x-velocity …)")
        self.rename_cb.setChecked(True)
        self.rename_cb.setToolTip(
            "체크박스의 이름은 Fluent SVAR(SV_*)이고 저장 시 표시명으로 바뀝니다 (cff_common.py 매핑표).\n"
            "SV_U, SV_V, SV_W 를 모두 고르면 벡터 velocity(3) 가 추가됩니다.\n"
            "⚠ PyVista 변환기 결과와 같은 학습 세트에 섞을 때는 두 탭의 이 옵션을 같게 두세요.")
        for fmt, rb in self.format_radios.items():
            self.fmt_group.addButton(rb)
            fmt_layout.addWidget(rb)
            rb.setToolTip(PYFLUENT_FORMAT_HINTS[fmt])
            rb.toggled.connect(lambda checked, f=fmt: checked and self._on_format_changed(f))
        self.radio_vtu.setChecked(True)
        fmt_layout.addStretch()
        out_layout.addWidget(fmt_widget, 0, 1, 1, 4)
        out_layout.addWidget(self.format_hint_label, 1, 1, 1, 4)
        prefix_label = QLabel("폴더명:")
        set_role(prefix_label, "field")
        out_layout.addWidget(prefix_label, 2, 0)
        self.folder_prefix_edit = QLineEdit()
        self.folder_prefix_edit.setText(DEFAULT_FOLDER_PREFIX)
        self.folder_prefix_edit.setPlaceholderText("예: Design → Design_001, Design_002 … (비우면 입력 파일명 기반)")
        out_layout.addWidget(self.folder_prefix_edit, 2, 1)
        mode_label = QLabel("출력 위치:")
        set_role(mode_label, "field")
        out_layout.addWidget(mode_label, 2, 2)   # 폴더명과 같은 행 (v2.0: 세로 공간 절약)
        self.output_mode = QComboBox()
        self.output_mode.addItems(["입력 파일과 같은 폴더", "지정 폴더에 모아서 저장"])
        self.output_mode.currentIndexChanged.connect(self._on_output_mode_changed)
        out_layout.addWidget(self.output_mode, 2, 3, 1, 2)
        self.outdir_label = QLabel("출력 폴더:")
        set_role(self.outdir_label, "field")
        self.outdir_edit = QLineEdit()
        self.outdir_edit.setPlaceholderText("모아서 저장할 폴더 (지정 모드에서만)")
        self.outdir_btn = QPushButton("찾아보기")
        self.outdir_btn.clicked.connect(self._browse_outdir)
        out_layout.addWidget(self.outdir_label, 3, 0)
        out_layout.addWidget(self.outdir_edit, 3, 1, 1, 3)
        out_layout.addWidget(self.outdir_btn, 3, 4)
        name_label = QLabel("변수명:")
        set_role(name_label, "field")
        out_layout.addWidget(name_label, 4, 0)
        out_layout.addWidget(self.rename_cb, 4, 1, 1, 4)
        self._set_outdir_enabled(False)
        left.addWidget(out_group)

        # --- 3. 변수 선택 (오른쪽, 세로로 늘어남) ---
        var_group = QGroupBox("3. 저장할 변수 선택 (첫 파일 기준 · 포맷에 따라 목록이 다름)")
        var_outer = QVBoxLayout(var_group)
        var_outer.setSpacing(6)
        self.load_vars_btn = QPushButton("첫 파일로 변수 불러오기 (Fluent 기동, 1–2분)")
        self.load_vars_btn.clicked.connect(self._load_variables)
        var_outer.addWidget(self.load_vars_btn)
        var_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("전체 선택")
        self.select_all_btn.clicked.connect(lambda: self._set_all_vars(True))
        self.deselect_all_btn = QPushButton("전체 해제")
        self.deselect_all_btn.clicked.connect(lambda: self._set_all_vars(False))
        var_btns.addWidget(self.select_all_btn)
        var_btns.addWidget(self.deselect_all_btn)
        var_btns.addStretch()
        var_outer.addLayout(var_btns)
        self.var_count_label = QLabel("변수를 불러오세요")
        set_role(self.var_count_label, "hint")
        self.var_count_label.setWordWrap(True)
        var_outer.addWidget(self.var_count_label)
        self.var_scroll = QScrollArea()
        self.var_scroll.setWidgetResizable(True)
        self.var_scroll.setMinimumHeight(100)
        self.var_container = QWidget()
        self.var_grid = QGridLayout(self.var_container)
        self.var_grid.setSpacing(6)
        self.var_grid.setContentsMargins(10, 10, 10, 10)
        self.var_scroll.setWidget(self.var_container)
        var_outer.addWidget(self.var_scroll, 1)
        right.addWidget(var_group, 1)
        self._on_format_changed("vtu")   # 힌트 라벨·변수 라벨이 모두 만들어진 뒤 호출

        # --- 5. 실행 · 중단 · 전체 진행 (오른쪽 아래) ---
        self.run_btn = QPushButton("변환 실행")
        set_role(self.run_btn, "primary")
        self.run_btn.setMinimumHeight(44)
        self.run_btn.clicked.connect(self._run_batch)
        self.cancel_btn = QPushButton("중단")
        set_role(self.cancel_btn, "danger")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        right.addWidget(self.run_btn)
        right.addWidget(self.cancel_btn)
        self.overall_label = QLabel("전체 진행: 대기 중")
        set_role(self.overall_label, "status")
        self.overall_label.setWordWrap(True)
        right.addWidget(self.overall_label)
        self.overall_progress = QProgressBar()
        self.overall_progress.setValue(0)
        right.addWidget(self.overall_progress)

        body.addLayout(left, 11)
        body.addLayout(right, 9)
        root.addLayout(body)

        # --- 6. 콘솔 (전폭) ---
        console_group = QGroupBox("콘솔 출력 (동일 내용이 로그 파일에 실시간 기록됨)")
        console_layout = QVBoxLayout(console_group)
        console_layout.setSpacing(6)
        log_row = QHBoxLayout()
        log_label = QLabel("로그 파일:")
        set_role(log_label, "field")
        log_row.addWidget(log_label)
        self.log_path_edit = QLineEdit()
        self.log_path_edit.setReadOnly(True)
        self.log_path_edit.setText(session_log.get_log_path() or "(세션 시작 시 생성)")
        log_row.addWidget(self.log_path_edit, 1)
        self.open_log_btn = QPushButton("로그 열기")
        self.open_log_btn.clicked.connect(self._open_log_file)
        log_row.addWidget(self.open_log_btn)
        self.open_logdir_btn = QPushButton("폴더 열기")
        self.open_logdir_btn.clicked.connect(self._open_log_dir)
        log_row.addWidget(self.open_logdir_btn)
        console_layout.addLayout(log_row)
        self.console = ConsoleEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(90)
        set_role(self.console, "console")
        console_layout.addWidget(self.console, 1)
        root.addWidget(console_group, 1)

    # --------------------------------------------------------
    def _log(self, msg):
        append_log(self.console, msg)
        session_log.write(msg, tag="PyFluent")

    def _current_format(self):
        for fmt, rb in self.format_radios.items():
            if rb.isChecked():
                return fmt
        return "vtu"

    def _vars_for_format(self, fmt):
        return self.vars_face if fmt == "vtp" else self.vars_cell

    def _on_format_changed(self, fmt):
        """포맷에 맞는 변수 목록으로 바꾸되, 같은 이름의 체크는 유지한다 (결정 004 축 3)."""
        self.format_hint_label.setText(PYFLUENT_FORMAT_HINTS.get(fmt, ""))
        if not self.vars_loaded:
            return
        keep = set(self._selected_variables())
        names = self._vars_for_format(fmt)
        self._populate_variables(names)
        for cb in self.var_checkboxes:
            if cb.text() in keep:
                cb.setChecked(True)
        self._update_var_count_label(fmt)

    def _update_var_count_label(self, fmt):
        names = self._vars_for_format(fmt)
        if fmt == "vtp":
            bnames = [b.get("name", "?") for b in self.boundaries]
            txt = "%d개 변수 (경계 면 존 SVAR) · 경계 %d개: %s" % (len(names), len(bnames), ", ".join(bnames[:6]) + (" …" if len(bnames) > 6 else ""))
        else:
            txt = "%d개 변수 (셀 존 SVAR, 솔버 내부 배열 숨김)" % len(names)
        self.var_count_label.setText(txt)
        set_role(self.var_count_label, "hint")

    def _set_batch_widgets_enabled(self, enabled):
        for w in (self.load_vars_btn, self.select_all_btn, self.deselect_all_btn, self.rename_cb,
                  self.radio_vtu, self.radio_vtp, self.proc_spin, self.scan_btn):
            w.setEnabled(enabled)

    # --------------------------------------------------------
    def _resolve_interpreter(self):
        if not self.pyfluent_ok:
            return None, "PyFluent 를 쓸 수 없습니다: %s" % self.pyfluent_status
        interp = python_interpreter()
        if not interp or not os.path.exists(interp):
            return None, "Python 인터프리터를 찾지 못했습니다: %s" % interp
        if not os.path.exists(PYFLUENT_WORKER_SCRIPT):
            return None, "워커 스크립트가 없습니다: %s" % PYFLUENT_WORKER_SCRIPT
        return interp, PYFLUENT_WORKER_SCRIPT

    def _load_variables(self):
        interp, worker = self._resolve_interpreter()
        if interp is None:
            QMessageBox.warning(self, "경고", worker)
            return
        if not self.cff_files:
            QMessageBox.warning(self, "경고", "먼저 폴더를 스캔하여 CFF 파일을 찾으세요.")
            return
        first_file = self.cff_files[0]
        dat, _ = resolve_data_file(first_file)
        if dat is None:
            QMessageBox.warning(self, "경고", "첫 파일의 데이터 파일(.dat.h5)이 없습니다. PyFluent 탭은 결과 데이터가 있어야 합니다:\n%s" % first_file)
            return
        self._log("[GUI] 첫 파일로 변수 불러오는 중 (PyFluent, Fluent 기동 포함 1–2분): %s" % Path(first_file).name)
        self.load_vars_btn.setEnabled(False)
        self.load_vars_btn.setText("Fluent 기동·읽는 중... (1–2분)")
        self.loader = PyFluentVariableLoader(interp, worker, first_file)
        self.loader.finished_ok.connect(self._on_vars_loaded)
        self.loader.finished_err.connect(self._on_vars_error)
        self.loader.start()

    def _restore_load_btn(self):
        self.load_vars_btn.setEnabled(True)
        self.load_vars_btn.setText("첫 파일로 변수 불러오기 (Fluent 기동, 1–2분)")
        loader = self.loader
        if loader is not None:
            self._release_workdir(getattr(loader, "workdir", ""))   # 로더 워커의 임시 폴더 (잠겨 있으면 60초 뒤 재시도)

    def _on_vars_loaded(self, data):
        self._restore_load_btn()
        self.vars_cell = list(data.get("cell_arrays", []))
        self.vars_face = list(data.get("face_arrays", []))
        self.boundaries = list(data.get("boundaries", []))
        self.vars_loaded = True
        fmt = self._current_format()
        self._populate_variables(self._vars_for_format(fmt))
        self._update_var_count_label(fmt)
        self._log("[GUI] 변수 로드 완료: 셀 존 %d개, 경계 면 존 %d개 · 경계 %s · %s · 셀 %s개" % (
            len(self.vars_cell), len(self.vars_face),
            [b.get("name") for b in self.boundaries], data.get("fluent_version", "?"), data.get("n_cells", "?")))
        dat = data.get("data_file")
        if dat and data.get("data_name_matches") is False:
            self._log("[GUI] 데이터 파일 이름이 케이스와 달라 PyFluent 에 직접 지정했습니다: %s" % Path(dat).name)
        if not self._vars_for_format(fmt):
            self.var_count_label.setText("변수 0개 — 데이터 파일을 확인하세요")
            set_role(self.var_count_label, "warn")
            QMessageBox.warning(self, "경고", "변수를 찾지 못했습니다 (0개).\n케이스: %s" % Path(self.cff_files[0]).name)

    def _on_vars_error(self, msg):
        self._restore_load_btn()
        self._log("[ERROR] 변수 로딩 실패 (PyFluent): %s" % msg)
        QMessageBox.critical(self, "오류", "변수 로딩 실패 (PyFluent):\n%s" % msg)

    # --------------------------------------------------------
    def _run_batch(self):
        interp, worker = self._resolve_interpreter()
        selected = self._selected_variables()
        if interp is None:
            QMessageBox.warning(self, "경고", worker)
            return
        if not self.cff_files:
            QMessageBox.warning(self, "경고", "변환할 CFF 파일이 없습니다. 폴더를 스캔하세요.")
            return
        if not self.vars_loaded:
            QMessageBox.warning(self, "경고", "'첫 파일로 변수 불러오기'를 먼저 실행하세요.")
            return
        if not selected:
            QMessageBox.warning(self, "경고", "저장할 변수를 하나 이상 선택하세요.")
            return
        out_format = self._current_format()
        rename = self.rename_cb.isChecked()
        if self.output_mode.currentIndex() == 1:
            outdir = self.outdir_edit.text().strip()
            if not outdir:
                QMessageBox.warning(self, "경고", "출력 폴더를 지정하세요.")
                return
            try:
                os.makedirs(outdir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "경고", "출력 폴더를 만들 수 없습니다:\n%s\n%s" % (outdir, e))
                return
            self.output_dir_override = outdir
        else:
            self.output_dir_override = ""
        prefix = self.folder_prefix_edit.text().strip()
        used_bad = [c for c in prefix if c in set('<>:"/\\|?*')]
        if used_bad:
            QMessageBox.warning(self, "경고", "폴더명 접두사에 사용할 수 없는 문자가 있습니다: %s" % " ".join(sorted(set(used_bad))))
            return
        overwrite_count = 0
        dry_folders = set()
        for i, cf in enumerate(self.cff_files, start=1):
            try:
                out_path = self._compute_output_path(cf, i, dry_folders, prefix, out_format, self.output_dir_override, log=False)
            except Exception:
                continue
            if self._output_exists(out_path, out_format):
                overwrite_count += 1
        n_no_dat, n_renamed = 0, 0
        for cf in self.cff_files:
            dat, matches = resolve_data_file(cf)
            if dat is None:
                n_no_dat += 1
            elif not matches:
                n_renamed += 1
        inner = "%s.vtp (경계 병합 1장, boundary_id)" % UNIFIED_VTU_NAME if out_format == "vtp" else "%s.vtu" % UNIFIED_VTU_NAME
        if prefix:
            naming = "폴더명: %s_%s, %s_%s … (내부 파일: %s)\n  · 파일명에 DP 번호가 있으면 그 번호 사용 (dp_016 → %s_016)" % (
                prefix, "1".zfill(FOLDER_NUM_WIDTH), prefix, "2".zfill(FOLDER_NUM_WIDTH), inner, prefix)
        else:
            naming = "폴더명: 입력 파일명 기반(<파일명>%s), 내부 파일: %s" % (EXPORT_SUFFIX, inner)
        extra = ""
        if overwrite_count:
            extra += "\n⚠ 기존 출력 %d개를 덮어씁니다." % overwrite_count
        if n_no_dat:
            extra += "\n⚠ 데이터 파일(.dat.h5)이 없는 케이스 %d개 → 실패 처리됩니다 (초기화 값은 내보내지 않음)" % n_no_dat
        if n_renamed:
            extra += "\n데이터 파일 이름이 다른 케이스 %d개 (예: FFF.3-2-11200.dat.h5) → PyFluent 에 직접 지정" % n_renamed
        reply = QMessageBox.question(
            self, "PyFluent 배치 변환 확인",
            "%d개 파일을 변환합니다.\n엔진: PyFluent (Fluent 1회 기동 30–45초 + 케이스당 약 20초–1분, 라이선스 1석)\n"
            "변수: %d개, 포맷: %s\n변수명: %s\nFluent 프로세스 수: %d\n%s%s\n\n계속하시겠습니까?" % (
                len(self.cff_files), len(selected), out_format.upper(),
                "Fluent 표시명 (pressure, temperature …)" if rename else "Fluent 원본 (SV_P, SV_T …)",
                self.proc_spin.value(), naming, extra),
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self.selected_vars = selected
        self.out_format = out_format
        self.batch_interpreter = interp
        self.batch_worker = worker
        self.batch_rename = rename
        self.batch_processors = self.proc_spin.value()
        self.folder_prefix = prefix
        self.batch_queue = list(self.cff_files)
        self.batch_total = len(self.batch_queue)
        self.batch_index = 0
        self.batch_success = 0
        self.batch_failed = 0
        self._batch_folders = set()
        self._cancelling = False
        self.run_btn.setEnabled(False)
        self.run_btn.setText("변환 중...")
        self.cancel_btn.setEnabled(True)
        self._set_batch_widgets_enabled(False)
        self.overall_progress.setMaximum(self.batch_total)
        self.overall_progress.setValue(0)
        self._log("\n" + "=" * 60)
        self._log("[GUI] PyFluent 배치 변환 시작: %d개 파일, %s 포맷, 변수 %d개, 프로세스 %d (Fluent 1회 기동)" % (
            self.batch_total, out_format.upper(), len(selected), self.batch_processors))
        self._log("[GUI] 인터프리터: %s" % interp)
        self._log("[GUI] 워커: %s" % worker)
        self._log("=" * 60)
        # 출력 경로를 미리 전부 계산해 jobs 파일로 넘긴다 (순서가 같으므로 폴더 유일화 결과는 파일별 호출 때와 같다)
        jobs = []
        self._jobs = {}
        for i, case_file in enumerate(self.batch_queue, start=1):
            try:
                output_path = self._compute_output_path(case_file, i, self._batch_folders, self.folder_prefix,
                                                        self.out_format, self.output_dir_override, log=True)
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._log("\n[%d/%d] %s" % (i, self.batch_total, Path(case_file).name))
                self._log("    [GUI] ✗ 출력 경로 준비 실패: %s" % e)
                self.batch_failed += 1
                continue
            job = {"index": i, "case": case_file, "output": output_path, "format": self.out_format}
            jobs.append(job)
            self._jobs[i] = job
        self.overall_progress.setValue(self.batch_success + self.batch_failed)
        if not jobs:
            self._batch_finished()
            return
        try:
            fd, jobs_file = tempfile.mkstemp(prefix="cff_pyfluent_jobs_", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False)
        except Exception as e:
            self._log("[GUI] ✗ 작업 목록 파일을 만들지 못했습니다: %s" % e)
            self.batch_failed += len(jobs)
            self._batch_finished()
            return
        self._jobs_file = jobs_file
        self._start_worker()

    def _cleanup_jobs_file(self):
        path = getattr(self, "_jobs_file", "")
        self._jobs_file = ""
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    def _release_workdir(self, path):
        """끝난 워커/로더의 임시 폴더를 지운다. Fluent 가 .trn 을 아직 잡고 있으면 60초 뒤 다시 시도한다."""
        if path and path not in self._pending_workdirs:
            self._pending_workdirs.append(path)
        self._sweep_workdirs()

    def _sweep_workdirs(self):
        self._pending_workdirs = [d for d in self._pending_workdirs if not remove_dir_quiet(d)]
        if self._pending_workdirs:
            QTimer.singleShot(WORKDIR_SWEEP_MS, self._sweep_workdirs)

    def _start_worker(self):
        """배치 전체를 처리할 워커 1개를 띄운다 (--jobs). 케이스 경계·성공/실패는 stdout 의 [FILE_START]/[FILE_DONE] 로 받는다."""
        self.overall_label.setText("전체 진행: 0 / %d  —  Fluent 기동 중..." % self.batch_total)
        args = [self.batch_worker, "--jobs", self._jobs_file,
                "--vars", ",".join(self.selected_vars), "--processors", str(self.batch_processors)]
        if self.batch_rename:
            args += ["--rename"]
        self._out_buf = ""
        self._fluent_pids = []
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.errorOccurred.connect(self._on_process_error)
        self.process.finished.connect(self._on_worker_finished)
        # stdin 은 열어 둔다 (중단 시 "CANCEL\n" 을 보낸다) — closeWriteChannel 을 부르지 않는다
        self.process.start(self.batch_interpreter, args)

    def _remaining(self):
        return self.batch_total - self.batch_success - self.batch_failed

    def _on_process_error(self, error):
        if error != QProcess.FailedToStart or self.process is None:
            return
        self._log("[GUI] ✗ 프로세스 시작 실패: 인터프리터 또는 워커 스크립트를 확인하세요")
        self._log("    인터프리터: %s" % self.batch_interpreter)
        self._log("    워커: %s" % self.batch_worker)
        self.batch_failed += self._remaining()      # 워커가 못 떴으니 남은 케이스 전부 실패
        self.process = None
        self._cleanup_jobs_file()
        self.overall_progress.setValue(self.batch_success + self.batch_failed)
        QTimer.singleShot(0, self._batch_finished)

    def _emit_worker_lines(self, lines):
        for line in lines:
            line = line.rstrip()
            if not line:
                continue
            m = FLUENT_PID_RE.match(line)
            if m:
                self._fluent_pids = [int(m.group(2)), int(m.group(1))]   # cortex, fluent host (재기동 시 최신 값으로 덮어씀)
                self._log("    [GUI] Fluent pid 기억: cortex %s, fluent %s (중단·크래시 시 정리용)" % (m.group(2), m.group(1)))
                continue
            m = WORKDIR_RE.match(line)
            if m:
                self._workdir = m.group(1).strip()
                continue
            m = FILE_START_RE.match(line)
            if m:
                idx = int(m.group(1))
                job = self._jobs.get(idx, {})
                name = Path(job.get("case") or m.group(3)).name
                target = self._target_display(job["output"], self.out_format) if job.get("output") else ""
                self.overall_label.setText("전체 진행: %d / %d  (성공 %d, 실패 %d)  —  현재: %s" % (
                    idx, self.batch_total, self.batch_success, self.batch_failed, name))
                self._log("\n[%d/%d] %s → %s" % (idx, self.batch_total, name, target))
                continue
            m = FILE_DONE_RE.match(line)
            if m:
                reason = m.group(4) or ""
                if m.group(3) == "ok":
                    self.batch_success += 1
                    self._log("    [GUI] ✓ 완료")
                elif reason.startswith("사용자 중단"):
                    self._log("    [GUI] ⏹ 중단됨 (이 케이스는 완료되지 않음)")   # 중단은 실패로 세지 않는다
                else:
                    self.batch_failed += 1
                    self._log("    [GUI] ✗ 실패: %s" % reason)
                self.overall_progress.setValue(self.batch_success + self.batch_failed)
                continue
            if line.startswith("[PROGRESS]") or line == "[SUCCESS]":
                continue
            self._log("    " + line)

    def _on_worker_finished(self, exit_code, exit_status):
        """배치 워커 종료. 집계는 [FILE_DONE] 이 맡고, 여기서는 끝까지 보고되지 않은 케이스를 실패로 센다."""
        if self._out_buf.strip():
            self._emit_worker_lines([self._out_buf])
        self._out_buf = ""
        remaining = self._remaining()
        if exit_status == QProcess.CrashExit:
            self._log("    [GUI] ✗ 워커가 비정상 종료됨 — 보고되지 않은 케이스 %d개를 실패로 처리" % remaining)
        elif remaining > 0:
            self._log("    [GUI] ✗ 워커가 먼저 끝남 (exit code %d) — 보고되지 않은 케이스 %d개를 실패로 처리" % (exit_code, remaining))
        elif exit_code != 0:
            self._log("    [GUI] 워커 종료 (exit code %d: 일부 케이스 실패)" % exit_code)
        else:
            self._log("    [GUI] 워커 종료 (exit code 0)")
        self.batch_failed += remaining
        if exit_status == QProcess.CrashExit or exit_code != 0:
            kill_fluent_pids(self._fluent_pids, log=self._log)   # 워커가 끝난 뒤에만. 정상 종료면 이미 없다
        self.process = None
        self._fluent_pids = []
        self._cleanup_jobs_file()
        self._release_workdir(self._workdir)
        self._workdir = ""
        self.overall_progress.setValue(self.batch_success + self.batch_failed)
        QTimer.singleShot(0, self._batch_finished)

    def _batch_finished(self):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("변환 실행")
        self.cancel_btn.setEnabled(False)
        self._set_batch_widgets_enabled(True)
        self.overall_label.setText("완료: 총 %d개  (성공 %d, 실패 %d)" % (self.batch_total, self.batch_success, self.batch_failed))
        self._log("\n" + "=" * 60)
        self._log("[GUI] PyFluent 배치 변환 완료: 성공 %d / 실패 %d (총 %d)" % (self.batch_success, self.batch_failed, self.batch_total))
        self._log("=" * 60)
        QMessageBox.information(self, "배치 완료", "변환 완료!\n\n총 %d개\n성공: %d개\n실패: %d개" % (
            self.batch_total, self.batch_success, self.batch_failed))

    # --------------------------------------------------------
    # 중단: CANCEL(협조) → 대기 → kill + taskkill (폴백)
    # --------------------------------------------------------
    def _cancel_batch(self):
        if self._cancelling:
            return
        reply = QMessageBox.question(self, "중단 확인", "PyFluent 배치 변환을 중단하시겠습니까?\n(실행 중인 Fluent 세션도 함께 종료합니다)",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        if self.process is None:
            self._log("[GUI] 배치가 이미 완료되어 중단할 것이 없습니다.")
            return
        self._cancelling = True                      # 다음 케이스를 시작하지 않는 것은 워커가 CANCEL 을 받아 루프를 끝내며 보장한다
        self.cancel_btn.setEnabled(False)
        if self.process is None:
            self._finish_cancel()
            return
        try:
            self.process.finished.disconnect()
        except Exception:
            pass
        self.process.finished.connect(self._on_cancelled_finished)
        self._log("\n[GUI] 중단 요청 → 워커에 CANCEL 송신 (Fluent 세션 종료 대기, 최대 %d초)" % (PYFLUENT_CANCEL_WAIT_MS // 1000))
        self.overall_label.setText("중단 중... (Fluent 세션 종료 대기)")
        self.process.write(b"CANCEL\n")
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._force_kill_worker)
        self._cancel_timer.start(PYFLUENT_CANCEL_WAIT_MS)

    def _on_cancelled_finished(self, exit_code, exit_status):
        timer = getattr(self, "_cancel_timer", None)
        if timer is not None:
            timer.stop()
        if self._out_buf.strip():
            self._emit_worker_lines([self._out_buf])
        self._out_buf = ""
        self._log("    [GUI] 워커 종료 (exit code %s)" % exit_code)
        self.process = None
        kill_fluent_pids(self._fluent_pids, log=self._log)   # 보통 이미 없다. 남아 있으면 여기서 정리
        self._fluent_pids = []
        self._finish_cancel()

    def _force_kill_worker(self):
        if self.process is None:
            return
        self._log("    [GUI] 워커가 %d초 안에 끝나지 않아 강제 종료합니다" % (PYFLUENT_CANCEL_WAIT_MS // 1000))
        try:
            self.process.finished.disconnect()
        except Exception:
            pass
        self.process.kill()
        self.process.waitForFinished(3000)
        self.process = None
        self._out_buf = ""
        kill_fluent_pids(self._fluent_pids, log=self._log)
        self._fluent_pids = []
        self._finish_cancel()

    def _finish_cancel(self):
        self._cancelling = False
        self._cleanup_jobs_file()
        self._release_workdir(self._workdir)
        self._workdir = ""
        self.run_btn.setEnabled(True)
        self.run_btn.setText("변환 실행")
        self.cancel_btn.setEnabled(False)
        self._set_batch_widgets_enabled(True)
        self._log("[GUI] 사용자가 PyFluent 배치 변환을 중단했습니다.")
        self.overall_label.setText("중단됨 (성공 %d, 실패 %d)" % (self.batch_success, self.batch_failed))

    def shutdown(self):
        """앱 종료: 로더·워커에 CANCEL → 잠시 대기 → kill → Fluent pid 정리."""
        loader = self.loader
        if loader is not None:
            try:
                if loader.isRunning():
                    loader.cancel()
                    loader.wait(8000)
            except Exception:
                pass
        if self.process is not None:
            try:
                self.process.finished.disconnect()
            except Exception:
                pass
            try:
                self.process.write(b"CANCEL\n")
                if not self.process.waitForFinished(8000):
                    self.process.kill()
                    self.process.waitForFinished(2000)
            except Exception:
                pass
            kill_fluent_pids(self._fluent_pids)
            self.process = None
        self._cleanup_jobs_file()
        # 임시 작업 폴더는 한 번만 시도 (잠겨 있으면 다음 실행의 워커가 10분 뒤 정리)
        for d in [self._workdir, getattr(loader, "workdir", "") if loader is not None else ""] + list(self._pending_workdirs):
            if d:
                remove_dir_quiet(d)


# ============================================================
# 메인 윈도우 (탭 호스트)
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(960, 640)

        self.converter = ConverterTab()
        self.dp_tab = DPCollectTab()
        self.pyfluent_tab = PyFluentTab()
        self.bc_tab = BCJsonTab(start_dir_provider=lambda: self.converter.outdir_edit.text().strip())

        self._pages = (self.dp_tab, self.converter, self.pyfluent_tab, self.bc_tab)
        tabs = QTabWidget()
        # 탭 내용은 스크롤 영역에 담는다: 작은 화면(노트북 125~150 %)에서는 위젯이 잘리는 대신 세로 스크롤이 생긴다 (v2.0)
        tabs.addTab(self._scrollable(self.dp_tab), "Workbench DP 정리")
        tabs.addTab(self._scrollable(self.converter), "PyVista 변환기")
        tabs.addTab(self._scrollable(self.pyfluent_tab), "PyFluent 변환기")
        tabs.addTab(self._scrollable(self.bc_tab), "JSON 생성기")
        self.setCentralWidget(tabs)

        # Solarized Light 테마를 창 전체(탭 바 + 모든 탭 + QMessageBox)에 적용 (app_theme.py)
        self.setStyleSheet(APP_QSS)
        self._apply_initial_size()

    @staticmethod
    def _scrollable(page):
        sa = QScrollArea()
        sa.setObjectName("tabScroll")
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.NoFrame)
        sa.setWidget(page)
        return sa

    def _apply_initial_size(self):
        """시작 크기: 내용이 원하는 크기(sizeHint)를 화면 가용 영역(작업표시줄 제외) 안으로 맞춘다 (v2.0).
        이전에는 resize() 가 없어 Qt 가 화면의 2/3 높이로 깎아 띄웠고, 그 높이에서는 변수 목록·콘솔이 눌렸다."""
        # 탭 페이지가 스크롤 영역 안에 있어 창의 sizeHint 는 작게 나온다 → 페이지들의 sizeHint 로 직접 계산
        tabs = self.centralWidget()
        pw = max(p.sizeHint().width() for p in self._pages) + 24
        ph = max(p.sizeHint().height() for p in self._pages) + tabs.tabBar().sizeHint().height() + 16
        w, h = max(pw, 1120), max(ph, 780)
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(w, avail.width() - 60)
            h = min(h, avail.height() - 56)
        self.resize(max(w, self.minimumWidth()), max(h, self.minimumHeight()))

    def closeEvent(self, event):
        # 각 탭의 백그라운드 작업을 정리한 뒤 종료 (로딩/변환 중 크래시 방지)
        self.converter.shutdown()
        self.pyfluent_tab.shutdown()
        self.dp_tab.shutdown()
        self.bc_tab.shutdown()
        session_log.close_session_log()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_palette(app)          # Windows 다크 모드여도 라이트 팔레트 (스크롤바·스핀박스 등 QSS 밖 요소)
    app.setStyleSheet(APP_QSS)
    log_path = session_log.init_session_log()   # 콘솔 출력을 실시간 기록할 세션 로그 파일
    window = MainWindow()
    if log_path:
        window.converter._log("로그 파일: %s" % log_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
