# GUI ↔ 워커 프로토콜

- 갱신: 2026-10-03 (v2.1 — **PyFluent 배치 jobs 모드**(결정 005): 워커 1개가 `--jobs` 목록을 받아 Fluent 1회 기동, `[FILE_START]/[FILE_DONE]` 줄 추가. v2.0 — GUI 화면만 바뀜: Solarized Light 테마, 두 변환기 탭 2단 배치, 탭 이름 "PyVista 변환기"/"PyFluent 변환기". **프로토콜·인자·종료코드 불변**. v1.7 — **PyFluent 변환 탭** 추가(결정 004). v1.6 — PyFluent 엔진 제거, 데이터 파일 이름 해석·임시 링크 폴더. 결정 003)
- 적용 대상: `pv_export_gui.py` ↔ `pv_export_worker.py`(pvpython) · `cff_export_worker.py`(일반 python) · **`pyfluent_export_worker.py`(일반 python, Fluent 세션)** · 공용 `cff_common.py`
- 이 문서가 다음 수정의 판정 기준이다. 양쪽을 바꾸면 여기도 같이 바꾼다. v1.5 와 달라진 곳은 **[v1.6]**, v1.6 과 달라진 곳은 **[v1.7]**.

## 1. 실행 경로

| 탭 / 엔진 | 인터프리터 | 워커 | 포맷 |
|---|---|---|---|
| 변환기 탭 `pyvista` (기본) | `sys.executable` (pythonw.exe 면 같은 폴더의 python.exe) | `cff_export_worker.py` | vtu, vtp(외곽 표면 1장) |
| 변환기 탭 `paraview` | GUI 입력란의 pvpython 경로 | `pv_export_worker.py` | vtu (vtm 은 CLI 전용) |
| **[v1.7] PyFluent 변환 탭** (`PyFluentTab`, 엔진 라디오 없음) | `python_interpreter()` (같은 venv, ansys-fluent-core 필요) | `pyfluent_export_worker.py` | vtu(셀 존 격자 재구성), vtp(경계 면 존 병합 1장) |

- **[v1.6]** 변환기 탭에 PyFluent 엔진·`--engine` 인자·경계 선택 UI 는 없다. `cff_export_worker.py` 에 `--engine` 을 보내면 argparse 종료코드 2. **[v1.7]** PyFluent 는 변환기 탭의 엔진이 아니라 **별도 탭**이다 (모듈 상수 `ENGINE_PYFLUENT` 는 여전히 없다. 새 탭은 `PYFLUENT_ENGINE`/`PYFLUENT_WORKER_SCRIPT` 를 쓴다).

## 1b. PyFluent 변환기 탭 **[v1.7]** (결정 004) + 배치 jobs 모드 **[v2.1]** (결정 005)

| 항목 | 규칙 |
|---|---|
| 기동 | **[v2.1]** 배치 워커는 `launch_fluent(mode="solver", processor_count=N, ui_mode="no_gui_or_graphics", start_transcript=False, start_watchdog=False, cwd=%TEMP%/cff_pyfluent_*)` 를 **배치당 1회**만 부르고 케이스마다 `read_case`→`read_data` 로 바꿔 읽는다 (`ensure_session`/`load_case`). 케이스 차원(2D/3D)이 세션과 다르면, 또는 Fluent 호출 중 예외가 나면 세션을 닫고 다음 케이스에서 재기동. 기동 30–45 s + 케이스당 읽기·변환 20 s–1분. 라이선스 1석. 단일 `--case` 모드와 `--list-json` 은 기동 1회·케이스 1개 그대로 |
| `[FLUENT_PID] fluent=<pid> cortex=<pid>` | 기동할 때마다 1줄 (jobs 모드는 보통 배치당 1회, 재기동하면 다시). GUI 는 마지막 값만 쓴다. GUI(배치: `_emit_worker_lines`, 로더: 줄 단위 읽기)가 `[cortex, fluent]` 로 기억한다 |
| 변수 목록 | `--list-json` 응답에 `cell_arrays`(셀 존 SVAR, VTU 용), `face_arrays`(경계 면 존 SVAR, VTP 용), `boundaries[{name, zone_id, n_faces}]`, `cell_zones`, `fluent_version`, `dimension`, `hidden_cell_arrays`, `n_cells`, `data_file`, `data_name_matches`. 솔버 내부 배열(`cff_common.is_hidden_svar`)은 숨김, `--all` 이면 포함. GUI 는 선택 포맷의 목록을 보여 주고, 포맷 전환 시 **같은 이름의 체크를 유지**한다 |
| 로더 | `PyFluentVariableLoader` (stdin PIPE, 타임아웃 600 s, 줄 단위 읽기). 취소/시간 초과 = `CANCEL` 한 줄 → **20 s** 대기(워커는 Fluent 가 실제로 내려간 뒤 끝난다) → `kill()` → `taskkill /T /F <pid>` + 소멸 확인(최대 8 s, 재시도). **[v2.1]** 워커 `close_session` 은 다른 스레드(CANCEL 리스너)가 `solver.exit()` 중이면 끝날 때까지 기다린다 — 메인이 먼저 끝나 데몬 스레드의 exit 가 끊기면 Fluent 가 반쯤 닫힌 채 수십 초 남았다(실측 2026-10-03, 로더 shutdown 시험) |
| 변환 인자 | 단일: `--case --output --format vtu\|vtp --vars a,b,c --processors N [--rename]`. **[v2.1] 배치(GUI)**: `--jobs <json> --vars a,b,c --processors N [--rename]` — jobs JSON 은 `[{"index": i, "case": …, "output": …, "format": "vtu"\|"vtp"}]`(utf-8, GUI 가 `%TEMP%/cff_pyfluent_jobs_*.json` 에 쓰고 배치가 끝나면 삭제). 워커 stdout 에 케이스마다 `[FILE_START] i/n <case>` … `[FILE_DONE] i/n ok` 또는 `[FILE_DONE] i/n fail <사유 한 줄>`. 파일 안 `[PROGRESS]` 는 케이스 내 0–100 (GUI 는 버림). 두 포맷 모두 `Design_NNN/Results.*` 규칙 동일. `SV_U,SV_V,SV_W` 가 모두 있으면 워커가 `velocity`(3) 를 추가한다 |
| 데이터 파일 | `cff_common.resolve_data_file` 로 고른 경로를 `read_data` 에 직접 지정 (하드링크 폴더 없음). dat 없음 → 단일 모드 `[ERROR]` + 1, jobs 모드 `[FILE_DONE] i/n fail …` 뒤 **세션 유지**하고 다음 케이스 (초기화 금지). 로그 `  데이터 파일: FFF.3-2-11200.dat.h5 (이름이 달라 PyFluent 에 직접 지정)` |
| **중단 순서** | GUI `중단` → 확인 → `process.write(b"CANCEL\n")` (jobs 모드: 다음 케이스를 시작하지 않는 것은 워커가 루프 머리·기동 직전·`check_cancel` 지점에서 `_CANCEL` 을 보고 루프를 끝내며 보장) (stdin 은 열어 둔다 — `closeWriteChannel` 금지) → 워커의 stdin 스레드가 `solver.exit()` → 메인은 `[ERROR] 사용자 중단` + 종료코드 1 → GUI `_on_cancelled_finished` 가 pid 를 한 번 더 `taskkill`(보통 이미 없음). **30 s** 안에 안 끝나면 `_force_kill_worker`: `kill()` → `waitForFinished(3000)` → `taskkill /T /F` cortex, fluent |
| 실패·크래시 | **[v2.1]** 집계는 `[FILE_DONE]` 이 기준. 워커가 끝났을 때 `[FILE_DONE]` 을 못 받은 케이스는 실패로 센다(크래시·FailedToStart·조기 종료). `kill_fluent_pids` 는 **워커가 끝난 뒤에만**(CrashExit 또는 종료코드≠0; 케이스 실패 중에는 살아 있는 세션이므로 부르지 않는다). 종료코드: 전부 성공 0, 하나라도 실패 1(`[ERROR] k건 실패 (성공 m건)`), 중단 1(`[ERROR] 사용자 중단`) |
| 앱 종료 | `PyFluentTab.shutdown()`: 로더 `cancel()`+`wait(8000)`, 프로세스 `CANCEL` → `waitForFinished(8000)` → `kill()` → pid 정리 |
| `[WORKDIR] <경로>` **[v2.1]** | 워커가 시작 직후 임시 작업 폴더(`%TEMP%/cff_pyfluent_*`)를 알린다. 워커는 끝날 때 최대 20 s 재시도해 지우고, 못 지우면 `임시 폴더 삭제 보류` 줄을 남긴다(Fluent 가 끝난 뒤에도 `.trn` 이 잠시 잠겨 있을 수 있음, 실측). GUI 는 **끝난** 워커·로더의 폴더만 기억해 즉시·60 s 간격으로 다시 지운다(`_release_workdir`/`_sweep_workdirs`). 실행 중인 워커 폴더는 건드리지 않는다 |
| 잔여물 | 한글 경로 별칭(정션)은 케이스별 `work_dir/c<i>/case_dir` 에 만들고 케이스가 끝나면 `os.rmdir`(링크만)·복사본 삭제. 배치 중 `work_dir` mtime 을 갱신해 다른 워커의 10분 정리로부터 보호. Fluent 전사(`.trn`)·`cortexerror.log` 는 임시 cwd 에만 생기고 워커 종료 시 삭제(실패하면 다음 실행이 10분 지난 것 정리). 케이스 폴더·출력 폴더에는 아무것도 남지 않는다 |
| 실측 근거 | `docs/probe/pyfluent-live.md` §4: 워커 kill 만으로는 Fluent 8개 프로세스가 남고 pyfluent watchdog·cleanup bat 는 믿을 수 없다 → 협조적 중단 + pid 폴백 |
- GUI 시작 시 `detect_engine_modules()` 가 `importlib.util.find_spec("pyvista")` 로 PyVista 가능 여부만 확인한다.
- 포맷 라디오는 VTU / VTP. 엔진을 바꿀 때 현재 포맷이 허용되면 유지, 아니면 엔진의 첫 포맷으로 옮긴다. **[v1.6]** 포맷 전환은 변수 체크 상태를 건드리지 않는다.
- 배치 시작 시 엔진·인터프리터·워커·포맷·변수·변수명 옵션을 `batch_*` 로 캡처한다. 배치 중 엔진·포맷·변수·변수명 위젯은 잠긴다.
- Windows venv 의 `python.exe` 는 런처이며 자식 인터프리터를 띄운다. 런처를 `kill()` 하면 자식도 함께 종료된다 (실측).

## 2. 데이터 파일 이름 해석 **[v1.6]** (`cff_common.py`, 두 워커 공통)

vtkFLUENTCFFReader 는 `<base>.cas.h5` 와 같은 이름의 `<base>.dat.h5` 만 자동으로 읽는다. Workbench 원본(`FFF.3-2.cas.h5` + `FFF.3-2-11200.dat.h5`)은 못 찾아 셀 배열 0개가 된다 (사용자 2차 시험의 "변수 불러오기 안 됨").

| 단계 | 규칙 |
|---|---|
| 후보 | `<base>.dat.h5` 가 있으면 그것. 없으면 같은 폴더의 `<base>-<n>.dat.h5` 중 n 최대 (`<base>-<n>.cas.h5` 가 있으면 형제 케이스 것이라 제외) |
| 이름이 다를 때 | 케이스 폴더 안 `.cff_link_<rand>_tmp/` 에 `case.cas.h5`·`case.dat.h5` 하드링크(`os.link`). 실패하면 복사 + `[WARN] 하드링크 실패 … 복사로 대체` |
| 로그 | `  데이터 파일: box.dat.h5` / `  데이터 파일: FFF.3-2-11200.dat.h5 (이름이 달라 임시 하드링크로 연결)` |
| dat 없음 | `--list-json`: `###JSON_START###{"error": "데이터 파일(.dat.h5) 없음: …"}###JSON_END###` + 종료코드 1 → GUI `_on_vars_error` 오류창. 변환: `[ERROR] 데이터 파일(.dat.h5)을 찾지 못했습니다 …` + 종료코드 1. 격자만 변환하는 경로는 없다 |
| 정리 (워커) | 읽은 뒤 삭제 시도 → 실패하면 `  임시 링크 폴더(…)는 프로세스 종료 후 정리됩니다` 출력 + 종료 시 재시도. 실측: 프로세스의 첫 CFF 리더는 종료까지 HDF5 핸들을 놓지 않으므로 보통 남는다 |
| 정리 (GUI) | 워커 프로세스가 끝난 직후 `remove_stale_link_dirs(케이스 폴더, retries=10, delay=0.3)` — 변수 로드 완료·실패, 파일 완료, 중단, 앱 종료 전부. 콘솔 `[GUI] 임시 링크 폴더 N개 정리` |
| 정리 (CLI) | 워커 시작 시 같은 폴더의 10분 넘은 `.cff_link_*` 삭제 |
| 스캔 | GUI `_scan_folder` 는 경로에 `.cff_link_` 폴더가 있는 `.cas.h5` 를 제외한다. 폴더명이 `_tmp` 로 끝나므로 `bc_json_gen` 이 설계 번호로 오인하지 않는다 |
| 사전 고지 | 배치 확인 다이얼로그에 "dat 없는 케이스 N개 → 실패 처리", "이름이 다른 케이스 M개 → 임시 링크" 표시 (GUI 가 `resolve_data_file` 직접 호출, 표준 라이브러리만) |

## 3. 변수 목록 (`--list-json`)

호출: `<interp> <worker> --case <cas.h5> --list-json`
GUI: `VariableLoader(QThread)` → `subprocess.Popen(stdout=PIPE, stderr=STDOUT, text, utf-8)`, 타임아웃 300초, 취소는 `proc.kill()`.

```
###JSON_START###
{ … 한 줄 JSON … }
###JSON_END###
```

| 키 | ParaView | PyVista | 비고 |
|---|---|---|---|
| `cell_arrays` | 셀 배열 이름 | 셀 배열 이름 | 체크박스 원천. 이름은 항상 Fluent 원본(`SV_*`) |
| `point_arrays` | 포인트 배열 | `[]` | |
| `case_file`, `case_size_mb` | ✓ | ✓ | |
| `engine` | 없음 → GUI 가 `"paraview"` 로 보정 | `"pyvista"` | |
| `vector_fields` | 없음 | 3성분 배열 이름 | 참고용 |
| `data_file`, `data_name_matches` **[v1.6]** | 없음 | 실제로 읽은 dat 경로, 이름 일치 여부 | 불일치면 GUI 로그에 한 줄 |
| `n_cells`, `n_points` | 없음 | ✓ | |
| `error` | `{"error": …}` | 〃 + `"engine"` | 종료코드 1. GUI 오류창 |

- 응답의 `engine` 이 현재 선택 엔진과 다르면 목록을 버린다. 엔진 라디오를 바꾸면 목록을 비우고 "다시 불러오세요". `vars_engine != engine` 이면 실행 차단.
- **[v1.6]** `cell_arrays` 가 비어 있으면(dat 는 열렸으나 결과 없음) 경고창 "변수를 찾지 못했습니다 (0개)".

## 4. 변환 호출 인자

`--case <cas.h5> --output <경로> --format <vtu|vtp> --vars a,b,c [--rename]` — 두 엔진 동일. 그 외 인자는 보내지 않는다.

| 포맷 | 경로 | 생성 파일 |
|---|---|---|
| vtu | `<parent>/<folder>/Results.vtu` | 그 파일 |
| vtp | `<parent>/<folder>/Results.vtp` | 외곽 표면 1장 (PyVista 엔진만) |
| (CLI) | `--surface` / `--slice` | `Results_surface.vtp`, `Results_slice.vtp` |

- `--rename`: GUI "Fluent 표시명으로 저장" 체크(기본 ON). 매핑표 `cff_common.FLUENT_DISPLAY_NAMES`. 매핑 없는 이름은 원본 유지 + `[WARN] 표시명 없음(원본 유지)`. 신규 워커는 저장 직전 `cell_data` 이름 변경, ParaView 워커는 VTU 저장 뒤 vtk XML 되읽기로 변경.
- `<folder>` 규칙은 두 엔진 동일: `<prefix>_NNN` (`FOLDER_NUM_WIDTH` = 3), 파일명에 `dp_016` 이 있으면 `Design_016`. GUI 는 **원본** 파일명으로 출력 경로를 계산한다 (임시 링크의 `case.cas.h5` 이름은 출력에 영향 없음).
- 덮어쓰기 드라이런: 그 파일의 `exists`.

## 5. stdout 메시지 (변환 모드)

한 줄 단위, 모든 print 는 `flush=True`. GUI 는 `QProcess` + `MergedChannels`, 청크 경계 버퍼링(`_out_buf`).

| 줄 | 의미 | GUI 처리 |
|---|---|---|
| `[PROGRESS] N` | 파일 내 진행률, 단조 증가 | 무시 |
| `[SUCCESS]` | 성공 마지막 줄 | 무시 (판정은 종료코드) |
| `[ERROR] …` | 치명 오류 → 종료코드 1 | 들여쓰기 로그 |
| `[WARN] …` | 건너뜀·폴백 (없는 변수, 표시명 없음, 하드링크 실패→복사, 자기 검증 실패, 임시 폴더 삭제 실패) | 들여쓰기 로그 |
| `  데이터 파일: …` **[v1.6]**, `  임시 링크 폴더(…)는 프로세스 종료 후 정리됩니다` **[v1.6]** | dat 해석 결과 | 들여쓰기 로그 |
| `  [RENAME] a→b, …`, `[1]`~`[5]`, `[완료]`, `  [OK]`, `  [VERIFY] …`, `  최대 메모리: N MB` | 단계·요약·자기 검증 | 들여쓰기 로그 |

## 6. 종료 코드와 판정

| 상황 | 종료코드 | `exitStatus` | GUI 집계 |
|---|---|---|---|
| 성공 | 0 | NormalExit | 성공 +1 |
| `[ERROR]` (dat 없음 포함) | 1 | NormalExit | 실패 +1 |
| argparse 오류 (`--engine`, `--format vtm` 등 신규 워커가 모르는 인자) | 2 | NormalExit | 실패 +1 |
| 강제 종료·크래시 | 무관 | CrashExit | 실패 +1 |
| 인터프리터·스크립트 없음 | — | `FailedToStart` | 실패 +1 |

## 7. 취소·종료 순서

- 중단: 확인 → `finished.disconnect()` → `kill()` → `waitForFinished(3000)` → `process=None`, 버퍼 비움 → **[v1.6]** 케이스 폴더 링크 정리(재시도) → `batch_index = batch_total` → 버튼·위젯 복구.
- 앱 종료 `shutdown()`: 로더 `cancel()`+`wait(3000)`, 프로세스 `kill()`+`waitForFinished(2000)`, **[v1.6]** 링크 정리. `BCJsonTab.shutdown()` 은 비어 있다.
- 반쯤 쓰인 출력: 워커가 저장 직전에 같은 이름 파일을 지우고 저장한다.

## 8. 인코딩·경로
- 로더·QProcess 양쪽에 `PYTHONIOENCODING=utf-8`. 신규 워커는 `sys.stdout.reconfigure(utf-8)`. 경로는 인자 리스트로 전달(셸 미사용) → 한글·공백 안전. 임시 링크 폴더도 `tempfile.mkdtemp(dir=케이스 폴더)` 라 유니코드 경로 OK.

## 9. 탭 구성
| 탭 | 클래스 | 콘솔 / 로그 태그 | 백그라운드 |
|---|---|---|---|
| Workbench DP 정리 | `DPCollectTab` | 자체 / `DP정리` | 스레드 |
| PyVista 변환기 (v2.0 개명, 구 CFF To VTK 변환기) | `ConverterTab` | 자체 + 로그 파일 열기 / `변환` | `VariableLoader`, `QProcess` |
| **[v1.7]** PyFluent 변환기 (v2.0 개명) | `PyFluentTab` (ConverterTab 의 순수 헬퍼를 빌려 씀) | 자체 + 로그 파일 열기 / `PyFluent` | `PyFluentVariableLoader`, `QProcess`(+stdin CANCEL), Fluent 자식 프로세스 |
| JSON 생성기 (v2.0 개명, 구 boundary_conditions.json) | `BCJsonTab` | 자체 / `BC-JSON` | 없음 |

## 10. 시험 기록
- **[v1.7]** `tests/headless/gui_headless_test_v17.py` 27/28 (2026-10-03, 1건은 시험 기준 오류 — `docs/verification/v17-decision004.md` §4): 탭 4개·변환기 탭 불변, 한글 경로 + Workbench dat 이름에서 변수 로드 44 s, 포맷 전환 체크 유지, VTU 배치(성공 1/dat 없음 실패 1), `CANCEL` 중단 8 s 뒤 Fluent 잔존 0, 로더 중 shutdown 12 s 뒤 잔존 0. `pyfluent_mesh_selftest.py` 0 failure. v16 회귀 21/21.
- **[v1.6]** `tests/headless/gui_headless_test_v16.py` 21/21 (2026-10-03): 엔진 라디오 2개·경계 위젯 없음, 스캔이 `.cff_link_*` 제외, Workbench 식 이름(`dp_007-0100.dat.h5`)에서 변수 12개 로드·링크 폴더 정리, 포맷 전환 시 체크 유지, 배치 인자에 `--engine` 없음, dat 없는 케이스 실패 집계(1/1), `Results.vtu` 표시명, ParaView 엔진도 링크 경로로 성공·정리, 실제 Workbench 원본 39개 로드·정리, dp 변환 중 중단 시 워커 종료·링크 폴더 정리.
- v1.5(32/32)·v1.4(29/29) 기록은 git 이력.
