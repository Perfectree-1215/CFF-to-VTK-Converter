
---

## 메인 세션 보충 (2026-10-03)

에이전트가 "미검사"로 남긴 4건은 메인 세션에서 같은 인터프리터로 직접 확인했다.

| 항목 | 실제 | 판정 |
|---|---|---|
| box PyVista VTP | `--vars SV_P` 만 주면 `{SV_P}` 가 맞다(표시명은 `--rename` 일 때만). 판정 기준 문구를 `--rename` 포함으로 정정. `--rename` 시 `{pressure}` 는 v1.5 검증(`box-v15-decision002.md`)과 동일 경로 | 통과 |
| nodat 변환 (`--all`) | PyVista·ParaView 모두 `[ERROR] … 데이터 파일(.dat.h5)이 없습니다 …` 1줄, 종료코드 1, 출력 파일 없음 | 통과 |
| Cyclone 원본 `FFF.3-2.cas.h5` `--list-json` | `cell_arrays` 39개, `n_cells` 394,817, 로그 `임시 하드링크로 연결` | 통과 |
| `--engine pyfluent` 회귀 | `error: unrecognized arguments: --engine pyfluent`, 종료코드 2 | 통과 |
| GUI 헤드리스 (`tests/headless/gui_headless_test_v16.py`) | 21/21 — 스캔 제외, 로드·완료·중단 뒤 링크 폴더 없음, `--engine` 미전송, 포맷 전환 시 체크 유지, dat 없는 케이스 1/1 실패 집계, ParaView 경로 동일 | 통과 |

**최종 판정: 결정 003 §5 전 항목 통과.**
