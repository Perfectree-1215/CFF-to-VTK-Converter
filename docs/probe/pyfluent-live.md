# probe: PyFluent 라이브 솔버 세션 실측 (pyfluent 0.42.1 + Fluent 2026 R1)

- 날짜: 2026-10-03 · 방법: 메인 세션이 스크래치 스크립트로 Fluent 를 실제로 띄워 측정 (box 4회, Cyclone 1회, kill 시험 1회). 참조 스크립트 정독 결과는 `pyfluent-examples.md`.
- 환경: venv `D:/Venvs_collec/CFF2VTK_venv/venv` (ansys-fluent-core 0.42.1), Fluent 설치 v242·v252·v261, `launch_fluent()` 기본 선택 = **2026 R1** (`AWP_ROOT261`). 라이선스 체크아웃 정상.
- 목적: 결정 004(PyFluent 탭) 의 근거. "실측" 은 이 PC 에서 1회 이상 재현된 값.

## 1. 기동·읽기 시간 (processor_count=1, double, ui_mode no_gui / no_gui_or_graphics 동일)

| 케이스 | import pyfluent | launch_fluent | read_case | read_data | get_mesh(fluid) | solver.exit |
|---|---|---|---|---|---|---|
| box (31,250 hex, 34,476 nodes) | 3.1 s | 32–44 s | 12.8–14.9 s | 0.3–0.5 s | 0.5 s | 0.0–0.1 s (프로세스는 수 초 뒤 소멸) |
| Cyclone `FFF.3-2.cas.h5` + `FFF.3-2-11200.dat.h5` (394,817 cells = 261,079 poly + 133,738 hex, **1,013,398 nodes**) | — | 32.6 s | 36.4 s | 3.3 s | **22.0 s** | — |

- 케이스 1건당 고정 비용 ≈ 50–80 s (기동 + 읽기). PyVista 엔진의 dp_000 14 s 와 비교해 느리다.
- `read_data(file_name="…/FFF.3-2-11200.dat.h5")` 는 **임의 이름 그대로 받는다** → 하드링크 폴더(`PreparedCase`) 불필요. `cff_common.resolve_data_file` 로 경로만 고르면 된다.

## 2. API 모양 (0.42.1)

| 항목 | 실측 |
|---|---|
| `solver.fields` | `field_data`, `field_data_streaming`, `reduction`, `solution_variable_data`, `solution_variable_info` (`field_info` 없음) |
| `fd.get_zones_info()` | `list[ZoneInfo(_id, name, zone_type∈{CELL, FACE})]`. box: fluid(CELL) + interior-fluid/inlet/outlet/wall(FACE) |
| `fd.surfaces.allowed_values()` | 경계 면 존 + 케이스에 저장된 후처리 표면. box `['inlet','outlet','wall']`(내부면 제외). Cyclone 은 `p-01…p-39`, `plane-44`, `z=…` 같은 후처리 표면 42개 + 경계 5개 |
| `fd.scalar_fields.allowed_values()` | Fluent **표시명** 100여 개 (`pressure`, `x-velocity`, `velocity-magnitude`, `wall-shear`, …). `fd.vector_fields.allowed_values()` = `['velocity','relative-velocity']` |
| `fd.get_mesh(zone: str\|int) -> Mesh` | **셀 존만** (면 존은 `NotImplementedError: Face zone mesh is not supported`). `Mesh.nodes` = ndarray[Node(x,y,z)], `Mesh.elements` = ndarray[Element(element_type, node_indices, facets)]. node_indices 는 0-based 존 로컬. 폴리헤드론은 `node_indices=[]`, `facets=[[i…],…]` |
| `CellElementType` | TRIANGLE 1, TETRAHEDRON 2, QUADRILATERAL 3, HEXAHEDRON 4, PYRAMID 5, WEDGE 6, POLYHEDRON 7, GHOST 8, QUADRATIC_* 9–12 (`ansys.fluent.core.fields.live_field_data`) |
| `svi.get_zones_info()` | `.domains=['mixture']`, `.zone_names=[…]` |
| `svi.get_variables_info(zone_names=[z], domain_name="mixture").solution_variables` | `list[str]` **SV_\* 이름** — CFF 리더(PyVista 엔진)와 같은 체계. 여러 존을 주면 교집합 |
| `svd.get_data(variable_name, zone_names, domain_name).data` | `{zone: ndarray(float64)}`. 벡터는 평탄 `(3n,)` (SV_BF_V 93,750 = 3×31,250). 면 존에도 SV_P 등 면 중심값 존재 |
| `fd.get_field_data(SurfaceFieldDataRequest(surfaces, data_types, flatten_connectivity))` | `{surface: SurfaceData(vertices (n,3) f32, connectivity (m,k) int32 또는 flat, face_centroids, face_normals)}`. 구조형 connectivity 는 deprecated 경고 → `flatten_connectivity=True` 권장. **`FacesNormal` 을 넣어도 `face_normals=None`** (3D box) |
| `ScalarFieldDataRequest(surfaces, field_name, node_value, boundary_value)` | `{surface: ndarray}`; `node_value=False` → 면 수, `True` → 꼭짓점 수 |
| `VectorFieldDataRequest(surfaces, field_name)` | box 'inlet' → (625,3) 성공. **Cyclone 의 후처리 선(line) 표면에 요청하면 서버 오류** (`RuntimeError: … error in server`). 벡터는 `x/y/z-velocity` 스칼라 3개로 조립하는 편이 안전 |
| `start_transcript=False` | Fluent 전사가 파이썬 stdout 에 **안 찍힌다** (실측). 기본값 True 면 `Reading … Done.` 수십 줄이 섞인다 |
| `.trn` 전사 파일 | `cwd` 로 준 폴더에 `fluent-YYYYMMDD-HHMMSS-<pid>.trn` 생성 (Cyclone 은 `cortexerror.log` 도). 케이스 폴더에 안 남기려면 `cwd=임시 폴더` 필수 |

## 3. SVAR 목록 (셀 존 `fluid`)

- box 31개: `SV_P SV_T SV_U SV_V SV_W SV_BF_V SV_DENSITY SV_K SV_D SV_H SV_MU_LAM SV_MU_T SV_VOLUME SV_CENTROID …` + 보조(`SV_ADS_*`, `SV_C_INDEX`, `SV_PARTITION`, `SV_*_G`, `SV_*_RG`, `SV_MOM_AP_*`, `SV_PRODUCTION`, `SV_MASS_IMBALANCE`, `SV_BFP_V`, `SV_BF_MARANGONI`).
- Cyclone 66개: 위 + `SV_P_MEAN/RMS`, `SV_U/V/W_MEAN/RMS`, `SV_RUU…SV_RWW`, `SV_*_RG_AUX` 다수.
- PyVista 엔진(CFF 리더)의 dp_000 39개와 집합이 다르다: 리더는 `SV_*_G`·`SV_*_RG_AUX`·`SV_MOM_AP_*` 같은 솔버 내부 배열을 안 준다. 보조 배열은 기본 숨김 대상.
- 면 존(wall)에는 `SV_WALL_SHEAR`, `SV_WALL_YPLUS`, `SV_HEAT_FLUX`(inlet/outlet) 등 벽 전용 SVAR 가 있다.

## 4. 종료·중단 실측

| 시험 | 결과 |
|---|---|
| 정상 `solver.exit()` | 호출 0.1 s 반환, Fluent 프로세스(cx2610, fl2610, fluent.exe×2, mpiexec, hydra_pmi_proxy, watchdog pythonw×2) 전부 수 초 안에 소멸. 재확인 시 잔존 0 |
| 워커 `proc.kill()` (= QProcess.kill, venv 런처에 TerminateProcess) | 런처와 자식 python 은 죽음. **Fluent 8개 프로세스(cx2610 882 MB, fl2610 673 MB 포함)와 watchdog pythonw 2개는 43 s 뒤에도 전부 생존**. 수동 `taskkill /T /F` 로만 정리됨 |
| pyfluent watchdog | 부모 소멸을 감지해 `fluent.exit()`→`force_exit()` 까지 갔으나 Fluent 자체 정리 스크립트 `cleanup-fluent-<host>-<pid>.bat` 가 rc=1 로 실패 → `pyfluent_watchdog.err` 남기고 종료. **믿을 수 없다** |
| 프로세스 트리 | `fluent.exe(런처)` → `cx2610.exe` → `fluent.exe` → `fl2610.exe`. `mpiexec`·`hydra_pmi_proxy` 는 부모가 이미 사라져 트리로 못 잡는다. `connection_properties.fluent_host_pid`(= fl2610), `cortex_pid`(= cx2610) 를 pyfluent 가 알려준다 |

→ 중단 설계 요구: 워커 kill 만으로는 안 된다. 워커가 `solver.exit()` 를 스스로 부르게 하거나(협조적 중단), GUI 가 pid 를 받아 트리를 죽여야 한다. §5 에 cleanup bat 내용·동작 추가 예정.

## 5. 네이티브 `settings.file.export.vtk` (26R1) 와 cleanup bat

| 항목 | 실측 |
|---|---|
| `export.vtk(file_name, scope="volume-select", cell_zones=[…], surfaces=[], cell_centered=True, binary_format=True, point_cloud=False, quantities=[…])` | box **0.8 s**, `native_box.vtu` 5.7 MB, UnstructuredGrid 31,250 hex / 34,476 points (PyVista 엔진과 동일 수) |
| 배열 이름 | Fluent **라벨**: `Static Pressure`, `Static Temperature`, `X Velocity`, `Y Velocity`, `Z Velocity` (float64, cell data). 우리 표시명(`pressure`)도 `SV_*` 도 아니다 → 저장 뒤 이름 변경 필요 |
| `quantities` 허용값 | `fd.scalar_fields.allowed_values()` 와 같은 표시명 목록. **`velocity`(벡터) 는 거부** (`Values contain disallowed entries`) → 성분 3개를 받아 뒤에서 합쳐야 함 |
| `scope="surface-select"` (표면 네이티브 내보내기) | **Fluent 크래시** (gRPC disconnected, 10054). 참조 스크립트 fluent_to_vtu 주석과 일치. VTP 는 field data API 로만 |
| 파일 쓰기 주체 | Fluent 프로세스가 직접 쓴다 → 한글·공백 경로는 미검증 |
| `cleanup-fluent-<host>-<pid>.bat` 내용 | `tell.exe <host> <port> CLEANUP_EXITING` → `timeout /t 1` → `winkill.exe <pid>` ×3 (런처·fl·cx) → 자기 삭제. **PATH 에 Git `usr/bin` 이 앞서면 GNU `timeout` 이 잡혀 rc=1** (이번 세션·watchdog 실패 원인으로 추정). 정상 cmd 환경에서는 동작할 가능성이 있으나 믿고 설계하지 않는다 |
| Fluent 가 crash 한 뒤 `solver.exit()` | 예외 없이 반환, 프로세스 잔존 0 |
| cwd 잔여물 | `fluent-*.trn`, `fluent-0-error.log`(크래시 시), `cortexerror.log`, `pyfluent_watchdog.err` |

## 5b. 한글 경로 (헤드리스 v17 에서 발견)

| 실험 | 결과 |
|---|---|
| `read_case(file_name="…\\입력 폴더 v17\\a\\dp_007.cas.h5")` (Fluent 2026 R1, pyfluent 0.42.1) | `RuntimeError: File "…" not found!` — 파일은 존재. **비ASCII 경로 거부** (gRPC 는 UTF-8 로 넘기지만 Fluent 쪽 파일 열기가 실패) |
| 같은 폴더를 `%TEMP%\cff_pyfluent_*\case_dir` 로 **정션**(`_winapi.CreateJunction`) 걸고 그 경로로 열기 | 성공 (워커 `ascii_alias`). 정션은 권한 없이 만들 수 있고 다른 볼륨도 가리킨다. `shutil.rmtree` 는 정션을 따라가지 않는다 (Python 3.12 실측) |
| 파일명 자체가 비ASCII | 정션으로 해결 안 됨 → work_dir 로 복사 (`case.cas.h5`/`case.dat.h5`) |
| 파이썬이 쓰는 출력 VTU/VTP 의 한글 경로 | 문제 없음 (vtk XML writer) |

## 6. 면 존 SVAR 순서 = 표면 요청 면 순서 (VTP 값 출처 결정 근거)

경계 면 존 = `zone_type==FACE` ∧ 이름이 `interior` 로 시작하지 않음 ∧ `fd.surfaces.allowed_values()` 포함. `SurfaceFieldDataRequest(flatten_connectivity=True)` 의 면 순서와 `svd.get_data(zone_names=[존])` 의 면 순서를 `SV_CENTROID` vs `FacesCentroid`, `SV_P` vs `pressure(node_value=False)` 로 비교.

| 케이스 | 존 | 면 수 (요청 = 평탄 파싱) | 면 꼭짓점 수 분포 | 중심 최대차 [m] | SV_P vs pressure 최대차 (정렬 전 = 정렬 후) |
|---|---|---|---|---|---|
| box | inlet / outlet / wall | 625 / 625 / 5,000 | 전부 4 | 3e-8 / 3e-8 / 2.4e-7 | 0 / 0 / 0 |
| Cyclone | inlet / outlet / wall_v-finder / outlet_under / wall_cyclone | 481 / 859 / 13,003 / 333 / 22,082 | 3–8각형 혼합 | 3.2e-4 / 3.8e-4 / 5.6e-4 / 1.6e-4 / 4.5e-4 | 3.0e-5 / 3.3e-6 / 1.5e-5 / 7.6e-6 / 3.1e-5 (값 크기 71–681 → 상대 ~5e-8) |

- 결론: **순서가 같다**. 차이는 field data API 가 float32 를 돌려주는 데서 온다(다각형 중심은 float32 + 계산식 차이로 1e-4 m 수준). 따라서 VTP 값은 면 존 SVAR(float64, `SV_*` 이름) 을 쓴다.
- 표면 요청 시간: box 0.1 s, Cyclone 1.0 s (경계 5개 36,758 면). SVAR 면 데이터 0.4–0.6 s.
- 면 존 SVAR 가용성: `SV_P/U/V/W/K/D` 는 모든 경계에, `SV_DENSITY` 는 inlet/outlet, `SV_WALL_SHEAR/SV_WALL_YPLUS` 는 벽에만, `SV_T/SV_HEAT_FLUX` 는 에너지 방정식이 있는 box 에만 → 존마다 없는 배열은 NaN 으로 채운다.

## 7. 세션 재사용 실측 — Fluent 1회 기동으로 여러 케이스 변환 (2026-10-03 저녁, 사용자 요청)

스크립트: 스크래치 `pf_multi/multi_session_test.py` — 워커의 `launch/zone_lists/build_volume/build_boundaries/apply_display_names` 를 그대로 import 해 **세션 1개**에서 `read_case → read_data → 조립 → 저장` 을 6번 반복. 비교군은 워커 CLI 를 케이스마다 띄운 것(`pf_multi/cold/`, 같은 시각대·같은 변수 `SV_P,SV_U,SV_V,SV_W --rename`).

### 7a. 한 세션에서 6건 연속 (processor_count=1, 3D)

| 순서 | 케이스 | read_case | read_data | 조립(get_mesh 포함) | 저장 | 케이스 합계 | 셀 수 | Fluent 메모리(fl+cx) |
|---|---|---|---|---|---|---|---|---|
| 1 | Cyclone dp0 VTU | 20.0 s | 2.5 s | 31.0 s | 4.7 s | **59.1 s** | 394,817 | 1,523 MB |
| 2 | Cyclone dp2 VTU (다른 격자) | 28.1 | 2.9 | 28.1 | 5.7 | **65.1** | 367,041 | 1,524 |
| 3 | Cyclone dp4 VTU (다른 격자) | 30.3 | 3.9 | 29.5 | 4.6 | **68.8** | 375,736 | 1,523 |
| 4 | box VTU | 17.0 | 0.3 | 1.3 | 0.2 | **19.0** | 31,250 | 1,524 |
| 5 | Cyclone dp0 VTU (재) | 21.1 | 4.4 | 35.7 | 6.1 | **67.8** | 394,817 | 1,526 |
| 6 | Cyclone dp0 VTP | 31.9 | 6.4 | 7.8 | 0.2 | **46.9** | (면 36,758) | 1,530 |

기동 33.2 s (1회, 기동 직후 1,486 MB), 종료 5.5 s, 전체 377 s. 파이썬 피크 1.4–1.5 GB.

### 7b. 비교군: 케이스별 기동 (워커 CLI 그대로)

| 케이스 | 기동 | read_case | read_data | get_mesh | 저장 | 워커 내부 전체 | 벽시계(프로세스 시작→종료) |
|---|---|---|---|---|---|---|---|
| dp0, 1 proc | 30.3 s | 23.8 s | 2.5 s | 18.8 s | 7.5 s | 101.7 s | **107 s** |
| dp2, 1 proc | 28.3 | 22.0 | 2.3 | 15.1 | 5.5 | 90.0 | **96 s** |
| dp0, **4 proc** | 29.6 | 23.1 | 3.5 | 18.2 | 6.8 | 99.9 | 106 s |

### 7c. 결론

| 항목 | 실측 |
|---|---|
| 같은 세션에서 다른 격자의 케이스를 `read_case` | **된다**. 확인 질문·예외 없음. `get_zones_info`·`surfaces.allowed_values`·셀 수·SVAR 전부 새 케이스로 갱신 (dp0 394,817 → dp2 367,041 → dp4 375,736 → box 31,250 → dp0) |
| 출력 동일성 | 세션 5번째 dp0 = 세션 1번째 dp0 = 케이스별 기동 dp0: 셀·점·좌표·전 배열 최대차 **0**. dp2 도 0. VTP(6번째)도 정상 (36,758 면, 중심차 5.6e-4 m) |
| 메모리 누적 | 없음 (6건 동안 Fluent 1,486 → 1,530 MB) |
| 케이스당 절감 | 기동 ~30 s + 종료 ~5 s + 인터프리터·pyfluent import ~5 s ≈ **35–40 s**. Cyclone 급 96–107 s → 59–69 s (−35 %), box 급 58 s → 19 s (−67 %). 2건 실측: 203 s → 163 s. 13 DP 추정: 21–23분 → 14–15분 |
| 남는 시간(Cyclone, 세션 재사용 후) | read_case 20–32 s(Fluent 내부) > get_mesh 15–21 s(gRPC, 1M 절점+2.6M facet) > 방향 보정·검증 ~8 s > 저장 5–6 s |
| `processor_count=4` | read_case·get_mesh **안 빨라짐**(23.1/18.2 s). 값 집합은 같으나 **셀 순서가 1 proc 과 다르다**(파티션 순서; 정렬 후 차 0, 정렬 전 pressure 차 694) → 기본 1 유지, 셀 순서 일관성이 필요한 용도에는 1 고정 |
| read_case 가 세션 안에서 20 → 28 → 30 s 로 느려지는 경향 | 원인 미확인(메모리는 평탄). 수십 건 배치에서 재확인 필요 |
| 파이썬이 예외로 **정상 종료**하면 | `cleanup_on_exit` 가 Fluent 를 내린다(잔존 0). kill 과 다름(§4) |
