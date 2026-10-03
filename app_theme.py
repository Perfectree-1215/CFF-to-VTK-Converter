"""
앱 공통 테마 — Solarized Light (v2.0, 사용자 지시서 수정사항-01.pptx)
Author: 퍼팩트리

pv_export_gui.py(모든 탭)와 dp_collect_tab.py 가 import 한다. 색·글꼴은 전부 이 파일의 QSS 한 곳에서 관리하고,
개별 위젯은 인라인 setStyleSheet 대신 **역할(role) 속성**으로 모양을 고른다:

    set_role(label, "hint")      # 보조 설명 (연한 회색)
    set_role(label, "ok")        # 정상 상태 (초록)
    set_role(label, "warn")      # 주의 (주황)
    set_role(label, "error")     # 오류 (빨강)
    set_role(label, "title")     # 탭 제목
    set_role(button, "primary")  # 실행 버튼 (파랑 바탕)
    set_role(button, "danger")   # 중단 버튼 (빨강 테두리)
    set_role(console, "console") # 로그 콘솔 (고정폭)

콘솔 로그는 append_log(console, msg) 로 쓰면 [ERROR]/[WARN]/[완료] 줄에 색이 붙는다.
글자 크기: 본문 12pt, 보조 11.5pt, 그룹·탭 12.5pt, 제목 18pt, 실행 버튼 13pt. 콘솔 출력만 9.5pt 고정 (사용자 요청 2026-10-03).
"""
from string import Template

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

BASE_FONT_PT = 12   # 본문 글자 크기 (QSS 의 QWidget font-size 와 같게 유지). 고정 폭 입력란의 폭 계산에 쓴다

# Solarized 팔레트 (Ethan Schoonover). Light 테마: 배경 base3/base2, 본문 base00, 강조 base01, 보조 base1
SOLARIZED = {
    "base03": "#002b36", "base02": "#073642", "base01": "#586e75", "base00": "#657b83",
    "base0": "#839496", "base1": "#93a1a1", "base2": "#eee8d5", "base3": "#fdf6e3",
    "yellow": "#b58900", "orange": "#cb4b16", "red": "#dc322f", "magenta": "#d33682",
    "violet": "#6c71c4", "blue": "#268bd2", "cyan": "#2aa198", "green": "#859900",
}

# 의미별 색 (코드에서 색이 필요할 때 — 표 셀 전경색 등).
# 글자색은 사용자 요청(가독성)에 따라 Solarized 의 가장 어두운 쪽을 쓴다: 본문 base02(#073642, 거의 검정), 강조 base03, 보조 base01.
# 상태색(초록·주황·빨강·파랑 글자)은 원색이 밝은 배경에서 대비 2.6~3.5:1 에 그치므로 같은 색조로 어둡게 (base2 위 4.3:1 이상).
COLOR_TEXT = SOLARIZED["base02"]
COLOR_HINT = SOLARIZED["base01"]
COLOR_OK = "#5f7300"            # Solarized green 을 어둡게
COLOR_WARN = "#a63d10"          # orange 를 어둡게
COLOR_ERROR = "#c0211e"         # red 를 어둡게
COLOR_ACCENT_TEXT = "#1b6ca8"   # 밝은 배경 위 파랑 글자 (체크된 변수, 선택 탭)
COLOR_LINE = "#d9d2bb"            # 카드·입력란 테두리 (base2 와 base1 사이의 중간 톤)
COLOR_ACCENT_HOVER = "#1f7bbf"    # 파랑 버튼 hover

_QSS = Template("""
/* ---------- 바탕·글꼴 ---------- */
QWidget { color: $base02; font-size: 12pt; }
QMainWindow, QDialog, QFileDialog { background-color: $base3; }
QToolTip { background-color: $base02; color: $base2; border: 1px solid $base01; padding: 5px; font-size: 11.5pt; }

/* ---------- 탭 ---------- */
QTabWidget::pane { background-color: $base3; border: 1px solid $line; border-radius: 0 6px 6px 6px; top: -1px; }
QTabBar::tab {
    background: $base2; color: $base02; padding: 9px 22px; margin-right: 3px;
    border: 1px solid $line; border-bottom: none;
    border-top-left-radius: 7px; border-top-right-radius: 7px;
    font-size: 12.5pt; font-weight: 600;
}
QTabBar::tab:selected { background: $base3; color: $accent_text; border-top: 3px solid $blue; padding-top: 7px; }
QTabBar::tab:hover:!selected { background: $base3; color: $base03; }

/* ---------- 그룹 카드 ---------- */
QGroupBox {
    background-color: $base2; border: 1px solid $line; border-radius: 9px;
    margin-top: 12px; padding: 13px 10px 8px 10px;
    font-size: 12.5pt; font-weight: 700; color: $base03;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; top: 3px; padding: 0 7px; background-color: $base3; border-radius: 4px;
}

/* ---------- 라벨 역할 ---------- */
QLabel { color: $base02; background: transparent; }
QLabel[role="title"] { font-size: 18pt; font-weight: 700; color: $base03; }
QLabel[role="subtitle"] { font-size: 11.5pt; color: $base01; }
QLabel[role="hint"] { font-size: 11.5pt; color: $base01; }
QLabel[role="ok"] { color: $ok; font-weight: 700; }
QLabel[role="warn"] { color: $warn; font-weight: 700; }
QLabel[role="error"] { color: $error; font-weight: 700; }
QLabel[role="status"] { color: $base03; font-weight: 700; }
QLabel[role="field"] { color: $base03; font-weight: 700; }

/* ---------- 입력 ---------- */
QLineEdit, QComboBox, QSpinBox {
    background-color: $base3; color: $base02;
    border: 1px solid $line; border-radius: 6px; padding: 5px 7px;
    selection-background-color: $blue; selection-color: $base3;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid $blue; }
QLineEdit:read-only { color: $base02; background-color: $base2; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $base00; background-color: $base2; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: $base3; color: $base02; border: 1px solid $line;
    selection-background-color: $blue; selection-color: $base3; outline: none;
}

/* ---------- 버튼 ---------- */
QPushButton {
    background-color: $base3; color: $base02;
    border: 1px solid $base1; border-radius: 6px; padding: 6px 14px; font-weight: 600;
}
QPushButton:hover { border: 1px solid $blue; color: $accent_text; }
QPushButton:pressed { background-color: $base2; }
QPushButton:disabled { color: $base00; border: 1px solid $line; background-color: $base2; }
QPushButton[role="primary"] {
    background-color: $blue; color: $base3; border: 1px solid $blue;
    font-size: 13pt; font-weight: 700; padding: 10px 14px;
}
QPushButton[role="primary"]:hover { background-color: $accent_hover; color: $base3; }
QPushButton[role="primary"]:pressed { background-color: $base02; }
QPushButton[role="primary"]:disabled { background-color: $base1; color: $base3; border: 1px solid $base1; }
QPushButton[role="danger"] { color: $error; border: 1px solid $error; font-weight: 700; padding: 8px 14px; }
QPushButton[role="danger"]:hover { background-color: $error; color: $base3; }
QPushButton[role="danger"]:disabled { color: $base00; border: 1px solid $line; background-color: $base2; }

/* ---------- 체크·라디오 ---------- */
QCheckBox, QRadioButton { color: $base02; spacing: 7px; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px; border: 1px solid $base1; border-radius: 4px; background-color: $base3;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border: 1px solid $blue; }
QCheckBox::indicator:checked { background-color: $blue; border: 1px solid $blue; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { border: 1px solid $line; background-color: $base2; }
QRadioButton::indicator { border-radius: 8px; }
QRadioButton::indicator:checked { background-color: $blue; border: 1px solid $blue; }
QRadioButton:checked { color: $base03; font-weight: 700; }

/* ---------- 진행바 ---------- */
QProgressBar {
    border: 1px solid $line; border-radius: 6px; background-color: $base3;
    text-align: center; color: $base03; font-weight: 700; min-height: 24px;
}
QProgressBar::chunk { background-color: $blue; border-radius: 5px; }

/* ---------- 목록·표·스크롤·콘솔 ---------- */
QScrollArea { background-color: $base3; border: 1px solid $line; border-radius: 6px; }
QScrollArea#tabScroll { border: none; background-color: $base3; }   /* 탭 전체를 담는 스크롤 (작은 화면용) */
QScrollArea > QWidget > QWidget { background-color: $base3; }
QListWidget, QTableWidget, QPlainTextEdit, QTextEdit {
    background-color: $base3; color: $base02; border: 1px solid $line; border-radius: 6px;
    alternate-background-color: $base2;
    selection-background-color: $blue; selection-color: $base3;
}
QTableWidget { gridline-color: $line; }
QHeaderView::section {
    background-color: $base2; color: $base03; border: none; border-bottom: 1px solid $line;
    padding: 5px; font-weight: 700;
}
QHeaderView::section:hover { background-color: $base3; }
QPlainTextEdit[role="console"] { font-family: Consolas, "D2Coding", "Courier New", monospace; font-size: 9.5pt; color: $base02; }   /* 콘솔 출력은 크기 유지(사용자 요청), 색만 진하게 */
QPlainTextEdit[role="mono"] { font-family: Consolas, "D2Coding", "Courier New", monospace; font-size: 11.5pt; color: $base02; }      /* 고정폭 입력란 (bc_json 파라미터) */

/* ---------- 알림창 ---------- */
QMessageBox { background-color: $base3; }
QMessageBox QLabel { color: $base03; font-size: 12pt; }
QMessageBox QPushButton { min-width: 72px; }
""")

APP_QSS = _QSS.substitute(SOLARIZED, line=COLOR_LINE, accent_hover=COLOR_ACCENT_HOVER, accent_text=COLOR_ACCENT_TEXT,
                          ok=COLOR_OK, warn=COLOR_WARN, error=COLOR_ERROR)


class ConsoleEdit(QPlainTextEdit):
    """로그 콘솔. QPlainTextEdit 의 기본 선호 높이(192px)는 작은 화면에서 탭 페이지를 길게 만들어 세로 스크롤을 부르므로
    선호 높이를 낮춘다. 큰 화면에서는 레이아웃 stretch 로 남는 공간을 전부 받는다."""
    def sizeHint(self):
        return QSize(480, 110)


def set_role(widget, role):
    """위젯의 role 속성을 바꾸고 스타일을 다시 적용한다 (QSS 의 [role="…"] 선택자가 반응)."""
    if widget.property("role") == role:
        return
    widget.setProperty("role", role)
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


# 콘솔 줄 색: 접두사(앞뒤 공백 무시)로 판정. 순서가 우선순위.
_LOG_RULES = (
    (("[ERROR]", "[실패]", "Traceback", "ERROR:"), COLOR_ERROR),
    (("[WARN]", "[주의]", "[경고]", "WARNING"), COLOR_WARN),
    (("[완료]", "[SUCCESS]", "[OK]", "✅"), COLOR_OK),
    (("[GUI]", "[스캔]", "[VERIFY]", "[RENAME]"), COLOR_HINT),
)


def log_color(msg):
    s = msg.lstrip()
    for prefixes, color in _LOG_RULES:
        if s.startswith(prefixes):
            return color
    return None


def append_log(console, msg):
    """QPlainTextEdit 에 한 줄 추가 (appendPlainText 와 같은 단락 추가) + 종류별 색. 끝으로 스크롤."""
    color = log_color(msg)
    doc = console.document()
    cursor = QTextCursor(doc)
    cursor.movePosition(QTextCursor.End)
    if not (doc.blockCount() == 1 and doc.firstBlock().length() <= 1):
        cursor.insertBlock()
    fmt = QTextCharFormat()
    if color:
        fmt.setForeground(QColor(color))
    cursor.insertText(msg, fmt)
    sb = console.verticalScrollBar()
    sb.setValue(sb.maximum())


def apply_palette(app):
    """QSS 가 닿지 않는 요소(스크롤바, 스핀박스 화살표, 네이티브 대화상자 일부)도 라이트로. Windows 다크 모드 영향 차단."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    S = SOLARIZED
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except Exception:
        pass
    p = QPalette()
    roles = {
        QPalette.Window: S["base3"], QPalette.WindowText: S["base02"],
        QPalette.Base: S["base3"], QPalette.AlternateBase: S["base2"],
        QPalette.Text: S["base02"], QPalette.PlaceholderText: S["base01"],
        QPalette.Button: S["base2"], QPalette.ButtonText: S["base02"],
        QPalette.Highlight: S["blue"], QPalette.HighlightedText: S["base3"],
        QPalette.ToolTipBase: S["base02"], QPalette.ToolTipText: S["base2"],
        QPalette.Link: S["blue"], QPalette.LinkVisited: S["violet"],
        QPalette.Light: "#ffffff", QPalette.Midlight: S["base2"], QPalette.Mid: COLOR_LINE,
        QPalette.Dark: S["base1"], QPalette.Shadow: S["base01"], QPalette.BrightText: S["red"],
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(S["base00"]))
    app.setPalette(p)
