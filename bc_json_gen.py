# -*- coding: utf-8 -*-
"""
optiSLang / Workbench 설계 테이블 CSV → 설계별 boundary_conditions.json 자동 생성
================================================================================
Stochos Flow DIM-GP 그래프 회귀 학습에 필요한, 설계 폴더별 전역 파라미터 JSON을
optiSLang 설계 테이블 CSV에서 자동 생성한다. (앱 통합용 모듈 + CLI)

이 모듈은 순수 표준 라이브러리(csv, json, re, pathlib, logging)만 사용한다.

★ Stochos 불변 규칙 (어떤 리팩터링에서도 깨면 안 됨)
  1. JSON 키 삽입 순서 = Stochos X_global_feat 열 순서
     → param_cols(dict)의 정의 순서를 그대로 보존. 정렬/set/재배열 금지.
  2. 파일명은 boundary_conditions.json 고정, 위치는 각 설계 폴더(= VTU와 동일 폴더).
  3. 모든 학습 대상 폴더에 동일 키 집합. JSON 없는 폴더는 리포트로 반드시 노출.
  4. 값은 float로 기록 (문자열 금지).
  5. boundary_conditions.json 에는 파라미터 키 외 어떤 키도 추가 금지.
     사람용 메타데이터는 별도 사이드카 design_info.json 에만 기록
     (Stochos read_vtk 는 이 파일을 읽지 않음).

원본 standalone 스크립트(Handoff_docs/generate_bc_json.py, 실데이터 검증 완료)와
동일한 동작·바이트 동일한 JSON을 생성하도록 이식했다.

지원 CSV 포맷
  A) 구식 설계 테이블: 첫 행이 헤더('#'이 설계 번호 열), 탭/세미콜론/콤마 구분.
  B) Workbench/optiSLang 설계점 내보내기: '# ' 주석 선행 행 + 파라미터 정의 주석
     ('P1 - Inlet_length [mm]' …) + 'Name,P1,P2,…' 헤더(P번호 참조),
     설계 열 'Name'(값 'DP 0' …). 주석의 정의를 파싱해 이름으로 열을 매칭한다.
"""

import argparse
import csv
import json
import logging
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# 기본 파라미터 매핑 (JSON 키 → CSV 열 이름). ★ 이 순서가 X_global_feat 열 순서.
DEFAULT_PARAM_COLS = {
    "inlet_length":         "Inlet_length",
    "cone_length":          "Cone_length",
    "vortex_finder_length": "V.Finder_length",
}

DEFAULT_JSON_NAME = "boundary_conditions.json"
DEFAULT_SIDECAR_NAME = "design_info.json"
DEFAULT_DESIGN_COL_HINT = "#"

_TRAILING_INT = re.compile(r"(\d+)\s*$")
_DELIM_NAMES = {"\t": "탭(\\t)", ";": "세미콜론(;)", ",": "콤마(,)"}

# 헤더 행 탐색 시 구분자 없는 선행 행(제목/빈 줄 등)을 건너뛰는 최대 행 수
_HEADER_SCAN_LIMIT = 20

# 설계 번호 열 힌트가 안 맞을 때 시도하는 폴백 열 이름
# (Workbench 설계점 내보내기는 'Name' 열에 'DP 0', 'DP 1' … 형식)
_DESIGN_COL_FALLBACKS = ("Name", "#")

# Workbench 주석의 파라미터 정의 토큰: "P1 - Inlet_length [mm]" → (P1, Inlet_length)
_PARAM_DEF = re.compile(r"^\s*(P\d+)\s*-\s*(.+?)\s*(?:\[[^\]]*\])?\s*$")


# =============================================================================
# 예외 / 설정 / 리포트
# =============================================================================
class BCGenError(Exception):
    """boundary_conditions.json 생성 중 발생하는 복구 불가 오류 (CLI에서 exit 처리)."""


@dataclass
class BCGenConfig:
    """생성 설정. 앱에서 주입 가능하며 기본값은 원본 스크립트 상수와 동일하다."""
    csv_path: str
    data_roots: list                       # 설계 폴더들의 부모 경로 리스트
    delimiter: str = "auto"                # "auto" 또는 "\t" / ";" / ","
    design_col_hint: str = DEFAULT_DESIGN_COL_HINT
    design_number_offset: int = 0          # 폴더 번호 = CSV 번호 + offset
    param_cols: dict = field(default_factory=lambda: dict(DEFAULT_PARAM_COLS))
    json_name: str = DEFAULT_JSON_NAME
    sidecar_name: str = DEFAULT_SIDECAR_NAME   # None 이면 사이드카 미생성
    # CSV에 없는 설계(예: optiSLang이 내보내지 않는 기준설계 DP0)를 직접 입력한 값으로 채움.
    # {설계번호: {json_key: 값}} — 값은 to_float 로 변환, 키는 param_cols 순서로 정렬됨.
    manual_designs: dict = field(default_factory=dict)
    dry_run: bool = True


@dataclass
class BCGenReport:
    """생성 결과 리포트. UI/로그가 그대로 표시할 수 있도록 필드를 공개한다."""
    written: list = field(default_factory=list)        # 생성(예정) 설계 번호
    no_folder: list = field(default_factory=list)      # CSV엔 있으나 폴더 없음
    folder_only: list = field(default_factory=list)    # 폴더엔 있으나 CSV 없음
    bad_value: list = field(default_factory=list)      # (설계번호, 열, 원본값)
    write_failed: list = field(default_factory=list)   # (설계번호, 대상경로, 오류메시지)
    key_order_ok: bool = True
    matched_columns: dict = field(default_factory=dict)  # json_key → CSV 열
    delimiter: str = ""
    design_col: str = ""
    folders_found: int = 0
    sidecar_enabled: bool = False                      # 사이드카 생성 설정 여부
    sidecar_written: int = 0
    previews: list = field(default_factory=list)       # 매칭 미리보기 문자열
    dry_run: bool = True


# =============================================================================
# 순수 로직 (단위 테스트 대상)
# =============================================================================
def extract_design_number(name):
    """문자열 끝의 정수를 설계 번호로 추출. 예: 'Design0012'→12, '12'→12, '12.0'→12."""
    s = str(name).strip()
    # 순수 숫자(소수 포함) 처리: '12' 또는 '12.0'
    try:
        f = float(s.replace(",", "."))
        if f.is_integer():
            return int(f)
    except ValueError:
        pass
    m = _TRAILING_INT.search(s)
    return int(m.group(1)) if m else None


def to_float(raw):
    """숫자 변환. 소수점 콤마('1,25')도 처리.

    NaN/Inf('nan', '1e400' 등)는 유효한 입력 파라미터가 아니므로 ValueError 로 거부한다.
    (Stochos X_global_feat 에 NaN/Inf 피처가 조용히 섞여 학습이 오염되는 것을 차단.)
    """
    s = str(raw).strip()
    try:
        v = float(s)
    except ValueError:
        v = float(s.replace(",", "."))
    if not math.isfinite(v):
        raise ValueError("유한한 수가 아님: %r" % (raw,))
    return v


def detect_delimiter(header_line):
    """헤더 행에서 후보 구분자 개수를 직접 세어 최다 후보 선택.

    (csv.Sniffer 는 이 데이터에서 오작동했으므로 사용하지 않는다.)
    """
    counts = {d: header_line.count(d) for d in ("\t", ";", ",")}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        raise BCGenError("헤더에서 탭/세미콜론/콤마를 찾지 못했습니다. "
                         "구분자를 직접 지정하세요.")
    log.info("구분자 감지: %s  (탭 %d개 / ; %d개 / , %d개)",
             _DELIM_NAMES[best], counts["\t"], counts[";"], counts[","])
    return best


def match_column(headers, hint, aliases=None):
    """1) 정확 일치(대소문자 무시) → 2) 유일한 부분 일치 → 3) 다중이면 최단 이름.

    aliases: {헤더: 실제 파라미터 이름}. Workbench 내보내기처럼 헤더가 참조 ID
    (P1, P2 …)일 때, 힌트를 헤더 자체뿐 아니라 별칭 이름과도 비교한다.
    반환값은 항상 원본 헤더(행 접근 키)다.
    """
    aliases = aliases or {}
    hint_low = hint.strip().lower()

    def names(h):
        return [h] + ([aliases[h]] if h in aliases else [])

    exact = [h for h in headers
             if any(n.lower() == hint_low for n in names(h))]
    if exact:
        return exact[0]
    partial = [h for h in headers
               if any(hint_low in n.lower() for n in names(h))]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        chosen = min(partial, key=lambda h: min(
            len(n) for n in names(h) if hint_low in n.lower()))
        log.warning("'%s' 부분 일치가 여러 개: %s → 최단 이름 '%s' 사용",
                    hint, partial, chosen)
        return chosen
    return None


def _is_comment_line(line):
    """Workbench/optiSLang 내보내기 주석 행('# …') 여부.

    구식 탭 구분 테이블의 헤더는 '#'이 첫 열 이름이라 '#\\t…'로 시작한다 —
    이는 주석이 아니므로 '#' 단독 행 또는 '# '(해시+공백)로 시작하는 행만 주석으로 본다.
    """
    s = line.rstrip("\r\n")
    return s.startswith("#") and (s == "#" or s[1] == " ")


def parse_param_defs(comment_lines):
    """주석 행들에서 'P# - 이름 [단위]' 파라미터 정의를 추출 → {P#: 이름}."""
    defs = {}
    for line in comment_lines:
        body = line.lstrip("#").strip()
        for token in re.split(r"[\t;,]", body):
            m = _PARAM_DEF.match(token)
            if m:
                defs[m.group(1)] = m.group(2)
    return defs


def _preview_line(line, limit=80):
    """오류 메시지용 행 미리보기 (제어문자 노출을 위해 repr, 길면 자름)."""
    s = line.rstrip("\r\n")
    if len(s) > limit:
        s = s[:limit] + "…"
    return repr(s)


def read_csv_rows(csv_path, delimiter="auto"):
    """CSV 로드. 반환: (headers, rows, delim, param_defs). 오류 시 BCGenError.

    - Workbench/optiSLang 설계점 내보내기의 '# ' 주석 행은 건너뛰되, 주석 안의
      파라미터 정의('P1 - Inlet_length [mm]' …)는 param_defs({P#: 이름})로 반환한다
      (헤더가 P1, P2 … 참조 ID일 때 열 매칭에 사용).
    - 그 외 구분자가 전혀 없는 선행 행(제목·빈 줄 등)도 헤더가 아니므로 건너뛴다
      (최대 _HEADER_SCAN_LIMIT 행). 헤더를 못 찾으면 첫 행 미리보기를 포함한
      오류를 던져 사용자가 파일이 올바른 설계 테이블 CSV인지 판단할 수 있게 한다.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise BCGenError("CSV 파일을 찾을 수 없습니다: %s" % path)
    candidates = ("\t", ";", ",") if delimiter == "auto" else (delimiter,)
    cand_names = ("탭/세미콜론/콤마" if delimiter == "auto"
                  else _DELIM_NAMES.get(delimiter, repr(delimiter)))
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        first_line = None
        comment_lines = []
        skipped = 0
        while True:
            pos = f.tell()
            header_line = f.readline()
            if first_line is None:
                first_line = header_line
            if not header_line:
                raise BCGenError(
                    "CSV에서 %s 구분자가 있는 헤더 행을 찾지 못했습니다. "
                    "설계 테이블 CSV가 맞는지 확인하거나 구분자를 직접 지정하세요.\n"
                    "  첫 행 미리보기: %s" % (cand_names, _preview_line(first_line)))
            # 주석 판정이 구분자 판정보다 먼저 — Workbench 파라미터 정의 주석에는
            # 구분자(콤마)가 들어 있어 헤더로 오인될 수 있다.
            if _is_comment_line(header_line):
                comment_lines.append(header_line)
            elif any(d in header_line for d in candidates):
                f.seek(pos)
                break
            elif header_line.strip():
                log.warning("구분자 없는 선행 행 건너뜀: %s", _preview_line(header_line))
            skipped += 1
            if skipped >= _HEADER_SCAN_LIMIT:
                raise BCGenError(
                    "처음 %d행 어디에도 %s 구분자가 있는 헤더가 없습니다. "
                    "설계 테이블 CSV가 맞는지 확인하거나 구분자를 직접 지정하세요.\n"
                    "  첫 행 미리보기: %s"
                    % (_HEADER_SCAN_LIMIT, cand_names, _preview_line(first_line)))
        delim = detect_delimiter(header_line) if delimiter == "auto" else delimiter
        reader = csv.DictReader(f, delimiter=delim)
        rows = list(reader)
        headers = [h.strip() for h in (reader.fieldnames or [])]
    if not rows:
        raise BCGenError("CSV에 데이터 행이 없습니다.")
    if len(headers) < 2:
        raise BCGenError("열이 %d개뿐입니다. 구분자가 잘못 감지된 듯합니다. "
                         "구분자를 '\\t' 등으로 직접 지정해 보세요." % len(headers))
    # 헤더에 실제로 존재하는 참조 ID만 유효한 정의로 인정
    param_defs = {k: v for k, v in parse_param_defs(comment_lines).items()
                  if k in headers}
    if param_defs:
        log.info("파라미터 정의 주석 감지: %d개 (헤더가 P번호 참조 → 이름으로 매칭)",
                 len(param_defs))
    return headers, rows, delim, param_defs


def scan_design_folders(roots):
    """루트들 아래 직속 폴더에서 {설계번호: Path}. 번호 중복 시 BCGenError."""
    folders = {}
    duplicates = []
    for root in roots:
        root_path = Path(root)
        if not root_path.is_dir():
            log.warning("루트 폴더가 없습니다: %s", root_path)
            continue
        for sub in sorted(root_path.iterdir()):
            if not sub.is_dir():
                continue
            num = extract_design_number(sub.name)
            if num is None:
                log.warning("폴더 이름에서 설계 번호를 찾지 못함, 건너뜀: %s", sub)
                continue
            if num in folders:
                duplicates.append((num, folders[num], sub))
            folders[num] = sub
    if duplicates:
        for num, first, second in duplicates:
            log.error("설계 번호 %d 중복:\n       %s\n       %s", num, first, second)
        raise BCGenError("설계 번호 중복을 해결한 뒤 다시 실행하세요.")
    return folders


# =============================================================================
# 핵심 API
# =============================================================================
def generate_bc_jsons(config):
    """설정에 따라 boundary_conditions.json(+사이드카)을 생성하고 리포트를 반환.

    dry_run=True 이면 파일시스템을 변경하지 않고 매칭/리포트만 수행한다.
    복구 불가 오류는 BCGenError 로 던진다.
    """
    if not config.param_cols:
        raise BCGenError("파라미터 매핑(param_cols)이 비어 있습니다.")

    report = BCGenReport(dry_run=config.dry_run)
    report.sidecar_enabled = bool(config.sidecar_name)

    folders = scan_design_folders(config.data_roots)
    report.folders_found = len(folders)
    if not folders:
        raise BCGenError("설계 폴더를 하나도 찾지 못했습니다. 설계 폴더 루트를 확인하세요.")
    log.info("설계 폴더 %d개 발견 (번호 범위: %d–%d)",
             len(folders), min(folders), max(folders))

    headers, rows, delim, param_defs = read_csv_rows(config.csv_path,
                                                     config.delimiter)
    report.delimiter = delim
    log.info("CSV 로드: %s — %d행 × %d열", config.csv_path, len(rows), len(headers))

    design_col = match_column(headers, config.design_col_hint, param_defs)
    if design_col is None:
        # Workbench 내보내기는 설계 열 이름이 'Name'(값: 'DP 0' …) — 폴백 시도
        for fb in _DESIGN_COL_FALLBACKS:
            if fb.lower() == config.design_col_hint.strip().lower():
                continue
            design_col = match_column(headers, fb, param_defs)
            if design_col is not None:
                log.info("설계 번호 열 '%s' 없음 → 폴백 '%s' 사용",
                         config.design_col_hint, design_col)
                break
    if design_col is None:
        raise BCGenError("설계 번호 열('%s')을 찾지 못했습니다. CSV 열: %s ..."
                         % (config.design_col_hint, headers[:8]))
    report.design_col = design_col

    col_map = {}
    for json_key, hint in config.param_cols.items():
        col = match_column(headers, hint, param_defs)
        if col is None:
            raise BCGenError("파라미터 열('%s')을 찾지 못했습니다. CSV 열: %s ..."
                             % (hint, headers[:8]))
        resolved = param_defs.get(col, col)
        if resolved.lower().endswith(("_op", "-op")):
            log.warning("'%s' → '%s'(%s)는 출력(op) 열로 보입니다 — "
                        "입력 파라미터로 사용하면 안 됩니다. 매핑을 확인하세요.",
                        hint, col, resolved)
        col_map[json_key] = col
    report.matched_columns = dict(col_map)

    log.info("열 매칭: 설계번호 ← '%s'  (오프셋 %+d)", design_col, config.design_number_offset)
    for k, c in col_map.items():
        disp = ("  (= %s)" % param_defs[c]) if c in param_defs else ""
        log.info("          %-22s ← '%s'%s", k, c, disp)

    csv_numbers = set()
    for row in rows:
        raw_num = extract_design_number(row.get(design_col, ""))
        if raw_num is None:
            log.warning("설계 번호 해석 불가, 행 건너뜀: %r", row.get(design_col))
            continue
        num = raw_num + config.design_number_offset
        csv_numbers.add(num)

        if num not in folders:
            report.no_folder.append(num)
            continue

        bc = {}
        ok = True
        for json_key, csv_col in col_map.items():
            try:
                bc[json_key] = to_float(row[csv_col])
            except (ValueError, TypeError, KeyError):
                report.bad_value.append((num, csv_col, row.get(csv_col)))
                ok = False
                break
        if not ok:
            continue

        if len(report.previews) < 3:
            report.previews.append("CSV #%s → 폴더 '%s' : %s"
                                   % (raw_num, folders[num].name, bc))

        info = None
        if config.sidecar_name and not config.dry_run:
            info = {
                "design_name": folders[num].name,
                "csv_design_number": raw_num,
                "folder_design_number": num,
                "source_csv": Path(config.csv_path).name,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "parameters": bc,
            }
        _emit_design(config, report, folders[num], num, bc, info)

    # 수동 기준설계 입력 처리 (CSV에 없는 폴더, 예: DP0/Design_000 채우기)
    manual_written = _apply_manual_designs(config, report, folders)

    report.folder_only = sorted(set(folders) - csv_numbers - manual_written)

    # 키 순서 일관성: 생성물이 있으면 실제 파일을 읽어 검증, 아니면 정의 순서로 True.
    report.key_order_ok = _verify_key_order(config, folders, report)
    return report


def _write_json(path, obj):
    """JSON 기록 (원본 스크립트와 바이트 동일: indent=2, ensure_ascii=False).

    allow_nan=False 로 NaN/Infinity 같은 비표준 JSON 토큰 기록을 원천 차단한다.
    (유한 값에는 출력이 동일하므로 바이트 동일성은 유지된다. to_float 가 이미
    비유한 값을 걸러내므로 이는 방어선.)
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, allow_nan=False)


def _emit_design(config, report, folder, num, bc, sidecar_info):
    """한 설계의 bc JSON(+사이드카)을 기록하고 report 를 갱신.

    dry_run 이면 카운트만 하고 True. 실제 실행 시 bc JSON 쓰기가 성공하면 True
    (사이드카는 독립적으로 시도 — 실패해도 bc 생성/카운트에는 영향 없음),
    bc JSON 쓰기가 OSError 로 실패하면 write_failed 에 기록 후 False.
    """
    if config.dry_run:
        report.written.append(num)
        return True
    # 핵심 산출물(bc JSON)을 먼저 기록. 실패해도 예외를 밖으로 흘리지 않고 write_failed 에
    # 모아 다음 폴더를 계속 처리한다 — 부분 생성 상태(불변 규칙 3 위반: 학습 루트에 JSON
    # 없는 폴더 잔존)를 사용자에게 반드시 노출하기 위함.
    bc_path = folder / config.json_name
    try:
        _write_json(bc_path, bc)
    except OSError as e:
        report.write_failed.append((num, str(bc_path), str(e)))
        log.error("boundary_conditions.json 쓰기 실패 (설계 %s): %s", num, e)
        return False
    report.written.append(num)   # bc JSON 쓰기 성공 직후 카운트
    if config.sidecar_name and sidecar_info is not None:
        sc_path = folder / config.sidecar_name
        try:
            _write_json(sc_path, sidecar_info)
            report.sidecar_written += 1
        except OSError as e:
            report.write_failed.append((num, str(sc_path), str(e)))
            log.warning("사이드카 쓰기 실패 (설계 %s, bc JSON은 생성됨): %s", num, e)
    return True


def _apply_manual_designs(config, report, folders):
    """CSV에 없는 설계를 사용자가 직접 입력한 값으로 채운다. 채운 설계번호 집합을 반환.

    optiSLang이 내보내지 않는 기준설계(DP0/Design_000) 등을 위한 경로.
    bc 는 param_cols 정의 순서로 구성해 키 순서(=X_global_feat 열 순서) 불변 규칙을 보존한다.
    """
    manual_written = set()
    for num, raw_values in (config.manual_designs or {}).items():
        if num in report.written:
            log.warning("수동 입력 설계 %s: 이미 CSV로 생성됨 → 무시", num)
            continue
        bc = {}
        ok = True
        for json_key in config.param_cols:      # 정의 순서 보존
            if json_key not in raw_values:
                report.bad_value.append((num, json_key, "(수동 입력 누락)"))
                ok = False
                break
            try:
                bc[json_key] = to_float(raw_values[json_key])
            except (ValueError, TypeError):
                report.bad_value.append((num, json_key, raw_values.get(json_key)))
                ok = False
                break
        if not ok:
            continue
        if num not in folders:
            report.no_folder.append(num)
            continue
        if len(report.previews) < 3:
            report.previews.append("수동 DP%s → 폴더 '%s' : %s"
                                   % (num, folders[num].name, bc))
        info = None
        if config.sidecar_name and not config.dry_run:
            info = {
                "design_name": folders[num].name,
                "csv_design_number": None,       # 수동 입력이라 CSV 번호 없음
                "folder_design_number": num,
                "source_csv": Path(config.csv_path).name,
                "source": "manual",              # 수동 입력 표시 (Stochos 미사용)
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "parameters": bc,
            }
        if _emit_design(config, report, folders[num], num, bc, info):
            manual_written.add(num)
    return manual_written


def _verify_key_order(config, folders, report):
    """전 설계의 bc JSON 키 순서가 param_cols 정의 순서와 동일한지 검증."""
    expected = list(config.param_cols.keys())
    if config.dry_run or not report.written:
        return True   # 생성 안 함 → 정의 순서로 동일함이 보장됨
    for num in report.written:
        try:
            with open(folders[num] / config.json_name, encoding="utf-8") as f:
                keys = list(json.load(f).keys())
        except Exception:
            return False
        if keys != expected:
            log.error("키 순서 불일치 설계: %d (%s != %s)", num, keys, expected)
            return False
    return True


# =============================================================================
# CLI 진입점 (standalone 호환)
# =============================================================================
def _parse_params(items):
    """['inlet_length=Inlet_length', ...] → OrderedDict(정의 순서 보존)."""
    out = {}
    for item in items:
        if "=" not in item:
            raise BCGenError("파라미터 형식 오류(‘json_key=CSV열’ 필요): %r" % item)
        key, col = item.split("=", 1)
        key, col = key.strip(), col.strip()
        if not key or not col:
            raise BCGenError("파라미터 형식 오류(빈 값): %r" % item)
        out[key] = col
    return out


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="optiSLang CSV → 설계별 boundary_conditions.json 생성 (Stochos용)")
    p.add_argument("--csv", "-c", required=True, help="설계 테이블 CSV 경로")
    p.add_argument("--root", "-r", action="append", required=True,
                   help="설계 폴더들의 부모 경로 (여러 번 지정 가능)")
    p.add_argument("--delimiter", "-d", default="auto",
                   help=r"구분자: auto(기본) 또는 \t / ; / ,")
    p.add_argument("--design-col", default=DEFAULT_DESIGN_COL_HINT,
                   help="설계 번호 열 이름 (기본 '#')")
    p.add_argument("--offset", type=int, default=0,
                   help="폴더 번호 = CSV 번호 + offset (기본 0)")
    p.add_argument("--param", action="append", metavar="KEY=COL",
                   help="파라미터 매핑(순서 유지). 미지정 시 기본 3개 사용")
    p.add_argument("--json-name", default=DEFAULT_JSON_NAME)
    p.add_argument("--sidecar-name", default=DEFAULT_SIDECAR_NAME)
    p.add_argument("--no-sidecar", action="store_true", help="사이드카 미생성")
    p.add_argument("--manual-design", type=int, metavar="NUM",
                   help="CSV에 없는 설계 번호를 직접 값으로 채움 (예: 기준설계 0)")
    p.add_argument("--manual-value", action="append", metavar="KEY=VAL",
                   help="--manual-design 의 파라미터 값 (param 키와 동일, 여러 번)")
    p.add_argument("--execute", action="store_true",
                   help="실제 생성 (미지정 시 DRY-RUN: 파일 미변경)")
    return p


def report_to_lines(report):
    """리포트를 사람이 읽는 텍스트 줄 목록으로 (CLI/GUI 공용)."""
    action = "생성 예정(DRY-RUN)" if report.dry_run else "생성 완료"
    lines = ["=" * 60, "요약", "=" * 60,
             "JSON %s : %d개" % (action, len(report.written))]
    if report.sidecar_enabled:
        # DRY-RUN 이면 생성 예정 개수(=written), 실제 실행이면 기록 성공 개수.
        sc_count = len(report.written) if report.dry_run else report.sidecar_written
        lines.append("사이드카 %s : %d개" % (action, sc_count))
    if report.no_folder:
        lines.append("폴더 없음(CSV에만) : %s" % sorted(report.no_folder))
    if report.folder_only:
        lines.append("CSV 없음(폴더에만) : %s" % report.folder_only)
    if report.bad_value:
        lines.append("값 변환 실패:")
        for num, col, val in report.bad_value:
            lines.append("  - 설계 %s, 열 '%s', 값 %r" % (num, col, val))
    if report.write_failed:
        lines.append("[경고] 쓰기 실패 (부분 생성됨 — 학습 전 반드시 확인):")
        for num, path, err in report.write_failed:
            lines.append("  - 설계 %s → %s : %s" % (num, path, err))
    if not (report.no_folder or report.folder_only or report.bad_value
            or report.write_failed):
        lines.append("불일치 없음 — 모든 설계 폴더와 CSV 행이 1:1로 매칭되었습니다.")
    lines.append("키 순서 일관성: %s" % ("통과" if report.key_order_ok else "불일치"))
    return lines


def main(argv=None):
    # 한국어 Windows 콘솔(cp949)에서 '—' 등 유니코드 출력 시 UnicodeEncodeError 방지.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_arg_parser().parse_args(argv)
    param_cols = _parse_params(args.param) if args.param else dict(DEFAULT_PARAM_COLS)
    manual_designs = {}
    if args.manual_design is not None:
        manual_designs = {args.manual_design: _parse_params(args.manual_value or [])}
    config = BCGenConfig(
        csv_path=args.csv,
        data_roots=args.root,
        delimiter=args.delimiter,
        design_col_hint=args.design_col,
        design_number_offset=args.offset,
        param_cols=param_cols,
        json_name=args.json_name,
        sidecar_name=(None if args.no_sidecar else args.sidecar_name),
        manual_designs=manual_designs,
        dry_run=(not args.execute),
    )
    try:
        report = generate_bc_jsons(config)
    except BCGenError as e:
        print("[오류] %s" % e, file=sys.stderr)
        return 1
    for line in report_to_lines(report):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
