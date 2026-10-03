# Fluent CFF 유틸리티 (v2.1)

ANSYS Fluent 결과(CFF: `.cas.h5` + `.dat.h5`)를 정리하고 VTK 파일(VTU/VTP)로 바꾸는 Windows 데스크톱 앱입니다.
탭 네 개로 되어 있고, 보통 **왼쪽 탭부터 오른쪽으로** 순서대로 씁니다.

| 탭 | 하는 일 | 추가로 필요한 것 |
|---|---|---|
| **Workbench DP 정리** | Workbench 의 `dp0, dp1 …` 폴더에 흩어진 Case/Data 를 `dp_001.cas.h5` / `dp_001.dat.h5` 로 복사·이름 통일 | 없음 |
| **PyVista 변환기** | CFF → `Design_NNN/Results.vtu`(체적) 또는 `Results.vtp`(외곽 표면). 폴더 안의 모든 케이스를 한 번에. 빠르고 라이선스 불필요 | ParaView 엔진을 고를 때만 ParaView |
| **PyFluent 변환기** | 창 없는 Fluent 를 띄워 같은 CFF 를 VTU(Fluent 격자 그대로) / VTP(경계면을 한 장으로, `boundary_id` 로 구분)로. Fluent 는 배치당 한 번 기동, 케이스당 20 s–1분 | Ansys Fluent 설치 + 솔버 라이선스 1석 |
| **JSON 생성기** | 설계 테이블 CSV(`Parameters.csv`) → 설계 폴더마다 `boundary_conditions.json` (Stochos 학습용) | 없음 |

사용 방법은 **[USER_GUIDE.md](USER_GUIDE.md)** 에 있습니다.

## 설치와 실행

1. Python 3.10 이상이 설치되어 있어야 합니다 (검증: 3.12).
2. `setup_and_run.bat` 를 더블클릭합니다. 가상환경을 만들고 의존성을 설치한 뒤 앱을 띄웁니다.
   - 이후에는 같은 `.bat` 를 다시 실행하면 바로 앱이 뜹니다.
3. 직접 실행하려면:
   ```bash
   pip install -r requirements.txt
   python pv_export_gui.py
   ```
   `pvpython` 이 아니라 **일반 `python`** 으로 실행합니다.

## 요구사항

| 구성 | 필요한 경우 | 비고 |
|---|---|---|
| PySide6, pyvista (`requirements.txt`) | 항상 | pip 로 설치됨. PyVista 엔진은 이것만으로 동작 |
| ansys-fluent-core (`requirements.txt`) | PyFluent 변환기 탭 | pip 로 설치됨. 없으면 그 탭만 비활성 |
| Ansys Fluent 설치 + 솔버 라이선스 | PyFluent 변환기 탭 | 환경변수 `AWP_ROOTnnn` 으로 설치 위치를 찾음 (검증: 2026 R1) |
| ParaView 6.1 | PyVista 변환기에서 ParaView 엔진을 고를 때 | `pvpython.exe` 자동 탐지 |

## 파일 구성

| 파일 | 설명 |
|---|---|
| `pv_export_gui.py` | 앱 본체 (탭 4개) |
| `app_theme.py` | 화면 테마 (Solarized Light) |
| `dp_collect_tab.py` | Workbench DP 정리 탭 |
| `bc_json_gen.py` | JSON 생성기 (명령줄로도 실행 가능) |
| `session_log.py` | 세션 로그 (`logs/`) |
| `cff_common.py` | 공용: 변수 표시명 매핑표, 데이터 파일 이름 해석 |
| `cff_export_worker.py` | PyVista 변환 워커 |
| `pv_export_worker.py` | ParaView 변환 워커 (pvpython 이 실행) |
| `pyfluent_export_worker.py`, `pyfluent_mesh.py` | PyFluent 변환 워커와 격자 조립 |
| `requirements.txt`, `setup_and_run.bat` | 설치·실행 |
| `docs/` | 설계 결정 기록, 워커 프로토콜, 검증 기록, 작업 일지 |

모든 `.py` 는 **같은 폴더**에 있어야 합니다. 앱이 같은 폴더의 워커를 찾아 실행합니다.

## 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE)입니다. 외부 의존성: PySide6(LGPLv3), PyVista/VTK(MIT/BSD-3), ParaView(BSD-3, 사용자 설치), ansys-fluent-core(MIT, Fluent 본체는 별도 라이선스).
PySide6 를 포함한 단일 실행 파일로 **배포**할 때는 LGPLv3 의 재링크 의무가 생깁니다. 소스 형태로 쓰거나 배포하면 해당되지 않습니다.

ANSYS, Fluent, Workbench 는 ANSYS, Inc. 의 상표이고 Stochos 는 Stochos 의 상표입니다. 이 프로젝트는 두 회사와 관계가 없습니다.
