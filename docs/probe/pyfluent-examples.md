# probe: PyFluent 참조 스크립트 2종 (cas2vtu.py / fluent_to_vtu.py)

- 날짜: 2026-10-03 · 방법: 두 스크립트 전문 정독 + 설치된 `ansys-fluent-core` 소스·생성 설정 파일 정적 대조 + `cas2vtu.py --self-test`(오프라인) 1회 실행. **Fluent 는 실행하지 않았다.** 실행 결과로 확인된 항목과 코드만 보고 적은 항목을 구분해 표기한다 (표의 "근거" 열).
- 대상: `00_Temp/Examples/cas2vtu.py`(1424행) · `00_Temp/Examples/fluent_to_vtu.py`(704행)
- 환경 실측: `D:/Venvs_collec/CFF2VTK_venv/venv` — ansys-fluent-core **0.42.1**, vtk 9.7.1, pyvista 0.49.0, numpy 2.5.3, h5py 3.16.0, Python 3.12.9
- 이 PC 의 Fluent 설치: 환경변수 `AWP_ROOT242`, `AWP_ROOT252`, `AWP_ROOT261`(= `C:\Program Files\ANSYS Inc\v261`) 설정됨. `C:\Program Files\ANSYS Inc\` 에 `v232 v242 v252 v261` 폴더. PyFluent `FluentVersion.get_latest_installed()` 실측 결과 = **Ansys Fluent 2026 R1**. 0.42.1 의 `FluentVersion` 열거: v271, v261, v252, v251, v242 (v232 미지원)
- 맥락 주의: 결정 003(`docs/decisions/003-remove-pyfluent-dat-resolution.md`)이 v1.6 에서 PyFluent 엔진을 제거했다. 이 문서는 그 결정을 바꾸지 않으며, 두 참조 스크립트가 무엇을 하는지만 기록한다.

## 0. 한눈에 보기

| 항목 | cas2vtu.py | fluent_to_vtu.py |
|---|---|---|
| 한 줄 요약 | Fluent 는 **데이터 공급원**으로만 쓴다. 셀 존 메쉬·SVAR 를 gRPC 로 받아 **파이썬에서 VTK 메쉬를 직접 재구성**하고 vtk XML 라이터로 저장 | VTU 는 **Fluent 자체 VTK 내보내기**(`settings.file.export.vtk`)를 호출, VTP 는 필드 데이터 API + PyVista |
| 볼륨 메쉬 추출 | `field_data.get_mesh(zone)` + 파이썬 루프 | 없음 (Fluent 가 파일을 씀) |
| 출력 | `.vtu`, `.vtp`, `.vtm`(수제 XML) | `.vtu` 또는 `.vtp` 1개 |
| 변수 이름 체계 | VTU: `SV_*`(원본) 또는 기본 12종 표시명 / VTP: Fluent 표면 필드 이름 | Fluent "quantities" 이름 (VTU), 표면 필드 이름 (VTP). `SV_*` 아님 |
| 진행률·프로토콜 | `[PROGRESS]`/`[SUCCESS]`/`[ERROR]` 없음. 로그는 **stderr**(logging) | 〃 없음. 단계 메시지는 stdout(print, flush 없음), 오류는 stderr `ERROR: …` |
| 종료 코드 | 0 / 1 / 2 혼재 (§1.1) | 0 / 1 (argparse 오류만 2) |
| 요구 Fluent | 코드 주석상 2025 R2·2026 R1 에서 검증 (cas2vtu.py:87-90) | VTU 경로의 `file.export.vtk` 는 설치된 0.42.1 생성 설정 중 **261·271 에만 존재** (§3.4) |

---

## 1. cas2vtu.py

### 1.1 목적·CLI·종료·출력 방식

목적: 모듈 docstring(cas2vtu.py:2-50) — "Convert an Ansys Fluent case (.cas.h5) [+ data (.dat.h5)] to VTK .vtu using PyFluent". 헤드리스 솔버 세션 → case(+data) 읽기 → 셀 존별 `get_mesh()` → VTK 비정형 격자 재구성 → `.vtu`. `--vtp` 면 경계 면 존(+케이스에 저장된 후처리 표면)을 `.vtp` 로.

CLI (`parse_args`, 1342-1379):

| 인자 | 기본값 | 의미 |
|---|---|---|
| `case` (위치, `nargs="?"`) | — | `.cas.h5 .cas .msh.h5 .msh` 등. `--self-test` 가 아니면 필수 (1377-1378) |
| `-d/--data` | None | 데이터 파일. 생략 시 케이스 옆에서 자동 탐색 (`find_data_file`) |
| `--no-data` | off | 데이터 무시, 메쉬만 |
| `-o/--output` | `<케이스 폴더>/<stem>.vtu` (1405) | 출력 `.vtu` 경로 |
| `-z/--zones` | 전체 | 셀 존 이름 (`nargs="+"`) |
| `-f/--fields` | 기본 12종 | SVAR 이름 (`nargs="+"`, 공백 구분 — 쉼표 아님) |
| `--all-fields` | off | `SKIP_FIELDS` 를 뺀 모든 셀 SVAR |
| `--domain` | `mixture` | SVAR 도메인 |
| `--per-zone` | off | 존마다 `.vtu` + `.vtm` (표면도 면마다 `.vtp` + `.vtm`) |
| `--vtp` | off | 경계 면을 `<stem>_surfaces.vtp` 로도 출력 |
| `--no-vtu` | off | VTU 생략 (`--vtp`/`--surfaces` 필요, 아니면 종료코드 2: 1402-1404) |
| `-s/--surfaces` | 경계 존 전체 | 표면 이름. 지정하면 `--vtp` 함의 |
| `--surface-fields` | 기본 표면 필드 | Fluent 표면 필드 이름 (`pressure wall-shear velocity` 등) |
| `--all-surface-fields` | off | 가능한 표면 필드 전부 |
| `--ascii` | off | ASCII XML (기본은 zlib 압축 binary) |
| `--no-check` | off | Fluent SV_VOLUME/SV_CENTROID 대조 생략 |
| `--fluent-ids` | off | `FluentCellId` 셀 배열 추가 |
| `--list` | off | 존·SVAR·표면·표면 필드를 stdout 에 텍스트로 출력하고 종료 |
| `--version` | None | Fluent 제품 버전(`25.2.0` 형식). 기본 = 설치된 최신 |
| `--precision` | `double` | `single`/`double` |
| `--dimension` | None | 2/3. 기본 = h5py 로 읽음, 실패 시 3 + 자동 재시도 |
| `-n/--processors` | 1 | Fluent 프로세서 수 |
| `--gui` | off | Fluent GUI 표시 |
| `--self-test` | off | 오프라인 단위 점검 후 종료 |
| `-v/--verbose` | off | 이 스크립트의 debug 로그 |

종료 동작 (`main`, 1382-1420 / `convert`):

| 상황 | 종료 코드 | 근거 |
|---|---|---|
| 정상 완료 | 0 | 1420 |
| 케이스 파일 없음 / 명시한 데이터 파일 없음 / `--no-vtu` 단독 | **2** | 1393-1395, 1399-1401, 1402-1404 |
| 알 수 없는 셀 존·표면 이름 | **1** (`raise SystemExit("메시지")` → 문자열은 stderr, 코드 1) | 986, 1111 |
| 그 외 예외 (Fluent 오류, `RuntimeError` 등) | 1 (파이썬 트레이스백) | 처리 없음 |
| **기하 검증 불일치**, 표면 0개로 파일 0개 | **0** (경고만) | 1191-1193, 1016-1017 |
| `--self-test` 실패 | 1 | 1315 |

출력 방식: `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)-7s %(message)s")` (1384) → 기본 핸들러는 **stderr**. `print` 는 `--list`(1117-1128)·self-test 에서만 stdout. pyfluent 로거 6종은 ERROR 로 낮춤 (1386-1388). 진행률 숫자·`[SUCCESS]`·`[ERROR]` 접두사 없음. 완료 줄: `Done in %.1f s. Files: …` (1419).

### 1.2 Fluent 실행

`launch_solver` (248-271), 호출처 `convert` 1085-1086:

| kwarg | 값 | 비고 |
|---|---|---|
| `dimension` | `--dimension` 또는 `detect_dimension()`(h5py) 또는 3 | 1085 |
| `precision` | `--precision` (기본 double) | |
| `processor_count` | `-n` (기본 1) | |
| `mode` | `"solver"` | |
| `ui_mode` | `--gui` ? `"gui"` : `"no_gui_or_graphics"` | Fluent 인자 `-g` (launch_options.py:176-199) |
| `start_transcript` | False | |
| `cleanup_on_exit` | True | |
| `cwd` | `tempfile.mkdtemp(prefix="cas2vtu_fluent_")` (1084) | 트랜스크립트·정리 스크립트를 출력 폴더 밖에 두려는 목적 (주석 1082-1083) |
| `product_version` | `--version` 이 있을 때만 | |
| `start_watchdog` | **False** (267) | `TypeError` 면 이 인자 없이 재호출 (268-269) |
| `start_timeout` | 지정 안 함 | PyFluent 기본 사용: `config.launch_fluent_timeout` = 환경변수 `PYFLUENT_FLUENT_LAUNCH_TIMEOUT` 또는 **100초** (module_config.py:270-272) |

- 버전·경로 탐색: 스크립트는 직접 하지 않는다. `--version` 이 `product_version` 으로 가고, 없으면 PyFluent 가 `AWP_ROOTnnn` 중 최신을 고른다 (launch_options.py:358-391, process_launch_string.py:141-180). 우선순위: `fluent_path` kwarg(미사용) → `product_version` → (`PYFLUENT_FLUENT_ROOT` 개발용) → 최신 `AWP_ROOT`. 이 PC 에서는 2026 R1 (실측).
- 세션 종료: `finally` 에서 `solver.exit()` (1198-1203) — `wait` 없음 → 종료 요청만 보내고 반환, 직후 `shutil.rmtree(work_dir, ignore_errors=True)` (1203). 예외는 삼킨다. 차원 불일치 재시도 경로도 `solver.exit()` 후 새로 띄운다 (1097-1102).
- 재시도: `read_case` 예외 문자열에 `"wrong dimensions"` 가 있으면 2D↔3D 를 바꿔 Fluent 를 다시 띄움 (1089-1102).
- `launch_solver` 자체가 실패하면 `try` 밖이라 `work_dir`(mkdtemp) 이 남는다 (1084-1086 vs 1088).
- 로그: `Fluent %dD launched in %.1f s (%s)` (270) 로 기동 시간·버전을 출력한다 (값은 미측정).

### 1.3 case/data 읽기

| 항목 | 내용 | 근거 |
|---|---|---|
| API | `solver.settings.file.read_case(file_name=…)` 후 `solver.settings.file.read_data(file_name=…)` 를 **따로** 호출. `read_case_data` 미사용 | `read_case` 274-284 |
| data 탐색 | `find_data_file` (1333-1339): `case_stem()` 이 `.cas.h5 .cas.gz .cas .msh.h5 .msh.gz .msh` 접미사를 떼고, `DATA_SUFFIXES = (".dat.h5", ".dat.gz", ".dat")`(1322) 를 **같은 stem** 으로 시도 | 1321-1339 |
| 명시 지정 | `-d` 로 경로를 주면 그대로 `read_data` 에 전달. 파일이 없으면 종료코드 2 | 1398-1401 |
| dat 없음 | `find_data_file` → None → `has_data=False`. 로그에 `Data : (none - mesh only)` 한 줄(1408)만 남고 **계속 진행**(메쉬만 VTU). 오류 아님, 종료코드 0 | 1396-1399, 1408, 274-283 |
| `FFF.3-2-11200.dat.h5` 같은 이름 | 이름 해석 로직 **없음** (글롭·접미사 후보·최대 반복 선택 없음). `FFF.3-2.cas.h5` 만 주면 자동 탐색이 실패해 **메쉬만** 나온다. `-d FFF.3-2-11200.dat.h5` 로 직접 주면 그 경로가 그대로 `read_data` 로 간다. Fluent 가 임의 이름의 dat 를 받아들이는지는 **미실행이라 미확인** | 1333-1339 |
| 2D/3D | `detect_dimension` (229-245): h5py 로 `h["meshes"]` 각 항목의 `dimension` 속성. h5py 가 없거나 실패하면 None → 3 | |

### 1.4 메쉬 추출

| 항목 | 내용 | 근거 |
|---|---|---|
| 존 목록 | `solver.fields.field_data.get_zones_info()` 중 `zone_type == ZoneType.CELL` → `[(z._id, z.name)]`. `ZoneType` 은 0.42.1 에서 `{CELL, FACE}` | 294-299 |
| 추출 단위 | **셀 존 하나씩** `solver.fields.field_data.get_mesh(zone_name)` → `Mesh.nodes`(x,y,z 객체), `Mesh.elements`(`_id`, `element_type`, `node_indices`, `facets`) | `fetch_zone_mesh` 403-412 |
| 변환 | `build_zone_mesh` (336-400): 절점은 `np.fromiter`(343), 요소는 **파이썬 for 루프**(354-384)로 평탄 배열 구성 → `ZoneMesh` 데이터클래스 (155-199) | |
| 셀 타입 | 아래 표. 2D 고스트 셀(`FL_GHOST=8`)은 버림(356-358). 미지원 타입은 `RuntimeError`(375-376), 절점 수 불일치도 `RuntimeError`(378-380) | 71-102 |
| 폴리헤드론 | 각 facet 의 `node_indices` 를 `face_conn/face_offsets/face_cell` 에 저장, 셀 절점은 facet 절점의 고유 집합 | 360-371 |
| 절점 순서 보정 | hex/tet/pyramid 는 밑면 감김 반전 (`FLUENT_TO_VTK` 순열), wedge 는 그대로. 주석: Fluent SV_VOLUME 과 상대오차 < 1e-12 로 검증 (2025 R2 / 2026 R1) | 81-102 |
| 방향 재보정 | `orient_polyhedra` (451-469): facet 법선이 셀 중심에서 **바깥**을 향하도록 재감김 (중심 = SV_CENTROID, 없으면 절점 평균). `orient_linear_cells` (504-528): 타입별 다수결로 음수 부피면 `VTK_FLIP` 적용 | |
| 부피·중심 검증 | `verify_against_fluent` (629-672): Fluent 식(면 팬)으로 부피 재계산 → SV_VOLUME 과 셀별·총합 비교, 점평균 중심 → SV_CENTROID 비교(1 셀 크기 초과면 경고). **로그/경고만, 실패로 취급하지 않음**(종료코드 0). `--no-check` 로 생략. SV_VOLUME/SV_CENTROID 는 데이터가 있을 때 얻어짐(주석 1140) | 1140-1167 |
| 2D | `is_2d_case`: `solver.scheme.eval("(rp-2d?)")` (287-291). 삼각/사각 셀(타입 1·3), 부호 있는 xy 면적 검증(496-500), SV_CENTROID 가 2성분이면 z=0 패딩(1149-1150) | |
| VTK 격자 | `to_vtk_grid` (531-588): `vtkUnstructuredGrid`. 폴리헤드론이 있으면 VTK ≥ 9.4 의 `SetPolyhedralCells`, 아니면 구형 face-stream 삽입. 설치된 vtk 9.7.1 에는 `SetPolyhedralCells` 있음(실측) | |
| 존 병합 | `merge_grids` (609-623): `vtkAppendFilter` + `MergePointsOff` — **절점 병합 없음**(존 경계 중복 절점). 존이 1개면 병합 생략(1187) | |
| 오프라인 검증 | `--self-test` 를 이 환경에서 실행: **SELF-TEST PASSED** (hex/tet/pyramid/wedge 부피·순열 8건, 폴리헤드론, 평탄 face 파싱, PolyData, 표면 방향, 병합 — 모두 ok) | 1224-1315, 실측 |

Fluent→VTK 셀 타입 표 (`FLUENT_TO_VTK`, 91-102):

| Fluent id | 이름 | VTK 타입 | 순열 |
|---|---|---|---|
| 1 | triangle | VTK_TRIANGLE(5) | 0,1,2 |
| 3 | quadrilateral | VTK_QUAD(9) | 0,1,2,3 |
| 2 | tetrahedron | VTK_TETRA(10) | 0,2,1,3 |
| 4 | hexahedron | VTK_HEXAHEDRON(12) | 0,3,2,1,4,7,6,5 |
| 5 | pyramid | VTK_PYRAMID(14) | 0,3,2,1,4 |
| 6 | wedge | VTK_WEDGE(13) | 0,1,2,3,4,5 |
| 7 | polyhedron | VTK_POLYHEDRON(42) | facet 스트림 (별도) |
| 8 | ghost (2D) | 버림 | — |
| 9-12 | quad tet/hex/pyr/wedge | VTK_QUADRATIC_* (24-27) | 항등 (재감김·검증 대상 아님) |

### 1.5 필드 추출

| 항목 | 내용 | 근거 |
|---|---|---|
| 변수 목록 | `solver.fields.solution_variable_info.get_variables_info(zone_names=[zone], domain_name=domain)` → `info.solution_variables`(이름), `info[name].dimension`. 이름은 **`SV_*`** | `available_svars` 302-317 |
| 값 | `solver.fields.solution_variable_data.get_data(variable_name, zone_names=[zone], domain_name)` — **변수 1개 × 존 1개마다 1회 호출**. 결과는 존 이름 키 dict | `get_svar` 320-330 |
| 위치 | **셀 데이터만** (VTU 에 point data 없음). 길이가 셀 수와 다르면 경고 후 건너뜀(1068-1070) | `attach_fields` 1046-1072 |
| 선택 규칙 | `--fields` 지정 → 그 이름만 (없는 이름은 **경고 후 제외**, 1038-1040). `--all-fields` → `SKIP_FIELDS` 제외 전부. 둘 다 없으면 `DEFAULT_FIELDS` ∪ `SV_U/V/W` 만 | `pick_fields` 1035-1043 |
| 이름 바꾸기 | 기본 선택일 때만(`rename = not fields and not all_fields`, 1050) `DEFAULT_FIELDS` 표시명(CamelCase)으로 바꿈. `--fields` 로 주면 `SV_*` 그대로 | 1050, 1071 |
| 벡터 | 기본 선택에서 `SV_U/V/W` 중 2개 이상이면 `Velocity` (n,3) 로 합침, 없는 성분은 0(1052-1059). 그 밖의 다차원 SVAR 는 `(n_cells, dim)` 로 reshape(1066-1067). 명시 `--fields SV_U SV_V SV_W` 는 스칼라 3개로 따로 나옴 | |
| 추가 배열 | `ZoneId`(int32, 1162), `FluentCellId`(`--fluent-ids`, 1164) | |

### 1.6 VTP / 경계 출력

| 항목 | 내용 | 근거 |
|---|---|---|
| 대상 선택 | `surfaces_info()`: `solver.fields._field_info._get_surfaces_info()`(비공개), 실패 시 `solver._fluent_connection._service_factory.field_data.get_surfaces_info()` (678-693). 항목 키: `surface_id`, `zone_id`, `zone_type`, `type` | |
| 기본 대상 | `type == "zone-surf"` 이고 `zone_type != "interior"` — 즉 **경계 존만**(내부면 제외). 내부 존은 `--surfaces` 로 명시해야 함(주석 989-990). 모듈 docstring(16-18)의 "post-processing surfaces" 포함 서술과 코드(991-992)는 다르다: 기본값에서는 `zone-surf` 가 아닌 표면이 빠진다 | 989-992 |
| 파일 단위 | 기본: 전부 `vtkAppendPolyData` 로 **1개 병합** `<stem>_surfaces.vtp` (`-o x.vtp` 면 그 경로). `--per-zone`: 표면마다 `<stem>_<안전한이름>.vtp` + `<stem>_surfaces.vtm` | 1005-1028 |
| 기하 요청 | `SurfaceFieldDataRequest(surfaces=names, flatten_connectivity=True, data_types=[Vertices, FacesConnectivity, FacesCentroid, FacesNormal])`. **2D 에서는 `FacesNormal` 을 빼야 함**: "requesting FacesNormal in a 2-D session crashes Fluent (observed with 2026 R1)" | 777-783 |
| 면 폴리곤 | `_parse_flat_faces` (720-739): `[n,i0..,n,…]` 평탄 배열 → (offsets, conn). 균일/혼합 모두 처리 | |
| 방향 | `orient_surface_faces` (839-863): Fluent 저장 순서의 우수 법선은 영역 안쪽을 향하므로 `FacesNormal` 에 맞게 재감김(바깥). 엣지(2점)는 그대로 | |
| 검증 | `verify_surface` (866-884): 꼭짓점 평균 vs `FacesCentroid`. 로그만 | |
| 2D 처리 | 2점 "면" = 선분 → `to_vtk_polydata` 가 `SetLines`, 나머지는 `SetPolys` (선분을 먼저 두므로 셀 데이터도 같은 순서로 재배열) | 887-938 |
| 점/셀 데이터 | 스칼라: 필드마다 `node_value=True`(→ **point data**) 와 `node_value=False`(→ **cell data**) **둘 다 같은 이름**으로 요청(786-789, 824-827). 벡터: `VectorFieldDataRequest` → 면 값(cell data) 만 — 주석 141-143 "Fluent provides no node vectors". 응답이 없거나 크기가 안 맞으면 NaN 배열로 채워 표면 간 배열 구성 일치(828-831) | 786-836 |
| 추가 배열 | cell data `SurfaceId`, `ZoneId` (int32) | 833-834 |
| 기본 표면 필드 | `DEFAULT_SURFACE_FIELDS` 12종 + 벡터 `velocity` (아래 7b) 중 케이스에 존재하는 것 | 704-717 |
| 요청 방식 | `fd.new_batch()` + `add_requests(*requests)` 로 **한 번에**, 실패하면 하나씩(742-765) | |
| 데이터 없을 때 | `has_data=False` 면 필드 요청 없음 → 기하만 (997-1000) | |

### 1.7 출력 레이아웃·라이터

| 파일 | 이름 규칙 | 내용 |
|---|---|---|
| VTU(병합) | `-o` 또는 `<케이스 폴더>/<stem>.vtu` | 모든 셀 존 병합, 절점 중복 |
| VTU(`--per-zone`) | `<out stem>_<_safe(존이름)>.vtu` + `<out>.vtm` | `_safe` 는 영숫자·`-_.` 외를 `_` (1207-1208) |
| VTP | `<stem>_surfaces.vtp` 또는 `<stem>_<_safe(표면)>.vtp` + `<stem>_surfaces.vtm` | `stem` 은 `case_stem(out_path)` (1325-1330) |
| VTM | `_write_vtm` (1211-1218) 이 XML 을 손으로 씀 (`vtkMultiBlockDataSet`, `DataSet index/name/file`) | |

- 라이터: `vtk.vtkXMLUnstructuredGridWriter` / `vtk.vtkXMLPolyDataWriter` (591-606, 957-972). 기본 `SetDataModeToAppended` + `EncodeAppendedDataOff`(raw) + `SetCompressorTypeToZLib`. `--ascii` 면 `SetDataModeToAscii`. 쓰기 실패 시 `RuntimeError`.
- PyVista 는 **선택**: 있으면 `pv.wrap`으로 감싸 반환, 없으면 vtk 객체 그대로(585-588). meshio 미사용.
- **임시 파일 + 교체 없음**: 목적 경로에 바로 씀 → 도중에 죽으면 불완전 파일이 남는다. 덮어쓰기 확인 없음.

### 1.7b 이름 표

`DEFAULT_FIELDS` (VTU 기본 선택일 때만 적용, 123-136):

| SVAR | VTK 배열 이름 |
|---|---|
| SV_P | Pressure |
| SV_T | Temperature |
| SV_DENSITY | Density |
| SV_K | TurbKineticEnergy |
| SV_D | TurbDissipationRate |
| SV_O | SpecificDissipationRate |
| SV_MU_LAM | LaminarViscosity |
| SV_MU_T | TurbViscosity |
| SV_H | Enthalpy |
| SV_VOF | VolumeFraction |
| SV_WALL_DIST | WallDistance |
| SV_VOLUME | CellVolume |
| SV_U/V/W | → `Velocity` (n,3) (137, 1052-1059) |

그 밖의 상수: `SKIP_FIELDS = {SV_CENTROID, SV_C_INDEX, SV_PARTITION, SV_ADS_0, SV_ADS_1}` (139). `DEFAULT_SURFACE_FIELDS` (144-148): `pressure, total-pressure, velocity-magnitude, temperature, density, wall-shear, y-plus, turb-kinetic-energy, turb-diss-rate, specific-diss-rate, total-surface-heat-flux, wall-temperature` + `DEFAULT_SURFACE_VECTORS = ["velocity"]` (149). 표면 필드 이름은 Fluent 표시명 그대로(바꾸지 않음).

프로젝트 `cff_common.FLUENT_DISPLAY_NAMES` 와의 관계(코드 대조): 이 표는 **CamelCase** 이고 프로젝트 표는 Fluent 표시명(`pressure`, `temperature`, `turb-kinetic-energy`, `turb-diss-rate`, `specific-diss-rate`, `y-plus`, `wall-shear` …)이라 이름이 서로 다르다. 반대로 `DEFAULT_SURFACE_FIELDS` 의 이름은 프로젝트 표시명과 같은 철자가 여럿이다(`pressure`, `temperature`, `density`, `turb-kinetic-energy`, `turb-diss-rate`, `specific-diss-rate`, `y-plus`, `wall-shear`).

### 1.8 의존성

| 항목 | 내용 |
|---|---|
| 필수 | `numpy`, `vtk`(함수 안 지연 import: `import vtk`, `vtkmodules.util.numpy_support`), `ansys-fluent-core` (`pyfluent.launch_fluent`, `ansys.fluent.core.fields.live_field_data.ZoneType`, `ansys.fluent.core.fields.field_data_interfaces` 의 `ScalarFieldDataRequest/SurfaceDataType/SurfaceFieldDataRequest/VectorFieldDataRequest`) + 설치된 Fluent |
| 선택 | `pyvista`(`pv.wrap`), `h5py`(`detect_dimension`) |
| 버전 | `ansys-fluent-core` 최소 버전 명시 없음. 주석은 PyFluent 0.42 / Fluent 2025 R2·2026 R1 에서 검증이라고 함 (87-90). `start_watchdog` 없는 구버전 대비 `TypeError` 폴백 (268-269) |
| 비공개 API 사용 | `fields._field_info._get_*_info` (680), `solver._fluent_connection._service_factory.field_data` (685), `zone._id`, `element._id` — 0.42.1 에서 모두 존재 확인(§4) |

---

## 2. (참고) cas2vtu.py 의 흐름 요약

`main` → `parse_args` → `convert`: `mkdtemp` → `launch_solver` → `read_case` → `is_2d_case` → `list_cell_zones` → (`--list` 이면 출력 후 반환) → 존마다 [`fetch_zone_mesh` → SV_VOLUME/SV_CENTROID 조회 → `orient_polyhedra`/`orient_linear_cells` → `attach_fields` → `ZoneId` → `verify_against_fluent` → `to_vtk_grid` → (per-zone 이면 `write_grid`)] → 병합·`write_grid` → (`--vtp` 이면 `export_surfaces`) → `finally: solver.exit(); rmtree`.

---

## 3. fluent_to_vtu.py

### 3.1 목적·CLI·종료·출력 방식

목적: docstring(2-9) — `.cas.h5` → VTU 또는 VTP. "VTU volume export uses Fluent's native VTK exporter through PyFluent. VTP surface export uses PyFluent's Field Data API and PyVista, avoiding a native surface-export crash observed in Fluent 2026 R1." 데이터 파일이 없으면 **유동장을 초기화한 뒤** 내보낸다.

CLI (`build_parser`, 586-684):

| 인자 | 기본값 | 의미 |
|---|---|---|
| `case_file` (위치, 필수) | — | `.cas.h5` 만 허용 (`CASE_SUFFIX`, 22, 447-448) |
| `-o/--output` | `<케이스 폴더>/<base>.vtu|.vtp` | 확장자로 포맷 결정 |
| `--format {vtu,vtp}` | 출력 확장자에서 추론, 없으면 vtu | 확장자와 충돌하면 `ConversionError` (60-72) |
| `--data` / `--ignore-data` (상호 배타) | 자동 탐색 / off | dat 지정 / 자동 탐색 안 함(초기화) |
| `-z/--zone` | 전체 | 셀 존, 반복·쉼표 구분(`flatten_values`, 75-80). **VTU 전용** |
| `-s/--surface` | 전체 | 표면, 반복·쉼표. **VTP 전용** |
| `-q/--quantity` | 없음(메쉬만) | Fluent 필드 이름, 반복·쉼표 |
| `--version` | None | Fluent 제품 버전. 기본 = 설치된 최신 |
| `--dimension {2,3}` | 자동 | `infer_case_dimension` 재정의 |
| `--precision` | `double` | |
| `--processors` | 1 (≥1 검사, 690-691) | |
| `--initialization {standard,hybrid}` | `standard` | dat 가 없을 때 초기화 방식 |
| `--node-centered` | off | 절점/면 절점 값. 기본은 셀/면 중심 값 |
| `--ascii` | off | 기본 binary |
| `--overwrite` | off | 없으면 기존 출력이 있을 때 `ConversionError` (234-237, 311-314, 458-461) |
| `--start-timeout` | 120 (≥1) | Fluent 기동 대기 초 |
| `--fluent-transcript` | off | 트랜스크립트 스트리밍 |

종료·출력:

| 상황 | 동작 | 근거 |
|---|---|---|
| 정상 | 0 | 700 |
| `ConversionError` | stderr `ERROR: <메시지>`, **1** | 696-699 |
| Fluent 쪽 예외 | `ConversionError("Fluent conversion failed: …")` 로 감싸 1 | 566-569 |
| argparse / 범위 오류 | 2 | `parser.error` 690-693 |
| 그 밖(예: `KeyboardInterrupt`) | 처리 없음. `finally` 의 세션 종료는 수행 | 570-580 |

stdout 에 `print` 로 단계 메시지: `Case/Data/Output/Format/Dimension`(489-493), `Launching Fluent...`, `Reading case...`, `Reading solution data...` 또는 `Running <init> initialization...`, `Quantities`, `Cell zones`/`Surfaces`, `Exporting VTU...`/`VTP...`, `Done : <경로> (<바이트> bytes)`(582). **`flush=True` 없음**, `[PROGRESS]`/`[SUCCESS]` 없음. 경고는 stderr.

### 3.2 Fluent 실행

`convert_case` (442-583), `launch_options` 498-516:

| kwarg | 값 | 비고 |
|---|---|---|
| `dimension` | `--dimension` 또는 `infer_case_dimension()` | PyFluent `CaseFile.num_dimensions()` (83-115). h5py 필요(`ansys-fluent-core[reader]`). 못 읽으면 `ConversionError` 로 중단 — **cas2vtu 같은 3→2 재시도 없음** |
| `precision` | `--precision` | |
| `processor_count` | `--processors` | |
| `mode` | `"solver"` | |
| `ui_mode` | `"no_gui"` | Fluent 인자 `-gu`. PyFluent 소스 주석(launch_options.py:185-190): Windows 에서 NO_GUI 는 "opens a new cmd or shows Fluent output in the current cmd" 가능성 때문에 PyFluent 기본값이 아님 |
| `start_timeout` | `--start-timeout` (120) | 실행 문자열에 timeout 인자가 붙음 (standalone_launcher.py:281-283) |
| `start_transcript` | `--fluent-transcript` (기본 False) | |
| `cwd` | `tempfile.TemporaryDirectory(prefix="pyfluent-vtu-", ignore_cleanup_errors=True)` | 컨텍스트 매니저로 자동 삭제 (498-500) |
| `product_version` | `--version` 이 있을 때만 | |
| `cleanup_on_exit`, `start_watchdog` | **지정 안 함** → PyFluent 기본: `cleanup_on_exit=True`, `start_watchdog=None` → 로컬이면 **watchdog 자동 기동** (launcher_utils.py:204-214, standalone_launcher.py:377-393) | cas2vtu 와 반대 |

- 버전·경로 탐색: cas2vtu 와 동일하게 PyFluent 에 위임 (`--version` → `product_version`, 없으면 최신 `AWP_ROOTnnn`).
- 세션 종료: `finally` 에서 `solver.exit(wait=30)` (570-580). 주석: Windows 에서 Fluent 가 트랜스크립트를 잡은 채 임시 cwd 가 지워지는 경쟁을 피하려고 대기. `wait=30` 은 종료 요청 후 최대 30초 프로세스 종료를 기다리고 그래도 남으면 강제 종료 (fluent_connection.py:847-947 docstring/코드). 실패는 stderr 경고만.
- 단, `exit()` 의 `timeout` 인자는 안 줬으므로 종료 요청 자체는 무기한 대기할 수 있다 (fluent_connection.py:866-877, 환경변수 `PYFLUENT_TIMEOUT_FORCE_EXIT` 로만 제한 가능).

### 3.3 case/data 읽기

| 항목 | 내용 | 근거 |
|---|---|---|
| API | `solver.settings.file.read_case(file_name=…)` 후 `solver.settings.file.read_data(file_name=…)` 를 따로 호출 | 518-522 |
| data 탐색 | `matching_data_path` (46-49): `<base>.dat.h5` **한 가지**만. `.cas.h5` 접미사만 허용(대소문자 무시, `_has_suffix` 33-34). `--data` 로 명시 가능, `--ignore-data` 로 끔 | 463-471 |
| dat 없음 | 오류가 **아니다**: `Data : (none; initialize in Fluent)` 출력 후 `solution.initialization.standard_initialize()` 또는 `hybrid_initialize()` 실행 (524-529) → **초기화 값이 그대로 내보내져 해석 결과가 아닌 값이 파일에 들어간다** | 520-529 |
| `FFF.3-2-11200.dat.h5` | 이름 해석 **없음**. `FFF.3-2.cas.h5` 와 `FFF.3-2-11200.dat.h5` 가 있어도 `matching_data_path` 는 `FFF.3-2.dat.h5` 를 보므로 없다고 판단 → **초기화 경로로 조용히 진행**. `--data FFF.3-2-11200.dat.h5` 로 직접 주면 그 경로가 `read_data` 로 전달됨(Fluent 수용 여부는 미실행이라 미확인) | 46-49, 463-471 |

### 3.4 메쉬 추출

| 항목 | 내용 | 근거 |
|---|---|---|
| VTU | **파이썬에서 메쉬를 만들지 않는다.** `solver.settings.file.export.vtk(file_name, scope="volume-select", cell_zones=[…], surfaces=[], cell_centered, binary_format, point_cloud=False, quantities=[…])` 호출 → Fluent 가 파일을 씀 | `export_vtu` 223-267 |
| 존 목록 | `settings.setup.cell_zone_conditions.fluid` 와 `.solid` 의 `get_object_names()` 합집합. 둘 다 비면 `ConversionError`. (`field_data.get_zones_info` 미사용) | `get_cell_zone_names` 118-139 |
| 셀 타입·절점 순서·폴리헤드론·2D | 스크립트가 다루지 않음 (Fluent 내보내기에 위임). 부피/중심 검증 **없음** | |
| 출력 파일 이름 | "Fluent appends .vtu even when the supplied file name already has it" (244 주석) → 임시 base 에 `.vtu` 가 붙은 파일을 확인 후 `os.replace` | 240-264 |
| 필요 Fluent 버전 | 설치된 0.42.1 의 생성 설정(`generated/solver/settings_NNN.py`)에서 `class vtk(Command)` 는 **settings_261.py:1414 와 settings_271.py 에만** 있고 242·251·252 에는 없다 (정적 grep). 261 의 인자: `file_name, scope, cell_zones, surfaces, cell_centered, binary_format, point_cloud, quantities`, 설명 "Write a VTK (.vtp/.vtu) file." → 스크립트가 쓰는 인자와 일치 | |
| VTP 메쉬 | `solver.fields.field_data.get_field_data(SurfaceFieldDataRequest(surfaces, data_types=[Vertices, FacesConnectivity], flatten_connectivity=True))` → `geometry[name].vertices/.connectivity` → `pv.PolyData(vertices, connectivity)` | `export_vtp` 336-346, 374 |
| VTP 방향·검증 | 면 법선 재정렬 **없음**, 중심 검증 **없음**, 2D(2점 면) 전용 처리 **없음** (2점 면이 `PolyData` 에서 어떻게 되는지는 미확인) | |

### 3.5 필드 추출

| 항목 | VTU | VTP |
|---|---|---|
| 이름 체계 | Fluent "quantities" (표시명 계열; 예시 목록은 스크립트에 없음). 검증: `vtk_exporter.quantities.allowed_values()` 가 있으면 대조해 없는 이름은 **`ConversionError`**(실패). API 가 없으면 Fluent 에 맡김 | `field_info` 의 스칼라/벡터 필드 이름. 없는 이름은 `ConversionError` (326-334) |
| 위치 | 기본 **cell** (`cell_centered = not --node-centered`), `--node-centered` 면 node. **한 번에 한 위치만** | 〃 : 기본 cell(면 값), `--node-centered` 면 point. 한 위치만 |
| 벡터 | Fluent 내보내기가 결정 (미확인) | 벡터 이름 → `vector_info[q]` 의 `x-component/y-component/z-component` 가 가리키는 **스칼라 성분들을 각각 요청해 `column_stack`**. 2성분이면 z=0 패딩. 그래서 `--node-centered` 에서도 벡터가 나온다 (348-349 주석, 378-394) |
| 요청 | 이름 목록만 전달 | 스칼라마다 `ScalarFieldDataRequest(surfaces, field_name, node_value=not cell_centered, boundary_value=True)` **개별 호출** (배치 아님) (279-296, 356-364) |
| 크기 검증 | 없음 | 값 개수 ≠ 셀/점 수면 `ConversionError` (396-401) |
| 변수 목록 API | 없음 (`--list`/`--list-json` 없음) | 없음 |
| 이름 바꾸기 | **없음** | **없음** |
| 추가 배열 | (Fluent 가 결정 — 미확인) | cell data `Fluent Surface Index`, `Fluent Surface ID`, `Fluent Zone ID` (int32), field data `Fluent Surface Names` (문자열 배열) (407-419) |

`quantities` 가 비면 `(mesh only)` 로 격자·기하만 내보낸다 (531-534).

### 3.6 VTP / 경계 출력

| 항목 | 내용 | 근거 |
|---|---|---|
| 표면 목록 | `get_surface_info` (168-173): field_info 의 `surfaces` 메타를 **필터 없이 전부**. 비면 `ConversionError`. `-s` 로 부분 선택 가능(`select_surfaces`, 190-201, 모르는 이름은 오류) | |
| 기본 대상 | **모든 표면** — 내부 존(interior)도 제외하지 않는다. (참고: `docs/probe/box.md` 의 오프라인 FileSession 실측에서는 box 에 `interior-fluid`(90,625 면)·`inlet`·`outlet`·`wall` 이 보고됨. 라이브 Fluent 에서의 목록은 미확인) | 170-173, 551-553 |
| 파일 단위 | **병합 1개** (`pieces[0].append_polydata(*pieces[1:])`). 표면별 파일·`.vtm` 없음 | 418 |
| 면 폴리곤 | `flatten_connectivity=True` 로 받은 평탄 배열을 그대로 `pv.PolyData(vertices, connectivity)` 에 전달 (374) | |
| 점/셀 | §3.5 표 — 한 번에 한 위치 | |
| 2D | 2D 전용 분기 없음. `FacesNormal` 을 요청하지 않으므로 cas2vtu 가 겪은 2D 크래시 경로는 밟지 않는다 (설계상, 미실행) | |

### 3.7 출력 레이아웃·라이터

| 항목 | 내용 | 근거 |
|---|---|---|
| 파일 | 요청 포맷의 파일 **1개** (`.vtu` 또는 `.vtp`). `.vtm` 없음 | |
| 경로 | `normalize_output_path`: 확장자가 없으면 붙임 (52-57). 출력=입력 경로면 오류(456-457) | |
| VTU 라이터 | **Fluent 내장** (`binary_format=not --ascii`). 압축 옵션 노출 없음 | 249-258 |
| VTP 라이터 | PyVista `PolyData.save(temp, binary=not --ascii, recompute_normals=False)` — 설치 0.49.0 시그니처 `save(filename, binary=True, texture=None, recompute_normals=True, compression='zlib', **writer_kwargs)` (실측) | 427-431 |
| 원자성 | 출력 폴더에 숨김 임시 이름 `.<stem>.<uuid>.pyfluent-export(.vtu|.vtp)` 로 쓰고 **`os.replace`** 로 교체, `finally` 에서 임시 파일 삭제. 크기 0/없음 검사 포함 | 240-267, 422-439 |
| meshio | 미사용 | |

### 3.7b 이름 표

없음. 변수 이름 매핑·표시명 표·`--rename` 에 해당하는 것이 코드에 없다. 사용자가 준 이름이 곧 출력 배열 이름이다 (VTP: `data_attributes[quantity] = values`, 402).

### 3.8 의존성

| 항목 | 내용 |
|---|---|
| 필수 | 표준 라이브러리 + `ansys-fluent-core` (`import ansys.fluent.core as pyfluent`, `from ansys.fluent.core import ScalarFieldDataRequest, SurfaceDataType, SurfaceFieldDataRequest` — 0.42.1 에서 최상위 import 가능, 실측) + 설치된 Fluent |
| 조건부 | `numpy`, `pyvista` (VTP 에서만, 없으면 `ConversionError` "VTP export requires PyVista", 316-323). `h5py` (`CaseFile` 차원 추정, `ansys-fluent-core[reader]`; 없으면 `--dimension` 을 요구하는 오류, 83-104) |
| 버전 방어 | `FieldInfo` 접근을 `fields.field_info` → `solver.field_info` → `fields._field_info` 순으로 시도 (142-154), 메타 getter 도 `get_*_info` → `_get_*_info` (157-165), 파일리더 모듈 경로도 `filereader` → `file_reader` 두 철자 (86-104). 0.42.1 에서는 `Fields._field_info` 와 `_get_surfaces_info` 만 있어 3번째 경로·비공개 getter 로 동작 (session.py:489, live_field_data.py:113) |
| Fluent 버전 | VTU 는 `file.export.vtk` 가 있는 **26R1 이상** 필요 (§3.4). VTP 는 field data API 라 버전 의존이 적음(미실행) |

---

## 4. 설치된 ansys-fluent-core 0.42.1 정적 대조 (Fluent 미실행)

| 스크립트가 쓰는 것 | 0.42.1 에서 확인 | 근거 |
|---|---|---|
| `launch_fluent(product_version, dimension, precision, processor_count, mode, ui_mode, start_timeout, start_transcript, cleanup_on_exit, cwd, start_watchdog)` | 모두 시그니처에 있음 | launcher.py:329-357 |
| `ui_mode` 값 | `no_gui_or_graphics`(-g), `no_graphics`(-gr), `no_gui`(-gu), `hidden_gui`, `gui`. Windows 기본값은 `hidden_gui` | launch_options.py:176-199 |
| `solver.exit(wait=…)` | `Session.exit(**kwargs)` → `FluentConnection.exit(timeout=None, timeout_force=True, wait=False)` | session.py:357-371, fluent_connection.py:847-947 |
| `solver.scheme.eval` / `solver.get_fluent_version()` | 있음 (`scheme_eval` 속성은 deprecated) | session.py:168, 238-241, 325-327 |
| `fields.field_data.get_mesh(zone)` | 있음. docstring: 셀 존만 지원, 면 존은 `NotImplementedError` | live_field_data.py:1061 |
| `fields.field_data.get_zones_info()` | 인스턴스 속성으로 설정됨 | live_field_data.py:877, session_solver.py:188-195 |
| `fields.solution_variable_info/data` | 솔버 세션에서 연결됨 | session_solver.py:148-152 |
| `fields._field_info._get_surfaces_info/_get_scalar_fields_info/_get_vector_fields_info` | 있음 (공개 `field_info` 속성은 없음) | session.py:489, live_field_data.py:107-115 |
| 요청 클래스 (`ScalarFieldDataRequest` 등) | 최상위·`fields.field_data_interfaces` 양쪽 import 가능. `ScalarFieldDataRequest` 필드: `field_name, node_value=True, boundary_value=True` | field_data_interfaces.py:126-146, 실측 import |
| `LiveFieldData` 공개 메서드 | `get_field_data, get_mesh, get_surface_ids, new_batch` (+ `get_zones_info` 인스턴스 속성) | 실측 `dir()` |
| `settings.file.read_case(file_name)`, `read_data`, `solution.initialization.standard_initialize/hybrid_initialize` | 242·251·252·261 모두 `read_case`(인자 `file_name, pdf_file_name`)·초기화 명령 존재 | generated/solver/settings_*.py |
| `settings.file.export.vtk` | **261·271 만** (§3.4) | settings_261.py:1414 |
| `CaseFile.num_dimensions()` | 있음 (`filereader/case_file.py:461`), import 실측 OK (h5py 3.16.0 설치) | |
| watchdog | `cleanup_on_exit=True` 이고 로컬이면 `start_watchdog=None` 이 True 로 간주. `config.start_watchdog is False` 면 끔 | launcher_utils.py:204-214, launcher.py:439-440 |

---

## 5. 최종 비교

### 5.1 종합

| 항목 | cas2vtu.py | fluent_to_vtu.py | 더 나은 쪽 |
|---|---|---|---|
| 볼륨 기하 정확성 | 셀 타입 순열·폴리헤드론 재감김·부피/중심 검증·자동 반전 (self-test 통과) | Fluent 에 위임, 검증 없음 | cas2vtu |
| 필드 범위 | 모든 셀 SVAR(`SV_*`) 가능, 표면은 스칼라(점+셀)+벡터(셀) | 이름 목록만 전달 (VTU 는 Fluent 가 결정) | cas2vtu (SVAR 이름이 `--list-json` 의 `SV_*` 와 같은 체계) |
| 2D 처리 | 고스트 셀 제거, 선분 PolyData, `FacesNormal` 생략, 차원 자동 재시도 | 차원 감지만, 2D 별도 처리 없음 | cas2vtu |
| 경계(VTP) | 경계 존만 기본, 면 방향 보정, 표면별 파일 가능, 점+셀 동시 | 전 표면 병합 1개, 보정 없음, 한 위치만 | cas2vtu (단, 내부면 포함 여부는 목적에 따라) |
| 구현 단순성·유지보수 | 1424행, 비공개 API 다수, 파이썬 루프 | 704행, Fluent 내보내기 위임 | fluent_to_vtu |
| 대형 메쉬 속도·메모리 | 요소마다 파이썬 객체를 받아 루프(343-384) → 느리고 큼 (미측정) | VTU 는 Fluent 가 씀 → 파이썬 부담 없음 | fluent_to_vtu (VTU) |
| 출력 안전성 | 목적 경로에 직접 씀, 덮어쓰기 확인 없음 | 임시 파일 → `os.replace`, `--overwrite` 필요, 0바이트 검사 | fluent_to_vtu |
| 종료 코드·오류 | 0/1/2 혼재, 검증 불일치·빈 출력도 0 | `ConversionError` → 1 일관 | fluent_to_vtu |
| 입력 검증 | 없는 변수는 경고 후 제외 | 없는 변수·존·표면은 오류 | 상황 (GUI 가 이미 목록을 주면 후자가 안전) |
| 세션 종료 | `exit()` 대기 없음 → 직후 임시 폴더 삭제, watchdog 끔 | `exit(wait=30)`, watchdog 기본 켬 | fluent_to_vtu |
| 데이터 없음 처리 | 조용히 메쉬만 | 조용히 **초기화 값** 내보냄 | 둘 다 위험 (§6) |
| `Workbench 이름 FFF.3-2-11200.dat.h5` | 해석 없음 (메쉬만) | 해석 없음 (초기화) | 둘 다 미해결 |
| Fluent 버전 의존 | 2025 R2·2026 R1 검증 주석 | VTU 는 26R1+ (`file.export.vtk`) | cas2vtu |
| 오프라인 시험 | `--self-test` | 없음 | cas2vtu |

### 5.2 목표 워커 요구와의 대응

목표 CLI: `--case <cas.h5> --output <path> --format vtu|vtp --vars a,b,c [--rename] [--list-json]`, `[PROGRESS] n`, `[SUCCESS]`, `[ERROR] …`, 종료 0/1, GUI 에서 kill 가능.

| 요구 | cas2vtu.py | fluent_to_vtu.py | 재사용 후보 |
|---|---|---|---|
| `--case` | 위치 인자 `case` | 위치 인자 `case_file` | 둘 다 이름만 바꾸면 됨 |
| `--output` | `-o` (VTU 경로 기준, VTP 는 파생 이름) | `-o` (확장자로 포맷 추론) | fluent_to_vtu 의 `resolve_output_format`/`normalize_output_path` (52-72) |
| `--format vtu\|vtp` | 없음 (`--vtp/--no-vtu` 조합) | **있음** | fluent_to_vtu |
| `--vars a,b,c` | `-f` 공백 구분 `SV_*` | `-q` 쉼표·반복 | 파싱: `flatten_values` (75-80). 이름 체계: VTU 셀 변수는 cas2vtu(`SV_*`)가 프로젝트와 일치 |
| `--rename` | 없음 (기본 선택일 때만 CamelCase 자동) | 없음 | 프로젝트 `cff_common.display_name`. cas2vtu `DEFAULT_FIELDS` 는 CamelCase 라 프로젝트 표와 다름 |
| `--list-json` | `--list` 텍스트(stdout). 재료: `list_cell_zones`, `available_svars`(302-317), `surfaces_info`, `scalar_fields_info`, `vector_fields_info`, 출력부 1114-1129 | 없음 | cas2vtu 의 조회 함수 → JSON 으로 감싸면 됨 |
| `[PROGRESS] n` | 없음. 자연스러운 지점: 존 루프(1136), 표면 루프(1006), 단계별 `log.info` | 없음. 단계 print 5~6개(515-565) | 존 루프가 있는 cas2vtu 가 세밀한 진행률에 유리, VTU 네이티브는 Fluent 호출 1회라 단계 단위만 가능 |
| `[SUCCESS]`/`[ERROR]` | 없음 (logging→stderr) | `ERROR: …`(stderr) 만 | fluent_to_vtu 의 `ConversionError` + 최상위 `main` 구조 (687-700) |
| 종료 0/1 | 0/1/2 혼재 | 0/1 (+argparse 2) | fluent_to_vtu |
| kill 가능 | §6 R5 | §6 R5 | 어느 쪽도 부족 |
| 원자적 쓰기 | 없음 | 있음 | fluent_to_vtu (240-267, 422-439) |
| 임시 cwd | `mkdtemp` + `rmtree(ignore_errors)` | `TemporaryDirectory(ignore_cleanup_errors=True)` + `exit(wait=30)` | fluent_to_vtu 의 종료 순서 |
| 기하 재구성·검증 | **전부** (`build_zone_mesh`, `orient_*`, `verify_*`, `to_vtk_*`, `_parse_flat_faces`) | — | cas2vtu (VTU 를 파이썬으로 만들 경우) |
| 차원 감지 | h5py 직접 (229-245, PyFluent 불필요) | PyFluent `CaseFile` (83-115) | 둘 다 Fluent 기동 전 가능 |
| 2D 재시도 | `"wrong dimensions"` 재기동 (1089-1102) | 없음 | cas2vtu |

---

## 6. 위험 (코드·설치 소스 근거, 실행 실측 아님)

| # | 위험 | 내용 | 근거 |
|---|---|---|---|
| R1 | Fluent 설치 + 라이선스 필수 | 둘 다 `launch_fluent(mode="solver")` 로 실제 솔버를 띄운다. 라이선스 체크아웃 실패·미설치면 변환 불가. 변환 1건마다 Fluent 1개 기동(세션 재사용 없음). 오프라인 대안으로 PyFluent `FileSession` 이 있으나 표면 데이터만 줌(`docs/probe/box.md`) | cas2vtu.py:1086, fluent_to_vtu.py:516 |
| R2 | 기동 시간 | 케이스당 Fluent 기동 비용이 매번 발생(수치 미측정). 기동 대기: cas2vtu 는 PyFluent 기본 100초(`PYFLUENT_FLUENT_LAUNCH_TIMEOUT`), fluent_to_vtu 는 120초 | module_config.py:270-272 |
| R3 | 메모리·속도 (cas2vtu) | `get_mesh` 가 노드·요소·facet 을 파이썬 객체로 돌려주고, 이를 for 루프로 리스트에 `extend`. 셀 수십만~수백만(프로젝트 샘플 Cyclone 394,817 셀)에서 시간·메모리 부담 가능. 이후 `ZoneMesh` + vtk 격자 + (여러 존이면) 병합 사본이 동시에 존재 | cas2vtu.py:343-384, 609-623 |
| R4 | 데이터 파일 이름 | Workbench 원본 `FFF.3-2.cas.h5` + `FFF.3-2-11200.dat.h5` 를 둘 다 못 찾는다(결정 003 §1 의 원인과 같은 현상). cas2vtu 는 **메쉬만 조용히** 출력, fluent_to_vtu 는 **초기화 값을 조용히** 출력 → 후자는 잘못된 해석값이 정상 결과처럼 보임 | cas2vtu.py:1333-1339, fluent_to_vtu.py:46-49, 520-529 |
| R5 | GUI 중단(kill) | 두 스크립트 모두 시그널/중단 처리·진행 확인점이 없다. 블로킹 구간 = Fluent 기동, `read_case`/`read_data`, `get_mesh`·`get_data` 호출, `export.vtk`, `solver.exit()`. `QProcess.kill()`(= `TerminateProcess`)은 `finally` 를 건너뛰므로 `solver.exit()`·임시 폴더 정리가 실행되지 않는다 | 전체 |
| R6 | 살아남는 Fluent 프로세스 | cas2vtu 는 `start_watchdog=False`(267) → 부모가 `TerminateProcess` 등으로 죽으면 Fluent 고아 프로세스가 남을 수 있다 (`cleanup_on_exit` 는 정상 종료 때만 작동). fluent_to_vtu 는 PyFluent 기본 watchdog 이 켜진다: 별도 프로세스가 부모 PID 를 `IDLE_PERIOD = 2` 초마다 확인하고(watchdog_exec:122, 138), 사라지면 `fluent.exit(timeout=…)` 후 `force_exit()` 로 정리하도록 작성돼 있다(watchdog_exec:142-182, 미실측). watchdog 은 `pythonw.exe` 로 `DETACHED_PROCESS`+`CREATE_BREAKAWAY_FROM_JOB` 로 뜨므로 부모 쪽 Job Object 에 묶이지 않고 독립으로 남는다 | cas2vtu.py:267, watchdog.py:43, 126-130, 165-166 |
| R7 | stdout 파이프 상속 | PyFluent 기본 `launch_fluent_stdout`/`stderr` = None → Fluent 가 부모의 stdout/stderr 핸들을 **상속**한다(Windows 에서 `shell=True`, `CREATE_NO_WINDOW`). GUI 가 워커 stdout 을 파이프로 읽으면 (a) Fluent 콘솔 출력이 `[PROGRESS]` 스트림에 섞일 수 있고 (b) 워커가 죽어도 Fluent 가 살아 있으면 파이프 쓰기 끝이 열려 있어 EOF 가 오지 않을 수 있다. 코드만 본 추론이며 실측 전 | module_config.py:200-210, launcher_utils.py:108-123 |
| R8 | 임시 파일 잔존 | cas2vtu: `%TEMP%\cas2vtu_fluent_*`(kill·`launch_solver` 실패·Windows 에서 Fluent 가 cwd 를 잡고 있을 때 `rmtree(ignore_errors=True)` 실패), 목적 경로의 불완전 VTU. fluent_to_vtu: `%TEMP%\pyfluent-vtu-*`(`ignore_cleanup_errors`), 출력 폴더의 `.<stem>.<uuid>.pyfluent-export.vtu|vtp`. watchdog 관련: watchdog.py 가 파이썬 프로세스 작업 디렉터리의 `watchdog_<id>_init`·`pyfluent_watchdog.err` 를 확인·삭제하고, watchdog_exec 은 오류 시 `pyfluent_watchdog.err` 를 쓴다(watchdog_exec:187) | cas2vtu.py:1084, 1203; fluent_to_vtu.py:240-244, 498-500; watchdog.py, watchdog_exec:187 |
| R9 | 종료 대기 | cas2vtu `exit()` 는 `wait` 없음 → 직후 `rmtree`. 둘 다 `exit(timeout=…)` 를 지정하지 않아 `timeout is None` 경로(종료 요청에서 무기한 대기, docstring: "will lock up the interpreter")를 탄다. `PYFLUENT_TIMEOUT_FORCE_EXIT`(config `force_exit_timeout`)로만 제한 가능. fluent_to_vtu 의 `wait=30` 은 종료 요청 *이후* 프로세스 소멸 대기(0.5초 간격 PID 확인, fluent_connection.py:792-846) | cas2vtu.py:1200, fluent_to_vtu.py:575, fluent_connection.py:847-947 |
| R10 | stdout/stderr 프로토콜 | cas2vtu 로그 전부 stderr, `print` 없음(`--list` 제외); fluent_to_vtu 는 `print` 에 `flush` 가 없어 파이프로 읽으면 블록 버퍼링 가능(`-u`/`PYTHONUNBUFFERED` 필요). 둘 다 `[PROGRESS]` 부재 | |
| R11 | Windows 경로·인코딩 | 프로젝트 경로에는 한글·공백이 있다(CLAUDE.md). 두 스크립트는 `str(path)` 를 Fluent 설정 API 로 넘긴다(gRPC). fluent_to_vtu 의 VTU 는 **Fluent 프로세스가 출력 경로에 쓰므로** 한글 경로 처리가 Fluent 쪽에 달림. 실측 없음 | cas2vtu.py:278, fluent_to_vtu.py:518, 250-251 |
| R12 | `ui_mode` | fluent_to_vtu 의 `no_gui` 는 PyFluent 소스 주석상 Windows 기본값이 아니다(콘솔 창/출력 노출 가능성). cas2vtu 의 `no_gui_or_graphics`(-g)는 그런 주석이 없다. 둘 다 실측 전 | launch_options.py:185-190 |
| R13 | 버전 취약성 | cas2vtu 는 비공개 API(`_field_info`, `_service_factory`, `_id`)에 의존. fluent_to_vtu 는 폴백 다단(§3.8)으로 방어. VTU 네이티브 내보내기는 26R1+ 한정. 2026 R1 에서 2D `FacesNormal` 요청 크래시, 네이티브 표면 내보내기 크래시가 각 스크립트 주석에 기록됨 | cas2vtu.py:779-781, fluent_to_vtu.py:4-6 |
| R14 | 표면 이름 충돌 | cas2vtu 의 표면 스칼라는 point data 와 cell data 에 **같은 이름**(`pressure` 등)으로 들어간다. ParaView/PyVista 에서 같은 이름이 점·셀 양쪽에 나타남 | cas2vtu.py:786-789, 824-827 |
| R15 | 이름 체계 불일치 | 오프라인 `FileSession`(`docs/probe/box.md`)의 표면 필드 이름은 `SV_*`, 라이브 Fluent field_info 는 `pressure`·`wall-shear` 등 표시명(cas2vtu `DEFAULT_SURFACE_FIELDS`). 라이브 쪽 전체 목록·`SV_BF_V` 등 존재 여부는 미확인 | |
| R16 | 병합 절점 | cas2vtu 의 존 병합은 절점을 합치지 않아 존 경계에서 절점이 중복된다 (`MergePointsOff`) | cas2vtu.py:609-623 |

## 7. 이 조사에서 하지 않은 것 (미확인)

- Fluent 기동·`read_data` 임의 이름 수용 여부·기동 시간·메모리·한글 경로·라이브 표면 목록(`zone_type` 값)·`file.export.vtk` 가 만드는 배열 이름/존 분리: 모두 미실행.
- watchdog 의 실제 정리 동작, Fluent 의 stdout 상속 영향: 소스 정독만.
- 실행한 것: `import ansys.fluent.core` 버전 조회(0.42.1), 요청 클래스·`CaseFile`·`FluentVersion.get_latest_installed()` import/호출, `pv.PolyData.save` 시그니처, `vtk.vtkUnstructuredGrid.SetPolyhedralCells` 존재, `cas2vtu.py --self-test`(PASSED).
