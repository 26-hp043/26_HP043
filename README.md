# 중소선사를 위한 CII 예측 및 운항 의사결정 보조 플랫폼

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
| [`TECH_SPEC.md`](./TECH_SPEC.md) | 기술 명세서 (v1.1, Oracle Review + 외부 리뷰 반영) — 이중 정밀도 엔진, PCG64DXSM RNG, capacity 분리(transport/reference), canonical hashing, 스냅샷 격리 | ✅ 완료 |
| [`API_SPEC.md`](./API_SPEC.md) | REST API 명세서 (v1.1, Oracle Review + 외부 리뷰 반영) — 29개 엔드포인트, 수치 직렬화 정책, field_label 오류 체계, CSV escape 보안 | ✅ 완료 |
| [`DB_SCHEMA.md`](./DB_SCHEMA.md) | 데이터베이스 스키마 (v1.1, Oracle Review 반영) — 14개 테이블, PostgreSQL 16, FK ON DELETE 정책, immutable 트리거, 마이그레이션 전략 | ✅ 완료 |
| [`TEST_PLAN.md`](./TEST_PLAN.md) | 테스트 계획서 (v1.0 Draft) — 104개 테스트 케이스, Fixture 1~4, 이중 capacity 검증, Decimal/Monte Carlo 비교 방식, DB 제약 테스트 | ✅ 완료 |

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
