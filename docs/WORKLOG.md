# 작업 기록 (WORKLOG)

이어서 작업할 때 먼저 읽는 파일. 최신 항목이 위. 세부 근거는 `docs/decisions/`·`docs/verification/`·`docs/worker-protocol.md` 에 있고 여기엔 "오늘 무엇이 바뀌었고 지금 어디까지 왔는지"만 적는다.

---

## 2026-10-03 (밤) — v2.1 PyFluent 배치 세션 재사용 (결정 005 확정·구현)

### 한 일
1. 사용자 승인(설계 A). `pyfluent_export_worker.py`: `fail()` → `CaseFailed` 예외, `check_cancel()` → `Cancelled`; `ensure_session`(같은 차원이면 재사용, 아니면 닫고 재기동)·`load_case`(read_case/read_data, 차원 불일치 1회 재시도)로 `open_case` 대체; `ascii_alias(alias_dir)` 케이스별 폴더 + `cleanup_alias`(정션은 rmdir 로 링크만); `--jobs <json>` 모드 `run_jobs`(`[FILE_START]/[FILE_DONE]`, 케이스 실패는 계속, Fluent 호출 중 예외면 세션 폐기, work_dir mtime 갱신), 종료코드 0=전부 성공·1=일부 실패/중단; 단일 모드는 `run_case` 로 동일 동작.
2. `pv_export_gui.py` `PyFluentTab`: `_run_batch` 가 출력 경로 N개를 선계산해 `%TEMP%/cff_pyfluent_jobs_*.json` 에 쓰고 `_start_worker` 로 QProcess 1개 실행; `_emit_worker_lines` 가 `FILE_START_RE/FILE_DONE_RE` 로 라벨·로그·집계·진행률; `_on_worker_finished` 가 미보고 케이스를 실패 처리하고 크래시/≠0 일 때만 pid kill; `_cancel_batch` 의 `batch_index=batch_total` 트릭 제거; jobs 파일은 종료·중단·shutdown 에서 삭제. 확인창·안내문 "Fluent 1회 기동".
3. 시험: `tests/headless/gui_headless_test_v17.py` 를 jobs 모드로 개정 — 한글 경로 케이스 3개 [dat 없음, 정상(Workbench 식 dat 이름), 정상], `[FLUENT_PID]` 1회, 실패 뒤 세션 계속, 2번째 케이스 중 CANCEL → 3번째 미시작, 로더 중 shutdown. `samples/` 가 없으면 외부 Box(`…/Claude code-pyfluent/samples/Box`) 자동 탐색(`CFF_BOX_DIR`).
4. 문서: worker-protocol §1b(v2.1 행), 결정 005 확정, CLAUDE.md 불변 규칙, USER_GUIDE 5장·FAQ·버전 이력, README. 앱 버전 v2.1.

### 결과
- `gui_headless_test_v17.py` **4차 32/32 통과** (`docs/verification/v21-decision005.md`). Box 3건 배치 41 s(Fluent 1회 기동, 기존 방식이면 ≈ 3×43 s), 실패 케이스 뒤 세션 유지, 2번째 케이스 중 CANCEL 12 s·3번째 미시작, 로더 중 shutdown 뒤 잔존 0.
- 1~3차에서 잡은 결함 3건(모두 고침): ① 워커 메인 스레드가 CANCEL 리스너의 `solver.exit()` 를 안 기다리고 끝나 Fluent 가 반쯤 닫힌 채 수십 초 잔존 → `close_session` 이 `_EXIT_DONE` 대기 ② 종료 뒤에도 pid 가 남는 경우 → 워커 `_ensure_pids_gone` + GUI `kill_fluent_pids` 소멸 확인·재시도, 로더 CANCEL 유예 20 s ③ 로더 임시 폴더가 `.trn` 잠금으로 안 지워짐 → `[WORKDIR]` 줄 + GUI 지연 삭제(즉시·60 s 간격).
- 결정 005 **확정·구현 완료**. 변환기 탭(`ConverterTab`)·JSON 생성기 코드는 jobs 패치 전과 바이트 동일.
- **사용자 ⑦ 통과** (2026-10-04 "모두 이상 없음"). 2026-10-04 마무리: `docs/CLEANUP_PLAN.md` 삭제, README·USER_GUIDE 에 임시 폴더 지연 삭제 안내 추가, **v2.0+v2.1 를 한 커밋으로 origin/main 에 푸시**.

---

## 2026-10-03 (저녁) — v2.0 화면 개편 (사용자 지시서 `00_Temp/수정사항-01.pptx`)

### 지시 내용
1. 앱 전체 디자인을 Solarized Light 테마로, 글자 크기·굵기를 위치마다 조절. 2. "CFF To VTK 변환기" → **"PyVista 변환기"**, 2단 레이아웃(슬라이드 2). 3. "PyFluent 변환" → **"PyFluent 변환기"**, 같은 레이아웃(슬라이드 3). 초보자도 쓰기 쉽게.

### 한 일
1. impact-scan: 인라인 색 지정 45곳(4개 파일), 다크 QSS 가 `ConverterTab._apply_dark_theme` + `TAB_QSS` 로 나뉘어 MainWindow 가 합성, DP 표 `Qt.yellow`, 변수 체크박스 3열 고정, 탭 이름 참조는 코드 2곳 + 문서. 깨지면 안 되는 속성명 목록 확보 → 전부 유지.
2. **`app_theme.py` 신설**: Solarized 팔레트, `APP_QSS`(탭·카드형 그룹·입력·버튼 primary/danger·체크/라디오·진행바·목록·콘솔·알림창), `set_role()`(역할 속성으로 색 전환), `append_log()`(콘솔 줄 색: ERROR 빨강·WARN 주황·완료 초록·GUI 회색), `ConsoleEdit`, `apply_palette()`(Windows 다크 모드 차단).
3. `pv_export_gui.py`: `ConverterTab`/`PyFluentTab._build_ui` 를 2단으로 새로 씀(왼쪽 1·2·4 / 오른쪽 3·실행·중단·진행 / 아래 콘솔), pvpython 행 `pv_row_widget` 은 ParaView 선택 시만 표시, 출력 설정의 "폴더명·출력 위치"를 한 행으로, 변수 체크박스 2열, 다크 QSS·`TAB_QSS` 삭제, 인라인 색 → `set_role`, 탭 이름 변경, `APP_TITLE` v2.0, **탭 페이지를 `QScrollArea#tabScroll` 에 담음**(작은 화면: 잘림 대신 세로 스크롤), `_apply_initial_size()`(페이지 sizeHint 를 화면 가용 영역으로 클램프; 이 모니터 1215×976), `setMinimumSize(960, 640)`.
4. `dp_collect_tab.py`·`BCJsonTab`: 색 → 역할, 표 상태 셀 `Qt.yellow` → 주황, 콘솔 `ConsoleEdit`, DP 표 `_DPTable`(선호 높이 150).
5. 검증: `tests/headless/gui_headless_test_v20_layout.py` **48/48** (탭 이름, pvpython 행 토글, 다크 리터럴 0, 2열, 콘솔 색, 세 화면 크기에서 그룹 눌림·잘림 0, 가로 스크롤 없음) · v16 **21/21** · v17 **27/28** — 유일한 FAIL "임시 작업 폴더 잔존 0" 은 이날 오후 CLI 실험이 남긴 `%TEMP%\cff_pyfluent_wgs9f51p`(.trn 이 다른 프로세스에 잠겨 삭제 불가)가 배치 전부터 있었던 것으로, 화면 개편과 무관. 스크린샷으로 육안 확인(스크래치 `ui18/shots`). **사용자 ⑦(실제 화면) 대기**.
6. 문서: README·USER_GUIDE(6장 화면 구성, 14장 제목·앵커, 버전 이력 v2.0)·CLAUDE.md(v2.0 화면 규칙)·worker-protocol §9 탭 이름.
7. **JSON 생성기 탭** (사용자 3차 지시, 구 boundary_conditions.json): ① 탭·제목 "JSON 생성기" ② `00_Temp/Parameters.csv` 형식(`Name,inlet_length,cone_length,vortex_finder_length` / `DP n,…`) 지원 — 읽기 자체는 되고 있었으나 기본 매핑의 `V.Finder_length` 가 안 맞아 실패했음 → `bc_json_gen.generate_bc_jsons` 에 **자동 모드**(매핑이 비면 설계번호 열을 뺀 CSV 열을 그 순서대로 JSON 키로; `_op`·비숫자 열 제외, 키 충돌 오류), 키 순서 검증도 실제 col_map 기준으로 ③ 파라미터 매핑 선택화(기본 비움, 빈 매핑 허용) ④ 누락 기준설계 직접 입력 UI·메서드 제거(라이브러리 CLI 옵션은 유지) ⑤ [작성 방법 자세히](`CSV_FORMAT_HELP`)·[예시 CSV 저장…](`EXAMPLE_CSV_TEXT`, UTF-8 BOM+CRLF) 버튼, CLI `--auto-params`·`--write-example` ⑥ impact-scan 지적 반영: cp949 CSV 폴백, 헤더 공백 시 DictReader 키 불일치 수정. 시험 `tests/headless/gui_headless_test_v20_bcjson.py` **20/20**(Parameters.csv → Design_000/036 값·키 순서·사이드카, 매핑 지정·오류, Workbench 식 CSV 자동/기본 모드), 레이아웃 48/48. USER_GUIDE 13장 전면 개정(앵커 변경 `#13-json-생성기-탭-boundary_conditionsjson-생성-stochos-dim-gp-학습용`).

### 마무리 정리 (v2.0 — 계획서는 이 항목으로 흡수하고 삭제)
- 2단계 삭제 완료: `logs/`, `__pycache__/`, `00_Temp/`(Parameters.csv 는 `tests/data/` 로 이동), 깨진 옛 시험 3개, `docs/DEV_PLAN_pyvista_pyfluent.md`(P0–P6 전부 완료되어 삭제; 결정 001·002 와 WORKLOG 가 내용을 대신함), `.gitignore` 를 프로젝트용 10여 줄로 축소. `.bat` 를 `setup_and_run.bat` 로 개명. `samples/` 는 3단계 회귀 시험 뒤 삭제 예정.
- 3단계 코드 클린업 완료: pyflakes 를 venv 에 설치해 전수 검사(지적 0, `paraview.simple import *` 만 의도된 예외). 제거: `dp_collect_tab` 미사용 import 2개, `pv_export_gui` 미사용 지역변수·`engine_status_labels`, `bc_json_gen` 수동 기준설계 코드(`manual_designs`·`_apply_manual_designs`·CLI `--manual-*`), `app_theme` 미사용 상수 2개, 코드 주석의 v1.x 이력 문구 전부(13곳), 시험 파일 미사용 import. `pv_export_gui` 모듈 docstring 을 v2.0 구성으로 새로 씀. 회귀: v20 레이아웃 48/48·v20 JSON 20/20·mesh selftest 0 failure·**v16 21/21·v17 27/28**(FAIL 1 = 오후 CLI 실험이 남긴 `%TEMP%\cff_pyfluent_wgs9f51p` 의 잠긴 .trn, 환경 요인). 그 뒤 **`samples/` 7 GB 삭제**. `_build_ui` 공통화는 사용자 비승인으로 하지 않음.
- 4단계 문서: README 83→59줄(소개·탭 표·설치·요구사항·파일 구성·라이선스), USER_GUIDE 940→300줄(설치 / 화면 공통 / 탭 4장 각 "언제 쓰나→순서→결과→알아 둘 것" / 문제 해결 표 3종+FAQ / 부록 CLI·버전 이력). 옛 장 번호 참조(결정 005 의 "14장")도 갱신. 레이아웃 시험은 `samples/` 대신 `tests/data/scan_sample/` 의 빈 .cas.h5 를 스캔하도록 수정.
- **사용자 ⑦ 통과** ("테스트 결과 이상 없음", 2026-10-03 저녁) → 결정 004 를 확정으로 바꿈. 결정 005(세션 재사용)는 구현 전이라 제안 유지.
- 남은 것: 커밋(보류 중, 사용자 측 자동 커밋 `6b1285b` 가 22:12 에 한 번 있었음), 결정 004·005 상태 확정 여부.

### 알아둘 것
- 워드랩 QLabel 이 하나라도 있으면 `QScrollArea(widgetResizable)` 는 페이지를 **선호 높이**(min 이 아님)로 키운다 → 콘솔·표의 sizeHint 를 낮춘 이유. FHD 125 %(논리 1536×826) 노트북에서는 변환기 탭이 약 110 px, DP 탭이 약 180 px 세로 스크롤된다(잘림은 없음). 이 모니터(2048×1232)는 스크롤 없음.
- `processors>1` 안내문을 PyFluent 탭 스핀박스 툴팁에 넣었다("2개 이상이면 셀 순서가 바뀜").
- **사용자 2차 피드백 반영 (같은 날 저녁)**: "테마는 좋은데 글씨가 안 보인다" → 콘솔 출력(9.5pt)만 빼고 전부 **+2pt**(본문 12, 보조 11.5, 그룹·탭 12.5, 제목 18, 실행 버튼 13), 글자색을 Solarized 의 가장 어두운 쪽으로(본문 base02 `#073642` 대비 10.6:1, 강조 base03, 보조 base01 4.4:1), 상태색은 같은 색조로 어둡게(OK `#5f7300`·WARN `#a63d10`·ERROR `#c0211e`·파랑 글자 `#1b6ca8`, 전부 4.4:1 이상). bc_json 의 고정폭 입력란은 role `mono`(11.5pt, 높이 88). 레이아웃 시험 48/48 재통과, 시작 크기 1362×1022(이 모니터).

---

## 2026-10-03 (오후) — v1.7 PyFluent 변환 탭 (사용자 요청: `00_Temp/Examples` 예제 참고)

### 한 일
1. 참조 스크립트 2종 정독(`docs/probe/pyfluent-examples.md`, 서브에이전트) + 라이브 Fluent 실측(`docs/probe/pyfluent-live.md`): 기동 30–45 s, read_case 11–36 s, `get_mesh` 는 셀 존만, SVAR 이름은 `SV_*`, 면 존 SVAR 순서 = 표면 요청 순서(VTP 값 출처 근거), 네이티브 `export.vtk` 는 라벨 이름·표면 크래시, **워커 kill 만으로는 Fluent 8개 프로세스 생존(watchdog·cleanup bat 신뢰 불가)**.
2. 결정 004(`docs/decisions/004-pyfluent-tab.md`, **제안** 상태로 구현 진행): VTU = 파이썬 재구성(cas2vtu 이식), VTP = 경계 면 존 병합 1장 + `boundary_id`, 값은 면 존 SVAR, `velocity` = SV_U/V/W 합성, dat 없음 = 실패, 중단 = stdin `CANCEL` + pid 폴백.
3. 구현: `pyfluent_mesh.py`(numpy/vtk, 부호 규약을 VTK 기준으로 통일 — 참조 스크립트의 wedge 면 정의는 VTK 와 반대였음), `pyfluent_export_worker.py`, `cff_common.is_hidden_svar`, `pv_export_gui.py` 의 `PyFluentTab`/`PyFluentVariableLoader`/`kill_fluent_pids`(4번째 탭), `requirements.txt`·`.bat` 에 ansys-fluent-core 복귀, `docs/worker-protocol.md` §1b.
4. box CLI: VTU 58 s(SV_VOLUME 대비 상대오차 0, 표시명, velocity(3)), VTP 52 s(6,250면, boundary_id, wall-shear 는 inlet/outlet 에서 NaN). PyVista 엔진 VTU 와 값 집합은 같으나 **셀 순서가 다르다**. 경계면 저장 순서의 법선이 전부 안쪽 → 전부 반전해 바깥으로.
5. 발견(후속 과제): PyVista 엔진의 `SV_BF_V→velocity` 는 box·dp_000 에서 **0 벡터**다 (결정 002 R1 매핑표 수정 후보 — 사용자 판단 필요).

7. 사용자 1차 실행 보고 "실행 안 됨 (`still은(는) 예상되지 않았습니다`)": `.bat` 의 `if errorlevel 1 ( … )` 블록 안 echo 문구에 괄호 `(PyVista/ParaView)` 가 있어 cmd 가 블록을 조기 종료 → 괄호 제거. 실행 생략 사본으로 [4/4] 까지 파싱 확인.
6. 시험 중 고친 것: 상대 경로(Fluent 는 임시 cwd 기준) → `resolve()`; **한글 경로는 Fluent 가 `File not found`** → `%TEMP%` 정션 별칭(`ascii_alias`); `ConverterTab` staticmethod 차용 시 `staticmethod()` 재포장; `solver.exit(wait=20)` 으로 워커 종료 = Fluent 종료.
8. 사용자 요청 "여러 CFF 일 때 Fluent 1회 기동으로" 실측 (`docs/probe/pyfluent-live.md` §7): 한 세션에서 격자가 다른 케이스 6건 연속 `read_case` → 존·셀 수·SVAR 갱신 OK, 출력은 케이스별 기동과 최대차 0, 메모리 평탄. 절감 케이스당 35–40 s (Cyclone 급 −35 %, box 급 −67 %, 13 DP 추정 21–23분 → 14–15분). `processors=4` 는 안 빨라지고 **셀 순서가 바뀜**. → **결정 005**(`docs/decisions/005-pyfluent-session-reuse.md`, 제안): 워커 `--jobs` 파일 + `[FILE_START]/[FILE_DONE]` 줄, 배치당 QProcess 1개(설계 A). impact-scan 으로 GUI 8개 메서드·워커 9개 함수 범위 확인. **코드는 미수정 — 사용자 선택 대기**

### 상태 (2026-10-03 19:00)
| 항목 | 상태 |
|---|---|
| 헤드리스 `tests/headless/gui_headless_test_v17.py` | 27/28 (1건은 시험 기준 오류, 수정) · v16 회귀 21/21 · `pyfluent_mesh_selftest.py` 0 failure |
| Cyclone(Workbench 원본) | VTU 74.7 s / 1.44 GB, VTP 48.6 s, 값 집합이 PyVista 엔진과 동일 |
| vtk-verify (결정 004 §6) | 통과 27 / 실패 0 / 조건 다름 4 / 판정 불가 7 → `docs/verification/v17-decision004.md` |
| 결정 004 | **확정** (사용자 ⑦ 통과 2026-10-03 저녁) |
| 사용자 ⑦ 시험 | **통과** (2026-10-03 저녁, v2.0 화면으로 "테스트 결과 이상 없음") |
| 문서 | README·USER_GUIDE(14장 신설, 서브에이전트 작성)·CLAUDE.md·worker-protocol §1b·요구사항·.bat 갱신 |
| git | v1.5~v1.7 전부 **미커밋** (신규: cff_common 외 `pyfluent_export_worker.py`, `pyfluent_mesh.py`, 결정 004, probe 2종, 검증 v17) |
| 결정 005 (세션 재사용, v2.1) | **확정·구현 완료** (2026-10-03 밤, v17 32/32 — `docs/verification/v21-decision005.md`) |
| 후속 과제 | ① PyVista 엔진 `SV_BF_V→velocity` 0 벡터 문제(결정 002 R1 매핑 수정 여부, 사용자 판단) ② 2D·wedge·다중 존 샘플 확보 시 검증 ③ `--ascii`·`--processors>1` 미실행 ④ 중단/shutdown 뒤 `%TEMP%\cff_pyfluent_*` 1개 남을 수 있음(10분 뒤 자동 정리) ⑤ `processors>1` 은 셀 순서가 바뀌고 속도 이득 없음 → 기본 1 유지·안내문 검토 ⑥ `ascii_alias` 정션 이름 `case_dir` 고정은 세션 재사용 시 충돌(005 §5.1) |

---

## 2026-10-03 — v1.5 → v1.6 (PyVista 엔진 도입, PyFluent 제거, Workbench dat 이름 해석)

### 한 일 (순서대로)
1. **P0–P6 (v1.5)**: `docs/DEV_PLAN_pyvista_pyfluent.md` 대로 PyVista 엔진 추가. 신규 워커 `cff_export_worker.py`, 결정 001(엔진·포맷 행렬), 통합 venv `CFF2VTK_venv`, GUI 엔진 라디오.
2. **1차 사용자 시험 반영 (v1.5)**: 표시명 옵션 `--rename` (SV_P→pressure 등, 결정 002 R1), VTM 을 GUI 에서 제거(R4), `boundary_conditions.json` 생성을 세 번째 탭 `BCJsonTab` 으로 분리 + JSON 파일명 입력란.
3. **2차 사용자 시험 반영 (v1.6)**:
   - "PyVista 변수 불러오기 안 됨" 원인: Workbench 원본은 `FFF.3-2.cas.h5` + `FFF.3-2-11200.dat.h5` 라 vtkFLUENTCFFReader 가 dat 를 못 찾아 셀 배열 0개. 해결: `cff_common.PreparedCase` 가 케이스 폴더 안 `.cff_link_<rand>_tmp/` 에 `case.cas.h5`·`case.dat.h5` 하드링크를 만들어 읽음. 두 워커 공통.
   - 프로세스의 **첫** CFF 리더는 종료 전까지 HDF5 핸들을 안 놓는다(실측). 그래서 임시 폴더는 GUI 가 워커 프로세스 종료 뒤 `remove_stale_link_dirs(retries=10)` 로 지운다. CLI 는 10분 지난 폴더만 정리.
   - **PyFluent 엔진 완전 제거** (사용자 지시). `--engine/--surfaces` 인자, 경계 선택 UI, ansys 의존성, `cff_var_names.py`(→`cff_common.py` 로 흡수) 삭제. 결정 003 으로 기록.
   - dat 가 없으면 변환하지 않는다 (`--list-json` 은 `{"error":…}` + 종료코드 1, 변환은 `[ERROR]` + 1). 포맷 전환 시 변수 체크 유지. 변수 0개면 경고창.
4. **3차 사용자 시험**: "Workbench DP 정리" 탭·"CFF To VTK 변환기" 탭 이상 없음 → 결정 001(유효 항목)·002(R1·R4) 상태를 확정으로 갱신.
5. 헤드리스 시험 스크립트를 임시 스크래치에서 `tests/headless/` 로 복사 (gitignore 대상, 로컬 보관). 실행법은 아래.

### 지금 상태
| 항목 | 상태 |
|---|---|
| 엔진 | PyVista(기본, `cff_export_worker.py`, venv python) / ParaView(`pv_export_worker.py`, pvpython 6.1.0) |
| 포맷 | VTU (두 엔진), VTP 외곽 표면 1장 (PyVista 만). VTM 은 CLI 전용 |
| 결정 기록 | 001 확정(유효 항목), 002 R1·R4 확정, **003 확정** |
| 검증 | 결정 003 §5 전부 통과 (`docs/verification/v16-decision003.md`), 헤드리스 v1.6 21/21 |
| 사용자 시험 | DP 정리 탭·변환 탭 통과. **boundary_conditions.json 탭은 미보고** |
| git | v1.5·v1.6 변경 **미커밋** (수정 11 + 신규 5 파일, 이 기록 포함). 이전 커밋들은 사용자 측 자동 커밋이었음 |
| 미착수 | D8 다중 셀 존 케이스의 내부 경계면 처리 — 다중 존 샘플 없음. 샘플이 오면 `cff-probe` 부터 |

### 이어서 할 때
- 코드 수정 전 CLAUDE.md 라우팅 표를 따른다. GUI↔워커를 건드리면 `gui-worker-link` 스킬 재호출, 출력이 바뀌면 `vtk-verify` (기준: 결정 003 §5).
- 헤드리스 회귀: 
  ```
  "D:/Venvs_collec/CFF2VTK_venv/venv/Scripts/python.exe" tests/headless/gui_headless_test_v16.py "<임시 폴더>"
  ```
  첫 인자는 출력·입력 사본을 만들 임시 폴더. 샘플 `samples/Box/`, `samples/Cyclone/dp0/FFF/Fluent/` 가 있어야 한다. 기대 21/21.
- 커밋을 요청받으면 한 번에 묶어도 된다: "v1.6: PyFluent 제거, Workbench dat 이름 해석, 표시명 옵션, bc_json 탭 분리".
- 사용자가 bc_json 탭 결과를 보고하면 `docs/DEV_PLAN_pyvista_pyfluent.md` 상태 줄의 "미보고" 를 갱신한다.

### 오늘 얻은 환경 사실 (CLAUDE.md 에도 반영됨)
- venv `python.exe` 는 런처. kill 하면 자식도 죽는다. 피크 메모리는 워커가 출력하는 `최대 메모리:` 줄로 본다.
- 샘플은 사용자가 하위 폴더로 재배치: `samples/Box/`, `samples/00_Collect/01_Rename/dp_000/`(140 MB), `samples/Cyclone/dp*/FFF/Fluent/`.
- dp_000 변환 시간: PyVista 14 s / 피크 1,025 MB (변수 2개면 614 MB), ParaView 3 s. 결과 VTU 는 두 엔진 동일(오차 0).
- Bash 도구의 heredoc 은 본문에 `\"` 가 있으면 깨진다 → 그런 파일은 Write 도구로 쓴다.
