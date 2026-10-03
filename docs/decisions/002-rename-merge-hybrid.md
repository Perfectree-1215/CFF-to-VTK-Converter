# 결정 002 — 변수명 변경, 경계 통합 VTP, PyFluent VTU(하이브리드), VTM 제거

- 날짜: 2026-10-03 · 상태: **R1·R4 확정 (사용자 3차 GUI 시험 통과), 나머지 폐기 (결정 003, v1.6)** — R2(PyFluent VTU 하이브리드)·R3(경계 통합 VTP)·§7 의 PyFluent 행은 PyFluent 엔진 제거로 무효. **R1(표시명 옵션)·R4(VTM 제거)는 유효**. 매핑표 파일은 `cff_var_names.py` → `cff_common.py`
- 개정 대상: 결정 001 의 D3(파일명), D5(VTM·ParaView 워커 무변경), 벡터 축
- 근거: `docs/probe/box.md`(변수 목록·면 수), `docs/verification/dp000-p5.md` §3(존마다 성분 수가 다른 면 변수), 2026-10-03 실측(아래 §2)

## 1. 맥락 (사용자 피드백)
1. 변수명을 `SV_P` 대신 `pressure`, `temperature` 처럼 저장할 수 있는지 — 세 엔진 모두
2. PyFluent 엔진에서도 VTU 가 나와야 한다
3. PyFluent VTP 는 경계별 파일이 아니라 **모든 경계가 든 한 파일**
4. VTM 은 필요 없다

## 2. 추가 실측 (2026-10-03, pyvista 0.49.0)
| 실험 | 결과 | 영향 |
|---|---|---|
| `pv.merge([a,b])` 에서 같은 이름 배열의 성분 수가 다르면 | 그 배열이 **조용히 사라짐** (`SHEAR` 3 vs 1 → 결과에 없음) | 통합 전에 성분 수를 맞춰야 한다 |
| 한쪽에만 있는 배열 | 역시 사라짐 | 통합 전에 없는 배열을 채워야 한다 |
| `zone_id`(int32) 셀 배열 + `zone_name` 문자열 셀 배열 + 문자열 field_data | `.vtp` 저장 → `pv.read` 되읽기 전부 보존 | 존 식별 가능 |
| `merge_points` | False: 절점 수 = 합 (8). True: 공유 절점 병합 (6) | 기본값 결정 필요 |
| PyFluent 셀 데이터 | 공개 API 없음 (`DataFile.get_cell_variables` 는 이름만) — probe | PyFluent 단독 VTU 불가 → 하이브리드 |
| Fluent 면 변수 성분 수 | `SV_WALL_SHEAR`, `SV_WALL_PRORUS_ZONE_FORCE_MEAN` wall 존 3 / inlet·outlet 1, `SV_DENSITY_RG_AUX` 는 반대 — dp_000 | 통합 시 패딩 규칙 필요 |

## 3. 가정
| # | 가정 | 비고 |
|---|---|---|
| A1 | Stochos 는 배열 이름을 설정으로 지정해 읽는다. 이름 변경 시 사용자가 그 설정을 맞춘다 | 결정 001 A1 연장. `bc_json_gen`·`dp_collect_tab` 은 배열 이름을 보지 않는다(impact-scan v1.4) |
| A2 | 이미 변환해 둔 DP 세트(`SV_*` 이름)와 새 세트를 **한 학습에 섞지 않는다**. 섞어야 하면 옵션을 끄고 변환한다 | 섞이면 Stochos 학습 입력 열이 어긋나 늦게 드러난다 |
| A3 | PyFluent 엔진 사용자가 원하는 VTU 는 "체적 셀 데이터"이며 PyVista 엔진 VTU 와 같은 것이어도 된다 | 라이선스 없이 체적을 읽는 방법은 PyVista 리더뿐 |
| A4 | 통합 VTP 의 소비자는 ParaView 시각화·경계별 후처리이며 `zone_id` 로 경계를 골라낸다 (Threshold / Extract Selection) | |

## 4. 후보 비교

### R1 변수명 변경
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. 옵션(기본 ON). 매핑표에 있는 이름만 바꾸고 나머지는 `SV_*` 유지** | 사용자가 원한 이름. 미매핑이 눈에 보임(`SV_RUU`) | 두 이름 체계가 한 파일에 섞일 수 있음 |
| b. 전부 규칙 변환(`SV_` 떼고 소문자·하이픈) | 일관됨 | `ruu`, `density-rg-aux` 처럼 뜻이 안 드러남, Fluent 표시명과 불일치 |
| c. 바꾸지 않음(현행) | 호환 단순 | 사용자 요구 미충족 |

적용 지점: **세 엔진 모두 저장 직전 한 함수**(`apply_display_names(dataset, on)`)에서. ParaView 엔진은 `pv_export_worker.py` 가 VTU 저장 뒤 vtk XML 리더/라이터로 되읽어 이름을 바꾸고 다시 쓴다(`--rename` 가 있을 때만. pvpython 에 vtk 모듈 있음). 결정 001 D5 의 "ParaView 워커 무변경"은 여기서 **개정**한다 — GUI 가 두 번째 프로세스를 띄우는 것보다 단순하고 프로토콜이 같다.

매핑표 (`FLUENT_DISPLAY_NAMES`, 워커 한 곳에 둔다. 사용자가 추가 가능):

| Fluent HDF5 | 표시명 | 성분 | 비고 |
|---|---|---|---|
| SV_P | pressure | 1 | |
| SV_T | temperature | 1 | |
| SV_U / SV_V / SV_W | x-velocity / y-velocity / z-velocity | 1 | |
| SV_BF_V | velocity | 3 | PyVista·ParaView 체적 벡터 |
| velocity (PyFluent) | velocity | 3 | 그대로 |
| SV_DENSITY | density | 1 | |
| SV_K | turb-kinetic-energy | 1 | |
| SV_D | turb-diss-rate | 1 | |
| SV_O | specific-diss-rate | 1 | k-ω 케이스 |
| SV_MU_LAM / SV_MU_T | viscosity-lam / viscosity-turb | 1 | |
| SV_H | enthalpy | 1 | |
| SV_MACH | mach-number | 1 | |
| SV_FLUX | mass-flux | 1 | 면 |
| SV_WALL_SHEAR | wall-shear | 3 또는 1 | 면 |
| SV_HEAT_FLUX / SV_HEAT_FLUX_SENSIBLE | heat-flux / heat-flux-sensible | 1 | 면 |
| SV_RAD_HEAT_FLUX / SV_RAD_HEAT_FLUX_EXTERIOR | rad-heat-flux / rad-heat-flux-exterior | 1 | 면 |
| SV_WALL_YPLUS / SV_WALL_YPLUS_UTAU | y-plus / y-plus-utau | 1 | 면 |
| SV_WALL_T_INNER | wall-temp-inner | 1 | 면 |
| SV_WALL_V | wall-velocity | 3 또는 1 | 면 |
| `<base>_MEAN` / `<base>_RMS` | `<표시명>-mean` / `<표시명>-rms` | | base 가 표에 있을 때만 (예: SV_P_MEAN → pressure-mean) |
| 그 외 (`SV_RUU`, `*_RG_AUX`, `SV_ARTIFICIAL_WALL_FLAG` …) | **원래 이름 유지** | | `[WARN] 표시명 없음(원본 유지): [...]` 1줄 |

충돌 규칙: 변환 결과 이름이 이미 존재하면 뒤의 것은 원본 이름을 유지하고 `[WARN]`.

### R2 PyFluent 엔진 VTU
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. 하이브리드 — `--engine pyfluent --format vtu` 는 워커 안에서 PyVista 리더로 체적 VTU 를 만든다** | 사용자 요구 충족, 결과는 PyVista 엔진과 동일(값 검증됨) | "PyFluent 엔진"이란 이름과 실제 리더가 다름 → 로그·가이드에 명시 |
| b. h5py 로 셀 데이터 직접 파싱 | PyFluent 만으로 가능 | 결정 001 §8 범위 밖(자체 리더 개발). 셀 연결성 재구성 필요 |
| c. 불가로 유지 | 변경 없음 | 사용자 요구 미충족 |

GUI 영향: PyFluent 엔진의 `--list-json` 은 체적 셀 배열(`cell_arrays`, PyVista 리더)과 면 변수(`face_arrays`, PyFluent)를 **둘 다** 돌려주고, GUI 는 포맷(VTU→cell, VTP→face)에 따라 체크박스를 바꾼다. 변수를 다시 불러올 필요는 없다.

### R3 경계 통합 VTP
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. 선택 경계 전부를 `Results.vtp` 한 파일로. `zone_id`(int32) 셀 배열 + field_data `zone_names`(`"id:name"` 목록). 성분 수가 다르면 최대 성분으로 0 패딩, 한 존에서 못 읽은 배열은 NaN 채움, 둘 다 `[WARN]`** | 파일 1개, ParaView Threshold 로 경계 선택, 값 보존 | 패딩된 0 은 "값 없음"과 구분이 안 됨 → WARN 과 가이드로 알림 |
| b. 통합하되 성분 수 다른 변수는 제외 | 조작 없음 | wall-shear 가 사라짐(주 사용 변수) |
| c. 경계별 파일 유지(현행) | 단순 | 사용자 요구 미충족 |

- `merge_points=False` (절점 수 = 경계 절점 합). Fluent 면 존을 그대로 보존하고 판정이 결정적. 공유 절점 병합은 Point Data 가 없는 지금은 이점이 없다.
- 문자열 `zone_name` 셀 배열은 넣지 않는다 (90k 면에 문자열 반복은 크기만 늘림). field_data 로 충분.
- 경계별 파일은 CLI `--split-boundaries` 로만 남긴다 (`Results_<boundary>.vtp`, 결정 001 규칙).
- PyVista 엔진 VTP(외곽 skin)도 파일명을 `Results.vtp` 로 통일한다 (`Results_surface.vtp` 폐기). `zone_id` 는 없다.

### R4 VTM 제거 (D5 개정)
| 후보 | 장점 | 단점 |
|---|---|---|
| **a. GUI 에서 VTM 라디오 제거. 포맷 = VTU / VTP. ParaView 엔진은 VTU 전용. `pv_export_worker.py` 의 vtm 코드는 CLI 용으로 남김** | 사용자 요구. GUI 분기 단순 | 기존 `.vtm` 사용자는 CLI 로만 |
| b. 숨김 옵션으로 유지 | 회귀 안전망 | UI 복잡 |

## 5. 결정 (추천안)
| # | 결정 | 틀렸을 때 드러나는 곳 |
|---|---|---|
| R1 | **a** — GUI 체크박스 "Fluent 표시명으로 저장" 기본 ON → 워커 `--rename`. 세 엔진 공통 매핑표. 미매핑은 원본 유지 + WARN | Stochos 설정이 `SV_P` 를 찾을 때(A1·A2). 가이드에 "기존 세트와 섞지 말 것" 명시 |
| R2 | **a** — 하이브리드. 로그 첫 줄에 `체적은 PyVista 리더로 읽습니다` 표기. `--list-json` 에 `cell_arrays`+`face_arrays` | PyFluent 엔진 VTU 가 PyVista 엔진 VTU 와 다르면 틀린 것 (판정: 동일) |
| R3 | **a** — `Design_NNN/Results.vtp` 통합, `zone_id` + `zone_names`, 0 패딩/NaN 채움 + WARN, `merge_points=False`. `--split-boundaries` 는 CLI 전용 | ParaView 에서 Threshold(zone_id) 로 경계가 안 나뉘면 틀린 것 |
| R4 | **a** — VTM 라디오 제거, 포맷 라디오 2개 | GUI 가 `--format vtm` 또는 `--inner-name` 을 보내면 틀린 것 |
| 파일명 | VTU → `Results.vtu`, VTP → `Results.vtp` (두 엔진 공통). 덮어쓰기 검사는 두 포맷 모두 단일 `exists` | `Results_surface.vtp` 가 생기면 틀린 것 |

## 6. 영향받는 코드 (③ impact-scan 입력)
| 파일 | 변경 |
|---|---|
| `cff_export_worker.py` | `FLUENT_DISPLAY_NAMES`·`apply_display_names`, `--rename`, `--split-boundaries`, pyfluent+vtu → `pv_convert`, 통합 VTP 조립(패딩·NaN·zone_id·field_data), `pf_list_json` 에 `cell_arrays`(pyvista)+`face_arrays`, VTP 파일명 `Results.vtp` |
| `pv_export_worker.py` | `--rename` 추가: VTU 저장 뒤 vtk XML 로 되읽어 이름 변경 후 재저장 (vtm 경로엔 적용 안 함, WARN). 그 외 무변경 |
| `pv_export_gui.py` | VTM 제거, `ENGINE_FORMATS`, 포맷별 변수 목록(cell/face), rename 체크박스, `_compute_output_path`/`_output_exists`/`_inner_file_desc`/`_target_display` 단순화, `_process_next` 인자, bc_json 탭 분리(별도 ⑤ 작업) |
| `docs/worker-protocol.md` | §1 표, §2 키(`face_arrays`), §3 인자·파일명, §4 WARN 종류 |

## 7. 판정 기준 (box 기준, `vtk-verify` 가 그대로 대조)
변환 조건: 접두사 `Design`, `samples/box` → `Design_001` (DP 번호 없음, 순번 1).

| 대상 파일 | 항목 | 기대값 | 비고 |
|---|---|---|---|
| **PyVista VTU, `--vars SV_P,SV_T,SV_BF_V --rename`** `Design_001/Results.vtu` | cell_data 이름 집합 | 정확히 `{pressure, temperature, velocity}` | `velocity` 성분 3 |
| 〃 | cells / points / point_data | 31,250 / 34,476 / 0 | |
| 〃 `--rename` 없이 | cell_data 이름 집합 | 정확히 `{SV_P, SV_T, SV_BF_V}` | 현행 유지 |
| 〃 `--all --rename` | 이름 집합 | `{velocity, turb-diss-rate, density, enthalpy, turb-kinetic-energy, viscosity-lam, viscosity-turb, pressure, temperature, x-velocity, y-velocity, z-velocity}` (12개) | box 는 전부 매핑됨 |
| 〃 값 | `pressure` 의 min/max/mean = ParaView 엔진 `SV_P` 의 min/max/mean | 상대 오차 < 1e-6 | 이름만 바뀜 |
| **PyFluent VTU(하이브리드), `--vars SV_P,SV_T,SV_BF_V --rename`** `Results.vtu` | 위 PyVista VTU 와 | 타입·cells·points·이름 집합·각 배열 min/max/mean 동일 | R2 |
| 〃 로그 | 포함 줄 | `체적은 PyVista 리더` 문구 1줄 | |
| **PyFluent VTP, `--vars SV_P,SV_T,velocity --rename`** `Design_001/Results.vtp` | 타입 / cells / points | PolyData / 6,250 / 6,452 | 625+625+5,000 / 676+676+5,100 |
| 〃 | cell_data 이름 집합 | 정확히 `{pressure, temperature, velocity, zone_id}` | `velocity` 성분 3, `zone_id` 성분 1 정수형 |
| 〃 | `zone_id` 값과 개수 | 5: 625, 6: 625, 7: 5,000 | 그 외 값 없음 |
| 〃 | field_data `zone_names` | `["5:inlet", "6:outlet", "7:wall"]` | 순서 = 경계 id 오름차순 |
| 〃 | point_data | 0 | |
| 〃 | 생성되지 않아야 하는 파일 | `Results_inlet.vtp`, `Results_outlet.vtp`, `Results_wall.vtp`, `Results_surface.vtp`, `Results_interior-fluid.vtp` | 통합 기본 |
| 〃 `--include-interior` | cells | 96,875 (90,625+6,250), `zone_id` 에 1 포함 | |
| 〃 `--split-boundaries` | 파일 | `Results_inlet.vtp`(625) / `Results_outlet.vtp`(625) / `Results_wall.vtp`(5,000), `Results.vtp` 없음 | CLI 전용 |
| **PyVista VTP** `Design_001/Results.vtp` | 타입 / cells / cell_data | PolyData / 6,250 / 선택 변수(표시명)만, `zone_id` 없음 | `Results_surface.vtp` 없음 |
| **ParaView VTU, `--vars SV_P,SV_T --rename`** `Results.vtu` | cell_data 이름 집합 | 정확히 `{pressure, temperature}`, cells 31,250 | pvpython 후처리 |
| 〃 `--rename` 없이 | 이름 집합 | `{SV_P, SV_T}` | 회귀 |
| **PyFluent `--list-json`** | 키 | 기존 키 + `cell_arrays`(12개, PyVista 리더) + `face_arrays`(24개) + `vector_fields=["velocity"]` + `surfaces` 4개 | |
| **dp_000 PyFluent VTP `--all --rename`** | `wall-shear` | 성분 3, 통합 파일에 존재, outlet·inlet 행은 0 | 패딩 규칙 |
| 〃 로그 | `[WARN]` | 성분 패딩 변수 목록 1줄 + 표시명 없음(원본 유지) 목록 1줄 | |
| 〃 | `SV_RUU` | 통합 파일에 `SV_RUU` 이름 그대로 | 미매핑 유지 |
| **GUI** | ParaView 엔진 인자 | `--format vtm`, `--inner-name` 을 보내지 않음 | 로그로 확인 |
| 〃 | 포맷 라디오 | VTU, VTP 두 개. PyFluent 엔진에서 둘 다 활성 | |
| 〃 | 변수 체크박스 | PyFluent + VTU → cell 목록 12개, PyFluent + VTP → face 목록 24개 + velocity | 다시 불러오지 않고 전환 |
| 〃 | 덮어쓰기 드라이런 | `Results.vtu` / `Results.vtp` 존재 여부 | glob 폐기 |
| 폴더·프로토콜 | 결정 001 §6 과 동일 | `dp_016→Design_016`, 마커, 종료코드, kill | 회귀 |
