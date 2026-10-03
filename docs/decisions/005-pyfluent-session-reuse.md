# 결정 005 — PyFluent 변환 탭 배치의 Fluent 세션 재사용 (v2.1 후보)

- 상태: **확정 → 구현 완료** (2026-10-03 밤, 사용자 "진행해줘" — 설계 A, 나머지 축은 추천안). 검증: `tests/headless/gui_headless_test_v17.py`(jobs 모드로 개정) — 결과는 `docs/WORKLOG.md`
- 범위: `PyFluentTab` 배치 변환 + `pyfluent_export_worker.py`. 변환기 탭(PyVista/ParaView)·DP 정리·bc_json 탭은 무관
- 근거: `docs/probe/pyfluent-live.md` §7 (세션 재사용 실측), impact-scan 보고(이 문서 §6 에 요약), 결정 004

## 1. 맥락

v1.7 PyFluent 탭은 **CFF 파일 1개 = 워커 프로세스 1개 = Fluent 기동 1회**다. Cyclone 급 케이스 하나에 96–107 s 가 드는데 그중 기동 30 s + 종료 5 s + 인터프리터·pyfluent import 5 s ≈ 40 s 는 케이스 내용과 무관한 고정비다. 사용자 요청: 여러 CFF 를 변환할 때 Fluent 를 한 번만 띄우고 케이스를 바꿔 가며 변환할 수 있는지 시험하고 개선 여부를 검토.

## 2. 실측 요약 (상세 §7 of pyfluent-live.md)

| 질문 | 답 |
|---|---|
| 같은 세션에서 격자가 다른 케이스를 `read_case` 로 바꿔 읽을 수 있나 | 된다. 존·표면·셀 수·SVAR 가 새 케이스로 갱신되고 확인 질문·예외 없음 (dp0→dp2→dp4→box→dp0→dp0 VTP, 6건) |
| 결과가 케이스별 기동과 같은가 | 같다. 셀·점·좌표·전 배열 최대차 0 (dp0, dp2) |
| 메모리가 쌓이나 | 안 쌓인다 (Fluent 1,486 → 1,530 MB / 6건) |
| 얼마나 빨라지나 | 케이스당 35–40 s. Cyclone 급 −35 % (96–107 → 59–69 s), box 급 −67 % (58 → 19 s). 13 DP 추정 21–23분 → 14–15분 |
| 더 줄일 곳 | 남는 시간은 read_case 20–32 s, get_mesh 15–21 s 가 대부분. `processor_count=4` 는 둘 다 안 빨라지고 **셀 순서가 바뀐다** |

## 3. 가정
- A1. 배치의 케이스는 대부분 같은 차원(2D 또는 3D)이다. 섞이면 세션을 다시 띄운다(기동 1회 추가).
- A2. 사용자는 배치 동안 Fluent 라이선스 1석이 계속 점유되는 것을 받아들인다(지금도 케이스마다 점유하므로 총량은 줄어든다).
- A3. 변수 불러오기(`--list-json`)는 지금처럼 별도 기동 1회를 유지한다(라이선스를 유휴 점유하지 않기 위해).
- A4. `processors` 는 기본 1 을 유지한다(속도 이득 없음 + 셀 순서 변화).

## 4. 후보 비교

| 후보 | 내용 | 장점 | 단점 / 위험 |
|---|---|---|---|
| C. 현행 유지 | 케이스마다 워커·Fluent | 변경 없음, 실패 격리가 프로세스 단위로 단순 | 케이스당 ~40 s 고정비. 13 DP 에 ~8분 낭비 |
| **A. jobs 파일 (추천)** | 워커가 `--jobs <json>` 으로 케이스 목록을 받아 Fluent 1회 기동 후 루프. stdout 에 `[FILE_START]/[FILE_DONE]` 추가 | 절감 전부 확보. stdin 은 CANCEL 전용으로 유지(불변 규칙). 로더·변환기 탭 무수정. 단일 `--case` 모드 병존으로 CLI·기존 시험 호환 | GUI 배치 흐름 8개 메서드와 워커 9개 함수 수정. 케이스 실패를 `sys.exit` 가 아닌 예외로 격리해야 함. 워커 크래시 시 남은 케이스 정책 필요 |
| B. 상주 서버 | 워커를 탭 수명 동안 띄워 두고 stdin 으로 LIST/CONVERT 명령 | 변수 불러오기 기동까지 재사용 | stdin 명령과 CANCEL 이 같은 채널(프레이밍 필요), 라이선스 유휴 점유, 로더 재작성, 상태 오염 누적. 닿는 함수 A 의 1.5배 |

## 5. 결정 (제안: A)

### 5.1 워커 (`pyfluent_export_worker.py`)
| 항목 | 내용 |
|---|---|
| 인자 | `--jobs <json 파일>` (utf-8): `[{"index": 1, "case": "...", "output": "...", "format": "vtu"|"vtp"}, ...]`. 공통 `--vars --rename --processors --ascii --no-check`. 기존 `--case/--output` 단일 모드는 그대로 둔다(`--jobs` 와 상호 배타) |
| 세션 | 첫 케이스 차원으로 1회 기동. 케이스 차원 ≠ 세션 차원이면 `close_session` → 재기동. 기동마다 `[FLUENT_PID]` 1줄 |
| 케이스 경계 줄 | `[FILE_START] i/n <case 경로>` → (기존 `[1]…[6]`·`[PROGRESS] 0–100`·`[VERIFY]`) → `[FILE_DONE] i/n ok` 또는 `[FILE_DONE] i/n fail <메시지 1줄>` |
| 실패 격리 | dat 없음·변수 없음 등 **Fluent 호출 전** 실패: `[FILE_DONE] fail`, 세션 유지, 다음 케이스. `read_case/read_data/get_mesh/SVAR` 등 **Fluent 호출 중** 예외: `[FILE_DONE] fail` 후 세션 폐기(`close_session`), 다음 케이스에서 재기동 (상태 오염 방지). `fail()`=`sys.exit` 호출 경로는 단일 모드에만 남긴다 |
| 마무리 | 전부 성공 → `[PROGRESS] 100` + `[SUCCESS]`, 종료코드 0. 하나라도 실패 → `[ERROR] n건 실패 (성공 m건)`, 종료코드 1. 중단 → `[ERROR] 사용자 중단`, 종료코드 1 |
| 중단 | stdin `CANCEL` 수신 경로 불변. 루프 머리·기동 직전·기존 `check_cancel` 지점에서 `_CANCEL` 검사 → 남은 케이스 건너뜀 |
| 임시 폴더 | work_dir 1개(배치 전체). 정션은 케이스별 `work_dir/c<i>/case_dir` (현재 고정 이름 `case_dir` 는 2번째 케이스에서 충돌 → 조용히 복사 폴백으로 빠지는 버그 요인). 케이스 끝나면 정션 `os.rmdir`·복사본 삭제. 케이스마다 work_dir mtime 갱신(`remove_stale_workdirs` 의 10분 규칙으로부터 보호) |

### 5.2 GUI (`PyFluentTab`)
| 항목 | 내용 |
|---|---|
| 배치 = QProcess 1개 | `_run_batch` 가 출력 경로 N개를 미리 계산(`_compute_output_path`, 같은 순서라 결과 동일)해 jobs 파일을 `%TEMP%` 에 쓰고 워커 1회 호출. 배치 끝·중단·크래시 뒤 jobs 파일 삭제 |
| 집계 | `[FILE_DONE] ok/fail` 로 성공·실패 카운트와 진행률(완료 건수/전체). `[FILE_START]` 에서 현재 파일 라벨·로그 헤더 `[i/n] 이름 → 폴더/Results.vtu` |
| 워커 종료 처리 | `finished` 시 `FILE_DONE` 을 못 받은 케이스는 실패로 집계(크래시·FailedToStart). `kill_fluent_pids` 는 **워커가 끝난 뒤에만**(케이스 실패 때 호출하면 살아 있는 세션을 죽인다) |
| 중단 | 현행 그대로 CANCEL → 30 s → kill → taskkill. `batch_index = batch_total` 트릭은 불필요(워커가 루프를 끝낸다) |
| 문구 | 확인창 "케이스마다 Fluent 기동 — 약 1–2분/케이스" → "Fluent 1회 기동(30–45 s) + 케이스당 20 s–1분". 탭 안내문 동일 취지로 |

### 5.3 틀렸을 때 어디서 드러나는가
- 세션 상태 오염(이전 케이스 값이 섞임) → §7 판정 기준 "2번째 케이스 값 = 케이스별 기동 결과(최대차 0)" 에서 잡힌다.
- 케이스 실패 뒤 다음 케이스가 안 돌거나 Fluent 가 남음 → 판정 기준 "[dat 없음, 정상, 정상] 배치" 와 "Fluent 잔존 0".
- 중단 시 다음 케이스가 시작됨 → 판정 기준 "2번째 중 CANCEL → 3번째 미시작".

## 6. 영향받는 코드 (impact-scan 2026-10-03 요약; 줄 번호는 현재 파일 기준)

| 파일 | 함수·위치 | 변경 |
|---|---|---|
| `pv_export_gui.py` | `_run_batch` 2165-2265, `_process_next` 2267-2304, `_on_process_error` 2306-2316, `_emit_worker_lines` 2318-2330, `_on_file_finished` 2332-2351, `_cancel_batch` 2378, `_build_ui` 1883/1901 문구, 확인창 2231 | 배치 흐름 재작성(§5.2). `ConverterTab` 은 한 줄도 안 바꾼다(`_on_process_output` 차용 유지, FILE_* 파싱은 `_emit_worker_lines` 에만) |
| `pyfluent_export_worker.py` | `fail` 79, `check_cancel` 158, `launch` 201, `close_session`/`_STATE` 64·222, `ascii_alias` 239, `open_case` 271(→ ensure_session + load_case 분리), `resolve_or_fail` 301, `convert` 586, `main` 658 | §5.1 |
| `docs/worker-protocol.md` | §1b 21·22·25–28·30, §4·§5·§6 표 | `--jobs`, FILE_*, 종료코드 정책, 재기동 시 `[FLUENT_PID]` 반복 |
| `tests/headless/gui_headless_test_v17.py` | 97–113 배치 단언 | 케이스 순서를 [dat 없음, 정상, 정상] 으로 바꿔 "실패 뒤 세션 계속" 검증, `[FLUENT_PID]` 1회 확인, 유효 한글 경로 케이스 2개(정션 충돌) |
| `USER_GUIDE.md` 5장(PyFluent 변환기), `README.md` | 소요 시간·라이선스·중단 설명, CLI `--jobs` | 문구 |

## 7. 판정 기준 (`vtk-verify` 가 그대로 대조)

| 대상 | 항목 | 기대값 | 비고 |
|---|---|---|---|
| 배치 2건 (box 사본 dp_007·dp_009, 한글 경로, VTU `SV_P,SV_T --rename`) | 콘솔 `[FLUENT_PID]` 줄 수 | 1 | 세션 1회 |
| 〃 `Design_007/Results.vtu`, `Design_009/Results.vtu` | 타입·셀 수·cell_data | UnstructuredGrid, 31,250, {pressure, temperature} 각각 | 단일 모드와 동일 |
| 배치 3건 [dp_008(dat 없음), dp_007, dp_009] | 집계 / 종료코드 / 출력 | 실패 1·성공 2 / 1 / Design_008 없음, 007·009 있음 | 실패 뒤 세션 계속 |
| Cyclone dp0 → dp2 세션 재사용 VTU | dp2 셀 수 / 케이스별 기동 결과 대비 | 367,041 / 전 배열·좌표 최대차 0 | §7a·7b 실측 완료 |
| 2번째 케이스 진행 중 CANCEL | 3번째 `[FILE_START]` 없음, 1번째 출력 유지, Fluent 잔존 0, 중단 완료 ≤ 30 s | | |
| 배치 뒤 | `cx2610.exe`/`fl2610.exe` 0, `%TEMP%\cff_pyfluent_*` 0, 케이스 폴더에 `.cff_link_*`·`.trn`·`cleanup-fluent*` 0, jobs 파일 0 | | |
| 변환기 탭 | `gui_headless_test_v16.py` | 21/21 | 불변 |
| 시간 | Cyclone 2건 배치 벽시계 | ≤ 175 s (실측 163 s), 케이스별 기동 203 s 대비 −20 % 이상 | 기동·디스크 편차 고려 |

## 8. 사용자 선택

| 축 | 추천 | 대안 |
|---|---|---|
| 방식 | **A** jobs 파일, 배치당 워커 1개 | C 현행 유지 / B 상주 서버 |
| 일부 실패 시 종료코드 | 1 + `[ERROR] n건 실패` | 0 + `[WARN]` |
| Fluent 호출 중 예외 뒤 | 세션 폐기 → 다음 케이스에서 재기동 | 세션 유지 시도 |
| `processors` | 기본 1 유지, 안내문에 "2 이상은 셀 순서가 바뀜" | 그대로 |
| 변수 불러오기 세션 재사용 | 안 함 | B 로 확장(별도 결정) |

## 9. 미확정
- read_case 가 세션 안에서 20 → 30 s 로 느려지는 경향의 원인(수십 건 배치에서 재확인).
- 2D·3D 혼재 배치의 재기동 경로(샘플 없음).
- Fluent 호출 중 예외 뒤 세션을 유지해도 되는지(보수적으로 폐기 선택).
- 정션을 `read_data` 뒤 바로 지워도 Fluent 가 그 경로를 다시 열지 않는지(케이스 끝난 뒤 삭제로 회피).
