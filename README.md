# Fluent CFF 유틸리티

ANSYS Fluent 결과를 다루는 두 가지 도구를 **탭 하나로 묶은** 데스크톱 앱입니다.
자세한 앱 사용 방법은 **'USER_GUIDE.md'**를 확인하시기 바랍니다.

1. **Workbench DP 정리** — 파라메트릭(Design Point) 결과의 Case/Data를 DP 이름(dp_001, dp_002 …)으로 복사·이름변경
2. **CFF To VTK** — CFF 결과(`.cas.h5` / `.dat.h5`)를 ParaView로 VTM/VTU 일괄 변환

## 파일 구성

| 파일 | 설명 |
|---|---|
| `pv_export_gui.py` | PySide6 GUI 앱 (일반 python으로 실행) — 두 탭의 메인 창 |
| `dp_collect_tab.py` | "Workbench DP 정리" 탭 (순수 python, ParaView 불필요) |
| `pv_export_worker.py` | 변환 워커 (pvpython이 실행, 변환 탭이 자동 호출) |
| `requirements.txt` | GUI 실행에 필요한 Python 의존성 (PySide6) |
| `USER_GUIDE.md` | **사용자 가이드** — 설치, 사용법, 항목 설명, FAQ |
| `LICENSE` | MIT 라이선스 전문 |

## 빠른 시작

```bash
# 1. 의존성 설치 (venv에서)
pip install -r requirements.txt

# 2. .py 파일들을 같은 폴더에 두고 GUI 실행 (일반 python!)
python pv_export_gui.py
```

> ⚠️ "CFF To VTK" 탭은 별도로 설치된 ParaView(pvpython 포함)가 필요합니다(pip로는 설치 불가).
> "Workbench DP 정리" 탭은 순수 파이썬으로 동작하여 ParaView 없이도 사용할 수 있습니다.
> 자세한 내용은 `USER_GUIDE.md`를 참고하세요.

## 핵심 요약

- **구조**: 상단 탭으로 두 도구 스위칭. GUI(PySide6, 일반 python) + 변환 워커(pvpython) 분리
- **DP 정리 탭**: `dp*` 폴더 재귀 탐색 → Case/Data를 DP 번호 제로패딩으로 복사·통일(dp1 → `dp_001.cas.h5`/`dp_001.dat.h5`).
  Data 여러 개면 반복횟수 최대 선택, 완료 후 CSV+요약 로그 생성
- **변환 탭**: Fluent CFF → VTM/VTU 배치 변환(100개+). VTM 기본(영역 구조 유지)·VTU 옵션(단일 grid),
  내부 데이터 파일명은 `Results.vtu`로 통일, 출력 폴더는 접두사+순번(`Design_001` …)
- **연계**: DP 정리 결과(`dp_001.cas.h5`/`dp_001.dat.h5`)는 변환 탭에 바로 투입 가능.
  변환 탭은 입력 파일명의 dp 번호를 폴더 번호로 이어받습니다 (`dp_016` → `Design_016`)

## 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE)로 배포됩니다. 상업적 이용을 포함해 자유롭게
사용·수정·재배포할 수 있으며, 저작권 표시와 라이선스 전문만 함께 포함하면 됩니다.

### 서드파티 고지

본 저장소의 코드에는 서드파티 소스가 포함되어 있지 않으며, 아래 소프트웨어를
외부 의존성으로 사용합니다.

| 소프트웨어 | 라이선스 | 사용 방식 |
|---|---|---|
| [PySide6](https://doc.qt.io/qtforpython/) | LGPLv3 / 상용 | `pip` 설치, GUI 프레임워크 |
| [ParaView](https://www.paraview.org/) (`paraview.simple`) | BSD-3-Clause | 사용자가 별도 설치, 변환 엔진 |

> PySide6를 포함한 단일 실행 파일(예: PyInstaller `--onefile`)을 만들어 **배포**하는
> 경우에는 LGPLv3의 재링크 관련 의무가 추가로 발생합니다. 소스 형태로 배포하거나
> 개인적으로 사용하는 경우에는 해당되지 않습니다.

ANSYS, Fluent, Workbench, optiSLang은 ANSYS, Inc.의 상표이며, Stochos는 Stochos의
상표입니다. 본 프로젝트는 이들 회사와 제휴·후원 관계가 없습니다.
