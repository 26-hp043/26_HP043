# AGENTS.md — 본 저장소 작업 규칙

본 파일은 AI 에이전트가 이 저장소에서 작업할 때 반드시 따라야 할 규칙을 정의한다.

---

## 1. 언어 정책

- **커밋 메시지**: 한국어로 작성한다. 단, 기술 용어(PR, API, SQL 등)는 영어를 그대로 사용한다.
- **문서 수정**: 본문은 한국어, 기술 용어는 영어를 병용한다.
- **코드 주석**: 한국어로 작성한다.

---

## 2. Oracle 리뷰 교차 검증 규칙 (필수)

> **교훈**: Oracle 리뷰에서 규제값·외부 팩트에 대한 finding이 나오면, 반드시 권위 있는 원문으로 교차 검증한다. Oracle이 두 번이나 잘못된 "정정"을 제안했다.

### 2.1 검증 대상

Oracle이 다음 유형의 finding을 제공할 때, 원문 교차 검증 없이 적용하지 않는다:

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
- Oracle이 한때 `14779E10`을 `14479E10`의 오타라고 "정정"했으나, 실제로는 두 값 모두 유효한 서로 다른 구간의 값이었다.
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
- Oracle 리뷰 또는 외부 리뷰 반영 시 버전을 올리고, 전용 섹션(예: §12, §14)에 리뷰 결과를 기록한다.
- `README.md`는 각 문서의 최신 버전과 상태를 항상 반영한다.

---

## 5. 검색·분석 원칙

- "결과가 나오면 멈추지 말고 최소 2개 이상의 독립적 소스를 교차 확인한다."
- 수치 검증: 정수 연산으로 직접 계산하여 확인한다 (예: `5045066331 × 94 = 474236235114`).
- 외부 라이브러리: 공식 문서 + 실제 OSS 구현 예를 함께 확인한다.
