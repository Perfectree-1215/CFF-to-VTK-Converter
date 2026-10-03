# 검증 v1.7 — 결정 004 (PyFluent 변환 탭)

- 날짜: 2026-10-03 · 기준: `docs/decisions/004-pyfluent-tab.md` §6 · 환경: venv `CFF2VTK_venv` (pyfluent 0.42.1, pyvista 0.49.0, vtk 9.7.1), Fluent 2026 R1, processor_count=1
- 수행: 메인 세션 CLI 실행(box·Cyclone) + 오프라인 자가시험 + 헤드리스 GUI 시험 + `vtk-verify` 서브에이전트(출력 파일 재대조)
- 상태: 코드 검증 완료 항목은 아래 표. **사용자 ⑦(GUI 직접 조작) 통과** (2026-10-03 저녁, v2.0 화면·JSON 생성기 포함 "테스트 결과 이상 없음") → 결정 004 확정

## 1. 워커 CLI (메인 세션 실측)

| 대상 | 결과 | 판정 |
|---|---|---|
| box `--list-json` | `cell_arrays` 11개(`SV_P,SV_T,SV_U…`, 숨김 `SV_BF_V`·`SV_C_INDEX` 등 20개 별도), `face_arrays` 21개(`SV_WALL_SHEAR` 포함), `boundaries` inlet(5,625)·outlet(6,625)·wall(7,5000), `fluent_version` "Ansys Fluent 2026 R1", `n_cells` 31250. 마커 사이 한 줄 JSON, Fluent 전사 미혼입. 종료코드 0 | 통과 |
| box VTU `SV_P,SV_T,SV_U,SV_V,SV_W --rename` | UnstructuredGrid 31,250 / 34,476, 전부 hex(12), cell_data `{pressure, temperature, x-velocity, y-velocity, z-velocity, velocity(3)}`, point_data 0. `[VERIFY] 부피 5.000000e+00, SV_VOLUME 대비 상대오차 0.0e+00 (셀 최대 8.1e-15), 음수 부피 0, 중심 편차 0.00셀`. 58 s, 피크 267 MB | 통과 |
| 〃 vs PyVista 엔진 `Results.vtu` | cells·points 동일. `pressure`·`temperature` **정렬 후** 최대차 0.0, 같은 순서 비교는 0.054·260 → **셀 순서가 다르다** (§6 비고대로 "순서 다름"). `velocity[:,0] == x-velocity` (차 0) | 통과 (순서 다름 표기) |
| box VTP `SV_P,SV_WALL_SHEAR,SV_U,SV_V,SV_W --rename` | PolyData 6,250 면 / 6,452 점, cell_data `{pressure, x-velocity, y-velocity, z-velocity, wall-shear(3), boundary_id, velocity(3)}`, field data `boundary_names=[inlet, outlet, wall]`, `boundary_id` 5×625·6×625·7×5000, `wall-shear` NaN 1,250면(inlet·outlet)·유한 5,000면, `pressure` NaN 0. `[VERIFY] 면 중심 최대차 2.4e-07 m`. 52 s | 통과 |
| 〃 면 방향 | 반전 전 실측: 3개 경계 모두 바깥 비율 0.00 → `build_surface_mesh` 가 전부 반전 → (vtk-verify 재확인 예정) 1.00 | 통과 예정 |
| Cyclone VTU `SV_P,SV_U,SV_V,SV_W --rename` (`FFF.3-2.cas.h5` + `FFF.3-2-11200.dat.h5`) | 로그 `데이터 파일: FFF.3-2-11200.dat.h5 (이름이 달라 PyFluent 에 직접 지정)`. 394,817 cells / 1,013,398 points, 42×261,079 + 12×133,738. `get_mesh` 12.4 s, 조립 3.0 s, facet 2,606,122개 중 1,268,489개 반전, `SV_VOLUME 대비 상대오차 0.0e+00 (셀 최대 1.8e-04), 음수 0, 중심 편차 0.40셀`. **전체 74.7 s** (기준 ≤ 300 s), 피크 1,440 MB, VTU 73.7 MB. 케이스 폴더에 `.cff_link_*`·`.trn` 없음 | 통과 |
| 〃 vs PyVista 엔진 dp_000 `Results.vtu` | 같은 셀 수·celltypes·총 부피(4.986089e-02, 음수 0 양쪽). `pressure`/`x-velocity`/`z-velocity` 정렬 후 최대차 **0.0**. 점 수는 PyVista 1,015,751 vs PyFluent 1,013,398 (리더 쪽 절점 중복 — §6 비고대로 셀 수·값만 비교) | 통과 |
| Cyclone VTP `SV_P,SV_WALL_SHEAR,SV_U,SV_V,SV_W --rename` | 36,758 면 (= 481+859+13,003+333+22,082) / 69,902 점, `boundary_names=[inlet, outlet, wall_v-finder, outlet_under, wall_cyclone]`, `boundary_id` 30–34, `wall-shear` NaN 1,340면(inlet·outlet), 후처리 표면(`p-01`…) 미포함. `SV_CENTROID 차 ≤ 5.6e-4 m` (기준 < 1e-3). 48.6 s | 통과 |
| dat 없음 (헤드리스 dp_008) | `[ERROR] 데이터 파일(.dat.h5)을 찾지 못했습니다 …` + 1, 출력 없음, Fluent 미기동 | 통과 |
| 상대 경로 입력 (`samples/Box/box.cas.h5`) | 1차 실행에서 Fluent `File not found` → 워커가 `resolve()` 로 절대 경로화 후 통과 | 통과 (수정 후) |
| **한글·공백 경로** (`…\입력 폴더 v17\a\dp_007.cas.h5`) | 1차: Fluent `File "…" not found!` (파일 존재) → `ascii_alias`(%TEMP% 정션) 추가 후 변수 로드 성공 | 통과 (수정 후) |
| `--list-json` 상대/비ASCII 경로·오류 JSON | `{"error": …, "engine": "pyfluent"}` + 종료코드 1 | 통과 |

## 2. 오프라인 자가시험 (`tests/headless/pyfluent_mesh_selftest.py`, Fluent 불필요)

| 항목 | 결과 |
|---|---|
| hex·tet·pyramid·wedge 부호 있는 부피 = VTK `vtkCellSizeFilter` 부호 (정상·거울상 8건), `VTK_FLIP` 이 부호 반전 | 전부 ok |
| Fluent 순서 → `FLUENT_TO_VTK` 순열 뒤 부피 양수 (4 타입) | ok. **참조 cas2vtu 의 wedge 면 정의는 VTK 와 부호가 반대**였음 → 수정 |
| 폴리헤드론 facet 재감김(안쪽 2개 반전)·부피 1.0·`verify_zone` ok·`SetPolyhedralCells` 타입 42·절점 비병합 병합(16점) | ok |
| 평탄 connectivity → PolyData, `boundary_names`, vtp/vtu 쓰기·되읽기, `rename_arrays`, 혼합 면 파싱 | ok |
| 결과 | **0 failure** |

## 3. 중단·프로세스 (실측)

| 시험 | 결과 |
|---|---|
| 워커 `proc.kill()` 만 (설계 전 실측, `docs/probe/pyfluent-live.md` §4) | Fluent 8개 프로세스 + watchdog 2개 생존 43 s+ → 협조적 중단 설계의 근거 |
| 워커 정상 종료·`[ERROR]` 종료 | `solver.exit(timeout=30, wait=20)` 뒤 프로세스 소멸. 임시 cwd 삭제 (한 번 `.trn` 잠금으로 남은 폴더는 다음 실행이 10분 뒤 정리) |
| GUI `CANCEL` → 워커 종료 → pid 재확인 | 헤드리스 v17 §4 참조 |

## 4. 헤드리스 GUI 시험 (`tests/headless/gui_headless_test_v17.py`)

- 1차(18:15): 14/27 — 한글 경로에서 Fluent `File not found` → `ascii_alias` 추가.
- 2차(18:35): 19/27 — 변수 로드·경계·pid·잔존 0 통과, `_update_checkbox_style` staticmethod 차용 버그(TypeError) → 수정.
- 3차(18:50): **27/28**. 유일한 FAIL 은 시험 스크립트 쪽 기준 오류 — 스캔 제외 확인용으로 시험이 직접 심은 `.cff_link_zzzz_tmp` 를 "잔여물"로 셌다 (PyFluent 탭은 링크 폴더를 만들지도 지우지도 않는 게 맞음). 단언을 고쳤고 Fluent 재기동 비용 때문에 재실행은 생략했다 (판정 대상 폴더 목록이 로그에 그대로 있어 수정 후 통과가 자명).

| 항목 | 결과 |
|---|---|
| 탭 4개, 변환기 탭 엔진 라디오 2개 유지, `ENGINE_PYFLUENT` 상수 없음 | 통과 |
| 스캔: `.cff_link_*` 제외, 2개 | 통과 |
| 변수 로드 (한글 경로 `입력 폴더 v17`, Workbench 식 `dp_007-0100.dat.h5`): 44 s, `cell_arrays` 11개(숨김 적용), `face_arrays` 21개, 경계 3개(면 수 포함), 로더가 pid 2개 기억, 로드 뒤 Fluent 잔존 0 | 통과 |
| 포맷 전환: VTP 목록 = `face_arrays`, `SV_P`·`SV_T` 체크 유지, VTU 복귀 시 유지 | 통과 |
| VTU 배치 2건 (43 s): 성공 1(`Design_007/Results.vtu`, 31,250 cells, `{pressure, temperature}`) / 실패 1(dat 없는 dp_008, 출력 없음) | 통과 |
| 배치 뒤 Fluent 잔존 0, `%TEMP%` 임시 폴더 잔존 0 | 통과 |
| 변환 중 `[FLUENT_PID]` 수신 → `CANCEL` 중단 **8 s** 에 완료, "중단됨", Fluent 잔존 0, 버튼 복구 | 통과 |
| 로더 진행 중 `shutdown()` → 12 s 뒤 Fluent 잔존 0 | 통과 |
| 전체 실행 뒤 `%TEMP%` 에 `cff_pyfluent_*` 1개 잔존 (중단·shutdown 으로 워커가 죽은 경우 정리 못 함 → 다음 실행이 10분 뒤 삭제) | 허용 (설계대로) |
| `tests/headless/gui_headless_test_v16.py` 회귀 | **21/21** — 변환기 탭 불변 |

## 5. vtk-verify 서브에이전트 (출력 파일 재대조, Fluent 미실행)

결과: **통과 27 / 실패 0 / 조건 다름 4 / 판정 불가 7**.
- 통과: box VTU 타입·cells·points·celltypes·`velocity[:,0]==x-velocity`·음수 부피 0·총합 5.0; box VTP 6,250 = 625/625/5,000, `boundary_names`, `wall-shear` NaN 1,250(inlet+outlet)·유한 5,000(wall), 금지 배열 없음; Cyclone VTU cells/points/celltypes/배열 이름/값 범위(`pressure` −164.6…538.3, `x-velocity` −14.49…13.80)/음수 0/총합 4.986089e-02; Cyclone VTP 36,758, `boundary_names` 5개, `wall-shear` NaN 1,340·유한 35,418; 파일명 규칙.
- 조건 다름(4): CLI 실행이 §6 의 변수 조합보다 **상위 집합**(`SV_U,SV_V,SV_W` 추가)으로 돌았다. §6 의 정확한 조합(`SV_P,SV_T --rename` → `{pressure, temperature}`)은 헤드리스 §4 가 확인했다.
- 판정 불가(7): 파일 재대조로는 볼 수 없는 항목(dat 없음, 한글 경로, `--list-json`, 중단, 프로토콜, 회귀, `--ascii`) — §1·§4 의 직접 실측으로 대체. `--ascii` 는 미실행(§6).

## 6. 미검증 / 조건 다름
- 2D 케이스, 다중 셀 존, wedge/pyramid/tet 가 든 실제 Fluent 격자: 샘플 없음 (box = hex, Cyclone = hex + 폴리헤드론). wedge 노드 순서는 `orient_linear_cells` 다수결이 VTK 기준으로 보정한다.
- Cyclone VTP 면 방향: 비볼록 형상이라 점 평균 기준 검사 불가 (경계별 0.52–1.00). Fluent 의 경계면 저장 방향(안쪽) 불변식에 따라 전부 반전함 — ParaView 에서 사용자 확인 필요.
- `--ascii`, `--processors > 1`, `--fluent-version` 지정: 미실행.
- 사용자 ⑦: 통과 (2026-10-03 저녁).
