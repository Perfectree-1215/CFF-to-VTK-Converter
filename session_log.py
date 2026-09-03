# -*- coding: utf-8 -*-
"""앱 세션 로그 파일 — 콘솔에 표시되는 모든 줄을 실시간으로 파일에도 기록한다.

콘솔 창이 작아 확인이 어려울 때, 이 로그 파일을 외부 편집기(VS Code, Notepad++)나
PowerShell `Get-Content <파일> -Wait` 로 열어 실시간으로 확인할 수 있다.

- 로그 위치: 앱 폴더 아래 `logs/pv_export_YYYYmmdd_HHMMSS.log`
- 두 탭(변환 / DP 정리)이 하나의 세션 파일을 공유하며, 각 줄에 시각과 태그가 붙는다.
- 파일 I/O 실패는 조용히 무시되어 GUI 동작을 방해하지 않는다.

pv_export_gui / dp_collect_tab 양쪽에서 import 하되, 순환 import 를 피하기 위해
독립 모듈로 둔다.
"""
import os
import sys
from datetime import datetime

_log_path = None
_log_file = None


def _app_dir():
    """앱(스크립트/실행파일) 폴더. PyInstaller 등 frozen 환경도 처리."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def init_session_log():
    """세션 로그 파일을 생성(최초 1회)하고 경로를 반환. 실패해도 None 을 반환하며 계속 동작."""
    global _log_path, _log_file
    if _log_file is not None:
        return _log_path
    try:
        log_dir = os.path.join(_app_dir(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_path = os.path.join(log_dir, "pv_export_%s.log" % stamp)
        _log_file = open(_log_path, "a", encoding="utf-8")
        _log_file.write("=== 세션 시작: %s ===\n"
                        % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        _log_file.flush()
    except Exception:
        _log_path, _log_file = None, None
    return _log_path


def get_log_path():
    """현재 세션 로그 파일 경로(없으면 None)."""
    return _log_path


def write(line, tag=None):
    """한 줄을 로그 파일에 기록하고 즉시 flush(실시간 확인). 콘솔 append 와 병행 호출."""
    if _log_file is None:
        return
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = "[%s]" % ts if not tag else "[%s|%s]" % (ts, tag)
        _log_file.write("%s %s\n" % (prefix, line))
        _log_file.flush()
    except Exception:
        pass


def close_session_log():
    """세션 종료 표시 후 파일을 닫는다."""
    global _log_file
    if _log_file is not None:
        try:
            _log_file.write("=== 세션 종료: %s ===\n"
                            % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            _log_file.flush()
            _log_file.close()
        except Exception:
            pass
        _log_file = None
