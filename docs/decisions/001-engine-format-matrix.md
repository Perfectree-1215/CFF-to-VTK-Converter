# 결정 001 — 엔진·포맷 조합과 경계 데이터 처리 방식

- 날짜: 2026-10-03 · 상태: **확정** (2026-10-03 사용자 3차 GUI 시험 통과. 유효 항목: D3 폴더·`Results.vtu` 규칙, D6 통합 venv, D7 Cell Data 유지, 변수 필터·combine() 축. 나머지는 아래 개정 참조)
- **개정 (v1.6, 결정 003)**: PyFluent 엔진 제거 → D1·D2·D4·경계 분리 축·§6 의 PyFluent 행 전부 무효. 엔진은 PyVista/ParaView.
- **개정 (v1.5, 결정 002로 대체된 항목)**: D1·D5 — VTM 제거, ParaView 엔진은 VTU 전용, PyFluent 엔진도 VTU 허용(하이브리드), ParaView 워커에 `--rename` 추가 / D3 — VTP 는 `Results.vtp` 한 파일(경계 통합, 경계별 파일은 CLI `--split-boundaries`), `Results_surface.vtp` 폐기 / 벡터·변수명 — 표시명 옵션 추가. §6 판정 기준 중 경계별 파일·PyFluent+vtu 거부 행은 `002-rename-merge-hybrid.md` §7 로 대체
- 범위: `docs/DEV_PLAN_pyvista_pyfluent.md` §3 D1~D5 + 스킬 결정 축(경계 분리 / 데이터 위치 / 벡터 / 병합)
- 근거: `docs/probe/box.md` (2026-10-03 실측, pyvista 0.47.3 / ansys-fluent-core 0.42.1)
- 보류: D8(다중 셀 존 내부 경계면) — 다중 존 샘플 확보 후 `cff-probe` → 별도 결정 002

## 1. 맥락
ParaView(pvpython) 의존을 없애려고 PyVista·PyFluent 엔진을 추가한다. 실측 결과 두 엔진은 서로를 대체하지 못한다.
- PyVista `FLUENTCFFReader`: 체적 격자 + 12개 셀 배열은 pvpython과 같으나, 블록 1개뿐이고 zone id 배열이 없어 **경계를 나눌 수 없다**.
- PyFluent `FileSession`: 경계 이름·id·연결성·면 중심값을 주지만 **체적 셀 데이터를 꺼내는 공개 API가 없다**.

## 2. 가정 (하류 요구, 확인 전까지 가정으로 둔다)
| # | 가정 | 근거 |
|---|---|---|
| A1 | Stochos DIM-GP 학습 입력은 `Design_NNN/Results.vtu` + `boundary_conditions.json`뿐이다. `.vtp`는 학습 입력이 아니다 | `bc_json_gen.py` 문서 문자열. `.vtp` 소비자는 ParaView 시각화·경계별 후처리 |
| A2 | 기존 pvpython 경로 결과(Cell Data, 리더 배열명 그대로)와 호환이 필요하다 | 이미 변환된 DP 세트와 섞여 쓰임. §6 P5의 min/max/mean 대조가 전제 |
| A3 | `bc_json_gen`·DP 정리 탭은 `Design_NNN` 폴더 직속 자식 폴더와 끝 번호만 본다. 폴더 안 파일 종류는 보지 않는다 | `bc_json_gen.scan_design_folders`, `extract_design_number` |
| A4 | Fluent 경계 이름에 파일명 금지 문자(`:` `/` 등)가 올 수 있다 (예: `wall:012`) | Fluent 관례. box에는 없음 |

## 3. 후보 비교

### D1 불가능한 조합(PyFluent + .vtu)의 처리
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. 엔진 선택 시 포맷 라디오를 갱신해 불가 조합을 비활성 + 안내 문구** | 실행 전에 막힘. 선택권(R1·R2) 유지 | GUI 상태 전이 코드 추가 |
| b. 실행 시 워커가 `[ERROR]`로 거부 | 구현 단순 | 일괄 변환 100개가 전부 실패한 뒤에야 알게 됨 |
| c. 포맷을 먼저 고르고 엔진을 자동 선택 | 조합 문제 자체가 사라짐 | PyVista `.vtp`(외곽 skin) 경로를 노출할 수 없음 |

### D2 `.vtp`의 기본 엔진
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. PyFluent** (경계별 파일, 이름 보존) | 경계별 분석에 이름이 필수 | 의존성 무거움, `SV_BF_V/SV_MU_*` 없음 |
| b. PyVista 외곽 skin 1장 | 의존성 가벼움, 셀 변수 12개 전부 | 경계 이름 없음. inlet/outlet/wall 구분 불가 |

### D3 `.vtp` 파일명
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. `Design_NNN/Results_<boundary>.vtp` (PyFluent), `Design_NNN/Results_surface.vtp` (PyVista skin)** | `Results.vtu`와 같은 폴더. bc_json·DP 탭 규칙(A3) 무변경. `.vtu`와 `.vtp`를 같은 폴더에 함께 둘 수 있음 | 파일 수가 경계 수만큼 늘어남 |
| b. `Design_NNN.vtm` 멀티블록 1개에 경계를 블록으로 | 파일 1개 | pyvista MultiBlock 저장은 VTM이라 포맷 라디오 의미가 흐려짐. PyVista skin과 규칙이 갈라짐 |
| c. `Design_NNN_<boundary>.vtp` 를 폴더 밖에 | 폴더 열지 않고 보임 | 루트에 파일이 쌓여 `scan_design_folders`가 폴더만 보긴 하나 사용자 혼동 |

### D4 interior-fluid 면 존
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. 기본 제외, `--include-interior` 로 포함** | box 기준 90,625면(전체 면의 93%)을 기본에서 뺀다 | 내부 면이 필요한 사용자는 체크박스를 켜야 함 |
| b. 항상 포함 | 선택지 없음 | 파일 크기·시간 지배, 시각화에 거의 안 씀 |

### D5 기존 ParaView 엔진
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. 세 번째 라디오로 남긴다. VTM은 이 엔진 전용** | P5 회귀 비교 기준. 실패 시 안전망 | 코드 두 벌 유지 |
| b. 삭제 | 단순 | 대조 기준이 사라져 P5 판정 불가 |

### 스킬 결정 축
| 축 | 후보 | 결정 | 이유 |
|---|---|---|---|
| 경계 분리 | 리더 블록 / zone id 배열 / 외곽 표면만 / pvpython 유지 | **PyFluent `surfaces()` 로 분리**. PyVista는 외곽 표면 1장만 | 리더 블록 1개, zone id 배열 없음(probe). pvpython도 경계 분리 안 함 |
| 데이터 위치 | Cell 유지 / Point 추가 / 둘 다 | **Cell Data 유지**. `--point-data` 플래그만 예약, 1차 미구현 | 원본 보존(A2). PyFluent 면값도 중심값이라 절점 평균 없음 |
| 벡터 | 리더 형태 그대로 / 성분 합쳐 벡터 추가 | `.vtu`: **리더 그대로**(`SV_BF_V`(N,3) + `SV_U/V/W`). `.vtp`(PyFluent): 사용자가 `velocity`를 고르면 (N,3) 추가 | `.vtu`는 pvpython과 배열 집합을 맞춰야 대조 가능(A2). PyFluent에는 `SV_BF_V`가 없어 `velocity`가 유일한 벡터 |
| 병합 | `combine()` / `combine(merge_points=True)` | **`combine()`** (기본값) | 블록 1개라 차이 없음. 다중 존은 D8(결정 002)에서 |

## 4. 결정 (추천안)
| # | 결정 | 틀렸을 때 드러나는 곳 |
|---|---|---|
| D1 | **a** — 엔진 라디오 변경 → 포맷 라디오 갱신. PyFluent 선택 시 VTM·VTU 비활성 + "PyFluent는 경계별 .vtp만 지원". ParaView 선택 시 VTP 비활성 | GUI에서 PyFluent + VTU로 실행이 되면 틀린 것 (워커가 `[ERROR]`로 2차 방어) |
| D2 | **a** — 앱 시작 기본값: 엔진 PyVista, 포맷 VTU. PyVista + VTP 선택 시 상태 줄에 "외곽 전체 1장, 경계 이름 없음. 경계별이면 PyFluent" 표시. 가이드에는 `.vtp` 권장 엔진 = PyFluent | 사용자가 PyVista `.vtp`를 열어 inlet을 못 찾을 때 |
| D3 | **a** — `_compute_output_path`가 `.vtp`일 때 `<parent>/<folder>/Results.vtp`를 **기준 경로**로 반환. 워커는 기준 경로의 stem(`Results`)으로 `Results_<name>.vtp`(PyFluent) / `Results_surface.vtp`(PyVista)를 만든다. 경계 이름은 `[^A-Za-z0-9_.-]` → `_` 로 치환(A4). 덮어쓰기 검사는 폴더 안 `Results_*.vtp` glob | bc_json 생성이 `Design_NNN`을 못 찾거나, 경계 이름에 `:`가 있어 저장 실패할 때 |
| D4 | **a** — 이름이 `interior`로 시작(대소문자 무시)하는 면 존은 기본 제외. GUI 체크박스 "내부 면 존 포함" → `--include-interior` | 기본 실행에 `Results_interior-fluid.vtp`가 생기면 틀린 것 |
| D5 | **a** — 라디오 3개(ParaView / PyVista / PyFluent). VTM은 ParaView에서만. `pv_export_worker.py` 무변경 | ParaView 엔진으로 box 변환이 P4 이후 실패하면 회귀 |
| 변수 필터 | PyVista: raw 리더 `SetCellArrayStatus`로 읽기 단계에서 끄기를 1차 시도, 실패하면 읽은 뒤 `cell_data.pop`. 결과는 같아야 한다 | `Results.vtu`에 선택하지 않은 배열이 남으면 틀린 것 |
| 없는 변수 | PyFluent: 요청 변수 중 `scalar_fields`/`vector_fields`에 없는 것은 `[WARN]` 1줄 후 건너뛴다. 유효 변수 0개면 `[ERROR]` | box에서 `SV_MU_T` 요청 시 KeyError로 죽으면 틀린 것 |

## 5. 영향받는 코드 (③ impact-scan 입력)
| 파일 | 변경 |
|---|---|
| `pv_export_gui.py` | 엔진 라디오·상태 줄, 포맷 라디오 활성화 규칙, `_compute_output_path` `.vtp` 분기, 덮어쓰기 glob, `_process_next` 인자 조립(`--engine`, `--surfaces`, `--include-interior`), `VariableLoader` 인터프리터 인자화, 경계 선택 리스트 |
| `cff_export_worker.py` (신규) | 두 엔진, `--list-json` 확장(`engine`, `surfaces`, `vector_fields`), 자기 검증 출력 |
| `pv_export_worker.py` | 변경 없음 |
| `bc_json_gen.py`, `dp_collect_tab.py` | 변경 없음 (A3) |
| `requirements.txt`, `.bat` | pyvista, `ansys-fluent-core[reader]` 추가. venv 하나 |
| `docs/worker-protocol.md` | `--list-json` 추가 필드, 새 인자 기록 (⑤에서 작성) |

## 6. 판정 기준 (box, `vtk-verify`가 그대로 대조)
변환 조건: 선택 변수 = `SV_P, SV_T, SV_BF_V`(PyVista) / `SV_P, SV_T, velocity`(PyFluent). 접두사 `Design`.

| 대상 파일 | 항목 | 기대값 | 비고 |
|---|---|---|---|
| `Design_NNN/Results.vtu` (PyVista) | 타입 | UnstructuredGrid | `samples/box/box.cas.h5`는 DP 번호가 없어 순번 1 → `Design_001`. `dp_000` 샘플이면 `Design_000` |
| 〃 | cells / points | 31,250 / 34,476 | |
| 〃 | cell_data 이름 집합 | 정확히 `{SV_P, SV_T, SV_BF_V}` | 선택하지 않은 배열 0개 |
| 〃 | `SV_BF_V` 성분 수 | 3 | `SV_P`, `SV_T`는 1 |
| 〃 | point_data 개수 | 0 | D7 전까지 |
| 〃 | `--all` 로 변환 시 cell_data 개수 | 12 | probe 표의 12개 이름과 집합 일치 |
| 〃 vs ParaView 엔진 `Results.vtu` | 같은 이름 배열의 min/max/mean | 상대 오차 < 1e-6 (0인 값은 절대 오차 < 1e-12) | 셀 순서는 비교하지 않음 |
| `Design_NNN/Results_surface.vtp` (PyVista, `--surface`) | 타입 / cells | PolyData / 6,250 | |
| 〃 | 금지 배열 | `vtkOriginalPointIds`, `vtkOriginalCellIds` 없음 | `pass_pointid=False, pass_cellid=False` |
| 〃 | cell_data 이름 집합 | `Results.vtu`와 동일 | |
| `Design_NNN/Results_inlet.vtp` | 타입 / cells / points | PolyData / 625 / 676 | PyFluent id 5 |
| `Design_NNN/Results_outlet.vtp` | cells / points | 625 / 676 | id 6 |
| `Design_NNN/Results_wall.vtp` | cells / points | 5,000 / 5,100 | id 7 |
| 〃 세 파일 공통 | cell_data 이름 집합 | 정확히 `{SV_P, SV_T, velocity}` | `velocity` 성분 수 3 |
| 〃 | point_data 개수 | 0 | |
| `Design_NNN/Results_interior-fluid.vtp` | 기본 실행 | 파일 없음 | D4 |
| 〃 | `--include-interior` | PolyData / 90,625 cells / 34,468 points | |
| PyFluent, `--vars SV_P,SV_MU_T` | 결과 | `[WARN]` 1줄 + `SV_P`만 저장 + 종료코드 0 | 없는 변수 건너뜀 |
| PyFluent, `--format vtu` | 결과 | `[ERROR]` 1줄 + 종료코드 1, 파일 생성 없음 | D1 2차 방어 |
| 폴더 규칙 | `dp_016.cas.h5` → `Design_016/` | 세 엔진 동일 | `FOLDER_NUM_WIDTH` = 3 |
| 파일명 치환 | 경계 이름 `wall:012` | `Results_wall_012.vtp` | A4. 단위 함수 테스트 |
| 워커 공통 | 종료코드 / 마커 | 성공 0 + `[SUCCESS]` 1줄, 실패 1 + `[ERROR]` 1줄 이상, `[PROGRESS]` 단조 증가 | |
| `--list-json` | 필수 키 | `cell_arrays`, `point_arrays`, `case_file`, `case_size_mb`, `engine` + (PyFluent) `surfaces[{id,name,faces}]`, `vector_fields` | 기존 키 유지 |
| 〃 (PyFluent, box) | `surfaces` | 4개: 1 interior-fluid 90625 / 5 inlet 625 / 6 outlet 625 / 7 wall 5000 | 제외 여부와 무관하게 목록엔 전부 |
| GUI | 중단 직후 | 워커 프로세스 종료, 다음 파일 미시작, 버튼 복구 | ⑤ 기준 |
