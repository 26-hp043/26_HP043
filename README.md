# 중소선사를 위한 CII 예측 및 운항 의사결정 보조 플랫폼

| 항목 | 내용 |
|---|---|
| 문서명 | README.md |
| 버전 | v1.0 |
| 상태 | 운영 중 — 저장소 진입점 |
| 최종 수정일 | 2026-08-15 |
| 하위 문서 | `PRD.md`, `TECH_SPEC.md`, `API_SPEC.md`, `DB_SCHEMA.md`, `TEST_PLAN.md`, `AGENTS.md`, `DESIGN_SYSTEM.md`, `UIFLOW.md` |
| 문서 목적 | 프로젝트 개요·문서 구조·MVP 범위를 안내한다. 규범적 내용은 각 정본이 소유하며 본 문서는 요약만 담는다 |

중소선사가 **보유 선박 전체의 IMO 탄소집약도(CII) 등급을 상시 관리**할 수 있도록 지원하는 웹 기반 플랫폼입니다. 정보 구조는 **선대 → 선박 → 항차** 3계층이며, 각 계층의 결과를 조합해 보고서로 산출합니다.

> **면책 조항**: 본 플랫폼은 운항 의사결정을 보조하는 예측·시뮬레이션 도구입니다. 규제 제출용 공식 CII 계산 시스템이 아니며, 최종 운항 판단은 사용자에게 있습니다.

---

## 핵심 기능

| 계층 | 기능 | 설명 |
|---|---|---|
| **선대** | **대시보드** | 보유 선박 전체의 현 등급·운항 상태·위치를 한 화면에서 조망하고 위험 선박을 식별 |
| **선박** | **선박 상세** | 연도별 CII 이력, 올해 누적(YTD) 등급, 현재 위치·상태 |
| **선박** | 연간 CII 시뮬레이터 | 누적 실적 + 잔여 계획 기반 연말 예상 등급, 목표 달성 확률(Monte Carlo), 민감도 분석 |
| **항차** | **실시간 CII** | 항해 중 누적값 변화, 남은 거리 기반 연말 예상 등급, 정박 지속 시 등급 하락 반영 |
| **항차** | 항차 CII 추정 | 출항 전 항차 조건 입력 → CII 추정값, CO₂ 배출량, 예상 등급, 위험도 (실시간 산출의 계획 단계) |
| **항차** | 운항 시나리오 비교 | 직항·우회·감속 시나리오별 연료·CII·소요시간 중립 비교 (보고서의 사후 설명 근거) |
| **산출물** | **보고서** | 항차 완료 리포트 · 연간 실적 리포트 (PDF · CSV) |

---

## 문서 구조

| 문서 | 내용 | 상태 |
|---|---|---|
| [`PRD.md`](./PRD.md) | 제품 요구사항 정의서 (**v4.0**, 관리 중심 전환 #343, Oracle Review + 외부 리뷰 반영 + 선종별 CII 지표·단위 #163) — 이중 capacity 규칙(G1/G2 분리), 상태 모델, 검증 규칙 | ✅ 완료 |
| [`TECH_SPEC.md`](./TECH_SPEC.md) | 기술 명세서 (v1.4, Oracle Review + 외부 리뷰 반영 + 서비스 레이어 아키텍처 #100 + 재현성 계약 명문화 #102 + Layer 1 계산 규칙 #166) — 이중 정밀도 엔진, Layer 1 계산 규칙(§1.2.1), PCG64DXSM RNG(canonical vector 고정), capacity 분리(transport/reference), canonical hashing, 스냅샷 격리, 서비스 레이어 아키텍처(§16), 재현성 계약(§5.4) | ✅ 완료 |
| [`API_SPEC.md`](./API_SPEC.md) | REST API 명세서 (v1.4, Oracle Review + 외부 리뷰 반영 + 인증(#272) + PATCH null 의미론·전환 policy 규칙 #310·#312) — 30개 엔드포인트, 수치 직렬화 정책, field_label 오류 체계, CSV escape 보안 | ✅ 완료 |
| [`DB_SCHEMA.md`](./DB_SCHEMA.md) | 데이터베이스 스키마 (v1.5, Oracle Review + 외부 리뷰 반영 + weather 추적 컬럼 스펙 #102 + 파라미터 CHECK·FK 자식 인덱스 #96·#97 + needs_recalc 플립 #283) — 14개 테이블, PostgreSQL 16, FK ON DELETE 정책, immutable 트리거, pg_trgm, 마이그레이션 전략 | ✅ 완료 |
| [`TEST_PLAN.md`](./TEST_PLAN.md) | 테스트 계획서 (v1.5, Oracle Review + 외부 리뷰 반영 + Layer 1 픽스처 정본값 규칙 #166 + §1.3 케이스 스키마 #46 + §4.7 인증 API #279) — 181개 테스트 케이스, Fixture 1~4, 정본값 생성기 계약(§1.7), 이중 capacity 검증, Layer 변환/감사 로그/소프트 삭제/CSV injection 테스트, 유효숫자 기반 Monte Carlo 비교 | ✅ 완료 |
| [`AGENTS.md`](./AGENTS.md) | AI 에이전트 작업 규칙 — Oracle 교차 검증 규칙, 규제값 권위 소스, 한국어 정책 | ✅ 신규 |
| [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) | 디자인 토큰 계약서 (v1.1, §4.1 단위 표기 capacity 축 파생 #163) — 컬러·타이포그래피·숫자 포맷·차트 규약·접근성. 토큰의 이름·의미·제약을 확정하고 값은 Figma가 소유 | ✅ 신규 |
| [`UIFLOW.md`](./UIFLOW.md) | UI Flow 명세서 (**v2.0**, 선대·선박·항차 3계층 재작성 #344) — 화면 흐름·진입 조건 정의 | 🟡 초안 |

---

## MVP 범위

### 포함

- **선대 대시보드 및 위험 선박 경고 배너**
- **선박 상세 — 연도별 CII 이력 · 올해 누적(YTD) 등급 · 현재 위치·운항 상태**
- **실시간 CII 산출 — 항해 중 누적값 · 연말 예상 등급 · 정박 반영**
- **보고서 — 항차 완료 리포트 · 연간 실적 리포트 (PDF · CSV)**
- 연도별 운항 기록 관리 (CSV 가져오기/내보내기)
- 항차 CII 추정 (기능①) · 운항 시나리오 비교 (기능②) · 연간 CII 등급 시뮬레이터 (기능③)
- 선박 등록·관리 및 샘플 선박 제공
- 규정 파라미터 관리 (Z-factor, 선종별 reference line, d-vector, 연료 CF)
- 기상 데이터 연동 (Open-Meteo API, 실패 시 fallback)
- 사용자 인증 (구글 OIDC)

### 제외

- 규제 제출용 공식 CII 보고서 생성 (내부 보고용 리포트는 포함)
- 자동 최적항로 추천
- AIS/IoT **자동** 위치 수집 — 위치·운항 상태 데이터 자체는 포함
- 지도 기반 항로 렌더링
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

## 작업 조직 축 — 레이어

**마일스톤 체제를 폐지했습니다.** 기능①②③ 축으로 짠 시간 버킷이 관리 중심 전환 뒤에는 성립하지 않아, **레이어**를 1차 조직 축으로 씁니다. 순서는 이슈 간 선후 관계로 관리합니다.

| 라벨 | 레이어 | 범위 |
|---|---|---|
| `layer:base` | L0 기반 | 배포·시드·스키마·표기 — 전 레이어의 토대 |
| `layer:fleet` | L1 선대 | 대시보드 · 경고 배너 |
| `layer:vessel` | L2 선박 | 상세 · 연도별 이력 · YTD · 연간 시뮬 |
| `layer:voyage` | L3 항차 | 실시간 CII · 시나리오 · 운항 기록 |
| `layer:report` | L4 산출물 | 항차 완료 · 연간 실적 리포트 |
| `layer:cross` | LX 횡단 | 품질 · 운영 · 추적 |
| `layer:backlog` | LB 백로그 | 현 범위 밖 |

전체 의존 관계와 이슈 매트릭스는 **[#93](https://github.com/26-hp043/26_HP043/issues/93)** 에 있습니다.

> 완료된 `2026.07` 마일스톤(closed 35건)만 기록으로 남아 있습니다.

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
| 2026-08-06 | `#180` | 문서 구조 표의 `TEST_PLAN.md` 행을 v1.3으로, `TECH_SPEC.md` 행을 v1.4로 갱신 — §1.7 정본값 생성기 계약·§1.2.1 계산 규칙 신설 반영 (#166) |
| 2026-08-07 | `#196` | 문서 구조 표 갱신 — `PRD` v3.2 · `DESIGN_SYSTEM` v1.1 (#163) |
| 2026-08-07 | `#195` | 문서 구조 표의 `TEST_PLAN.md` 행을 v1.4로 갱신 — §1.3 케이스 스키마 기호 표기 전환 반영 (#46) |
| 2026-08-07 | `#137` | 문서 구조 표에 `docs/DEMO_CHECKLIST.md` 행 추가 후 철회 — 시연 확인용 개인 문서라 저장소 밖으로 옮김. 기대값은 `demoPath.test.ts`가 계속 고정한다 |
| 2026-08-15 | `#___` | **관리 중심 전환 반영.** 소개 문장·핵심 기능 표를 3계층 기준으로 교체 · MVP 포함 목록에 대시보드·선박 상세·실시간 CII·보고서 추가 · 제외 목록에서 「선대 통합 모니터링」 삭제하고 AIS 항목을 「자동 수집」으로 한정 · **마일스톤 표를 레이어 축 설명으로 교체**(마일스톤 체제 폐지) · 문서 구조 표 `PRD v4.0`·`UIFLOW v2.0` 갱신 (#349) |
