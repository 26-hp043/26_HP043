# TEST_PLAN — BlueLog

| 항목 | 내용 |
|---|---|
| 문서명 | TEST_PLAN.md |
| 버전 | v1.12 |
| 상태 | Oracle Review + 외부 리뷰 반영 + Layer 1 픽스처 정본값 규칙 반영 (#166) + v1.4에서 §1.3 케이스 스키마 기호 표기 전환 (#46) + §4.7 인증 API 케이스 (#279) + **v1.6에서 방향 전환 반영 — 신규 서브시스템 5절 · §14 파일 인벤토리 · §11 실측 정정 (#394)** |
| 최종 수정일 | 2026-09-02 |
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
| UT-YTD-005 | CF 스냅샷 분리 집계 | `(fuel_type, cf_used)`로 묶여 개정 전후 행이 각자 CF로 곱해진다 — not under way(`#378`)와 **항해(`#863`)** 양쪽 모두 |
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
| `test_audit_actions_db.py` | 7 | **§3.7 통합 · 감사 로그** — 항차 확정(`VOYAGE_CONFIRM`, 변경 전/후 포함) · 계산 실행의 해시 기록 · **기능③ 실행과 재현 검증이 남는가**(`#869`). **라우트를 지나서** 확인한다 (`#65`) |
| `test_auth_api.py` | 14 | **§4.7 인증 API** — 계정 존재 여부 비노출 · 가입 중복 고지 · 이메일 정규화 |
| `test_auth_failure_paths.py` | 6 | §4.7 API · 인증 |
| `test_auth_session.py` | 27 | §4.7 API · 인증 |
| `test_auth_wiring.py` | 10 | §4.7 API · 인증 |
| `test_calc_run_needs_recalc_db.py` | 6 | §5 DB · 제약·마이그레이션 |
| `test_compose_env_wiring.py` | 8 | **§5 인프라 · 배포 배선** — compose가 `.env`를 컨테이너에 주입하는지, `environment:`가 `DATABASE_URL`을 덮는지 (`#508`) · **`.env.example`이 `APP_ENV`를 설정하지 않는지**(`#810`) · **프로덕션 `app`이 호스트 포트를 열지 않는지**(`#811`). 뒤의 둘이 조용하다 — 본보기를 그대로 `.env`로 복사하면 `docker-compose.prod.yml`의 `${APP_ENV:-production}` 치환이 그 값을 읽어 **프로덕션 스택이 development로 뜨고**, `:8000`이 열린 채 `#786` ⑵가 `USE_FORWARDED_FOR=true`로 바꾸면 공격자가 그 포트에 직접 붙어 `X-Forwarded-For`를 위조해 **요청 한도를 완전히 우회**한다. 개발 compose의 `8000:8000`은 그대로 유지되는지도 함께 본다 |
| `test_data_export_db.py` | 21 | **§3.10 통합 · 자료 내보내기** — **왕복**(내보낸 파일을 그대로 다시 가져온다. 깨져도 오류가 아니라 「필수 컬럼이 없습니다」로만 보여 눈으로는 지켜지지 않는다) · 채울 수 없는 열을 두지 않는다(`attained_cii`·`rating`. **전제인 `calculation_run.voyage_id` 전부 NULL도 함께 단언** — 언젠가 채우면 이 단언이 깨지고 그때 다시 판단하게 된다) · BOM·CRLF · 수식 주입 4종 · 한 행 = 항차 × 연료 · `year`의 type별 의미 · HTTP 계약(라우트 등록·인증 뒤·`Content-Disposition`) (`#59`) |
| `test_db_target_guard.py` | 20 | **§5 인프라 · 테스트 격리** — 파괴적 롤백 테스트가 개발 DB를 치지 않게 한다. CI에서 그 테스트가 조용히 skip되는 것도 함께 막는다 (`#507`) |
| `test_issue_matrix.py` | 6 | **§14 운영 · 이슈 매트릭스 집계** — `#93`(추적용 메타 이슈)의 「현재 상태」 표를 손으로 갱신해 오다 **세 번 낡았다**. 세는 일을 `scripts/issue_matrix.py`로 옮기고 그 집계를 잠근다: **라벨 없는 이슈가 표에서 사라지지 않는다**(08-22에 겪은 상태 — 사라지면 「없는 것」이 된다) · 레이어를 둘 붙인 이슈를 **두 번 세지 않는다**(합계가 열린 이슈 수와 달라지면 그 차이를 설명할 수 없다) · 비어 있는 레이어도 행을 낸다. 네트워크를 타지 않는다 — `gh`를 부르는 자리는 `fetch` 하나이며 여기서 보지 않는다 (`#93`) |
| `test_response_contract_db.py` | 6 | **§4 API · 응답 계약** — 화면이 쓰는 엔드포인트 **16종의 필드 집합을 중첩까지** 대조한다(400키). 라우트 46개가 `dict`를 돌려줘 OpenAPI 응답 스키마가 0건이라 **응답이 조용히 바뀌어도 아무것도 잡지 않았다**(`#559`). **값이 아니라 키**를 본다 — 결함의 실제 모습이 이름 변경·필드 누락이고 그때는 오류가 아니라 화면에 `undefined`가 뜬다. **집합 동등**이라 필드를 더해도 실패한다. `data[]`가 비면 그 아래 키가 통째로 사라지므로 `/calculations`는 **먼저 계산을 하나 만들고** 조회한다 — 새 DB에서 0건임을 실측했다 (`#559`) |
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
| `test_fleet_summary.py` | 45 | **§4 API · 선대 요약** — 규제 트리거 판정 · `days_to_d` 산식·경계 6종 · KPI 집계 · 한 척 실패의 격리(`#419`) · **경계 키가 실재하는지**(`#814`) · **기준선의 진행분**(`#864`). 마지막이 조용했다 — `fleet_summary`가 `boundaries.get("d")`를 조회했는데 `determine_rating`은 그 키를 만들지 않아 `days_to_d`가 **한 번도 숫자를 낸 적이 없었다.** 픽스처가 `{"d": ...}`라는 **엔진이 만들 수 없는 dict**여서 검사가 자기 가짜 키를 자기가 읽고 통과했다. 지금은 픽스처를 `determine_rating` 출력으로 만들고, `src/`의 `*_boundary` 리터럴 참조를 전수 대조하며, `get_fleet_summary` 응답까지 지나가 **실제로 숫자가 나오는지** 본다 |
| `test_mail_link.py` | 10 | **§4.7 인증 API** — 메일 링크가 프론트엔드를 가리키는지 (`#429` 회귀) |
| `test_reports.py` | 54 | **§3.4~§3.5 리포트 렌더링** — CSV injection 방어 · BOM · 면책 · 한글 PDF · **`DESIGN_SYSTEM §4` 표시 형식**(자릿수·천단위 구분자·선종 표기·KST 시각). 문서가 직렬화 자릿수를 그대로 내보내 화면과 갈렸다 (`#584`) · **표시 문구 동기화**(위험도·경고·사유·항차 상태를 정본/화면과 대조 — `#631`) · **연료 표시 문구**(`fuelTypes.ts`와 대조 · `DB_SCHEMA §3.2` 8종 전수 · 모르는 코드는 코드를 그대로 — `#598`) |
| `test_reports_db.py` | 28 | **§4 API · 리포트 데이터 수집** — 진행 중 항차 제외 · 시나리오 인용 · 값 재계산 금지 · **문서 어디에도 UTC ISO가 남지 않는다**(`#646`) · **유종도 원문 코드가 남지 않는다**(`#598` — `#645`가 출처를 고칠 때 같은 표의 옆 칸이 남아 있었다) |
| `test_annual_simulation_api_db.py` | 24 | **§4 API · 기능③ 실행** — 스냅샷 격리 · 정책 필터링 · 분포 프로파일 기록·**존재 검증**(`#870`) |
| `test_in_progress_year_scope_db.py` | 4 | **§4 API · 정본 정합 · 진행 중 항차의 연도 범위** — 과거 연도 조회에 현재 진행분이 섞이지 않는가(실시간 CII · 선대 요약 · 연간 실적 리포트) · 올해 조회에는 실제로 실리는가 (`#815`) |
| `test_ytd_definition_sync_db.py` | 5 | **§4 API · 정본 정합 · YTD 정의** — **다섯 경로**(실시간 CII · 연도별 이력 · 선대 요약 · 연간 실적 리포트 · **항차 완료 리포트**(`#866`))가 같은 attained CII를 내는가 · 리포트 한 문서 안의 두 행이 일치하는가 · 과거 연도가 진행분에 흔들리지 않는가 (`#750`) |
| `test_annual_simulation_read_db.py` | 26 | **§4 API · 기능③ 조회·재실행** — 조회가 다시 계산하지 않는지 · 스냅샷 항차 표현 · 재현 판정(파라미터 변경 409 / 재현 실패 500) (`#443`) · **선박 제원 스냅샷**(`#493` — 제원·capacity·선종을 고쳐도 재현이 흔들리지 않는다 · `037` 이전 실행은 사유를 밝히고 끊는다) |
| `test_simulation_parameter_db.py` | 8 | **§5.7 DB · seed 적재** — 분포 파라미터가 PRD 표와 일치하는지 · DB→엔진 변환 |
| `test_soft_delete_db.py` | 10 | **§3.9 통합 · §5.6 DB · 소프트 삭제** — 조회·집계에서 빠지는가 · 삭제된 IMO 자리를 비우는가(partial unique) · 행이 남아 있는가 (`#66`) |
| `test_annual_simulation.py` | 48 | **§2 단위 · 기능③ 시뮬레이터** — seed 재현성 · 확률 누적 · 방향 · `§12.8` 예외 · `parameters_used` 스키마 버전 동결(`#816`) |
| `test_cii_current_db.py` | 31 | **§4 API · 실시간 CII 3종 값** — 등급이 ⑴에만 붙는 것 · 진행분 반쪽 주입 금지 · `as_of` 재현성 · **⑶ 연말 예상이 「남은 거리 기반」인 것**(`#798`) · **대표 유종이 행 순서에 흔들리지 않는 것**(`#867`). 마지막이 조용했다 — 종전 방식(`YTD_DAILY_AVERAGE`)은 거리·연료를 같은 비율로 더해 `M/W`가 보존되므로 ⑶이 **구조적으로 ⑴과 항상 같은 값**이었고, 그 상태를 잡는 검사가 없었다. 지금은 잔여 계획이 있으면 ⑶ ≠ ⑴임을, 그리고 ⑶이 **기능③의 `projected_attained_cii`와 문자 단위로 같음**을 단언한다 |
| `test_not_underway_crud_db.py` | 32 | **§4 API · not under way 구간 CRUD** — 구간 겹침 금지 · CF snapshot · 소프트 삭제 · 집계 도달 |
| `test_parameters_api_db.py` | 15 | **§4 API · 규제 파라미터 조회** — 네 종류 조회 · 수치 문자열 직렬화(`§1.7`) · 값이 DB와 일치 · 모르는 선종은 오류 · `#370` 우회 제거 확인 (`#444`) |
| `test_auth_tokens.py` | 13 | **§4.7 인증 API** — 토큰 일회성·만료·용도 분리 · 재설정 시 세션 전량 무효화 |
| `test_password.py` | 15 | **§4.7 인증 API** — 해싱·정책·타이밍 방어 |
| `test_mail.py` | 21 | **§5 인프라 · 메일 발송** — 프로덕션 console 가드 · 백엔드 선택 · 발송 실패 래핑 · 템플릿 · **`SMTP_USE_TLS` 모르는 값 거부**(`#868`). `#810`부터 **`APP_ENV=Production`에서도 console 가드가 발동하는지**를 함께 본다 — `load_mail_settings()`가 `APP_ENV`를 독립적으로 읽어 `== "production"`으로 비교했으므로, `config.py`만 고쳐서는 닫히지 않는 **다섯 번째 가드**였다 |
| `test_config.py` | 12 | **§5 인프라 · 기동 검증** — `APP_ENV` 해석의 계약. `DATABASE_URL` 프로덕션 가드(`#118`)에 더해 **`APP_ENV` 정규화·허용값 검증**을 고정한다(`#810`): `Production`·`"production "`이 **프로덕션으로 닫히는지**(종전에는 이 셋이 전부 development로 떨어져 dev-login·`/docs`·데모 계정 시드·DB URL 폴백·console 메일 백엔드가 **함께, 조용히** 열렸다 — 앱은 정상 기동하고 `/health`도 200이다) · `prod`·`prd`·`live` 같은 **모르는 값이면 기동이 서는지** · 허용값 넷(`development`·`test`·`staging`·`production`)이 전부 뜨는지 · 정규화가 값을 바꾸면 **경고 로그가 남는지**(엄격 일치 안이 주는 「틀렸다는 신호」를 이 로그가 대신한다) |
| `test_csv_fixture.py` | 3 | §3 통합 · CSV |
| `test_voyage_import_db.py` | 23 | **§3.4 통합 · CSV 가져오기 · 커서 페이지네이션** — 수식 주입 4종 escape · 숫자 열은 거부 · 부분 성공(행 번호 보고) · 1000행 상한은 자르되 알린다 · dry-run (`#60`) · **커서 페이지네이션 3종** — 페이지 크기를 넘는 항차에 도달 · **발급한 커서를 서버가 읽는다** · 깨진 커서는 422 (`#627`) |
| `test_case_id_sync.py` | 7 | **§5 인프라 · 문서 정합** — 케이스 ID가 코드·면제 표 어디에도 없는 상태를 막는다 (`§14.5`). 범위 규칙 자체를 고정하는 3건 포함 — 인용은 커버리지 주장이 아니다 (`#498`) |
| `test_dashboard_seed.py` | 16 | **§5.7 DB · seed 적재** |
| `test_doc_cross_refs.py` | 4 | **§5 인프라 · 문서 정합** — `UIFLOW`·`DESIGN_SYSTEM`을 가리키는 절·화면 참조가 **실재하는지**, 그리고 `AGENTS §4.7` 표기 규칙(화면에 `§`를 붙이지 않는다)을 지키는지. `.md`와 `frontend/src` 주석을 함께 훑는다 (`#583`·`#602`) |
| `test_doc_version_sync.py` | 3 | **§5 인프라 · 문서 정합** — `README` ↔ 정본 헤더 버전 일치 (`AGENTS §4`) |
| `test_db_hardening_023.py` | 6 | §5 DB · 제약·마이그레이션 |
| `test_demo_up_script.py` | 22 | **§5 DB · 운영 스크립트** — 시연 기동 스크립트의 계약. `bash -n` 문법 · **JSON 값 추출**(파이썬 없이) · `--check`가 `.venv` 없이 도는 것 · 기동은 여전히 막히는 것. **CI가 이 스크립트를 실행하지 않아** `#616`의 `mktemp` 오류가 저장소에 들어와 있었다 (`#637`) |
| `test_demo_vessel_seed.py` | 17 | **§5.7 DB · seed 적재** — 합성 IMO의 체크섬 유효성 포함 (`#525`) · **제원 역산과 시드↔DB 어긋남 감지**(`#587` — 시드는 `ON CONFLICT DO NOTHING`이라 **기존 행을 갱신하지 않는다**. 시드에 값을 채워도 볼륨을 유지한 환경에는 들어가지 않고, 그 상태는 오류가 아니라 화면의 `—`로만 드러난다) |
| `test_demo_seed_counts.py` | 5 | **§5.7 DB · seed 적재** — 적재·삭제 **행 수 보고**가 사실인지 (재실행 0 · 비운 뒤 실제 건수 · 음수 없음, `#481`) |
| `test_demo_user_seed.py` | 11 | **§5.7 DB · seed 적재** — **시연 계정**의 계약 (`#692`). 시드가 계정을 만들지 않아 DB를 다시 만들 때마다 사람이 가입해야 했고, `#691` 이전의 테스트가 계정을 지우면 로그인 화면으로 들어갈 길이 없었다. 넷을 고정한다 — ⑴ 저장된 해시가 **그 비밀번호로 실제 검증**되는지(행 수만 보면 평문이 들어가도 통과한다) ⑵ 다시 돌려도 늘지 않고 **사람이 고친 값을 덮지 않는지** ⑶ **`APP_ENV=production`에서는 만들지 않는지**(고정 비밀번호가 프로덕션에 있으면 알려진 순간 누구나 들어온다) ⑷ 없으면 없다고 말하는지 — `is_deleted` 행을 「있다」로 세면 점검이 거짓말을 한다 |
| `test_dev_auth.py` | 6 | **§4.7 API · 인증** — 스텁 인증 라우트 등록 판정(`AT-AUTH-013`). `#810`부터 **`auth_dev`가 `APP_ENV` 사본을 갖지 않는 것**까지 본다 — 종전에는 `from cii_platform.config import _ENV`로 import 시점에 값을 복사해 `!= "production"`으로 다시 비교했고, 부정형이라 **모르는 값에서 여는 쪽으로** 틀렸다 |
| `test_docs_exposure.py` | 15 | **§4.7 API · 인증** — 프로덕션 OpenAPI 문서 노출 범위 (`AT-AUTH-014`) · **공개 경로 불변식**(`AT-AUTH-015`). 판정이 import 시점에 확정되므로 **하위 프로세스로 진짜 앱을 기동**해 응답 코드를 본다 (`#593` · `#648`) |
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
| `test_rate_limit.py` | 21 | **§4 API · 요청 한도** — `API_SPEC §13.2` 계약. 카운터 자체(고정 윈도·IP 분리·`0` 비활성·`X-Forwarded-For` 무시·429 봉투의 `meta.request_id`)와 **경로 버킷**(`#811`)을 함께 본다. 버킷은 세 갈래다 — 인증 10 · 계산 60 · 그 밖 300. 종전에는 전역 한도 하나(300)뿐이라 **로그인 무차별 대입에 분당 300회**가 허용됐고, 정본이 규정한 계산 60회는 적용되지 않았다. ⚠️ **경로 목록이 실제 라우트와 어긋나면 한도가 조용히 풀리므로** 두 집합의 모든 경로가 앱에 실재하는지 대조한다 — `app.routes`가 아니라 **OpenAPI**를 읽는다(`include_router`한 경로는 `app.routes`에 펼쳐지지 않아 0개로 보이고, 그러면 검사가 「없는 것끼리 비교해」 통과한다. `#634`가 같은 함정에 걸릴 뻔했다). 경계가 **넓어지는** 방향도 함께 막는다: `/auth/logout`·`/auth/me`·`GET /calculations`·`POST /scenarios/{id}/adopt`가 기본 버킷에 남는지 |
| `test_rating_boundary.py` | 16 | §2 단위 · 계산 엔진 |
| `test_request_context.py` | 3 | §4 API · 공통·운영 |
| `test_risk_level.py` | 26 | §2 단위 · 계산 엔진 |
| `test_rng_reproducibility.py` | 4 | §2 단위 · 계산 엔진 |
| `test_scenario_compare_api.py` | 35 | §4 API · 기능② 시나리오 |
| `test_scenario_compare_db.py` | 2 | §4 API · 기능② 시나리오 |
| `test_scenario_adopt_db.py` | 17 | **§3 통합 · 시나리오 채택** — 계획값 반영 · 계산 무효화(항차 범위) · 계획 단계 항차만 허용 · 항차당 채택 하나 · `CREATE_NEW_VOYAGE` (`#58`) |
| `test_seed_data.py` | 17 | **§5.7 DB · seed 적재** |
| `test_seed_migration.py` | 8 | **§5.7 DB · seed 적재** |
| `test_simulation_clock.py` | 30 | **§2.11 단위 · 시뮬레이션 시계** |
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
| `test_voyages_api.py` | 28 | §4 API · 선박·항차·계산 (실적 입력 라우트 포함) · **확정 항차 PATCH 가드**(`#865`) |
| `test_weather_seed.py` | 5 | **§5.7 DB · seed 적재** |
| `test_weather_model.py` | 18 | **§2 단위 · 기상 보정 모델** — Townsin-Kwon 경험식(BN·Cβ 보간·적용 한계)과 SIMPLE_RULE(clamp·상한). **두 모델의 실패 규칙이 서로 새지 않는지** (`#61`) |
| `test_weather_client_db.py` | 19 | **§3 통합 · 기상 조회** — 두 엔드포인트 · 부분 실패 · 시각 선택 · 캐시 격자 · 스냅샷 저장 · 모델 디스패치 (`#61`) |
| `test_weather_fallback_db.py` | 12 | **§3 통합 · 기상 fallback** — `PRD §11.6` 네 칸(최신·6h·6~24h·없음) · 실험 모델 배지 · 「보정하지 않았다」를 조용히 넘기지 않는다 (`#62`) |
| `test_weather_simulation_migrations.py` | 12 | §5 DB · 제약·마이그레이션 |
| `test_ytd_cii_service_db.py` | 21 | **§2.10 단위 · YTD 산출 엔진** |
| `test_ytd_engine.py` | 26 | **§2.10 단위 · YTD 산출 엔진** |
| `test_zz_roundtrip.py` | 6 | §5 DB · 제약·마이그레이션 (데모 seed 분리 후 롤백 — `#451`) |

**합계 109개 파일 · 1516 함수 · 1876 수집.** (2026-09-09 실측)

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
| 2026-09-02 | `#792` | §14 인벤토리 함수 수 갱신 — `test_dashboard_seed.py`(15 → **16**) · 합계 실측 갱신(1426함수·1732수집 → **1427함수·1733수집**). 신설한 것은 `test_planned_voyage_departure_is_still_ahead`이며, **기존 단언과 같은 부류인데 아무도 보고 있지 않던 자리**다 — 진행 중 항차의 도착 예정일이 만료돼 CI가 빨개진 그날, 계획 항차의 출항 예정일도 **사흘 뒤**였다. 함께 `test_in_progress_voyage_arrival_is_still_ahead`의 docstring을 사실로 고쳤다: 종전 근거였던 「누적이 날짜마다 늘어 값이 달라진다」는 `#649`(PR `#664`)가 `simulation_clock`에 상한을 넣으며 **이미 해소됐고**, 이 단언이 지금 지키는 것은 **시드가 상대 시각을 쓴다는 계약**이다. 근본 원인은 시드가 「오늘 = 2026-08-25」를 가정한 절대 시각 14개로 짜여 있던 것이며, `demo_seed._rel()`이 적재 시각을 기준으로 만들도록 바꿨다 (#792) |
| 2026-09-08 | `#816` | §14 인벤토리 함수 수 갱신 — `test_annual_simulation.py`(38 → **46**) · `test_annual_simulation_read_db.py`(24 → **26**) · 합계 실측 갱신(1427함수·1733수집 → **1437함수·1748수집**). 고정하는 것은 **`parameters_used`가 어느 스키마 버전으로 저장됐는지**다. `reproduce`는 저장된 `parameter_hash`를 그대로 두고 **지금 코드로** `parameters_used`를 다시 만들어 비교하므로, 빌더 출력이 한 글자만 바뀌면 **과거 실행 전부**가 409 `PARAMETER_ERROR`를 받는다 — 바뀐 것은 규정이 아니라 우리 코드인데 사용자에게는 「규정 파라미터가 변경되었다」가 나간다. `calculation_run`은 `calc_run_guard()`(마이그레이션 024)가 UPDATE를 막아 **저장된 해시를 소급해 고칠 수도 없다.** 그래서 v1을 빌더로 동결하고 버전 필드가 **없는** 행을 v1으로 판정한다. ⚠️ 배선 테스트를 「409가 나지 않았다」로 두면 **버전을 통째로 무시해도 통과한다**(지금은 v1이 최신이므로). 그래서 넷을 본다: ⑴ 버전 필드가 없는 행이 v1으로 판정 ⑵ 빌더가 실제로 `version=1`로 호출 ⑶ 가상 v2였다면 해시가 달랐다(판별력 증명) ⑷ 재현 결과·해시가 원본과 동일. 판정 함수만 가상 v2를 돌려주게 바꾸면 빌더가 `2`를 받는지도 함께 본다 — 상수를 넘기던 구현을 실제로 잡아냈다. 손상된 버전 필드(`null`·`"abc"`·`1.5`·`true`)는 v1으로 흡수하지 않고 끊는다: 흡수하면 해시 불일치의 이유가 「버전이 다르다」인지 「값이 손상됐다」인지 가려진다. `bool`을 먼저 막는 것은 파이썬에서 `isinstance(True, int)`가 참이기 때문이다 (#816) |
| 2026-09-08 | `#752` | §14 인벤토리 함수 수 갱신 — `test_annual_simulation_api_db.py`(14 → **15**) · `test_response_contract_db.py`(5 → **6**) · 합계 실측 갱신(1437함수·1748수집 → **1439함수·1750수집**). 고정하는 것은 **기능③이 `API_SPEC §1.3.1` 계산 결과 응답 봉투를 따르는가**다. 종전에는 최상위가 `data`·`meta` 둘뿐이라 `parameters_used`·`calculation_run_id`·`model_version`·`input_hash`·`parameter_hash`·`warnings`·`disclaimer`·`meta.duration_ms`가 전부 빠져 있었고, 기능①·②는 규격대로 냈다. 그중 `disclaimer` 누락은 `PRD §0.3`(제품 내 모든 결과에 고지) 위반이다 — **화면이 자체 상수로 그리고 있어 눈에 띄지 않았을 뿐**, 리포트·외부 소비처가 생기면 그대로 빠진다. 계약 표에 `POST /annual-simulations`(100키)를 넣고 **`§6.2` 조회도 같은 표로 본다** — `§6.2`가 「§6.1의 응답과 동일」로 규정하므로 표를 나누면 갈린 것을 볼 수 없다(실측으로 두 응답의 키 집합이 완전히 같음을 확인했다). ⚠️ 이 계약 테스트는 **실행을 스스로 만들고 바로 조회한다** — 「먼저 만들어 두는 테스트」를 앞에 두는 방식은 정의 순서에 기대는 것이라 함수를 옮기면 조용히 깨진다(`#838`이 그 상태를 다룬다). `calculation_run_id`와 `warnings`는 `data` 밖으로 옮겼고 **안에 남아 있지 않은지도 함께 본다** — 같은 값이 두 곳에 있으면 어긋났을 때 어느 쪽이 정본인지 알 수 없다. 재현 비교는 `_duration_ms`만 뺀 응답 전체로 한다: 두 실행의 계산 시간은 당연히 다르지만, 그 하나 때문에 `data`만 비교하면 해시·`parameters_used`·`model_version`이 어긋나도 통과한다. 프론트엔드는 봉투의 최상위 필드를 provider 경계에서 합치고, **빠지거나 타입이 다르면 차단**한다(+5) — 빈 배열로 채우면 「경고가 없다」와 「경고를 받지 못했다」가 구분되지 않는다. §14 인벤토리는 백엔드 pytest만 세므로 프론트 증가는 합계에 반영되지 않는다 (#752) |
| 2026-09-08 | `#812` | §14 인벤토리 함수 수 갱신 — `test_annual_simulation_api_db.py`(15 → **20**) · 합계 실측 갱신(1439함수·1750수집 → **1444함수·1755수집**). 고정하는 것은 **연료 종류 수가 결과를 바꾸지 않는다**이다. 종전에는 계획 항차의 `fuel_uses`마다 한 줄을 만들면서 **항차 전체 거리를 그대로 복사**해, 연료가 2종이면 그 항차 거리가 2배로 계상됐다 — 분모만 커져 연말 예상 CII가 1/N로 낮아지고 **목표 달성 확률이 0%↔100%로 뒤집힌다.** 확정(ACTUAL) 분기는 거리를 항차당 한 번만 더하는데 계획(PLAN) 분기만 규칙이 달랐다. `voyage_fuel_use`의 `idx_fuel_use_unique` 주석이 「중복 시 CO₂ 이중 산정 버그 방어」인데 **분자는 막고 분모가 뚫려 있었다.** ⚠️ 검사는 **거리를 먼저 본다** — CII만 비교하면 실패해도 원인이 거리인지 배출인지 가려지지 않는다. CF가 같은 두 연료로 나눈 입력(거리 검증)과 CF가 다른 두 연료(유효 CF 합산 검증)를 따로 둔다: 앞의 것만 두면 유효 CF가 틀려도 통과하고, 뒤의 것만 두면 거리가 두 배여도 배출 비교는 맞을 수 있다. 유효 CF는 float이라 상대오차 `1e-12`로 본다 — 절대 동등은 표현 오차로 실패하고, 자릿수를 버리면 유효 CF가 틀려도 통과한다. 연료를 알 수 없는 계획 항차는 **빼되 경고(`SIMULATION_PLAN_NO_FUEL`)를 남긴다**: 거리만 넣으면 「거리는 가는데 배출은 0」이 되어 분모만 커지고 연말 예상이 **실제보다 좋게** 나오는데, 그것이 이 이슈가 고치는 결함과 같은 방향이다. `remaining_voyage_count`는 스냅샷의 PLAN 행을 세므로 경고가 없으면 일부만 계산했다는 사실이 드러날 자리가 없다. 경고가 **늘 붙지는 않는지**도 함께 본다. `len(remaining)`이 항차 수라는 불변식을 따로 못 박았다 — 서비스(`len(planned)`)와 엔진(`len(remaining)`)의 상한 가드가 같은 단위를 보게 하고, 민감도 `voyage_count ±1`이 연료 행이 아니라 항차를 가감하게 하는 것이 이 한 값에 걸려 있다 (#812) |
| 2026-09-08 | `#750` | §14 인벤토리에 `test_ytd_definition_sync_db.py`(4함수) 등재 · 합계 실측 갱신(107파일·1444함수·1755수집 → **108파일·1448함수·1759수집**). 고정하는 것은 **네 경로가 같은 YTD를 내는가**다. 실측에서 같은 선박·같은 연도에 대시보드 8.9799 · 선박 상세 8.980 · 실시간 CII 7.028270이 나왔고, 연간 실적 리포트는 한 문서 안에 7.028과 8.980을 함께 인쇄했다 — 수식을 다시 구현한 곳은 없고 `compute_ytd_cii`의 `in_progress` 인자를 **넘기는 호출과 넘기지 않는 호출**이 섞였을 뿐이라, 화면은 멀쩡한 채 값만 갈렸다. ⚠️ **파일을 따로 두는 이유**는 네 경로가 각자의 테스트를 갖고 있고 **각자는 통과했기** 때문이다 — 갈린 것이 경로 사이라 넷을 나란히 놓아야 잡힌다. ⚠️ **진행 중 항차가 없으면 네 경로가 원래 같은 값을 내므로**, 그런 선박으로 검사하면 정의가 다시 갈려도 통과한다. 그래서 픽스처가 진행 중 항차를 만들고, **진행분이 실제로 값을 바꾸는지 먼저 확인하는 검사**를 따로 둔다. 비교는 문자열이 아니라 값으로 한다 — 표시 자릿수가 경로마다 달라(6자리·4자리·3자리) 문자열 비교는 진짜 불일치를 가린다. 실패 메시지에 **다섯 경로의 값을 함께 싣는다**: 어디가 갈렸는지 바로 보이지 않으면 원인 추적이 다시 전수 대조가 된다. 과거 연도가 진행분에 흔들리지 않는 것도 함께 본다 — 확정된 과거가 조회할 때마다 달라지면 안 된다. ⚠️ **이 작업이 스스로 만든 회귀를 이 파일이 잡았다**: 선대 요약에 진행분을 넣으면서 **과거 연도 조회에도 더해지는 경로가 열렸고**(`fleet_summary(year=2024)`가 4.9824 대신 5.1486), `#815`가 `cii/current`에서 보고한 것과 같은 종류의 오염이다. 연도 가드를 넣고 검사를 하나 더 뒀다 — 이력과 선대 요약 **두 경로가 각각** 막혀 있어야 한다(한쪽만 보면 다른 쪽이 열려도 통과한다) (#750) |
| 2026-09-08 | `#815` | §14 인벤토리에 `test_in_progress_year_scope_db.py`(4함수) 등재 · 합계 실측 갱신(108파일·1449함수·1760수집 → **109파일·1453함수·1764수집**). 고정하는 것은 **진행 중 항차가 그 항차의 연도에만 들어가는가**다. 진행 중 항차 조회(`find_in_progress`)에 연도 조건이 없었고 기여분은 무조건 더해져, `?year=2024`로 물어도 2026년 항해분이 2024년 확정 실적에 합산됐다 — **끝난 해의 실적이 조회할 때마다 달라졌고** 그 값이 연간 실적 리포트 PDF에도 실렸다. 집계의 나머지는 이미 `Voyage.regulation_year == regulation_year`로 거른다(`db/repositories/voyage.py:224`) — 진행분만 다른 기준을 써서 분자와 분모가 다른 해의 항차를 섞었다. ⚠️ **`#750`의 검사와 질문이 다르다**: 그쪽은 「네 경로가 서로 같은 값을 내는가」이고 여기는 「조회한 해의 값이 맞는가」다 — **네 경로가 사이좋게 전부 틀리면 `#750`의 검사는 통과한다.** 그래서 파일을 따로 둔다. ⚠️ **과거 연도에 확정 실적이 없으면 값이 `None`이라 오염이 「데이터 없음」과 구분되지 않으므로** 픽스처가 작년 실적을 넣는다. 기여분만 지우지 않고 상태 전체를 비우는 것도 함께 본다 — ⑵ 항차 구간값과 `meta.simulated`가 같은 항차에서 나오므로 하나만 지우면 「2025년을 보는데 지금 뛰는 항차의 구간값이 떠 있는」 상태가 된다. 리포트 검사는 표시 형식 문자열을 박지 않고 **값을 파싱해** 비교한다 — 자릿수 규칙이 바뀔 때 오염과 무관하게 깨지지 않게 한다. `#750`이 급히 넣었던 「올해를 볼 때만」 가드 둘은 이 기준 하나로 통합했다: 그 가드는 진행 중 항차가 늘 올해 것이라는 가정에 기댄다 (#815) |
| 2026-09-08 | `#796` | §14 인벤토리 함수 수 갱신 — `test_simulation_clock.py`(26 → **30**) · `test_cii_current_db.py`(24 → **26**) · 합계 실측 갱신(1453함수·1764수집 → **1459함수·1770수집**). 고정하는 것은 **진행 중 항차의 누적 연료가 cubic speed model을 따르는가**다. 종전에는 `daily_foc_ton × underway_hours / 24`로, **거리는 항차의 계획 속도로 늘리면서 연료는 선박 기준 속도의 소모율을 그대로** 곱했다 — 계획 14 kn · 기준 12 kn이면 연료가 `(14/12)³ = 1.588`배 **과소** 산출된다. 과소는 「등급이 좋아 보이는」 방향이라 사용자가 조치를 미루고, 같은 파일의 주석(`cii_current.py:443`)이 이미 그 방향을 경계하고 있었다. 같은 저장소의 기능②는 이미 이 식을 쓴다 — **한 경로만 규정을 벗어나 있었다.** ⚠️ **보정이 늘 값을 바꾸지 않는 것도 함께 본다**(계획 속도 = 기준 속도면 배수 1): 이것이 없으면 배수를 아무 상수로 두어도 「값이 커진다」 검사만으로는 드러나지 않는다. ⚠️ **시계와 기능②가 같은 입력에서 같은 연료를 내는지 대조한다** — 두 경로가 각자 계산하면 같은 배·같은 속도인데 화면마다 연료가 다르다. ⚠️ 기대값을 **Layer 1 컨텍스트(`prec=30`)에서 만든다**: 테스트가 기본 컨텍스트(`prec=28`)로 계산하면 끝자리가 갈려 식이 맞아도 실패한다. 기준 속도가 없으면 배수 1로 쌓되 `SIMULATION_NO_REFERENCE_SPEED`를 싣는다 — 소모율도 속도도 있고 모르는 것이 보정 계수 하나뿐이라 기여를 통째로 빼지 않지만, 조용히 넘어가지도 않는다. 경고가 **늘 붙지는 않는지**도 함께 본다. `#796` 정정으로 종전 단언 하나(*"연료는 속도와 무관하다"*)가 뒤집혔다 — 속도가 없으면 거리도 0이라, 연료만 쌓으면 **분자만 늘고 분모는 그대로**가 되어 항해할수록 등급이 나빠진다(방향만 반대인 같은 오류) (#796) |
| 2026-09-08 | `#757` | §14 인벤토리 함수 수 갱신 — `test_annual_simulation.py`(46 → **48**) · 합계 실측 갱신(1459함수·1770수집 → **1461함수·1778수집**). 고정하는 것은 **Monte Carlo 집계의 반올림이 정본과 같은 값을 내는가**다. 구현이 `round()`를 썼는데 그것은 **은행가 반올림**(half-to-even)이라 `TECH_SPEC §2.4`가 규정한 `ROUND_HALF_UP`과 다른 값을 냈다 — 자릿수(`PRD §12.4.3`)만 보고 **모드**를 놓친 형태다. ⚠️ **종전 검사는 「자릿수가 4 이하」만 봤다**: 모드가 무엇이든 통과하고, `round()`가 후행 0을 버려 `0.0`·`1.0`이 나가도 통과했다 — `API_SPEC §1.7`이 「4 유효숫자」를 적고 `§6.1` 예시가 `0.0200`을 드는 것과 다르다. 이제 **자릿수가 정확히 4**임을 보고, 경계 입력 7건을 **값으로** 고정한다(`0.56785`·`0.00015`·`2.00005`가 은행가 반올림과 갈리는 지점, `0.0`·`1.0`이 후행 0 고정). ⚠️ **정본의 참조 구현을 그대로 옮겨 돌려 대조하는 검사를 따로 둔다** — 손으로 적은 기대값만 보면 그 기대값을 잘못 적었을 때 두 검사가 함께 틀린다. 재현 경로 영향을 실측했다: 두 반올림이 갈리는 `simulation_runs`는 허용 구간 1,000~10,000 중 **281개(전부 32의 배수)**이고 **기본값 5,000과 1,000·2,000·10,000은 0개**다 — 어긋나는 것은 「과거 값이 옳았는데 깨진 것」이 아니라 「과거 값이 정본과 달랐던 것」이다 (#757) |
| 2026-09-08 | `#820` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`annualRules.test.ts` +13). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **임계 판정이 표시된 숫자와 같은 답을 내는가**다. `probabilityOfDorE`가 `Number(D) + Number(E)`로 더해, 서버가 4자리로 양자화해 보낸 정확한 십진 문자열이 float에서 어긋났다 — `0.3500 + 0.0500 = 0.39999999999999997`. 그 결과 **같은 40.0%가 D·E 배분에 따라 주황과 빨강으로 갈리고, 같은 20.0%가 ⚠ 유무로 갈렸다.** ⚠️ **색과 아이콘 두 채널이 함께 무너진다** — `DESIGN_SYSTEM §14`가 요구한 「색 외 보조 채널」이 ⚠ 아이콘인데, 색맹 사용자가 의존하는 그 채널이 같은 값에서 나타났다 사라졌다. 그래서 검사가 `tone`뿐 아니라 **⚠ 포함 여부도 함께** 본다. 배분만 다른 6개 조합을 파라미터라이즈로 고정한다 — 한 조합만 보면 「그 조합에서만 맞는」 구현도 통과한다. `riskFlag`의 표기도 `toFixed`에서 `formatPercent`(ROUND_HALF_UP)로 바꿨다: **바로 아래 `toPercent`가 같은 결함을 이미 고쳤는데 형제인 `riskFlag`만 옛 경로에 남아 있었다** — 그래서 십진 사칙을 복사하지 않고 `display/decimal.ts`로 옮겨 기능② `comparisonRules.ts`와 공유한다. `moduleBoundary.test.ts`(`#594`)가 불필요한 export 둘을 잡아 내부 함수로 되돌렸다. 스윕 결과 남은 `Number()` 사용처는 픽셀·레이아웃용이며, 그중 스택 바의 8% 임계가 같은 계열의 별건으로 드러나 `#846`으로 등록했다 (#820) |
| 2026-09-08 | `#799` | §14 인벤토리 함수 수 갱신 — `test_scenario_compare_api.py`(34 → **35**) · 합계 실측 갱신(1461함수·1778수집 → **1462함수·1779수집**). 프론트엔드도 늘었으나(`comparisonRules.test.ts` +2) §14는 백엔드 pytest만 센다. 고정하는 것은 **동률일 때 전부 싣는가**다. `summary`가 지표별 최소값을 하나씩만 골라, **같은 값 중 하나만 지목**했다 — 그것 자체가 추천이고 `PRD §11.2`의 「추천 시나리오를 표시하지 않는다」에 어긋난다. 동률은 드문 일이 아니라 **정의상 필연**이다: `§11.4.1` cubic speed model에서 연료는 거리에 비례하고 AER은 거리로 나누므로 **같은 속도의 직항과 우회는 `attained_cii`가 정확히 같다.** ⚠️ **비교를 응답 자릿수로 한다** — 내부 `Decimal`은 `TECH_SPEC §1.2.1`상 30자리라 거리가 소거되는 두 시나리오도 끝자리가 갈리고, 그대로 비교하면 **응답에 같은 값이 실려 있는데 동률이 아니라고 판정**한다(작업 중 실측으로 드러났다). ⚠️ **양자화한 뒤에도 문자열이 아니라 숫자로 비교한다** — `_publish`가 낸 문자열을 그대로 `min`에 넣으면 사전순이 되어 자릿수가 다를 때 뒤집힌다(기존 계약 테스트가 이 실수를 잡았다). 동률을 만드는 조건은 **감속 속도를 현재 속도와 같게** 두는 것이다 — 세 시나리오의 속도가 같아져 CII가 셋 다 같아진다. 화면 쪽은 표기가 다른 같은 값(`5.0`·`5.00`)도 동률로 보는지 함께 고정한다 (#799) |
| 2026-09-08 | `#813` | §14 인벤토리 함수 수 갱신 — `test_weather_client_db.py`(16 → **19**) · 합계 실측 갱신(1462함수·1779수집 → **1465함수·1782수집**). 고정하는 것은 **풍속 단위**다. Open-Meteo의 기본 단위는 `km/h`인데 요청에 `wind_speed_unit`이 없었고 응답을 변환 없이 `wind_speed_ms`에 넣어 **값이 3.6배** 커졌다(실측: 같은 좌표에서 기본 `15.4`, `wind_speed_unit=ms`로 `4.27`). ⚠️ **픽스처가 잘못된 전제를 고정하고 있었다** — `WIND_BODY`에 `hourly_units`가 없어 **단위를 m/s로 단정**했고, 그래서 이 결함이 테스트를 통과했다. 실제 응답 형태(단위 블록 포함)로 고쳤다. 검사 셋을 둔다: ⑴ 요청이 `wind_speed_unit=ms`를 싣는가 ⑵ 응답 단위가 다르면(`km/h`) 풍속을 **쓰지 않는가**(파고는 살아 있다 — 한쪽 문제가 전체를 죽이지 않는다) ⑶ 단위 블록이 **없으면** 참으로 보지 않는가. ⑶을 따로 두는 이유는 **없는 것을 「기본값이겠지」로 읽는 사고방식이 이 결함을 만들었기** 때문이다. `/3.6` 변환 대신 요청에 단위를 싣는 이유는 나누는 쪽이 「기본값이 계속 km/h다」라는 가정에 기대기 때문이다 (#813) |
| 2026-09-08 | `#809` | §14 인벤토리 함수 수 갱신 — `test_mail_link.py`(5 → **10**) · 합계 실측 갱신(1465함수·1782수집 → **1470함수·1789수집**). 고정하는 것은 **요청 `Host`가 메일 링크를 바꾸지 못한다**이다. `APP_PUBLIC_URL`이 없으면 `public_base_url`이 `request.base_url`로 폴백했고, 공격자가 `Host: attacker.example`로 재설정을 요청하면 피해자는 **정상 발신지에서 온 정상 문구의 메일**을 받는데 링크만 공격자 도메인이었다 — 클릭 한 번에 유효한 재설정 토큰(1시간)·인증 토큰(24시간)이 넘어간다. ⚠️ **종전 테스트가 취약 동작을 「정상」으로 고정**하고 있었다: `test_falls_back_to_request_origin`의 docstring이 *"운영은 nginx 뒤에서 같은 origin이라 이 값이 정확하다"* 였는데, 그 전제는 **`Host` 헤더를 믿을 수 있어야** 성립한다. 그것을 믿을 수 없다는 것이 이 이슈다 — 이름과 문구를 「개발에서만」으로 정정했다. 검사는 셋을 본다: ⑴ 설정이 있으면 **어떤 `Host`가 와도 결과가 같다**(공격자 도메인·유사 도메인·루프백 3종 파라미터라이즈) ⑵ 프로덕션 미설정은 **폴백이 아니라 거부** ⑶ **기동 시점**에 끊는다(`#524` 선례 — 호출 시점 방어만 두면 드러나는 시점이 「배포 직후」가 아니라 「첫 사용자가 비밀번호를 잊은 순간」이 된다). 가드가 **늘 막지는 않는지**도 함께 본다(개발에서는 통과·설정이 있으면 프로덕션에서도 통과). ⚠️ **함수 단위 검사만으로는 부족하다** — 가드가 있다는 것만 보고 그것이 **기동 경로에 실제로 연결됐는지**는 보지 못한다(lifespan에서 호출을 빠뜨려도 통과한다). 그래서 `test_docs_exposure.py`의 서브프로세스 하네스로 **진짜 프로세스가 기동을 거부하는지**를 따로 단언하고, 막는 것만이 아니라 **사유가 stderr에 드러나는지**도 본다 — 막혔는데 이유를 모르면 운영자가 원인을 찾을 수 없다. 그 하네스의 환경에 `APP_PUBLIC_URL`을 추가했다: **기존 테스트 2건이 이 가드 때문에 실패한 것 자체가 가드가 동작한다는 증거**였다 (#809) |
| 2026-09-08 | `#810` | §14 인벤토리 함수 수 갱신 — `test_config.py`(6 → **12**) · `test_dev_auth.py`(5 → **6**) · `test_mail.py`(16 → **18**) · 합계 실측 갱신`test_compose_env_wiring.py`(5 → **6**) · 합계 실측 갱신(1471함수·1790수집 → **1481함수·1813수집**). 고정하는 것은 **`APP_ENV`가 오타 하나로 프로덕션 가드 다섯을 동시에 열지 못한다**이다. `config.py:17`이 `os.environ.get("APP_ENV", "development")`로 원문을 그대로 받아 `== "production"`과 비교했고 **strip()·lower()·허용값 검증이 하나도 없었다** — `Production`·`prod`·후행 공백 하나면 dev-login(**미인증 세션 발급**) · `/docs`·`/redoc`·`/openapi.json` · **데모 계정 시드**(비밀번호가 `README.md`에 공개돼 있다) · DB URL 개발 기본값 폴백 · `console` 메일 백엔드가 **함께** 열린다. ⚠️ **실패가 조용하다** — 앱은 정상 기동하고 `/health`도 200이라 틀렸다는 신호가 어디에도 없다. ⚠️ **미검증 지점이 둘이었다**: 이슈 본문은 `mail/config.py`를 「제대로 하는 선례」로 인용했지만 그건 `MAIL_BACKEND` 얘기고, **같은 함수 안 `APP_ENV`는 똑같이 원문을 받았다**(`mail/config.py:53`). 그래서 `config.py`만 고치면 다섯 번째 가드(프로덕션 console 금지)는 닫히지 않는다 — 주입 dict를 받는 함수라 `config._ENV`를 쓸 수 없어 **해석 함수**(`normalize_app_env`·`is_production_env`)를 공유하게 했다. 정규화만 하는 안과 엄격 일치만 하는 안 **둘 다 fail-open을 없애며 차이는 관용도뿐**이므로, `MAIL_BACKEND`가 이미 쓰는 저장소 관례(정규화 후 허용값 검증)를 따르고 **정규화가 값을 바꾸면 경고 로그**를 남겨 「틀렸다는 신호」를 보존한다. 허용값은 `development`·`test`·`staging`·`production` 넷 — `staging`·`test`는 지금 어느 배포 경로도 쓰지 않지만, 허용 목록이 배포 환경보다 좁으면 환경을 늘리는 사람이 **가드를 여는 방향으로** 우회한다. 부정형 판정 둘도 함께 없앴다: `routes/auth_dev.py`가 `config._ENV`라는 **private 이름을 import해** `!= "production"`으로 다시 비교하던 것을 `should_expose_dev_auth()` 위임으로 바꿔 **판정이 하나만 남았다** — 갈리면 dev-login이 401이 아니라 **404**가 되어 「여기에 무언가 있다」는 신호가 남는다(`#276`·`#593`). 그에 맞춰 `test_docs_exposure.py::test_the_two_dev_auth_judgements_agree`의 단언을 강화했다: 종전에는 두 사본을 **함께** 갈아 끼워 답이 같은지만 봤는데(즉 *「같은 값을 받으면 같은 답을 낸다」*), 실제 위험은 **둘이 다른 값을 받는 것**이었다 — 지금은 `config._ENV` **하나만** 갈아 양쪽이 따라오는지 본다. 배포 확인도 넣었다: CI `docker` 잡의 **APP_ENV 스모크**와 README 배포 확인 표 첫 행 — 나머지 확인 항목(화면·API·SPA fallback)은 `APP_ENV`가 `development`로 떨어져도 **전부 통과**한다. ⚠️ **그 스모크를 실제로 돌려 보니 배포 경로가 이미 열려 있었다**: 이슈 본문은 `docker-compose.prod.yml:52`를 `APP_ENV: production`으로 인용하며 「이 경로로만 배포하면 안전하다」고 적었는데, 실제 값은 `${APP_ENV:-production}`이고 compose 치환은 셸 다음으로 **저장소 `.env`를 읽는다.** `.env.example:22`가 `APP_ENV=development`였고 `#524`가 프로덕션 SMTP 설정을 요구해 운영 호스트에도 `.env`가 생기므로, **본보기를 그대로 복사한 프로덕션 스택은 development로 뜬다** — 이 저장소의 `.env`로 prod 스택을 띄워 `APP_ENV: development`가 나오는 것을 실측했다. 그래서 `.env.example`의 그 줄을 **주석으로 내리고**(지우지 않는다 — 이 파일이 변수의 존재를 알리는 유일한 목록이고 `test_env_example_documents_every_variable_the_app_reads`가 그것을 강제한다) 재발을 `test_env_example_does_not_set_app_env`로 막는다. 개발에는 값이 필요 없다: 미설정이 곧 `development`이고 `docker-compose.yml`은 이 변수를 넘기지도 않는다 (#810) |
| 2026-09-09 | `#811` | §14 인벤토리 함수 수 갱신 — `test_rate_limit.py`(12 → **21**) · `test_compose_env_wiring.py`(5 → **7**) · 합계 실측 갱신(1471함수·1790수집 → **1482함수·1815수집**). 고정하는 것은 **요청 한도가 경로에 맞는 값인가**다. 종전에는 전역 한도 하나(300)뿐이었다: ⑴ **로그인 300회/분은 무차별 대입 방어가 아니고**, `/password-reset/request`·`/verify-email/request`는 같은 한도 아래에서 **메일 발송 증폭기**로 쓰였다. ⑵ `API_SPEC §13.2`는 **두 행**(계산 60 / CRUD 300)을 규정하는데 `rate_limit.py:3`이 **아래 행만 인용**해 계산 경로에도 300이 걸렸다 — `#238`의 체크리스트가 *「API_SPEC에 규정이 있으면 그 수치를 그대로 쓴다」*였고, 계산 1건이 `prec=50` 컨텍스트라 CPU가 크다는 것이 그 이슈 자신의 근거였다. 카운터 키를 `(버킷, IP)`로 바꿔 **버킷을 서로 독립**으로 두었다 — `IP`만으로 잡으면 로그인 10회에 대시보드가 함께 막힌다. ⚠️ **경로 목록은 문자열 상수라 라우트가 바뀌면 한도만 조용히 풀린다**(오류도 로그도 응답 변화도 없다). 그래서 두 집합의 모든 경로가 앱에 실재하는지 대조하되 **`app.routes`가 아니라 OpenAPI**를 읽는다 — `include_router`한 경로는 `app.routes`에 `_IncludedRouter` 항목으로만 있고 펼쳐지지 않아 **0개로 보이고**, 그러면 검사가 「없는 것끼리 비교해」 통과한다(실제로 이 작업 중 그 상태를 만들었다가 잡았다. `#634`가 같은 함정에 걸릴 뻔한 뒤 `test_api_spec_endpoints_sync.py`가 이미 OpenAPI를 읽고 있었다). 경계가 **넓어지는** 방향도 막는다 — 접두사 매칭으로 바꾸면 `/auth/logout`·`/auth/me`가 10회/분에 걸려 **정상 사용이 막힌다**. ⚠️ **`conftest.py`의 격리 픽스처도 함께 고쳤다**: `RateLimiter(previous.limit)`처럼 기본 버킷 값 하나만 넘기면 **인증 10·계산 60이 전부 300으로 통일**되어, `main.app`을 쓰는 25개 파일에서 새 한도가 조용히 사라진다. `test_compose_env_wiring.py` 쪽은 **프로덕션 `app`이 호스트 포트를 열지 않는지**를 고정한다 — `#786` ⑵가 `USE_FORWARDED_FOR=true`로 바꿀 때 `:8000`이 열려 있으면 공격자가 그 포트에 직접 붙어 헤더를 위조해 **한도를 완전히 우회**한다. 개발 compose의 `8000:8000`은 유지되는지도 함께 본다(닫으면 Vite dev 프록시와 `demo_up.sh`가 죽고, 그 실패는 「화면은 뜨는데 데이터가 안 온다」로 나타난다) (#811) |
| 2026-09-09 | `#821` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`apiProvider.test.ts` +4 · `ScenarioComparison.test.tsx` +6). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **서버가 보낸 경고·면책 문구가 화면에 도달하는가**다. 항로 비교의 provider가 `warnings: []` 리터럴을 넣어 배너 조건(`response.warnings.length > 0`)이 **영구 거짓**이었고, `NON_CII_VESSEL`·`CII_APPLICABILITY_UNKNOWN`·`WEATHER_NONE_FALLBACK`·`SLOW_SPEED_FLOOR`·`REFERENCE_ONLY`가 **이 화면에서만** 사라졌다 — 같은 코드를 기능① CII 예측 화면은 정상 표시한다. ⚠️ **서버 쪽은 이미 완전했다**: `tests/test_scenario_compare_api.py`가 다섯 코드를 전부 단언하고 있었고(`:273`·`:339`·`:377`·`:406`), 결함은 프론트가 그 값을 읽지 않는 것 하나였다 — **백엔드 계약 테스트만으로는 화면 도달을 증명하지 못한다.** 면책 문구도 접두 `본 결과는 `이 붙은 별도 문자열이라 서버 정본(`services/voyage_cii.py`의 `DISCLAIMER`)을 고쳐도 이 화면만 옛 문구가 남았다 — 기능①은 이미 서버 값을 쓴다(`CiiForecastPage.tsx`). 선박명은 `vessel_display_name: ''`이라 제목이 `` · 2026년 기준 · …``처럼 **구분점만 남은** 채 배포됐다: 서버가 내지 않는 필드를 **응답 타입에 둔 것**이 「서버가 준다」는 오해를 만들었으므로 타입에서 없애고, 셸이 이미 들고 있는 선박 목록(드롭다운이 같은 `displayName`을 렌더한다)에서 도출한다 — `GET /vessels/{id}` 추가 호출이 필요 없다. ⚠️ **기존 프론트 검사 4개 파일 59건이 이 결함을 하나도 잡지 못했다** — provider 검사는 응답 평탄화만, 컴포넌트 검사는 폼 배선만 봤고 **결과 렌더는 아무도 보지 않았다.** 그래서 `PRD §0.3`·`COR-2`가 규정한 법적 방어선이 조용히 빠진 채 남았다. 문구 맵 자체는 손대지 않았다 — `voyage-cii/resultRules.ts`를 두 화면이 공유하고 `#630`의 `warningMessage.sync.test.ts`가 `API_SPEC §1.6`과 대조하므로 다섯 코드가 이미 들어 있었다 (#821) |
| 2026-09-09 | `#798` | §14 인벤토리 함수 수 갱신 — `test_cii_current_db.py`(26 → **30**) · 합계 실측 갱신(1471함수·1790수집 → **1475함수·1794수집**). 프론트엔드도 늘었으나(`realtime-cii/apiProvider.test.ts` +3) §14는 백엔드 pytest만 센다. 고정하는 것은 **⑶ 연말 예상이 「남은 거리 기반」인가**다. 종전 방식(`YTD_DAILY_AVERAGE`)은 지금까지의 일평균을 잔여 기간에 곱해 ⑴에 더했는데, **거리와 연료를 같은 비율로 더하므로 `M/W`가 보존**되어 ⑶이 구조적으로 ⑴과 **항상 같은 값**이 됐다 — 데모 4척 전부에서 실측됐고, 연간 리포트는 같은 숫자를 「누적」과 「연말 예상」 두 제목으로 나란히 인쇄했다(`PRD §3.3.8`의 「구분해 표시」가 성립하지 않았다). ⚠️ **그 이름은 정본에 근거가 없었다** — `YTD_DAILY_AVERAGE`는 `API_SPEC` 응답 **예시에만** 있었고 `PRD §5.1`·사용자 여정은 「남은 거리 기반」을 규정한다. 두 번째 결함은 **같은 이름의 값이 기능③과 달랐던 것**이다(7.654488 vs 8.971119): 실시간 CII는 진행 중 항차를 경과분만 세고 잔여 계획을 무시했고, 기능③은 계획 전량으로 셌다. 그래서 조립을 하나로 모았다 — `load_projection_context`·`collect_annual_inputs`·`project_deterministic`을 두 화면이 **같은 순서로** 부르므로 값이 갈릴 수 없다(`#493`이 실행 경로와 재현 경로에 대해 한 판단과 같다). 「이름을 다르게 붙인다」는 대안은 *같은 질문에 두 답을 준다*는 문제를 그대로 남긴다. ⚠️ **진행 중 항차를 ⑶에서 계획 전량으로 센다**(⑴은 경과 누적을 쓴다) — ⑴의 경과 누적은 측정값이 아니라 시뮬레이션 시계가 **계획 속력·계획 소모율로 만든 모델값**이라 `경과 + 잔여계획 ≈ 계획 전량`이고, 쪼개는 대안은 `RemainingVoyage`를 깎아야 하는데 그 목록이 기능③ **Monte Carlo 표본추출의 입력**이자 스냅샷의 근거다(재현성 `#816`이 열려 있는 경로). **잔여 계획이 0건이면 값을 내되 경고로 성격을 밝힌다** — 빈칸은 「로딩 중」으로 읽히고, 값만 내면 종전 결함(항상 ⑴과 같음)과 구분되지 않는다. 곁가지로 `API_SPEC` 예시의 `risk_level: "WATCH"` 2곳도 고쳤다 — 코드 허용값은 `LOW`·`MEDIUM`·`HIGH`·`CRITICAL` 넷이고 `WATCH`는 저장소 어디에도 없었다 (#798) |
| 2026-09-09 | `#814` | §14 인벤토리 함수 수 갱신 — `test_fleet_summary.py`(39 → **44**) · 합계 실측 갱신(1471함수·1790수집 → **1476함수·1795수집**). 고정하는 것은 **대시보드의 「D등급 진입까지 n일」이 실제로 숫자를 내는가**다. `fleet_summary.py:190`이 `boundaries.get("d")`를 조회했는데 `determine_rating`은 그 키를 만들지 않는다 — 넷뿐이고 전부 `*_boundary` 형태다(`superior`·`lower`·`upper`·`inferior`). 그래서 `boundary is None`이 **항상 참**이라 `#431`이 만든 산식 33줄이 **한 줄도 실행되지 않았고** 사유는 언제나 `NO_DATA`였다. ⚠️ **테스트가 그것을 가렸다** — 픽스처가 `{"d": Decimal("6.0")}`이라는 **엔진이 만들 수 없는 dict**여서, 검사가 자기가 만든 가짜 키를 자기가 읽고 전부 통과했다. 픽스처를 `determine_rating` 출력으로 바꾸니 순수 함수 검사 7건이 즉시 붉어졌다. 올바른 키는 `upper_boundary`(C→D 임계)이며, 리터럴을 새로 쓰지 않고 `NEXT_WORSE_BOUNDARY_KEY["C"]`에서 파생시킨다 — 그 표는 등급 판정 부등식(`attained <= upper` → C)과 짝을 이루는 정본이라, 리터럴을 두면 경계 정의가 바뀔 때 이 파일만 옛 값을 가리킨다. **체크리스트의 「dataclass·Enum으로 바꿀지」는 바꾸지 않기로 판단했다** — `boundaries`는 API 응답과 `calculation_run.result_json`에 그 키 이름 그대로 실리므로 **저장된 JSON을 다시 읽는 경로는 타입이 닿지 않는다.** 대신 `src/`의 `*_boundary` 리터럴 참조를 실제 엔진 출력과 **전수 대조**하는 가드를 넣었다(`#591`·`#641`의 동기화 가드와 같은 방식). 곁가지로 `API_SPEC §2.8`의 사유 표에 `NO_RECENT_DATA`·`NOT_WORSENING` 2행을 보탰다 — `#431`이 만든 사유인데 정본에 옮기지 못했고, **같은 시기에 산식이 실행되지 않아 그 사유가 응답에 나온 적이 없어** 빠진 사실이 드러날 자리가 없었다(결함 둘이 서로를 가렸다). 표와 코드 상수를 양방향으로 대조하고, 그 대조가 새 상수를 놓치지 않도록 모듈의 `REASON_*` 전수와도 맞춘다 (#814) |
| 2026-09-09 | `#822` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`annualRules.test.ts` +9 · `VesselDetail.test.tsx` +3 · `resultRules.test.ts` +4 · 신설 `realtime-cii/warningText.sync.test.ts` 5). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **화면에 나가는 수치·문구 표기**다. ⑴ 민감도 표의 「달성 확률 변화」가 서버 원값(`+0.12`)을 그대로 그려 **100배로 오독**됐다 — 같은 화면 위쪽 지표가 `30.0%`(백분율)라 사용자는 0.12%p로 읽지만 실제는 12%p다. `formatPercent`는 앞의 `+`를 떼어 버리므로 부호를 보존하는 `toSignedPercent`를 만들었고, **표시 결정을 컴포넌트에서 `sensitivityRows`로 옮겼다** — 컴포넌트 안 삼항 연산자는 검사가 닿지 않는 자리였다(돌연변이로 확인: 옮기기 전에는 원값으로 되돌려도 62건이 전부 통과했다). ⑵ 같은 값이 화면마다 다른 자릿수로 떴다 — 시드의 DWT `6405.77`이 등록 결과에서는 `6,405.77`(`toLocaleString`), 선박 관리·상세에서는 `6,406`(`formatCapacity`)이었고, 기준 속력 `18.00`이 상세에서는 `18`, 목록에서는 `18.0 kn`이었다. **`#633`의 수정 대상에서 등록 결과와 선박 상세가 빠져 있었다** — `DESIGN_SYSTEM §4.2`가 그 결함을 이름으로 지목하고 있는데도 그랬다. `VesselDetail`의 리터럴 단위(`" kn"`·`" t"`)도 `DISPLAY_UNITS`로 바꿨다(`§4.2` 🔒가 리터럴을 금지한다). ⑶ 실시간 CII 화면이 `COMPLETED_NO_DISTANCE`를 **영문 대문자 그대로** 렌더했다 — 그 화면의 문구 맵이 7종뿐인데 `?? code`로 폴백했다. ⚠️ **`#630`의 동기화 가드가 `voyage-cii` 한 파일만 봐서** 문구를 내보내는 두 번째 파일이 사각이었다(`#749`와 같은 구조). `warningText`가 정본 전수 전사 맵(`warningMessage`)으로 폴백하게 하고, `§1.6`의 **어느 코드도 원문으로 나가지 않음**을 새 가드가 검사한다. 로컬 맵을 지우지 않은 것은 두 맵의 문구가 2종에서 다르고(`REFERENCE_ONLY`·`COMPLETED_NO_FUEL`) 화면 문구가 `AGENTS §3.2.2`상 디자인 소관이기 때문이다 — 구현이 임의로 통일할 사안이 아니다. `reports/labels.py`는 `test_reports.py`가 이미 전수 대조하고 있어 사각이 아니었다 (#822) |
| 2026-09-09 | `#823` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(신설 `components/ErrorBoundary.test.tsx` 11 · 신설 `components/errorBoundaryWiring.sync.test.ts` 3 · `layout/AppShell.test.tsx` +4). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **렌더 예외가 앱을 백지로 만들지 않는가**다. 앱 전체에 에러 경계가 **0개**였고(`grep`으로 확인), **React 19는 렌더 예외에서 루트를 언마운트**하므로 `#root`가 비어 완전 백지가 됐다 — **새로고침해도 같은 지점에서 다시 던져 복구되지 않고**, 사용자가 빠져나올 길은 URL 직접 입력뿐이었다. 그런데 표시 포매터는 **던지도록 설계돼 있다**: `formatCapacity(1e-7)`·`(1e21)`이 `TypeError`를 낸다(JS가 `1e-6` 미만·`1e21` 이상에서 지수 표기로 전환하는 지점). 재화중량톤수에 `0.0000001`을 넣은 선박이 등록되면(서버는 `Field(gt=0)`뿐이다) 그 선박의 목록·상세가 앱을 통째로 죽였다. ⚠️ **던지는 설계를 고치지 않은 이유**(`#823` 판정): 조용한 폴백은 **틀린 값을 숨긴다** — 실제로 `formatCapacity(0.000001)`은 던지지 않고 **`0`을 낸다**. 경계를 **2겹**으로 둔다: 루트(`main.tsx`, 라우터·셸의 예외까지 받고 라우터가 죽었을 수 있어 `window.location`으로 이동)와 화면(`AppShell`의 `<Outlet>` 주위, **셸이 남아** 사용자가 다른 화면으로 갈 수 있다). ⚠️ **`key={pathname}`이 핵심이다** — 에러 경계는 스스로 리셋되지 않아, key가 없으면 한 화면이 깨진 뒤 **사이드바를 눌러도 오류 화면이 그대로 남는다**(사용자 입장에서 백지와 같다). ⚠️ **컴포넌트 검사만으로는 배선을 증명하지 못한다** — 실제로 `key`를 지워도 컴포넌트 검사 11건이 전부 통과했다. 그래서 `AppShell.test.tsx`가 **진짜 셸에 던지는 화면을 물려** 셸 생존·경로 전환 회복을 본다. `main.tsx`는 진입점이라 어떤 검사도 import하지 않으므로(루트 경계를 통째로 지워도 1162건이 전부 통과했다) **소스 대조 가드**를 별도로 뒀다 — `screens.test.ts`의 `isComingSoonStub()`이 페이지 소스를 읽는 것과 같은 방식이다 (#823) |
| 2026-09-09 | `#755` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(신설 `realtime-cii/RealtimeCiiView.test.tsx` 7). §14는 백엔드 pytest만 센다. 고정하는 것은 **폴링이 실패해도 값이 화면에 남는가**다. 60초 폴링이 **한 번** 실패하면 YTD·등급·항차 기여도·연말 예상이 **전부 사라졌다** — 코드 주석은 정반대를 적고 있었다(*「폴링 중 실패는 화면을 비우지 않는다 … 최초 로드 실패만 화면을 대체한다」*). 원인은 `setInterval`이 **마운트 시점의 `load`를 캡처**하는 것이다: 그 클로저에 담긴 `data`는 첫 렌더의 `null`이고 이후 값이 들어와도 **그 클로저 안에서는 영원히 `null`**이라, `if (data === null)` 판정이 **항상 참**이 되어 폴링 실패가 최초-로드 실패로 처리됐다. `oxlint`가 못 잡은 것은 그 effect에 `exhaustive-deps` 억제 주석이 붙어 있었기 때문이다. 판정을 **`setData`의 함수형 갱신 안**으로 옮겨 `load`의 상태 의존을 없앴다 — React가 주는 `prev`는 항상 최신값이라 클로저 나이와 무관하고, **억제 주석 두 개를 모두 제거**할 수 있다(ref에 최신 `load`나 `data`를 담는 대안은 같은 사실이 상태와 ref 두 곳에 있게 만든다). 함께 넣은 것이 **갱신 실패 표시**다 — 값을 남기는 것과 **값이 최신인 척하는 것**은 다르고, 이 화면은 「항해 중 CII가 변하는 것을 보여 주는」 자리(`UIFLOW 2-9`)라 그 침묵이 특히 나쁘다. ⚠️ **이 기능에는 컴포넌트 렌더 검사가 없었다** — `apiProvider.test.ts`·`realtimeRules.test.ts`가 전부 순수 함수인데, 결함이 **타이머와 클로저 사이**에 있어 순수 함수 검사로는 원리적으로 드러나지 않는다(`#823`과 같은 구조). 가짜 타이머로 60초를 돌려 이슈의 재현 절차를 그대로 재현하고, 최초 로드 실패는 여전히 오류 패널을 내는지·`notFound`면 대시보드 CTA가 붙는지·탭이 숨으면 요청하지 않는지도 함께 본다 (#755) |
| 2026-09-09 | `#754` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(신설 `account/AccountPanel.test.tsx` 8 · 신설 `auth/canonicalNotice.sync.test.ts` 3 · `auth/session.test.ts` +5). §14는 백엔드 pytest만 센다. 고정하는 것은 **탈퇴 화면이 존재하고 정본 문구를 그대로 쓰는가**다. 서버(`DELETE /auth/me`)·정본(`API_SPEC §1.2`·`§12` · `PRD §5.1` MUST · `§6.3` 확정 문구)·`UIFLOW 2-6`이 전부 갖춰졌는데 **화면만 없었다** — `PRD §6.3`이 원문까지 확정한 탈퇴 문구를 쓰는 코드가 저장소에 **한 곳도 없었다**(`grep`으로 확인). 그 사이 **이메일을 바꿀 유일한 경로가 막혀 있었다**: 같은 화면이 *「다른 주소를 쓰려면 탈퇴 후 다시 가입해 주세요」*라고 안내하는데 탈퇴할 수가 없었다. ⚠️ **정본 문구에 소비처가 0인 것을 잡는 자리가 없었다** — `AGENTS §4.6`이 「정본 문구」와 「표시 문구」를 구분하는데 그 규칙을 확인하는 검사가 없어서, 다음에 화면을 만드는 사람이 문구를 못 찾고 **새로 적을** 여지가 그대로 남아 있었다. `canonicalNotice.sync.test.ts`가 `PRD §6.3` 표를 읽어 **문자 단위로** 대조한다(`digits.sync.test.ts`가 `DESIGN_SYSTEM §4.2` 표를 읽는 것과 같은 방식). 종전부터 있던 `EMAIL_IMMUTABLE_NOTICE`도 **대조된 적이 없어** 함께 잠갔다. ⚠️ **화면 검사가 실제 구현을 증명하지 못한다** — `AccountPanel.test.tsx`는 `deleteAccount`를 대역으로 바꾸므로, 실패 처리를 되돌려도 18건이 전부 통과했다. `session.test.ts`에 실제 계약을 따로 잠갔다: **실패하면 던지고 캐시를 비우지 않는다**(`logout`과 반대다 — 실패한 채 로그인 화면으로 보내면 사용자는 탈퇴됐다고 믿는데 계정이 살아 있다) (#754) |
| 2026-09-09 | `#863` | §14 인벤토리 함수 수 갱신 — `test_ytd_cii_service_db.py`(20 → **21**) · 합계 실측 갱신(**1502함수·1848수집** — 직전 수치(#811 행) 이후 오늘 머지분의 증가를 함께 흡수). 고정하는 것은 **CF 개정이 지난 실적을 소급해 바꾸지 않는가**다(PRD §8.4). 항해 연료 집계가 유종만으로 톤수를 합하고 CF는 「가장 최근 행」 하나로 덮어, 같은 유종에 스냅샷이 둘 이상이면 개정 CF가 개정 전 항차에까지 곱해졌다 — 재현: HFO 620t(CF 3.114)+100t(CF 3.500)에서 정본 2,280.68t 대신 2,520.00t(과대 10.49%). 같은 파일 모듈 docstring은 반대를 선언하고 있었고 not under way 쪽(#378/030)만 올바르게 `(fuel_type, cf_used)`로 묶어 두 갈래가 같은 규정을 정반대로 구현하고 있었다. 수정은 서비스 `_aggregate` 한 곳 — 엔진(`ytd_engine`)은 애초 스냅샷별 `FuelUse` 목록을 받아 각자 곱하도록 만들어져 있었다(호출부 주석이 그렇게 선언). ⚠️ **새 검사는 not-under-way 쪽 쌍(`test_mixed_cf_snapshots_each_use_their_own_value`)이 이미 있음을 확인하고 만들었다** — 그 검사는 `not_underway_co2_g`만 봐서 항해 쪽 뭉개짐을 못 잡았다. 진행 중 항차 주입분(#368)은 스냅샷이 없어 **현재 활성 CF의 별개 묶음**으로 분리했다 — 종전에는 같은 유종의 마지막 스냅샷 CF를 상속했는데, 진행 중 항차는 현재 계산이라 PRD §8.4상 현재 CF가 맞다. 돌연변이 검사: 수정을 stash로 제거하면 새 검사가 실패하고 복원하면 통과한다 (#863) |
| 2026-09-09 | `#832` | §14 인벤토리 함수 수 갱신 — `test_annual_simulation_api_db.py`(20 → **21**) · 합계 실측 갱신(1502함수·1848수집 → **1503함수·1849수집**). 고정하는 것은 **CF 개정 뒤 새로 실행한 계산이 계획 항차를 새 CF로 예측하는가**다(PRD §8.4 「변경 이후 계산에만 적용」 — ⓐ 구현 버그 판정). 종전 구현은 CF를 항차 생성 시점에 행에 박아 기능③이 `fuel_type` 테이블을 아예 읽지 않았다 — 개정 뒤 연말 예상이 옛 계수로 나가 아직 일어나지 않은 배출의 예측이 현행 규제 기준이 아니었다. 수정은 스냅샷 빌드 한 곳 — PLAN 묶음의 CF를 실행 시점 활성 CF로 기록하고(#378의 「그때 쓴 값」 기록이 그대로 재현성이 된다), 확정 실적은 #863과 같이 행 기록을 유지한다. ⚠️ **#812의 행-수 불변 검사가 깨졌다** — 두 입력을 「같은 CO₂」로 맞춘 전제가 임베디드 CF 기준이었는데 가스오일 활성 CF(3.206)가 개입해 471.7 vs 467.1로 갈렸다. 검사 의도(#812: 행 수가 거리·M을 부풀리나)를 유지하기 위해 활성 CF를 3.114로 고정해 행 수만의 효과를 분리했다. 정본 3곳 동반 개정 — `PRD §8.4` 행 명시 · `DB_SCHEMA §2.3` `cf_used` 역할 재정의 · `voyage.py` 주석의 잘못된 §8.4 인용 정정 (#832) |
| 2026-09-09 | `#864` | §14 인벤토리 함수 수 갱신 — `test_fleet_summary.py`(44 → **45**) · 합계 실측 갱신(1503함수·1849수집 → **1504함수·1850수집**). 고정하는 것은 **「D등급까지 n일」의 30일 전 기준선에도 그 시점의 진행분이 들어가는가**다. 현재값에는 진행 중 항차의 연초부터 누적이 들어 있는데 기준선 호출(`fleet_summary.py`의 `past`)에 `in_progress` 인자가 없어, 그 전체가 30일 창의 증가분으로 계상되어 n일이 실제보다 몇 배 짧아졌다 — 재현: foc 30t/일 · 14kn 진행 항차에서 올바른 기준선은 수백 일, 결함 기준선은 수십 일. ⚠️ **재현 데이터를 만드는 데 세 번 걸렸다** — ⑴ 시계가 유종 코드를 선박 `default_fuel_type`에서 가져오므로 이를 빼면 기여분이 None ⑵ attained가 D 진입 경계를 넘으면 `ALREADY_AT_OR_BELOW` ⑶ 외삽 일수가 연말을 넘으면 `NOT_THIS_YEAR` — 셋 다 값이 None이라 실패 메시지만으로는 원인이 가려진다. 결함 기준선의 증상도 두 갈래다(겉소비율이 경계 아래로 내려가 `NOT_WORSENING`으로 값 소실 / 증가분 전량 계상으로 과대 짧은 n일) — 단언이 둘 다를 받는다. 돌연변이 검사: 수정을 stash로 제거하면 새 검사가 실패하고 복원하면 통과한다 (#864) |
| 2026-09-09 | `#865` | §14 인벤토리 함수 수 갱신 — `test_voyages_api.py`(25 → **28**) · 합계 실측 갱신(1504함수·1850수집 → **1507함수·1853수집**). 고정하는 것은 **확정된 항차의 계획값·귀속 연도를 PATCH로 못 바꾸게 막는 가드**다. 종전 구현은 상태 가드·필드 화이트리스트·무효화 호출이 셋 다 없어, CONFIRMED 항차의 `planned_distance_nm`을 99999로 · `regulation_year`를 2024로 바꾸면 200 OK로 통과하고 그 해 YTD가 움직였다(재현: 8.098405 → 8.366563). 시나리오 반영(`#580`)은 같은 필드를 `PLANNING_STATUSES`로 이미 막고 있었으므로 상수를 `services/voyage.py`로 모아 두 경로가 같은 기준을 쓰게 했다. 허용되는 계획값 변경에는 `mark_calculations_needing_recalc`를 호출한다 — `PRD §8.4` 무효화 규정의 호출 규약이며 `calculation_run.voyage_id`가 NULL인 #817 때문에 지금은 no-op이다. 가드 대상에서 항구명·좌표·notes는 뺐다 — 계산 입력이 아니어서 확정 항차의 정정 메모까지 막을 이유가 없다. 돌연변이 검사: 가드를 stash로 제거하면 새 검사 2건이 실패하고 복원하면 통과한다 (#865) |
| 2026-09-09 | `#866` | §14 인벤토리 **함수 수·합계 변화 없음**(1507함수·1853수집 유지) — 새 검사를 만들지 않고 `test_ytd_definition_sync_db.py`의 대조 경로를 **넷에서 다섯으로** 넓혔다(`_four_paths` → `_all_paths`, `test_four_paths_report_the_same_ytd` → `test_all_paths_report_the_same_ytd`). 고정하는 것은 **항차 완료 리포트의 「연간 누적」이 나머지 경로와 같은 YTD인가**다. `compute_ytd_cii` 호출부 5곳 중 `report.py:244` 하나만 `as_of`·`in_progress`를 넘기지 않아, 같은 라벨의 값이 리포트 1,930.68 t · 화면 2,495.46 t로 **29% 갈렸다** — `#750`이 네 경로를 통일할 때 남은 누락분이다. ⚠️ **이 파일이 그것을 못 잡은 이유**는 리포트 쪽에서 `build_annual_report`(연간 실적)만 보고 `build_voyage_report`(항차 완료)를 안 봤기 때문이다 — 전자는 `get_current_cii`를 거쳐 진행분을 포함하고 후자만 `compute_ytd_cii`를 직접 부른다. **경로를 빠뜨리면 그 경로는 「각자는 통과하는」 상태로 남는다**는 것이 이 파일의 존재 이유인데 그 함정에 스스로 걸렸다. 직접 회귀 검사를 `test_reports_db.py`에 따로 만들지 않은 것은 의도다 — 경로 사이의 불일치는 나란히 놓고 봐야 잡히고, 중복 검사는 어느 쪽이 정본인지 흐린다. 돌연변이 검사: `report.py` 수정을 stash로 제거하면 `test_all_paths_report_the_same_ytd`가 실패하고 복원하면 통과한다 (#866) |
| 2026-09-09 | `#867` | §14 인벤토리 함수 수 갱신 — `test_cii_current_db.py`(30 → **31**) · 합계 실측 갱신(1507함수·1853수집 → **1508함수·1854수집**). 고정하는 것은 **연료 행 하나를 고쳐도 진행 중 항차의 대표 유종이 바뀌지 않는가**다. `voyage_repo.list_fuel_uses`에 `ORDER BY`가 없어 PostgreSQL이 힙 순서를 줬고, 소비처(`_voyage_fuel_code`)가 「첫 항목」에 의존하므로 **행 하나를 UPDATE하는 정상 조작만으로** 대표 유종이 뒤집혀 CO₂ 기여가 튀었다 — 돌연변이 검사에서 실제로 `HFO`(CF 3.114) → `DIESEL_GAS_OIL`(3.206)로 바뀌는 것을 재현했다. 형제 저장소(`not_underway.list_fuel_uses:270`)는 처음부터 `.order_by(consumer_type, fuel_type)`을 명시하고 있었고 **항차 쪽만 빠져** 있었다. `list_fuel_uses_by_voyage_ids`에도 같은 정렬을 넣었다 — 한쪽만 정렬하면 같은 항차의 `fuel_uses`가 단건 조회와 목록 조회에서 다른 순서로 나온다. 2차 키를 `id`로 둔 것은 `idx_fuel_use_unique`가 `(voyage_id, fuel_type)`이라 같은 유종이 둘일 수 없어도 인덱스가 바뀌면 순서가 다시 미정이 되기 때문이다. ⚠️ **「어느 유종이 대표여야 하는가」는 이 검사의 범위 밖이다** — 정본에 규칙이 없음을 확인하고(PRD·TECH_SPEC·API_SPEC·DB_SCHEMA grep 0건) 사용자 판정으로 `#885`(계획 비율 안분)로 분리했다. 여기서 고정하는 것은 **같은 데이터가 같은 답을 내는가**뿐이다 (#867) |
| 2026-09-09 | `#868` | §14 인벤토리 함수 수 갱신 — `test_mail.py`(18 → **21**) · 합계 실측 갱신(1508함수·1854수집 → **1511함수·1867수집**). 고정하는 것은 **`SMTP_USE_TLS`의 모르는 값이 기동을 막는가**다. 종전 `_as_bool`은 참으로 읽는 목록(`1`·`true`·`yes`·`on`)에 없으면 **전부 거짓**이었다 — `enabled`·`Y`·`TLS` 같은 값이 오류도 경고 로그도 없이 「끔」이 되어 SMTP 자격증명과 **비밀번호 재설정(1시간)·이메일 인증(24시간) 토큰 링크 전문**이 평문으로 나갔다. ⚠️ **메일은 정상 도착하므로 배포 후에도 드러나지 않는다** — `#809`가 링크 생성 경로를 막은 뒤 남아 있던 전송 경로의 구멍이다. 같은 파일의 `MAIL_BACKEND`(`_VALID_BACKENDS` 대조 후 `RuntimeError`)·`SMTP_PORT`(`int()` 실패 시 `RuntimeError`)는 이미 모르는 값을 거부하고 있었고 **보안 스위치 하나만 fail-open**이었다 — 모듈 docstring이 선언한 「프로덕션에서 조용히 개발용 기본값으로 폴백하지 않고 기동 시점에 실패한다」를 그 줄이 깨고 있었다. ⚠️ **`false`는 정당한 선택이라 막지 않는다**(465 포트 implicit TLS): 「거짓으로 읽는 값」(`0`·`false`·`no`·`off`)을 따로 두고 **그 목록에도 없는 것만** 거부한다. 미설정·빈 값은 안전한 쪽(켬)으로 떨어지는 것도 함께 고정했다. `.env.example`에 허용값 여덟 개와 「그 밖의 값은 서버가 뜨지 않는다」를 명기했다. 돌연변이 검사: 수정을 stash로 제거하면 7건이 실패한다 (#868) |
| 2026-09-09 | `#869` | §14 인벤토리 함수 수 갱신 — `test_audit_actions_db.py`(5 → **7**) · 합계 실측 갱신(1511함수·1867수집 → **1513함수·1869수집**). 고정하는 것은 **기능③ 실행과 재현 검증이 감사 로그에 남는가**다. `TECH_SPEC §13.1`은 「**모든** `CalculationRun` 생성 시」로 적고 `calculation_type` 행에 `ANNUAL_DETERMINISTIC`·`ANNUAL_MONTE_CARLO`를 **명시**하는데, `routes/annual_simulations.py`는 `calculation_run` 행을 실제로 만들면서(서비스의 raw INSERT, `annual_simulation.py:1139`) 감사 기록만 빠뜨렸다 — `grep record_calculation_run src/`가 기능①(`calculations.py:129`)·②(`scenarios.py:71`)만 짚었다. **세 기능 중 가장 무거운 계산의 실행 이력이 없었고 사후 복구가 불가능했다.** ⚠️ **재현 검증(`§6.4`)은 새 `calculation_run` 행을 만들지 않고 원본의 `run_id`를 그대로 쓴다** — 표식이 없으면 감사 로그에서 두 실행이 같은 모양이 되어 「재현 검증을 언제 돌렸나」에 답할 수 없다. `record_calculation_run`에 `details_extra`를 열어 `reproduced: true`를 덧붙였다. 같은 스트림에 변형을 플래그로 구분하는 것은 **§13.1 자신의 방식**이다(스텁 dev-login이 `dev_login`으로 구분된다). 표의 필드는 덧붙인 키가 덮을 수 없게 뒤에 병합한다. ⚠️ **정리 코드가 두 번 막혔다** — `simulation_snapshot`·`calculation_run`이 트리거로 보호된 **불변 테이블**이라(`immutable table`, `#493`·`#277`) 검사가 지울 수 없다. 위의 `test_calculation_run_records_hashes`도 같은 이유로 `audit_log`만 치우고 있었다 — 불변이 의도인 테이블을 검사가 우회할 이유가 없어 같은 선례를 따랐다. 돌연변이 검사: 라우트 배선을 stash로 제거하면 신규 2건이 실패한다 (#869) |
| 2026-09-09 | `#870` | §14 인벤토리 함수 수 갱신 — `test_annual_simulation_api_db.py`(21 → **24**) · 합계 실측 갱신(1513함수·1869수집 → **1516함수·1876수집**). 고정하는 것은 **모르는 분포 프로파일이 거부되는가**다. `api/schemas/annual_simulation.py:30`이 `distribution_profile`을 `Field(max_length=30)`으로만 받아 열거·존재 검증이 없었고, 저장소가 없는 프로파일에 **빈 목록**을 돌려주면 `profile_from_rows([])`가 상수 기본값으로 조용히 폴백해 **200으로 통과**했다. 그런데 응답의 `parameters_used.simulation_profile.profile`에는 **사용자가 보낸 이름이 그대로** 실려, 「보수적 분포」를 고른 줄 아는 목표 달성 확률·P10/P50/P90이 사실은 기본 분포 값인데 화면은 고른 이름을 보여 준다 — **오인을 확인할 방법이 없다.** 마이그레이션 035가 심는 프로파일은 `DEFAULT` 하나뿐이라 `CONSERVATIVE`·소문자 `default`·오타가 전부 이 경로를 탔다. ⚠️ **가드를 「행 0건」에만 건 것이 핵심이다** — 변수 한 줄이 빠진 것은 「프로파일이 없다」가 아니라 「행 하나가 비었다」이고, 그때는 종전대로 그 변수만 기본값으로 채운다(`profile_from_rows` docstring). 구분하지 않으면 운영자가 행 하나를 비활성화하는 순간 기능③이 통째로 멈춘다 — 속도 행만 끄고 나머지 2행으로 정상 실행되는지를 검사로 고정했다. 판단 위치는 저장소가 아니라 서비스다(`load_distribution_profile` docstring이 *「기본값이 없다」를 오류로 만들지 판단하는 것은 서비스의 몫*이라 적는다). 재현 경로(`:1422`)는 손대지 않았다 — 그쪽 입력은 사용자가 아니라 저장값이고, 파라미터 변화는 `parameter_hash` 대조가 이미 잡는다. 모르는 선종을 422로 거부하는 `services/parameters.py:52-64`와 같은 판단이다. 돌연변이 검사: 가드를 stash로 제거하면 5건이 실패한다 (#870) |
| 2026-09-10 | `#872` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`display/format.test.ts` +6 · `realtime-cii/RealtimeCiiView.test.tsx` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **출항 직후 극소 진행률이 화면을 죽이지 않는가**다. `RealtimeCiiView.tsx`가 `formatPercent(String(ratio))`로 그렸는데 `ratio`는 JSON number이고, 자바스크립트는 `1e-6` 미만에서 **지수 표기로 전환**한다 — `String(5e-7)`은 `"5e-7"`이라 십진 문자열만 받는 포매터가 `TypeError`를 냈고, **React 19는 렌더 예외에서 루트를 언마운트**하므로 화면이 통째로 백지가 됐다(`#823`이 에러 경계를 넣기 전에는 새로고침해도 복구되지 않았다). 계획 거리 1만 nm 이상 항차의 출항 직후가 정확히 그 구간이다. ⚠️ **같은 패턴이 이슈가 지목한 2곳이 아니라 7곳이었다** — 실시간 CII 진행률 · 항로 비교 거리·속력 · 선박 목록 속력·일일연료 · 대시보드 n일 · 기능① 항해거리. 그중 선박 제원 2곳과 시나리오 거리는 서버가 `Field(gt=0)`뿐이라(`#860`) `1e-7`이 실제로 저장·표시될 수 있다. 다리(`toDecimalInput`)를 `display/format.ts`에 두고 일곱 곳에 적용했으며, 같은 규율을 자체 구현하던 `not-underway/periodRules.ts`의 중복도 걷어 공용으로 바꿨다 — **복사하면 한쪽만 고쳐진다**(`display/decimal.ts`가 `#820`에서 기능 폴더 밖으로 옮겨진 것과 같은 이유). ⚠️ **`formatCapacity`는 일부러 두었다** — `#823`이 *"조용한 폴백은 틀린 값을 숨긴다 — 실제로 `formatCapacity(0.000001)`은 던지지 않고 `0`을 낸다"*를 근거로 **던지는 설계를 유지하기로 판정**했고, 여기에 다리를 놓으면 `1e-7` DWT가 `0`으로 표시되어 그 판정을 뒤집는다. 입력 하한은 `#860`이 서버에서 막는다. `1e21` 이상은 `toFixed`도 지수 표기를 내므로 다리를 지나도 던진다는 것을 검사로 명시했다 — 그 경계는 값이 아니라 입력 상한의 문제다. ⚠️ **순수 함수 검사만으로는 배선이 증명되지 않아**(`#823`·`#755`가 각각 겪은 함정) 실제 화면을 그리는 검사를 함께 뒀다. 돌연변이 검사: 다리를 `String()`으로 되돌리면 그 렌더 검사가 실패한다 (#872) |
| 2026-09-10 | `#876` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`vessel-detail/VesselDetail.test.tsx` +4). §14는 백엔드 pytest만 센다. 고정하는 것은 **등급이 없어도 누적값이 보이는가**다. 선박 상세의 YTD 카드 게이트가 `current?.dataAvailable && current.rating`이라, 서버가 실적·기준·항차 수를 다 줬는데 **등급 하나가 null이면 그 전부를 버리고** 「올해 등록된 항차 실적이 없습니다」를 냈다 — 실적이 있는데 없다고 말하므로 사용자는 항차를 다시 등록하려 한다. ⚠️ **등급 null은 비정상이 아니다** — `API_SPEC §2.7`이 `rating: string | null`로 규정하고 `#834`(RO_RO 여객선 고속선의 등급 경계 누락)가 그 조건을 실재시킨다. 게다가 카드 **안쪽은 이미 각 값의 null을 `—`로 세심히 처리**하고 있었고(`attainedCii`·`requiredCii`), `GradeBadge`도 null을 「없음」 변형으로 그린다 — **바깥 게이트가 그 처리를 전부 무효화**하고 있었다. 게이트를 `dataAvailable` 하나로 좁히고 배지 라벨만 null 분기를 더했다(`올해 누적 등급 없음`). ⚠️ **검사 단언을 두 번 고쳤다** — ⑴ 같은 값이 연도별 이력 표에도 나와 `getByText`가 중복으로 실패했고(YTD 카드로 범위를 좁혔다) ⑵ 배지 라벨도 이력 표에 있어 대기 기준으로 쓸 수 없었다(`waitFor`로 카드 요소 자체를 기다린다). 화면에 같은 값이 두 번 나오는 자리에서는 **범위를 좁히지 않은 단언이 구현이 아니라 검사를 깨뜨린다.** ⚠️ **`npm run build`가 타입 오류를 잡았다** — 픽스처를 리터럴로 두어 `attainedCii`가 `string`으로 추론됐고, 「데이터 없음」 검사에서 `null`로 덮을 때 `TS2322`가 났다. **vitest 1200건은 그대로 통과했다** — 타입 검사는 `npm run build`만 한다. `CiiYear`로 명시해 해소했다. 돌연변이 검사: 게이트를 되돌리면 2건이 실패한다 (#876) |
| 2026-09-10 | `#875` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`scenario-comparison/ScenarioComparison.test.tsx` +5). §14는 백엔드 pytest만 센다. 고정하는 것은 **화면의 숫자와 제목이 같은 계산을 가리키는가**다. 항로 비교 제목이 살아 있는 `form.vesselId`·`form.regulationYear`를 읽고 숫자만 계산 시점 스냅샷(`response`)을 읽어, 결과를 본 뒤 상단바에서 배를 바꾸면 **A선의 계산 결과 위에 B선의 이름**이 붙었다(연도도 같다 — 「2027년 기준」 제목 아래 2026년 계산이 남는다). 원인 경로는 셸→폼 동기화 효과다: 상단바 선택이 `form`에 즉시 반영되는데 `response`는 그대로다. ⚠️ **`#821`이 같은 제목 줄에 넣은 검사 2건이 이 결함을 못 잡았다** — 계산 **직후**의 제목만 봤기 때문이다. 두 출처가 우연히 같은 값을 가리키는 순간만 보면 어긋남은 영영 드러나지 않는다. 성공 상태에 `ResultSnapshot`(선박명 + 계산에 쓴 조건 전부)을 응답과 **같은 자리에** 담아 제목이 그것을 읽게 했다 — 「제목만 따로 조심한다」로 두면 다음에 추가되는 표시값에서 같은 결함이 되풀이된다. 스냅샷은 응답 시점이 아니라 **제출 시점**에 뜬다(계산이 도는 동안에도 상단바를 바꿀 수 있다). 제목을 고정하면 이번에는 결과와 폼이 어긋난 상태가 남으므로 `#727` 선례대로 **「결과가 낡음」 표시**를 함께 넣었다 — 판정은 폼 **전 필드**를 본다(선박·연도만 보면 거리·연료만 고쳤을 때 안내가 빠진다). ⚠️ **`sameInputs`를 복사하지 않고 형태만 열었다** — `voyage-cii/formRules.ts`의 그 함수는 키를 열거하지 않아 폼에 칸이 늘어도 자동 포함되는데, 복사하면 그 규율이 한쪽에서만 유지된다(`#820`·`#872`와 같은 판단). ⚠️ **`npm run build`가 또 타입 오류를 잡았다** — 제네릭 제약을 `Record<string, string>`으로 두었더니 두 폼 상태가 모두 `interface`라 인덱스 시그니처가 없어 `TS2345`가 났다. **vitest 1205건은 그대로 통과했다.** `Record<keyof T, string>`으로 바꿔 해소했다. 흐림 처리도 기능①을 그대로 베끼지 않았다 — 이 화면은 제목과 선박명·연도가 **같은 `<header>` 안**에 있어 직계 자식만 걸면 정작 어긋나는 그 줄이 흐려지지 않는다. 돌연변이 검사: 스냅샷을 `form`으로 되돌리고 `stale`을 `false`로 고정하면 4건이 실패한다 (#875) |
| 2026-09-10 | `#874` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`realtime-cii/RealtimeCiiView.test.tsx` +4). §14는 백엔드 pytest만 센다. 고정하는 것은 **선박 전환 직후 화면이 이전 선박의 어떤 값도 보여 주지 않는가**다. `/vessels/:vesselId/voyages/:voyageId`는 라우트 파라미터만 바뀌므로 **언마운트 없이 선박이 전환되는데** 이 화면은 그 전환을 전혀 몰랐다 — ⑴ A선의 이름·등급이 B선의 URL 아래 그대로 남고(「불러오는 중」은 두 번째 선박부터 영영 뜨지 않는다) ⑵ 늦게 도착한 A의 폴링 응답이 `setData(A)`로 B의 화면을 덮으며(다음 폴링까지 60초간 복구 없음) ⑶ A의 404 오류 패널이 B에서 유지됐다. ⚠️ **`VesselDetail.tsx`의 「effect 안 `let alive`」 선례를 그대로 쓸 수 없다** — 그 방식은 요청을 **그 effect가 시작한 경우에만** 덮는데, 이 화면은 60초 폴링이 effect 밖에서 `load`를 부르고 `clearInterval`은 **이미 날아간 요청을 취소하지 않는다.** 그래서 소유권을 ref 하나(`generationRef`)에 두고, 리셋 effect가 세대를 올리며 `load`가 시작 시점의 표를 응답 시점에 대조한다. `vesselId` 자체를 비교하지 않는 것은 **A → B → A 왕복** 때문이다 — 그때 첫 A의 인플라이트 응답은 `vesselId`가 같아 통과하지만 더 오래된 값이다. ⚠️ **첫 검사 판본 5건 중 2건만 돌연변이 검사에서 실패했다.** 오류 패널 검사가 새 선박의 응답을 **곧바로** 돌려줘, 성공 경로의 `setFailure(null)`이 패널을 어차피 지웠다 — 결함이 보이는 창은 **전환 직후 응답 전까지**인데 그 창을 만들지 않았다. 응답을 늦춰 다시 박았다(3건 실패). 폴링 대상 검사는 **고정되지 않음을 명시**했다(`load`가 `vesselId` 의존이라 리셋 없이도 새 선박을 조회한다) — `#755`의 클로저 회귀를 잡는 용도로 남긴다. `BackLink`도 URL 기준으로 바꿨는데 **이쪽은 독립적으로 고정되지 않는다**: 리셋이 「`data`와 URL이 어긋나는 상태」 자체를 도달 불가로 만들기 때문이다. 격리 돌연변이: 가드만 제거 → 경합 1건 실패 · 리셋만 제거 → 3건 실패 (#874) |
