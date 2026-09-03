"""
Workbench Design Point Case/Data 수집·이름변경 도구
Author: 퍼팩트리

Ansys Workbench 파라메트릭 결과 폴더(...-NNN_files/dp0, dp1, ...)를 스캔하여
각 Design Point의 Fluent Case(.cas.h5)/Data(.dat.h5) 파일을 지정 경로로 복사하면서
DP 번호 제로패딩 이름(dp_000, dp_001, ...)으로 이름을 통일한다.

  - Case/Data 모두 동일 base 로 변경: dp_001.cas.h5 + dp_001.dat.h5
    → 기존 CFF 변환기(워커가 .cas.h5↔.dat.h5 치환 페어링)에 바로 투입 가능
  - Data가 여러 개면 파일명 끝 반복횟수(-1200 등)가 가장 큰 것 선택
  - 저장 구조: (A) 이름별 폴더 생성 / (B) 한 폴더에 모두
  - 완료 후 원본↔변경 매핑 로그(CSV + 요약 txt) 생성

이 탭은 순수 파이썬으로 동작하며 ParaView/pvpython 이 필요 없다.
"""
import csv
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import session_log

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QPlainTextEdit, QProgressBar, QGroupBox,
    QRadioButton, QButtonGroup, QCheckBox, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)

# ============================================================
# 상수 / 패턴
# ============================================================
DP_DIR_RE = re.compile(r"^dp(\d+)$", re.IGNORECASE)      # dp0, dp1, dp15 ...
DP_NUM_WIDTH = 3                                          # 번호 제로패딩 자릿수 (dp_000, dp_016)
                                                         # pv_export_gui.FOLDER_NUM_WIDTH와 자릿수를 맞춰 사용
DATA_ITER_RE = re.compile(r"-(\d+)\.dat\.h5$", re.IGNORECASE)  # ...-1200.dat.h5
CASE_SUFFIX = ".cas.h5"
DATA_SUFFIX = ".dat.h5"
PREFERRED_SUBPATH = ("FFF", "Fluent")  # dp/FFF/Fluent 우선 탐색

STATUS_OK = "정상"
STATUS_NO_CASE = "Case 없음"
STATUS_NO_DATA = "Data 없음"
STATUS_EMPTY = "결과 없음"


# ============================================================
# 탐색/선택 로직 (순수 함수 — Qt 비의존, 단위 테스트 용이)
# ============================================================
def find_dp_dirs(root):
    """root 아래에서 dp<번호> 디렉터리 목록을 반환. 직속 우선, 없으면 재귀."""
    root = Path(root)
    if not root.is_dir():
        return []
    direct = [p for p in root.iterdir() if p.is_dir() and DP_DIR_RE.match(p.name)]
    if direct:
        found = direct
    else:
        found = [p for p in root.rglob("*") if p.is_dir() and DP_DIR_RE.match(p.name)]
    # dp 번호로 자연 정렬 (dp0,1,2,...,9,11,15)
    return sorted(found, key=lambda p: int(DP_DIR_RE.match(p.name).group(1)))


def _find_by_suffix(dp_dir, suffix):
    """dp 폴더에서 특정 확장자 파일 목록. FFF/Fluent 우선, 없으면 재귀."""
    dp_dir = Path(dp_dir)
    preferred = dp_dir.joinpath(*PREFERRED_SUBPATH)
    if preferred.is_dir():
        hits = [p for p in preferred.iterdir()
                if p.is_file() and p.name.lower().endswith(suffix)]
        if hits:
            return sorted(hits)
    # 폴백: 재귀 탐색
    return sorted(p for p in dp_dir.rglob("*")
                  if p.is_file() and p.name.lower().endswith(suffix))


def data_iterations(path, case_bases=None):
    """Data 파일명 끝의 반복횟수(-1200) 정수. 없으면 None.

    case_bases(케이스 base 문자열 리스트, 예 ["FFF.5-1"])가 주어지면 Case
    파일명과 대조해 케이스 인덱스를 반복횟수로 오인하지 않도록 정확히 판정한다.
      - data base 가 어떤 case base 와 정확히 같으면 → None (반복횟수 없음)
      - "case_base-<숫자>" 형태면 → 그 숫자 (긴 base 부터 검사)
      - 매칭되는 case base 가 없으면 → 기존 정규식으로 폴백
    case_bases 가 없으면 종전과 동일하게 정규식만 사용한다.
    """
    name = Path(path).name
    if case_bases:
        # data base 추출 (.dat.h5 제거, 대소문자 무시)
        if name.lower().endswith(DATA_SUFFIX):
            data_base = name[:-len(DATA_SUFFIX)]
        else:
            data_base = name
        # 긴 base 부터 검사 (부분일치로 짧은 base 가 먼저 잡히는 것 방지)
        for cb in sorted(case_bases, key=len, reverse=True):
            if data_base == cb:
                return None
            if data_base.startswith(cb + "-"):
                tail = data_base[len(cb) + 1:]
                if tail.isdigit():
                    return int(tail)
    m = DATA_ITER_RE.search(name)
    return int(m.group(1)) if m else None


def pick_data(data_list, case_bases=None):
    """Data 여러 개 중 반복횟수 최대(동률/미표기 시 mtime 최신) 선택.

    case_bases 가 주어지면 data_iterations 판정에 그대로 전달한다.
    반환: (선택 Path 또는 None, 반복횟수 또는 None, 미선택 리스트)
    """
    if not data_list:
        return None, None, []

    def sort_key(p):
        it = data_iterations(p, case_bases)
        # 반복횟수 우선(없으면 -1), 그다음 mtime
        return (it if it is not None else -1, p.stat().st_mtime)

    ordered = sorted(data_list, key=sort_key, reverse=True)
    chosen = ordered[0]
    return chosen, data_iterations(chosen, case_bases), ordered[1:]


def pick_case(case_list, chosen_data):
    """Case 여러 개면 선택 Data의 base로 시작하는 것 우선, 없으면 mtime 최신.

    반환: (선택 Path 또는 None, 미선택 리스트)
    """
    if not case_list:
        return None, []
    if len(case_list) == 1:
        return case_list[0], []

    chosen = None
    if chosen_data is not None:
        data_base = Path(chosen_data).name[:-len(DATA_SUFFIX)]  # FFF.27-3-1200
        # Case base(FFF.27-3)가 data_base의 접두가 되는 경우 매칭
        for c in case_list:
            c_base = c.name[:-len(CASE_SUFFIX)]
            if data_base == c_base or data_base.startswith(c_base + "-"):
                chosen = c
                break
    if chosen is None:
        chosen = max(case_list, key=lambda p: p.stat().st_mtime)
    rest = [c for c in case_list if c != chosen]
    return chosen, rest


def discover_design_points(root):
    """root 아래 모든 DP를 스캔하여 레코드 목록 반환."""
    records = []
    for dp_dir in find_dp_dirs(root):
        cases = _find_by_suffix(dp_dir, CASE_SUFFIX)
        datas = _find_by_suffix(dp_dir, DATA_SUFFIX)
        # Case base 목록으로 Data 반복횟수를 정확히 판정 (케이스 인덱스 오인 방지)
        case_bases = [c.name[:-len(CASE_SUFFIX)] for c in cases]
        data, iters, unsel_data = pick_data(datas, case_bases)
        case, unsel_case = pick_case(cases, data)

        if case and data:
            status = STATUS_OK
        elif case and not data:
            status = STATUS_NO_DATA
        elif data and not case:
            status = STATUS_NO_CASE
        else:
            status = STATUS_EMPTY

        num = int(DP_DIR_RE.match(dp_dir.name).group(1))
        records.append({
            "dp": dp_dir.name,
            "dp_num": num,
            "dp_dir": dp_dir,
            "case": case,
            "data": data,
            "iterations": iters,
            "unselected_data": unsel_data,
            "unselected_case": unsel_case,
            "status": status,
        })
    return records


# ============================================================
# 이름/경로 규칙
# ============================================================
def dp_padded_name(dp_name, dp_num, width=DP_NUM_WIDTH):
    """DP 폴더명을 제로패딩 형식으로. 예: dp16 → dp_016 (알파 접두 dp/DP 보존)."""
    m = DP_DIR_RE.match(dp_name)
    alpha = dp_name[:m.start(1)] if m else "dp"
    return "%s_%0*d" % (alpha, width, dp_num)


def build_base_name(dp_name, dp_num, prefix, suffix):
    """<prefix>dp_<번호(제로패딩)><suffix> (기본: dp_000, dp_001 …)."""
    return "%s%s%s" % (prefix or "", dp_padded_name(dp_name, dp_num), suffix or "")


def build_targets(out_dir, base, per_folder):
    """(case_dst, data_dst) 경로 산출."""
    out_dir = Path(out_dir)
    folder = out_dir / base if per_folder else out_dir
    return folder / (base + CASE_SUFFIX), folder / (base + DATA_SUFFIX)


# ============================================================
# 복사 스레드
# ============================================================
class DPCollectWorker(QThread):
    progress = Signal(int, int, str)   # done, total, message
    item_done = Signal(dict)           # per-DP 결과
    finished_all = Signal(dict)        # 요약 + 로그 경로

    def __init__(self, records, out_dir, prefix, suffix, per_folder,
                 skip_existing, input_root):
        super().__init__()
        self.records = records
        self.out_dir = Path(out_dir)
        self.prefix = prefix
        self.suffix = suffix
        self.per_folder = per_folder
        self.skip_existing = skip_existing
        self.input_root = input_root
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    @staticmethod
    def _size_mb(path):
        """파일 크기를 MB로 반환. 조회 실패 시 빈 문자열."""
        try:
            return round(Path(path).stat().st_size / 1024**2, 2)
        except Exception:
            return ""

    def _copy_one(self, src, dst):
        """단일 파일 복사. 반환: 'copied' | 'skipped' | 'failed'."""
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if self.skip_existing and dst.exists() and dst.stat().st_size == src.stat().st_size:
                return "skipped"
            shutil.copy2(str(src), str(dst))
            # 크기 검증
            if dst.stat().st_size != src.stat().st_size:
                return "failed"
            return "copied"
        except Exception:
            return "failed"

    def run(self):
        total = len(self.records)
        results = []
        for i, rec in enumerate(self.records, start=1):
            if self._cancel:
                break
            # 레코드 1건 처리 전체를 보호: 어떤 예외가 나도 finished_all 이
            # 방출되지 않아 GUI 가 영구 잠기는 상황을 막는다.
            try:
                base = build_base_name(rec["dp"], rec["dp_num"], self.prefix, self.suffix)
                case_dst, data_dst = build_targets(self.out_dir, base, self.per_folder)

                self.progress.emit(i, total, "%s → %s" % (rec["dp"], base))

                case_res = data_res = "none"
                if rec["case"]:
                    case_res = self._copy_one(rec["case"], case_dst)
                if rec["data"]:
                    data_res = self._copy_one(rec["data"], data_dst)

                parts = [r for r in (case_res, data_res) if r != "none"]
                if not parts:
                    copy_status = "실패"       # 원본 없음
                elif "failed" in parts:
                    copy_status = "실패"
                elif all(p == "skipped" for p in parts):
                    copy_status = "건너뜀"
                elif "copied" in parts and "skipped" in parts:
                    copy_status = "부분(일부 건너뜀)"
                else:
                    copy_status = "성공"

                result = {
                    "dp": rec["dp"], "dp_num": rec["dp_num"], "status": rec["status"],
                    "iterations": rec["iterations"], "copy_status": copy_status,
                    "orig_case": str(rec["case"]) if rec["case"] else "",
                    "orig_case_name": rec["case"].name if rec["case"] else "",
                    "new_case": str(case_dst) if rec["case"] else "",
                    "new_case_name": case_dst.name if rec["case"] else "",
                    "case_mb": self._size_mb(rec["case"]) if rec["case"] else "",
                    "orig_data": str(rec["data"]) if rec["data"] else "",
                    "orig_data_name": rec["data"].name if rec["data"] else "",
                    "new_data": str(data_dst) if rec["data"] else "",
                    "new_data_name": data_dst.name if rec["data"] else "",
                    "data_mb": self._size_mb(rec["data"]) if rec["data"] else "",
                    "unselected_data": "; ".join(p.name for p in rec["unselected_data"]),
                    "unselected_case": "; ".join(p.name for p in rec["unselected_case"]),
                    "case_res": case_res, "data_res": data_res,
                    "note": "",
                }
            except Exception as e:
                # 해당 DP 만 실패로 기록하고 다음 레코드로 진행
                result = {
                    "dp": rec.get("dp", ""), "dp_num": rec.get("dp_num", ""),
                    "status": rec.get("status", ""),
                    "iterations": rec.get("iterations", None),
                    "copy_status": "실패",
                    "orig_case": "", "orig_case_name": "",
                    "new_case": "", "new_case_name": "", "case_mb": "",
                    "orig_data": "", "orig_data_name": "",
                    "new_data": "", "new_data_name": "", "data_mb": "",
                    "unselected_data": "", "unselected_case": "",
                    "case_res": "failed", "data_res": "failed",
                    "note": "예외: %s" % e,
                }
            results.append(result)
            self.item_done.emit(result)

        # 로그 기록 실패해도 finished_all 은 반드시 emit (GUI 복구 보장)
        try:
            summary = self._write_logs(results)
        except Exception as e:
            summary = {
                "total": len(results),
                "ok": sum(1 for r in results if r.get("copy_status") == "성공"),
                "part": sum(1 for r in results if str(r.get("copy_status", "")).startswith("부분")),
                "skip": sum(1 for r in results if r.get("copy_status") == "건너뜀"),
                "fail": sum(1 for r in results if r.get("copy_status") == "실패"),
                "csv": "", "txt": "", "note": "로그 기록 실패: %s" % e,
            }
        summary["cancelled"] = self._cancel
        self.finished_all.emit(summary)

    def _write_logs(self, results):
        """CSV + 요약 txt 생성. 요약 dict 반환."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.out_dir / ("dp_collect_%s.csv" % ts)
        txt_path = self.out_dir / ("dp_collect_%s.txt" % ts)

        n = len(results)
        ok = sum(1 for r in results if r["copy_status"] == "성공")
        skip = sum(1 for r in results if r["copy_status"] == "건너뜀")
        part = sum(1 for r in results if r["copy_status"].startswith("부분"))
        fail = sum(1 for r in results if r["copy_status"] == "실패")

        # --- CSV (Excel 한글 대응: utf-8-sig) ---
        cols = [
            ("dp", "dp"), ("dp_num", "dp_num"), ("status", "탐색상태"),
            ("copy_status", "복사상태"), ("iterations", "반복횟수"),
            ("orig_case", "원본_Case_경로"), ("orig_case_name", "원본_Case_파일명"),
            ("new_case", "변경_Case_경로"), ("new_case_name", "변경_Case_파일명"),
            ("case_mb", "Case_MB"),
            ("orig_data", "원본_Data_경로"), ("orig_data_name", "원본_Data_파일명"),
            ("new_data", "변경_Data_경로"), ("new_data_name", "변경_Data_파일명"),
            ("data_mb", "Data_MB"),
            ("unselected_data", "미선택_Data"),
            ("unselected_case", "미선택_Case"),
            ("note", "비고"),
        ]
        try:
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([h for _, h in cols])
                for r in results:
                    w.writerow([r.get(k, "") for k, _ in cols])
        except Exception:
            csv_path = None

        # --- 요약 txt ---
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("Workbench DP 수집·이름변경 로그\n")
                f.write("생성 시각 : %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                f.write("입력 폴더 : %s\n" % self.input_root)
                f.write("출력 폴더 : %s\n" % self.out_dir)
                f.write("저장 구조 : %s\n" % ("이름별 폴더" if self.per_folder else "한 폴더에 모두"))
                f.write("이름 규칙 : 접두사='%s'  접미사='%s'\n" % (self.prefix, self.suffix))
                f.write("-" * 70 + "\n")
                f.write("총 %d개  |  성공 %d  부분 %d  건너뜀 %d  실패 %d\n" % (n, ok, part, skip, fail))
                f.write("-" * 70 + "\n\n")
                for r in results:
                    it = "" if r["iterations"] is None else "  (반복횟수=%s)" % r["iterations"]
                    f.write("[%s] %s / %s\n" % (r["dp"], r["status"], r["copy_status"]))
                    if r["orig_case"]:
                        f.write("   Case: %s\n         -> %s\n" % (r["orig_case_name"], r["new_case"]))
                    else:
                        f.write("   Case: (없음)\n")
                    if r["orig_data"]:
                        f.write("   Data: %s%s\n         -> %s\n" % (r["orig_data_name"], it, r["new_data"]))
                    else:
                        f.write("   Data: (없음)\n")
                    if r["unselected_data"]:
                        f.write("   (미선택 Data: %s)\n" % r["unselected_data"])
                    if r.get("unselected_case"):
                        f.write("   (미선택 Case: %s)\n" % r["unselected_case"])
                    f.write("\n")
        except Exception:
            txt_path = None

        return {
            "total": n, "ok": ok, "part": part, "skip": skip, "fail": fail,
            "csv": str(csv_path) if csv_path else "", "txt": str(txt_path) if txt_path else "",
        }


# ============================================================
# 탭 위젯
# ============================================================
class DPCollectTab(QWidget):
    def __init__(self):
        super().__init__()
        self.records = []          # 스캔된 DP 레코드
        self.worker = None
        self.input_root = ""
        self._build_ui()

    # --------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        title = QLabel("Workbench Design Point 정리 (Case/Data 수집·이름변경)")
        tf = QFont(); tf.setPointSize(15); tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)
        subtitle = QLabel("각 DP(dp0, dp1, …)의 Fluent Case/Data를 복사하면서 DP 이름으로 통일")
        subtitle.setStyleSheet("color: #888;")
        root.addWidget(subtitle)

        # --- 1. 입력 폴더 ---
        in_group = QGroupBox("1. 입력 폴더 (Workbench ..._files 또는 상위 폴더)")
        in_outer = QVBoxLayout(in_group)
        row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("dp0, dp1 … 폴더가 들어있는 상위 폴더를 선택하세요")
        browse_btn = QPushButton("폴더 선택")
        browse_btn.clicked.connect(self._browse_input)
        self.scan_btn = QPushButton("스캔")
        self.scan_btn.clicked.connect(self._scan)
        row.addWidget(self.input_edit, 1)
        row.addWidget(browse_btn)
        row.addWidget(self.scan_btn)
        in_outer.addLayout(row)

        hdr = QHBoxLayout()
        self.count_label = QLabel("폴더를 선택하고 스캔하세요")
        self.count_label.setStyleSheet("color: #888;")
        hdr.addWidget(self.count_label)
        hdr.addStretch()
        self.select_all_btn = QPushButton("전체 선택")
        self.select_all_btn.clicked.connect(lambda: self._set_all(True))
        self.deselect_all_btn = QPushButton("전체 해제")
        self.deselect_all_btn.clicked.connect(lambda: self._set_all(False))
        hdr.addWidget(self.select_all_btn)
        hdr.addWidget(self.deselect_all_btn)
        in_outer.addLayout(hdr)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["선택", "DP", "Case 파일", "Data 파일", "반복횟수", "상태"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(200)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #252525; color: #c8c8c8; "
            "gridline-color: #444; border: 1px solid #444; }"
            "QHeaderView::section { background-color: #333; color: #ddd; "
            "border: 0px; padding: 4px; }")
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        in_outer.addWidget(self.table)
        root.addWidget(in_group, 1)

        # --- 2. 이름 규칙 ---
        name_group = QGroupBox("2. 이름 규칙 (기본: DP 폴더명 그대로)")
        name_layout = QGridLayout(name_group)
        name_layout.addWidget(QLabel("접두사:"), 0, 0)
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("(선택) 예: Cristea_")
        self.prefix_edit.textChanged.connect(self._update_preview)
        name_layout.addWidget(self.prefix_edit, 0, 1)
        name_layout.addWidget(QLabel("접미사:"), 0, 2)
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("(선택) 예: _v1")
        self.suffix_edit.textChanged.connect(self._update_preview)
        name_layout.addWidget(self.suffix_edit, 0, 3)
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("color: #4ec9b0;")
        name_layout.addWidget(self.preview_label, 1, 0, 1, 4)
        root.addWidget(name_group)
        self._update_preview()

        # --- 3. 출력 설정 ---
        out_group = QGroupBox("3. 출력 설정")
        out_layout = QGridLayout(out_group)
        out_layout.addWidget(QLabel("출력 폴더:"), 0, 0)
        self.outdir_edit = QLineEdit()
        self.outdir_edit.setPlaceholderText("복사본을 저장할 폴더")
        outdir_btn = QPushButton("찾아보기")
        outdir_btn.clicked.connect(self._browse_outdir)
        out_layout.addWidget(self.outdir_edit, 0, 1)
        out_layout.addWidget(outdir_btn, 0, 2)

        out_layout.addWidget(QLabel("저장 구조:"), 1, 0)
        struct_widget = QWidget()
        struct_layout = QHBoxLayout(struct_widget)
        struct_layout.setContentsMargins(0, 0, 0, 0)
        self.struct_group = QButtonGroup(self)
        self.radio_per_folder = QRadioButton("이름별 폴더 생성 (dp_001/dp_001.cas.h5)")
        self.radio_flat = QRadioButton("한 폴더에 모두 (dp_001.cas.h5)")
        self.radio_per_folder.setChecked(True)
        self.struct_group.addButton(self.radio_per_folder)
        self.struct_group.addButton(self.radio_flat)
        struct_layout.addWidget(self.radio_per_folder)
        struct_layout.addWidget(self.radio_flat)
        struct_layout.addStretch()
        out_layout.addWidget(struct_widget, 1, 1, 1, 2)

        self.skip_existing_cb = QCheckBox("이미 있는 파일 건너뛰기 (이어하기, 같은 크기면 skip)")
        self.skip_existing_cb.setChecked(True)
        out_layout.addWidget(self.skip_existing_cb, 2, 1, 1, 2)
        root.addWidget(out_group)

        # --- 4. 실행 ---
        run_row = QHBoxLayout()
        self.run_btn = QPushButton("수집·이름변경 실행")
        self.run_btn.setMinimumHeight(40)
        rf = QFont(); rf.setBold(True)
        self.run_btn.setFont(rf)
        self.run_btn.clicked.connect(self._run)
        self.cancel_btn = QPushButton("중단")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.open_btn = QPushButton("출력 폴더 열기")
        self.open_btn.setMinimumHeight(40)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output_folder)
        run_row.addWidget(self.run_btn, 2)
        run_row.addWidget(self.cancel_btn, 1)
        run_row.addWidget(self.open_btn, 1)
        root.addLayout(run_row)

        self.overall_label = QLabel("대기 중")
        self.overall_label.setStyleSheet("color: #d0d0d0;")
        root.addWidget(self.overall_label)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)

        # --- 5. 콘솔 ---
        console_group = QGroupBox("로그")
        console_layout = QVBoxLayout(console_group)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        cf = QFont("Consolas"); cf.setStyleHint(QFont.Monospace); cf.setPointSize(9)
        self.console.setFont(cf)
        self.console.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; }")
        console_layout.addWidget(self.console)
        root.addWidget(console_group, 1)

    # --------------------------------------------------------
    # 입력 / 스캔
    # --------------------------------------------------------
    def _browse_input(self):
        folder = QFileDialog.getExistingDirectory(self, "입력 폴더 선택")
        if folder:
            self.input_edit.setText(folder)
            self._scan()

    def _scan(self):
        root = self.input_edit.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "경고", "올바른 폴더를 선택하세요.")
            return
        self.input_root = root
        self._log("[스캔] %s" % root)
        self.records = discover_design_points(root)
        self._populate_table()

        if not self.records:
            self.count_label.setText("⚠️  dp 폴더를 찾지 못했습니다")
            self.count_label.setStyleSheet("color: #e0a030;")
            self._log("[스캔] dp<번호> 폴더가 없습니다.")
            return
        ok = sum(1 for r in self.records if r["status"] == STATUS_OK)
        self.count_label.setText("✅ DP %d개 발견 (정상 %d)" % (len(self.records), ok))
        self.count_label.setStyleSheet("color: #4ec9b0;")
        self._log("[스캔] DP %d개 (정상 %d)" % (len(self.records), ok))

    def _populate_table(self):
        self.table.setRowCount(0)
        for rec in self.records:
            r = self.table.rowCount()
            self.table.insertRow(r)

            chk = QTableWidgetItem()
            valid = rec["status"] in (STATUS_OK, STATUS_NO_DATA, STATUS_NO_CASE)
            if valid:
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Checked if rec["status"] == STATUS_OK else Qt.Unchecked)
            else:
                chk.setFlags(Qt.ItemIsUserCheckable)
                chk.setCheckState(Qt.Unchecked)
            self.table.setItem(r, 0, chk)

            self.table.setItem(r, 1, QTableWidgetItem(rec["dp"]))
            self.table.setItem(r, 2, QTableWidgetItem(rec["case"].name if rec["case"] else "—"))
            self.table.setItem(r, 3, QTableWidgetItem(rec["data"].name if rec["data"] else "—"))
            it = "" if rec["iterations"] is None else str(rec["iterations"])
            self.table.setItem(r, 4, QTableWidgetItem(it))
            status_item = QTableWidgetItem(rec["status"])
            if rec["status"] != STATUS_OK:
                status_item.setForeground(Qt.gray if rec["status"] == STATUS_EMPTY else Qt.yellow)
            self.table.setItem(r, 5, status_item)

    def _set_all(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item.flags() & Qt.ItemIsEnabled:
                item.setCheckState(state)

    def _selected_records(self):
        out = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() == Qt.Checked:
                out.append(self.records[r])
        return out

    # --------------------------------------------------------
    # 이름 미리보기
    # --------------------------------------------------------
    def _update_preview(self):
        prefix = self.prefix_edit.text()
        suffix = self.suffix_edit.text()
        base = build_base_name("dp16", 16, prefix, suffix)
        self.preview_label.setText(
            "미리보기:  dp16  →  %s%s , %s%s" % (base, CASE_SUFFIX, base, DATA_SUFFIX))

    def _browse_outdir(self):
        folder = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if folder:
            self.outdir_edit.setText(folder)

    # --------------------------------------------------------
    # 실행
    # --------------------------------------------------------
    def _run(self):
        selected = self._selected_records()
        out_dir = self.outdir_edit.text().strip()

        if not selected:
            QMessageBox.warning(self, "경고", "복사할 DP를 하나 이상 선택하세요.")
            return
        if not out_dir:
            QMessageBox.warning(self, "경고", "출력 폴더를 지정하세요.")
            return

        prefix = self.prefix_edit.text()
        suffix = self.suffix_edit.text()
        per_folder = self.radio_per_folder.isChecked()

        # 출력 이름(base) 충돌 검사: 서로 다른 프로젝트가 함께 스캔되면
        # 여러 DP 가 같은 base 로 매핑되어 같은 출력에 덮어쓰게 되므로 차단한다.
        base_map = {}
        for rec in selected:
            base = build_base_name(rec["dp"], rec["dp_num"], prefix, suffix)
            base_map.setdefault(base, []).append(rec)
        dup_lines = []
        for base, recs in base_map.items():
            if len(recs) > 1:
                for rec in recs:
                    dup_lines.append("%s  ←  %s" % (base, rec["dp_dir"]))
        if dup_lines:
            shown = dup_lines[:5]
            more = ("\n… 외 %d개" % (len(dup_lines) - 5)) if len(dup_lines) > 5 else ""
            QMessageBox.critical(
                self, "출력 이름 충돌",
                "여러 DP가 같은 출력 이름(base)으로 매핑됩니다.\n"
                "서로 다른 프로젝트 폴더가 함께 스캔된 것 같습니다. "
                "프로젝트 하나의 폴더만 선택하세요.\n\n"
                + "\n".join(shown) + more)
            return

        # 디스크 여유공간 확인
        est = 0
        for rec in selected:
            if rec["case"]:
                try:
                    est += rec["case"].stat().st_size
                except OSError:
                    pass   # 조회 실패 파일은 0으로 취급하고 집계 계속
            if rec["data"]:
                try:
                    est += rec["data"].stat().st_size
                except OSError:
                    pass
        try:
            os.makedirs(out_dir, exist_ok=True)
            free = shutil.disk_usage(out_dir).free
            if est > free:
                QMessageBox.critical(
                    self, "디스크 공간 부족",
                    "예상 복사량 %.1f GB > 여유공간 %.1f GB" % (est / 1024**3, free / 1024**3))
                return
        except Exception as e:
            QMessageBox.warning(self, "경고", "출력 폴더 확인 실패: %s" % e)
            return

        reply = QMessageBox.question(
            self, "실행 확인",
            "%d개 DP를 복사·이름변경합니다.\n예상 용량: %.2f GB\n저장 구조: %s\n\n계속하시겠습니까?" % (
                len(selected), est / 1024**3,
                "이름별 폴더" if per_folder else "한 폴더에 모두"),
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self.run_btn.setEnabled(False)
        self.run_btn.setText("복사 중...")
        self.cancel_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.progress.setMaximum(len(selected))
        self.progress.setValue(0)
        self._last_out_dir = out_dir

        self._log("\n" + "=" * 60)
        self._log("[실행] %d개 DP → %s" % (len(selected), out_dir))
        self._log("=" * 60)

        self.worker = DPCollectWorker(
            selected, out_dir, prefix, suffix, per_folder,
            self.skip_existing_cb.isChecked(), self.input_root)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, done, total, msg):
        self.overall_label.setText("진행: %d / %d  —  %s" % (done, total, msg))
        self.progress.setValue(done)

    def _on_item_done(self, r):
        mark = {"성공": "✓", "건너뜀": "→", "실패": "✗"}.get(r["copy_status"], "•")
        self._log("  %s [%s] %s  (Case %s / Data %s)" % (
            mark, r["dp"], r["copy_status"], r["case_res"], r["data_res"]))

    def _on_finished(self, s):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("수집·이름변경 실행")
        self.cancel_btn.setEnabled(False)
        self.open_btn.setEnabled(True)
        state = "중단됨" if s.get("cancelled") else "완료"
        self.overall_label.setText(
            "%s: 총 %d (성공 %d, 부분 %d, 건너뜀 %d, 실패 %d)" % (
                state, s["total"], s["ok"], s["part"], s["skip"], s["fail"]))
        self._log("\n" + "=" * 60)
        self._log("[%s] 성공 %d / 부분 %d / 건너뜀 %d / 실패 %d (총 %d)" % (
            state, s["ok"], s["part"], s["skip"], s["fail"], s["total"]))
        if s.get("csv"):
            self._log("[로그] %s" % s["csv"])
        if s.get("txt"):
            self._log("[로그] %s" % s["txt"])
        self._log("=" * 60)
        QMessageBox.information(
            self, state,
            "%s!\n\n총 %d개\n성공 %d / 부분 %d / 건너뜀 %d / 실패 %d\n\n로그:\n%s" % (
                state, s["total"], s["ok"], s["part"], s["skip"], s["fail"],
                s.get("csv", "(없음)")))

    def _cancel(self):
        if self.worker is not None:
            self.worker.request_cancel()
            self._log("[중단] 현재 파일까지 처리 후 멈춥니다...")
            self.cancel_btn.setEnabled(False)

    def shutdown(self):
        """앱 종료 시 호출: 실행 중인 복사 워커를 정리한다."""
        try:
            if self.worker is not None and self.worker.isRunning():
                self.worker.request_cancel()
                if not self.worker.wait(5000):
                    # 정상 종료 실패 시 강제 종료 (QThread 파괴로 인한 크래시 방지)
                    self.worker.terminate()
                    self.worker.wait(2000)
        except Exception:
            pass

    def _open_output_folder(self):
        out_dir = getattr(self, "_last_out_dir", "") or self.outdir_edit.text().strip()
        if out_dir and os.path.isdir(out_dir):
            try:
                os.startfile(out_dir)  # Windows
            except AttributeError:
                import subprocess
                subprocess.Popen(["xdg-open", out_dir])

    # --------------------------------------------------------
    def _log(self, msg):
        self.console.appendPlainText(msg)
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())
        session_log.write(msg, tag="DP정리")
