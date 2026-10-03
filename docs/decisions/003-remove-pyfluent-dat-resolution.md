# 결정 003 — PyFluent 엔진 제거, 데이터 파일 이름 해석 (v1.6)

- 날짜: 2026-10-03 · 상태: **확정** (사용자 지시: "불필요한 기능 제거, PyFluent 는 제거". 데이터 파일 해석은 버그 수정)
- **개정 (결정 004, v1.7)**: 사용자 요청으로 PyFluent 가 **별도 탭**(`PyFluentTab` + `pyfluent_export_worker.py`, 라이브 솔버 세션)으로 다시 들어왔다. E1 중 "변환기 탭의 PyFluent 엔진·경계 선택 UI·`--engine` 인자 삭제"는 그대로 유효하고, "`ansys-fluent-core` 의존성 삭제"만 되돌렸다. E2–E8 유효.
- 개정 대상: 결정 001 의 PyFluent 관련 항목 전부(D1·D2·D4, 경계 분리 축), 결정 002 의 R2(하이브리드)·R3(경계 통합 VTP). R1(표시명)·R4(VTM 제거)는 유효
- 근거: 사용자 2차 시험 로그 `logs/pv_export_20261003_113906.log` ("변수 0개 로드 완료", 입력 `FFF.3-2.cas.h5`), 2026-10-03 실측(§2)

## 1. 맥락
1. 사용자가 PyFluent 엔진을 쓰지 않기로 했다 → 엔진은 **PyVista(기본) / ParaView** 두 개. 경계 통합 VTP·경계 선택·면 변수는 모두 제거.
2. "PyVista 에서 변수 불러오기 안 됨"의 원인: Workbench 원본 폴더의 데이터 파일 이름이 `FFF.3-2-11200.dat.h5`(반복 횟수 접미사)라 vtkFLUENTCFFReader(PyVista·ParaView 공통)가 `FFF.3-2.dat.h5` 를 찾지 못하고 격자만 읽어 셀 배열이 0개였다. HANDOFF P7 "시계열 dat 처리" 항목이 실제로 막혔던 것.

## 2. 실측
| 실험 | 결과 |
|---|---|
| `FFF.3-2.cas.h5` 를 그대로 열기 | 리더 경고 `No data file (.dat.h5) found`, 셀 배열 0개 |
| 케이스 폴더 안 임시 폴더에 `case.cas.h5` + `case.dat.h5` 하드링크(`os.link`)를 만들어 열기 | 셀 배열 39개, 394,817 cells, 2.8 s. base 에 점이 있어도 짧은 이름으로 문제 없음 |
| 리더가 잡은 HDF5 핸들 | 프로세스의 **첫** vtkFLUENTCFFReader 인스턴스는 `SetFileName("")`·`del`·`gc`·atexit 어느 것으로도 종료 전에 핸들을 놓지 않는다. 두 번째 인스턴스부터는 놓는다 |
| 프로세스 종료 후 삭제 | 즉시 가능. 중단(kill) 직후에는 자식 인터프리터 종료가 수백 ms 늦어 재시도 필요 |
| `pv.get_reader` 가 점으로 시작하는 폴더(`.cff_link_*`) 안 경로 | 정상 |

## 3. 결정
| # | 결정 | 틀렸을 때 드러나는 곳 |
|---|---|---|
| E1 | PyFluent 엔진·`ansys-fluent-core` 의존성·경계 선택 UI·`--engine/--surfaces/--include-interior/--split-boundaries` 인자·`face_arrays`/`surfaces` 키 전부 삭제. `cff_var_names.py` 는 `cff_common.py` 로 흡수 | GUI 가 `--engine` 을 보내면 워커 argparse 종료코드 2 → 로더 "파싱 실패" |
| E2 | 데이터 파일 해석 `cff_common.resolve_data_file`: `<base>.dat.h5` 우선, 없으면 `<base>-<n>.dat.h5` 중 n 최대. `<base>-<n>.cas.h5` 가 함께 있으면 그 dat 는 형제 케이스 것이라 제외 | Workbench 원본에서 변수 0개면 틀린 것 |
| E3 | 이름이 다르면 케이스 폴더 안 `.cff_link_<rand>_tmp/` 에 `case.cas.h5`·`case.dat.h5` **하드링크**(실패 시 복사 + WARN)를 만들어 그 경로를 리더에 넘긴다. 두 워커 공통(`PreparedCase`) | 리더가 dat 를 못 찾으면 틀린 것 |
| E4 | 임시 폴더 정리는 층을 둔다: 워커가 읽은 뒤 시도(첫 리더라 보통 실패) → 워커 종료 시 재시도 → **GUI 가 워커 프로세스 종료 직후 `remove_stale_link_dirs(폴더, retries=10)`** (변수 로드·파일 완료·중단·앱 종료 모두) → CLI 는 다음 실행이 10분 지난 폴더 정리 | 변환 뒤 케이스 폴더에 `.cff_link_*` 가 남으면 틀린 것 (GUI 경로) |
| E5 | dat 가 전혀 없으면: `--list-json` 은 `{"error": …}` 마커 + 종료코드 1(GUI 오류창), 변환은 `[ERROR]` + 종료코드 1. **격자만 변환하던 동작은 폐지** | 빈 VTU 가 생기면 틀린 것 |
| E6 | GUI `_scan_folder` 는 경로에 `.cff_link_` 폴더가 끼면 제외. `bc_json_gen` 오인 방지를 위해 임시 폴더명은 `_tmp` 로 끝난다 | 같은 케이스가 두 번 변환되거나 bc_json 이 설계 번호 중복을 내면 틀린 것 |
| E7 | 포맷 전환은 변수 체크 상태를 유지한다 (v1.5 의 `_refresh_variable_list` 호출 제거) | 포맷 라디오를 바꾸면 체크가 풀리면 틀린 것 |
| E8 | 변수 0개(= dat 는 열렸으나 셀 배열 없음)이면 GUI 경고창 | |

## 4. 영향받는 코드
`cff_common.py`(신규), `cff_export_worker.py`(재작성), `pv_export_worker.py`(`prepare_case`/`cleanup_prepared`), `pv_export_gui.py`(엔진 2개, 경계 UI 삭제, 링크 폴더 정리, 스캔 제외, dat 사전 고지), `requirements.txt`, `.bat`, 문서 일체. `cff_var_names.py` 삭제.

## 5. 판정 기준 (`vtk-verify`)
변환 조건: 접두사 `Design`, `--rename` 기본. 인터프리터 `D:/Venvs_collec/CFF2VTK_venv/venv/Scripts/python.exe`, pvpython 6.1.0.

| 대상 | 항목 | 기대값 |
|---|---|---|
| box (`samples/Box/box.cas.h5`, 이름 일치) PyVista VTU `--vars SV_P,SV_T,SV_BF_V --rename` | cells / points / 이름 집합 | 31,250 / 34,476 / `{pressure, temperature, velocity}` (결정 002 와 동일). 케이스 폴더에 `.cff_link_*` 없음(링크 불필요) |
| box PyVista VTP `--vars SV_P --rename` | PolyData cells | 6,250, 이름 `{pressure}` (`--rename` 없이는 `{SV_P}`) |
| box ParaView VTU `--vars SV_P,SV_T --rename` | 이름 집합 | `{pressure, temperature}`, `.vtm` 없음 |
| **Workbench 식 픽스처**: box 를 `dp_007.cas.h5` + `dp_007-0100.dat.h5` 로 복사 | PyVista `--list-json` | `cell_arrays` 12개, `data_file` 끝이 `dp_007-0100.dat.h5`, `data_name_matches` false |
| 〃 PyVista VTU `--vars SV_P,SV_T,SV_BF_V --rename` | 결과 | box 와 동일(cells 31,250, 이름 집합). 로그에 `임시 하드링크로 연결` |
| 〃 ParaView VTU `--vars SV_P --rename` | 결과 | cells 31,250, `{pressure}`. 로그에 `임시 하드링크로 연결` |
| 〃 반복 횟수 두 개 (`dp_007-0100.dat.h5`, `dp_007-0200.dat.h5` 둘 다 box dat 복사) | `--list-json` 의 `data_file` | `dp_007-0200.dat.h5` (최대값) |
| 〃 형제 케이스 (`dp_007.cas.h5` + `dp_007-2.cas.h5` + `dp_007-2.dat.h5` 만) | `dp_007.cas.h5` 의 `--list-json` | `error` 키 (dat 없음) — `dp_007-2.dat.h5` 를 가져가지 않음 |
| dat 없음 (`box.cas.h5` 만 복사) | PyVista·ParaView `--list-json` | `###JSON_START###{"error": …}###JSON_END###` + 종료코드 1 |
| 〃 | PyVista·ParaView 변환 `--all` | `[ERROR]` 1줄 + 종료코드 1, 출력 파일 없음 |
| 실제 Workbench 원본 `samples/Cyclone/dp0/FFF/Fluent/FFF.3-2.cas.h5` | PyVista `--list-json` | `cell_arrays` 39개, `n_cells` 394,817 |
| 워커 CLI 직후 케이스 폴더 | `.cff_link_*_tmp` | 1개 남을 수 있음 (첫 리더 핸들). 10분 뒤 다음 실행이 정리 — "미검사(허용)" |
| GUI (헤드리스 시험) | 스캔 제외, 로드·완료·중단·종료 뒤 `.cff_link_*` 없음, `--engine` 미전송, 포맷 전환 시 체크 유지, dat 없는 케이스 실패 집계 | `docs/worker-protocol.md` §9 — 21/21 통과 |
| 제거 회귀 | `cff_export_worker.py --engine pyfluent` | argparse 오류, 종료코드 2 |
| 워커 공통 | 종료코드 0/1, `[SUCCESS]`, `[PROGRESS]` 단조 증가 | 결정 001 과 동일 |
