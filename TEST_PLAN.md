# TEST_PLAN — CII 예측 및 운항 의사결정 보조 플랫폼

| 항목 | 내용 |
|---|---|
| 문서명 | TEST_PLAN.md |
| 버전 | v1.0 |
| 상태 | Draft |
| 최종 수정일 | 2026-07-03 |
| 상위 문서 | `PRD.md` v3.1, `TECH_SPEC.md` v1.1, `API_SPEC.md` v1.1, `DB_SCHEMA.md` v1.1 |
| 테스트 프레임워크 | pytest (Python), httpx (API 통합 테스트) |

---

## 0. 범위 및 목적

본 문서는 PRD §18 테스트 계획 요약, TECH_SPEC §13.2 성능 검증, DB_SCHEMA 제약 조건, API_SPEC 검증 규칙을 기반으로 상세 테스트 케이스를 정의한다.

### 0.1 테스트 원칙

| 원칙 | 설명 |
|---|---|
| 재현성 우선 | 동일 입력·동일 파라미터·동일 seed는 동일 결과. Layer 1은 bit-exact, Layer 2는 4자리 유효숫자 |
| Fixture 기반 | 모든 계산 테스트는 JSON fixture 파일로 입력·기대값·허용 오차를 정의 |
| 경계값 필수 | 등급 경계, 수치 한계, 상태 전이 경계를 반드시 테스트 |
| Disclaimer 검증 | 모든 결과 화면/API 응답에 면책 문구가 포함되어 있는지 확인 |
| 이중 capacity 검증 | transport_capacity(실제 DWT/GT)와 reference_capacity(G2 rule) 분리 적용 확인 |

### 0.2 기준 문서 참조

| 문서 | 참조 내용 |
|---|---|
| PRD §13 | 계산 검증 Fixture 1~3 |
| PRD §18 | 테스트 계획 요약 (TC-CALC, TC-F, TC-ERR, TC-A11Y) |
| PRD §10.7, §11.9, §12.9 | 기능별 수용 기준 (AC-F1, AC-F2, AC-F3) |
| TECH_SPEC §1.2.3 | Fixture 1 검증 수식 |
| TECH_SPEC §2.5 | RNG canonical vector 검증 |
| TECH_SPEC §13.2 | 성능 벤치마크 기준 |
| API_SPEC §11 | 검증 규칙 요약 (VAL-001~010) |
| API_SPEC §1.7 | 수치 직렬화 정책 |
| DB_SCHEMA §7 | 전역 제약 및 트리거 |

---

## 1. 테스트 Fixture 정의

### 1.1 디렉토리 구조

```
tests/
  fixtures/
    cii/
      bulk_50000_hfo_2026.json          # Fixture 1
      rating_boundaries_bulk_2026.json  # Fixture 2
      tanker_80000_hfo_2025.json        # 추가 선종
      container_50000_hfo_2026.json     # 추가 선종
    capacity/
      bulk_300k_capacity_separation.json  # P0-1 이중 capacity
      lng_50k_capacity_separation.json    # P0-1 LNG 위험 사례
    simulation/
      annual_seed_12345_input.json
      annual_seed_12345_expected.json
    api/
      voyage_estimate_response.json
      scenario_compare_response.json
      voyage_create_invalid_policy.json
    weather/
      open_meteo_success.json
      api_fail_cache_6h.json
      api_fail_no_cache.json
  unit/
    test_cii_engine.py
    test_rating_boundary.py
    test_capacity_rules.py
    test_rng_reproducibility.py
    test_hashing.py
    test_weather_factor.py
    test_imo_notation.py
  integration/
    test_voyage_state_transition.py
    test_scenario_adopt.py
    test_annual_simulation_snapshot.py
    test_parameter_import.py
    test_csv_security.py
  api/
    test_voyage_cii_api.py
    test_scenario_compare_api.py
    test_annual_simulation_api.py
    test_calculation_query_api.py
    test_error_format.py
  db/
    test_constraints.py
    test_immutable_tables.py
    test_triggers.py
  performance/
    test_benchmarks.py
```

### 1.2 Fixture 1 — Bulk carrier, 2026, HFO

**파일**: `tests/fixtures/cii/bulk_50000_hfo_2026.json`

```json
{
  "description": "PRD §13.1 Fixture 1 — Bulk carrier 50,000 DWT, 2026, HFO",
  "input": {
    "ship_type": "BULK_CARRIER",
    "deadweight": 50000,
    "gross_tonnage": 30000,
    "regulation_year": 2026,
    "distance_nm": 1000,
    "speed_kn": 12.0,
    "fuel_uses": [
      { "fuel_type": "HFO", "fuel_ton": 80.0, "cf": 3.114 }
    ],
    "weather_model": "NONE"
  },
  "expected": {
    "transport_capacity": "50000",
    "reference_capacity": "50000",
    "reference_capacity_rule": "DWT",
    "co2_emission_g": "249120000",
    "co2_emission_ton": "249.12",
    "attained_cii": "4.982400",
    "cii_ref": "5.668613856",
    "required_cii": "5.045066331",
    "superior_boundary": "4.338757045",
    "lower_boundary": "4.742362352",
    "upper_boundary": "5.347770311",
    "inferior_boundary": "5.953178271",
    "estimated_rating": "C",
    "ratio_to_required": "0.987585",
    "risk_level": "MEDIUM"
  },
  "tolerance": {
    "layer1": "0",          // bit-exact (Decimal 비교)
    "layer1_display": "6"    // 표시값 6자리 일치
  }
}
```

### 1.3 Fixture 2 — 등급 경계값

**파일**: `tests/fixtures/cii/rating_boundaries_bulk_2026.json`

```json
{
  "description": "PRD §13.2 Fixture 2 — 등급 경계값 테스트 (BULK_CARRIER, 2026)",
  "base_required_cii": "5.045066331",
  "boundaries": {
    "superior":  "4.338757045",
    "lower":     "4.742362352",
    "upper":     "5.347770311",
    "inferior":  "5.953178271"
  },
  "cases": [
    { "attained_cii": "4.338757045", "expected_rating": "A", "note": "경계값 = 더 우수한 등급" },
    { "attained_cii": "4.742362352", "expected_rating": "B", "note": "경계값 = 더 우수한 등급" },
    { "attained_cii": "5.347770311", "expected_rating": "C", "note": "경계값 = 더 우수한 등급" },
    { "attained_cii": "5.953178271", "expected_rating": "D", "note": "경계값 = 더 우수한 등급" },
    { "attained_cii": "5.953178272", "expected_rating": "E", "note": "경계값 + 0.000001 = E" }
  ]
}
```

> **경계값 판정 규칙 (PRD §9.4.1)**: attained_CII가 경계값과 정확히 같으면 더 우수한 등급으로 판정한다. 예: `attained_CII == lower_boundary` → B (C가 아님).

### 1.4 Fixture 3 — Monte Carlo 재현성

**파일**: `tests/fixtures/simulation/annual_seed_12345_input.json`

```json
{
  "description": "PRD §13.3 Fixture 3 — Monte Carlo seed 재현성",
  "input": {
    "vessel_id": "test-vessel-uuid",
    "regulation_year": 2026,
    "target_rating": "B",
    "simulation_runs": 5000,
    "random_seed": 12345,
    "distribution_profile": "DEFAULT",
    "voyages": [
      {
        "status": "CONFIRMED",
        "distance_nm": 11000,
        "fuel_uses": [{ "fuel_type": "HFO", "fuel_ton": 800.0 }]
      }
    ]
  }
}
```

**파일**: `tests/fixtures/simulation/annual_seed_12345_expected.json`

```json
{
  "description": "Fixture 3 기대 결과 — 동일 seed 재실행 시 결과 동일",
  "comparison_rule": {
    "deterministic": "bit_exact",
    "monte_carlo": "rating_probabilities_4_sig_digits",
    "assert": "첫 번째 실행 결과 JSON == 두 번째 실행 결과 JSON"
  }
}
```

### 1.5 Fixture 4 — 이중 Capacity 분리 [P0-1]

**파일**: `tests/fixtures/capacity/bulk_300k_capacity_separation.json`

```json
{
  "description": "P0-1: 300,000 DWT 벌크캐리어 — transport vs reference capacity 분리",
  "input": {
    "ship_type": "BULK_CARRIER",
    "deadweight": 300000,
    "regulation_year": 2026,
    "distance_nm": 10000,
    "fuel_uses": [{ "fuel_type": "HFO", "fuel_ton": 1000.0 }]
  },
  "expected": {
    "transport_capacity": "300000",
    "transport_capacity_basis": "DWT",
    "reference_capacity": "279000",
    "reference_capacity_rule": "fixed 279000",
    "note": "W = 300,000 × 10,000 (실제 DWT). CII_ref = 4745 × 279,000^(-0.622) (fixed)"
  }
}
```

**파일**: `tests/fixtures/capacity/lng_50k_capacity_separation.json`

```json
{
  "description": "P0-1: 50,000 DWT LNG 캐리어 — 위험 사례 (과소 산정 방지)",
  "input": {
    "ship_type": "LNG_CARRIER",
    "deadweight": 50000,
    "regulation_year": 2026,
    "distance_nm": 10000,
    "fuel_uses": [{ "fuel_type": "LNG", "fuel_ton": 500.0 }]
  },
  "expected": {
    "transport_capacity": "50000",
    "transport_capacity_basis": "DWT",
    "reference_capacity": "65000",
    "reference_capacity_rule": "fixed 65000",
    "note": "W = 50,000 × 10,000 (실제 DWT). CII_ref = 14479E10 × 65,000^(-2.673) (fixed). 잘못 fixed를 W에 적용하면 -23% 과소 산정"
  }
}
```

---

## 2. 단위 테스트 (Unit Tests)

### 2.1 CII 계산 엔진 (`test_cii_engine.py`)

| TC ID | 테스트 | 입력 | 기대 결과 | 허용 오차 |
|---|---|---|---|---|
| UT-CII-001 | Fixture 1 전체 계산 | Fixture 1 JSON | 모든 기대값 일치 | bit-exact (Decimal) |
| UT-CII-002 | CO₂ 배출량 단일 연료 | HFO 80ton, CF=3.114 | 249,120,000 gCO₂ | bit-exact |
| UT-CII-003 | CO₂ 배출량 다중 연료 | HFO 60ton + LNG 20ton | 각 연료별 CO₂ 합산 | bit-exact |
| UT-CII-004 | Transport work 계산 | DWT=50,000, dist=1,000 | W=50,000,000 | bit-exact |
| UT-CII-005 | Required CII 연도별 차이 | 2026 vs 2027 | 2027 required_CII가 더 낮음 (Z-factor 증가) | bit-exact |
| UT-CII-006 | 동일 입력 반복 | Fixture 1 × 3회 | 모든 결과 bit-exact 일치 | 0 |
| UT-CII-007 | Layer 1 NaN/Infinity 가드 | fuel_ton=0 | `ValueError` 발생 | — |
| UT-CII-008 | plan_value = 0 가드 | 0인 삼각분포 입력 | `ValueError` 발생 (TECH_SPEC S-1) | — |

### 2.2 등급 경계값 (`test_rating_boundary.py`)

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| UT-RATING-001 | superior 경계값 | attained = superior_boundary | A |
| UT-RATING-002 | lower 경계값 | attained = lower_boundary | B |
| UT-RATING-003 | upper 경계값 | attained = upper_boundary | C |
| UT-RATING-004 | inferior 경계값 | attained = inferior_boundary | D |
| UT-RATING-005 | inferior + epsilon | attained = inferior + 0.000001 | E |
| UT-RATING-006 | A 등급 (매우 양호) | attained = 0.1 × required | A |
| UT-RATING-007 | E 등급 (매우 불량) | attained = 2.0 × required | E |

### 2.3 Capacity 규칙 (`test_capacity_rules.py`) [P0-1]

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| UT-CAP-001 | 벌크캐리어 ≥ 279k: transport = 실제 DWT | DWT=300,000 | `transport_capacity = 300000` |
| UT-CAP-002 | 벌크캐리어 ≥ 279k: reference = fixed 279k | DWT=300,000 | `reference_capacity = 279000` |
| UT-CAP-003 | 벌크캐리어 < 279k: 동일 capacity | DWT=50,000 | `transport = reference = 50000` |
| UT-CAP-004 | LNG < 65k: transport = 실제 DWT | DWT=50,000 | `transport_capacity = 50000` |
| UT-CAP-005 | LNG < 65k: reference = fixed 65k | DWT=50,000 | `reference_capacity = 65000` |
| UT-CAP-006 | LNG ≥ 100k: c=0 (고정 CII_ref) | DWT=120,000 | `CII_ref = 9.827` (capacity 무관) |
| UT-CAP-007 | Ro-Ro Vehicle ≥ 57.7k: reference = fixed | GT=70,000 | `reference_capacity = 57700` |
| UT-CAP-008 | 오차 검증: 벌크 300k에서 W 오차 | DWT=300,000 | `W_error = 0%` (fixed 미적용) |

```python
# test_capacity_rules.py — 핵심 테스트
def test_bulk_over_279k_uses_actual_dwt_for_transport():
    """P0-1: attained CII의 W는 실제 DWT를 사용해야 함"""
    vessel = Vessel(ship_type="BULK_CARRIER", deadweight=300000)
    transport_cap = resolve_transport_capacity(vessel)
    assert transport_cap == Decimal("300000"), \
        "transport_capacity must be actual DWT (300000), not fixed 279000"

def test_bulk_over_279k_uses_279000_for_reference():
    """P0-1: reference CII는 G2 fixed capacity를 사용"""
    vessel = Vessel(ship_type="BULK_CARRIER", deadweight=300000)
    ref_line = get_reference_line("BULK_CARRIER", "DWT >= 279000")
    reference_cap = resolve_reference_capacity(vessel, ref_line)
    assert reference_cap == Decimal("279000"), \
        "reference_capacity must use G2 fixed value (279000)"
```

### 2.4 RNG 재현성 (`test_rng_reproducibility.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| UT-RNG-001 | Canonical vector 검증 | PCG64DXSM seed=12345의 처음 5개 값이 EXPECTED_UNIFORM_5와 일치 (1e-15 오차 내) |
| UT-RNG-002 | 동일 seed 재현성 | seed=12345로 5000회 생성 → 두 번째 실행과 bit-exact 일치 |
| UT-RNG-003 | Seed 변경 시 결과 상이 | seed=12345 vs seed=99999 → rating_probabilities가 다름 |
| UT-RNG-004 | default_rng 사용 금지 | `np.random.default_rng()` 사용 시 테스트 실패 (PCG64 vs PCG64DXSM) |

### 2.5 해싱 (`test_hashing.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| UT-HASH-001 | Parameter hash 결정성 | 동일 파라미터 → 동일 hash |
| UT-HASH-002 | Decimal trailing zeros 정규화 | `"3.114"` == `"3.114000"` after normalize() |
| UT-HASH-003 | Canonical JSON 키 정렬 | 키 순서가 달라도 동일 hash |
| UT-HASH-004 | float 금지 | `canonical_json({"x": 1.0})` → `TypeError` |
| UT-HASH-005 | Input hash 필드 명시성 | weather_factor가 None이면 "1.0"으로 간주 후 hash |

### 2.6 기상 보정 (`test_weather_factor.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| UT-WX-001 | NONE 모델 | weather_factor = 1.0 |
| UT-WX-002 | SIMPLE_RULE: BN=0 | weather_factor ≈ 1.0 |
| UT-WX-003 | SIMPLE_RULE: BN=5 | weather_factor > 1.0 |
| UT-WX-004 | TOWNSIN-Kwon: 실험 모델 배지 | 결과에 `EXPERIMENTAL_MODEL` warning 포함 |
| UT-WX-005 | 음수 파고 입력 가드 | wave_height < 0 → `max(0.0, ...)` clamping |

### 2.7 IMO 과학 표기법 (`test_imo_notation.py`)

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| UT-IMO-001 | `14405E7` 파싱 | `"14405E7"` | `Decimal("144050000000")` |
| UT-IMO-002 | `14479E10` 파싱 | `"14479E10"` | `Decimal("144790000000000")` |
| UT-IMO-003 | a_raw == a_decimal 검증 | seed 데이터 전체 | 모든 행에서 `parse(a_raw) == a_decimal` |
| UT-IMO-004 | NaN/Infinity 거부 | `"NaN"` | `ValueError` |
| UT-IMO-005 | 음수 거부 | `"-100"` | `ValueError` |

---

## 3. 통합 테스트 (Integration Tests)

### 3.1 항차 상태 전이 (`test_voyage_state_transition.py`)

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-STATE-001 | DRAFT → PLANNED 전환 | transition API | status = PLANNED, annual_inclusion_policy 설정 가능 |
| IT-STATE-002 | DRAFT + INCLUDE_AS_PLAN 거부 | DRAFT에서 policy 설정 시 | 422 또는 자동 EXCLUDE 보정 |
| IT-STATE-003 | PLANNED → IN_PROGRESS | transition API | status 변경 성공 |
| IT-STATE-004 | COMPLETED 전환 시 actual_fuel_ton 필요 | fuel_ton 없이 COMPLETED 전환 | 거부 (ORACLE-C4) |
| IT-STATE-005 | CONFIRMED → ARCHIVED | transition API | status = ARCHIVED, policy = EXCLUDE |
| IT-STATE-006 | CANCELLED → CONFIRMED 불가 | 잘못된 전환 | 422 오류 |
| IT-STATE-007 | 스냅샷 격리: 시뮬레이션 중 항차 수정 | sim 실행 중 voyage PATCH | 스냅샷은 변경되지 않음 |

### 3.2 시나리오 채택 (`test_scenario_adopt.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| IT-ADOPT-001 | SLOW_STEAMING 채택 | Voyage 계획값이 시나리오 기준으로 업데이트 |
| IT-ADOPT-002 | 채택 후 계산 무효화 | Voyage에 재계산 필요 표시 설정 |
| IT-ADOPT-003 | 존재하지 않는 scenario_id | 404 오류 |
| IT-ADOPT-004 | scenario_id가 응답에 포함됨 | compare 응답의 각 시나리오에 scenario_id 존재 |

### 3.3 연간 시뮬레이션 스냅샷 (`test_annual_simulation_snapshot.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| IT-SNAP-001 | 스냅샷 생성 확인 | simulation_snapshot 레코드 존재 |
| IT-SNAP-002 | 스냅샷 immutability | UPDATE/DELETE 시도 → Exception |
| IT-SNAP-003 | 스냅샷 내 항차 수 일치 | 입력 항차 수 == voyages_json 배열 길이 |
| IT-SNAP-004 | 동일 seed 재실행 | reproduce API → 동일 rating_probabilities (4자리) |

### 3.4 CSV 보안 (`test_csv_security.py`)

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-CSV-001 | Formula injection 방어 | `=cmd()` 셀 | `'` prefix로 escape |
| IT-CSV-002 | 숫자 컬럼 문자열 거부 | distance_nm = `=1+1` | 오류, 해당 row skip |
| IT-CSV-003 | 최대 행 수 초과 | 1001행 | 1000행까지만 처리, 초과분 skip |
| IT-CSV-004 | BOM 인코딩 처리 | UTF-8 BOM | 정상 파싱 |

---

## 4. API 테스트

### 4.1 항차 CII 추정 API (`test_voyage_cii_api.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-VC-001 | 정상 계산 | 200 OK, attained_cii가 JSON 문자열 |
| AT-VC-002 | parameters_used 포함 | 응답에 parameters_used 객체 존재 |
| AT-VC-003 | input_hash 형식 | `sha256:` + 64 hex chars |
| AT-VC-004 | DISCLAIMER warning | warnings 배열에 "REFERENCE_ONLY" 포함 |
| AT-VC-005 | transport/reference_capacity 포함 | 응답 data에 두 필드 모두 존재 |
| AT-VC-006 | Distance 누락 | 422, field_label "운항 거리" |
| AT-VC-007 | Speed < 1.0 | 422, VAL-009 |
| AT-VC-008 | 존재하지 않는 선박 | 404 |

### 4.2 시나리오 비교 API (`test_scenario_compare_api.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-SC-001 | 3개 시나리오 응답 | DIRECT, DETOUR, SLOW_STEAMING 각각 scenario_id 포함 |
| AT-SC-002 | summary 중립성 | "추천" 문구 없음, 지표별 최소값만 |
| AT-SC-003 | calculation_basis에 capacity 필드 | transport_capacity, reference_capacity 포함 |
| AT-SC-004 | DISCLAIMER 포함 | warnings + disclaimer 필드 존재 |

### 4.3 연간 시뮬레이션 API (`test_annual_simulation_api.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-AS-001 | Monte Carlo 정상 실행 | 200, rating_probabilities 합 = 1.0 (±0.001) |
| AT-AS-002 | rng_metadata 포함 | seed_entropy, bit_generator, numpy_version 포함 |
| AT-AS-003 | target_rating = E 거부 | 422 오류 |
| AT-AS-004 | reproduce 동일 결과 | 동일 seed 재실행 → 동일 probabilities |
| AT-AS-005 | 데이터 부족 | 200 + 원인 안내 메시지 |

### 4.4 계산 결과 조회 API (`test_calculation_query_api.py`) [P1-2]

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-CQ-001 | input_hash + parameter_hash 조회 | 일치하는 CalculationRun 반환 |
| AT-CQ-002 | 존재하지 않는 hash | 200, 빈 배열 |
| AT-CQ-003 | type 필터 | 해당 타입만 반환 |

### 4.5 오류 응답 형식 (`test_error_format.py`) [P1-6]

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-ERR-001 | field_label 포함 | error.details[].field_label 존재 (한글 라벨) |
| AT-ERR-002 | 한국어 조사 자연스러움 | "운항 거리는 0보다 커야 합니다." (`{field}은/는` 형태 아님) |
| AT-ERR-003 | 422 ValidationError | code, message, details 구조 |
| AT-ERR-004 | 409 ParameterError | 해당 연도 파라미터 없음 |

---

## 5. DB 제약 테스트 (`test_constraints.py`)

### 5.1 CHECK 제약

| TC ID | 테스트 | 위배 입력 | 기대 결과 |
|---|---|---|---|
| DB-CHK-001 | status × policy 매트릭스 | DRAFT + INCLUDE_AS_PLAN | CHECK 위반 |
| DB-CHK-002 | regulation_year 범위 | year = 2051 | CHECK 위반 |
| DB-CHK-003 | d-vector 순서 | d1=1.18, d4=0.86 | CHECK 위반 |
| DB-CHK-004 | hash 형식 | input_hash = "invalid" | CHECK 위반 |
| DB-CHK-005 | target_rating | target_rating = "E" | CHECK 위반 |
| DB-CHK-006 | simulation_runs 양수 | simulation_runs = 0 | CHECK 위반 |
| DB-CHK-007 | lat/lon 범위 | arrival_lat = 999 | CHECK 위반 |
| DB-CHK-008 | capacity_rule 형식 | capacity_rule = "fixed abc" | CHECK 위반 |

### 5.2 UNIQUE 제약

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| DB-UNIQ-001 | voyage_fuel_use(voyage_id, fuel_type) 중복 | UNIQUE 위반 |
| DB-UNIQ-002 | weather_model_parameter(model_version, key) 중복 | UNIQUE 위반 |
| DB-UNIQ-003 | cii_reference_line(ship_type, condition_expr) 중복 | UNIQUE 위반 |
| DB-UNIQ-004 | simulation_snapshot ↔ annual_simulation_run 1:1 | UNIQUE 위반 |

### 5.3 FK 제약

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| DB-FK-001 | vessel 물리 삭제 시 voyage 존재 | RESTRICT |
| DB-FK-002 | voyage 삭제 시 calculation_run.voyage_id | SET NULL |
| DB-FK-003 | fuel_type 코드 변경 시 vessel.default_fuel_type | ON UPDATE CASCADE |
| DB-FK-004 | weather_snapshot 삭제 시 voyage_scenario.weather_snapshot_id | SET NULL |

### 5.4 Immutable 트리거

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| DB-IMM-001 | calculation_run UPDATE 시도 | Exception |
| DB-IMM-002 | calculation_run DELETE 시도 | Exception |
| DB-IMM-003 | simulation_snapshot UPDATE 시도 | Exception |
| DB-IMM-004 | simulation_snapshot DELETE 시도 | Exception |

### 5.5 updated_at 트리거

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| DB-TRG-001 | voyage UPDATE 후 updated_at 갱신 | updated_at > 이전값 |
| DB-TRG-002 | vessel UPDATE 후 updated_at 갱신 | updated_at > 이전값 |

---

## 6. 성능 벤치마크 (`test_benchmarks.py`)

> TECH_SPEC §13.2 기준. CI 파이프라인에서 회귀 감지.

| TC ID | 테스트 | 기준 | 측정 방법 |
|---|---|---|---|
| PERF-001 | 일반 CII 계산 | p95 < 1초 | Fixture 1 기반 100회 반복 |
| PERF-002 | 시나리오 3개 비교 | p95 < 5초, 캐시 시 < 2초 | 샘플 선박 3개 시나리오 |
| PERF-003 | 연간 결정론 계산 | p95 < 1초 | 12개월 항차 데이터 |
| PERF-004 | Monte Carlo 5,000회 | p95 < 3초 | 단일 선박 12개월 |

---

## 7. 접근성 테스트

> PRD §18.4 기준.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| A11Y-001 | 위험도 색상 제거 | 텍스트만으로 위험도 이해 가능 |
| A11Y-002 | 키보드 이동 | Tab 키로 주요 액션 접근 가능 |
| A11Y-003 | 차트 대체 표 | 확률 차트에 표(table) 요약 제공 |
| A11Y-004 | Disclaimer 가시성 | 모든 결과 화면에 면책 문구 표시 |

---

## 8. 수용 기준 매핑

### 8.1 기능① (항차 CII 추정)

| AC ID | 테스트 매핑 | 검증 방법 |
|---|---|---|
| AC-F1-001 | UT-CII-001, AT-VC-001 | 필수 입력 시 CII, CO₂, 등급, 위험도 표시 |
| AC-F1-002 | UT-CII-006 | 동일 입력 반복 → 동일 결과 |
| AC-F1-003 | AT-VC-006, AT-VC-007 | 필수값 누락 시 오류 표시 |
| AC-F1-004 | UT-RATING-001~005 | 경계값 = 더 우수한 등급 |
| AC-F1-005 | IT-STATE-001 | 계획 저장 시 PLANNED 생성 |

### 8.2 기능② (시나리오 비교)

| AC ID | 테스트 매핑 | 검증 방법 |
|---|---|---|
| AC-F2-001 | AT-SC-001 | 동일 기준으로 3개 시나리오 계산 |
| AC-F2-002 | UT-WX-002~003 | 기상 API 실패 + 캐시 시 경고 표시 |
| AC-F2-003 | IT-CSV-001~004 | 기상 API 실패 + 캐시 없음 시 NONE 또는 중단 |
| AC-F2-004 | IT-ADOPT-001 | 채택 시 Voyage 계획값 업데이트 |
| AC-F2-005 | AT-SC-002 | "추천" 없이 지표별 최소값만 표시 |

### 8.3 기능③ (연간 시뮬레이터)

| AC ID | 테스트 매핑 | 검증 방법 |
|---|---|---|
| AC-F3-001 | AT-AS-001 | 결정론 연말 CII와 등급 표시 |
| AC-F3-002 | UT-RNG-002, AT-AS-004 | 동일 seed 재현성 |
| AC-F3-003 | AT-AS-001 | A+B 확률을 목표 달성 확률로 표시 |
| AC-F3-004 | AT-AS-005 | 잔여 계획 없이 확정 실적만으로 산출 |
| AC-F3-005 | AT-AS-005 | 데이터 부족 시 원인 안내 |
| AC-F3-006 | — | 민감도 분석 변수별 변화 표시 |

---

## 9. Decimal 비교 방식

### 9.1 Layer 1 (결정론 계산)

```python
from decimal import Decimal

def assert_layer1_equal(actual: str, expected: str, display_digits: int = 6):
    """
    Layer 1 값은 Decimal로 bit-exact 비교.
    표시값은 지정 자리수에서 반올림하여 비교.
    """
    actual_dec = Decimal(actual)
    expected_dec = Decimal(expected)

    # bit-exact 비교 (정규화 후)
    assert actual_dec.normalize() == expected_dec.normalize(), (
        f"Layer 1 mismatch: {actual} != {expected}"
    )

    # 표시값 비교 (지정 자리수)
    quantizer = Decimal("1e-{}".format(display_digits))
    assert actual_dec.quantize(quantizer) == expected_dec.quantize(quantizer), (
        f"Display value mismatch at {display_digits} digits: "
        f"{actual} != {expected}"
    )
```

### 9.2 Layer 2 (Monte Carlo)

```python
def assert_monte_carlo_equal(actual: dict, expected: dict, sig_digits: int = 4):
    """
    Layer 2 값은 float64로 4 유효숫자 비교.
    rating_probabilities의 각 값이 지정 유효숫자 내에서 일치.
    """
    for rating in ["A", "B", "C", "D", "E"]:
        a = actual["rating_probabilities"][rating]
        e = expected["rating_probabilities"][rating]
        assert round(a, sig_digits) == round(e, sig_digits), (
            f"Monte Carlo mismatch for rating {rating}: {a} != {e} "
            f"at {sig_digits} significant digits"
        )
```

---

## 10. CI 파이프라인 통합

### 10.1 단계별 실행

```yaml
# .github/workflows/test.yml (참고용)
stages:
  - lint:           # ruff, mypy
  - unit:           # pytest tests/unit/
  - integration:    # pytest tests/integration/
  - api:            # pytest tests/api/ (test DB + test server)
  - db:             # pytest tests/db/ (PostgreSQL test container)
  - performance:    # pytest tests/performance/ (벤치마크)
```

### 10.2 환경 고정

| 항목 | 방법 |
|---|---|
| Python | 3.12.x (Docker 이미지 고정) |
| NumPy | `numpy==2.1.0` (requirements.txt) |
| PostgreSQL | 16.x (test container) |
| OS | Linux x86_64 (CI runner) |

### 10.3 RNG canonical vector 검증

CI 시작 시 `canonical_rng_vector.py`를 실행하여 환경이 재현성 기준을 충족하는지 검증한다. 실패 시 즉시 빌드 중단.

---

## 11. 테스트 요약

### 11.1 테스트 수

| 카테고리 | 테스트 수 |
|---|---|
| 단위 (Unit) | 38 |
| 통합 (Integration) | 19 |
| API | 21 |
| DB 제약 | 18 |
| 성능 | 4 |
| 접근성 | 4 |
| **합계** | **104** |

### 11.2 우선순위

| 우선순위 | 테스트 | 시기 |
|---|---|---|
| P0 (MVP 차단) | UT-CII, UT-RATING, UT-CAP, UT-RNG, UT-HASH, IT-STATE, DB-CHK | 2026.07 |
| P1 (기능 검증) | AT-VC, AT-SC, IT-ADOPT, IT-SNAP | 2026.08 |
| P2 (품질 강화) | AT-AS, PERF, A11Y, IT-CSV | 2026.09~10 |
