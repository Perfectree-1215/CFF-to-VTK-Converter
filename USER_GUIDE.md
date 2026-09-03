# Fluent CFF 유틸리티 — 사용 가이드

> ANSYS Fluent 결과를 다루는 두 도구를 상단 **탭**으로 묶은 데스크톱 앱

## 이 앱의 구성 (탭)

앱 상단에 두 개의 탭이 있으며 클릭으로 전환합니다.

| 탭 | 하는 일 | ParaView 필요? |
|---|---|---|
| **Workbench DP 정리** | Design Point별 Case/Data를 DP 이름으로 복사·이름변경 | ❌ 불필요 (순수 파이썬) |
| **CFF to VTM/VTU** | CFF 결과(`.cas.h5`/`.dat.h5`)를 VTM/VTU로 일괄 변환 | ✅ 필요 (pvpython) |

이 가이드의 2~11장은 **CFF to VTM/VTU** 탭을, [12장](#12-workbench-dp-정리-탭)은 **Workbench DP 정리** 탭을 설명합니다.
두 탭은 연계됩니다 — DP 정리로 만든 `dp_001.cas.h5`/`dp_001.dat.h5`를 변환 탭에 바로 넣을 수 있습니다.

---

> 아래부터는 **CFF to VTM/VTU** 탭 설명입니다.

## 목차
- [1. 이 앱이 하는 일](#1-이-앱이-하는-일)
- [2. 필수 요구사항](#2-필수-요구사항)
- [3. 설치](#3-설치)
- [4. ParaView를 통해 Export되는 내용](#4-paraview를-통해-export되는-내용)
- [5. 앱 실행](#5-앱-실행)
- [6. 화면 구성과 각 항목 설명](#6-화면-구성과-각-항목-설명)
- [7. 단계별 사용법](#7-단계별-사용법)
- [8. VTM vs VTU 선택 가이드](#8-vtm-vs-vtu-선택-가이드)
- [9. 출력 파일 구조](#9-출력-파일-구조)
- [10. 트러블슈팅](#10-트러블슈팅)
- [11. 자주 묻는 질문](#11-자주-묻는-질문)
- [12. Workbench DP 정리 탭](#12-workbench-dp-정리-탭)
- [13. boundary_conditions.json 생성 (Stochos DIM-GP 학습용)](#13-boundary_conditionsjson-생성-stochos-dim-gp-학습용)

---

## 1. 이 앱이 하는 일

ANSYS Fluent로 계산한 결과(CFF 포맷)를 **ParaView가 읽을 수 있는 VTK 포맷(VTM/VTU)으로 일괄 변환**합니다.

```
[Fluent 결과]              [이 앱]                  [변환 결과]
FFF.3-1.cas.h5      →   ParaView로 읽고     →    Design_001.vtm
FFF.3-1.dat.h5          변수 선택 후 저장        (+ Design_001/Results.vtu)
... (100개)         →   순차 배치 처리      →    ... (100개)
```

### 핵심 특징
- 폴더 하나를 지정하면 **하위 폴더까지 모든 CFF 파일을 자동으로 찾아** 일괄 변환
- 100개 이상의 케이스도 순차 처리 (파라미터 스윕 결과 정리에 적합)
- 저장할 변수를 체크박스로 선택 (압력, 속도 등 필요한 것만)
- 변환 중 진행률과 로그를 실시간 확인

---

## 2. 필수 요구사항

이 앱은 **두 가지 실행 환경**을 사용합니다.

| 구성요소 | 요구사항 | 용도 |
|---|---|---|
| **Python** | 3.9 이상 | GUI 실행 |
| **PySide6** | 최신 | GUI 프레임워크 |
| **ParaView** | 6.1.0 (권장) | 실제 변환 엔진 (pvpython 포함) |

### 왜 두 환경이 필요한가?
- **GUI**는 일반 Python(PySide6 설치된 환경)에서 실행됩니다
- **변환 작업**은 ParaView에 내장된 `pvpython`이 수행합니다
- GUI가 내부적으로 pvpython을 자동 호출하므로, 사용자는 GUI만 실행하면 됩니다

> 💡 ParaView의 pvpython에는 PySide6가 없기 때문에 이렇게 분리되어 있습니다. 사용자는 신경 쓸 필요 없이 일반 Python으로 GUI만 켜면 됩니다.

---

## 3. 설치

### Step 1. ParaView 설치 (이미 있으면 생략)

[ParaView 공식 사이트](https://www.paraview.org/download/)에서 6.1.0 다운로드 후 설치.

일반적인 설치 경로:
```
C:\Program Files\ParaView 6.1.0\bin\pvpython.exe
```

> ⚠️ **Windows 보안 차단 주의**: 다운로드한 ParaView는 Windows가 일부 파일(`.pyd`)을 차단할 수 있습니다. (차단 시 관리자 PowerShell 또는 CMD 실행)


### Step 2. Python 의존성 설치

명령 프롬프트(또는 venv 활성화 상태)에서 프로젝트 폴더의 `requirements.txt`로 설치합니다:
```bash
pip install -r requirements.txt
```

> 💡 `requirements.txt`에는 GUI 실행에 필요한 PySide6가 들어 있습니다. ParaView는 pip로 설치되지 않으므로 Step 1에서 별도로 설치해야 합니다.

### Step 3. 앱 파일 배치

파일들을 **같은 폴더**에 둡니다:
```
내_작업폴더/
├── pv_export_gui.py       ← GUI (메인, 두 탭)
├── dp_collect_tab.py      ← "Workbench DP 정리" 탭
└── pv_export_worker.py    ← 변환 워커 (pvpython)
```

> ⚠️ 세 파일이 같은 폴더에 있어야 합니다. GUI가 같은 폴더의 워커를 자동으로 찾습니다.

---

## 4. ParaView를 통해 Export되는 내용

### 변환 과정 (내부 동작)

이 앱은 ParaView에서 다음 작업을 자동으로 수행합니다. GUI에서 수동으로 하던 작업을 코드화한 것입니다.

```
1. CFF 파일 열기 (FLUENTCFFReader)
   - .cas.h5 (메시) + .dat.h5 (결과) 자동 로드
   - 모든 cell zone 활성화

2. VTM 선택 시 Multi-Block 유지 (Default)

3. VTU 선택 시 Merge Blocks 필터 적용
   - Fluent의 multi-block 구조(interior-fluid, inlet, outlet, wall 등)를
     단일 unstructured grid로 병합

4. Save Data
   - 포맷: VTK Multi-Block(.vtm) 또는 VTK Unstructured Grid(.vtu)
   - Data Selection: 선택한 Cell Data 변수만 저장
```

### 저장되는 데이터: Cell Data

Fluent 결과는 **셀 중심(Cell Data)** 으로 저장됩니다. 이 앱은 원본 그대로 Cell Data를 보존합니다 (보간 없음).

> 💡 Cell Data는 각 셀(요소)이 단일 값을 가지는 방식입니다. 정량 분석에 정확합니다. ParaView에서 부드러운 컨투어를 원하면 `Cell Data to Point Data` 필터를 적용하면 됩니다.

### 변환 가능한 변수 (예시)

ParaView의 CFF reader가 인식하는 Fluent 변수들입니다. 변수명은 `SV_` 접두사를 사용합니다.

| 변수명 | 의미 | 분류 |
|---|---|---|
| `SV_P` | 정압 (Static Pressure) | 기본 유동장 |
| `SV_U`, `SV_V`, `SV_W` | 속도 x/y/z 성분 | 기본 유동장 |
| `SV_DENSITY`, `SV_D` | 밀도 | 기본 유동장 |
| `SV_K` | 난류 운동에너지 | 난류 |
| `SV_MU_LAM` | 층류 점도 | 점성 |
| `SV_MU_T` | 난류 점도 | 난류 |
| `SV_P_MEAN`, `SV_P_RMS` | 압력 평균/변동 | 통계(transient) |
| `SV_U_MEAN`, `SV_V_MEAN`, `SV_W_MEAN` | 속도 평균 | 통계 |
| `SV_RUU`, `SV_RVV`, `SV_RWW` | 레이놀즈 수직응력 | 난류 응력 |
| `SV_RUV`, `SV_RUW`, `SV_RVW` | 레이놀즈 전단응력 | 난류 응력 |
| `*_RG_AUX` | gradient reconstruction 보조량 | 보통 시각화 불필요 |

> 💡 실제 사용 가능한 변수는 케이스마다 다릅니다. 앱에서 "첫 파일로 변수 불러오기"를 누르면 해당 결과의 실제 변수 목록이 표시됩니다.

> ⚠️ **변수 개수 참고**: ParaView CFF reader가 보여주는 변수는 Fluent가 `.dat.h5`에 저장한 것만입니다. Fluent GUI에서 즉석 계산되는 일부 파생 변수(total pressure, vorticity 등)는 저장되지 않았다면 나타나지 않습니다. 필요하면 Fluent에서 결과 저장 시 해당 변수를 포함시키세요.

---

## 5. 앱 실행

명령 프롬프트에서 **일반 python**으로 GUI를 실행합니다:

```bash
python pv_export_gui.py
```

> ⚠️ **중요**: `pvpython`이 아니라 **`python`** 으로 실행합니다. (pvpython은 GUI가 내부적으로 자동 호출)

실행하면 다크 테마의 GUI 창이 열립니다.

---

## 6. 화면 구성과 각 항목 설명

앱은 위에서 아래로 7개 영역으로 구성됩니다.

### 1. ParaView 실행 파일 (pvpython)

ParaView의 `pvpython.exe` 경로를 지정하는 영역입니다.

| 항목 | 설명 |
|---|---|
| 경로 입력란 | pvpython.exe의 전체 경로 |
| **자동 탐지** 버튼 | `C:\Program Files\ParaView*\bin\pvpython.exe`를 자동으로 찾음 |
| **찾아보기** 버튼 | 수동으로 pvpython.exe 선택 |

> 💡 앱 시작 시 자동으로 탐지를 시도합니다. 경로가 비어 있으면 수동 지정하세요.

### 2. 입력 폴더 (하위 폴더까지 재귀 탐색)

변환할 CFF 파일들이 있는 폴더를 지정하는 영역입니다.

| 항목 | 설명 |
|---|---|
| 폴더 입력란 | CFF 파일이 있는 폴더 경로 |
| **폴더 선택** 버튼 | 폴더 선택 대화상자 (선택 즉시 자동 스캔) |
| **파일 스캔** 버튼 | 폴더를 다시 스캔 |
| 파일 개수 라벨 | "✅ 102개의 CFF 파일 발견" |
| 파일 목록 | 발견된 모든 `.cas.h5` 파일을 상대 경로로 표시 |

> 💡 폴더를 선택하면 **하위 폴더까지 재귀적으로** 모든 `.cas.h5` 파일을 찾습니다. `run_001/`, `run_002/sub/` 등 어디에 있든 모두 탐색합니다.

### 3. 저장할 변수 선택 (첫 파일 기준, 모든 파일 동일 적용)

변환에 포함할 변수를 체크박스로 선택하는 영역입니다.

| 항목 | 설명 |
|---|---|
| **첫 파일로 변수 불러오기** | 목록의 첫 번째 파일을 분석해 변수 목록 표시 |
| **전체 선택** / **전체 해제** | 모든 체크박스 일괄 토글 |
| 변수 개수 라벨 | "39개 변수" |
| 체크박스 영역 | 변수 목록 (3열). 선택 시 파란색으로 강조 |

> 💡 첫 파일 기준으로 변수를 선택하면 **모든 파일에 동일한 변수 세트**가 적용됩니다. 배치 처리하는 케이스들은 보통 같은 변수 구성을 가지므로 이 방식이 효율적입니다.

### 4. 출력 설정

출력 포맷과 저장 위치를 지정하는 영역입니다.

| 항목 | 설명 |
|---|---|
| **포맷: VTM** (기본) | Multi-Block. Merge Blocks 미적용 (영역 구조 유지) |
| **포맷: VTU** | Unstructured Grid. Merge Blocks 적용 (단일 grid) |
| **폴더명** 입력란 | 출력 폴더 접두사 (기본 `Design`). 변환 순서대로 `Design_001`, `Design_002` … 부여. 비우면 파일명 기반 |
| **출력 위치** 드롭다운 | "입력 파일과 같은 폴더" 또는 "지정 폴더에 모아서 저장" |
| 출력 폴더 입력란 | "지정 폴더" 모드에서만 활성화 |

> 💡 내부 데이터 파일명은 항상 `Results.vtu`로 통일됩니다. 자세한 구조는 [9장](#9-출력-파일-구조) 참고.

### 5. 변환 실행 / 중단

| 항목 | 설명 |
|---|---|
| **변환 실행** 버튼 | 전체 파일 변환 시작 (확인 다이얼로그 표시) |
| **중단** 버튼 | 진행 중인 배치 중단 (변환 중에만 활성화) |
| 전체 진행 라벨 | "전체 진행: 45 / 102 (성공 44, 실패 1) — 현재: ..." |
| 진행률 바 | 전체 파일 대비 완료 비율 |

### 6. boundary_conditions.json 생성 (Stochos DIM-GP · 선택)

변환한 설계 폴더에, Stochos Flow의 DIM-GP 그래프 회귀 학습에 필요한 전역 파라미터 JSON을
**Workbench Parameter Table에서 Export한 전체 DP 테이블 CSV**로부터 자동 생성하는 **선택 기능**입니다.
ParaView와 무관하며, Stochos 학습을 하지 않는다면 이 영역은 무시해도 됩니다.
(자세한 설명은 [13장](#13-boundary_conditionsjson-생성-stochos-dim-gp-학습용))

| 항목 | 설명 |
|---|---|
| **설계 테이블 CSV** | Workbench Parameter Table에서 Export한 전체 DP 테이블 CSV (탭/세미콜론/콤마 구분 자동 감지) |
| **설계 폴더 루트** | `Design_001`, `Design_002` … 설계 폴더들의 부모 폴더 (변환 출력 폴더) |
| **설계 번호 열** | CSV에서 설계 번호가 든 열 이름 (Workbench 포맷은 `Name` 열의 `DP 0`/`DP 1` … 을 자동 인식) |
| **폴더 번호 오프셋** | 폴더 번호 = CSV 번호 + 오프셋 (번호 체계가 어긋날 때 보정) |
| **파라미터 매핑** | `JSON키 = CSV열` 형식(줄당 하나). **이 순서가 학습 입력 피처 순서**가 되므로 바꾸지 말 것 |
| **design_info.json 함께 생성** | 사람용 메타데이터 사이드카 (Stochos는 읽지 않음) |
| **미리보기(DRY-RUN)** 버튼 | 파일을 만들지 않고 매칭 결과/불일치만 확인 |
| **JSON 생성** 버튼 | 실제 생성 (확인 후) |

### 7. 콘솔 출력

각 파일의 변환 로그가 실시간으로 표시됩니다. 파일별 시작/완료/실패와 워커의 상세 로그를 확인할 수 있습니다.
boundary_conditions.json 생성 로그(구분자 감지, 열 매칭, 요약)도 여기에 표시됩니다.

**로그 파일 (실시간 기록)**: 콘솔에 표시되는 모든 줄은 앱 폴더의 `logs/pv_export_<타임스탬프>.log` 파일에도 동시에 기록됩니다(각 줄에 시각·탭 태그 포함). 콘솔 창이 작아 한눈에 보기 어려울 때, 이 파일을 외부 편집기나 뷰어로 열어 스크롤·검색하며 확인하세요.

| 항목 | 설명 |
|---|---|
| **로그 파일** 경로 | 이번 세션의 로그 파일 위치 (앱 시작 시 자동 생성) |
| **로그 열기** 버튼 | 로그 파일을 기본 프로그램으로 엽니다 |
| **폴더 열기** 버튼 | `logs/` 폴더를 엽니다 |

> 💡 **실시간 모니터링 팁**: 로그는 한 줄마다 즉시 기록(flush)되므로, VS Code·Notepad++ 등 자동 새로고침 편집기로 열거나 PowerShell에서 `Get-Content <로그파일> -Wait` 로 tail 하면 변환/생성 진행을 실시간으로 볼 수 있습니다. 두 탭(변환/DP 정리)의 출력이 하나의 세션 로그에 태그와 함께 합쳐집니다.

---

## 7. 단계별 사용법

### 전체 흐름

```
1. 앱 실행 (python pv_export_gui.py)
   → ParaView 경로 자동 탐지됨

2. [폴더 선택] 클릭 → CFF 파일들이 있는 폴더 선택
   → "102개의 CFF 파일 발견" 표시, 목록에 파일 나열

3. [첫 파일로 변수 불러오기] 클릭
   → 잠시 후 변수 체크박스들이 나타남

4. 저장할 변수 체크 (예: SV_P, SV_U, SV_V, SV_W, SV_DENSITY)
   → 선택한 변수가 파란색으로 강조됨

5. 출력 설정
   → 포맷: VTM (기본) 또는 VTU
   → 폴더명 접두사 (기본 Design), 출력 위치: 같은 폴더 (또는 지정 폴더)

6. [변환 실행] 클릭
   → "102개 파일을 변환합니다. 계속?" → [예]
   → 순차 변환 시작, 진행률과 콘솔 로그 표시

7. 완료
   → "변환 완료! 총 102개, 성공 100, 실패 2" 팝업
```

### 실전 예시: 파라미터 스윕 결과 변환

Re 값을 바꿔가며 100개 케이스를 계산했고, 각 결과의 압력/속도장을 ParaView로 보고 싶은 경우:

```
1. 모든 결과가 들어있는 상위 폴더 선택
   D:/sweep/  (하위에 Re_1e5/, Re_2e5/, ... 각각 .cas.h5/.dat.h5)

2. 변수 불러오기 → SV_P, SV_U, SV_V, SV_W 체크

3. 포맷 VTM, 출력 위치 "같은 폴더"

4. 배치 실행 → 각 Re 폴더에 Design_001.vtm, Design_002.vtm … 생성 (내부 Results.vtu)

5. ParaView에서 여러 .vtm을 동시에 열어 비교
```

---

## 8. VTM vs VTU 선택 가이드

| 항목 | VTM (Multi-Block) | VTU (Unstructured Grid) |
|---|---|---|
| Merge Blocks | 미적용 (영역 구조 유지) | 적용 (단일 grid) |
| 영역 구분 | inlet/outlet/wall 등 블록 분리 유지 | 모두 병합됨 |
| 파일 구조 | `.vtm` + 데이터 폴더 | 단일 `.vtu` 파일 |
| 영역별 분석 | ✅ 용이 (블록별 선택 가능) | ⚠️ 병합되어 구분 어려움 |
| 단순 시각화 | ✅ | ✅ |
| 권장 상황 | 영역별 구분이 필요한 경우 (기본) | 전체를 하나로 다룰 경우 |

### 어떤 걸 선택해야 하나?
- **VTM (기본 권장)**: Fluent의 영역 구조(inlet, outlet, wall, interior 등)를 ParaView에서도 구분해서 보고 싶을 때. 대부분의 경우 적합.
- **VTU**: 영역 구분 없이 전체 도메인을 단일 객체로 다루고 싶을 때, 또는 다른 도구와의 호환성이 단일 grid를 요구할 때.

> 💡 확신이 없으면 기본값인 **VTM**을 사용하세요. 영역 정보가 보존되어 나중에 더 유연하게 활용할 수 있습니다.

---

## 9. 출력 파일 구조

### 폴더명 규칙
"출력 설정"의 **폴더명** 접두사(기본 `Design`)에 변환 순서대로 번호가 붙습니다.
데이터 파일명은 항상 `Results`로 통일됩니다.

```
1번째 파일  →  Design_001 (폴더/파일)
2번째 파일  →  Design_002
...
```

> 💡 폴더명 접두사를 비우면 입력 파일명 기반(`<파일명>_export`)으로 폴백합니다.

> 💡 입력 파일명에 dp 번호가 있으면 변환 순번 대신 그 번호가 폴더 번호로 사용됩니다 (`dp_016.cas.h5` → `Design_016`).

### 포맷별 생성물
- **VTM**: `Design_001.vtm` 메타 파일 + `Design_001/` 폴더 (내부 데이터는 `Results.vtu`)
  ```
  Design_001.vtm          ← 메타 파일 (블록 구조 정의)
  Design_001/
  └── Results.vtu         ← 실제 데이터 (블록이 여러 개면 Results_0.vtu, Results_1.vtu …)
  ```
- **VTU**: `Design_001/` 폴더 안에 `Results.vtu`
  ```
  Design_001/
  └── Results.vtu
  ```
→ ParaView에서는 VTM은 `.vtm` 파일을, VTU는 `Results.vtu`를 열면 됩니다.

### 출력 위치
- **"입력 파일과 같은 폴더" 모드**: 원본 CFF 파일이 있는 폴더에 생성
- **"지정 폴더에 모아서 저장" 모드**: 모든 결과 폴더를 지정한 한 폴더 아래에 모음
  ```
  D:/output/Design_001.vtm , D:/output/Design_001/Results.vtu
  D:/output/Design_002.vtm , D:/output/Design_002/Results.vtu
  ```

---

## 10. 트러블슈팅

### 문제 1: "pvpython을 찾지 못했습니다"
**원인**: ParaView 자동 탐지 실패

**해결**: [찾아보기] 버튼으로 직접 `pvpython.exe` 지정
```
C:\Program Files\ParaView 6.1.0\bin\pvpython.exe
```

### 문제 2: 변수 불러오기 실패 / ModuleNotFoundError
**원인**: Windows가 ParaView의 `.pyd` 파일 차단 (보안)

**해결**: 관리자 PowerShell에서
```powershell
Get-ChildItem "C:\Program Files\ParaView 6.1.0" -Recurse | Unblock-File
```

### 문제 3: ".cas.h5 파일을 찾지 못했습니다"
**원인**: 폴더에 CFF 파일이 없거나, 레거시 포맷(.cas/.dat)만 있음

**해결**:
- CFF 포맷(`.cas.h5`)인지 확인
- 레거시 포맷이면 Fluent에서 CFF로 재저장: `/file/write-case-data 파일명.cas.h5`

### 문제 4: GUI가 안 뜸 / PySide6 오류
**원인**: PySide6 미설치

**해결**:
```bash
pip install PySide6
```

### 문제 5: 일부 파일만 실패
**원인**: 특정 CFF 파일의 손상 또는 결과 데이터 없음

**해결**: 콘솔 로그에서 실패한 파일명 확인 → 해당 파일을 Fluent에서 점검. 실패해도 나머지 파일은 정상 변환됨.

### 문제 6: 변환은 됐는데 변수가 비어있음
**원인**: 선택한 변수가 해당 파일에 없거나, Point Data로 잘못 저장

**해결**: 이 앱은 Cell Data로 저장합니다. ParaView에서 파일을 열어 Cell Data 탭에서 변수를 확인하세요.

---

## 11. 자주 묻는 질문

**Q. pvpython으로 실행해야 하나요?**
A. 아니요. GUI는 일반 `python`으로 실행합니다. pvpython은 GUI가 내부적으로 자동 호출합니다.

**Q. 100개 변환에 얼마나 걸리나요?**
A. 파일 크기에 따라 다르지만, 파일당 3~5초 정도면 100개에 5~10분 예상입니다. 순차 처리이므로 변환 중에도 진행률을 확인할 수 있습니다.

**Q. 변환 중에 중단할 수 있나요?**
A. 네, [중단] 버튼으로 언제든 멈출 수 있습니다. 이미 변환된 파일은 유지됩니다.

**Q. 각 파일의 변수가 다르면 어떻게 되나요?**
A. 첫 파일 기준으로 선택한 변수를 모든 파일에 적용합니다. 특정 파일에 그 변수가 없으면 해당 변수는 건너뛰고 나머지는 저장됩니다 (워커가 자동 처리).

**Q. Point Data로 저장할 수 있나요?**
A. 현재 버전은 Cell Data만 저장합니다 (Fluent 원본 보존). Point Data가 필요하면 ParaView에서 `Cell Data to Point Data` 필터를 적용하세요.

**Q. 레거시 Fluent 포맷(.cas/.dat)도 되나요?**
A. 이 앱은 CFF 포맷(`.cas.h5`)만 지원합니다. 레거시는 Fluent에서 CFF로 재저장 후 사용하세요.

**Q. 변환된 파일을 ParaView에서 어떻게 여나요?**
A. ParaView에서 File → Open으로 `.vtm` 또는 `.vtu` 파일을 선택하면 됩니다. VTM은 `.vtm` 파일만 열면 데이터 폴더는 자동으로 참조됩니다.

---

## 12. Workbench DP 정리 탭

Ansys Workbench 파라메트릭(Design Point) 시뮬레이션 결과를 정리하는 도구입니다.
각 DP 폴더(dp0, dp1, dp2 …)에 흩어진 Fluent Case/Data를 **지정 경로로 복사하면서 DP 이름으로 통일**합니다.

### 무엇을 해결하나
Workbench 결과는 아래처럼 저장되어, 파일명만으로는 어느 DP의 결과인지 알 수 없습니다.
```
...-001_files/dp1/FFF/Fluent/FFF.27-3.cas.h5
...-001_files/dp1/FFF/Fluent/FFF.27-3-1200.dat.h5   (끝의 -1200 = 반복횟수)
```
이 탭은 이를 다음과 같이 정리합니다 → `dp_001.cas.h5` + `dp_001.dat.h5`.
Case와 Data의 이름(base)이 같아지므로 **곧바로 "CFF to VTM/VTU" 탭에 넣어 변환**할 수 있습니다.

### 사용법
1. **입력 폴더**: dp 폴더들이 들어있는 상위 폴더 선택 → [스캔]
   - `dp<번호>` 폴더를 재귀 탐색하고, 각 폴더에서 `FFF/Fluent` 우선(없으면 재귀)으로 Case/Data를 찾습니다.
   - 결과가 표로 표시됩니다: 선택 / DP / Case / Data / 반복횟수 / 상태.
   - Data가 여러 개(반복/시간 스텝)면 **반복횟수가 가장 큰 것**을 자동 선택합니다(나머지는 로그에 기록).
2. **이름 규칙**: 기본은 DP 번호 제로패딩(dp1 → `dp_001`, dp16 → `dp_016`). 필요하면 접두사/접미사를 지정합니다(미리보기 제공).
3. **출력 설정**:
   - 출력 폴더 선택
   - 저장 구조: **이름별 폴더**(`dp_001/dp_001.cas.h5`) 또는 **한 폴더에 모두**(`dp_001.cas.h5`)
   - **이미 있는 파일 건너뛰기**(이어하기): 같은 크기 파일이 이미 있으면 복사 생략
4. **실행**: 선택한 DP만 복사합니다(원본은 그대로 유지). 실행 전 예상 용량/디스크 여유공간을 확인합니다.

### 상태 표시
| 상태 | 의미 |
|---|---|
| 정상 | Case + Data 모두 존재 (기본 선택됨) |
| Data 없음 / Case 없음 | 한쪽만 존재 (기본 미선택, 필요 시 수동 체크) |
| 결과 없음 | Case/Data 둘 다 없음 (선택 불가) |

### 로그 파일 (작업 내역)
완료 후 출력 폴더에 두 개의 로그가 생성됩니다.
- `dp_collect_<타임스탬프>.csv` — 원본↔변경 경로/파일명, 반복횟수, 크기, 복사상태 등 전 항목 (Excel에서 분석)
- `dp_collect_<타임스탬프>.txt` — 사람이 읽기 쉬운 요약 (DP별 원본 → 변경 매핑)

> 💡 이 탭은 순수 파이썬으로 동작하여 **ParaView가 없어도** 사용할 수 있습니다.

---

## 13. boundary_conditions.json 생성 (Stochos DIM-GP 학습용)

**"CFF to VTM/VTU" 탭 하단의 선택 기능**입니다([6.6절](#6-화면-구성과-각-항목-설명) 참고).
VTU로 변환한 설계 폴더에, Stochos Flow VTK Reader(`read_vtk`)가 요구하는
**설계 폴더별 전역 파라미터 JSON**(`boundary_conditions.json`)을
**Workbench Parameter Table에서 Export한 전체 DP 테이블 CSV**에서 자동 생성합니다.

> ⚠️ 설계 테이블 CSV는 **Ansys Workbench의 Parameter Table(설계점 테이블)을 Export한 CSV**를 사용합니다.
> optiSLang에서 Export한 CSV는 양식이 달라 **사용하지 않습니다**.

```
[Workbench DP 테이블 CSV]            [이 기능]             [설계 폴더별 생성물]
Name   P1      P2     ...
DP 0   120.0   85.0   ...  →  번호 매칭 후     →  Design_000/boundary_conditions.json
DP 1   125.0   88.0   ...     설계 폴더에 기록      Design_000/design_info.json (사이드카)
DP 2   130.0   90.0   ...  →                   →  Design_001/, Design_002/ … 동일 생성
```

이렇게 만든 JSON은 Stochos에서 설계당 `(inlet_length, cone_length, vortex_finder_length)`
전역 피처(`X_global_feat`)로 읽혀 DIM-GP 그래프 회귀 학습에 사용됩니다.

### ⚠️ 반드시 지켜지는 Stochos 규칙 (앱이 자동 보장)

이 기능은 아래 규칙을 코드로 강제합니다. **파라미터 매핑을 편집할 때만 주의**하면 됩니다.

1. **키 순서 = 학습 피처 순서**: 파라미터 매핑에 적은 순서가 그대로 JSON 키 순서 → `X_global_feat` 열 순서가 됩니다. 순서를 바꾸면 학습 피처 의미가 뒤바뀝니다.
2. **파라미터 키만 기록**: `boundary_conditions.json`에는 파라미터 키만 들어갑니다. 설계 이름·생성 시각 등 메타데이터는 **별도 `design_info.json`**에만 기록됩니다(Stochos는 이 파일을 읽지 않음). 메타데이터가 bc JSON에 섞이면 오류 없이 조용히 입력 피처로 학습되어 모델이 오염되므로, 앱은 이를 분리합니다.
3. **값은 float**: `1,25` 같은 소수점 콤마도 처리합니다. `nan`/`inf`/오버플로 값은 **거부**되어 "값 변환 실패"로 보고됩니다(비정상 피처 유입 차단).
4. **열 매칭은 정확 일치 우선**: `Cone_length`와 `Cone_length_1`이 함께 있어도 정확히 일치하는 열을 고릅니다. 출력(응답)값 열은 입력 파라미터로 매핑하지 마세요 (`_op` 접미사 열은 자동 거부됩니다).
5. **모든 학습 폴더에 동일 키 집합**: 일부 폴더만 생성되면(쓰기 실패 등) 요약에 **"쓰기 실패(부분 생성됨)"** 경고가 뜹니다. 이 상태로 학습하면 Stochos 읽기 단계가 실패하므로, 경고가 있으면 반드시 재생성하세요.

### 사용법

1. **설계 테이블 CSV**: [찾아보기]로 **Workbench Parameter Table에서 Export한 전체 DP 테이블 CSV**를 선택합니다. 구분자(탭/세미콜론/콤마)는 자동 감지되며, 헤더 앞의 제목 행이나 빈 행은 건너뜁니다.
   - **Workbench 포맷 자동 인식**: `# ` 주석 행들, `P1 - Inlet_length [mm]` 형식의 파라미터 정의 주석, `Name,P1,P2,…` 헤더(P번호 참조), `DP 0`/`DP 1` … 설계명을 자동 인식합니다. 파라미터 매핑에는 P번호가 아니라 **파라미터 이름**(예: `Inlet_length`)을 쓰면 되고, 설계번호 열도 `#`이 없으면 `Name`으로 자동 폴백되므로 보통 그대로 두면 됩니다.
   - ⚠️ optiSLang에서 Export한 설계 테이블 CSV는 양식이 달라 **사용하지 않습니다**. Workbench의 Parameter Table에서 전체 DP 테이블을 Export하세요.
   - 자동 감지에 실패하면("헤더 행을 찾지 못했습니다" 오류 — 첫 행 미리보기가 함께 표시됨) 옵션의 **구분자** 드롭다운에서 탭/세미콜론/콤마를 직접 지정하세요. 미리보기에 구분자가 전혀 안 보이면 선택한 파일이 설계 테이블 CSV가 맞는지 확인하세요.
2. **설계 폴더 루트**: 설계 폴더(`Design_001` …)들의 부모 폴더를 지정합니다. 보통 변환 탭의 출력 폴더와 같습니다.
3. (필요 시) **설계 번호 열**(기본 `#`), **구분자**(기본 자동 감지), **폴더 번호 오프셋**(폴더 번호 = CSV 번호 + 오프셋), **파라미터 매핑**을 조정합니다.
   - 파라미터 매핑 기본값:
     ```
     inlet_length = Inlet_length
     cone_length = Cone_length
     vortex_finder_length = V.Finder_length
     ```
4. **[미리보기(DRY-RUN)]**: 파일을 만들지 않고 매칭 결과를 확인합니다.
   - 요약에서 **생성 대상 개수 / 폴더 없음(CSV에만) / CSV 없음(폴더에만) / 값 변환 실패**를 확인하세요.
   - "폴더 없음"이 많으면 오프셋이 어긋난 것입니다 — 오프셋을 조정해 다시 미리보기.
5. **[JSON 생성]**: 확인 대화상자 후 실제로 각 설계 폴더에 `boundary_conditions.json`(+ 선택 시 `design_info.json`)을 씁니다. 기존 파일은 덮어씁니다.

### 기준설계(DP0)가 CSV에 없을 때 — 직접 입력

Workbench Parameter Table의 전체 DP 테이블에는 보통 기준설계 **DP 0**이 포함되지만, 테이블을 일부만 Export했거나 DP 0 행이 빠진 CSV를 받은 경우가 있을 수 있습니다. 그러면 `Design_000` 폴더는 있지만 CSV에 대응 행이 없어 JSON이 생성되지 않고, 그대로 학습하면 Stochos가 그 폴더에서 읽기에 실패합니다. 기준설계의 파라미터 값은 스터디의 **기준(nominal) 상수**로 이미 알고 있으므로, 그 값을 직접 입력해 채웁니다.

1. **[누락 기준설계(DP0) 값 직접 입력]** 체크박스를 켭니다.
2. **설계번호**를 지정합니다(기준설계는 보통 `0`).
3. **기준설계 값**에 `json_key = 값` 형식으로 입력합니다(파라미터 매핑의 키와 동일, 순서는 무관 — 저장 시 매핑 순서로 정렬됨):
   ```
   inlet_length = 120.0
   cone_length = 85.0
   vortex_finder_length = 45.0
   ```
4. [미리보기]/[JSON 생성]을 실행하면, CSV로 채워지는 설계와 함께 해당 폴더에 `boundary_conditions.json`이 생성됩니다.

> 💡 사이드카(`design_info.json`)에는 `"source": "manual"`, `"csv_design_number": null`로 기록되어 수동 입력임을 구분할 수 있습니다. 입력 키가 파라미터 매핑과 다르면(누락·오타) 생성 전에 경고합니다. 이미 CSV로 생성된 번호를 지정하면 CSV 값이 우선하고 수동 입력은 무시됩니다.

> 💡 CLI에서도 동일하게: `--manual-design 0 --manual-value inlet_length=120.0 --manual-value cone_length=85.0 --manual-value vortex_finder_length=45.0`

### 번호 매칭과 오프셋

- 폴더 번호는 폴더명 끝의 정수로 인식합니다 (`Design_016` → 16, `dp_016` → 16).
- CSV 설계 번호는 `Name` 열의 설계명에서 정수를 추출합니다 (`DP 0` → 0, `DP 16` → 16).
- CSV 설계 번호와 폴더 번호 체계가 다르면 오프셋으로 보정합니다.
  - 예: CSV가 `DP 0`부터인데 폴더가 `Design_001`부터면 **오프셋 +1**, 반대로 CSV가 1부터인데 폴더가 `Design_000`부터면 **오프셋 −1**.
- 매칭되지 않은 항목은 요약에 그대로 표시되므로, 학습 전에 1:1로 맞는지 확인하세요.

### 명령줄(CLI)로도 사용 가능

GUI 없이 `bc_json_gen.py`를 직접 실행할 수도 있습니다 (기본은 DRY-RUN, `--execute`로 실제 생성).

```bash
# 미리보기 (파일 미생성)
python bc_json_gen.py --csv Cyclone_design_table.csv --root D:/vtu_data

# 실제 생성 + 오프셋 보정
python bc_json_gen.py --csv Cyclone_design_table.csv --root D:/vtu_data --offset -1 --execute

# 사이드카 없이, 파라미터 매핑 직접 지정 (순서 유지)
python bc_json_gen.py --csv table.csv --root D:/vtu_data --no-sidecar \
    --param inlet_length=Inlet_length \
    --param cone_length=Cone_length \
    --param vortex_finder_length=V.Finder_length --execute
```

> 💡 이 기능은 순수 표준 라이브러리로 동작하므로 **ParaView 없이도** 실행됩니다.

---

## 부록: 워커 직접 실행 (고급)

GUI 없이 워커를 직접 명령줄에서 쓸 수도 있습니다 (자동화/스크립팅용).

```bash
# 변수 목록 확인
"C:/Program Files/ParaView 6.1.0/bin/pvpython.exe" pv_export_worker.py \
    --case FFF.3-1.cas.h5 --list-json

# VTM 변환
"C:/Program Files/ParaView 6.1.0/bin/pvpython.exe" pv_export_worker.py \
    --case FFF.3-1.cas.h5 --output FFF.3-1.vtm --format vtm \
    --vars SV_P,SV_U,SV_V,SV_W

# 모든 변수를 VTU로
"C:/Program Files/ParaView 6.1.0/bin/pvpython.exe" pv_export_worker.py \
    --case FFF.3-1.cas.h5 --output FFF.3-1.vtu --format vtu --all
```

이를 활용하면 PowerShell/배치 스크립트로 자체 배치 처리도 구성할 수 있습니다.
