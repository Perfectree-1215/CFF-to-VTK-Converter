# 검증 v2.1 — 결정 005 (PyFluent 배치 Fluent 세션 재사용, 설계 A)

- 날짜: 2026-10-03 밤 · 기준: `docs/decisions/005-pyfluent-session-reuse.md` §7 · 환경: venv `CFF2VTK_venv` (pyfluent 0.42.1), Fluent 2026 R1, processor_count=1
- 수행: `tests/headless/gui_headless_test_v17.py`(jobs 모드로 개정, Box 샘플은 `…/Claude code-pyfluent/samples/Box` 외부 경로 자동 탐색) 4회 반복 + 워커 CLI 직접 실행 + 세션 재사용 실측(`docs/probe/pyfluent-live.md` §7)
- 결과: **4차 32/32 통과**, 사용자 ⑦(실제 화면 배치·중단) 통과 2026-10-04. 1~3차에서 드러난 결함 3건을 고쳤다 (아래 §3).

## 1. 결정 005 §7 판정표 대조

| 대상 | 항목 | 기대값 | 결과 |
|---|---|---|---|
| 배치 3건 (Box 사본 dp_006·dp_007·dp_009, 한글 경로 `입력 폴더 v17`, VTU `SV_P,SV_T --rename`) | 콘솔 `[FLUENT_PID]` 줄 수 | 1 | **1** (워커 1개, Fluent 1회 기동) — 통과 |
| 〃 `Design_007/Results.vtu`, `Design_009/Results.vtu` | 타입·셀 수·cell_data | UnstructuredGrid, 31,250, {pressure, temperature} | 둘 다 일치 — 통과 |
| 〃 순서 [dp_006(dat 없음), dp_007(Workbench 식 dat 이름), dp_009] | 집계 / 출력 / 순서 | 실패 1·성공 2, Design_006 없음, 실패가 먼저 보고된 뒤 세션 유지 | (2, 1), Design_006 없음, ✗ 가 ✓ 보다 앞 — 통과. 종료코드 1 은 CLI 확인(`[ERROR] 2건 실패 (성공 0건)`, exit 1) |
| Cyclone dp0 → dp2 세션 재사용 VTU | dp2 셀 수 / 케이스별 기동 결과 대비 | 367,041 / 전 배열·좌표 최대차 0 | 실측 §7a·7b 그대로 (jobs 모드도 같은 `load_case`→`convert` 경로) — 통과 |
| 2번째 케이스 진행 중 CANCEL (VTP, [dp_007, dp_009, dp_006]) | 3번째 `[FILE_START]` 없음, 1번째 출력 유지, Fluent 잔존 0, ≤ 30 s | | `[3/3]` 없음, `Design_007/Results.vtp` 유지, 잔존 0, **12 s**, 라벨 "중단됨 (성공 1, 실패 0)" — 통과 |
| 배치 뒤 | `cx2610`/`fl2610` 0, `%TEMP%\cff_pyfluent_*` 0, 케이스 폴더 잔여물 0, jobs 파일 0 | | 전부 0 (작업 폴더는 0 s 안에) — 통과 |
| 로더 진행 중 `shutdown()` | Fluent 잔존 0 | | 27 s 뒤 0 — 통과 |
| 변환기 탭 | `gui_headless_test_v16.py` 21/21 | 불변 | jobs 변경 전 마지막 실행 21/21. jobs 패치 전후 `ConverterTab`·`BCJsonTab` 클래스 본문이 바이트 동일함을 확인(`samples/` 삭제로 재실행 불가) |
| 시간 | Cyclone 2건 배치 ≤ 175 s | | 실측 163 s (§7). Box 3건 배치 **41 s**(기동 포함; 케이스별 기동이면 ≈ 3 × 43 s) |
| 레이아웃·JSON 생성기 | v20 시험 | 48/48, 20/20 | 통과 |

## 2. 반복 실행 이력

| 회차 | 결과 | 실패 항목 → 원인 → 조치 |
|---|---|---|
| 1차 | 31/32 | `shutdown` 뒤 Fluent 잔존 (12 s) → 워커 메인 스레드가 CANCEL 리스너의 `solver.exit()` 를 기다리지 않고 끝나 데몬 스레드가 끊김, Fluent 가 반쯤 닫힌 채 잔존 → `close_session` 에 `_EXIT_DONE` 대기 추가. 중단된 케이스가 "실패 1" 로 집계 → `사용자 중단` 사유는 실패로 세지 않음 |
| 2차 | 27/32 | 로드·배치·중단·종료 뒤 Fluent 잔존 → 단독 재현 안 됨(워커·로더 모두 즉시 소멸). 진단용으로 시험이 잔존 pid·시작 시각을 찍게 하고, 워커에 `_ensure_pids_gone`(exit 뒤 pid 소멸 확인, 남으면 워커가 taskkill), GUI `kill_fluent_pids` 에 소멸 확인·재시도, 로더 CANCEL 유예 5→20 s |
| 3차 | 31/32 | Fluent 잔존 전부 해소. 로더의 임시 작업 폴더가 `.trn` 잠금으로 15 s 안에 안 지워짐 → 워커 `[WORKDIR]` 줄 + GUI 가 끝난 워커의 폴더를 즉시·60 s 간격으로 지연 삭제(`_release_workdir`/`_sweep_workdirs`), 시험은 75 s 안에 0 으로 판정 |
| 4차 | **32/32** | — |

## 3. 이번 검증으로 바뀐 코드 (결정 005 범위 밖이지만 함께 고침)
- `pyfluent_export_worker.py`: `close_session` 이 다른 스레드의 종료를 기다림(`_EXIT_DONE`), `_ensure_pids_gone`, `remove_workdir`(20 s 재시도 + 보류 안내), `[WORKDIR]` 줄.
- `pv_export_gui.py`: `kill_fluent_pids` 소멸 확인·재시도, 로더 `_terminate` 유예 20 s, `WORKDIR_RE`·`_release_workdir`·`_sweep_workdirs`, `shutdown()` 의 임시 폴더 정리 1회 시도, 중단 사유 케이스는 실패 미집계.

## 4. 미검증
- 2D·3D 혼재 배치의 재기동 경로(샘플 없음). Fluent 호출 중 예외 뒤 세션 폐기·재기동 경로(인위적으로 만들지 않음 — 코드 경로만 존재).
- `samples/` 삭제로 v16(변환기 탭) 재실행 불가 — 클래스 본문 동일성으로 대신함.
- `%TEMP%\cff_pyfluent_wgs9f51p`(오후 실험, `.trn` 이 다른 프로세스에 잠김)는 수동 삭제 대상.
