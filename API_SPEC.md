# API_SPEC — CII 예측 및 운항 의사결정 보조 플랫폼

| 항목 | 내용 |
|---|---|
| 문서명 | API_SPEC.md |
| 버전 | v1.9 |
| 상태 | Oracle Review + 외부 리뷰 반영 |
| 최종 수정일 | 2026-08-15 |
| 상위 문서 | `PRD.md` v4.0, `TECH_SPEC.md` v1.5 |
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

MVP는 **구글 OIDC 인증 + 서버 세션 쿠키**를 사용한다. 단일 조직·단일 역할을 가정하므로 권한 분리는 두지 않는다 (PRD §5.2 · §20 O-13).

| 항목 | MVP 정책 |
|---|---|
| 인증 방식 | 구글 OIDC (Authorization Code + PKCE) → 서버 발급 세션 쿠키 `sid` |
| 쿠키 속성 | `HttpOnly` · `Secure` · `SameSite=Lax` · `Path=/` |
| 권한 분리 | 없음. 인증된 모든 사용자가 동일 권한을 가진다 |
| 데이터 격리 | 없음. 선박·항차 데이터는 전 사용자가 공유한다 (PRD §5.2) |
| 미인증 응답 | `401 UNAUTHORIZED` |
| CSRF | 상태 변경 요청(POST·PATCH·DELETE)에 `X-CSRF-Token` 헤더 요구 |
| 향후 확장 | 역할 기반 접근 제어(RBAC), 사용자별 데이터 격리 |

**인증 예외 경로** — 다음은 세션 없이 접근할 수 있다.

| 경로 | 사유 |
|---|---|
| `GET /health` | 헬스 체크 |
| `GET /auth/login` · `GET /auth/callback` | 인증 플로우 자체 |

그 밖의 모든 `/api/v1/*` 경로는 유효한 세션을 요구한다. 인증 엔드포인트 명세는 아래 표를 참조한다.

> 파라미터 변경(POST/PATCH `/parameters/*`) 및 항차 확정(CONFIRMED 전환)은 감사 로그에 기록된다 (TECH_SPEC §13.1). **인증 도입에 따라 `audit_log.user_id`에 `app_user.id`를 기록한다.**

**인증 엔드포인트** — §1.2 인증 정책에 따른 엔드포인트 (#272).

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| `GET` | `/auth/login?redirect_to={path}` | 불필요 | 구글 인증 화면으로 302. `redirect_to`는 앱 내부 경로만 허용 |
| `GET` | `/auth/callback?code={code}&state={state}` | 불필요 | 토큰 교환 → `id_token` 검증 → 세션 발급 → `redirect_to`로 302 |
| `GET` | `/auth/me` | **필요** | 현재 사용자 정보 (id, email, display_name). `google_sub`는 미노출 |
| `POST` | `/auth/logout` | **필요** | 세션 즉시 무효화 + 쿠키 만료. 멱등 (세션 없어도 204) |

> `id_token` 검증 항목: 서명(JWKS) · `iss` · `aud` · `exp` · `nonce` · `email_verified=true`.
> 개발 환경(`APP_ENV != production`)에서는 `POST /auth/dev-login` 스텁 경로를 추가한다 — 고정 테스트 사용자로 세션 발급. **production에서는 라우트 자체를 등록하지 않는다.**

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

> **`message` 언어 규정**: `error.message`·`details[].message`는 `field_label`과 동일하게 **한국어**로 작성한다 (§1.4의 프레임워크 발생 오류 포함). 프레임워크(Starlette/FastAPI) 기본 영문 문구(`'Not Found'`, `'Method Not Allowed'`)를 그대로 내보내지 않는다.

### 1.4 HTTP Status Code 매핑

> TECH_SPEC §12.1 오류 분류에 따른 매핑.

| HTTP Status | Error Code | 발생 조건 |
|---|---|---|
| 200 OK | — | 성공 (warning 포함 가능). 기상 API 실패 시 NONE fallback으로 계산, `warnings`에 `WEATHER_NONE_FALLBACK` 포함 |
| 201 Created | — | 리소스 생성 성공 |
| 400 Bad Request | `BAD_REQUEST` | JSON 파싱 오류, 잘못된 Content-Type |
| 401 Unauthorized | `UNAUTHORIZED` | 세션 없음, 세션 만료, 세션 무효 |
| 403 Forbidden | `CSRF_ERROR` | CSRF 토큰 누락 또는 불일치 |
| 404 Not Found | `NOT_FOUND` | 존재하지 않는 리소스 ID |
| 404 Not Found | `NOT_FOUND` | 존재하지 않는 **경로** (프레임워크 자동 발생 — `#183`에서 §1.3.2 포맷으로 변환). 리소스 ID 미존재와 동일한 코드를 쓴다 |
| 405 Method Not Allowed | `METHOD_NOT_ALLOWED` | 경로는 존재하나 HTTP 메서드가 허용되지 않음 (프레임워크 자동 발생 — `#183`에서 변환) |
| 409 Conflict | `PARAMETER_ERROR` | 규정 파라미터 누락 또는 불일치. 재현 시 파라미터 변경 |
| 409 Conflict | `CONFLICT` | 리소스 중복 (예: 동일 IMO 번호 선박 재등록) |
| 422 Unprocessable Entity | `VALIDATION_ERROR` | VAL-001~010 위반 |
| 422 Unprocessable Entity | `CALCULATION_ERROR` | 분모 0, overflow, 음수 결과 |
| 422 Unprocessable Entity | `MODEL_BREAKDOWN_ERROR` | BN > 8, ΔV/V ≥ 100% |
| 422 Unprocessable Entity | `STATE_TRANSITION_ERROR` | 허용되지 않은 상태 전환 (PRD §8.1.1) |
| 422 Unprocessable Entity | `WEATHER_FETCH_ERROR` | 기상 API 실패 + 사용자가 NONE fallback을 명시적으로 거부 |
| 429 Too Many Requests | `RATE_LIMIT_EXCEEDED` | 분당 요청 한도 초과 |
| 500 Internal Server Error | `INTERNAL_ERROR` | 서버 내부 오류 |
| 500 Internal Server Error | `REPRODUCIBILITY_ERROR` | canonical test vector 불일치, 재현 결과 hash 불일치 |
| 미등록 status (403·415 등) | `HTTP_ERROR` | §1.4 표에 없는 status를 만났을 때의 범용 코드 — 모든 status에 걸쳐 쓰므로 단일 status를 붙이지 않는다 (`#183`에서 변환) |

> **[#182] `HTTPException` 변환 정책** — 이 절에서 정의한 `NOT_FOUND`(경로 404)·`METHOD_NOT_ALLOWED`(405)·`HTTP_ERROR`(미등록 status) 3개 코드는 **우리가 `AppError`로 raise하지 않고, 프레임워크(Starlette/FastAPI) 자동 발생 오류와 라우트의 명시적 `HTTPException` 양쪽에 모두 적용**된다. `errors.py`의 `ERROR_HTTP_STATUS`(error_code → 단일 status 매핑)에는 **넣지 않는다** — `METHOD_NOT_ALLOWED`는 405 하나에 고정되지만 `AppError`가 아니고, `HTTP_ERROR`는 여러 status에 걸쳐 쓰여 단일 매핑이 불가능하다 (`NOT_FOUND`는 기존 리소스 ID 미존재 매핑이 그대로 쓰인다). `METHOD_NOT_ALLOWED`·`HTTP_ERROR`의 HTTP status는 **프레임워크 예외의 `status_code`를 그대로 보존**한다. 구현은 `#183`에서 담당한다.
>
> **프레임워크 발생 오류의 사용자 노출 문구 (한국어)**
>
> | status | 문구 |
> |---|---|
> | 404 (경로 없음) | `"요청한 경로를 찾을 수 없습니다."` |
> | 405 Method Not Allowed | `"허용되지 않은 HTTP 메서드입니다."` |
> | 미등록 status (403·415 등) | `"요청을 처리할 수 없습니다."` |
> | 그 외 등록 status | §1.3.2 포맷의 해당 `error_code` 문구를 따른다 |
>
> ※ 404의 경우 리소스 ID 미존재(`NOT_FOUND`)와 경로 미존재가 같은 HTTP status를 쓰므로 같은 코드 `NOT_FOUND`를 공유한다. 다만 사용자 문구는 위 표처럼 구분한다.

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
| `SLOW_SPEED_FLOOR` | 기능② 감속 시나리오 속도가 최소 속도(1.0kn)에 도달 (PRD §11.2 「floor 도달 시 경고 표시」) | 감속 시나리오가 최소 속도(1.0kn)로 운항합니다. 속도 기반 연료 추정의 신뢰도가 낮습니다. |

### 1.7 수치 직렬화 정책

> **[ORACLE-C-1 추가]** TECH_SPEC의 이중 정밀도 엔진에 따라 API 응답의 수치 표현 방식을 레이어별로 구분한다.

| 레이어 | 대상 필드 | JSON 표현 | 정밀도 보장 |
|---|---|---|---|
| Layer 1 (결정론) | 결정론 계산에서 생성되거나 Decimal로 표현되는 수치 응답 (예: `attained_cii`, `required_cii`). **`parameters_used.*` · `calculation_basis.*`의 파라미터 값도 문자열이다.** | **JSON 문자열** (예: `"4.982400"`) | **[#132 정정]** 문자열로 직렬화하여 JSON float 파싱에 의한 정밀도 손실을 방지한다. 구체적인 필드 경로와 JSON 표현은 각 endpoint의 응답 계약(응답 예시 및 명시된 타입 표)을 따른다. |
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
      "needs_recalc": false,
      "created_at": "2026-07-03T12:00:00Z"
    }
  ],
  "meta": { ... }
}
```

> `input_hash` + `parameter_hash` 모두 지정 시 정확히 일치하는 계산 결과를 반환. 재현성 검증에 사용.
>
> `needs_recalc` — 선박 DWT/GT 변경 시 `true`로 플립된다(PRD §8.4 · #283). 계산 결과 자체는 immutable이라 바뀌지 않으며, 화면은 이 플래그로 재계산 권고를 표시한다. `false`로 되돌아가는 일은 없다.

### 1.10 `as_of` 공통 계약 — 시각 의존 계산 (#368)

> 정본 근거는 `TECH_SPEC §5.4.1`이다. 여기에는 **API 표면의 규약**만 적는다.

`PRD §1 COR-5`가 MVP에서 AIS·IoT 연동을 제외하므로 값이 저절로 변하지 않는다. 「실시간 CII」는 서버의 **시뮬레이션 시계**가 시각으로부터 누적량을 만들어 성립시키며, 그때 재현성을 지키는 장치가 `as_of`다.

**요청**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `as_of` | string (ISO 8601, UTC) | 아니오 | 계산 기준 시각. 미지정 시 서버가 현재 시각을 확정한다 |

```http
GET /vessels/{id}/cii/current?as_of=2026-08-15T15:00:00Z
```

**응답** — 시각 의존 엔드포인트는 `meta.as_of`에 **실제 사용한 값을 반드시 포함**한다.

```json
{
  "data": { "...": "..." },
  "meta": {
    "as_of": "2026-08-15T15:00:00Z",
    "is_simulated": true
  }
}
```

| 필드 | 의미 |
|---|---|
| `meta.as_of` | 이 응답을 만든 기준 시각. **이 값으로 다시 요청하면 같은 결과가 나온다** |
| `meta.is_simulated` | 시뮬레이션 시계가 만든 값인지. `true`면 화면은 「시뮬레이션 데이터」 배지를 표시한다(`PRD R-5`). 실적이 확정된 구간은 `false` |

**보장**

1. **같은 `as_of` + 같은 입력 → 항상 같은 결과** (`TECH_SPEC §5.4` 1항).
2. `as_of`는 `input_hash`에 포함된다. `as_of`가 다르면 **다른 계산**이며, 이는 §5.4 2항이 규정한 의도된 동작이다.
3. `as_of`를 넘기지 않는 기존 엔드포인트(기능① `/calculations/voyage-cii` 등)의 `input_hash`는 이 계약 도입으로 **달라지지 않는다** — 해시 필터가 입력에 존재하는 키만 담기 때문이다.

**오류**

| 상황 | 응답 |
|---|---|
| `as_of` 형식이 ISO 8601이 아님 | `422` · `VALIDATION_ERROR` (§1.4) |

> `as_of`가 미래이거나 출항 이전인 것 자체는 오류가 아니다. 진행량이 0이 되거나 도착 시각에서 멈출 뿐이며, 경계 처리는 `TECH_SPEC §5.4.1`의 표를 따른다.

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
      "underway_state": "UNDER_WAY",
      "detail_status": "SAILING",
      "current_lat": 35.1,
      "current_lon": 129.04,
      "position_updated_at": "2026-08-15T06:00:00Z",
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

### 2.6 선박 위치·운항 상태 갱신 (#369)

```http
PATCH /api/v1/vessels/{vessel_id}/position
```

마이그레이션 026(`#346`)이 추가한 위치·상태 컬럼을 바꾸는 **유일한 경로**다. 이 엔드포인트가 없으면 대시보드(`#351`)의 「지금 어디서 무엇을 하고 있나」가 시드 이후 고정된다.

> **왜 저장인가 (파생이 아니라)** — 상태 2축은 진행 중 `not_underway_period`에서 파생할 수 있으나 **위경도는 파생할 수 없다.** 항로 모델이 없어 「지금 어디쯤」을 유도할 방법이 없고, `#346`이 이미 저장 컬럼으로 만들었다. 둘을 갈라 한쪽만 파생시키면 같은 화면의 두 값이 서로 다른 시점을 가리킨다.
>
> **조회 경로에서 갱신하지 않는다.** `#350` 선대 요약이 단순 SELECT로 끝나야 하며, 쓰기를 조회에 섞으면 GET이 트랜잭션을 잡는다.

#### 요청 본문

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `underway_state` | string | 아니오 | `UNDER_WAY` / `NOT_UNDER_WAY` |
| `detail_status` | string | 아니오 | `UNDER_WAY`면 `SAILING`. `NOT_UNDER_WAY`면 `IN_PORT`/`AT_ANCHOR`/`DRIFTING`/`STS`/`CANAL_TRANSIT`/`DRYDOCK` |
| `current_lat` | number | 아니오 | −90 ~ 90 |
| `current_lon` | number | 아니오 | −180 ~ 180 |

`position_updated_at`은 **요청에 넣을 수 없다** — `extra="forbid"`가 422로 거부한다. 클라이언트 시계를 신뢰하면 「언제 기준 위치인가」가 단말마다 갈리므로 **서버가 확정**한다.

#### 함께 보내야 하는 쌍

마이그레이션 026의 CHECK 제약을 스키마 표면에 그대로 옮긴 규칙이다.

| 규칙 | 위반 시 |
|---|---|
| `underway_state`와 `detail_status`는 **함께** 지정 | `422` · `VALIDATION_ERROR` |
| 두 상태의 조합이 허용 집합에 있어야 함 | `422` — 예: `UNDER_WAY` + `AT_ANCHOR` |
| `current_lat`과 `current_lon`은 **함께** 지정 | `422` |

`detail_status`의 `NOT_UNDER_WAY` 6값은 `not_underway_period.period_type`(마이그레이션 025)과 **같은 집합**이다 — 정박 구간의 성격이 곧 선박의 표시 상태가 된다.

#### 응답 (200 OK)

§2.2와 동일한 선박 객체. `position_updated_at`에 서버가 확정한 시각이 들어간다.

> **빈 본문(`{}`)은 200이지만 `position_updated_at`을 건드리지 않는다.** 갱신하지 않은 것을 갱신했다고 기록하면 「낡은 값인지」 판별이 무의미해진다.

#### 인증

다른 변경 API와 동일하게 세션 쿠키 + `X-CSRF-Token`을 요구한다. `#307`(변경 API 8종이 인증 게이트 밖에 노출)의 선례에 따라 **새 변경 엔드포인트는 게이트 배선을 테스트로 확인**한다.

---

### 2.7 선박 연도별 CII 이력 조회 (#355)

```http
GET /api/v1/vessels/{vessel_id}/cii-history?from=2025&to=2026
```

선박 상세 화면(`UIFLOW §2-8`)의 **연도별 CII 이력** 축. 연도별 집계는 YTD 엔진(#353)을 그대로 위임한다 — 이 엔드포인트의 소관은 **창·상태 구분**이다.

> **`transport_capacity_basis` (#356 추가).** 응답 최상위에 표시 단위의 축(`DWT` · `GT`)을 함께 싣는다. `DESIGN_SYSTEM §4.1` 🔒이 `gCO₂/(DWT·nm)`과 `gCO₂/(GT·nm)`을 **선종에 따라 갈리는 값**으로 규정하고 고정 문자열을 금지하기 때문이다. 화면이 선종에서 축을 유추하면 선종이 늘 때 서버와 갈라지고, **크루즈선에 `DWT`가 표시돼도 화면은 깨지지 않아 발견이 늦다.** 축을 정하는 것은 `calc.capacity.capacity_axis`이며 그 결과를 그대로 반환한다. 연도별로 달라지지 않는 선박 속성이라 `years` 안이 아니라 최상위에 둔다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `from` | integer | 아니오 | 시작 연도. 기본 `to - 2` (최근 3년 창) |
| `to` | integer | 아니오 | 종료 연도. 기본 `as_of` 연도(올해) |
| `as_of` | string(ISO 8601) | 아니오 | 확정/진행 중 판정 기준 시각. 미지정이면 서버 현재 시각. **응답 `meta.as_of`를 그대로 되돌려 보내면 같은 결과를 얻는다** (#368 계약 ⑶ — 재현성) |

**검증 (422 · `VALIDATION_ERROR`)** — `from ≥ 2019` · `from ≤ to` · 창 ≤ 10년.

#### 연도 행 구조

| 필드 | 타입 | 설명 |
|---|---|---|
| `regulation_year` | integer | 규제 연도 |
| `status` | string | `CONFIRMED`(과거 연도, 확정) / `IN_PROGRESS`(`as_of` 연도 이상, YTD) |
| `data_available` | boolean | 집계 가능한 실적이 있는가 |
| `reason` | string \| null | `NO_REGULATION_PARAMS` — 해당 연도 `regulation_year` 행 없음. `NO_DATA` — 파라미터는 있으나 집계할 실적 없음 |
| `attained_cii` | string \| null | 연도 누적 attained CII (6자리) |
| `required_cii` | string \| null | 해당 연도 required CII (6자리) |
| `rating` | string \| null | A~E. `IN_PROGRESS` 연도는 **YTD 등급** — 공식 등급이 아니다(`PRD §3.3.8`) |
| `voyage_count` | integer | 실적 확정(`INCLUDE_AS_ACTUAL`) 항차 수 |
| `total_distance_nm` | string \| null | 두 갈래(항해 + not under way) 거리 합 (2자리) |
| `total_fuel_ton` | string \| null | 두 갈래 연료 합 (2자리). `data_available=false`여도 거리·연료 값 자체는 실릴 수 있다 |

> **파라미터가 없는 해도 요청 전체가 실패하지 않는다.** 그 해만 `data_available=false` + `reason=NO_REGULATION_PARAMS` 행으로 내보낸다 — 한 해 파라미터 미적재로 3년 이력 전체가 409로 죽으면 화면이 아무것도 그리지 못한다.

> **`INCLUDE_AS_PLAN` 항차는 세지 않는다.** 진행 중 항차의 실시간 기여분(시뮬레이션 시계)은 `GET /vessels/{id}/cii/current`(#354)의 소관이다.

#### 응답 예시 (200 OK)

```json
{
  "data": {
    "vessel_id": "00000000-0000-4000-8000-000000000001",
    "from": 2024,
    "to": 2026,
    "years": [
      {
        "regulation_year": 2024,
        "status": "CONFIRMED",
        "data_available": false,
        "reason": "NO_DATA",
        "attained_cii": null,
        "required_cii": null,
        "rating": null,
        "voyage_count": 0,
        "total_distance_nm": "0.00",
        "total_fuel_ton": "0.00"
      },
      {
        "regulation_year": 2025,
        "status": "CONFIRMED",
        "data_available": true,
        "reason": null,
        "attained_cii": "5.841032",
        "required_cii": "5.158439",
        "rating": "D",
        "voyage_count": 1,
        "total_distance_nm": "4265.00",
        "total_fuel_ton": "400.00"
      },
      {
        "regulation_year": 2026,
        "status": "IN_PROGRESS",
        "data_available": true,
        "reason": null,
        "attained_cii": "8.979907",
        "required_cii": "5.045066",
        "rating": "E",
        "voyage_count": 1,
        "total_distance_nm": "4300.00",
        "total_fuel_ton": "620.00"
      }
    ]
  },
  "meta": {
    "request_id": "req-8f14e45f",
    "timestamp": "2026-08-15T06:00:00Z",
    "as_of": "2026-08-15T00:00:00+00:00"
  }
}
```

#### 오류

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 선박 없음 |
| 422 | `VALIDATION_ERROR` | 창 규칙 위반 (`from > to` · 창 > 10년 · `from < 2019`) |

---

### 2.8 선대 요약 조회 (#350)

```http
GET /api/v1/fleet/summary?regulation_year=2026&as_of=2026-08-16T12:00:00Z
```

대시보드(`UIFLOW §2-4` · `PRD §6.2 SCR-001`)가 **한 번의 호출로** 선대 전체 현황과 경고 배너 데이터를 받는다.

> **왜 별도 엔드포인트인가.** `GET /vessels`는 선박 제원만 반환하고 등급·위치·상태 요약이 없다. 화면이 선박마다 개별 조회를 돌면 10척에 21회 호출이 된다.

> **계산을 다시 하지 않는다.** 선박별 YTD 값·등급·위험도는 `#353`의 YTD 엔진(`services.ytd_cii`)을 그대로 위임한다. 이 엔드포인트의 소관은 **모으기·판정·집계**다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `regulation_year` | integer | 아니오 | 집계 대상 규제연도. 기본 `as_of` 연도 |
| `as_of` | string | 아니오 | 기준 시각 (ISO 8601 UTC). 미지정 시 서버가 확정하고 응답에 실어 반환한다 (`TECH_SPEC §5.4.1` 계약 ⑵) |

#### 응답 (200 OK)

```json
{
  "data": {
    "as_of": "2026-08-16T12:00:00+00:00",
    "regulation_year": 2026,
    "summary": {
      "total": 10,
      "under_way": 7,
      "not_under_way": 3,
      "unknown_state": 0,
      "rating_distribution": { "A": 2, "B": 2, "C": 3, "D": 2, "E": 1 },
      "at_risk": 2,
      "no_data": 0
    },
    "vessels": [
      {
        "vessel_id": "uuid",
        "name": "MV Hanla",
        "ship_type": "BULK_CARRIER",
        "imo_number": "9100001",
        "underway_state": "UNDER_WAY",
        "detail_status": "SAILING",
        "current_lat": "35.100000",
        "current_lon": "129.040000",
        "position_updated_at": "2026-08-16T11:00:00+00:00",
        "data_available": true,
        "ytd_attained_cii": "9.4200",
        "ytd_required_cii": "5.0450",
        "ytd_rating": "E",
        "risk_level": "CRITICAL",
        "risk_reasons": ["E_THIS_YEAR"],
        "days_to_d": null,
        "days_to_d_reason": "ALREADY_AT_OR_BELOW"
      }
    ],
    "actions": [
      {
        "vessel_id": "uuid",
        "vessel_name": "MV Hanla",
        "severity": "critical",
        "reason": "E_THIS_YEAR",
        "message": "E등급 1년차 — SEEMP Part III 시정조치계획 대상"
      }
    ]
  },
  "meta": { "request_id": "...", "timestamp": "...", "as_of": "..." }
}
```

#### `risk_level`과 `risk_reasons`는 다른 것을 본다

| 필드 | 근거 | 의미 |
|---|---|---|
| `risk_level` | `PRD §9.4.1` | 표시용 4단계 — LOW · MEDIUM · HIGH · CRITICAL. 「지금 여유가 얼마나 있나」 |
| `risk_reasons` | `PRD §3.3.7` | **규제 트리거** — 「MARPOL Reg 28.7에 걸렸나」 |

C등급이어도 여유가 없으면 `risk_level`은 `HIGH`지만 규제 의무는 없고, D등급 3년차는 여유와 무관하게 의무가 생긴다. **하나로 합치면 조치 목록에 사유를 쓸 수 없다.**

`risk_reasons` 값은 `PRD §3.3.7`의 판정 기준을 그대로 따른다.

| 값 | 조건 |
|---|---|
| `E_THIS_YEAR` | 올해 YTD 등급이 **E** |
| `D_THIRD_YEAR` | 직전 2개 규제연도의 확정 등급이 연속 **D**이고 올해 YTD도 **D** |

> 기준이 **연말 예상 등급이 아니라 YTD 등급**이다. 예상 등급은 Monte Carlo 종속이라 같은 화면을 두 번 열면 값이 달라질 수 있어, `PRD §3.3.7`이 그 기준을 후속 이슈로 연기했다.

#### `days_to_d` — 「D등급 진입까지 n일」

숫자를 내지 못하는 경우 `days_to_d`는 `null`이고 `days_to_d_reason`이 사유를 준다. **숫자를 못 낸 것과 0일인 것은 다르므로** 같은 자리에 넣지 않는다.

| `days_to_d_reason` | 조건 |
|---|---|
| `ALREADY_AT_OR_BELOW` | 이미 D 이하 — 「진입까지」가 정의되지 않음 |
| `NOT_THIS_YEAR` | 외삽 결과가 연말을 넘음 |
| `NOT_UNDER_WAY` | **정박 중 — 산정하지 않음** |
| `NO_DATA` | 실적 또는 경계값 없음 |

> **정박 중에 산정하지 않는 이유.** not under way 구간은 거리가 늘지 않고 연료만 늘어(`PRD §3.3` · `MEPC.412(84)` §4.2) CII가 단조 악화한다. 그대로 외삽하면 n일이 하루가 다르게 짧아졌다가 **출항하는 순간 되돌아간다.** 평활화 규칙을 두는 대신 사유로 표기한다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 409 | `PARAMETER_ERROR` | 해당 규제연도 파라미터 없음 (VAL-005) |

> **선박 0척은 오류가 아니다.** 아직 등록하지 않은 선사가 정상적으로 만나는 상태이므로 200에 빈 배열을 반환한다. 404로 내면 화면이 「기능 미구현」과 구분하지 못한다.

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
      "regulation_year": 2026,
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
  "regulation_year": 2026,
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

> **[EXT-P0-4]** `annual_inclusion_policy`는 요청 본문에서 제외했다. 생성 시 `status = DRAFT`이며, DRAFT에서는 `annual_inclusion_policy = EXCLUDE`만 허용된다(§3.5 제약 매트릭스 참조).
>
> **[#150 정정] `PLANNED` 전환이 곧 연간 반영은 아니다.** 종전 문장은 *"`PLANNED` 전환 시 `annual_inclusion_policy`를 `INCLUDE_AS_PLAN`으로 설정한다"* 였으나, `§3.5` 제약 매트릭스와 `PRD §8.1.2`는 `PLANNED`에서 **`EXCLUDE`와 `INCLUDE_AS_PLAN`을 모두 허용**한다. **계획 저장 여부와 연간 반영 여부는 별개다** — 연간 반영을 선택할 때만 `INCLUDE_AS_PLAN`을 지정한다. 종전 문장은 대표 경로 서술이었고 그대로 두면 「계획 저장 = 무조건 연간 반영」으로 읽힌다.

> **[#150] `regulation_year`는 optional이다.** 주어지면 `VAL-005`(`regulation_year` 테이블에 해당 연도 존재)로 검증한다. `annual_inclusion_policy = EXCLUDE`인 동안에는 없어도 되고, **`INCLUDE_AS_PLAN` 전환 시점에는 반드시 있어야 한다**(§3.5 전환 가드 · `PRD §8.1.1`). 생성 시 넣지 않았다면 §3.4 PATCH로 설정한다.

#### 응답 (201 Created)

생성된 항차 객체. 초기 `status = DRAFT`, `annual_inclusion_policy = EXCLUDE` (자동 설정).

### 3.4 항차 수정

```http
PATCH /api/v1/voyages/{voyage_id}
```

모든 필드는 optional. `status` 변경은 §3.5 참조. **생략 = 변경 없음, 명시적 `null` = 클리어**다(#312).

> **[#150]** 대상 필드는 §3.3 요청 본문과 같으므로 **`regulation_year`도 여기서 설정·변경한다.** 주어지면 `VAL-005`로 검증한다. `annual_inclusion_policy ≠ EXCLUDE`인 항차에서 `regulation_year`를 `null`로 지우는 요청은 `DB_SCHEMA`의 `chk_year_policy`를 깨뜨리므로 거부한다.

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
| `annual_inclusion_policy`를 `INCLUDE_AS_PLAN` · `INCLUDE_AS_ACTUAL`로 지정하는 모든 전환 | `voyage.regulation_year != null` (#150) | 422 `STATE_TRANSITION_ERROR`: 기준연도 설정 요청 |

> **[ORACLE-C-4 추가]** `CONFIRMED → ARCHIVED` 전환을 추가했다. PRD §8.1 상태 다이어그램에 명시된 전환이다. 보관된 항차는 읽기 전용이며 `annual_inclusion_policy = EXCLUDE`로 자동 설정된다.
>
> **[#150] 마지막 행은 상태가 아니라 policy에 걸리는 가드다.** `DB_SCHEMA`의 `chk_year_policy`(`annual_inclusion_policy = 'EXCLUDE' OR regulation_year IS NOT NULL`)에 **도달해 우연히 실패하는 것이 아니라, 공개 API가 전환 전에 거부한다.** 값은 §3.3 생성 또는 §3.4 PATCH로 설정하며 **전환 요청 본문에서는 받지 않는다** — `regulation_year`는 전환 명령의 옵션이 아니라 Voyage 도메인 데이터이기 때문이다. §3.1이 이미 목록 필터로 쓰고 있는 것도 같은 성격을 보여준다.

#### status × annual_inclusion_policy 제약

> PRD §8.1.2 (ORACLE-R-1).

전환 요청에서 `annual_inclusion_policy`를 **생략하면 현행 값을 유지한다**(#310). 단, 아래 두 경우는 예외다.

- 목표 상태가 EXCLUDE only(`CANCELLED`·`ARCHIVED`)면 **자동으로 `EXCLUDE`로 설정**한다(아래 표 「자동 설정」·ORACLE-C-4).
- 목표 상태가 현행 policy를 허용하지 않는 조합(예: `PLANNED`(`INCLUDE_AS_PLAN`) → `COMPLETED`)이면 자동 보정하지 않고 **명시적 재지정을 요구하며 거부한다(422)**.

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

> **[#313]** Hard delete 대상이라도 이 항차를 참조하는 계산 이력(`calculation_run`)이 있으면 **409 `CONFLICT`**로 거부한다. `fk_calculation_run_voyage`가 ON DELETE `RESTRICT`라 참조가 있는 물리 삭제는 DB 제약 위반이다 — 계산 이력은 보존 대상이다(DB_SCHEMA §7.1).

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
| `speed_kn` | decimal | Y | VAL-009: ≥ 1.0 | 평균 예정 속도. **Layer 1 CII 계산에는 사용되지 않으며**, 항차 조건 표시 및 항차 저장 매핑을 위한 필수 입력이다 |
| `fuel_uses` | array | Y | **최소 1개 이상** · VAL-006: active fuel_type | 연료 사용량 목록. **동일 `fuel_type`이 여러 행으로 들어오면 Decimal로 합산한다** |
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
    "next_worse_boundary_margin": "0.365370",
    "next_worse_boundary_margin_ratio": "0.0724",
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
      "z_factor_percent": "11.0"
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

**등급 E 응답 예시** (#171) — 같은 선박·연도에 연료량만 늘린 경우다. 위 예시와
다른 부분만 봐도 된다:

```json
{
  "data": {
    "attained_cii": "12.456000",
    "required_cii": "5.045066",
    "ratio_to_required": "2.46895",
    "estimated_rating": "E",
    "next_worse_boundary_margin": null,
    "next_worse_boundary_margin_ratio": null,
    "co2_emission_ton": "622.80",
    "fuel_consumption_ton": "200.00",
    "distance_nm": 1000.0,
    "risk_level": "CRITICAL"
  }
}
```

> `next_worse_boundary_margin` · `next_worse_boundary_margin_ratio`는 **등급 E에서
> `null`**이다 — 최하위 등급이라 악화 방향 경계가 존재하지 않는다 (#171). 화면은
> 「해당 없음 — 최하위 등급」 문구로 표시한다(DESIGN_SYSTEM §2.5). 위 값은 실제
> 구현 응답에서 추출한 것으로, 전체 응답에서 `data`의 계산 필드만 발췌했다
> (`parameters_used` 등 나머지 구조는 동일하다).

#### 응답 필드·JSON 타입

Layer 1 결정론 수치는 **JSON 문자열**로 직렬화한다(§1.7). 입력 에코 값은 숫자다.

**최상위 (envelope)**

| 경로 | JSON 타입 |
|---|---|
| `data` | object |
| `parameters_used` | object |
| `calculation_run_id` | string (UUID) |
| `model_version` | object — **혼합 타입**. `decimal_precision`만 number, 나머지(`engine` · `decimal_rounding` · `rng_algorithm` · `numpy_version` · `python_version`)는 string |
| `input_hash` · `parameter_hash` | string (`sha256:…`) |
| `warnings` | array of string |
| `disclaimer` | string |
| `meta` | object — `request_id` string · `timestamp` string(ISO8601) · `duration_ms` number |

**`data.*`**

| 경로 | JSON 타입 | 비고 |
|---|---|---|
| `attained_cii` | **string** | Layer 1 |
| `required_cii` | **string** | Layer 1 |
| `ratio_to_required` | **string** | Layer 1 |
| `estimated_rating` | string | enum `A`~`E` |
| `next_worse_boundary_margin` | **string \| null** | Layer 1. **등급 E는 `null`** — 최하위 등급이라 악화 방향 경계가 없다 (#171) |
| `next_worse_boundary_margin_ratio` | **string \| null** | Layer 1. 등급 E는 `null` (#171) |
| `co2_emission_ton` | **string** | Layer 1 |
| `fuel_consumption_ton` | **string** | Layer 1. 입력 연료량 전체의 합 |
| `distance_nm` | **number** | 입력 에코 |
| `risk_level` | string | enum `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` (PRD §9.4.1) |
| `transport_capacity` | **string** | |
| `transport_capacity_basis` | string | enum `DWT` \| `GT` |
| `reference_capacity` | **string** | |
| `reference_capacity_rule` | string | **enum이 아니다** — 파라미터 테이블 값 그대로 (`DWT` · `GT` · `fixed 279000` 등) |
| `calculation_basis` | object | 아래 |

**`data.calculation_basis.*`**

| 경로 | JSON 타입 |
|---|---|
| `ship_type` | string |
| `z_factor_percent` | **string** |
| `fuel_cf_details` | array of object. **연료 종류별 한 행으로 정규화한다** |
| `fuel_cf_details[].fuel_type` | string |
| `fuel_cf_details[].cf` | **string** |
| `fuel_cf_details[].fuel_ton` | **string**. 동일 `fuel_type` 입력 행의 합 |
| `a_decimal` | **string** |
| `c` | **string** |

`parameters_used` 하위 수치(`z_factor_percent` · `cf` · `a_decimal` · `c` · `d1`~`d4`)와 `parameter_source_version`도 모두 string이다.

> `risk_level` 산정 기준은 **PRD §9.4.1**(결정론 화면 — 기능①·②, `등급 + margin_ratio`)과 **PRD §9.4.2**(확률 화면 — 기능③, `목표 등급 달성 확률`) 참조. 두 절이 임계값 표를 소유하며, 이 문서는 값을 전사하지 않는다.

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
      "source_ref": "MEPC.364(79)",
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

> **`rng_canonical_test`** — PCG64DXSM(seed=12345)의 첫 5개 uniform 값이 `TECH_SPEC §2.5.1`
> canonical vector와 `1e-15` 이내로 일치하면 `"passed"`, 아니면 `"failed"`다.
> **프로세스당 1회만 계산**한다 — 이 값은 NumPy 버전과 플랫폼에서 결정되며 둘 다
> 프로세스 수명 동안 바뀌지 않는다.
>
> **`"failed"`여도 `status`는 `"ok"`를 유지한다** (#400). 두 필드는 서로 다른 것을 본다 —
> `status`는 liveness(루트 `Dockerfile`의 HEALTHCHECK 용도)이고, RNG 불일치는 프로세스가
> 살아 있고 응답도 하는 상태다. **재시작으로 해결되지 않으므로**(NumPy 버전은 이미지에
> 고정) `status`를 내리면 오케스트레이터가 무한 재시작 루프에 빠지면서 원인은 그대로
> 남는다. 재현성 계약(`TECH_SPEC §5.4`) 위반 신호는 이 필드가 전달하며, 모니터링이
> 이 값에 알람을 건다.
>
> *(2026-08-12~08-15 유예: `#43` 완료 전까지 거짓 `"passed"`를 내지 않으려 필드를 생략했다.
> `#43` 머지로 유예가 해소되어 `#400`에서 구현했다.)*

---

## 11. 검증 규칙 요약

> PRD §9.1의 모든 검증 규칙을 API 응답에 매핑한다.

| Rule ID | 규칙 | 오류 응답 |
|---|---|---|
| VAL-001 | 필수값 비어 있음 | 422: `{field_label}을/를 입력하세요.` (`field_label`는 한글 라벨) |
| VAL-002 | 거리·연료·DWT·GT·선박 기준속도(`reference_speed_kn`) ≤ 0 | 422: `{field_label}는 0보다 커야 합니다.` (`field_label`는 한글 라벨) |
| VAL-003 | IMO 번호 형식 오류 | 422: `IMO 번호는 7자리 숫자여야 합니다.` |
| VAL-004 | 지원하지 않는 선종 | 422: `지원하지 않는 선종입니다.` |
| VAL-005 | 기준연도 파라미터 없음 | 409: `해당 연도의 규정 파라미터가 없습니다.` |
| VAL-006 | 지원하지 않는 연료 | 422: `지원하지 않는 연료입니다.` |
| VAL-007 | 좌표 범위 오류 | 422: `좌표 형식이 올바르지 않습니다.` |
| VAL-008 | NaN·Infinity 결과 | 422: `계산 오류: 입력값을 확인하세요.` |
| VAL-009 | 항차·시나리오 운항 속도 < 1.0kn | 422: `속도는 1.0노트 이상이어야 합니다.` |
| VAL-010 | capacity ≤ 0 | 422: `선박 용량 정보가 부족합니다.` |

---

## 12. 엔드포인트 요약

| Method | Path | 기능 | PRD 참조 |
|---|---|---|---|
| GET | `/api/v1/health` | 헬스 체크 | — |
| GET | `/api/v1/vessels` | 선박 목록 | §6.2 SCR-002 |
| POST | `/api/v1/vessels` | 선박 등록 | §6.2 SCR-002 |
| GET | `/api/v1/vessels/{id}` | 선박 상세 | §6.2 SCR-002 |
| GET | `/api/v1/vessels/{id}/cii-history` | 연도별 CII 이력 | §6.2 SCR-008 |
| GET | `/api/v1/fleet/summary` | 선대 요약 (대시보드) | §6.2 SCR-001 |
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
| 허용 Header | Content-Type, X-API-Key, Authorization, X-CSRF-Token |

> 쿠키 기반 세션을 사용하므로 CORS 설정은 `allow_credentials = true`가 필요하며, **`allow_origins`에 와일드카드(`*`)를 쓸 수 없다.** 허용 출처를 명시적으로 나열한다 (#272).

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

> **[#132 후속 정정]** EXT-P0-1 반영 당시 §4.1·§5.1의 이중 capacity 분리는 완료됐으나, §1.7의 Layer 1 필드 열거에 `effective_capacity`가 남은 사실이 후속 확인됐다. #132에서 §1.7의 중복 필드 열거를 제거하고 endpoint별 응답 계약을 참조하도록 정정했다.

- **수정 소요**: Critical + Significant 이슈 해결에 약 2~3시간 소요 (문서 수정 기준).

---

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준). 버전 번호 매핑은 커밋 메시지·헤더 기준의 추정을 포함한다.
>
> **2026-07-23까지가 사후 복원분이다.** 이후 항목은 변경 시점에 직접 기록하며, squash merge로 브랜치 커밋 해시가 재작성되므로 커밋 열에는 **PR 번호**를 적는다.

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-07-03 | `eba6cb8` | v1.1 최초 작성 |
| 2026-07-03 | `9f8a7eb` | 외부 리뷰 반영 (capacity 규칙 분리 등) |
| 2026-07-04 | `0f59999` | 외부 리뷰 P0/P1/P2 전체 반영 + AGENTS.md 추가 |
| 2026-07-04 | `af3b752` | Oracle 리뷰 4건 문서 정합성 수정 |
| 2026-07-04 | `bee61e9` | 포맷 정리 |
| 2026-07-04 | `ec1bf23` | Oracle 3차 리뷰 반영 (F-006~F-008) → v1.2 |
| 2026-07-14 | `0173105` | annotation 라벨 번호 정규화 (5개 정본 일괄) |
| 2026-07-21 | `be0dc23` | 변경이력 표 추가 및 최종 수정일 갱신 |
| 2026-07-29 | `#140` | §7.2 연료 종류 조회 응답 예시 source_ref 정정 (#87) |
| 2026-07-29 | `#142` | 최종 수정일 정정 (07-14 → 07-29) |
| 2026-07-31 | `#152` | 기능① 응답 타입·연료 정규화 계약 명시, Layer 1 직렬화 참조 정리 및 산술 예시 정정 (#132) |
| 2026-08-04 | `#175` | §4.1 `risk_level` 산정 기준 참조에 PRD §9.4.2(확률 화면) 추가 — 기존에는 §9.4.1만 가리켜 기능③ 임계값 출처가 드러나지 않았다 |
| 2026-08-06 | `#187` | §3.1 응답·§3.3 생성 요청에 `regulation_year` 노출, §3.4 PATCH 대상 명시, §3.5에 `INCLUDE_AS_PLAN` 전환 가드 행 신설, §3.3 `[EXT-P0-4]`의 「PLANNED 전환 = INCLUDE_AS_PLAN」 서술 정정 (#150) |
| 2026-08-07 | `#196` | 헤더 「상위 문서」 버전 참조 갱신 — `PRD` v3.2 · `TECH_SPEC` v1.2→v1.4(낡은 참조 정정) (#163) |
| 2026-08-10 | `#218` | §4.1 응답 예시의 `parameters_used.regulation_year.z_factor_percent` 표기를 `"11"` → `"11.0"`로 정정 — `calculation_basis` 블록과 통일 (#208) |
| 2026-08-11 | `#222` | §1.3.2에 `message` 한국어 규정, §1.4에 405 `METHOD_NOT_ALLOWED`·경로 404·미등록 status 범용 `HTTP_ERROR` 행 및 프레임워크 발생 오류 정책(문구·status 보존) 신설 (#182) |
| 2026-08-13 | `#297` | v1.3: §1.2 인증 전면 재작성(구글 OIDC + 세션 쿠키), §1.4에 401·403 행 추가, §13.3 CORS에 X-CSRF-Token·credentials 정책 추가, 인증 엔드포인트 표 신설 (#272) |
| 2026-08-13 | `#323` | v1.4: §3.4에 null 의미론(생략=변경 없음·명시적 null=클리어) 명시, §3.5 policy 제약 서두를 「미지정=현행 유지·EXCLUDE-only 자동 설정·불가 조합 명시적 재지정 요구」로 정정 (#310 #312) |
| 2026-08-13 | `#324` | §3.7 삭제 규칙에 계산 이력 참조 시 409 `CONFLICT` 거부 행 추가 (#313) |
| 2026-08-14 | `#332` | §1.9 응답에 `needs_recalc` 필드 노출 — DWT/GT 변경 시 재계산 필요 표시 (#283) |
| 2026-08-14 | `#338` | §4.1 `next_worse_boundary_margin`·`_ratio`를 nullable(string \| null)로 표기 + 등급 E 응답 예시 블록 추가 — 등급 E는 `null` (#171) |
| 2026-08-14 | `#373` | §1.6에 `SLOW_SPEED_FLOOR` 경고 코드 신설 — 기능② 감속 시나리오 속도 floor(1.0kn) 도달 고지, PRD §11.2 (#57) |
| 2026-08-15 | `#383` | v1.5: §1.10 `as_of` 공통 계약 신설 — 시각 의존 계산의 요청 파라미터·`meta.as_of`·`meta.is_simulated`·재현성 보장 3항. 정본 근거는 `TECH_SPEC §5.4.1` (#368) |
| 2026-08-15 | `#384` | v1.6: §2.6 선박 위치·운항 상태 갱신 엔드포인트 신설 — 026(#346)이 만든 컬럼의 유일한 갱신 경로. 상태 2축·위경도 쌍 규칙을 스키마 표면에 명시, `position_updated_at`은 서버 확정. §2.1 선박 객체에 위치·상태 5키 추가 (#369) |
| 2026-08-15 | `#404` | §10 `rng_canonical_test` 유예 각주를 구현 완료 서술로 교체 — `#43` 머지로 유예 조건이 해소됐다. `"failed"`여도 `status`는 `ok`를 유지하는 근거(liveness vs 재현성 신호 분리)를 명시 (#400) |
| 2026-08-15 | `#405` | 변경 이력 표의 PR 번호 공란 2건을 채우고 순서 교정 — v1.5 → #383(`as_of` 계약) · v1.6 → #384(위치 갱신). #401이 `DB_SCHEMA`만 정리하고 이 문서를 빠뜨린 것을 보완한다. 문서 내용 변경 없음 (#401) |
| 2026-08-16 | `#356` | §2.7 응답에 `transport_capacity_basis` 추가 — 표시 단위의 축(DWT·GT)을 서버가 내려준다. `DESIGN_SYSTEM §4.1`이 고정 문자열을 금지하므로 화면이 선종에서 유추하지 않게 하기 위함이며, 유추하면 선종 확장 시 서버와 갈라진다 (#356) |
| 2026-08-16 | `#350` | **§2.8 선대 요약 조회 신설** — 대시보드가 한 번의 호출로 선대 전체 현황을 받는 `GET /fleet/summary`. `risk_level`(PRD §9.4.1 표시용)과 `risk_reasons`(PRD §3.3.7 규제 트리거)를 분리해 함께 반환하는 근거, `days_to_d` 경계 4종, 선박 0척이 오류가 아닌 근거를 명시. 엔드포인트 요약 표에 1행 추가 (#350) |
| 2026-08-15 | `#380` | §2.7 `rating` 설명의 `PRD §3.3.7` 참조를 `§3.3.8`로 정정 — 이 근거(YTD는 공식 등급이 아님)는 실시간 CII 절의 내용인데, `#386`이 `§3.3.7`을 「등급 하락의 규제상 귀결」로 선점해 참조가 다른 절을 가리키고 있었다 (#358) |
