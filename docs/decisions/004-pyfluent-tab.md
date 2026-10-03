# 결정 004 — PyFluent 변환 탭 (라이브 Fluent 솔버 세션, VTU/VTP)

- 날짜: 2026-10-03 · 상태: **확정** (추천안대로 구현. 코드 검증 `docs/verification/v17-decision004.md` + 사용자 ⑦ GUI 시험 통과 2026-10-03 저녁, v2.0 화면 기준)
- 요청: 사용자 2026-10-03 "`00_Temp/Examples` 의 PyFluent 예제를 참고해서 PyFluent 를 이용한 VTU, VTP 변환 **탭**을 추가". 결정 003(E1, PyFluent 엔진 삭제)을 **부분 개정**한다: 변환기 탭의 엔진은 그대로 PyVista/ParaView 두 개이고, PyFluent 는 **별도 탭**으로 들어온다. 003 의 E2–E8 은 유효.
- 근거: `docs/probe/pyfluent-examples.md`(참조 스크립트 2종), `docs/probe/pyfluent-live.md`(이 PC 실측 §1–§5), `docs/probe/box.md`, 결정 001·002·003, impact-scan 보고(2026-10-03, 탭 구조·재사용 조각·헤드리스 시험 단언).

## 1. 맥락
- PyFluent 의 두 경로 중 오프라인 `FileSession` 은 셀 데이터를 못 주어 v1.5 에서 경계별 VTP 밖에 못 만들었다(결정 001·002). 사용자가 준 예제는 **라이브 솔버 세션**(`launch_fluent(mode="solver")`)으로 셀 존 격자(`get_mesh`)와 SVAR(`SV_*`)를 꺼내 VTU 를 만든다. 라이선스가 필요하고 케이스당 50–80 s 의 기동·읽기 비용이 든다(실측).
- 하류 요구(가정 포함): ① Stochos 학습 입력 `Design_NNN/Results.vtu` + `boundary_conditions.json` — 변환기 탭(PyVista 엔진) 결과와 **같은 폴더 규칙, 같은 Cell Data 기준, 같은 배열 이름**이어야 섞어 쓸 수 있다. ② VTP 는 1차 시험 때 사용자가 요구한 "모든 경계면이 포함된 하나의 VTP". ③ ParaView 시각 확인.

## 2. 가정
| # | 가정 | 틀리면 |
|---|---|---|
| A1 | 이 탭의 결과는 변환기 탭(PyVista) 결과와 같은 학습 세트에 섞인다 → 배열 이름·데이터 위치를 맞추는 것이 속도보다 우선 | 속도가 우선이면 축 1 의 대안 B |
| A2 | Fluent 라이선스는 변환 중 1석 사용 가능 (실측: 체크아웃 정상). 동시 변환은 하지 않는다 (케이스 순차) | 라이선스 부족이면 탭 자체가 못 돈다 → GUI 가 기동 실패를 `[ERROR]` 로 보여 준다 |
| A3 | 2D 케이스·다중 셀 존 샘플은 없다 → 코드는 지원하되 "미검증" 으로 둔다 | 샘플이 오면 `cff-probe` → 기준 추가 |
| A4 | 후처리 표면(`p-01`, `plane-44`, iso-line) 은 경계가 아니므로 VTP 대상이 아니다 | 필요하면 CLI `--surfaces` 로 명시 선택 (GUI 미노출) |

## 3. 후보 비교

### 축 1. VTU 생성 경로
| 후보 | 내용 | 근거 | 평가 |
|---|---|---|---|
| **A. 파이썬 재구성** (cas2vtu 방식) | `fd.get_mesh(셀 존)` + `svd.get_data(SV_*)` → vtkUnstructuredGrid 를 직접 조립 (hex/tet/pyr/wedge 순열, 폴리헤드론 `SetPolyhedralCells`, 바깥 방향 재감김, SV_VOLUME 대조) | live §2 (`Mesh.nodes/elements`, 폴리헤드론 `facets`), examples §1.4 (self-test 통과), box 0.5 s / Cyclone 22 s + 조립 시간(미측정) | 배열 이름이 **`SV_*`** 라 CFF 리더와 동일 → `cff_common.plan_renames` 와 `--rename` 의미가 변환기 탭과 같다. Fluent 버전 무관. 파일은 파이썬이 쓴다(한글 경로 OK). 단점: 큰 격자에서 느리고 메모리 큼(1 M Node 객체) |
| B. 네이티브 `settings.file.export.vtk` | Fluent 가 VTU 를 쓰고(0.8 s), 파이썬이 되읽어 이름 변경·벡터 조립 | live §5 | 배열 이름이 `Static Pressure` 식 **라벨**이라 라벨→표시명 표가 따로 필요(출처 없음), `velocity` 벡터 거부, `_MEAN/_RMS` 가 quantities 에 있는지 미확인, **26R1 이상 전용**, Fluent 가 파일을 쓰므로 한글·공백 경로 미검증, 되읽기로 I/O 2배 |
| **추천: A.** 이유: A1(이름·위치 호환). 틀렸을 때 드러나는 곳: Cyclone 변환이 수 분을 넘기면(기준 §6) B 를 CLI 옵션으로 추가 검토 |

### 축 2. VTP (경계)
| 하위 축 | 후보 | 추천 | 근거·드러나는 곳 |
|---|---|---|---|
| 대상 | (a) 경계 면 존만 (`zone_type==FACE`, 이름이 `interior` 로 시작하지 않고 `fd.surfaces.allowed_values()` 에 있는 것) / (b) 모든 표면(후처리 표면 포함) / (c) 외곽 표면 1장(PyVista 방식) | **(a)** | live §2: box `inlet/outlet/wall`, Cyclone 경계 5개 + 후처리 42개. (b) 는 선·평면이 섞이고 벡터 요청이 서버 오류를 냈다. (c) 는 PyVista 탭이 이미 한다 |
| 파일 | 병합 1장 `Results.vtp` / 경계별 `Results_<name>.vtp` | **병합 1장** + cell data `boundary_id`(int32, 존 id) + field data `boundary_names`(이름 목록) | 1차 시험 사용자 요구. 결정 002 R3 폐기 사유(경계별 파일)와 일치. 틀리면: ParaView 에서 경계를 구분 못 함 → `boundary_id` 로 Threshold |
| 기하 | `SurfaceFieldDataRequest(Vertices, FacesConnectivity, FacesCentroid, flatten_connectivity=True)` | 〃. `FacesNormal` 은 None 이라(live §2) 법선 기반 재감김은 불가. 대신 **실측(box 6,250면 전부 안쪽 법선)** 에 따라 다각형 노드 순서를 **전부 뒤집어** 바깥 법선으로 만든다 (`pyfluent_mesh.build_surface_mesh`). 선분(2D)은 그대로 | 틀리면: ParaView 에서 법선이 안쪽. 가시화에만 영향 (Stochos 는 셀 값만 씀). 판정: 경계별 바깥 법선 비율 = 1.00 |
| 값 위치 | 면 중심 cell data 만 / point(node) 동시 | **cell data 만** | 결정 001 D7(Cell 유지), examples R14(같은 이름이 점·셀 양쪽에 생김) |
| 값 출처 | (i) `ScalarFieldDataRequest(표시명)` — SV_*→표시명 변환표 필요(`SV_HEAT_FLUX`→`total-surface-heat-flux` 같은 예외 다수), float32 / (ii) **면 존 SVAR `svd.get_data(SV_*, zone_names=[존])`** — 이름 변환 불필요, `_MEAN/_RMS`·벡터(SV_WALL_SHEAR 3n) 그대로, float64 | **(ii)** — live §6 실측으로 면 순서 일치 확인 (box 중심차 ≤ 2.4e-7 m·SV_P 차 0, Cyclone 다각형 중심차 ≤ 5.6e-4 m·SV_P 상대차 ~5e-8, 정렬 전후 차이 동일) | 틀리면: 값이 엉뚱한 면에 붙는다 → 판정 기준 "SV_CENTROID vs FacesCentroid 최대 차 < 1e-3 m, box 는 < 1e-6" |
| 벡터 | SV_U/V/W 성분 조립 / `VectorFieldDataRequest('velocity')` | **성분 조립** (`velocity` = stack(SV_U,SV_V,SV_W)) | live §2: 벡터 요청이 Cyclone 에서 서버 오류 |

### 축 3. 변수 선택·이름
| 항목 | 결정 | 근거 |
|---|---|---|
| GUI 목록 | `--list-json` 이 `cell_arrays`(셀 존 SVAR 합집합) 와 `face_arrays`(경계 면 존 SVAR 합집합) 를 **둘 다** 돌려주고, GUI 는 선택 포맷에 맞는 쪽을 보여 준다. 포맷을 바꾸면 목록을 바꾸되 같은 이름의 체크는 유지 | live §3: 두 집합이 다르다(면 존에 `SV_WALL_SHEAR` 등, 셀 존에 `SV_K` 등) |
| 숨김 규칙 | 솔버 내부 배열은 기본 숨김: 접두사·접미사 규칙 `SV_ADS_*, SV_C_INDEX, SV_PARTITION, SV_CENTROID, SV_VOLUME, SV_AREA, SV_C0, SV_C1, SV_F_A*, SV_FACE_*, SV_F_GHOSTLINK, SV_LSQ_*, SV_LSF_*, SV_*_G, SV_*_RG, SV_*_RG_AUX, SV_MOM_AP_*, SV_BFP_V, SV_BF_MARANGONI, SV_BF_V, SV_MASS_IMBALANCE, SV_PRODUCTION, SV_FLUX_LIMIT, SV_FP_COEFF, SV_PP_COEFF, SV_DT_BC_SOURCE, SV_ARTIFICIAL_WALL_FLAG, SV_PROFILE_*, SV_WALL_FACE_FORCE, SV_WALL_KCON, SV_WALL_KS, SV_WALL_PRORUS_*, SV_WALL_DIFFUSIVE_*, SV_WALL_VV`. `--all` 은 숨김 포함 전부 | live §3. **`SV_BF_V` 는 box·dp_000 모두 전부 0** (PyVista 출력 실측) → 속도 벡터가 아니다 |
| `velocity` | `--vars` 에 `SV_U,SV_V,SV_W` 가 모두 있으면 벡터 `velocity`(3) 를 **추가**로 넣는다(성분 스칼라도 유지). `--rename` 과 무관하게 이름은 `velocity` | 하류 ①. PyVista 탭의 `SV_BF_V→velocity` 가 0 벡터인 문제는 **별도 후속**(결정 002 R1 매핑표 수정 후보)으로 기록 |
| `--rename` | `cff_common.plan_renames` 그대로 (`SV_P→pressure`, `SV_T→temperature`, `SV_U→x-velocity` …). 매핑 없는 이름은 원본 유지 + `[WARN]` 1줄 | 결정 002 R1 |
| 다른 탭과의 호환 | 변환기 탭에서 `SV_P,SV_T` + `--rename` 으로 만든 `Results.vtu` 와 이 탭의 결과는 **같은 이름·같은 셀 수**여야 한다 (판정 기준) | A1 |

### 축 4. 다중 셀 존·2D
| 항목 | 결정 | 근거 |
|---|---|---|
| 존 병합 | `vtkAppendFilter`, **절점 병합 없음** (`MergePointsOff`) — PyVista 탭의 `combine()` 과 같은 동작. `zone_id` 배열은 넣지 않는다(PyVista 탭과 배열 집합을 맞춤) | 결정 001 병합 축, examples §1.4 R16. D8(다중 존 샘플)은 여전히 미착수 |
| 2D | 삼각/사각 셀, 고스트 셀 제거, 경계는 선분 PolyData. 차원은 h5py 로 미리 읽고 실패 시 3→2 재시도 | examples §1.4. **미검증(샘플 없음)** |

### 축 5. 데이터 파일
| 항목 | 결정 |
|---|---|
| 해석 | `cff_common.resolve_data_file(case)` → 경로를 `read_data(file_name=…)` 에 **직접** 전달. 하드링크 폴더(`PreparedCase`) 는 만들지 않는다 (live §1: 임의 이름 수용 실측) |
| dat 없음 | `[ERROR] 데이터 파일(.dat.h5)을 찾지 못했습니다` + 종료코드 1. **초기화(standard/hybrid) 금지**, 격자만 변환도 없음 (결정 003 E5 와 동일). `--list-json` 은 `{"error": …}` + 1 |
| 로그 | `  데이터 파일: FFF.3-2-11200.dat.h5 (PyFluent 직접 지정)` |

### 축 6. 세션·중단·잔여물
| 항목 | 결정 | 근거 |
|---|---|---|
| 기동 | `launch_fluent(mode="solver", precision="double", processor_count=1, dimension=<감지>, ui_mode="no_gui_or_graphics", start_transcript=False, cleanup_on_exit=True, start_timeout=240, cwd=<임시 폴더>)`. `product_version` 은 CLI `--fluent-version` 으로만 (기본 = 설치된 최신) | live §1·§2·§5. `start_transcript=False` 가 아니면 stdout 에 전사가 섞인다 |
| 임시 cwd | `tempfile.mkdtemp(prefix="cff_pyfluent_")` (%TEMP%). 종료 후 삭제 시도, 실패해도 무시. 케이스 폴더·출력 폴더에는 `.trn` 이 안 생긴다 | live §2·§5 |
| 프로토콜 추가 | 기동 직후 `[FLUENT_PID] fluent=<fl pid> cortex=<cx pid>` 한 줄 (GUI 가 기억). 그 밖은 기존 프로토콜 그대로 | live §4 |
| 협조적 중단 | 워커는 stdin 을 읽는 데몬 스레드를 두고 `CANCEL` 한 줄을 받으면 플래그를 세우고 `solver.exit()` 를 부른다. 메인 스레드는 단계 사이에 플래그를 보고 `[ERROR] 사용자 중단` + 종료코드 1 로 끝난다 | live §4: kill 만으로는 Fluent 8개 프로세스가 남는다 |
| GUI 폴백 | `CANCEL` 뒤 30 s 안에 안 끝나면 `kill()`, 이어서 `[FLUENT_PID]` 로 받은 pid 에 `taskkill /T /F` (cortex → fluent 순). 워커가 CrashExit 로 끝났을 때와 앱 종료 때도 같은 pid 정리 | live §4: watchdog·cleanup bat 는 신뢰 불가 |
| 변수 로더 | `--list-json` 도 Fluent 를 띄우므로 타임아웃 600 s, 취소 시 같은 pid 정리 | live §1 |
| 종료 | 정상 경로는 `solver.exit(timeout=30)` → 임시 cwd 삭제 | live §4 |

## 4. 결정 요약
| # | 결정 | 틀렸을 때 드러나는 곳 |
|---|---|---|
| F1 | 새 탭 "PyFluent 변환"(4번째). 변환기 탭의 엔진 라디오·동작은 불변 | 헤드리스 v1.6 21/21 유지 |
| F2 | 워커 `pyfluent_export_worker.py` (일반 python, 통합 venv). 인자 `--case --output --format vtu\|vtp --vars --all --rename --list-json --ascii --processors --fluent-version`. 격자 조립 코드는 `pyfluent_mesh.py` 로 분리(참조 cas2vtu 의 순열·재감김·검증 이식) | argparse 종료코드 2 |
| F3 | VTU = 파이썬 재구성(축 1 A), Cell Data, `SV_*` 이름, `--rename` 은 `plan_renames`, `velocity` 는 SV_U/V/W 합성 | §6 기준 |
| F4 | VTP = 경계 면 존 병합 1장 `Results.vtp`, cell data 만, `boundary_id` + field data `boundary_names`, 값 출처는 면 존 SVAR(순서 일치 확인 시) | §6 기준 |
| F5 | dat 없음 = 실패. 초기화 금지. Workbench 이름은 `resolve_data_file` 로 직접 지정 | 빈/초기화 VTU 가 생기면 틀린 것 |
| F6 | 중단 = `CANCEL` 협조 종료 + pid 폴백. 임시 cwd. `[FLUENT_PID]` 줄 | 중단 뒤 `tasklist` 에 `cx2610`/`fl2610` 이 남으면 틀린 것 |
| F7 | 출력 규칙은 변환기 탭과 동일 (`<prefix>_NNN/Results.vtu|vtp`, `dp_016→Design_016`, 3자리) | bc_json 탭이 못 읽으면 틀린 것 |

## 5. 영향받는 코드
`pyfluent_export_worker.py`(신규), `pyfluent_mesh.py`(신규, 순수 numpy/vtk), `pv_export_gui.py`(탭 클래스 `PyFluentTab` 추가, `MainWindow` 생성·`closeEvent`, 공용 경로 함수 추출은 **하지 않고** 새 탭이 `ConverterTab` 의 staticmethod 와 모듈 상수를 그대로 쓴다 — impact-scan 권고), `cff_common.py`(숨김 규칙 상수 `HIDDEN_SVAR_PATTERNS` 추가), `requirements.txt`(ansys-fluent-core 복귀), `.bat`([3/4] import 검사), `docs/worker-protocol.md`, `README.md`, `USER_GUIDE.md`, `CLAUDE.md`, `tests/headless/`(새 시험; v16 의 `not hasattr(g,"ENGINE_PYFLUENT")` 단언은 새 상수 이름을 `PYFLUENT_ENGINE` 로 두어 그대로 통과시킨다).

## 6. 판정 기준 (`vtk-verify`)
변환 조건: 접두사 `Design`, 인터프리터 `D:/Venvs_collec/CFF2VTK_venv/venv/Scripts/python.exe`, 워커 `pyfluent_export_worker.py`. 기준 파일(비교 대상)은 변환기 탭 PyVista 엔진이 같은 인자로 만든 `Results.vtu`.

| 대상 | 항목 | 기대값 | 비고 |
|---|---|---|---|
| box VTU `--vars SV_P,SV_T --rename` | 타입 / cells / points | UnstructuredGrid / 31,250 / 34,476 | PyVista 엔진과 동일 |
| 〃 | cell_data 이름 집합 | `{pressure, temperature}` | point_data 비어 있음 |
| 〃 | 값 | PyVista 엔진 `Results.vtu` 의 같은 이름 배열과 **셀별 최대 절대차 ≤ 1e-6** (압력 최대 0.0547, 온도 최대 560.28) | 셀 순서가 같다는 가정. 다르면 정렬 후 비교하고 "순서 다름" 표기 |
| 〃 | celltypes | 전부 12 (hex) | |
| 〃 | 기하 검증 로그 | `[VERIFY] 부피 … SV_VOLUME 대비 상대오차 < 1e-9` 한 줄 | 음수 부피 0개 |
| box VTU `--vars SV_U,SV_V,SV_W` (rename 없음) | cell_data | `{SV_U, SV_V, SV_W, velocity(3)}` | `velocity[:,0] == SV_U` |
| box VTU `--vars SV_P --rename --ascii` | 파일 | 텍스트로 열림, `pressure` 1개 | |
| box VTP `--vars SV_P,SV_WALL_SHEAR --rename` | 타입 / cells | PolyData / 6,250 (= inlet 625 + outlet 625 + wall 5,000) | 점 수는 병합 전 합 ≤ 6,250+… (절점 병합 없음) |
| 〃 | cell_data | `{pressure, wall-shear(3), boundary_id}` ; field_data `boundary_names` = `[inlet, outlet, wall]` 순서는 존 id 오름차순 | `wall-shear` 는 wall 외 면에서 NaN |
| 〃 | 값 | `pressure` 가 wall 구간(5,000면)에서 PyFluent 면 존 SVAR `SV_P` 와 동일(차 0). 워커 로그 `[VERIFY] 면 중심 최대차` box < 1e-6 m, Cyclone < 1e-3 m | §3 축 2 값 출처, live §6 |
| 〃 | 금지 배열 | `vtkOriginalPointIds`, `vtkOriginalCellIds`, `Normals` 없음 | |
| 〃 | 면 방향 | `compute_normals(auto_orient_normals=False)` 셀 법선과 (면 중심 − 점 평균) 내적 > 0 인 비율 = 1.00 (경계별) | 저장 순서 전부 반전. **볼록한 box 에서만 유효한 검사** — Cyclone 처럼 비볼록(내부 vortex finder)이면 점 평균 기준 비율이 1 이 안 되는 게 정상(실측 0.52–1.00)이라 판정하지 않는다 |
| Cyclone VTU `--vars SV_P,SV_U,SV_V,SV_W --rename` (`FFF.3-2.cas.h5`) | cells / points | 394,817 / 1,013,398 ± 0 (절점 병합 없음) | PyVista 엔진은 점 수가 다를 수 있다(리더가 절점을 공유) → **셀 수와 값 분포(min/max)만** 비교 |
| 〃 | cell_data | `{pressure, x-velocity, y-velocity, z-velocity, velocity(3)}` | |
| 〃 | celltypes | 42(polyhedron) 261,079 + 12(hex) 133,738 | |
| 〃 | 소요 시간 | 워커 전체 ≤ 300 s, `최대 메모리:` 줄 출력 | 초과하면 축 1 대안 B 검토 |
| 〃 로그 | `데이터 파일: FFF.3-2-11200.dat.h5 (PyFluent 직접 지정)`, 케이스 폴더에 `.cff_link_*`·`*.trn` 없음 | |
| Cyclone VTP `--vars SV_P --rename` | cells | = 경계 면 존 5개 면 수 합 (inlet 481 + outlet 859 + wall_v-finder + outlet_under + wall_cyclone; 워커 로그의 존별 면 수와 일치) | 후처리 표면(`p-01`…) 포함 금지 |
| dat 없음 (`box.cas.h5` 만 복사) | `--list-json` / 변환 | `{"error": …}` + 1 / `[ERROR]` + 1, 출력 없음, Fluent 프로세스 잔존 0 | |
| **한글·공백 경로** (`…\입력 폴더 v17\a\dp_007.cas.h5`) | 변환 | 성공. 로그 `경로에 비ASCII 문자 → Fluent 용 ASCII 별칭 사용 (폴더 정션)`. **실측: Fluent 2026 R1 은 비ASCII 경로를 `File not found` 로 거부** → 워커가 %TEMP% 안 정션으로 우회 | 헤드리스 v17 |
| `--list-json` (box) | 키 | `engine="pyfluent"`, `cell_arrays`(숨김 제외, `SV_P`·`SV_T`·`SV_U` 포함, `SV_BF_V`·`SV_C_INDEX` 미포함), `face_arrays`(`SV_WALL_SHEAR` 포함), `boundaries`(이름·존 id·면 수), `fluent_version`, `data_file`, `n_cells` | 마커 사이 한 줄 JSON, Fluent 전사 미혼입 |
| 중단 | 변환 중 `CANCEL` 송신 | 30 s 안에 종료코드 1, `tasklist` 에 `cx2610.exe`/`fl2610.exe` 없음 | GUI 헤드리스 시험 |
| 〃 | `kill()` 뒤 pid 폴백 | `taskkill` 뒤 잔존 0 | |
| 프로토콜 | `[PROGRESS]` 단조 증가, 마지막 `[SUCCESS]`, 종료코드 0/1, `[FLUENT_PID]` 1줄 | |
| 회귀 | `tests/headless/gui_headless_test_v16.py` | 21/21 유지 (변환기 탭 불변) | |

## 7. 사용자가 고를 것 (추천 = 굵게)
| 축 | 추천 | 대안 |
|---|---|---|
| VTU 경로 | **파이썬 재구성 (SV_* 이름, 버전 무관)** | Fluent 네이티브 export (빠름, 26R1+, 이름 변환표 필요) |
| VTP 대상 | **경계 면 존 병합 1장 + boundary_id** | 경계별 파일 / 후처리 표면 포함 |
| VTP 값 | **면 중심 cell data 만** | point data 동시 |
| 속도 벡터 | **SV_U/V/W 합성 `velocity` 추가** | 성분만 |
| 중단 | **CANCEL 협조 종료 + pid 폴백** | kill 만 (Fluent 잔존 위험) |
