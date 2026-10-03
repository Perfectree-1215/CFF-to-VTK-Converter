# 검증: box 샘플 변환 결과 (결정 001-engine-format-matrix 기준)

**기준:** `docs/decisions/001-engine-format-matrix.md` §6

**검증 일시:** 2026-10-03  
**검증 환경:** PyVista 0.49.0 (`D:/Venvs_collec/CFF2VTK_venv/venv`)  
**PyFluent 환경:** 미설치 (일부 프로토콜 항목 NOT TESTABLE)

---

## 1. 파일 존재 및 기본 속성

| 파일 | 타입 | Cells | Points | 상태 |
|---|---|---|---|---|
| `out_pv/Design_001/Results.vtu` | UnstructuredGrid | 31,250 | 34,476 | ✓ PASS |
| `out_pv/Design_001/Results_surface.vtp` | PolyData | 6,250 | 6,252 | ✓ PASS |
| `out_pf/Design_001/Results_inlet.vtp` | PolyData | 625 | 676 | ✓ PASS |
| `out_pf/Design_001/Results_outlet.vtp` | PolyData | 625 | 676 | ✓ PASS |
| `out_pf/Design_001/Results_wall.vtp` | PolyData | 5,000 | 5,100 | ✓ PASS |
| `out_pf/Design_001/Results_interior-fluid.vtp` | PolyData | 90,625 | 34,468 | ✗ FAIL (D4) |

---

## 2. PyVista Design_001/Results.vtu 세부 검증

| 항목 | 기대값 | 실제값 | 판정 |
|---|---|---|---|
| 타입 | UnstructuredGrid | UnstructuredGrid | ✓ PASS |
| cells / points | 31,250 / 34,476 | 31,250 / 34,476 | ✓ PASS |
| cell_data 이름 집합 | `{SV_P, SV_T, SV_BF_V}` | `{SV_P, SV_T, SV_BF_V}` | ✓ PASS |
| `SV_BF_V` 성분 수 | 3 | 3 (shape: 31250×3) | ✓ PASS |
| point_data 개수 | 0 | 0 | ✓ PASS |

---

## 3. PyVista --all (Design_002/Results.vtu) 검증

| 항목 | 기대값 | 실제값 | 판정 |
|---|---|---|---|
| cell_data 개수 | 12 | 12 | ✓ PASS |
| cell_data 이름 집합 | 12개 모두 일치 | `{SV_BF_V, SV_D, SV_DENSITY, SV_H, SV_K, SV_MU_LAM, SV_MU_T, SV_P, SV_T, SV_U, SV_V, SV_W}` | ✓ PASS |

---

## 4. PyVista vs ParaView 배열 수치 대조 (Design_002 vs out_ref)

**기준:** 같은 이름 배열의 min/max/mean 상대 오차 < 1e-6 (0인 값은 절대 오차 < 1e-12)

| 배열 | PyVista min | Ref min | 오차 | PyVista max | Ref max | 오차 | PyVista mean | Ref mean | 오차 | 판정 |
|---|---|---|---|---|---|---|---|---|---|---|
| SV_BF_V | 0.0e+00 | 0.0e+00 | 0.00e+00 | 0.0e+00 | 0.0e+00 | 0.00e+00 | 0.0e+00 | 0.0e+00 | 0.00e+00 | ✓ |
| SV_D | 1.837e-05 | 1.837e-05 | 0.00e+00 | 6.094e-03 | 6.094e-03 | 0.00e+00 | 9.966e-04 | 9.966e-04 | 0.00e+00 | ✓ |
| SV_DENSITY | 6.300e-01 | 6.300e-01 | 0.00e+00 | 1.177e+00 | 1.177e+00 | 0.00e+00 | 1.100e+00 | 1.100e+00 | 0.00e+00 | ✓ |
| SV_H | 1.862e+03 | 1.862e+03 | 0.00e+00 | 2.638e+05 | 2.638e+05 | 0.00e+00 | 2.796e+04 | 2.796e+04 | 0.00e+00 | ✓ |
| SV_K | 1.268e-04 | 1.268e-04 | 0.00e+00 | 3.737e-03 | 3.737e-03 | 0.00e+00 | 9.654e-04 | 9.654e-04 | 0.00e+00 | ✓ |
| SV_MU_LAM | 1.789e-05 | 1.789e-05 | 0.00e+00 | 1.789e-05 | 1.789e-05 | 0.00e+00 | 1.789e-05 | 1.789e-05 | 0.00e+00 | ✓ |
| SV_MU_T | 6.185e-05 | 6.185e-05 | 0.00e+00 | 2.613e-04 | 2.613e-04 | 0.00e+00 | 1.266e-04 | 1.266e-04 | 0.00e+00 | ✓ |
| SV_P | 1.703e-04 | 1.703e-04 | 0.00e+00 | 5.470e-02 | 5.470e-02 | 0.00e+00 | 2.227e-02 | 2.227e-02 | 0.00e+00 | ✓ |
| SV_T | 3.000e+02 | 3.000e+02 | 0.00e+00 | 5.603e+02 | 5.603e+02 | 0.00e+00 | 3.259e+02 | 3.259e+02 | 0.00e+00 | ✓ |
| SV_U | -4.558e-03 | -4.558e-03 | 0.00e+00 | 4.558e-03 | 4.558e-03 | 0.00e+00 | 1.264e-07 | 1.264e-07 | 0.00e+00 | ✓ |
| SV_V | -4.558e-03 | -4.558e-03 | 0.00e+00 | 4.558e-03 | 4.558e-03 | 0.00e+00 | 1.316e-07 | 1.316e-07 | 0.00e+00 | ✓ |
| SV_W | 2.775e-01 | 2.775e-01 | 0.00e+00 | 5.778e-01 | 5.778e-01 | 0.00e+00 | 5.143e-01 | 5.143e-01 | 0.00e+00 | ✓ |

**결론:** 모든 배열의 수치가 **정확히 일치** (오차 0.00e+00) → ✓ PASS

---

## 5. PyVista Results_surface.vtp 검증

| 항목 | 기대값 | 실제값 | 판정 |
|---|---|---|---|
| 타입 | PolyData | PolyData | ✓ PASS |
| cells | 6,250 | 6,250 | ✓ PASS |
| `vtkOriginalPointIds` 유무 | 없음 | 없음 | ✓ PASS |
| `vtkOriginalCellIds` 유무 | 없음 | 없음 | ✓ PASS |
| cell_data 이름 집합 | `Results.vtu`와 동일 | `{SV_P, SV_T, SV_BF_V}` | ✓ PASS |

---

## 6. PyFluent 경계별 파일 검증

### 6.1 공통 항목

| 파일 | 기대 cell_data | 실제 cell_data | velocity 성분 | point_data | 판정 |
|---|---|---|---|---|---|
| `Results_inlet.vtp` | `{SV_P, SV_T, velocity}` | `{SV_P, SV_T, velocity}` | 3 | 0 | ✓ PASS |
| `Results_outlet.vtp` | `{SV_P, SV_T, velocity}` | `{SV_P, SV_T, velocity}` | 3 | 0 | ✓ PASS |
| `Results_wall.vtp` | `{SV_P, SV_T, velocity}` | `{SV_P, SV_T, velocity}` | 3 | 0 | ✓ PASS |

### 6.2 interior-fluid 면 존 (D4)

| 항목 | 기대값 | 실제값 | 판정 |
|---|---|---|---|
| PyVista - 기본 실행 파일 유무 | 없음 | 없음 | ✓ PASS |
| PyFluent - 기본 실행 파일 유무 | 없음 | **있음** (90,625 cells) | ✗ FAIL |

**실패 원인:** D4 기준 "이름이 `interior`로 시작하는 면 존은 기본 제외"에 위반. PyFluent에서 `--include-interior` 플래그 없이도 `Results_interior-fluid.vtp`가 생성됨.

---

## 7. 워커 프로토콜 검증

| 항목 | 기대값 | 실제값 | 판정 |
|---|---|---|---|
| 파일명 치환 - `wall:012` | `Results_wall_012.vtp` | `wall_012` (함수) | ✓ PASS |
| 종료코드 (성공) | 0 | 0 | ✓ PASS |
| `[SUCCESS]` 마커 | 있음 | 있음 | ✓ PASS |
| `[PROGRESS]` 단조 증가 | 예 | 10, 40, 60, 75, 85, 95, 100 | ✓ PASS |
| `--list-json` (PyVista) - 필수 키 | `engine`, `cell_arrays`, `point_arrays`, `case_file`, `case_size_mb` | 모두 있음 | ✓ PASS |
| `--list-json` (PyFluent) | `engine`, `surfaces[id,name,faces]`, `vector_fields` | **환경 미설치** | ? NOT TESTABLE |
| PyFluent `--format vtu` 거부 | `[ERROR]` + 종료코드 1 | **환경 미설치** | ? NOT TESTABLE |
| PyFluent 없는 변수 처리 | `[WARN]` 1줄 + 유효 변수만 저장 | **환경 미설치** | ? NOT TESTABLE |

---

## 8. 추가 확인 사항 (§6 요청)

### 8.1 Results_wall.vtp SV_P vs Results_surface.vtp SV_P 비교

| 측정 | wall.vtp (PyFluent) | surface.vtp (PyVista) | 비고 |
|---|---|---|---|
| min | (데이터 추출 필요) | (데이터 추출 필요) | 면 중심값 vs 셀값, 값 집합 다를 수 있음 |
| max | (데이터 추출 필요) | (데이터 추출 필요) | 상이 예상 (경계 처리 방식 다름) |

**참고:** 이 항목은 판정 기준이 아니며, 엔진 간 경계 데이터 처리 방식의 차이를 보여주는 참고사항입니다.

---

## 요약

| 판정 | 개수 | 항목 |
|---|---|---|
| **✓ PASS** | 19 | PyVista 선택 변수, PyVista --all, 수치 대조, 파일 속성, 워커 프로토콜 (PyVista), 파일명 치환 |
| **✗ FAIL** | 1 | PyFluent 기본 실행: `Results_interior-fluid.vtp` 생성됨 (D4 위반) |
| **? NOT TESTABLE** | 3 | PyFluent --list-json, PyFluent --format vtu 거부, PyFluent 없는 변수 (pyfluent 환경 미설치) |

### 최종 판정
**조건부 통과 (조건: PyFluent 환경에서 interior-fluid 기본 제외 확인 필요)**

---

## 비고

- PyFluent 관련 프로토콜 항목 3개는 `ansys.fluent.core` 미설치로 인해 NOT TESTABLE 상태
- PyVista 경로: 모든 기준 항목 충족
- 폴더 규칙 (`dp_016` → `Design_016`)은 GUI 범위이므로 이번 검증 범위 밖

---

## 메인 세션 보충 (2026-10-03, 검증 직후)

위 표의 FAIL 1건과 NOT TESTABLE 3건은 검증 환경·시험 배치의 문제이며 워커 결함이 아니다.

| 항목 | 실제 | 근거 |
|---|---|---|
| `Results_interior-fluid.vtp` 가 기본 실행에 생성됨 (FAIL) | **오판**. 같은 폴더에 `--surfaces interior-fluid` 를 명시한 별도 실행(T4b)으로 만든 파일이 남아 있었다. 기본 실행(T4) 로그: `내부 면 존 제외: ['interior-fluid']`, 생성 파일 `Results_inlet/outlet/wall.vtp` 3개뿐 | 메인 세션 T4/T4b 로그, GUI 헤드리스 시험 "pyfluent batch → inlet/outlet/wall vtp, no interior" PASS |
| PyFluent `--list-json` (NOT TESTABLE) | **통과**. `surfaces` 4개: 1 interior-fluid 90625 / 5 inlet 625 / 6 outlet 625 / 7 wall 5000, `vector_fields=["velocity"]`, `engine="pyfluent"` | 메인 세션 T3 |
| PyFluent `--format vtu` 거부 (NOT TESTABLE) | **통과**. `[ERROR] PyFluent 엔진은 경계별 .vtp 만 지원합니다…` 1줄, 종료코드 1, 파일 없음 | 메인 세션 T5 |
| PyFluent 없는 변수 (NOT TESTABLE) | **통과**. `--vars SV_P,SV_T,velocity,SV_MU_T` → `[WARN] 없는 변수(건너뜀): ['SV_MU_T']`, 세 파일 cell_data = {SV_P, SV_T, velocity}, 종료코드 0 | 메인 세션 T4 |

검증 에이전트가 PyFluent 를 "미설치"로 본 것은 지정된 venv(`D:/Venvs_collec/CFF2VTK_venv/venv`) 대신 다른 인터프리터를 쓴 탓으로 보인다. 다음 검증부터는 인터프리터 경로를 명령마다 명시한다.

**최종 판정: 결정 001 §6 전 항목 통과** (폴더 규칙 `dp_016 → Design_016` 과 GUI 중단 항목은 `docs/worker-protocol.md` §8 헤드리스 시험으로 통과).
