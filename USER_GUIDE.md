# Fluent CFF 유틸리티 — 사용 가이드 (v2.1)

ANSYS Fluent 결과를 정리하고 VTK 파일로 바꾸는 앱입니다. 탭 네 개를 **왼쪽부터 순서대로** 쓰면 됩니다.

```
Workbench 결과 폴더 ──▶ [1] Workbench DP 정리 ──▶ dp_001.cas.h5 / dp_001.dat.h5
                                                   │
                     ┌──────────────────────────────┴──────────────────────────────┐
                     ▼                                                              ▼
            [2] PyVista 변환기  (빠름, 라이선스 불필요)              [3] PyFluent 변환기  (Fluent 필요, 경계면 구분)
                     │  Design_001/Results.vtu  (Results.vtp)                       │
                     └──────────────────────────────┬──────────────────────────────┘
                                                    ▼
                                      [4] JSON 생성기  ──▶ Design_001/boundary_conditions.json
```

## 목차
1. [설치와 실행](#1-설치와-실행)
2. [화면 공통](#2-화면-공통)
3. [Workbench DP 정리](#3-workbench-dp-정리)
4. [PyVista 변환기](#4-pyvista-변환기)
5. [PyFluent 변환기](#5-pyfluent-변환기)
6. [JSON 생성기](#6-json-생성기)
7. [문제 해결](#7-문제-해결)
- [부록 A. 명령줄 실행](#부록-a-명령줄-실행)
- [부록 B. 버전 이력](#부록-b-버전-이력)

---

## 1. 설치와 실행

### 1.1 한 번에 설치하고 실행하기
`setup_and_run.bat` 를 더블클릭합니다.

| 단계 | 하는 일 |
|---|---|
| [1/4] | 가상환경 생성 (`D:\Venvs_collec\CFF2VTK_venv\venv`, 이미 있으면 건너뜀) |
| [2/4] | `requirements.txt` 설치 (PySide6, pyvista, ansys-fluent-core) |
| [3/4] | 모듈 점검. `ansys-fluent-core` 가 안 되면 경고만 띄우고 PyFluent 변환기 탭만 비활성 |
| [4/4] | 앱 실행 |

두 번째부터는 같은 `.bat` 를 실행하면 바로 앱이 뜹니다.

### 1.2 직접 설치하기
```bash
pip install -r requirements.txt
python pv_export_gui.py
```
`pvpython` 이 아니라 **일반 `python`** 으로 실행합니다. 모든 `.py` 파일은 같은 폴더에 있어야 합니다.

### 1.3 탭별로 추가로 필요한 것

| 탭 | 추가 요구사항 |
|---|---|
| Workbench DP 정리, JSON 생성기 | 없음 |
| PyVista 변환기 | 없음. **ParaView 엔진**을 고를 때만 [ParaView 6.1](https://www.paraview.org/download/) 설치 (`pvpython.exe` 자동 탐지) |
| PyFluent 변환기 | **Ansys Fluent 설치**(환경변수 `AWP_ROOTnnn` 으로 찾음, 여러 버전이면 가장 높은 것) + **솔버 라이선스 1석** |

> ParaView 를 받은 뒤 "ModuleNotFoundError" 가 나면 Windows 가 파일을 차단한 것입니다. 관리자 PowerShell 에서
> `Get-ChildItem "C:\Program Files\ParaView 6.1.0" -Recurse | Unblock-File` 을 실행하세요.

---

## 2. 화면 공통

- 밝은 **Solarized Light** 테마입니다. 창 크기는 화면에 맞춰 자동으로 정해지고, 작은 화면(노트북 125~150 %)에서는 탭 안에 세로 스크롤이 생깁니다.
- 두 변환기 탭은 **2단**입니다. 왼쪽 열 1 → 2 → 4 번 그룹을 채우고, 오른쪽 열 3 번에서 변수를 고른 뒤 **[변환 실행]** 을 누릅니다. 진행바와 [중단] 은 그 바로 아래, 콘솔은 맨 아래 전폭입니다.
- **콘솔**: 오류는 빨강, 주의는 주황, 완료는 초록으로 표시됩니다. 같은 내용이 `logs/pv_export_<시각>.log` 에 실시간 기록되고, 콘솔 위의 [로그 열기]·[폴더 열기]로 바로 볼 수 있습니다. 로그 줄의 태그는 `DP정리` / `변환` / `PyFluent` / `BC-JSON` 입니다.
- 상태 글자색: 초록 = 정상, 주황 = 확인 필요, 빨강 = 오류.
- 변환 중에는 엔진·포맷·변수 선택이 잠기고, 끝나거나 중단하면 풀립니다. 이미 끝난 파일은 중단해도 남습니다.

---

## 3. Workbench DP 정리

**언제 쓰나** — Workbench 파라메트릭 결과는 `…_files/dp1/FFF/Fluent/FFF.27-3.cas.h5` + `FFF.27-3-1200.dat.h5` 처럼 흩어져 있어 파일명만으로는 어느 설계점인지 알 수 없습니다. 이 탭이 `dp_001.cas.h5` + `dp_001.dat.h5` 로 복사해 모아 줍니다. 원본은 건드리지 않습니다.

**순서**
1. **입력 폴더**: `dp0, dp1 …` 폴더가 들어 있는 상위 폴더를 고르고 [스캔]. 표에 DP / Case / Data / 반복횟수 / 상태가 나옵니다. Data 가 여러 개면 반복횟수가 가장 큰 것을 자동으로 고릅니다.
2. **이름 규칙**: 기본은 `dp1 → dp_001`(3자리). 접두사·접미사를 넣으면 미리보기에 바로 반영됩니다.
3. **출력 설정**: 출력 폴더, 저장 구조(`dp_001/dp_001.cas.h5` 이름별 폴더 또는 한 폴더에 모두), 이미 있는 파일 건너뛰기(이어하기).
4. **[수집·이름변경 실행]**: 체크된 DP 만 복사합니다. 실행 전에 예상 용량과 디스크 여유를 확인합니다.

**결과 확인** — 출력 폴더에 `dp_collect_<시각>.csv`(원본↔변경 전체 목록)와 `.txt`(요약)가 생깁니다.

| 상태 | 뜻 |
|---|---|
| 정상 | Case + Data 모두 있음 (기본 선택) |
| Data 없음 / Case 없음 | 한쪽만 있음 (기본 미선택, 필요하면 체크) |
| 결과 없음 | 둘 다 없음 (선택 불가) |

> 변환기 탭은 `FFF.3-2-11200.dat.h5` 같은 Workbench 원본 이름도 그대로 읽습니다. 그래도 이 탭을 거치면 **파일명의 dp 번호가 출력 폴더 번호로 이어지므로**(`dp_016` → `Design_016`) 설계 번호 관리가 쉬워집니다.

---

## 4. PyVista 변환기

**언제 쓰나** — CFF 결과를 `Design_NNN/Results.vtu`(체적) 또는 `Results.vtp`(외곽 표면)로 **대량 변환**할 때. 라이선스가 필요 없고 파일당 수 초~십여 초입니다. Stochos 학습 입력은 이 탭의 **PyVista + VTU** 가 기본입니다.

### 4.1 순서
1. **변환 엔진**: **PyVista**(기본) 또는 **ParaView**. ParaView 를 고르면 pvpython 경로 행이 나타납니다(자동 탐지, 필요하면 [찾아보기]).
2. **입력 폴더**: [폴더 선택] → 하위 폴더까지 `.cas.h5` 를 모두 찾아 목록에 보여 줍니다.
3. **저장할 변수 선택**: [첫 파일로 변수 불러오기] → 체크박스 목록이 뜹니다(파란 글씨 = 선택됨). 첫 파일 기준으로 고른 변수가 모든 파일에 적용됩니다. 필요한 변수만 고르면 메모리와 시간이 줄어듭니다.
4. **출력 설정**

   | 항목 | 설명 |
   |---|---|
   | 포맷 | **VTU** 체적 단일 격자(기본) / **VTP** 외곽 표면 1장(PyVista 엔진만) |
   | 폴더명 | 접두사(기본 `Design`) + 번호 → `Design_001`. 파일명에 dp 번호가 있으면 그 번호(`dp_016` → `Design_016`). 비우면 `<파일명>_export` |
   | 출력 위치 | 입력 파일과 같은 폴더 / 지정 폴더에 모아서 |
   | 변수명 | **Fluent 표시명으로 저장**(기본 켜짐): `SV_P → pressure`, `SV_T → temperature` …. 끄면 `SV_*` 원본 이름 |

5. **[변환 실행]** → 확인창(파일 수, 덮어쓰기 개수, dat 없는 케이스 수) → 순서대로 변환. **[중단]** 은 현재 파일 뒤에 멈추고 완료된 파일은 남습니다.

### 4.2 결과
- `Design_001/Results.vtu` (또는 `Results.vtp`). 두 포맷은 같은 폴더에 공존할 수 있습니다.
- 값은 Fluent 원본 그대로 **Cell Data**(셀 중심)입니다. ParaView 에서 부드러운 컨투어가 필요하면 `Cell Data to Point Data` 필터를 쓰세요.
- ParaView 에서 File → Open 으로 `Results.vtu` 를 열면 됩니다.

### 4.3 알아 둘 것

| 항목 | 내용 |
|---|---|
| 엔진 차이 | 두 엔진의 VTU 값은 같습니다. PyVista 는 pip 만으로 동작하고 VTP 도 만들며 파일이 절반 크기(압축)입니다. ParaView 엔진이 더 빠릅니다(대형 케이스 3 s vs 14 s). VTP 는 PyVista 만 |
| 변수 이름 | 체크박스는 Fluent 원본 이름(`SV_P` 정압, `SV_U/V/W` 속도 성분, `SV_T` 온도, `SV_K` 난류 운동에너지 …). 케이스마다 다르고, Fluent 가 `.dat.h5` 에 저장한 것만 나옵니다 |
| 데이터 파일 | 케이스와 같은 폴더의 `<이름>.dat.h5`, 없으면 `<이름>-<반복횟수>.dat.h5` 중 가장 큰 것. Workbench 원본 이름은 임시 하드링크 폴더(`.cff_link_*_tmp`)로 읽고 끝나면 지웁니다. **dat 가 없으면 그 파일은 실패**로 집계됩니다 |
| `velocity` 벡터 | 이 엔진의 `velocity` 는 `SV_BF_V` 에서 만들며 확인한 샘플에서는 **0 벡터**였습니다. 실제 속도 벡터가 필요하면 PyFluent 변환기를 쓰세요 |
| 학습 세트 | 한 학습 세트 안에서는 변수명 방식(표시명/원본)을 통일하고, PyFluent 변환기 결과와 섞지 마세요(셀 순서가 다름) |

---

## 5. PyFluent 변환기

**언제 쓰나**

| 필요한 것 | 쓰는 탭 |
|---|---|
| `Results.vtu` 대량 변환 | PyVista 변환기 (빠름, 라이선스 불필요) |
| **경계(inlet/outlet/wall …)별로 구분되는 표면** | **PyFluent 변환기 + VTP** — 경계면 전부가 한 파일에 들어가고 `boundary_id` 로 구분 |
| Fluent 가 계산한 격자·값 그대로 (Fluent 자체 부피와 대조) | PyFluent 변환기 |
| 실제 속도 벡터 `velocity` | PyFluent 변환기 (`SV_U/V/W` 로 조립) |

배치를 시작하면 창 없는 Fluent 를 **한 번만** 띄우고(30–45 s) 케이스를 차례로 읽어 변환합니다(케이스당 20 s–1분, Cyclone 급 40만 셀 기준 약 1분). 2D 와 3D 케이스가 섞여 있으면 그때만 다시 띄웁니다. 배치 동안 라이선스 1석을 씁니다.

### 5.1 순서
1. **Fluent 환경**: 상태 줄이 초록이면 준비된 것입니다(`ansys-fluent-core … 감지됨 · Fluent v261 …`). 주황이면 [7장](#7-문제-해결)을 보세요. **Fluent 프로세스 수**는 1 로 두세요(올려도 빨라지지 않고 셀 순서만 바뀝니다).
2. **입력 폴더**: PyVista 변환기와 같습니다.
3. **저장할 변수 선택**: [첫 파일로 변수 불러오기 (Fluent 기동, 1–2분)]. 목록은 **포맷에 따라 다릅니다**. VTU 는 셀 변수(`SV_P`, `SV_T`, `SV_U/V/W` …), VTP 는 경계면 변수(`SV_P`, `SV_WALL_SHEAR`, `SV_WALL_YPLUS` …)와 경계 목록이 나옵니다. 포맷을 바꿔도 같은 이름의 체크는 유지됩니다.
4. **출력 설정**: PyVista 변환기와 같습니다. `SV_U`, `SV_V`, `SV_W` 를 모두 체크하면 3성분 벡터 `velocity` 가 추가됩니다.
5. **[변환 실행]** → 확인창 → 워커 하나가 Fluent 를 띄우고 케이스를 차례로 변환합니다. 콘솔에 케이스마다 `[i/n] 이름 → 폴더` 와 ✓/✗ 가 찍힙니다. dat 가 없는 케이스는 ✗ 로 건너뛰고 다음 케이스를 계속합니다. **[중단]** 을 누르면 현재 케이스에서 멈추고 Fluent 세션을 정상 종료합니다(보통 수 초, 늦어도 30 초 뒤 강제 종료). 앱을 닫아도 같은 정리를 합니다.

### 5.2 결과

| 포맷 | 내용 |
|---|---|
| **VTU** | Fluent 셀 존을 다시 조립한 체적 격자(hex/tet/pyramid/wedge/다면체). Cell Data. 콘솔의 `[VERIFY] … SV_VOLUME 대비 상대오차 …` 가 매우 작고 음수 부피 0 이면 정상 |
| **VTP** | `interior` 를 뺀 **모든 경계면을 한 장**으로. Cell Data(면 중심) + `boundary_id`(각 면의 Fluent 존 번호) + Field Data `boundary_names`(이름 목록). 어떤 경계에 없는 변수는 그 경계에서 **NaN** (예: inlet 의 `wall-shear`) |

ParaView 에서 특정 경계만 보려면 **Threshold** 필터 → Scalars `boundary_id` → 번호 범위를 지정합니다. 번호와 이름의 대응은 Information 탭의 `boundary_names` 또는 콘솔 로그에 있습니다.

### 5.3 알아 둘 것
- 데이터 파일 규칙은 PyVista 변환기와 같습니다. Workbench 이름은 Fluent 에 경로를 직접 지정해 읽습니다(임시 폴더 없음). **dat 가 없으면 실패**합니다.
- 케이스 경로에 한글이 있으면 콘솔에 `경로에 비ASCII 문자 → Fluent 용 ASCII 별칭 사용` 이 뜹니다. Fluent 가 한글 경로를 못 열어 임시 별칭으로 읽는 정상 동작입니다.
- 케이스 폴더와 출력 폴더에는 아무것도 남기지 않습니다. Fluent 전사 파일은 `%TEMP%\cff_pyfluent_*` 에만 생겼다가 지워집니다. Fluent 가 끝난 직후에는 그 파일이 잠시 잠겨 있을 수 있어 콘솔에 `임시 폴더 삭제 보류` 가 뜰 수 있는데, 앱이 1분 간격으로 다시 지우고 그래도 남으면 다음 실행 때 자동 정리됩니다.
- PyVista 변환기와 **폴더 규칙·배열 이름은 같지만 셀 순서와 `velocity` 정의가 다릅니다.** 한 학습 세트에 두 탭 결과를 섞지 마세요.

---

## 6. JSON 생성기

**언제 쓰나** — Stochos 학습에 쓰려면 설계 폴더마다 전역 파라미터 JSON(`boundary_conditions.json`)이 필요합니다. 설계 테이블 CSV 한 장으로 모든 `Design_NNN/` 에 만들어 넣습니다.

### 6.1 CSV 준비
탭 맨 위의 **[작성 방법 자세히]** 에 같은 안내가 있고, **[예시 CSV 저장…]** 으로 아래 형식의 `Parameters_example.csv` 를 받을 수 있습니다. 엑셀로 열어 값을 채운 뒤 **"CSV UTF-8(쉼표로 분리)"** 로 저장하세요.

```
Name,inlet_length,cone_length,vortex_finder_length
DP 0,150,0.36,280
DP 1,238.95,0.09035,60.15
DP 2,84.25,0.39125,306.65
```

| 규칙 | 설명 |
|---|---|
| 첫 행 | 열 이름. 구분자는 콤마·세미콜론·탭 중 하나 (자동 감지) |
| 첫 열 | 설계 번호. 열 이름 `Name` 또는 `#`, 값은 `DP 0`, `DP 1` … 또는 `0`, `1` …. 설계 폴더 `Design_000` … 과 **번호**로 짝을 맞춤 |
| 나머지 열 | 파라미터. **열 이름이 그대로 JSON 키**, **열 순서가 키 순서**(= Stochos 피처 순서). 영문·숫자·밑줄만, 단위는 쓰지 않음 |
| 값 | 숫자만. 빈 칸·문자가 있으면 그 설계는 "값 변환 실패"로 건너뜀 |
| 인코딩 | UTF-8(BOM 허용), 한글 Windows(cp949) 모두 가능 |

Workbench Parameter Table 을 Export 한 CSV(`# ` 주석 + `Name,P1,P2,…`)도 그대로 읽습니다. 이때 키는 주석에 적힌 이름(`Inlet_length` …)입니다.

### 6.2 순서
1. **설계 테이블 CSV**: [찾아보기].
2. **설계 폴더 루트**: `Design_000 …` 이 들어 있는 폴더(보통 변환기 탭의 출력 폴더).
3. **옵션**(필요할 때만): JSON 파일명(기본 `boundary_conditions.json`, Stochos 가 이 이름을 읽으므로 유지 권장), 설계번호 열(자동), 구분자(자동), 오프셋(폴더 번호 = CSV 번호 + 오프셋), 사이드카.
4. **파라미터 매핑 (선택)**: **비워 두면 CSV 열 이름을 그대로 키로 씁니다.** 다른 키 이름을 쓰거나 일부 열만 내보낼 때만 한 줄에 하나씩 `json_key = CSV열` 로 적습니다. 적은 순서가 키 순서입니다.
5. **[미리보기(DRY-RUN)]**: 파일을 만들지 않고 요약을 보여 줍니다 — 생성 대상 / 폴더 없음(CSV에만) / CSV 없음(폴더에만) / 값 변환 실패 / JSON 키. "폴더 없음"이 많으면 오프셋이 어긋난 것입니다.
6. **[JSON 생성]**: 각 설계 폴더에 `boundary_conditions.json`(+ `design_info.json` 사이드카)을 씁니다. 기존 파일은 덮어씁니다.

### 6.3 앱이 지키는 규칙
- 키 순서 = CSV 열 순서(또는 매핑 순서). 학습 세트 안에서 바꾸지 마세요.
- `boundary_conditions.json` 에는 파라미터 키만 들어가고, 메타데이터는 `design_info.json` 에만 들어갑니다.
- 값은 숫자(float)만. `nan`/`inf` 는 거부됩니다.
- 일부 폴더만 생성되면 "쓰기 실패(부분 생성됨)" 경고가 뜹니다. 그 상태로 학습하지 마세요.
- 키 이름이 다른 세트(예: `inlet_length` 와 `Inlet_length`)를 한 학습에 섞지 마세요.

---

## 7. 문제 해결

### 7.1 공통·PyVista 변환기

| 증상 | 원인 → 해결 |
|---|---|
| 앱이 안 뜸 / PySide6 오류 | 의존성 미설치 → `setup_and_run.bat` 다시 실행 또는 `pip install -r requirements.txt` |
| `.cas.h5 파일을 찾지 못했습니다` | 폴더에 CFF 가 없거나 구형 `.cas/.dat` 만 있음 → Fluent 에서 `/file/write-case-data 이름.cas.h5` 로 재저장 |
| 변수 0개 / `데이터 파일(.dat.h5) 없음` | dat 가 없거나 이름 규칙(`<이름>.dat.h5`, `<이름>-<n>.dat.h5`)이 다름 → dat 를 같은 폴더에 두거나 DP 정리 탭으로 이름 통일 |
| `pvpython을 찾지 못했습니다` | ParaView 자동 탐지 실패 → [찾아보기]로 `…\ParaView 6.1.0\bin\pvpython.exe` 지정 |
| ParaView 엔진에서 `ModuleNotFoundError` | Windows 가 ParaView 파일 차단 → 관리자 PowerShell 에서 `Unblock-File` ([1.3](#13-탭별로-추가로-필요한-것)) |
| PyVista 라디오가 비활성 | pyvista 없음 → `pip install pyvista` |
| 포맷 라디오가 회색 | 그 엔진이 지원하지 않는 조합(ParaView + VTP) → VTP 는 PyVista 엔진 |
| `변수 목록이 ○○ 엔진 것이 아닙니다` | 변수를 불러온 뒤 엔진을 바꿈 → [첫 파일로 변수 불러오기] 다시 |
| 일부 파일만 실패 | 그 파일의 손상·결과 없음 → 콘솔의 실패 파일명 확인. 나머지는 정상 변환됨 |
| 변수가 `pressure` 로 나오는데 `SV_P` 가 필요 (또는 반대) | "Fluent 표시명으로 저장" 옵션 → 끄면 원본 이름. 한 세트 안에서는 한 방식만 |
| 케이스 폴더에 `.cff_link_*_tmp` 가 남음 | 변환 중 강제 종료 → 지워도 됨. 다음 실행 때 자동 정리 |
| 대형 케이스에서 PyVista 가 느림 | 저장 압축 때문 → 변수를 필요한 것만 선택, 또는 ParaView 엔진 |

### 7.2 PyFluent 변환기

| 증상 | 원인 → 해결 |
|---|---|
| 상태 줄 주황 `ansys-fluent-core 없음` | 패키지 미설치 → `setup_and_run.bat` 다시 실행 (또는 `pip install "ansys-fluent-core[reader]"`) |
| `Fluent 설치를 찾지 못함 (AWP_ROOTnnn …)` | Fluent 미설치 또는 환경변수 없음 → 시스템 환경변수 `AWP_ROOT261`(버전에 맞게) = `…\ANSYS Inc\v261` 추가 후 앱 재실행 |
| 라이선스 오류(콘솔에 license / checkout) | 석 부족, 라이선스 서버·VPN 연결 → 다른 Fluent/Workbench 종료, 서버 연결 확인 |
| 변수 불러오기 10분 뒤 "시간 초과" / 기동이 매우 느림 | Fluent 기동 지연(백신 실시간 검사, VPN) → 콘솔 마지막 줄 확인, Fluent 폴더·`%TEMP%` 백신 예외, 재시도 |
| 작업 관리자에 `cx2610.exe` / `fl2610.exe` 가 남음 | 파이썬을 강제 종료함 → 아래 명령으로 정리 (버전 숫자는 Fluent 버전에 따라 다름) |
| VTP 의 `wall-shear` 가 inlet/outlet 에서 NaN | 그 경계에 없는 변수 (정상) → `boundary_id` 로 wall 만 Threshold |
| PyVista 변환기 결과와 셀 순서·`velocity` 가 다름 | 엔진 차이 (정상) → 한 학습 세트에 섞지 않기 |
| `%TEMP%\cff_pyfluent_*` 폴더가 남아 있음 | Fluent 가 전사 파일을 잠시 잡고 있었거나 앱을 강제로 끝냄 → 지워도 됨. 다음 실행 때 10분 지난 폴더는 자동 정리 |

```powershell
tasklist | findstr /i "cx2610 fl2610 fluent"
taskkill /PID <번호> /T /F      # 변환이 끝났는데도 남은 것만
```

### 7.3 JSON 생성기

| 증상 | 원인 → 해결 |
|---|---|
| `헤더 행을 찾지 못했습니다` | 첫 행에 구분자가 없음 → CSV 형식 확인([6.1](#61-csv-준비)), 또는 옵션의 구분자를 직접 지정 |
| `설계 번호 열을 찾지 못했습니다` | 첫 열 이름이 `Name`/`#` 이 아님 → 옵션 "설계번호 열"에 실제 열 이름 입력 |
| "폴더 없음(CSV에만)" 이 많음 | CSV 번호와 폴더 번호가 어긋남(`DP 0` ↔ `Design_001`) → 오프셋 +1 또는 −1 |
| "값 변환 실패" | 셀에 문자·빈 칸 → CSV 수정 |
| 모든 열이 키로 들어가 버림 | 자동 모드는 설계번호·출력(`_op`)·숫자 아닌 열만 뺌 → 일부 열만 원하면 파라미터 매핑에 적기 |

### 7.4 자주 묻는 질문
- **100개 변환에 얼마나 걸리나요?** PyVista 변환기는 파일당 수 초~십여 초(100개 10~20분). PyFluent 변환기는 Fluent 기동 1분 + 케이스당 20 s–1분.
- **변환 중 중단하면?** 완료된 파일은 남고 현재 파일에서 멈춥니다. PyFluent 는 Fluent 도 함께 종료됩니다.
- **파일마다 변수가 다르면?** 첫 파일 기준 선택을 모든 파일에 적용하고, 없는 변수는 그 파일에서 건너뜁니다.
- **Point Data 로 저장되나요?** 아니요, Cell Data 만. 필요하면 ParaView 의 `Cell Data to Point Data`.
- **구형 `.cas/.dat` 도 되나요?** 아니요. Fluent 에서 CFF(`.cas.h5`)로 재저장하세요.
- **경계별로 파일을 나눠 주나요?** PyFluent VTP 는 한 장에 모두 넣고 `boundary_id` 로 구분합니다. 나누려면 ParaView 에서 Threshold 후 저장.

---

## 부록 A. 명령줄 실행

워커는 GUI 없이도 실행할 수 있습니다 (자동화용). 종료코드 0 = 성공(`[SUCCESS]`), 1 = 실패(`[ERROR] …`). `--vars` 는 항상 원본 이름 `SV_*`, `--rename` 을 주면 표시명으로 저장. 프로토콜은 `docs/worker-protocol.md`.

```bash
# PyVista 워커 (GUI 와 같은 python)
python cff_export_worker.py --case dp_001.cas.h5 --list-json
python cff_export_worker.py --case dp_001.cas.h5 --output Design_001/Results.vtu --vars SV_P,SV_T --rename
python cff_export_worker.py --case dp_001.cas.h5 --output Design_001/Results.vtp --vars SV_P --rename

# ParaView 워커 (pvpython). VTM 은 여기서만 가능
"C:/Program Files/ParaView 6.1.0/bin/pvpython.exe" pv_export_worker.py --case dp_001.cas.h5 --output Design_001/Results.vtu --vars SV_P,SV_T --rename
"C:/Program Files/ParaView 6.1.0/bin/pvpython.exe" pv_export_worker.py --case dp_001.cas.h5 --output Design_001.vtm --format vtm --all --inner-name Results

# PyFluent 워커 (Fluent 설치·라이선스 필요). SV_U,SV_V,SV_W 를 모두 주면 velocity 벡터 추가
python pyfluent_export_worker.py --case box.cas.h5 --list-json
python pyfluent_export_worker.py --case box.cas.h5 --output Design_001/Results.vtu --vars SV_P,SV_T,SV_U,SV_V,SV_W --rename
python pyfluent_export_worker.py --case box.cas.h5 --output Design_001/Results.vtp --vars SV_P,SV_WALL_SHEAR --rename
#   그 밖에 --processors N, --fluent-version 26.1.0, --ascii, --all, --surfaces a,b, --no-check. 실행 중 stdin 에 CANCEL 한 줄 → Fluent 종료 후 종료코드 1

# JSON 생성기 (기본은 DRY-RUN, --execute 로 실제 생성)
python bc_json_gen.py --write-example Parameters_example.csv
python bc_json_gen.py --csv Parameters.csv --root D:/vtu_data --auto-params
python bc_json_gen.py --csv Parameters.csv --root D:/vtu_data --auto-params --offset -1 --execute
python bc_json_gen.py --csv table.csv --root D:/vtu_data --param inlet_length=Inlet_length --param cone_length=Cone_length --execute
```

## 부록 B. 버전 이력

| 버전 | 날짜 | 변경 |
|---|---|---|
| **v2.0** | 2026-10-03 | Solarized Light 테마, 글자 크기·대비 개선, 두 변환기 탭 2단 배치, 탭 이름 변경(PyVista 변환기 / PyFluent 변환기 / JSON 생성기), 시작 창 크기 자동·작은 화면 스크롤, 콘솔 로그 색. JSON 생성기: `Parameters.csv` 형식(열 이름 = 키) 자동 모드, 매핑 선택화, 기준설계 직접 입력 제거, 예시 CSV·작성 안내. 코드·파일 정리 |
| **v2.1** | 2026-10-03 | PyFluent 변환기 배치가 Fluent 를 **배치당 한 번만** 띄움(결정 005). 케이스당 35–40 s 절감, 실패 케이스는 건너뛰고 계속 |
| v1.7 | 2026-10-03 | PyFluent 변환 탭 추가 (헤드리스 Fluent, VTU 재구성 / VTP 경계 병합 `boundary_id`, `velocity` 벡터, 협조적 중단) |
| v1.6 | 2026-10-03 | 변환기 탭의 PyFluent 엔진 제거(PyVista·ParaView 2개), Workbench 원본 dat 이름 바로 변환 |
| v1.5 | 2026-10-03 | boundary_conditions.json 을 별도 탭으로 분리, VTM 을 GUI 에서 제외(CLI 전용), 변수 표시명 옵션 |
