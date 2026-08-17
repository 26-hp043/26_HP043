# DB_SCHEMA — CII 예측 및 운항 의사결정 보조 플랫폼

| 항목 | 내용 |
|---|---|
| 문서명 | DB_SCHEMA.md |
| 버전 | v1.15 |
| 상태 | Oracle Review + 외부 리뷰 반영 + weather 추적 컬럼 스펙 (#102) + 파라미터 CHECK·FK 자식 인덱스 (#96 #97) + needs_recalc 플립 예외 (#283) + not under way 스키마 (#345) + 운항 상태 2축 (#346) + not under way 이동 거리 (#353) |
| 최종 수정일 | 2026-08-17 |
| 상위 문서 | `PRD.md` v4.0, `TECH_SPEC.md` v1.4, `API_SPEC.md` v1.2 |
| 후속 문서 | `TEST_PLAN.md` |
| DB 엔진 | PostgreSQL 16 (권장) |

---

## 0. 범위 및 목적

본 문서는 PRD §7 데이터 모델, TECH_SPEC의 기술 명세, API_SPEC의 응답 스키마를 기반으로 데이터베이스 스키마를 정의한다.

### 0.1 설계 원칙

| 원칙 | 설명 |
|---|---|
| 정밀도 우선 | CII 계산 관련 수치는 `NUMERIC(30,6)`. `FLOAT`/`DOUBLE` 사용 금지 (TECH_SPEC §1) |
| 스냅샷 보존 | 계산 결과는 변경 불가 snapshot으로 저장. 원본 데이터 변경 후에도 재현 가능 |
| 감사 추적 | 파라미터 변경, 항차 확정, 계산 실행 로그 저장 (TECH_SPEC §13.1) |
| 논리 삭제 | 비즈니스 데이터는 soft delete. 물리 삭제는 관리자 전용 |
| UUID PK | 모든 테이블 PK는 UUID v4. 자동 증분 정수 사용 안 함 |
| **타임존 정책 [X-6]** | 모든 `TIMESTAMPTZ` 값은 UTC 기준으로 저장된다. 서버 `timezone = UTC` 설정 필수. 클라이언트는 UTC로 전송하고 표시 시 로컬 변환을 수행한다 |

### 0.2 기준 문서 참조

| 문서 | 참조 내용 |
|---|---|
| PRD §7 | 핵심 엔티티 (Vessel, Voyage, VoyageFuelUse, VoyageScenario, CalculationRun) |
| PRD §7.6 | RegulationParameter 테이블 구조 |
| PRD §8.1 | 항차 상태 모델, status × policy 제약 |
| TECH_SPEC §2.2.2 | `rng_metadata` JSON 구조 |
| TECH_SPEC §5.2.1 | `parameters_used` JSON 스키마 |
| TECH_SPEC §9.1 | `a_raw` VARCHAR + `a_decimal` NUMERIC(30,6) 이중 저장 |
| TECH_SPEC §10.1 | `model_version` structured JSON |
| TECH_SPEC §11 | 스냅샷 격리 (`SimulationSnapshot`) |
| TECH_SPEC §13.1 | 감사 로그 필드 |
| API_SPEC §1.7 | 수치 직렬화 정책 (Layer 1 = 문자열) |

---

## 1. ER 다이어그램

```mermaid
erDiagram
    VESSEL ||--o{ VOYAGE : has
    VESSEL ||--o{ VOYAGE_SCENARIO : standalone
    VOYAGE ||--o{ VOYAGE_FUEL_USE : consumes
    VOYAGE ||--o{ VOYAGE_SCENARIO : derived_from
    VOYAGE ||--o{ CALCULATION_RUN : calculated_by
    VESSEL ||--o{ ANNUAL_SIMULATION_RUN : simulated_by
    SIMULATION_SNAPSHOT ||--o| ANNUAL_SIMULATION_RUN : used_by
    REGULATION_YEAR ||--o{ CALCULATION_RUN : used_by
    FUEL_TYPE ||--o{ VOYAGE_FUEL_USE : used_in
    FUEL_TYPE ||--o{ VESSEL : default_fuel
    CII_REFERENCE_LINE ||--o{ CALCULATION_RUN : referenced_by
    CII_RATING_BOUNDARY ||--o{ CALCULATION_RUN : referenced_by
    WEATHER_SNAPSHOT ||--o{ VOYAGE_SCENARIO : used_by
    AUDIT_LOG }o--o| VESSEL : references
    AUDIT_LOG }o--o| VOYAGE : references
    VESSEL ||--o{ NOT_UNDERWAY_PERIOD : idle_in
    VOYAGE |o--o{ NOT_UNDERWAY_PERIOD : context
    NOT_UNDERWAY_PERIOD ||--o{ NOT_UNDERWAY_FUEL_USE : consumes
    FUEL_TYPE ||--o{ NOT_UNDERWAY_FUEL_USE : used_in
```

> **[S-6 수정]** `SIMULATION_SNAPSHOT ||--o| ANNUAL_SIMULATION_RUN` (1:1 또는 1:0..1)으로 변경. 시뮬레이션 실행 1건당 스냅샷 1건이 생성되며, 스냅샷이 부모이다. `AUDIT_LOG`의 카디널리티도 `}o--o|`로 수정 (entity_id가 NULL 허용).

---

## 2. 테이블 정의

> **[C-3 전역 정책]** 모든 FK에 명시적 `ON DELETE` 동작을 지정한다. 상세는 §7.1 "FK ON DELETE 정책" 참조.

### 2.1 `vessel` — 선박

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK, NOT NULL | 내부 ID |
| `imo_number` | VARCHAR(7) | NOT NULL | IMO 번호 (7자리 숫자). 유일성은 partial unique index로만 보장 (soft delete 호환) |
| `name` | VARCHAR(100) | NOT NULL | 선박명 |
| `ship_type` | VARCHAR(50) | NOT NULL | CII 선종 enum. `cii_reference_line.ship_type`에 존재해야 함 |
| `gross_tonnage` | NUMERIC(12,2) | NULL | GT |
| `deadweight` | NUMERIC(12,2) | NULL | DWT |
| `default_fuel_type` | VARCHAR(30) | NULL, **FK → fuel_type(code) ON UPDATE CASCADE** [S-1] | 기본 연료 코드 |
| `reference_speed_kn` | NUMERIC(6,2) | NULL | 기준 속도 (kn) |
| `reference_daily_foc_ton` | NUMERIC(8,2) | NULL | 기준 일일 연료소모량 (ton/day) |
| `is_cii_applicable_hint` | BOOLEAN | NOT NULL DEFAULT false | GT ≥ 5000 및 선종 기준 자동 산정 |
| `is_deleted` | BOOLEAN | NOT NULL DEFAULT false | Soft delete 플래그 |
| `underway_state` | VARCHAR(20) | NULL, CHECK 허용값 2종 | **계산 축** — `UNDER_WAY`/`NOT_UNDER_WAY` (#346) |
| `detail_status` | VARCHAR(20) | NULL, CHECK 허용값 7종 | **화면 축** — `SAILING`/`IN_PORT`/`AT_ANCHOR`/`DRIFTING`/`STS`/`CANAL_TRANSIT`/`DRYDOCK` |
| `current_lat` | NUMERIC(9,6) | NULL, CHECK −90~90 | 현재 위치 위도 |
| `current_lon` | NUMERIC(9,6) | NULL, CHECK −180~180 | 현재 위치 경도 |
| `position_updated_at` | TIMESTAMPTZ | NULL | 위치 갱신 시각. **위치가 있으면 필수** (UIFLOW §2-8) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 수정일 (§7.2 trigger로 자동 갱신) |

**인덱스:**

```sql
-- pg_trgm extension (GIN trigram index에 필요)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE UNIQUE INDEX idx_vessel_imo ON vessel (imo_number) WHERE is_deleted = false;
CREATE INDEX idx_vessel_ship_type ON vessel (ship_type) WHERE is_deleted = false;
CREATE INDEX idx_vessel_name ON vessel USING gin (name gin_trgm_ops) WHERE is_deleted = false;
```

**검증 제약:**

```sql
ALTER TABLE vessel ADD CONSTRAINT chk_imo_format CHECK (imo_number ~ '^\d{7}$');
ALTER TABLE vessel ADD CONSTRAINT chk_gt_positive CHECK (gross_tonnage IS NULL OR gross_tonnage > 0);
ALTER TABLE vessel ADD CONSTRAINT chk_dwt_positive CHECK (deadweight IS NULL OR deadweight > 0);
ALTER TABLE vessel ADD CONSTRAINT chk_speed_positive CHECK (reference_speed_kn IS NULL OR reference_speed_kn > 0);
-- 026 (#346): 운항 상태 2축 + 위치. 전부 NULL 허용 — 미갱신 선박도 정상 조회.
ALTER TABLE vessel ADD CONSTRAINT chk_underway_state_allowed CHECK (underway_state IS NULL OR underway_state IN ('UNDER_WAY','NOT_UNDER_WAY'));
ALTER TABLE vessel ADD CONSTRAINT chk_detail_status_allowed CHECK (detail_status IS NULL OR detail_status IN ('SAILING','IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK'));
ALTER TABLE vessel ADD CONSTRAINT chk_vessel_state_pair CHECK (
    (underway_state IS NULL AND detail_status IS NULL)
    OR (underway_state IS NOT NULL AND detail_status IS NOT NULL AND (
        (underway_state = 'UNDER_WAY' AND detail_status = 'SAILING')
        OR (underway_state = 'NOT_UNDER_WAY' AND detail_status IN ('IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK'))
    ))
);
ALTER TABLE vessel ADD CONSTRAINT chk_vessel_lat_range CHECK (current_lat IS NULL OR current_lat BETWEEN -90 AND 90);
ALTER TABLE vessel ADD CONSTRAINT chk_vessel_lon_range CHECK (current_lon IS NULL OR current_lon BETWEEN -180 AND 180);
ALTER TABLE vessel ADD CONSTRAINT chk_vessel_position_pair CHECK (
    (current_lat IS NULL AND current_lon IS NULL)
    OR (current_lat IS NOT NULL AND current_lon IS NOT NULL AND position_updated_at IS NOT NULL)
);
```

> `gross_tonnage`와 `deadweight`는 PRD §7.2에서 "조건부 필수"이다. CII 계산 시점에 VAL-010으로 검증한다.
>
> **[S-1]** `default_fuel_type`에 FK 제약 추가. `fuel_type.code`를 참조하며 `ON UPDATE CASCADE`로 코드 변경 시 자동 전파.

---

### 2.2 `voyage` — 항차

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | 항차 ID |
| `vessel_id` | UUID | NOT NULL, FK → vessel(id) **ON DELETE RESTRICT** [DB-C-3] | 선박 ID |
| `voyage_no` | VARCHAR(100) | NULL | 사용자 입력 항차 번호 |
| `status` | VARCHAR(20) | NOT NULL | DRAFT, PLANNED, IN_PROGRESS, COMPLETED, CONFIRMED, CANCELLED, ARCHIVED |
| `regulation_year` | INTEGER | NULL **[C-1 추가]** | 해당 항차가 포함될 규정연도. `annual_inclusion_policy ≠ EXCLUDE`인 경우 NOT NULL 필수 |
| `departure_port_name` | VARCHAR(200) | NOT NULL | 출발항 |
| `departure_lat` | NUMERIC(9,6) | NULL | 출발항 위도 |
| `departure_lon` | NUMERIC(9,6) | NULL | 출발항 경도 |
| `arrival_port_name` | VARCHAR(200) | NOT NULL | 도착항 |
| `arrival_lat` | NUMERIC(9,6) | NULL | 도착항 위도 |
| `arrival_lon` | NUMERIC(9,6) | NULL | 도착항 경도 |
| `planned_distance_nm` | NUMERIC(12,2) | NOT NULL | 계획 거리 |
| `actual_distance_nm` | NUMERIC(12,2) | NULL | 실제 거리 |
| `planned_speed_kn` | NUMERIC(6,2) | NOT NULL | 예정 평균 속도 |
| `actual_avg_speed_kn` | NUMERIC(6,2) | NULL | 실제 평균 속도 |
| `planned_departure_at` | TIMESTAMPTZ | NULL | 예정 출항 |
| `planned_arrival_at` | TIMESTAMPTZ | NULL | 예정 도착 |
| `actual_departure_at` | TIMESTAMPTZ | NULL | 실제 출항 |
| `actual_arrival_at` | TIMESTAMPTZ | NULL | 실제 도착 |
| `annual_inclusion_policy` | VARCHAR(30) | NOT NULL DEFAULT 'EXCLUDE' | EXCLUDE, INCLUDE_AS_PLAN, INCLUDE_AS_ACTUAL |
| `created_from` | VARCHAR(30) | NOT NULL DEFAULT 'MANUAL' | MANUAL, FEATURE_1, FEATURE_2_ADOPTED, IMPORT, SAMPLE |
| `notes` | TEXT | NULL | 메모 |
| `is_deleted` | BOOLEAN | NOT NULL DEFAULT false | Soft delete |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 수정일 (§7.2 trigger로 자동 갱신) |

**인덱스:**

```sql
CREATE INDEX idx_voyage_vessel ON voyage (vessel_id, created_at DESC) WHERE is_deleted = false;
CREATE INDEX idx_voyage_status ON voyage (vessel_id, status) WHERE is_deleted = false;
CREATE INDEX idx_voyage_year ON voyage (vessel_id, regulation_year) WHERE is_deleted = false;
```

**검증 제약:**

```sql
ALTER TABLE voyage ADD CONSTRAINT chk_voyage_status
    CHECK (status IN ('DRAFT','PLANNED','IN_PROGRESS','COMPLETED','CONFIRMED','CANCELLED','ARCHIVED'));

ALTER TABLE voyage ADD CONSTRAINT chk_voyage_policy
    CHECK (annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN','INCLUDE_AS_ACTUAL'));

-- status × annual_inclusion_policy 제약 (PRD §8.1.2 ORACLE-R-1)
ALTER TABLE voyage ADD CONSTRAINT chk_status_policy CHECK (
    (status = 'DRAFT' AND annual_inclusion_policy = 'EXCLUDE')
    OR (status IN ('PLANNED','IN_PROGRESS') AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN'))
    OR (status IN ('COMPLETED','CONFIRMED') AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_ACTUAL'))
    OR (status IN ('CANCELLED','ARCHIVED') AND annual_inclusion_policy = 'EXCLUDE')
);

-- regulation_year 범위 및 policy 연관 제약 [DB-C-1]
ALTER TABLE voyage ADD CONSTRAINT chk_regulation_year_range
    CHECK (regulation_year IS NULL OR regulation_year BETWEEN 2019 AND 2050);
ALTER TABLE voyage ADD CONSTRAINT chk_year_policy
    CHECK (annual_inclusion_policy = 'EXCLUDE' OR regulation_year IS NOT NULL);

ALTER TABLE voyage ADD CONSTRAINT chk_distance_positive CHECK (planned_distance_nm > 0);
ALTER TABLE voyage ADD CONSTRAINT chk_speed_positive CHECK (planned_speed_kn >= 1.0);
ALTER TABLE voyage ADD CONSTRAINT chk_actual_dist_positive
    CHECK (actual_distance_nm IS NULL OR actual_distance_nm > 0);  -- [M-6]
ALTER TABLE voyage ADD CONSTRAINT chk_actual_speed_positive
    CHECK (actual_avg_speed_kn IS NULL OR actual_avg_speed_kn >= 1.0);  -- [M-6]
ALTER TABLE voyage ADD CONSTRAINT chk_dep_lat_range
    CHECK (departure_lat IS NULL OR departure_lat BETWEEN -90 AND 90);
ALTER TABLE voyage ADD CONSTRAINT chk_dep_lon_range
    CHECK (departure_lon IS NULL OR departure_lon BETWEEN -180 AND 180);
ALTER TABLE voyage ADD CONSTRAINT chk_arr_lat_range
    CHECK (arrival_lat IS NULL OR arrival_lat BETWEEN -90 AND 90);  -- [S-3]
ALTER TABLE voyage ADD CONSTRAINT chk_arr_lon_range
    CHECK (arrival_lon IS NULL OR arrival_lon BETWEEN -180 AND 180);  -- [S-3]
```

> **[DB-C-1]** `regulation_year` 컬럼이 누락되어 있었다. 인덱스 `idx_voyage_year`가 이 컬럼을 참조하므로 DDL 실행이 실패했다. 컬럼을 추가하고, `annual_inclusion_policy ≠ EXCLUDE`인 경우 NOT NULL을 강제하는 CHECK 제약도 추가했다.

---

### 2.3 `voyage_fuel_use` — 항차 연료 사용량

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `voyage_id` | UUID | NOT NULL, FK → voyage(id) **ON DELETE CASCADE** [DB-C-3] | 항차 ID |
| `fuel_type` | VARCHAR(30) | NOT NULL, **FK → fuel_type(code) ON UPDATE CASCADE** [S-1] | 연료 종류 |
| `planned_fuel_ton` | NUMERIC(12,4) | NULL | 계획 연료 사용량 |
| `actual_fuel_ton` | NUMERIC(12,4) | NULL | 실제 연료 사용량 |
| `cf_used` | NUMERIC(10,6) | NOT NULL | 계산 시점 CF snapshot |
| `source` | VARCHAR(30) | NOT NULL | USER_INPUT, MODEL_ESTIMATE, IMPORT, SAMPLE |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 수정일 (§7.2 trigger로 자동 갱신) |

**인덱스:**

```sql
-- [S-2] 동일 항차+연료 타입 중복 방지
CREATE UNIQUE INDEX idx_fuel_use_unique ON voyage_fuel_use (voyage_id, fuel_type);
```

**검증 제약:**

```sql
ALTER TABLE voyage_fuel_use ADD CONSTRAINT chk_fuel_source
    CHECK (source IN ('USER_INPUT','MODEL_ESTIMATE','IMPORT','SAMPLE'));

ALTER TABLE voyage_fuel_use ADD CONSTRAINT chk_fuel_positive
    CHECK (planned_fuel_ton IS NULL OR planned_fuel_ton > 0);
ALTER TABLE voyage_fuel_use ADD CONSTRAINT chk_actual_fuel_positive
    CHECK (actual_fuel_ton IS NULL OR actual_fuel_ton > 0);


-- ORACLE-C-4: COMPLETED 상태에서는 최소 1개 actual_fuel_ton > 0 필요
-- 애플리케이션 레벨에서 검증 (DB 트리거 또는 서비스 계층)
```

> **[ORACLE-C-4 제약]** `voyage.status = COMPLETED` 전환 시 최소 1개 `voyage_fuel_use.actual_fuel_ton > 0`이 필요하다. 이는 DB 제약보다 애플리케이션 서비스 계층에서 검증한다. DB 트리거 대안도 가능하나 복잡도가 높다.
>
> **[S-1]** `fuel_type`에 FK 제약 추가. `ON UPDATE CASCADE`로 연료 코드 변경 시 자동 전파.
>
> **[S-2]** `(voyage_id, fuel_type)` UNIQUE 제약 추가. 동일 항차에 동일 연료 타입 레코드가 중복 삽입되는 것을 방지한다. 중복 시 CII 계산에서 CO₂ 배출량이 이중 산정되는 치명적 버그가 발생한다.

---

### 2.4 `voyage_scenario` — 운항 시나리오

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | 시나리오 ID |
| `vessel_id` | UUID | NOT NULL, FK → vessel(id) **ON DELETE CASCADE** **[S-8 추가]** | 대상 선박 |
| `voyage_id` | UUID | NULL, FK → voyage(id) **ON DELETE SET NULL** [DB-C-3] | 기존 항차에서 생성된 경우 |
| `scenario_type` | VARCHAR(20) | NOT NULL | DIRECT, DETOUR, SLOW_STEAMING |
| `scenario_name` | VARCHAR(100) | NOT NULL | 표시명 |
| `distance_nm` | NUMERIC(12,2) | NOT NULL | 시나리오 거리 |
| `speed_kn` | NUMERIC(6,2) | NOT NULL | 평균 속도 |
| `duration_hours` | NUMERIC(10,2) | NOT NULL | 예상 소요 시간 |
| `fuel_ton` | NUMERIC(12,4) | NOT NULL | 예상 연료 |
| `weather_factor` | NUMERIC(8,4) | NULL | 기상 보정 계수 |
| `cii_value` | NUMERIC(15,8) | NOT NULL | 항차 CII 추정값. **[M-8]** 목록 조회·정렬용 denormalized numeric cache. canonical Layer 1 값은 반드시 `calculation_run.result_json.attained_cii`를 사용 |
| `estimated_rating` | VARCHAR(1) | NOT NULL | A~E |
| `risk_level` | VARCHAR(10) | NOT NULL | LOW, MEDIUM, HIGH, CRITICAL |
| `is_adopted` | BOOLEAN | NOT NULL DEFAULT false | 사용자 반영 여부 |
| `is_deleted` | BOOLEAN | NOT NULL DEFAULT false | Soft delete **[M-1 추가]** |
| `weather_snapshot_id` | UUID | NULL, FK → weather_snapshot(id) **ON DELETE SET NULL** [DB-C-3] | 사용된 기상 스냅샷 |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 수정일 (§7.2 trigger로 자동 갱신) |

**검증 제약 [S-4]:**

```sql
ALTER TABLE voyage_scenario ADD CONSTRAINT chk_scenario_type
    CHECK (scenario_type IN ('DIRECT','DETOUR','SLOW_STEAMING'));
ALTER TABLE voyage_scenario ADD CONSTRAINT chk_scenario_rating
    CHECK (estimated_rating IN ('A','B','C','D','E'));
ALTER TABLE voyage_scenario ADD CONSTRAINT chk_scenario_risk
    CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL'));
-- [#84] 물리량 양수 검증. speed_kn은 아래 각주 참조(voyage와 통일해 >= 1.0).
ALTER TABLE voyage_scenario ADD CONSTRAINT chk_scenario_distance_positive
    CHECK (distance_nm > 0);
ALTER TABLE voyage_scenario ADD CONSTRAINT chk_scenario_speed_positive
    CHECK (speed_kn >= 1.0);
ALTER TABLE voyage_scenario ADD CONSTRAINT chk_scenario_duration_positive
    CHECK (duration_hours > 0);
ALTER TABLE voyage_scenario ADD CONSTRAINT chk_scenario_fuel_positive
    CHECK (fuel_ton > 0);
```

**인덱스:**

```sql
-- [#97] FK 자식 인덱스 — vessel/voyage 삭제 시 CASCADE·SET NULL 체크가
-- full table scan하지 않게 한다. 목록 조회(WHERE vessel_id ORDER BY created_at DESC)도
-- 함께 서비스한다 (idx_calc_vessel과 같은 복합 형태).
CREATE INDEX idx_scenario_vessel ON voyage_scenario (vessel_id, created_at DESC);
-- voyage_id는 SET NULL 체크 전용 — NULL 허용 컬럼이라 단일 컬럼으로 족하다.
CREATE INDEX idx_scenario_voyage ON voyage_scenario (voyage_id);
```

> **[S-8]** `vessel_id` 컬럼 추가. 기존 항차에서 생성되지 않은 독립 시나리오의 경우 `voyage_id`가 NULL이 되므로, 선박 단위 조회 및 권한 검사를 위해 `vessel_id`가 필수이다.
>
> **[M-1]** `is_deleted` 컬럼 추가. 다른 비즈니스 테이블과 삭제 정책을 통일한다.
>
> **[#84]** `distance_nm`, `speed_kn`, `duration_hours`, `fuel_ton`은 물리량이므로 양수 CHECK를 추가한다. `speed_kn`은 이슈 #84 본문의 `> 0`이 아니라 형제 테이블 `voyage`(§2.2 `chk_speed_positive`)의 `>= 1.0` 기준과 통일한다. 시나리오 채택(#58) 시 이 값이 `voyage.planned_speed_kn`으로 반영되는데, `> 0`으로 두면 `0.7`kn 같은 값이 입력 단계는 통과하나 채택 단계에서 `voyage`의 `>= 1.0`에 뒤늦게 걸리기 때문이다.

---

### 2.5 `calculation_run` — 계산 실행 결과

> **[X-2]** 이 테이블은 immutable이다. §7.3의 가드 트리거로 UPDATE/DELETE를 차단한다. **유일한 예외는 `needs_recalc`의 false→true 플립이다** (마이그레이션 024의 `calc_run_guard` — 나머지 컬럼이 불변일 때만 통과, true→false 되돌림·다른 컬럼 변경·DELETE는 여전히 거부).

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | 계산 실행 ID |
| `calculation_type` | VARCHAR(30) | NOT NULL | VOYAGE_ESTIMATE, SCENARIO, ANNUAL_DETERMINISTIC, ANNUAL_MONTE_CARLO |
| `vessel_id` | UUID | NOT NULL, FK → vessel(id) **ON DELETE RESTRICT** [DB-C-3] | 대상 선박 |
| `voyage_id` | UUID | NULL, FK → voyage(id) **ON DELETE RESTRICT** [DB-C-3, #28 정정] | 관련 항차 (있으면). 계산 이력 보존을 위해 항차 물리 삭제를 차단 |
| `weather_snapshot_id` | UUID | NULL, FK → weather_snapshot(id) **ON DELETE RESTRICT** [#102] | 계산에 사용한 기상 스냅샷 (있으면). NONE 모델·fallback 계산은 NULL. ⚠️ 실물 컬럼·FK는 #103(013 `weather_snapshot`) 생성 후 **016+ 후속 마이그레이션**에서 추가 |
| `input_hash` | VARCHAR(71) | NOT NULL | `sha256:` + 64 hex chars |
| `parameter_hash` | VARCHAR(71) | NOT NULL | `sha256:` + 64 hex chars |
| `model_version` | JSONB | NOT NULL | TECH_SPEC §10.1 structured JSON |
| `result_json` | JSONB | NOT NULL | 결과 snapshot (모든 출력값 포함) |
| `parameters_used` | JSONB | NOT NULL | TECH_SPEC §5.2.1 스키마 |
| `warnings_json` | JSONB | NULL | 경고 목록 배열 |
| `duration_ms` | INTEGER | NULL | 계산 소요 시간 (ms) |
| `needs_recalc` | BOOLEAN | NOT NULL DEFAULT false **[#283]** | 재계산 필요 표시. 선박 DWT/GT 변경 시 서비스가 false→true로만 플립한다 (PRD §8.4) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**인덱스:**

```sql
CREATE INDEX idx_calc_vessel ON calculation_run (vessel_id, created_at DESC);
CREATE INDEX idx_calc_input_hash ON calculation_run (input_hash, parameter_hash);
CREATE INDEX idx_calc_type ON calculation_run (calculation_type, created_at DESC);
-- [#115] FK 자식 인덱스. weather_snapshot 삭제 시 RESTRICT 검사가 full scan이 되지 않도록 한다.
CREATE INDEX idx_calc_weather_snapshot ON calculation_run (weather_snapshot_id);
```

**검증 제약 [S-7]:**

```sql
ALTER TABLE calculation_run ADD CONSTRAINT chk_input_hash_format
    CHECK (input_hash ~ '^sha256:[0-9a-f]{64}$');
ALTER TABLE calculation_run ADD CONSTRAINT chk_param_hash_format
    CHECK (parameter_hash ~ '^sha256:[0-9a-f]{64}$');
-- [#84] calculation_type enum 검증. 4개 허용값 외 임의 문자열 차단.
ALTER TABLE calculation_run ADD CONSTRAINT chk_calculation_type
    CHECK (calculation_type IN
        ('VOYAGE_ESTIMATE','SCENARIO','ANNUAL_DETERMINISTIC','ANNUAL_MONTE_CARLO'));
```

**`result_json` 구조 (계산 타입별):**

> 아래 두 블록은 **각각 유효한 JSON**이다. JSON 표준(RFC 8259)에 주석 문법이 없고 한 문서에 최상위 값이 하나만 올 수 있으므로, 변형별로 블록을 나누고 필드 설명은 블록 밖 표로 둔다. 복사해 파서에 그대로 넣을 수 있어야 재현성 테스트(`TEST_PLAN`)와 픽스처(`#45`)가 이 예시를 기준으로 삼을 수 있다.

**`calculation_type = VOYAGE_ESTIMATE`**

```json
{
  "attained_cii": "4.982400",
  "required_cii": "5.045066",
  "rating": "C",
  "co2_ton": "249.12",
  "risk_level": "MEDIUM",
  "weather_factor": "1.0482",
  "weather_snapshot_id": "uuid-or-null"
}
```

| 필드 | 설명 |
|---|---|
| `weather_factor` | **[#102]** 재현성 계약(`TECH_SPEC §5.4`). `weather_model = NONE`이거나 fallback이면 `"1.0"` |
| `weather_snapshot_id` | **[#102]** 계산에 사용한 기상 스냅샷. 없으면 `null` |

**`calculation_type = ANNUAL_MONTE_CARLO`**

```json
{
  "deterministic": { "projected_attained_cii": "5.02", "projected_rating": "C" },
  "monte_carlo": {
    "rng_metadata": {
      "seed_entropy": "0x000000000000000000000000003039",
      "bit_generator": "PCG64DXSM",
      "numpy_version": "2.1.0",
      "python_version": "3.12.4",
      "platform": "Linux-6.5.0-x86_64"
    },
    "runs": 5000,
    "rating_probabilities": { "A": 0.02, "B": 0.28, "C": 0.55, "D": 0.13, "E": 0.02 }
  }
}
```

**`model_version` JSONB 구조:**

```json
{
  "engine": "dual-precision-v1",
  "decimal_precision": 30,
  "decimal_rounding": "ROUND_HALF_UP",
  "rng_algorithm": "PCG64DXSM",
  "numpy_version": "2.1.0",
  "python_version": "3.12.4"
}
```

> **[S-7]** hash 형식 CHECK 제약 추가. `sha256:` prefix + 64 hex chars 형식이 아닌 값의 삽입을 차단한다.
>
> **검증 책임 (parameter_hash vs parameters_used):** `SHA256(canonical_json(parameters_used)) == parameter_hash` 검증은 애플리케이션 서비스 계층 또는 테스트 단계에서 수행한다 (Oracle 추가 관찰 #9).
>
> **[#28 정정]** `voyage_id`의 ON DELETE 정책을 `SET NULL` → `RESTRICT`로 정정했다 (이슈 #28). 근거: `calculation_run`은 immutable(§7.3, `BEFORE UPDATE OR DELETE` 트리거)이다. `SET NULL`은 PostgreSQL 내부적으로 자식 행 UPDATE로 실행되는데, immutable 트리거가 이 UPDATE를 차단하여 부모 `voyage` 삭제 트랜잭션 전체가 롤백된다. 즉 `SET NULL`은 원리적으로 달성 불가능하고 실효 동작이 `RESTRICT`다. 실효 동작에 문서를 맞추고, §7.1의 "immutable 테이블 참조는 RESTRICT" 관례와 대칭을 회복한다. (평소에는 voyage가 soft-delete(§2.2 `is_deleted`)만 되므로 이 경로가 드물어 잠복해 있던 모순이다.)
>
> **[#102] `weather_snapshot_id` 컬럼 (스펙 선행 정의):** 계산에 사용한 기상 스냅샷을 기록하여 재현성 계약(TECH_SPEC §5.4)의 추적성을 보장한다. 이슈 #102 본문의 "행 삭제 시 NULL로 설정"(SET NULL)은 [#28 정정]과 동일한 이유(immutable 트리거가 자식 UPDATE 차단)로 달성 불가능하므로 **RESTRICT로 정정**한다. NULL 허용 근거: `weather_model = NONE`·캐시 만료 fallback(TECH_SPEC §7.3)은 스냅샷 없이 계산하는 정상 경로이며, 컬럼 추가 이전의 기존 행도 backfill이 불가능하다. 실물 컬럼·FK·ORM 모델 반영은 #103(013 `weather_snapshot` 테이블) 완료 후 016+ 후속 마이그레이션에서 수행한다(ROADMAP §4.1 번호 규약).

---

### 2.6 `annual_simulation_run` — 연간 시뮬레이션 실행

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | 시뮬레이션 실행 ID |
| `calculation_run_id` | UUID | NOT NULL, FK → calculation_run(id) **ON DELETE RESTRICT** [DB-C-3] | 계산 실행 참조 |
| `vessel_id` | UUID | NOT NULL, FK → vessel(id) **ON DELETE RESTRICT** [DB-C-3] | 대상 선박 |
| `regulation_year` | INTEGER | NOT NULL | 기준연도 |
| `target_rating` | VARCHAR(1) | NOT NULL | 목표 등급 (A~D, E 불가) |
| `simulation_runs` | INTEGER | NOT NULL | Monte Carlo 반복 횟수 |
| `snapshot_id` | UUID | NOT NULL, FK → simulation_snapshot(id) **ON DELETE RESTRICT** [DB-C-3] | 스냅샷 참조. UNIQUE (1:1) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**검증 제약 [M-4, M-5]:**

```sql
ALTER TABLE annual_simulation_run ADD CONSTRAINT chk_target_rating
    CHECK (target_rating IN ('A','B','C','D'));  -- [M-4] E 불가
ALTER TABLE annual_simulation_run ADD CONSTRAINT chk_sim_runs_positive
    CHECK (simulation_runs > 0);  -- [M-5]

-- [S-6] 1:1 관계 보장
CREATE UNIQUE INDEX idx_sim_snapshot_unique ON annual_simulation_run (snapshot_id);
```

---

### 2.7 `simulation_snapshot` — 시뮬레이션 스냅샷

> TECH_SPEC §11 구현. 시뮬레이션 시작 시점의 항차 데이터 사본.
>
> **[X-2]** 이 테이블은 immutable이다. §7.3의 가드 트리거로 UPDATE/DELETE를 차단한다. **유일한 예외는 `needs_recalc`의 false→true 플립이다** (마이그레이션 024의 `calc_run_guard` — 나머지 컬럼이 불변일 때만 통과, true→false 되돌림·다른 컬럼 변경·DELETE는 여전히 거부).

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | 스냅샷 ID |
| `vessel_id` | UUID | NOT NULL, FK → vessel(id) **ON DELETE RESTRICT** [DB-C-3] | 대상 선박 |
| `regulation_year` | INTEGER | NOT NULL | 기준연도 |
| `voyages_json` | JSONB | NOT NULL | 항차별 완전한 데이터 사본 배열 |
| `input_hash` | VARCHAR(71) | NOT NULL | 스냅샷 시점 input_hash |
| `parameter_hash` | VARCHAR(71) | NOT NULL | 스냅샷 시점 parameter_hash |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 스냅샷 생성일 |

**검증 제약 [S-7]:**

```sql
ALTER TABLE simulation_snapshot ADD CONSTRAINT chk_snap_input_hash_format
    CHECK (input_hash ~ '^sha256:[0-9a-f]{64}$');
ALTER TABLE simulation_snapshot ADD CONSTRAINT chk_snap_param_hash_format
    CHECK (parameter_hash ~ '^sha256:[0-9a-f]{64}$');
```

**`voyages_json` 구조:**

```json
[
  {
    "snapshot_voyage_id": "uuid",
    "original_voyage_id": "uuid",
    "voyage_no": "V-2026-001",
    "status_at_snapshot": "CONFIRMED",
    "distance_nm": "11200.00",
    "speed_kn": "13.50",
    "fuel_uses": [
      { "fuel_type": "HFO", "fuel_ton": "850.0000", "cf_used": "3.114000" }
    ],
    "annual_inclusion_policy": "INCLUDE_AS_ACTUAL"
  }
]
```

> 스냅샷은 변경 불가(immutable)이다. 한 번 생성되면 수정되지 않는다.

**인덱스:**

```sql
-- [#97] FK 자식 인덱스 — vessel 삭제 시 RESTRICT 체크가 full table scan하지 않게.
CREATE INDEX idx_snapshot_vessel ON simulation_snapshot (vessel_id, created_at DESC);
```

---

### 2.8 `regulation_year` — 규정 연도 Z-factor

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `year` | INTEGER | NOT NULL, UNIQUE | 연도 |
| `z_factor_percent` | NUMERIC(8,4) | NOT NULL, CHECK (>= 0) [#96] | Z factor (%) |
| `effective_from` | DATE | NOT NULL | 적용 시작일 |
| `source_ref` | VARCHAR(200) | NOT NULL | 출처 — **값이 인쇄된 문서**를 적는다. 참조 지정만 하는 문서가 아니다(의미 정의는 §3.2 각주). 예: `MEPC.400(83)` |
| `version` | VARCHAR(50) | NOT NULL | 파라미터 세트 버전 |
| `is_active` | BOOLEAN | NOT NULL DEFAULT true | 활성 여부 |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

> **[#98] `updated_at`이 없는 것은 의도적이다.** 파라미터 테이블은 값이 개정되면 행을 고치지 않고 **새 `version` 행을 넣고 `is_active`를 전환**한다 — 기준과 예외(`fuel_type`)는 §7.2를 따른다.
>
> **[#96] `chk_z_factor_nonneg` (마이그레이션 023).** Z-factor reduction은 음수일 수 없다(MEPC.400(83) 0%~). 음수면 required_CII가 reference line보다 커지는 역산이 일어나 계산이 무의미해진다. 2023년의 `0`은 유효값이므로 `> 0`이 아니라 `>= 0`이다.

---

### 2.9 `fuel_type` — 연료 종류

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `code` | VARCHAR(30) | NOT NULL, UNIQUE | 연료 코드 (예: HFO, LNG) |
| `display_name` | VARCHAR(100) | NOT NULL | 표시명 |
| `cf` | NUMERIC(10,6) | NOT NULL, CHECK (> 0) [#96] | tCO₂/tFuel 변환계수 |
| `unit` | VARCHAR(30) | NOT NULL DEFAULT 'tCO₂/tFuel' | 단위 |
| `source_ref` | VARCHAR(200) | NOT NULL | 출처 — **값이 인쇄된 문서**를 적는다. 참조 지정만 하는 문서가 아니다(의미 정의는 §3.2 각주) |
| `version` | VARCHAR(50) | NOT NULL DEFAULT '1.0' **[X-3 추가]** | 파라미터 세트 버전 |
| `content_hash` | VARCHAR(71) | NULL **[X-3 추가]** | seed/update 시 산출된 content hash |
| `is_active` | BOOLEAN | NOT NULL DEFAULT true | 활성 여부 |
| `effective_from` | DATE | NULL | 적용 시작일 (OTHER 연료용) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 수정일 (§7.2 trigger로 자동 갱신) |

> **[X-3]** `version` 및 `content_hash` 컬럼 추가. TECH_SPEC §5.2의 `parameter_hash = SHA256(canonical_json(all_parameters))` 요구사항을 충족하기 위해, CF 값 변경 시 버전 및 content_hash를 갱신하여 파라미터 세트 변경을 추적 가능하게 한다.
>
> **[#96] `chk_cf_positive` (마이그레이션 023).** CF는 물리적으로 항상 양수다(MEPC.364(79) §2.2.1 기준값). 음수 cf가 들어가면 CO₂ 배출량이 음수가 되는 비상식적 결과가 나온다. `cii_reference_line`의 `chk_a_decimal_positive`·`chk_c_positive`와 같은 물리량 가드로 정합성을 맞춘다(Oracle 재리뷰 F5).

---

### 2.10 `cii_reference_line` — 선종별 CII Reference Line

> TECH_SPEC §9: `a_raw` VARCHAR + `a_decimal` NUMERIC(30,6) 이중 저장.
>
> **[EXT-P0-1]** `capacity_rule`은 **reference CII 공식(CII_ref = a × Capacity^(-c))에만 적용**된다. attained CII의 transport work(W = transport_capacity × Distance)에는 선박의 실제 DWT/GT를 사용한다 (IMO G1 vs G2 분리). `capacity_rule` 컬럼은 reference line 테이블에 속하므로 올바르게 스코프된다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `ship_type` | VARCHAR(50) | NOT NULL | CII 선종 |
| `condition_expr` | VARCHAR(200) | NOT NULL | 조건식 (예: `DWT >= 279000`, `all`) |
| `capacity_rule` | VARCHAR(50) | NOT NULL | `DWT`, `GT`, `fixed 279000` |
| `a_raw` | VARCHAR(50) | NOT NULL | IMO 원문 표기 (예: `14405E7`) |
| `a_decimal` | NUMERIC(30,6) | NOT NULL | Decimal 변환값 |
| `c` | NUMERIC(10,6) | NOT NULL | 지수 (예: 0.622). LNG_CARRIER DWT ≥ 100000의 경우 0.000000 (고정 CII_ref) |
| `source_ref` | VARCHAR(200) | NOT NULL | 출처 — **값이 인쇄된 문서**를 적는다. 참조 지정만 하는 문서가 아니다(의미 정의는 §3.2 각주) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**인덱스:**

```sql
CREATE UNIQUE INDEX idx_refline_unique ON cii_reference_line (ship_type, condition_expr);
CREATE INDEX idx_refline_ship_type ON cii_reference_line (ship_type);
```

**검증 제약:**

```sql
-- [M-7] 'fixed' 뒤에 숫자만 허용하도록 강화
ALTER TABLE cii_reference_line ADD CONSTRAINT chk_capacity_rule
    CHECK (capacity_rule IN ('DWT','GT') OR capacity_rule ~ '^fixed \d+$');

ALTER TABLE cii_reference_line ADD CONSTRAINT chk_a_decimal_positive CHECK (a_decimal > 0);
ALTER TABLE cii_reference_line ADD CONSTRAINT chk_c_positive CHECK (c >= 0);
```

> 애플리케이션 시작 시 `parse_imo_scientific(a_raw) == a_decimal` 검증을 수행한다 (TECH_SPEC §9.3).
>
> **[Oracle 관찰]** `c = 0.000000` for LNG_CARRIER DWT ≥ 100000은 **정상**이다. MEPC.353(78) Table 1에 따라 대형 LNG 캐리어는 고정 CII_ref 값을 사용하며 `CII_ref = 9.827 × Capacity^0 = 9.827`이다.

---

### 2.11 `cii_rating_boundary` — 등급 경계 d-vector

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `ship_type` | VARCHAR(50) | NOT NULL | CII 선종 |
| `condition_expr` | VARCHAR(200) | NOT NULL | 조건식 |
| `capacity_basis` | VARCHAR(10) | NOT NULL | DWT 또는 GT |
| `d1` | NUMERIC(6,4) | NOT NULL | superior boundary 계수 |
| `d2` | NUMERIC(6,4) | NOT NULL | lower boundary 계수 |
| `d3` | NUMERIC(6,4) | NOT NULL | upper boundary 계수 |
| `d4` | NUMERIC(6,4) | NOT NULL | inferior boundary 계수 |
| `source_ref` | VARCHAR(200) | NOT NULL | 출처 — **값이 인쇄된 문서**를 적는다. 참조 지정만 하는 문서가 아니다(의미 정의는 §3.2 각주) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**인덱스:**

```sql
CREATE UNIQUE INDEX idx_boundary_unique ON cii_rating_boundary (ship_type, condition_expr);
```

**검증 제약 [M-3]:**

```sql
-- d-vector 순서 보장: d1 < d2 < d3 < d4
-- d1/d2는 1.0 미만(양호 등급 경계), d3/d4는 1.0 초과(불량 등급 경계)
ALTER TABLE cii_rating_boundary ADD CONSTRAINT chk_d_order
    CHECK (d1 < d2 AND d2 < d3 AND d3 < d4);
```

---

### 2.12 `weather_model_parameter` — 기상 모델 파라미터

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `model_version` | VARCHAR(50) | NOT NULL | NONE, SIMPLE_RULE, TOWNSIN_KWON_ALPHA |
| `key` | VARCHAR(100) | NOT NULL | 파라미터 키 |
| `value` | VARCHAR(200) | NOT NULL | 파라미터 값 |
| `unit` | VARCHAR(30) | NULL | 단위 |
| `source_ref` | VARCHAR(200) | NULL | 출처 — **값이 인쇄된 문서**를 적는다. 참조 지정만 하는 문서가 아니다(의미 정의는 §3.2 각주) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**인덱스 [S-5]:**

```sql
-- (model_version, key) 조합의 유일성 보장
CREATE UNIQUE INDEX idx_weather_param_unique ON weather_model_parameter (model_version, key);
```

---

### 2.13 `weather_snapshot` — 기상 스냅샷

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `lat` | NUMERIC(9,6) | NOT NULL | 위도 |
| `lon` | NUMERIC(9,6) | NOT NULL | 경도 |
| `lat_rounded` | NUMERIC(4,1) | NOT NULL | 반올림 위도 (캐시 key용) |
| `lon_rounded` | NUMERIC(5,1) | NOT NULL | 반올림 경도 (캐시 key용) |
| `fetched_at` | TIMESTAMPTZ | NOT NULL | 조회 시각 |
| `wave_height_m` | NUMERIC(6,2) | NULL | 유의파고 |
| `wave_direction_deg` | NUMERIC(6,2) | NULL | 파향 |
| `wave_period_s` | NUMERIC(6,2) | NULL | 파 주기 |
| `wind_speed_ms` | NUMERIC(6,2) | NULL | 풍속 |
| `wind_direction_deg` | NUMERIC(6,2) | NULL | 풍향 |
| `source` | VARCHAR(50) | NOT NULL | open_meteo_marine, open_meteo_forecast, sample |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**인덱스:**

```sql
CREATE INDEX idx_weather_cache ON weather_snapshot (lat_rounded, lon_rounded, fetched_at DESC);
```

> 캐시 TTL 24시간. 24시간 초과 스냅샷은 PRD §11.6 기상 API 장애 정책에 따라 fallback 처리된다.
>
> **[#102] TTL과 보존의 구분:** TTL 24시간은 **재사용 판단 기준(신선도 창)이지 삭제 스케줄이 아니다.** `calculation_run.weather_snapshot_id`(§2.5 [#102], FK **RESTRICT**)가 참조하는 스냅샷은 TTL 경과와 무관하게 보존되어야 재현성 계약(TECH_SPEC §5.4)의 추적성이 성립한다. 캐시 정리(eviction) 작업은 **참조되지 않는 행만** 삭제해야 하며, 참조 행을 포함한 일괄 DELETE는 RESTRICT에 막혀 트랜잭션 전체가 롤백된다.

---

### 2.14 `audit_log` — 감사 로그

> TECH_SPEC §13.1 요구사항.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | ID |
| `timestamp` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 이벤트 시각 |
| `user_id` | VARCHAR(100) | NULL | 실행 사용자 ID |
| `action` | VARCHAR(50) | NOT NULL | PARAMETER_CHANGE, VOYAGE_CONFIRM, CALCULATION_RUN, VOYAGE_TRANSITION, IMPORT, EXPORT, **LOGIN_SUCCESS, LOGIN_FAILURE, LOGOUT** [#277] |
| `entity_type` | VARCHAR(30) | NULL | `vessel`, `voyage`, `calculation_run`, **`regulation_year`**, **`fuel_type`**, **`reference_line`** **[Oracle 관찰 #4]** |
| `entity_id` | UUID | NULL | 대상 엔티티 ID. 모든 파라미터 테이블이 UUID PK를 가지므로 정상 동작 |
| `details_json` | JSONB | NULL | 상세 정보 (변경 전후 값 등) |
| `ip_address` | VARCHAR(45) | NULL | 요청 IP |

**인덱스:**

```sql
CREATE INDEX idx_audit_timestamp ON audit_log (timestamp DESC);
CREATE INDEX idx_audit_entity ON audit_log (entity_type, entity_id);
CREATE INDEX idx_audit_action ON audit_log (action, timestamp DESC);
```

> **[Oracle 관찰 #4]** `entity_type = 'parameter'` 대신 구체적인 테이블명(`regulation_year`, `fuel_type`, `reference_line`)을 사용하여 조회성을 향상시킨다. 모든 파라미터 테이블이 UUID PK를 가지므로 `entity_id` 호환성에 문제가 없다.
>
> **[#277] 인증 이벤트 (LOGIN_SUCCESS · LOGIN_FAILURE · LOGOUT).** `user_id`는 `app_user.id`(§2.15)다. 실패 시 주체를 알 수 없어 `NULL`이며, `details_json`은 사유 코드(`reason`)만 담는다 — **`id_token`·`code`·state·세션 토큰 등 자격 증명 값은 절대 기록하지 않는다.** 스텁 dev-login도 같은 스트림에 남기며 `details_json.dev_login` 플래그로 구분한다. `LOGOUT`은 실제 세션 무효화가 일어난 경우만 기록한다(멱등 재호출 제외).

---

### 2.15 `app_user` — 사용자 (#273)

> `PRD §7.10` 요구사항. **제품이 비밀번호를 직접 관리한다**(#413) — 단, 저장하는 것은 해시뿐이다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK, NOT NULL | 내부 사용자 ID |
| `password_hash` | VARCHAR(255) | NOT NULL | 비밀번호 해시(Argon2id). **평문을 저장하지 않는다** |
| `email_verified_at` | TIMESTAMPTZ | NULL | 이메일 인증 완료 시각. `NULL`이면 미인증 |
| `email` | VARCHAR(320) | NOT NULL | 표시·연락용. **식별자가 아니다** |
| `display_name` | VARCHAR(100) | NULL | 표시 이름 |
| `last_login_at` | TIMESTAMPTZ | NULL | 마지막 로그인 시각 |
| `is_deleted` | BOOLEAN | NOT NULL DEFAULT false | Soft delete 플래그 |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 수정일 (§7.2 trigger로 자동 갱신) |

**인덱스:**

```sql
CREATE UNIQUE INDEX idx_app_user_email ON app_user (email) WHERE is_deleted = false;
```

> **[#413] `email`이 로그인 ID이자 유일 키다.** 종전에는 *"구글 계정의 이메일은 변경될 수 있으므로 unique를 걸지 않는다"* 로 두고 유일성을 `google_sub`에 두었으나, **구글 위임을 그만두면서 그 전제가 사라졌다**(`PRD O-14`). 자체 인증에서 이메일은 사용자가 스스로 정하는 로그인 ID이므로 유일해야 한다.
>
> **`password_hash`는 해시만 담는다.** 평문 비밀번호는 저장·로그·감사 기록 어디에도 남기지 않는다 — `app_session`이 토큰 원문을 저장하지 않는 것(§2.16)과 같은 원칙이다.

### 2.15.1 `user_token` — 일회용 인증 토큰 (#408)

이메일 인증과 비밀번호 재설정에 쓰는 **한 번 쓰고 버리는 증명**이다. 세션(`§2.16`)과 수명주기가 달라 별도 테이블로 둔다 — 세션은 로그인 상태를 유지하고 이 토큰은 단발성이다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK | |
| `user_id` | UUID | NOT NULL, **FK → app_user(id) ON DELETE CASCADE** | 토큰 소유자 |
| `purpose` | VARCHAR(20) | NOT NULL, CHECK IN (`EMAIL_VERIFY`, `PASSWORD_RESET`) | 용도 |
| `token_hash` | VARCHAR(64) | NOT NULL, UNIQUE | 토큰의 SHA-256 hex. **원문을 저장하지 않는다** |
| `expires_at` | TIMESTAMPTZ | NOT NULL | 만료 시각 |
| `used_at` | TIMESTAMPTZ | NULL | 사용 시각. NOT NULL이면 재사용 불가 |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

```sql
CREATE UNIQUE INDEX idx_user_token_hash ON user_token (token_hash);
CREATE INDEX idx_user_token_user_purpose ON user_token (user_id, purpose);
```

> **원문 대신 해시만 저장한다.** `app_session.session_token_hash`(§2.16)와 같은 규칙이다 — **DB가 유출돼도 토큰을 되돌릴 수 없어야 한다.** 원문은 메일 본문에만 실린다.
>
> **유효기간** — 이메일 인증 24시간 · 비밀번호 재설정 1시간. 재설정이 짧은 것은 그 토큰이 계정을 통째로 넘기는 힘을 갖기 때문이다.
>
> 실물 테이블 생성은 **`#408`**이 담당한다. 이 절은 계약만 확정한다.

### 2.16 `user_session` — 로그인 세션 (#273)

> API_SPEC §1.2 요구사항. 세션 토큰은 SHA-256 해시만 저장한다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK, NOT NULL | 세션 ID |
| `user_id` | UUID | NOT NULL, **FK → app_user(id) ON DELETE CASCADE** | 세션 소유자 |
| `session_token_hash` | VARCHAR(64) | NOT NULL, UNIQUE | 쿠키 값의 SHA-256 hex. **원문을 저장하지 않는다** |
| `csrf_token_hash` | VARCHAR(64) | NOT NULL | CSRF 토큰의 SHA-256 hex |
| `expires_at` | TIMESTAMPTZ | NOT NULL | 만료 시각 |
| `revoked_at` | TIMESTAMPTZ | NULL | 로그아웃 시각. NOT NULL이면 무효 |
| `user_agent` | VARCHAR(255) | NULL | 요청 User-Agent (감사용) |
| `ip_address` | VARCHAR(45) | NULL | 발급 시 IP |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**인덱스:**

```sql
CREATE UNIQUE INDEX idx_session_token ON user_session (session_token_hash);
CREATE INDEX idx_session_user ON user_session (user_id, created_at DESC);
CREATE INDEX idx_session_expiry ON user_session (expires_at) WHERE revoked_at IS NULL;
```

> **세션 토큰 원문을 저장하지 않는다** — DB 유출 시 저장된 값으로 로그인 위조를 막기 위함. 비밀번호를 해시하는 것과 같은 이유.

> **[#287] `chat_session`·`chat_message`은 이 스키마에 정의돼 있지 않다.** 챗봇(O-12)은 실험 기능(PRD §5.1 MAY)이며 구현 이슈(#120~#123) 시점에 별도 마이그레이션으로 추가한다. 귀속 주체만 확정해 둔다 — `PRD §7.8`의 `ChatSession.user_id`는 **`app_user.id`(§2.15)** 를 참조한다(인증 주체 모델 #273 · #275 확정에 따른 결정). 보존 정책(90일)은 §4.3에 반영한다.

---

### 2.17 `not_underway_period` — not under way 구간 (#345)

> 마이그레이션 025. 항해하지 않는 구간(정박·묘박·표류·STS·운하 통과·드라이독)을 기록한다. 현재 연료는 `voyage_fuel_use`로 **항차에만** 매달려 있어 이 구간의 연료를 담을 곳이 없었다. 귀속은 **선박+규제연도** — 정박은 항차 사이에 있어 특정 항차에 속하지 않는다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK, NOT NULL DEFAULT `gen_random_uuid()` | 행 ID |
| `vessel_id` | UUID | NOT NULL, **FK → vessel(id) ON DELETE RESTRICT** | 소유 선박 |
| `regulation_year` | INTEGER | NOT NULL | 규제연도 (YTD·연간 실적 집계 축) |
| `period_type` | VARCHAR(20) | NOT NULL, CHECK 허용값 6종 | `IN_PORT`/`AT_ANCHOR`/`DRIFTING`/`STS`/`CANAL_TRANSIT`/`DRYDOCK` |
| `started_at` | TIMESTAMPTZ | NOT NULL | 구간 시작 |
| `ended_at` | TIMESTAMPTZ | NULL | 구간 종료. NULL이면 진행 중. **CHECK: `ended_at IS NULL OR ended_at > started_at`** |
| `port_name` | VARCHAR(200) | NULL | 항구명 (정박·입항 시) |
| `lat` | NUMERIC(9,6) | NULL | 구간 위치 위도 |
| `lon` | NUMERIC(9,6) | NULL | 구간 위치 경도 |
| `voyage_id` | UUID | NULL, **FK → voyage(id) ON DELETE SET NULL** | 맥락 항차 참조. 항차 삭제 시 링크만 끊긴다 |
| `distance_nm` | NUMERIC(12,2) | NOT NULL DEFAULT 0, **CHECK: `distance_nm >= 0`** | 구간 이동 거리 (nm). **CII 분모 `Dt`에 더해진다** — 마이그레이션 028 (#353) |
| `is_deleted` | BOOLEAN | NOT NULL DEFAULT false | soft delete |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 수정일 (§7.2 trigger로 자동 갱신) |

**인덱스:**

```sql
CREATE INDEX idx_not_underway_period_vessel_year
    ON not_underway_period (vessel_id, regulation_year)
    WHERE is_deleted = false;

-- 029 (#376) — #368 시뮬레이션 시계의 구간 겹침 조회 경로.
-- vessel_year는 regulation_year가 선행열이 아니라 started_at 범위 조건이
-- 인덱스로 내려가지 않는다.
CREATE INDEX idx_not_underway_period_vessel_started
    ON not_underway_period (vessel_id, started_at)
    WHERE is_deleted = false;

-- 029 (#376) — fk_not_underway_period_voyage가 ON DELETE SET NULL이라 인덱스가
-- 없으면 voyage 삭제 시 자식 확인이 full scan 한다 (023 idx_scenario_voyage 패턴).
-- FK 확인은 삭제된 행도 봐야 하므로 partial로 두지 않는다.
CREATE INDEX idx_not_underway_period_voyage
    ON not_underway_period (voyage_id);
```

> **`period_type` 6값의 근거** — 「not under way」는 정박보다 넓다. `MEPC.401(83)` 기준으로 EOSP → 다음 FAOP 구간이며 묘박·표류·STS·운하 통과를 포함하고, 드라이독도 idle 배출 범위에 든다. 정박 지속 시 연료(분자 `M`)만 늘고 거리(분모 `W`)는 늘지 않아 등급이 악화된다 — 이것이 규제 계산식이 원래 그렇게 동작하는 것이다(`MEPC 82/6/31`: *"emissions continue to accumulate without corresponding transport work … penalised under the current system"*).

> **✅ 원문 대조 완료 (2026-08-15, #358).** IMO 공식 PDF를 직접 대조했다.
>
> - **`M` — 포함이 맞다.** `MEPC.352(78)` §4.1: *"The total mass of CO₂ is the sum of CO₂ emissions (in grams) from **all the fuel oil consumed on board a ship in a given calendar year**"*. 항해 여부를 가리지 않는다.
> - **`Dt` — 종전 전제가 틀렸다.** `MEPC.412(84)` §4.2(2026-05-01 채택, G1 §4.2를 통째로 교체): *"the total distance travelled **(both under way and not under way)** in a given calendar year"*. **not under way 구간의 이동 거리도 분모에 들어간다.** 그래서 마이그레이션 028이 `distance_nm`을 추가했다.
>
> ⚠️ **구판 `MEPC.352(78)` §4.2에는 이 한정어가 없다**(*"the distance travelled in a given calendar year"*). 한정어가 없어 「under way만」으로 읽었던 것이 종전 전제였다. **구판을 출처로 인용하면 오기가 된다.**
>
> 접안·묘박은 이동이 0이라 분모에 기여하지 않으므로 **「정박 지속 시 등급 악화」는 그대로 성립**한다. 분모를 실제로 늘리는 것은 운하 통과(수에즈 약 104 nm·파나마 약 44 nm)·표류·STS다.

---

### 2.18 `not_underway_fuel_use` — not under way 연료 사용량 (#345)

> 마이그레이션 025. 구간의 소비자별 연료 기록. `voyage ──< voyage_fuel_use` 부모-자식 패턴과 동일하다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK, NOT NULL DEFAULT `gen_random_uuid()` | 행 ID |
| `period_id` | UUID | NOT NULL, **FK → not_underway_period(id) ON DELETE CASCADE** | 소속 구간 |
| `consumer_type` | VARCHAR(20) | NOT NULL, CHECK 허용값 4종 | `MAIN_ENGINE`/`AUX_ENGINE`/`OIL_FIRED_BOILER`/`OTHER` |
| `fuel_type` | VARCHAR(30) | NOT NULL, **FK → fuel_type(code) ON UPDATE CASCADE ON DELETE NO ACTION** | 연료 코드 |
| `fuel_ton` | NUMERIC(12,2) | NOT NULL, CHECK `fuel_ton > 0` | 사용량 (t) |
| `cf_used` | NUMERIC(10,6) | NOT NULL, CHECK `cf_used > 0` | **계산 시점 CF snapshot** (마이그레이션 030 · `#378`) |

> **`cf_used`가 필요한 이유 (`#378`)** — `PRD` §8.4가 「연료 CF 변경: 변경 이후 계산에만 적용. **과거 계산은 snapshot 보존**」을 규정한다. 030 이전에는 이 표에 snapshot 컬럼이 없어 `#353` YTD 집계가 `fuel_type.cf` **현재값**을 조회했고, `voyage_fuel_use`는 `cf_used`를 쓰므로 **같은 연도·같은 선박 안에서 항차 연료는 옛 CF, 정박 연료는 새 CF**로 계산됐다. 같은 실적인데 조회 시점에 따라 YTD가 달라지는 상태였다.
>
> 맞추는 방향은 **스냅샷 쪽**이다. `fuel_type.cf` 현재값으로 통일하면 두 갈래가 일치하지만 `cf_used`의 존재 이유를 무시하고 §8.4를 정면으로 위반하며, 기능①(`voyage_cii`)의 계산 근거와도 어긋난다.
>
> 집계는 `(fuel_type, cf_used)`로 묶는다. CF 개정 후에는 같은 유종에 snapshot이 둘 이상 생기며, 하나로 합쳐 대표 CF를 고르면 그 차이가 사라진다. 계산 엔진은 같은 `fuel_code`가 여러 번 들어와도 배출량을 합산하므로 묶음을 그대로 넘기는 것이 정확하다.
>
> 백필은 무손실이다 — `fuel_type`은 `code`가 PK인 단일 행 테이블이라 CF 이력을 보관하지 않으며, 아직 CF 개정이 일어난 적이 없어 현재값이 곧 기록 시점값이다.

**인덱스:**

```sql
-- 029 (#376) [S-2 패턴] — 구간+소비원+연료 중복 방지.
-- 선행열이 period_id라 FK 자식 조회(CASCADE·조인) 경로도 이 인덱스가 처리한다.
CREATE UNIQUE INDEX idx_not_underway_fuel_use_unique
    ON not_underway_fuel_use (period_id, consumer_type, fuel_type);
```

> **⚠️ 중복 삽입은 CO₂를 이중 산정한다 (`#376`).** `§2.3` **[S-2]**가 `voyage_fuel_use`에서 막아 둔 것과 같은 사안이다. `#353`의 YTD 집계(`sum_fuel_by_type`)가 `Σ(fuel_ton)`을 유종별로 합산하므로, 같은 구간·소비원·연료 행이 두 번 들어가면 분자 `M`이 그만큼 부풀고 **등급이 실제보다 나쁘게** 나온다.
>
> 키가 3열인 이유는 `consumer_type` 축이 있기 때문이다 — `MEPC.385(81)` DCS 보고 단위가 「구간 × 소비원 × 연료」이므로, 한 구간에서 보조엔진과 보일러가 같은 유종을 쓰는 것은 **정상 기록**이며 막으면 안 된다.
>
> 마이그레이션 025의 `idx_not_underway_fuel_use_period (period_id)`는 029에서 **제거했다.** 위 UNIQUE의 선행열이 같아 prefix 조회를 그대로 처리하므로 완전히 중복이며, 선례인 `voyage_fuel_use`(006)도 UNIQUE 인덱스 하나만 둔다.

> **`consumer_type` 4값의 근거** — `MEPC.385(81)`이 MARPOL Annex VI Appendix IX에 추가한 DCS 보고 항목 그대로다. 적용 시작이 **데이터연도 2026년**으로 본 프로젝트 기준연도와 일치한다.

---

### 2.19 `simulation_parameter` — Monte Carlo 분포 파라미터 (#434)

> `PRD §12.4.1` 구현. *"분포 기본값은 `simulation_parameter`로 관리하며 **코드 하드코딩하지 않는다**"* 를 충족한다.
>
> **왜 테이블인가.** 삼각분포의 min/mode/max는 규제값이 아니라 **모델 가정**이다. 운항 데이터가 쌓이면 조정될 값이고, 그때 코드를 고쳐 배포하는 대신 행을 바꿀 수 있어야 한다 — `regulation_year`·`cii_reference_line`을 코드 밖에 둔 것과 같은 이유다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT `gen_random_uuid()` | 내부 ID |
| `profile` | VARCHAR(30) | NOT NULL | 프로파일명. `PRD §12.2`의 `distribution_profile` 입력값과 같은 어휘 |
| `variable` | VARCHAR(20) | NOT NULL, CHECK | `DISTANCE` · `FUEL` · `SPEED` |
| `distribution` | VARCHAR(20) | NOT NULL, CHECK | `TRIANGULAR` (MVP는 이 하나) |
| `bound_type` | VARCHAR(10) | NOT NULL, CHECK | `FACTOR`(계획값의 배수) · `DELTA`(계획값에 더하는 값) |
| `min_value` | NUMERIC(10,4) | NOT NULL | 삼각분포 좌단 |
| `mode_value` | NUMERIC(10,4) | NOT NULL | 최빈값. 계획값 자체이므로 `FACTOR`면 `1.0`, `DELTA`면 `0.0` |
| `max_value` | NUMERIC(10,4) | NOT NULL | 삼각분포 우단 |
| `floor_value` | NUMERIC(10,4) | NULL | 물리 하한. 속도만 `1.0`(kn)을 갖는다 |
| `source_ref` | VARCHAR(200) | NOT NULL | 출처. `PRD §12.4.1` |
| `version` | VARCHAR(50) | NOT NULL | 파라미터 판본 |
| `is_active` | BOOLEAN | NOT NULL DEFAULT true | 비활성 행은 조회에서 제외 |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | 생성일 |

**`bound_type`이 필요한 이유.** `PRD §12.4.1` 표에서 거리·연료는 계획값의 **배수**(`0.97×plan`)지만 속도는 **덧셈**(`plan − 1kn`)이다. 한 컬럼 집합으로 둘을 담으려면 해석 방식을 행이 스스로 말해야 한다. 배수만 지원하면 속도를 표현할 수 없고, 속도를 위해 별도 테이블을 만들면 같은 개념이 두 곳에 생긴다.

**검증 제약:**

```sql
ALTER TABLE simulation_parameter ADD CONSTRAINT chk_sim_param_variable
  CHECK (variable IN ('DISTANCE','FUEL','SPEED'));
ALTER TABLE simulation_parameter ADD CONSTRAINT chk_sim_param_distribution
  CHECK (distribution IN ('TRIANGULAR'));
ALTER TABLE simulation_parameter ADD CONSTRAINT chk_sim_param_bound_type
  CHECK (bound_type IN ('FACTOR','DELTA'));
-- PRD §12.4.1 [ORACLE 삼각분포 가드] — min ≤ mode ≤ max 불변식.
-- 애플리케이션도 재조정하지만(계산이 파라미터 오타로 죽지 않게), 애초에
-- 위반한 행이 들어오지 않는 편이 낫다.
ALTER TABLE simulation_parameter ADD CONSTRAINT chk_sim_param_bounds_ordered
  CHECK (min_value <= mode_value AND mode_value <= max_value);
ALTER TABLE simulation_parameter ADD CONSTRAINT chk_sim_param_floor_positive
  CHECK (floor_value IS NULL OR floor_value > 0);
```

**인덱스:**

```sql
-- 조회는 언제나 (프로파일, 변수) 단위다. 같은 조합이 둘이면 어느 쪽을 쓸지 알 수 없다.
CREATE UNIQUE INDEX idx_sim_param_unique ON simulation_parameter (profile, variable);
```

**재현성 (`TECH_SPEC §5.4`).** 이 행이 바뀌면 **같은 seed로 다시 돌려도 결과가 달라진다.** 그래서 시뮬레이션 실행은 사용한 프로파일을 `calculation_run.parameters_used`에 함께 기록한다 — `parameter_hash`가 그 내용을 덮으므로 「동일 파라미터 버전」이 해시로 고정된다. 상세는 `TECH_SPEC §5.2.1`.

`voyage_fuel_use.cf_used`가 CF 개정에 대해 하는 일과 같은 처리다(`#378`).

## 3. 시드 데이터

### 3.1 규정 연도 Z-factor

> PRD §3.4.1 기준.

| year | z_factor_percent | source_ref |
|---|---|---|
| 2023 | 5.0000 | MEPC.400(83) |
| 2024 | 7.0000 | MEPC.400(83) |
| 2025 | 9.0000 | MEPC.400(83) |
| 2026 | 11.0000 | MEPC.400(83) |
| 2027 | 13.6250 | MEPC.400(83) |
| 2028 | 16.2500 | MEPC.400(83) |
| 2029 | 18.8750 | MEPC.400(83) |
| 2030 | 21.5000 | MEPC.400(83) |

> **[z-factor 출처 확인 · PR #145]** 위 8개 값은 **MEPC.400(83) Table 1**(MEPC.338(76) G3 개정 — 2027~2030 계수 도입, 2025-04-11 채택)에 인쇄되어 있으며 원문과 전건 일치한다. `source_ref`에는 값이 인쇄된 문서를 적는다(§3.2 각주와 같은 기준).
>
> 2023~2026(5 · 7 · 9 · 11%)은 **MEPC.338(76)이 최초 제정**하고 `MEPC.400(83)`이 재수록한 값이다. 다만 `MEPC.338(76)` Table 1은 **2027~2030이 공란**(`- **`)이므로, 그 문서를 출처로 적으면 8행 중 절반이 검증 불가능해진다. 8행 모두 `MEPC.400(83)`이 맞다.
>
> **원문 대조 확인: sky01170851.**

### 3.2 연료 CF 기본값

> PRD §3.4.2 기준.

| code | display_name | cf | source_ref |
|---|---|---|---|
| DIESEL_GAS_OIL | Diesel/Gas Oil | 3.206000 | MEPC.364(79) |
| LFO | Light Fuel Oil | 3.151000 | MEPC.364(79) |
| HFO | Heavy Fuel Oil | 3.114000 | MEPC.364(79) |
| LPG_PROPANE | LPG Propane | 3.000000 | MEPC.364(79) |
| LPG_BUTANE | LPG Butane | 3.030000 | MEPC.364(79) |
| LNG | Liquefied Natural Gas | 2.750000 | MEPC.364(79) |
| METHANOL | Methanol | 1.375000 | MEPC.364(79) |
| ETHANOL | Ethanol | 1.913000 | MEPC.364(79) |

> **[#87 정정]** `source_ref`에는 **값이 인쇄된 문서**를 적는다(검증·추적 목적 — 문서를 열었을 때 숫자가 실제로 있어야 한다). 위 8개 CF 값은 **MEPC.364(79) §2.2.1 표**(Annex 9, 4~5쪽)에 인쇄되어 있다.
>
> CII 계산에 쓰는 값인데 출처가 EEDI 계산 지침인 이유: **G1(MEPC.352(78)) §4.1이 CF를 이 계열에 참조 지정**하기 때문이다 — *"C_Fj … in line with those specified in the 2018 Guidelines … (resolution MEPC.308(73)), as may be further amended."* 문언상 지목 판본은 `MEPC.308(73)`이나 현행 대체판은 `MEPC.364(79)`다(`322(74)` · `332(76)` 경유 → `364(79)`가 앞의 셋을 폐지·대체, 이후 개정 없음).
>
> 종전 표기 `MEPC.352(78)`은 오류였다. G1에는 CF 표가 존재하지 않는다.
>
> **원문 대조 확인: sky01170851.** 위 판정(`MEPC.364(79)` §2.2.1에 값이 인쇄되어 있음 · `MEPC.352(78)` §4.1이 참조 지정만 함 · 판본 사슬 `308(73)`→`322(74)`·`332(76)`→`364(79)`)은 IMO 원문을 직접 대조해 확인한 결과다. 위 8개 값이 원문과 전건 일치함도 함께 확인됐다.

### 3.3 선종별 Reference Line

> PRD §3.4.3 기준. `a_raw`는 IMO 원문 표기 그대로 저장.

> **[#149] 20행 전수 대조 완료 — 2026-07-30 · 불일치 0건.** 원문 `MEPC.353(78)` Table 1(`MEPC 78/17/Add.1` Annex 15, 인쇄면 4쪽)과 `db/seed.py`의 `SEED_REFERENCE_LINES`를 `ship_type` · `condition_expr` · `capacity_rule` · `a_raw` · `c` **5개 필드 전부** 행 단위로 대조했다. 원문 20행 = seed 20행이고 인쇄 순서도 같다. **최상위 선종은 12종**이며 18·19행이 `Ro-ro passenger ship` 칸 아래 하위 2행이다. 원문 `Capacity` 칸에 숫자가 든 캡 3건(벌크 279,000 · LNG 65,000 · ro-ro 차량운반선 57,700)이 seed의 `fixed N` 3건과 일대일로 대응한다.
>
> **특기 사항** — ⑴ `GENERAL_CARGO_SHIP` `DWT < 20,000`의 `c = 0.3885`는 소수 4자리라 `0.389`로 반올림 전사되기 쉬운 지점인데 seed가 4자리를 보존한다. ⑵ LNG 두 밴드의 `a`(`14479E10` · `14779E10`)는 `AGENTS §2.3`이 오정정 사례로 기록해 둔 값 쌍이며, 원문에서도 서로 다른 값임이 재확인됐다. ⑶ LNG `DWT ≥ 100,000`의 `c = 0.000`은 상수 기준선으로 정상이다(§2.10).
>
> **대조 절차와 재현 명령**(PDF 페이지 인덱스 · 전사 가드 포함)은 `db/seed.py`의 `SEED_REFERENCE_LINES` 주석에 있다. 값 옆에는 결과를, 코드에는 절차를 두어 원문을 다시 받지 않고도 「이 값들은 언제 무엇과 대조됐는가」에 답할 수 있게 한다.
>
> ⚠️ **이 대조는 개발이 수행했다.** `AGENTS §2.1`이 요구하는 **팀원 원문 확인은 아직 없다** — §3.1 · §3.2 각주와 달리 확인자 이름이 비어 있는 이유다.

| ship_type | condition_expr | capacity_rule | a_raw | c |
|---|---|---|---|---|
| BULK_CARRIER | DWT >= 279000 | fixed 279000 | 4745 | 0.622000 |
| BULK_CARRIER | DWT < 279000 | DWT | 4745 | 0.622000 |
| GAS_CARRIER | DWT >= 65000 | DWT | 14405E7 | 2.071000 |
| GAS_CARRIER | DWT < 65000 | DWT | 8104 | 0.639000 |
| TANKER | all | DWT | 5247 | 0.610000 |
| CONTAINER_SHIP | all | DWT | 1984 | 0.489000 |
| GENERAL_CARGO_SHIP | DWT >= 20000 | DWT | 31948 | 0.792000 |
| GENERAL_CARGO_SHIP | DWT < 20000 | DWT | 588 | 0.388500 |
| REFRIGERATED_CARGO_CARRIER | all | DWT | 4600 | 0.557000 |
| COMBINATION_CARRIER | all | DWT | 5119 | 0.622000 |
| LNG_CARRIER | DWT >= 100000 | DWT | 9.827 | 0.000000 |
| LNG_CARRIER | 65000 <= DWT < 100000 | DWT | 14479E10 | 2.673000 |
| LNG_CARRIER | DWT < 65000 | fixed 65000 | **14779E10** | 2.673000 |
| RO_RO_CARGO_VEHICLE | GT >= 57700 | fixed 57700 | 3627 | 0.590000 |
| RO_RO_CARGO_VEHICLE | 30000 <= GT < 57700 | GT | 3627 | 0.590000 |
| RO_RO_CARGO_VEHICLE | GT < 30000 | GT | 330 | 0.329000 |
| RO_RO_CARGO | all | GT | 1967 | 0.485000 |
| RO_RO_PASSENGER | all | GT | 2023 | 0.460000 |
| RO_RO_PASSENGER_HSC | all | GT | 4196 | 0.460000 |
| CRUISE_PASSENGER | all | GT | 930 | 0.383000 |

> **[C-2 정정 철회]** 이전 Oracle 리뷰(C-2)에서 `14779E10`을 `14479E10`의 전치 오류로 보고 정정했으나, MEPC.353(78) Table 1 원문 교차 검증 결과 `14479E10`(65k≤DWT<100k 구간)과 `14779E10`(DWT<65k 구간)은 **서로 다른 구간의 서로 다른 유효한 값**이었다. 따라서 원래 값 `14779E10`으로 복원한다. (AGENTS.md §2.3 참조)

### 3.4 등급 경계 d-vector

> PRD §3.4.4 기준.

| ship_type | condition_expr | d1 | d2 | d3 | d4 |
|---|---|---|---|---|---|
| BULK_CARRIER | all | 0.8600 | 0.9400 | 1.0600 | 1.1800 |
| GAS_CARRIER | DWT >= 65000 | 0.8100 | 0.9100 | 1.1200 | 1.4400 |
| GAS_CARRIER | DWT < 65000 | 0.8500 | 0.9500 | 1.0600 | 1.2500 |
| TANKER | all | 0.8200 | 0.9300 | 1.0800 | 1.2800 |
| CONTAINER_SHIP | all | 0.8300 | 0.9400 | 1.0700 | 1.1900 |
| GENERAL_CARGO_SHIP | all | 0.8300 | 0.9400 | 1.0600 | 1.1900 |
| ... | ... | ... | ... | ... | ... |

> 전체 d-vector 테이블은 PRD §3.4.4 참조.
>
> **[#126]** `§3.3`에는 `RO_RO_PASSENGER_HSC` 행이 있으나 본 표에는 **없다.** MEPC.354(78) 원문에 해당 행이 없기 때문이며, 원문대로다. HSC의 등급 경계는 `RO_RO_PASSENGER` 행을 적용한다 — 근거와 처리 방침은 `PRD §3.4.4` 각주 참조.

---

## 4. 성능 및 인덱스 전략

### 4.1 주요 쿼리 패턴

| 쿼리 | 사용 인덱스 |
|---|---|
| 선박별 항차 목록 (최신순) | `idx_voyage_vessel` |
| 특정 상태 항차 조회 | `idx_voyage_status` |
| 규정연도별 항차 조회 | `idx_voyage_year` |
| 동일 입력 계산 결과 조회 | `idx_calc_input_hash` |
| IMO 번호 검색 | `idx_vessel_imo` |
| 기상 캐시 조회 | `idx_weather_cache` |
| 감사 로그 조회 | `idx_audit_timestamp` |
| 동일 항차 연료 중복 확인 | `idx_fuel_use_unique` |

### 4.2 파티셔닝 (향후 확장)

| 테이블 | 파티셔닝 전략 |
|---|---|
| `calculation_run` | 월별 RANGE 파티셔닝 (created_at 기준) |
| `audit_log` | 월별 RANGE 파티셔닝 (timestamp 기준) |
| `weather_snapshot` | 월별 RANGE 파티셔닝 + 오래된 데이터 자동 삭제 |

### 4.3 백업 및 보존

| 데이터 | 보존 기간 |
|---|---|
| `calculation_run` | 무기한 (재현성 보장) |
| `simulation_snapshot` | 무기한 |
| `audit_log` | 최소 5년 |
| `weather_snapshot` | 30일 (TTL 만료 후 삭제) |
| `chat_session` · `chat_message` | 90일 (만료 후 삭제, PRD §16.3 채팅 보존 정책) — 테이블 미정의 각주는 §2.16 [#287] |

---

## 5. 데이터 타입 결정 근거

### 5.1 NUMERIC vs FLOAT

> TECH_SPEC §1의 이중 정밀도 전략에 따른다.

| 필드 | 타입 | 근거 |
|---|---|---|
| `attained_cii`, `required_cii` | JSON 문자열 (result_json 내) | Layer 1 Decimal 결과. DB에 직접 컬럼으로 저장하지 않고 JSONB snapshot으로 보존 |
| `a_decimal` | NUMERIC(30,6) | `14779E10` = 147,790,000,000,000 (15자리). float64 한계 근접 |
| `cf` | NUMERIC(10,6) | CF 값은 소수점 3자리 (3.114)이지만 연산 정밀도를 위해 6자리 확보 |
| `distance_nm`, `fuel_ton` | NUMERIC(12,2) / NUMERIC(12,4) | 사용자 입력값. 표시 정밀도에 맞춤 |
| `z_factor_percent` | NUMERIC(8,4) | 13.625%와 같은 분수 값 처리 |
| `voyage_scenario.cii_value` | NUMERIC(15,8) **[M-8]** | 목록 조회·정렬용 denormalized numeric cache. canonical Layer 1 값은 반드시 `calculation_run.result_json.attained_cii`를 사용 |

### 5.2 JSONB 사용 기준

> **[X-5]** 모든 JSONB 컬럼은 애플리케이션 서비스 계층에서 INSERT 전 구조를 검증한다. DB 계층은 JSONB 타입으로 유효한 JSON임만 보장한다.

| 컬럼 | JSONB 사용 이유 | 검증 계층 |
|---|---|---|
| `result_json` | 계산 타입별로 구조가 다름. 스키마리스 저장이 적합 | Service layer (Pydantic model 검증) |
| `parameters_used` | TECH_SPEC §5.2.1 정의 구조. 해시 검증용 | Service layer + hash 재계산 |
| `model_version` | TECH_SPEC §10.1 structured JSON. 버전 비교용 | Service layer (startup validation) |
| `voyages_json` (snapshot) | 항차 배열 전체 사본. 동적 길이 | Service layer (snapshot builder) |
| `warnings_json` | 경고 코드 배열. 동적 | Service layer (warning aggregator) |
| `details_json` (audit) | action별로 상이한 구조 | Service layer (audit writer) |

---

## 6. 하위 문서 의존성

### 6.1 TEST_PLAN.md 필요 참조

| DB_SCHEMA 섹션 | TEST_PLAN 사용처 |
|---|---|
| §2 테이블 정의 | Fixture 데이터 생성 스크립트 |
| §2.5 `calculation_run` | 재현성 테스트 (result_json 비교) |
| §2.7 `simulation_snapshot` | 스냅샷 격리 테스트 |
| §2.10 `cii_reference_line` | `a_raw/a_decimal` 일치 검증 테스트 |
| §2.14 `audit_log` | 감사 로그 테스트 |
| §3 시드 데이터 | Fixture 1~3 검증 데이터 |
| §7 전역 제약 및 트리거 | 제약 위반 테스트 (CHECK, UNIQUE, FK) |
| §8 마이그레이션 전략 | Fixture DB 초기화 방식 |

---

## 7. 전역 제약 및 트리거

### 7.1 FK ON DELETE 정책 [DB-C-3]

> 모든 FK에 명시적 `ON DELETE` 동작을 지정한다.

| 부모 테이블 | 자식 테이블.컬럼 | ON DELETE | 근거 |
|---|---|---|---|
| `vessel(id)` | `voyage.vessel_id` | **RESTRICT** | 선박은 soft-delete만 허용. 물리 삭제 시 항차가 orphan됨 |
| `vessel(id)` | `voyage_scenario.vessel_id` | **CASCADE** | 시나리오는 선박 종속 데이터 |
| `vessel(id)` | `calculation_run.vessel_id` | **RESTRICT** | 계산 이력 보존 |
| `vessel(id)` | `annual_simulation_run.vessel_id` | **RESTRICT** | 시뮬레이션 이력 보존 |
| `vessel(id)` | `simulation_snapshot.vessel_id` | **RESTRICT** | 스냅샷 보존 |
| `voyage(id)` | `voyage_fuel_use.voyage_id` | **CASCADE** | 연료 기록은 항차 종속 |
| `voyage(id)` | `voyage_scenario.voyage_id` | **SET NULL** | 시나리오는 항차 삭제 후에도 선박 단위로 보존 (`vessel_id` 유지) |
| `voyage(id)` | `calculation_run.voyage_id` | **RESTRICT** [#28 정정] | 계산 이력 보존. calculation_run은 immutable(§7.3)이라 SET NULL(자식 UPDATE)이 트리거로 차단됨 → RESTRICT |
| `calculation_run(id)` | `annual_simulation_run.calculation_run_id` | **RESTRICT** | immutable 테이블 참조 |
| `simulation_snapshot(id)` | `annual_simulation_run.snapshot_id` | **RESTRICT** | immutable 테이블 참조 |
| `weather_snapshot(id)` | `voyage_scenario.weather_snapshot_id` | **SET NULL** | 기상 스냅샷 만료 시 시나리오 보존 |
| `weather_snapshot(id)` | `calculation_run.weather_snapshot_id` | **RESTRICT** [#102] | immutable 테이블 참조(§7.3). SET NULL은 자식 UPDATE라 트리거에 차단됨 → RESTRICT (§2.5 [#102] 참조) |
| `fuel_type(code)` | `vessel.default_fuel_type` | **ON UPDATE CASCADE** (코드 변경 시), ON DELETE NO ACTION (활성 연료 삭제 방지) |
| `fuel_type(code)` | `voyage_fuel_use.fuel_type` | **ON UPDATE CASCADE**, ON DELETE NO ACTION |

### 7.2 `updated_at` 자동 갱신 트리거 [M-2]

```sql
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- updated_at 컬럼을 가진 모든 테이블에 적용
CREATE TRIGGER trg_vessel_updated   BEFORE UPDATE ON vessel           FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER trg_voyage_updated   BEFORE UPDATE ON voyage           FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER trg_voyage_fuel_use_updated BEFORE UPDATE ON voyage_fuel_use  FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER trg_voyage_scenario_updated BEFORE UPDATE ON voyage_scenario  FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER trg_fuel_type_updated BEFORE UPDATE ON fuel_type       FOR EACH ROW EXECUTE FUNCTION update_timestamp();
```

**[#98] `updated_at`을 두는 기준**

| 구분 | `updated_at` | 근거 |
|---|---|---|
| 운영 데이터 — `vessel` · `voyage` · `voyage_fuel_use` · `voyage_scenario` | **둔다** | 사용자가 행을 제자리에서 수시로 고친다. 마지막 수정 시각이 곧 감사 정보다 |
| 파라미터 테이블 — `regulation_year` · `cii_reference_line` · `cii_rating_boundary` · `weather_model_parameter` | **두지 않는다** | 규제값이 개정되면 **행을 고치지 않고 새 `version` 행을 넣고 `is_active`를 전환**한다. 시점은 `created_at`·`effective_from`이 담는다 |
| 파라미터 테이블 중 `fuel_type` | **예외로 둔다** | `TECH_SPEC §5.2`의 `parameter_hash` 계약이 CF 값의 **제자리 갱신 추적**을 요구한다. 그래서 `content_hash`(§2.9 `[X-3]`)와 함께 `updated_at`을 둔다. **`content_hash`를 가진 파라미터 테이블은 이것뿐이다** |

> **파라미터 테이블에 `updated_at`이 없는 것은 누락이 아니라 정책이다.** 5종 중 `fuel_type`만 가지고 있어 「`regulation_year`에 빠졌다」로 읽히기 쉬우나, 실제 구조는 그 반대다 — **`fuel_type`이 유일한 예외**다.
>
> 이 정책이 성립하려면 **파라미터 값 개정 시 새 `version` 행 + `is_active` 전환으로 운용**해야 한다. 기존 행을 UPDATE로 덮어쓰면 개정 이력이 사라진다. `regulation_year`·`fuel_type`이 `version`·`is_active`를 가진 이유가 이것이다.
>
> ⚠️ `weather_model_parameter`(§2.12)는 `version`·`is_active`가 없어 이 운용을 적용할 수 없다. 외부 규제값이 아니라 모델 파라미터라 성격이 다르며, 필요해지면 별도로 정한다.

### 7.3 Immutable 테이블 보호 트리거 [X-2]

```sql
CREATE OR REPLACE FUNCTION prevent_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'immutable table: % cannot be modified after creation', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

-- calculation_run: UPDATE/DELETE 차단 — 단 needs_recalc 플립만 허용 (024, #283)
CREATE OR REPLACE FUNCTION calc_run_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'immutable table: calculation_run cannot be modified after creation';
    END IF;
    IF NEW.needs_recalc = TRUE AND OLD.needs_recalc = FALSE
       AND (to_jsonb(NEW) - 'needs_recalc')
           IS NOT DISTINCT FROM (to_jsonb(OLD) - 'needs_recalc')
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION
        'immutable table: calculation_run cannot be modified after creation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_calcrun_immutable
    BEFORE UPDATE OR DELETE ON calculation_run
    FOR EACH ROW EXECUTE FUNCTION calc_run_guard();

-- simulation_snapshot: UPDATE/DELETE 차단
CREATE TRIGGER trg_snapshot_immutable
    BEFORE UPDATE OR DELETE ON simulation_snapshot
    FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
```

> 애플리케이션 버그로 인한 historical data 변조를 DB 계층에서 차단한다.
>
> **[#283] `calc_run_guard` (마이그레이션 024).** calculation_run만 예외를 둔다 — PRD §8.4가 선박 DWT/GT 변경 시 재계산 필요 표시(`needs_recalc` false→true)를 요구하는데, 이는 UPDATE여야만 한다. 가드는 **플립 외 모든 변경을 여전히 거부**한다: 다른 컬럼 동시 변경, true→false 되돌림, DELETE 전부 차단. 컬럼을 열거하지 않고 `to_jsonb` 차집합으로 비교하므로 이후 컬럼 추가도 자동으로 보호된다. 공유 함수 `prevent_mutation()`은 simulation_snapshot이 계속 사용한다.

---

## 8. 마이그레이션 전략 [X-1]

### 8.1 도구 선택

| 항목 | 선택 | 근거 |
|---|---|---|
| 마이그레이션 도구 | **Alembic** (Python) | TECH_SPEC의 Python 스택과 일치. SQLAlchemy와 통합 |
| 명명 규칙 | `{revision}_{description}.py` (예: `001_initial_schema.py`) | Alembic 기본 규칙 준수 |
| rollback 정책 | 모든 마이그레이션에 `downgrade()` 구현 필수 | 프로덕션 안전성 |
| seed 데이터 | **값·로직은 `src/cii_platform/db/seed.py`가 관리. 적재는 Alembic data migration** | 아래 §8.1.1 |

#### 8.1.1 seed의 위치와 적재 경로 [#127]

**계산에 필요한 seed는 `alembic upgrade head` 경로에 들어 있다.** 배포에 별도 스크립트 실행 단계가 없다.

| 대상 | 적재 경로 | 성격 |
|---|---|---|
| `fuel_type` CF 8행 | 017 (`#83`) · `content_hash`는 031 (`#154`) | 필수 |
| `regulation_year` Z-factor 8행 · `cii_reference_line` 20행 · `cii_rating_boundary` d-vector 14행 | **032 (`#127`)** | 필수 |
| 데모용 선박·항차·정박 기록 | **`python -m cii_platform.db.demo_seed`** (`#451`) | 시연·개발 전용 |

> **데모 데이터는 2026-08-17에 마이그레이션에서 분리됐다 (`#451`).** 018·027은 리비전만 남고 무동작이다.
>
> **왜 옮겼는가.** 데모 선박으로 계산을 한 번 돌리면 `calculation_run`이 그 선박을 참조하고, `fk_calculation_run_vessel`(023 신설, `RESTRICT`)이 018의 다운그레이드 DELETE를 막았다. 018 자신은 *"그 컬럼에는 FK가 없어(003) 실제로는 막히지 않는다"* 고 적었으나 **그 전제가 023에서 깨졌다.**
>
> 다른 두 안은 각각 이것을 깬다 — 「참조 행까지 삭제」는 **마이그레이션이 사용자 계산 이력을 지우는 선례**가 되고(`§7.3` immutable 가드가 있는 보존 대상이다), 「참조 있으면 남기고 경고」는 롤백이 절반만 되는 상태를 만든다.
>
> **분리가 이 절의 원칙과도 맞는다** — 「스키마 변경과 seed 데이터 분리」이며, 데모 데이터는 스키마도 아니고 모든 환경에 필요한 값도 아니다.
>
> 제거는 `clear_demo()`가 한다. **계산 이력이 참조하는 항차·선박은 남긴다** — `calculation_run`은 DELETE까지 트리거로 차단된 보존 대상이므로 지울 수 없고, 억지로 지우는 대신 남긴 수를 돌려준다.

**값과 로직은 `src/cii_platform/db/seed.py`에 둔다 — 별도 `seed/` 디렉토리를 만들지 않는다.**

> 이 절은 원래 「별도 `seed/` 디렉토리에서 관리」로 규정했으나, 그 디렉토리는 만들어진 적이 없고 만들 이유도 없다는 것이 확인되어 실제 구조로 고쳤다(#127). 패키지 안에 있어야 **DB 없이 값 검증 테스트가 가능**하다 — 현재 5개 테스트 파일(`test_seed_data.py` · `test_capacity_rules.py` · `test_rating_boundary.py` · `test_hashing.py` · `test_dashboard_seed.py`)이 이 상수를 import해 `PRD §3.4`와 대조한다. `seed/`로 옮기면 그 검증 경로가 끊긴다.

**마이그레이션은 `src/` 상수를 import하지 않는다 🔒**

마이그레이션은 **과거 한 시점의 스냅샷**이다. 상수를 import하면 규제 개정으로 그 상수가 바뀔 때 과거 마이그레이션의 동작이 소급 변경되어, 새 환경의 `upgrade head`가 「그날의 값」이 아니라 「오늘의 값」을 넣는다. 그러면 이후 마이그레이션의 전제가 무너진다. 값은 마이그레이션 파일에 인라인으로 고정한다.

| 주체 | 담는 것 | 성격 |
|---|---|---|
| data migration (017 · 032) | 그날 넣은 값 | **불변** — 신규 환경 부트스트랩 |
| `seed_all()` (upsert) | 지금 옳다고 보는 값 | **가변** — 규제 개정 시 재적재 |

**규제 개정 시 둘이 갈라지는 것이 정상이다.** 다만 그 순간을 모르고 지나가면 안 되므로 `tests/test_seed_migration.py`가 양쪽을 매 실행 대조한다.

**data migration에 upsert를 쓰지 않는다 🔒** — Alembic은 각 마이그레이션을 한 번만 실행하는 모델이고, upsert는 덮어쓴 원래 값을 모르므로 `downgrade()`를 정의할 수 없다. 위 표의 「모든 마이그레이션에 `downgrade()` 구현 필수」와 충돌한다. 재적재가 필요하면 `seed_all()`을 쓴다.

**downgrade는 자기가 넣은 키만 지운다 🔒** — 전체 DELETE는 운영 중 추가된 행까지 지운다.

### 8.2 마이그레이션 워크플로우

```
1. 스키마 변경 필요 발생
2. alembic revision --autogenerate -m "description"
3. 생성된 마이그레이션 파일 검토 (autogenerate 누락 확인)
4. 로컬 DB에서 upgrade → 테스트
5. downgrade → 재테스트 (롤백 검증)
6. PR에 마이그레이션 파일 포함
7. CI에서 자동 upgrade/downgrade 테스트 수행
```

### 8.3 Seed 데이터 버전 관리

| 데이터 | 버전 관리 방식 | 갱신 시기 |
|---|---|---|
| `regulation_year` Z-factor | `version` 컬럼 + Alembic data migration (032) | IMO 새 결의안 채택 시 |
| `fuel_type` CF 값 | `version` + `content_hash` 컬럼 | MEPC 새 지침 발행 시 |
| `cii_reference_line` | `source_ref` 컬럼으로 추적. 적재는 data migration (032) | MEPC 새 지침 발행 시 |
| `cii_rating_boundary` | `source_ref` 컬럼으로 추적. 적재는 data migration (032) | MEPC 새 지침 발행 시 |

> Seed 데이터 변경 시 기존 `calculation_run`의 `parameter_hash`와 새 파라미터의 hash가 달라지므로, 과거 계산 결과는 재현성이 보장된다 (다른 hash = 다른 결과 세트).

#### 8.3.1 `fuel_type.content_hash` 산출 규칙 [#154]

**해싱 단위는 행이다.** 8행 집합이 아니라 각 행이 자기 내용의 해시를 갖는다.

| 항목 | 규칙 |
|---|---|
| 단위 | **행 1개당 해시 1개** |
| 대상 필드 | **`{code, cf}`** — `TECH_SPEC §5.2.1`의 `parameters_used.fuel_types[]` 원소 스키마와 동일 |
| 직렬화 | `TECH_SPEC §5.1.2`의 `canonical_json` — `sort_keys=True` · `separators=(",",":")` · Decimal은 문자열 · float 금지 |
| Decimal 표기 | `normalize()` 후 고정소수점 (`[ORACLE-C-2]`). `3.000000` → `"3"` |
| 해시 | `"sha256:" + SHA-256(canonical.encode("utf-8")).hexdigest()` — 총 71자로 컬럼 폭과 일치 |

```
{"cf":"3.114","code":"HFO"}
  → sha256:fa0bb45993735ee22cde1b56c3af2e08da30b0237a025d33fd9e4041e564d597
```

**행 단위인 이유** — ⑴ 컬럼이 행마다 있으므로 집합 해시면 8행이 전부 같은 값을 갖는다(같은 값의 8중 중복 저장). ⑵ `§2.9`가 `effective_from`을 「OTHER 연료용」으로 정의해 행이 추가될 수 있는데, 집합 해시라면 그때 기존 행을 전부 다시 써야 한다. ⑶ 세트 전체의 추적은 `calculation_run.parameter_hash`가 이미 한다(`TECH_SPEC §5.2`) — 여기까지 집합이면 같은 일을 두 곳에서 한다. ⑷ 행 단위여야 **어느 행이 바뀌었는지** 짚을 수 있으며, `version` 갱신 없이 `cf`만 UPDATE되는 드리프트가 이 컬럼이 잡을 대상이다.

**대상 필드가 `{code, cf}`인 이유** — `TECH_SPEC §5.2.1`이 이미 그렇게 규정한다. 여기서 다른 필드 집합을 쓰면 **같은 엔티티에 canonical 규약이 두 벌** 생긴다. 같은 집합을 쓰면 과거 `calculation_run`이 사용한 CF가 현재 행과 같은지를 해시 대조로 확인할 수 있다.

제외 필드와 사유 — `display_name`·`unit`(표시·고정 기본값이지 규제값이 아님) · `id`·`created_at`·`updated_at`(운영 메타) · `is_active`(운영 상태) · `version`(내용이 아니라 내용 **세트의 라벨**. 위 표가 둘을 나란히 두므로 서로를 포함하면 순환이다).

> **`version`과의 관계** — CF 값이 **바뀔 때** 둘을 함께 갱신한다. 값 변경 없이 비어 있던 추적 컬럼만 채우는 경우(마이그레이션 031)에는 `version`을 올리지 않는다.

> **마이그레이션은 이 값을 리터럴로 담는다.** 마이그레이션이 `src/`의 해시 함수를 import하면 규약이 바뀔 때 과거 마이그레이션의 동작이 소급 변경된다(PR #147 구현 결정 2). 대신 테스트가 `src/`의 살아 있는 규약으로 재계산해 DB 값과 대조하므로, 규약이 바뀌면 테스트가 깨져 드리프트가 드러난다.

---

## 9. 멀티테넌시 고려사항 [X-4]

### 9.1 현재 설계: Single-Tenant-per-Instance

MVP 단계에서는 **단일 회사 per 인스턴스** 모델을 채택한다. 모든 데이터는 하나의 회사에 속하며, `tenant_id` / `company_id` 컬럼이 없다.

### 9.2 향후 다중 회사 지원 시 마이그레이션 경로

다중 회사 지원이 필요한 경우:

1. `company` 테이블 추가 (`id UUID PK`, `name VARCHAR`)
2. `vessel`, `audit_log`에 `company_id UUID NOT NULL, FK → company(id)` 추가
3. `voyage`, `calculation_run`, `annual_simulation_run`, `voyage_scenario`에 `company_id` 추가 (반정규화)
4. PostgreSQL Row-Level Security (RLS) 정책 설정:
   ```sql
   ALTER TABLE vessel ENABLE ROW LEVEL SECURITY;
   CREATE POLICY vessel_tenant_isolation ON vessel
       USING (company_id = current_setting('app.current_company_id')::uuid);
   ```
5. 애플리케이션에서 요청 컨텍스트에 따라 `SET app.current_company_id = ...` 실행

> 이 마이그레이션은 schema 변경뿐 아니라 애플리케이션 로직 전면 수정을 수반하므로, MVP 단계에서는 single-tenant로 시작하고 필요 시 전용 마이그레이션을 수행한다.

---

## 10. Oracle 리뷰 반영

> DB_SCHEMA.md v1.0에 대한 Oracle 리뷰 결과. 총 25건 (3 Critical + 8 Significant + 8 Minor + 6 Missing).

### 10.1 Critical (3건)

| ID | 제목 | 조치 | 반영 위치 |
|---|---|---|---|
| C-1 | `regulation_year` 컬럼 누락 (DDL 실패) | 컬럼 추가 + CHECK 제약 | §2.2 voyage |
| C-2 | ~~`14779E10` → `14479E10` 오타 정정~~ → **철회**: MEPC.353(78) 원문 확인 결과 14779E10은 DWT<65k 구간의 올바른 값 (AGENTS.md §2.3) | seed 데이터 복원 | §3.3 |
| C-3 | 모든 FK에 ON DELETE 동작 미지정 | 전역 FK 정책 수립 + 각 FK에 명시 | §7.1 + §2 전체 |

### 10.2 Significant (8건)

| ID | 제목 | 조치 | 반영 위치 |
|---|---|---|---|
| S-1 | fuel_type 참조 FK 누락 | FK 제약 추가 (vessel + voyage_fuel_use) | §2.1, §2.3 |
| S-2 | voyage_fuel_use(voyage_id, fuel_type) UNIQUE 누락 | UNIQUE 인덱스 추가 | §2.3 |
| S-3 | 도착항 lat/lon CHECK 누락 | CHECK 제약 추가 | §2.2 |
| S-4 | voyage_scenario enum CHECK 누락 | scenario_type, rating, risk_level CHECK 추가 | §2.4 |
| S-5 | weather_model_parameter UNIQUE 누락 | (model_version, key) UNIQUE 인덱스 추가 | §2.12 |
| S-6 | ER 다이어그램 카디널리티 오류 | SIMULATION_SNAPSHOT ||--o| ANNUAL_SIMULATION_RUN으로 수정 | §1 |
| S-7 | hash 형식 CHECK 제약 누락 | sha256 형식 regex CHECK 추가 | §2.5, §2.7 |
| S-8 | voyage_scenario.vessel_id 누락 | vessel_id NOT NULL 컬럼 추가 | §2.4 |

### 10.3 Minor (8건)

| ID | 제목 | 조치 | 반영 위치 |
|---|---|---|---|
| M-1 | voyage_scenario is_deleted 누락 | is_deleted 컬럼 추가 | §2.4 |
| M-2 | updated_at 자동 갱신 트리거 미정의 | 공유 trigger 함수 + 각 테이블 적용 | §7.2 |
| M-3 | d-vector 순서 제약 누락 | d1 < d2 < d3 < d4 CHECK 추가 | §2.11 |
| M-4 | annual_simulation_run.target_rating CHECK 누락 | A~D만 허용 CHECK 추가 | §2.6 |
| M-5 | simulation_runs 양수 CHECK 누락 | > 0 CHECK 추가 | §2.6 |
| M-6 | actual_distance/speed 양수 CHECK 누락 | CHECK 추가 | §2.2 |
| M-7 | capacity_rule CHECK regex 강화 | `^fixed \d+$` 패턴으로 변경 | §2.10 |
| M-8 | NUMERIC(15,8) 정밀도 문서화 | 의도적 설계로 문서화 | §2.4, §5.1 |

### 10.4 Missing (6건)

| ID | 제목 | 조치 | 반영 위치 |
|---|---|---|---|
| X-1 | 마이그레이션 전략 부재 | §8 "마이그레이션 전략" 섹션 추가 | §8 |
| X-2 | immutable 테이블 보호 부재 | prevent_mutation 트리거 추가 | §7.3 |
| X-3 | fuel_type version/content_hash 부재 | 컬럼 추가 | §2.9 |
| X-4 | 멀티테넌시 설계 부재 | §9 "멀티테넌시 고려사항" 섹션 추가 | §9 |
| X-5 | JSONB 검증 전략 미문서화 | 검증 계층 표 추가 | §5.2 |
| X-6 | 타임존 정책 미문서화 | 설계 원칙에 UTC 정책 추가 | §0.1 |

### 10.5 요약

| 심각도 | 건수 | 상태 |
|---|---|---|
| Critical | 3 | ✅ 전체 반영 |
| Significant | 8 | ✅ 전체 반영 |
| Minor | 8 | ✅ 전체 반영 |
| Missing | 6 | ✅ 전체 반영 |
| **합계** | **25** | **✅ 전체 반영 완료** |

---

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준). 버전 번호 매핑은 커밋 메시지·헤더 기준의 추정을 포함한다.
>
> **2026-07-23까지가 사후 복원분이다.** 이후 항목은 변경 시점에 직접 기록하며, squash merge로 브랜치 커밋 해시가 재작성되므로 커밋 열에는 **PR 번호**를 적는다.

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-07-03 | `9f8a7eb` | 최초 작성 / 외부 리뷰 반영 (capacity 규칙 분리 등) |
| 2026-07-04 | `0f59999` | 외부 리뷰 P0/P1/P2 전체 반영 + AGENTS.md 추가 |
| 2026-07-04 | `af3b752` | Oracle 리뷰 4건 문서 정합성 수정 |
| 2026-07-04 | `ec1bf23` | Oracle 3차 리뷰 반영 (F-006~F-008) → v1.2 |
| 2026-07-13 | `ccb838e` | calculation_run·simulation_snapshot 반영, voyage_id FK를 SET NULL→RESTRICT로 정정 (#28) |
| 2026-07-14 | `0173105` | annotation 라벨 번호 정규화 (5개 정본 일괄) |
| 2026-07-16 | `e82d9da` | §7.2 트리거명을 마이그레이션 코드와 일치하도록 정정 (#78) |
| 2026-07-16 | `c302d9e` | calculation_type enum + voyage_scenario 양수 CHECK 추가 (#84) |
| 2026-07-21 | `be0dc23` | 변경이력 표 추가 및 최종 수정일 갱신 |
| 2026-07-23 | `3a38d0c` | calculation_run.weather_snapshot_id 컬럼 스펙 + FK 정책 추가, 헤더 v1.3 (#102) |
| 2026-07-29 | `#140` | §3.2 CF 8행 source_ref를 값 인쇄처(MEPC.364(79))로 정정 + 근거 각주 (#87) |
| 2026-07-29 | `#142` | §3.2 각주에 원문 대조 확인자(sky01170851) 명시 + 최종 수정일 정정 |
| 2026-07-29 | `#128` | §2.7에 calculation_run.weather_snapshot_id 자식 인덱스 추가 (#115) |
| 2026-07-29 | `#145` | §3.1에 z-factor 출처 확인 각주 + §3.4에 HSC 부재 각주 추가 (#126) |
| 2026-08-06 | `#188` | §2.5 `result_json` 예시를 계산 타입별 블록으로 분리하고 JSON 비표준 `//` 주석을 표로 이관 — 세 블록 모두 유효 JSON (#111) |
| 2026-08-06 | `#189` | §3.3에 reference line 20행 전수 대조 결과 각주 추가 — 대조 일자·로케이터·특기 사항. 절차와 재현 명령은 `db/seed.py` 주석에 분리 (#149) |
| 2026-08-06 | `#189` | §2.8 · §2.9 · §2.10 · §2.11 · §2.12의 `source_ref` 설명을 「출처」에서 「값이 인쇄된 문서」로 보강하고 §3.2 각주와 연결 (#155) |
| 2026-08-06 | `#98` | §7.2에 `updated_at`을 두는 기준 신설(운영 데이터 / 파라미터 테이블 / `fuel_type` 예외) · §2.8에 생략 근거 참조 추가 (#98) |
| 2026-08-07 | `#196` | 헤더 「상위 문서」 버전 참조 갱신 — `PRD` v3.2 · `TECH_SPEC` v1.3→v1.4(낡은 참조 정정) (#163) |
| 2026-08-14 | `#330` | v1.4: §2.8·§2.9에 파라미터 CHECK 제약(`chk_z_factor_nonneg`·`chk_cf_positive`), §2.4·§2.7에 FK 자식 인덱스(`idx_scenario_vessel`·`idx_scenario_voyage`·`idx_snapshot_vessel`) 신설 — 마이그레이션 023 (#96 #97) |
| 2026-08-14 | `#332` | v1.5: §2.5에 `needs_recalc` 컬럼·§7.3를 `calc_run_guard`(플립만 허용)로 교체 — 마이그레이션 024. PRD §8.4 DWT/GT 변경 시 재계산 필요 표시 (#283) |
| 2026-08-14 | `#333` | §2.16 말미에 `chat_session`·`chat_message` 미정의 각주(`user_id` → `app_user.id` 귀속 확정), §4.3에 채팅 90일 보존 행 추가 (#287) |
| 2026-08-14 | `#335` | §2.14 `action` 열거에 인증 이벤트 3종(LOGIN_SUCCESS·LOGIN_FAILURE·LOGOUT) 추가 + 자격 증명 미기록 규칙 각주 (#277) |
| 2026-08-15 | `#374` | v1.6: §2.17 `not_underway_period`·§2.18 `not_underway_fuel_use` 신설(마이그레이션 025) — ER 다이어그램 3줄 추가, 헤더 상위 문서 `PRD` v4.0 갱신 (#345) |
| 2026-08-15 | `#375` | v1.7: §2.1에 운항 상태 2축·위치 5컬럼 반영(마이그레이션 026) — `chk_vessel_state_pair` 정합 규칙(`SAILING`↔`UNDER_WAY`·6값↔`NOT_UNDER_WAY`, IS NOT NULL 가드)·위경도 범위·위치-시각 페어 (#346) |
| 2026-08-15 | `#377` | v1.8: §2.17에 `distance_nm` 추가(마이그레이션 028) — `MEPC.412(84)` §4.2가 `Dt`를 「both under way and not under way」로 정의해 not under way 이동 거리가 분모에 들어간다. `M`·`Dt` 원문 대조 완료 표기 (#353 · #358) |
| 2026-08-15 | `#381` | v1.9: §2.18에 `idx_not_underway_fuel_use_unique`(`period_id`, `consumer_type`, `fuel_type`) UNIQUE 신설 — §2.3 [S-2]와 같은 CO₂ 이중 산정 차단. 선행열이 같아 중복인 `idx_not_underway_fuel_use_period` 제거. §2.17에 `idx_not_underway_period_vessel_started`(#368 구간 겹침 조회)·`idx_not_underway_period_voyage`(SET NULL 확인 full scan 방지) 신설 — 마이그레이션 029 (#376) |
| 2026-08-16 | `#413` | **v1.13 — 자체 ID/PW 인증 전환.** §2.15 `app_user` 재정의 — `google_sub` 삭제, `password_hash`·`email_verified_at` 추가, **`email`에 UNIQUE 부여**(종전 「unique를 걸지 않는 것은 의도」 각주는 구글 위임 전제가 사라져 정정) · **§2.15.1 `user_token` 테이블 계약 신설**(#408 구현 대상, 원문 대신 해시 저장) (#413) |
| 2026-08-15 | `#382` | v1.10: §2.18에 `cf_used` NUMERIC(10,6) NOT NULL 추가(마이그레이션 030) — `PRD` §8.4의 CF snapshot 보존이 `voyage_fuel_use`에만 적용되고 not under way 연료는 `fuel_type.cf` 현재값을 쓰고 있었다. 집계를 `(fuel_type, cf_used)`로 묶어 개정 전후 행이 각자의 CF로 곱해지게 했다 (#378) |
| 2026-08-15 | `#389` | v1.11: §8.3.1 `fuel_type.content_hash` 산출 규칙 신설 — **행 단위** · 대상 필드 `{code, cf}`(`TECH_SPEC` §5.2.1 `parameters_used.fuel_types[]` 원소 스키마 재사용) · `canonical_json` + `sha256:` 접두사(총 71자, 컬럼 폭 일치). 017이 보류한 값을 마이그레이션 031이 리터럴로 적재하고, 테스트가 `src/` 규약으로 재계산해 대조한다 (#154) |
| 2026-08-15 | `#390` | v1.12: §8.1.1 「seed의 위치와 적재 경로」 신설 — 모든 seed를 `alembic upgrade head` 경로로 일원화(마이그레이션 032, 규제 파라미터 42행). **§8.1의 「별도 `seed/` 디렉토리」 규정을 실제 구조(`src/cii_platform/db/seed.py`)로 정정** — 패키지 안이라야 DB 없이 값 검증이 가능하고 5개 테스트가 그 상수를 쓴다. 「마이그레이션은 `src/` 상수를 import하지 않는다」·「data migration에 upsert 금지」·「downgrade는 넣은 키만 삭제」를 🔒로 명문화(017이 세우고 031·032가 따른 원칙) (#127) |
| 2026-08-15 | `#403` | 변경 이력 표 정리 — 2026-08-15 행 7건을 버전 오름차순으로 재배열(v1.10이 v1.9보다 앞, v1.6·v1.7이 맨 끝이던 상태)하고 **PR 번호 공란 2건을 채움**(v1.9 → #381 · v1.10 → #382). AGENTS §7이 squash merge 환경에서 커밋 열에 PR 번호를 적도록 규정한다. 문서 내용 변경 없음 (#401) |
| 2026-08-17 | PR #436 | **v1.14 — `§2.19 simulation_parameter` 신설 (`#434`).** `PRD §12.4.1`이 「코드 하드코딩하지 않는다」며 이름을 부르는데 **정의도 실체도 없던** 테이블이다. `bound_type`(`FACTOR`·`DELTA`)을 둔 이유는 거리·연료가 계획값의 **배수**인 반면 속도는 **덧셈**이라 한 컬럼 집합으로 둘을 담으려면 해석 방식을 행이 스스로 말해야 하기 때문이다. 재현성은 `TECH_SPEC §5.2.1.1`이 `parameter_hash`로 고정한다 |
| 2026-08-17 | PR #459 | **v1.15 — §8.1.1 데모 seed 분리 (`#451`).** 데모용 선박·항차를 마이그레이션 018·027에서 `cii_platform.db.demo_seed`로 옮겼다. 데모 선박으로 계산을 한 번 돌리면 `fk_calculation_run_vessel`(023, RESTRICT)이 018의 다운그레이드를 막아 **롤백 전체가 실패**했고, 018은 «그 컬럼에는 FK가 없어 막히지 않는다»는 **023에서 깨진 전제**를 적고 있었다. 대안 둘을 기각한 근거(마이그레이션이 계산 이력을 지우는 선례 · 절반만 되는 롤백)와 `clear_demo()`가 계산 이력이 참조하는 행을 남기는 이유를 함께 명시 (#451) |
