# AGENTS.md — 본 저장소 작업 규칙

본 파일은 AI 에이전트가 이 저장소에서 작업할 때 반드시 따라야 할 규칙을 정의한다.

| 항목 | 내용 |
|---|---|
| 문서명 | AGENTS.md |
| 버전 | v1.1 |
| 상태 | 운영 중 (전 저장소 적용) |
| 최종 수정일 | 2026-07-05 |

---

## 1. 언어 정책

- **커밋 메시지**: 한국어로 작성한다. 단, 기술 용어(PR, API, SQL 등)는 영어를 그대로 사용한다.
- **문서 수정**: 본문은 한국어, 기술 용어는 영어를 병용한다.
- **코드 주석**: 한국어로 작성한다.

---

## 2. AI 보조 리뷰 교차 검증 규칙 (필수)

> **교훈**: AI 에이전트 보조 리뷰에서 규제값·외부 팩트에 대한 finding이 나오면, 반드시 권위 있는 원문으로 교차 검증한다. AI 에이전트가 두 번이나 잘못된 "정정"을 제안했다.

### 2.1 검증 대상

AI 에이전트(리뷰·분석 에이전트 등)가 다음 유형의 finding을 제공할 때, 원문 교차 검증 없이 적용하지 않는다:

- IMO 결의안 인용 값 (MEPC.xxx)
- 공식 규제 표의 수치
- 외부 라이브러리/프레임워크의 공식 스펙
- 타 문서와의 정합성 주장 (한 쪽이 오타라고 단정하는 경우)

### 2.2 권위 소스 우선순위

| 주제 | 권위 소스 | 링크 |
|---|---|---|
| CII Reference Line (G2) | MEPC.353(78) Annex Table 1 | [PDF](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.353%2878%29.pdf) |
| CII Reduction Factor (G3) | MEPC.400(83) | [PDF](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.400%2883%29.pdf) |
| CII Rating (G4) | MEPC.354(78) | [PDF](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.354%2878%29.pdf) |
| CII Guidelines (G1) | MEPC.352(78) | [PDF](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.352%2878%29.pdf) |

> **MEPC.364(79)는 EEDI 계산 지침이며, CII G2 reference line과 무관하다.** G2 인용 시 MEPC.353(78)을 사용한다.

### 2.3 사례: LNG_CARRIER reference line `a` 값

MEPC.353(78) Table 1 기준 (권위값):

| 선종 | 조건 | capacity_rule | a_raw | c |
|---|---|---|---|---|
| LNG_CARRIER | DWT ≥ 100,000 | DWT | 9.827 | 0.000 |
| LNG_CARRIER | 65,000 ≤ DWT < 100,000 | DWT | **14479E10** | 2.673 |
| LNG_CARRIER | DWT < 65,000 | fixed 65000 | **14779E10** | 2.673 |

- `14479E10`과 `14779E10`은 **서로 다른 DWT 구간의 서로 다른 값**이다.
- AI 에이전트가 한때 `14779E10`을 `14479E10`의 오타라고 "정정"했으나, 실제로는 두 값 모두 유효한 서로 다른 구간의 값이었다.
- 이 교훈을 되새워, 수치 정정 시 반드시 원문 표의 전체 행을 확인한다.

---

## 3. 문서 우선순위

문서 간 충돌 시 다음 우선순위를 따른다:

```
1. IMO 원문 (MEPC 결의안)     — 규제값의 최종 권위
2. PRD.md                     — 제품 요구사항의 최종 권위
3. TECH_SPEC.md               — 기술 구현의 최종 권위
4. API_SPEC.md                — API 인터페이스의 최종 권위
5. DB_SCHEMA.md               — DB 구조의 최종 권위
6. TEST_PLAN.md               — 테스트의 최종 권위
```

상위 문서가 하위 문서와 충돌하면, 하위 문서를 상위 문서에 맞춘다. 단, 규제값은 항상 IMO 원문이 최우선이다.

---

## 4. 문서 버전 관리

- 각 문서는 헤더에 버전, 상태, 최종 수정일을 명시한다.
- AI 보조 리뷰 또는 외부 리뷰 반영 시 버전을 올리고, 전용 섹션(예: §12, §14)에 리뷰 결과를 기록한다.
- `README.md`는 각 문서의 최신 버전과 상태를 항상 반영한다.

---

## 5. 검색·분석 원칙

- "결과가 나오면 멈추지 말고 최소 2개 이상의 독립적 소스를 교차 확인한다."
- 수치 검증: 정수 연산으로 직접 계산하여 확인한다 (예: `5045066331 × 94 = 474236235114`).
- 외부 라이브러리: 공식 문서 + 실제 OSS 구현 예를 함께 확인한다.

---

## 6. 이슈 생성 규칙

- **제목에 분류 태그를 넣지 않는다.** 우선순위(P0/P1/P2)와 영역(infra/db/calc/api/test/quality)은 GitHub 라벨로 표시한다.
  - ❌ `[P0][calc] attained_cii 계산`
  - ✅ `attained_cii 계산 (Layer 1: Decimal prec=30)`
- **이슈 하나의 크기는 하루(6~8시간) 작업량을 기준으로 한다.** 한 이슈가 여러 파일·여러 기능을 다루면 더 작게 쪼갠다.
- 이슈 본문에는 반드시 포함한다:
  - **목표**: 이 이슈가 해결하는 문제 (1~2문장)
  - **작업 체크리스트**: 구체적인 구현 항목들 (`- [ ]` 마크다운 체크박스)
  - **참조**: PRD/TECH_SPEC/API_SPEC/DB_SCHEMA/TEST_PLAN의 관련 섹션 번호
  - **완료 기준**: 어떤 상태가 되어야 이슈를 닫을 수 있는지 (테스트 이름, 동작 등)
- 수치·공식·규제값은 반드시 상위 문서(PRD/TECH_SPEC/DB_SCHEMA)에서 복사하고, 해당 섹션 번호를 참조한다. 임의로 값을 재작성하지 않는다.
- 본 문서의 §3 우선순위에 따라, 이슈 본문이 하위 문서(API_SPEC/TEST_PLAN)와 충돌하면 상위 문서(PRD/TECH_SPEC) 기준으로 맞춘다.

---

## 7. PR 생성 규칙

- **PR 제목**: 한국어로 작성. 커밋 메시지와 동일한 형식.
- **커밋 메시지**: 한국어. 기술 용어(PR, API, SQL 등)는 영어 그대로 사용. (§1 언어 정책 준수)
- **이슈 연결**: PR 본문에 `Closes #이슈번호` 또는 `Fixes #이슈번호`를 명시한다.
- **계층 분리 준수**: 코드 변경 PR은 서비스 레이어 규칙(TECH_SPEC §16)을 지키는지 확인한다. 상세 체크리스트는 TECH_SPEC §16.5 참조.
- **단위**: 1 PR = 1 이슈 원칙. 단, 밀접하게 관련된 이슈 2~3개는 하나의 PR에 포함할 수 있다.
- **PR 본문 템플릿**:
  ```markdown
  ## Summary
  - 변경 내용 요약 (2~3 bullet)

  ## 관련 이슈
  Closes #이슈번호

  ## 변경 사항
  - 주요 변경 파일 및 내용

  ## 테스트
  - [ ] 단위 테스트 통과
  - [ ] lint 통과 (ruff check)
  ```
- **머지 조건**: CI(lint + test)가 전부 통과해야 머지할 수 있다.
- **Squash merge 원칙**: 여러 커밋이 있더라도 머지 시 1개 커밋으로 squash한다.

---

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준).

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-07-04 | `0f59999` | v1.0 최초 작성 (외부 리뷰 반영 커밋에 포함) |
| 2026-07-04 | `547eeed` | Oracle → AI 에이전트 용어 일반화 |
| 2026-07-05 | `7bc248b` | v1.1: 이슈·PR 생성 규칙 추가 (§6, §7) |
