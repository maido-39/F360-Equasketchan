# 수식 기반 곡선 — 구현·실행 명세 (SPEC v0.2, Implementation & Execution Addendum)

> **이 문서의 위치:** v0.1(`SPEC_features.md`, 기능 요구사항 FR-1…FR-13 등 "이상적 타깃")과
> **함께** 전체 명세를 구성한다. v0.1이 "무엇을 만드는가"라면, v0.2는 "Fusion 현실 위에서
> 어떻게 만들고, 에이전트(Claude Code)가 어떻게 검증·실행하는가"를 정의한다.
> **Claude Code는 구현을 시작하기 전에 두 문서를 모두 정독하고, §24 리서치 재검증을 수행한 뒤,
> §25 실행 런북을 따른다.**

---

## 0. v0.1 대비 보강 내역 (Gap Analysis)

| 영역 | v0.1 상태 | v0.2에서 추가 |
|---|---|---|
| 기능 요구사항(입력·함수·연동·출력·UI·오류·NFR·수용기준·프리셋) | ✅ 있음 | (그대로 유효, 변경 없음) |
| 플랫폼·구현 제약(Custom Feature 현실, in-process, 단위, 브리지 한계) | ❌ 없음 | §16 |
| 아키텍처 강제사항(코어/어댑터 분리, 단위 경계, 정의 저장, 결정성) | ❌ 없음 | §17 |
| 재편집/연동 **구현 마일스톤**(MVP vs 풀 Custom Feature, 폴백) | △ 이상치만 | §18 |
| 개발 환경 요구사항 | ❌ 없음 | §19 |
| 에이전트 테스트·검증 요구사항(2단 테스트, 브리지 도구) | ❌ 없음 | §20 |
| 보안 요구사항(브리지) | ❌ 없음 | §21 |
| 원격 Windows / SSH 토폴로지 | ❌ 없음 | §22 |
| 프로젝트 구조·패키징 | ❌ 없음 | §23 |
| **리서치 재검증 체크리스트** | ❌ 없음 | §24 |
| **Claude Code 실행 런북 + Definition of Done** | ❌ 없음 | §25 |
| 추적성/커버리지(누락 검증) | ❌ 없음 | §26 |

우선순위 표기는 v0.1과 동일: **[M]** Must / **[S]** Should / **[C]** Could / **[W]** Won't(now).

---

## 16. 플랫폼 · 구현 제약 (Fusion 현실)

이 제약들은 v0.1의 "이상적" 요구사항을 **실현 가능한 범위로 사상(map)**하기 위한 것이다.

- **PC-1 [M] In-process API.** `adsk.*`는 실행 중인 Fusion 안에서만 로드된다. 외부에서 직접
  실행 불가. → 테스트는 Fusion 구동 + 브리지 경유(§20)로만 가능.
- **PC-2 [M] 헤드리스 없음.** Fusion은 CLI/헤드리스 모드가 없다. 완전 무인 CI 불가 →
  GUI Fusion이 떠 있는 호스트 필요.
- **PC-3 [M] 번들 Python.** Fusion은 자체 번들 Python을 쓴다(버전은 §24에서 재확인).
  애드인/어댑터 코드는 **추가 pip 의존 없이 stdlib만** 사용한다.
- **PC-4 [M] 내부 단위 = cm.** 모든 `adsk` 지오메트리 단위는 cm. 단위 변환은 어댑터 경계
  한 곳에서만 수행한다(§17 ARC-3).
- **PC-5 [M] Custom Feature 재계산은 좁은 경로만 신뢰 가능.** 자동 재계산은
  base feature·sketch·combine 구성에 한해 지원되며, 그 밖에선 실패할 수 있다. 컴퓨트 중
  Fusion은 "취약 상태"라 가능한 작업이 제한된다. → 곡선은 **base feature 안의 스케치**로
  감싸 지원 라인에 맞춘다.
- **PC-6 [M] 편집 시 타임라인 롤백.** Custom Feature는 단일 노드라 내부 피처 앞으로 타임라인을
  되감을 수 없다. 편집 핸들러에서 "피처 일시 제거 → 마커 이동 → 편집 → 재삽입" 우회를 구현한다.
- **PC-7 [M] 애드인 상주 의존.** 컴퓨트/편집은 정의 애드인이 로드·실행 중일 때만 동작한다.
  애드인 없는 환경에 파일을 넘기면 곡선은 정적(dumb)이 된다. → 사용자 문서/README에 명시.
- **PC-8 [S] 관측 동작은 "노란 경고".** 파라미터 변경 시 자동 무손실 재생성이 보장되지 않고,
  노드가 노랗게 갱신필요 표시되는 경우가 흔하다 → **Regenerate 폴백 명령**을 제공한다(§18 MS-2).
- **PC-9 [M] 브리지 호출 제약.** 호출당 1 작업, 30초 타임아웃을 전제로 설계·테스트한다.

---

## 17. 아키텍처 강제사항 (Binding)

- **ARC-1 [M] 코어/어댑터 분리.** 수학·정의·샘플링은 `eqcurve.core`에, `adsk` 호출은
  `eqcurve/adapter.py`와 애드인에만 둔다.
- **ARC-2 [M] adsk-비의존 코어.** 코어는 stdlib만 사용해 **시스템 Python(pytest)과 Fusion
  번들 Python 양쪽에서 import** 가능해야 한다.
- **ARC-3 [M] 단위 경계.** 코어는 mm로 점을 산출하고, 어댑터에서만 mm→cm(×0.1) 변환한다.
- **ARC-4 [M] 정의 저장은 무손실·역추출 금지.** `CurveDef`(식·범위·좌표계·단위·변환)를 JSON으로
  스케치/피처 attribute에 저장한다. 재편집 시 형상에서 역추출하지 않고 저장본을 복원한다(v0.1 FR-11.4).
- **ARC-5 [M] 결정적 샘플링.** 동일 입력→동일 점군(무작위 금지). 적응 샘플링도 결정적 규칙으로
  구현한다(테스트 가능성·NFR-4).
- **ARC-6 [S] 독립변수 별칭.** `t`(매개변수), 명시적 데카르트의 `x`, 명시적 극의 `a`를 허용.
- **ARC-7 [M] 안전 파서.** 사용자 식은 AST 화이트리스트로 평가하며, 사용자 입력에 대해
  `eval`/`exec`를 직접 쓰지 않는다(임의 코드 실행 차단).

---

## 18. 재편집 · 연동 — 구현 마일스톤 (v0.1 §9의 현실 사상)

v0.1 §9의 "완전 라이브 연동"은 PC-5~PC-8 때문에 플랫폼상 상한이 있다. 목표를 **"타임라인 노드 +
더블클릭 재편집 + (지원 경로에서) 재계산 또는 갱신필요 표시"**로 현실화하고, 두 단계로 나눈다.

- **MS-1 (MVP) [M]** 곡선 생성 + `CurveDef` 저장 + 재오픈/편집 다이얼로그(무손실 복원).
  파라미터는 생성 시점 값으로 평가. — *현 스캐폴드가 여기까지 충족.*
- **MS-2 (풀 연동) [M]** Custom Feature로 승격:
  - 타임라인 노드 + 더블클릭/우클릭 Edit (PC-6 롤백 처리 포함).
  - 참조하는 User Parameter(D3 등)에 **dependency 등록** → 변경 시 재계산 대상.
  - 곡선 스플라인을 **base feature 안 스케치**로 구성해 지원 컴퓨트 경로에 맞춤(PC-5).
  - **Regenerate 폴백 명령** 제공(PC-8): 자동 재계산이 노란 경고로 끝날 때 사용자가 1클릭 갱신.
- **MS-3 (확장) [C]** 적응(곡률) 샘플링 + 편차 공차, 프리셋 UI, 정의 import/export.

수용: v0.1 AC-5(무손실 재편집)는 MS-1에서, "D-파라미터 변경 시 갱신 대상이 됨"은 MS-2에서 검증.

---

## 19. 개발 환경 요구사항

- **DEV-1 [M]** 개발/테스트 호스트에 Fusion 360 설치·실행(원격 Windows 가정, §22).
- **DEV-2 [S]** VS Code + ms-python 확장으로 브레이크포인트 디버깅(애드인 Stop→Start Debugging,
  Restart는 미지원→Disconnect 후 재시작).
- **DEV-3 [S]** `adsk` 타입 스텁 설치로 Fusion 밖에서도 자동완성·정적검사.
- **DEV-4 [M]** 브리지 애드인은 별도로 Run(개발 세션 한정; Run on Startup 비활성).
- **DEV-5 [M]** 코어는 시스템 Python에서 `pytest`로 단독 실행 가능해야 한다.

---

## 20. 에이전트 테스트 · 검증 요구사항

- **TEST-1 [M] 2단 테스트.** (a) 코어 → `pytest`(Fusion 불필요), (b) 어댑터/플러그인 →
  브리지 경유 통합 테스트(Fusion 필요).
- **TEST-2 [M] 브리지 도구.** `execute(script, session)`, `screenshot()`, `health()`,
  `list_api(query)`를 MCP로 노출.
- **TEST-3 [S] 영속 세션.** `execute` 호출 간 변수 상태 유지(반복 루프 효율).
- **TEST-4 [M] 통합 하니스.** Fusion 안에서 곡선을 생성하고 결과(스플라인 수/좌표)를 어서션.
- **TEST-5 [S] 시각 검증.** `screenshot()`로 생성 곡선을 PNG로 확인.
- **TEST-6 [M] 수용기준 매핑.** v0.1 §13의 각 AC와 §26의 항목을 자동 검사로 1:1 연결.
- **TEST-7 [M]** 호출당 1 작업·30초 타임아웃·cm 단위(PC-4/PC-9)를 준수.

---

## 21. 보안 요구사항 (브리지)

- **SEC-1 [M]** 브리지는 **`127.0.0.1` 전용 바인드. 절대 `0.0.0.0` 금지.**
- **SEC-2 [M]** 모든 요청에 Bearer 토큰. 토큰은 사용자 프로필에 저장하고 **레포에 커밋 금지**.
- **SEC-3 [M]** 원격 접근은 **SSH만**(토폴로지 A: 서버를 Fusion 호스트에서 실행, §22).
- **SEC-4 [M]** 브리지에 **자동업데이트·외부 네트워크 호출 없음**(전수 감사된 자체 구현).
- **SEC-5 [M]** 브리지는 임의 Python을 실행한다(테스트 하니스의 본질) → **단일 사용자·신뢰 호스트**
  전제. 사용 전 코드 전수 검토.
- **SEC-6 [S]** 방화벽으로 브리지 포트(기본 7654) 인바운드 차단.
- **SEC-7 [M]** 브리지는 개발 세션에만 Run, 평소 Stop(Run on Startup 금지).
- **SEC-8 [C]** 토큰 회전 = 시크릿 파일 삭제 후 재생성.

---

## 22. 원격(Windows) 토폴로지 요구사항

토폴로지 A를 기본으로 한다: **MCP stdio 서버를 Windows Fusion 호스트에서 실행하고, 클라이언트는
SSH로 그 stdio를 파이프**한다. 모든 통신은 호스트 `127.0.0.1`에 머물고 토큰은 호스트를 떠나지 않는다.

- **WIN-1 [M]** Windows OpenSSH Server 활성화.
- **WIN-2 [M]** 브리지/플러그인 애드인을 AddIns 경로에 설치. 버전에 따라 둘 중 하나:
  `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\` 또는
  `%APPDATA%\Autodesk\Autodesk Fusion\API\AddIns\` (§24에서 현재 명칭 재확인).
- **WIN-3 [M]** 토큰 경로 `%LOCALAPPDATA%\fusion-eqbridge\secret`(또는 `FUSION_BRIDGE_SECRET`).
- **WIN-4 [M]** MCP 등록: `claude mcp add fusion-eqcurve -- ssh USER@WINHOST "py -m bridge.mcp_server"`
  (호스트 프로젝트 루트에서 실행되도록 작업 디렉터리 지정).
- **WIN-5 [M]** 호스트에 서버 의존 설치: `py -m pip install "mcp>=1.2.0" httpx`(§24에서 패키지 API 재확인).
- **WIN-6 [C]** 폴백 토폴로지 B(`ssh -L 7654:127.0.0.1:7654`)는 토큰 동기화가 필요 → A를 우선.

---

## 23. 프로젝트 구조 · 패키징 (Binding)

```
eqcurve/core/        # adsk-FREE: evaluator, curvedef, sampler   (ARC-2, pytest)
eqcurve/adapter.py   # adsk: 점→스플라인 + 정의 저장             (ARC-3, ARC-4)
eqcurve/addin/EquationCurve/   # 플러그인(MVP→MS-2)
bridge/addin/FusionEqBridge/   # 자체 브리지(SEC-*; stdlib only)
bridge/mcp_server/             # stdio MCP(외부 실행; httpx→브리지)
tests/test_core.py             # 수용기준(Fusion 불필요)
tests/integration_harness.py   # 라이브 브리지 검증
docs/SPEC_features.md          # v0.1
docs/SPEC_implementation.md    # v0.2 (이 문서)
```
- 코어는 런타임 의존 0. 서버 의존(`mcp`,`httpx`)은 `optional-dependencies.server`로 분리.
- 콘솔 엔트리 `fusion-eqcurve-mcp = bridge.mcp_server.server:main`.

---

## 24. 리서치 재검증 체크리스트 (구현 착수 전 Claude Code가 **반드시** 수행)

본 명세의 시간 민감 사실은 작성 시점 기준이다. **착수 전 아래를 권위 출처에서 재확인하고,
달라진 점이 있으면 해당 요구사항을 갱신**한다. (검색 키워드 + 1차 출처)

| # | 재확인 항목 | 영향 요구사항 | 1차 출처 |
|---|---|---|---|
| R-1 | Fusion 번들 **Python 버전** | PC-3 | help.autodesk.com → Fusion-360-API → *Python Specific Issues* |
| R-2 | **AddIns 폴더 명칭**("Fusion 360" vs "Fusion") | WIN-2 | Fusion Help → *Creating a Script or Add-In* |
| R-3 | **Custom Feature 컴퓨트** 지원 범위 변동 여부 | PC-5, MS-2 | Fusion-360-API → *Custom Features* |
| R-4 | **내부 단위(cm)** 유지 여부 | PC-4, ARC-3 | Fusion API 단위 문서/릴리스 노트 |
| R-5 | **Custom Feature 커스텀 파라미터**의 Change Parameters 노출 동작 | MS-2 | Custom Features 문서(Custom Parameters 절) |
| R-6 | **`mcp` Python 패키지** API(FastMCP import 경로/버전) | bridge/mcp_server | PyPI `mcp` / modelcontextprotocol 문서 |
| R-7 | **Claude Code MCP 등록**(`claude mcp add`, stdio-over-ssh) 현행 문법 | WIN-4 | docs.claude.com → Claude Code → MCP |
| R-8 | Autodesk **공식 MCP/AI 도구** 출시 여부(있다면 자체 브리지 대체 검토) | §20, §21 | Autodesk 발표/포럼 |
| R-9 | VS Code **ms-python 디버그 attach** 절차 변동 | DEV-2 | Fusion-360-API → Python Specific |
| R-10 | (참고) **Inventor Equation Curve** 함수/단위 의미론 — 함수표·단위균형의 레퍼런스 | v0.1 §5–6 | Inventor Help → *Equation Curve Formula Reference* |

> 규칙: R-1~R-7 중 하나라도 명세와 다르면, 구현 전에 해당 §를 수정하고 변경 로그를 남긴다.

---

## 25. Claude Code 실행 런북 (Execution Runbook)

**순서대로** 수행한다.

1. **정독.** `docs/SPEC_features.md`(v0.1) + 본 문서(v0.2)를 처음부터 끝까지 읽는다.
2. **리서치 재검증.** §24 표의 R-1~R-9를 검색·확인. 변경점은 해당 요구사항에 반영하고 짧은
   변경 로그를 `docs/CHANGES.md`에 기록.
3. **환경 점검(DEV/WIN/SEC).** 원격 Windows에 OpenSSH·Fusion·번들 Python 확인,
   브리지 애드인 설치·Run, `health` 그린 확인. `0.0.0.0` 바인드 아님을 확인(SEC-1).
4. **코어 우선 구현(M 먼저).** v0.1 FR 중 [M]을 §17 아키텍처 강제사항에 맞춰 완성하고,
   `pytest`로 §13 수용기준의 Fusion-불필요 항목을 모두 통과시킨다(결정성 ARC-5 유지).
5. **어댑터·플러그인(MS-1).** 어댑터로 스플라인 생성 + `CurveDef` 저장, 통합 하니스로
   Fusion 안에서 곡선 생성을 어서션(TEST-4), 필요 시 `screenshot`로 시각 확인(TEST-5).
6. **풀 연동(MS-2).** Custom Feature 승격 — base-feature/sketch 구성(PC-5),
   User Parameter dependency, 편집 핸들러 롤백(PC-6), Regenerate 폴백(PC-8).
   "D3 변경 → 갱신 대상" 통합 테스트 추가.
7. **[S]/[C] 확장(MS-3).** 적응 샘플링·프리셋 UI·import/export.
8. **Definition of Done 검증(§ 아래).**

### Definition of Done (DoD)
- [ ] §24 리서치 재검증 완료, 변경점 반영·기록.
- [ ] v0.1 [M] FR 전부 구현(입력 모드·전 좌표계·함수 라이브러리(쌍곡 포함)·폐곡선·도메인·특이점 안전).
- [ ] `pytest` 전부 통과(코어 수용기준; 결정적).
- [ ] 통합 하니스로 Fusion 안 곡선 생성·재오픈(MS-1) 검증.
- [ ] MS-2: 타임라인 노드 + 더블클릭 편집 + D-파라미터 변경 시 갱신(또는 Regenerate 폴백) 검증.
- [ ] 보안: 브리지 127.0.0.1+토큰, 외부통신·자동업데이트 없음, 개발 세션에만 Run.
- [ ] 단위 변환은 어댑터 한 곳(ARC-3), 정의는 attribute 저장·역추출 금지(ARC-4).
- [ ] PC-7(애드인 상주 의존)·PC-8(갱신 동작) 한계를 README/사용자 문서에 명시.

---

## 26. 추적성 / 커버리지 (누락 검증)

대화에서 내려진 모든 결정 → 요구사항 사상. (v0.1 FR 전체가 유효함을 전제)

| 결정/논점 (대화) | 반영 위치 |
|---|---|
| 수식 곡선(sin/cos/tan/쌍곡/지수/매개변수/다변수/폐곡선) | v0.1 §4–5, AC-1~AC-6 |
| 파라미터(D3) 연동·재편집 최우선 | v0.1 §6, §9 + v0.2 §18(MS-2) |
| 쌍곡함수 네이티브(상용 대비 차별화) | v0.1 FR-5.3 + AC-4 |
| 단위 균형 자동화(Inventor식 강제 제거) | v0.1 FR-8.5 + v0.2 ARC-3 |
| 좌표계 2D/3D 전체 | v0.1 FR-2 + v0.2 sampler 규약 |
| 특이점 안전 처리 | v0.1 FR-13.1 + v0.2 AC(test_core) |
| Custom Feature 현실(좁은 컴퓨트·롤백·상주·노란경고) | v0.2 PC-5~PC-8, MS-2 |
| in-process·헤드리스 없음·번들 Python·cm | v0.2 PC-1~PC-4 |
| 코어/어댑터 분리·결정성·정의저장 | v0.2 ARC-1~ARC-7 |
| 개발환경(VS Code 디버그·스텁) | v0.2 §19 |
| 에이전트 2단 테스트·브리지 도구·시각검증 | v0.2 §20 |
| 보안(localhost·토큰·무자동업데이트·자체감사) | v0.2 §21 |
| 원격 Windows·SSH 토폴로지 A | v0.2 §22 |
| MCP 선정(자체 브리지; faust 보조) | v0.2 §20–21, §23 |
| 리서치 재검증 가능화 | v0.2 §24 |
| 구현 전 전체 명세 정독·실행 | v0.2 §25 |

> 본 표에 빠진 신규 결정이 발견되면 요구사항으로 추가하고 표를 갱신한다.
```
