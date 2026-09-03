"""
ParaView CFF -> VTU/VTM 배치 변환기 GUI
Author: 퍼팩트리

PySide6 기반 GUI. 일반 Python(venv)에서 실행하며,
ParaView의 pvpython을 subprocess로 호출하여 변환을 수행합니다.

기능:
  - 폴더 선택 → 하위 폴더까지 재귀 탐색하여 모든 .cas.h5 자동 리스트업
  - 100개 이상의 CFF 파일 순차 배치 처리
  - 첫 파일 기준으로 변수 체크박스 → 모든 파일에 동일 적용
  - VTU / VTM 포맷 선택 (VTU=Merge Blocks O, VTM=Merge Blocks X)
  - 출력 폴더 자동 (접두사+번호: Design_001/Results.vtu, 파일명에 dp 번호가
    있으면 그 번호 사용)
  - 전체 진행률 + 파일별 진행 상황 + 실시간 콘솔

설치:
  pip install PySide6

실행:
  python pv_export_gui.py

★ 같은 폴더에 pv_export_worker.py와 dp_collect_tab.py가 함께 있어야 합니다.
"""
import sys
import os
import re
import json
import logging
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit, QProgressBar,
    QGroupBox, QScrollArea, QCheckBox, QRadioButton, QButtonGroup,
    QMessageBox, QListWidget, QListWidgetItem, QComboBox, QTabWidget, QSpinBox,
)

from dp_collect_tab import DPCollectTab
import bc_json_gen
import session_log

# 앱 버전은 이 상수 하나로 관리 (윈도우 타이틀에 표시)
APP_TITLE = "ParaView CFF To VTK 변환기 v1.3"


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
TAB_QSS = """
    QTabWidget::pane { border: 1px solid #444; background-color: #2b2b2b; }
    QTabBar::tab {
        background: #333; color: #cfcfcf; padding: 8px 18px;
        border: 1px solid #444; border-bottom: none;
        border-top-left-radius: 4px; border-top-right-radius: 4px;
    }
    QTabBar::tab:selected { background: #0078d4; color: #ffffff; }
    QTabBar::tab:hover:!selected { background: #484848; }
    QHeaderView::section:hover { background-color: #3a3a3a; }
"""

# 워커 스크립트 경로 (같은 폴더)
WORKER_SCRIPT = str(Path(__file__).parent / "pv_export_worker.py")

# 출력 구조 규칙
#   폴더명 접두사(prefix)를 지정하면 변환 순서대로 번호가 붙는다.
#   - VTU: <prefix>_001/Results.vtu
#   - VTM: <prefix>_001.vtm (+ <prefix>_001/Results.vtu)
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

    def __init__(self, pvpython, case_file):
        super().__init__()
        self.pvpython = pvpython
        self.case_file = case_file
        self.proc = None          # 실행 중인 subprocess (취소 시 kill 대상)
        self._cancelled = False   # True면 어떤 시그널도 emit하지 않음

    def run(self):
        import subprocess
        try:
            # Popen으로 실행해 프로세스 핸들(self.proc)을 보관 → 로딩 중 종료 시 kill 가능.
            # 한글 로그 깨짐 방지를 위해 PYTHONIOENCODING=utf-8 환경변수 주입.
            self.proc = subprocess.Popen(
                [self.pvpython, WORKER_SCRIPT, "--case", self.case_file, "--list-json"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            try:
                out, _ = self.proc.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                if not self._cancelled:
                    self.finished_err.emit("시간 초과 (120초).")
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
                    self.finished_ok.emit(data)
            else:
                self.finished_err.emit("변수 목록 파싱 실패.\n출력:\n" + out[-500:])
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
        self.out_format = "vtm"       # 출력 포맷 (기본값 VTM)
        self.batch_pvpython = ""      # 배치 시작 시 캡처한 pvpython 경로 (중간 변경 무시)
        self.output_dir_override = "" # 출력 폴더 (선택)
        self.folder_prefix = ""       # 폴더명 접두사 (배치 시작 시 캡처)
        self._batch_folders = set()   # 배치 내 폴더명 충돌 감지용

        self._build_ui()
        self._auto_detect_pvpython()

    # --------------------------------------------------------
    # UI 구성
    # --------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- 제목 ---
        title = QLabel("ParaView CFF To VTK 변환기")
        tf = QFont(); tf.setPointSize(15); tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)
        subtitle = QLabel("폴더 내 모든 CFF(.cas.h5)를 재귀 탐색하여 일괄 변환")
        subtitle.setStyleSheet("color: #888;")
        root.addWidget(subtitle)

        # --- 1. ParaView 경로 ---
        pv_group = QGroupBox("1. ParaView 실행 파일 (pvpython)")
        pv_layout = QHBoxLayout(pv_group)
        self.pvpython_edit = QLineEdit()
        self.pvpython_edit.setPlaceholderText("pvpython.exe 경로 (자동 탐지됨)")
        pv_detect = QPushButton("자동 탐지")
        pv_detect.clicked.connect(self._auto_detect_pvpython)
        pv_btn = QPushButton("찾아보기")
        pv_btn.clicked.connect(self._browse_pvpython)
        pv_layout.addWidget(self.pvpython_edit, 1)
        pv_layout.addWidget(pv_detect)
        pv_layout.addWidget(pv_btn)
        root.addWidget(pv_group)

        # --- 2. 입력 폴더 (재귀 탐색) ---
        in_group = QGroupBox("2. 입력 폴더 (하위 폴더까지 재귀 탐색)")
        in_outer = QVBoxLayout(in_group)
        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("CFF 파일이 있는 폴더를 선택하세요")
        folder_btn = QPushButton("폴더 선택")
        folder_btn.clicked.connect(self._browse_folder)
        self.scan_btn = QPushButton("파일 스캔")
        self.scan_btn.clicked.connect(self._scan_folder)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(folder_btn)
        folder_layout.addWidget(self.scan_btn)
        in_outer.addLayout(folder_layout)

        # 파일 목록 표시
        list_header = QHBoxLayout()
        self.file_count_label = QLabel("폴더를 선택하고 스캔하세요")
        self.file_count_label.setStyleSheet("color: #888;")
        list_header.addWidget(self.file_count_label)
        list_header.addStretch()
        in_outer.addLayout(list_header)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(120)
        self.file_list.setStyleSheet(
            "QListWidget { background-color: #252525; color: #c0c0c0; "
            "border: 1px solid #444; border-radius: 4px; }"
        )
        in_outer.addWidget(self.file_list)
        root.addWidget(in_group)

        # --- 3. 변수 선택 ---
        var_group = QGroupBox("3. 저장할 변수 선택 (첫 파일 기준, 모든 파일 동일 적용)")
        var_outer = QVBoxLayout(var_group)
        var_btns = QHBoxLayout()
        self.load_vars_btn = QPushButton("첫 파일로 변수 불러오기")
        self.load_vars_btn.clicked.connect(self._load_variables)
        self.select_all_btn = QPushButton("전체 선택")
        self.select_all_btn.clicked.connect(lambda: self._set_all_vars(True))
        self.deselect_all_btn = QPushButton("전체 해제")
        self.deselect_all_btn.clicked.connect(lambda: self._set_all_vars(False))
        self.var_count_label = QLabel("변수를 불러오세요")
        self.var_count_label.setStyleSheet("color: #888;")
        var_btns.addWidget(self.load_vars_btn)
        var_btns.addWidget(self.select_all_btn)
        var_btns.addWidget(self.deselect_all_btn)
        var_btns.addStretch()
        var_btns.addWidget(self.var_count_label)
        var_outer.addLayout(var_btns)

        self.var_scroll = QScrollArea()
        self.var_scroll.setWidgetResizable(True)
        self.var_scroll.setMinimumHeight(140)
        self.var_container = QWidget()
        self.var_container.setStyleSheet("background-color: #2b2b2b;")
        self.var_grid = QGridLayout(self.var_container)
        self.var_grid.setSpacing(6)
        self.var_grid.setContentsMargins(10, 10, 10, 10)
        self.var_scroll.setWidget(self.var_container)
        var_outer.addWidget(self.var_scroll)
        root.addWidget(var_group, 1)

        # --- 4. 출력 설정 ---
        out_group = QGroupBox("4. 출력 설정")
        out_layout = QGridLayout(out_group)
        out_layout.addWidget(QLabel("포맷:"), 0, 0)
        fmt_widget = QWidget()
        fmt_layout = QHBoxLayout(fmt_widget)
        fmt_layout.setContentsMargins(0, 0, 0, 0)
        self.fmt_group = QButtonGroup(self)
        self.radio_vtm = QRadioButton("VTM (Merge Blocks X · multi-block)")
        self.radio_vtu = QRadioButton("VTU (Merge Blocks O · 단일 grid)")
        self.radio_vtm.setChecked(True)   # 기본값: VTM
        self.fmt_group.addButton(self.radio_vtm)
        self.fmt_group.addButton(self.radio_vtu)
        fmt_layout.addWidget(self.radio_vtm)
        fmt_layout.addWidget(self.radio_vtu)
        fmt_layout.addStretch()
        out_layout.addWidget(fmt_widget, 0, 1, 1, 2)

        # 폴더명 접두사 (변환 순서대로 _001, _002 부여)
        out_layout.addWidget(QLabel("폴더명:"), 1, 0)
        self.folder_prefix_edit = QLineEdit()
        self.folder_prefix_edit.setText(DEFAULT_FOLDER_PREFIX)
        self.folder_prefix_edit.setPlaceholderText(
            "예: Design → Design_001, Design_002 … (비우면 입력 파일명 기반)")
        out_layout.addWidget(self.folder_prefix_edit, 1, 1, 1, 2)

        # 출력 위치 옵션
        out_layout.addWidget(QLabel("출력 위치:"), 2, 0)
        self.output_mode = QComboBox()
        self.output_mode.addItems([
            "입력 파일과 같은 폴더",
            "지정 폴더에 모아서 저장",
        ])
        self.output_mode.currentIndexChanged.connect(self._on_output_mode_changed)
        out_layout.addWidget(self.output_mode, 2, 1, 1, 2)

        # 지정 출력 폴더 (옵션)
        self.outdir_label = QLabel("출력 폴더:")
        self.outdir_edit = QLineEdit()
        self.outdir_edit.setPlaceholderText("모아서 저장할 폴더 (지정 모드에서만)")
        self.outdir_btn = QPushButton("찾아보기")
        self.outdir_btn.clicked.connect(self._browse_outdir)
        out_layout.addWidget(self.outdir_label, 3, 0)
        out_layout.addWidget(self.outdir_edit, 3, 1)
        out_layout.addWidget(self.outdir_btn, 3, 2)
        # 초기에는 비활성 (같은 폴더 모드가 기본)
        self._set_outdir_enabled(False)
        root.addWidget(out_group)

        # --- 5. 실행 + 진행률 ---
        run_layout = QHBoxLayout()
        self.run_btn = QPushButton("변환 실행")
        self.run_btn.setMinimumHeight(40)
        rf = QFont(); rf.setBold(True)
        self.run_btn.setFont(rf)
        self.run_btn.clicked.connect(self._run_batch)
        self.cancel_btn = QPushButton("중단")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        run_layout.addWidget(self.run_btn, 2)
        run_layout.addWidget(self.cancel_btn, 1)
        root.addLayout(run_layout)

        # 전체 진행률
        prog_layout = QVBoxLayout()
        self.overall_label = QLabel("전체 진행: 대기 중")
        self.overall_label.setStyleSheet("color: #d0d0d0;")
        prog_layout.addWidget(self.overall_label)
        self.overall_progress = QProgressBar()
        self.overall_progress.setValue(0)
        prog_layout.addWidget(self.overall_progress)
        root.addLayout(prog_layout)

        # --- 6. boundary_conditions.json 생성 (Stochos DIM-GP · 선택) ---
        self._build_bc_group(root)

        # --- 7. 콘솔 ---
        console_group = QGroupBox("콘솔 출력 (동일 내용이 로그 파일에 실시간 기록됨)")
        console_layout = QVBoxLayout(console_group)

        # 로그 파일 행: 경로 표시 + 열기 버튼 (콘솔이 작아도 외부에서 실시간 확인 가능)
        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("로그 파일:"))
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

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        cf = QFont("Consolas"); cf.setStyleHint(QFont.Monospace); cf.setPointSize(9)
        self.console.setFont(cf)
        self.console.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; }"
        )
        console_layout.addWidget(self.console)
        root.addWidget(console_group, 1)

        self._apply_dark_theme()

    # --------------------------------------------------------
    # 다크 테마
    # --------------------------------------------------------
    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; }
            QGroupBox {
                color: #e0e0e0; border: 1px solid #444;
                border-radius: 6px; margin-top: 8px; padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLabel { color: #d0d0d0; }
            QLineEdit {
                background-color: #3c3c3c; color: #e0e0e0;
                border: 1px solid #555; border-radius: 4px; padding: 5px;
            }
            QLineEdit:focus { border: 1px solid #0078d4; }
            QComboBox {
                background-color: #3c3c3c; color: #e0e0e0;
                border: 1px solid #555; border-radius: 4px; padding: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #3c3c3c; color: #e0e0e0;
                selection-background-color: #0078d4;
            }
            QPushButton {
                background-color: #3c3c3c; color: #e0e0e0;
                border: 1px solid #555; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #484848; }
            QPushButton:pressed { background-color: #0078d4; }
            QPushButton:disabled { color: #666; background-color: #333; }
            QCheckBox, QRadioButton { color: #d0d0d0; }
            QCheckBox::indicator, QRadioButton::indicator {
                width: 15px; height: 15px;
                border: 1px solid #666; border-radius: 3px; background-color: #3c3c3c;
            }
            QCheckBox::indicator:checked {
                background-color: #0078d4; border: 1px solid #0078d4; image: none;
            }
            QCheckBox::indicator:hover, QRadioButton::indicator:hover {
                border: 1px solid #0078d4;
            }
            QRadioButton::indicator { border-radius: 8px; }
            QRadioButton::indicator:checked {
                background-color: #0078d4; border: 4px solid #3c3c3c;
            }
            QProgressBar {
                border: 1px solid #555; border-radius: 4px;
                text-align: center; color: #fff; background-color: #3c3c3c;
                min-height: 22px;
            }
            QProgressBar::chunk { background-color: #0078d4; border-radius: 3px; }
            QScrollArea { border: 1px solid #444; border-radius: 4px; }
            /* 알림창(QMessageBox): 밝은 배경 + 검은색 글자 */
            QMessageBox { background-color: #f0f0f0; }
            QMessageBox QLabel { color: #000000; }
            QMessageBox QPushButton {
                color: #000000; background-color: #e0e0e0;
                border: 1px solid #999; border-radius: 4px;
                padding: 6px 12px; min-width: 64px;
            }
            QMessageBox QPushButton:hover { background-color: #d4d4d4; }
            QMessageBox QPushButton:pressed { background-color: #bcbcbc; }
        """)

    # --------------------------------------------------------
    # ParaView 경로
    # --------------------------------------------------------
    def _auto_detect_pvpython(self):
        path = find_pvpython()
        if path:
            self.pvpython_edit.setText(path)
            self._log("[GUI] pvpython 자동 탐지: %s" % path)
        else:
            self._log("[GUI] pvpython을 찾지 못했습니다. 수동으로 지정하세요.")

    def _browse_pvpython(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "pvpython 실행 파일 선택", "",
            "실행 파일 (pvpython.exe pvpython);;모든 파일 (*)"
        )
        if path:
            self.pvpython_edit.setText(path)

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
            if path.is_file():
                cff_files.append(str(path))
        cff_files.sort()

        self.cff_files = cff_files
        self.file_list.clear()

        if not cff_files:
            self.file_count_label.setText("⚠️  .cas.h5 파일을 찾지 못했습니다")
            self.file_count_label.setStyleSheet("color: #e0a030;")
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
        self.file_count_label.setStyleSheet("color: #4ec9b0;")
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
    def _load_variables(self):
        pvpython = self.pvpython_edit.text().strip()
        if not pvpython or not os.path.exists(pvpython):
            QMessageBox.warning(self, "경고", "pvpython 경로가 올바르지 않습니다.")
            return
        if not self.cff_files:
            QMessageBox.warning(self, "경고", "먼저 폴더를 스캔하여 CFF 파일을 찾으세요.")
            return

        first_file = self.cff_files[0]
        self._log("[GUI] 첫 파일로 변수 불러오는 중: %s" % Path(first_file).name)
        self.load_vars_btn.setEnabled(False)
        self.load_vars_btn.setText("불러오는 중...")

        self.loader = VariableLoader(pvpython, first_file)
        self.loader.finished_ok.connect(self._on_vars_loaded)
        self.loader.finished_err.connect(self._on_vars_error)
        self.loader.start()

    def _on_vars_loaded(self, data):
        self.load_vars_btn.setEnabled(True)
        self.load_vars_btn.setText("첫 파일로 변수 불러오기")
        cell_arrays = data.get("cell_arrays", [])
        self._populate_variables(cell_arrays)
        self._log("[GUI] 변수 %d개 로드 완료 (Cell Data)" % len(cell_arrays))

    def _on_vars_error(self, msg):
        self.load_vars_btn.setEnabled(True)
        self.load_vars_btn.setText("첫 파일로 변수 불러오기")
        self._log("[ERROR] 변수 로딩 실패: %s" % msg)
        QMessageBox.critical(self, "오류", "변수 로딩 실패:\n%s" % msg)

    def _populate_variables(self, arrays):
        """체크박스 동적 생성 (3열). 선택 시 파란색 강조."""
        for cb in self.var_checkboxes:
            cb.deleteLater()
        self.var_checkboxes = []
        cols = 3
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
            checkbox.setStyleSheet("QCheckBox { color: #4ea3f0; font-weight: 500; }")
        else:
            checkbox.setStyleSheet("QCheckBox { color: #b0b0b0; font-weight: 400; }")

    def _set_all_vars(self, checked):
        for cb in self.var_checkboxes:
            cb.setChecked(checked)

    def _selected_variables(self):
        return [cb.text() for cb in self.var_checkboxes if cb.isChecked()]

    # --------------------------------------------------------
    # 배치 변환 실행
    # --------------------------------------------------------
    def _run_batch(self):
        pvpython = self.pvpython_edit.text().strip()
        selected = self._selected_variables()

        # 검증
        if not pvpython or not os.path.exists(pvpython):
            QMessageBox.warning(self, "경고", "pvpython 경로가 올바르지 않습니다.")
            return
        if not self.cff_files:
            QMessageBox.warning(self, "경고", "변환할 CFF 파일이 없습니다. 폴더를 스캔하세요.")
            return
        if not selected:
            QMessageBox.warning(self, "경고", "저장할 변수를 하나 이상 선택하세요.")
            return

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
        out_format = "vtu" if self.radio_vtu.isChecked() else "vtm"

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
            # VTU는 out_path가 Results.vtu, VTM은 out_path가 .vtm → 둘 다 존재 확인 대상
            if os.path.exists(out_path):
                overwrite_count += 1

        # 확인 다이얼로그 (폴더명 예시 포함)
        if prefix:
            example = "%s_%s" % (prefix, "1".zfill(FOLDER_NUM_WIDTH))
            dp_ex = "%s_%s" % (prefix, "016")
            naming = ("폴더명: %s, %s … (내부 파일: %s.vtu)\n"
                      "  · 파일명에 DP 번호가 있으면 그 번호 사용 (dp_016 → %s)") % (
                example, "%s_%s" % (prefix, "2".zfill(FOLDER_NUM_WIDTH)),
                UNIFIED_VTU_NAME, dp_ex)
        else:
            naming = "폴더명: 입력 파일명 기반(<파일명>%s), 내부 파일: %s.vtu" % (
                EXPORT_SUFFIX, UNIFIED_VTU_NAME)
        overwrite_line = ""
        if overwrite_count > 0:
            overwrite_line = "\n⚠ 기존 출력 %d개를 덮어씁니다." % overwrite_count
        reply = QMessageBox.question(
            self, "배치 변환 확인",
            "%d개 파일을 변환합니다.\n변수: %d개, 포맷: %s\n%s%s\n\n계속하시겠습니까?" % (
                len(self.cff_files), len(selected),
                "VTU" if self.radio_vtu.isChecked() else "VTM", naming, overwrite_line
            ),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 배치 상태 초기화
        self.selected_vars = selected
        self.out_format = out_format
        self.batch_pvpython = pvpython  # 배치 동안 사용할 pvpython 고정 (중간 변경 무시)
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
        self.overall_progress.setMaximum(self.batch_total)
        self.overall_progress.setValue(0)

        self._log("\n" + "=" * 60)
        self._log("[GUI] 배치 변환 시작: %d개 파일, %s 포맷, 변수 %d개" % (
            self.batch_total, self.out_format.upper(), len(selected)))
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
        - VTM: <parent>/<folder>.vtm (+ <folder>/Results.vtu, 내부는 워커가 통일)
        parent = 지정 폴더(모아서 저장) 또는 입력 파일과 같은 폴더
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
        else:
            return str(parent / ("%s.vtm" % folder))

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
        pvpython = self.batch_pvpython  # 배치 시작 시 캡처한 경로 사용 (중간 변경 무시)

        self.overall_label.setText(
            "전체 진행: %d / %d  (성공 %d, 실패 %d)  —  현재: %s" % (
                n, self.batch_total, self.batch_success, self.batch_failed,
                Path(case_file).name))

        # 출력 경로 계산 + 폴더 생성 (실패 시 이 파일만 건너뛰고 다음으로 진행)
        try:
            output_path = self._build_output_path(case_file, n, self._batch_folders)
            # 대상 표시: VTU는 폴더/Results.vtu, VTM은 <folder>.vtm
            op = Path(output_path)
            target_disp = "%s/%s" % (op.parent.name, op.name) if self.out_format == "vtu" else op.name
            self._log("\n[%d/%d] %s → %s" % (
                n, self.batch_total, Path(case_file).name, target_disp))
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
            WORKER_SCRIPT,
            "--case", case_file,
            "--output", output_path,
            "--format", self.out_format,
            "--vars", ",".join(self.selected_vars),
        ]
        # --inner-name은 VTM일 때만 필요 (VTU는 GUI가 경로로 Results.vtu를 지정)
        if self.out_format == "vtm":
            args += ["--inner-name", UNIFIED_VTU_NAME]

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        # 한글 로그 깨짐 방지: 워커의 stdout 인코딩을 utf-8로 강제
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.errorOccurred.connect(self._on_process_error)
        self.process.finished.connect(self._on_file_finished)
        self.process.start(pvpython, args)

    def _on_process_error(self, error):
        """QProcess 시작 실패(FailedToStart) 처리. 그 외 에러는 finished가 처리."""
        if error != QProcess.FailedToStart:
            return
        # finished와의 이중 처리 방지 (이미 정리되었으면 무시)
        if self.process is None:
            return
        self._log("[GUI] ✗ 프로세스 시작 실패 (pvpython 경로 확인)")
        self.batch_failed += 1
        self.process = None
        self.batch_index += 1
        self.overall_progress.setValue(self.batch_index)
        QTimer.singleShot(0, self._process_next)

    def _on_process_output(self):
        if self.process is None:
            return
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="replace")
        for line in text.splitlines():
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

    def _on_file_finished(self, exit_code, exit_status):
        if exit_code == 0:
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
        # 진행 중인 프로세스 종료
        if self.process is not None:
            self.process.finished.disconnect()
            self.process.kill()
            self.process = None
        # 대기열 비우기
        self.batch_index = self.batch_total
        self.run_btn.setEnabled(True)
        self.run_btn.setText("변환 실행")
        self.cancel_btn.setEnabled(False)
        self._log("\n[GUI] 사용자가 배치 변환을 중단했습니다.")
        self.overall_label.setText("중단됨 (성공 %d, 실패 %d)" % (
            self.batch_success, self.batch_failed))

    # --------------------------------------------------------
    # boundary_conditions.json 생성 (Stochos DIM-GP · 선택)
    # --------------------------------------------------------
    def _build_bc_group(self, root):
        bc_group = QGroupBox("6. boundary_conditions.json 생성 (Stochos DIM-GP · 선택)")
        g = QGridLayout(bc_group)

        # 설계 테이블 CSV
        g.addWidget(QLabel("설계 테이블 CSV:"), 0, 0)
        self.bc_csv_edit = QLineEdit()
        self.bc_csv_edit.setPlaceholderText("optiSLang 설계 테이블 CSV (구분자 자동 감지)")
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
        opt.addWidget(QLabel("설계번호 열:"))
        self.bc_designcol_edit = QLineEdit(bc_json_gen.DEFAULT_DESIGN_COL_HINT)
        self.bc_designcol_edit.setFixedWidth(60)
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
        g.addWidget(QLabel("파라미터 매핑:"), 3, 0)
        self.bc_params_edit = QPlainTextEdit()
        self.bc_params_edit.setPlaceholderText(
            "json_key = CSV열  (한 줄에 하나, 위→아래 순서가 X_global_feat 열 순서)")
        default_params = "\n".join(
            "%s = %s" % (k, v) for k, v in bc_json_gen.DEFAULT_PARAM_COLS.items())
        self.bc_params_edit.setPlainText(default_params)
        self.bc_params_edit.setFixedHeight(72)
        cf = QFont("Consolas"); cf.setStyleHint(QFont.Monospace)
        self.bc_params_edit.setFont(cf)
        self.bc_params_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #252525; color: #d4d4d4; }")
        g.addWidget(self.bc_params_edit, 3, 1, 1, 2)

        # 누락 기준설계(DP0) 직접 입력 — optiSLang이 기준설계를 CSV로 내보내지 않을 때
        man_widget = QWidget()
        man = QHBoxLayout(man_widget); man.setContentsMargins(0, 0, 0, 0)
        self.bc_manual_cb = QCheckBox("누락 기준설계(DP0) 값 직접 입력")
        self.bc_manual_cb.setChecked(False)
        man.addWidget(self.bc_manual_cb)
        man.addSpacing(12)
        man.addWidget(QLabel("설계번호:"))
        self.bc_manual_num_spin = QSpinBox()
        self.bc_manual_num_spin.setRange(0, 100000)
        self.bc_manual_num_spin.setValue(0)
        man.addWidget(self.bc_manual_num_spin)
        man.addStretch()
        g.addWidget(man_widget, 4, 1, 1, 2)

        g.addWidget(QLabel("기준설계 값:"), 5, 0)
        self.bc_manual_edit = QPlainTextEdit()
        self.bc_manual_edit.setPlaceholderText(
            "json_key = 값  (파라미터 매핑의 키와 동일, 한 줄에 하나)")
        default_manual = "\n".join("%s = " % k for k in bc_json_gen.DEFAULT_PARAM_COLS)
        self.bc_manual_edit.setPlainText(default_manual)
        self.bc_manual_edit.setFixedHeight(72)
        self.bc_manual_edit.setFont(cf)
        self.bc_manual_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #252525; color: #d4d4d4; }")
        g.addWidget(self.bc_manual_edit, 5, 1, 1, 2)

        # 체크 시에만 활성화
        def _toggle_manual(on):
            self.bc_manual_num_spin.setEnabled(on)
            self.bc_manual_edit.setEnabled(on)
        self.bc_manual_cb.toggled.connect(_toggle_manual)
        _toggle_manual(False)

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

    def _browse_bc_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "설계 테이블 CSV 선택", "", "CSV 파일 (*.csv);;모든 파일 (*)")
        if path:
            self.bc_csv_edit.setText(path)

    def _browse_bc_root(self):
        start = self.outdir_edit.text().strip()
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
        if not params:
            raise ValueError("파라미터 매핑이 비어 있습니다.")
        return params

    def _parse_bc_manual(self):
        """기준설계 값 텍스트 → 순서 보존 {json_key: 값문자열}. 형식 오류 시 ValueError."""
        values = {}
        for lineno, raw in enumerate(self.bc_manual_edit.toPlainText().splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("%d번째 줄 형식 오류('json_key = 값' 필요): %s" % (lineno, raw))
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if not key or not val:
                raise ValueError("%d번째 줄에 빈 값이 있습니다: %s" % (lineno, raw))
            if key in values:
                raise ValueError("중복된 json_key: %s" % key)
            values[key] = val
        if not values:
            raise ValueError("기준설계 값이 비어 있습니다.")
        return values

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

        manual_designs = {}
        if self.bc_manual_cb.isChecked():
            try:
                manual_values = self._parse_bc_manual()
            except ValueError as e:
                QMessageBox.warning(self, "경고", "기준설계 값 오류:\n%s" % e)
                return
            missing = [k for k in param_cols if k not in manual_values]
            extra = [k for k in manual_values if k not in param_cols]
            if missing or extra:
                msg = "기준설계 값의 키가 파라미터 매핑과 일치해야 합니다."
                if missing:
                    msg += "\n누락된 키: %s" % ", ".join(missing)
                if extra:
                    msg += "\n매핑에 없는 키: %s" % ", ".join(extra)
                QMessageBox.warning(self, "경고", msg)
                return
            manual_designs = {self.bc_manual_num_spin.value(): manual_values}

        if not dry_run:
            reply = QMessageBox.question(
                self, "JSON 생성 확인",
                "설계 폴더에 boundary_conditions.json%s을 생성합니다.\n"
                "기존 파일은 덮어써집니다.\n\n계속하시겠습니까?" % (
                    " + design_info.json" if self.bc_sidecar_cb.isChecked() else ""),
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
            manual_designs=manual_designs,
            dry_run=dry_run,
        )

        self._log("\n" + "=" * 60)
        self._log("[BC-JSON] %s 시작" % ("미리보기(DRY-RUN)" if dry_run else "생성"))
        self._log("=" * 60)

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
        summary = ("boundary_conditions.json %s\n\n"
                   "생성 대상: %d개\n"
                   "폴더 없음(CSV에만): %d개\n"
                   "CSV 없음(폴더에만): %d개\n"
                   "값 변환 실패: %d개\n"
                   "쓰기 실패: %d개\n"
                   "키 순서 일관성: %s\n"
                   "구분자: %r") % (
            action, len(report.written), len(report.no_folder),
            len(report.folder_only), len(report.bad_value),
            len(report.write_failed),
            "통과" if report.key_order_ok else "불일치", report.delimiter)
        if dry_run and report.written:
            summary += "\n\n※ DRY-RUN이라 파일은 생성되지 않았습니다. [JSON 생성]으로 실제 생성하세요."
        if report.write_failed:
            # 일부 폴더만 JSON 생성 → 학습 루트에 키집합 불일치 위험. 반드시 경고로 노출.
            summary += ("\n\n⚠ 일부 폴더 쓰기에 실패해 데이터셋이 부분 생성되었습니다.\n"
                        "학습 전 콘솔 로그의 '쓰기 실패' 목록을 확인하고 재생성하세요.")
            QMessageBox.warning(self, action + " (부분 생성)", summary)
        else:
            QMessageBox.information(self, action, summary)

    # --------------------------------------------------------
    # 콘솔 로그
    # --------------------------------------------------------
    def _log(self, msg):
        self.console.appendPlainText(msg)
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())
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


# ============================================================
# 메인 윈도우 (탭 호스트)
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(900, 860)

        self.converter = ConverterTab()
        self.dp_tab = DPCollectTab()

        tabs = QTabWidget()
        tabs.addTab(self.dp_tab, "Workbench DP 정리")
        tabs.addTab(self.converter, "CFF To VTK 변환기")
        self.setCentralWidget(tabs)

        # 변환기 탭이 구성한 다크 테마를 앱 전체(탭 바 + 모든 탭 + QMessageBox)에 적용
        self.setStyleSheet(self.converter.styleSheet() + TAB_QSS)

    def closeEvent(self, event):
        # 각 탭의 백그라운드 작업을 정리한 뒤 종료 (로딩/변환 중 크래시 방지)
        self.converter.shutdown()
        self.dp_tab.shutdown()
        session_log.close_session_log()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    log_path = session_log.init_session_log()   # 콘솔 출력을 실시간 기록할 세션 로그 파일
    window = MainWindow()
    if log_path:
        window.converter._log("로그 파일: %s" % log_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
