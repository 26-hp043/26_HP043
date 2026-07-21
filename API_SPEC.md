# API_SPEC — CII 예측 및 운항 의사결정 보조 플랫폼

| 항목 | 내용 |
|---|---|
| 문서명 | API_SPEC.md |
| 버전 | v1.2 |
| 상태 | Oracle Review + 외부 리뷰 반영 |
| 최종 수정일 | 2026-07-14 |
| 상위 문서 | `PRD.md` v3.1, `TECH_SPEC.md` v1.2 |
| 후속 문서 | `DB_SCHEMA.md`, `TEST_PLAN.md` |

---

## 0. 범위 및 목적

본 문서는 PRD §14의 API 요구사항 초안과 TECH_SPEC의 기술 명세를 기반으로 REST API 상세 명세를 정의한다.

### 0.1 설계 원칙

| 원칙 | 설명 |
|---|---|
| RESTful | HTTP method로 리소스 조작 의미 표현. 동사는 URL에 포함하지 않음 (예외: 계산 액션) |
| 버전 관리 | URL prefix `/api/v1/` 사용 |
| 일관된 응답 포맷 | 모든 응답은 동일한 JSON 구조 |
| 오류 코드 표준화 | TECH_SPEC §12 오류 분류에 따른 HTTP status code |
| 면책 고지 | 모든 계산 결과 응답에 `disclaimer` 및 `warnings` 포함 |

### 0.2 기준 문서

| 문서 | 참조 섹션 |
|---|---|
| PRD §14 | API 엔드포인트 초안 |
| TECH_SPEC §2.2.2 | `rng_metadata` 스키마 |
| TECH_SPEC §5.2.1 | `parameters_used` 스키마 |
| TECH_SPEC §10.1 | `model_version` 포맷 |
| TECH_SPEC §11 | 스냅샷 격리 |
| TECH_SPEC §12 | 오류 분류 및 전파 |
| TECH_SPEC §12.3 | Warning 코드 체계 |

---

## 1. 공통 사양

### 1.1 Base URL

```text
https://{host}/api/v1
```

MVP에서는 단일 인스턴스를 가정한다. 향후 멀티테넌트 확장 시 `/api/v1/orgs/{org_id}/` prefix 추가.

### 1.2 인증

MVP는 단일 조직·단일 역할을 가정하므로 인증을 최소화한다.

| 항목 | MVP 정책 |
|---|---|
| 인증 방식 | API Key (Header: `X-API-Key: {key}`) 또는 세션 쿠키 |
| 권한 분리 | 없음 (모든 사용자 동일 권한) |
| 향후 확장 | JWT + 역할 기반 접근 제어 (RBAC) |

> 파라미터 변경(POST/PATCH `/parameters/*`) 및 항차 확정(CONFIRMED 전환)은 감사 로그에 기록된다 (TECH_SPEC §13.1)。

### 1.3 공통 응답 포맷

#### 1.3.1 성공 응답

```json
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z"
  }
}
```

계산 결과를 포함하는 응답은 추가 필드:

```json
{
  "data": { ... },
  "parameters_used": { ... },
  "calculation_run_id": "uuid",
  "model_version": { ... },
  "input_hash": "sha256:...",
  "parameter_hash": "sha256:...",
  "warnings": ["REFERENCE_ONLY"],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z",
    "duration_ms": 142
  }
}
```

#### 1.3.2 오류 응답

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "운항 거리는 0보다 커야 합니다.",
    "details": [
      {
        "field": "distance_nm",
        "field_label": "운항 거리",
        "rule": "VAL-002",
        "message": "운항 거리는 0보다 커야 합니다."
      }
    ]
  },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z"
  }
}
```

### 1.4 HTTP Status Code 매핑

> TECH_SPEC §12.1 오류 분류에 따른 매핑.

| HTTP Status | Error Code | 발생 조건 |
|---|---|---|
| 200 OK | — | 성공 (warning 포함 가능). 기상 API 실패 시 NONE fallback으로 계산, `warnings`에 `WEATHER_NONE_FALLBACK` 포함 |
| 201 Created | — | 리소스 생성 성공 |
| 400 Bad Request | `BAD_REQUEST` | JSON 파싱 오류, 잘못된 Content-Type |
| 404 Not Found | `NOT_FOUND` | 존재하지 않는 리소스 ID |
| 409 Conflict | `PARAMETER_ERROR` | 규정 파라미터 누락 또는 불일치. 재현 시 파라미터 변경 |
| 422 Unprocessable Entity | `VALIDATION_ERROR` | VAL-001~010 위반 |
| 422 Unprocessable Entity | `CALCULATION_ERROR` | 분모 0, overflow, 음수 결과 |
| 422 Unprocessable Entity | `MODEL_BREAKDOWN_ERROR` | BN > 8, ΔV/V ≥ 100% |
| 422 Unprocessable Entity | `STATE_TRANSITION_ERROR` | 허용되지 않은 상태 전환 (PRD §8.1.1) |
| 422 Unprocessable Entity | `WEATHER_FETCH_ERROR` | 기상 API 실패 + 사용자가 NONE fallback을 명시적으로 거부 |
| 429 Too Many Requests | `RATE_LIMIT_EXCEEDED` | 분당 요청 한도 초과 |
| 500 Internal Server Error | `INTERNAL_ERROR` | 서버 내부 오류 |
| 500 Internal Server Error | `REPRODUCIBILITY_ERROR` | canonical test vector 불일치, 재현 결과 hash 불일치 |

> **[ORACLE-C-2 정정]** 기상 API 실패 처리 경로를 두 가지로 명확히 분리했다: (1) 200 OK + `WEATHER_NONE_FALLBACK` warning (사용자가 fallback 허용), (2) 422 `WEATHER_FETCH_ERROR` (사용자가 NONE 모델 거부). 이전의 503 매핑은 제거했다.

### 1.5 페이지네이션

목록 조회 API는 커서 기반 페이지네이션을 사용한다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `limit` | int | 20 | 페이지 크기 (최대 100) |
| `cursor` | string | null | 이전 응답의 `meta.next_cursor` |

```json
{
  "data": [ ... ],
  "meta": {
    "next_cursor": "eyJpZCI6IjEyMzQ1NiJ9...",
    "has_more": true
  }
}
```

### 1.6 Warning 코드

> TECH_SPEC §12.3 정의. 모든 계산 결과 응답의 `warnings` 배열에 포함.

> **[ORACLE-M-4 주의]** PRD §14.2 예시의 `REFERENCE_ONLY_NOT_FOR_REGULATORY_SUBMISSION`는 TECH_SPEC §12.3에 따라 `REFERENCE_ONLY`로 정규화되었다.

| 코드 | 조건 | 사용자 메시지 |
|---|---|---|
| `REFERENCE_ONLY` | 모든 계산 결과 | 참고용 예측값입니다. 규제 제출용이 아닙니다. |
| `WEATHER_STALE` | 기상 캐시 6~24시간 | 오래된 기상 데이터를 사용 중입니다. |
| `WEATHER_NONE_FALLBACK` | 기상 API 실패, NONE 모델 사용 | 기상 보정 없이 계산했습니다. |
| `CB_ESTIMATED` | block coefficient 추정값 사용 | 선형 계수가 추정값입니다. |
| `EXPERIMENTAL_MODEL` | TOWNSIN_KWON_ALPHA 사용 | 실험 모델 기반 결과입니다. |
| `NON_CII_VESSEL` | GT < 5,000 | 공식 CII 적용 대상이 아닐 수 있습니다. |
| `COMPLETED_NO_FUEL` | COMPLETED 항차 actual_fuel_ton NULL | 실적이 입력되지 않은 완료 항차입니다. 계획값을 임시 사용 중. |

### 1.7 수치 직렬화 정책

> **[ORACLE-C-1 추가]** TECH_SPEC의 이중 정밀도 엔진에 따라 API 응답의 수치 표현 방식을 레이어별로 구분한다.

| 레이어 | 대상 필드 | JSON 표현 | 정밀도 보장 |
|---|---|---|---|
| Layer 1 (결정론) | `attained_cii`, `required_cii`, `co2_emission_ton`, `next_worse_boundary_margin`, `ratio_to_required`, `effective_capacity` | **JSON 문자열** (예: `"4.982400"`) | 6+ 유효숫자. 클라이언트는 임의 정밀도 Decimal로 파싱 권장 |
| Layer 2 (Monte Carlo) | `p10`, `p50`, `p90`, `mean_cii`, `rating_probabilities.*`, `target_success_probability` | **JSON 숫자** (예: `0.0200`) | 4 유효숫자. float64 정밀도 |
| 입력/CRUD | `distance_nm`, `speed_kn`, `fuel_ton`, `gross_tonnage`, `deadweight` | **JSON 숫자** (예: `1000.0`) | 사용자 입력 정밀도 |

> 클라이언트는 `parameter_hash` + `input_hash`로 결과의 무결성을 검증한다. 값 자체의 bit-exact 비교는 JSON float 파싱으로 인해 신뢰할 수 없다.

### 1.8 멱등성 (Idempotency)

> **[ORACLE-MISS-1 추가]**

계산 POST 엔드포인트 (`/calculations/voyage-cii`, `/scenarios/compare`, `/annual-simulations`)는 **항상 새 `CalculationRun`을 생성**한다. 멱등성을 강제하지 않는다.

클라이언트가 동일 입력의 이전 결과를 재사용하려면 `input_hash` + `parameter_hash`로 기존 결과를 조회한다.

CRUD 엔드포인트(PATCH, PUT, DELETE)는 HTTP 표준 멱등성을 따른다.

### 1.9 CalculationRun 조회 API

> **[EXT-P1-2]** 재현성·캐싱·디버깅을 위한 계산 결과 조회 엔드포인트.

```http
GET /api/v1/calculations
```

**쿼리 파라미터:**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `input_hash` | string | N | `sha256:` + 64 hex chars |
| `parameter_hash` | string | N | `sha256:` + 64 hex chars |
| `type` | string | N | VOYAGE_ESTIMATE, SCENARIO, ANNUAL_DETERMINISTIC, ANNUAL_MONTE_CARLO |
| `vessel_id` | UUID | N | 선박 필터 |
| `limit` | int | N | 페이지 크기 (기본 20, 최대 100) |
| `cursor` | string | N | 페이지네이션 커서 |

**응답 (200 OK):**

```json
{
  "data": [
    {
      "calculation_run_id": "uuid",
      "calculation_type": "VOYAGE_ESTIMATE",
      "vessel_id": "uuid",
      "voyage_id": "uuid",
      "input_hash": "sha256:a1b2c3d4...",
      "parameter_hash": "sha256:e5f6g7h8...",
      "model_version": { ... },
      "result_summary": {
        "attained_cii": "4.982400",
        "estimated_rating": "C"
      },
      "created_at": "2026-07-03T12:00:00Z"
    }
  ],
  "meta": { ... }
}
```

> `input_hash` + `parameter_hash` 모두 지정 시 정확히 일치하는 계산 결과를 반환. 재현성 검증에 사용.


---

## 2. Vessel API

### 2.1 선박 목록 조회

```http
GET /api/v1/vessels?limit=20&cursor={cursor}
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `limit` | int | N | 페이지 크기 (기본 20, 최대 100) |
| `cursor` | string | N | 페이지네이션 커서 |
| `ship_type` | string | N | 선종 필터 |
| `search` | string | N | 선박명 또는 IMO 번호 검색 |

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "id": "uuid",
      "imo_number": "1234567",
      "name": "Pacific Star",
      "ship_type": "BULK_CARRIER",
      "gross_tonnage": 25000.0,
      "deadweight": 50000.0,
      "default_fuel_type": "HFO",
      "reference_speed_kn": 14.0,
      "reference_daily_foc_ton": 35.0,
      "is_cii_applicable_hint": true,
      "created_at": "2026-07-01T00:00:00Z",
      "updated_at": "2026-07-01T00:00:00Z"
    }
  ],
  "meta": {
    "next_cursor": null,
    "has_more": false,
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z"
  }
}
```

### 2.2 선박 상세 조회

```http
GET /api/v1/vessels/{vessel_id}
```

#### 응답 (200 OK)

§2.1의 단일 선박 객체와 동일.

#### 오류

| Status | Code | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않는 vessel_id |

### 2.3 선박 등록

```http
POST /api/v1/vessels
```

#### 요청 Body

```json
{
  "imo_number": "1234567",
  "name": "Pacific Star",
  "ship_type": "BULK_CARRIER",
  "gross_tonnage": 25000.0,
  "deadweight": 50000.0,
  "default_fuel_type": "HFO",
  "reference_speed_kn": 14.0,
  "reference_daily_foc_ton": 35.0
}
```

#### 검증 규칙

| 필드 | 규칙 | 오류 코드 |
|---|---|---|
| `imo_number` | 7자리 숫자 (VAL-003) | VAL-003 |
| `name` | 1~100자 | VAL-001 |
| `ship_type` | 파라미터 테이블 존재 (VAL-004) | VAL-004 |
| `gross_tonnage` | > 0 (VAL-002) | VAL-002 |
| `deadweight` | > 0 (VAL-002) | VAL-002 |
| `reference_speed_kn` | > 0 (VAL-002), 지정 시 | VAL-002 |

> `is_cii_applicable_hint`는 서버가 GT ≥ 5,000 및 선종 기준으로 자동 계산한다.

#### 응답 (201 Created)

§2.2와 동일한 선박 객체.

### 2.4 선박 수정

```http
PATCH /api/v1/vessels/{vessel_id}
```

#### 요청 Body

§2.3의 모든 필드는 optional. `imo_number`는 변경 불가.

> 선박 DWT/GT 변경 시 해당 선박의 미확정 계산 결과에 재계산 필요 표시가 설정된다 (PRD §8.4)。

#### 응답 (200 OK)

수정된 선박 객체.

### 2.5 선박 삭제

```http
DELETE /api/v1/vessels/{vessel_id}
```

#### 응답 (200 OK)

```json
{
  "data": {
    "id": "uuid",
    "deleted": true
  },
  "meta": { ... }
}
```

> 연관된 Voyage, CalculationRun이 있는 경우 soft delete. 완전 삭제는 관리자 권한 필요.

---

## 3. Voyage API

### 3.1 항차 목록 조회

```http
GET /api/v1/vessels/{vessel_id}/voyages?status=PLANNED&limit=20
```

> **[ORACLE-MISS-3 주의]** MVP에서는 선박별 항차 조회만 지원한다. 전체 선박의 항차를 통합 조회하는 글로벌 엔드포인트(`GET /api/v1/voyages`)는 MVP 범위 외이다. Dashboard는 클라이언트에서 다중 선박 조회 후 병합한다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `status` | string | N | 상태 필터 (DRAFT, PLANNED, IN_PROGRESS, COMPLETED, CONFIRMED, CANCELLED, ARCHIVED) |
| `regulation_year` | int | N | 기준연도 필터 |
| `annual_inclusion_policy` | string | N | EXCLUDE, INCLUDE_AS_PLAN, INCLUDE_AS_ACTUAL |
| `limit` | int | N | 페이지 크기 |
| `cursor` | string | N | 페이지네이션 커서 |

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "id": "uuid",
      "vessel_id": "uuid",
      "voyage_no": "V-2026-001",
      "status": "PLANNED",
      "departure_port_name": "Busan",
      "departure_lat": 35.0833,
      "departure_lon": 129.0,
      "arrival_port_name": "Rotterdam",
      "arrival_lat": 51.9244,
      "arrival_lon": 4.4778,
      "planned_distance_nm": 11000.0,
      "actual_distance_nm": null,
      "planned_speed_kn": 14.0,
      "actual_avg_speed_kn": null,
      "planned_departure_at": "2026-07-15T00:00:00Z",
      "planned_arrival_at": "2026-08-12T00:00:00Z",
      "actual_departure_at": null,
      "actual_arrival_at": null,
      "annual_inclusion_policy": "INCLUDE_AS_PLAN",
      "created_from": "MANUAL",
      "fuel_uses": [
        {
          "id": "uuid",
          "fuel_type": "HFO",
          "planned_fuel_ton": 800.0,
          "actual_fuel_ton": null,
          "cf_used": 3.114,
          "source": "USER_INPUT"
        }
      ],
      "notes": null,
      "created_at": "2026-07-01T00:00:00Z"
    }
  ],
  "meta": { ... }
}
```

### 3.2 항차 상세 조회

```http
GET /api/v1/voyages/{voyage_id}
```

#### 응답 (200 OK)

§3.1의 단일 항차 객체와 동일.

### 3.3 항차 생성

```http
POST /api/v1/vessels/{vessel_id}/voyages
```

#### 요청 Body

```json
{
  "voyage_no": "V-2026-001",
  "departure_port_name": "Busan",
  "departure_lat": 35.0833,
  "departure_lon": 129.0,
  "arrival_port_name": "Rotterdam",
  "arrival_lat": 51.9244,
  "arrival_lon": 4.4778,
  "planned_distance_nm": 11000.0,
  "planned_speed_kn": 14.0,
  "planned_departure_at": "2026-07-15T00:00:00Z",
  "planned_arrival_at": "2026-08-12T00:00:00Z",
  "fuel_uses": [
    {
      "fuel_type": "HFO",
      "planned_fuel_ton": 800.0,
      "source": "USER_INPUT"
    }
  ],
  "notes": "정기 항차"
}
```

> **[EXT-P0-4]** `annual_inclusion_policy`는 요청 본문에서 제외했다. 생성 시 `status = DRAFT`이며, DRAFT에서는 `annual_inclusion_policy = EXCLUDE`만 허용된다(§3.5 제약 매트릭스 참조). `PLANNED` 전환 시 `annual_inclusion_policy`를 `INCLUDE_AS_PLAN`으로 설정한다.

#### 응답 (201 Created)

생성된 항차 객체. 초기 `status = DRAFT`, `annual_inclusion_policy = EXCLUDE` (자동 설정).

### 3.4 항차 수정

```http
PATCH /api/v1/voyages/{voyage_id}
```

모든 필드는 optional. `status` 변경은 §3.5 참조.

### 3.5 항차 상태 전환

```http
POST /api/v1/voyages/{voyage_id}/transition
```

#### 요청 Body

```json
{
  "to_status": "PLANNED",
  "annual_inclusion_policy": "INCLUDE_AS_PLAN"
}
```

#### 상태 전환 규칙

> PRD §8.1.1, §8.1.2 기준.

| 전환 | 가드 조건 | 실패 시 |
|---|---|---|
| DRAFT → PLANNED | — | — |
| PLANNED → IN_PROGRESS | — | — |
| IN_PROGRESS → COMPLETED | 최소 1개 `actual_fuel_ton > 0` (ORACLE-C-4) | 422: 실적 입력 요청 |
| COMPLETED → CONFIRMED | 모든 `actual_fuel_ton > 0` 및 `actual_distance_nm > 0` | 422: 누락 실적 입력 요청 |
| CONFIRMED → COMPLETED | audit log 필수 (오류 정정 목적만) | 재확인 다이얼로그 표시 |
| CONFIRMED → ARCHIVED | audit log 필수. regulation_year < current_year 또는 수동 | — |
| PLANNED → CANCELLED | — | — |
| IN_PROGRESS → CANCELLED | — | — |

> **[ORACLE-C-4 추가]** `CONFIRMED → ARCHIVED` 전환을 추가했다. PRD §8.1 상태 다이어그램에 명시된 전환이다. 보관된 항차는 읽기 전용이며 `annual_inclusion_policy = EXCLUDE`로 자동 설정된다.

#### status × annual_inclusion_policy 제약

> PRD §8.1.2 (ORACLE-R-1). 허용되지 않은 조합은 자동으로 `EXCLUDE`로 보정하거나 전환을 거부한다.

| status | 허용 policy |
|---|---|
| DRAFT | EXCLUDE only (자동 설정) |
| PLANNED | EXCLUDE, INCLUDE_AS_PLAN |
| IN_PROGRESS | EXCLUDE, INCLUDE_AS_PLAN |
| COMPLETED | EXCLUDE, INCLUDE_AS_ACTUAL |
| CONFIRMED | EXCLUDE, INCLUDE_AS_ACTUAL |
| CANCELLED | EXCLUDE only (자동 설정) |
| ARCHIVED | EXCLUDE only (자동 설정) |

#### 응답 (200 OK)

```json
{
  "data": {
    "id": "uuid",
    "status": "PLANNED",
    "annual_inclusion_policy": "INCLUDE_AS_PLAN"
  },
  "meta": { ... }
}
```

#### 오류 (422)

```json
{
  "error": {
    "code": "STATE_TRANSITION_ERROR",
    "message": "IN_PROGRESS → COMPLETED 전환 시 최소 1개 actual_fuel_ton > 0이 필요합니다.",
    "details": [
      {
        "rule": "ORACLE-C-4",
        "message": "실적 연료 사용량을 입력하세요."
      }
    ]
  }
}
```

### 3.6 항차 실적 입력

```http
PUT /api/v1/voyages/{voyage_id}/actuals
```

#### 요청 Body

```json
{
  "actual_distance_nm": 11200.0,
  "actual_avg_speed_kn": 13.5,
  "actual_departure_at": "2026-07-15T08:00:00Z",
  "actual_arrival_at": "2026-08-13T12:00:00Z",
  "fuel_uses": [
    {
      "fuel_type": "HFO",
      "actual_fuel_ton": 850.0,
      "source": "USER_INPUT"
    }
  ]
}
```

#### 응답 (200 OK)

수정된 항차 객체. `status`는 변경하지 않는다 (별도 transition 호출 필요).

### 3.7 항차 삭제

> **[ORACLE-S-6 추가]**

```http
DELETE /api/v1/voyages/{voyage_id}
```

#### 삭제 규칙

| 현재 status | 처리 |
|---|---|
| DRAFT | Hard delete 허용 |
| CANCELLED | Hard delete 허용 |
| PLANNED, IN_PROGRESS | 422: 먼저 CANCELLED로 전환 필요 |
| COMPLETED, CONFIRMED, ARCHIVED | Soft delete only (감사 보존) |

#### 응답 (200 OK)

```json
{
  "data": {
    "id": "uuid",
    "deleted": true,
    "hard_delete": true
  },
  "meta": { ... }
}
```

---

## 4. Voyage CII Calculation API

### 4.1 항차 CII 추정 (기능①)

```http
POST /api/v1/calculations/voyage-cii
```

#### 요청 Body

```json
{
  "vessel_id": "uuid",
  "regulation_year": 2026,
  "distance_nm": 1000.0,
  "speed_kn": 12.0,
  "fuel_uses": [
    {
      "fuel_type": "HFO",
      "fuel_ton": 80.0
    }
  ],
  "weather_model": "NONE"
}
```

| 필드 | 타입 | 필수 | 검증 | 설명 |
|---|---|---|---|---|
| `vessel_id` | UUID | Y | 존재 확인 | 대상 선박 |
| `regulation_year` | int | Y | VAL-005: regulation_year 존재 | 등급 기준연도 |
| `distance_nm` | decimal | Y | VAL-002: > 0 | 항차 거리 |
| `speed_kn` | decimal | Y | VAL-009: ≥ 1.0 | 평균 예정 속도 |
| `fuel_uses` | array | Y | VAL-006: active fuel_type | 연료 사용량 목록 |
| `fuel_uses[].fuel_type` | string | Y | VAL-006 | 연료 코드 |
| `fuel_uses[].fuel_ton` | decimal | Y | VAL-002: > 0 | 연료 사용량 (ton) |
| `weather_model` | string | N | enum: NONE, SIMPLE_RULE, TOWNSIN_KWON_ALPHA | 기본: NONE |

#### 응답 (200 OK)

> **[ORACLE-C-1 정정]** Layer 1 결정론 값을 JSON 문자열로 직렬화한다 (§1.7 참조).
>
> **[ORACLE-C-3 추가]** `parameters_used`를 응답에 포함한다 (TECH_SPEC §5.2.1).
>
> **[ORACLE-S-5 정정]** `calculation_basis` 필드명을 TECH_SPEC과 통일했다 (`a_decimal`, `c`).

```json
{
  "data": {
    "attained_cii": "4.982400",
    "required_cii": "5.045066",
    "ratio_to_required": "0.98758",
    "estimated_rating": "C",
    "next_worse_boundary_margin": "0.365537",
    "next_worse_boundary_margin_ratio": "0.0725",
    "co2_emission_ton": "249.12",
    "fuel_consumption_ton": "80.00",
    "distance_nm": 1000.0,
    "risk_level": "MEDIUM",
    "transport_capacity": "50000",
    "transport_capacity_basis": "DWT",
    "reference_capacity": "50000",
    "reference_capacity_rule": "DWT",
    "calculation_basis": {
      "ship_type": "BULK_CARRIER",
      "z_factor_percent": "11.0",
      "fuel_cf_details": [
        { "fuel_type": "HFO", "cf": "3.114", "fuel_ton": "80.0" }
      ],
      "a_decimal": "4745",
      "c": "0.622"
    }
  },
  "parameters_used": {
    "regulation_year": {
      "year": "2026",
      "z_factor_percent": "11"
    },
    "fuel_types": [
      { "code": "HFO", "cf": "3.114" }
    ],
    "reference_line": {
      "ship_type": "BULK_CARRIER",
      "reference_capacity_rule": "DWT",
      "a_decimal": "4745",
      "c": "0.622"
    },
    "rating_boundary": {
      "d1": "0.86",
      "d2": "0.94",
      "d3": "1.06",
      "d4": "1.18"
    },
    "parameter_source_version": "imo-mepc-2024-q1"
  },
  "calculation_run_id": "uuid",
  "model_version": {
    "engine": "dual-precision-v1",
    "decimal_precision": 30,
    "decimal_rounding": "ROUND_HALF_UP",
    "rng_algorithm": "PCG64DXSM",
    "numpy_version": "2.1.0",
    "python_version": "3.12.4"
  },
  "input_hash": "sha256:a1b2c3d4...",
  "parameter_hash": "sha256:e5f6g7h8...",
  "warnings": [
    "REFERENCE_ONLY"
  ],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z",
    "duration_ms": 42
  }
}
```

> `risk_level` 산정 기준은 PRD §9.4.1 참조.

---

## 5. Scenario Comparison API (기능②)

### 5.1 시나리오 비교 계산

```http
POST /api/v1/scenarios/compare
```

#### 요청 Body

```json
{
  "vessel_id": "uuid",
  "regulation_year": 2026,
  "current_lat": 35.0,
  "current_lon": 129.0,
  "destination_port_name": "Rotterdam",
  "destination_lat": 51.9244,
  "destination_lon": 4.4778,
  "current_speed_kn": 14.0,
  "fuel_type": "HFO",
  "base_daily_foc_ton": 35.0,
  "direct_distance_nm": 11000.0,
  "detour_distance_nm": 11550.0,
  "slow_speed_kn": 13.0,
  "weather_model": "SIMPLE_RULE"
}
```

| 필드 | 타입 | 필수 | 검증 | 설명 |
|---|---|---|---|---|
| `vessel_id` | UUID | Y | 존재 확인 | 대상 선박 |
| `regulation_year` | int | Y | VAL-005 | 등급 기준연도 |
| `current_lat` | decimal | Y | VAL-007: −90 ~ +90 | 현재 위도 |
| `current_lon` | decimal | Y | VAL-007: −180 ~ +180 | 현재 경도 |
| `destination_lat` | decimal | 조건부 | VAL-007 | 목적항 위도 (거리 자동 계산 시 필요) |
| `destination_lon` | decimal | 조건부 | VAL-007 | 목적항 경도 |
| `current_speed_kn` | decimal | Y | VAL-009: ≥ 1.0 | 현재 속도 |
| `fuel_type` | string | Y | VAL-006 | 연료 종류 |
| `base_daily_foc_ton` | decimal | 조건부 | VAL-002 | 선박 기준값 없을 시 필요 |
| `direct_distance_nm` | decimal | 조건부 | VAL-002 | 좌표 있으면 자동 계산 |
| `detour_distance_nm` | decimal | N | VAL-002 | 기본: direct × 1.05 |
| `slow_speed_kn` | decimal | N | VAL-009: ≥ 1.0 | 감속 속도. **미지정 시 서버가 `max(current_speed - 1, 1.0)`으로 계산** |
| `weather_model` | string | N | enum | 기본: NONE |

#### 응답 (200 OK)

> **[ORACLE-S-1 정정]** 각 시나리오에 PRD §9.2 필수 출력 필드(`required_cii`, `ratio_to_required`, `next_worse_boundary_margin`, `calculation_basis`)를 추가했다.
>
> **[EXT-P0-5]** 각 시나리오에 `scenario_id`를 추가했다. 클라이언트는 이 ID로 `/scenarios/{scenario_id}/adopt`를 호출한다.
>
> **[EXT-3-1]** `calculation_basis`에 `transport_capacity`와 `reference_capacity`를 추가했다 (P0-1 이중 capacity 규칙).

```json
{
  "data": {
    "scenarios": [
      {
        "scenario_id": "550e8400-e29b-41d4-a716-446655440001",
        "scenario_type": "DIRECT",
        "scenario_name": "직항",
        "distance_nm": 11000.0,
        "speed_kn": 14.0,
        "duration_hours": 785.7,
        "fuel_ton": "780.00",
        "co2_emission_ton": "2428.90",
        "attained_cii": "4.982",
        "required_cii": "5.045066",
        "ratio_to_required": "0.98758",
        "estimated_rating": "C",
        "next_worse_boundary_margin": "0.365537",
        "next_worse_boundary_margin_ratio": "0.0725",
        "risk_level": "MEDIUM",
        "weather_factor": 1.0,
        "weather_model_used": "NONE",
        "calculation_basis": {
          "ship_type": "BULK_CARRIER",
          "transport_capacity": "50000",
          "transport_capacity_basis": "DWT",
          "reference_capacity": "50000",
          "reference_capacity_rule": "DWT",
          "z_factor_percent": "11.0",
          "a_decimal": "4745",
          "c": "0.622"
        }
      },
      {
        "scenario_id": "550e8400-e29b-41d4-a716-446655440002",
        "scenario_type": "DETOUR",
        "scenario_name": "우회",
        "distance_nm": 11550.0,
        "speed_kn": 14.0,
        "duration_hours": 825.0,
        "fuel_ton": "819.00",
        "co2_emission_ton": "2550.30",
        "attained_cii": "5.231",
        "required_cii": "5.045066",
        "ratio_to_required": "1.03687",
        "estimated_rating": "C",
        "next_worse_boundary_margin": "0.116537",
        "next_worse_boundary_margin_ratio": "0.0231",
        "risk_level": "HIGH",
        "weather_factor": 1.0,
        "weather_model_used": "NONE",
        "calculation_basis": {
          "ship_type": "BULK_CARRIER",
          "transport_capacity": "50000",
          "transport_capacity_basis": "DWT",
          "reference_capacity": "50000",
          "reference_capacity_rule": "DWT",
          "z_factor_percent": "11.0",
          "a_decimal": "4745",
          "c": "0.622"
        }
      },
      {
        "scenario_id": "550e8400-e29b-41d4-a716-446655440003",
        "scenario_type": "SLOW_STEAMING",
        "scenario_name": "감속",
        "distance_nm": 11000.0,
        "speed_kn": 13.0,
        "duration_hours": 846.2,
        "fuel_ton": "627.00",
        "co2_emission_ton": "1953.00",
        "attained_cii": "4.004",
        "required_cii": "5.045066",
        "ratio_to_required": "0.79360",
        "estimated_rating": "B",
        "next_worse_boundary_margin": "0.738050",
        "next_worse_boundary_margin_ratio": "0.1463",
        "risk_level": "LOW",
        "weather_factor": 1.0,
        "weather_model_used": "NONE",
        "calculation_basis": {
          "ship_type": "BULK_CARRIER",
          "transport_capacity": "50000",
          "transport_capacity_basis": "DWT",
          "reference_capacity": "50000",
          "reference_capacity_rule": "DWT",
          "z_factor_percent": "11.0",
          "a_decimal": "4745",
          "c": "0.622"
        }
      }
    ],
    "summary": {
      "lowest_cii_scenario": "SLOW_STEAMING",
      "shortest_duration_scenario": "DIRECT",
      "lowest_fuel_scenario": "SLOW_STEAMING"
    }
  },
  "parameters_used": { ... },
  "calculation_run_id": "uuid",
  "model_version": { ... },
  "input_hash": "sha256:...",
  "parameter_hash": "sha256:...",
  "warnings": [
    "REFERENCE_ONLY"
  ],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": { ... }
}
```

> `summary`는 특정 시나리오를 "추천"하지 않고, 지표별 최소값만 중립적으로 표시한다 (PRD §11.2, AC-F2-005).

### 5.2 시나리오 채택

```http
POST /api/v1/scenarios/{scenario_id}/adopt
```

선택한 시나리오를 Voyage 계획값으로 반영한다.

#### 요청 Body

```json
{
  "target_voyage_id": "uuid",
  "adopt_mode": "UPDATE_EXISTING_PLAN"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `target_voyage_id` | UUID | Y | 반영할 대상 항차 ID. `CREATE_NEW_VOYAGE` 모드 시 신규 항차 생성 |
| `adopt_mode` | string | N | 기본: `UPDATE_EXISTING_PLAN`. `CREATE_NEW_VOYAGE` 시 신규 항차 생성 (departure_port_name, arrival_port_name, planned_departure_at 추가 필요) |

#### 응답 (200 OK)

```json
{
  "data": {
    "voyage_id": "uuid",
    "adopted_scenario_type": "SLOW_STEAMING",
    "updated_fields": [
      "planned_distance_nm",
      "planned_speed_kn",
      "planned_arrival_at"
    ]
  },
  "meta": { ... }
}
```

> 시나리오 채택 시 해당 Voyage의 계산 결과는 무효화되고 재계산 필요 표시가 설정된다 (PRD §8.4)。

---

## 6. Annual CII Simulation API (기능③)

### 6.1 연간 시뮬레이션 실행

```http
POST /api/v1/annual-simulations
```

#### 요청 Body

```json
{
  "vessel_id": "uuid",
  "regulation_year": 2026,
  "target_rating": "B",
  "simulation_runs": 5000,
  "random_seed": 12345,
  "distribution_profile": "DEFAULT"
}
```

| 필드 | 타입 | 필수 | 검증 | 설명 |
|---|---|---|---|---|
| `vessel_id` | UUID | Y | 존재 확인 | 대상 선박 |
| `regulation_year` | int | Y | VAL-005 | 기준연도 |
| `target_rating` | string | Y | enum: A, B, C, D (E 불가, PRD §12.8) | 목표 등급 |
| `simulation_runs` | int | Y | 1000~10000 | Monte Carlo 반복 횟수 |
| `random_seed` | int/string | N | 0 ~ 2^128-1. 큰 값은 문자열로 전송 권장 | 미지정 시 서버가 128-bit entropy 자동 생성. 응답의 `rng_metadata.seed_entropy`에서 hex 형태로 반환 |
| `distribution_profile` | string | N | enum: DEFAULT | 기본: DEFAULT |

> **[ORACLE-S-3 정정]** `random_seed` 타입과 크기를 명확히 했다. JSON int는 2^53까지만 안전하게 표현 가능하므로, 큰 seed 값(2^53 초과)은 문자열로 전송해야 한다. 서버는 응답에서 항상 `rng_metadata.seed_entropy`에 128-bit hex 표기를 포함한다.

#### 오류

| Status | Code | 조건 |
|---|---|---|
| 422 | `VALIDATION_ERROR` | target_rating = E (PRD §12.8: 실행 거부) |
| 422 | `VALIDATION_ERROR` | 잔여 항차 200개 초과 (PRD §12.8: DoS 방지) |

#### 응답 (200 OK)

> **[ORACLE-S-2 정정]** 민감도 분석에 거리 ±5% 및 연료 CF 대체 시나리오를 추가했다 (PRD §12.6 전체 변수 커버).
>
> **[ORACLE-M-3 정정]** `interaction_note`를 JSON 응답에 포함했다.

```json
{
  "data": {
    "deterministic": {
      "projected_attained_cii": "5.02",
      "projected_rating": "C",
      "completed_voyage_count": 8,
      "remaining_voyage_count": 4,
      "completed_M_gco2": "1992960000",
      "completed_W_capacity_nm": "400000000",
      "planned_M_gco2": "996480000",
      "planned_W_capacity_nm": "200000000"
    },
    "monte_carlo": {
      "rng_metadata": {
        "seed_entropy": "0x000000000000000000000000003039",
        "bit_generator": "PCG64DXSM",
        "numpy_version": "2.1.0",
        "python_version": "3.12.4",
        "platform": "Linux-6.5.0-x86_64"
      },
      "runs": 5000,
      "rating_probabilities": {
        "A": 0.0200,
        "B": 0.2800,
        "C": 0.5500,
        "D": 0.1300,
        "E": 0.0200
      },
      "target_success_probability": 0.3000,
      "target_rating": "B",
      "p10": 4.71,
      "p50": 5.04,
      "p90": 5.42,
      "mean_cii": 5.06
    },
    "risk_level": "HIGH",
    "sensitivity_analysis": {
      "interaction_note": "각 변수의 개별 효과만 표시합니다. 복합 효과는 포함되지 않습니다.",
      "speed_minus_1kn": {
        "projected_cii": "4.85",
        "rating_change": "C→B",
        "target_probability_change": "+0.12"
      },
      "speed_plus_1kn": {
        "projected_cii": "5.21",
        "rating_change": "C→C",
        "target_probability_change": "-0.08"
      },
      "fuel_minus_10pct": {
        "projected_cii": "4.89",
        "rating_change": "C→B",
        "target_probability_change": "+0.10"
      },
      "fuel_plus_10pct": {
        "projected_cii": "5.18",
        "rating_change": "C→C",
        "target_probability_change": "-0.06"
      },
      "distance_minus_5pct": {
        "projected_cii": "4.96",
        "rating_change": "C→C"
      },
      "distance_plus_5pct": {
        "projected_cii": "5.08",
        "rating_change": "C→C"
      },
      "fuel_cf_alternative": {
        "alternative_fuel": "LNG",
        "alternative_cf": "2.750",
        "projected_cii": "4.42",
        "co2_change": "-21.1%",
        "rating_change": "C→B"
      },
      "voyage_minus_1": {
        "projected_cii": "5.12",
        "rating_change": "C→C"
      },
      "voyage_plus_1": {
        "projected_cii": "4.95",
        "rating_change": "C→C"
      }
    },
    "snapshot": {
      "snapshot_id": "uuid",
      "created_at": "2026-07-03T12:00:00Z",
      "voyage_count": 12
    }
  },
  "parameters_used": { ... },
  "calculation_run_id": "uuid",
  "model_version": { ... },
  "input_hash": "sha256:...",
  "parameter_hash": "sha256:...",
  "warnings": [
    "REFERENCE_ONLY"
  ],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z",
    "duration_ms": 2840
  }
}
```

> **스냅샷 격리** (TECH_SPEC §11): 시뮬레이션 시작 시점의 모든 항차 데이터를 스냅샷으로 복사한다. 시뮬레이션 실행 중 발생하는 상태 변경은 진행 중인 시뮬레이션에 영향을 주지 않는다.

### 6.2 연간 시뮬레이션 결과 조회

```http
GET /api/v1/annual-simulations/{simulation_run_id}
```

#### 응답 (200 OK)

§6.1의 응답과 동일. `calculation_run_id`로 저장된 결과를 재조회한다.

### 6.3 스냅샷 항차 상세 조회

> **[ORACLE-S-7 추가]**

```http
GET /api/v1/annual-simulations/{simulation_run_id}/snapshot-voyages
```

시뮬레이션 시작 시점의 스냅샷에 포함된 항차 데이터를 조회한다.

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "snapshot_voyage_id": "uuid",
      "original_voyage_id": "uuid",
      "voyage_no": "V-2026-001",
      "status_at_snapshot": "CONFIRMED",
      "distance_nm": 11200.0,
      "speed_kn": 13.5,
      "fuel_uses": [
        { "fuel_type": "HFO", "fuel_ton": 850.0, "cf_used": 3.114 }
      ],
      "annual_inclusion_policy": "INCLUDE_AS_ACTUAL"
    }
  ],
  "meta": { ... }
}
```

### 6.4 동일 seed로 재실행

```http
POST /api/v1/annual-simulations/{simulation_run_id}/reproduce
```

동일 vessel_id, regulation_year, random_seed, simulation_runs, distribution_profile로 재실행한다.

#### 응답 (200 OK)

§6.1의 응답과 동일. 결과는 동일해야 한다 (재현성 보장).

#### 오류

> **[ORACLE-S-4 추가]**

| Status | Code | 조건 |
|---|---|---|
| 409 Conflict | `PARAMETER_ERROR` | 원본 실행 이후 규정 파라미터가 변경됨. `parameter_hash` 불일치. |
| 500 Internal Server Error | `REPRODUCIBILITY_ERROR` | 재현 결과의 `input_hash` 또는 Monte Carlo 결과가 원본과 불일치. canonical test vector 실패 가능. |

---

## 7. Parameter API

### 7.1 규정 연도 조회

```http
GET /api/v1/parameters/regulation-years
```

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "year": 2026,
      "z_factor_percent": "11.0",
      "effective_from": "2026-01-01",
      "source_ref": "MEPC.400(83)",
      "version": "2024-q1"
    }
  ],
  "meta": { ... }
}
```

### 7.2 연료 종류 조회

```http
GET /api/v1/parameters/fuel-types?active=true
```

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "code": "HFO",
      "display_name": "Heavy Fuel Oil",
      "cf": "3.114",
      "unit": "tCO₂/tFuel",
      "source_ref": "MEPC.352(78)",
      "is_active": true
    }
  ],
  "meta": { ... }
}
```

### 7.3 선종별 Reference Line 조회

```http
GET /api/v1/parameters/reference-lines?ship_type=BULK_CARRIER
```

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "ship_type": "BULK_CARRIER",
      "condition_expr": "DWT >= 279000",
      "capacity_rule": "fixed 279000",
      "a_raw": "4745",
      "a_decimal": "4745",
      "c": "0.622",
      "source_ref": "MEPC.353(78)"
    },
    {
      "ship_type": "BULK_CARRIER",
      "condition_expr": "DWT < 279000",
      "capacity_rule": "DWT",
      "a_raw": "4745",
      "a_decimal": "4745",
      "c": "0.622",
      "source_ref": "MEPC.353(78)"
    }
  ],
  "meta": { ... }
}
```

### 7.4 등급 경계 조회

```http
GET /api/v1/parameters/rating-boundaries?ship_type=BULK_CARRIER
```

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "ship_type": "BULK_CARRIER",
      "condition_expr": "all",
      "capacity_basis": "DWT",
      "d1": "0.86",
      "d2": "0.94",
      "d3": "1.06",
      "d4": "1.18",
      "source_ref": "MEPC.354(78)"
    }
  ],
  "meta": { ... }
}
```

### 7.5 파라미터 Import

```http
POST /api/v1/parameters/import
```

#### 요청 Body

```json
{
  "format": "JSON",
  "source_ref": "MEPC.400(83) 2024 update",
  "data": {
    "regulation_years": [
      { "year": 2027, "z_factor_percent": 13.625 }
    ],
    "fuel_types": [],
    "reference_lines": [],
    "rating_boundaries": []
  }
}
```

#### 응답 (200 OK)

```json
{
  "data": {
    "imported": {
      "regulation_years": 1,
      "fuel_types": 0,
      "reference_lines": 0,
      "rating_boundaries": 0
    },
    "validation_passed": true
  },
  "meta": { ... }
}
```

> Import 시 `parse_imo_scientific` 검증(TECH_SPEC §9.2)과 `a_raw/a_decimal` 일치 검증(TECH_SPEC §9.3)을 수행한다. 검증 실패 시 409 Conflict.

---

## 8. Data Import/Export API

### 8.1 CSV 내보내기

```http
GET /api/v1/vessels/{vessel_id}/export?type=voyages&year=2026&format=csv
```

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `type` | string | Y | `voyages`, `calculations`, `simulations` |
| `year` | int | N | 기준연도 필터 |
| `format` | string | N | `csv` (기본), `json` |

#### 응답 (200 OK)

```http
Content-Type: text/csv
Content-Disposition: attachment; filename="voyages_2026.csv"

voyage_no,status,departure,arrival,distance_nm,speed_kn,fuel_type,fuel_ton,co2_ton,attained_cii,rating
V-2026-001,CONFIRMED,Busan,Rotterdam,11200,13.5,HFO,850,2646.9,5.32,C
...
```

### 8.2 CSV 가져오기

```http
POST /api/v1/vessels/{vessel_id}/import
```

#### 요청 (multipart/form-data)

| 필드 | 타입 | 설명 |
|---|---|---|
| `file` | file | CSV 파일 |
| `type` | string | `voyages` |

#### 보안 제한

> **[ORACLE-MISS-2 추가]**

| 항목 | 제한 |
|---|---|
| 최대 파일 크기 | 5MB |
| 최대 행 수 | 1,000행 |
| 인코딩 | UTF-8 (BOM optional) |
| Content-Type 검증 | `text/csv`, `application/vnd.ms-excel` 허용. 그 외 거부 |
| 수식 주입 방지 | 셀 값이 `=`, `@`, `+`, `-`로 시작하는 경우 앞에 `'` (apostrophe)를 prefix하여 escape (formula injection 방지). 숫자 컬럼은 numeric parser로 검증하여 문자열 수식 거부 |
| 필수 컬럼 | `voyage_no`, `departure_port_name`, `arrival_port_name`, `planned_distance_nm`, `planned_speed_kn`, `fuel_type`, `planned_fuel_ton` |

#### 응답 (200 OK)

```json
{
  "data": {
    "imported_count": 12,
    "skipped_count": 1,
    "errors": [
      { "row": 5, "field": "distance_nm", "message": "0보다 커야 합니다." }
    ]
  },
  "meta": { ... }
}
```

---

## 9. Weather API (내부)

> 이 엔드포인트는 내부 디버깅용이며, 일반 사용자에게는 노출되지 않는다.

### 9.1 기상 스냅샷 조회

```http
GET /api/v1/weather/snapshot?lat=35.0&lon=129.0
```

#### 응답 (200 OK)

```json
{
  "data": {
    "lat": 35.0,
    "lon": 129.0,
    "fetched_at": "2026-07-03T11:30:00Z",
    "wave_height_m": 1.5,
    "wave_direction_deg": 45.0,
    "wave_period_s": 6.0,
    "wind_speed_ms": 8.0,
    "wind_direction_deg": 90.0,
    "source": "open_meteo_marine",
    "age_hours": 0.5,
    "freshness": "FRESH"
  },
  "meta": { ... }
}
```

| freshness | 조건 |
|---|---|
| `FRESH` | age ≤ 6h |
| `STALE` | 6h < age ≤ 24h |
| `EXPIRED` | age > 24h |

### 9.2 기상 수동 갱신

```http
POST /api/v1/weather/refresh?lat=35.0&lon=129.0
```

Open-Meteo API에서 최신 데이터를 강제로 가져온다.

---

## 10. Health Check

> **[ORACLE-M-5 추가]**

```http
GET /api/v1/health
```

로드 밸런서 및 모니터링용 헬스 체크 엔드포인트. 인증 불필요.

#### 응답 (200 OK)

```json
{
  "data": {
    "status": "ok",
    "version": "1.0.0",
    "numpy_version": "2.1.0",
    "rng_canonical_test": "passed"
  }
}
```

---

## 11. 검증 규칙 요약

> PRD §9.1의 모든 검증 규칙을 API 응답에 매핑한다.

| Rule ID | 규칙 | 오류 응답 |
|---|---|---|
| VAL-001 | 필수값 비어 있음 | 422: `{field_label}을/를 입력하세요.` (`field_label`는 한글 라벨) |
| VAL-002 | 거리·속도·연료·DWT·GT ≤ 0 | 422: `{field_label}는 0보다 커야 합니다.` (`field_label`는 한글 라벨) |
| VAL-003 | IMO 번호 형식 오류 | 422: `IMO 번호는 7자리 숫자여야 합니다.` |
| VAL-004 | 지원하지 않는 선종 | 422: `지원하지 않는 선종입니다.` |
| VAL-005 | 기준연도 파라미터 없음 | 409: `해당 연도의 규정 파라미터가 없습니다.` |
| VAL-006 | 지원하지 않는 연료 | 422: `지원하지 않는 연료입니다.` |
| VAL-007 | 좌표 범위 오류 | 422: `좌표 형식이 올바르지 않습니다.` |
| VAL-008 | NaN·Infinity 결과 | 422: `계산 오류: 입력값을 확인하세요.` |
| VAL-009 | 속도 < 1.0kn | 422: `속도는 1.0노트 이상이어야 합니다.` |
| VAL-010 | capacity ≤ 0 | 422: `선박 용량 정보가 부족합니다.` |

---

## 12. 엔드포인트 요약

| Method | Path | 기능 | PRD 참조 |
|---|---|---|---|
| GET | `/api/v1/health` | 헬스 체크 | — |
| GET | `/api/v1/vessels` | 선박 목록 | §6.2 SCR-002 |
| POST | `/api/v1/vessels` | 선박 등록 | §6.2 SCR-002 |
| GET | `/api/v1/vessels/{id}` | 선박 상세 | §6.2 SCR-002 |
| PATCH | `/api/v1/vessels/{id}` | 선박 수정 | §6.2 SCR-002 |
| DELETE | `/api/v1/vessels/{id}` | 선박 삭제 | §6.2 SCR-002 |
| GET | `/api/v1/vessels/{id}/voyages` | 항차 목록 | §6.2 SCR-003 |
| POST | `/api/v1/vessels/{id}/voyages` | 항차 생성 | §6.2 SCR-003 |
| GET | `/api/v1/voyages/{id}` | 항차 상세 | §6.2 SCR-003 |
| PATCH | `/api/v1/voyages/{id}` | 항차 수정 | §6.2 SCR-003 |
| DELETE | `/api/v1/voyages/{id}` | 항차 삭제 | §8.1 |
| POST | `/api/v1/voyages/{id}/transition` | 항차 상태 전환 | §8.1 |
| PUT | `/api/v1/voyages/{id}/actuals` | 항차 실적 입력 | §17.2 |
| POST | `/api/v1/calculations/voyage-cii` | 항차 CII 추정 | §10 (기능①) |
| GET | `/api/v1/calculations` | 계산 결과 조회 (hash 기반) | §1.9 |
| POST | `/api/v1/scenarios/compare` | 시나리오 비교 | §11 (기능②) |
| POST | `/api/v1/scenarios/{id}/adopt` | 시나리오 채택 | §11.8 |
| POST | `/api/v1/annual-simulations` | 연간 시뮬레이션 | §12 (기능③) |
| GET | `/api/v1/annual-simulations/{id}` | 시뮬레이션 결과 조회 | §12 |
| GET | `/api/v1/annual-simulations/{id}/snapshot-voyages` | 스냅샷 항차 상세 | TECH_SPEC §11 |
| POST | `/api/v1/annual-simulations/{id}/reproduce` | 동일 seed 재실행 | §12.4.3 |
| GET | `/api/v1/parameters/regulation-years` | 규정 연도 조회 | §6.2 SCR-006 |
| GET | `/api/v1/parameters/fuel-types` | 연료 조회 | §6.2 SCR-006 |
| GET | `/api/v1/parameters/reference-lines` | Reference line 조회 | §6.2 SCR-006 |
| GET | `/api/v1/parameters/rating-boundaries` | 등급 경계 조회 | §6.2 SCR-006 |
| POST | `/api/v1/parameters/import` | 파라미터 Import | §6.2 SCR-006 |
| GET | `/api/v1/vessels/{id}/export` | CSV 내보내기 | §6.2 SCR-007 |
| POST | `/api/v1/vessels/{id}/import` | CSV 가져오기 | §6.2 SCR-007 |
| GET | `/api/v1/weather/snapshot` | 기상 스냅샷 (내부) | §15.3 |
| POST | `/api/v1/weather/refresh` | 기상 수동 갱신 (내부) | §15.3 |

---

## 13. 비기능 요구사항 (API 관점)

### 13.1 성능 목표

> PRD §16.1 기준.

| 엔드포인트 | 목표 |
|---|---|
| `POST /calculations/voyage-cii` | p95 < 1초 |
| `POST /scenarios/compare` | p95 < 5초, 캐시 시 < 2초 |
| `POST /annual-simulations` (결정론) | p95 < 1초 |
| `POST /annual-simulations` (Monte Carlo 5000) | p95 < 3초 |
| 기본 CRUD | p95 < 500ms |

### 13.2 Rate Limiting

| 항목 | MVP 정책 |
|---|---|
| 계산 API | 분당 60회 / 사용자 |
| CRUD API | 분당 300회 / 사용자 |
| 초과 시 | 429 Too Many Requests |

### 13.3 CORS

| 항목 | 정책 |
|---|---|
| 허용 Origin | 동일 출처 또는 명시적 화이트리스트 |
| 허용 Method | GET, POST, PATCH, PUT, DELETE, **OPTIONS** |
| 허용 Header | Content-Type, X-API-Key, Authorization |

### 13.4 API 버전 관리

| 항목 | 정책 |
|---|---|
| 현재 버전 | v1 |
| 버전 표기 | URL prefix `/api/v1/` |
| 하위 호환성 | 필드 추가는 허용. 필드 제거/이름 변경은 v2 필요. |
| Deprecation | 최소 6개월 전 공지. `Deprecation` header 응답에 포함. |

---

## 14. Oracle Review Corrections (v1.1)

> 본 섹션은 Oracle 기술 검토(2026-07-03)에서 식별된 이슈를 기록하고, 각 이슈의 수정 위치와 상태를 추적한다.

### 14.1 Critical Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-C-1 | Layer 1 Decimal 값을 JSON number로 직렬화하여 정밀도 손실. JS `JSON.parse`가 float64로 truncation. | §1.7 수치 직렬화 정책 추가. Layer 1 값은 JSON 문자열로 직렬화 | **수정 완료** |
| API-ORACLE-C-2 | `WeatherFetchError` HTTP 매핑이 TECH_SPEC §12.1과 불일치. 503이 TECH_SPEC에 없음. | §1.4 status code 테이블 수정. 503 제거, 200+warning 및 422 두 경로로 분리 | **수정 완료** |
| API-ORACLE-C-3 | `parameters_used`가 계산 응답에 누락. TECH_SPEC §15.1에서 필수 의존성으로 명시. | §1.3.1, §4.1, §5.1, §6.1 응답에 `parameters_used` 추가 | **수정 완료** |
| API-ORACLE-C-4 | `CONFIRMED → ARCHIVED` 상태 전환 누락. PRD §8.1 상태 다이어그램에 명시됨. | §3.5 전환 테이블에 추가 | **수정 완료** |

### 14.2 Significant Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-S-1 | 시나리오 응답에 PRD §9.2 필수 필드 누락 (required_cii, ratio_to_required 등) | §5.1 각 시나리오 객체에 추가 | **수정 완료** |
| API-ORACLE-S-2 | 민감도 분석이 PRD §12.6의 5개 변수 중 3개만 커버. 거리 ±5%, 연료 CF 대체 누락 | §6.1 sensitivity_analysis에 추가 | **수정 완료** |
| API-ORACLE-S-3 | `random_seed` 타입/크기 불명확. JSON int는 2^53까지만 안전 | §6.1 필드 설명에 타입/범위 명시 | **수정 완료** |
| API-ORACLE-S-4 | reproduce 엔드포인트의 오류 시나리오 미정의 | §6.4 오류 테이블 추가 (409, 500) | **수정 완료** |
| API-ORACLE-S-5 | `calculation_basis` 필드명이 TECH_SPEC과 불일치 (a_coefficient vs a_decimal) | §4.1, §5.1 — TECH_SPEC 명명법(a_decimal, c)으로 통일 | **수정 완료** |
| API-ORACLE-S-6 | 항차 삭제 엔드포인트 없음 | §3.7 DELETE /voyages/{id} 추가 | **수정 완료** |
| API-ORACLE-S-7 | 스냅샷 항차 상세 조회 불가 | §6.3 GET /annual-simulations/{id}/snapshot-voyages 추가 | **수정 완료** |

### 14.3 Minor Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-M-1 | `slow_speed_kn`이 required이면서 기본값이 있어 모순 | §5.1 — optional로 변경 | **수정 완료** |
| API-ORACLE-M-2 | CORS 허용 method에 OPTIONS 누락 | §13.3 — OPTIONS 추가 | **수정 완료** |
| API-ORACLE-M-3 | `interaction_note`가 JSON 응답에 없음 | §6.1 — sensitivity_analysis 내에 추가 | **수정 완료** |
| API-ORACLE-M-4 | warning 코드가 PRD 예시와 상이 | §1.6 — 정규화 노트 추가 | **수정 완료** |
| API-ORACLE-M-5 | 헬스 체크 엔드포인트 없음 | §10 — GET /health 추가 | **수정 완료** |

### 14.4 Missing Topics

| ID | 누락 항목 | 추가 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-MISS-1 | 계산 엔드포인트 멱등성 정책 누락 | §1.8 멱등성 섹션 추가 | **추가 완료** |
| API-ORACLE-MISS-2 | CSV import 보안 제한 미정의 | §8.2 보안 제한 테이블 추가 | **추가 완료** |
| API-ORACLE-MISS-3 | 선박 간 항차 통합 조회 불가 | §3.1 — MVP 범위 외로 명시 | **추가 완료** |

### 14.5 검토 요약

- **API_SPEC 품질 평가**: v1.0은 구조적으로 건전하나 수치 직렬화 정책 미정의(C-1), `parameters_used` 누락(C-3)이 Critical. v1.1에서 모두 해결.
- **하위 문서 준비도**: v1.1은 DB_SCHEMA, TEST_PLAN이 참조할 모든 API 계약을 포함. 수치 직렬화 정책(§1.7), 멱등성(§1.8), 오류 분류(§1.4), 보안 제한(§8.2)이 명확히 정의되어 하위 문서 작성이 차단 없이 진행 가능.

### 14.6 외부 리뷰 반영 (v1.2)

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
|| EXT-P0-1 | `effective_capacity`를 단일 값으로 사용 → IMO G1/G2 이중 capacity 분리 필요 | §4.1, §5.1 — `transport_capacity`/`reference_capacity` 분리 | **수정 완료** |
|| EXT-P0-4 | Voyage 생성 API에서 DRAFT + INCLUDE_AS_PLAN 충돌 | §3.3 — `annual_inclusion_policy`를 요청에서 제거, DRAFT는 EXCLUDE 강제 | **수정 완료** |
|| EXT-P0-5 | Scenario compare 응답에 `scenario_id` 누락 | §5.1 — 각 시나리오에 `scenario_id` 추가 | **수정 완료** |
|| EXT-3.1 | 시나리오 응답에 capacity 필드 누락 | §5.1 — `calculation_basis`에 capacity 필드 추가 | **수정 완료** |
| EXT-3.3/P1-5 | CSV formula injection strip이 데이터 훼손 위험 | §8.2 — strip 대신 apostrophe escape로 변경 | **수정 완료** |
| EXT-3.4/P1-6 | 오류 메시지 한국어 조사 처리 (`{field}은/는`) | §1.3.2, §11 — `field_label` 한글 라벨 도입 | **수정 완료** |
|| EXT-P1-2/3.2 | CalculationRun 조회 API 상세 누락 | §1.9 (신규) — GET /api/v1/calculations 상세 스펙 추가 | **추가 완료** |
- **수정 소요**: Critical + Significant 이슈 해결에 약 2~3시간 소요 (문서 수정 기준).

---

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준). 버전 번호 매핑은 커밋 메시지·헤더 기준의 추정을 포함한다.

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-07-03 | `eba6cb8` | v1.1 최초 작성 |
| 2026-07-03 | `9f8a7eb` | 외부 리뷰 반영 (capacity 규칙 분리 등) |
| 2026-07-04 | `0f59999` | 외부 리뷰 P0/P1/P2 전체 반영 + AGENTS.md 추가 |
| 2026-07-04 | `af3b752` | Oracle 리뷰 4건 문서 정합성 수정 |
| 2026-07-04 | `bee61e9` | 포맷 정리 |
| 2026-07-04 | `ec1bf23` | Oracle 3차 리뷰 반영 (F-006~F-008) → v1.2 |
| 2026-07-14 | `0173105` | annotation 라벨 번호 정규화 (5개 정본 일괄) |
