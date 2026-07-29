# 중소선사를 위한 CII 예측 및 운항 의사결정 보조 플랫폼

| 항목 | 내용 |
|---|---|
| 문서명 | README.md |
| 버전 | v1.0 |
| 상태 | 운영 중 — 저장소 진입점 |
| 최종 수정일 | 2026-07-23 |
| 하위 문서 | `PRD.md`, `TECH_SPEC.md`, `API_SPEC.md`, `DB_SCHEMA.md`, `TEST_PLAN.md`, `AGENTS.md`, `DESIGN_SYSTEM.md`, `UIFLOW.md` |
| 문서 목적 | 프로젝트 개요·문서 구조·MVP 범위를 안내한다. 규범적 내용은 각 정본이 소유하며 본 문서는 요약만 담는다 |

중소선사 선장·항해사·운항관리 담당자가 IMO 탄소집약도(CII) 등급을 예측하고, 운항 시나리오를 비교하여 데이터 기반 의사결정을 할 수 있도록 지원하는 웹 기반 플랫폼입니다.

> **면책 조항**: 본 플랫폼은 운항 의사결정을 보조하는 예측·시뮬레이션 도구입니다. 규제 제출용 공식 CII 계산 시스템이 아니며, 최종 운항 판단은 사용자에게 있습니다.

---

## 핵심 기능

| 기능 | 설명 |
|---|---|
| **항차 CII 추정** | 출항 전 항차 조건(선박, 거리, 속도, 연료) 입력 → CII 추정값, CO₂ 배출량, 예상 등급, 위험도 제공 |
| **운항 시나리오 비교** | 직항(Direct)·우회(Detour)·감속(Slow Steaming) 시나리오별 연료·CII·소요시간 중립 비교 |
| **연간 CII 시뮬레이터** | 누적 실적 + 잔여 계획 기반 연말 예상 등급, 목표 달성 확률(Monte Carlo), 민감도 분석 |

---

## 문서 구조

| 문서 | 내용 | 상태 |
|---|---|---|
| [`PRD.md`](./PRD.md) | 제품 요구사항 정의서 (v3.1, Oracle Review + 외부 리뷰 반영) — 이중 capacity 규칙(G1/G2 분리), 상태 모델, 검증 규칙 | ✅ 완료 |
| [`TECH_SPEC.md`](./TECH_SPEC.md) | 기술 명세서 (v1.3, Oracle Review + 외부 리뷰 반영 + 서비스 레이어 아키텍처 #100 + 재현성 계약 명문화 #102) — 이중 정밀도 엔진, PCG64DXSM RNG(canonical vector 고정), capacity 분리(transport/reference), canonical hashing, 스냅샷 격리, 서비스 레이어 아키텍처(§16), 재현성 계약(§5.4) | ✅ 완료 |
| [`API_SPEC.md`](./API_SPEC.md) | REST API 명세서 (v1.2, Oracle Review + 외부 리뷰 반영) — 30개 엔드포인트, 수치 직렬화 정책, field_label 오류 체계, CSV escape 보안 | ✅ 완료 |
| [`DB_SCHEMA.md`](./DB_SCHEMA.md) | 데이터베이스 스키마 (v1.3, Oracle Review + 외부 리뷰 반영 + weather 추적 컬럼 스펙 #102) — 14개 테이블, PostgreSQL 16, FK ON DELETE 정책, immutable 트리거, pg_trgm, 마이그레이션 전략 | ✅ 완료 |
| [`TEST_PLAN.md`](./TEST_PLAN.md) | 테스트 계획서 (v1.2, Oracle Review + 외부 리뷰 반영) — 168개 테스트 케이스, Fixture 1~4, 이중 capacity 검증, Layer 변환/감사 로그/소프트 삭제/CSV injection 테스트, 유효숫자 기반 Monte Carlo 비교 | ✅ 완료 |
| [`AGENTS.md`](./AGENTS.md) | AI 에이전트 작업 규칙 — Oracle 교차 검증 규칙, 규제값 권위 소스, 한국어 정책 | ✅ 신규 |
| [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) | 디자인 토큰 계약서 (v1.0) — 컬러·타이포그래피·숫자 포맷·차트 규약·접근성. 토큰의 이름·의미·제약을 확정하고 값은 Figma가 소유 | ✅ 신규 |
| [`UIFLOW.md`](./UIFLOW.md) | UI Flow 명세서 (v1.0) — 화면 흐름·진입 조건 정의 | 🟡 초안 |

---

## MVP 범위

### 포함

- 선박 등록·관리 및 샘플 선박 제공
- 규정 파라미터 관리 (Z-factor, 선종별 reference line, d-vector, 연료 CF)
- 항차 CII 추정 (기능①)
- 운항 시나리오 비교 (기능②)
- 연간 CII 등급 시뮬레이터 (기능③)
- 기상 데이터 연동 (Open-Meteo API, 실패 시 fallback)
- CSV 데이터 가져오기/내보내기

### 제외

- 규제 제출용 공식 CII 보고서 생성
- 자동 최적항로 추천
- AIS/IoT 실시간 연동
- 선대 통합 모니터링
- 사용자 권한·조직 관리 고도화

---

## 계산 규제 기준

- IMO CII (Carbon Intensity Indicator) 체계 기반
- MARPOL Annex VI Regulation 28 (5,000 GT 이상 선박)
- Z-factor: MEPC.400(83) 기준값 (2023–2030)
- 선종별 reference line: MEPC.353(78) (G2 Guidelines)
- 등급 경계 d-vector: MEPC.354(78) (G4 Guidelines)

> 본 플랫폼의 계산 결과는 공식 규제 제출용이 아닙니다. 참고용 예측값으로만 사용하세요.

---

## 마일스톤

| 시점 | 산출물 |
|---|---|
| 2026.07 | 계산 모듈·파라미터 seed·Fixture 테스트 |
| 2026.08 | 기능①·② 데모 (샘플 선박 기반) |
| 2026.09 | 1차 선정 제출 (기능①·② 수용 기준 충족) |
| 2026.10 | 기능③ 통합 시연 (연간 시뮬레이션·민감도 분석) |

---

## 참고 문헌

- [IMO EEXI and CII FAQ](https://www.imo.org/en/mediacentre/hottopics/pages/eexi-cii-faq.aspx)
- [MEPC.352(78) — CII Guidelines (G1)](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.352%2878%29.pdf)
- [MEPC.353(78) — CII Reference Lines (G2)](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.353%2878%29.pdf)
- [MEPC.354(78) — CII Rating Guidelines (G4)](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.354%2878%29.pdf)
- [MEPC.400(83) — CII Reduction Factors (G3)](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.400%2883%29.pdf)
- [Open-Meteo Marine Weather API](https://open-meteo.com/en/docs/marine-weather-api)

---

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준).
>
> **2026-07-23까지가 사후 복원분이다.** 이후 항목은 변경 시점에 직접 기록하며, squash merge로 브랜치 커밋 해시가 재작성되므로 커밋 열에는 **PR 번호**를 적는다.

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-06-13 | `c496fa6` | 저장소 최초 생성 |
| 2026-07-03 | `060beb5` | TECH_SPEC v1.1 추가에 따른 갱신 |
| 2026-07-03 | `eba6cb8` | API_SPEC v1.1 추가에 따른 갱신 |
| 2026-07-03 | `9f8a7eb` | 외부 리뷰 반영 (P0-1 capacity 규칙 분리, P0-2~5, P1) |
| 2026-07-03 | `8d48ba8` | DB_SCHEMA 완료 + 외부 리뷰 상태 반영 |
| 2026-07-03 | `efdcdbf` | TEST_PLAN v1.0 초안 추가에 따른 갱신 |
| 2026-07-03 | `f065755` | TEST_PLAN v1.1 (Oracle 리뷰 21건) 반영 |
| 2026-07-04 | `0f59999` | 외부 리뷰 P0/P1/P2 전체 반영 + AGENTS.md 추가 |
| 2026-07-04 | `bee61e9` | 문서 마감: canonical vector 고정 + 포맷 정리 |
| 2026-07-23 | `9febca6` | 서비스 레이어 아키텍처·모듈 구조 확정 (#100) |
| 2026-07-23 | `3a38d0c` | 재현성 계약 명문화 + weather 추적 컬럼 스펙 (#102) |
| 2026-07-29 | `#142` | 헤더·변경이력 표 신설 + 문서 구조 표에 DESIGN_SYSTEM·UIFLOW 2행 추가 |
