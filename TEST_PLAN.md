# TEST_PLAN — BlueLog

| 항목 | 내용 |
|---|---|
| 문서명 | TEST_PLAN.md |
| 버전 | v1.12 |
| 상태 | Oracle Review + 외부 리뷰 반영 + Layer 1 픽스처 정본값 규칙 반영 (#166) + v1.4에서 §1.3 케이스 스키마 기호 표기 전환 (#46) + §4.7 인증 API 케이스 (#279) + **v1.6에서 방향 전환 반영 — 신규 서브시스템 5절 · §14 파일 인벤토리 · §11 실측 정정 (#394)** |
| 최종 수정일 | 2026-08-23 |
| 상위 문서 | `PRD.md` v4.4, `TECH_SPEC.md` v1.8, `API_SPEC.md` v1.21, `DB_SCHEMA.md` v1.16 — `AGENTS §4.4` 「마지막으로 대조를 마친 판본」 |
| 테스트 프레임워크 | pytest (Python), httpx (API 통합 테스트) |

---

## 0. 범위 및 목적

본 문서는 PRD §18 테스트 계획 요약, TECH_SPEC §13.2 성능 검증, DB_SCHEMA 제약 조건, API_SPEC 검증 규칙을 기반으로 상세 테스트 케이스를 정의한다.

### 0.1 테스트 원칙

| 원칙 | 설명 |
|---|---|
| 재현성 우선 | 동일 입력·동일 파라미터·동일 seed는 동일 결과. Layer 1은 Decimal 정밀 비교, Layer 2는 4자리 유효숫자 |
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
  conftest.py                           # 공용 fixture (DB session, httpx client, JSON loader) [ORACLE-M-5]
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
    test_layer_conversion.py            # [ORACLE-S-6]
    test_risk_level.py                  # [ORACLE-X-6]
  integration/
    test_voyage_state_transition.py
    test_scenario_adopt.py
    test_annual_simulation_snapshot.py
    test_parameter_import.py            # [ORACLE-X-1]
    test_csv_security.py
    test_weather_fallback.py            # [ORACLE-X-4]
    test_audit_log.py                   # [ORACLE-X-3]
    test_simulation_policy_filter.py    # [ORACLE-S-5]
    test_soft_delete.py                 # [ORACLE-X-5]
  api/
    test_voyage_cii_api.py
    test_scenario_compare_api.py
    test_annual_simulation_api.py
    test_calculation_query_api.py
    test_sensitivity_analysis_api.py    # [ORACLE-X-2]
    test_error_format.py
  db/
    test_constraints.py
    test_immutable_tables.py
    test_triggers.py
    test_soft_delete.py                 # [ORACLE-X-5]
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
    "attained_cii": "4.9824",
    "cii_ref": "5.66861385673728321407947925818",
    "required_cii": "5.04506633249618206053073653978",
    "superior_boundary": "4.33875704594671657205643342421",
    "lower_boundary": "4.74236235254641113689889234739",
    "upper_boundary": "5.34777031244595298416258073217",
    "inferior_boundary": "5.95317827234549483142626911694",
    "estimated_rating": "C",
    "ratio_to_required": "0.987578690077365898669252012581",
    "risk_level": "MEDIUM"
  },
  "canonical_digits": {
    "significant": 30,
    "fields": [
      "cii_ref", "required_cii",
      "superior_boundary", "lower_boundary", "upper_boundary", "inferior_boundary",
      "ratio_to_required"
    ]
  },
  "tolerance": {
    "layer1_integer": "0",
    "layer1_decimal": "9",
    "layer1_display": "6"
  },
  "fixture_note": "이 파일의 값이 유일한 기준값이며, 서비스 코드와 독립된 참조 구현체로 생성한다 — 작업 정밀도는 정본값 자릿수 + 최소 20자리, 확정은 마지막에 한 번만 정본값 자릿수(30)로 한다 (TECH_SPEC §1.2.1). 생성기: scripts/gen_fixtures.py. 정수값(M, W, capacity)은 bit-exact 비교, 소수값은 수치 비교이며 표기 자릿수는 비교 결과에 영향을 주지 않는다 (TEST_PLAN §9.1). 나누어떨어지지 않는 값의 확정 자릿수는 canonical_digits 블록에 적는다."
}
```

> 위 기대값 6개는 데이터·문서 담당(`sky01170851`)이 산출하고 개발 측이 독립 재계산으로 전건 대조했다(2026-08-05, 확인 9). 전정밀도 30자리 값은 `TECH_SPEC §1.2.3`, 계산 규칙은 `§1.2.1`을 따른다.
>
> **[ORACLE-C-1] — 폐기 (#166).** 이 항목은 `lower_boundary`를 `4.742362351`로 정정하며 산출 근거로 `5,045,066,331 × 94`를 들었다. **소수 9자리로 절단한 `required_CII`를 다시 곱한 계산**이며 `TECH_SPEC §1.2.1`이 금지하는 형태다. 원값에서 직접 반올림한 값은 **`4.742362353`**이다. 정수 연산 검산 자체는 맞았으나, 절단된 입력에서 출발해 **틀린 값을 확증**했다.
>
> **[ORACLE-C-3]** 기존 `"tolerance": {"layer1": "0"}` (bit-exact) 선언은 fixture 값이 9~10자리로 절단된 상태에서 모순 발생. tolerance 구조를 정수/소수/표시 3단계로 분리하여 정정.
>
> **[ORACLE-C-1b]** `ratio_to_required` 값을 `0.987585`에서 `0.987579`로 정정. 기존 `0.987585`는 산술 오류. PRD §14.2 응답 예시 `0.98758`과 일치.
>
> **산출 근거 교체 (#166)** — 기존 근거는 `4.9824 ÷ 5.045066331`이었다. 분모가 **소수 9자리로 절단한 `required_CII`** 라 `§1.2.1`이 금지하는 형태다. 원값으로 나누면 `4.9824 ÷ 5.04506633249618206053073653978 = 0.98757869007…` → 6자리 유효숫자 = **`0.987579`**. **결과값은 바뀌지 않는다.**
>
> **표기 확정 (#166 · 확인 11)** — 픽스처 표기를 `TECH_SPEC §1.2.1` 「픽스처 표기와 비교」 3조항에 맞춘다.
>
> | 필드 | 종전 | 확정 | 근거 |
> |---|---|---|---|
> | `co2_emission_g` | `249120000.000` (확인 9(2)) | **`249120000`** | 후행 0 금지 — `.000`은 `CF`를 소수 3자리로 적어 생긴 표기 부산물이다 |
> | `co2_emission_ton` | `249.120` | **`249.12`** | 위와 같다 |
> | `attained_cii` | `4.982400` | **`4.9824`** | 위와 같다. `4.982400`은 계산값이 아니라 `PRD §9.3`의 API 응답 **표시값**이었다 |
> | `cii_ref` 외 5개 · `ratio_to_required` | 소수 9자리 | **정본값 30자리** | 나누어떨어지지 않아 최소 표기가 성립하지 않는다. 확정 자릿수는 `canonical_digits`에 적는다 |
>
> **확인 9(2)의 `249120000.000` 결정은 철회됐다.** 근거였던 「실제 산출값이라 더 정확하다」가 성립하지 않는다 — 수학적으로 이 값은 정확히 `249,120,000`이고, `.000`은 `CF` 표기를 따라 움직인다.
>
> `ratio_to_required`는 **확정 전 원값을 분모로** 계산한 `0.987578690077365898669252012581`을 싣는다. 30자리로 확정한 `required_cii`로 나누면 끝자리가 `…580`으로 갈린다(`TECH_SPEC §1.2.1` 「중간 단계 처리」). **본문 표시 6자리 `0.987579`와 등급 `C`는 어느 쪽이든 같다.**

### 1.3 Fixture 2 — 등급 경계값

**파일**: `tests/fixtures/cii/rating_boundaries_bulk_2026.json`

```json
{
  "description": "PRD §13.2 Fixture 2 — 등급 경계값 테스트 (BULK_CARRIER, 2026)",
  "input": {
    "ship_type": "BULK_CARRIER",
    "deadweight": 50000,
    "regulation_year": 2026
  },
  "base_required_cii": "5.04506633249618206053073653978",
  "boundaries": {
    "superior":  "4.33875704594671657205643342421",
    "lower":     "4.74236235254641113689889234739",
    "upper":     "5.34777031244595298416258073217",
    "inferior":  "5.95317827234549483142626911694"
  },
  "canonical_digits": {
    "significant": 30,
    "fields": ["base_required_cii", "boundaries.*"]
  },
  "cases": [
    { "boundary": "superior", "offset": "0",        "expected_rating": "A", "note": "경계값 = 더 우수한 등급" },
    { "boundary": "lower",    "offset": "0",        "expected_rating": "B", "note": "경계값 = 더 우수한 등급" },
    { "boundary": "upper",    "offset": "0",        "expected_rating": "C", "note": "경계값 = 더 우수한 등급" },
    { "boundary": "inferior", "offset": "0",        "expected_rating": "D", "note": "경계값 = 더 우수한 등급" },
    { "boundary": "inferior", "offset": "0.000001", "expected_rating": "E", "note": "inferior + 0.000001 = E [ORACLE-M-2]" }
  ]
}
```

> **경계값 판정 규칙 (PRD §3.3.6)**: attained_CII가 경계값과 정확히 같으면 더 우수한 등급으로 판정한다. 예: `attained_CII == lower_boundary` → B (C가 아님).

##### 케이스 입력을 기호로 적는 이유 (#45 · #46)

**케이스의 판정 입력은 `boundaries`에 적힌 값이 아니다.** `boundary` + `offset`으로 기술하고, 소비자가 **확정 전 원경계에 `offset`을 더해** 만든다.

```text
판정 입력 = raw_boundary(case.boundary) + Decimal(case.offset)
raw_boundary = input 조건으로 재계산한 확정 전 경계 (§1.2.1 「공표 시점의 확정」)
```

**공표된 30자리 경계값을 그대로 `attained_cii`로 적으면 틀린 입력이 되기 때문이다.** `boundaries`는 **공표 자릿수로 확정한 값**이고, 판정은 `§1.2.1`에 따라 **확정 전 원값**과 비교한다. 확정이 **올림**되면 확정값이 원래 경계보다 커져 `PRD §3.3.6`의 `<=`가 깨진다.

> **구체적인 숫자를 적는 것 자체가 불가능한 것은 아니다.** 작업 정밀도 원값을 그대로 저장할 수도 있다. 다만 그 값은 **작업 정밀도 설정에 종속**되고 자릿수도 50자리를 넘어, 정밀도를 조정하면 픽스처가 함께 흔들린다. 기호 표기는 그 종속을 없앤다.

| 경계 | 확정 방향 | 원경계로 판정 | **확정값으로 판정** |
|---|---|---|---|
| `superior` | 내림 | A | A |
| `lower` | 내림 | B | B |
| `upper` | **올림** | C | **D** ← 뒤집힘 |
| `inferior` | **올림** | D | **E** ← 뒤집힘 |

> `#179` 조사에서 **경계 정착 1,820건 중 919건(50.49%)** 이 같은 이유로 뒤집힌 것과 동일한 현상이다.

**`input` 블록을 둔 것도 같은 이유다.** 원경계를 얻으려면 재계산이 필요하고, 그 조건이 파일 안에 없으면 `§1.2`를 함께 열어야 성립한다.

> **소비자는 `input`의 세 필드를 전부 써야 한다** — `ship_type`이 기준선 계수와 d-vector를, `regulation_year`가 감축률을, `deadweight`가 capacity를 정한다. 하나라도 하드코딩하면 그 필드는 **적혀만 있고 아무 영향을 주지 않는 장식**이 되고, 조건이 바뀌어도 옛 값으로 계속 통과한다.

**`canonical_digits`에서 `cases[].attained_cii`를 뺐다.** 케이스에는 이제 확정 대상 값이 없다.

> **[ORACLE-M-2]** 기존 E 케이스 `"5.953178272"` (inferior + 1e-9)의 note가 "경계값 + 0.000001"로 표기되어 실제 delta와 불일치. `offset`을 `0.000001`로 명시해 note와 값이 한 곳에서 결정되게 했다.
>
> **갱신 (#166)** — 경계값이 정본값 30자리로 확정되면서 E 케이스의 절대값도 함께 움직여야 했다. `offset` 표기로 바꾸면 **경계가 바뀌어도 케이스를 손대지 않는다.**
>
> **30자리 승격 (#166 · 확인 11)** — `boundaries`와 `base_required_cii`는 `§1.2`와 **글자까지 같아야 한다.** 두 픽스처가 같은 값을 다른 자릿수로 적으면 어느 쪽이 정본인지 알 수 없다.
>
> **`note`의 「경계값 + 0.000001」을 「inferior + 0.000001」로 적는다.** 케이스 5건 중 넷은 그 자체가 경계이므로 「경계값 + …」이 어느 값에 더하는지 가리지 못했다.

### 1.4 Fixture 3 — Monte Carlo 재현성

> **[ORACLE-S-1]** RNG는 TECH_SPEC §2.1에 따라 **PCG64DXSM** (`numpy.random.Generator(numpy.random.PCG64DXSM(seed))`)으로 확정되었으며, PRD v3.1에서도 동일하게 정정 완료됨.

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
    "deterministic": "decimal_exact",
    "monte_carlo": "rating_probabilities_4_sig_digits",
    "assert": "재현성 핵심 필드(input_hash, parameter_hash, model_version, rng_metadata.seed_entropy, rating_probabilities, target_success_probability, p10/p50/p90/mean_cii, deterministic.*)만 비교. 변동 필드(calculation_run_id, meta.request_id, meta.timestamp, meta.duration_ms, snapshot_id)는 제외"
  },
  "fields_to_compare": [
    "input_hash",
    "parameter_hash",
    "model_version",
    "rng_metadata.seed_entropy",
    "rating_probabilities",
    "target_success_probability",
    "p10",
    "p50",
    "p90",
    "mean_cii",
    "deterministic.*"
  ],
  "fields_to_exclude": [
    "calculation_run_id",
    "meta.request_id",
    "meta.timestamp",
    "meta.duration_ms",
    "snapshot_id"
  ]
}
```

### 1.5 Fixture 4 — 이중 Capacity 분리 [EXT-P0-1]

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
    "note": "W = 50,000 × 10,000 (실제 DWT). CII_ref = 14779E10 × 65,000^(-2.673) (fixed). 잘못 fixed를 W에 적용하면 -23% 과소 산정"
  }
}
```

### 1.6 Fixture Loading 전략 [ORACLE-M-5]

```python
# tests/conftest.py — 공용 fixture 정의
import json
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture(scope="session")
def db_session():
    """PostgreSQL test container 기반 세션 (세션 전체 공유, 각 테스트 후 롤백)"""
    ...

@pytest.fixture(scope="function")
def httpx_client(db_session):
    """각 테스트 함수마다 독립적인 httpx 클라이언트"""
    ...

@pytest.fixture(scope="session")
def load_fixture():
    """JSON fixture 파일 로더 (세션 내 캐싱)"""
    cache = {}
    def _load(rel_path: str):
        if rel_path not in cache:
            with open(FIXTURE_DIR / rel_path) as f:
                cache[rel_path] = json.load(f)
        return cache[rel_path]
    return _load
```

| Fixture | Scope | 용도 |
|---|---|---|
| `db_session` | session | PostgreSQL test container, 트랜잭션 롤백 |
| `httpx_client` | function | API 통합 테스트, 각 테스트 후 세션 초기화 |
| `load_fixture` | session | JSON fixture 캐싱 로더 |

### 1.7 정본값 생성기 — `scripts/gen_fixtures.py`

픽스처의 **Layer 1 정본값은 손으로 적지 않고 생성기로 만든다.** 생성기는 **서비스 계산 코드와 독립**이어야 한다 — 서비스 코드로 기준값을 만들면 서비스에 오류가 있을 때 **그 오류가 그대로 정답이 되어, 테스트는 통과하는데 값은 틀린 상태**가 된다.

> 이것은 가정이 아니다. `#179`가 정확히 그 상태였다 — `calc/precision.py`가 작업 정밀도를 정본값 자릿수와 같게 두어 `cii_ref`가 30자리에서 어긋났고, 기존 테스트는 전부 통과하고 있었다.

**독립성 조건** — 세 가지를 모두 지킨다.

| | 조건 | 이유 |
|---|---|---|
| 1 | **서비스 코드를 import하지 않는다** (`src/cii_platform/**`) | 언어를 바꾸는 대신 **호출 경로로부터 분리**한다. 언어를 바꾸면 값이 어긋났을 때 계산 규칙 위반인지 언어·라이브러리 차이인지 구분할 수 없어 검증력이 떨어진다 |
| 2 | **상수는 규정 원문에서 독립 전사하고 값마다 출처를 주석으로 적는다** — 예: `c = Decimal("0.622")  # MEPC.353(78) Table 1` | import만 막고 **서비스 상수 파일에서 값을 옮겨 오면** 같은 값이 들어오고, 그 값이 틀렸을 때 **틀린 값을 그대로 정답으로 삼는다.** 독립성이 여기서 깨진다 |
| 3 | **작업 정밀도는 정본값 자릿수 + 최소 20자리, 확정은 마지막에 한 번만** (`TECH_SPEC §1.2.1`) | 중간 확정이 없어야 끝자리 오차가 재발하지 않는다 |

**실행과 검증**

- **CI에 넣지 않는다.** 값 고정이 목적이므로 픽스처를 추가·변경할 때만 수동 실행한다.
- **불변성 검사를 생성기가 스스로 수행한다** — 같은 값을 작업 정밀도 `P` · `P+10` · `P+20`에서 계산해 셋이 같은지 확인한다(`TECH_SPEC §1.2.1`).
- **합격 기준은 수기로 검증이 끝난 `§1.2`의 6개 값이다.** 독립 구현만으로는 한계가 있다 — 같은 식을 다시 옮겨 적는 것이라 **옮겨 적는 실수는 잡아도 식 자체가 틀렸으면 같이 틀린다.**
- **작업 순서** — ⑴ 생성기를 먼저 만들고 ⑵ 확정된 6개 값이 그대로 재현되는지로 생성기를 검증한 뒤 ⑶ 픽스처 파일을 만든다. **없는 파일을 가리키는 문장이 중간에 존재하지 않게** 하는 순서다.

> **소관** — 생성기와 `tests/fixtures/` 파일은 **`#45`에서 만든다.** 현재 저장소에 둘 다 없으며, 픽스처를 **글자로 대조하는 코드도 0곳**이다. 경로·조건은 데이터·문서 담당(`sky01170851`)의 확인 9 · 10 회신에서 확정됐다.

---

## 2. 단위 테스트 (Unit Tests)

### 2.1 CII 계산 엔진 (`test_cii_engine.py`)

| TC ID | 테스트 | 입력 | 기대 결과 | 허용 오차 |
|---|---|---|---|---|
| UT-CII-001 | Fixture 1 전체 계산 | Fixture 1 JSON | 모든 기대값 일치 | Decimal 9자리 |
| UT-CII-002 | CO₂ 배출량 단일 연료 | HFO 80ton, CF=3.114 | 249,120,000 gCO₂ | bit-exact |
| UT-CII-003 | CO₂ 배출량 다중 연료 | HFO 60ton + LNG 20ton | 각 연료별 CO₂ 합산 | bit-exact |
| UT-CII-004 | Transport work 계산 | DWT=50,000, dist=1,000 | W=50,000,000 | bit-exact |
| UT-CII-005 | Required CII 연도별 차이 | 2026 vs 2027 | 2027 required_CII가 더 낮음 (Z-factor 증가) | Decimal 9자리 |
| UT-CII-006 | 동일 입력 반복 | Fixture 1 × 3회 | 모든 결과 일치 | 0 |
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

### 2.3 Capacity 규칙 (`test_capacity_rules.py`) [EXT-P0-1]

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
| UT-CAP-009 | 정확한 경계: DWT=279,000 [ORACLE-S-7] | DWT=279,000 | `transport=279000, reference=279000` (fixed 적용) |
| UT-CAP-010 | 경계 -1: DWT=278,999 [ORACLE-S-7] | DWT=278,999 | `transport=278999, reference=278999` (실제 DWT, fixed 미적용) |

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

def test_bulk_exact_boundary_279k_uses_fixed():
    """[ORACLE-S-7] DWT=279,000은 condition_expr 'DWT >= 279000'을 만족하므로 fixed 적용"""
    vessel = Vessel(ship_type="BULK_CARRIER", deadweight=279000)
    ref_line = get_reference_line("BULK_CARRIER", "DWT >= 279000")
    reference_cap = resolve_reference_capacity(vessel, ref_line)
    assert reference_cap == Decimal("279000")

def test_bulk_just_below_boundary_278999_uses_actual():
    """[EXT-P1-4] DWT=278,999는 condition_expr을 만족하지 않으므로 DWT < 279000 행 선택 → 실제 DWT 사용"""
    vessel = Vessel(ship_type="BULK_CARRIER", deadweight=278999)

    # get_reference_line이 아닌 select_reference_line으로 조건에 맞는 행을 선택
    ref_line = select_reference_line(vessel)

    assert ref_line.condition_expr == "DWT < 279000"
    assert ref_line.capacity_rule == "DWT"

    reference_cap = resolve_reference_capacity(vessel, ref_line)
    assert reference_cap == Decimal("278999")

### 2.4 RNG 재현성 (`test_rng_reproducibility.py`)

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| UT-RNG-001 | Canonical vector 검증 | PCG64DXSM seed=12345의 처음 5개 값이 EXPECTED_UNIFORM_5와 일치 (1e-15 오차 내) |
| UT-RNG-002 | 동일 seed 재현성 | seed=12345로 5000회 생성 → 두 번째 실행과 bit-exact 일치 |
| UT-RNG-003 | Seed 변경 시 결과 상이 | seed=12345 vs seed=99999 → rating_probabilities가 다름 |
| UT-RNG-004 | default_rng 사용 금지 | `np.random.default_rng()` 사용 시 테스트 실패 (PCG64 vs PCG64DXSM) |

> **[ORACLE-M-1]** UT-RNG-004는 런타임 canary 테스트로 유지하되, 정적 분석으로 보강. `pyproject.toml`에 ruff 규칙 추가: `flake8-bugbear`의 `ban-api: [numpy.random.default_rng]`. 이 규칙은 PR 단계에서 코드 내 `default_rng()` 사용을 차단한다.

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
| UT-IMO-002 | `14779E10` 파싱 | `"14779E10"` | `Decimal("147790000000000")` |
| UT-IMO-003 | a_raw == a_decimal 검증 | seed 데이터 전체 | 모든 행에서 `parse(a_raw) == a_decimal` |
| UT-IMO-004 | NaN/Infinity 거부 | `"NaN"` | `ValueError` |
| UT-IMO-005 | 음수 거부 | `"-100"` | `ValueError` |

### 2.8 Layer 변환 (`test_layer_conversion.py`) [ORACLE-S-6]

> TECH_SPEC §1.1 [ORACLE-S-2]: Layer 1 (Decimal) ↔ Layer 2 (float64) 경계의 단일 명시적 변환 지점을 검증.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| UT-CONVERT-001 | Layer 1 출력 타입 확인 | CII 계산 함수 반환값이 `Decimal` 타입 (`isinstance(result, Decimal)`) |
| UT-CONVERT-002 | Decimal→float 변환 정밀도 | `float(Decimal("5.66861385673728321407947925818"))`가 IEEE 754 float64 예상 비트 패턴과 일치. **소수 9자리 표시값이 아니라 정본값 30자리를 쓴다** — Layer 1→2 경계에서 실제로 변환되는 것이 그 값이다 (#166) |
| UT-CONVERT-003 | Layer 1 내 암시적 변환 탐지 | monkey-patch `float()` → Layer 1 계산 중 float 호출 0회 확인 |

```python
# test_layer_conversion.py
from decimal import Decimal
from unittest.mock import patch

def test_layer1_returns_decimal():
    """[ORACLE-S-6] Layer 1 함수는 Decimal을 반환해야 함"""
    result = calculate_cii(fixture1_input)
    assert isinstance(result.attained_cii, Decimal), \
        f"Layer 1 must return Decimal, got {type(result.attained_cii)}"

def test_no_implicit_float_in_layer1():
    """[ORACLE-S-6] Layer 1 계산 중 float() 호출이 발생하지 않아야 함"""
    with patch("builtins.float", side_effect=AssertionError("Implicit float in Layer 1")):
        calculate_cii(fixture1_input)  # 예외 없으면 통과
```

### 2.9 위험도 산정 (`test_risk_level.py`) [ORACLE-X-6]

> PRD §9.4.1(결정론 화면 위험도) 및 §9.4.2(확률 화면 위험도) 기준.

#### 결정론 위험도 (PRD §9.4.1)

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| UT-RISK-001 | A/B 등급 + margin_ratio ≥ 5% | rating=B, margin=8% | `risk_level = LOW` |
| UT-RISK-002 | A/B 등급 + margin_ratio < 5% | rating=B, margin=3% | `risk_level = MEDIUM` |
| UT-RISK-003 | C 등급 + margin_ratio < 3% 또는 D 등급 | rating=C, margin=1% | `risk_level = HIGH` |
| UT-RISK-004 | E 등급 | rating=E | `risk_level = CRITICAL` |
| UT-RISK-001B | A/B 등급 + margin_ratio = 5% (경계값) | rating=B, margin=5% | `risk_level = LOW` |
| UT-RISK-003A | C 등급 + margin_ratio ≥ 3% (단독) | rating=C, margin=5% | `risk_level = MEDIUM` |
| UT-RISK-003B | C 등급 + margin_ratio = 3% (경계값) | rating=C, margin=3% | `risk_level = MEDIUM` |
| UT-RISK-003C | D 등급 단독 | rating=D, margin=8% | `risk_level = HIGH` |

#### 확률 위험도 (PRD §9.4.2)

| TC ID | 테스트 | 입력 (달성 확률) | 기대 결과 |
|---|---|---|---|
| UT-RISK-005 | 목표 등급 달성 확률 ≥ 80% | P=0.85 | `risk_level = LOW` |
| UT-RISK-006 | 50% ≤ P < 80% | P=0.60 | `risk_level = MEDIUM` |
| UT-RISK-007 | 20% ≤ P < 50% | P=0.35 | `risk_level = HIGH` |
| UT-RISK-008 | P < 20% | P=0.10 | `risk_level = CRITICAL` |
| UT-RISK-005B | 경계값: P = 80% | P=0.80 | `risk_level = LOW` |
| UT-RISK-006B | 경계값: P = 50% | P=0.50 | `risk_level = MEDIUM` |
| UT-RISK-007B | 경계값: P = 20% | P=0.20 | `risk_level = HIGH` |

---

### 2.10 YTD 누적 CII 산출 엔진 (`test_ytd_engine.py` · `test_ytd_cii_service_db.py`) [#394]

`#353`이 신설한 연간 누적 산출이다. **등급이 붙는 값은 YTD 하나뿐**이므로(`PRD §3.3.8`) 이 영역의 오류는 곧 등급 오류다.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| UT-YTD-001 | 항차 연료와 not under way 연료를 분자 `M`에 합산 | 두 갈래가 모두 반영 |
| UT-YTD-002 | 분모 `Dt`에 not under way 이동 거리 포함 | `MEPC.412(84)` §4.2 「both under way and not under way」 |
| UT-YTD-003 | 정박 연료 증가에 따른 등급 악화 | 0t→C · 10t→D · 30t→E |
| UT-YTD-004 | `annual_inclusion_policy` 판정 | `PRD §8.1.2` 매트릭스대로 포함/제외 |
| UT-YTD-005 | CF 스냅샷 분리 집계 | `(fuel_type, cf_used)`로 묶여 개정 전후 행이 각자 CF로 곱해진다 (`#378`) |
| UT-YTD-006 | 계산 코어가 시각을 모른다 | `calc` 인자에 `as_of`·`regulation_year` 없음 (`#368` 계약) |

> **`UT-YTD-002`가 중요한 이유** — `#353` 작업 중 IMO 원문 대조로 **분모 전제가 틀렸음**이 드러났다. `MEPC.352(78)` 구판에는 「under way」 한정어가 없어 우리가 잘못 읽었고, `MEPC.412(84)`가 괄호로 명시했다. 오차 방향이 **분모 과소 → 등급이 실제보다 나쁘게** 나오는 쪽이다.

### 2.11 시뮬레이션 시계 (`test_simulation_clock.py`) [#394]

`#368`이 신설했다. **시각을 명시적 입력으로 승격**해 `TECH_SPEC §5.4` 재현성 계약을 깨지 않고 값이 변하게 한다.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| UT-CLOCK-001 | `as_of`가 같으면 결과가 같다 | 재현성 계약 유지 |
| UT-CLOCK-002 | `as_of`가 다르면 누적값이 다르다 | 시간 진행이 반영 |
| UT-CLOCK-003 | `as_of` 미지정 시 동작 | 계약대로 (서버 확정 또는 거부) |
| UT-CLOCK-004 | `as_of`가 `input_hash`에 들어가는가 | `#42` canonical 규약과 정합 |

> 시각을 암묵적 `now()`로 두면 **같은 입력이 매번 다른 결과**를 내 `§5.4`가 무너진다. 이 절은 그 경계를 지킨다.

## 3. 통합 테스트 (Integration Tests)

### 3.1 항차 상태 전이 (`test_voyage_state_transition.py`)

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-STATE-001 | DRAFT → PLANNED 전환 | transition API | status = PLANNED, annual_inclusion_policy 설정 가능 |
| IT-STATE-002 | DRAFT + INCLUDE_AS_PLAN 거부 | DRAFT에서 policy 설정 시 | 422 또는 자동 EXCLUDE 보정 |
| IT-STATE-003 | PLANNED → IN_PROGRESS | transition API | status 변경 성공 |
| IT-STATE-004 | COMPLETED 전환 시 actual_fuel_ton 필요 | fuel_ton 없이 COMPLETED 전환 | 거부 (ORACLE-C-4) |
| IT-STATE-005 | CONFIRMED → ARCHIVED | transition API | status = ARCHIVED, policy = EXCLUDE |
| IT-STATE-006 | CANCELLED → CONFIRMED 불가 | 잘못된 전환 | 422 오류 |
| IT-STATE-007 | 스냅샷 격리: 시뮬레이션 중 항차 수정 | sim 실행 중 voyage PATCH | 스냅샷은 변경되지 않음 |
| IT-STATE-008 | **IN_PROGRESS → COMPLETED 정상 완료** | `annual_inclusion_policy=INCLUDE_AS_ACTUAL` 동반 | 200 · status·policy가 **함께** 반영 (`#688`) |

> **`IT-STATE-008`을 뒤늦게 넣은 이유** — `001`~`007`에 **정상 완료가 없었다.** `004`는 실적이 없을 때 거부되는 쪽만 보고, 나머지는 다른 전이거나 거부 케이스다. `IN_PROGRESS → COMPLETED`는 `annual_inclusion_policy`가 **상태 그룹을 건너뛰는 유일한 전이**(`INCLUDE_AS_PLAN` → `INCLUDE_AS_ACTUAL`)인데, 그 경로를 확인하는 케이스가 없어 `chk_status_policy` 위반이 500으로 새어 나가는 상태가 오래 남아 있었다. **거부만 검사하면 전부 거부해도 통과한다** (`#636`이 같은 교훈을 남겼다).


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
| IT-SNAP-004 | 동일 seed 재실행 | reproduce API → 동일 rating_probabilities (4자리 유효숫자) |

### 3.4 CSV 보안 (`test_csv_security.py`)

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-CSV-001 | Formula injection 방어 (`=`) | `=cmd()` 셀 | `'` prefix로 escape |
| IT-CSV-002 | 숫자 컬럼 문자열 거부 | distance_nm = `=1+1` | 오류, 해당 row skip |
| IT-CSV-003 | 최대 행 수 초과 | 1001행 | 1000행까지만 처리, 초과분 skip |
| IT-CSV-004 | BOM 인코딩 처리 | UTF-8 BOM | 정상 파싱 |
| IT-CSV-005 | Formula injection 방어 (`+`) [ORACLE-S-2] | `+cmd()` 셀 | `'` prefix로 escape |
| IT-CSV-006 | Formula injection 방어 (`-`) [ORACLE-S-2] | `-cmd()` 셀 | `'` prefix로 escape |
| IT-CSV-007 | Formula injection 방어 (`@`) [ORACLE-S-2] | `@SUM()` 셀 | `'` prefix로 escape |

> **[ORACLE-S-2]** API_SPEC §8.2는 `=`, `@`, `+`, `-` 네 가지 prefix escape를 요구. 기존 테스트는 `=`만 검증하여 3개 공격 벡터가 누락되었음. IT-CSV-005~007 추가.

### 3.5 파라미터 가져오기 (`test_parameter_import.py`) [ORACLE-X-1]

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-IMPORT-001 | 정상 가져오기 | 유효한 JSON 파라미터 파일 | 파라미터 저장, content_hash 생성 |
| IT-IMPORT-002 | 중복 버전 거부 | 동일 regulation_year + ship_type | 409 오류 |
| IT-IMPORT-003 | 잘못된 형식 거부 | a_raw가 숫자가 아님 | 422 오류 |
| IT-IMPORT-004 | content_hash 불일치 검증 | hash 값과 실제 내용 불일치 | 422 오류 |
| IT-IMPORT-005 | 실패 시 롤백 | 가져오기 중 3번째 행 오류 | 트랜잭션 롤백, 이전 상태 유지 |

### 3.6 기상 Fallback 체인 (`test_weather_fallback.py`) [ORACLE-X-4]

> PRD §11.6 3단계 fallback: fresh API → stale cache (6h) + warning → NONE + warning.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-WX-001 | API 정상 → factor 적용 | Open-Meteo 정상 응답 | weather_factor > 1.0, warning 없음 |
| IT-WX-002 | API 실패 + 6h 캐시 | API timeout, 캐시 존재 | 캐시 factor 사용, `WEATHER_STALE` warning |
| IT-WX-003 | API 실패 + 캐시 없음 | API timeout, 캐시 없음 | weather_model = NONE, `WEATHER_NONE_FALLBACK` warning |

### 3.7 감사 로그 (`test_audit_log.py`) [ORACLE-X-3]

> DB_SCHEMA §2.14, TECH_SPEC §13.1 감사 로그 요구사항.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-AUDIT-001 | 항차 확정 시 감사 로그 | voyage CONFIRM 전환 | audit_log 레코드 존재 (action=VOYAGE_CONFIRM) |
| IT-AUDIT-002 | 파라미터 변경 시 감사 로그 | reference_line 수정 | audit_log에 before/after 값 포함 |
| IT-AUDIT-003 | 계산 실행 시 감사 로그 | CII 계산 실행 | audit_log에 input_hash, parameter_hash 포함 |

### 3.8 시뮬레이션 정책 필터링 (`test_simulation_policy_filter.py`) [ORACLE-S-5]

> annual_inclusion_policy에 따라 시뮬레이션 입력 항차가 올바르게 필터링되는지 검증.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-SIM-POLICY-001 | 혼합 정책 필터링 | EXCLUDE 2건 + INCLUDE_AS_PLAN 1건 + INCLUDE_AS_ACTUAL 1건 | 시뮬레이션 입력에 INCLUDE_* 항차만 포함 (2건) |
| IT-SIM-POLICY-002 | CONFIRMED + EXCLUDE 제외 | CONFIRMED, policy=EXCLUDE | 시뮬레이션 입력에서 제외됨 |

### 3.9 소프트 삭제 (`test_soft_delete.py`) [ORACLE-X-5]

> vessel 및 voyage의 `is_deleted` 플래그 + partial unique index 동작 검증.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-SOFTDEL-001 | 소프트 삭제 후 조회 제외 | vessel DELETE (soft) | GET /vessels 응답에 미포함 |
| IT-SOFTDEL-002 | 삭제 후 IMO 번호 재사용 | vessel A soft-delete → 동일 IMO로 신규 등록 | 등록 성공 (partial unique index 허용) |

### 3.10 자료 내보내기 (`test_data_export_db.py`) [#59]

> `API_SPEC §8.1`. **가져오기(`§3.4`)의 반대 방향이다.**
>
> ⚠️ `IT-CSV-001~004`는 이 절의 케이스가 **아니다.** 「row skip」·「1001행」·「정상 파싱」은 전부 **파일을 읽는 쪽**의 시나리오이며 `#60`이 `test_voyage_import_db.py`로 이미 덮었다. `#59`의 완료 기준이 그 넷을 인용한 것은 `§8.1`과 `§8.2`를 한 덩어리로 본 흔적이다 — 아래가 내보내기의 완료 기준이다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-EXPORT-001 | **왕복** — 내보낸 파일을 그대로 다시 가져온다 | 항차 1건 export → 다른 선박으로 import | `imported_count = 1` · `errors = []`. 앞 일곱 열이 `§8.2` 필수 컬럼과 이름·순서 일치 |
| IT-EXPORT-002 | 채울 수 없는 열을 두지 않는다 | 항차 표 컬럼 | `attained_cii`·`rating` 없음. 전제(`calculation_run.voyage_id`가 전부 NULL)도 함께 단언 |
| IT-EXPORT-003 | Excel 호환 | 한글이 든 항차 | 첫 바이트 UTF-8 BOM · 줄바꿈 전부 CRLF · 한글 보존 |
| IT-EXPORT-004 | 수식 주입 방어 (`=`·`+`·`-`·`@`) | `notes`에 `=HYPERLINK(…)` | 셀이 `'` 접두를 받는다 (`§8.2`와 **같은 함수**) |
| IT-EXPORT-005 | 값의 표기 | 실적·시각·빈 값 | 지수 표기 없음 · KST 오프셋 ISO 8601 · 없는 값은 빈 칸 · CO₂는 실적 우선 |
| IT-EXPORT-006 | 한 행 = 항차 × 연료 | 연료 2종 항차 / 연료 없는 항차 | 행 2개(같은 `voyage_id`) / 행 1개(연료 칸 빈다) |
| IT-EXPORT-007 | 필터·파라미터 | `year` · 잘못된 `type` · 없는 선박 | 규제연도로 거른다 · 422(기본값으로 되돌리지 않는다) · 404(빈 표 아님) |
| IT-EXPORT-008 | `calculations`·`simulations`·`format=json` | 계산 이력 · 시뮬레이션 실행 | 저장된 `result_json`을 재계산 없이 읽는다 · `SCENARIO`는 식별자만 · `year`는 KST 생성연도 · JSON이 CSV와 같은 값 |

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

### 4.4 계산 결과 조회 API (`test_calculation_query_api.py`) [EXT-P1-2]

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-CQ-001 | input_hash + parameter_hash 조회 | 일치하는 CalculationRun 반환 |
| AT-CQ-002 | 존재하지 않는 hash | 200, 빈 배열 |
| AT-CQ-003 | type 필터 | 해당 타입만 반환 |

### 4.5 민감도 분석 API (`test_sensitivity_analysis_api.py`) [ORACLE-X-2]

> PRD §12.7 MUST 요구사항. AC-F3-006 매핑.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-SA-001 | 민감도 분석 응답 구조 | 변수별 delta_CII 값 포함 (speed, fuel_consumption, distance) |
| AT-SA-002 | 속도 vs 연료 영향도 비교 | 속도 감소가 연료 감소보다 CII 개선 효과 큼 (물리적 타당성) |

### 4.6 오류 응답 형식 (`test_error_format.py`) [EXT-P1-6]

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-ERR-001 | field_label 포함 | error.details[].field_label 존재 (한글 라벨) |
| AT-ERR-002 | 한국어 조사 자연스러움 | "운항 거리는 0보다 커야 합니다." (`{field}은/는` 형태 아님) |
| AT-ERR-003 | 422 ValidationError | code, message, details 구조 |
| AT-ERR-004 | 409 ParameterError | 해당 연도 파라미터 없음 |

### 4.7 인증 API (#279)

> **[#414] 구글 OIDC를 제거하고 자체 이메일·비밀번호 인증으로 전환했다.** 종전
> `AT-AUTH-001`~`004`는 `id_token` 검증·`state`·`redirect_to`를 보던 항목이라 대상이
> 사라졌다. TC ID는 재번호하지 않고 **같은 번호에 새 항목을 배치**한다 — 번호를
> 밀면 이슈·커밋의 기존 참조가 어긋난다.

> 구현 파일 — `test_auth_api.py`(가입·로그인 계약) · `test_password.py`(해싱·정책) ·
> `test_auth_session.py`(세션·CSRF 단위) · `test_auth_wiring.py`(배선, main.app) ·
> `test_auth_failure_paths.py`(만료·무효화·미등록) · `test_dev_auth.py`(스텁 인증) ·
> `test_docs_exposure.py`(OpenAPI 문서 노출 범위).
> 성공 경로만 검증하면 인증이 실제로 막고 있는지 알 수 없다 — 실패 경로가 핵심이다.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| AT-AUTH-001 | **틀린 비밀번호와 없는 이메일** | **401 · 같은 문구·같은 코드** — 계정 존재 여부 비노출 (`test_auth_api.py`) |
| AT-AUTH-002 | 비밀번호 정책 위반 (10자 미만·128자 초과) | 422 `VALIDATION_ERROR` (`test_auth_api.py`·`test_password.py`) |
| AT-AUTH-003 | 이메일 대소문자 차이 | 같은 계정으로 취급 — 소문자 정규화 (`test_auth_api.py`) |
| AT-AUTH-004 | 응답·감사 로그에 비밀번호 노출 | **원문·해시 모두 미노출** (`test_auth_api.py`·`test_audit_events_db.py`) |
| AT-AUTH-005 | 이메일 중복 가입 시도 | **409 거부 + 중복 사실 고지** — 로그인 실패와 반대 방향의 의도된 비대칭 (`test_auth_api.py`) |
| AT-AUTH-006 | 세션 없는 보호 경로 | 401 (`test_auth_wiring.py`) |
| AT-AUTH-007 | 세션 만료 후 같은 쿠키 | 401 + "만료" 안내 (`test_auth_failure_paths.py`) |
| AT-AUTH-008 | 로그아웃 후 같은 쿠키 재사용 | 401 (`test_auth_failure_paths.py`) |
| AT-AUTH-009 | CSRF 토큰 누락·불일치 (POST·PATCH·DELETE) | 403 `CSRF_ERROR`, GET은 통과 (`test_auth_session.py`·`test_auth_wiring.py`) |
| AT-AUTH-010 | `session_row` 없는 상태 변경 (배선 어김) | 401 — fail-closed (`test_auth_session.py`) |
| AT-AUTH-011 | 공개 경로 | 열거 경로(health·signup·login·dev-login)만 무인증 통과 (`test_auth_failure_paths.py`) |
| AT-AUTH-012 | `APP_ENV=production` dev-login | 라우트 미등록 (`test_auth_failure_paths.py`) |
| AT-AUTH-013 | dev-login 재기동 (고정 UUID) | 2회 모두 200 (`test_dev_auth.py`) |
| AT-AUTH-014 | `APP_ENV=production` OpenAPI 문서 (`/docs`·`/redoc`·`/openapi.json`) | **401** — 라우트 미등록 + 공개 경로 제외. 404가 아니라 **다른 미등록 경로와 같은 응답**이어야 한다 (`test_docs_exposure.py`) |
| AT-AUTH-015 | 공개 경로 목록의 모든 경로에 라우트가 실재하는가 | **전부 실재.** 없으면 그 경로만 404가 되어 신호가 남는다 — `APP_ENV=production` dev-login이 그랬다 (`test_docs_exposure.py`) |

---

## 5. DB 제약 테스트 (`test_constraints.py`)

### 5.1 CHECK 제약

| TC ID | 테스트 | 위배 입력 | 기대 결과 |
|---|---|---|---|
| DB-CHK-001 | status × policy: DRAFT + INCLUDE_AS_PLAN | DRAFT, INCLUDE_AS_PLAN | CHECK 위반 |
| DB-CHK-001a | status × policy: DRAFT + INCLUDE_AS_ACTUAL [ORACLE-S-3] | DRAFT, INCLUDE_AS_ACTUAL | CHECK 위반 |
| DB-CHK-001b | status × policy: CANCELLED + INCLUDE_AS_PLAN [ORACLE-S-3] | CANCELLED, INCLUDE_AS_PLAN | CHECK 위반 |
| DB-CHK-001c | status × policy: ARCHIVED + INCLUDE_AS_ACTUAL [ORACLE-S-3] | ARCHIVED, INCLUDE_AS_ACTUAL | CHECK 위반 |
| DB-CHK-001d | status × policy: COMPLETED + INCLUDE_AS_PLAN [ORACLE-S-3] | COMPLETED, INCLUDE_AS_PLAN | CHECK 위반 |
| DB-CHK-001e | status × policy: PLANNED + INCLUDE_AS_ACTUAL [ORACLE-S-3] | PLANNED, INCLUDE_AS_ACTUAL | CHECK 위반 |
| DB-CHK-002 | regulation_year 범위 | year = 2051 | CHECK 위반 |
| DB-CHK-003 | d-vector 순서 | d1=1.18, d4=0.86 | CHECK 위반 |
| DB-CHK-004 | hash 형식 | input_hash = "invalid" | CHECK 위반 |
| DB-CHK-005 | target_rating | target_rating = "E" | CHECK 위반 |
| DB-CHK-006 | simulation_runs 양수 | simulation_runs = 0 | CHECK 위반 |
| DB-CHK-007 | lat/lon 범위 | arrival_lat = 999 | CHECK 위반 |
| DB-CHK-008 | capacity_rule 형식 | capacity_rule = "fixed abc" | CHECK 위반 |
| DB-CHK-009 | IMO 번호 형식 [ORACLE-S-4] | imo_number = "12345" (6자리) | CHECK 위반 |
| DB-CHK-010 | gross_tonnage 양수 [ORACLE-S-4] | gross_tonnage = 0 | CHECK 위반 |
| DB-CHK-011 | deadweight 양수 [ORACLE-S-4] | deadweight = -1 | CHECK 위반 |
| DB-CHK-012 | distance_nm 양수 [ORACLE-S-4] | distance_nm = 0 | CHECK 위반 |
| DB-CHK-013 | speed_kn 최소값 [ORACLE-S-4] | speed_kn = 0.5 | CHECK 위반 (VAL-009) |
| DB-CHK-014 | fuel_ton 양수 [ORACLE-S-4] | fuel_ton = -10 | CHECK 위반 |
| DB-CHK-015 | fuel_source enum [ORACLE-S-4] | fuel_source = "GUESS" | CHECK 위반 |
| DB-CHK-016 | scenario_type enum [ORACLE-S-4] | scenario_type = "FAST" | CHECK 위반 |
| DB-CHK-017 | scenario_rating enum [ORACLE-S-4] | estimated_rating = "F" | CHECK 위반 |
| DB-CHK-018 | scenario_risk enum [ORACLE-S-4] | risk_level = "EXTREME" | CHECK 위반 |
| DB-CHK-019 | a_decimal 양수 [ORACLE-S-4] | a_decimal = -100 | CHECK 위반 |
| DB-CHK-020 | c ≥ 0 [ORACLE-S-4] | c = -0.1 | CHECK 위반 |
| DB-CHK-021 | policy ≠ EXCLUDE 시 regulation_year 필수 [ORACLE-S-4] | INCLUDE_AS_PLAN, regulation_year = NULL | CHECK 위반 |

> **[ORACLE-S-3]** 기존 DB-CHK-001은 1개 무효 조합만 검증. status × policy 매트릭스의 전체 무효 조합을 커버하도록 001a~001e 추가.
>
> **[ORACLE-S-4]** DB_SCHEMA에 정의된 13개 이상의 CHECK 제약(imoo 형식, 양수 제약, enum 제약 등)에 대한 테스트가 누락됨. DB-CHK-009~021 추가.

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

### 5.6 소프트 삭제 (`test_soft_delete.py`) [ORACLE-X-5]

> partial unique index (`WHERE is_deleted = false`) 동작 검증.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| DB-SOFT-001 | 소프트 삭제 후 동일 IMO 등록 | vessel A soft-delete → 동일 IMO 신규 등록 | 등록 성공 (partial unique index 허용) |
| DB-SOFT-002 | 소프트 삭제 vessel이 unique 위반 유발 | 동일 IMO, 둘 다 is_deleted=false | UNIQUE 위반 |

---

### 5.7 seed 적재 (`test_seed_data.py` · `test_seed_migration.py` 외 5개) [#394]

`#127`이 모든 seed를 `alembic upgrade head` 경로로 일원화했다(`DB_SCHEMA §8.1.1`).

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| DB-SEED-001 | `upgrade head` 단독으로 50행 적재 | `regulation_year` 8 · `cii_reference_line` 20 · `cii_rating_boundary` 14 · `fuel_type` 8 |
| DB-SEED-002 | 마이그레이션 값과 `seed.py` 상수 대조 | 전건 일치 — 갈라지면 실패 |
| DB-SEED-003 | 마이그레이션이 `src/` 상수를 import하지 않는다 | import 문에 `cii_platform` 없음 |
| DB-SEED-004 | `seed_all()` 재실행 시 행이 늘지 않는다 | upsert 충돌 키가 UNIQUE 키와 일치 |
| DB-SEED-005 | `fuel_type.content_hash` 재계산 대조 | `{code, cf}` canonical (`DB_SCHEMA §8.3.1`) |
| DB-SEED-006 | downgrade가 넣은 키만 지운다 | 운영 중 추가된 행 보존 |

> **`DB-SEED-002`·`DB-SEED-003`이 한 쌍이다.** 마이그레이션은 「그날 넣은 값(불변)」, `seed.py`는 「지금 옳다고 보는 값(가변)」이라 규제 개정 시 갈라지는 것이 정상이다. 다만 **모르고 지나가면 안 되므로** 대조가 그 순간을 드러낸다.

### 5.8 not under way 구간·연료 (`test_not_underway_migrations.py`) [#394]

`#345`가 신설하고 `#376`·`#378`이 보강했다. **기록하지 않으면 분자 `M`이 늘지 않아 정박해도 등급이 떨어지지 않는다.**

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| DB-NUW-001 | `period_type` 6값 · `consumer_type` 4값 CHECK | `MEPC.385(81)` DCS 보고 항목 |
| DB-NUW-002 | `(period_id, consumer_type, fuel_type)` UNIQUE | **CO₂ 이중 산정 차단** (`#376`) |
| DB-NUW-003 | `cf_used` NOT NULL | CF 스냅샷 보존 (`#378` · `PRD §8.4`) |
| DB-NUW-004 | FK 자식 인덱스 존재 | 구간 겹침 조회 · SET NULL 확인 |
| DB-NUW-005 | `distance_nm` 컬럼 | 분모 `Dt`에 들어가는 이동 거리 (`#353`) |

> **`DB-NUW-002`는 성능이 아니라 정합성이다.** `voyage_fuel_use`가 `[S-2]`로 이미 막아 둔 것과 같은 사안이며, 중복되면 YTD 집계가 CO₂를 두 번 센다.

### 5.9 운항 상태·현재 위치 (`test_vessel_position_state_migrations.py`) [#394]

`#346`이 신설하고 `#369`가 갱신 경로를 붙였다.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| DB-VSTATE-001 | `underway_state` + `detail_status` 2축 CHECK | `UIFLOW v2.0` 7값 표 |
| DB-VSTATE-002 | 두 축의 정합 규칙 | `chk_vessel_state_pair` |
| DB-VSTATE-003 | `position_updated_at`은 서버가 확정 | 클라이언트 시계 불신 (`API_SPEC §2.2`) |

## 6. 성능 벤치마크 (`test_benchmarks.py`)

> TECH_SPEC §13.2 기준. CI 파이프라인에서 회귀 감지.
>
> **[ORACLE-M-3]** 측정 조건: 첫 10회 warm-up 제외, 최소 100회 측정, `gc.disable()` 적용.

| TC ID | 테스트 | 기준 | 측정 방법 |
|---|---|---|---|
| PERF-001 | 일반 CII 계산 | p95 < 1초 | Fixture 1 기반 100회 반복 (warm-up 10회 제외, gc.disable) |
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
| AC-F2-002 | IT-WX-002 | 기상 API 실패 + 캐시 시 경고 표시 |
| AC-F2-003 | IT-WX-003 | 기상 API 실패 + 캐시 없음 시 NONE 또는 중단 |
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
| AC-F3-006 | AT-SA-001, AT-SA-002 [ORACLE-X-2] | 민감도 분석 변수별 변화 표시 |

---

## 9. Decimal 비교 방식

### 9.1 Layer 1 (결정론 계산)

```python
from decimal import Decimal

from cii_platform.calc.precision import publish_layer1_canonical


def assert_layer1_equal(actual: str, expected: str, decimal_places: int | None = None):
    """
    Layer 1 값은 Decimal 수치 비교.

    정수값은 bit-exact. 소수값은 **공표 자릿수로 확정한 뒤 정확 일치**를 본다
    (TECH_SPEC §1.2.1 「공표 시점의 확정」).

    비교는 항상 수치 비교다. 표기 자릿수(`249120000` vs `249120000.000`)는
    비교 결과에 영향을 주지 않는다 (TECH_SPEC §1.2.1 픽스처 표기 조항 2).

    `actual`은 서비스가 반환한 **작업 정밀도 원값**이고 `expected`는 픽스처의
    **정본값 30자리**다. 두 값은 자릿수가 다르므로 그대로 비교하면 항상 어긋난다.
    확정을 이 함수가 수행하는 이유는, 호출부마다 확정 시점이 달라지면 §1.2.1이
    금지하는 중간 확정이 테스트 코드에 섞이기 때문이다.

    decimal_places를 넘기면 그 소수 자릿수로 완화 비교한다. **정본값 필드에는
    쓰지 않는다** — 화면 표시값(`layer1_display`)처럼 자릿수가 규정된 값을
    대조할 때만 쓴다.

    [ORACLE-C-3] 기존 bit-exact (tolerance=0) 주장은 소수 9자리로 절단된 fixture
    값과 모순되어 자릿수 비교로 정정했다.

    [ORACLE-C-3 재정정, #166] 절단의 근거였던 fixture 값이 정본값 30자리로
    교체되어 그 전제가 사라졌다.

    [#179] 구현이 §1.2.1을 충족해 정확 일치 비교가 성립한다. 종전에는 작업
    정밀도가 정본값 자릿수와 같아 30자리 지점에서 어긋났고, 그 때문에 기본값을
    소수 9자리로 두고 있었다.

    `decimal_digits` → `decimal_places` 개명: quantize가 실제로 적용하는 것은
    소수 자릿수인데 이름과 설명이 '유효숫자'였다. TECH_SPEC §1.2.1의 표기
    규약(「N자리」=유효숫자, 소수 자릿수는 「소수 N자리」)에 맞춘다.
    """
    actual_dec = Decimal(actual)
    expected_dec = Decimal(expected)

    # 정수값은 bit-exact 비교
    if actual_dec == actual_dec.to_integral_value() and \
       expected_dec == expected_dec.to_integral_value():
        assert actual_dec == expected_dec, (
            f"Layer 1 integer mismatch: {actual} != {expected}"
        )
        return

    # 완화 비교 — 표시 자릿수가 규정된 값에만 쓴다
    if decimal_places is not None:
        quantizer = Decimal("1e-{}".format(decimal_places))
        assert actual_dec.quantize(quantizer) == expected_dec.quantize(quantizer), (
            f"Layer 1 decimal mismatch at {decimal_places} decimal places: "
            f"{actual} != {expected}"
        )
        return

    # 기본 — 공표 자릿수로 확정한 뒤 정확 일치
    assert publish_layer1_canonical(actual_dec) == expected_dec, (
        f"Layer 1 canonical mismatch: "
        f"{publish_layer1_canonical(actual_dec)} != {expected_dec} "
        f"(raw actual: {actual})"
    )
```

> **`tolerance.layer1_decimal`의 역할이 바뀐다.** 종전에는 **정본값 비교의 기본 강도**였으나, 이제 정본값은 정확 일치로 본다. 픽스처의 `layer1_decimal`·`layer1_display`는 **화면 표시값 대조용 완화치**로만 쓴다(`§1.2` `canonical_digits`에 없는 필드).

### 9.2 Layer 2 (Monte Carlo)

```python
import math

def assert_monte_carlo_equal(actual: dict, expected: dict, sig_digits: int = 4):
    """
    Layer 2 값은 float64로 지정 유효숫자 내에서 비교.
    rating_probabilities의 각 값이 지정 유효숫자 내에서 일치.

    [ORACLE-C-2] 기존 round(a, sig_digits)는 소수점 자리수로 반올림하여
    유효숫자와 다른 결과를 냄 (예: 0.0312 → round(0.0312, 4) = 0.0312는
    3자리 유효숫자만 비교). 상대 오차 기반 비교로 정정.
    """
    rel_tol = 0.5 * 10 ** (-(sig_digits - 1))  # 4자리 → 5e-4

    for rating in ["A", "B", "C", "D", "E"]:
        a = actual["rating_probabilities"][rating]
        e = expected["rating_probabilities"][rating]

        if e == 0:
            assert a == 0, (
                f"MC mismatch for rating {rating}: expected 0, got {a}"
            )
        else:
            assert math.isclose(a, e, rel_tol=rel_tol), (
                f"Monte Carlo mismatch for rating {rating}: "
                f"{a} != {e} at {sig_digits} significant digits "
                f"(rel_tol={rel_tol})"
            )

    # probabilities 합계 검증
    total = sum(actual["rating_probabilities"].values())
    assert math.isclose(total, 1.0, abs_tol=1e-3), (
        f"Rating probabilities sum != 1.0: {total}"
    )
```

> **[ORACLE-C-2]** 기존 `round(a, sig_digits)`는 N번째 **소수점 자리수**로 반올림함. PRD §9.3.1과 TECH_SPEC §1.3은 "4자리 **유효숫자**"를 요구. 예: `P(E)=0.0312`의 경우 `round(0.0312, 4) = 0.0312`이지만 4 유효숫자 비교에서는 `0.03120` 정밀도가 필요. `math.isclose(rel_tol=5e-4)`로 정정하여 유효숫자 기반 비교 구현.

---

## 10. CI 파이프라인 통합

### 10.1 단계별 실행

```yaml
# .github/workflows/test.yml (참고용)
stages:
  - lint:           # ruff (flake8-bugbear ban-api: numpy.random.default_rng 포함) [ORACLE-M-1]
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

**실측 기준 (2026-08-15 · `pytest --collect-only`)**

| 영역 | 파일 | `def test_` 함수 |
|---|---:|---:|
| 단위 · 계산 엔진 | 11 | 155 |
| DB · 제약·마이그레이션 | 11 | 75 |
| DB · seed 적재 | 7 | 59 |
| API · 공통·운영 | 8 | 51 |
| API · 선박·항차·계산 | 8 | 27 |
| 단위 · 시뮬레이션 시계 | 1 | 20 |
| API · 인증 | 6 | 16 |
| 단위 · YTD 산출 엔진 | 2 | 16 |
| DB · not under way | 1 | 15 |
| DB · 운항 상태·위치 | 1 | 12 |
| 단위 · 추정·기상 | 1 | 11 |
| 문서 · 인벤토리 동기화 | 1 | 4 |
| 통합 · 감사 로그 | 1 | 3 |
| 통합 · CSV | 1 | 3 |
| API · 기능② 시나리오 | 2 | 2 |
| **합계** | **62** | **469** |

> **함수 469 → 수집 979.** 차이는 파라미터화다. 파일별 내역은 `§14`에 있다.
> 프론트엔드(`vitest`)는 별도로 **331건**이며 이 문서의 관할 밖이다(`§14.5`).

> **[ORACLE-M-4] [#394 정정]** 종전 이 표는 합계 **181**(단위 55·통합 37·API 39·DB 42·성능 4·접근성 4)이었고, 바로 아래 `§11.3`은 같은 시점을 **168**(API 26)로 적어 **두 표가 서로 달랐다.** `README` 문서 구조 표는 181을, 이 각주는 168을 인용해 **사중 불일치** 상태였다. 실측으로 대체한다.
>
> `[ORACLE-M-4]`가 남긴 교훈은 「요약이 실제와 불일치했다」였는데, **같은 일이 재발했다.** 재발을 막는 장치는 `§14`의 인벤토리와 `tests/test_testplan_sync.py`다 — 수치가 아니라 **파일 목록**을 CI가 강제한다.

### 11.2 우선순위

| 우선순위 | 테스트 | 시기 |
|---|---|---|
| P0 (MVP 차단) | UT-CII, UT-RATING, UT-CAP, UT-RNG, UT-HASH, UT-CONVERT, IT-STATE, DB-CHK | 2026.07 |
| P1 (기능 검증) | AT-VC, AT-SC, AT-SA, IT-ADOPT, IT-SNAP, IT-CSV, IT-IMPORT, IT-WX | 2026.08 |
| P2 (품질 강화) | AT-AS, PERF, A11Y, IT-AUDIT, IT-SIM-POLICY, IT-SOFTDEL, DB-SOFT | 2026.09~10 |

### 11.3 버전별 테스트 케이스 증감

| 항목 | v1.0 (초안) | v1.1 (Oracle 리뷰) | v1.2 (외부 리뷰) | 총 증감 |
|---|---|---|---|---|
| 단위 (Unit) | 42 | 51 | 55 | +13 |
| 통합 (Integration) | 19 | 37 | 37 | +18 |
| API | 24 | 26 | 26 | +2 |
| DB 제약 | 22 | 42 | 42 | +20 |
| 성능 | 4 | 4 | 4 | 0 |
| 접근성 | 4 | 4 | 4 | 0 |
| **합계** | **115** | **164** | **168** | **+53** |

> **이 표는 v1.2까지의 이력이다.** v1.5(2026-08-14) 이후 방향 전환으로 들어온 서브시스템은 이 증감표에 반영되지 않았다. 현재 규모는 위 `§11.1` 실측표를 따른다 (#394).

---

## 12. Oracle 리뷰 반영 (v1.1)

> Oracle 리뷰 (2026-07-03, session `ses_0d7a829d7ffeX2HRJ3BqtjLZ5s`)에서 도출된 21건의 피드백을 모두 반영하였다.

### 12.1 리뷰 요약

| 중요도 | 건수 | 반영 |
|---|---|---|
| Critical | 3 | 전부 반영 |
| Significant | 7 | 전부 반영 |
| Missing | 6 | 전부 반영 |
| Minor | 5 | 전부 반영 |
| **합계** | **21** | **21** |

### 12.2 상세 내역

| ID | 중요도 | 제목 | 조치 | 반영 위치 |
|---|---|---|---|---|
| ORACLE-C-1 | Critical | `lower_boundary` 산술 오류 (352 → 351) | 값 정정 | §1.2, §1.3 |
| ORACLE-C-2 | Critical | Monte Carlo 비교가 유효숫자가 아닌 소수점 자리 사용 | `math.isclose(rel_tol=)` 기반 재작성 | §9.2 |
| ORACLE-C-3 | Critical | Fixture 정밀도(9자리)와 bit-exact tolerance(0) 모순 | tolerance 구조를 integer/decimal/display 3단계로 분리 | §1.2, §9.1 |
| ORACLE-S-1 | Significant | PRD MT19937 vs TECH_SPEC PCG64DXSM 미문서화 | divergence 노트 추가 | §1.4 |
| ORACLE-S-2 | Significant | CSV injection `=`만 테스트, `@`/`+`/`-` 누락 | IT-CSV-005~007 추가 | §3.4 |
| ORACLE-S-3 | Significant | status×policy 매트릭스 1/8 무효 조합만 테스트 | DB-CHK-001a~001e 추가 | §5.1 |
| ORACLE-S-4 | Significant | 13+ DB CHECK 제약 미테스트 | DB-CHK-009~021 추가 | §5.1 |
| ORACLE-S-5 | Significant | annual_inclusion_policy 시뮬레이션 필터링 미테스트 | IT-SIM-POLICY-001~002 추가 | §3.8 |
| ORACLE-S-6 | Significant | Layer 1→2 변환 경계 미테스트 | UT-CONVERT-001~003 + §2.8 추가 | §2.8 |
| ORACLE-S-7 | Significant | capacity 정확한 경계(DWT=279,000) 미테스트 | UT-CAP-009~010 추가 | §2.3 |
| ORACLE-X-1 | Missing | 파라미터 가져오기: 파일만 있고 테스트 없음 | IT-IMPORT-001~005 + §3.5 추가 | §3.5 |
| ORACLE-X-2 | Missing | AC-F3-006 민감도 분석 테스트 미매핑 | AT-SA-001~002 + §4.5 추가, AC 매핑 | §4.5, §8.3 |
| ORACLE-X-3 | Missing | audit_log 테스트 없음 | IT-AUDIT-001~003 + §3.7 추가 | §3.7 |
| ORACLE-X-4 | Missing | 기상 fallback 체인 미테스트 | IT-WX-001~003 + §3.6 추가 | §3.6 |
| ORACLE-X-5 | Missing | 소프트 삭제 동작 미테스트 | IT-SOFTDEL-001~002, DB-SOFT-001~002 추가 | §3.9, §5.6 |
| ORACLE-X-6 | Missing | risk_level 임계값 미테스트 | UT-RISK-001~004 + §2.9 추가 | §2.9 |
| ORACLE-M-1 | Minor | UT-RNG-004는 lint check 성격 | ruff 규칙(`ban-api: numpy.random.default_rng`) 보강 | §2.4, §10.1 |
| ORACLE-M-2 | Minor | Fixture 2 E-case epsilon이 note와 불일치 | 값을 `5.953179271` (+ 0.000001)로 수정 | §1.3 |
| ORACLE-M-3 | Minor | 벤치마크 warm-up/통계 기준 미명시 | warm-up 10회, gc.disable() 명시 | §6 |
| ORACLE-M-4 | Minor | 테스트 수 요약 불일치 (38 vs 실제 42) | 실제 카운트로 정정 (164건) | §11.1 |
| ORACLE-M-5 | Minor | conftest.py/fixture loading 전략 없음 | §1.6 conftest 전략 추가 | §1.6 |

### 12.3 다운스트림 준비도 평가

| 항목 | 상태 |
|---|---|
| Fixture 값 정확성 | ✅ 모든 경계값 산술 검증 완료 |
| 비교 함수 신뢰성 | ✅ 유효숫자 기반 비교로 정정 |
| 테스트 커버리지 | ✅ 모든 PRD 수용 기준에 테스트 매핑 |
| DB 제약 커버리지 | ✅ CHECK/UNIQUE/FK/trigger/soft-delete 전 영역 |
| 개발자 착수 가능성 | ✅ 모든 테스트에 충분한 명세 제공 |

> **참고**: Canonical full-precision fixture 값(Decimal prec=30 출력)은 참조 구현체 구축 후 별도 생성 필요. 본 문서의 fixture 값은 9~10자리 유효숫자 기준이며, tolerance 설정과 일치함.
>
> **갱신 (#166)** — 위 「참고」는 v1.2 시점 기록이다. `§1.2`·`§1.3`의 값은 **정본값 30자리로 승격**됐고(확인 11), 참조 구현체의 성격·경로·조건은 `§1.2`의 `fixture_note`와 `TECH_SPEC §1.2.1`이 정의한다. `prec=30`은 **정본값 자릿수**를 가리키는 표현이며, 생성기의 작업 정밀도는 그보다 최소 20자리 크다.

---

## 13. Post-fix Oracle 리뷰 반영 (v1.2)

> 외부 리뷰 P0/P1/P2 일괄 수정(commit `547eeed`)에 대한 Oracle 리뷰(2026-07-04)에서 도출된 4건의 피드백을 반영하였다.

| ID | Severity | 이슈 | 수정 내용 | 위치 |
|---|---|---|---|---|
| EXT-F-001 | Significant | §1.4 ORACLE-S-1 노트가 PRD의 MT19937 참조를 "정정 예정"으로 남김 — PRD는 이미 정정 완료 | 노트를 "PCG64DXSM 확정, PRD v3.1에서도 정정 완료"로 교체 | §1.4 |
| EXT-F-002 | Significant | DB_SCHEMA §2.10에서 LNG 대형선 c=0 출처를 MEPC.364(79)로 인용 — CII G2와 무관 | MEPC.353(78) Table 1로 정정 | DB_SCHEMA §2.10 |
| F-003 | Minor | API_SPEC·DB_SCHEMA·TEST_PLAN 헤더 버전이 README(v1.2)와 불일치(v1.1) | 세 파일 헤더를 v1.2로 업데이트 | 각 파일 헤더 |
| F-004 | Minor | §11.1(168건) vs §11.3(164건) 테스트 수 불일치 | §11.3 표에 v1.2 컬럼 추가, 168건으로 통일 | §11.3 |

> **Oracle 종합 평가**: 15건 원본 수정(P0×6, P1×7, P2×3) 모두 정상 적용 확인. F-001·F-002 수정 후 즉시 구현 착수 가능.

---


---

## 14. 테스트 파일 인벤토리 [#394]

**이 절은 「어느 파일이 어느 절의 소관인가」를 한 곳에 모은다.** 케이스 하나하나를 옮겨 적는 자리가 아니다 — 케이스 규정은 `§2`~`§7`이 소유하고, 여기는 **파일과 절의 대응**만 담는다.

### 14.1 왜 이 절이 필요한가

2026-08-15 시점에 이 문서의 **파일 참조 정확도가 24%**였다(실제 61개 중 15개만 일치). 방향 전환으로 들어온 서브시스템 — not under way · YTD 산출 엔진 · 시뮬레이션 시계 · 운항 상태 — 이 **키워드 검색에서 0건**이었다.

원인은 문서를 안 고쳐서가 아니라 **어긋난 것이 보이지 않아서**다. 테스트 파일이 늘어도 이 문서는 아무 신호를 내지 않았다.

그래서 이 표와 함께 **`tests/test_testplan_sync.py`** 를 둔다. 새 테스트 파일을 만들고 이 표에 넣지 않으면 CI가 실패한다. **드리프트를 못 하게 만드는 것**이 이 절의 목적이다.

### 14.2 구현된 파일

> ⚠️ **「함수」는 `def test_` 개수다.** pytest가 실제로 수집하는 케이스는 파라미터화 때문에 이보다 많다 — 799 함수 → **1040 수집**(2026-08-17 실측).

| 파일 | 함수 | 대응 절 |
|---|---:|---|
| `test_account_self_service_db.py` | 18 | **§4.7 API · 인증** — 계정 관리(비밀번호 변경·표시 이름 변경·탈퇴). **응답이 아니라 DB를 다시 읽어** 확인한다 — detached 객체를 고치면 200이 나가는데 아무것도 안 쓰인다 (`#506`) |
| `test_annual_run_restrict_db.py` | 2 | §5 DB · 제약·마이그레이션 |
| `test_api_spec_endpoints_sync.py` | 5 | **§14 문서 동기화 · `API_SPEC §12` ↔ 실제 라우트** — 어긋남을 **세 방향**으로 본다: 「미구현」으로 적은 것이 정말 없는지 · 표시 없는 것이 정말 있는지 · **표에 없는 라우트가 코드에 있지는 않은지**. 마지막이 조용하다 — `#506`의 계정 관리 3종이 `§1.2` 본문에는 있고 `§12`에만 없어 **같은 문서가 자기와 어긋난** 채 두 판을 지났다. `app.routes`가 아니라 OpenAPI를 읽는다 (`#634`에서 0개를 검사하고 통과할 뻔했다) (`#591`) |
| `test_app_user_migration.py` | 2 | §5 DB · 제약·마이그레이션 |
| `test_audit_events_db.py` | 3 | §3 통합 · 감사 로그 |
| `test_audit_actions_db.py` | 5 | **§3.7 통합 · 감사 로그** — 항차 확정(`VOYAGE_CONFIRM`, 변경 전/후 포함) · 계산 실행의 해시 기록. **라우트를 지나서** 확인한다 (`#65`) |
| `test_auth_api.py` | 14 | **§4.7 인증 API** — 계정 존재 여부 비노출 · 가입 중복 고지 · 이메일 정규화 |
| `test_auth_failure_paths.py` | 6 | §4.7 API · 인증 |
| `test_auth_session.py` | 27 | §4.7 API · 인증 |
| `test_auth_wiring.py` | 10 | §4.7 API · 인증 |
| `test_calc_run_needs_recalc_db.py` | 6 | §5 DB · 제약·마이그레이션 |
| `test_compose_env_wiring.py` | 5 | **§5 인프라 · 배포 배선** — compose가 `.env`를 컨테이너에 주입하는지, `environment:`가 `DATABASE_URL`을 덮는지 (`#508`) |
| `test_data_export_db.py` | 21 | **§3.10 통합 · 자료 내보내기** — **왕복**(내보낸 파일을 그대로 다시 가져온다. 깨져도 오류가 아니라 「필수 컬럼이 없습니다」로만 보여 눈으로는 지켜지지 않는다) · 채울 수 없는 열을 두지 않는다(`attained_cii`·`rating`. **전제인 `calculation_run.voyage_id` 전부 NULL도 함께 단언** — 언젠가 채우면 이 단언이 깨지고 그때 다시 판단하게 된다) · BOM·CRLF · 수식 주입 4종 · 한 행 = 항차 × 연료 · `year`의 type별 의미 · HTTP 계약(라우트 등록·인증 뒤·`Content-Disposition`) (`#59`) |
| `test_db_target_guard.py` | 20 | **§5 인프라 · 테스트 격리** — 파괴적 롤백 테스트가 개발 DB를 치지 않게 한다. CI에서 그 테스트가 조용히 skip되는 것도 함께 막는다 (`#507`) |
| `test_issue_matrix.py` | 6 | **§14 운영 · 이슈 매트릭스 집계** — `#93`(추적용 메타 이슈)의 「현재 상태」 표를 손으로 갱신해 오다 **세 번 낡았다**. 세는 일을 `scripts/issue_matrix.py`로 옮기고 그 집계를 잠근다: **라벨 없는 이슈가 표에서 사라지지 않는다**(08-22에 겪은 상태 — 사라지면 「없는 것」이 된다) · 레이어를 둘 붙인 이슈를 **두 번 세지 않는다**(합계가 열린 이슈 수와 달라지면 그 차이를 설명할 수 없다) · 비어 있는 레이어도 행을 낸다. 네트워크를 타지 않는다 — `gh`를 부르는 자리는 `fetch` 하나이며 여기서 보지 않는다 (`#93`) |
| `test_response_contract_db.py` | 5 | **§4 API · 응답 계약** — 화면이 쓰는 엔드포인트 **16종의 필드 집합을 중첩까지** 대조한다(400키). 라우트 46개가 `dict`를 돌려줘 OpenAPI 응답 스키마가 0건이라 **응답이 조용히 바뀌어도 아무것도 잡지 않았다**(`#559`). **값이 아니라 키**를 본다 — 결함의 실제 모습이 이름 변경·필드 누락이고 그때는 오류가 아니라 화면에 `undefined`가 뜬다. **집합 동등**이라 필드를 더해도 실패한다. `data[]`가 비면 그 아래 키가 통째로 사라지므로 `/calculations`는 **먼저 계산을 하나 만들고** 조회한다 — 새 DB에서 0건임을 실측했다 (`#559`) |
| `test_scenario_example_sync.py` | 5 | **§14 문서 동기화 · `API_SPEC §5.1` 응답 예시 ↔ 실제 응답** — 문서에서 **요청과 응답을 둘 다 읽어** 실제로 실행하고 값을 대조한다. `#559`의 응답 계약이 **필드 집합**을 보는 것과 층이 다르다 — 이쪽은 「인쇄된 숫자가 맞는가」다. 값을 한 번 고치는 것으로 부족한 이유를 `#151` 본문이 적었다: **개별 수치만 고쳐도 다음 검토에서 다시 어긋난다.** 예시가 다시 밋밋해지는 것(셋 다 등급 E → margin 전부 null)도 함께 막는다 (`#151`) |
| `test_workflow_timeouts.py` | 4 | **§5 인프라 · CI 안정성** — 모든 워크플로 잡에 실행 상한이 있는지, `apt-get`이 `timeout`으로 감싸였는지 (`#533`) |
| `test_depcheck.py` | 13 | **§5 인프라 · 개발 환경** — dev 이미지에 없는 런타임 의존성을 기동 전에 잡는다. 저장소의 실제 `pyproject.toml`로도 돌아 파서가 현실과 어긋나면 잡힌다 (`#523`) |
| `test_uv_lock_sync.py` | 6 | **§5 인프라 · 의존성 선언** — `uv.lock`이 `pyproject.toml`과 어긋난 채 커밋되는 것을 막는다. 해석된 버전이 아니라 **선언**(이름·extras·범위)을 대조한다 (`#399`) |
| `test_warning_codes_sync.py` | 3 | **§5 인프라 · 문서 정합** — 경고 코드 정본 사슬(`TECH_SPEC §12.3` → `API_SPEC §1.6` → 화면)이 어긋나는 것을 막는다 (`#641`) |
| `test_required_checks_doc.py` | 3 | **§5 인프라 · 머지 게이트** — CI 잡이 `AGENTS §7` required check 표에 등재됐는지. 「잡은 도는데 아무것도 막지 않는」 상태를 막는다 (`#402`) |
| `test_mail_startup_guard.py` | 5 | **§5 인프라 · 기동 검증** — 프로덕션 메일 설정이 어긋나면 **기동 시점에** 막히는지. 종전에는 첫 발송에서 500이 났다 (`#524`) |
| `test_calculation_migrations.py` | 14 | §5 DB · 제약·마이그레이션 |
| `test_calculations_api.py` | 12 | §4 API · 선박·항차·계산 |
| `test_calculations_query_db.py` | 3 | §4 API · 선박·항차·계산 |
| `test_applicability.py` | 12 | **§2 단위 · CII 적용 대상 판정** — 「미해당」과 「GT가 없어 판정 불가」가 합쳐지지 않는지 · 임계값이 두 곳에 중복 정의되지 않았는지 (`#653`) |
| `test_capacity_rules.py` | 19 | §2 단위 · 계산 엔진 |
| `test_cii_engine.py` | 21 | §2 단위 · 계산 엔진 |
| `test_cii_history.py` | 7 | §4 API · 선박·항차·계산 |
| `test_fleet_summary.py` | 39 | **§4 API · 선대 요약** — 규제 트리거 판정 · `days_to_d` 산식·경계 6종 · KPI 집계 · 한 척 실패의 격리(`#419`) |
| `test_mail_link.py` | 5 | **§4.7 인증 API** — 메일 링크가 프론트엔드를 가리키는지 (`#429` 회귀) |
| `test_reports.py` | 54 | **§3.4~§3.5 리포트 렌더링** — CSV injection 방어 · BOM · 면책 · 한글 PDF · **`DESIGN_SYSTEM §4` 표시 형식**(자릿수·천단위 구분자·선종 표기·KST 시각). 문서가 직렬화 자릿수를 그대로 내보내 화면과 갈렸다 (`#584`) · **표시 문구 동기화**(위험도·경고·사유·항차 상태를 정본/화면과 대조 — `#631`) · **연료 표시 문구**(`fuelTypes.ts`와 대조 · `DB_SCHEMA §3.2` 8종 전수 · 모르는 코드는 코드를 그대로 — `#598`) |
| `test_reports_db.py` | 28 | **§4 API · 리포트 데이터 수집** — 진행 중 항차 제외 · 시나리오 인용 · 값 재계산 금지 · **문서 어디에도 UTC ISO가 남지 않는다**(`#646`) · **유종도 원문 코드가 남지 않는다**(`#598` — `#645`가 출처를 고칠 때 같은 표의 옆 칸이 남아 있었다) |
| `test_annual_simulation_api_db.py` | 14 | **§4 API · 기능③ 실행** — 스냅샷 격리 · 정책 필터링 · 분포 프로파일 기록 |
| `test_annual_simulation_read_db.py` | 24 | **§4 API · 기능③ 조회·재실행** — 조회가 다시 계산하지 않는지 · 스냅샷 항차 표현 · 재현 판정(파라미터 변경 409 / 재현 실패 500) (`#443`) · **선박 제원 스냅샷**(`#493` — 제원·capacity·선종을 고쳐도 재현이 흔들리지 않는다 · `037` 이전 실행은 사유를 밝히고 끊는다) |
| `test_simulation_parameter_db.py` | 8 | **§5.7 DB · seed 적재** — 분포 파라미터가 PRD 표와 일치하는지 · DB→엔진 변환 |
| `test_soft_delete_db.py` | 10 | **§3.9 통합 · §5.6 DB · 소프트 삭제** — 조회·집계에서 빠지는가 · 삭제된 IMO 자리를 비우는가(partial unique) · 행이 남아 있는가 (`#66`) |
| `test_annual_simulation.py` | 38 | **§2 단위 · 기능③ 시뮬레이터** — seed 재현성 · 확률 누적 · 방향 · `§12.8` 예외 |
| `test_cii_current_db.py` | 24 | **§4 API · 실시간 CII 3종 값** — 등급이 ⑴에만 붙는 것 · 진행분 반쪽 주입 금지 · `as_of` 재현성 |
| `test_not_underway_crud_db.py` | 32 | **§4 API · not under way 구간 CRUD** — 구간 겹침 금지 · CF snapshot · 소프트 삭제 · 집계 도달 |
| `test_parameters_api_db.py` | 15 | **§4 API · 규제 파라미터 조회** — 네 종류 조회 · 수치 문자열 직렬화(`§1.7`) · 값이 DB와 일치 · 모르는 선종은 오류 · `#370` 우회 제거 확인 (`#444`) |
| `test_auth_tokens.py` | 13 | **§4.7 인증 API** — 토큰 일회성·만료·용도 분리 · 재설정 시 세션 전량 무효화 |
| `test_password.py` | 15 | **§4.7 인증 API** — 해싱·정책·타이밍 방어 |
| `test_mail.py` | 16 | **§5 인프라 · 메일 발송** — 프로덕션 console 가드 · 백엔드 선택 · 발송 실패 래핑 · 템플릿 |
| `test_config.py` | 6 | §4 API · 공통·운영 |
| `test_csv_fixture.py` | 3 | §3 통합 · CSV |
| `test_voyage_import_db.py` | 23 | **§3.4 통합 · CSV 가져오기 · 커서 페이지네이션** — 수식 주입 4종 escape · 숫자 열은 거부 · 부분 성공(행 번호 보고) · 1000행 상한은 자르되 알린다 · dry-run (`#60`) · **커서 페이지네이션 3종** — 페이지 크기를 넘는 항차에 도달 · **발급한 커서를 서버가 읽는다** · 깨진 커서는 422 (`#627`) |
| `test_case_id_sync.py` | 7 | **§5 인프라 · 문서 정합** — 케이스 ID가 코드·면제 표 어디에도 없는 상태를 막는다 (`§14.5`). 범위 규칙 자체를 고정하는 3건 포함 — 인용은 커버리지 주장이 아니다 (`#498`) |
| `test_dashboard_seed.py` | 15 | **§5.7 DB · seed 적재** |
| `test_doc_cross_refs.py` | 4 | **§5 인프라 · 문서 정합** — `UIFLOW`·`DESIGN_SYSTEM`을 가리키는 절·화면 참조가 **실재하는지**, 그리고 `AGENTS §4.7` 표기 규칙(화면에 `§`를 붙이지 않는다)을 지키는지. `.md`와 `frontend/src` 주석을 함께 훑는다 (`#583`·`#602`) |
| `test_doc_version_sync.py` | 3 | **§5 인프라 · 문서 정합** — `README` ↔ 정본 헤더 버전 일치 (`AGENTS §4`) |
| `test_db_hardening_023.py` | 6 | §5 DB · 제약·마이그레이션 |
| `test_demo_up_script.py` | 22 | **§5 DB · 운영 스크립트** — 시연 기동 스크립트의 계약. `bash -n` 문법 · **JSON 값 추출**(파이썬 없이) · `--check`가 `.venv` 없이 도는 것 · 기동은 여전히 막히는 것. **CI가 이 스크립트를 실행하지 않아** `#616`의 `mktemp` 오류가 저장소에 들어와 있었다 (`#637`) |
| `test_demo_vessel_seed.py` | 17 | **§5.7 DB · seed 적재** — 합성 IMO의 체크섬 유효성 포함 (`#525`) · **제원 역산과 시드↔DB 어긋남 감지**(`#587` — 시드는 `ON CONFLICT DO NOTHING`이라 **기존 행을 갱신하지 않는다**. 시드에 값을 채워도 볼륨을 유지한 환경에는 들어가지 않고, 그 상태는 오류가 아니라 화면의 `—`로만 드러난다) |
| `test_demo_seed_counts.py` | 5 | **§5.7 DB · seed 적재** — 적재·삭제 **행 수 보고**가 사실인지 (재실행 0 · 비운 뒤 실제 건수 · 음수 없음, `#481`) |
| `test_demo_user_seed.py` | 11 | **§5.7 DB · seed 적재** — **시연 계정**의 계약 (`#692`). 시드가 계정을 만들지 않아 DB를 다시 만들 때마다 사람이 가입해야 했고, `#691` 이전의 테스트가 계정을 지우면 로그인 화면으로 들어갈 길이 없었다. 넷을 고정한다 — ⑴ 저장된 해시가 **그 비밀번호로 실제 검증**되는지(행 수만 보면 평문이 들어가도 통과한다) ⑵ 다시 돌려도 늘지 않고 **사람이 고친 값을 덮지 않는지** ⑶ **`APP_ENV=production`에서는 만들지 않는지**(고정 비밀번호가 프로덕션에 있으면 알려진 순간 누구나 들어온다) ⑷ 없으면 없다고 말하는지 — `is_deleted` 행을 「있다」로 세면 점검이 거짓말을 한다 |
| `test_dev_auth.py` | 5 | §4.7 API · 인증 |
| `test_docs_exposure.py` | 14 | **§4.7 API · 인증** — 프로덕션 OpenAPI 문서 노출 범위 (`AT-AUTH-014`) · **공개 경로 불변식**(`AT-AUTH-015`). 판정이 import 시점에 확정되므로 **하위 프로세스로 진짜 앱을 기동**해 응답 코드를 본다 (`#593` · `#648`) |
| `test_error_handlers.py` | 19 | §4 API · 공통·운영 |
| `test_error_handlers_116.py` | 18 | §4 API · 공통·운영 |
| `test_field_labels.py` | 7 | §4 API · 공통·운영 |
| `test_fuel_estimator.py` | 11 | §2 단위 · 추정·기상 |
| `test_fuel_type_content_hash.py` | 7 | **§5.7 DB · seed 적재** |
| `test_fuel_type_seed.py` | 4 | **§5.7 DB · seed 적재** |
| `test_hashing.py` | 22 | §2 단위 · 계산 엔진 · **기능③ `input_hash` 필드 목록**(`#493` — 기능③이 기능①의 목록을 써서 일곱 키 중 둘만 살아남고 있었다. 필드마다 따로 본다: 한 필드만 빠져도 조용히 통과한다) |
| `test_health.py` | 14 | §4 API · 공통·운영 |
| `test_imo_parser.py` | 10 | §2 단위 · 계산 엔진 |
| `test_layer1_context.py` | 7 | §2 단위 · 계산 엔진 |
| `test_layer1_fixtures.py` | 20 | §2 단위 · 계산 엔진 |
| `test_layer1_working_precision.py` | 7 | §2 단위 · 계산 엔진 |
| `test_layer_conversion.py` | 6 | §2 단위 · 계산 엔진 |
| `test_not_underway_migrations.py` | 15 | **§5.8 DB · not under way** |
| `test_orm_schema_sync.py` | 2 | §5 DB · 제약·마이그레이션 |
| `test_parameter_migrations.py` | 12 | §5 DB · 제약·마이그레이션 |
| `test_rate_limit.py` | 12 | §4 API · 공통·운영 |
| `test_rating_boundary.py` | 16 | §2 단위 · 계산 엔진 |
| `test_request_context.py` | 3 | §4 API · 공통·운영 |
| `test_risk_level.py` | 26 | §2 단위 · 계산 엔진 |
| `test_rng_reproducibility.py` | 4 | §2 단위 · 계산 엔진 |
| `test_scenario_compare_api.py` | 34 | §4 API · 기능② 시나리오 |
| `test_scenario_compare_db.py` | 2 | §4 API · 기능② 시나리오 |
| `test_scenario_adopt_db.py` | 17 | **§3 통합 · 시나리오 채택** — 계획값 반영 · 계산 무효화(항차 범위) · 계획 단계 항차만 허용 · 항차당 채택 하나 · `CREATE_NEW_VOYAGE` (`#58`) |
| `test_seed_data.py` | 17 | **§5.7 DB · seed 적재** |
| `test_seed_migration.py` | 8 | **§5.7 DB · seed 적재** |
| `test_simulation_clock.py` | 26 | **§2.11 단위 · 시뮬레이션 시계** |
| `test_testplan_sync.py` | 8 | **§14 인벤토리 동기화** |
| `test_tracked_files_are_text.py` | 2 | **§14 인벤토리 동기화** — 추적 소스에 NUL이 섞이면 git이 바이너리로 보아 **PR diff와 `grep`이 막힌다.** `.gitattributes`는 보이게 할 뿐 유입을 막지 못해 들어오는 자리에 신호를 둔다 (`#572` 발견 · `#575`) |
| `test_url_normalize.py` | 3 | §4 API · 공통·운영 |
| `test_vessel_position_state_migrations.py` | 12 | **§5.9 DB · 운항 상태·위치** |
| `test_vessels_api.py` | 62 | §4 API · 선박·항차·계산 |
| `test_voyage_cii_api.py` | 32 | §4 API · 선박·항차·계산 |
| `test_voyage_cii_service.py` | 18 | §4 API · 선박·항차·계산 |
| `test_voyage_delete_db.py` | 2 | §5 DB · 제약·마이그레이션 |
| `test_voyage_migrations.py` | 11 | §5 DB · 제약·마이그레이션 |
| `test_voyage_state_machine.py` | 17 | §4 API · 선박·항차·계산 |
| `test_voyage_transition_db.py` | 5 | **§3.1 통합 · 항차 상태 전이(DB 실동작)** — 정책 그룹 교차 · 조합 제약 · 실패 요청의 무영향 |
| `test_voyage_actuals_db.py` | 10 | **§4 API · 항차 실적 입력** — 계획값 보존 · CF snapshot · 상태 경계 · 유종 중복 |
| `test_voyages_api.py` | 25 | §4 API · 선박·항차·계산 (실적 입력 라우트 포함) |
| `test_weather_seed.py` | 5 | **§5.7 DB · seed 적재** |
| `test_weather_model.py` | 18 | **§2 단위 · 기상 보정 모델** — Townsin-Kwon 경험식(BN·Cβ 보간·적용 한계)과 SIMPLE_RULE(clamp·상한). **두 모델의 실패 규칙이 서로 새지 않는지** (`#61`) |
| `test_weather_client_db.py` | 16 | **§3 통합 · 기상 조회** — 두 엔드포인트 · 부분 실패 · 시각 선택 · 캐시 격자 · 스냅샷 저장 · 모델 디스패치 (`#61`) |
| `test_weather_fallback_db.py` | 12 | **§3 통합 · 기상 fallback** — `PRD §11.6` 네 칸(최신·6h·6~24h·없음) · 실험 모델 배지 · 「보정하지 않았다」를 조용히 넘기지 않는다 (`#62`) |
| `test_weather_simulation_migrations.py` | 12 | §5 DB · 제약·마이그레이션 |
| `test_ytd_cii_service_db.py` | 20 | **§2.10 단위 · YTD 산출 엔진** |
| `test_ytd_engine.py` | 26 | **§2.10 단위 · YTD 산출 엔진** |
| `test_zz_roundtrip.py` | 6 | §5 DB · 제약·마이그레이션 (데모 seed 분리 후 롤백 — `#451`) |

**합계 107개 파일 · 1426 함수 · 1732 수집.** (2026-08-23 실측)

### 14.3 계획분 — 아직 파일이 없는 것

아래는 `§2`~`§7`이 규정하나 **구현이 아직 없는** 테스트다. 대응 이슈가 열려 있다. **이 목록을 「틀린 참조」로 지우지 않는다** — 계획 문서가 계획을 담는 것은 정상이다.

| 파일 | 대응 이슈 |
|---|---|
| `test_annual_simulation_api.py` · `test_annual_simulation_snapshot.py` · `test_sensitivity_analysis_api.py` | #63 · #64 (기능③) |
| `test_weather_factor.py` · `test_weather_fallback.py` | #61 · #62 (기상 연동) |
| `test_scenario_adopt.py` | #58 (시나리오 채택) |
| `test_csv_security.py` | #59 · #60 (CSV) |
| `test_simulation_policy_filter.py` | #105 (스냅샷 정책) |
| `test_benchmarks.py` | #67 (성능 벤치마크) |
| `test_soft_delete.py` | #66 (소프트 삭제 통합) |
| `test_audit_log.py` | #65 (감사 로그) |

### 14.4 이름이 바뀐 것 — 참조 정정

구현은 됐으나 파일명이 달라져 이 문서의 참조가 끊겨 있던 것들이다.

| 종전 참조 | 실제 파일 |
|---|---|
| `test_imo_notation.py` | `test_imo_parser.py` |
| `test_error_format.py` | `test_error_handlers.py` · `test_error_handlers_116.py` |
| `test_constraints.py` · `test_triggers.py` · `test_immutable_tables.py` | `test_calculation_migrations.py` · `test_voyage_migrations.py` 등에 분산 |
| `test_calculation_query_api.py` | `test_calculations_query_db.py` |
| `test_parameter_import.py` | `test_parameter_migrations.py` |
| `test_voyage_state_transition.py` | `test_voyage_state_machine.py` |

### 14.5 케이스 ID의 소재 [#447]

**이 표가 없으면 「완료 기준 충족」을 확인할 방법이 없다.**

이슈의 완료 기준이 `AT-AS-001~004 통과`처럼 케이스 ID로 적힌다. 그런데 2026-08-17 시점에 정의된 **146개 ID 중 95개가 코드에 흔적이 없었다.** 그 ID를 단 테스트가 없으므로, 「통과했다」는 말이 무엇을 뜻하는지 확인할 수 없었다.

세 상태로 나눈다. **어느 것도 아닌 ID가 남으면 `tests/test_case_id_sync.py`가 CI에서 막는다.**

| 상태 | 뜻 |
|---|---|
| **대응됨** | 그 ID가 테스트 코드에 있다. 표에 적지 않는다 — 코드가 스스로 말한다 |
| **미대응** | 기능은 구현됐으나 그 케이스를 고정한 테스트가 아직 없다 |
| **계획분** | 기능 자체가 아직 없다. 대응 이슈가 열려 있다 |

#### 미대응 — 기능은 있으나 케이스가 비어 있다

| ID | 내용 | 왜 아직 없는가 |
|---|---|---|
| `UT-CAP-006` | LNG ≥ 100k: c=0 (고정 CII_ref) | 경계 케이스. `UT-CAP-004·005`가 LNG 하한만 덮는다 |
| `UT-CAP-008` | 벌크 300k에서 W 오차 = 0% | `UT-CAP-001·002`가 값은 덮으나 **오차 형태로는** 단언하지 않는다 |
| `UT-CLOCK-003` | `as_of` 미지정 시 동작 | `resolve_as_of`의 서버 확정 경로가 여러 서비스에 흩어져 있어 소유 파일이 정해지지 않았다 |
| `UT-CLOCK-004` | `as_of`가 `input_hash`에 들어가는가 | `#42` canonical 규약과의 정합. 해싱 테스트와 시계 테스트 어느 쪽 소관인지 미정 |
| `UT-YTD-006` | 계산 코어가 시각을 모른다 | `test_ytd_engine.py`에 **테스트 26건이 들어왔으나** 이 케이스 ID를 단 것은 없다. 종전 사유(「파일만 있고 테스트가 0건」)는 `#652` 시점에 이미 사실이 아니었다 |
| `AT-CQ-002` | 존재하지 않는 hash → 200 빈 배열 | 조회 테스트 3건이 일치·필터·인증만 덮는다 |
| `AT-VC-006`~`008` | 거리 누락 · 속도 < 1.0 · 없는 선박 | 검증 실패 3종. 스키마 레벨에서 막히는 것과 서비스에서 막히는 것이 섞여 있어 소유가 갈린다 |
| `AT-AS-002` | `rng_metadata` 포함 | 재현성 계약의 표시 축. `UT-RNG-*`가 생성기를 덮으나 **응답에 실리는지**는 비어 있다 |
| `IT-STATE-007` | 스냅샷 격리: 시뮬레이션 중 항차 수정 | `test_annual_simulation_api_db.py`가 스냅샷 불변을 덮으나 **전환 중 수정** 시나리오는 아니다 |

> **이 목록은 부채다.** 「구현은 됐는데 그 성질을 아무도 고정하지 않았다」는 뜻이다. `UT-YTD-006`의 사유는 `#652`에서 정정했다 — 파일은 더 이상 비어 있지 않고, **그 케이스만 없다.**

#### 계획분 — 기능이 아직 없다

| ID | 대응 이슈 |
|---|---|
| `IT-IMPORT-001`~`005` | `#444` (파라미터 import) |
| `IT-AUDIT-002` | `#444` (파라미터 import — **변경 경로가 생겨야 기록할 것이 생긴다**) |
| `AT-SA-001`~`002` | `#443` (민감도 분석 API — 엔진은 `#63`이 넣었다) |

### 14.6 프론트엔드 테스트의 관할

**이 문서는 Python 테스트를 관할한다.** 프론트엔드(`vitest` 331건)는 여기서 규정하지 않는다.

| 영역 | 관할 |
|---|---|
| Python (`tests/`) | 본 문서 `§2`~`§7` · `§14` |
| 프론트엔드 (`frontend/src/**/*.test.ts`) | 각 모듈 옆에 두고 `frontend/README.md`가 안내 |
| 화면 접근성 | 본 문서 `§7` (WCAG 2.1 AA · #68) |

경계를 여기 적어 두는 이유는 **방향 전환으로 화면이 4개 늘기 때문**이다(#351 · #356 · #357 · #362). 관할이 불분명하면 그 화면들의 테스트가 어느 문서 규정도 받지 않는 상태가 된다.

> 프론트엔드를 본 문서로 끌어오는 것은 **지금 결정하지 않는다.** `vitest`는 모듈 옆 co-location이 관례이고, 화면 4개가 들어온 뒤 실제 형태를 보고 판단하는 편이 낫다. 그때까지는 위 표가 경계다.

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준). 버전 번호 매핑은 커밋 메시지·헤더 기준의 추정을 포함한다.
>
> **2026-07-23까지가 사후 복원분이다.** 이후 항목은 변경 시점에 직접 기록하며, squash merge로 브랜치 커밋 해시가 재작성되므로 커밋 열에는 **PR 번호**를 적는다.

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-07-03 | `efdcdbf` | v1.0 초안 작성 |
| 2026-07-03 | `f065755` | v1.1: Oracle 리뷰 21건 반영 (164 케이스) |
| 2026-07-04 | `0f59999` | 외부 리뷰 P0/P1/P2 전체 반영 + AGENTS.md 추가 |
| 2026-07-04 | `af3b752` | Oracle 리뷰 4건 문서 정합성 수정 |
| 2026-07-04 | `ec1bf23` | Oracle 3차 리뷰 반영 (F-006~F-008, 168 케이스) → v1.2 |
| 2026-07-14 | `0173105` | annotation 라벨 번호 정규화 (5개 정본 일괄) |
| 2026-07-29 | `#142` | 변경이력 기록 방식 전환 주석 보완 |
| 2026-08-03 | `#169` | §1.3 각주의 경계값 판정 규칙 참조를 `PRD §9.4.1`에서 `§3.3.6`으로 정정 |
| 2026-08-04 | `#173` | §2.9 확률 위험도 경계값 TC ID 중복 정정 (`UT-RISK-005B` → `UT-RISK-006B`) |
| 2026-08-05 | `#180` | §9.1 `[ORACLE-C-3]` 재정정 — 절단 전제 소멸, 수치 비교 명시, `decimal_digits` → `decimal_places` 개명 (#166) |
| 2026-08-05 | `#180` | §1.2 Fixture 1 기대값 6개를 `PRD §13.1`과 일치시킴, `fixture_note` 자릿수 단위 표기 정정, `[ORACLE-C-1]` 폐기 (#166) |
| 2026-08-05 | `#180` | §1.3 Fixture 2 `base_required_cii`·경계 4개·케이스 5건 입력값을 §1.2와 함께 이동, `[ORACLE-M-2]` 갱신 (#166) |
| 2026-08-05 | `#180` | §2.8 `UT-CONVERT-002` 인용값을 정본값 30자리로, `[ORACLE-C-1b]` 산출 근거를 절단 없는 나눗셈으로 교체 (#166) |
| 2026-08-06 | `#180` | §1.2·§1.3 픽스처 값을 정본값 30자리로 승격 — 후행 0 제거(`4.982400`→`4.9824`), `ratio_to_required` 전정밀도 등재, `canonical_digits` 블록 신설, `fixture_note` 전면 교체(참조 구현체 성격·경로·`#45` 소관), §12.3 참고 갱신 (#166 · 확인 10 · 11) |
| 2026-08-06 | `#180` | 헤더 「상위 문서」의 낡은 버전 정정(`TECH_SPEC` v1.2→v1.4 · `DB_SCHEMA` v1.2→v1.3) · §1.7 정본값 생성기(`scripts/gen_fixtures.py`) 신설 — 독립성 조건 3개(서비스 import 금지·상수 원문 독립 전사·작업 정밀도), 실행·불변성 검사·합격 기준·작업 순서, `#45` 소관 명시 (#166 · 확인 10) |
| 2026-08-07 | `#194` | §9.1 비교 기준 상향 — 정본값 필드를 `publish_layer1_canonical()` 경유 정확 일치 비교로, `decimal_places`는 표시값 대조용 완화치로 강등. `tolerance.layer1_decimal`의 역할 변경 명시 (#179) |
| 2026-08-07 | `#196` | 헤더 「상위 문서」의 `PRD` 버전 참조 갱신 (v3.1 → v3.2) (#163) |
| 2026-08-07 | `#195` | §1.2 `fixture_note`에서 「이 파일과 생성기는 #45에서 만든다」 삭제 — 실제로 생성되어 사실과 달라짐 (#45) |
| 2026-08-07 | `#195` | v1.4: §1.3 케이스를 **기호 표기(`boundary` + `offset`)로 교체** — 적힌 확정값을 그대로 판정에 넣으면 올림된 경계(`upper`·`inferior`)에서 등급이 뒤집힌다. `input` 블록 신설(원경계 재계산 조건), `canonical_digits`에서 `cases[].attained_cii` 제거, 뒤집힘 표와 근거 소절 추가 (#46) |
| 2026-08-14 | `#328` | v1.5: §4.7 인증 API 케이스 신설(13건) — 기존 구현 파일들(`test_oidc`·`test_auth_api`·`test_auth_session`·`test_auth_wiring`·`test_auth_failure_paths`·`test_dev_auth`)의 케이스를 문서화. 헤더 「상위 문서」의 `API_SPEC` 버전 참조 갱신 (v1.2 → v1.4) (#279) |
| 2026-08-14 | `#342` | §1.4 Fixture 3 픽스처 실제 파일 2종 적재 — `annual_seed_12345_input.json`·`annual_seed_12345_expected.json`. expected.json 예시에 `fields_to_compare`(11개)·`fields_to_exclude`(5개) 키 추가로 실제 파일과 구조 일치 (#47) |
| 2026-08-17 | `#419` | `test_fleet_summary.py` 26 → **36함수** (선대 요약의 선박별 실패 격리) · 합계 실측 갱신(960함수·1207수집 → **970함수·1217수집**). **한 척의 실패가 선대 전체의 실패가 아니다**를 고정한다 — 제원이 빈 선박이 섞여 있어도 나머지가 정상 반환되는지, 그리고 「실적 없음」·「제원 미입력」·「기준값 없음」이 **서로 다른 사유로 구분되는지**다. 셋을 뭉치면 화면이 무엇을 하라고 말할 수 없다(항차 등록 vs 제원 입력 vs 운영자 문의). 반대 방향도 함께 박았다 — **연도 파라미터 부재는 여전히 요청 전체가 실패해야 한다.** 선박별로 잡으면 「전 선박이 파라미터 없음」이 되어 실제 원인이 선박 문제로 위장된다. **계산에 성공한 값을 뒤의 조회 실패가 버리지 않는 것**과 **제원으로 설명되지 않는 실패를 「제원 미비」로 적지 않는 것**도 함께 박았다 — 코드 리뷰에서 재현된 결함이다. 프론트엔드는 `fleetRules.test.ts`(+6)·`apiProvider.test.ts`(+3)에 사유별 안내 문구·매핑·**모르는 사유의 차단**을 고정했다 — §14 인벤토리는 **백엔드 pytest만** 세므로 합계는 바뀌지 않는다 (#419) |
| 2026-08-17 | `#64` | §14 인벤토리에 `test_annual_simulation_api_db.py`(14함수) 등재 · 합계 실측 갱신(946함수·1193수집 → **960함수·1207수집**). 계산은 `#63`이 검증하므로 여기서는 **조립과 격리**를 본다 — ⑴ **스냅샷 격리**(실행 뒤 원본을 고쳐도 스냅샷이 그대로인지. 깨지면 「그때 무슨 데이터로 돌렸나」에 답할 수 없다) ⑵ `annual_inclusion_policy` 필터링(`status`로 다시 판정하지 않는다) ⑶ **`parameters_used`에 분포가 실리는지**(빠지면 분포가 바뀐 뒤 결과는 달라지는데 해시는 같아진다) (#64) |
| 2026-08-17 | `#434` | §14 인벤토리에 `test_simulation_parameter_db.py`(8함수) 등재 · 합계 실측 갱신(938함수·1185수집 → **946함수·1193수집**). **DB 행이 종전 상수와 같은 프로파일로 변환되는지**를 고정한다 — 다르면 `#63` 병합 이후 시뮬레이션 결과가 조용히 바뀐다. `DELTA` 행이 배수로 잘못 옮겨지는 경우(`0.97` 자리에 `-1.0`이 들어가 분포가 뒤집힌다)도 함께 막았다 (#434) |
| 2026-08-17 | `#63` | §14 인벤토리에 `test_annual_simulation.py`(36함수) 등재 · 합계 실측 갱신(902함수·1149수집 → **938함수·1185수집**). 검증 범위를 **재현성·방향·예외** 셋으로 잡았다 — ⑴ 동일 seed → 등급별 확률 bit-exact(`AC-F3-002`. 깨지면 「이 seed로 다시 실행」이 거짓말이 된다) ⑵ **부호** (연료↑ → CII 악화. 뒤집혀도 값이 그럴듯해 드러나지 않는다) ⑶ `§12.8` 예외 8종. 추가로 **항차별 독립 표본추출**을 고정했다 — 합계에 배수를 한 번 곱하면 항차 40건과 1건이 같은 변동폭을 갖는다 (#63) |
| 2026-08-17 | `#431` | `test_fleet_summary.py` 20 → **26함수** (`days_to_d` 산식 정정) · 합계 실측 갱신(896함수·1143수집 → **902함수·1149수집**). **결함이 안 지켰던 성질을 직접 고정한다** — 「경계까지의 여유가 좁을수록 n일이 짧아진다」와 「값이 경과일수와 같지 않다」를 단언으로 박았다. 종전 식은 분자가 약분돼 입력과 무관하게 경과일수를 냈다. 추가로 **일정 강도 운항은 진입하지 않는다**(누적 CII는 평평하다)를 고정했다 — 이쪽이 모델의 본질이다 (#431) |
| 2026-08-17 | `#429` | §14 인벤토리에 `test_mail_link.py`(5함수) 등재 · 합계 실측 갱신(69파일·891함수·1138수집 → **70파일·896함수·1143수집**). **토큰이 아니라 링크 문자열 자체를 검증한다** — 이 결함이 숨어 있던 이유가 개발 환경에서 로그의 토큰만 꺼내 쓰면 플로우가 통과했기 때문이고, 링크를 실제로 누르는 경로를 아무도 밟지 않았다 (#429) |
| 2026-08-17 | `#362` | 프론트엔드 보고서 화면 — `reportRules.test.ts`(20) · `apiProvider.test.ts`(13) 신설. §14 인벤토리는 **백엔드 pytest 파일만** 세므로 합계는 바뀌지 않는다. 검증 범위는 **거부를 미리 알리는 것**이다 — 진행 중 항차는 서버가 422로 막지만 화면이 먼저 알려야 사용자가 다 고르고 나서 거부당하지 않는다. 미리보기 신선도 판정(선택이 바뀌면 지금 보이는 문서가 그 선택의 것이 아니다) · 서버가 준 파일명 사용(RFC 6266 `filename*` 우선) (#362) |
| 2026-08-17 | `#361` | §14 인벤토리에 `test_reports.py`(21) · `test_reports_db.py`(18) 등재 · 합계 실측 갱신(67파일·852함수·1093수집 → **69파일·891함수·1138수집**). **`§3.4~§3.5` CSV injection 케이스가 실제 코드로 내려왔다** — 시작 문자 6종 파라미터화 · `HYPERLINK` 유출 형태 · **음수 예외 없음**(예외를 만들면 그 예외로 payload가 빠져나간다) · 제목·머리글·값·각주 **모든 셀** 적용. PDF 검증은 바이트 길이가 아니라 **추출 텍스트**로 한다 — 폰트가 없으면 오류 없이 tofu가 되어 길이·상태·예외가 모두 정상이다. **CI에 `libpango`·`fonts-nanum` 설치 단계를 추가**했다(없으면 회귀를 CI가 못 잡는다) (#361) |
| 2026-08-17 | `#357` | 프론트엔드 실시간 CII 화면 — `realtimeRules.test.ts`(20) · `apiProvider.test.ts`(13) 신설. §14 인벤토리는 **백엔드 pytest 파일만** 세므로 합계는 바뀌지 않는다. 검증 범위는 **방향과 사유**다 — CII는 낮을수록 좋으므로 추세 부호를 뒤집으면 화면이 정반대를 말하고, 「정박 중」과 「정박이 등급을 밀고 있다」를 같게 그리면 사실과 다른 말이 된다 (#357) |
| 2026-08-17 | `#354` | §14 인벤토리에 `test_cii_current_db.py`(21함수) 등재 · 합계 실측 갱신(66파일·831함수·1072수집 → **67파일·852함수·1093수집**). 수치는 `#353`·`#368`이 이미 계산하므로 **조합에서 나는 결함**을 검증 범위로 잡았다 — 등급이 ⑵에 붙지 않는 것(`COR-1`) · **진행분을 반쪽만 넣지 않는 것**(거리만 넣으면 항해할수록 등급이 좋아진다) · `as_of` 재현성 · 못 낸 이유를 사유로 말하는 것 (#354) |
| 2026-08-17 | `#370` | §14 인벤토리에 `test_not_underway_crud_db.py`(32함수) 등재 · 합계 실측 갱신(65파일·799함수·1040수집 → **66파일·831함수·1072수집**). 이 이슈의 위험은 계산이 아니라 **쓰기 규칙**이므로 검증 범위를 구간 겹침 금지(열린 구간 = 무한대) · CF snapshot을 서버가 뜨는 것 · 소프트 삭제가 집계에서 즉시 빠지는 것 · **넣은 연료가 `#353` 집계에 실제로 도달하는 것**으로 잡았다 (#370) |
| 2026-08-17 | `#408` | §14 인벤토리에 `test_auth_tokens.py`(13함수) 등재 · 합계 실측 갱신(64파일·786함수·1027수집 → **65파일·799함수·1040수집**) (#408) |
| 2026-08-17 | `#414` | **§4.7 인증 API 절 재작성** — 구글 OIDC 제거로 대상이 사라진 AT-AUTH-001~004를 이메일·비밀번호 케이스로 교체(계정 존재 여부 비노출 · 정책 위반 · 소문자 정규화 · 비밀번호 미노출). **TC ID는 재번호하지 않고 같은 번호에 새 항목을 배치**했다 — 번호를 밀면 이슈·커밋의 기존 참조가 어긋난다. §14 인벤토리에서 `test_oidc.py` 제거하고 `test_password.py` 등재 · 합계 실측 갱신 (#414) |
| 2026-08-16 | `#407` | §14 인벤토리에 `test_mail.py`(16함수 · 파라미터화로 21건 수집) 등재 · 합계 실측 갱신(63파일·489함수·999수집 → **64파일·505함수·1020수집**) (#407) |
| 2026-08-16 | `#350` | §14 인벤토리에 `test_fleet_summary.py`(20함수) 등재 · 합계 실측 갱신(62파일·469함수·979수집 → **63파일·489함수·999수집**). 선대 요약 서비스의 검증 범위는 규제 트리거 판정(`PRD §3.3.7`) · `days_to_d` 경계 4종 · KPI 집계 일치다 (#350) |
| 2026-08-15 | `#398` | **v1.6 — 방향 전환 반영.** §2.10 YTD 산출 엔진 · §2.11 시뮬레이션 시계 · §5.7 seed 적재 · §5.8 not under way · §5.9 운항 상태·위치 5개 절 신설(케이스 ID 영역 코드 `UT-YTD`·`UT-CLOCK`·`DB-SEED`·`DB-NUW`·`DB-VSTATE` 확장) · **§14 테스트 파일 인벤토리 신설** — 파일 참조 정확도가 24%(61개 중 15개)였고 신규 서브시스템 키워드가 0건이던 상태를 해소 · §11.1을 실측(62파일·466함수·976수집)으로 대체 — 종전 §11.1(181)과 §11.3(168)이 서로 달랐고 README는 181을 인용해 사중 불일치였다 · 재발 방지로 `tests/test_testplan_sync.py` 추가(등재하지 않은 테스트 파일이 있으면 CI 실패) (#394) |
| 2026-08-15 | `#380` | §2.10 도입부의 `PRD §3.3.7` 참조를 `§3.3.8`로 정정 — 「등급이 붙는 값은 YTD 하나뿐」은 실시간 CII 절의 내용이며, `#386`이 `§3.3.7`을 선점해 참조가 끊겨 있었다 (#358) |
| 2026-08-17 | `#445` | 헤더 「상위 문서」의 낡은 버전 정정(`PRD` v3.2→v4.3 · `TECH_SPEC` v1.4→v1.6 · `API_SPEC` v1.4→v1.16 · `DB_SCHEMA` v1.3→v1.14). **내용은 `#398`(v1.6)이 이미 방향 전환을 반영했고 헤더만 전환 이전 판본에 멈춰 있었다** — `#180`이 같은 정정을 한 선례가 있다. §14 인벤토리에 `test_doc_version_sync.py`(3함수) 등재 · 합계 실측 갱신(73파일·970함수·1217수집 → **74파일·973함수·1220수집**). 이 파일은 `README` ↔ 정본 헤더 버전 일치를 강제한다 — `AGENTS §4`의 규칙이 이미 있었는데도 7종 중 6종이 어긋났으므로, 사람이 기억하는 방식은 실패한 것으로 본다 (#445) |
| 2026-08-17 | `#449` | `test_ytd_cii_service_db.py` 16 → **20함수** (대체 내역 기록) · 합계 실측 갱신(973함수·1220수집 → **977함수·1224수집**). **조용한 대체를 조용하지 않게 만든 것**을 고정한다 — ⑴ 거리 대체에 경고가 나가는지(종전에는 침묵했다. 거리는 CII의 분모다) ⑵ 어느 항차의 무엇이 대체됐는지가 남는지 ⑶ 연료와 거리가 **서로 다른 축**으로 기록되는지 ⑷ **실적이 온전하면 목록이 비는지**(있지도 않은 대체를 보고하지 않는다) (#449) |
| 2026-08-17 | `#440` | §14 인벤토리에 `test_voyage_actuals_db.py`(10함수) 등재 · `test_voyages_api.py` +5 (인벤토리 수치도 7 → **23**으로 실측 정정 — 종전 값이 낡아 있었다) · 합계 실측 갱신(74파일·977함수·1224수집 → **75파일·992함수·1239수집**). **계산이 아니라 보존과 경계를 본다** — ⑴ 실적을 넣어도 **계획값이 살아 있는지**(`PRD §8.4`. 잃으면 `#363` 계획 대비 실적 비교가 영영 불가능해진다) ⑵ 기존 행의 CF snapshot이 현재 CF로 덮이지 않는지(`#378`) ⑶ 상태 경계(`PLANNED`·`CONFIRMED` 거부) ⑷ **같은 유종 중복 거부** — 중복은 CO₂ 이중 산정이 되는데 값이 그럴듯해 드러나지 않는다 (#440) |
| 2026-08-17 | `#451` | `test_zz_roundtrip.py`의 018 계약 변경 — 「018 다운그레이드가 데모 선박 3행을 삭제한다」를 **「계산 이력이 있어도 롤백이 된다」**로 교체했다. 데모 데이터가 마이그레이션에서 분리되어(`db.demo_seed`) 018이 지울 것이 없어졌고, 확인해야 할 것도 「지웠는가」에서 **「막히지 않는가」**로 바뀌었다 — 그것이 이 이슈의 결함이었다. 롤백 전 `clear_demo()`를 부르는 이유도 테스트에 적었다: **데모 데이터는 스키마가 아니므로 스키마 롤백이 그것을 치우게 만들지 않는다.** 함수 수는 그대로(6) — 교체이지 추가가 아니다 (#451) |
| 2026-08-17 | `#460` | 헤더 「상위 문서」를 현행 대조 판본으로 갱신 (`AGENTS §4.4`) — §14 인벤토리가 `#440`(실적 입력 · API_SPEC v1.18) · `#451`(데모 seed 분리 · DB_SCHEMA v1.15) · `#445`(문서 버전 게이트)를 이미 담고 있다. **`#445`에서 맞춘 참조가 같은 날 안에 다시 낡은 것**이 §4.4를 「최신판 강제」가 아니라 「대조 시점」으로 정의한 계기다. 제목을 `TEST_PLAN — BlueLog`로 통일(`AGENTS §4.5`) (#460) |
| 2026-08-17 | `#447` | **§14.5 「케이스 ID의 소재」 신설** · §14 인벤토리에 `test_case_id_sync.py`(4함수) 등재 · 합계 실측 갱신(75파일·992함수·1239수집 → **76파일·996함수·1243수집**). 정의된 146개 중 **95개가 코드에 흔적이 없었다** — 이슈의 완료 기준이 이 ID로 적히는데(`#63`은 「AT-AS-001~004 통과」) 그 ID를 단 테스트가 없어 **충족 여부를 확인할 방법이 없었다.** 케이스 ID를 17개 파일에 붙여 **51 → 106건**으로 올리고, 남은 40건은 「미대응」(기능은 있으나 케이스가 빈 것 · 9건)과 「계획분」(기능이 아직 없는 것 · 31건)으로 **이유와 함께** 나눴다. 어느 것도 아닌 ID가 남으면 CI가 막는다. 붙이는 과정에서 **축약 ID(`UT-CAP-001 · 002`) 때문에 실제로는 덮여 있던 케이스 2건**이 드러났다 (#447) |
| 2026-08-18 | PR #499 | **v1.8 — §14.2에 `test_weather_model.py`(25함수)·`test_weather_client_db.py`(19함수) 등재** · §14.5 계획분의 기상 행에서 `#61`이 덮은 것을 빼고 나머지를 `#62`로 남겼다 · 합계 실측 갱신. `TECH_SPEC §3`·`§8`이 **두 모델의 실패 규칙을 반대로** 정하고 있다 — 경험식은 적용 범위 밖에서 **중단**하고(`§3.5`), SIMPLE_RULE은 **clamp**한다(`§8.2` `[ORACLE-M-2]`). 뒤는 fallback이라 예외를 던지면 fallback이 아니게 되기 때문이며, **한쪽 규칙이 다른 쪽으로 새는 것**을 케이스로 막았다. Beaufort Number의 짝수 반올림(`[ORACLE-M-1]`)도 함께 고정했다 — 전역 정책(`ROUND_HALF_UP`)과 다르지만 정본이 알고 허용한 값이라, 통일하면 정본과 달라진다 (#61) |
| 2026-08-18 | PR #500 | **§14.2에 `test_weather_fallback_db.py`(12함수) 등재** · §14.5 계획분의 기상 행을 삭제(`#62`가 나머지를 덮었다) · 합계 실측 갱신. `PRD §11.6`의 네 칸을 케이스로 고정했다. **「보정하지 않았다」를 조용히 넘기지 않는 것**이 요점이다 — 값은 언제나 나오므로 경고가 없으면 사용자는 보정된 값으로 읽는다. `WEATHER_STALE`을 6시간 이내에는 붙이지 않는다: `API_SPEC §1.6`이 조건을 「6~24시간」으로, 문구를 「오래된 기상 데이터를 사용 중입니다」로 확정했고 3시간 전 값에 그 문구를 붙이면 틀린 말이 된다 (#62) |
| 2026-08-18 | PR #494 | **v1.8 — §14.2에 `test_parameters_api_db.py`(15함수) 등재** · 합계 실측 갱신(76파일·996함수·1243수집 → **77파일·1011함수·1258수집**). `API_SPEC §7.1`~`§7.4` 파라미터 조회가 **명세만 있고 구현이 없어**, `#370` 때 연료 선택지를 **관계없는 엔드포인트의 `meta`에 실어 나르는 우회**가 들어가 있었다. 케이스로 고정한 것은 넷이다: ⑴ 네 종류가 모두 조회된다 ⑵ 수치가 문자열이다(`§1.7`) ⑶ **값이 DB와 같다**(문자열 여부만 보면 `"0"`을 돌려주는 구현도 통과한다) ⑷ 모르는 선종은 빈 배열이 아니라 오류다(오타와 「아직 없다」의 구분). 우회가 사라졌는지도 함께 본다 (#444) |
| 2026-08-18 | PR #492 | **v1.8 — §14.2에 `test_annual_simulation_read_db.py`(17함수) 등재** · 합계 실측 갱신(76파일·996함수·1243수집 → **77파일·1014함수·1261수집**). `API_SPEC §6.2`~`§6.4`(조회·스냅샷 항차·재실행)가 **명세만 있고 구현이 없었다** — 스냅샷을 남기는 목적이 조회인데(`TECH_SPEC §11.1`) 꺼내 볼 경로가 없었다. 케이스로 고정한 것은 셋이다: ⑴ **조회는 다시 계산하지 않는다**(규정 파라미터가 바뀐 뒤 조회해도 그때의 값) ⑵ 스냅샷 항차는 원본 수정을 따라가지 않는다 ⑶ 재현 판정은 **파라미터 변경(409)과 재현성 실패(500)를 가른다** — `rng_metadata`의 `numpy_version`·`platform`은 비교하지 않는다(`NEP 19`, 환경이 다르면 당연히 다르다). IT-SNAP-004가 처음으로 `reproduce` 경로에서 검증된다 (#443) |
| 2026-08-18 | PR #501 | **v1.8 — §14.2에 `test_scenario_adopt_db.py`(19함수) 등재** · §14.5 계획분에서 `IT-ADOPT-001~004` 삭제 · 합계 실측 갱신. 비교(`§5.1`)가 「무엇이 나은가」를 보여 주는 데서 끝나 **그 판단이 운항 계획에 닿지 않고 있었다.** 케이스로 고정한 것은 넷이다: ⑴ 계획값이 실제로 바뀐다 ⑵ **그 항차의** 계산이 무효화된다(선박 전체를 표시하면 표시가 무의미해진다) ⑶ 계획 단계 항차만 받는다(출항 뒤 계획을 갈아 끼우면 계획 대비 실적 비교의 기준선이 사라진다) ⑷ 채택은 항차당 하나다. `PRD §8.1.1`이 **상태에서 무엇을 고칠 수 있는지는 규정하지 않아** 그 빈칸을 보수적으로 메웠다 (#58) |
| 2026-08-18 | PR #496 | **v1.8 — §14.2에 `test_voyage_import_db.py`(23함수) 등재** · §14.5 계획분에서 `IT-CSV-002~007` 삭제(`#60`이 전부 덮었다) · 합계 실측 갱신. `IT-CSV-003`의 「1000행까지만 처리, 초과분 skip」을 그대로 따르되 **잘라 낸 행 수를 응답에 남기도록** 구현했다 — 조용히 자르면 1,001행을 올린 사용자가 마지막 행이 없어진 것을 모른다. `IT-CSV-002`(숫자 열의 수식 거부)와 `IT-CSV-001·005~007`(문자 열 escape)이 **한 파일에서 두 방향을 함께** 잠근다 (#60) |
| 2026-08-19 | `#506` | **v1.11 — §14.2에 `test_account_self_service_db.py`(18함수) 등재.** 인증이 가입에서 로그인까지만 있어 **로그인한 사용자가 자기 계정을 관리하는 경로가 없었다** — 비밀번호를 바꾸려면 로그아웃하고 재설정 메일을 받아야 했고, 개발 환경은 메일이 로그로만 나가 **로그를 볼 수 있는 사람만 바꿀 수 있었다.** 이 파일은 **응답이 아니라 DB를 다시 읽어** 검증한다 — 미들웨어가 넘긴 detached 객체를 고치고 commit하면 아무것도 안 쓰이는데 200이 나가기 때문이다(`#279`가 `logout`에서 겪은 것). 이메일 변경은 **경로 자체를 두지 않으며**(로그인 ID라 잘못 바꾸면 계정에 접근할 수 없다) 탈퇴 후 재가입으로 대신한다 — `idx_app_user_email`이 부분 유일 인덱스라 성립한다 (#506) |
| 2026-08-19 | `#498` | §14.2의 `test_case_id_sync.py` 행을 **4 → 7함수**로 갱신하고 합계를 실측으로 맞췄다(`+3`). `#498`(PR #517)이 범위 규칙 고정 테스트 3건을 더했으나, **같은 시점에 열려 있던 PR #518이 이 표와 합계 줄을 함께 고치고 있어** 충돌을 피하려고 문서를 건드리지 않았다. 두 PR이 머지된 뒤 여기서 한 번에 맞춘다 (#498) |
| 2026-08-19 | `#507` | **v1.10 — §14.2에 `test_db_target_guard.py`(13함수) 등재.** `test_zz_roundtrip.py`가 `alembic downgrade base`로 스키마를 드롭하는데 대상이 **개발 DB와 같은 데이터베이스**여서, `pytest`를 한 번 돌릴 때마다 `app_user`가 사라졌다 — 실제로 가입 계정이 그렇게 없어졌다. 이름이 `_test`로 끝나는 DB에서만 돌게 하고, **CI에서 그 테스트가 조용히 skip되는 것**도 함께 막는다(가드는 안전을 얻는 대신 검사를 잃을 위험을 만든다). CI는 이미 `cii_test`를 쓰므로 CI 동작은 그대로다 (#507) |
| 2026-08-19 | `#508` | **v1.9 — §14.2에 `test_compose_env_wiring.py`(5함수) 등재.** compose가 `.env`를 컨테이너에 **주입**하는지 고정한다. compose가 `.env`를 읽는 것은 파일 안의 `${VAR}` **치환용**이지 컨테이너 주입이 아니어서, `app` 서비스가 `DATABASE_URL` 하나만 받고 `MAIL_BACKEND`가 비어 **메일이 조용히 로그로만 나갔다.** 함께 **합계 함수 수를 실측으로 정정**했다 — 종전 `1147`은 §14.2 머리말이 정의한 `def test_` 개수(실측 `1133`)와도, 표의 함수 열 합(`906`)과도 맞지 않았다. 파일·수집 수는 각각 `+1`·`+5`가 이번 변경분이다 (#508) |
| 2026-08-19 | PR #551 | **v1.8 — §14.2에 `test_workflow_timeouts.py`(4함수) 등재** · 합계 실측 갱신(91파일·1189함수·1460수집 → **92파일·1195함수·1466수집**). 워크플로 잡에 실행 상한이 없어 `test` 잡이 `apt-get update`에서 멈춘 채 **5시간 59분**을 태운 일이 있었다(2026-08-18, 같은 날 5회). 멈춘 것 자체보다 **자동으로 끝나지 않은 것**이 문제였다 — 잡이 실패가 아니라 실행 중이라 알림도 오지 않았다. 상한은 한 번 넣으면 눈에 띄지 않는 값이라 새 잡에서 빠져도 **다음에 멈출 때까지** 드러나지 않으므로 테스트로 잠근다 (#533) |
| 2026-08-19 | PR #549 | **v1.8 — §14.2에 `test_depcheck.py`(13함수) 등재** · 합계 실측 갱신(90파일·1176함수·1447수집 → **91파일·1189함수·1460수집**). dev 이미지에 없는 런타임 의존성을 **기동 전에** 잡는 검사다. `#60`이 `python-multipart`를 추가한 뒤 재빌드하지 않은 환경에서 앱이 기동조차 못 했고, 그때 오류가 안내한 해법(`pip install`)은 컨테이너 안에서는 틀렸다. 파서가 현실과 어긋나는 것을 막기 위해 **저장소의 실제 `pyproject.toml`로도** 돌린다 (#523) |
| 2026-08-19 | PR #550 | **v1.8 — §14.2에 `test_uv_lock_sync.py`(6함수) 등재** · 합계 실측 갱신(91파일·1189함수·1460수집 → **92파일·1195함수·1466수집**). `uv.lock`이 `pyproject.toml`과 어긋난 채 커밋되는 것을 막는다. `pyjwt[crypto]`가 pyproject에만 추가되고 lock에는 6주간 반영되지 않아 `uv sync` 환경이 깨져 있었는데, CI는 `pip install -e ".[dev]"`를 쓰므로 초록이었다 — **있으면 신뢰받고, 신뢰하면 깨진다.** 해석된 버전이 아니라 **선언**(이름·extras·범위)을 대조한다 — 해석은 uv가 정할 몫이고 범위 안에서 달라지는 것이 정상이다 (#399) |
| 2026-08-19 | PR #552 | **v1.8 — §14.2에 `test_required_checks_doc.py`(3함수) 등재** · 합계 실측 갱신(92파일·1195함수·1466수집 → **93파일·1198함수·1469수집**). `#393`이 `docker` 잡을 만들고도 required check로 올리지 못해 **잡은 도는데 실패해도 머지가 막히지 않는** 상태가 됐고, 그 사실이 저장소 문서 어디에도 없어 확인할 방법이 없었다. PR 본문의 「후속 대응 필요」는 머지되면 목록에서 멀어진다. 실제 브랜치 보호 설정과 대조하지는 않는다 — 네트워크·토큰이 필요해 오프라인에서 깨진다. 여기서 잠그는 것은 **결정이 기록됐는가**다 (#402) |
| 2026-08-19 | PR #554 | **v1.8 — §14.2에 `test_mail_startup_guard.py`(5함수) 등재** · 합계 실측 갱신(93파일·1198함수·1469수집 → **94파일·1203함수·1474수집**). `mail/backends.py`와 `.env.example`이 「프로덕션에서 console이면 기동을 막는다」고 적었으나 `get_mailer()`가 `lru_cache`로 **라우트 안에서** 처음 불려 가드가 첫 발송 시도에서야 돌았다. 앱은 정상 기동하고(health 200) 사용자가 「비밀번호를 잊었어요」를 누를 때 500이 났다 — 드러나는 시점이 「배포 직후」가 아니라 「첫 사용자가 계정을 잃을 뻔한 순간」이었다. 규칙 자체는 `test_mail.py`가 이미 검증하므로 여기서는 **기동 경로에 연결됐는가**만 본다 (#524) |
| 2026-08-19 | PR #555 | **v1.8 — `test_demo_vessel_seed.py` 9 → 11함수**(합성 IMO 체크섬) · 합계 실측 갱신(94파일·1203함수·1474수집 → **94파일·1205함수·1476수집**). 데모 4척 중 합성 2척이 IMO 체크섬을 만족하지 않았다 — 실수가 아니라 고려 대상이 아니었던 것이다(`018` 주석의 목적은 「실선과 충돌 방지」였고 그건 지켜졌다). 0으로 시작하면서 체크섬이 맞는 7자리가 10만 개 있어 **두 조건을 함께 만족할 수 있다.** 검산 함수 자신을 먼저 잠근다 — 틀리면 본 검사가 조용히 통과한다. 파일 수는 그대로(신규 아님) (#525) |
| 2026-08-18 | PR #497 | **v1.8 — §14.2에 `test_audit_actions_db.py`(5함수) 등재** · §14.5 계획분의 `IT-AUDIT-001~003`을 **`IT-AUDIT-002`만 남기고 `#444`로 이관** · 합계 실측 갱신. `TECH_SPEC §13.1`이 지목한 기록 대상 셋 중 **항차 확정은 기록 자체가 없었고, 계산 실행은 기록은 있는데 테스트가 없었다**(`#277`이 넣은 배선이 지워져도 아무것도 실패하지 않는 상태였다). 파라미터 변경(`IT-AUDIT-002`)은 **변경 경로가 아직 없어**(`§7.5` import 미구현) 기록할 사건이 생기지 않으므로 그 이슈로 옮겼다. 확인은 **라우트를 지나서** 한다 — 서비스만 부르면 「기록하는 함수가 있다」까지만 확인된다 (#65) |
| 2026-08-18 | PR #495 | **v1.8 — §14.2에 `test_soft_delete_db.py`(10함수) 등재** · §14.5 계획분에서 `IT-SOFTDEL-001~002` 삭제 · 합계 실측 갱신(76파일·996함수·1243수집 → **77파일·1006함수·1253수집**). 소프트 삭제는 **두 가지가 동시에 성립해야 하는데** 그 어느 쪽도 고정돼 있지 않았다(`ORACLE-X-5`): 조회·집계에서 빠지는가, 그리고 **삭제된 IMO의 자리를 비우는가**. 뒤쪽이 특히 조용하다 — 파셜 인덱스의 `WHERE is_deleted = false`가 빠져도 평소에는 아무 일도 없고 **같은 배를 다시 등록하려는 순간에만** 드러난다. 서비스 경로와 인덱스를 **따로** 단언해 어느 쪽이 허용하는지 구분했고, 「표시일 뿐 지워지지 않는다」도 함께 고정했다 — 없으면 hard delete로 바꿔도 나머지가 통과한다 (#66) |
| 2026-08-17 | PR #491 | **v1.8 — §14.2에 `test_demo_seed_counts.py`(5함수) 등재** · 합계 실측 갱신(76파일·996함수·1243수집 → **77파일·1001함수·1248수집**). 데모 데이터 적재가 **몇 행을 넣었는지 보고하지 못하고 있었다** — `rowcount`를 그대로 써서 executemany 경로에서 `-1`이 나왔고, 단일 행 INSERT의 정상값과 합해져 **「0행」이라는 그럴듯한 거짓**이 되기도 했다. 적재 결과를 눈으로 확인하는 유일한 출력이라 **첫 실행과 재실행이 구분되지 않았다.** 「음수가 아니다 · 재실행은 0 · 비운 뒤에는 실제 건수」 셋을 케이스로 고정했다 (#481) |
| 2026-08-21 | `#604` | §14 인벤토리에 `test_doc_cross_refs.py`(3함수) 등재 · 합계 실측 갱신(95파일·1216함수·1495수집 → **96파일·1222함수·1501수집**). 이 파일은 `UIFLOW`·`DESIGN_SYSTEM`을 가리키는 참조가 **실재하는지**를 강제한다 — `test_doc_version_sync.py`가 버전 드리프트를 잡는 것과 같은 자리이나, 이번 결함은 드리프트가 아니라 **처음부터 없는 절을 가리켜 쓴 것**이라 그 가드로는 잡히지 않았다. `.md`뿐 아니라 `frontend/src` 주석까지 훑는다 — `screens.ts`도 같은 끊긴 참조를 쓰고 있었다. 함께 **헤더에 두 개였던 `최종 수정일` 행을 하나로 합쳤다**(2026-08-18 · 2026-08-17이 나란히 있었다). `AGENTS §4.3`상 「소규모 행 추가·오기 정정」이므로 버전은 올리지 않는다 (#583) |
| 2026-08-21 | `#606` | `test_doc_cross_refs.py` 3 → **4함수** — `AGENTS §4.7` 표기 규칙 강제를 추가했다. 화면 번호에 `§`를 붙이면 **화면 번호·`§16` 표의 행 번호·없는 절이 한 모양**이 되어 실재 여부를 판정할 수 없다. 합계 실측 갱신(1222함수·1501수집 → **1223함수·1502수집**) (#602) |
| 2026-08-22 | `#641` | §14 인벤토리에 `test_warning_codes_sync.py`(3함수) 등재 · `test_annual_simulation.py` 36 → **38함수**(`#630`) · 합계 실측 갱신(96파일·1223함수·1502수집 → **97파일·1230함수·1509수집**). `README` 문서 표의 수치가 **89파일·1172함수·1443수집**으로 사흘 낡아 있던 것도 함께 맞췄다 — `test_doc_version_sync`는 **버전만 보고 수치는 보지 않는다** (#641) |
| 2026-08-22 | `#631` | `test_reports.py` 33 → **44함수** — 인벤토리 수치가 **이미 5함수 낡아 있었고**(#584 이후 갱신되지 않았다) 여기에 표시 문구 동기화 6종을 더했다. 위험도·경고는 **정본**(`DESIGN_SYSTEM §2.5` 🔒 · `API_SPEC §1.6`)과, 연말 예상 사유·항차 상태·집계 정책은 **화면**과 대조한다 — `AGENTS §4.6`이 정본 문구와 표시 문구를 나누므로 대조 상대가 갈린다. 합계 실측 갱신(1230함수·1509수집 → **1236함수·1515수집**) (#631) |
| 2026-08-22 | `#593` | §4.7에 **`AT-AUTH-014`** 신설(프로덕션 OpenAPI 문서 노출) · §14 인벤토리에 `test_docs_exposure.py`(9함수) 등재 · 합계 실측 갱신(97파일·1236함수·1515수집 → **98파일·1245함수·1524수집**). 기대값을 **404가 아니라 401**로 적은 것이 요점이다 — 라우트만 끄면 `/docs`는 404이고 다른 미등재 경로는 401이라, **그 차이 자체가 「여기에 무언가 있다」는 신호**가 된다. 판정이 import 시점에 확정돼 같은 프로세스에서 환경을 바꿔 다시 만들 수 없으므로 **하위 프로세스로 진짜 앱을 기동**한다 — 순수 함수만 보면 「값이 실제 앱에 닿았다」가 빠진다(`#318`의 논거) (#593) |
| 2026-08-22 | `#627` | `test_voyage_import_db.py`에 **커서 페이지네이션 3종** 추가 · 합계 실측 갱신(1245함수·1524수집 → **1253함수·1532수집**). **DB에 붙는 테스트여야 했다** — 결함이 파이썬 오류가 아니라 SQL 타입 불일치였다(커서의 `created_at`이 `str`이라 `timestamptz`와 비교되지 않아 `operator does not exist`로 500). 서버가 **자기가 발급한 커서를 읽지 못하는** 상태였고, 화면 두 곳이 `meta.next_cursor`를 버려 와서 아무도 밟지 않았다. ⚠️ 이 파일의 기재 수치가 **문서 23 / 실측 20**으로 3 높아 있었다 — `#652`가 지적한 그 구멍이며, 합계도 5 낮았다. 함께 맞췄다 (#627) |
| 2026-08-22 | `#648` | §4.7에 **`AT-AUTH-015`** 신설(공개 경로 불변식) · `test_docs_exposure.py` 9 → **14함수** · 합계 실측 갱신(1253함수·1532수집 → **1258함수·1537수집**). `PUBLIC_PATHS`의 경로에 라우트가 없으면 **그 경로만 404**가 되어 신호가 남는다 — 프로덕션 dev-login이 그랬고, `#593`이 `/docs`에서 없앤 것과 같은 부류다. 함께 **접두사 없는 사본 8개를 제거**했다: `is_public_path()` 주석이 「실제 요청 경로는 항상 `/api/v1` prefix를 달고 나온다」고 적고 있어 **영원히 매치되지 않는 항목**이었다 (#648) |
| 2026-08-22 | `#651` | `test_rate_limit.py` 9 → **12함수**(공용 카운터 격리 3종) · 합계 실측 갱신(1258함수·1537수집 → **1261함수·1540수집**). `main.app`이 모듈 레벨 객체라 분당 카운터(300/분)를 **pytest 프로세스 전체가 공유**했고, 고정 윈도라 **실패 여부가 전체 실행 속도에 달려 있었다** — 로컬 3분대는 통과하고 CI 1분대는 429가 났다. `#593`·`#648`이 각각 한 번씩 이것으로 막혔고 두 번 다 해당 파일에서만 우회했다. `conftest.py`의 autouse 픽스처가 매 테스트마다 **같은 한도의 새 인스턴스**를 끼운다 — 한도 자체는 살아 있어 한 테스트 안에서 넘기면 여전히 429다 (#651) |
| 2026-08-22 | `#652` | **§14.2 함수 수·합계를 테스트가 검사한다.** 종전 가드 4종은 **파일 목록만** 봤고, 그 사이 함수 수 열이 낡았다 — 가드를 켜자마자 **16개 파일이 어긋나 있었다.** 그중 7개는 **`0`**으로 적혀 있었는데 실제로는 12~62개다(`test_vessels_api.py` 0 → **62** · `test_scenario_compare_api.py` 0 → **34** · `test_voyage_cii_api.py` 0 → **32** · `test_auth_session.py` 0 → **27** · `test_ytd_engine.py` 0 → **26** · `test_error_handlers_116.py` 0 → **18** · `test_voyage_cii_service.py` 0 → **16**). 나머지 9개는 양방향으로 어긋났다. 합계 실측 갱신(1261함수 → **1265함수** · 1540수집 → **1544수집**). **수집 수는 검사하지 않는다** — 파라미터라이즈 때문에 실행해야 알 수 있고, 그 하나를 위해 전 테스트를 수집하면 가드가 본체보다 오래 걸린다. §14.5 `UT-YTD-006`의 사유도 정정했다 — 「파일만 있고 테스트가 0건」이 이미 사실이 아니었다 (#652) |
| 2026-08-22 | `#646` | `test_reports_db.py` 18 → **21함수**(시각 표기 3종) · 합계 실측 갱신(1265함수·1544수집 → **1268함수·1547수집**). `#584`가 `meta`의 시각만 KST로 고치고 **본문 행 둘을 두고 갔다** — 같은 문서 안에서 `2026-08-22 16:26:33 KST`와 `2026-02-10T07:00:00+00:00`이 섞였다. 행 이름을 열거하지 않고 **문서 전체를 훑는다** — 시각이 하나 더 늘어도 그대로 걸린다 (#646) |
| 2026-08-22 | `#637` | §14 인벤토리에 `test_demo_up_script.py`(6함수) 등재 · 합계 실측 갱신(98파일·1268함수·1547수집 → **99파일·1274함수·1557수집**). `demo_up.sh`가 `.venv`가 없으면 **1단계보다 앞에서 `exit 1`** 해 Docker만 있는 환경에서는 `--check`조차 할 수 없었다. 점검 갈래를 열고 6단계 JSON 파싱을 **파이썬에서 `sed`로** 바꿨다. ⚠️ **CI가 이 스크립트를 실행하지 않는다** — `#616`의 `mktemp` 오류가 그래서 들어왔다. 실행 환경 없이 확인할 수 있는 것만 잠갔다 (#637) |
| 2026-08-22 | `#653` | §14 인벤토리에 `test_applicability.py`(12) 등재 · `test_fleet_summary.py` 36 → **39함수** · `test_reports_db.py` 21 → **25함수** · `test_voyage_cii_service.py` 16 → **18함수** · 합계 실측 갱신(99파일·1274함수·1557수집 → **100파일·1295함수·1578수집**). **고정하는 것은 「미해당」과 「GT가 없어 판정 불가」가 합쳐지지 않는다**이다 — 둘을 뭉치면 총톤수를 넣지 않은 사용자가 「이 배는 규제 대상이 아니다」로 읽는다. 선대 응답이 두 상태를 가를 수 있는지, 리포트 2종이 그 사실을 meta와 경고 양쪽에 남기는지, 적용 대상인 선박에는 **경고를 붙이지 않는지**(정상 상태를 덮으면 진짜 예외가 묻힌다)를 함께 박았다. 임계값이 `services/vessel.py`·`services/voyage_cii.py`에 따로 적혀 있던 것도 단언으로 잠갔다. 프론트엔드는 `ApplicabilityBadge.test.tsx`(9)에 3상태·임계값 비노출·접근성 라벨을 고정했다 — §14 인벤토리는 **백엔드 pytest만** 세므로 합계에는 들어가지 않는다 (#653) |
| 2026-08-22 | `#634` | `test_auth_failure_paths.py` 4 → **6함수** · `test_auth_wiring.py` 7 → **10함수** · 합계 실측 갱신(1295함수·1578수집 → **1300함수·1583수집**). **개별 라우트를 열거하지 않는 불변식을 넣었다** — `routes/*.py`를 AST로 읽어 「세션이 필요한 상태 변경 라우트에 `require_csrf`가 걸렸는가」를 전수 검사한다. 열거하면 새 라우트가 목록에 없어 검사되지 않는데, `#527`이 그 형태로 6개를 놓쳤다. **가드가 조용해지는 것도 함께 막는다** — 처음 구현은 `app.routes`를 돌았고 이 FastAPI 버전이 라우트를 래퍼에 감춰 두어 **0개를 검사하고 통과**했다. 「검사 대상이 20개 이상」·「`require_csrf`를 하나라도 찾았다」 단언이 그것을 잡았다. 반대 방향(검증이 빠진 것은 전부 공개 경로인가)도 함께 박았다 — 한쪽만 보면 전부 공개로 만들어 통과시킬 수 있다. 동작 쪽은 CSRF 헤더 없는 로그아웃이 403이면서 **세션이 살아 있는지**와, 세션 없는 로그아웃이 401인지를 고정한다 (#634) |
| 2026-08-22 | `#649` | `test_simulation_clock.py` 20 → **26함수** · `test_cii_current_db.py` 21 → **24함수** · 합계 실측 갱신(1300함수·1583수집 → **1309함수·1592수집**). **고정하는 것은 「도착 예정일을 지나도 누적이 자라지 않는다」**이다 — 종전에는 상한이 없어 출항 90일 뒤면 계획의 7배가 됐다. 자르기만 하는 것으로는 부족해 **잘렸다는 사실이 응답에 실리는지**도 함께 박았다(자르고 알리지 않으면 값이 멈춘 것을 「항차가 끝났나」로 읽는다). 반대 방향 3종도 넣었다 — 실적이 있으면 계획이 아니라 실적으로 자르는지(계획으로 자르면 실제 항해 구간을 버린다), 예정일 전에는 종전과 같은지, 예정일이 없는 항차에 없는 상한을 만들지 않는지. 잘린 값이 **여전히 시뮬레이션 값인지**도 잠갔다 — 플래그를 내리면 계획이 곧 실적이 된다 (#649) |
| 2026-08-22 | `#650` | `test_dashboard_seed.py` 12 → **15함수** · 합계 실측 갱신(1309함수·1592수집 → **1312함수·1595수집**). **세는 방식을 바꾼 것이 핵심이다** — 종전 가드는 진행 중 정박 구간을 `count(*) == 2`로만 봤고, 그래서 로로 여객선이 `IN_PORT`로 표시되면서 **뒷받침하는 구간이 없는 상태**를 잡지 못했다. 이제 `period_type` 집합으로 세고, 정박 중인 모든 시드 선박에 대해 「표시 상태 == 진행 중 구간 종류」를 대조한다. 완료 기준은 시드 유무가 아니라 **분자에 들어가는가**이므로 YTD 서비스를 실제로 돌려 `not_underway_period_count == 1`·`not_underway_co2_g > 0`을 확인한다 — 구간만 있고 연료가 없으면 「정박이 지속되면 등급이 나빠진다」가 성립하지 않는다. 가드 4종이 종전 시드에서 실제로 실패하는지 되돌려 확인했다 (#650) |
| 2026-08-22 | `#645` | `test_reports.py` 44 → **46함수** · `test_reports_db.py` 25 → **27함수** · 합계 실측 갱신(1312함수·1595수집 → **1316함수·1599수집**). **코드 집합을 전사하지 않는다** — `voyage_fuel_use`의 `chk_fuel_source` CHECK 제약을 SQLAlchemy 메타데이터에서 읽어 대조한다. 기대값을 테스트에 다시 적으면 새 출처가 늘 때 두 곳을 고쳐야 하고, 한쪽만 고치면 리포트가 원문 코드를 낸다. 문서 쪽은 열 이름을 짚지 않고 **문서 전체를 훑어** 원문 코드가 남지 않았는지 본다 — 출처가 다른 절에 하나 더 실려도 걸린다. 반대 방향도 함께 박았다: 「원문 코드가 없다」만 보면 **열을 통째로 빼도 통과**하므로 한국어 표기가 실제로 실렸는지도 확인한다. `DESIGN_SYSTEM §11`(🔒)이 출처 표기를 요구하기 때문이다. 화면에 이 값이 생기면 분류를 다시 정해야 하므로 그 사실도 가드로 남겼다 (#645) |
| 2026-08-22 | `#636` | `test_voyages_api.py` 23 → **25함수** · 합계 실측 갱신(1316함수·1599수집 → **1318함수·1601수집**). **폼을 다연료로 넓히면서 처음으로 도달 가능해진 경로를 함께 잠갔다** — `create_voyage`에 중복 `fuel_type` 가드가 없어 `idx_fuel_use_unique` 위반이 `IntegrityError`로 올라와 **500**이 됐다(실제로 돌려 확인). 실적 갱신(`_upsert_fuel_actuals`)은 같은 가드를 갖고 있었고 생성 경로만 빠져 있었는데, **화면이 한 종만 보내 아무도 밟지 않았다.** 정상 경로(서로 다른 유종 2줄이 201로 들어간다)도 함께 박았다 — 거부만 검사하면 **전부 거부해도 통과한다.** 프론트엔드는 `voyageRules.test.ts`(+5)·`apiProvider.test.ts`(+3)에 줄별 오류 키 분리·중복 줄 지목·배열 직렬화를 고정했다 — §14 인벤토리는 **백엔드 pytest만** 세므로 합계에는 들어가지 않는다 (#636) |
| 2026-08-23 | `#589` | 헤더 「상위 문서」의 `API_SPEC`을 v1.18 → **v1.20**으로 갱신. v1.19(CSV 가져오기)·v1.20(CII 적용 대상 표시)에 대응하는 테스트가 `§14.2` 인벤토리에 이미 등재돼 있다 — `test_voyage_import_db.py` · `test_applicability.py`(`#653`에서 신설) · `test_fleet_summary.py`(선대 응답 필드 2종). `§4.3`상 헤더 정정이라 버전은 올리지 않는다 (#589) |
| 2026-08-23 | `#59` | **v1.12 — §3.10 자료 내보내기 신설(`IT-EXPORT-001~008`)** · §14 인벤토리에 `test_data_export_db.py`(21) 등재 · 합계 실측 갱신(100파일·1318함수·1601수집 → **101파일·1339함수·1625수집**). ⚠️ **`#59`의 완료 기준이 인용한 `IT-CSV-001~004`는 내보내기 케이스가 아니었다** — 「row skip」·「1001행」·「정상 파싱」은 전부 파일을 **읽는** 쪽 시나리오이고 `#60`이 이미 덮었다(`PR #496` 행 참조). 착수 전에 이미 통과해 있던 기준이라 그대로 두면 무엇도 검증하지 않는다. 새 기준의 중심은 **왕복**이다 — 내보낸 파일을 그대로 다시 가져올 수 있는지는 깨져도 오류가 나지 않고 「필수 컬럼이 없습니다」로만 보이므로, 사람이 눈으로 열을 대조하는 것으로는 지켜지지 않는다. 두 번째는 **채울 수 없는 열을 만들지 않는다**이며, 그 판단의 전제(`calculation_run.voyage_id`가 전부 NULL)를 **직접 단언**해 조건이 바뀌면 재판단하게 했다 (#59) |
| 2026-08-23 | `#591` | §14 인벤토리에 `test_api_spec_endpoints_sync.py`(5) 등재 · 합계 실측 갱신(101파일·1339함수·1625수집 → **102파일·1344함수·1630수집**). `#591`이 **손으로** 한 51행 대조를 CI가 매번 하게 한다. 잠그는 것은 **어긋남이 양방향**이라는 사실이다 — 문서에만 있는 3종(`weather` 2종·`parameters/import`)뿐 아니라 **코드에만 있는 3종**(`#506` 계정 관리)이 함께 나왔고, 뒤엣것은 `§1.2` 본문에 있어 아무도 알아채지 못한 채 요약표만 낡아 있었다. 「미구현」을 문서에만 적으면 **구현되는 날 표시가 거짓말**로 남으므로, 그 표시를 **검사 가능한 주장**으로 바꿨다. 메타 단언(50행 이상 읽었다·「미구현」 행을 실제로 읽었다)이 없으면 표 형식이 바뀌었을 때 셋이 「빈 것끼리 같다」로 통과한다 (#591) |
| 2026-08-23 | `#598` | `test_reports.py` 46 → **50함수** · `test_reports_db.py` 27 → **28함수** · 합계 실측 갱신(1344함수·1630수집 → **1349함수·1635수집**). 연료의 한국어 이름은 `AGENTS §4.6` 기준 **표시 문구**이고 화면(`fuelTypes.ts`)이 원본이다 — 선종이 이미 그 구조(`SHIP_TYPE_LABELS` ↔ `shipTypes.ts` ↔ 동기화 테스트)로 서 있어 같은 모양으로 복제했다. 서버 마스터의 `display_name`은 `MEPC.364(79)` 원문 표기라 **옮겨 적으면 안 된다.** 코드 집합은 `DB_SCHEMA §3.2` 값 표를 읽어 8종 전수로 대조한다 — 표에 없는 연료가 마스터에 있으면 그 연료만 문서에서 코드로 나오는데, `fuel_type_label`이 모르는 코드를 그대로 내므로 **오류 없이** 지나간다. `#645`의 원문 코드 훑기를 **유종까지 넓혔다** — 그때 출처를 고치면서 같은 표의 옆 칸이 남아 있었고, 훑는 대상을 넓히지 않으면 다음 칸도 같은 방식으로 남는다. 반대 방향(유종이 실제로 실렸는가)도 함께 박았다 — 훑기만 있으면 열을 통째로 빼도 통과한다. 프론트엔드는 `josa.test.ts`(11)·`fuelTypes.test.ts`(6)에 조사 판정과 표시 문구를 고정했다 — §14 인벤토리는 **백엔드 pytest만** 세므로 합계에는 들어가지 않는다 (#598) |
| 2026-08-23 | `#93` | §14 인벤토리에 `test_issue_matrix.py`(6) 등재 · 합계 실측 갱신(1349함수·1635수집 → **1355함수·1641수집**). `#93`은 **닫지 않는 추적용 메타 이슈**인데 본문의 「현재 상태」 표가 세 번 낡았다(07-16 · 08-15 전면 재작성 · 08-22 정정). 네 번째 재작성을 예약하는 대신 **세는 일을 명령 하나로** 옮겼고, 그 집계를 여기서 잠근다. 핵심은 **라벨 없는 이슈가 표에서 사라지지 않는다**이다 — 08-22 실측에서 미부착 4건이 어느 레이어에도 세어지지 않아 합계가 어긋났고, 사라진 이슈는 「없는 것」이 된다. `gh`를 부르는 자리를 함수 하나로 몰아 **테스트가 네트워크를 타지 않게** 했다 (#93) |
| 2026-08-23 | `#559` | §14 인벤토리에 `test_response_contract_db.py`(5) 등재 · 합계 실측 갱신(1355함수·1641수집 → **1360함수·1660수집**. 함수 5개인데 수집이 19인 것은 GET 15종을 파라미터라이즈하기 때문이다). `#559`가 권고한 **B안**(필드 집합 테스트)을 그대로 따랐다. 잠그는 것은 **키**다 — 값까지 맞추면 `API_SPEC` 예시 30곳을 함께 관리해야 하고, 이 결함의 실제 모습은 이름 변경·필드 누락이다. ⚠️ **목록이 비면 그 아래 키가 통째로 사라져 부분집합 비교였다면 조용히 통과한다** — 집합 동등으로 두고, 새 DB에서 0건인 `/calculations`는 테스트가 먼저 계산을 하나 만든다(빈 DB에서 실제로 확인했다). 경로의 UUID는 표에 박지 않고 자리표시자로 두어 시드가 바뀌어도 무엇을 가리키는지 읽을 수 있게 했다 (#559) |
| 2026-08-23 | `#493` | `test_annual_simulation_read_db.py` 18 → **24함수** · `test_hashing.py` 19 → **22함수** · 합계 실측 갱신(1360함수·1660수집 → **1369함수·1673수집**). 고정하는 것은 **재현이 살아 있는 선박을 읽지 않는다**이다 — 제원·capacity·선종을 고쳐도 결과가 그대로여야 한다. ⚠️ 첫 시도의 테스트가 **결함 상태에서도 통과**했다: `reference_speed_kn`을 `14 → 9`로 바꿨는데 결과가 같았기 때문이다. 실측하니 그 두 값은 `calc/annual_simulation.py`에서 **산술에 한 번도 쓰이지 않고** `_has_speed_model()`의 존재 여부 게이트일 뿐이었다 — 이슈 본문의 「그 값으로 표본을 흔든다」가 정확하지 않다. 값 변경이 아니라 **NULL↔비NULL 뒤집힘**으로 바꿔야 잡힌다. `input_hash` 쪽은 **필드마다 따로** 본다: 하나로 묶으면 한 필드만 빠져도 조용히 통과한다 (#493) |
| 2026-08-23 | `#587` | `test_demo_vessel_seed.py` 13 → **17함수** · 합계 실측 갱신(1369함수·1673수집 → **1373함수·1677수집**). 샘플 로로의 `reference_daily_foc_ton`을 **이 배의 항차에서 역산**해 채웠고(`62.0t × 18.0kn × 24h ÷ 450nm = 59.52`), 테스트가 상수를 전사만 하지 않고 **항차에서 다시 낸다** — 항차가 바뀌면 함께 갱신을 강제한다. ⚠️ 더 중요한 것은 **시드가 기존 행을 갱신하지 않는다**는 사실이다: 시드에 값을 새로 채워도 볼륨을 유지한 환경(시연 노트북)에는 영원히 들어가지 않고, 그 상태는 오류가 아니라 화면의 `—`로만 드러난다. 덮어쓰기로 바꾸는 대신(사용자가 고친 값을 덮으면 안 된다) **어긋난 사실을 값으로 만들어** `demo_up.sh`가 시연 전에 경고하게 했다. 감지기가 정말 잡는지, 그리고 **시드가 비워 둔 값(회신 대기분)까지 잡지는 않는지**를 함께 박았다 — 무시해야 하는 경고는 진짜 경고도 함께 묻는다 (#587) |
| 2026-08-23 | `#151` | §14 인벤토리에 `test_scenario_example_sync.py`(5) 등재 · 합계 실측 갱신(104파일·1373함수·1677수집 → **105파일·1378함수·1682수집**). `API_SPEC §5.1` 응답 예시를 **실행 결과로 교체**하고 그것이 다시 어긋나지 않게 잠근다. 이슈 본문이 「개별 수치만 고쳐도 다음 검토에서 다시 어긋난다」고 적었으므로 **문서에서 요청과 응답을 둘 다 읽어** 실제로 실행한다. 함께 막는 것 둘 — ⑴ `weather_model`이 `SIMPLE_RULE`로 돌아가는 것(Open-Meteo를 실제로 호출해 **문서 예시가 외부 서비스의 그날 값에 따라 달라진다**) ⑵ 예시가 다시 밋밋해지는 것(셋 다 등급 `E` → `next_worse_boundary_margin`이 전부 `null`이 되어 `[ORACLE-S-1]`이 그 필드를 추가한 목적이 사라진다). `DIRECT`와 `DETOUR`가 같은 CII를 내는 것이 **오기가 아님**도 단언으로 남겼다 (#151) |
| 2026-08-23 | `#688` | **§3.1에 `IT-STATE-008` 신설 · §14 인벤토리에 `test_voyage_transition_db.py`(5) 등재 · 합계 실측 갱신(105파일·1378함수·1682수집 → **106파일·1383함수·1687수집**).** `IN_PROGRESS → COMPLETED`에 `INCLUDE_AS_ACTUAL`을 실어 보내면 **500**이 났다 — 서비스가 정책을 먼저 대입한 뒤 실적 가드가 SELECT를 날려 **autoflush**가 정책만 먼저 쓰고, `chk_status_policy`(`DB_SCHEMA §2.2`)가 `IN_PROGRESS` + `INCLUDE_AS_ACTUAL` 조합을 거부한다. ⚠️ **테스트 2,638건이 통과했다** — `test_voyage_state_machine.py`는 `_StubVoyage`, `test_voyages_api.py`는 `_FakeSession`이라 **DB 제약이 없고**, 정책을 넘긴 유일한 케이스가 거부값이라 검증에서 끝났다. 근본은 이 문서였다: `§3.1` 표에 **정상 완료 케이스가 없었다.** `EXCLUDE`는 모든 그룹에 있어 통과하므로 **그룹을 건너뛰는 값**으로만 재현되며, 그 경로가 화면의 「항해 완료」 버튼이다. 되돌려 확인했다 — 수정 전 코드에서 3건, 정책 대입만 빼면 4건이 실패한다 (#688) |
| 2026-08-23 | `#689` | §14 인벤토리 함수 수 갱신 — `test_reports.py`(50 → **54**) · `test_health.py`(9 → **14**) · `test_demo_up_script.py`(6 → **9**) · 합계 실측 갱신(1383함수·1687수집 → **1395함수·1699수집**). 파일 수는 그대로다. **폰트가 없을 때 PDF를 거부하는 것**을 고정한다 — 종전에는 `200`과 유효한 `%PDF-1.7`이 나가고 한글만 □가 됐다. 검증 범위를 넷으로 잡았다: ⑴ 폰트 없으면 `PdfUnavailableError`이며 메시지가 **없는 것(폰트)과 할 일(`fonts-nanum` 설치)과 대안(CSV)**을 함께 말하는지 ⑵ **렌더러 부재를 폰트 문제로 보고하지 않는지** — `has_korean_font()`가 Pango 없을 때도 `False`를 내므로 검사 순서를 뒤집으면 해결되지 않는 안내가 나간다 ⑶ 판정이 **프로세스당 1회**인지 — 캐시하지 않으면 PDF 한 건에 렌더링이 두 번, 헬스 체크마다 한 장씩 일어난다 ⑷ **프로브가 폰트 검사를 거치지 않는지** — 거치면 판정과 렌더링이 서로를 불러 무한 재귀다. `/health`는 `"missing"`에서도 `status`가 `ok`로 남는 것과 판정 실패가 500이 되지 않는 것을 함께 박았다(`#400`과 같은 규약). `demo_up.sh`는 7단계가 **기동을 세우지 않는 것**까지 고정한다 — 막히는 것은 PDF 하나이고 DB·계산·화면은 정상이다 (#689) |
| 2026-08-23 | `#691` | §14 인벤토리 함수 수 갱신 — `test_db_target_guard.py`(13 → **20**) · 합계 실측 갱신(`#689` 머지 후 1395함수·1699수집 → **1402함수·1708수집**). **`#507`이 만든 판정을 원래 걸었어야 할 범위로 넓힌 분이다** — 그 판정은 `test_zz_roundtrip.py` 한 파일에만 걸려 있었고, 계정·세션·토큰을 지우는 나머지 12개 파일은 아무 제약 없이 개발 DB에 붙어 2026-08-23에 가입 계정이 사라졌다. 검증 범위를 셋으로 잡았다: ⑴ 거부 문구가 **대상·이유·해결 명령**을 모두 담는지(하나라도 빠지면 사람은 가드를 우회할 방법부터 찾는다) ⑵ 판정이 개발 DB를 막고 `_test` DB를 통과시키는지 ⑶ **그 판정이 실제로 fixture에 걸려 있는지.** ⑶이 이 묶음의 핵심이다 — `#507`의 실패 모드가 「판정 함수는 옳았고 부르는 곳이 없었다」였고, 그 상태에서도 나머지 테스트는 전부 통과한다. `run_alembic`·`migrated_db`·`app_fresh_engine` 세 진입점의 소스에서 호출을 확인하며, 되돌려 실제로 실패하는 것까지 확인했다. 12개 파일이 가드가 걸린 fixture를 지나는지도 함께 본다 (#691) |
| 2026-08-23 | `#692` | §14 인벤토리에 `test_demo_user_seed.py`(11함수) 등재 · `test_demo_up_script.py`(6 → **11**) · 합계 실측 갱신(`#689`·`#691` 머지 후 106파일·1402함수·1708수집 → **107파일·1418함수·1727수집**). **시연 계정을 시드에 넣은 분이다.** 검증 범위를 「행이 들어갔는가」로 잡지 않았다 — 그러면 **해시가 다른 값에서 나왔거나 평문이 그대로 들어가도 통과한다.** 로그인 경로가 실제로 쓰는 `verify_password`로 확인하고, 저장값이 `$argon2`로 시작하는 것까지 본다. 멱등성은 두 방향으로 박았다: 다시 돌려도 **늘지 않는 것**과 **사람이 고친 값을 덮지 않는 것**(`#587`이 선박 제원에서 세운 원칙과 같다). `APP_ENV=production`에서 만들지 않는 것이 이 묶음의 보안 조건이며, `is_deleted` 행을 「있다」로 세지 않는 것도 함께 본다 — 이메일 UNIQUE가 `is_deleted = false`에만 걸려 있어 삭제된 행은 로그인에 쓰이지 않는다. `demo_up.sh` 쪽은 **스크립트에 적힌 이메일·비밀번호가 시드 상수와 같은지**를 대조한다: 스크립트는 파이썬을 부르지 않으므로(`#637`) 상수를 읽어 올 수단이 없고, 어긋나면 **점검이 거짓말을 하고 안내문이 안 되는 비밀번호를 알려 준다** (#692) |
| 2026-08-23 | `#693` | §14 인벤토리 함수 수 갱신 — `test_demo_up_script.py`(6 → **14**) · 합계 실측 갱신(`#689`·`#691`·`#692` 머지 후 107파일·1418함수·1724수집 → **107파일·1426함수·1732수집**). **`.env`를 시연 기동 경로에 싣는 분이다.** `test_compose_env_wiring.py`가 compose에 대해 고정한 세 계약(`#508`)을 **같은 모양으로** 이 스크립트에 걸었다 — ⑴ `--env-file`이 붙는가 ⑵ `.env`가 없어도 기동하는가(gitignore 대상이라 새 클론에는 없다) ⑶ `DATABASE_URL`이 여전히 우선하는가(uvicorn은 `load_dotenv(override=False)`라 기존 환경변수가 이긴다 — 이 줄이 사라지면 **점검한 DB와 서버가 붙는 DB가 갈린다**). ⚠️ 판정 근거를 **서버가 남긴 로그**로 잡은 것이 이 묶음의 핵심이다: `.env` 파일을 읽으면 「파일에 뭐라고 적혀 있나」만 알 뿐 그 값이 서버에 닿았는지는 모르고, 이 이슈의 결함이 정확히 「설정은 되어 있고 읽는 경로가 없다」였으므로 **파일을 보는 검사는 같은 사고를 그대로 통과시킨다.** `/proc/<pid>/environ`도 쓰지 않는다 — **exec 시점 사본**이라 `--env-file`로 나중에 실린 값이 나타나지 않으며, 실제로 그 방식으로 만들었다가 「고친 뒤에도 계속 console이라고 말하는」 검사를 얻었다. 셸이 `.env`를 `source`하지 않는 것과 `SMTP_PASSWORD`를 출력하지 않는 것, `.env`가 gitignore에 있는 것도 함께 박았다 (#693) |
