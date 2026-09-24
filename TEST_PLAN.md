# TEST_PLAN — BlueLog

| 항목 | 내용 |
|---|---|
| 문서명 | TEST_PLAN.md |
| 버전 | v1.30 |
| 상태 | Oracle Review + 외부 리뷰 반영 + Layer 1 픽스처 정본값 규칙 반영 (#166) + v1.4에서 §1.3 케이스 스키마 기호 표기 전환 (#46) + §4.7 인증 API 케이스 (#279) + **v1.6에서 방향 전환 반영 — 신규 서브시스템 5절 · §14 파일 인벤토리 · §11 실측 정정 (#394)** + **§3.25~3.27 신설 · §10 실CI 재작성 · §14.3~14.5 갱신 (#1104 · #1081)** + **§4.11 올해 누적 CII 추이 API (#1671)** + **§3.28 해상 경로망 (#1300)** |
| 최종 수정일 | 2026-09-24 |
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
  conftest.py                           # 공용 fixture — §1.6 참조 (DB 마이그레이션·연결·JSON 로더) [ORACLE-M-5]
  fixtures/
    cii/
      bulk_50000_hfo_2026.json          # Fixture 1
      rating_boundaries_bulk_2026.json  # Fixture 2
    csv/
      voyage_import_sample.csv          # 항차 CSV 가져오기 (§8.2)
    simulation/
      annual_seed_12345_input.json      # Fixture 3
      annual_seed_12345_expected.json
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
> **[ORACLE-C-1b]** `ratio_to_required` 값을 `0.987585`에서 `0.987579`로 정정. 기존 `0.987585`는 산술 오류. PRD §14.2 응답 예시 `0.98757`과 같은 원값(`0.98757869…`)에서 나온다 — 종전 인용 `0.98758`은 반올림값이었고, `#1714`(`#1600`)가 비율도 전송 자릿수로 **절사**하면서 PRD 예시의 끝자리가 내려갔다(`TECH_SPEC §1.2.1`). 6자리 유효숫자 `0.987579`와 등급 `C`는 그대로다.
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

> ⚠️ **이 절의 파일은 만들어지지 않았다** (`#1666` 확인 · 2026-09-23). `tests/fixtures/capacity/`는 저장소에 없고, 아래 JSON을 읽는 코드도 없다 — 문자열 `capacity_separation`이 나오는 곳은 **이 문서 자신뿐**이다.
>
> **대신 `tests/test_capacity_rules.py`(19함수)가 같은 것을 인라인 값으로 검증한다.** 300,000 DWT 벌크선의 transport capacity(실제 DWT)와 reference capacity(`fixed 65000`)가 갈리는지를 값으로 단언하며, 픽스처 파일을 거치지 않는다.
>
> **아래 JSON은 그 규칙의 설명으로 남긴다** — 값이 `§1.2`·`§1.3`처럼 파일과 대조되는 정본값이 아니라, **무엇을 가르는가**를 적어 둔 예시다. 파일을 만들 이유가 생기면(다른 언어 구현이 같은 값을 읽어야 할 때) 그때 이 블록에서 만든다.

**파일**: `tests/fixtures/capacity/bulk_300k_capacity_separation.json` (미생성 — 위 각주)

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

**파일**: `tests/fixtures/capacity/lng_50k_capacity_separation.json` (미생성 — 위 각주)

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

### 1.6 픽스처와 테스트 격리 [ORACLE-M-5] [#1583]

`tests/conftest.py`에 **실제로 있는** 픽스처·도우미만 적는다. 아래 표 첫 열의 이름은 `tests/test_testplan_fixture_names.py`가 `conftest.py`의 정의와 대조한다 — 이름을 바꾸거나 지우면 여기서 걸린다.

| 이름 | 종류 · 범위 | 하는 일 |
|---|---|---|
| `migrated_db` | 픽스처 · session | 세션 시작 때 head까지 `alembic upgrade`하고 데모 데이터를 **멱등**으로 적재한다(`ON CONFLICT DO NOTHING`) |
| `conn` | 픽스처 · function | 검사마다 연결을 열어 `begin()`하고 **끝나면 무조건 `rollback()`** 한다 — 서비스·저장소를 직접 부르는 검사의 기본 격리다 |
| `app_fresh_engine` | 픽스처 · function | `TestClient` 검사용 `NullPool` 엔진으로 앱의 엔진을 갈아 끼운다. **라우트가 실제로 커밋**하므로 검사가 스스로 행을 지운다 |
| `load_fixture` | 픽스처 · session | `tests/fixtures/` JSON 로더(구현 `tests/fixture_loader.py`) |
| `require_disposable_target` | 도우미 | DB를 여는 모든 자리(`run_alembic` · `migrated_db` · `app_fresh_engine`)가 먼저 부른다 — 대상이 `_test`로 끝나는 버려도 되는 DB가 아니면 **fail**(`#691`) |
| `_hold_suite_lock` | 도우미 | 스위트가 도는 동안 **대상 DB 단위 파일 잠금**(`fcntl.flock`)을 쥔다. 겹쳐 돌면 두 번째 실행이 종료 코드 3으로 끝난다(`#894` · `#1250`) |

**정리 방식이 둘이다.** `conn`은 롤백으로 끝나 흔적이 없고, `app_fresh_engine`을 쓰는 검사는 라우트가 커밋한 행을 스스로 지운다.

> **커밋하는 검사를 롤백으로 바꾸지 않는다** (`#1250` · 결정요청 v6 `D-18`). `TestClient` 검사를 SAVEPOINT 롤백으로 감싸면 빨라지지만, **운영과 같은 커밋 경로**를 더는 지나지 않는다. 이 저장소의 결함 상당수가 「검사는 초록인데 운영이 깨진다」였고, 커밋을 실제로 하는 검사가 그런 결함을 잡아 왔다(`src/cii_platform/db/session.py`의 CUBRID 파라미터 변환기 사례) — 충실도를 속도보다 앞에 둔다. 연결 루프가 갈려 한 번에 묶는 방식은 실측으로도 실패했다(`#1315`).

> **실행 잠금의 한계** — 같은 파일 시스템의 실행끼리만 막는다. 호스트의 pytest와 컨테이너 안의 pytest가 같은 DB를 쓰는 겹침은 잡지 못한다. 잠금 파일은 `TMPDIR`이 아니라 고정 경로(`/tmp`)에 두어 셸·워크트리가 달라도 같은 DB면 같은 파일을 잡는다.

> **[#1583] 종전 이 절은 저장소에 없는 픽스처를 적고 있었다** — `db_session`(「PostgreSQL test container」) · `httpx_client`. 둘 다 정의가 0건이었고(`git grep "def db_session\|def httpx_client" -- tests`), 저장소는 CUBRID로 옮겨 컨테이너 전제도 사라졌다(`#1058`). 새로 검사를 쓰는 사람이 이 절을 보고 찾으면 없었다. 이름을 가드로 묶어 다시 벌어지지 않게 했다.

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

> **소관 — 생성기도 픽스처도 이미 있다** (`#1666` 정정 · 2026-09-23). `scripts/gen_fixtures.py`와 `tests/fixtures/`의 다섯 파일은 `#45`에서 **만들어졌다.** 픽스처를 **글자로 대조하는 검사**도 있다 — `tests/test_layer1_fixtures.py`의 `test_generator_reproduces_fixture_files`(생성기를 다시 돌려 파일과 대조) · `test_fixture_files_match_test_plan`(파일이 `§1.2`·`§1.3`의 JSON 블록과 같은지 대조) · `test_generator_does_not_import_service_code`(위 독립성 조건 1). 종전 문장은 *「현재 저장소에 둘 다 없으며, 픽스처를 글자로 대조하는 코드도 0곳이다」*로 적고 있었다 — `§1.2`의 같은 종류 문장은 `#195`가 이미 같은 이유로 지웠고, 이 자리만 남아 있었다.

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
```

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
| UT-WX-006 | **입사각 유도** [#766] — 파향과 침로의 상대각 | 같은 방향이면 β=0(head sea) · 반대면 180 · 좌현 30° = 우현 30° · 0° 넘김은 짧은 쪽 · 침로가 없으면 β=0 |

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
| IT-STATE-009 | **동시 쓰기의 직렬화** | 두 연결이 같은 항차에 전환 × 전환·PATCH·실적·삭제·채택을 **커밋 직전에** 교차 | 뒤 요청은 앞 커밋 뒤의 상태로 판정 — 종결 상태 덮어쓰기 없음 · 채택 행 하나 (`#1626`) |

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
| IT-CSV-008 | 출항·도착 예정 시각 선택 컬럼 (#906) | `2026-09-12T09:00:00+09:00` · `…Z` · 빈 칸 | UTC로 저장 · 빈 칸은 비어 들어감 · 시간대 없는 값은 행 오류 |
| IT-CSV-009 | **정박 구간 적재** [#765] | `type=not_underway_periods` 2행 | 구간·연료가 함께 저장되고 **CF 스냅샷**이 붙는다 · 빈 소비원은 `AUX_ENGINE` |
| IT-CSV-010 | 부분 성공 | 3행 중 1행 유형 오류 · 1행 연료 오류 | 1행 저장 · **행 번호와 필드**가 오류에 실린다 |
| IT-CSV-011 | **겹치면 그 행만 거부** | 시간대가 겹치는 2행 | 1행 저장 · `overlap_checked: true` — 겹침을 받으면 같은 연료가 두 번 세어진다 |
| IT-CSV-012 | 시간대 없는 시각 | `2026-06-01T00:00:00` | 거부 — 서버 시간대로 읽으면 9시간 어긋난 구간이 들어간다 (`#906`과 같은 규칙) |
| IT-CSV-013 | `dry_run` | 정상 1행 | 저장 0건 · **`overlap_checked: false`** — 저장하지 않으므로 겹침을 볼 수 없다는 사실을 말한다 |
| IT-CSV-014 | 필수 컬럼 누락 | 헤더 2열 | 파일 전체 거부 — **한 행도 읽지 않는다** |

> **[ORACLE-S-2]** API_SPEC §8.2는 `=`, `@`, `+`, `-` 네 가지 prefix escape를 요구. 기존 테스트는 `=`만 검증하여 3개 공격 벡터가 누락되었음. IT-CSV-005~007 추가.

### 3.5 파라미터 가져오기 (`test_parameter_import_db.py`) [ORACLE-X-1 · #673]

> **2026-09-18 재작성 (#673 · 결정요청 v9 회신 「가」)** — 종전 명세는 JSON 요청 본문을
> 전제해 HTTP 코드(409·422)로 기대를 적었으나, 구현은 **CSV·행 오류 `errors[]`** 계약으로
> 확정됐다(§7.5). 각 케이스가 지키려던 것(중복 거부·형식 거부·해시 무결성·롤백)은 그대로이고
> **판정의 모양만 실제 계약에 맞췄다.** 001의 「content_hash 생성」은 연료 갱신 경로로 옮겨
> 졌다(세 테이블에는 `content_hash`가 없다 — `DB_SCHEMA §2.9 [X-3]`).

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-IMPORT-001 | 정상 가져오기 | 유효한 CSV(새 연도 · 개정 연도) | 파라미터 저장(개정은 이행 행 보존) · 감사 로그 기록 |
| IT-IMPORT-002 | 중복 거부 | 파일 안 같은 키 둘 | 두 번째 행이 `errors[]`로 떨어진다 — **아무것도 들어가지 않는다** |
| IT-IMPORT-003 | 잘못된 형식 거부 | a_raw가 숫자가 아님 | `{row, field: "a_raw"}` 행 오류 — 숫자가 아닌 것은 값이 아니라 오류다 |
| IT-IMPORT-004 | content_hash 무결성 | CF를 다른 값으로 갱신 | 갱신 뒤 `content_hash`가 `DB_SCHEMA §8.3.1` 산출 규약대로 재계산된다 |
| IT-IMPORT-005 | 실패 시 롤백 | 가져오기 중 한 행 오류 | **트랜잭션 롤백, 이전 상태 유지** — 멀쩡한 행도 들어가지 않는다(전부 아니면 전무) |

### 3.6 기상 Fallback 체인 (`test_weather_fallback.py`) [ORACLE-X-4]

> PRD §11.6 3단계 fallback: fresh API → stale cache (6h) + warning → NONE + warning.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-WX-001 | API 정상 → factor 적용 | Open-Meteo 정상 응답 | weather_factor > 1.0, warning 없음 |
| IT-WX-002 | API 실패 + 6h 캐시 | API timeout, 캐시 존재 | 캐시 factor 사용, `WEATHER_STALE` warning |
| IT-WX-003 | API 실패 + 캐시 없음 | API timeout, 캐시 없음 | weather_model = NONE, `WEATHER_NONE_FALLBACK` warning |
| IT-WX-004 | **보정한 계산이 근거를 남긴다** [#904] (`test_scenario_compare_db.py`) | 기능② `SIMPLE_RULE` + 좌표 + 6시간 이내 캐시 / `NONE` / 좌표 없음 | 보정하면 `calculation_run.weather_snapshot_id` = 시나리오 3행의 스냅샷 = 쓴 스냅샷, `result_json.scenarios[].weather_factor` > 1.0(값 하나). `NONE`·fallback은 스냅샷 NULL · 인자 1.0 — 캐시가 있어도 **쓰지 않은 기상을 근거로 적지 않는다** (`TECH_SPEC §5.4` 4·5항) |

### 3.7 감사 로그 (`test_audit_log.py`) [ORACLE-X-3]

> DB_SCHEMA §2.14, TECH_SPEC §13.1 감사 로그 요구사항.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-AUDIT-001 | 항차 확정 시 감사 로그 | voyage CONFIRM 전환 | audit_log 레코드 존재 (action=VOYAGE_CONFIRM) |
| IT-AUDIT-002 | 파라미터 변경 시 감사 로그 | reference_line 수정 | audit_log에 before/after 값 포함 |
| IT-AUDIT-003 | 계산 실행 시 감사 로그 | CII 계산 실행 | audit_log에 input_hash, parameter_hash 포함 |
| IT-AUDIT-004 | **감사 기록 실패 시 원본도 남지 않는다** [#1625] (`test_audit_actions_db.py`) | 항차 확정 · 기능①·②·③ 실행에서 `audit_log.insert_event` 예외 주입 | 500 · 항차 상태는 전환 전 그대로 · `calculation_run`(기능③은 스냅샷·실행 행까지) 늘지 않음 · `audit_log` 행 없음 — 원본과 감사를 **한 번의 커밋**으로 확정한다(`TECH_SPEC §16.3`). 반대로 계산 이력 INSERT가 실패하면 감사도 남지 않는다 |

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
| IT-EXPORT-002 | 채울 수 없는 열을 두지 않는다 | 항차 표 컬럼 | `attained_cii`·`rating` 없음. ~~전제(`calculation_run.voyage_id`가 전부 NULL)도 함께 단언~~ — `#817`로 전제가 사라져 그 단언을 걷고 판단을 다시 적었다(항차 하나의 CII는 정본의 양이 아니다) |
| IT-EXPORT-003 | Excel 호환 | 한글이 든 항차 | 첫 바이트 UTF-8 BOM · 줄바꿈 전부 CRLF · 한글 보존 |
| IT-EXPORT-004 | 수식 주입 방어 (`=`·`+`·`-`·`@`) | `notes`에 `=HYPERLINK(…)` | 셀이 `'` 접두를 받는다 (`§8.2`와 **같은 함수**) |
| IT-EXPORT-005 | 값의 표기 | 실적·시각·빈 값 | 지수 표기 없음 · KST 오프셋 ISO 8601 · 없는 값은 빈 칸 · CO₂는 실적 우선 |
| IT-EXPORT-006 | 한 행 = 항차 × 연료 | 연료 2종 항차 / 연료 없는 항차 | 행 2개(같은 `voyage_id`) / 행 1개(연료 칸 빈다) |
| IT-EXPORT-007 | 필터·파라미터 | `year` · 잘못된 `type` · 없는 선박 | 규제연도로 거른다 · 422(기본값으로 되돌리지 않는다) · 404(빈 표 아님) |
| IT-EXPORT-008 | `calculations`·`simulations`·`format=json` | 계산 이력 · 시뮬레이션 실행 | 저장된 `result_json`을 재계산 없이 읽는다 · `SCENARIO`는 식별자만 · `year`는 KST 생성연도 · JSON이 CSV와 같은 값 · **`calculation_run_id`로 한 건만**(다른 선박 404 · 다른 type 422 · #891) |
| IT-EXPORT-009 | **행 수 상한을 두지 않는다** (`#1078`) | 계산 이력 10,002건 / 2025년 1건 + 2026년 10,001건 / 연도 경계 정각 | 10,002행 전부(잘리지 않는다) · `year=2025`가 **상한 밖의 1건을 집는다**(쿼리에서 거른다) · 경계는 **반열림**(다음 해 첫 순간은 제외) |
| IT-EXPORT-010 | **수치 열 선언** (`#1247` · `§8.1` 「수치 열」) | `co2_ton`에 `-12.5` · `voyage_no`에 `-12.5` · `notes`에 `-1+1+cmd\|…` · 수치 열에 `=SUM(A1)` | 수치 열은 `'` 없이 `-12.5` · 사용자 입력 열은 값이 숫자여도 `'` 접두(판정은 **선언으로만**) · 숫자 아닌 값은 접두를 받는다(원문이 그대로 나가지 않는다) · `NUMERIC_COLUMNS`는 실제 열 이름만 담고 사용자 입력 열이 없으며 세 종류 전부에 선언이 있다 · `kinds`는 열 순서 그대로. DB 없이 표를 손으로 만든다 — 실제 열은 CHECK 제약상 음수가 없다 |

### 3.13 제출 전 자체 점검 (`test_reports_db.py`) [#770]

> `PRD §21` 「공식 보고서 보조」 · `§25.3`. **새 리포트가 아니라 연간 실적 리포트의 절**이다 — 「제출 전 검토용」이라는 제목의 별도 문서가 있으면 `§25.1`의 「대관 제출용은 하지 않는다」와 경계가 흐려진다.

| TC ID | 테스트 | 기대 결과 |
|---|---|---|
| IT-REPORT-001 | 절인가, 문서인가 | 「제출 전 자체 점검」이 **연간 실적 리포트 안의 절**이다 |
| IT-REPORT-002 | **용도 고지** | 절의 note에 「제출용 문서가 아닙니다」와 「규제 적합 판정이 아닙니다」가 실린다 |
| IT-REPORT-003 | 대체 계산을 **축으로** 나눈다 | 연료·거리 행이 각각 있고, 건수 0이면 「해당 없음」(`#1052` ⓶ — 종전 「이상 없음」) |
| IT-REPORT-004 | 제원이 비면 **리포트 자체가 막힌다** | 422 — 그래서 점검 표에 「선박 제원」 행을 두지 않는다(늘 「확인」만 찍히는 죽은 칸이 된다) |
| IT-REPORT-005 | **G5 미반영 고지** (`#762`) | note에 `PRD §25.3` 정본 문구가 원문 그대로 실린다 · 「G5」 **행은 없다**(고지 문장이지 점검 행이 아니다) |
| IT-REPORT-006 | **진행 중과 실적 확정 전은 다른 행** (`#1532`) | 자체 점검에 「진행 중 항차」(항해 중)와 「실적 확정 전 항차」(`COMPLETED`)가 따로 있고 건수·판정이 각각 맞다 · 확정 전 건수가 데이터 점검 화면(`UNCONFIRMED`)과 같다 · 옛 이름 「실적 미입력」이 표에 없다 |

---

### 3.12 항만명 좌표 조회 (`test_port_geocoding_db.py`) [#768]

> `API_SPEC §3.10` · `PRD §15.1` MAY. **사용 정책이 설계를 정한다** — 공개 Nominatim은 초당 1회 · User-Agent 필수 · 결과 캐시 필수 · **자동완성 금지**다. 그래서 여기서 보는 것은 속도가 아니라 **정책을 코드가 지키는가**이다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-GEO-001 | 샘플 목록이 먼저 답한다 | `BUSAN` | 좌표 반환 · **외부 호출 0회** |
| IT-GEO-002 | 한글 이름·공백·대소문자 | `  부산  ` | 같은 항을 가리킨다 · 외부 호출 0회 |
| IT-GEO-003 | **캐시** | 같은 이름 2회 | 1회는 `LOOKUP`, 2회는 `CACHE` · `port_geocode` 1행 |
| IT-GEO-004 | 항만이 아닌 결과 | 도시(`place:city`) | 버린다 · 저장하지 않는다 (「부산」은 도시이기도 하다) |
| IT-GEO-005 | 실패와 없음을 가른다 | 조회 예외 | `LOOKUP_FAILED`(≠ `NOT_A_PORT`) |
| IT-GEO-006 | 제공자 없음 | provider 미지정 | 외부로 나가지 않는다 — 오프라인·테스트 환경 |
| IT-GEO-007 | **식별** | 조회 요청 | `User-Agent`가 제품을 밝힌다(라이브러리 기본값은 차단 대상) |
| IT-GEO-008 | **초당 1회** | 연속 2회 호출 | 두 번째가 1초 뒤에 나간다 — 정책을 **코드가 강제**한다 |
| IT-GEO-009 | **제공자는 프로세스에 하나** [#1335] | 라우트 2회(다른 이름) · 가짜 시계 | 두 요청이 `app.state`의 **같은 인스턴스**를 쓴다 · 두 번째 외부 호출이 1초 뒤에 나간다(요청마다 새로 만들면 시각이 0으로 돌아가 상한이 걸리지 않는다) |
| IT-GEO-010 | **동시 요청 간격** [#1335] | 한 제공자에 `gather` 3건 · 가짜 시계 | 외부로 나간 시각의 간격이 모두 ≥ 1초 — 락 없이 각자 재면 셋이 같은 시각에 나간다 |
| IT-GEO-011 | 라우트 **캐시** [#1335] | 라우트 2회(같은 이름) | 두 번째는 `CACHE` · 외부 호출 **1회** · 대기 0회 |
| IT-GEO-012 | **커넥션을 쥐지 않는다** [#1364] | 커넥션 1개짜리 엔진 · 조회가 바깥에 붙잡힌 동안 다른 세션이 질의 | 다른 세션이 **그 하나뿐인 커넥션을 받아** 질의한다(쥐고 있으면 `pool_timeout` 초과) · 조회 중 `in_transaction()`이 거짓 |
| IT-GEO-013 | **대기 상한** [#1364] | 앞 조회가 락을 쥔 채 바깥에 있고 상한 0.05초 | `LOOKUP_FAILED` — 줄이 길면 기다리게 두지 않고 사실대로 말한다 |
| IT-GEO-014 | **동시에 같은 이름** [#1364] | 바깥에 나간 사이 다른 세션이 같은 이름을 먼저 저장 | `UNIQUE(query)` 충돌을 정상 경로로 받아 **먼저 저장된 행**(`CACHE`)을 돌려준다 · 행은 1개 |
| IT-GEO-015 | 미커밋 변경 **가드** [#1364] | 대기 중인 객체를 들고 호출 | `RuntimeError` — 트랜잭션을 닫는 설계라 남의 작업이 함께 확정되는 것을 부르는 쪽에서 막는다 |

---

### 3.11 요청 캐시 (`test_request_cache_db.py`) [#989]

> `services/request_cache.py`. **선대 요약이 같은 규제 파라미터를 요청 하나에서 여러 번 읽던 것**을 없앤다. 선박마다 `compute_ytd_cii`를 최대 네 번 부르고(올해 · 직전 2개 연도 · 최근 30일 창) 그 네 번이 각자 규정연도 · 기준선 · 등급 경계 · 선박을 다시 읽었다(`#772` 실측: 200척 8,402 쿼리 · 10.7초).
>
> ⚠️ **줄이는 것보다 값이 같은 것이 먼저다.** `IT-CACHE-002`가 없으면 나머지는 「빨라졌는데 답이 달라졌다」를 잡지 못한다.
>
> **[#989 ⑵ B안] 파라미터 너머의 집계 조회까지 배치로 묶는다** (2026-09-18). 요청 캐시가 파라미터·선박을 담은 뒤에도 **집계 5종**(연간 포함 항차 · 항차 연료 · not under way 연료·거리·구간)이 선박마다 나가 선박 수만큼 쿼리가 늘었다(200척 재실측 4,624쿼리 · 16.4s — CUBRID). 선대 요약이 `(연도, 시점)` 조합별 **배치 쿼리**로 캐시를 미리 채운다 → **32쿼리 · 0.57s**. `IT-CACHE-005`가 배치가 캐시 키를 빗나가지 않는지(단건 조회가 다시 나가면 N+1로 되돌아간 것)를 본다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-CACHE-001 | 같은 값을 다시 읽지 않는다 | 데모 선대로 `GET /fleet/summary` 1회 | 규정연도·기준선·등급 경계를 **같은 인자로 두 번 읽지 않는다** · 선박 개별 조회 0회(목록으로 이미 읽었다) |
| IT-CACHE-002 | **답이 같다** | 같은 요청을 캐시 켜고 / 끄고 | 응답이 글자 그대로 같다(서버가 확정하는 `as_of` 제외) |
| IT-CACHE-003 | 켠 요청에서만 돈다 | 캐시를 켜지 않은 세션 · 단건 YTD 계산 | 매번 읽는다 — 고치는 경로가 방금 바꾼 값을 본다 |
| IT-CACHE-004 | 실패는 기억하지 않는다 | 첫 조회가 예외, 두 번째는 성공 | 두 번째 호출이 성공값을 받는다 |
| IT-CACHE-005 | **배치가 캐시를 채운다** | 데모 선대로 `GET /fleet/summary` 1회(단건 저장소 함수를 대역으로 교체) | 집계 단건 5종·진행분 3종 **0회 호출** · 배치 `list_annual_inclusions_for_vessels` 정확히 4회(올해 현재 · 올해 창 시작 · 직전 2개 연도) · 항차 연료 배치 5회(조합 4 + 진행분 1) |

---

### 3.14 연도별 CII 이력의 연료축 (`test_cii_history_fuel_db.py`) [#769]

> `API_SPEC §2.7` `fuels[]` · `PRD §21` 「통계 분석」. **창·상태 구분은 `test_cii_history.py`가 본다** — 여기가 보는 것은 연도 행 안의 연료 내역이다.
>
> ⚠️ **`IT-FUEL-002`가 이 표의 중심이다.** 비중을 톤으로 내면 CF가 낮은 연료를 많이 쓴 해가 실제보다 나빠 보이는데, **두 값이 가까워 눈으로는 구분되지 않는다**(75.0% vs 77.3%). 그래서 톤 비중과 **다른 값**이 나오는지를 단언으로 고정한다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-FUEL-001 | 유종별로 나뉜다 | HFO 300t + LNG 100t | 두 줄 · 유종별 톤의 합 = `total_fuel_ton` |
| IT-FUEL-002 | **비중은 CO₂ 기준** | 같은 입력 | HFO **77.3%**(톤 기준 75.0%가 아니다) · 합이 100 |
| IT-FUEL-003 | CF 스냅샷 둘 → 한 줄 | 같은 해 다른 항차에 구·신 CF | `HFO` 한 줄 · CO₂는 **각 스냅샷 CF로** 곱한 합 |
| IT-FUEL-004 | 정박 연료도 축에 든다 | 항해 HFO + 정박 LNG | 두 줄 — 분자에 들어간 연료가 축에서 빠지지 않는다 |
| IT-FUEL-005 | 정렬을 서버가 정한다 | 작은 것을 먼저 입력 | CO₂ 내림차순으로 되돌아온다 |
| IT-FUEL-006 | 실적 없는 해 | 데이터 없는 연도 | `fuels: []` — `null`이 아니다 |

---

---

### 3.15 위치 스냅샷 · AIS 수집 (`test_position_snapshot_db.py`) [#764]

> `DB_SCHEMA §2.21` · `PRD §21` 「AIS 연동」. **AIS 제공자는 아직 없다** — 데모 선박 5척 중 3척의 IMO가 합성값이라 어떤 출처도 그 셋의 위치를 주지 않고, 실존 2척(`STAR SKIPPER` · `DONGJIN ENDURANCE`)은 항차가 시드가 만든 것이라 받은 위치와 맞지 않는다(`PRD §21` `[#764]` · `#1662` 정정 — 종전 「5척 모두 합성」). 그래서 보는 것은 「AIS가 맞는 값을 주는가」가 아니라 **받은 것을 우리가 어떻게 다루는가**다.
>
> ⚠️ **넷이 틀리면 화면에서 배가 사라지거나 뒤로 간다** — 중복(`002`) · 역주행(`004`) · 소실(`005`) · 단정(`008` 보조).

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-POS-001 | 사람이 넣은 위치도 항적이 된다 | `PATCH` 위치 | `source=MANUAL` 스냅샷 1행 |
| IT-POS-002 | **재전송은 한 행** | 같은 `(선박·출처·관측 시각)` 2회 | 1행 · 두 번째는 「넣지 않았다」를 돌려준다 |
| IT-POS-003 | AIS 위치가 반영된다 | `nav_status=0` 관측 | 스냅샷 + 선박 현재 위치 · **운항 상태 2축을 함께** 적는다 |
| IT-POS-004 | **역주행 방지** | 오래된 관측이 나중에 도착 | 현재 위치는 그대로 · **항적에는 남는다** |
| IT-POS-005 | 소실 방지 | 위치가 오지 않은 선박 | 마지막 위치를 지우지 않는다 |
| IT-POS-006 | 남의 배 | 선대에 없는 IMO | 세기만 하고 저장하지 않는다 |
| IT-POS-007 | 조회 실패 | 제공자 예외 | **사유와 함께** 돌려준다 · 배치를 죽이지 않는다 |
| IT-POS-008 | **신선도는 관측 시각으로** | 30분 전 관측 | 1800초 (수신 시각이 아니다) |
| IT-POS-008 보조 | 모르는 상태를 단정하지 않는다 | `nav_status` 3·6·15·`None` | `None` — 기존 상태를 그대로 둔다 |
### 3.16 선대 요약의 항로 좌표 (`test_fleet_route_db.py`) [#763]

> `API_SPEC §2.8` `vessels[].route` · `UIFLOW 2-4` 지도. 지도가 **대권선**을 그리는 근거다.
>
> ⚠️ **`IT-MAP-004`는 성능 회귀 방어다** — 선박마다 진행 중 항차를 물으면 200척에 200쿼리가 붙는데, 이 엔드포인트는 쿼리 수를 방금 줄여 놓은 자리다(`#989` — 212 → 129).

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-MAP-001 | 네 좌표가 그대로 실린다 | 좌표가 있는 진행 중 항차 | 출발·도착 4값 (6자리) |
| IT-MAP-002 | **반쪽 선분 금지** | 좌표가 빈 항차 | `null` — 그리지 않는다 |
| IT-MAP-003 | 없는 항로를 지어내지 않는다 | 진행 중 항차 없음 | `null` |
| IT-MAP-004 | **쿼리 한 번** | 선박 3척 | `execute` 호출 1회 |
| IT-MAP-005 | 선박당 하나 · 최근 출항분 | 진행 중 항차 2건 | `find_in_progress`와 **같은 항차** |
| IT-MAP-006 | **목적항 방향 = 항로 비교의 방위** (`#1804`) | 위치·도착항이 있는 진행 중 항차 | `course_deg`가 `calc/distance.initial_bearing_deg`와 **같은 값** (소수 1자리) |
| IT-MAP-007 | 없는 방향을 지어내지 않는다 (`#1804`) | 현재 위치 없음 · 진행 중 항차 없음 | `null` |


### 3.17 챗봇 가드 · 대화 보존 (`test_llm_guard.py` · `test_chat_store_db.py`) [#120]

> `PRD §20 O-12` 3대 봉쇄 원칙 중 **둘을 코드가 실제로 막는지** 본다 — No-Recall(전송 통제)과 No-Compute(수학 검증). **프롬프트로는 「검증」이 성립하지 않는다.**
>
> ⚠️ **`IT-CHAT-001`이 이 절의 중심이다.** 정본(`PRD §16.3.1`)이 MUST로 목록을 정하는데 코드가 다른 목록을 쓰면 **정본은 지켜진 것처럼 보이면서 실제로는 새어 나간다.** 검사가 `PRD` 표를 읽어 코드 상수와 대조하므로 한쪽만 고치면 걸린다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-CHAT-001 | **정본 ↔ 코드 동기** | `PRD §16.3.1` 표 | 코드 상수와 **집합이 같다** |
| IT-CHAT-002 | 금지 예시도 동기 | 「보내지 않는 것」 표 | 같다 (문서와 코드가 서로를 가리킨다) |
| IT-CHAT-003 | 허용 필드 통과 | 수치 3종 | 그대로 나간다 |
| IT-CHAT-004 | **선박명 차단** | `vessel_name` | 오류 · **무엇이 막혔는지 말한다** |
| IT-CHAT-005 | **모르는 필드는 오류** | 목록에 없는 새 키 | 조용히 빠지지 않고 터진다 |
| IT-CHAT-006 | 인용 통과 | 도구가 준 수치 | 통과 |
| IT-CHAT-007 | **파생 수치 차단** | 두 값의 차(`0.07`) | 오류 — **빼기도 계산이다** |
| IT-CHAT-008 | 표기 차이 허용 | `4.980` vs `4.98` | 통과 — 막을 것은 표기가 아니라 **출처** |
| IT-CHAT-009 | 예외가 넓지 않다 | 연도·한 자리는 통과 · **두 자리는 걸린다** | 판단에 쓰이는 수치는 전부 두 자리 이상 |
| IT-CHAT-010 | 만료일 **생성 시 확정** | 세션 생성 | 생성 + 90일 |
| IT-CHAT-011 | **CASCADE 삭제** | 만료 세션 청소 | 메시지도 함께 사라진다 |
| IT-CHAT-012 | 과한 청소 방지 | 89일 · 91일 | 0건 · 1건 |
| IT-CHAT-013 | 이력 자르기 | 8건 중 최근 3건 | **시간순**으로 3건 |
| IT-CHAT-014 | `role` 제한 | `SYSTEM` | DB가 거부 |
| IT-CHAT-015 | **감사는 해시** | 본문 | 원문이 없고 대조는 된다 |
| IT-CHAT-050 | ⚠️ **화면 자릿수 인용 허용** | 도구 `4.982400` → 답 `4.982` | 통과 — 표기 차이다 |
| IT-CHAT-051 | 넓혀도 **파생은 막힌다** | 차 · 지어낸 값 · 사용자 입력 | 전부 폐기 |
| IT-CHAT-052 | 허용 자릿수 ↔ **화면 자릿수** | `DISPLAY_DIGITS` | 화면이 더 세밀하면 실패 |

### 3.18 챗봇 도구·오케스트레이션·공급자 (`test_chat_tools.py` · `test_chat_api_db.py` · `test_llm_provider.py`) [#121]

> `§3.17`이 **가드 자체**를 보고, 이 절은 **가드가 실제 경로에 꽂혀 있는지**를 본다. 함수가 있어도 부르지 않으면 아무것도 막지 못한다 — `#121`의 가장 큰 위험이 그것이다.
>
> 외부 모델을 부르지 않는다(`FakeProvider`). CI가 바깥과 말하면 ⑴ PR마다 과금되고 ⑵ 같은 입력에 다른 출력이 나와 검사가 불규칙하게 깨진다. **못 잡는 것은 「실제 모델이 도구를 제대로 고르는가」**이고, 그것은 릴리스 게이트의 일이다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-CHAT-016 | 도구 4종 · **쓰기 없음** | 도구 목록 | `create_voyage`가 없다 |
| IT-CHAT-017 | 설명이 한국어 | 도구 설명 | 사용자가 묻는 언어와 같다 |
| IT-CHAT-018 | 봉투는 구조만 | 성공·실패 | 우리가 만든 상수만 담긴다 |
| IT-CHAT-019 | **이름을 경계에서 맞춘다** | `estimated_rating` | `rating`으로 나간다 (정본 목록 안) |
| IT-CHAT-020 | 두 겹이 다른 방향으로 | 대응표 밖 · 목록 밖 | 조용히 빠진다 · 오류로 막힌다 |
| IT-CHAT-021 | 대응표 도착지 검사 | `_PUBLISH_MAP` 값 | 전부 화이트리스트 안 |
| IT-CHAT-022 | 모르는 도구 | 없는 이름 | **예외가 아니라 봉투** — 모델이 고쳐 부른다 |
| IT-CHAT-023 | 선박이 먼저 | `vessel_id` 없음 | 계산 도구가 돌지 않는다 |
| IT-CHAT-048 | ⚠️ **오류 원문 금지** | 식별자 섞인 예외 | 우리가 만든 고정 문구만 |
| IT-CHAT-049 | 실제 경로로도 안 샌다 | 없는 선박으로 계산 | 봉투에 UUID 없음 |
| IT-CHAT-024 | **모든 응답에 면책** | 도구 없는 답 | `disclaimer` 있음 |
| IT-CHAT-025 | 면책 ↔ 정본 대조 | `PRD §6.3` 표 | 글자 그대로 같다 |
| IT-CHAT-026 | 도구 → 답 | 도구 1회 | `tool_calls`에 기록 |
| IT-CHAT-027 | **선박명이 안 나간다** | `search_vessel` | 모델이 받은 것은 **척수뿐** |
| IT-CHAT-028 | **지어낸 수치 폐기** | 도구 없이 `4.98` | `discarded: true` · 200 |
| IT-CHAT-029 | 폐기분은 **저장도 안 한다** | 위와 같음 | `chat_message`에 `USER`만 |
| IT-CHAT-030 | 호출 상한 | 도구 5회 요청 | 3회에서 끊는다 |
| IT-CHAT-031 | **감사 로그** | 한 턴 | `CHAT_MESSAGE` 2 · `CHAT_TOOL_CALL` · 원문 없음 |
| IT-CHAT-032 | 남의 대화 | 다른 `session_id` | **404** (403이면 존재가 새어 나간다) |
| IT-CHAT-033 | 대화 이어가기 | 같은 `session_id` | 이력 4건 |
| IT-CHAT-034 | `system`을 배열에서 뗀다 | 역할 3종 | 별도 필드 (안 떼면 400) |
| IT-CHAT-035 | 같은 역할 연속 합치기 | `user` 2연속 | 하나로 — 도구 응답 때문에 **실제로 생긴다** |
| IT-CHAT-036 | 텍스트 + 도구 동시 | 두 블록 | 둘 다 읽는다 |
| IT-CHAT-037 | **출력 상한을 매 호출에** | 요청 본문 | `max_tokens` 실림 |
| IT-CHAT-038 | 실패 문구에 **본문을 안 싣는다** | 400 + 선박명 | 문구에 선박명 없음 |
| IT-CHAT-039 | 키 없음은 **다른 오류** | 키 미설정 | `LLMUnavailableError` (503) |
| IT-CHAT-053 | ⚠️ **왕복이 벤더 규격대로** | `tool_use` + `tool_result` | 같은 `tool_use_id`로 짝 |
| IT-CHAT-054 | `tool_use` id를 잃지 않는다 | 응답 파싱 | id가 남는다 |
| IT-CHAT-055 | **블록은 합치지 않는다** | 문자열 + 블록 | 두 메시지로 유지 |
| IT-CHAT-056 | **오케스트레이션이 짝을 만든다** | 한 턴 | assistant `tool_use` → user `tool_result` |
| IT-CHAT-057 | `stop_reason`을 **옮기기만** | 응답 파싱 | 판정은 서비스가 |
| IT-CHAT-058 | ⚠️ **잘린 답을 안 보인다** | `max_tokens` | 폐기 · 안내 |
| IT-CHAT-059 | ⚠️ **잘린 응답으로 도구를 안 돌린다** | `max_tokens` + 도구 | 호출 0건 |
| IT-CHAT-060 | 거절은 **사유를 안 지어낸다** | `refusal` | 고정 문구 |
| IT-CHAT-061 | ⚠️ **이력 창이 질문부터** | 네 번 주고받기 | 첫 대화 줄이 `user` |
| IT-CHAT-062 | 화면 선박이 세션 귀속을 이긴다 (#1243) | 세션에 A·요청에 B | B로 계산하고 **세션은 A 그대로** |
| IT-CHAT-063 | 찾은 선박이 다음 턴까지 이어진다 (#1243) | 1턴 검색 → 2턴 `vessel_id` 없이 계산 | 2턴에서 계산 성공·`vessel_resolved=true` |
| IT-CHAT-064 | 후속 질문이 이전 답 수치를 인용한다 (#1244) | 2턴, 도구 없이 1턴 수치 재인용 | `discarded=false` |
| IT-CHAT-065 | 느린 턴은 예산 안에 폐기된다 (#1245) | 주입 예산 0.05초 + 자는 공급자 | `discarded=true`·「초과」 문구·면책 유지 |

### 3.19 챗봇 용어 풀이 ↔ 정본 (`test_chat_explain.py`) [#123]

> 풀이는 **제품이 사용자에게 하는 말**이다. 정본에 없는 말을 만들면 화면과 챗봇이 **같은 것을 다르게** 말하는데, 그 차이는 화면을 깨뜨리지 않아 발견되지 않는다.
>
> ⚠️ **`IT-CHAT-046`이 이 절의 실질이다.** 풀이에 `Reg 28.7` 같은 수를 적으면, 모델이 그것을 답변에 인용하는 순간 수학 가드가 「도구 응답에 없는 수치」로 보고 **답변을 통째로 폐기한다.** 그 실패는 「챗봇이 가끔 답을 안 준다」로 나타나 원인을 찾기 어렵다. 가드를 푸는 대신 **풀이에서 숫자를 뺀다.**

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-CHAT-040 | 방향이 정본에서 온다 | `PRD §3.3.6` | 「낮을수록 우수」 — 뒤집히면 설명 전부가 거꾸로 |
| IT-CHAT-041 | 경계값 동률 규칙 | `PRD §3.3.6` | 「같으면 더 우수한 등급」 |
| IT-CHAT-042 | **과장하지 않는다** | `PRD §3.3.7` | 시정조치계획 · **「운항 제한」 없음** |
| IT-CHAT-043 | 위험도 라벨 ↔ 화면 | `DESIGN_SYSTEM §2.5 (b)` 🔒 | 글자 그대로 같다 |
| IT-CHAT-044 | 여유는 **악화 방향** | `DESIGN_SYSTEM §2.5 (b)` | 방향을 말한다 · 등급 E는 없음 |
| IT-CHAT-045 | **등급 형용사 금지** | 「보통」·「불량」 | 등급 풀이에 없다 |
| IT-CHAT-046 | ⚠️ **두 자리 수 금지** | 풀이 전문 | 가드와 **같은 눈**(`extract_numbers`)으로 0건 |
| IT-CHAT-047 | 풀이가 **실제로 간다** | `SYSTEM_PROMPT` | 프롬프트에 꽂혀 있다 |

### 3.20 두 규정 표의 선종 집합 (`test_regulation_ship_type_sync_db.py`) [#834]

> `cii_reference_line`(기준선)과 `cii_rating_boundary`(등급 경계)는 **선종으로 짝을 이룬다.** 한쪽에만 있으면 그 선박은 반쪽 결과만 나온다 — 기준선만 있으면 `required_CII`는 나오는데 **등급을 못 내고**, 경계만 있으면 `required_CII` 자체가 안 나온다.
>
> ⚠️ **`#834`가 손으로 찾아 `RO_RO_PASSENGER_HSC` 한 건을 드러냈다.** 그때까지 몰랐던 이유는 **그 선종의 선박이 데모 선대에 없었기** 때문이다 — 코드는 정상이고 값만 비어 있으므로 어떤 검사에도 걸리지 않았다.
>
> ⚠️ **`RO_RO_PASSENGER_HSC`의 판정은 이미 끝나 있었다** — `PRD §3.4.4` 각주(`#126` · 원문 대조 확인 sky01170851)가 ⑴ G4 원문에 행이 없는 것이 **원문대로**이고 ⑵ **`RO_RO_PASSENGER` 행을 적용**하며 ⑶ **시드에는 넣지 않는다**(넣으면 `source_ref`가 거짓이 된다)로 정했다. 그래서 이 공백은 **의도된 것**이고 채워질 일이 없다 — 남는 물음은 **그 매핑이 실제로 동작하는가**뿐이다(`IT-REG-004`·`005`).
>
> 빈 자리는 **사유와 함께 목록으로 붙잡고** 목록과 정확히 같을 때만 통과시킨다 — 새 누락이 생겨도, 성격이 바뀐 뒤 목록을 안 고쳐도 실패한다(**낡은 목록은 거짓말이다**).

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-REG-001 | 기준선 없는 경계 | 두 표 차집합 | **0건** — 예외 없음 |
| IT-REG-002 | 누락 목록과 **정확히 일치** | 두 표 차집합 | 새로 생겨도 · 채워져도 실패 |
| IT-REG-003 | 목록에 **사유가 있다** | 각 항목 | 원문 근거 + 이슈 번호 |
| IT-REG-004 | ⚠️ **계산 계층이 상속한다** | HSC + 전체 경계 목록 | `RO_RO_PASSENGER` 행 |
| IT-REG-005 | ⚠️ **호출부가 걸러 조회하지 않는다** | `services/*.py` | 거르면 폴백이 죽는다 |

### 3.21 만료 행 정리 스크립트 (`test_purge_expired_script.py`) [#827]

> **지우는 물건이고, 아무도 보고 있지 않을 때 돈다**(호스트 cron). 그래서 DB를 붙여 「지워졌다」를 보는 대신, 가짜 실행기를 끼워 **어떤 SQL이 나가는지**를 본다 — DB 검사로는 「무엇을 지우려 했는지」가 안 보인다.
>
> ⚠️ **`IT-PURGE-001`이 막는 것이 가장 크다.** 조건을 빠뜨린 `DELETE FROM user_session`은 **전원 로그아웃**이다. 코드 리뷰로 놓치기 쉬운 한 줄이다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-PURGE-001 | ⚠️ **조건 없는 DELETE 금지** | 세 문장 | 전부 `WHERE` + `expires_at` |
| IT-PURGE-002 | dry-run이 **거짓말하지 않는다** | 세는 조건 ↔ 지우는 조건 | 글자 그대로 같다 |
| IT-PURGE-003 | 유예는 세션·토큰만 | 채팅 문장 | `make_interval` 없음 (90일이 이미 정본) |
| IT-PURGE-004 | ⚠️ **한 표가 실패해도 나머지는 돈다** | 표 부재 | 나머지 둘 집계 · 실패 목록 |
| IT-PURGE-005 | 실패면 **종료 코드 1** | 위와 같음 | cron이 성공으로 못 읽는다 |
| IT-PURGE-006 | **0건이어도 감사 기록** | 정상 실행 | `EXPIRED_PURGE` 1행 |
| IT-PURGE-007 | dry-run은 **아무것도 안 바꾼다** | `--dry-run` | DELETE·INSERT 0건 |

### 3.22 연료 CF 표 ↔ 시드 (`test_fuel_table_sync_db.py`) [#773]

> `PRD §3.4.2`가 연료 코드와 CF를 정한다. 그 표와 `fuel_type` 시드가 갈리면 **화면의 연료 선택지와 정본이 다른 말을 한다** — 그리고 **화면을 깨뜨리지 않으므로 발견되지 않는다.**
>
> ⚠️ **CF는 CII의 분자를 만드는 값이다.** 0.1만 달라도 등급이 바뀔 수 있는데 화면은 그대로 뜬다(`IT-FUEL-009`).
>
> 알려진 공백 둘 중 **`OTHER`만 여기서 본다**(정본 ↔ 시드). `Ethane`은 **정본 ↔ 원문**이라 기계가 읽을 형태가 아니어서 `PRD §3.4.2` 각주가 대신 적는다 — 값은 정하지 않는다(`AGENTS §2.1` 팀원 확인 사항).

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-FUEL-007 | 표를 **읽을 수 있는가** | `PRD §3.4.2` | 8행 이상 · `HFO` = `3.114` |
| IT-FUEL-008 | 코드가 **정확히 같다** | 정본 ↔ 시드 | 양방향 · 공백은 목록과 대조 |
| IT-FUEL-009 | ⚠️ **CF 값이 같다** | 정본 ↔ 시드 | 어긋나면 계산이 조용히 틀린다 |
| IT-FUEL-010 | 공백에 **사유가 있다** | 예외 목록 | 사유 + 이슈 번호 |

### 3.23 파일별 커버리지 하한 (`test_coverage_floor_script.py`) [#955]

> CI 게이트(`--cov-fail-under=90`)는 **전체 합계만** 본다. 합계가 96%여도 파일 하나가 60%대로 남을 수 있고, 이 저장소에서 **실제로 두 번 오래 남았다** — `#871`(`auth.py` 41~58% · 라우트 본문이 한 번도 실행되지 않는 결함)과 `#911`(`reports.py` 61% · `exports.py` 65% · 전부 실제 검사 공백). 5,900문장 중 69문장이 비어도 합계는 1pp도 움직이지 않으므로 **합계 게이트는 구조상 그것을 볼 수 없다.**
>
> ⚠️ **두 기준 중 하나만 넘으면 통과다** — 비율(80%) **또는** 미커버 문장 수(5 이하). 작은 파일에 비율만 걸면 8문장 중 1문장(87.5%)에 CI가 걸리고, 그러면 **하한을 낮추라는 압력**이 생겨 게이트가 있으나 마나가 된다. 크기로 대상에서 빼지는 않는다 — 빼면 그 크기 아래가 통째로 사각지대가 된다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-COV-001 | ⚠️ **큰 파일의 비율 구멍** | 100문장 · 39 미커버 | 실패 (`#911`의 실물) |
| IT-COV-002 | 작은 파일은 문장 수로 | 8문장 · 3 미커버 | 통과 (37.5%지만 산술) |
| IT-COV-003 | ⚠️ **작다고 면제 안 된다** | 10문장 · 9 미커버 | 실패 |
| IT-COV-004 | 예외는 **더 내려가면** 실패 | 65% → 55% | 통과 → 실패 |
| IT-COV-005 | ⚠️ **낡은 예외는 거짓말** | 예외인데 95% | 실패 — 「빼라」 |
| IT-COV-006 | 없는 경로가 목록에 | 지워진 파일 | 실패 |
| IT-COV-007 | 항목마다 **사유 + 이슈 번호** | 「TODO」 · 번호 없음 | 각각 실패 |
| IT-COV-008 | ⚠️ **경로 세 형태 정규화** | `src/cii_platform/…` · `cii_platform/…` · `…` | 셋이 같은 파일로 모인다 |
| IT-COV-009 | 저장소의 **실제 목록**이 유효 | `KNOWN_BELOW_FLOOR` | 위반 0건 |
| IT-COV-010 | ⚠️ **면제 목록 항목 수 상한** (`#1250`) | 사유·번호를 갖춘 1건 · 상한 0 / 1 | 상한 0이면 실패 · 1이면 통과 — 늘리려면 상한을 이슈 번호와 함께 올린다 |

### 3.24 챗봇 도구의 실제 실행 경로 (`test_chat_tools_db.py`) [#120]

> `test_chat_tools.py`는 도구 **바깥**을 본다 — 스키마·봉투 모양·화이트리스트 함수·오류 문구. 오케스트레이션 검사(`§3.18`)는 `FakeProvider`로 모델만 대역화하고 **도구는 부르지 않는다.** 그래서 `#955`(파일별 커버리지 하한)를 붙이자마자 `services/chat_tools.py` **66.2%**가 걸렸고, 미커버 구간이 **도구 4종의 본문 전체**였다.
>
> ⚠️ **화이트리스트가 실제 응답에 대해 도는 것을 아무도 보지 않고 있었다.** `_publishable` 단위 검사는 손으로 만든 `dict`를 본다 — 응답 필드가 늘거나 이름이 바뀌면 그 검사는 그대로 통과하고, `_PUBLISH_MAP`이 놓친 값은 `filter_outbound`가 마지막으로 막는다. **그 조합이 한 번도 실행된 적이 없었다.** `PRD §16.3.1`이 선박명·IMO·`vessel_id`를 전송 금지로 둔다.
>
> 대역을 쓰지 않는다 — `session`만 진짜면 도구 → 서비스 → 계산 → 저장소가 한 줄로 이어진다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| IT-CHATDB-001 | ⚠️ **검색이 이름·식별자를 안 준다** | 실제 선박명 검색 | `{"matched": 1}`만 |
| IT-CHATDB-002 | 빈 이름은 DB에 안 간다 | 공백 | 되묻는다 |
| IT-CHATDB-003 | ⚠️ **실제 계산 응답이 필터를 지난다** | 항차 CII 계산 | 정본 이름만 · 금지 값 0건 |
| IT-CHATDB-004 | API 이름 → 정본 이름 | `estimated_rating` | `rating`으로 나간다 |
| IT-CHATDB-005 | ⚠️ **순위로 정렬하지 않는다** | 시나리오 비교 | 서비스 순서 그대로 |
| IT-CHATDB-006 | 사유 코드를 그대로 | 실적 없는 선박 | 서버가 문장을 만들지 않는다 |
| IT-CHATDB-007 | ⚠️ **성공 경로도 필터를 지난다** | 실적 있는 선박 | `vessel_name`이 안 나간다 |

### 3.25 데이터 점검 판정 (`test_data_quality.py` · `test_data_quality_db.py`) [#513]

> `PRD §17.4`가 2026-09-13 사용자 결정으로 정한 판정 셋의 검사다. **판정하지 못한 것(UNKNOWN)이 0건·완결성 100%와 섞이지 않는 것**이 이 절의 뼈대다 — 섞이면 「데이터가 깨끗하다」와 「살펴보지 않았다」가 같은 화면을 쓴다.

| 검사 | 파일 | 무엇을 잠그는가 |
|---|---|---|
| 이상치 경계의 배타성 | `test_data_quality.py` | 정확히 0.6배·1.4배는 정상 — 경계값이 이상치 쪽으로 붙지 않는다 |
| 톤↔kg 입력 실수 | 〃 | 자릿수가 어긋난 연료 입력을 이상치로 잡는다 |
| cubic law | 〃 | 기대 연료가 속력의 제곱에 비례 — 선형이면 감속 항차가 이상치로 몰린다 |
| 완결성 = 실측 CO₂ 비율 | `test_data_quality_db.py` | 항차 수 비율이 아니라 배출량 비율 · 배출 없음이 100%가 아니다 |
| 이상치 항차의 완결성 제외 | 〃 | 이상치는 「실측」에서 빼고 「판정 불가」로 갈라 센다 |
| 대체 연료로 판정하지 않는다 | 〃 | `ytd.substitutions`(`#449`)로 대체된 연료는 이상치 판정의 분모에 들어가지 않는다 |
| HTTP 경로 | 〃 | 인증 401 · 봉투 · 연도 범위 422 — 서비스가 아니라 실제 엔드포인트(`API_SPEC §2.16`) |

### 3.26 실적 보정계수 (`test_annual_simulation.py` · `test_annual_simulation_read_db.py` · `test_hashing.py`) [#363]

> `PRD §12.2.1`의 보정계수(최근 실적이 계획보다 나쁘면 잔여 계획의 연료에 비를 곱한다)는 **켰다는 사실만** 저장한다(`annual_simulation_run.apply_feedback_factor` · `DB_SCHEMA §2.6`).

| 검사 | 파일 | 무엇을 잠그는가 |
|---|---|---|
| 강도는 비(총량이 아니다) | `test_annual_simulation.py` | 연료만 곱하고 거리는 그대로 |
| 최소 표본 미만은 `null` | 〃 · `test_annual_simulation_read_db.py` | 표본이 모자라면 적용하지 않고 `FEEDBACK_FACTOR_UNAVAILABLE` 경고(`TECH_SPEC §12.3`) |
| 켠 실행의 재현 | `test_annual_simulation_read_db.py` | 켜고 돌린 실행이 파라미터 재현으로 같은 값 |
| `input_hash` 분리 | `test_hashing.py` | 켠 실행과 끈 실행의 해시가 갈라진다 — 바뀌면 저장된 실행 전부가 재현 불가 |
| 끄지 않아도 계수를 싣는가 | `test_annual_simulation_read_db.py` | 응답 메타가 켬/끔을 그대로 말한다 |

### 3.27 필요 감축량 역산 (`test_annual_simulation.py`) [#433]

> `PRD §12.3.1`(목표 역산) — 「줄이라는 만큼 줄이면 목표 경계에 정확히 정착하는가」를 검사한다.

| 검사 | 파일 | 무엇을 잠그는가 |
|---|---|---|
| 역산의 정착 | `test_annual_simulation.py` | 줄이라는 만큼 줄이면 목표 등급 경계에 정확히 닿는다 |
| 목표 경계의 출처 | 〃 | 등급 판정과 같은 표(`cii_rating_boundary`)에서 온다 — 별도 기준이 아니다 |
| 연료 환산 | 〃 | 구성비 비례 — 한 유종에 몰아 넣지 않는다 |
| 잔여 계획 없음 ≠ 줄일 것 없음 | 〃 | 둘을 갈라 말한다 |
| 닿을 수 없는 목표 | 〃 | 전부 없애도 못 닿으면 그렇게 말한다 — 조용히 0%를 내지 않는다 |

| IT-CHATDB-008 | ⚠️ **없는 선박 id가 안 샌다** | 임의 UUID | 문구에 UUID 없음 |
| IT-CHATDB-009 | 연도 기본값이 상수가 아니다 | 연도 생략 | 문구가 고정 |
| IT-CHATDB-010 | 검색→계산이 이어진다 (#1243) | 요청 `vessel_id` 없이 두 도구 | 계산 성공 · 어디에도 선박명·IMO·hex id 없음 |
| IT-CHATDB-011 | 2척은 화면을 가리킨다 (#1243) | 같은 키워드에 2척 | 오류 봉투 · 귀속 저장 없음 |

### 3.28 공개 해상 경로망 위의 바닷길 (`test_sea_route.py`) [#1300]

> `PRD §5.2` · `API_SPEC §3.11` — 지도의 선이 대권선에서 서버 경로망 선으로 바뀌었다. **DB 없이 돈다**(경로망은 패키지가 번들한다 · 첫 호출에 그래프를 올려 수 초 걸린다). 계산 거리(`§3.9`)는 건드리지 않으므로 여기서 보는 것은 **선의 성질**이다.

| 검사 | 파일 | 무엇을 잠그는가 |
|---|---|---|
| 양 끝이 입력 좌표 그대로 | `test_sea_route.py` | 붙이지 않으면 마커와 선 끝이 떨어져 보인다 |
| 길이 ≥ 대권거리 | 〃 | 육지를 돌아가는 선이 최단 경로보다 짧으면 지어낸 선이다(부산 → 로테르담) |
| 결정론 | 〃 | 같은 입력은 같은 선 — 캐시 유무와 무관 |
| 같은 점 둘 | 〃 | 점 하나 · 0nm — 라이브러리의 「가까운 노드까지 갔다 오는 선」을 거른다 |
| 경유지 | 〃 | 「출발 → 경유지 → 목적항」을 지나고 길이는 두 구간의 합, 이음새 점 하나가 겹친다 |
| 날짜변경선 | 〃 | 이웃한 점의 경도 차가 180° 안 — 한 구간 안에서도, 구간을 이을 때도(부산 → 호놀룰루 → LA) |
| 경로 없음 | 〃 | 라이브러리는 경고 + 두 점 직선을 낸다 — 직선은 바닷길이 아니라 **실패로 올리고** API는 404다(라이브러리 함수를 대역으로 바꿔 경고를 낸다) |
| 기동 워밍 | 〃 | 첫 적재를 백그라운드로 — 적재 함수가 던져도 `warm_up`은 `False`를 돌려주고 예외를 내지 않는다 |
| API | 〃 | 200 모양(`coordinates`·`length_nm`·`legs`·`source`) · 경유지 반쪽은 422(빠진 쪽 필드) · 범위 밖은 한국어 422 · 경로 없음 404 · 비로그인 401 |

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
| AT-SC-005 | 우회 경유지 (#1300) | DETOUR = 대권(현재 → 경유지) + 대권(경유지 → 목적항) · 입력 우회 거리가 경유지보다 우선 · **경유지 검사는 우회 거리 입력과 무관하게 먼저** · 좌표 넷 없이 경유지는 422(`detour_waypoint_lat`) · 반쪽 경유지는 빠진 쪽 필드로 422 · 경유지가 **목적항과만** 같으면 「목적항과 같은」 · **현재 위치와만** 같으면 「현재 위치와 같은」 · **세 점 전부** 같으면 둘 다 말하며 422 · **경유지는 해시 재료이고 없으면 종전 해시 그대로** |

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
| AT-AUTH-001 | **틀린 비밀번호와 없는 이메일** | **401 · 같은 문구·같은 코드** — 계정 존재 여부 비노출 · **없는 계정도 가짜 해시 검증을 정확히 한 번 거친다**(`verify_dummy_async` — `API_SPEC §1.2`가 「같은 소요시간」을 로그인 하나로 좁혀 보증하는 근거. 벽시계 비교는 CI 부하에 흔들려 호출을 단언한다 · `#1405`) (`test_auth_api.py`) |
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
| AT-AUTH-012 | **배포 환경**(`APP_ENV`가 `production`·`staging`) dev-login | 라우트 미등록 (`test_auth_failure_paths.py`·`test_dev_auth.py`). `staging`을 함께 보는 이유는 `#1058` — 종전 판정 `not is_production()`이 허용값 넷 중 셋에서 열었고, 이 표가 `production`만 적어 **`staging`이 어느 쪽으로 떨어지는지 아무도 보지 않았다** |
| AT-AUTH-013 | dev-login 재기동 (고정 UUID) | 2회 모두 200 (`test_dev_auth.py`) |
| AT-AUTH-014 | **배포 환경**(`production`·`staging`) OpenAPI 문서 (`/docs`·`/redoc`·`/openapi.json`) | **401** — 라우트 미등록 + 공개 경로 제외. 404가 아니라 **다른 미등록 경로와 같은 응답**이어야 한다 (`test_docs_exposure.py`) |
| AT-AUTH-015 | 공개 경로 목록의 모든 경로에 라우트가 실재하는가 | **전부 실재.** 없으면 그 경로만 404가 되어 신호가 남는다 — 배포 환경(`production`·`staging`) dev-login이 그랬다 (`test_docs_exposure.py`) |
| AT-AUTH-016 | **가입 게이트** — 허용 도메인 밖 · 초대 코드 없음 / 틀림 (`#808`) | **422 · 조건을 가르지 않는 한 문구**(`PRD §6.3`) · 계정·세션 미발급. 도메인 **또는** 코드 하나만 맞으면 201. 도메인은 정확히 일치만(`evil`·하위 도메인 불가). **프로덕션에서 둘 다 미설정이면 기동 거부** (`test_signup_gate.py`·`test_auth_api.py`) |
| AT-AUTH-017 | **역할 3종** (`#1301` — 종전 역할 2종 `#672`) — 현장직이 사무직 전용 경로(`API_SPEC §1.2` 표 14종)를, 또는 현장직·사무직이 관리자 전용 경로(같은 절 「관리자 전용 경로」 표 2종)를 부름 · 마지막 관리자의 탈퇴·강등(대상 역할이 `OFFICE`·`FIELD` 어느 쪽이든) · 새 계정·최초 관리자 이메일 · 옛 설정 `INITIAL_OFFICE_EMAILS`가 남아 있으면 기동 거부 | **403 `FORBIDDEN_ROLE` · 경계별 정본 문구**(사무직 전용·관리자 전용이 다른 문구를 쓴다. CSRF 403과는 코드가 다르다) · 마지막 관리자는 **409 `CONFLICT`**, 계정·세션 그대로 · 새 계정은 `FIELD`, `INITIAL_ADMIN_EMAILS`에 든 이메일은 가입·로그인에서 `ADMIN`(한 번만 감사 기록) · **정본 두 표 ↔ 소스의 `require_office`·`require_admin` 목록 일치** · 프로덕션에서 `INITIAL_ADMIN_EMAILS` 미설정이면 기동 거부(실제 lifespan) · **옛 이름 `INITIAL_OFFICE_EMAILS`가 설정돼 있으면 값과 무관하게 기동 거부** · 044가 기존 계정을 전부 사무직으로, 057이 트리거를 `ADMIN` 포함 3종으로 재생성 (`test_roles_db.py`) |
| AT-AUTH-018 | **세션 검증 한 벌** (`#1050`) — 쿠키 없음 · 세션 없음 · 만료 · 폐기 · 삭제된 계정을 **실제 쿠키로** `resolve_session`에 통과시킴 · 같은 상황을 HTTP로 | 다섯 분기 각각의 문구(`UNAUTHORIZED`) · **미들웨어의 401 문구 = 의존성의 문구**(한 벌) · `auth/` 아래 세션 토큰 조회 코드가 **한 곳** · 미들웨어에 자기 검증(`hash_token`) 없음 (`test_session_resolution_db.py`) |

### 4.10 기상 스냅샷 조회 API (`test_weather_api_db.py`) [#767]

> `API_SPEC §9.1`. **`§9.2`(수동 갱신)는 열지 않는다** — 그 판정도 여기서 검사한다(`AT-WX-005`). 「미구현」이 아니라 **정책으로 닫은 것**이라, 라우트가 생기면 이 케이스가 깨진다.

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| AT-WX-001 | `§9.1` 응답 모양 | 1시간 전 스냅샷 | 저장값 그대로 · 키 11개가 **정확히** 일치 · `freshness=FRESH` |
| AT-WX-002 | 신선도 경계 | 3h · 12h · 30h | `FRESH` · `STALE` · `EXPIRED` (`PRD §11.6`과 **같은 시간**) |
| AT-WX-003 | 만료돼도 돌려준다 | 48시간 전 | 200 · `EXPIRED` — 「없다」와 「낡았다」는 다른 답이다 |
| AT-WX-004 | 저장된 것이 없다 | 스냅샷 없는 좌표 | 404 (빈 값을 지어내지 않는다) |
| AT-WX-005 | **열지 않은 것은 정말 없는가** | `POST /weather/refresh` | 404 |
| AT-WX-006 | 로그인 경계 | 미인증 | 401 |
| AT-WX-007 | 좌표 범위 (VAL-007) | `lat=95` | 422 · `field_label`이 「위도」(`#900`) |

### 4.11 올해 누적 CII 추이 API (`test_cii_ytd_series_db.py`) [#1671]

> `API_SPEC §2.18`. 수치 자체는 `§3`의 YTD 엔진·연말 예상이 검증한다. 이 절이 지키는 것은 **한 화면에 두 숫자가 생기지 않는 것**이다 — 추이의 끝점이 `§2.14`의 `ytd`·`year_end_projection`과 **문자 단위로** 같아야 한다. 구현이 같은 조립·같은 엔진을 부르므로 구성상 같지만, 그 구성이 갈리는 순간(잔여 항차를 정렬하다 하나를 빠뜨림)을 잡는 검사가 없으면 화면은 멀쩡한 채 값만 어긋난다(`#798`이 그렇게 7.65 vs 8.97을 냈다).

| TC ID | 테스트 | 입력 | 기대 결과 |
|---|---|---|---|
| AT-YTDS-001 | **실적 마지막 점 = `ytd`** | 실적 2 · 진행 1 · 계획 2 | `attained_cii`·`rating` 문자열 동치 · `required_cii`·`boundaries`도 같다 |
| AT-YTDS-002 | **계획 마지막 점 = `year_end_projection`** | 같은 픽스처 | 문자열 동치 · 잔여 계획이 있으면 실적 열과 갈린다 |
| AT-YTDS-003 | 실적 점마다 그 시각의 `resolve_ytd_at` 재호출과 같다 | 같은 픽스처 | 점 3개 전부 동치 |
| AT-YTDS-004 | `at` 오름차순 · 종류 분할 · 확정 항차는 **도착 시각에 전량** · 계획은 **도착 예정 순**(등록 순이 아님) | 9월분을 먼저 등록 | `ACTUAL, ACTUAL, IN_PROGRESS, PLAN, PLAN` · 계획 점의 값이 점마다 다르다 |
| AT-YTDS-005 | 도착 예정이 지난 잔여 항차(`#1323`) | 예정 6/15 · `as_of` 7/1 | 계획 점이 `as_of`에 붙는다 |
| AT-YTDS-006 | 정박 구간 | 종료 1 · 진행 중 1 | 둘 다 **`started_at`**에 `period_id` 점(저장소 절단 술어와 같은 시각) · 값이 그 시각에 나빠진다 · `simulated=false` |
| AT-YTDS-007 | 실적 없음 | 항차 0건 | 200 · `ytd_available=false` · `points=[]`(연초 점 금지) · `PROJECTION_NO_REMAINING_PLAN` · 경계·기준선은 준다 |
| AT-YTDS-008 | 과거 연도 | `year=2025` · `as_of` 2026-07-01 | `ACTUAL`만 — `PLAN`·`IN_PROGRESS` 없음 · `as_of` 점의 `at`은 **그 해 끝**(2026-01-01T00:00Z) · `simulated=false` (`#815`) |
| AT-YTDS-009 | `EXCLUDE` 항차 · 계획값 대체 | 취소 항차 1 · 거리 실적 없는 확정 항차 1 | 취소 항차의 점 없음 · 대체 항차의 점은 `substituted=true` + `COMPLETED_NO_DISTANCE` |
| AT-YTDS-010 | 오류 | 없는 선박 · `year=1900` | 404 · 422 |
| AT-YTDS-011 | 직렬화 | — | 수치는 문자열 6자리 · 시각은 `+00:00` · 점의 키 집합은 종류와 무관 |
| AT-YTDS-012 | **데모 벌크선 기준값 · HTTP** | `…0001` · `DEMO_ANCHOR+3d` | 첫 점 `8.979906`(2/26 23:00Z) · 마지막 실적 `8.213830` = `ytd` · 계획 열 `8.973981 → 8.971119 → 8.969484 → 8.967383 → 8.965893` = `year_end_projection` · 라우트 200/404/422 |
| AT-YTDS-013 | 규제연도 파라미터 없음 | `year=2045` | 409 `PARAMETER_ERROR` |
| AT-YTDS-014 | **진행 중 항차가 첫 `PLAN` 점** (`#1673` ②) | 진행 항차 도착 예정 9/15 · 잔여 계획 8/1 | `PLAN` 순서 = 진행 항차 → 잔여 계획 · 진행 항차 점은 9/15, 이른 계획은 그 시각을 잇는다 · `as_of`·첫·둘째 값이 전부 다르다 |
| AT-YTDS-015 | 같은 순간 두 항차 도착 | 둘째만 계획값 대체 | 점 하나 · `substituted=true`(둘 다 본다) |

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
| DB-CHK-022 | 호출부호 형식 (`vessel.call_sign` · 트리거 `trg_chk_call_sign_ins/upd` · 058) [#1197] | call_sign = "ABC" · "hlxq" · "HL-XQ" · "HLXQ " | 트리거 REJECT (`^[A-Z0-9]{4,7}$` · `REGEXP BINARY`). ⚠️ 「앞 두 글자 모두 숫자 불가」는 API만 본다 — `12AB`는 DB에 들어간다(의도한 느슨함) |
| DB-CHK-023 | 계획 거리 출처 (`voyage.planned_distance_source` · 트리거 `trg_chk_planned_distance_source_ins/upd` · 059) [#1256] | planned_distance_source = "MODEL_ESTIMATE" · "user_input" · "ESTIMATE" · "" | 트리거 REJECT (`USER_INPUT`·`COORDINATE_ESTIMATE`·NULL만 통과). NULL은 「모른다」— 기존 행을 되채우지 않는다 |

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
>
> **[#67] 별도 성능 잡·`pytest-benchmark`를 두지 않는다.** `test_benchmarks.py`는 **CI의 `test` 잡 안에서** 매 PR마다 돈다 — 목표(1~5초)와 실측(2026-09-11 · 0.05 ms · 49 ms · 0.01 ms · 2.2 ms) 사이 여유가 수십 배라, 도구의 정밀도보다 회귀를 매번 잡는 쪽이 먼저다. 임계값은 `PRD §16.1`의 초 단위 값을 **그대로** 옮겨 적으며 코드에서 완화하지 않는다. 재는 것은 계산 **엔진**(HTTP·인증 제외)이고, `PERF-002`만 규제값 조회·저장까지 포함한 서비스 경로다. `PERF-002`의 「캐시 시 < 2초」는 재지 않는다 — 시나리오 비교의 캐시는 기상 캐시(`TECH_SPEC §7.3`)인데 벤치마크는 기상을 쓰지 않아 그 조건이 성립할 자리가 없다.

| TC ID | 테스트 | 기준 | 측정 방법 |
|---|---|---|---|
| PERF-001 | 일반 CII 계산 | p95 < 1초 | Fixture 1 기반 100회 반복 (warm-up 10회 제외, gc.disable) |
| PERF-002 | 시나리오 3개 비교 | p95 < 5초, 캐시 시 < 2초 | 샘플 선박 3개 시나리오 |
| PERF-003 | 연간 결정론 계산 | p95 < 1초 | 12개월 항차 데이터 |
| PERF-004 | Monte Carlo 5,000회 | p95 < 3초 | 단일 선박 12개월 |
| PERF-005 | 초기 페이지 로드 — 선대 요약 | p95 < 3초 | **200척** 선대의 `GET /fleet/summary` 100회 반복 (`#1617`). 벤치마크 전용 선박(`IMO 98xxxxx`)을 만들고 끝나면 지운다 — 남기면 뒤따르는 검사의 선대 수치가 흔들린다 |

---

## 7. 접근성 테스트

> PRD §18.4 기준.
>
> **[#68] 검사는 `frontend/src/a11y.test.tsx`(vitest)에 있다.** 네 케이스는 화면의 성질이라 파이썬 `tests/`에 둘 수 없고, `§14.6`이 화면 접근성의 관할을 이 문서(`§7`)에 두므로 케이스 ID 가드(`tests/test_case_id_sync.py`)가 **프론트 검사 파일(`*.test.ts*`)의 인용도** 커버리지로 센다 — 구현 파일의 설명 인용은 세지 않는다(`#498`과 같은 규칙). `axe-core` 같은 범용 검사기는 넣지 않았다 — 네 케이스는 전부 이 제품의 규칙(등급 색 옆의 문자·패턴 · 비활성 항목은 링크가 아님 · 차트 값의 문자 사본 · 면책 상시 노출)이라 범용 검사기가 알 수 있는 것이 아니다. 대비(4.5:1)는 `frontend/src/styles/tokens.sync.test.ts`가 모든 문자 토큰 × 모든 표면으로 이미 잰다(`DESIGN_SYSTEM §0.2` 제약 6).

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
| AC-F1-005 | IT-STATE-001 · 화면 배선 `VoyageCiiActions.test.tsx`(#891) | 계획 저장 시 PLANNED 생성 · 연간 반영 기본 `INCLUDE_AS_PLAN` |

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

> 이 절은 2026-09-17에 실제 워크플로와 대조해 재작성했다(#1104) — 종전 §10은 `test.yml`의 5단계 파이프라인을 적고 있었으나 **그 파일도 단계도 존재한 적이 없었다.**

### 10.1 워크플로와 잡

CI는 `.github/workflows/ci.yml` 한 파일에 잡 4개, 제목 검사가 `pr-title.yml`로 분리돼 있다. **다섯 모두 required check다**(`AGENTS §7` 머지 조건 표).

| 잡 | 워크플로 | 무엇을 보는가 |
|---|---|---|
| `lint` | `ci.yml` | `ruff check` + `ruff format --check`(`src/`·`alembic/`·`tests/`·`scripts/`). ruff 버전 핀은 `pyproject.toml`에서 읽는다 — 못 찾으면 즉시 실패(#478). **PR에서는 정본 변경 이력 행 삭제 감지**(`scripts/check_changelog_rows.py` · `#1498`) — base와 PR 커밋(**직전 푸시의 head 포함** · `#1522`)을 읽으므로 `fetch-depth: 0`. 머지된 행을 일부러 지울 때만 `changelog-row-removal` 라벨 + 재실행(`AGENTS §4.1`) |
| `test` | `ci.yml` | **CUBRID 11.4 서비스 컨테이너**(`cii_test`) 위에서 pytest 전체. `--cov-fail-under=90`(전체 #235) + `scripts/check_coverage_floor.py`(파일별 하한 #955). PDF 렌더링 런타임(`libpango`·`fonts-nanum`)을 깔아 한글 tofu 회귀를 잡는다(#361) |
| `frontend` | `ci.yml` | Node 고정 버전에서 `npm ci` → oxlint → `tsc -b` + `vite build` → `vitest run`(#177) |
| `docker` | `ci.yml` | 프로덕션 스택(`docker-compose.prod.yml`) 빌드·마이그레이션·시드 행 수(50행)·`APP_ENV` 스모크·HTTP 검증(화면·`/api` 프록시·SPA fallback)·백업 리허설·교체까지 실제로 돈다(#393 · #827) |
| `pr-title` | `pr-title.yml` | PR 제목 형식 `종류(#이슈번호): 설명`(#600). 제목만 고쳤을 때도 다시 돈다(`edited` 이벤트) |

`audit.yml`은 CI와 별도의 **주간 스케줄** `npm audit`이다(#160) — 외부 advisory DB 갱신으로 코드 변경 없는 날에 실패하므로 머지 게이트에 두지 않는다.

### 10.2 환경 고정

| 항목 | 방법 |
|---|---|
| Python | 3.12 (`actions/setup-python`) |
| Python 의존성 | `pyproject.toml` + `uv.lock` (`pip install -e ".[dev]"` · `tests/test_uv_lock_sync.py`가 잠금 파일 일치를 본다). **`requirements.txt`는 없다** — `numpy==2.1.0` 핀도 `pyproject.toml`에 있다 |
| DB | **CUBRID 11.4** 서비스 컨테이너(`cubrid/cubrid:11.4` · `cii_test`) — 헬스체크는 브로커가 아니라 DB에 `SELECT 1`로 물는다(#1058) |
| Node | 22.22.0 — `frontend/package.json`의 `engines`와 `ci.yml`·`audit.yml` 세 곳에 같은 값이 손으로 들어 있다(자동 동기화 없음) |
| OS | `ubuntu-latest` |

### 10.3 RNG 재현성 검증

별도의 선행 스크립트는 없다 — `tests/test_rng_reproducibility.py`(`UT-RNG-001`, `TECH_SPEC §2.5.1` canonical vector 일치)가 pytest 안에서 핀 환경을 매 실행 검증한다. 비트 정확 일치가 깨지면 그 파일이 실패한다.

---

## 11. 테스트 요약

### 11.1 테스트 수

**수치는 `§14.2` 말미의 합계 문장 하나에만 적는다.** 파일·함수 수는 CI가 실측과 대조한다(`tests/test_testplan_sync.py`). 이 절과 `README` 문서 구조 표는 **수치를 다시 적지 않고** 그 문장을 가리킨다.

> **[#830 정정] 이 절의 영역별 표를 뺐다.** 2026-08-15 실측(62파일 · 469함수)에서 멈춰 있었고, 같은 문서 `§14.2`는 그사이 121파일 · 1631함수로 늘어 **한 문서 안의 두 합계가 서로 달랐다.** 이 절 각주가 두 표를 「파일별 내역은 `§14`에 있다」로 연결해 두었기 때문에 **어느 쪽이 현재인지 읽는 사람이 판단할 수 없었다.** 가드는 `§14.2`만 봤다. 영역별로 다시 세어 되살리면 **같은 수치를 두 곳에서 손으로 맞추는 구조**가 그대로 남으므로, 수치를 한 곳에만 두고 이 절이 수치를 다시 품으면 가드가 실패하게 했다.
>
> 프론트엔드(`vitest`)는 이 문서의 관할 밖이다(`§14.6`). 종전 이 자리의 「331건」도 멈춘 수치였다 — 가드가 없는 수치는 적지 않는다.

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
| `test_account_self_service_db.py` | 19 | **§4.7 API · 인증** — 현재 비밀번호 오입력은 **`INVALID_CREDENTIALS` + 칸 짚기**, 세션 없음은 여전히 `UNAUTHORIZED` — **코드만으로** 두 사유가 갈린다(`#902`) · 계정 관리(비밀번호 변경·표시 이름 변경·탈퇴). **응답이 아니라 DB를 다시 읽어** 확인한다 — detached 객체를 고치면 200이 나가는데 아무것도 안 쓰인다 (`#506`) |
| `test_annual_run_restrict_db.py` | 2 | §5 DB · 제약·마이그레이션 |
| `test_api_spec_endpoints_sync.py` | 5 | **§14 문서 동기화 · `API_SPEC §12` ↔ 실제 라우트** — 어긋남을 **세 방향**으로 본다: 「미구현」으로 적은 것이 정말 없는지 · 표시 없는 것이 정말 있는지 · **표에 없는 라우트가 코드에 있지는 않은지**. 마지막이 조용하다 — `#506`의 계정 관리 3종이 `§1.2` 본문에는 있고 `§12`에만 없어 **같은 문서가 자기와 어긋난** 채 두 판을 지났다. `app.routes`가 아니라 OpenAPI를 읽는다 (`#634`에서 0개를 검사하고 통과할 뻔했다) (`#591`) |
| `test_api_spec_request_fields_sync.py` | 19 | **§14 문서 동기화 · `API_SPEC` JSON 요청 표 ↔ 요청 스키마** (`#1523`) — 엔드포인트만 보던 위 검사가 못 보는 **필드**를 본다. 요청 표 8곳(`§2.6`·`§2.10`·`§2.17.1`·`§4.1`·`§5.1`·`§5.2`·`§6.1`·`§15.1`)을 **양방향·필수 여부까지** 대조하고(「조건부」는 선택 필드와 짝 · 모르는 필수 표기는 실패), 예시만 있는 절 5곳은 키 집합, PATCH 문장 절 3곳은 「전부 선택」, `§2.17.2`는 상위 표 + `plan_name` 합성으로 본다. `api/schemas/*`의 **모든 요청 모델이 어느 대조에든 들어야** 한다(인증 10종은 표가 없어 사유와 함께 목록 — 후속). 첫 실행에서 `§2.10`·`§2.17.1`·`§5.2` 표의 누락 7행이 나왔다 — `destination_port_name`(`#1454`)처럼 표가 스키마를 뒤따르지 못한 자리 |
| `test_app_user_migration.py` | 2 | §5 DB · 제약·마이그레이션 |
| `test_audit_events_db.py` | 3 | §3 통합 · 감사 로그 |
| `test_audit_actions_db.py` | 16 | **§3.7 통합 · 감사 로그** — 항차 확정(`VOYAGE_CONFIRM`, 변경 전/후 포함) · 계산 실행의 해시 기록 · **기능③ 실행과 재현 검증이 남는가**(`#869`). **라우트를 지나서** 확인한다 (`#65`) · **확정 뒤의 전환**(`#1328`) — `PRD §8.1.1`·`API_SPEC §3.5`가 `CONFIRMED → COMPLETED`(정정)·`CONFIRMED → ARCHIVED`(보관)에 「audit log 필수」를 정하는데 코드는 `TECH_SPEC §13.1`(「항차 확정」 하나)만 근거로 삼아 **확정만** 남겼다 — **확정된 실적을 되돌려 고친 뒤 다시 확정하면** 로그에 「확정」 두 건만 남고 **누가 언제 되돌렸는지**가 사라진다. ⚠️ **기록 대상을 넓히지 않았는지도 함께 본다** — 그 검사가 없으면 「모든 전환을 기록한다」로 만족시킬 수 있고, 그러면 `record_voyage_confirm`이 세운 판단(무엇이 중요한지를 흐리지 않는다)이 무너진다 · **감사 INSERT가 실패하면 원본도 남지 않는가**(`IT-AUDIT-004` · `#1625`) — 네 경로(항차 확정 · 기능① · ② · ③)에 `insert_event` 실패를 주입해 상태·`calculation_run`(기능③은 스냅샷·실행 행까지)·`audit_log` **셋 다 없는지**, 반대로 계산 이력 INSERT가 실패하면 감사도 없는지. 원본과 감사는 한 트랜잭션이다(`TECH_SPEC §16.3`) |
| `test_voyage_transition_canon_sync.py` | 4 | **§5 인프라 · 문서 정합** — 항차 상태 전환 ↔ `PRD §8.1` 상태도 ↔ `API_SPEC §3.5` 표 (`#1328`). 세 곳이 같은 것을 말하는데 **아무도 대조하지 않았다** — `DRAFT → CANCELLED`가 코드와 **화면**(`voyageRules.ts`)에는 있고 정본 둘에는 없었다(문서를 보고 만든 쪽은 **422를 기대**한다). 어느 쪽이 틀렸다고 단정하지 않는다: **갈렸다는 사실**을 드러내고 무엇을 정본으로 삼을지는 사람이 정한다. ⚠️ **파서가 `[*] --> DRAFT`(시작 표시)를 전환으로 세지 않는지**와 **읽은 집합이 비어 있지 않은지**를 먼저 본다 — 빈 집합이면 양쪽이 다 비어도 대조가 통과한다 |
| `test_auth_api.py` | 22 | **§4.7 인증 API** — 계정 존재 여부 비노출 · 가입 중복 고지 · 이메일 정규화 · **가입 게이트 왕복**(`AT-AUTH-016` · `#808`) |
| `test_auth_failure_paths.py` | 7 | §4.7 API · 인증 — **CSRF 403은 새 토큰을 실어 주지 않는다**(`#1366`): `API_SPEC §1.4`가 *「화면이 토큰을 다시 실어 재시도한다」*고 적었으나 **서버에 토큰을 다시 받을 자리가 없다** — `csrf` 쿠키는 세션을 발급하는 응답에서만 나온다. 실패 뒤 세션이 멀쩡한 조회 2종을 불러도 토큰이 돌아오지 않는 것까지 본다 |
| `test_auth_session.py` | 27 | §4.7 API · 인증 |
| `test_auth_wiring.py` | 10 | §4.7 API · 인증 |
| `test_benchmarks.py` | 5 | **§6 성능 벤치마크** — `PERF-001`~`004` · `PRD §16.1` p95 목표를 정본 값 그대로 · CI `test` 잡 안에서 매 PR (`#67`) |
| `test_calc_run_needs_recalc_db.py` | 11 | §5 DB · 제약·마이그레이션 |
| `test_coverage_config.py` | 2 | **§5 인프라 · 계측 설정** — `pyproject.toml`의 `[tool.coverage.run] concurrency`에 `thread`·`greenlet`이 **둘 다** 있는지. 없으면 HTTP 검사가 지나간 라우트 본문이 **미실행으로 집계**되고, 그 상태에서 「검사가 있는데 안 돈다」로 오진하게 된다 — `#871`이 실제로 그렇게 읽혔다. 설정 한 줄이라 지워져도 아무 검사가 깨지지 않으므로 가드가 없으면 다음에 커버리지를 들여다볼 때까지 드러나지 않는다 (`#871`) |
| `test_compose_env_wiring.py` | 18 | **§5 인프라 · 배포 배선** — compose가 `.env`를 컨테이너에 주입하는지, `environment:`가 `DATABASE_URL`을 덮는지 (`#508`) · **`.env.example`이 `APP_ENV`를 설정하지 않는지**(`#810`) · **프로덕션 `app`이 호스트 포트를 열지 않는지**(`#811`) · **본보기가 앱이 읽는 변수를 전부 적는지 — 상수를 경유해 읽는 것까지**(`#1290`) · **`.env.app.example`이 적는 값을 OCI 분리 토폴로지 compose가 실제로 쓰는지**(`#1290` — 그 파일에는 `env_file:`이 없어 `environment:`에 없으면 `.env`에 채워도 닿지 않는다) · **자동 배포가 `APP_ENV`를 렌더링하는지(기본 staging)**(`#1201` — 첫 자동 배포가 이 값 없이 `production`으로 떨어져 SMTP 가드에서 죽었다. 수동 절차 §3.3은 `staging`을 적었다). 뒤의 셋이 조용하다 — 본보기를 그대로 `.env`로 복사하면 `docker-compose.prod.yml`의 `${APP_ENV:-production}` 치환이 그 값을 읽어 **프로덕션 스택이 development로 뜨고**, `:8000`이 열린 채 `#786` ⑵가 `USE_FORWARDED_FOR=true`로 바꾸면 공격자가 그 포트에 직접 붙어 `X-Forwarded-For`를 위조해 **요청 한도를 완전히 우회**한다. 개발 compose의 `8000:8000`은 그대로 유지되는지도 함께 본다 · **OCI 분리 토폴로지의 두 구멍**(`#1331` — `SMTP_PORT`를 빈 값이 아니라 `587`로 넘기는지 · `LOG_FILE`과 **이름 있는 로그 볼륨**이 있는지 · 그 경로가 `docs/OPERATIONS.md §8.2.1`이 적는 경로와 같은지). 둘 다 단일 호스트 compose에는 있었고 분리 토폴로지 파일만 빠져 있었다 — 「문서대로 했는데 안 된다」에 이르는 길이다 |
| `test_deploy_frontend_origin.py` | 6 | **§5 인프라 · 배포 배선** — 클라우드 배포가 화면과 API를 **같은 오리진**에 두는지 (`#1322`). `deploy.yml`의 `VITE_API_BASE_URL`이 상대 경로인지 · Pages Function `/api/*` catch-all(`functions/api/[[path]].ts`)과 그 순수부(`_proxy.ts`)가 있는지 · `wrangler.toml`이 `API_ORIGIN`과 `pages_build_output_dir`을 들고 있는지 · 배포 명령이 출력 디렉터리를 위치 인자로 주지 않는지(설정과 충돌해 wrangler가 거부한다). ⚠️ **되돌림이 조용하다** — 절대 주소로 한 글자만 되돌리면 혼합 콘텐츠·`Secure` 쿠키 거부·`SameSite=Lax` 세 겹이 한꺼번에 돌아오는데, **배포는 성공하고 `/health`도 200이며 CORS preflight도 통과한다.** 로그인 버튼을 눌러 봐야 드러나고 그 시점이 시연 당일이면 늦다 — 종전 「배포 검증 결과」가 정확히 그 셋만 확인하고 **로그인 성공 항목이 없었다**. `#1496`이 둘을 더했다 — 🔴 **`API_ORIGIN`이 IP 리터럴이 아닌지**(Cloudflare 공식 문서: *「Workers 서브리퀘스트는 URL로만 보낼 수 있고 IP로는 보낼 수 없다」* · 실측 `error code: 1003`) · **배포가 그 값을 시크릿에서 렌더하는지**(터널 호스트명은 커밋 시점에 알 수 없다). ⚠️ **이것도 조용하다** — 배포는 성공하고 화면은 200으로 뜬다. 끊기는 것은 `/api/*`뿐이라 `#1322` 이전(혼합 콘텐츠)과 **화면에서 구분되지 않는다** |
| `test_deploy_demo_seed.py` | 4 | **§5 인프라 · 배포 배선** — 배포가 데모 데이터를 **수동 트리거로만** 적재하는지 (`#1485`). 배포본에 **선박이 0척**이었고, 원인은 환경 가드가 아니라 **호출 누락**이었다 — `deploy.yml`이 규제 파라미터 시드만 부르고 `demo_seed`를 한 번도 부르지 않았다. ⚠️ **「데모 데이터는 `development`·`test`에서만 적재된다」는 설명은 틀렸다** — `seed_demo()`는 환경을 보지 않고, 가드는 `seed_demo_user()`(시연 계정) **한 항목 안에만** 있다. 넷을 잠근다 — ⑴ 호출이 있는가(없으면 다시 0척) ⑵ `SEED_DEMO` 조건 **안**에 있는가(무조건 실행이면 시연 데이터가 매 배포마다 운영 DB에 들어간다) ⑶ `--clear`가 **제 입력** 뒤에 있는가(같은 스위치에 묶으면 적재하려다 지운다) ⑷ `--clear` 진입점이 있는가 — 적재는 덮어쓰지 않는데(`IntegrityError`를 삼킨다) 시드 시각은 **적재일 기준 상대값**이라(`#792`) 지우고 넣어야 갱신된다. 종전에는 배포본 초기화 수단이 `force_db_init`(볼륨 파괴, 비가역)뿐이었다. ⚠️ **되돌림이 조용하다** — 조건을 지우거나 호출을 빼도 배포는 성공하고 `/health`도 200이다 |
| `test_deploy_env_rendering.py` | 3 | **§5 인프라 · 배포 배선** — 배포가 렌더하는 `.env`가 **compose가 쓰는 값을 빠뜨리지 않는지** (`#1475`). 체인은 세 고리인데(`본보기 → compose → deploy.yml의 .env 렌더`) 검사는 **둘까지만** 있었다 — `#1290`이 첫 고리를 메우고 멈췄고, 그래서 `INITIAL_ADMIN_EMAILS`가 본보기에도 compose `environment:`에도 있는데 **배포가 쓰지 않아 항상 빈 값**이었다. ⚠️ **`cat > .env`가 통째로 덮어쓰므로** app-01에 손으로 적어 두어도 다음 배포가 지운다 — `#508`·`#1290`·`#1331`과 같은 「적어 뒀는데 아무 일도 없다」 계열이다. ⚠️ **증상이 환경에 따라 갈린다** — `production`이면 기동 거부로 배포 로그에 빨갛게 남지만 **`staging`이면 조용히 관리자 0명으로 뜬다**(`role_bootstrap` 독스트링이 그 공백을 미리 적어 두었다). 배포본은 `staging`이라 **더 조용한 쪽**이었다. 옛 이름 `INITIAL_OFFICE_EMAILS`를 **렌더하지 않는 것**도 함께 본다 — 렌더하면 이름이 바뀐 것을 알리는 기동 거부가 무의미해진다(`#1301`). 돌연변이 3종 **3/3 검출** |
| `test_tour_gate.py` | 14 | **§2 단위 · 둘러보기 접근 코드** (`#1486`) — 🔴 **fail-closed**가 핵심이다. `TOUR_ACCESS_CODE`가 없거나 공백뿐이면 **정답 코드를 넣어도 거절**한다. 가입 게이트(`SignupGate.is_open`)는 둘 다 비면 **통과**시키는데, 그 패턴을 여기에 쓰면 **변수 미설정 배포에서 누구나 관리자 세션을 받는다** — `#1058`·`#810`이 세운 「닫는 쪽으로 틀린다」와 같은 방향이다. 한 글자 차이·대소문자·접두사 일치(양방향)·빈 제시도 함께 잠근다. 환경은 `environ` 인자로 주입해 `os.environ`을 건드리지 않는다 |
| `test_tour_login_db.py` | 12 | **§4 API · 둘러보기 로그인** (`#1486`) — 코드가 맞으면 `ADMIN` 세션(`sid`·`csrf` 쿠키), 미설정·불일치는 **같은 422·같은 문구**(꺼짐과 불일치를 가르지 않는다). 잠그는 것 넷이 더 있다 — ⑴ 스텁 계정이 **`POST /auth/login`으로 열리지 않는다**(Argon2 형식이 아닌 해시 · 이메일이 알려져도 코드 없이는 못 들어온다) ⑵ 재호출이 **같은 고정 UUID를 재사용**한다 ⑶ 강등해 두어도 다음 로그인이 `ADMIN`으로 되돌린다 ⑷ **탈퇴(`is_deleted`)해 두어도 되살린다** — 라우트가 PK로 직접 가져와 `is_deleted`를 보지 않으므로, 되살리지 않으면 **탈퇴한 계정이 살아 있는 세션을 갖는다**(화면은 멀쩡하고 계정 목록에만 없다). 그리고 ⑸ **스텁이 「마지막 관리자」 계수에 들지 않는다** — 그냥 세면 사람 관리자가 한 명뿐일 때도 「둘」로 읽혀 강등이 통과하는데, 둘러보기는 코드가 설정돼 있을 때만 닿는 **런타임 설정**이라 코드를 비우면 역할을 되돌릴 사람이 없어진다. 감사 로그는 성공 `{"tour": true}` · 실패 `reason="tour_code_rejected"`이며 **코드 원문을 남기지 않는다**. `#1495`가 둘을 더했다 — 🔴 **스텁 이메일로 재설정을 요청해도 토큰이 발급되지 않는다**(발급되면 확정 시 Argon2 해시가 되어 `POST /auth/login`이 열리고 **접근 코드를 비워도 닫히지 않는다**. ⚠️ **응답은 일반 계정과 같아야** 하므로 그것도 함께 단언한다) · **해시가 이미 바뀐 행은 다음 로그인이 되돌린다** |
| `test_tour_policy_db.py` | 9 | **§4 API · 둘러보기 읽기 전용 정책** (`#1486` 후속) — 공개 스위치로 문을 넓히면 인터넷의 누구나 **관리자 세션**을 받으므로 권한을 중앙에서 묶는다(`auth/tour_policy.py`). 잠그는 것: ⑴ 읽기(`GET /fleet/summary`)는 **200**(이 대조가 없으면 전부 막아도 통과한다) ⑵ 쓰기(`POST /vessels`)는 403이고 **행이 생기지 않는다**(403인데 행이 생기면 정책이 라우트 뒤에서 돈 것이다) ⑶ `GET /auth/users`는 **GET이지만** 403 — 실제 가입자 이메일이 실린다 ⑷ `GET /audit-logs`도 403 ⑸ 탈퇴는 403 — **공유 계정이라 한 사람이 모두의 둘러보기를 끊는다** ⑹ 로그아웃은 통과(자기 세션 한 줄만 닫는다) ⑺ 🔴 **대조군 — 같은 요청이 일반 관리자에게는 통과한다**(없으면 「서비스 전체 읽기 전용」 구현도 통과한다). 돌연변이(미들웨어 가드 제거) 4/7 검출 |
| `test_data_export_db.py` | 32 | **§3.10 통합 · 자료 내보내기** — **왕복**(내보낸 파일을 그대로 다시 가져온다. 깨져도 오류가 아니라 「필수 컬럼이 없습니다」로만 보여 눈으로는 지켜지지 않는다) · 채울 수 없는 열을 두지 않는다(`attained_cii`·`rating`. 종전의 전제 단언(`calculation_run.voyage_id` 전부 NULL)은 `#817`로 전제가 사라져 걷었다 — 판단은 「항차 하나의 CII는 정본의 양이 아니다」로 유지) · BOM·CRLF · 수식 주입 4종 · 한 행 = 항차 × 연료 · `year`의 type별 의미 · **행 수 상한을 두지 않는다**(`#1078` — 계산 이력만 페이지네이션 함수를 빌려 써 10,001행에서 조용히 잘렸고, 연도 필터가 그 뒤에 걸려 상한 밖의 연도는 0건이 나왔다. 10,002건을 넣는 이유는 10,001건까지는 종전 코드도 전부 돌려주었기 때문이다) · HTTP 계약(라우트 등록·인증 뒤·`Content-Disposition`) (`#59`) · **수치 열 선언**(`IT-EXPORT-010` · `#1247` — 선언 목록이 실제 열 이름만 담고 사용자 입력 열이 없는가 · `kinds`가 열 순서인가 · `co2_ton`의 `-12.5`는 접두 없이, `voyage_no`의 같은 값은 접두를 받는가 · 숫자 아닌 값은 되돌아가는가) · **계획 거리 출처 열**(`#1354` ⑵) — 내보낸 파일이 **추정 거리와 직접 입력을 구분한다**. 화면은 `COORDINATE_ESTIMATE`에만 「좌표 기반 추정 거리」를 붙이는데(`PRD §15.2`) 파일에는 그 축이 아예 없어 **두 값이 같은 모양**이었다. ⚠️ **`null`은 빈 칸이다** — 「모른다」이지 「직접 입력」이 아니며, 채우면 `PRD §0.3`이 금하는 거짓말이 된다. 새 열이 **왕복 구간(앞 7열)을 밀어내지 않는지**도 함께 본다 |
| `test_data_quality.py` | 14 | **§2 단위 · 데이터 점검 판정**(`#513` · `PRD §17.4`) — 이상치 경계가 **배타적인가**(정확히 0.6배·1.4배는 정상) · 톤↔kg 입력 실수를 잡는가 · 기대 연료가 **cubic law**를 따르는가(선형이면 감속 항차가 이상치가 된다) · 속력 상한·불일치 · ⚠️ **판정하지 못한 것이 0건과 섞이지 않는가** · 대체된 연료로 판정하지 않는가 · 완결성이 **CO₂ 비율**인가 · 배출 없음이 100%가 아닌가 · **응답 직렬화의 절사**(`#1349` · `TECH_SPEC §1.2.1`) — CII 필드는 전송 자릿수로 `ROUND_DOWN`, 그 밖은 `ROUND_HALF_UP` |
| `test_data_quality_db.py` | 19 | **§4 API · 데이터 점검 서비스**(`#513` · `API_SPEC §2.16`) — 네 심각도가 실제 행에서 갈리는가 · ⚠️ **CII 영향이 같은 함수로 따로 구한 두 누적값의 차와 같은가** · 실적·계획 모두 빈 행이 대체가 아니라 계산 불가인가 · 이상치를 계산에서 빼지 않는가 · 실적 미입력은 완결성에서 빼지 않는가 · **이상치 항차는 완결성의 실측에서 빼는가** · 선박 단위 사유가 `§2.8`과 같은 어휘인가 · 그룹 순서 · 응답 필드 집합(영향 블록이 있는 행과 없는 행 둘 다) · **실제 HTTP 경로**(인증 401 · 봉투 · 연도 범위 422) · `#1532` — 완결성의 **분자·분모·제외 내역**(`completeness`)이 응답에 실리고 「실측 + 제외 합 = 누적」이 성립하는가 · 유일한 항차가 이상치일 때 0%가 이상치 축으로 설명되는가 · 두 심각도가 겹친 항차는 **한 축에만** 들어가는가(계산 불가 > 대체 > 이상치) · 비율이 없으면 내역도 없는가 |
| `test_db_target_guard.py` | 22 | **§1.6 테스트 격리** — 파괴적 롤백 테스트가 개발 DB를 치지 않게 한다. CI에서 그 테스트가 조용히 skip되는 것도 함께 막는다 (`#507`) |
| `test_suite_lock_db.py` | 3 | **§1.6 테스트 격리 · 실행 잠금** — 스위트가 도는 동안 테스트 DB 잠금을 쥔다 · **두 번째 `pytest`를 실제로 띄워** 원인을 말하며 즉시 멈추는지(종료 코드 3) · `upgrade head` 실패가 남은 리비전과 복구 절차를 알리는지 (`#894` — `#691`과 다른 층: 이쪽은 「지금 누가 쓰는가」) · **CUBRID에서는 호스트 파일 잠금**(`fcntl.flock`, 대상 DB별 잠금 파일 · `#1250`) — `#1058` 이후 no-op이라 두 검사가 skip돼 있던 것을 되살렸다 |
| `test_input_boundaries_api_db.py` | 5 | **§5.6 API · 입력 경계** — 같은 입력에 **엔드포인트마다 다르게 답하는 것**을 막는다. 세 자리 모두 다른 엔드포인트가 이미 옳게 처리하던 입력이다 — ⑴ `year=2019` 연간 리포트가 **사용자가 보낸 적 없는 `from`에 대한 422**를 냈다(최근 3년 창이 2017을 파생시켜 `API_SPEC §2.7`의 `from ≥ 2019`에 걸린다). ⑵ 항차 목록 `limit`이 정규화되지 않아 `-2`→**500**, `-1`→**0행인데 has_more=true·next_cursor=null**, `0`→조용히 20건이었다(선박·계산 목록은 422). ⑶ `ship_type` 변경이 재계산 표시를 안 남겼다 — 선종은 **capacity 축·기준선 a/c·등급 경계 d1~d4를 전부** 바꾼다. ⚠️ **상한 절단 정책도 함께 잠근다** — 하한만 보면 상한도 막는 방향으로 잘못 고칠 수 있다. ⑶만 서비스 계층에서 본다 — `calculation_run`이 immutable이라(`008`·`024`) HTTP로 검사하면 **정리할 수 없는 행이 남는다** (`#818`) · ⚠️ **`simulation_runs` 상한 초과는 422가 아니라 10000으로 잘라 `SIMULATION_RUNS_CLAMPED`** — `PRD §12.8`대로 엔진이 자르는데 요청 스키마가 먼저 422를 내 그 경고가 HTTP로 도달할 수 없었다. 하한 미만은 여전히 422 (`#830`) |
| `test_issue_matrix.py` | 6 | **§14 운영 · 이슈 매트릭스 집계** — `#93`(추적용 메타 이슈)의 「현재 상태」 표를 손으로 갱신해 오다 **세 번 낡았다**. 세는 일을 `scripts/issue_matrix.py`로 옮기고 그 집계를 잠근다: **라벨 없는 이슈가 표에서 사라지지 않는다**(08-22에 겪은 상태 — 사라지면 「없는 것」이 된다) · 레이어를 둘 붙인 이슈를 **두 번 세지 않는다**(합계가 열린 이슈 수와 달라지면 그 차이를 설명할 수 없다) · 비어 있는 레이어도 행을 낸다. 네트워크를 타지 않는다 — `gh`를 부르는 자리는 `fetch` 하나이며 여기서 보지 않는다 (`#93`) |
| `test_roles_db.py` | 15 | **§4.7 인증 API · 역할 3종**(`AT-AUTH-017` · `#672` · `#1301`) — 현장직 403 `FORBIDDEN_ROLE`(표의 14경로 전부 실제 요청) · 정본 `API_SPEC §1.2` **두 표**(사무직 전용 · 관리자 전용) ↔ 소스 `require_office`·`require_admin` 대조(한쪽만 바뀌면 실패 · 계정 관리 2경로가 사무직 표에 남아 있으면 실패 — `#1301`) · 최초 관리자(`INITIAL_ADMIN_EMAILS` — 가입·로그인 승격, 감사 1회 · 운영에서 비면 기동 거부) · 목록·역할 변경 응답이 `/auth/me` 계약과 같은가 · 마지막 관리자 탈퇴·강등 409 · 044 마이그레이션이 기존 계정을 사무직으로. **응답이 아니라 DB를 다시 읽어** 본다 |
| `test_request_bounds.py` | 6 | **§5 API · 입력 경계**(`#1086`) — 항차·시나리오·정박 요청 15필드의 스키마 경계가 **ORM 컬럼 `Numeric(p,s)`와 같은가**(`#860`의 선박 검사와 같은 방식) · `regulation_year`가 DB CHECK(2019~2050)와 같은가 · 종전 500이던 항차 5입력(연도 2010/2080 · 거리 0.001/초과 · 속력 10000)이 422 · 정박 연료 0·0.001 거부 · 소요시간 0.01h 미만은 계산 단계에서 422(`_db_rows`) |
| `test_request_instants.py` | 4 | **§5 API · 요청 시각의 시간대**(`#1627` · `API_SPEC §1.11`) — 항차 생성·수정·실적 · 시나리오 채택 · 연간 시뮬레이션 **여덟 자리**에서 ⑴ 시간대 없는 시각이 스키마에서 걸리는가(`timezone_aware`) ⑵ 서로 다른 offset이 같은 순간이면 **같은 UTC 값**이 되는가 ⑶ 빈 값은 그대로 빈 값인가. 시간대 없는 값이 들어오면 **읽는 쪽에 따라 다른 순간**이 되어 배포 호스트의 시간대가 항차 순서·연간 귀속·`as_of` 경계를 바꾼다 — 같은 요청이 호스트에 따라 다른 답을 낸다. `#1333`(not under way)·`#906`(CSV)이 같은 규칙을 먼저 세웠고 이 파일이 나머지 세 경로를 잠근다. **DB 없이 돈다** — 스키마 경계만 보므로 모델을 직접 만든다. 돌연변이(한 필드를 `datetime`으로 되돌리기) **5건 검출** |
| `test_response_contract_db.py` | 14 | **§4 API · 응답 계약** — 화면이 쓰는 엔드포인트 **16종의 필드 집합을 중첩까지** 대조한다(400키). 라우트 46개가 `dict`를 돌려줘 OpenAPI 응답 스키마가 0건이라 **응답이 조용히 바뀌어도 아무것도 잡지 않았다**(`#559`). **값이 아니라 키**를 본다 — 결함의 실제 모습이 이름 변경·필드 누락이고 그때는 오류가 아니라 화면에 `undefined`가 뜬다. **집합 동등**이라 필드를 더해도 실패한다. `data[]`가 비면 그 아래 키가 통째로 사라지므로 `/calculations`는 **먼저 계산을 하나 만들고** 조회한다 — 새 DB에서 0건임을 실측했다 (`#559`) |
| `test_scenario_example_sync.py` | 5 | **§14 문서 동기화 · `API_SPEC §5.1` 응답 예시 ↔ 실제 응답** — 문서에서 **요청과 응답을 둘 다 읽어** 실제로 실행하고 값을 대조한다. `#559`의 응답 계약이 **필드 집합**을 보는 것과 층이 다르다 — 이쪽은 「인쇄된 숫자가 맞는가」다. 값을 한 번 고치는 것으로 부족한 이유를 `#151` 본문이 적었다: **개별 수치만 고쳐도 다음 검토에서 다시 어긋난다.** 예시가 다시 밋밋해지는 것(셋 다 등급 E → margin 전부 null)도 함께 막는다 (`#151`) |
| `test_seed_cf_matches_fuel_table.py` | 3 | **§5.7 DB · seed 적재** — 데모 시드가 찍는 `cf_used`가 **연료 종류의 정본 CF와 같은가**. 막으려는 것은 계산 오류가 아니라 **원문 대조를 마친 표가 조용히 무력화되는 것**이다 — `fuel_type` 8행이 `MEPC.364(79)`를 출처로 갖고 `031`이 `content_hash`까지 추적하는데, 계산에 들어가는 것은 **적재 시점에 얼린 스냅샷**이라 시드가 틀리면 표를 아무리 관리해도 값이 틀린 채로 남는다. 종전 시드 검사는 **행 수뿐**이었다(`test_demo_seed_counts.py`). ⚠️ **시드 행만 본다** — `PRD §8.4`상 규정 개정 뒤의 과거 실적은 달라도 정상이라, 전체를 훑으면 정당한 불일치까지 잡는다. 상수 재발 가드는 **AST로 이름·키만** 본다 — 문자열로 훑으면 자기 설명에 걸리고(4회째 함정), 값 범위로 보면 **연료 톤수 4건**이 걸린다 (`#797`) |
| `test_vessel_spec_bounds.py` | 3 | **§5.6 API · 입력 경계** — 선박 제원 4필드가 **DB가 담을 수 없는 값**을 API에서 걸러내는가. 종전 스키마는 `> 0`만 봐서 `1e-7`이 통과했고 DB가 `0.00`으로 반올림한 뒤 `chk_dwt_positive`에 걸려 **500**이 났다(`1e10`은 정밀도 초과로 500). ⚠️ 이슈 본문은 「1e-7이 저장된다」로 적었으나 **실측하면 저장되지 않는다** — DB가 이미 막고 있었고 결함은 500이었다. 경계를 스키마에 적어 두면 정밀도가 바뀔 때 한쪽만 고쳐지므로 **ORM 모델의 `Numeric(p,s)`에서 기대값을 계산해 대조**한다. 소수 셋째 자리는 막지 않는다는 것도 함께 잠근다 (`#860`). **방형계수는 경계 대조 집합에 넣지 않고** 물리 범위(0 < CB ≤ 1) 사례로만 잠근다(#966 — 저장 범위를 일부러 좁히는 도메인 규칙이라 정밀도와 같아질 수 없다) |
| `test_workflow_timeouts.py` | 6 | **§5 인프라 · CI 안정성** — 모든 워크플로 잡에 실행 상한이 있는지, `apt-get`이 `timeout`으로 감싸였는지 (`#533`) |
| `test_workflow_action_pins.py` | 3 | **§5 인프라 · 워크플로 액션 고정**(`#1638` · `F-12`) — `uses:`가 **커밋 SHA**인가 · SHA 옆에 **버전 주석**이 있는가 · 파서가 `uses:` 줄을 실제로 읽었는가. 태그는 움직인다 — 같은 `v7`이 어제와 오늘 다른 코드를 가리킬 수 있고, 이 저장소의 배포 워크플로는 **GHCR 쓰기 권한과 SSH 개인키**를 쥐고 돈다. 셋째 검사가 없으면 파서가 깨져 0건이 될 때 **빈 것끼리 비교해 통과**한다(`test_workflow_timeouts.py`와 같은 판단으로 `PyYAML`을 들이지 않는다). 저장소 설정 `sha_pinning_required`는 관리 권한이라 별도이며, 설정과 파일이 어긋나는 것 자체를 여기서 본다 |
| `test_deploy_sha_pinning.py` | 4 | **§5 인프라 · 배포 커밋 고정**(`#1633` · `F-10`) — 원격이 **브랜치를 받아 가지 않는가** · 두 호스트가 **이 실행의 커밋**을 넘겨받는가 · 받은 것이 다르면 **멈추는가** · 파일을 실제로 읽었는가. 종전에는 이미지에 `GITHUB_SHA`를 붙이면서 원격은 `git fetch … main`이라, 빌드 뒤 다른 PR이 머지되면 **이미지 A와 실행 코드 B**가 함께 돌고 두 호스트가 받는 시점이 다르면 **호스트끼리도 어긋났다** — 이 저장소는 PR을 연달아 머지하므로 흔한 일이다. 배포는 실행해야 재현되는데 그 실행이 **운영 서버를 건드리므로**, 재현 대신 배포가 무엇을 받아 가는지를 파일에서 본다 |
| `test_deploy_remote_script_syntax.py` | 3 | **§5 인프라 · 원격 스크립트 문법**(`#1794`) — `deploy.yml`이 `ssh … bash -s`로 보내는 heredoc 본문은 **원격 bash가 읽는 스크립트**인데 저장소 어느 검사도 그것을 셸로 읽어 보지 않았다. `#1633`(PR `#1762`)이 넣은 `echo "[deploy] 실행 커밋 ${got}` 에서 **닫는 큰따옴표가 빠져** 열린 문자열이 세 줄 뒤의 `"` 까지 삼켰고, 한참 뒤 괄호가 있는 줄에서 `syntax error near unexpected token '('` 로 터져 **운영 배포가 멈췄다**(`deploy-db` 실패 → `deploy-app` skipped). 블록을 뽑아 **`bash -n`**(실행하지 않고 문법만 본다)으로 검사하고, `bash -n`이 우연히 통과하는 경우를 위해 **한 줄 안에서 큰따옴표가 짝인지**도 본다. 블록이 2개인지 함께 세어 검사가 조용히 통과하지 않게 한다 |
| `test_depcheck.py` | 17 | **§5 인프라 · 개발 환경** — dev 이미지에 없는 런타임 의존성을 기동 전에 잡는다. 저장소의 실제 `pyproject.toml`로도 돌아 파서가 현실과 어긋나면 잡힌다. ⚠️ **판정과 종료 코드**도 본다 — `pyproject` 없음(검사 불가)은 **0**이고 없는 패키지(검사 실패)는 **1**이다. 둘을 같게 만들면 마운트가 빠진 환경에서 앱이 영영 뜨지 않는다 (`#523`) |
| `test_distance.py` | 13 | **§2 단위 · 대권거리** — 날짜변경선(짧은 쪽 1°) · 극(경도 무관 · 극↔극 = πR) · 이종 반구를 **다른 식**(호 길이 · 구면 코사인 법칙)으로 대조 · 자릿수 확정 · `TECH_SPEC §6` 반경 (`#828`) · **초기 방위각**(기상 입사각의 입력 · `#766` ⑴) — 대권 항로는 **가는 방위와 오는 방위가 서로의 반대각이 아니다** |
| `test_uv_lock_sync.py` | 6 | **§5 인프라 · 의존성 선언** — `uv.lock`이 `pyproject.toml`과 어긋난 채 커밋되는 것을 막는다. 해석된 버전이 아니라 **선언**(이름·extras·범위)을 대조한다 (`#399`) |
| `test_readme_deploy_sync.py` | 4 | **§5 인프라 · 문서 정합** — `README` 「배포」 절이 실제 운영·코드와 갈리지 않게 한다 (`#1339`). 절이 ⑴ **「백엔드에 CORS 설정이 없다」류의 사실과 다른 단정**을 담지 않고 ⑵ **운영 정본(`docs/OPERATIONS.md`)과 분리 토폴로지 compose 두 파일**을 가리키며 ⑶ **이름을 적은 compose 파일이 실재하는지**까지 본다. 문장을 통째로 묶지 않는다(`AGENTS §4.6` — 표시 문구는 성질로 단언한다) — 정정 각주에서 인용하는 형태(「…는 사실이 아니다」)는 걸러 내고 **단정만** 찾는다. ⚠️ **절을 못 찾으면 나머지 셋이 「빈 문자열에 없다」로 조용히 통과**하므로 절 길이부터 본다. 돌연변이 3종(CORS 부정문 복원 · 운영 정본 링크를 없는 파일로 · 분리 토폴로지 compose 이름 제거) **3/3 검출** |
| `test_warning_codes_sync.py` | 3 | **§5 인프라 · 문서 정합** — 경고 코드 정본 사슬(`TECH_SPEC §12.3` → `API_SPEC §1.6` → 화면)이 어긋나는 것을 막는다 (`#641`) |
| `test_required_checks_doc.py` | 3 | **§5 인프라 · 머지 게이트** — CI 잡이 `AGENTS §7` required check 표에 등재됐는지. 「잡은 도는데 아무것도 막지 않는」 상태를 막는다 (`#402`) |
| `test_mail_startup_guard.py` | 5 | **§5 인프라 · 기동 검증** — 프로덕션 메일 설정이 어긋나면 **기동 시점에** 막히는지. 종전에는 첫 발송에서 500이 났다 (`#524`) |
| `test_calculation_migrations.py` | 14 | §5 DB · 제약·마이그레이션 |
| `test_calculations_api.py` | 15 | §4 API · 선박·항차·계산 |
| `test_calculation_filter_enum_sync.py` | 4 | **§5 인프라 · 문서 정합** — 계산 목록 필터의 허용값 사슬 (`#1367`). `calc_run_repo.CALCULATION_TYPES` **==** 모델 `CheckConstraint` **==** `DB_SCHEMA §2.5`, 그리고 서비스의 해시 정규식 **==** `DB_SCHEMA`가 집행하는 정규식. 두 방향 모두 나쁘다 — 코드가 **더 좁으면** DB에 있는 행을 필터로 꺼낼 수 없고(422가 나는데 그 값은 실재한다), **더 넓으면** 검증이 통과하고 빈 목록이 돌아와 **검증을 넣은 이유가 사라진다**. ⚠️ **목록이 비어 있지 않은지도 본다** — 빈 튜플이면 양쪽이 다 비어도 대조가 통과한다 |
| `test_calculations_query_db.py` | 4 | §4 API · 선박·항차·계산 — `meta.needs_recalc_total`이 **받은 페이지가 아니라 필터 전체**를 세는가(`#1076`) |
| `test_applicability.py` | 12 | **§2 단위 · CII 적용 대상 판정** — 「미해당」과 「GT가 없어 판정 불가」가 합쳐지지 않는지 · 임계값이 두 곳에 중복 정의되지 않았는지 (`#653`) |
| `test_capacity_rules.py` | 19 | §2 단위 · 계산 엔진 |
| `test_cii_engine.py` | 21 | §2 단위 · 계산 엔진 |
| `test_cii_history.py` | 8 | §4 API · 선박·항차·계산 · **응답 직렬화의 절사**(`#1349` · `TECH_SPEC §1.2.1`) — CII 필드는 전송 자릿수로 `ROUND_DOWN`, 그 밖은 `ROUND_HALF_UP` |
| `test_fleet_summary.py` | 55 | **§4 API · 선대 요약** — 규제 트리거 판정 · `days_to_d` 산식·경계 6종 · KPI 집계 · 한 척 실패의 격리(`#419`) · **경계 키가 실재하는지**(`#814`) · **기준선의 진행분**(`#864`). 마지막이 조용했다 — `fleet_summary`가 `boundaries.get("d")`를 조회했는데 `determine_rating`은 그 키를 만들지 않아 `days_to_d`가 **한 번도 숫자를 낸 적이 없었다.** 픽스처가 `{"d": ...}`라는 **엔진이 만들 수 없는 dict**여서 검사가 자기 가짜 키를 자기가 읽고 통과했다. 지금은 픽스처를 `determine_rating` 출력으로 만들고, `src/`의 `*_boundary` 리터럴 참조를 전수 대조하며, `get_fleet_summary` 응답까지 지나가 **실제로 숫자가 나오는지** 본다. **[#989] 파생 표시 2종(`soonest_d_entry`·`missing_gross_tonnage`)이 선대 전체 기준** — `limit=1`로 첫 페이지를 잘라도 페이지 밖의 급한 배를 가리키고, GT NULL만 센다(0은 「0으로 적혀 있다」다 — DB 트리거가 막는 값이지만 집계 규칙은 순수 함수 검사로 명시적으로 둔다) · **응답 직렬화의 절사**(`#1349` · `TECH_SPEC §1.2.1`) — CII 필드는 전송 자릿수로 `ROUND_DOWN`, 그 밖은 `ROUND_HALF_UP` |
| `test_mail_link.py` | 10 | **§4.7 인증 API** — 메일 링크가 프론트엔드를 가리키는지 (`#429` 회귀) |
| `test_port_geocoding_db.py` | 15 | **§3.12 통합 · 항만명 좌표 조회** — 샘플 → 캐시 → 외부 순서 · 항만이 아닌 결과는 버린다 · 실패와 없음을 가른다 · **정책(User-Agent · 초당 1회 · 캐시)을 코드가 지키는가** (`#768`) · 제공자가 **프로세스에 하나**라 라우트·동시 요청에서도 간격이 걸리는가 — 가짜 시계 (`#1335`) · **바깥을 기다리는 동안 DB 커넥션을 쥐지 않는가** — 커넥션 1개짜리 엔진으로 직접 본다 · 대기 상한 · 동시에 같은 이름을 물었을 때의 `UNIQUE` 충돌 (`#1364`) |
| `test_request_cache_db.py` | 6 | **§3.11 통합 · 요청 캐시** — 선대 요약이 같은 규정연도·기준선·등급 경계를 **요청 하나에서 다시 읽지 않는가**. 값이 같은지를 먼저 본다(캐시 켠 실행 ↔ 끈 실행의 응답이 글자 그대로 같다) — 빨라졌는데 답이 달라지면 고친 것이 아니다. 캐시는 **켠 요청에서만** 돌고 실패는 기억하지 않는다 (`#989`). **[#989 ⑵] 배치 프리페치가 캐시 키를 빗나가지 않는지** — 집계 단건 5종·진행분 3종이 0회 호출되고 배치가 `(연도, 시점)` 조합별로 정확히 나가는지를 대역으로 센다(IT-CACHE-005) |
| `test_reports.py` | 70 | **§3.4~§3.5 리포트 렌더링** — CSV injection 방어 · **수치 열 선언**(`#1247` — 선언된 열의 `-12.5`는 접두 없이, 선언 없는 열·문자열 열의 `-1+1+cmd\|…`는 종전대로 · 선언된 열에 숫자 아닌 값이 오면 문자열 규칙으로 되돌아가는가 · 라벨은 선언과 무관하게 막히는가 · 숫자 문법 · 선언 수·이름 오류) · BOM · 면책 · 한글 PDF · **`DESIGN_SYSTEM §4` 표시 형식**(자릿수·천단위 구분자·선종 표기·KST 시각). 문서가 직렬화 자릿수를 그대로 내보내 화면과 갈렸다 (`#584`) · **표시 문구 동기화**(위험도·경고·사유·항차 상태를 정본/화면과 대조 — `#631`) · **연료 표시 문구**(`fuelTypes.ts`와 대조 · `DB_SCHEMA §3.2` 8종 전수 · 모르는 코드는 코드를 그대로 — `#598`) · **렌더링이 이벤트 루프를 막지 않는가**(`#1363` — 0.3초를 동기로 쓰는 가짜 렌더러를 돌리는 동안 10 ms 틱이 계속 깨어나는가 · 동시 4건이 와도 한 번에 하나만 도는가) · **CSV 검증이 응답 시작 전에 끝나는가**(`#1368` — 제너레이터 본문 안에 있으면 첫 조각을 요구받을 때 도는데, 그때는 `StreamingResponse`가 이미 상태·헤더를 보낸 뒤라 오류 응답이 될 수 없고 **사용자는 깨진 파일을 받는다**. 「반복하지 않아도 터지는가」를 본다) |
| `test_reports_db.py` | 43 | **§4 API · 리포트 데이터 수집** — 진행 중 항차 제외 · 시나리오 인용 · 값 재계산 금지 · **실제 문서의 수치 열 선언**(`#1247` — 수치를 싣는 표 전부에 선언이 있고 선언된 열의 값은 숫자·`—`뿐인가 · 시나리오 이름은 접두를 받고 옆의 수치는 받지 않는가) · **문서 어디에도 UTC ISO가 남지 않는다**(`#646`) · **유종도 원문 코드가 남지 않는다**(`#598`) · **제출 전 자체 점검 절**(`#770`) — 새 리포트가 아니라 절인가 · 용도 고지가 실리는가 · 대체 계산을 축으로 나누는가 · 제원이 비면 **리포트 자체가 막히는가**(그래서 그 행을 두지 않았다) · **렌더링 시점에 DB 커넥션을 쥐고 있지 않은가**(`#1363`) · `#1532` — 자체 점검의 「진행 중 항차」와 「실적 확정 전 항차」가 **다른 행**이고, 확정 전 건수가 데이터 점검 화면과 같은가 |
| `test_report_export_routes_api_db.py` | 10 | **§4 API · 리포트·내보내기 라우트** — 형식 분기(html·csv·pdf)와 `Content-Disposition`(미리보기는 첨부가 아니다 · 첨부는 ASCII `filename`과 UTF-8 `filename*`을 둘 다) · 내보내기 `type` 3종의 CSV 첨부와 JSON 봉투(`meta.row_count` = 실제 행 수) · `year` 필터 · 형식·종류 오류의 422 (`#911`) |
| `test_annual_simulation_api_db.py` | 27 | **§4 API · 기능③ 실행** — 스냅샷 격리 · 정책 필터링 · 분포 프로파일 기록·**존재 검증**(`#870`) · ⚠️ **거리가 없는 선박이 500이 아니라 422인가**(서비스 · 실제 HTTP · 실행/재현 배선 — `#1084`) |
| `test_in_progress_year_scope_db.py` | 4 | **§4 API · 정본 정합 · 진행 중 항차의 연도 범위** — 과거 연도 조회에 현재 진행분이 섞이지 않는가(실시간 CII · 선대 요약 · 연간 실적 리포트) · 올해 조회에는 실제로 실리는가 (`#815`) |
| `test_ytd_definition_sync_db.py` | 5 | **§4 API · 정본 정합 · YTD 정의** — **다섯 경로**(실시간 CII · 연도별 이력 · 선대 요약 · 연간 실적 리포트 · **항차 완료 리포트**(`#866`))가 같은 attained CII를 내는가 · 리포트 한 문서 안의 두 행이 일치하는가 · 과거 연도가 진행분에 흔들리지 않는가 (`#750`) |
| `test_annual_simulation_read_db.py` | 54 | **§4 API · 기능③ 조회·재실행** — 조회가 다시 계산하지 않는지 · 스냅샷 항차 표현(⚠️ **진행 중(PLAN) 항차는 실적 일부가 있어도 계획값을 보이는가** — `#1337` · 응답의 `planned_W_capacity_nm`·`planned_M_gco2`와 대조) · 재현 판정(파라미터 변경 409 / 재현 실패 500) (`#443`) · **선박 제원 스냅샷**(`#493` — 제원·capacity·선종을 고쳐도 재현이 흔들리지 않는다 · `037` 이전 실행은 사유를 밝히고 끊는다) · ⚠️ **실행·조회·재현 응답에 `reduction_plan`이 실리는가**(`#433` — PR #1054가 저장 본문에만 넣고 응답을 조립하는 `_envelope`를 고치지 않아 **한 번도 나가지 않았다**) · **실적 보정계수**(`#363` — ⚠️ **켜고 돌린 실행이 재현되는가** · 켠 실행과 끈 실행의 `input_hash`가 갈리는가 · 켜지 않아도 계수를 싣는가 · 표본이 모자라면 적용하지 않고 경고하는가) · **확정·잔여가 상보인가**(`#1323`) — 종전에는 잔여를 `도착 예정 > as_of`로 잘라, **도착 예정이 지난 `INCLUDE_AS_PLAN` 항차가 어느 쪽에도 들지 않았다**(지연된 `IN_PROGRESS`·기한이 지난 `PLANNED`). 실측 연말 예상 등급이 **D → C**로 바뀌었고, ⚠️ **시드의 진행 항차 ETA가 `_rel(8)`이라 시드를 시연 8일 이상 전에 적재하면 그대로 재현된다.** ⚠️ **집합이 아니라 개수를 센다** — 「잔여에 들어왔다」만 보면 **확정분이 같은 항차를 함께 세는 이중 계상**을 놓친다. 돌연변이 2종(절단 복원 · 정책 필터 제거) **2/2 검출**이며 **두 방향이 서로의 반대쪽**을 잡는다 · **이미 쓴 정박·묘박 몫**(`#1803`) — 연말 예상 확정분에 들어가는가 · `as_of` 뒤에 시작한 정박은 빠지는가(⑴과 같은 절단) · 스냅샷 `not_underway_json`에 남고 재현이 같은 결과를 내는가 · 기록이 없으면 NULL인가 · **선박별 실행 목록 `§6.5`**(`#1805`) — 정렬 규약(`created_at desc, id desc`) · `limit=1`의 `simulation_id`로 `§6.2`가 열리는가 · 커서 이어 받기 · 없는 선박 404 · 깨진 커서 422. ⚠️ 한 트랜잭션 안의 실행은 `created_at`이 같아 시각이 아니라 정렬 규약을 단언한다 |
| `test_simulation_parameter_db.py` | 8 | **§5.7 DB · seed 적재** — 분포 파라미터가 PRD 표와 일치하는지 · DB→엔진 변환 |
| `test_soft_delete_db.py` | 10 | **§3.9 통합 · §5.6 DB · 소프트 삭제** — 조회·집계에서 빠지는가 · 삭제된 IMO 자리를 비우는가(partial unique) · 행이 남아 있는가 (`#66`) |
| `test_annual_simulation.py` | 72 | **§2 단위 · 기능③ 시뮬레이터** — seed 재현성 · 확률 누적 · 방향 · `§12.8` 예외 · `parameters_used` 스키마 버전 동결(`#816`) · **거리 지렛대가 강도 차이만 잰다**(`#756` — 혼합비가 아니다) · `PRD §12.6` 다섯 변수 ↔ 구현 지렛대 대응 · **필요 감축량 역산**(`#433` — ⚠️ **줄이라는 만큼 줄이면 목표 경계에 정확히 정착하는가** · 목표 경계가 등급 판정과 **같은 표**에서 오는가 · 연료 환산이 구성비 비례인가 · **잔여 계획 없음 ≠ 줄일 것 없음** · 전부 없애도 못 닿으면 그렇게 말하는가 · **데이터를 다시 읽을 수단이 없는가**) · **실적 보정계수**(`#363` — 강도의 비인가(총량 비가 아니다) · 최소 표본 미만은 `null` · 연료만 곱하고 거리는 그대로인가) · **응답 직렬화의 절사**(`#1349` · `TECH_SPEC §1.2.1`) — CII 필드는 전송 자릿수로 `ROUND_DOWN`, 그 밖은 `ROUND_HALF_UP` |
| `test_cii_current_db.py` | 54 | **§4 API · 실시간 CII 3종 값** — 등급이 ⑴에만 붙는 것 · 진행분 반쪽 주입 금지 · `as_of` 재현성 · **⑶ 연말 예상이 「남은 거리 기반」인 것**(`#798`) · **대표 유종이 행 순서에 흔들리지 않는 것**(`#867`). 마지막이 조용했다 — 종전 방식(`YTD_DAILY_AVERAGE`)은 거리·연료를 같은 비율로 더해 `M/W`가 보존되므로 ⑶이 **구조적으로 ⑴과 항상 같은 값**이었고, 그 상태를 잡는 검사가 없었다. 지금은 잔여 계획이 있으면 ⑶ ≠ ⑴임을, 그리고 ⑶이 **기능③의 `projected_attained_cii`와 문자 단위로 같음**을 단언한다 · ⚠️ **「연간 반영 안 함」 진행 항차가 누적을 바꾸지 않고 누적 반영 경고도 띄우지 않는가**(`#1085`) · **연도 없는 진행 항차**(`#1336`) — `chk_year_policy`상 `regulation_year IS NULL`은 반드시 `EXCLUDE`이고 `PRD §8.1.2`상 `IN_PROGRESS + EXCLUDE`는 합법인데, `InProgressState.for_year`가 `None != 2026`으로 **상태 전체를 비워** 선박이 `UNDER_WAY`인데 「현재 항차」 카드가 없고 `meta.simulated`도 내려갔다. `#1085`가 이미 **⑴만 비우고 ⑵는 남긴다**로 판단한 자리를 `for_year`가 뒤에서 되돌리고 있었다. ⚠️ **⑴까지 되살리지 않는지**를 함께 본다 — 그 검사가 없으면 「`for_year`를 통째로 없앤다」로 만족시킬 수 있다. 다만 **그 과잉 수정은 이 파일이 아니라 `test_in_progress_year_scope_db.py`(`#815`)가 3건으로 잡는다** — 이 함수를 손댈 때는 두 파일을 함께 돌린다 · **응답 직렬화의 절사**(`#1349` · `TECH_SPEC §1.2.1`) — CII 필드는 전송 자릿수로 `ROUND_DOWN`, 그 밖은 `ROUND_HALF_UP` · ⚠️ **⑶ 확정분의 정박 CO₂가 ⑴의 `not_underway_co2_ton`과 같은가**(`#1803` — 종전에는 ⑴만 정박을 넣어 연말 예상이 늘 실제보다 좋게 나왔다) · **⑶을 무엇이 올리는가 `drivers[]`**(`#1673`) — 합이 `attained_cii − ytd.attained_cii`와 **문자열 단위로** 같은가(진행 중 항차·잔여 계획·정박 유무 다섯 조합) · `CURRENT_VOYAGE`가 「경과분 → 계획 전량」의 변화이고 `REMAINING_PLAN`이 그 뒤의 나머지인가(같은 엔진으로 직접 만들어 대조) · 계획 강도의 부호가 그대로 드러나는가 · ⑴이 없으면 `[]`이고 ⑶이 없으면 키가 없는가 · ⑶이 세지 않는 진행 항차(계획 연료 없음 · `#812`)가 탈락으로 드러나는가 · ⚠️ **확정분 집합이 갈릴 때만 `BASIS_DIFFERENCE`가 맨 앞에 실리는가** — 실측에서는 늘 같아 엔진을 직접 불러 갈린 상태를 만든다 · 시드 벌크선 기준값(⑴ `8.213830` → `+0.760151` → `−0.008088` → ⑶ `8.965893`) · 확정 거리 0인데 ⑶이 진행 항차를 세지 않으면 `CURRENT_VOYAGE`를 생략하고 `REMAINING_PLAN` 한 줄로 사슬을 잇는가 · `EXCLUDE` 진행 항차는 `CURRENT_VOYAGE`가 없는가 · 소모율 없음(`SIMULATION_NO_FUEL_RATE`)이면 `CURRENT_VOYAGE`가 계획 전량 효과로 실리는가 — 셋 다 합 유지 |
| `test_cii_ytd_series_db.py` | 17 | **§4.11 API · 올해 누적 CII 추이**(`#1671`) — 추이의 **끝점 동치**(실적 마지막 점 = `§2.14` `ytd` · 계획 마지막 점 = `year_end_projection`, 문자 단위) · 실적 점마다 `resolve_ytd_at` 재호출과 동치 · `at` 오름차순·종류 분할 · 확정 항차는 도착 시각에 전량 · **진행 중 항차가 첫 `PLAN` 점**(`#1673` ②) · 나머지 계획은 도착 예정 순 · 예정 지난 항차는 `as_of`에 · 정박 구간은 `started_at`에 점(종료·진행 중 둘 다) · 실적 없음 200 · 과거 연도 `ACTUAL`만 + `as_of` 점은 그 해 끝 · `EXCLUDE` 점 없음·대체 플래그 · 같은 순간 두 항차는 점 하나 · 404·409·422 · 직렬화 · **데모 벌크선 기준값**(첫 점 8.979906 · 마지막 실적 8.213830 · 계획 열 끝 8.965893)과 HTTP 봉투 |
| `test_not_underway_import_db.py` | 13 | **§3.4 통합 · 정박 구간 CSV 적재**(`#765`) — 구간·연료가 함께 들어가고 CF 스냅샷이 붙는가 · 부분 성공(틀린 행의 번호와 필드) · **겹치면 그 행만 거부**(겹침을 받으면 같은 연료가 두 번 세어진다) · 시간대 없는 시각 거부 · `dry_run`이 **겹침을 보지 않았다는 사실**을 말하는가 |
| `test_position_snapshot_db.py` | 10 | **§3.15 통합 · 위치 스냅샷·AIS 수집**(`#764`) — 사람이 넣은 위치도 항적으로 남는가 · **재전송 중복을 한 행으로 접는가** · 늦게 온 오래된 관측이 현재 위치를 뒤로 돌리지 않는가 · 위치가 안 온 선박의 마지막 위치를 지우지 않는가 · 남의 배(미대조 IMO)를 저장하지 않는가 · 조회 실패를 사유와 함께 돌려주는가 · 신선도를 **관측 시각**으로 재는가 · 모르는 항행 상태를 단정하지 않는가 |
| `test_fleet_route_db.py` | 7 | **§3.16 통합 · 선대 요약의 항로 좌표**(`#763`) · 목적항 방향 `course_deg`(`#1804`) — 네 좌표가 그대로 실리는가 · **한쪽이라도 비면 싣지 않는가**(반쪽 선분 금지) · 진행 중 항차가 없으면 없는 항로를 지어내지 않는가 · **선대 전체를 쿼리 한 번**으로 묻는가(`#989` 성능 회귀 방어) · 선박당 하나를 `find_in_progress`와 같은 규칙으로 고르는가 |
| `test_fleet_reduction.py` | 15 | **§2 단위 · 함대 감축 계획 계산**(`#513` · `PRD §12.3.2`) — ⚠️ **0%면 아무것도 바뀌지 않는가**(완료 기준) · 연료가 **속력의 제곱**으로 주는가 · 추가 항해일 · **연간 등급 관리의 속력 민감도와 같은 연료인가** · 제원 없는 항차를 건너뛰고 세는가 · 50% 상한 · 두 목록 어긋남 거부 · 비용 곱셈 · ⚠️ **단가가 없으면 0이 아니라 빈칸인가** · 감속 안 한 선박은 단가가 없어도 되는가 · 목표 등급(직전 2년 D면 C) · ⚠️ **감속 후 연료가 `2-2 항로 비교`(cubic model)와 같은가**(`#513` 완료 기준) · **응답 직렬화의 절사**(`#1349` · `TECH_SPEC §1.2.1`) — CII 필드는 전송 자릿수로 `ROUND_DOWN`, 그 밖은 `ROUND_HALF_UP` |
| `test_fleet_reduction_db.py` | 15 | **§4 API · 함대 감축 계획 서비스**(`#513` · `API_SPEC §2.17`) — ⚠️ **감속률 0%면 전 선박 등급이 그대로인가**(데모 선박 포함) · ⚠️ **조정 전 값이 연간 등급 관리의 결정론 예상과 같은가** · 감속 시 CII·추가 항해일·절감 톤 · 단가 누락 칸이 빈칸인가 · 모르는 선박 거부 · ⚠️ **저장본이 저장 시점 결과 그대로인가**(항차를 더한 뒤에도) · 없는 계획 404 · 실제 HTTP(봉투 · 422 · 201 · 목록 · 단건) · ⚠️ **대문자 UUID 단가 키로도 용선료가 계산되는가**(`#1070` ⑵) · ⚠️ **연료 없는 계획 항차가 항차 수에서 빠지지 않고 경고로 드러나는가 — 연간 등급 관리와 같은 수인가**(`#1070` ⑷) · ⚠️ **고칠 수 있는 입력이 500이 아니라 422와 그 칸의 라벨로 끝나는가**(공백 계획 이름 · 중복 선박 · UUID 아닌 단가 키 — `#1070` ⑴⑵⑶) · **목록 페이지네이션**(`#1367`) — 종전에는 20건에서 자르면서 `has_more`도 `next_cursor`도 없어 **21번째 계획을 볼 방법이 없었다**. 한 페이지·커서 이어받기·마지막 페이지·깨진 커서 넷을 본다. ⚠️ **표를 먼저 비운다** — 페이지네이션은 표 전체의 순서를 보는 것이라 남의 행이 섞이면 단언할 수 없고, 같은 파일의 HTTP 검사가 실제 클라이언트로 돌아 그 행이 트랜잭션 밖에 남는다(실측 2건). 그 `DELETE`는 바깥 트랜잭션 안이라 함께 되돌아간다 |
| `test_llm_guard.py` | 18 | **§3.17 통합 · 챗봇 가드 둘**(`#120`) — 전송 화이트리스트가 **정본 표와 같은가**(한쪽만 고치면 걸린다) · 선박명이 막히는가 · **모르는 새 필드가 조용히 빠지지 않고 터지는가** · 파생 수치(빼기도 계산이다)가 막히는가 · 표기 차이(`4.980`)로 정상 응답을 막지 않는가 · 연도·한 자리 수 예외가 너무 넓지 않은가 |
| `test_chat_store_db.py` | 7 | **§3.17 통합 · 대화 보존**(`#120`) — 만료일이 **만든 시점에 확정**되는가(조회 때 계산하면 정책 변경이 과거를 흔든다) · 만료 세션을 지우면 **메시지도 함께** 사라지는가 · 만료 전 세션이 남는가 · 이력이 최근 N건으로 **시간순** 잘리는가 · `role`이 둘로 제한되는가 · **감사 로그가 원문이 아니라 해시를 남기는가** |
| `test_chat_tools.py` | 13 | **§3.18 통합 · 도구 계층**(`#121`) — 쓰기 도구가 없는가 · 봉투에 도메인 값이 섞이지 않는가 · **API 이름(`estimated_rating`)이 정본 이름(`rating`)으로 바뀌어 나가는가** · 대응표 도착지가 전부 화이트리스트 안인가 · 모르는 도구가 예외가 아니라 봉투로 돌아오는가 · 도구 `project_year_end`의 이름·설명이 「시뮬레이션」「기능③」을 쓰지 않는다(결정론 연말 예상 · `#1534`) |
| `test_chat_tool_defects_db.py` | 11 | **§3.18 통합 · 챗봇 도구의 네 결함** (`#1334`). 서로 다른 층인데 **한 화면에서 같이 드러난다** — 「다음 등급까지 얼마나 남았어?」 한 번에 ⑴ 인자가 빠지면 500 ⑵ 화면 표기로 답하면 폐기 ⑶ 지어낸 「7%」는 통과 ⑷ 지울 수 없는 계산 행이 쌓인다. ⚠️ **⑵와 ⑶은 함께 고쳐야 한다** — ⑶만 고치면 도구가 백분율을 안 주므로 **화면과 같은 `1.2%`가 전부 폐기**되고, ⑵만 고치면 지어낸 `7%`가 **여전히 한 자리라 무검사**다. ⑴은 선택 인자를 **`None`으로 삼키지 않는지**도 본다(삼키면 모델이 보낸 조건이 조용히 사라져 **사용자가 물은 것과 다른 계산**의 답이 된다 — 오류보다 나쁘다)와 **봉투가 인자 이름을 말하지 않는지**(`#1310`이 오류 경로로 화이트리스트가 뚫린 것을 고쳤다). ⑷는 **화면 경로가 남기는지를 먼저** 본다 — 대조군이 없으면 챗봇 검사가 `0 == 0`으로 **엔진이 죽어도 통과**한다. 돌연변이 7종 **7/7 검출**, 그중 둘(무시 목록 전체 삭제 · 화면 경로 저장 중단)은 **과잉 수정 쪽**을 막는다. 11함수·14수집(⑴ 인자 3종과 ⑶ 정상 문장 2종이 parametrize) |
| `test_chat_api_db.py` | 30 | **§3.18 통합 · 오케스트레이션**(`#121`) — **가드가 실제 경로에 꽂혀 있는가**(함수가 있어도 부르지 않으면 못 막는다) · 면책이 정본과 글자 그대로 같은가 · **모델이 받은 메시지에 선박명이 없는가** · 지어낸 수치를 버리고 **저장도 하지 않는가** · 호출 상한에서 끊는가 · 남의 대화가 404인가 · **응답 키 집합**(`#1365`) — `API_SPEC §15.1` 표가 `data`의 키 **전부**인가를 잠근다. 종전 계약 검사는 **값 몇 개만** 보아 표에 없는 키가 늘어도 통과했고, 실제로 `tool_output_count`가 그렇게 실려 나가고 있었다. **「빠진 키」는 화면이 깨져 드러나지만 「늘어난 키」는 아무 데서도 드러나지 않는다.** **폐기한 턴도 같은 키**인지 함께 본다 — 폐기 경로는 `_result(...)`를 여러 자리에서 따로 부르므로 한 자리만 고치면 「어떤 답은 키가 다른」 상태가 된다 |
| `test_llm_provider.py` | 15 | **§3.18 통합 · 공급자**(`#121`) — 요청 본문을 만드는 규칙이 틀리면 **400인데 운영에서만 드러난다**(오케스트레이션 검사는 `FakeProvider`라 지나간다). `system` 분리 · 같은 역할 연속 합치기 · 출력 상한 동봉 · **실패 문구에 응답 본문을 싣지 않는가**(전송 금지 값이 로그로 샌다) |
| `test_chat_explain.py` | 9 | **§3.19 통합 · 용어 풀이**(`#123`) — 풀이가 `PRD`·`DESIGN_SYSTEM` 원문에서 왔는가 · 정본에 없는 등급 형용사를 만들지 않았는가 · ⚠️ **두 자리 수가 없는가**(있으면 모델이 인용하는 순간 답변이 폐기된다) · 프롬프트에 실제로 꽂혀 있는가 · 용어 풀이가 「연말 예상」과 「목표 달성 확률」을 가른다 — 숫자 없이(`#1534`) |
| `test_regulation_ship_type_sync_db.py` | 5 | **§3.20 통합 · 규정 표 정합**(`#834`) — 기준선과 등급 경계의 선종 집합이 어긋나는가 · 알려진 누락이 **사유와 함께** 목록에 있는가 · ⚠️ 그 누락(`RO_RO_PASSENGER_HSC`)을 **계산 계층이 실제로 상속하는가** · ⚠️ **호출부가 선종으로 걸러 조회하지 않는가**(걸러면 상속 대상 행이 목록에 없어 폴백이 죽는데, 데모 선대에 HSC가 없어 아무도 모른다) |
| `test_fuel_table_sync_db.py` | 4 | **§3.22 통합 · 연료 표 정합**(`#773`) — 정본 표를 읽을 수 있는가(형식이 바뀌면 **0건을 대조하고 통과**한다) · 코드가 양방향으로 같은가 · ⚠️ **CF 값이 같은가**(어긋나면 계산이 조용히 틀린다) · 알려진 공백에 사유가 있는가 |
| `test_chat_tools_db.py` | 24 | **§3.24 통합 · 챗봇 도구의 실제 실행 경로**(`#120`) — ⚠️ **화이트리스트가 진짜 계산 응답에 대해 도는가**(단위 검사는 손으로 만든 dict를 본다) · 검색이 선박명·IMO·id를 돌려주지 않는가 · API 이름이 정본 이름으로 바뀌는가 · 시나리오를 **순위로 정렬하지 않는가** · 연말 예상 성공·실패 두 경로가 다 도는가 · ⚠️ **없는 선박의 id가 오류 문구로 새지 않는가** |
| `test_coverage_floor_script.py` | 10 | **§3.23 통합 · 파일별 커버리지 하한**(`#955`) — 합계 게이트가 못 보는 파일별 구멍을 잡는가 · ⚠️ **작은 파일을 비율로 잡지 않는가**(8문장 중 1문장에 CI가 걸리면 하한을 낮추라는 압력이 생긴다) · 작다고 면제되지는 않는가 · 예외가 **더 내려가면** 실패하는가 · ⚠️ **올라간 뒤 목록에 남으면** 실패하는가(낡은 목록은 거짓말) · 사유와 이슈 번호가 있는가 · `src/` 접두사가 붙어도 같은 파일인가 |
| `test_purge_expired_script.py` | 8 | **§3.21 통합 · 정리 스크립트**(`#827` ⑶) — ⚠️ 조건 없는 `DELETE`가 없는가(전원 로그아웃이 된다) · `--dry-run`이 세는 조건과 지우는 조건이 같은가 · **한 표가 실패해도 나머지가 도는가** · 0건이어도 감사 기록이 남는가(「돌았는데 없었다」와 「안 돌았다」는 다르다) · **`weather_snapshot` 정리**(`#1347`) — `DB_SCHEMA §4.3`이 30일 삭제를 적는데 **지우는 경로가 없었다**. ⚠️ **참조 검사가 두 표다**: `calculation_run`은 `ON DELETE RESTRICT`라 DB가 막지만 `voyage_scenario`는 **`ON DELETE SET NULL`**이라 막지 않고 **조용히 링크만 끊는다**(그쪽이 더 나쁘다 — 「어느 기상으로 계산했나」가 사라진 것을 아무도 모른다). `NOT IN`에 NULL이 섞이면 전체가 거짓이 되어 **한 행도 못 지운다**는 것까지 본다. 30일은 `--grace-days`를 받지 않는다(정본이 정한 값이다). 종전 검사 둘을 함께 넓혔다 — 만료 열을 `expires_at` 리터럴로 찾던 것을 **「시각으로 자른다」는 성질**로, 대상 표 전체를 비교하던 것을 **「실패한 표가 나머지를 세우지 않는다」**로(대상이 하나 늘 때마다 깨지던 자리) |
| `test_erasure_paths_db.py` | 13 | **§3.21 통합 + §5 인프라 · 삭제 경로 셋과 운영 스크립트** (`#1330`). `PRD §16.3`이 「GDPR 유사 삭제 요청 **지원**」이라 적었는데 **응할 경로가 없었다** — 대화 삭제 엔드포인트가 없었고, **탈퇴해도 원문이 남았으며**, 90일 만료 삭제는 `csql`에 **`-p`를 넘기지 않아** crontab이 매일 돌면서도 **한 번도 지우지 못했다**(실패해도 cron은 조용하다). 셋을 한 파일에 모으는 이유는 **같은 약속의 세 경로**이기 때문이다 — 하나만 있으면 「대화는 지웠는데 탈퇴하면 남는다」가 된다. ⚠️ **저장소 함수만 보면 라우트가 끊겨도 통과한다** — 돌연변이 M4(탈퇴 라우트에서 호출 제거)가 **처음에 빠져나갔고**, HTTP 검사 3건(탈퇴→대화 0행·감사의 `purged_chat_sessions` · 204/404 · CSRF 403)을 더해 잡았다(`#1321`·`#433`과 같은 자리). 기한 삭제가 **살아 있는 대화까지 지우지 않는지**도 함께 본다 — 새 경로가 생겼다고 넓어지면 사용자가 쓰는 중에 사라진다. 서비스 이름은 문서가 아니라 **compose 파일에서 읽어** 대조한다(운영 문서만 고치고 스크립트를 두는 것을 막는다). 돌연변이 6종 **6/6 검출** |
| `test_retention_policy_sync.py` | 2 | **§5 인프라 · 문서 정합** — 보존 기간 ↔ `DB_SCHEMA §4.3` (`#1347`). ⑴ `weather_snapshot` 보존일이 정본과 같은가 ⑵ **정본이 「삭제」라 적은 표에 지우는 경로가 있는가**. 지운 것은 되돌릴 수 없는데 **기간이 짧으면 보존 약속을 깨고 길면 「30일 뒤 지워진다」가 거짓**이 된다 — 둘 다 스크립트가 정상 종료하고 표만 줄어들어 **조용히** 어긋난다. ⑵가 이 이슈를 만든 형태 자체를 막는다: `§4.3`이 30일 삭제를 적는 동안 **지우는 경로가 아예 없었다** |
| `test_cii_history_fuel_db.py` | 6 | **§3.14 통합 · 연도별 이력의 연료축**(`#769`) — 유종별로 나뉘는가 · **비중이 CO₂ 기준인가**(톤 기준과 다른 값이 나와야 한다) · CF 스냅샷이 둘이어도 한 줄인가 · 정박 연료가 축에 들어가는가 · 정렬이 서버에서 정해지는가 · 실적 없는 해가 빈 배열인가 |
| `test_not_underway_crud_db.py` | 36 | **§4 API · not under way 구간 CRUD** — 구간 겹침 금지 · **동시 요청에서도 겹침이 하나만 남는다**(`#1629` · `F-8` — 두 연결을 겹침 조회 직후에 교차시켜 생성·수정·CSV 가져오기 셋을 본다) · CF snapshot · 소프트 삭제 · 집계 도달 · **귀속 연도는 UTC 기준**(`#1333`) — 종전에는 `started_at.year`를 그대로 읽어 **오프셋 붙은 값의 현지 연도**가 나왔다. `API_SPEC §8.2` 예시 형식(`+09:00`)대로 KST 1/1 새벽 정박을 올리면 UTC로는 전년도인데 **다음 해 CII 분자·분모에 들어갔고**, 올바른 연도를 명시하면 거부됐다. 항차 CSV는 처음부터 `astimezone(UTC)`로 정규화한다 — **같은 저장소 안에서 두 경로가 갈려 있었다** |
| `test_not_underway_api_db.py` | 8 | **§4 API · 정박 쓰기 라우트 5종의 HTTP 계약**(`#828` ⑴) — 201 Created · PATCH가 **보내지 않은 칸을 건드리지 않는다**(`exclude_unset`) · 겹침 409 / 잘못된 enum 422 / 없는 구간 404 · **다섯 라우트 전부 CSRF 없이는 통과하지 못한다** · **시간대 필수**와 **귀속 항차 검사**(`#1333`). 시간대 없는 시각은 `PATCH`에서 **500**(요청 naive ↔ DB aware 비교), `POST`에서 **서버 세션 시간대로 조용히 해석**됐다 — 같은 리소스의 CSV 경로는 처음부터 시간대를 요구했다. 귀속 항차는 ⑴ 없는 id가 FK 위반으로 **500**이 되고 ⑵ **다른 선박의 항차에도 붙었다**(뒤엣것이 더 나쁘다 — 아무 오류 없이 지나가고 그 항차가 바뀔 때 엉뚱한 선박의 계산이 재계산 필요로 표시된다). ⚠️ **고치는 경로도 같은 검사를 받는지**와 **`null` 클리어는 통과하는지**를 함께 본다 — 앞엣것이 없으면 「만들 때는 못 붙이는데 고칠 때는 붙는」 상태가, 뒤엣것이 없으면 지우는 것까지 막는 과잉 수정이 통과한다 |
| `test_parameters_api_db.py` | 20 | **§4 API · 규제 파라미터 조회** — 네 종류 조회 · 수치 문자열 직렬화(`§1.7`) · 값이 DB와 일치 · 모르는 선종은 오류 · `#370` 우회 제거 확인 (`#444`) · **`active` 스위치**(`#1515`) — 기본이 **종전과 같은 목록**인가(호환이 조건이다) · `false`가 이행 행을 **현행과 함께** 주고 `is_active`가 `bool`인가(CUBRID가 `1`/`0`으로 주면 화면의 `=== true`가 뒤집힌다) · `false`가 기본의 상위집합인가 · **계산이 부르는 저장소 갈래(인자 없음)는 여전히 활성만인가** · `active_only=`를 넘기는 곳이 조회 서비스 하나뿐인지 **소스를 훑는다** — 개정이 한 번도 없던 DB에서는 동작 검사가 아무것도 못 잡는다(`#834`와 같은 이유·같은 방법) |
| `test_sample_vessels.py` | 6 | **§4 API · 샘플 선박 목록**(`#982` · `API_SPEC §2.15`) — 값의 출처가 데모 시드 한 곳 · 합성 샘플만 · 필드 = 등록 요청 − 신원 · 바로 계산되는 제원 · `/vessels/samples`가 `{vessel_id}` 경로에 먹히지 않음 |
| `test_sea_route.py` | 17 | **§3.28 해상 경로망**(`#1300` · `API_SPEC §3.11`) — 양 끝이 입력 그대로 · 길이 ≥ 대권거리 · 결정론 · 같은 점은 점 하나 · 경유지를 지나고 구간 합 · 날짜변경선에서 되돌아가지 않음(구간 이음새 포함) · **경로가 없으면 직선이 아니라 실패**(라이브러리 경고를 잡는다) · **기동 워밍은 실패해도 예외를 내지 않는다** · API 200 모양 · 반쪽 경유지 422 · 범위 밖 한국어 422 · 경로 없음 404 · 401. **DB 없이 돈다** |
| `test_sample_ports.py` | 8 | **§4 API · 샘플 항만 · 좌표 기반 추정 거리**(`#760` · `API_SPEC §3.8` · `§3.9` · `PRD §15.1` · `§15.2`) — **데모 항차가 쓰는 항만이 전부 목록에 있다**(시드에 항만이 늘면 드러난다) · 이름·코드·WPI 번호가 겹치지 않고 좌표가 범위 안 · **몇 곳의 좌표가 WPI 원본 표기(도·분)와 같다**(남·서반구 부호 포함 — 손으로 고치면 드러난다) · 추정 거리가 **기능②와 같은 대권거리 함수**다 · 범위 밖 좌표는 한국어 422 · 목록도 인증 뒤다 |
| `test_session_resolution_db.py` | 3 | **§4.7 인증 API · 세션 검증 한 벌**(`AT-AUTH-018` · `#1050`) — 종전에는 쿠키→해시→세션→만료→사용자 조회가 미들웨어와 `get_current_user`에 **두 벌** 있었고 의존성 쪽은 운영에서 실행되지 않았다(`#955`). `resolve_session` 하나로 합쳐 다섯 분기를 실제 쿠키로 지나가게 하고, 소스에 조회가 한 곳뿐인지를 잠근다 |
| `test_signup_gate.py` | 9 | **§4.7 인증 API · 가입 게이트**(`AT-AUTH-016` · `#808`) — 도메인·코드 중 하나 · 도메인 정확 일치 · 미설정 시 개발은 열림·**프로덕션은 기동 거부**(실제 앱 lifespan 배선 포함) · 거절 문구 ↔ `PRD §6.3` |
| `test_auth_tokens.py` | 28 | **§4.7 인증 API** — 토큰 일회성·만료·용도 분리 · 재설정 시 세션 전량 무효화 · 재설정 확인은 **유효한 토큰에만** 해싱한다(`#1327`) |
| `test_auth_token_copy_sync.py` | 5 | **§5 인프라 · 문서 정합** — 토큰 경로의 문구·상태 코드 ↔ 정본 (`#1326`). ⑴ 인증 메일 재발송이 **비밀번호 재설정 문구**를 돌려 썼다 — 화면이 서버 문구를 그대로 띄우므로 「다시 받기」를 누르면 **「재설정 안내를 보냈습니다」**가 떴고, 사용자는 **다른 메일이 온다고 믿는다**. ⑵ `VALIDATION_ERROR`에 **400**(`§1.4`는 422), 메일 실패에 **502**(표에 502 행이 없고 `INTERNAL_ERROR`는 500) — **검사가 그 값을 그대로 잠그고 있었다.** 문구는 `PRD §6.3` 표에서 **읽어서** 대조한다(검사에 문장을 또 적으면 정본이 바뀔 때 **한 곳만 고쳐도 검사가 낡은 문장을 지킨다**). ⚠️ **두 상수가 같은 문장이 아닌지**도 본다 — 같은 상수를 가리키면 대조가 통과한다(그 상태가 결함이었다). ⚠️ 상태는 **헬퍼 시그니처**로 본다 — 호출 모양(`_error(request, 502, …`)만 찾으면 **뒤쪽 인자로 넘길 때 빠져나간다**(실측) |
| `test_password.py` | 24 | **§4.7 인증 API** — 해싱·정책·타이밍 방어 · **해싱이 이벤트 루프를 막지 않는다**(`#827`) · 길이 규칙·세션 유효기간이 **`API_SPEC §1.2`에 같은 값으로** 적혀 있다(`#830`) |
| `test_mail.py` | 24 | **§5 인프라 · 메일 발송** — 프로덕션 console 가드 · 백엔드 선택 · 발송 실패 래핑 · 템플릿 · **`SMTP_USE_TLS` 모르는 값 거부**(`#868`). `#810`부터 **`APP_ENV=Production`에서도 console 가드가 발동하는지**를 함께 본다 — `load_mail_settings()`가 `APP_ENV`를 독립적으로 읽어 `== "production"`으로 비교했으므로, `config.py`만 고쳐서는 닫히지 않는 **다섯 번째 가드**였다 · **빈 `SMTP_PORT`를 미설정으로 접는지**(`#1331` — `source.get("SMTP_PORT", "587")`은 키가 있으면 기본값을 쓰지 않아 compose가 넘긴 빈 문자열에서 `int("")`로 기동이 실패했다) · **465는 implicit TLS로 붙는지**(`use_tls=True` · `start_tls=False` — `RFC 8314 §3.3`. 종전에는 `start_tls`만 넘겨 465가 어떤 설정으로도 동작하지 않았다) · 587은 종전대로 STARTTLS 축인지 |
| `test_constraint_triggers_db.py` | 13 | **§5 인프라 · DB 제약 대체** — CUBRID가 CHECK를 **검사하지 않아**(구문만 받고 위반 행을 넣는다) 트리거로 되살린 제약의 계약 (`#1058` · 마이그레이션 `a7d3e9b14f26`). 모델에 `CheckConstraint`가 적혀 있는지를 보지 않는다 — **적혀 있어도 막지 않으므로** 전부 실제로 위반을 넣어 보고 거부되는지만 본다. 넷을 고정한다 — ⑴ **해시 형식**(`sha256:` + 64 hex): 깨진 해시가 저장되면 그 실행은 영영 재현 대조를 못 하고 immutable이라 고칠 수도 없다 ⑵ **불변성**: `calculation_run`·`simulation_snapshot`의 UPDATE·DELETE 차단, 단 `needs_recalc` 0 → 1 플립만 통과(`024` 계약) — **플립에 다른 열을 실어 보내는 것**을 따로 본다 ⑶ **연료 코드 참조**: CUBRID의 FK는 **PK만** 가리킬 수 있어 `fuel_type.code`(별도 UNIQUE)에는 걸 수 없다(`errno=-920`), 그래서 FK가 아니라 트리거다 ⑷ **열 목록이 스키마를 따라가는가**: PostgreSQL은 `to_jsonb(NEW) - 'needs_recalc'`로 전 열을 자동 비교했는데 CUBRID에는 그 연산이 없어 열거로 옮겼고, **열거는 따라오지 않는다** — 빠뜨리면 그 열만 조용히 수정 가능해진다. 돌연변이(`upgrade()`가 아무 트리거도 만들지 않게)로 검출된다. ⚠️ **부모 쪽 연료 삭제 금지는 넣었다가 뺐다** — `REPLACE INTO`가 DELETE + INSERT로 구현돼 seed 재적재가 막혔고(`test_seed_data.py` 7건), 지금은 그 구멍이 열려 있다는 **사실을 고정하는 검사**가 그 자리에 있다(`test_parent_side_delete_is_deliberately_not_guarded`) |
| `test_config.py` | 12 | **§5 인프라 · 기동 검증** — `APP_ENV` 해석의 계약. `DATABASE_URL` 프로덕션 가드(`#118`)에 더해 **`APP_ENV` 정규화·허용값 검증**을 고정한다(`#810`): `Production`·`"production "`이 **프로덕션으로 닫히는지**(종전에는 이 셋이 전부 development로 떨어져 dev-login·`/docs`·데모 계정 시드·DB URL 폴백·console 메일 백엔드가 **함께, 조용히** 열렸다 — 앱은 정상 기동하고 `/health`도 200이다) · `prod`·`prd`·`live` 같은 **모르는 값이면 기동이 서는지** · 허용값 넷(`development`·`test`·`staging`·`production`)이 전부 뜨는지 · 정규화가 값을 바꾸면 **경고 로그가 남는지**(엄격 일치 안이 주는 「틀렸다는 신호」를 이 로그가 대신한다) |
| `test_csv_fixture.py` | 3 | §3 통합 · CSV |
| `test_voyage_import_db.py` | 36 | **§3.4 통합 · CSV 가져오기 · 커서 페이지네이션** — **출항·도착 예정 시각 선택 컬럼**(`IT-CSV-008` · `#906`: UTC 저장 · 옛 양식도 통과 · 시간대 없는 값은 행 오류 · 빈 출항 시각 수를 `dry_run`에서도 셈 · **가져온 진행 중 항차가 시뮬레이션 시계에서 실제로 누적에 기여**) · 수식 주입 4종 escape · 숫자 열은 거부 · 부분 성공(행 번호 보고) · 1000행 상한은 자르되 알린다 · dry-run (`#60`) · **커서 페이지네이션 3종** — 페이지 크기를 넘는 항차에 도달 · **발급한 커서를 서버가 읽는다** · 깨진 커서는 422 (`#627`) |
| `test_case_id_sync.py` | 9 | **§5 인프라 · 문서 정합** — 케이스 ID가 코드·면제 표 어디에도 없는 상태를 막는다 (`§14.5`). 범위 규칙 자체를 고정하는 3건 포함 — 인용은 커버리지 주장이 아니다 (`#498`) |
| `test_dashboard_seed.py` | 23 | **§5.7 DB · seed 적재** · `#1299` — 관찰 대상 선박(벌크 30,000)의 2026 확정 항차가 **실적 보정계수 최소 표본**(`MIN_FEEDBACK_SAMPLE`)을 채운다 · 셋째 항차를 더해도 **대시보드 분포 전체**(A1 B0 C1 D1 E2)·위험 2척·그 배 YTD `7.1462`(C)가 그대로다(기존 검사는 부등식이라 한 칸이 움직여도 통과했다) · 연간 시뮬레이션 보정계수가 `1.037681`(표본 3 · 기본 미적용)로 실제로 나온다 · `#1536` — 완료 항차를 `COMPLETED`·`CONFIRMED` 둘 다로 세고(시드가 확정 11건 · 확정 전 1건), **확정 전은 벌크 50k 2026-01 한 건뿐**이며 데이터 점검의 이상치와 같은 항차인지 잠근다 · `#1672` — **항해 중 선박의 위치 기록 시각이 진행 중 항차의 출항 뒤다**(화면이 기록 위치를 시각과 함께 그대로 보이므로 「출항 전 시각에 항해 중」이 되지 않게) |
| `test_dbschema_json_example_sync.py` | 5 | **§14 문서 동기화 · `DB_SCHEMA` JSONB 예시 ↔ 실제 기록 형태** — `§2.7 voyages_json`·`§2.5 result_json` 예시가 **저장 컬럼과 키 이름부터 달랐다**(`§2.7`은 API 응답 모양을, `§2.5`는 실제 15키 중 12키를 빠뜨린 채 없는 이름을 썼다). **키 집합**만 본다 — 값 대조는 `test_scenario_example_sync.py`의 몫이고, 여기서 막는 것은 「예시에 있는 이름이 실물에 없다」와 그 반대다. DB를 띄우지 않고 **기록을 만드는 함수를 직접 불러** 대조하므로 시드 상태에 흔들리지 않는다. 코드가 실제로 읽는 `kind`, 숫자/문자열 혼재 계약(`API_SPEC §1.7`), `rating_probabilities` 문자열 직렬화도 함께 잠근다 (`#879`) |
| `test_doc_cross_refs.py` | 10 | **§5 인프라 · 문서 정합** — `UIFLOW`·`DESIGN_SYSTEM`을 가리키는 절·화면 참조가 **실재하는지**, 그리고 `AGENTS §4.7` 표기 규칙(화면에 `§`를 붙이지 않는다)을 지키는지. `.md`와 `frontend/src` 주석을 함께 훑는다 (`#583`·`#602`). **규모 착수 조건**(`DB_SCHEMA §4.2` 1,000만 행 · `§9.2` 두 번째 회사 + `#672` 선행)이 지워지지 않았는지도 본다 (`#775`) **정본 변경 이력의 커밋 열이 비어 있지 않은지**도 본다 — `AGENTS §4.1`이 PR 번호를 적으라 한 자리인데 `#___`가 네 행 남아 있었다 (`#1286`) **정본 md의 코드펜스 개수가 짝수인지**도 본다 — 홀수면 마지막 마커 이후 EOF까지 이 파일의 모든 검사가 건너뛰어진다 (`#1324`) **사이드바 순서의 소관 절이 정확한지**도 본다 — 위 「실재하는지」만으로는 `§2.2`도 `§2.2.1`도 둘 다 있어 **틀린 쪽을 가리켜도 통과한다**(`#1341`) |
| `test_changelog_rows_script.py` | 18 | **§5 인프라 · 변경 이력 행 삭제 검사**(`#1498` · `scripts/check_changelog_rows.py`) — `test_doc_cross_refs.py`는 현재 파일만 보므로 **덮어쓰기**(`#1488` — 행 수가 그대로)와 **충돌 해결에서 빠진 행**(`#1512` — base에 없던 행)을 원리상 볼 수 없다. CI `lint` 잡이 base 브랜치 · PR 커밋과 비교한다. 여기서는 두 사고를 잡는가 · 요약 문구 수정은 막지 않는가(키는 **커밋 열의 참조 집합** — `#1522`에서 날짜를 뺐다) · **정상 편집 셋을 막지 않는가**(`#1522` — base 행 날짜 정정 · 커밋 열 꼬리 `⑵` · 자기 행 날짜 정정. 종전 키는 셋 다 「사라진 행」으로 읽었다) · **숫자 임시값을 PR 번호로 바꾸면 잡히고**(`#1519` — 의도된 실패) `#___`면 통과하는가 · **리베이스 충돌**에서 양쪽 행을 남기면 통과하고, 자기 행을 떨어뜨리면 **직전 푸시의 head**(`--previous-head`)로 잡는가(없으면 못 본다 — 사각을 함께 고정) · 직전 head가 비었거나 0이면 건너뛰는가 · 같은 PR의 여러 행을 **개수로** 세는가 · 채우지 않은 행(`#___` · `#<PR>`)은 대상이 아닌가 · **임시 git 저장소에서 실제로 base와 PR 커밋을 읽는가**(순수 함수만 보면 배선이 빠져도 통과한다) · **같은 PR의 여러 행 중 하나가 충돌 해결에서 빠져도 잡는가**(`#1607` — 키가 참조 집합이라 ⑼·⑽이 한 키가 되므로 PR 커밋의 행 수를 키별 최댓값으로 센다 · 순수 · 실제 git) |
| `test_windows_env.py` | 5 | **§14 환경 · Windows 새 환경**(`#1664` · `#1665` · `#1670`) — CI(Linux)에서는 드러나지 않던 셋을 잠근다. **UTF-8이 아닌 로캘을 Linux에서 만들어**(`LC_ALL=C` · `PYTHONCOERCECLOCALE=0` · `PYTHONUTF8=0` → 기본 인코딩 ASCII, CP949보다 좁다) 픽스처 생성기가 성공으로 끝나는지 · 변경 이력 스크립트가 Git 출력의 한국어를 UTF-8로 읽는지 본다. 두 검사 모두 **수정 전 스크립트로는 실패**한다(`UnicodeEncodeError '\u2713'` · `decoding with 'ANSI_X3.4-1968' codec failed` 실측). 변경 이력 스크립트·테스트가 텍스트 I/O에 인코딩을 적는지(괄호 짝을 세어 판정), `ZoneInfo`를 쓰는 코드가 있으면 `tzdata`가 설치 의존성인지, 패키지만으로 `Asia/Seoul`이 풀리는지 본다 |
| `test_dbschema_head_sync.py` | 3 | **§14 문서 동기화 · `DB_SCHEMA` ↔ alembic head · ORM**(`#1342`) — 헤더는 v1.33인데 절 일곱이 `051` 이전에 멈춰 있었다. 기계적으로 셀 수 있는 셋만 잠근다: §8.1.0 리비전 그래프의 끝 = `alembic/versions` head · §7.4 「지금 DB에 있는 트리거」 head 열 합계 = `upgrade()`가 내는 `CREATE TRIGGER` 누적 − `DROP TRIGGER`(`op`를 스텁해 DB 없이 센다 — 148은 `051` 시점, head는 160) · §2.6 `annual_simulation_run` 열 집합 = ORM 열 집합(`052` `as_of`·`053` `alternative_fuel`이 빠져 있었다). 돌연변이 셋(그래프 051 · 합계 148 · `as_of` 행 삭제) 각각 한 함수씩 실패(실측) |
| `test_doc_version_sync.py` | 4 | **§5 인프라 · 문서 정합** — `README` ↔ 정본 헤더 버전 일치 (`AGENTS §4`) · **현재 판본마다 README 변경 이력에 그 문서·판본의 행이 있는지**(`#1779` — 표만 고치고 행을 싣지 않은 PR이 일곱 건 쌓였다) |
| `test_db_hardening_023.py` | 6 | §5 DB · 제약·마이그레이션 |
| `test_demo_up_script.py` | 38 | **§5 DB · 운영 스크립트** — 시연 기동 스크립트의 계약. `bash -n` 문법 · **JSON 값 추출**(파이썬 없이) · `--check`가 `.venv` 없이 도는 것 · 기동은 여전히 막히는 것. **CI가 이 스크립트를 실행하지 않아** `#616`의 `mktemp` 오류가 저장소에 들어와 있었다 (`#637`) · **2단계 실패 원인 진단**(`#1294`) — 포트를 쥔 **다른** 컨테이너만 짚는가(가짜 docker로 실제 실행 · 우리 컨테이너는 빼야 안내가 거꾸로 되지 않는다) · 스크립트의 컨테이너 이름·포트 ↔ compose `db` 대조 · `compose up` 실패 메시지를 버리지 않는가 · healthy인데 호스트 포트가 빈 상태를 잡아 멈추는가(`--check` 포함) · `#1536` — `--reseed`(적재 전 `--clear` · 인자 순서 무관 · 모르는 인자는 거부) · 드리프트 안내가 볼륨을 부수지 않는다 · 안내가 회차 사이 재적재를 가리킨다 · `#1608` — `--reseed`가 **남긴 행**(계산 이력이 참조)을 화면에 알리는가(0행이면 조용 · 실제 bash) |
| `test_demo_vessel_seed.py` | 17 | **§5.7 DB · seed 적재** — 합성 IMO의 체크섬 유효성 포함 (`#525`) · **제원 역산과 시드↔DB 어긋남 감지**(`#587` — 시드는 `ON CONFLICT DO NOTHING`이라 **기존 행을 갱신하지 않는다**. 시드에 값을 채워도 볼륨을 유지한 환경에는 들어가지 않고, 그 상태는 오류가 아니라 화면의 `—`로만 드러난다) |
| `test_demo_seed_counts.py` | 9 | **§5.7 DB · seed 적재** — 적재·삭제 **행 수 보고**가 사실인지 (재실행 0 · 비운 뒤 실제 건수 · 음수 없음, `#481`) · `#1536` — `clear_demo`가 저장한 함대 감축 계획을 **전량** 지우고 건수를 보고한다(데모 표지가 없다) · `#1826` — 초기화가 시드가 덧씌운 **운항 상태·위치를 비워** 재적재 때 새 위치가 들어가는지(계산 이력 등이 참조해 **선박이 남는 경로**에서만 나는 결함이라 위치 스냅샷으로 세 척을 남긴 뒤 본다) |
| `test_demo_user_seed.py` | 11 | **§5.7 DB · seed 적재** — **시연 계정**의 계약 (`#692`). 시드가 계정을 만들지 않아 DB를 다시 만들 때마다 사람이 가입해야 했고, `#691` 이전의 테스트가 계정을 지우면 로그인 화면으로 들어갈 길이 없었다. 넷을 고정한다 — ⑴ 저장된 해시가 **그 비밀번호로 실제 검증**되는지(행 수만 보면 평문이 들어가도 통과한다) ⑵ 다시 돌려도 늘지 않고 **사람이 고친 값을 덮지 않는지** ⑶ **`APP_ENV=production`에서는 만들지 않는지**(고정 비밀번호가 프로덕션에 있으면 알려진 순간 누구나 들어온다) ⑷ 없으면 없다고 말하는지 — `is_deleted` 행을 「있다」로 세면 점검이 거짓말을 한다 |
| `test_db_types.py` | 10 | **§5 인프라 · CUBRID 호환 타입** — `db/types.py`의 입출력 계약 (`#1058`). ⚠️ **이 모듈에는 검사가 하나도 없었다.** PostgreSQL 전용 타입 둘(`JSONB`·`UUID`)을 파이썬 쪽으로 옮기면서 **입력 관용도가 조용히 좁아진 것**을 아무도 보지 못했고, 전체 pytest에서 **59건**이 `'str' object has no attribute 'hex'` 한 줄로 떨어지고 나서야 드러났다. 셋을 고정한다 — ⑴ `UuidText`가 **`str`을 받는다**(전환 전 `postgresql.UUID(as_uuid=True)`는 psycopg가 문자열을 받아 줬다 — 되돌린 것이지 넓힌 것이 아니다) ⑵ 그러면서 **아무 문자열이나 통과시키지 않는다**(파싱 실패는 `ValueError` — 종전 `AttributeError`는 무엇이 틀렸는지 말하지 않는다) ⑶ **저장 모양이 바뀌지 않는다**(`impl`이 `sa.Uuid` 그대로라 DDL이 `CHAR(32)`로 같고 **마이그레이션이 필요 없다**) — 이것이 깨지면 스키마가 갈리므로 이 검사가 먼저 실패한다. `JSONText`는 왕복·한글 보존·NULL과 함께 **이중 인코딩의 모양**을 기록한다(미리 `json.dumps`한 값을 넣으면 읽을 때 `dict`가 아니라 `str`이 나와 호출부가 `.get`에서 선다). DB가 필요 없다 — bind processor를 직접 부른다. 돌연변이(`str` 강제 변환 제거)로 19건 중 **7건 검출** |
| `test_dev_auth.py` | 8 | **§4.7 API · 인증** — 스텁 인증 라우트 등록 판정(`AT-AUTH-013`). `#810`부터 **`auth_dev`가 `APP_ENV` 사본을 갖지 않는 것**까지 본다 — 종전에는 `from cii_platform.config import _ENV`로 import 시점에 값을 복사해 `!= "production"`으로 다시 비교했고, 부정형이라 **모르는 값에서 여는 쪽으로** 틀렸다 · **관리자로 올린 스텁을 dev-login이 강등하지 않는가**(`#1301` — 종전 `!= OFFICE`는 유일한 관리자를 사무직으로 되돌렸다) |
| `test_docs_exposure.py` | 15 | **§4.7 API · 인증** — 프로덕션 OpenAPI 문서 노출 범위 (`AT-AUTH-014`) · **공개 경로 불변식**(`AT-AUTH-015`). 판정이 import 시점에 확정되므로 **하위 프로세스로 진짜 앱을 기동**해 응답 코드를 본다 (`#593` · `#648`) |
| `test_error_handlers.py` | 19 | §4 API · 공통·운영 |
| `test_error_handlers_116.py` | 18 | §4 API · 공통·운영 |
| `test_field_labels.py` | 7 | §4 API · 공통·운영 |
| `test_validation_messages.py` | 14 | **§4 API · 공통·운영 · 422 한국어화** (`API_SPEC §1.3.2` 언어 규정 · `#900`) — Pydantic 오류 `type`에서 만든 문장이 §11 VAL-001·002 틀과 같고 정본 예시 「운항 거리는 0보다 커야 합니다.」를 **글자 그대로** 재현하는지 · 조사가 받침을 따르는지(괄호 설명은 건너뛴다) · 영문 `ValueError`·모르는 `type`이 **영문으로 새지 않는지** · 본문이 JSON이 아니면 글자 위치가 아니라 「요청 본문」을 말하는지 · **OpenAPI의 모든 요청 필드가 한글 라벨을 가지는지**(종전 17항목 표가 84개를 빠뜨렸다) |
| `test_error_message_language.py` | 3 | **§4 API · 공통·운영 · 서비스 오류 문구의 언어** (`API_SPEC §1.3.2` · `#999`) — 서비스·스키마의 `raise` 문을 **AST로** 읽어, 사용자에게 나가는 문구에 `snake_case` 필드명 원문이 섞이거나 **예외 객체를 끼워 넣는** 곳이 없는지(2026-09-12 스캔 31곳 → 0) · 스캐너 자체가 두 모양을 잡는지(한글 조사가 바로 붙은 `direct_distance_nm을` 포함 — 파이썬 `\b`는 한글을 단어 문자로 본다) · **소문자 영단어까지 본다**(`#1329`) — `snake_case`만 찾던 동안 `from`·`to`·`sort`·`got`·`cursor`·`limit`·`seed`가 **밑줄이 없다는 이유로** 전부 빠져나갔다(「`from`은 2019 이상이어야 합니다: got 2000」이 그렇게 살아 있었다). 허용 집합은 **정본 라벨에서 유도한다** — `난수 시드(seed)`처럼 영문을 병기하기로 한 것은 정본의 결정이고, 손으로 적은 예외 목록을 두면 **두 곳이 갈린다** |
| `test_validation_message_canon_sync.py` | 6 | **§5 인프라 · 문서 정합** — VAL 문구 정본 틀 ↔ 실제 422 응답 (`#1329`). `API_SPEC §11`(= `PRD §9.1`)이 **문구의 정본**인데 실제와 갈려도 아무 데서도 드러나지 않았다 — **일곱 규칙이 어긋나** 있었고 차이는 전부 `#860`·`#999` 같은 **앞선 결정**이었으며 표만 뒤처져 있었다. **표가 낡으면 「문구 대조」 검사 자체가 성립하지 않는다**(무엇과 맞출지가 거짓이다). 표는 문장이 아니라 **틀**(`{field_label}`·`{하한}`)이므로 글자 비교가 아니라 **틀이 만드는 모양**을 본다. ⚠️ **두 입구(JSON·CSV)가 같은 말을 하는지**도 본다 — 한 규칙에 두 문장이 있으면 사용자에게는 두 규칙이다. ⚠️ **정본이 없는 문구를 들고 있지 않은지**까지 본다(`PRD §17.3`이 그랬다 — 다섯 중 넷이 `src/` grep 0건) |
| `test_calc_errors.py` | 8 | **§4 API · 계산 엔진 예외 → 사용자 문구** (`services/calc_errors.py` · `#999`) — 용량 축(DWT·GT)이 비었거나 0 이하면 **무엇이 비었는지** 한국어 422로 · 기준선 조건식에서 그 원인을 만나도 **409가 아니라 422**(종전 오분류) · 그 밖의 원인은 409·VAL-008 원문만 두고 **영문 진단은 로그로**(버리지 않는다) |
| `test_validation_messages_api_db.py` | 6 | **§4 API · 422 한국어화 — 실제 엔드포인트** (`#900`) — 발견 경로였던 가입·로그인과 인증 뒤의 선박 등록·항차(배열 원소 필드)·목록 쿼리·연간 시뮬레이션(직접 만든 검증기)에서 `error.message`·`details[].message`·`field_label`이 **전부 한국어**인지 |
| `test_fuel_estimator.py` | 11 | §2 단위 · 추정·기상 |
| `test_fuel_type_content_hash.py` | 7 | **§5.7 DB · seed 적재** |
| `test_fuel_type_seed.py` | 4 | **§5.7 DB · seed 적재** |
| `test_hashing.py` | 30 | §2 단위 · 계산 엔진 · **기능③ `input_hash` 필드 목록**(`#493` — 기능③이 기능①의 목록을 써서 일곱 키 중 둘만 살아남고 있었다. 필드마다 따로 본다: 한 필드만 빠져도 조용히 통과한다) · ⚠️ **보정계수를 끈 실행의 해시가 종전과 같은가**(`#363` — 바뀌면 저장된 실행 전부가 재현 불가) · **미명시 `as_of`·미선택 대체 연료·정박 기록 없음의 해시 무변경**(`#816` · `#756` · `#1803` — 선택 키 규약: 골랐을(있을) 때만 키가 들어간다) |
| `test_hash_fields_doc_sync.py` | 5 | **§5 인프라 · 문서 정합** — 해시 입력 키 집합(`calc/hash.py`) ↔ `TECH_SPEC §5.3` 대조 (`#1344`). 세 집합(`INPUT_FIELDS` 11 · `SCENARIO_INPUT_FIELDS` 12 · `ANNUAL_INPUT_FIELDS` 11)을 **문서에서 읽어 코드와 맞춘다**. `test_hashing.py`는 **코드 쪽 목록과 순서만** 잠그므로 문서가 뒤처진 것은 잡지 못한다 — 실제로 `#363`·`#816`·`#756`이 키를 셋 늘리는 동안 `§5.3`의 기능③ 목록은 **일곱 키로 남아 있었다**. ⚠️ **주석 뒤를 버리고 읽는다** — 따옴표는 주석 안에도 남아, 키를 주석 처리하면 「목록에서 뺐다」가 드러나지 않는다(돌연변이 4종 중 이 형태만 처음에 통과했다). **선택 키 넷이 「선택」이라고 적혀 있는가**도 함께 본다 — 「목록에 있다」와 「늘 담긴다」는 다른 명제이고, 끈 실행에 `False`를 넣으면 저장된 실행 전부의 해시가 바뀐다 |
| `test_health.py` | 14 | §4 API · 공통·운영 |
| `test_imo_parser.py` | 10 | §2 단위 · 계산 엔진 |
| `test_layer1_context.py` | 9 | §2 단위 · 계산 엔진 — 워커 스레드에서도 `prec`·`rounding`·traps가 서는가 · 작업 정밀도가 전역이 아닌가 · **파생값도 적용 지점 안에서 나는가**(`#1372` — ⑶ 연말 예상의 `ratio_to_required` · 「D등급 진입까지 n일」의 누적면적. 값이 아니라 **계산 시점의 정밀도**를 본다) |
| `test_layer1_fixtures.py` | 20 | §2 단위 · 계산 엔진 |
| `test_layer1_working_precision.py` | 7 | §2 단위 · 계산 엔진 |
| `test_layer_conversion.py` | 7 | §2 단위 · 계산 엔진 — Layer 1(`Decimal`) → Layer 2(`float64`) 변환. **손실은 float의 이진값과 잰다**(`#1349` — `Decimal(str(f))`로 재면 `str(float)`이 주는 **가장 짧은 십진 표기**와 비교해 `0.1`의 손실이 `0`으로 나왔다. 「손실을 숨기지 않는다」는 선언이 그 자리에서 깨져 있었다) |
| `test_not_underway_migrations.py` | 15 | **§5.8 DB · not under way** |
| `test_orm_schema_sync.py` | 5 | §5 DB · 제약·마이그레이션 |
| `test_login_backoff.py` | 9 | **§4 API · §16.3 로그인 실패 백오프 (#1203)** — 곡선(5회 여유 0초·0.4초 지수·상한 6.4초) · 🔴 **있는 계정과 없는 계정의 지연이 같다**(지연 키는 이메일 문자열뿐 — 시간 존재 오라클 차단) · 성공 즉시 초기화 · 15분 경과 구제 · 지연이 응답 형태를 바꾸지 않는다(같은 401·같은 문구). `_sleep` 인자 기록으로 시간 재기 흔들림 회피 · **표가 무한히 자라지 않는다**(`#1368` — 만료 항목은 **그 이메일을 다시 조회할 때만** 지워지는데 공격은 대개 매번 다른 이메일로 온다. 상한을 넘으면 만료분을 먼저 쓸어내고, 그래도 넘으면 **가장 오래된 것부터** 버린다 — 지연이 필요한 쪽은 지금 두드리고 있는 이메일이다. 상한이 정상 사용을 깨지 않을 만큼 큰지도 함께 본다) |
| `test_structured_logs_db.py` | 7 | **§4 API · 구조화 로그 (#827 ⑵ · E-2 「나」)** — 🔴 **쿼리스트링이 로그에 없다**(verify-email 토큰 유출이 이 이슈의 실측 결함) · **요청 본문이 로그에 없다**(로그인 비밀번호) · 접근 요약 JSON의 약속된 키(request_id·method·path·status·duration) · **5xx 접근은 ERROR** — 미들웨어가 예외를 최외곽으로 올리며 남긴다(Starlette의 Exception 핸들러는 사용자 미들웨어 **바깥**이다) · 예외 기록 `exc` 스택 |
| `test_parameter_migrations.py` | 13 | §5 DB · 제약·마이그레이션 · **기준선 키의 유일성이 활성 행끼리만이다**(054 — 이행 행 같은 키 허용) |
| `test_parameter_import_db.py` | 17 | **§4 API · §7.5 파라미터 적재 (#673)** — 🔴 **전부 아니면 전무**(한 행 오류 → 아무것도 안 들어감 · IT-IMPORT-005) · `dry_run` 실제와 같은 판정(#1190 규약) · 개정이 이행 행 보존+활성 전환(`DB_SCHEMA §7.2`) · `a_raw`→`a_decimal` 서버 계산(§9.2) · 파일 안 키 중복·모르는 선종·d순서·capacity_rule 행 오류 · 연료 제자리 갱신+`content_hash` 재계산 · **`OTHER` 생성에 `effective_from` 필수**(`PRD §3.4.2`) · 현장직 403 · 감사 로그 · **감사 `details.source_refs`**(`#1515`) — 적재 행들의 `source_ref` **고유·정렬** 목록인가(두 행이 같은 출처면 한 번만, 다른 출처는 사전순) |
| `test_rate_limit.py` | 21 | **§4 API · 요청 한도** — `API_SPEC §13.2` 계약. 카운터 자체(고정 윈도·IP 분리·`0` 비활성·`X-Forwarded-For` 무시·429 봉투의 `meta.request_id`)와 **경로 버킷**(`#811`)을 함께 본다. 버킷은 세 갈래다 — 인증 10 · 계산 60 · 그 밖 300. 종전에는 전역 한도 하나(300)뿐이라 **로그인 무차별 대입에 분당 300회**가 허용됐고, 정본이 규정한 계산 60회는 적용되지 않았다. ⚠️ **경로 목록이 실제 라우트와 어긋나면 한도가 조용히 풀리므로** 두 집합의 모든 경로가 앱에 실재하는지 대조한다 — `app.routes`가 아니라 **OpenAPI**를 읽는다(`include_router`한 경로는 `app.routes`에 펼쳐지지 않아 0개로 보이고, 그러면 검사가 「없는 것끼리 비교해」 통과한다. `#634`가 같은 함정에 걸릴 뻔했다). 경계가 **넓어지는** 방향도 함께 막는다: `/auth/logout`·`/auth/me`·`GET /calculations`·`POST /scenarios/{id}/adopt`가 기본 버킷에 남는지 |
| `test_rating_boundary.py` | 16 | §2 단위 · 계산 엔진 |
| `test_request_context.py` | 3 | §4 API · 공통·운영 |
| `test_risk_level.py` | 26 | §2 단위 · 계산 엔진 |
| `test_rng_reproducibility.py` | 4 | §2 단위 · 계산 엔진 |
| `test_scenario_compare_api.py` | 46 | §4 API · 기능② 시나리오 · **우회 경유지**(`AT-SC-005` · `#1300`) |
| `test_scenario_compare_db.py` | 6 | §4 API · 기능② 시나리오 · **보정한 계산이 쓴 기상 스냅샷을 계산 이력에 남기는가**(`IT-WX-004` · `#904`) · **저장된 `vessel.block_coefficient`가 범위 밖이면 시나리오가 `CB_OUT_OF_RANGE`를 내는가**(`#966` — 유일한 생산 경로) |
| `test_scenario_adopt_db.py` | 26 | **§3 통합 · 시나리오 채택** — 계획값 반영 · 계산 무효화(항차 범위) · 계획 단계 항차만 허용 · 항차당 채택 하나 · `CREATE_NEW_VOYAGE` (`#58`) |
| `test_seed_data.py` | 18 | **§5.7 DB · seed 적재** |
| `test_seed_migration.py` | 11 | **§5.7 DB · seed 적재** — 마이그레이션과 `seed.py` 상수가 **갈라지는 순간**을 드러낸다. Z·기준선·d-vector에 더해 **연료 CF 8행 · 기상 10행 · 시뮬 3행**도 대조한다(`#1370` — 종전에는 이 둘을 보지 않아 `simulation_parameter.version`이 두 곳에서 `"2026.08"`·`"1.0"`으로 갈린 채 남아 있었다). **`version`을 수치와 별개로 단언한다** — 그 값이 `parameters_used.simulation_profile.version`으로 `parameter_hash`에 들어가므로, 행의 수치가 같아도 **적재 순서에 따라 재현이 실패한다** |
| `test_simulation_clock.py` | 30 | **§2.11 단위 · 시뮬레이션 시계** |
| `test_progress_distance_cap_db.py` | 15 | **§2.11 단위 + §3 통합 · 진행 중 항차의 계획 거리 상한** (`#1321`). 시계의 창 상한이 **시각 하나**뿐이라(`#649`) `속력 × 경과시간`이 `planned_distance_nm`와 대조되지 않았고, **도착 예정일 안에서도** 계획을 넘었다 — 시연 시드 실측 **186%**(벌크)·**359%**(감시선). ⚠️ **픽스처가 실제로 넘치는지 먼저 본다** — 넘치지 않는 입력이면 나머지가 **상한이 없어도 전부 통과**한다. ⑵ 거리가 **정확히** 계획값인가 ⑶ **`Decimal` 정밀도 문맥에 기대지 않는가**(`prec=8`에서도 — `planned/speed`를 다시 곱하는 형태는 기본 28자리에서 **우연히 맞아** ⑵를 통과한다) ⑷ 시간·연료가 함께 멎는가(거리만 자르면 **같은 항차의 거리와 시간이 서로 다른 시각을 말한다**) ⑸ `is_simulated`가 남는가(`#649`와 같다 — 도착 실적은 확정된 것이 아니라 아직 입력되지 않은 것이다) ⑹ `IN_PROGRESS_PAST_ETA`와 **섞이지 않는가**(계획 거리는 예정일보다 **먼저** 찬다 — 감시선 시드는 3.6일 앞선다) ⑺ 계획에 못 미치는 항차는 아무것도 바뀌지 않는가(대조군). 그 위에 **네 곳이 같은 값을 말하는지** — ⑴ YTD · ⑵ 항차 구간값 · 선대 요약 · 리포트 PDF(`#750` 경로) — 를 보고, 마지막으로 **HTTP에서 한 번 더** 본다(`#433`의 교훈). 돌연변이 5종 **5/5 검출** |
| `test_testplan_sync.py` | 11 | **§14 인벤토리 동기화** · 파일·함수·수집 수가 **§14.2 합계 한 곳에만** 있다 — `§11.1`·`README`가 사본을 다시 품으면 실패(`#830`) · **같은 파일이 두 번 나오지 않는지**도 본다(`#1380` — 파일별 수를 dict으로 모으므로 **뒤 행이 앞 행을 덮어**, 두 행이 같은 수를 적으면 대조도 합계도 통과한다. 실제로 `test_doc_cross_refs.py` 행이 둘이고 한쪽만 갱신된 채 남아 있었다) |
| `test_operations_pages_commands.py` | 2 | **§14 운영 · 문서 정합** (`#1669`) — `docs/OPERATIONS.md` **코드 블록**의 Pages 명령이 현행 구성과 같은지 본다: 빌드의 `VITE_API_BASE_URL`은 `/api/v1`(같은 오리진)뿐 · `wrangler pages deploy`에 위치 인자·`--project-name`이 없다(`wrangler.toml`이 갖는다). 본문의 「종전에는」 역사 기록은 보지 않는다. 수정 전 문서로는 **2건 모두 실패**한다(실측) |
| `test_testplan_fixture_names.py` | 2 | **§1.6 테스트 격리 · 문서 정합** (`#1583`) — `§1.6` 표 첫 열의 이름이 `tests/conftest.py`에 `def`로 실재하는지 본다. 종전 절이 없는 `db_session`·`httpx_client`를 적고 있었는데 검사가 초록이라 아무도 몰랐다. 표가 비어 헛도는 것도 막는다 |
| `test_tracked_files_are_text.py` | 4 | **§14 인벤토리 동기화** — 추적 소스에 NUL이 섞이면 git이 바이너리로 보아 **PR diff와 `grep`이 막힌다.** `.gitattributes`는 보이게 할 뿐 유입을 막지 못해 들어오는 자리에 신호를 둔다 (`#572` 발견 · `#575`) · **풀리지 않은 병합 표시**(`<<<<<<< ` · `>>>>>>> ` · `|||||||` · 단독 `=======`)가 커밋되지 않았는가 — 문서가 그 자리에서 깨져도 다른 가드는 표가 아닌 줄을 건너뛴다(`#1309`) · **표를 끊는 떠돌이 줄**(표 행 두 줄 사이의 표가 아닌 한 줄 · 제목 제외 — 병합 표시를 지우고 남은 브랜치 이름 `main` 같은 조각, `#1309`) |
| `test_trigger_ddl.py` | 10 | **§5 DB · 트리거 DDL의 멱등 계약** (`db/trigger_ddl.py` · `#1373`) — CUBRID는 같은 이름의 트리거를 두 번 만드는 것을 막지 않고 중복이 생기면 이름으로는 지울 수 없어(`-503` · `DB_SCHEMA §7.4` 10항), 트리거를 만들고 지우는 마이그레이션 14개가 전부 이 모듈을 지난다. 가짜 `op`로 DB 없이 다섯을 고정한다 — 있으면 만들지 않고 없으면 만든다 · 없으면 지우지 않고 있으면 지운다 · **카탈로그에는 있는데 `-503`이 오면 경고를 남기고 넘어가되 다른 오류는 그대로 올린다**(조용히 삼키면 진짜 실패까지 가린다) · `existing` 집합을 주면 카탈로그를 한 번만 묻고 지운·만든 이름을 그 집합에 반영한다(`050`·`051`·`057`의 지우고-다시-만들기가 「있으면 건너뜀」에 걸리지 않는 근거) · **`-503`은 드라이버 `errno`로도 문구로도 알아본다** · **`replace_trigger`(upgrade의 교체)는 지운 뒤에도 이름이 남아 있으면 `README` 「테스트 DB 복구」를 가리키며 멈추고 옛 것 위에 만들지 않는다** — 관용은 downgrade에만 둔다(롤백이 갇히지 않게) |
| `test_url_normalize.py` | 5 | §4 API · 공통·운영 |
| `test_vessel_position_state_migrations.py` | 12 | **§5.9 DB · 운항 상태·위치** |
| `test_vessels_api.py` | 71 | §4 API · 선박·항차·계산 · **호출부호 정규화·형식**(`#1197` — 등록·수정 두 스키마가 같은 검증기를 쓰는지 · strip · upper · 빈 값 → `null` · 3자·8자·`12AB`·기호 422 · 등록/수정/조회 응답 조립) |
| `test_vessel_call_sign_db.py` | 7 | **§5.1 DB · `DB-CHK-022` 호출부호 트리거 + §4 API · HTTP 왕복**(`#1197`) — API를 거치지 않은 INSERT·UPDATE도 `trg_chk_call_sign_ins/upd`가 막는지 · RR No.19.55 네 형식과 NULL은 들어가는지 · 8자는 `VARCHAR(7)`이 먼저 거부한다(실측) · 「앞 두 글자 모두 숫자 불가」는 DB가 보지 않는다는 경계 · 등록 → 수정 → 조회가 실제 컬럼에서 접힌 값을 돌려주는지(`#433`의 교훈 — 응답 필드는 HTTP에서 확인한다) |
| `test_voyage_distance_source_db.py` | 6 | **§5.1 DB · `DB-CHK-023` 계획 거리 출처 트리거 + §4 API · HTTP 왕복**(`#1256`) — API를 거치지 않은 INSERT·UPDATE도 `trg_chk_planned_distance_source_ins/upd`가 막는지 · 스키마의 `DISTANCE_SOURCES` 전부와 NULL은 들어가는지(두 목록이 갈리면 500) · 좌표 추정으로 만든 항차 → **거리만 고친 PATCH → 조회가 `null`을 실제 컬럼에서 돌려주는지** · 함께 보낸 출처가 목록에 붙는지 · 출처 없는 생성이 `null`인지(`#433`의 교훈 — 응답 필드는 HTTP에서 확인한다) |
| `test_voyage_cii_api.py` | 33 | §4 API · 선박·항차·계산 |
| `test_voyage_attribution_db.py` | 6 | **§3 통합 · 계산 이력의 항차 귀속**(`#817` · 결정 2-③) — 밝힌 요청만 귀속(결과·`input_hash` 무영향) · 계획 변경 시 그 항차 계산만 재계산 필요 · 다른 선박 항차 422 · 없는 항차 404 · 이력 있는 항차 삭제 409 · **채택 응답의 `invalidated_calculation_runs`가 참값인가**(`#1077` — 종전 무효화 검사는 `voyage_id`를 raw SQL로 넣어 `#817` 이전에도 통과했다. 여기서는 실제 기능① 서비스가 만든 계산으로 세고, **`0`이 「이력 없음」과 「이미 전부 표시됨」 둘 다**임을 고정한다) |
| `test_annual_impact_db.py` | 13 | **§3 통합 · 기능①의 「연간 반영 시 변화」** (`PRD §10.3` ⑨ · `§10.4` · `#1338`). 정본 출력 표의 **한 행이 통째로 비어** 있었다 — `API_SPEC §4.1` 응답에도 `frontend/src`에도 0건이었다. ⚠️ **이 값은 항차 CII와 다른 질문에 답한다** — 항차 CII는 「이 항차 하나의 강도」이고 이 블록은 「선박의 연말 값이 이 항차 때문에 어디로 가나」다. **두 값이 반대 방향을 가리키는 것이 정상**이므로 그 성질을 직접 고정한다(실측: 항차 `C`인데 연말 개선 · 항차 `E`인데 연말 악화). **조립을 새로 만들지 않았다는 것**도 본다 — `before`가 `§2.14` ⑶ 실시간 CII의 연말 예상과 **글자 그대로 같아야** 한다(`#798`이 조립을 둘로 둬 7.654488 vs 8.971119를 냈다). 그 밖에 거리가 길수록 더 끌리는가(부호가 뒤집히면 화면이 정반대를 말한다) · 플래그가 두 등급과 같은 말을 하는가 · 자릿수가 `attained_cii`와 같은가 · 기초 자료가 없으면 **`null`인가**(0과 비교한 숫자를 지어내지 않는다) · **해시가 바뀌지 않는가**(파생 출력이지 입력이 아니다) · HTTP 응답까지 나가는가. ⚠️ **유종이 둘 이상이면 CF를 질량가중으로 모으는데, 단일 유종만 보면 그 차이가 드러나지 않는다** — 돌연변이(첫 유종의 CF)가 그렇게 빠져나갔고, **순서를 뒤집어** 보는 검사로 잡았다(질량가중은 순서 무관). 돌연변이 5종 **5/5 검출** |
| `test_voyage_cii_service.py` | 28 | §4 API · 선박·항차·계산 — Layer 1이 정본 픽스처와 **30자리까지** 같은가 · 응답 문자열이 `API_SPEC §4.1` 계약 예시와 같은가 · **등급 경계 CII 4종이 6자리로 실리는가**(`#1371` — 화면이 `required_cii × d`로 다시 만들지 않게 서버가 싣는 값이다. 자릿수는 `attained_cii`·`required_cii`와 같다) · **응답 직렬화의 절사**(`#1349` · `TECH_SPEC §1.2.1`) — CII 필드는 전송 자릿수로 `ROUND_DOWN`, 그 밖은 `ROUND_HALF_UP` |
| `test_voyage_delete_db.py` | 2 | §5 DB · 제약·마이그레이션 |
| `test_db_check_cases.py` | 9 | §5.1 DB · CHECK 제약 — `DB-CHK-*` 중 **다른 파일이 덮지 않던 15개**(상태×정책 무효 조합 5 · 규제연도 범위 · 도착 위도 · 집계 항차의 규제연도 · IMO 형식 · GT·DWT 양수 · 연료 출처 · 시나리오 열거값 3). 어긴 **제약 이름**까지 확인한다 (`#758`) |
| `test_voyage_migrations.py` | 12 | §5 DB · 제약·마이그레이션 |
| `test_voyage_state_machine.py` | 17 | §4 API · 선박·항차·계산 |
| `test_voyage_transition_db.py` | 5 | **§3.1 통합 · 항차 상태 전이(DB 실동작)** — 정책 그룹 교차 · 조합 제약 · 실패 요청의 무영향 |
| `test_voyage_row_lock_db.py` | 5 | **§3.1 통합 · 항차 쓰기의 직렬화**(`IT-STATE-009` · `#1626` · `F-8`) — **두 연결을 실제로 교차시킨다.** 첫 세션의 `commit`을 갈아 끼워 **잠금을 쥔 채 커밋 직전에** 머물게 하고 그 사이에 두 번째를 넣는다 — 서비스가 스스로 커밋하므로 호출이 끝난 뒤에 교차시키면 잠금이 있든 없든 같은 결과가 나온다(`#1629` 코멘트). 다섯 짝: 전환×전환(종결 뒤 `IN_PROGRESS` 422 · 새 상태를 **보고** 거절했는지 문구로 확인) · 전환×PATCH(출항 뒤 계획값 422) · 전환×실적(취소 뒤 실적 422) · 전환×삭제(`PLANNED` 뒤 삭제 422) · 채택×채택(**채택 행 하나**, 나중 것이 남는다). 돌연변이(`get_by_id`의 `for_update` 갈래 제거) 기대 결과: 앞 넷은 두 번째가 **예외 없이 성공**, 채택은 **행 2건** — `#1796` ⑹·⑺가 같은 형태를 실측했다. ⚠️ 로컬 DB가 내려가 있어 이 PR에서는 CI로만 확인한다 |
| `test_voyage_actuals_db.py` | 10 | **§4 API · 항차 실적 입력** — 계획값 보존 · CF snapshot · 상태 경계 · 유종 중복 |
| `test_voyages_api.py` | 38 | §4 API · 선박·항차·계산 (실적 입력 라우트 포함) · **확정 항차 PATCH 가드**(`#865`) · **계획 거리 출처**(`#1256` — 보낸 출처가 응답에 돌아오는지 · 생략은 `null`인지 · 두 값 밖은 422인지 · **거리만 고친 PATCH가 출처를 `null`로 돌리는지** · 함께 보내면 붙고 거리를 안 건드리면 그대로인지) |
| `test_voyage_input_validation_db.py` | 6 | **§4 API · 항차·선박 쓰기 입구의 입력 검증** (`#1332`) — `API_SPEC §1.4`가 4xx를 정한 자리에서 **500이 나거나 조용히 통과**하던 다섯을 잠근다: 없는 선박 404 · **삭제된 선박** 404(종전 201) · VAL-005 미시드 연도 409(종전 201) · 목록 필터 오타 422(종전 **빈 목록**) · 없는 `default_fuel_type` 422(종전 500). ⚠️ **빈 목록이 가장 조용하다** — 화면에서 「그런 항차가 없다」와 같은 모양이 된다. ⚠️ **필터는 「거르는 쪽과 걸러지는 쪽」을 함께 본다** — 「빈 목록이 온다」만 보면 필터가 늘 0건을 내도 통과한다. ⚠️ **HTTP로 본다** — `test_voyages_api.py`는 저장소를 대역으로 갈아 끼워 **FK가 없으므로 500이 나던 경로를 재현할 수 없다**(`#433`의 교훈) |
| `test_voyage_list_order_db.py` | 4 | **§4 API · 항차 목록 순서** (`#1806`) — 출항 시각(실제, 없으면 계획) 최신순 · 출항 시각 없는 항차 맨 아래 · 같은 출항 시각은 `created_at`→`id` 내림차순. ⚠️ **등록 순서와 출항 순서를 일부러 반대로 넣는다** — 같으면 정렬 키를 바꾸지 않아도 통과한다(돌연변이 「`created_at desc`로만 뒤집기」 4건 검출). `limit` 1·2·4로 끝까지 이어 받아도 겹침·누락 없음 · CSV 내보내기 같은 순서 · 옛 두 칸 커서 422. 종전에는 목록 순서를 실 DB로 검증하는 테스트가 없었다(`test_voyages_api.py`는 가짜 저장소) |
| `test_weather_seed.py` | 5 | **§5.7 DB · seed 적재** |
| `test_weather_model.py` | 23 | **§2 단위 · 기상 보정 모델** — Townsin-Kwon 경험식(BN·Cβ 보간·적용 한계)과 SIMPLE_RULE(clamp·상한). **두 모델의 실패 규칙이 서로 새지 않는지** (`#61`) |
| `test_weather_api_db.py` | 7 | **§4.10 API · 기상 스냅샷 조회** — `§9.1`을 열고 `§9.2`는 **정책으로 닫은** 상태를 함께 잠근다. 만료된 값도 돌려주는가(「없다」와 「낡았다」는 다른 답이다) · 신선도 경계가 fallback 체인과 같은 시간인가 (`#767`) |
| `test_weather_limits_canon_sync.py` | 4 | **§5 인프라 · 문서 정합** — Hs↔BN 표·적용 한계 ↔ 산식·구현 (`#1345`). `§3.3.2`는 산식(`BN = round(3.5 × √Hs)`)을 **바로 위에 적어 두고도** 표는 어림값이었다 — 「BN > 8 **(Hs > ~7m)**」의 실제 상한은 **5.898 m**이고 「1.5–3.0 m → BN 4–5」도 **2.470 m부터 BN 6**이다. **표를 베끼지 않고 `beaufort_number`를 돌려 경계를 얻어** 대조하므로, 산식이 바뀌면 문서가 낡았다는 사실이 여기서 먼저 드러난다. ⚠️ 표만 맞추고 **문장**을 두면 읽는 사람은 문장을 읽으므로 「적용 한계」 문장의 숫자도 함께 본다 — 정정 각주가 옛 문구를 **인용**하는 것은 정상이라 `#1345`를 적은 줄은 제외한다(`#1339` README 검사와 같은 규칙). ⑷는 `§3.6`이 혼자 「NONE 모델 fallback」이라 적던 것을 `§12.1`·`API_SPEC §1.4`·구현의 **422**와 맞춘 자리를 잠근다 |
| `test_simulation_speed_canon_sync.py` | 10 | **§5 인프라 · 문서 정합** — 속도 분포 ↔ 표본추출 코드 (`#1346`). `PRD §12.4.1`이 거리·연료·**속도** 셋을 나란히 적었지만 엔진은 **거리·연료만** 뽑고, 코드는 그 사실을 docstring에 적어 둔 채 「정본 정정이 필요한 지점」으로 남겨 두었다. ⚠️ **`parameters_used`를 보는 사람은 속도 변동이 확률 분포에 들어갔다고 읽는다** — `simulation_profile.parameters`에 `SPEED` 행이 실려 있기 때문이다. 문구만 맞추면 **다음 사람이 코드를 고칠 때 문서가 조용히 낡으므로** 정본의 주장 셋을 **엔진을 돌려** 확인한다: ⑴ 속도 폭을 10배로 늘려도 분위수·등급확률이 **한 톨도** 바뀌지 않는가(연료 폭은 바뀌는 **대조군**이 함께 있다 — 없으면 엔진이 죽어 있어도 통과한다) ⑵ 그런데도 `SPEED` 행이 `parameters_used`·`parameter_hash`에 실리는가(빼면 속도를 표본추출하게 되는 날 **옛 실행과 해시가 겹쳐 「재현됐다」가 거짓**이 된다) ⑶ `§12.6`의 ±1kn이 프로파일에서 오지 않는가 — `analyze_sensitivity` **서명에 `profile`이 없다**는 것으로 못 박는다(호출 모양 정규식은 인자 순서가 바뀔 때 놓친다). 돌연변이 5종(해시에서 SPEED 제거 · SPEED 행 미인식 · 지렛대 ±2kn · 정본 행·의사코드 원복 · 엔진이 속도 폭을 쓰기 시작) **5/5 검출** |
| `test_weather_client_db.py` | 19 | **§3 통합 · 기상 조회** — 두 엔드포인트 · 부분 실패 · 시각 선택 · 캐시 격자 · 스냅샷 저장 · 모델 디스패치 (`#61`) |
| `test_weather_fallback_db.py` | 17 | **§3 통합 · 기상 fallback** — `PRD §11.6` 네 칸(최신·6h·6~24h·없음) · 실험 모델 배지 · 「보정하지 않았다」를 조용히 넘기지 않는다 (`#62`) · **CB 있음/없음/범위 밖의 경고 조합**(`#966` — 실측 CB가 Cform 범위 밖이면 `CB_OUT_OF_RANGE`, 상한은 반개구간) |
| `test_weather_simulation_migrations.py` | 14 | §5 DB · 제약·마이그레이션 |
| `test_audit_enum_sync.py` | 6 | **§5 인프라 · 문서 정합** — `audit_log.action`·`entity_type` 값 사슬(`#1343`). `코드 리터럴 == AUDIT_ACTIONS(+DB_BACKUP) == DB_SCHEMA §2.14 행`을 양방향으로 본다. 이 컬럼에는 집행 CHECK·트리거가 없어(`§7.4`) **DB가 알려 주지 않는다** — 실제로 쓰는 5개가 문서에 없고 쓰지 않는 4개가 적혀 있었다. `#1241`(감사 로그 조회 화면)이 그 목록으로 필터를 만들면 **없는 값으로 거르고 있는 값을 빠뜨린다.** `DB_BACKUP`은 `migration_guard`가 상수 이름으로 넣어 리터럴로 잡히지 않으므로 따로 본다 |
| `test_audit_log_read_db.py` | 15 | **§3 통합 · 감사 로그 조회** (`IT-AUDIT-002` · `#1241`). `audit_log`는 **쌓이기만 하고 읽는 경로가 없었다** — `repositories/audit_log.py`에 `insert_event` **하나뿐**이라, `#673`이 남긴 규정 적재 이력(누가·언제·몇 행·어느 판본)에 **제품 안에서 닿을 방법이 없었다**. ⚠️ **이 검사는 자기 행만 본다** — `audit_log`는 세션 seed·다른 검사가 함께 쓰는 표이고 삭제하지 않으므로, 전체 건수를 단언하면 **실행 순서에 따라 깨진다**. 전용 `entity_type`으로 심고 그 필터로만 읽으며, 시각을 **벌려** 심는다(같은 시각이면 정렬 단언이 커서 2차 키에 기대는 우연이 된다). 보는 것 — 「기록이 N건뿐」과 「아직 다 주지 않았다」가 **다른 모양**인가(`#1076`·`#1395`가 같은 자리를 고쳤다) · 마지막 페이지가 **커서를 주지 않는가**(주면 클라이언트가 무한 루프) · 이어 받은 페이지가 앞 페이지를 **다시 주지 않는가** · 기간이 **양끝을 포함**하는가 · **모르는 `action`이 빈 목록이 아니라 422**인가(「없다」와 「잘못 물었다」는 다른 답이다) · 깨진 커서가 500이 아닌가 · **조회가 쓰기를 막지 않는가**(완료 기준 ⑵ — 막으면 기록을 줄이자는 압력이 생긴다). ⚠️ **현장직 403은 여기서 보지 않는다** — `test_roles_db.py`가 `API_SPEC §1.2` 표의 모든 경로를 현장직으로 두드리며 이 경로도 그 목록에 넣었다. 역할 하네스를 두 곳에 두면 한쪽만 고쳐진다 · **`actor`**(`#1515`) — `user_id` 옆에 이름·이메일이 서는가(`user_id`는 그대로) · **탈퇴(soft delete) 계정도 풀리는가**(감사가 답할 질문은 「그때 누가 했는가」다) · `app_user`에 없는 행위자는 **`null`**인가 — 빈 dict도 500도 아니다(`null`은 「못 찾았다」, `display_name: null`은 「찾았는데 이름이 없다」 — 다른 「없음」이다) |
| `test_weather_source_sync.py` | 3 | **§5 인프라 · 문서 정합** — `weather_snapshot.source` 값 사슬(코드 상수 `SOURCE_*` ⊆ `TECH_SPEC §7.1` 값 표 = `DB_SCHEMA §2.13` 행)이 어긋나는 것을 막는다. 이 컬럼은 DB가 강제하지 않는다(`DB_SCHEMA §7.4`) (`#968`) |
| `test_ytd_cii_service_db.py` | 25 | **§2.10 단위 · YTD 산출 엔진** |
| `test_ytd_engine.py` | 26 | **§2.10 단위 · YTD 산출 엔진** |
| `test_ytd_voyage_count_db.py` | 3 | **§2 YTD · 집계 정합** — YTD 「항차 수」가 같은 표의 누적 거리·연료와 **모순되지 않는가**. 진행 중 항차의 기여분은 거리·연료에 들어가는데 `voyage_count`는 세지 않아, 리포트가 **두 항차의 거리를 1항차로** 적었다(5,985 nm / 1항차). `voyage_count`의 뜻(실적 확정 항차 수, `API_SPEC §2.7`)은 바꾸지 않고 `in_progress_voyage_count`로 진행분을 따로 센다. `cii/current`와 `cii-history`가 **같은 필드를 같은 뜻**으로 내는지, 과거 연도가 늘 0인지, 리포트 라벨이 갈렸는지를 함께 본다 (`#800`) |
| `test_migration_guard.py` | 20 | **§5 DB · 마이그레이션 · 되돌릴 수 없는 downgrade** — 프로덕션에서만 막고 리비전을 하나씩 명시해야 풀리는지(와일드카드 없음) · **명시해도 24시간 안의 백업 기록이 없으면 무엇이든 지우기 전에 막히는지**(`#827`) · 목록의 모든 리비전이 **실제 호출에서** 무엇이든 지우기 전에 끊기는지 · 파괴적 `downgrade()`가 전부 세 분류 중 하나에 들어 있는지 (`DB_SCHEMA §8.1.2` · `#819`) |
| `test_migration_guard_backup_db.py` | 3 | **§5 DB · 되돌릴 수 없는 downgrade의 해제 조건** — 가드가 **실제 감사 로그에서** 가장 최근 `DB_BACKUP` 시각을 읽는지 · 다른 `action`을 백업으로 세지 않는지 · 방금 남긴 기록 하나로 실제 연결에서 해제되는지. 스크립트가 남기는 행과 같은 모양을 넣는다 — 어긋나면 스크립트는 기록했다고 믿고 가드는 없다고 읽는다 (`DB_SCHEMA §8.1.2` · `§2.14` · `#827`) |
| `test_db_backup_script.py` | 40 | **§5 DB · 백업 · 복구 리허설 · 교체** (`scripts/db_backup.py`) — 컨테이너 호출을 대역으로 바꿔 판단을 본다: `pg_restore`로 읽히지 않는 덤프는 **확정도 기록도 하지 않는다** · 가드가 찾는 `DB_BACKUP` 행을 남긴다 · 보존 개수는 같은 DB의 덤프만 센다 · 손상된 덤프(sha256)는 **서버에 닿기 전에** 거절 · 리허설이 행 수가 다른 테이블을 **이름으로** 말한다 · 교체는 운영 DB 이름을 그대로 적어야 하고, 대조에 실패하면 **앱을 멈추기 전에** 끝나며, 성공하면 이전 DB를 지우지 않고 남긴다 · 스크립트가 **표준 라이브러리만** 쓴다(배포 호스트에 가상환경이 없다). 실제 `pg_dump`·`pg_restore`는 CI docker 잡이 프로덕션 스택에서 매 실행 돌린다 (`#827`) |
| `test_db_session_param_convert.py` | 15 | **§5 DB · 운영 엔진의 CUBRID 파라미터 변환 훅** (`db/session.py`) — 🔴 이 훅은 **배포 엔진에만** 붙고 검사는 `conftest`가 붙이는 제 변환기를 쓰는 엔진으로 돌아, 전 검사에서 **한 번도 실행되지 않고 있었다**(커버리지 하한 게이트가 `db/session.py 78.6%`로 잡았다 · `#955`). 그 갈라짐은 이미 한 번 결함을 냈다 — `conftest` 쪽이 모든 `datetime`을 초로 깎아 **검사만 없는 결함을 만들어 내고** 있었다. 운영 쪽 규칙을 못 박는다: `UUID`→hex 32자 · `Decimal`→`str` · **`datetime`은 건드리지 않는다** · 그 밖의 값·딕셔너리 파라미터 통과 · **`CAST(? AS 타입)`·`IS 0/1`은 고쳐 쓰지 않고 감지만 한다**(`#1316` — 종전에는 `?`·`= 0/1`로 치환했다. 스위트 전체를 세어 운영 경로의 치환이 `auth.py` `.is_(False)` 세 곳뿐임을 확인하고 그 셋을 `== 0`으로, 테스트의 PostgreSQL 시절 `CAST(:x AS jsonb)`를 걷어 0건을 만든 뒤 치환을 걷었다) · `IS NULL`은 그대로 · 훅이 실제로 엔진에 **등록되는가**까지 · **소스 가드 2종**(`#1316`) — `src/`에 `.is_(True/False)` 호출이 없다(구문 트리로 본다 — 관례를 설명하는 docstring까지 잡지 않게) · 생 SQL에 `CAST(:이름 AS …)`가 없다. 돌연변이(`auth.py` 한 곳을 `.is_(False)`로 되돌림) 검출. `#1246` — 테스트 엔진이 **프로덕션 훅을 우선 붙이고** 테스트 전용 변환(datetime 리터럴·`::cast`·`RETURNING`·INSERT id)을 그 위에 얹는 2층이 됐다(운영 경로를 실제 쿼리로 탄다). 감지 관측 2종도 여기 — `cast=`/`bool=` 카운트 로그가 남는가 · 깨끗한 문장은 로그가 없는가. 스위트 전체 합계는 `conftest.py`가 끝에 찍는다(`cubrid_param_convert 감지 합계` — CI `test` 잡 로그) |
| `test_zz_roundtrip.py` | 7 | §5 DB · 제약·마이그레이션 (데모 seed 분리 후 롤백 — `#451`) · **seed migration 멱등(#1201)** — 행은 있고 `alembic_version`만 직전인 운영 상태(2026-09-15 수동 seed)를 `stamp`로 재현해 `upgrade head`가 UNIQUE 위반 없이 성공하는지 본다 · **head 트리거 집합 둘**(`#1373` · `D-20`) — 왕복을 돌리기 **전에** ⑴ 같은 이름의 트리거가 둘 이상인 것이 0건인가(`GROUP BY name HAVING count(*) > 1` — 있으면 그 이름은 `-503`으로 지울 수 없고 왕복이 거기서 끊긴다. `db/trigger_ddl.drop_trigger`가 그 `-503`을 넘어가므로 여기서 세지 않으면 조용하다) ⑵ `upgrade head` 뒤 `db_trigger`의 이름 집합이 마이그레이션 `upgrade()`가 만든다고 적은 집합(`CREATE` 누적 − `DROP` · `op` 스텁으로 DB 없이 센다)과 **이름 하나하나** 같은가 — 합계 160은 `test_dbschema_head_sync`가 `DB_SCHEMA §7.4`와 대조하고, 수가 같아도 남은 것 하나와 빠진 것 하나가 상쇄되는 경우는 여기서만 보인다. 두 단언은 `test_downgrade_upgrade_roundtrip`이 되올린 **뒤에도** 다시 부른다 — 종료 코드 0은 집합이 온전하다는 뜻이 아니다. 기대 집합은 `tests/migration_stub.py`(두 검사 파일이 공유 · `db_trigger` 조회에 만든−지운 집합으로 답해 DROP도 실제처럼 집계) |

**합계 203개 파일 · 2746 함수 · 3437 수집.** (2026-09-24 실측 — #1625 감사 로그 같은 트랜잭션 · #1629 정박 구간 겹침 직렬화 · #1626 항차 행 잠금 · #1300 해상 경로망·우회 경유지 · #1373 트리거 DDL 멱등화 반영)

### 14.3 계획분 — 아직 파일이 없는 것

**현재 계획분은 없다.** 2026-09-17 재검증에서 종전 7행의 대응 이슈(#58~#66·#105)가 **전부 CLOSED**여서 「대응 이슈가 열려 있다」는 전제가 무너졌고, 구현도 대부분 **다른 파일 이름**으로 이뤄져 §14.4로 옮겼다(#1081 ⑷).

- 스냅샷 표현·정책은 `test_annual_simulation_read_db.py`가, 민감도는 `test_annual_simulation.py`(`§3.26`·`§3.27`)이 덮는다 — 별도 파일 없이 같은 파일의 절로 들어갔다.
- 잔여 부채는 이 절이 아니라 **§14.5 미대응 표와 열린 이슈**(#673 파라미터 import · #756 민감도 2건 · #816 재현성 3종)가 추적한다.

> **이 원칙은 유지한다** — 계획분이 생기면 「틀린 참조」로 지우지 않고 이 절에 등재한다. 계획 문서가 계획을 담는 것은 정상이다.

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
| `test_scenario_adopt.py` | `test_scenario_adopt_db.py` (#58) |
| `test_soft_delete.py` | `test_soft_delete_db.py` (#66) |
| `test_audit_log.py` | `test_audit_events_db.py` · `test_audit_actions_db.py` (#65) |
| `test_annual_simulation_api.py` | `test_annual_simulation_api_db.py` (#63) |
| `test_weather_factor.py` · `test_weather_fallback.py` | `test_weather_model.py` · `test_weather_fallback_db.py` · `test_weather_client_db.py` (#61 · #62) |
| `test_csv_security.py` | `test_voyage_import_db.py` · `test_data_export_db.py` (#59 · #60) |

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

> 대응 이슈 번호를 2026-09-17에 실제 잔여로 정정했다(#1081 ⑸) — 종전 표가 가리키던 #443·#444는 **CLOSED**다. 기능은 살았고 잔여 이슈가 다른 번호로 이어받았다.

| ID | 대응 이슈 |
|---|---|
| `AT-SA-001`~`002` | `#756` (민감도 지렛대 2건 — `#443` 잔여 · 엔진은 `#63`이 넣었다) |

> **`IT-IMPORT-001`~`005`는 이 표에서 나갔다 (#673 · 2026-09-18).** `test_parameter_import_db.py`가 다섯 케이스를 전부 고정했다 — 「대응됨」 상태는 표에 적지 않는다. `test_case_id_sync`가 이 면제 목록이 낡는 것을 막는다.

### 14.6 프론트엔드 테스트의 관할

**이 문서는 Python 테스트를 관할한다.** 프론트엔드(`vitest`)는 여기서 규정하지 않는다 — 건수도 적지 않는다(`§11.1` · #830).

| 영역 | 관할 |
|---|---|
| Python (`tests/`) | 본 문서 `§2`~`§7` · `§14` |
| 프론트엔드 (`frontend/src/**/*.test.ts`) | 각 모듈 옆에 두고 `frontend/README.md`가 안내 |
| 화면 접근성 | 본 문서 `§7` (WCAG 2.1 AA · #68) — 검사는 `frontend/src/a11y.test.tsx`, 케이스 ID 가드가 프론트 검사 파일도 센다 |

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
| 2026-09-10 | `#876` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`vessel-detail/VesselDetail.test.tsx` +4). §14는 백엔드 pytest만 센다. 고정하는 것은 **등급이 없어도 누적값이 보이는가**다. 선박 상세의 YTD 카드 게이트가 `current?.dataAvailable && current.rating`이라, 서버가 실적·기준·항차 수를 다 줬는데 **등급 하나가 null이면 그 전부를 버리고** 「올해 등록된 항차 실적이 없습니다」를 냈다 — 실적이 있는데 없다고 말하므로 사용자는 항차를 다시 등록하려 한다. ⚠️ **등급 null은 비정상이 아니다** — `API_SPEC §2.7`이 `rating: string \| null`로 규정하고 `#834`(RO_RO 여객선 고속선의 등급 경계 누락)가 그 조건을 실재시킨다. 게다가 카드 **안쪽은 이미 각 값의 null을 `—`로 세심히 처리**하고 있었고(`attainedCii`·`requiredCii`), `GradeBadge`도 null을 「없음」 변형으로 그린다 — **바깥 게이트가 그 처리를 전부 무효화**하고 있었다. 게이트를 `dataAvailable` 하나로 좁히고 배지 라벨만 null 분기를 더했다(`올해 누적 등급 없음`). ⚠️ **검사 단언을 두 번 고쳤다** — ⑴ 같은 값이 연도별 이력 표에도 나와 `getByText`가 중복으로 실패했고(YTD 카드로 범위를 좁혔다) ⑵ 배지 라벨도 이력 표에 있어 대기 기준으로 쓸 수 없었다(`waitFor`로 카드 요소 자체를 기다린다). 화면에 같은 값이 두 번 나오는 자리에서는 **범위를 좁히지 않은 단언이 구현이 아니라 검사를 깨뜨린다.** ⚠️ **`npm run build`가 타입 오류를 잡았다** — 픽스처를 리터럴로 두어 `attainedCii`가 `string`으로 추론됐고, 「데이터 없음」 검사에서 `null`로 덮을 때 `TS2322`가 났다. **vitest 1200건은 그대로 통과했다** — 타입 검사는 `npm run build`만 한다. `CiiYear`로 명시해 해소했다. 돌연변이 검사: 게이트를 되돌리면 2건이 실패한다 (#876) |
| 2026-09-10 | `#875` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`scenario-comparison/ScenarioComparison.test.tsx` +5). §14는 백엔드 pytest만 센다. 고정하는 것은 **화면의 숫자와 제목이 같은 계산을 가리키는가**다. 항로 비교 제목이 살아 있는 `form.vesselId`·`form.regulationYear`를 읽고 숫자만 계산 시점 스냅샷(`response`)을 읽어, 결과를 본 뒤 상단바에서 배를 바꾸면 **A선의 계산 결과 위에 B선의 이름**이 붙었다(연도도 같다 — 「2027년 기준」 제목 아래 2026년 계산이 남는다). 원인 경로는 셸→폼 동기화 효과다: 상단바 선택이 `form`에 즉시 반영되는데 `response`는 그대로다. ⚠️ **`#821`이 같은 제목 줄에 넣은 검사 2건이 이 결함을 못 잡았다** — 계산 **직후**의 제목만 봤기 때문이다. 두 출처가 우연히 같은 값을 가리키는 순간만 보면 어긋남은 영영 드러나지 않는다. 성공 상태에 `ResultSnapshot`(선박명 + 계산에 쓴 조건 전부)을 응답과 **같은 자리에** 담아 제목이 그것을 읽게 했다 — 「제목만 따로 조심한다」로 두면 다음에 추가되는 표시값에서 같은 결함이 되풀이된다. 스냅샷은 응답 시점이 아니라 **제출 시점**에 뜬다(계산이 도는 동안에도 상단바를 바꿀 수 있다). 제목을 고정하면 이번에는 결과와 폼이 어긋난 상태가 남으므로 `#727` 선례대로 **「결과가 낡음」 표시**를 함께 넣었다 — 판정은 폼 **전 필드**를 본다(선박·연도만 보면 거리·연료만 고쳤을 때 안내가 빠진다). ⚠️ **`sameInputs`를 복사하지 않고 형태만 열었다** — `voyage-cii/formRules.ts`의 그 함수는 키를 열거하지 않아 폼에 칸이 늘어도 자동 포함되는데, 복사하면 그 규율이 한쪽에서만 유지된다(`#820`·`#872`와 같은 판단). ⚠️ **`npm run build`가 또 타입 오류를 잡았다** — 제네릭 제약을 `Record<string, string>`으로 두었더니 두 폼 상태가 모두 `interface`라 인덱스 시그니처가 없어 `TS2345`가 났다. **vitest 1205건은 그대로 통과했다.** `Record<keyof T, string>`으로 바꿔 해소했다. 흐림 처리도 기능①을 그대로 베끼지 않았다 — 이 화면은 제목과 선박명·연도가 **같은 `<header>` 안**에 있어 직계 자식만 걸면 정작 어긋나는 그 줄이 흐려지지 않는다. 돌연변이 검사: 스냅샷을 `form`으로 되돌리고 `stale`을 `false`로 고정하면 4건이 실패한다 (#875) |
| 2026-09-10 | `#874` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`realtime-cii/RealtimeCiiView.test.tsx` +4). §14는 백엔드 pytest만 센다. 고정하는 것은 **선박 전환 직후 화면이 이전 선박의 어떤 값도 보여 주지 않는가**다. `/vessels/:vesselId/voyages/:voyageId`는 라우트 파라미터만 바뀌므로 **언마운트 없이 선박이 전환되는데** 이 화면은 그 전환을 전혀 몰랐다 — ⑴ A선의 이름·등급이 B선의 URL 아래 그대로 남고(「불러오는 중」은 두 번째 선박부터 영영 뜨지 않는다) ⑵ 늦게 도착한 A의 폴링 응답이 `setData(A)`로 B의 화면을 덮으며(다음 폴링까지 60초간 복구 없음) ⑶ A의 404 오류 패널이 B에서 유지됐다. ⚠️ **`VesselDetail.tsx`의 「effect 안 `let alive`」 선례를 그대로 쓸 수 없다** — 그 방식은 요청을 **그 effect가 시작한 경우에만** 덮는데, 이 화면은 60초 폴링이 effect 밖에서 `load`를 부르고 `clearInterval`은 **이미 날아간 요청을 취소하지 않는다.** 그래서 소유권을 ref 하나(`generationRef`)에 두고, 리셋 effect가 세대를 올리며 `load`가 시작 시점의 표를 응답 시점에 대조한다. `vesselId` 자체를 비교하지 않는 것은 **A → B → A 왕복** 때문이다 — 그때 첫 A의 인플라이트 응답은 `vesselId`가 같아 통과하지만 더 오래된 값이다. ⚠️ **첫 검사 판본 5건 중 2건만 돌연변이 검사에서 실패했다.** 오류 패널 검사가 새 선박의 응답을 **곧바로** 돌려줘, 성공 경로의 `setFailure(null)`이 패널을 어차피 지웠다 — 결함이 보이는 창은 **전환 직후 응답 전까지**인데 그 창을 만들지 않았다. 응답을 늦춰 다시 박았다(3건 실패). 폴링 대상 검사는 **고정되지 않음을 명시**했다(`load`가 `vesselId` 의존이라 리셋 없이도 새 선박을 조회한다) — `#755`의 클로저 회귀를 잡는 용도로 남긴다. `BackLink`도 URL 기준으로 바꿨는데 **이쪽은 독립적으로 고정되지 않는다**: 리셋이 「`data`와 URL이 어긋나는 상태」 자체를 도달 불가로 만들기 때문이다. 격리 돌연변이: 가드만 제거 → 경합 1건 실패 · 리셋만 제거 → 3건 실패 (#874) |
| 2026-09-10 | `#878` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`auth/session.test.ts` +6, 기존 1건 정정). §14는 백엔드 pytest만 센다. 고정하는 것은 **세션이 만료된 설정 화면 동작이 로그인 유도로 끝나는가**다. `redirectToLogin()`의 소비처는 `features/<기능>/apiProvider.ts` 열세 곳뿐이고 **`auth/session.ts` 자신의 요청은 0곳**이었다 — 이름 변경·비밀번호 변경·탈퇴가 전부 이 파일의 요청이라, 설정 화면에 머무는 동안에는 401을 받아도 서버 문구가 폼 아래 붙을 뿐 **화면이 설정에 갇혔다.** `changePassword` 주석의 「다음 요청이 401을 받아 `redirectToLogin`으로 간다」가 **이 모듈 안에서는 성립하지 않았다**(그 주석도 정정했다). ⚠️ **이슈 본문의 「서버 응답의 `code`로 가른다」는 실행 불가능했다** — 실측 결과 세션 만료와 비밀번호 오입력이 **같은 `code`(`UNAUTHORIZED`)**로 온다(`middleware.py:82` vs `routes/auth.py:371`, `message`만 다르다). `API_SPEC:194`가 그 코드를 「세션 없음·만료·무효」로 정의하므로 지금 상태가 정본과 어긋나는 쪽이고, 그 수정은 서버 몫이라 `#902`로 갈랐다. 문구 대조는 **서버가 한 글자만 고쳐도 조용히 깨지고 그 실패가 「만료인데 폼에 머문다」 방향**이라 채택하지 않고, `GET /auth/me`로 **세션 생존을 직접 확인**한다(실패 경로에서만 요청이 한 번 더 난다 — 성공 경로는 추가 요청이 없음을 검사로 박았다). `postJson`에 401 처리를 넣지 않은 것은 **그쪽 401이 세션 만료가 아니라 자격 증명 오류**여서다 — 넣으면 로그인 실패가 화면 이동으로 나타나 사용자가 무엇이 틀렸는지 못 본다. ⚠️ **기존 검사 1건을 정정했다**: `deleteAccount`의 「거부돼도 캐시를 비우지 않는다」가 **401을 예시로** 쓰고 있었는데, 401은 거부가 아니라 세션 소멸이라 이번 변경과 충돌한다. 의도(「탈퇴된 척하지 않는다」)를 살려 **비-401 실패**로 바꾸고 401은 별도 검사로 갈랐다. 반대 방향(**비밀번호를 잘못 친 것만으로 로그아웃**)도 함께 박았다. 세션 만료 문구가 저장소에 **14곳·두 갈래**로 흩어져 있는 것은 `#901`로 갈랐다 — 이번에는 `session.ts`에 정본 상수를 두고 **새 사본을 만들지 않는 것**까지만 했다. 돌연변이 검사: 세 요청의 401 처리를 치우면 3건이 실패한다 (#878) |
| 2026-09-10 | `#908` | `test_workflow_timeouts.py` 4 → **6함수** · 합계 실측 갱신(109파일·1516함수·1876수집 → **109파일·1518함수·1878수집**). CI `test` 잡이 **러너 이미지에 미리 깔린 Chrome 저장소**의 인덱스 해시 오류로 죽었다 — `apt-get update`는 **소스 하나만 실패해도 exit 1**이고, 우분투 미러 네 곳은 전부 `Hit`이었다. ⚠️ **`#533`이 넣은 재시도로는 낫지 않는 종류다**: 해시 불일치는 결정적이라 재실행에서 같은 실패가 반복됐다(`#533`은 「응답이 오지 않는」 실패를 겨냥한 것이고 그 자리에서는 옳다 — 두 처방은 서로 대체하지 않으므로 재시도는 그대로 두었다). **중단 지점을 옮겼다** — 갱신 실패는 `::warning::`으로 남기고 계속 가고, **폰트 설치 실패는 여전히 하드 실패**다. 지켜야 하는 것은 「인덱스를 새로 받았는가」가 아니라 **「폰트가 실제로 깔렸는가」**이고(`#361` — 폰트가 없으면 한글이 tofu가 되어 회귀를 못 잡는다) 그 판정은 이미 설치 루프에 있었다. ⚠️ **처음 권장안(Chrome 저장소 파일 삭제)을 착수 후 바꿨다** — 오늘의 벤더만 고치고 파일명이 바뀌면 `rm -f`가 **조용히 아무것도 하지 않는다.** 검사는 **양방향**을 잠근다: 설치 실패가 여전히 `::error::`+`exit 1`인가(둘 다 경고가 되면 **폰트 없이 CI가 초록으로 통과**한다) · 갱신 실패에 `exit 1`이 다시 들어오지 않는가. 돌연변이 검사 양방향 각각 1건씩 실패한다 (#908) |
| 2026-09-10 | `#873` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`voyage-management/voyageRules.test.ts` +12 · `apiProvider.test.ts` +2 · **`VoyagePanel.test.tsx` 신설 5건**). §14는 백엔드 pytest만 센다. 고정하는 것은 **화면이 항차 시각 4종을 실제로 수집하는가**다. ⚠️ **결함은 「값이 틀렸다」가 아니라 「칸이 없다」였다** — 프론트 전체에서 `departure_at`·`arrival_at` 참조가 **0건**이었고(grep 실측), 서버는 `§3.3`·`§3.6`에서 **처음부터 받고 있었다.** 화면으로 만든 항차는 출항 시각이 영원히 `null`이라, 진행 중으로 옮기면 시뮬레이션 시계가 `departure_at is None`에서 곧바로 거리·연료 **0**을 돌려주고(`simulation_clock.py:177`) 경고 체계는 `distance_nm > 0`을 전제하므로 그 0도 잡지 못한다 — **조용히 0으로 기여한다.** ⚠️ **로컬 스택 실측으로 확정했다**(이슈가 `#616` 선례를 들어 요구한 절차). 진행 중 항차가 없는 선박에 시각 없이/있게 한 건씩 만들어 `IN_PROGRESS`로 옮기고 `/cii/current`를 대조: 시각 없음 → `underway_hours 0.0000 · distance_nm 0.00 · fuel_ton 0.00 · attained_cii null`, 시각 있음 → `456.0000 · 6384.00 · 532.09 · 10.381709`. 두 경우 모두 `warnings`는 `null`이었다. ⚠️ **이슈 본문의 「CSV·API 경로와 결과가 갈린다」는 사실이 아니다** — `services/voyage_import.py:282-283`이 `planned_departure_at=None`을 명시적으로 쓰고 `§8.2` 필수 컬럼 7종에 날짜가 없다. CSV도 같은 결함이라 완료 기준 「CSV 경로와 같은 기여」는 **버그 상태에서 이미 참**이었다. CSV 축은 정본(CSV 형식) 개정이라 `#906`으로 갈랐다. 검사 구성은 세 층이다 — 순수 함수(다리·검증), provider(본문에 키가 실리는가), **렌더(칸이 화면에 있는가)**. 마지막 층이 없으면 이 결함은 원리적으로 드러나지 않는다(`#823`·`#755`·`#872`가 각각 겪은 함정). 시각은 `§3.3`이 optional이므로 **화면도 필수로 만들지 않고** 「비워 두면 진행 중 누적에 0으로 기여합니다」를 안내로 말한다 — 규칙을 바꾸지 않고 결과를 알린다. 돌연변이 검사: provider에서 두 키를 빼면 1건, 폼에서 칸을 지우면 3건이 실패한다 (#873) |
| 2026-09-10 | `#890` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(**`voyage-management/exportRules.test.ts` 신설 11건** · `apiProvider.test.ts` +5 · `VoyagePanel.test.tsx` +5). §14는 백엔드 pytest만 센다. 고정하는 것은 **`PRD §5.1` MUST인 운항 기록 내보내기가 화면에서 도달 가능한가**다. 서버·검사가 완비돼 있는데 프론트 호출부가 **0건**이었다(`grep -rn "/export" frontend/src` → 0). ⚠️ **결함은 「값이 틀렸다」가 아니라 「버튼이 없다」였다** — `#873`과 같은 종류라 **렌더 층**이 핵심이다(규칙·provider만 검사하면 화면이 그것을 부르지 않아도 초록이다). ⚠️ **이슈가 ⚠️로 걸어 둔 진입점 결정(A 보고서 / B 선박상세 / C 새 화면)을 사실로 해소했다** — `UIFLOW`에 `SCR-007`이 **없고**(`screens.ts` 주석대로 `UIFLOW`는 `SCR-00x` ID를 부여하지 않는다) `PRD:636`이 `SCR-007`을 **「Data Import/Export」 한 항목**으로 규정하며 **가져오기는 이미 항차 패널에 있다**(`VoyagePanel.tsx:200`). 한쪽만 다른 화면에 두면 정본이 한 화면으로 정한 것이 쪼개지므로 **가져오기 옆**으로 갔다 — 이슈의 잠정 유력안(A)과 다르며, 그 잠정은 `UIFLOW` 확인 **전**의 것이었다. 되돌리기 비용을 낮추려 `ImportCsv`와 대칭인 **독립 컴포넌트**로 두었다(자리를 옮기면 렌더 한 줄). `filenameFrom`·`saveBlob`을 `download/file.ts`로 **공용화**했다 — 두 번째 소비처가 생겼고, 특히 `revokeObjectURL` 규율이 한 곳에만 남는 상태를 만들지 않는다(`#820`·`#872`와 같은 판단). ⚠️ **기존 가드 둘이 이번 변경을 잡았다**: `cardSpec.test.ts`가 셀렉트 배경을 카드 면으로 쓴 것을 `DESIGN_SYSTEM §8` 위반으로(→ `--surface-inset`), `moduleBoundary.test.ts`가 미참조 `export`를. 돌연변이 검사 3종: 화면에서 컴포넌트 제거 → 5건 · 실패 응답도 파일로 저장 → 1건 · 빈 연도를 쿼리에 실음 → 2건 실패 (#890) |
| 2026-09-10 | `#871` | `test_auth_tokens.py` 13 → **19함수** · §14 인벤토리에 `test_coverage_config.py`(2함수) 등재 · 합계 실측 갱신(109파일·1518함수·1878수집 → **110파일·1526함수·1886수집**). ⚠️ **이슈의 전제가 틀렸다 — 본문은 실행되고 있었다.** 재현은 정확했지만(409를 단언하는 검사에서 그 409를 만드는 `auth.py:190`이 `Missing`) 원인은 **커버리지 계측**이었다: `TestClient`가 앱을 **워커 스레드**의 blocking portal에서 돌리고 그 안에서 SQLAlchemy asyncio가 **greenlet**으로 스택을 전환하는데, 저장소에 coverage 설정이 **아예 없어**(`.coveragerc`도 없다) 기본값으로 돌았다. 같은 검사 한 건 실측: `thread` 41% · `greenlet` 31% · **둘 다 50%**. 그 검사는 라우트가 만드는 문구(`EMAIL_TAKEN_MESSAGE`)를 단언하므로 실행은 애초에 필연이었다. `concurrency = ["thread", "greenlet"]`을 넣자 **전체 93% → 96%**(미실행 집계 387 → 252, **135문장**). ⚠️ **이슈가 묶은 6파일이 갈렸다** — `auth.py` 49→**96%** · `auth_dev.py` 58→**100%** · `auth_tokens.py` 56→80%는 계측 문제였고, **`reports.py` 61% · `exports.py` 65%는 변화가 없어 진짜 공백**이다. ⚠️ **「왜 90% 게이트가 못 잡았는가」** — 게이트는 **전체 합계**를 본다. 5,897문장 중 라우트 몇 파일이 40~70%로 집계돼도 합계는 93%라 통과한다. **합계 게이트는 파일별 구멍을 볼 수 없다.** 계측을 고친 뒤 남은 `auth_tokens.py` 80%는 **진짜 미검사**였다 — 종전 검사가 **거부 경로만**(위조 토큰·모르는 주소·약한 비밀번호) 보고 인증 메일 재발송·인증 확인의 **성공 경로를 보지 않았다.** 6건을 신설해 **96%**로 올렸다. 남는 4문장(`168-169`·`232-233`, 「토큰은 유효한데 사용자가 없다」)은 `user_token` FK가 `ON DELETE CASCADE`라 **API로 도달 불가능한 방어 코드**임을 확인해 검사 대신 사유를 남겼다 — 도달시키려면 `session.get`을 갈아 끼워야 하고 그것은 동작이 아니라 구현을 검사하는 것이다. 돌연변이 검사: 설정에서 `thread`를 빼면 1건 · 설정 절을 지우면 2건 실패 (#871) |
| 2026-09-10 | `#824` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(**`reports/ReportsView.test.tsx` 신설 5건** · **`vessel-management/VesselManagement.test.tsx` 신설 1건** · `voyage-cii/VoyageCiiForm.test.tsx` +3 · `voyage-management/VoyagePanel.test.tsx` +3 · `layout/AppShell.test.tsx` +2). §14는 백엔드 pytest만 센다. 고정하는 것은 **로딩·실패·경합 6곳**이며, 전부 「이 저장소가 다른 화면에서는 이미 제대로 하고 있는 것」이 한 화면에만 빠진 형태다. ⑴ 연간 등급·기능① 폼이 `if (!vesselId) return`으로 조기 반환하며 `yearsLoading`을 `true`로 남겨 **선박 미선택 첫 진입에서 영구 로딩**이 됐다 — 공용 훅(`#632`)이 이미 막고 있던 자리라 이관으로 해소. ⑵ 보고서 항차 재조회가 **이 저장소에서 유일하게 취소 플래그가 없었고**(다른 열 곳은 전부 갖고 있다) 커서 전량 순회라 응답 시간이 항차 수에 비례한다 — 경합·잔류·실패 은폐 셋이 겹쳤다. `null`/`'failed'`/배열 3상태로 갈랐다. ⑶ 상단바 항차 셀렉트에 `voyagesState` 신설(선박 축의 `vesselsState`가 선례) — 조회 실패가 「항차 없음」으로 나가던 것을 갈랐다. ⑷ `VesselManagement` 최초 로딩 문구. ⑸ `run()`이 성공 여부를 돌려주게 해 **실패 시 실적 폼이 닫히며 입력이 소실**되던 것을 막았다(바로 옆 `VoyageForm`은 정반대로 처리하고 있었다 — 두 폼의 규율이 갈려 있었다). ⑹ 연료 목록이 폼보다 늦게 오면 `useState`가 `''`로 굳는데 `<option value="">`가 없어 **첫 연료가 선택된 것처럼 그려졌다** — 렌더·전송 양쪽에 같은 기본값 규칙을 넣었다. ⚠️ **이슈의 마지막 항목(「eslint를 도입한다」)은 불필요했다** — **oxlint 1.78.0이 `react-hooks/exhaustive-deps`를 구현한다**(일부러 깨뜨린 파일에서 정확히 잡는 것을 확인). 규칙을 켜자 `src/` 전체 위반이 **0건**이라 `.oxlintrc.json` 한 줄로 끝났고, CI는 이미 `npx oxlint`를 돌린다. ⚠️ **「무효한 억제 주석 5개」도 사실이 아니다** — oxlint가 `eslint-disable-next-line`을 **존중한다**(주석을 지우면 그 자리에서 오류가 뜨는 것으로 확인). 규칙이 꺼져 있어 아무것도 안 돌았을 뿐이고, 개수도 이번 ⑴ 이관으로 5 → **3**이 됐다. ⚠️ **⑹의 첫 검사 판본이 돌연변이 검사에서 통과했다** — 스텁이 즉시 응답해 「목록이 폼보다 늦게 온다」는 결함 조건이 만들어지지 않았다. 응답을 늦춰 다시 박았다. 돌연변이 검사 7종(취소 플래그·실패 구분·리셋·조기 반환·폼 닫기·연료 기본값·3상태) 전부 각각 실패한다 (#824) |
| 2026-09-10 | `#753` | `test_response_contract_db.py` 6 → **8함수** · 계약 표 15 → **18항목** · 합계 실측 갱신(110파일·1526함수·1886수집 → **110파일·1528함수·1891수집**). ⚠️ **이슈가 지목한 두 결함 중 하나는 이미 해소돼 있었다** — `API_SPEC §2.14`의 `"risk_level": "WATCH"`는 `#798`이 고쳤다(`4592032`). 프론트 픽스처에 남은 `WATCH`는 **의도적**이다(모르는 코드를 화면이 방어하는지 보는 검사). 그리고 체크리스트 ①의 「계산 3종」 중 **둘은 `#752`가 이미 넣어** `POST /scenarios/compare` 하나만 남아 있었다. 그래서 JSON 응답인 `§6.3` `snapshot-voyages`·`§6.4` `reproduce`를 함께 넣어 **계산 축의 공백을 닫았다** — `#751`(`rng_metadata` 키 불일치)·`#752`(계산 봉투 7필드 누락)가 어느 가드에도 걸리지 않은 이유가 이 공백이었다. 필드 집합은 **실제 응답을 띄워 뽑았고**(저장소의 `flatten`을 그대로 import해 표기를 맞췄다) 손으로 적지 않았다. 파라미터라이즈 목록의 제외 조건을 `POST ` → `("POST ", "GET ")`으로 넓혔다 — 접두가 붙은 것은 만들어야 하거나 식별자가 필요해 전용 테스트가 본다. ⚠️ **덮지 못한 곳을 표에 적어 두었다**: 민감도의 `voyage_±1` 여섯 키는 `calc/annual_simulation.py`가 `if remaining:`으로 가르는데(`PRD §12.6` — 항차가 있어야 성립하는 지렛대) **데모 시드에서는 잔여 계획이 잡히지 않아** 나오지 않는다. 표에 넣으면 거짓 실패가 나고 뺐으므로 **그 지렛대가 사라져도 통과한다** — 감추지 않고 사유와 함께 적었다(검증은 `#756` 소관, 시드에 잔여 계획을 넣으면 이 파일의 다른 계약이 함께 흔들린다). 완결성 가드 수치도 16→**19**·400→**600**으로 올렸다. 돌연변이 검사: 시나리오 응답에서 필드 하나를 지우면 1건 실패 (#753) |
| 2026-09-10 | `#825` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(**`auth/RequireAuth.test.tsx` 신설 3건** · **`features/auth/VerifyBanner.test.tsx` 신설 3건** · `auth/session.test.ts` +4, **기존 1건 정정**). §14는 백엔드 pytest만 센다. 고정하는 것은 **인증·세션 처리 5곳**이다. ⑴ `RequireAuth`에 **확인 전 상태가 없어** 첫 렌더에서 무조건 로그인으로 보냈다 — `currentUser`는 언제나 `null`로 시작하고 프로브는 `useEffect`라 커밋 **이후**에 돈다. 그 한 프레임 때문에 로그인 상태로 새로고침할 때마다 **로그인 카드가 그려졌다가 되돌아왔다.** ⚠️ **문서화된 동작이 구현되지 않은 상태였다** — 그 파일 주석이 이미 「확인 중에는 자식을 렌더하지 않되 레이아웃을 유지한다」를 규정하고 있었다. `authResolved`를 세우고 `useAuthResolved()`로 **같은 구독**에 실었다(별도 구독이면 한 프레임 어긋나 「확인은 끝났는데 사용자는 아직 null」이 생긴다). 곁가지로 `next`에 **해시**를 포함시켰다. ⑵ `logout()`이 **HTTP 상태를 보지 않아** 403·500에도 로그아웃한 척했다 — `fetch`는 네트워크 실패에서만 reject한다. `sid`가 살아 있고 `revoked_at`도 `NULL`이라 백엔드 복구 뒤 **재로그인 없이 진입**된다. ⚠️ **기존 검사 1건의 전제를 정정했다**: 「서버 호출 실패로 로그아웃이 **막히지 않는다**」가 그 동작을 옳다고 못 박고 있었다(근거는 「로그아웃 버튼에 갇히는 것이 최악」). 지금은 **이 기기의 상태는 지우되 이동하지 않고 던지고**, `AppShell`이 문구를 띄우며 버튼이 남아 다시 누를 수 있다 — 갇히지 않으면서 사실을 알린다. ⑶ 로그아웃이 `sessionStorage` 전역 컨텍스트를 지우지 않아 **같은 탭에서 다음 계정이 앞 계정의 선박 선택을 물려받았다**(`sessionStorage`는 「탭 수명」이지 「로그인 세션 수명」이 아니고 이동이 같은 탭에서 일어난다) — `globalContext.clearStored()` 신설. ⑷ `changePassword` 성공 후 캐시를 비운다 — 종전에는 남겨서 **「로그인 화면으로」 버튼이 로그인 화면에 도달하지 못했다**(살아 있는 캐시 → `Navigate` → `/dashboard` → 401 → 전체 재로드). `confirmPasswordReset`이 이미 같은 처리를 해 **대칭이 깨져 있었다.** ⑸ 재발송 실패 문구를 성공과 **같은 상태**에 담아 삼항이 **버튼을 문구로 교체**했다 — 「다시 시도해 주세요」라면서 수단을 없앴다(주석은 정반대를 적고 있었다). 별도 상태로 갈라 버튼을 남기고 `role="alert"`로 알린다(배너가 `role="status"`라 그냥 두면 오류로 안내되지 않는다). 돌연변이 검사 5종 전부 각각 실패한다 (#825) |
| 2026-09-10 | `#828` | `test_audit_actions_db.py` 7 → **9함수** · 합계 실측 갱신(110파일·1528함수·1891수집 → **110파일·1530함수·1893수집**) · **프론트엔드에 파일 완결성 가드 신설**. ⚠️ **이슈 다섯 축 중 ⑶은 전부 이미 해소돼 있었다** — `rng_metadata`의 `seed_entropy`·`bit_generator`는 `#751`이 서버에 넣어 **지금 실제로 나온다**(재현 응답 실측으로 확인), `test_fleet_summary.py`의 `boundaries` 픽스처도 `#814`가 `DVector`로 고쳤다. ⑵도 이날 `#753`이 `POST /scenarios/compare`·`snapshot-voyages`·`reproduce` 계약을 넣어 상당 부분 닫혔다. ⑷는 실재했다 — `services/audit.py`가 `PASSWORD_CHANGE`·`ACCOUNT_DELETE`를 기록하는데 **어느 검사도 단언하지 않았고**, 두 동작을 HTTP로 실제 호출하는 `test_account_self_service_db.py`에 `audit` 문자열이 **0건**이었다. 두 검사를 신설하며 **`revoked_sessions`가 담기는지**와 **자격 증명이 담기지 않는지**(`TECH_SPEC §13.1` `#277`)를 함께 못 박았다 — 행만 남기고 숫자를 빼면 「본인이 모르는 기기가 있었는가」에 답할 수 없고, 탈퇴는 `app_user`에 시각 컬럼이 없어 **이 기록이 유일한 시점 근거**다. ⑸는 **원인이 아니라 결과를 본다** — 관측된 원인(워커 기동 실패)은 자원 부족이라 명령으로 재현되지 않고, `include` 축소·파일 이동도 **같은 결과**(조용히 덜 도는 것)를 낸다. `frontend/scripts/check-test-files.mjs`가 **디스크의 검사 파일과 실제로 실행된 파일을 대조**하고 `npm run test`의 마지막 걸음으로 붙는다. 검사 파일은 자기가 몇 개 돌았는지 알 수 없으므로 vitest 안의 검사로는 둘 수 없다. 돌연변이 검사: `include`를 좁혀 7파일을 제외 → **exit 1**과 누락 목록 출력 · 정상 → exit 0. ⑴(리포트·정박 쓰기 라우트 6종)은 남았다 (#828) |
| 2026-09-10 | `#892` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(`scenario-comparison/requestRules.test.ts` 14 → **31** · `apiProvider.test.ts` 13 → **15** · `ScenarioComparison.test.tsx` 16 → **21**). §14는 백엔드 pytest만 센다. 고정하는 것은 **기능② 화면이 서버 입력 13종 중 6종만 보내던 것**이다 — `PRD:1165-1166`이 「사용자가 직접 입력」으로 규정한 우회 거리·감속 속력을 정할 수 없었고 `weather_model`은 **전송 0건**이라 기상 보정이 화면에서 도달 불가였다. ⚠️ **이슈의 잠정 유력안(A: 좌표·목적항은 `#760` 뒤로)이 이슈 자신의 완료 기준과 모순임을 실측으로 확인했다** — `services/weather.py:276-280`이 좌표 없는 요청을 `NEUTRAL_FACTOR`로 되돌리므로 모델만 고르면 **보정이 통째로 건너뛴다.** 실 API 3회 측정: 모델 없음 `fuel_ton 87.50` · `SIMPLE_RULE`+좌표 없음 **`87.50`(같다)** · `SIMPLE_RULE`+35N 140E `94.22`. 그래서 **현재 좌표 2칸을 포함**했다 — 현재 위치는 항만이 아니라 바다 한가운데라 `#760`(샘플 항만 테이블)이 막는 대상이 아니고, `_resolve_direct_distance()`가 `direct_distance_nm`을 먼저 보므로 대권거리 경로를 타지도 않는다. **목적항 좌표 3종만 `#760` 소관으로 남긴다**(항만을 고르는 UI가 선행). ⚠️ **미지정의 표현은 「키를 넣지 않는 것」 하나뿐이다** — `detour_distance_nm: 0`은 「기본을 쓰라」가 아니라 「0마일로 우회하라」이고 VAL-002에 걸려 422가, `null`은 `extra="forbid"` 스키마에서 명시적 값이 된다. `JSON.stringify`가 `undefined` 키를 빼는 성질을 그대로 쓰고, 검사가 **직렬화된 문자열에 그 낱말이 없는지**까지 본다(`toHaveProperty`만 보면 `"key":null`이 통과한다). ⚠️ **감속 속력만 하한이 다르다** — 다른 칸은 VAL-002(`> 0`)인데 이 칸은 `PRD §9.1` VAL-009(`>= 1.0`)라, 같은 규칙을 쓰면 `0.5`가 화면을 빠져나가 서버 422가 된다. 경계값 `1.0`이 통과하는 것까지 못 박았다. 좌표는 `API_SPEC:572`의 「함께 지정」을 화면에서 잡는다 — 한쪽만 넣으면 서버가 422를 내는데 **어느 칸이 빈지는 화면이 이미 안다.** `0`이 유효한 좌표(적도·본초자오선)라는 것도 별도로 박았다. ⚠️ **폼 렌더만 보면 배선이 증명되지 않는다**(`#821` 선례: 프론트 검사 59건이 통과하는 동안 `warnings: []` 리터럴이 배너 조건을 영구 거짓으로 두고 있었다) — 그래서 화면 검사가 **입력창에 친 값이 `fetch` 본문에 실리는지**를 직접 판다. ⚠️ **기존 가드 하나가 이번 변경을 잡았다**: `moduleBoundary.test.ts`가 `WeatherModel`을 미참조 목록에서 빼라고 했다 — 내 주석의 문자열 때문이었고, 가리는 대신 **인라인으로 복제했던 유니온을 정본 타입으로 교체**했다(복제해 두면 서버가 모델을 추가할 때 두 화면 중 하나만 따라간다). ⚠️ **`#139` 추적처는 이미 `#892`로 고쳐져 있었다** — 이슈 체크리스트 항목 하나가 착수 전에 해소된 상태였다. 돌연변이 검사 4종: provider 배선 제거 → 2건 · 감속 하한을 `> 0`으로 → 2건 · 빈 칸을 `0`으로 전송 → 3건 · 좌표 짝 검사 제거 → 2건 실패. 실 API로 세 경로 확인: 기본 `DETOUR 1050.0`·`SLOW 11.8kn` / 사용자 입력 `DETOUR 1200.0`·`SLOW 10.5kn` / 감속 `1.0` → `SLOW_SPEED_FLOOR` 경고 (#892) |
| 2026-09-10 | `#827` | `test_password.py` 15 → **22함수** · `test_reports_db.py` 28 → **29함수** · 합계 실측 갱신(110파일·1530함수·1893수집 → **110파일·1538함수·1902수집**). **네 축 중 판정이 끝난 것과 기계적인 것만** 처리했다(부분) — 백업·관측성·세션 정리 셋은 도구·주기 결정이 선행한다. ⚠️ **첫 측정이 통째로 오염돼 있었다** — 로그인은 **IP당 분당 10회**로 제한되고(`api/rate_limit.py:124`) 429는 즉시 응답하므로, 부하를 걸수록 「빨라지는」 숫자가 나왔다. `RATE_LIMIT_AUTH_PER_MINUTE`를 올려 다시 쟀다. ⚠️ **두 번째 측정도 냉시동에 오염돼 있었다** — 워밍업 없이 재면 개선 전후가 62 ms로 **같게 나온다**(첫 스레드 생성 + 첫 연결). 대조군(로그인 없음)을 두고 워밍업한 뒤에야 값이 갈렸다: **대조군 11.9 ms / 로그인 1건 동안 56.4 ms(동기) → 대조군 11.4 ms / 22.5 ms(스레드풀)**. 막는 몫이 44.5 → 11.1 ms다. 루프 자체는 직접 측정에서 **최대 정지 65.7 ms → 3.3 ms**(틱 1 → 27). ⚠️ **한도 상수를 실측으로 정했다** — 동시 검증 가속이 2에서 1.57x, **4에서 2.00x, 8에서 1.96x**로 4를 넘으면 늘지 않는다(Argon2가 1회당 64 MiB를 훑어 메모리 대역폭에 걸린다). 그래서 `MAX_CONCURRENT_HASHES = 4`(4 x 64 MiB = **256 MiB**)다 — 처음 8로 뒀다가 측정을 보고 내렸다. anyio 기본 한도 40을 그대로 쓰면 **2.5 GiB**가 되어 「이벤트 루프 정지」를 「메모리 고갈」로 바꾸는 것에 지나지 않는다(`docker-compose.prod.yml`에 메모리 상한이 없다). ⚠️ **동작 검사로는 되돌림을 잡을 수 없다** — 동기 형을 다시 불러도 결과와 상태 코드가 똑같고 달라지는 것은 *그동안 다른 요청이 어떻게 되는가*뿐이다. 그래서 라우트 2파일에 동기 호출(`hash_password(`·`verify_password(`·`verify_dummy(`)이 남았는지 **소스로 확인**하는 가드를 함께 뒀다. 루프 검사도 시간을 재지 않고 **다른 태스크가 몇 번 깨어났는지**를 센다 — 느린 CI에서 흔들리지 않으면서 막히면 1을 넘지 못한다. N+1은 `report.py`가 배치 함수(`repositories/not_underway.py:275`)를 쓰게 했다 — 목록 화면은 이미 쓰는데 **리포트 경로만 빠져 있었다.** 검사는 **구간을 셋** 넣는다(한 건이면 N+1과 배치의 쿼리 수가 같아 구분되지 않는다) 돌연변이 4종: 라우트를 동기로 되돌림 → 1건 · `_async`를 동기 함수로 위장 → 1건(루프 검사) · 한도를 40으로 → 1건 · 구간마다 조회로 되돌림 → 1건 실패. `logs/`를 `.dockerignore`에 넣었다 — 빌드 속도가 아니라 **인증 토큰이 쿼리 문자열째 남는 파일**이라 `.env` 옆이다. ⚠️ **기존 가드 하나가 이번 변경을 잡았다**: `anyio`를 `pyproject.toml`에 직접 의존으로 적었더니 `test_uv_lock_sync.py`가 `uv.lock` 미갱신을 잡아냈다 — `uv lock`으로 함께 커밋했다 (#827) |
| 2026-09-10 | `#828` (2차) | **`test_not_underway_api_db.py` 신설 6함수** · 합계 실측 갱신(110파일·1538함수·1902수집 → **111파일·1544함수·1908수집**). `#828` ⑴ 중 **정박 쓰기 라우트 5종**을 닫는다 — ⑴의 나머지(리포트 2종)는 `#753` ②의 「파일 응답을 계약 표에 어떤 형태로 적을 것인가」 판정에 걸려 있고, **정박 쪽은 그 제약이 없어** 먼저 했다. ⚠️ **기존 `test_not_underway_crud_db.py` 32함수는 서비스 함수를 직접 부른다** — 라우트를 지나지 않으므로 다음 다섯은 어느 검사도 보고 있지 않았다: ⑴ **201 Created**(서비스는 상태 코드를 만들지 않는다) ⑵ **PATCH의 `exclude_unset`** ⑶ 예외 → 상태 코드(409·422·404) ⑷ **CSRF** ⑸ 봉투 모양. ⚠️ **가장 위험한 것은 ⑵다** — 이 라우트의 주 용도가 「진행 중 구간의 종료 확정」이라 **종료 시각 한 칸만** 보내는 요청이 정상인데, `exclude_unset`이 없으면 그 요청이 `port_name`·`distance_nm`까지 `None`으로 실어 보내 **한 칸을 고치려던 사용자가 나머지를 지운다.** 서비스 층은 이미 풀린 인자를 받으므로 그 층에서는 재현되지 않는다. ⚠️ **`TestClient`는 실제로 커밋한다**(롤백 픽스처를 쓰지 않는다) — 전용 선박을 만들고 `finally`에서 지운다. 남기면 다음 실행의 겹침 판정과 리포트 집계가 그 행들을 본다. 삭제 확인은 **응답이 아니라 목록으로 다시 읽는다** — 삭제 응답만 보면 「지웠다고 말하지만 남아 있는」 경우를 잡지 못한다. 돌연변이 4종: `exclude_unset` 제거 → 1건 · 201을 200으로 → 1건 · CSRF 의존성 제거 → 1건 실패. **네 번째(자식 소유 확인 제거)는 이 파일이 잡지 않는다** — 기존 `test_fuel_use_of_another_period_cannot_be_deleted`가 잡는 것을 확인하고 **중복해 넣지 않았다** (#828) |
| 2026-09-10 | `#831` | §14 인벤토리 **수치 변화 없음** — **프론트엔드만 바뀌었다**(**`deadCss.test.ts` 신설 2건** · `screens.test.ts` 경로 대조 1건 → **가드 2건**으로 교체 · `voyage-cii/rules.test.ts` **삭제**). §14는 백엔드 pytest만 센다. 지운 것은 **파일 4개**(`voyage-cii/rules.ts`+검사 · `GradeChip.tsx`+`.css`) · **CSS 선택자 40개** · **토큰 10개** · **죽은 export 2건**이다. ⚠️ **⑴은 지우기 전에 `#134`가 건 조건 ⑶(대조)을 이행했다** — `#39`·`#40`이 둘 다 CLOSED임을 확인하고 `determineRating`·`nextWorseBoundary`·`determineRiskLevel` 셋을 서버(`calc/rating_engine.py`)와 대조했다. `<=` 연쇄와 `PRD §9.4.1` 위험도 표가 **일치**했고, 차이는 하나뿐이다 — `margin_ratio`가 `null`일 때 프론트는 `HIGH`로 흡수하고 **서버는 필수로 요구**한다. 죽은 코드이고 판정은 서버 소관이라 지웠다. ⚠️ **이슈 본문의 수치 두 개가 틀렸다**: `--chart-*` 8개 「전량」이 아니라 **`--chart-grid`는 살아 있고**(`VesselDetail.css:412`), 죽은 CSS는 35개가 아니라 **40개**였다(`.card__note`·`.chip:hover`·`.chip:focus-visible` 등이 목록 밖). ⚠️ **⑹은 손대지 않았다** — `DESIGN_SYSTEM.md:224`가 **`showPattern`을 이름으로 명시**해, 지우면 정본이 없는 prop을 가리키게 된다(정본 수정 선행). ⚠️ **⑺에서 경로 정본을 파생으로 바꿨다** — 종전에는 `session.ts`가 경로 5개를 문자열로 다시 적고 검사가 둘을 대조했는데, **한쪽만 고치면 라우트는 옛 경로에 남고 `findScreenByPath()`는 새 경로를 가리켜** `AppShell` 폭 정책(`§7.1`)만 조용히 어긋난다. `SCREEN_BY_ID`에서 파생시키자 대조할 것이 없어졌고, 대신 **경로 문자열을 밖에서 다시 적었는지** 보는 가드로 바꿨다 — 그 가드가 **실물 1건**(`LoginPage.tsx:125`의 `to="/login"`)을 즉시 잡았다. `deadCss.test.ts`를 만들며 오탐 3종을 차례로 걸러냈다: CSS 주석 속 `grid.gnb-expanded` · `@import` 파일명 `.generated` · **가드 자신의 `KEPT` 키 문자열**(검사 파일을 사용 집계에서 빼야 보존 목록 검사가 의미를 갖는다). 소스 주석도 걷어낸다 — 「지금 안 쓴다」고 적어 둔 주석이 사용 근거가 되어 `.app-shell--collapsed`가 잡히지 않았다. 돌연변이 4종: 죽은 선택자 되살리기 → 1건 · 보존 목록에 살아 있는 클래스 넣기 → 1건 · 경로 하드코딩 → 1건 · 중복 선언 되살리기 → 1건 실패 (#831) |
| 2026-09-10 | `#829` | §14 인벤토리 **수치 변화 없음** — **프론트엔드만 바뀌었다**(**`a11yWiring.test.ts` 신설 5건** · **`CiiHistoryChart.test.tsx` 신설 4건** · `tokens.sync.test.ts` +3). §14는 백엔드 pytest만 센다. **⑶·⑷는 손대지 않았다** — 둘 다 새 색 값을 정하는 일이라 디자인 소관이다(`§0.2` 제약상 hex는 Figma 소유). ⚠️ **⑵가 결정 없이 풀렸다** — 저장소가 같은 문제를 이미 `color-mix` **파생**으로 풀어 둔 선례가 있었다(`--color-primary-solid`). 새 hex를 만들지 않으므로 `§15` 하드코딩 금지에 걸리지 않는다. 방향만 반대다: 저쪽은 **면을 `--surface-page` 쪽으로 30% 내려** 글자를 세웠고, 이쪽은 **글자를 `--text-primary` 쪽으로 30% 올려** 면 위에 세운다. 다크 `#799dce` — 네 면 최저 **5.18**(popover). **80%는 4.51이라 여유가 0.01뿐이어서 쓰지 않았다.** ⚠️ **문자색 사용처가 이슈의 9곳이 아니라 23곳이었다** — `--color-primary`와 `--semantic-primary` 두 이름으로 갈려 있었다. `border-color` 14곳은 **그대로 뒀다**(테두리는 3:1 축이라 기준이 다르다). ⑴은 `45%` 알파 한 줄 제거로 8개 조합이 함께 통과로 바뀌고, `forced-colors`에서 `box-shadow`가 사라지는 것에 `outline: Highlight` 폴백을 넣었다. ⚠️ **⑸(a)의 `VoyageCiiForm` 지적은 이미 해소돼 있었다** — 힌트가 있는 유일한 칸(`speed`)이 `-hint`를 잇고 있다. 실재한 것은 **`role="alert"` 없는 오류 문구 26곳**이었다(검증 실패가 낭독되지 않는다) · `NotUnderwayPanel`의 `aria-invalid` 0건 · `role` 없는 `aria-label` 3곳 · 진행률 막대에 `role="progressbar"` 없음 · skip link 0건 · `document.title` 갱신 0건 · `aria-busy` 단독 8곳 · `AccountMenu` Escape 후 초점 유실. ⚠️ **⑸(f)(`disabled` → `aria-disabled`)는 하지 않았다** — 버튼이 초점·클릭을 유지하게 되므로 핸들러에 가드를 함께 넣어야 하고, 기존 검사가 `disabled`를 단언하고 있어 **동작 변경**에 해당한다. ⚠️ **가드를 만들며 같은 함정을 두 번 겪었다** — 「`role="img"`가 있어야 읽힌다」고 적어 둔 **주석 자체가 `role=`을 담아** 정작 속성이 빠졌을 때 잡히지 않았다(`deadCss.test.ts`와 같은 원인). 돌연변이 7종: 포커스 링 알파 복원 → 3건 · 링크색 되돌리기 → 1건 · 혼합비 88% → 1건 · `role=alert` 제거 → 1건 · skip link 제거 → 1건 · `document.title` 제거 → 1건 · `role="img"` 제거 → 1건 · 무늬 덮기 제거 → 2건 · A에도 무늬 → 1건 실패 (#829) |
| 2026-09-10 | `#889` | `test_dashboard_seed.py` 16 → **18함수** · 합계 실측 갱신(111파일·1544함수·1908수집 → **111파일·1546함수·1910수집**). ⚠️ **A/B/C 판정을 받고 시작했다** — 데모 데이터는 심사 서사 그 자체라 임의로 바꿀 수 없다. **A(C등급 선박 1척 추가)** 확정. ⚠️ **결함이 아니었다** — 종전 4척의 사유(`ALREADY_AT_OR_BELOW` 3 · `NOT_UNDER_WAY` 1)는 전부 규정대로였고, 문제는 **「아직 여유가 있는 배가 언제 D에 진입하는가」를 보여 줄 배가 하나도 없다**는 것이었다(`PRD §3.3.7` 대시보드 위험 지표). 값은 **산식에서 역산**했다 — `BULK_CARRIER` 30,000 DWT · `required 6.931972` · D 진입 경계 `1.06R = 7.347890`에서 초기 4,000nm/263t(강도 6.83) + 최근 1,200nm/95t(강도 8.22) → **YTD ratio 1.031(C) · n일 38**. ⚠️ **두 구간으로 나누는 것이 요점**이다 — 강도가 같으면 `NOT_WORSENING`이 나온다. 최근 구간은 **`_rel()` 상대 시각**이어야 한다: 절대 날짜면 시간이 지나며 30일 창을 벗어나 `NO_RECENT_DATA`로 다시 `—`가 된다(`#792`가 같은 함정을 이미 겪었다). n일을 38로 둔 것도 **연말까지 남은 날수**와의 관계다 — 크면 `NOT_THIS_YEAR`로 다시 빈다. ⚠️ **기존 검사 7건이 걸렸고 전부 갱신했다**: 선박 수 4→5 · UUID·IMO·축 목록 · 「모든 선박에 2년 이력」 · 「운항 중이면 진행 중 항차」 · 행 수 상수. 그래서 2025 이력과 진행 중 항차도 함께 넣었다 — 다른 4척과 같은 규율이다. ⚠️ **등급 헬퍼가 `one()`으로 항차 1건을 전제하고 있었다** — 두 구간을 가진 선박에서 `MultipleResultsFound`가 났다. **합산으로 고쳤다**(`attained = M / W`이고 둘 다 누적이므로 그쪽이 연간 등급의 정의다). 합성 IMO `0000036`은 체크섬 규칙(마이그레이션 036)을 만족한다 — `3 × 2 = 6`. 돌연변이: 최근 구간의 초과 연료를 계획치로 낮추면(악화 소멸) → 1건 실패. 실측 확인: 등급 분포 `B:1 C:0 D:1 E:2` → **`B:1 C:1 D:1 E:2`**, `at_risk` 2 유지 (#889) |
| 2026-09-10 | `#747` | §14 인벤토리 **수치 변화 없음** — **프론트엔드·정본만 바뀌었다**(`tokens.sync.test.ts` 48 → **56건**). §14는 백엔드 pytest만 센다. **`rlatnals4114`의 2026-09-10 확정 문서**를 받아 `§16` 미확정 4항목을 닫았다. ⚠️ **정본이 적어 둔 두 선택지가 둘 다 성립하지 않았다**(항목 1) — ⓐ「플레이스홀더 전용」은 저장소에 `::placeholder` 선언이 **0건**이고, ⓑ`#647380`의 `4.86:1`은 **흰 카드 위** 값이라 `--surface-inset` 위에서는 `4.34`로 미달이다. **값이 아니라 토큰을 쪼갰다** — `--color-text-faint` 폐기 → `--color-text-disabled`(비활성 6곳 · WCAG 1.4.3이 대비 요구에서 제외) + `--color-surface-muted`(면적 1곳 · 비텍스트 3:1). ⚠️ **`--border-faint`는 확정 목록에 있으나 만들지 않았다** — 소비처가 0곳이고 `#831`이 참조 0건 토큰 10개를 막 걷어낸 참이라, 쓰는 자리가 생길 때 넣는다. **2026-09-10 이 판단을 확정으로 닫고**(`§16` 항목 1 비고) 가드를 하나 더 걸었다 — 「지금 만들지 않는다」가 아니라 **「선언과 사용이 함께 간다」**를 잠근다. 미룬 것을 잠그면 쓸 자리가 생기는 날 가드를 지워야 하고 **지우는 순간 판단이 사라진다**. `all` 쪽 주석 스트립은 실측으로 무는 것을 확인했다(다른 CSS가 주석으로 `var(...)`를 언급만 해도 사용으로 읽힌다). 항목 2는 **정본이 정답**이었다 — 코드가 다크에 검은 그림자를 정의하고 있었고 `§5`는 `none`을 적고 있었다. 떠 있는 면을 위해 `--shadow-overlay`를 신설하고 `AccountMenu` 판·skip link에 배선했다. 항목 3은 `--cii-none-bg`를 **생성 원본(`Light.tokens.json`)에서** 중립 표면에 맞춰 닫았다 — 다크는 이미 `--surface-inset`과 같은 값이었고 **라이트만 웜톤**(`#f2f2ef`)이었다. 항목 5는 **Lucide**(MIT) 확정 — 기본 `strokeWidth`가 2라 `components/Icon.tsx`가 1.5를 강제한다(호출부마다 적게 두면 적는 곳과 잊는 곳이 갈린다). ⚠️ **정본 개정 8곳**: `§0.2` 제약 5 보강·**제약 6 신설**(문자 대비는 가장 어두운 표면 기준) · `§5` 전 항목에 〔확정〕/〔제안〕 표기 + `--shadow-overlay` · `§12` Lucide·커스텀 아이콘 규칙 · `§15` `--brand-*` 채널 신설 · `§16` 항목 1·2·3·5·13 닫음 · 항목 15ⓐ 삭제 · 항목 4에 `#925` 경고. 새 가드 8건: 문자 토큰 × 표면 전조합 대비 · 면적 토큰 3:1 · 다크 그림자 `none` · 오버레이 예외 · 브랜드 테마 불변 · `--cii-none-bg` 일치 · faint 폐기 · 쪼갠 토큰 실사용. 돌연변이 4종 전부 각각 실패한다 (#747) |
| 2026-09-10 | `#694` | §14 인벤토리 **수치 변화 없음** — **프론트엔드만 바뀌었다**(**`components/ErrorState.test.tsx` 신설 5건** · **`errorPattern.test.ts` 신설 2건**). §14는 백엔드 pytest만 센다. **`rlatnals4114`의 2026-09-10 확정 문서**대로 층위를 **3개**로 확정하고 공용 컴포넌트 하나로 모았다 — 종전에는 에러 표현 클래스가 **24종**이었다. ⑵와 ⑶(목록 실패·계산 실패)은 사용자 입장에서 둘 다 「이 영역이 실패했다」이고 **차이는 크기뿐**이라 `size` 속성으로 다룬다. 필드 검증(C)은 **폼 규격으로 이관**하고 손대지 않았다(5곳 · 전부 `id`로 `aria-describedby`에 물려 있다). CSV 행 오류 표도 대상 밖이다 — 상태 표시가 아니라 결과 데이터다. ⚠️ **선행 수정이 실재했다** — `.empty--error`가 **등급 E 토큰**(`--cii-e-*`)을 쓰고 있었고 그 코드가 살아 있는 화면이 하필 **등급을 보여 주는 선박 상세**였다. 「불러오지 못했습니다」가 「이 배는 E등급입니다」로 읽힌다. ⚠️ **새 가드가 같은 위반을 하나 더 잡았다** — `AuthShell.css`의 `.auth-alert--error`가 등급 E, `--ok`가 등급 A 색이었다(로그인 화면). 확정 문서가 지적하지 않은 자리이며 **가드가 없었다면 남았을 것**이다. 색면은 중립으로 빼고 **아이콘·문구에만** 위험색을 준다 — 큰 색면은 토큰을 분리해도 등급 신호로 읽히고, 색각 이상 사용자에게 아이콘이 두 번째 단서가 된다(`§0.2` 제약 3). 재시도 문구는 **「다시 시도」 하나**이고 컴포넌트가 인자로 받지 않는다 — 문구가 갈리는 것이 24종이 생긴 경로다. 재시도와 「다른 길」(404의 대시보드 링크)을 **함께 두지 않는다**: 다시 시도해도 소용없는 실패에 버튼을 두면 같은 실패를 반복한다. ⚠️ **`#831`의 죽은 CSS 가드가 곧바로 일했다** — 이관으로 죽은 선택자 **11개**를 즉시 잡아냈다. 그 가드는 `src/` 전체를 읽어 5초 제한을 넘었고, 결과를 기억하게 하고 제한을 20초로 올렸다(**대상을 좁히지 않는다** — 훑지 않은 파일이 곧 놓치는 파일이다). ⚠️ **주석이 가드를 무력화하는 함정을 세 번째로 만났다** — 「종전 `.empty--error`가 …」라고 적어 둔 설명이 그 문자열을 담아, 클래스가 되살아나도 구분되지 않았다(`#831`·`#829`에 이어). 돌연변이 3종: 에러 배경에 등급 토큰 되살리기 → 1건 · 재시도 문구를 「다시 불러오기」로 → 2건 · 재시도와 다른 길을 함께 그리기 → 1건 실패 (#694) |
| 2026-09-11 | `#818` | **`test_input_boundaries_api_db.py` 신설 4함수** · 합계 실측 갱신(113파일·1554함수·1916수집 → **114파일·1558함수·1920수집**). 고정하는 것은 **같은 입력에 같은 답을 내는가**다. ⚠️ **`limit` 규칙이 세 서비스에 각자 적혀 있었고 항차만 빠져 있었다** — `services/pagination.py`로 모아 셋이 위임하게 했다. 규칙을 세 번 적으면 세 번째가 빠진다. ⚠️ **`PRD §8.4`는 「선박 DWT/GT 변경」으로 좁게 적혀 있다** — 코드가 문서보다 넓게 보호하는 쪽이라 모순은 아니나 문구 확장은 별건으로 등록했다. 돌연변이 3종(리포트 클램프 제거 · `limit` 정규화 환원 · `ship_type` 표시 환원) 각각 실패한다 (#818) |
| 2026-09-11 | `#749` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 바뀌었다**(`annual-simulation/copy.test.ts` 범위 확장 +1 · **`styles/typography.test.ts` 신설 2건**). §14는 백엔드 pytest만 센다. ⑴ **금지 문구 가드가 이름만큼 넓지 않았다** — 테스트 이름은 「어느 문구에도 없다」인데 `ANNUAL_COPY` 한 곳만 봤고, 기능③이 경고를 그리는 `WARNING_MESSAGE`가 검사 밖이라 금지 낱말(「연말 예상 등급」)이 든 `NO_REMAINING_VOYAGES`가 데모 두 척에서 떴다. 범위를 **이 화면이 문구를 가져오는 두 곳**으로 넓히고 이름도 그 범위로 고쳤으며, 범위가 다시 좁아지면 걸리는 검사를 따로 뒀다. ⚠️ **넓히기 전에 금지 자체를 판정했다** — 「연말」·「예상 등급」·「누적 기준 예상」은 근거가 사라졌고(`#63` 엔진 · `#353` YTD — 종전 근거 `#136`은 **기능①** 이슈였고 그 근거도 「기능③과 누적 데이터가 **없으므로**」였다) `PRD COR-2`·`§12.7`이 바로 그 표기를 처방하므로 **금지를 풀었다**. 「추천」(`PRD §6.3`·`§11.2`)만 남는다. ⑷ `§3` 자간 조임을 `PageHeader`에서 `global.css`의 `h1`으로 옮겼다 — `§3`은 크기 토큰에 조임을 건다. 화면에서 달라지는 것은 **선박 등록 제목 하나**다(나머지 `h1`은 이미 조여 있거나 자체 값이 있다). ⑵ `ComingSoon`은 `#594` 판정대로 남기며 이유가 이미 적혀 있고, ⑶ `.vessel-management__banner`는 이미 없어 확인만 했다. 돌연변이 검사: `h1` 조임 제거 → 1건 · 검사 범위를 `ANNUAL_COPY`로 되돌림 → 1건 · 경고 문구에 「추천」 삽입 → 1건 실패 (#749) |
| 2026-09-11 | `#837` | `test_annual_simulation_read_db.py` 26 → **28함수** · 합계 실측 갱신(114파일·1558함수·1920수집 → **114파일·1560함수·1922수집**). 고정하는 것은 **두 해시가 동시에 어긋날 때 무결성 실패(500)가 파라미터 변경(409)에 가려지지 않는가**다. 종전에는 파라미터 해시가 어긋나는 순간 409를 던져 **입력 해시 검사가 실행조차 되지 않았다.** ⚠️ **반대 방향도 함께 잠근다** — 파라미터만 바뀐 흔한 경우가 500으로 오인되면 사용자가 「새로 실행」 대신 관리자를 찾는다. 가려진 쪽은 경고 로그로 남긴다. 돌연변이(종전 순서 환원) 1건이 실패한다 (#837) |
| 2026-09-11 | `#860` | **`test_vessel_spec_bounds.py` 신설 3함수** · 합계 실측 갱신(114파일·1560함수·1922수집 → **115파일·1563함수·1939수집**). 고정하는 것은 **선박 제원의 API 경계가 DB 저장 범위와 같은가**다. 화면 쪽은 `specBounds.sync.test.ts`가 같은 원본(ORM 모델)을 대조한다 — §14는 백엔드만 센다. ⚠️ **수정 화면에 같은 검사가 한 벌 더 있었다**(`vessel-management/editRules.ts`) — 공용으로 모았다. 돌연변이: 서버 `gt=0` 환원 13 failed · 화면 3종 각각 실패 (#860) |
| 2026-09-11 | `#800` | **`test_ytd_voyage_count_db.py` 신설 3함수** · 합계 실측 갱신(115파일·1563함수·1939수집 → **116파일·1566함수·1942수집**). 고정하는 것은 **한 표 안에서 거리·연료·항차 수가 검산되는가**다. 응답 계약 가드(`test_response_contract_db.py`)가 새 필드 추가를 **정확히 두 경로에서** 잡아 계약 표를 함께 갱신했다. 돌연변이 2종(진행분 미집계 환원 · 리포트 라벨 환원) 각각 실패한다 (#800) |
| 2026-09-11 | `#885` | `test_cii_current_db.py` 31 → **36함수** · 합계 실측 갱신(116파일·1566함수·1942수집 → **116파일·1571함수·1947수집**). 고정하는 것은 **다유종 진행 항차의 연료가 계획 비율로 나뉘어 각 유종의 CF를 받는가**다 — 누적 기여분과 `current_voyage` 구간 CO₂가 **같은 몫**을 쓰는지, 단일 유종이 **종전과 같은 값**인지, 계획량이 비면(`NULL`) 종전대로 첫 유종인지 함께 본다. ⚠️ **마지막 몫 보정은 60:40 같은 비율로는 검사되지 않는다** — 몫이 딱 떨어져 찌꺼기가 없다. 3등분(1:1:1)에서 `91.3333`이 `91.33329999…`가 되는 것을 실측해 단위 검사로 따로 잠갔다. ⚠️ 폴백 검사를 계획량 0으로 처음 만들었다가 `chk_fuel_positive`에 걸렸다 — 0은 막혀 있고 합이 0이 되는 길은 `NULL`뿐이다. 돌연변이 3종(누적 종전 환원 · 구간 종전 환원 · 마지막 몫 보정 제거) 각각 실패한다 (#885) |
| 2026-09-11 | `#911` | **`test_report_export_routes_api_db.py` 신설 9함수**(파라미터화로 14건 수집) · 합계 실측 갱신(116파일·1571함수·1947수집 → **117파일·1580함수·1961수집**, `#885` 머지 후 기준). `#871`이 커버리지 계측(`thread`·`greenlet`)을 고친 뒤에도 **`routes/reports.py` 61% · `routes/exports.py` 65%로 남은 진짜 공백**을 메운다 — 두 파일 모두 **라우트 층의 형식 분기와 응답 헤더**가 비어 있었다. 렌더링·수집은 `test_reports.py`·`test_reports_db.py`가 서비스 함수를 직접 불러 검사하므로, **URL을 지나서 그 함수들이 올바른 형식·헤더로 묶여 나가는가**를 본 검사가 없었다. 두 파일 **100%**가 됐다. 고정하는 것은 넷이다 — ⑴ **미리보기(html)는 첨부가 아니다**(첨부 헤더가 붙으면 브라우저가 화면 대신 파일 저장 창을 띄운다) ⑵ 첨부는 **ASCII `filename`과 UTF-8 `filename*`을 둘 다** 싣는다(한글 파일명만 보내면 구형 클라이언트가 이름을 버린다) ⑶ JSON 봉투의 **`meta.row_count`가 실제 행 수와 같다** ⑷ 모르는 형식·종류는 **어느 필드가 틀렸는지**를 담은 422다. ⚠️ **파일별 커버리지 하한(이슈의 B안)은 이번에 넣지 않았다** — 합계 게이트가 파일별 구멍을 못 보는 것은 `#871`이 확인한 사실이지만, 하한을 어느 파일에 몇 %로 둘지는 테스트 정책 결정이라 이 이슈(두 파일의 공백)의 범위를 넘는다. 돌연변이 검사 3종(리포트 `filename*` 제거 → 3건 · 미리보기에 첨부 헤더 → 2건 · `row_count` +1 → 3건) 각각 실패한다 (#911) |
| 2026-09-11 | `#776` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 늘었다**(**`annual-simulation/AnnualSimulation.test.tsx` 신설 4건** · `apiProvider.test.ts` +4). §14는 백엔드 pytest만 센다. 고정하는 것은 **`PRD §12.4.3` 「결과 재현 버튼」이 화면에서 도달 가능한가**다. `POST /annual-simulations/{id}/reproduce`는 서버·검사가 완비돼 있었는데 `#556`이 `PRD §5.1`·`§6.2`·`UIFLOW` 셋만 대조해 「검증 수단이지 사용자 기능이 아니다」로 범위 밖 판정을 내렸고 `§12.4.3`을 놓쳤다. 검사는 두 층이다 — provider(원본 실행의 경로로 **본문 없이** POST · 실행과 같은 봉투 규칙 · 409 문구 보존)와 **렌더**(실행 전에는 버튼이 없다 · 누르면 결과의 `simulation_id`로 재현한다 · 실패 사유를 그대로 보인다 · **새로 실행하면 직전의 재현 확인이 남지 않는다**). 본문을 싣지 않는 것이 요점이다 — 폼 값을 실으면 폼을 고친 뒤 누른 경우 원본이 아닌 조건이 섞인다. ⚠️ **렌더 검사가 처음에 흔들렸다** — 연도 선택지가 그려진 뒤 기본값을 고르는 effect가 돌기 전에 실행을 누르면 화면이 「목록을 불러오는 중」으로 거부한다. 표시값으로도 기다릴 수 없었다(값이 `''`인 제어 셀렉트도 첫 선택지를 표시한다). 선택지가 그려진 뒤 `act`로 effect를 비워 3회 연속 통과를 확인했다. 돌연변이 검사: 버튼이 재현을 부르지 않음 → 3건 · 계산 이력 ID로 재현 → 1건 · 재현에 본문을 실음 → 1건 실패. ⚠️ `key` 제거는 실패하지 않는다 — 실행 중에 결과가 내려가 어차피 새로 그려지기 때문이며, 그 사실을 코드 주석에 적었다 (#776) |
| 2026-09-10 | `#879` | §14 인벤토리에 `test_dbschema_json_example_sync.py`(5함수) 등재 · 합계 실측 갱신(111파일·1546함수·1910수집 → **112파일·1551함수·1913수집**, 증가분 전부 이번 신설분이다). 고정하는 것은 **`DB_SCHEMA` JSONB 예시가 실제 기록 형태와 같은 키를 쓰는가**다. `§2.7 voyages_json` 예시는 저장 컬럼이 아니라 **API 응답(`§6.3` `/snapshot-voyages`)의 모양**을 적고 있었다 — `snapshot_voyage_id`·`original_voyage_id`·`status_at_snapshot`·`distance_nm`·`fuel_ton`은 전부 응답 쪽 이름이라 **저장 컬럼의 키 이름을 규정하는 정본이 사실상 없었다**(`TECH_SPEC §11.2`는 스냅샷 **대상**만 규정한다). 코드가 실제로 읽는 `kind`("ACTUAL"/"PLAN" — 완료·잔여 항차 수 집계와 계획 항차 CF 선택)는 문서에 아예 없었다. `§2.5 VOYAGE_ESTIMATE` 예시는 7키였는데 **실물 15키와 겹치는 것이 3키뿐**이었다 — `rating`은 실제 `estimated_rating`, `co2_ton`은 `co2_emission_ton`이고(`API_SPEC §4.1`과도 어긋났다), `weather_factor`·`weather_snapshot_id`는 `result_json`에 **들어가지 않는다**(후자는 실물 **컬럼**이라 예시가 컬럼을 JSON 안에 중복해 적고 있었다). ⚠️ **이슈 본문은 「15키 중 9키 누락」으로 적었으나 라이브 덤프 실측은 12키 누락**이었다. `rating_probabilities`도 JSON 숫자가 아니라 문자열(`"0.0200"`)이다 — float로 내면 `"0.0"`·`"1.0"`으로 자릿수가 뭉개지는 회귀가 실제로 있었다. 검사는 **키 집합만** 본다: 값 대조는 `test_scenario_example_sync.py`가 실행으로 하고, 이쪽은 「예시를 복사해 만든 파서가 조용히 `None`을 읽는」 경우를 막는다. DB를 띄우지 않고 `_snapshot_row`·`_build_data`를 직접 불러 대조하므로 **시드 상태에 흔들리지 않는다.** 돌연변이 검사 4종(키 이름 되돌림·`kind` 삭제·확률 float화) 전부 실패한다. `AGENTS §4.3`상 「오기·값 정정」이므로 `DB_SCHEMA` 버전은 올리지 않는다(선례 #78·#84·#115·#140) (#879) |
| 2026-09-10 | `#797` | **`test_seed_cf_matches_fuel_table.py` 신설 3함수** · 합계 실측 갱신(112파일·1551함수·1913수집 → **113파일·1554함수·1916수집**). 고정하는 것은 **시드가 얼린 CF가 정본과 같은가**다. ⚠️ **가드를 두 번 헛디뎠다** — ⑴ 소스에서 `"3.114"`를 문자열로 찾았더니 **왜 그렇게 했는지 적은 docstring이 자기 규칙에 걸렸다**(주석 줄만 걷어내는 것으로는 docstring이 남는다). ⑵ `Decimal` 인자가 1.3~3.3이면 CF로 봤더니 **연료 톤수 4건**(`1.80`·`3.20`·`2.00`·`1.40`)이 걸렸다 — 같은 숫자 범위에 다른 뜻의 값이 산다. **AST로 이름(`*_CF`)과 키(`cf_used`)만** 보게 고쳤다. 돌연변이 2종(종전 결함 재현 · 상수 되살리기) 각각 실패한다 (#797) |
| 2026-09-11 | `#819` | **`test_migration_guard.py` 신설 12함수**(파라미터화로 49건 수집) · `test_auth_tokens.py` 19 → **22함수** · 합계 실측 갱신(117파일·1580함수·1961수집 → **118파일·1595함수·2013수집**). 두 가지를 고정한다. ⑴ **되돌릴 수 없는 downgrade를 프로덕션에서 막는다** — `037`을 되돌렸다 올리면 보존 대상 테이블이라 `vessel_json`을 영원히 채울 수 없는데 경고도 없었다. 전 이력을 재검토해 18개 리비전을 막는다(`DB_SCHEMA §8.1.2`). 배선은 **소스를 읽지 않고 실제로 호출**해 확인한다 — `op`에 닿는 순간 실패하는 대역을 끼우고 `downgrade()`를 불러, 가드가 빠졌거나 연산 뒤로 밀리면 그대로 드러나게 했다. 자기 리비전 번호로만 풀리는지도 따로 본다(번호를 복사해 붙인 경우를 잡는다). 분류의 완전성 검사는 판별기 자신을 먼저 잠근다 — 판별기가 틀리면 완전성 검사가 조용히 통과한다. ⑵ **메일 실패의 원인이 로그에 남는다** — 소비자 세 곳이 백엔드가 보존한 `__cause__`를 전부 버렸다(두 곳은 로그 0줄, 한 곳은 `warning`). 검사는 메시지가 아니라 `exc_info`의 `__cause__`를 본다 — 「실패했다」 한 줄은 종전에도 있었고 빠졌던 것은 **왜**다. 실측: `APP_ENV=production`으로 `alembic downgrade 036`을 돌리면 `037`에서 끊기고 `038`의 downgrade도 함께 되돌려져 DB가 `038`에 남는다. `test_zz_roundtrip.py` 6건은 그대로 통과한다(개발·테스트는 막지 않는다) (#819) |
| 2026-09-11 | `#753` | `test_response_contract_db.py` 8 → **14함수** · `test_auth_api.py` 14 → **16** · `test_auth_tokens.py` 22 → **23** · `test_report_export_routes_api_db.py` 9 → **10** · 합계 실측 갱신(118파일·1595함수·2013수집 → **118파일·1605함수·2025수집**). **응답 계약 가드를 모든 라우트로 넓혔다** — 종전 계약 표는 조회 위주라 계산·쓰기 엔드포인트의 절반이 빠져 있었고 그 자리에서 `#751`·`#752`가 실제로 깨졌다. 셋을 더했다. ⑴ **누락 감지** — 51개 라우트를 OpenAPI에서 세어, 계약 표에 없는 것은 필드 집합을 보는 테스트(`파일::함수`, AST로 실재 확인)나 **면제 사유**를 적게 했다. 면제는 `POST /auth/dev-login` 하나다. ⑵ **쓰기 응답은 조회 계약과 대조한다** — 새 계약을 쓰면 저장 응답과 조회 응답의 갈림을 볼 수 없다. 화면은 저장 응답을 그대로 목록에 끼워 넣으므로 갈리면 **저장 직후에만** 칸이 빈다. 선박·항차(상태 전이·실적 포함)·정박 구간 쓰기가 전부 조회 모양과 같음을 실측으로 확인했고, 조회에 같은 모양이 없는 가져오기·채택·삭제 4종만 새 계약을 뒀다. ⑶ **파일 응답은 헤더 행을 정본과 대조한다** — 내보내기 CSV 헤더·JSON `columns`를 **서비스 상수가 아니라 `API_SPEC §8.1` 본문에서 파싱**한 열과 비교한다(상수와 비교하면 상수를 고칠 때 검사도 따라간다). 파서는 절 제목의 N열과 개수를 대조한다. 인증 10경로의 필드 집합은 계정을 만들고 지우는 인증 테스트 파일에 두었다. `test_scenario_example_sync.py`를 `§4.1`·`§6.1`로 넓히지 않은 사유는 그 파일 docstring에 남겼다. 돌연변이 5종(표 밖 라우트 · 없는 테스트 가리킴 · 열 순서 · 사용자 표현 필드 추가 · 전이 응답 `status` 누락) 각 1건 실패 (#753) |
| 2026-09-11 | `#828` | **`test_distance.py` 신설 10함수**(파라미터화로 14건 수집) · 합계 실측 갱신(118파일·1605함수·2025수집 → **119파일·1615함수·2039수집**). `calc/distance.py`의 수치 단언이 부산→로테르담 **한 점**(같은 반구 · haversine이 쉽게 맞는 자리)뿐이었다. 틀리기 쉬운 자리 셋을 넣었다 — **날짜변경선**(경도 차를 그대로 빼면 359°) · **극**(경도가 의미를 잃어야 한다) · **이종 반구**. ⚠️ **기대값을 haversine으로 만들지 않았다** — 같은 식으로 기대값을 만들면 식의 오류가 양쪽에 똑같이 들어가 통과한다. 적도·자오선은 호의 길이(`R × 각`)로, 나머지는 구면 코사인 법칙으로 대조한다. 돌연변이 3종: 등장방형 근사로 「단순화」 → 6건 · 한 위도만 쓰기 → 4건 · 반경 변경 → 1건 실패(반경은 기대값도 같은 상수를 쓰므로 **반경 검사 하나만** 잡는다 — 그래서 그 검사를 따로 두었다). 이것으로 이슈의 완료 기준이 채워진다 — 라우트 전부의 실제 HTTP 검사는 `#753`(PR #960)의 누락 감지가, 픽스처 정정·감사 액션·검사 파일 완결성은 PR #916·#919가 처리했다 (#828) |
| 2026-09-11 | `#756` | `test_annual_simulation.py` 48 → **50함수** · 합계 실측 갱신(119파일·1615함수·2039수집 → **119파일·1617함수·2041수집**) · 프론트엔드 `AnnualSimulation.test.tsx` +2. 고정하는 것은 **거리 지렛대가 연료를 함께 움직인다**는 모델의 성질이다(`PRD §12.6` 각주). 거리만 늘리면 「같은 연료로 더 갔다」가 되어 CII가 좋아지는 쪽으로만 틀린다. 함께 움직이면 CII는 거리당 값이라 **잔여분만 있을 때 두 행이 정확히 같고**, 확정분이 섞이면 그 혼합비만큼만(1% 미만) 움직인다 — 그래서 화면에서 「효과 없음」으로 읽혔다. 기능② `#799`와 같은 처리(화면이 이유를 말한다)를 따랐고, 렌더 검사는 **거리 행이 있을 때만** 그 이유를 말하는지 본다. 돌연변이: 연료를 움직이지 않게 하면 백엔드 2건 실패. 대체 연료 지렛대(⑴)는 판정 대기라 이 PR은 이슈를 닫지 않는다 (#756) |
| 2026-09-11 | `#894` | **`test_suite_lock_db.py` 신설 3함수** · 합계 실측 갱신(119파일·1617함수·2041수집 → **120파일·1620함수·2044수집**). 로컬에서 스위트 두 개가 같은 테스트 DB를 겹쳐 쓰면 서로의 행을 지우고(전역 DELETE·UPDATE 정리) 스키마까지 내렸다(`test_zz_roundtrip.py`) — 2026-09-09에 세 번, **220 failed**가 원인을 가렸다. 이슈의 A안(실행 잠금)을 택했다: `conftest.require_disposable_target()`(`#691`이 만든 「DB를 여는 자리」의 단일 관문)에서 **어드바이저리 잠금을 전용 연결로 세션 내내 쥐고**, 이미 누가 쥐고 있으면 `pytest.exit`로 원인을 말하며 멈춘다. 잠금은 연결에 걸려 강제 종료돼도 남지 않고, DB를 쓰지 않는 검사는 여전히 겹쳐 돌 수 있다. B·C(실행별 DB·템플릿 복제)는 병렬 수요가 생길 때로 미뤘다 — 이 문제의 본질은 「병렬로 못 돈다」가 아니라 「겹친 것을 모른다」다. 함께 **`upgrade head` 실패 메시지가 남은 리비전과 복구 절차**를 말하게 했고(README 「테스트 DB 복구」 신설), 검사는 **두 번째 `pytest`를 실제로 띄워** 종료 코드와 메시지를 본다. 돌연변이: 잠금을 잡지 않으면 2건 실패. CI는 잡마다 새 DB에서 한 번만 돌아 잠금이 늘 잡힌다 (#894) |
| 2026-09-11 | `#758` | **`test_db_check_cases.py` 신설 9함수**(15건 수집) · `test_case_id_sync.py` 7 → **8** · `test_doc_cross_refs.py` 4 → **5** · §14.5에 `A11Y-001`~`004`(미대응 · `#68`) · `PERF-001`~`004`(계획분 · `#67`) 등재 · 합계 실측 갱신(120파일·1620함수·2044수집 → **121파일·1631함수·2061수집**). **「없다는 사실이 보이지 않는 상태」를 막는 가드 둘의 사각**을 닫았다. ⑴ 케이스 ID 가드가 3단 ID만 잡아 **34개가 분류 검사 밖**이었다 — `A11Y-001`(2단)은 접두어 목록에 있으면서 한 건도 안 잡혔고, `PERF`·`DB-CHK`는 접두어가 없었고, `DB-CHK-001a`의 소문자 접미도 못 잡았으며, `PT`·`SEC`는 ID가 0개인 죽은 접두어였다. 문법을 접두어별 표로 바꾸고 **「모든 접두어가 하나 이상 잡힌다」**를 검사로 박았다. 넓히기 전에 26개 `DB-CHK`를 대조해 **11개는 기존 검사가 같은 입력으로 덮고 있어 ID만 달고**, 제약은 있는데 검사가 없던 **15개를 새로 썼다**(어긴 제약 이름까지 확인 — 다른 제약에 먼저 걸려 통과하는 것을 막는다). ⑵ 절 참조 가드를 `UIFLOW`·`DESIGN_SYSTEM` 두 문서에서 **정본 8종**으로 넓히고 5단 헤딩까지 보게 했다 — 드러난 끊긴 참조는 1건(`UIFLOW` §0의 존재한 적 없는 `API_SPEC` 12.1절 · 사라진 `redirect_to`)이라 실제 메커니즘(`?next=`)으로 고쳤다. 함께 **저장소에 없는 로컬 전용 문서(ROADMAP)를 근거로 인용하는 것**을 막는 검사를 두고 두 곳(`DB_SCHEMA` §2.5 각주 · 마이그레이션 010)을 정리했다. 돌연변이 3종 각 1건 실패 (#758) |
| 2026-09-11 | `#830` | **§11.1 영역별 표 삭제 — 수치는 §14.2 합계 한 곳에만 둔다** · `test_testplan_sync.py` 8 → **10** · `test_password.py` 22 → **24** · `test_input_boundaries_api_db.py` 4 → **5** · 합계 실측 갱신(121파일·1631함수·2061수집 → **121파일·1636함수·2066수집**) · 헤더 최종 수정일 `2026-09-02` → `2026-09-11`. §11.1은 2026-08-15 실측(62파일·469함수)에서 멈춰 있어 **같은 문서 §14.2와 합계가 달랐다** — 각주가 두 표를 연결해 두어 어느 쪽이 현재인지 알 수 없었고, 가드는 §14.2만 봤다. 영역별로 다시 세면 같은 수치를 두 곳에서 손으로 맞추는 구조가 남으므로 **표를 빼고, §11.1·`README` 문서 구조 표가 수치를 다시 적으면 실패하는 가드**를 뒀다. 프론트엔드 「331건」(§11.1 · §14.6)도 멈춘 수치라 뺐다 — 가드가 없는 수치는 적지 않는다. §11.1 각주의 `§14.5`(실제 절은 §14.6) 오참조도 이 삭제로 함께 사라졌다. `AGENTS §4.3` 정정 계열이라 버전은 올리지 않는다 (#830) |
| 2026-09-11 | `#930` · `#932` · `#933` | §14 인벤토리 **수치 변화 없음** — **프론트엔드·정본만 바뀌었다**(`errorPattern.test.ts` 2 → **3건** · `tokens.sync.test.ts` 61 → **63건**). §14는 백엔드 pytest만 센다. **`rlatnals4114`의 2026-09-11 확정 문서** 반영. ⑴ 「실패 표시에 등급 토큰을 쓰지 않는다」 가드를 **토큰 그래프를 끝까지 펼쳐** 보게 바꿨다(확정 H) — 종전은 선언 문자열에서 `var(--cii-`만 찾아, **등급 토큰의 별칭**(`--color-warning` → `--cii-c-fill`)을 쓰면 통과했다. 브랜드 판 「테마 불변」 가드가 별칭 한 겹 아래를 못 본 것(`#608`)과 같은 함정이다. 수집이 깨지면 빈 목록으로 통과하므로 알려진 별칭 하나로 그래프를 먼저 확인한다 ⑵ **「오버레이 그림자를 쓰는 규칙은 테두리를 함께 선언한다」** 가드 신설(확정 A ⑶) — 테두리는 토큰이 아니라 컴포넌트가 가져, 새 오버레이가 그림자만 가져다 쓰면 **다크에서만** 분리가 사라진다. 돌연변이 2종(에러 문자색을 `--color-warning`으로 · 본문 바로가기 테두리 삭제) 각 1건 실패 |
| 2026-09-11 | `#931` | §14 인벤토리 **수치 변화 없음** — **프론트엔드·정본만 바뀌었다**(`components/errorCopy.sync.test.ts` **신설 6건** · `ErrorState.test.tsx` 5 → **12건** · `errorPattern.test.ts` 2 → **3건** · `display/josa.test.ts` +3건). §14는 백엔드 pytest만 센다. **`rlatnals4114`의 2026-09-11 확정(B·C)** 반영 — 영역 실패의 제목을 **대상 명사에서 짓게** 했다(`subject` → 「{대상}을/를 불러오지 못했습니다」 · `action` → 「{동작}에 실패했습니다」). 잠그는 것 넷: ⑴ 영역 실패에 **기본 제목이 없다** — `subject`·`action` 없이 쓰면 **타입 오류**(`@ts-expect-error`로 빌드가 잡는다) ⑵ 조사를 컴포넌트가 붙인다(받침 판정) ⑶ 기본 제목·본문·패턴이 **`PRD §6.4`와 같다** — 종전에는 컴포넌트 안에만 있어 대조할 정본이 없었다 ⑷ 재시도 문구 변형(「다시 시도하기」 등)이 **공용 컴포넌트 밖 소스에도 없다** — 로그인 실패 화면이 그 보호 밖에 있었다. 돌연변이 3종(조사 제거 → 2건 · `PRD §6.4` 본문 어미 → 1건 · 「다시 시도하기」 복원 → 1건) 실패 |
| 2026-09-11 | `#748` | §14 인벤토리 **수치 변화 없음** — **프론트엔드만 바뀌었다**(`features/auth/AuthShell.test.tsx` 9 → **11건**). §14는 백엔드 pytest만 센다. 이메일 미인증 배너가 **등급 C 색**(`--cii-c-*`)을 쓰고 있었다 — `DESIGN_SYSTEM §0.2` 제약 2는 등급 색을 A~E 문자·등급 축 라벨과 함께만 쓰게 하는데 이 배너엔 둘 다 없다. `--color-warning`은 **`--cii-c-fill`의 별칭**이라 이름만 바꿔서는 값이 같아, `§2.3`이 「안내 배너」 색으로 적은 **Info** 스트라이프(`§8`)로 옮겼다. 잠그는 것은 **배너 규칙이 등급 토큰에도 그 별칭에도 닿지 않는다**는 것 — 별칭을 문자열로 막지 않으면 `--color-warning`으로 옮기는 「고친 척」이 통과한다. 돌연변이(배경을 `--color-warning`으로) 1건 실패 |
| 2026-09-11 | `#580` | §14 인벤토리 **수치 변화 없음** — **프론트엔드만 바뀌었다**(`scenario-comparison/adoptRules.test.ts` **신설 5건** · `apiProvider.test.ts` +3 · `ScenarioComparison.test.tsx` +7). §14는 백엔드 pytest만 센다. 항로 비교 결과를 **항차 계획에 반영하는 화면 경로**를 열었다 — 서버(`POST /scenarios/{id}/adopt`, `#58` · `IT-ADOPT-001~004`)는 있었는데 화면 소비처가 0곳이었다. 잠그는 것: ⑴ 계획 단계(작성 중 · 계획 확정) 항차만 고를 수 있다 ⑵ **반영 전 확인**에서 거절하면 요청이 나가지 않는다 ⑶ 반영 뒤 바뀐 값 · 재계산 필요 · 그 항차 링크를 낸다 ⑷ 서버가 보낸 재계산 **건수는 화면에 내지 않는다**(`#817` 전에는 참값이 아니다) ⑸ 입력이 바뀌어 결과가 낡으면 반영하지 않는다 ⑹ 모드를 `UPDATE_EXISTING_PLAN`으로 **명시해** 보낸다 ⑺ 상단바에서 고른 항차가 반영 가능할 때만 기본값이 된다. 돌연변이 3종(상태 필터 제거 · 확인 생략 · 낡은 결과 허용) 각 1건 실패 |
| 2026-09-11 | `#67` | **`test_benchmarks.py` 신설 4함수** · §14.3 계획분에서 삭제 · §14.5 계획분에서 `PERF-001`~`004` 삭제(대응됨) · §6에 `[#67]` 각주 · 합계 실측 갱신(121파일·1636함수·2066수집 → **122파일·1640함수·2070수집**). `§6`이 규정한 파일이 없었고 `TECH_SPEC §13.2` 「CI에 통합해 회귀를 감지한다」가 미이행이었다. ⑴ **별도 잡·의존성 없이** `test` 잡 안에서 매 PR 돈다 — 목표 대비 실측 여유가 수십 배라 도구보다 매번 도는 것이 먼저다 ⑵ 임계값은 `PRD §16.1` 값 그대로 ⑶ `PERF-001`은 워크로드가 **실제 Fixture 1**임을 정본값 30자리로 먼저 단언한다 — 값이 어긋나면 다른 계산을 재는 것이다 ⑷ `PERF-004`는 `runs=5_000`(`PRD §12.2` 기본값)을 단언한다 — 종전 체감치는 1,000회 기준이라 목표 조건을 잰 적이 없었다 ⑸ `PERF-002`는 서비스 경로를 재고 남긴 행 440개를 id로 지운다. 「캐시 시 < 2초」는 성립할 자리가 없어 재지 않는다. 돌연변이(Monte Carlo 임계값을 1 ms로) 1건 실패 (#67) |
| 2026-09-11 | `#68` | **`A11Y-001`~`004`를 `frontend/src/a11y.test.tsx`(vitest · 12건)로 덮었다** · §14.5 미대응 표에서 삭제 · `test_case_id_sync.py` 8 → **9** · §7·§14.6 각주 · 합계 실측 갱신(122파일·1640함수·2070수집 → **122파일·1641함수·2071수집**). 케이스 넷은 `§7`이 정의하는데 화면의 성질이라 파이썬에 둘 수 없었고, 케이스 ID 가드는 `tests/`만 봐서 **덮어도 영원히 「미대응」**이었다. 가드가 프론트 검사 파일(`*.test.ts*`)의 인용도 세게 했다 — 구현 파일은 세지 않는다(`#498`의 함정). 잠그는 것: ⑴ 위험도 4단계가 한글 라벨 + 코드 문자 · 등급 스케일 바의 등급별 패턴 ⑵ 첫 Tab이 본문 바로가기, 이어 사이드바 항목 차례로 · 비활성 항목은 링크가 아님 ⑶ 등급 확률 스택 바의 다섯 값이 범례 문자에 · 구간마다 보조기술 이름 · 선대 등급 분포도 척수를 글로 ⑷ 결과 화면 7종이 전부 `DisclaimerBanner`를 그리고 문구가 `PRD §6.3`과 같다. ⚠️ 이슈 본문 「색상 대비 4.5:1」은 `tokens.sync.test.ts`가 이미 재고 실제 미달(`#748` Warning 값 · `#68` 중립 계조)은 디자인 소관이라 여기서 다시 재지 않는다. `axe-core`는 넣지 않았다 (#68) |
| 2026-09-11 | `#771` | §14 인벤토리 **수치 변화 없음** — **프론트엔드만 바뀌었다**(`layout/AppShell.test.tsx` +1건). §14는 백엔드 pytest만 센다. 상단바 알림 버튼이 `onClick` 없는 살아 있는 버튼이라 시연에서 누르면 아무 일도 없었고 `aria-label` 「읽지 않음 없음」이 셀 것이 없는 상태를 「없다」로 말했다 — 알림 체계(`DESIGN_SYSTEM §16` 항목 10 · PO)가 정해질 때까지 `disabled` + 「준비 중」으로 두고, 그 상태를 검사로 잠갔다(#771 ⑽ 부분 · 나머지 네 항목은 PO·디자이너 판정 대기) |
| 2026-09-11 | `#833` | `test_annual_simulation_read_db.py` 28 → **32** · 합계 실측 갱신(122파일·1641함수·2071수집 → **122파일·1645함수·2075수집**). `reproduce`가 `TECH_SPEC §5.4` 1항의 셋째 조건(`model_version`)을 보지 않아 **NumPy 업그레이드 뒤의 결과 차이가 500(계산 결함)으로 보고**될 상태였다. 잠그는 것 넷: ⑴ 환경이 달라도 결과가 같으면 200 + `MODEL_VERSION_DIFFERS`(응답의 `model_version`은 저장값) ⑵ 환경도 결과도 다르면 **409 `MODEL_VERSION_MISMATCH`** + 달라진 필드 `details` ⑶ 같은 환경에서 결과가 다르면 여전히 500 — 409로 눌러 감추지 않는다 ⑷ 비교는 여섯 필드 전부, 저장값이 비면 전부 다른 것으로. 환경 차이는 서비스의 `_model_version`을 갈아 끼워 만든다 — DB의 `calculation_run`은 immutable이라 저장값을 바꾸는 쪽으로는 만들 수 없다 (#833) |
| 2026-09-11 | `#969` | `test_hashing.py` 22 → **26** · 합계 실측 갱신(1645함수·2075수집 → **1649함수·2079수집**). `TECH_SPEC §5.1.1`의 「UUID 배열은 문자열 정렬」이 구현에 없었다. 잠그는 것 넷: ⑴ `uuid.UUID` 배열은 넣은 순서와 무관하게 같은 canonical ⑵ UUID 모양 문자열 배열은 `TypeError`(원소 하나라도 UUID 모양이 아니면 보통 배열로 순서 유지) ⑶ UUID 하나는 그 문자열과 같은 canonical ⑷ 객체 배열은 순서 유지 · 빈 배열은 빈 배열. 저장된 해시가 바뀌지 않는다는 것은 기존 `UT-HASH-001`·기능③ 필드별 검사가 그대로 통과하는 것으로 확인한다 (#969) |
| 2026-09-11 | `#967` | `test_annual_simulation.py` 50 → **53** · 합계 실측 갱신(1649함수·2079수집 → **1652함수·2084수집**). `TECH_SPEC §2.3.1` [ORACLE-S-1]의 「`plan_value <= 0`은 거부」가 엔진에 없었다 — 폭 0 표본으로 조용히 받아 그 항차가 매 반복 0으로 고정됐다. 잠그는 것 셋: ⑴ 결정론 경로가 거리 0·연료 0·음수 거리를 **어느 항차인지 밝히며** 거부 ⑵ Monte Carlo 경로도 같은 가드(두 경로가 다른 입력을 받으면 안 된다) ⑶ 폭 0 처리(`_sample_band`)는 남는다 — 계획값은 양수인데 뒤집힌 파라미터로 폭이 0이 된 항차는 p10=p90=결정론 값. 실제 서비스에서는 API `gt=0`·DB CHECK·`#812` 제외가 앞에서 막으므로 이 가드는 엔진을 직접 부르는 경로의 계약이다 (#967) |
| 2026-09-11 | `#808` | §4.7에 **`AT-AUTH-016`**(가입 게이트) 신설 · §14 인벤토리에 `test_signup_gate.py`(9함수) 등재 · `test_auth_api.py` 16 → **18** · 합계 실측 갱신(122파일·1652함수·2084수집 → **123파일·1663함수·2095수집**). 사내 도구로 확정되어 가입을 허용 도메인 또는 초대 코드로 제한한다. 잠그는 것 넷: ⑴ **둘 중 하나만** 맞으면 된다 ⑵ 도메인은 **정확히 일치**만 — `endswith`로 비교하면 `evilbluelog.kr`·`bluelog.kr.attacker.io`가 통과한다 ⑶ 거절은 **어느 조건에서 떨어졌는지 말하지 않는 한 문구**(`PRD §6.3`과 문자 단위 대조) — 가르면 허용 도메인을 하나씩 캐낼 수 있다 ⑷ **프로덕션에서 둘 다 미설정이면 기동 거부**, 개발은 열림 — 규칙 함수만 보면 `lifespan`에서 호출을 빠뜨려도 통과해(돌연변이로 확인) **실제 앱을 기동하는 배선 검사**를 함께 둔다. 게이트는 해싱 **전에** 본다 — 거절될 요청에 Argon2 비용을 쓰면 게이트가 비용 증폭기가 된다 (#808) |
| 2026-09-11 | `#982` | §14 인벤토리에 `test_sample_vessels.py`(6함수) 등재 · `test_response_contract_db.py` 계약 표에 `/vessels/samples` 추가(함수 수 불변 · 수집 +1) · 합계 실측 갱신(123파일·1663함수·2095수집 → **124파일·1669함수·2102수집**). 「샘플 선박 선택」(`PRD §5.1` 복원)의 재료가 **데모 시드 한 곳**임을 잠근다 — 샘플과 시드가 따로 고쳐지면 「샘플로 등록한 배」와 「데모의 같은 이름 배」가 다른 계산을 낸다. 실존 선박은 샘플이 아니고(합성 IMO만), 샘플 필드는 등록 요청 필드에서 신원(IMO·선명)을 뺀 전부다 — 등록 스키마가 필드를 늘리면 여기서 드러난다. 라우트 등록 순서도 본다: `/vessels/{vessel_id}`보다 뒤면 `samples`가 UUID 검증에서 422가 된다 (#982) |
| 2026-09-11 | `#891` | `test_data_export_db.py` 21 → **24** · 합계 실측 갱신(1669함수·2102수집 → **1672함수·2105수집**) · §8.1 `AC-F1-005` 매핑에 화면 배선 검사 추가 · `IT-EXPORT-008`에 한 건 내보내기. 기능① 결과 액션 3종(`PRD §10.5`)의 서버 쪽은 **계산 한 건 내보내기**다 — 같은 선박의 다른 계산이 섞이면 파일의 첫 행이 방금 본 결과라는 보장이 없고, 경로의 선박과 계산의 선박이 다르면 404, 다른 `type`과 함께면 **조용히 무시하지 않고** 422. 화면 쪽(프론트엔드 검사 · §14는 백엔드만 센다)은 `VoyageCiiActions.test.tsx`가 **버튼이 실제로 서버를 부르는가**를 본다 — 계획 저장이 `create` 뒤 `PLANNED` 전환에 `INCLUDE_AS_PLAN`(기본)·`EXCLUDE`(끔)를 싣는지 · 필수값 없이 서버를 부르지 않는지 · 실패를 성공처럼 보이지 않는지 · 입력이 바뀐 뒤 막히는지 (#891) |
| 2026-09-11 | `#772` | `test_fleet_summary.py` 45 → **49** · `test_response_contract_db.py` 선대 요약 계약에 `meta.next_cursor`·`has_more` · 합계 실측 갱신(1672함수·2105수집 → **1676함수·2109수집**). 결정 3-⑤ 「`vessels[]`만 자른다」를 잠근다 — ⑴ **`summary`는 페이지가 아니라 선대 전체**(3척 중 2척 페이지에서도 `total` 3) ⑵ 두 페이지를 합치면 겹치지도 빠지지도 않는다(같은 `as_of`·커서) ⑶ 정렬 규칙(트리거 → 나쁜 등급 → 이름 · 무등급은 뒤 · 동률은 id)이 **서버에** 있다 — 화면의 `sortVessels`와 그 검사 5건은 지웠다(페이지로 자르면 화면이 전체를 정렬할 수 없다) ⑷ 깨진 커서·**다른 정렬의 커서**·모르는 `sort`·`limit=0`은 422. 프론트엔드(§14 밖)는 `FleetDashboard.test.tsx`가 정렬을 바꾸면 첫 페이지부터 다시 묻고, 다음 페이지를 같은 정렬·첫 페이지의 `as_of`로 물어 **뒤에 붙이는가**를 본다 (#772) |
| 2026-09-11 | `#817` | §14 인벤토리에 `test_voyage_attribution_db.py`(4함수) 등재 · `test_data_export_db.py` 24 → **23**(전제 단언 1건 삭제) · 합계 실측 갱신(124파일·1676함수·2109수집 → **125파일·1679함수·2112수집**). 결정 2-③ 「항차 컨텍스트가 있는 요청만 귀속, 기존 NULL 행은 포기」를 잠근다 — 종전에는 계산 이력을 만드는 자리가 모두 `voyage_id`를 NULL로 넣어 **항차 단위 무효화가 항상 0행**이었고(무효화 검사는 `voyage_id`를 SQL로 직접 넣어 통과해 왔다) `#313` 삭제 가드도 죽어 있었다. 이제 **실제 계산 서비스를 거쳐** 귀속되는지, 계획 변경이 그 항차 계산만 표시하는지, 삭제가 409인지 본다. ⚠️ `IT-EXPORT-002`의 전제 단언(「`voyage_id`는 전부 NULL」)은 그 검사 자신이 적어 둔 대로 **전제가 바뀌어 걷고 판단을 다시 적었다** — 귀속된 계산도 「그 항차 조건의 가정 계산」이지 정본의 CII(연간 집계)가 아니므로 항차 표에 CII 열을 두지 않는 판단은 유지된다 (#817) |
| 2026-09-12 | `#827` | §14 인벤토리에 `test_db_backup_script.py`(20함수) · `test_migration_guard_backup_db.py`(3함수) 등재 · `test_migration_guard.py` 12 → **18** · 합계 실측 갱신(125파일·1679함수·2112수집 → **127파일·1708함수·2158수집**). 되돌릴 수 없는 downgrade의 해제에 **24시간 안의 백업 기록**을 요구한다(2026-09-11 결정 2-⑤). 스크립트의 판단은 대역으로, 실제 `pg_dump`·`pg_restore`는 CI docker 잡에서 본다 — 로컬에서는 개발 DB로 백업·리허설을 실제로 돌려 테이블 21개·행 2333개·트리거 9개 일치를 확인했다 (#827) |
| 2026-09-12 | `#900` | §14 인벤토리에 `test_validation_messages.py`(12함수) · `test_validation_messages_api_db.py`(6함수) 등재 · 합계 실측 갱신(127파일·1708함수·2158수집 → **129파일·1726함수·2191수집**). 가드는 **표를 보지 않고 OpenAPI를 본다** — 라벨 표만 검사하면 새 요청 필드가 표에 없을 때 아무것도 걸리지 않는다. 종전 표가 17항목에 머문 채 요청 필드 96개 중 84개를 빠뜨린 것이 그 결과였다 (#900) |
| 2026-09-12 | `#999` | §14 인벤토리에 `test_error_message_language.py`(3함수) · `test_calc_errors.py`(8함수) 등재 · `test_scenario_compare_api.py` 35 → **36** · 합계 실측 갱신(129파일·1726함수·2191수집 → **131파일·1738함수·2203수집**). 서비스 오류 문구 31곳의 영문(필드명 원문 · 계산 엔진 예외)을 걷어내고 **다시 들어오지 않게 `raise` 문을 읽는 검사**를 두었다. 선박 용량 축이 비어 기준선을 고르지 못하는 경우의 409 → 422 정정을 API 수준에서 잠갔다 (#999) |
| 2026-09-12 | `#906` | §3.4 `IT-CSV-008`(출항·도착 예정 시각 선택 컬럼) 추가 · `test_voyage_import_db.py` 23 → **28** · 합계 실측 갱신(131파일·1738함수·2203수집 → **131파일·1743함수·2208수집**). 종전에는 CSV로 가져온 항차가 늘 시각이 비어 진행 중 누적에 0으로 기여했다. **시간대 없는 값을 추측하지 않는다**(한국 시각이 9시간 어긋난다) · 옛 양식이 그대로 통과한다 · 빈 출항 시각 수를 검증 단계에서 센다를 잠갔다 (#906) |
| 2026-09-12 | `#902` | `test_account_self_service_db.py` 18 → **19** · 합계 실측 갱신(131파일·1743함수·2208수집 → **131파일·1744함수·2209수집**). 자격 증명 오류(로그인 실패 · 현재 비밀번호 오입력)가 세션 문제와 **다른 코드**(`INVALID_CREDENTIALS`)로 오는지, 세션 없음은 여전히 `UNAUTHORIZED`인지를 잠갔다 — 종전에는 봉투가 같아 화면이 세션을 한 번 더 조회해 갈랐다(`#878`) (#902) |
| 2026-09-12 | `#906` 후속 | `test_voyage_import_db.py` 28 → **29** · 합계 실측 갱신(131파일·1744함수·2209수집 → **131파일·1745함수·2210수집**). 이슈 완료 기준 「CSV로 만든 진행 중 항차가 화면 경로와 같은 누적 기여를 낸다」를 **시각 저장이 아니라 시계의 결과로** 잠갔다 — PR #1001은 시각이 UTC로 저장되는 것까지만 보았다(최종보고서 점검에서 드러난 빈틈). 출항 시각을 비운 행은 여전히 0임도 함께 본다 (#906) |
| 2026-09-12 | `#760` | §14 인벤토리에 `test_sample_ports.py`(8함수) 등재 · `test_response_contract_db.py` 계약 표에 `/ports/samples` · `/ports/great-circle` · 합계 실측 갱신(131파일·1745함수·2210수집 → **132파일·1753함수·2223수집**). 값이 원본(NGA World Port Index)에서 온 그대로인지 몇 곳을 도·분 표기로 고정했다 — 좌표는 한 번 들어가면 틀려도 드러나지 않는다 (#760) |
| 2026-09-12 | `#904` | §3.6 `IT-WX-004`(보정한 계산이 근거를 남긴다) 추가 · `test_scenario_compare_db.py` 2 → **5** · 합계 실측 갱신(132파일·1753함수·2223수집 → **132파일·1756함수·2226수집**). 기능②가 기상 스냅샷으로 보정해도 `calculation_run.weather_snapshot_id`가 늘 NULL이었다 — 같은 요청의 시나리오 3행에는 스냅샷이 붙는데 계산 이력만 비었다. 보정·`NONE`·fallback 세 갈래를 **실제 DB 행으로** 본다: 보정하면 이력과 시나리오 3행이 **같은 스냅샷**을 가리키고 인자가 결과에 남으며, 보정하지 않으면 캐시가 있어도 가리키지 않는다(쓰지 않은 기상을 근거로 적지 않는다). 수정 전 코드로 되돌리면 첫 케이스가 `None == UUID(...)`로 실패함을 확인했다 (#904) |
| 2026-09-12 | `#989` | **v1.13 — §3.11 「요청 캐시」 신설**(`IT-CACHE-001`~`004`) · §14 인벤토리에 `test_request_cache_db.py`(5함수) 등재 · 합계 실측 갱신(132파일·1756함수·2226수집 → **133파일·1761함수·2231수집**). 선대 요약이 선박마다 `compute_ytd_cii`를 최대 네 번 부르면서 **그때마다 규정연도·기준선·등급 경계·선박을 다시 읽고 있었다**(데모 선대 5척 실측: 요청당 212쿼리 → **129쿼리** · 176ms → **110ms**). 케이스 순서가 곧 규율이다 — `IT-CACHE-002`(캐시 켠 실행과 끈 실행의 응답이 같다)가 없으면 나머지는 「빨라졌는데 답이 달라졌다」를 잡지 못한다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#989) |
| 2026-09-12 | `#767` | §4.10 「기상 스냅샷 조회 API」 신설(`AT-WX-001`~`007`) · §14 인벤토리에 `test_weather_api_db.py`(7함수) 등재 · 합계 실측 갱신(133파일·1761함수·2231수집 → **134파일·1768함수·2238수집**). `§9.1`을 열고 `§9.2`는 **열지 않기로** 판정했으므로, 「열지 않았다」도 검사 대상이다 — `AT-WX-005`가 라우트 부재를 단언해 누가 나중에 열면 거기서 멈춘다. `tests/test_api_spec_endpoints_sync.py`의 표시 문구도 「미구현」 하나에서 **「미구현」·「열지 않는다」 둘**로 넓혔다(두 문구가 각각 읽히는지도 함께 단언한다) (#767) |
| 2026-09-12 | `#766` ⑴ | §2 `UT-WX-006`(입사각 유도) 추가 · `test_weather_model.py` 18 → **23** · `test_weather_fallback_db.py` 12 → **14** · `test_distance.py` +3 · 합계 실측 갱신(134파일·1768함수·2238수집 → **134파일·1778함수·2248수집**). 부호를 거꾸로 두면 **정면 파랑이 following sea**가 되므로 「같은 방향이면 β=0」을 단언으로 고정했다. 방위각은 **가는 길과 오는 길이 서로의 반대각이 아니라는 것**(대권 항로의 성질)을 함께 잠갔다 — 평면 지도 감각으로 `+180°`를 쓰면 고위도에서 어긋난다 (#766) |
| 2026-09-12 | `#768` | §3.12 「항만명 좌표 조회」 신설(`IT-GEO-001`~`008`) · §14 인벤토리에 `test_port_geocoding_db.py`(8함수) 등재 · 합계 실측 갱신(134파일·1778함수·2248수집 → **135파일·1786함수·2256수집**). 검사가 보는 것은 좌표가 맞는가가 아니라 **사용 정책을 코드가 지키는가**다 — User-Agent를 싣는가 · 초당 1회를 강제하는가 · 같은 이름을 두 번 묻지 않는가. 「부산」이 도시로 잡히는 경우(`place:city`)를 버리는지도 함께 본다: 도시 좌표를 항만으로 저장하면 그 뒤의 거리 추정이 조용히 틀린다 (#768) |
| 2026-09-12 | `#765` | §3.4에 `IT-CSV-009`~`014`(정박 구간 CSV 적재) 추가 · §14 인벤토리에 `test_not_underway_import_db.py`(6함수) 등재 · 합계 실측 갱신(135파일·1786함수·2256수집 → **136파일·1792함수·2262수집**). 「들어가는가」보다 **규약이 지켜지는가**를 본다 — 부분 성공(한 행이 틀려도 나머지는 들어간다) · 겹침 거부(같은 연료가 두 번 세어지지 않는다) · `dry_run`이 **보지 않은 것을 봤다고 하지 않는가**(`overlap_checked: false`) (#765) |
| 2026-09-12 | `#764` | **§3.15 「위치 스냅샷·AIS 수집」 신설**(`IT-POS-001`~`008`) · §14 인벤토리에 `test_position_snapshot_db.py`(9함수) 등재 · 합계 실측 갱신(137파일·1802함수·2272수집 → **138파일·1811함수·2284수집** — 마이그레이션 040이 `IRREVERSIBLE`에 들어가 `test_migration_guard`의 파라미터 검사 3건이 함께 늘었다). ⚠️ **AIS 제공자가 없는 상태에서 무엇을 검사하는가**가 이 절의 요점이다 — 데모 선박의 IMO가 합성값이라 실제 출처를 붙일 수 없으므로, 「받은 것을 우리가 어떻게 다루는가」만 본다: 재전송 중복을 접는가(`002`) · 늦게 온 오래된 관측이 현재 위치를 뒤로 돌리지 않는가(`004`) · 위치가 안 온 선박의 마지막 위치를 지우지 않는가(`005`) · 모르는 항행 상태를 단정하지 않는가(`008` 보조). **이 넷이 틀리면 화면에서 배가 사라지거나 뒤로 간다.** 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#764) |
| 2026-09-12 | `#775` | §14 인벤토리 `test_doc_cross_refs.py` 5 → **7함수** · 합계 실측 갱신(138파일·1811함수·2284수집 → **138파일·1813함수·2286수집**). `DB_SCHEMA §4.2`·`§9.2`의 **규모 착수 조건이 지워지지 않았는지**를 본다 — 하지 않는 일은 조건이 사라지면 「언젠가」로 남고 그 언젠가는 오지 않는다. **값이 맞는지는 검사하지 않는다**(판단의 문제다) — 없어지는 것만 막는다. 절 신설이 아니라 함수 추가라 버전은 올리지 않는다 (#775) |
| 2026-09-13 | `#120` | **§3.17 「챗봇 가드·대화 보존」 신설**(`IT-CHAT-001`~`015`) · §14 인벤토리에 `test_llm_guard.py`(11) · `test_chat_store_db.py`(6) 등재 · 합계 실측 갱신(139파일·1818함수·2291수집 → **141파일·1835함수·2308수집**). ⚠️ **`IT-CHAT-001`이 중심이다** — `PRD §16.3.1`이 전송 화이트리스트를 MUST로 정하는데 **코드가 다른 목록을 쓰면 정본은 지켜진 것처럼 보이면서 새어 나간다.** 검사가 정본 표를 읽어 코드 상수와 대조한다. 그 대조를 가능하게 하려고 **정본 표를 한글 서술에서 필드 이름으로** 고쳤다(같은 PR). No-Compute는 **문자열 대조**로 본다 — 「수학을 했는지」는 직접 볼 수 없으므로 **결과가 어디서 왔는지**로 판정하고, 파생 수치(빼기)도 막는다. 보존은 「저장되는가」가 아니라 **「지워지는가」**를 본다 — `audit_log`는 지우지 않는 기록이라 같은 내용을 두 곳에 넣으면 삭제 요청을 만족시킬 수 없다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#120) |
| 2026-09-12 | `#763` | **§3.16 「선대 요약의 항로 좌표」 신설**(`IT-MAP-001`~`005`) · §14 인벤토리에 `test_fleet_route_db.py`(5함수) 등재 · 합계 실측 갱신(138파일·1811함수·2284수집 → **139파일·1816함수·2289수집**). 보는 것은 좌표의 정확도가 아니라 **싣는 규율**이다 — 넷이 다 있을 때만 싣는가(`002`), 없는 항로를 지어내지 않는가(`003`), 그리고 ⚠️ **선대 전체를 쿼리 한 번으로 묻는가**(`004`). 마지막 것이 없으면 지도를 붙이면서 `#989`가 줄여 놓은 쿼리 수가 조용히 되돌아간다 (#763) |
| 2026-09-12 | `#769` | **§3.14 「연도별 CII 이력의 연료축」 신설**(`IT-FUEL-001`~`006`) · §14 인벤토리에 `test_cii_history_fuel_db.py`(6함수) 등재 · 합계 실측 갱신(136파일·1792함수·2262수집 → **137파일·1798함수·2268수집**). ⚠️ **표의 중심은 `IT-FUEL-002`다** — 비중을 톤으로 내면 CF가 낮은 연료를 많이 쓴 해가 실제보다 나빠 보이는데 **두 값이 가까워 눈으로는 구분되지 않는다**(75.0% vs 77.3%). 그래서 톤 비중과 **다른 값**이 나오는지를 단언으로 고정했다. CF 스냅샷이 둘인 경우를 한 줄로 합치는지(`#863`)와, **정박 연료가 축에서 빠지지 않는지**도 함께 본다 — 분자에는 들어가 있는데 축에서 빠지면 「정박해도 연료축이 안 움직이는」 화면이 된다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#769) |
| 2026-09-12 | `#770` | `test_reports_db.py` 29 → **33** · 합계 실측 갱신(136파일·1792함수·2262수집 → **136파일·1796함수·2266수집**). 「제출 전 자체 점검」 절을 잠근다 — **새 리포트가 아니라 절**인가(`§25.1`의 「대관 제출용은 하지 않는다」와 경계가 흐려지지 않게) · **용도 고지**가 실리는가 · 대체 계산을 축으로 나누는가. 넷째는 **처음 구현이 틀렸다는 기록**이다: 「선박 제원」 행을 두었는데 제원이 비면 리포트 생성이 먼저 422로 막혀 **늘 「확인」만 찍히는 죽은 칸**이었고, 검사가 그것을 드러냈다 — 행을 빼고 **막힌다는 사실**을 단언으로 바꿨다 (#770) |
| 2026-09-13 | `#121` | **§3.18 「챗봇 도구·오케스트레이션」 신설**(`IT-CHAT-016`~`033`) · §14 인벤토리에 `test_chat_tools.py`(8) · `test_chat_api_db.py`(10) · `test_llm_provider.py`(6) 등재 · 합계 실측 갱신(141파일·1835함수·2308수집 → **144파일·1859함수·2332수집**). ⚠️ **`§3.17`과 보는 것이 다르다** — 거기는 가드 함수 자체를, 여기는 **가드가 실제 경로에 꽂혀 있는가**를 본다. 함수가 있어도 부르지 않으면 아무것도 막지 못하고, 그것이 `#121`의 가장 큰 위험이다. `IT-CHAT-027`이 그 예다: `FakeProvider`가 **모델이 실제로 받은 메시지**를 들고 있어, 선박명이 섞였는지를 추측이 아니라 관측으로 판정한다. `IT-CHAT-029`는 폐기를 「안 내보낸다」가 아니라 **「저장도 안 한다」**로 잠근다 — 남기면 다음 턴이 지어낸 값을 근거로 삼아 한 번의 오류가 대화 전체로 번진다. 외부 모델은 부르지 않는다(과금·비결정성); **못 잡는 「실제 모델이 도구를 제대로 고르는가」는 릴리스 게이트의 일**로 남긴다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#121) |
| 2026-09-13 | `#121` | 프론트엔드 챗봇 오버레이 — `AssistantOverlay.test.tsx`(10) 신설. §14 인벤토리는 **백엔드 pytest 파일만** 세므로 합계는 바뀌지 않는다(`§14.6`). 검증 범위는 **모양이 아니라 `UIFLOW 2-7`이 이미 규정한 것**이다 — 화면 규격이 미확정이라 색·굵기를 고정하면 확정이 왔을 때 검사가 방해가 된다. 잠근 것 넷: ⑴ 버튼에서부터 **실험임을 밝히는가**(열어 본 뒤에야 알면 답이 이상할 때 제품 전체를 의심한다) ⑵ 답마다 **면책이 보이는가** ⑶ ⚠️ **버린 답이 답과 다르게 보이는가**(`API_SPEC §15.2` — 같은 모양이면 「답을 받았다」로 읽힌다) ⑷ ⚠️ **호출이 실패해도 던지지 않는가**(`PRD §16.2` 격리는 서버만의 이야기가 아니다 — 던지면 화면 단위 에러 경계가 잡아 대시보드가 오류 화면이 된다). 설정 부재(503)는 일반 실패와 나눠 **입력을 닫는다** — 다시 눌러도 소용없는 상태에서 계속 누르게 두지 않는다 (#121) |
| 2026-09-13 | `#123` | **§3.19 「챗봇 용어 풀이 ↔ 정본」 신설**(`IT-CHAT-040`~`047`) · §14 인벤토리에 `test_chat_explain.py`(8) 등재 · 합계 실측 갱신(144파일·1859함수·2332수집 → **145파일·1867함수·2340수집**). 풀이는 **제품이 사용자에게 하는 말**이라, 정본에 없는 말을 만들면 화면과 챗봇이 같은 것을 다르게 말한다 — 그리고 그 차이는 화면을 깨뜨리지 않아 발견되지 않는다. ⚠️ **`IT-CHAT-046`이 실질이다**: 풀이에 `Reg 28.7` 같은 수를 적으면 모델이 인용하는 순간 수학 가드가 「도구 응답에 없는 수치」로 보고 **답변을 통째로 폐기**하고, 그 실패는 「챗봇이 가끔 답을 안 준다」로 나타나 원인을 찾기 어렵다. 가드를 푸는 대신 풀이에서 숫자를 뺐고, **가드와 같은 함수(`extract_numbers`)로** 검사한다 — 따로 정규식을 쓰면 둘이 갈린다. `IT-CHAT-042`는 반대 방향이다: `PRD §3.3.7`이 「운항 제한·억류·거래 금지 조항은 확인 범위에 존재하지 않는다」로 **과장을 금지**하는데, 챗봇이 「운항이 제한됩니다」라고 하면 그 조항을 한 곳에서 깬다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#123) |
| 2026-09-13 | `#834` | **§3.20 「두 규정 표의 선종 집합」 신설**(`IT-REG-001`~`004`) · §14 인벤토리에 `test_regulation_ship_type_sync_db.py`(4) 등재 · 합계 실측 갱신(145파일·1867함수·2340수집 → **146파일·1871함수·2344수집**). ⚠️ **값을 채우는 것이 아니라 빈 것을 붙잡는 검사다** — `RO_RO_PASSENGER_HSC`의 등급 경계를 채우려면 `MEPC.354(78)`에 HSC 행이 없는 것이 「Ro-ro passenger 행이 HSC를 포함해서」인지 「등급 대상이 아니라서」인지 **원문 해석**이 필요하고, 그것은 `AGENTS §2.1`상 팀원 확인 사항이다. 확인 전까지 값을 지어내지 않는다 — **지어낸 등급 경계는 틀렸다는 사실이 화면에 드러나지 않는다.** 그래서 목록과 **정확히 같을 때만** 통과시킨다: 새 누락이 생겨도 실패하고, 채워진 뒤 목록을 안 지워도 실패한다(낡은 목록은 거짓말이다 — `#594`·`#591` 가드와 같은 방식). `IT-REG-004`는 이슈가 물은 「500인가 `rating: null`인가 조용한 빈 값인가」에 대한 **실측 답**을 고정한다: `PARAMETER_ERROR`(409)이고 문구에 선종 이름이 들어간다. 셋 중 **조용한 `null`이 가장 나쁘다** — 화면이 「등급 없음」으로 그려 값이 없는 것처럼 보이고, `#653`이 총톤수 누락에서 겪은 것과 같은 모양이다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#834) |
| 2026-09-13 | `#827` | **§3.21 「만료 행 정리 스크립트」 신설**(`IT-PURGE-001`~`007`) · §14 인벤토리에 `test_purge_expired_script.py`(7) 등재 · 합계 실측 갱신(146파일·1871함수·2344수집 → **147파일·1878함수·2351수집**). ⚠️ **`IT-PURGE-001`이 중심이다** — 조건을 빠뜨린 `DELETE FROM user_session`은 **전원 로그아웃**이고, 코드 리뷰로 놓치기 쉬운 한 줄이다. DB를 붙여 「지워졌다」를 보는 대신 **어떤 SQL이 나가는지**를 본다: DB 검사로는 「무엇을 지우려 했는지」가 안 보이고, 이 스크립트는 아무도 보고 있지 않을 때(호스트 cron) 돈다. `IT-PURGE-002`는 **dry-run이 거짓말하지 않는 것**을 잠근다 — 「3건입니다」를 보고 실행했더니 300건이 지워지면 다음부터 아무도 dry-run을 쓰지 않는다. `IT-PURGE-004`는 **구현 중 실제로 겪은 결함**이다: 마이그레이션이 덜 적용된 판에서 `chat_session`이 없어 앞의 두 표까지 함께 멈췄고, 배포 순서상 코드가 먼저 가고 마이그레이션이 뒤따르는 순간이 있어 그 틈에서도 세션 정리는 돌아야 한다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#827) |
| 2026-09-13 | `#756` | `test_annual_simulation.py` 53 → **55함수** · 합계 실측 갱신(147파일·1878함수·2351수집 → **147파일·1880함수·2356수집**). ⚠️ **종전 검사가 틀린 것을 단언하고 있었다** — 「확정 실적이 섞이면 **그 혼합비만큼만** 움직인다」였는데, 결정하는 것은 혼합비가 아니라 **두 구간의 배출 강도 차이**다. 강도가 같으면 확정 거리가 0이든 200,000 nm이든 변화가 **정확히 0**이다(4개 혼합비를 파라미터라이즈해 고정). 대수적으로도 `C/Cd = R/Rd`이면 `CII(f)`에서 `f`가 약분된다. 반대 방향(강도가 벌어지면 움직이고, **방향이 뜻을 갖는다**)도 함께 박았다 — 「거리 행은 언제나 무의미하다」가 아니다. 함께 `PRD §12.6` 다섯 변수와 실제 지렛대의 **일대일 대응 가드**를 넣었다: 정본이 든 변수와 구현이 도는 지렛대가 갈리면 표의 한 행이 영영 비고 화면에서 「효과 없음」과 구분되지 않는다(`#630` 속도·`#756` 거리가 둘 다 그 모양이었다). 아직 비어 있는 `연료 CF`는 **사유와 함께 목록에 적어** 대조한다 — 구현되는 날 검사가 깨져 목록을 지우게 한다 (#756) |
| 2026-09-13 | `#756` | 프론트엔드 — `AnnualSimulation.test.tsx`에 검사 1건 추가(79함수). §14 인벤토리는 **백엔드 pytest만** 세므로 합계는 바뀌지 않는다(`§14.6`). ⚠️ **화면을 실제로 띄워 보고서야 드러난 결함이다** — 잔여 계획 항차가 0건이면 지렛대가 움직일 대상이 없어 **여섯 행이 전부 같은 값**이 되는데(실측 `19.789` × 6), 그때도 화면은 **거리 행 설명만** 띄웠다. 그러면 **나머지 행은 의미가 있는 것처럼 읽힌다** — `#630`(속도)·`#756`(거리)과 같은 「계산하지 못한 것과 효과가 0인 것이 구분되지 않는」 형태다. 응답에 `NO_REMAINING_VOYAGES`가 **이미 실려 있었다**: 화면이 아는 사실을 그 자리에서 말하지 않았을 뿐이라 서버는 건드리지 않았다 (#756) |
| 2026-09-13 | `#120` | §3.18에 `IT-CHAT-048`·`049` 추가 · `test_chat_tools.py` 8 → **10함수** · 합계 실측 갱신(147파일·1880함수·2356수집 → **147파일·1882함수·2358수집**). ⚠️ **오늘 올린 코드에서 화이트리스트가 오류 경로로 뚫려 있었다** — `run_tool`이 도메인 오류 문구를 **원문 그대로** 봉투에 담았고, `NotFoundError("선박을 찾을 수 없습니다: <UUID>")`의 **`vessel_id`가 외부 모델로 나갔다**(실행으로 확인). `PRD §16.3.1`이 전송 금지로 둔 값이다. **어느 문구가 안전한지 목록으로 관리하는 방식은 성립하지 않는다** — 새 오류가 생길 때마다 검토가 필요하고, 빠뜨리면 조용히 새며 **전송은 되돌릴 수 없다.** 그래서 **종류별 고정 문구**로 바꿨다(봉투의 「우리가 만든 상수만 담는다」가 오류 칸에도 선다). 검사는 두 겹이다 — `048`이 변환 함수를, `049`가 **`except` 절이 그 함수를 실제로 쓰는지**를 본다(`#121`에서 반복해 겪은 「구현은 있고 부르는 곳이 없는」 형태를 막는다). 돌연변이(옛 코드로 되돌리기)로 `049`가 잡는 것을 확인했다 (#120) |
| 2026-09-13 | `#120` | §3.17에 `IT-CHAT-050`~`052` 추가 · `test_llm_guard.py` 11 → **14함수** · 합계 실측 갱신(147파일·1882함수·2358수집 → **147파일·1885함수·2361수집**). ⚠️ **수학 검증이 정상 응답을 막고 있었다** — 도구는 `attained_cii`를 **6자리**로 내려주고 화면은 **3자리**로 보이는데(`SERIALIZATION_DIGITS` vs `DESIGN_SYSTEM §4.1` 🔒), 모델이 화면과 같게 `4.982`라고 쓰면 **폐기됐다.** 값이 틀린 것이 아니라 **표기가 다른** 것이다. **면책이 「이 답변은 화면의 계산 결과를 풀어 쓴 것입니다」인데 화면과 같은 자릿수로 말할 수 없으면 그 면책이 거짓이 된다.** `IT-CHAT-008`이 이미 「막을 것은 표기가 아니라 **출처**」를 세웠으나 구현은 **끝자리 0만** 다루고 반올림은 다루지 않아, 같은 성질의 표기 차이 중 한쪽만 허용하고 있었다. ⚠️ **넓히는 것은 같은 값의 다른 표기뿐이다** — `IT-CHAT-051`이 파생(차)·지어낸 값·사용자 입력이 여전히 막히는지 함께 잠근다. `IT-CHAT-052`는 **화면 자릿수가 늘면 다시 폐기가 시작되는 것**을 막는다: 화면 쪽 정본(`frontend/src/display/format.ts`)을 읽어 대조하며, 값을 옮겨 적지 않는다. 돌연변이 2종(반올림 제거·화면 자릿수 4로 상향) 전부 검출 (#120) |
| 2026-09-13 | `#121` | §3.18에 `IT-CHAT-053`~`056` 추가 · `test_llm_provider.py` 6 → **9함수** · `test_chat_api_db.py` 10 → **11함수** · 합계 실측 갱신(147파일·1885함수·2361수집 → **147파일·1889함수·2365수집**). ⚠️ **도구 왕복이 벤더 규격을 따르지 않고 있었다** — Anthropic Messages API는 모델의 `tool_use` 블록을 **그대로 되돌려 보내고** 같은 `tool_use_id`를 단 `tool_result`로 답하기를 요구하는데, 구현은 도구 결과를 **평범한 `user` 문장**으로 보냈다. 오류가 나지는 않지만 모델이 **자기가 도구를 불렀다는 것을 모른 채** 데이터만 보고, 같은 도구를 다시 부를 수 있다(비용 폭주의 실제 경로 — `PRD §16.1` 가드 2). ⚠️ **키가 없어 실제 호출로는 확인할 수 없는 종류의 결함**이라, 「요청 본문이 규격과 같은가」를 대신 잠근다. 검사를 **두 층**으로 둔 이유는 한 층만으로는 부족하기 때문이다 — `053`(공급자가 받은 대로 보내는가)만 있으면 옛 동작도 통과한다(공급자는 받은 대로 보낸다). `056`이 **누가 그 모양을 만드는가**를 본다. 돌연변이 3종(id 버리기·블록 합치기·옛 동작 복귀) 전부 검출 (#121) |
| 2026-09-13 | `#121` | §3.18에 `IT-CHAT-057`~`060` 추가 · `test_llm_provider.py` 9 → **10함수** · `test_chat_api_db.py` 11 → **14함수** · 합계 실측 갱신(147파일·1889함수·2365수집 → **147파일·1893함수·2369수집**). ⚠️ **`stop_reason`을 아예 보지 않고 있었다.** 벤더 문서가 `max_tokens`를 *"Response is truncated"* 로 규정하는데, 구현은 **잘린 텍스트를 완성된 답으로** 내보냈다 — 문장 중간에서 끊긴 설명은 **뜻이 뒤집힐 수 있다**(「등급은 C가 아니라」에서 끊기면). ⚠️ **더 나쁜 것은 도구 쪽이다** — 잘린 `tool_use` 블록은 **인자까지 잘려** 있을 수 있어 그대로 돌리면 엉뚱한 값으로 계산하고, **그 결과는 수학 검증을 통과한다**(도구가 실제로 낸 값이므로). 가드가 원리적으로 못 잡는 자리라 `IT-CHAT-059`가 **도구를 부르기 전에** 막는다. 벤더 문서의 권고(`max_tokens`를 올리거나 이어 받기)는 **둘 다 쓰지 않았다** — 출력 상한은 `PRD §16.1` 가드 1이고, 이어 받기는 왕복을 늘려 가드 2와 부딪힌다. 판정을 **서비스에 둔 이유**는 모델을 바꿔도 정책이 따라가지 않게 하기 위해서다(`Q4` 교체 용이성) — 공급자는 값을 옮기기만 한다(`IT-CHAT-057`). 돌연변이 2종 전부 검출 (#121) |
| 2026-09-13 | `#121` | §3.18에 `IT-CHAT-061` 추가 · `test_chat_api_db.py` 14 → **15함수** · 합계 실측 갱신(147파일·1893함수·2369수집 → **147파일·1894함수·2370수집**). ⚠️ **4번째 질문부터 이력 창이 답변으로 시작하고 있었다.** `list_messages(limit=6)`이 **최근 6건**을 주는데 대화가 `U A U A …`로 쌓이므로, 7건이 되는 순간 창이 `A U A U A U`가 된다(실측으로 확인). 그 창은 **질문이 잘려 나간 답변**으로 대화를 열고, 모델은 무엇에 대한 답인지 모른 채 그것을 맥락으로 삼는다 — **수치를 인용하는 제품에서 특히 나쁘다.** 벤더 문서는 *「models are trained to operate on alternating user and assistant conversational turns」*까지 적고 **거절 여부는 명시하지 않는다** — 거절하지 않더라도 위 이유로 고칠 값어치가 있다고 판단했다. `limit`을 홀수로 두는 대안은 **폐기가 섞이면 다시 어긋난다**(버려진 답은 저장되지 않아 `U U A U`처럼 쌓이는 자리가 생긴다) — 창의 **앞을 보고 자르는** 쪽이 그런 경우까지 덮는다. 검사는 **네 번을 실제로 주고받아** 그 지점을 지난다 (#121) |
| 2026-09-13 | `#829` | 프론트엔드 — `ScenarioComparison.test.tsx`에 검사 1건 추가(119). §14 인벤토리는 **백엔드 pytest만** 세므로 합계는 바뀌지 않는다(`§14.6`). ⚠️ **화면을 띄워 보고서야 드러났다** — 항로 비교에 처음 들어오면(선박 미선택) 규제연도 자리에 **「등록된 규제연도가 없습니다」**가 떴는데 **사실이 아니다**: 연도는 8개 등재돼 있고 선박을 고르지 않았을 뿐이다(새 브라우저로 5회 전부 재현). 화면에 처음 들어온 사용자는 그것을 **데이터가 없다**로 읽고 선박을 고를 생각을 못 한다. `#630`(속도)·`#756`(거리)과 같은 **「값이 없다」와 「아직 물어보지 않았다」가 구분되지 않는** 형태다. **보고서 화면이 이미 `vesselId &&`로 같은 구분을 하고 있어** 그 형태에 맞췄다 — 새 규격을 만들지 않았다. 다른 세 화면(기능①·③·CSV)은 선박이 미리 채워지거나 필드를 가려 이 상태에 닿지 않는다(실측 확인) (#829) |
| 2026-09-13 | `#773` | **§3.22 「연료 CF 표 ↔ 시드」 신설**(`IT-FUEL-007`~`010`) · §14 인벤토리에 `test_fuel_table_sync_db.py`(4) 등재 · 합계 실측 갱신(147파일·1894함수·2370수집 → **148파일·1898함수·2374수집**). ⚠️ **CF는 CII의 분자를 만드는 값**이라 0.1만 달라도 등급이 바뀌는데 **화면은 그대로 뜬다** — 코드만 맞고 값이 갈리는 경우를 `IT-FUEL-009`가 잡는다. `IT-FUEL-007`이 **표를 읽을 수 있는지부터** 보는 이유는 형식이 바뀌면 나머지가 **0건을 대조하고 통과**하기 때문이다(`#634`에서 실제로 그럴 뻔했다). 알려진 공백 둘 중 **`OTHER`만 여기서 본다**(정본 ↔ 시드) — `Ethane`은 **정본 ↔ 원문**이라 기계가 읽을 형태가 아니어서 `PRD §3.4.2` 각주가 대신 적는다. **값은 정하지 않았다**: `Ethane`을 넣을지는 `AGENTS §2.1`상 팀원 확인을 거친 판정이고, 지어낸 규제값은 **틀렸다는 사실이 화면에 드러나지 않는다**(`#834`와 같은 판단). 돌연변이 4종(정본 행 삭제·CF 변조·예외 목록 비우기·사유를 TODO로) 전부 검출. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#773) |
| 2026-09-13 | `#834` | **§3.20 `IT-REG-004`를 다시 쓰고 `IT-REG-005`를 신설** · `test_regulation_ship_type_sync_db.py` 4 → **5함수** · 합계 실측 갱신(148파일·1898함수·2374수집 → **148파일·1899함수·2375수집**). ⚠️ **종전 `IT-REG-004`는 결함을 정답으로 고정하고 있었다** — 「HSC 선박은 409로 거부된다」를 단언했는데, `PRD §3.4.4` 각주(`#126` · 원문 대조 확인 sky01170851)는 **`RO_RO_PASSENGER` 행을 적용한다**로 이미 정해 두었다. 계산 계층에 상속 표(`RATING_BOUNDARY_FALLBACK`)와 단위 검사까지 있었는데, **호출부 셋이 선종으로 걸러 조회**해 폴백 대상 행이 목록에 없었고 **폴백이 실행될 기회조차 없었다**(「구현은 있고 제대로 부르는 곳이 없다」). `select_rating_boundary` docstring이 *「걸러지지 않은 전체 목록이어도 된다」*로 적은 이유가 그것이다. `IT-REG-005`가 **소스를 훑는 이유**는 동작 검사로는 잡히지 않기 때문이다 — 걸러도 HSC가 아닌 선박은 전부 정상이라, **데모 선대에 HSC가 없으면 아무도 모른다.** 돌연변이 2종(호출부를 옛 동작으로·상속 표 비우기) 전부 검출 (#834) |
| 2026-09-13 | `#955` | **§3.23 「파일별 커버리지 하한」 신설**(`IT-COV-001`~`009`) · §14 인벤토리에 `test_coverage_floor_script.py`(9) 등재 · 합계 실측 갱신(148파일·1899함수·2375수집 → **149파일·1908함수·2384수집**). ⚠️ **CI 게이트(`--cov-fail-under=90`)는 전체 합계만 본다** — 5,900문장 중 69문장이 비어도 합계는 1pp도 움직이지 않아, 합계가 96%인 채로 파일 하나가 60%대로 남을 수 있다. 이 저장소에서 실제로 두 번 오래 남았다(`#871` `auth.py` 41~58% · **라우트 본문 미실행 결함** · `#911` `reports.py` 61% · `exports.py` 65%). `#911`이 「A를 먼저 하고 B는 따로 판단」으로 남긴 **B안**이다. **두 기준 중 하나**(비율 80% **또는** 미커버 5문장 이하)를 쓰는데, 비율만 걸면 **8문장 중 1문장(87.5%)에 CI가 걸리고** 그런 실패가 쌓이면 **하한 자체를 낮추라는 압력**이 생겨 게이트가 무력해진다 — 그렇다고 크기로 대상에서 빼면 **그 크기 아래가 통째로 사각지대**가 되므로, 작은 파일은 절대 문장 수로 잡는다. 2026-09-13 실측(157파일·합계 96.5%)에서 분포에 **77.3% → 83.3%** 빈 구간이 있어 하한 80이 어느 무리도 가르지 않는다. 걸린 셋은 사유·이슈 번호와 함께 예외 목록에 올렸다 — ⚠️ 그중 `auth/dependencies.py`는 **`require_session`의 세션 조회 본문이 검사에서 한 번도 실행되지 않는다**(픽스처가 의존성 자체를 대체). CI가 이미 만드는 `coverage.xml`을 읽어 **검사를 다시 돌리지 않는다.** 돌연변이 3종(「또는」을 「그리고」로 · 작은 파일 면제 제거 · `src/` 정규화 제거) 전부 검출. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다. ⚠️ **정정(같은 날 `#120` 처리 중)** — 경로 정규화가 `src/`만 떼고 있었는데, Cobertura의 `filename`은 `<source>` 루트 기준이라 `--cov` 주는 방식에 따라 **세 형태**(`src/cii_platform/…` · `cii_platform/…` · `…`)로 나온다. 한 형태에서만 맞고 나머지에서는 **「없는 경로」와 「목록에 없는 위반」이 동시에** 떴다. 접두사 둘을 떼어 **패키지 루트 기준**으로 통일하고 `IT-COV-008`을 세 형태 파라미터라이즈로 바꿨다 (#955) |
| 2026-09-13 | `#120` | **§3.24 「챗봇 도구의 실제 실행 경로」 신설**(`IT-CHATDB-001`~`009`) · §14 인벤토리에 `test_chat_tools_db.py`(9) 등재 · 합계 실측 갱신(149파일·1908함수·2384수집 → **150파일·1917함수·2395수집**). ⚠️ **`#955`의 게이트가 붙자마자 드러난 공백이다** — `services/chat_tools.py` **66.2%**, 미커버 27문장이 **도구 4종의 본문 전체**였다. 오케스트레이션 검사는 `FakeProvider`로 모델만 대역화하고 **도구를 부르지 않았고**, 단위 검사는 `_publishable`을 **손으로 만든 dict**로만 봤다. 그래서 **화이트리스트가 진짜 계산 응답에 대해 도는 것을 아무도 보지 않았다** — 응답 필드가 늘거나 이름이 바뀌면 `_PUBLISH_MAP`이 놓치고 `filter_outbound`가 마지막 방어선이 되는데, 그 조합이 한 번도 실행된 적이 없었다(`PRD §16.3.1` 전송 금지: 선박명·IMO·`vessel_id`). 대역을 쓰지 않고 `session`만 진짜로 두어 도구 → 서비스 → 계산 → 저장소를 한 줄로 지나간다. **66.2% → 99%**(남은 1문장은 `_error_text`의 방어 폴백)이라 `#955`의 `KNOWN_BELOW_FLOOR`에서 이 파일을 **뺐다** — 낡은 예외는 거짓말이므로 게이트가 그것을 요구한다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올리고 README 문서 구조 표를 함께 갱신했다 (#120) |
| 2026-09-13 | `#523` | `test_depcheck.py` 13 → **17함수**(`TestMain` 신설) · 합계 실측 갱신(150파일·1917함수·2395수집 → **150파일·1921함수·2399수집**). ⚠️ **`#955` 게이트가 드러낸 세 번째(마지막) 공백이다** — `depcheck.py` **77.3%**, 미커버 구간이 `main()` 전체였다. 순수 함수 셋은 검사돼 있었지만 **판정을 조립하는 자리**가 비어 있었다. 이 모듈은 `Dockerfile`의 `CMD`가 uvicorn **앞에** 두는 물건이라 **종료 코드가 곧 컨테이너가 뜨느냐 마느냐**다. 잠근 것은 **검사가 불가능한 것과 검사가 실패한 것을 가르는 것** — `pyproject.toml`이 없으면(마운트 누락) **0**을 내어 기동을 막지 않고(막으면 그 환경에서 앱이 영영 안 뜬다), 없는 패키지는 **1**을 낸다(`#60`의 실제 실패 모드). 문구가 「이미지 재빌드」라는 **옳은 해법**을 가리키는지도 본다 — `pip install`은 다음 `up`에서 사라진다. **77.3% → 98%**(남은 1문장은 `if __name__ == "__main__"` 가드)이라 `#955`의 `KNOWN_BELOW_FLOOR`에서 이 파일을 **뺐다**. 예외 목록이 **3건 → 1건**이 됐다. **절을 신설하지 않았다** — `§14.2`가 이미 이 파일을 `§5`에 대응시켜 두었고 `AGENTS §4.3`상 행 갱신은 버전을 올리지 않는다 (#523) |
| 2026-09-13 | `#433` | `test_annual_simulation.py` 55 → **63함수** · 합계 실측 갱신(150파일·1921함수·2399수집 → **150파일·1929함수·2410수집**). **`PRD §12.3.1` 「필요 감축량(목표 역산)」을 구현했다** — 정본은 2026-09-10(v4.5)에 신설됐으나 **코드로 구현된 곳이 없었다.** ⚠️ **가장 중요한 검사는 「줄이라는 만큼 줄이면 목표 경계에 정확히 정착하는가」**다(A~D 파라미터라이즈) — 산식을 옮겨 적기만 하면 부호나 항 하나가 틀려도 **그럴듯한 양**이 나오고 화면은 그대로 뜬다. 되짚어 계산해 경계와 맞춰야 드러난다. 목표 경계는 **등급 판정이 쓴 그 경계**(`NEXT_WORSE_BOUNDARY_KEY`)를 재사용한다 — 두 벌이 되면 「경계를 넘었다는데 등급은 그대로」가 생긴다. **재현성 보장은 시그니처로 한다**: `backsolve_required_cut()`이 `projection`만 받고 `required_cii`·`d_vector`를 받지 않아 **데이터를 다시 읽을 수단 자체가 없다**(`§12.3.1` 재현성 각주 — 「확률은 78%인데 감축량은 다른 전제」를 구조적으로 막는다). ⚠️ **잔여 계획 없음(`None`)과 줄일 것 없음(`0`)을 구분한다** — 같게 두면 화면이 「이미 목표 안이다」로 말하는데 실제로는 계산할 대상이 없는 것이다. **전부 없애도 못 닿는 경우**(`achievable=False`)는 「n톤 줄이세요」가 거짓이 되므로 따로 표시한다. 프론트 6검사 추가(`AnnualSimulation.test.tsx` — §14.6상 합계 불변) (#433) |
| 2026-09-13 | `#433` | ⚠️ **결함 정정 — 필요 감축량이 API 응답에 한 번도 실리지 않았다.** `test_annual_simulation_read_db.py` 32 → **34함수** · `test_response_contract_db.py` 계약표에 `data.reduction_plan.*` 7키 등재 · 합계 실측 갱신(150파일·1929함수·2410수집 → **150파일·1931함수·2412수집**). 같은 날 PR #1054가 `reduction_plan`을 **저장 본문(`_payload`)에만** 넣고, 응답을 조립하는 `_envelope`가 **키를 골라 싣는다는 사실을 놓쳐** 블록이 실행·조회·재현 어느 응답에도 나가지 않았다. 화면 카드는 블록이 없으면 그리지 않도록 만들었으므로 **오류 없이 조용히 사라졌다.** 세 겹의 검사가 모두 통과한 이유가 각각 달랐다 — ⑴ 계산 검사는 **엔진**을 봤고 ⑵ 화면 검사는 **가짜 응답**을 봤고 ⑶ 응답 계약표는 **손으로 적은 키 집합**이라 그 블록이 없는 상태를 **정답으로** 들고 있었다. `#363` 작업 중 같은 `_envelope`에 `feedback` 블록을 넣다가 `KeyError`로 드러났다. **실행·조회·재현 세 경로 응답을 DB에서 실제로 받아 블록을 단언**하는 검사를 넣어 그 층위를 잠갔고, 돌연변이(옮겨 싣기 제거 = 머지된 상태)가 2건으로 검출된다 (#433) |
| 2026-09-13 | `#363` | `test_annual_simulation.py` 63 → **69함수** · `test_annual_simulation_read_db.py` 34 → **39함수** · `test_hashing.py` 26 → **27함수** · `test_response_contract_db.py` 계약표에 `data.feedback.*` 6키 · 합계 실측 갱신(150파일·1931함수·2412수집 → **150파일·1943함수·2427수집**). **`PRD §12.2.1` 「실적 보정계수」를 구현했다.** 가장 무거운 검사는 둘이다 — ⑴ **켜고 돌린 실행이 재현되는가**(계수를 저장하지 않고 같은 스냅샷에서 다시 내는 설계가 성립하는지) ⑵ **끈 실행의 `input_hash`가 종전과 같은가**(바뀌면 저장된 실행 전부가 재현 불가가 되고, 해시는 UPDATE 트리거가 막아 고칠 수도 없다) (#363) |
| 2026-09-13 | `#513` | §14.2 인벤토리에 `test_data_quality.py`(12함수) · `test_data_quality_db.py`(13함수) 등재 · 합계 실측 갱신(150파일·1943함수·2427수집 → **152파일·1968함수·2457수집**). **데이터 점검(`PRD §17.4`)의 판정과 서비스를 잠갔다.** 가장 무거운 검사는 셋이다 — ⑴ **CII 영향**을 서비스 밖에서 같은 함수로 두 번 구해 차와 대조(식을 옮겨 적으면 부호가 뒤집혀도 그럴듯한 값이 나온다) ⑵ **판정하지 못한 이상치가 0건과 섞이지 않는가** ⑶ **완결성이 항차 수가 아니라 CO₂ 비율인가**(240t 실측 + 360t 대체 → 0.4, 항차 수로는 0.5) (#513) |
| 2026-09-13 | `#513` | §14.2 인벤토리에 `test_fleet_reduction.py`(12함수) · `test_fleet_reduction_db.py`(8함수) 등재 · 합계 실측 갱신(152파일·1968함수·2457수집 → **154파일·1988함수·2483수집**). **함대 감축 계획(`PRD §12.3.2`)의 계산·저장을 잠갔다.** 가장 무거운 검사는 셋이다 — ⑴ **감속률 0%면 전 선박 등급이 그대로**(`#513` 완료 기준) ⑵ **조정 전 값이 연간 등급 관리의 결정론 예상과 같은가**(두 화면이 갈리면 어느 쪽이 맞는지부터 따진다) ⑶ **저장본이 저장 시점 결과 그대로인가** — 항차를 더해 지금 계산값이 달라진 뒤에도 (#513) |
| 2026-09-13 | `#513` | `test_fleet_reduction.py` 12 → **13함수** · 합계 실측 갱신(154파일·1988함수·2483수집 → **154파일·1989함수·2484수집**). **`#513` 완료 기준 「`2-10`의 연료 계산이 `2-2 항로 비교`와 같은 값을 낸다」를 검사로 잠갔다** — 계획 연료가 cubic model로 원래 속력에서 나온 값이면, 감속 후 연료가 같은 모델을 새 속력에 넣은 값과 같아야 한다 (#513) |
| 2026-09-14 | `#1070` | `test_fleet_reduction_db.py` 8 → **11함수** · 합계 실측 갱신(154파일·1989함수·2484수집 → **154파일·1992함수·2487수집**). **함대 감축 계획 서버의 요청 검증 틈 4종을 잠갔다.** 가장 무거운 검사는 둘이다 — ⑴ **고칠 수 있는 입력이 500이 아니라 422로 끝나는가**를 **실제 HTTP로** 본다. 공백만 있는 계획 이름은 종전에 검증을 통과한 뒤 선대 전체 계산을 한 번 돌리고 DB 제약에 걸려 500이 났는데, 스키마만 단위로 보면 「422가 난다」가 아니라 「예외가 난다」까지만 보이고 **어느 칸의 오류로 나가는지**가 빠진다. 그래서 `field`·`field_label`까지 단언한다 ⑵ **연료 없는 계획 항차가 조용히 빠지지 않는가** — 같은 선박·같은 연도를 연간 등급 관리(`run_annual_simulation`)로도 돌려 **두 응답의 항차 수가 같은지**를 대조한다. 한쪽만 보면 「그럴듯한 수」가 나와 통과한다. ⑵의 단가 키 정규화는 화면과 같은 경로(요청 모델 → `_payload` → 서비스)를 태워야 검사가 성립한다 — 서비스를 직접 부르면 정규화가 일어나는 자리를 건너뛴다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1070) |
| 2026-09-14 | `#1084` | §14 인벤토리 함수 수 갱신 — `test_annual_simulation_api_db.py`(24 → **27**) · 합계 실측 갱신(1992함수·2487수집 → **1995함수·2490수집**). **거리가 없는 선박에서 기능③이 500이 아니라 422를 내는지**를 세 층위로 잠갔다. 서비스 단위 검사만으로는 모자라다 — 서비스가 도메인 오류를 던져도 `api/error_handlers.py`가 그것을 422로 옮기지 않으면 **사용자는 여전히 500을 본다.** 그래서 **실제 HTTP로 상태 코드·오류 코드·문구**를 받아 본다(⚠️ 원문은 여기서 AGENTS의 **존재하지 않는 절**(3의 하위 3번째)을 근거로 인용했다 — 이 문장에 대응하는 절이 AGENTS에 없어 `#1324`에서 인용만 지웠다. 추측으로 다른 절을 대신 넣지 않는다). 세 번째는 **배선 검사**다 — 실행(`§6.1`)과 재현(`§6.4`) 두 호출부가 같은 변환 함수를 지나는지 소스에서 확인한다. 재현 경로는 저장된 스냅샷에서 거리가 0이 될 수 없어(실행 단계에서 이미 막힌다) 실데이터로는 지나갈 수 없는 갈래라, 값이 아니라 **배선**을 보는 것이 이 층위에서 할 수 있는 유일한 검사다. HTTP 검사는 전용 선박을 만들고 `finally`에서 지운다 — `TestClient`는 실제로 커밋하므로 남기면 다음 실행의 선대 집계가 이 행을 본다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1084) |
| 2026-09-14 | `#1085` | `test_cii_current_db.py` 36 → **38함수** · 합계 실측 갱신(1995함수·2490수집 → **1997함수·2492수집**). ⚠️ **이 파일의 검사 8건이 고친 결함을 정답으로 들고 있었다** — 픽스처 `_make_voyage`의 기본 `annual_inclusion_policy`가 **`EXCLUDE`** 였고, 진행분 검사들이 그 항차에 대해 `contribution is not None`을 **「사전 조건: 진행분이 누적에 들어가야 한다」**는 주석과 함께 단언했다. 기본값을 `INCLUDE_AS_PLAN`으로 바꾸고(`_add_actuals`가 확정 시 `INCLUDE_AS_ACTUAL`로 덮으므로 확정분 경로는 영향 없음) `EXCLUDE`는 **명시적으로 넘기는 전용 검사 2건**을 세웠다. 첫 검사는 「진행분이 줄었다」가 아니라 **「확정분만 있는 상태와 값이 같다」**를 본다 — 종전 결함(항해 중에는 늘다가 완료되는 순간 빠져 누적 CII가 한 번에 뛰는 것)은 그래야 잡힌다. 둘째 검사는 선박 **두 척**을 같은 조건으로 세우고 정책만 달리해, `INCLUDE_AS_PLAN`에서 경고가 **나오는 것**까지 함께 본다 — 한쪽만 보면 「경고 자체가 죽었다」와 구분되지 않는다. 정책을 나중에 `UPDATE`로 바꾸지 않는 것은 raw SQL이 ORM identity map을 갱신하지 않아 `find_in_progress`가 **바꾸기 전 객체**를 돌려주기 때문이다(실측으로 확인). ⚠️ **같은 성질의 검사가 `test_voyage_import_db.py`에도 하나 더 있었다** — `test_imported_in_progress_voyage_now_counts_toward_the_running_total`(`#906` 완료 기준)이 CSV로 만든 `DRAFT + EXCLUDE` 항차의 **상태만** `IN_PROGRESS`로 옮기고 「누적에 기여한다」를 단언했다. 실제 전환 API는 `INCLUDE_AS_PLAN`을 지정해야 연간에 반영하므로(`API_SPEC §3.5`) 정책 전환을 함께 넣었고, 회차마다 `DRAFT`로 되돌리는 줄에도 `EXCLUDE`를 함께 넣었다 — `PRD §8.1.2`상 `DRAFT`는 `EXCLUDE only`라 두 번째 회차에서 `chk_status_policy`를 어긴다(실측: `CheckViolationError`). 함수 수는 변하지 않는다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1085) |
| 2026-09-15 | `#672` | §4.7에 `AT-AUTH-017`(역할 2종) 신설 · §14.2 인벤토리에 `test_roles_db.py`(13함수) 등재 · 합계 실측 갱신(154파일·1997함수·2492수집 → **155파일·2010함수·2508수집**). `test_signup_gate.py`의 lifespan 검사에 `INITIAL_OFFICE_EMAILS`를 채웠다 — 같은 자리에서 최초 사무직 검사가 함께 돌기 때문이다. 행 추가라 버전은 올리지 않는다 (#672) |
| 2026-09-15 | `#1050` | §4.7에 `AT-AUTH-018`(세션 검증 한 벌) 신설 · §14.2 인벤토리에 `test_session_resolution_db.py`(3함수) 등재 · 합계 실측 갱신(155파일·2010함수·2508수집 → **156파일·2013함수·2511수집**). `#955`가 예외 목록에 남긴 `auth/dependencies.py`(65%)를 뺐다 — 두 벌이던 세션 검증을 `resolve_session` 한 벌로 합쳐 본문이 매 요청 실행된다. `tests/fakes.py`의 `install_fake_auth`가 그 모듈의 `get_sessionmaker`도 함께 갈아끼운다. 행 추가라 버전은 올리지 않는다 (#1050) |
| 2026-09-15 | `#1086` | §14.2 인벤토리에 `test_request_bounds.py`(6함수) 등재 · `test_voyage_import_db.py` 29 → **30** · `test_not_underway_import_db.py` 6 → **7** · 합계 실측 갱신(156파일·2013함수·2511수집 → **157파일·2021함수·2538수집**). 항차·시나리오·정박 요청과 CSV 파서가 DB `NUMERIC`·CHECK가 거부할 값을 통과시켜 500이 나던 6가지(`#1086` ①~⑥)를 422로 — 경계는 `api/schemas/bounds.py` 한 곳에서 ORM 정밀도로 계산한다. 행 추가라 버전은 올리지 않는다 (#1086) |
| 2026-09-15 | `#1078` | §3.10에 `IT-EXPORT-009`(행 수 상한 없음) 신설 · `test_data_export_db.py` 23 → **26** · 합계 실측 갱신(157파일·2021함수·2538수집 → **157파일·2024함수·2541수집**). ⚠️ **정본이 이미 정해 둔 것을 코드가 어기고 있었다** — `API_SPEC §8.1`은 「행 수 상한을 두지 않는다」를 세 종류 전부에 대해 규정하는데, 계산 이력만 페이지네이션 함수(`list_runs`)를 빌려 써 `limit + 1` = **10,001행에서 조용히 잘렸다.** 상한을 두기로 한 결정이 아니라 함수 재사용의 부산물이었고, 같은 자리의 주석이 약속한 「잘린 사실을 열로 알린다」는 구현된 적이 없다(`#59` 최초 커밋이 규정과 코드를 **한 번에** 넣으면서 갈렸다). 검사가 **10,002건**을 넣는 이유는 종전 코드가 10,001건까지는 전부 돌려주었기 때문이다 — 한 건 적게 넣으면 고치기 전에도 통과하는 검사가 된다. 연도 필터는 상한으로 자른 **뒤** 파이썬에서 걸려, 최신 10,001건이 전부 2026년이면 `year=2025`가 DB에 자료가 있는데도 **0건**을 냈다 — 쿼리로 내리고 경계를 **반열림**(다음 해 첫 순간 제외)으로 박았다. 닫힌 구간이면 정각의 계산이 두 해 파일 **양쪽에** 들어가 합친 건수가 하나 많아진다. `AGENTS §4.3`상 케이스 행 추가·인벤토리 갱신이라 버전은 올리지 않는다 (#1078) |
| 2026-09-15 | `#1077` | `test_voyage_attribution_db.py` 4 → **6** · 합계 실측 갱신(2024함수·2541수집 → **2026함수·2543수집**). **채택 응답의 `invalidated_calculation_runs`가 참값인지를 실제 서비스 경로로 처음 본다.** 종전 무효화 검사(`test_scenario_adopt_db.py::test_existing_calculations_are_marked_for_recalculation`)는 `voyage_id`를 **raw SQL로 직접 넣어** 계산 이력을 만들었기 때문에 `#817` 이전에도 통과했고 — `§14`의 `#817` 행이 그 사실을 이미 적어 두었다 — 「실제 기능① 계산이 채택으로 무효화되는가」는 아무도 보지 않았다. 화면이 이 수를 숨겨 온 근거가 「늘 0이라 참값이 아니다」였으므로, 표시를 여는 `#1077`은 그 전제가 사라졌음을 실행으로 확인해야 한다. 함께 **`0`의 두 뜻**(`API_SPEC §5.2` — 「계산 이력이 없다」와 「이미 전부 표시돼 있다」)을 재채택·빈 항차 두 경로로 고정했다 — 화면이 `0`을 「무효화된 계산이 없습니다」로 적으면 **옛 계산이 아직 유효하다**로 읽히기 때문이다. 프론트엔드 검사(`adoptRules.test.ts` +4 · `apiProvider.test.ts` +2)는 **§14가 백엔드 pytest만 세므로** 합계에 들어가지 않는다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1077) |
| 2026-09-16 | `#1058` | §14.2 인벤토리 7파일 갱신 · 합계 실측 갱신(159파일·2053함수·2529수집 → **159파일·2082함수·2561수집**). `test_db_backup_script.py` 20 → **37**(백업·복구를 `cubrid unloaddb`/`loaddb`로 옮기며 **CUBRID의 DB 이름 17자 한도** · tar 완전성 · `-p` 누락 · 적재 순서 · vol-path를 새로 고정) · `test_calc_run_needs_recalc_db.py` 6 → **11**(🔴 **불변성 가드가 nullable 열의 NULL↔값 변경을 놓치고 있었다** — 조건이 NULL을 내면 `IF NOT (NULL)`이 거부하지 않는다. `051`이 막았고 양방향 + 정상 플립 대칭까지 본다) · `test_compose_env_wiring.py` 8 → **11**(healthcheck가 `CUBRID_PASSWORD`를 넘기는가 · 셸을 거치는가 · DB 이름이 박혀 있지 않은가) · `test_orm_schema_sync.py` 2 → **5**(반영 표기 차이를 뺄 때 **범위가 좁은지**를 함께 본다 — `sa.text` 인덱스 목록이 실제와 정확히 같은가 · `sa.desc`로 적은 것이 빠지지 않았는가 · 길이 없는 문자열 동일시가 `VARCHAR(50)`까지 넓어지지 않았는가) · `test_weather_simulation_migrations.py` 12 → **14**(`[S-6]`의 FK를 빼고 UNIQUE + 트리거로 옮겼으므로 **FK가 하던 일을 양쪽에서** 본다 — 자식 쪽 없는 스냅샷 거부 · 부모 쪽은 `trg_snapshot_no_delete`가 이미 더 강하게 막는다) · `test_voyage_migrations.py` 11 → **12**(부모 쪽 `fuel_type` 삭제 검사를 **자식 쪽으로 돌렸다** — 지우지 않고 §7.1이 지키려던 것을 보게 했다) · `test_zz_roundtrip.py` 6 → **4**(리비전 통합으로 전제가 사라진 검사 2건을 지웠다 — 커버리지 상실은 `DB_SCHEMA §8.1.0`에 명시). `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1058) |
| 2026-09-16 | `#1058` | §14.2 `test_db_backup_script.py` 37 → **40** · 합계 실측 갱신(159파일·2082함수·2561수집 → **159파일·2085함수·2564수집**). 🔴 **CI docker 잡이 리허설 직후 죽던 사유를 커널이 적어 주었다** — cgroup OOM이 운영 `cub_server`를 죽이고 있었다. standalone 유틸리티가 자기 버퍼 풀을 따로 잡는 것을 막는 검사(`test_standalone_utilities_cap_their_own_buffers`)를 더했다. ⚠️ **바로 위 행의 수치가 그 세션의 마지막 두 커밋보다 먼저 측정됐다** — `c2ef8fb`(리허설 `createdb`의 실패 사유를 싣는다)·`4244d62`(리허설 DB를 전용 폴더로)가 각각 검사를 하나씩 더해, 갱신했다고 적은 뒤에 표가 다시 어긋났다. `test_testplan_sync` 2건이 그것을 잡고 있었다. 🔒 **인벤토리는 그 PR의 마지막 커밋 뒤에 잰다** — 검사를 더하는 커밋이 뒤에 오면 먼저 잰 값은 반드시 낡는다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1058) |
| 2026-09-17 | `#1090` | §14.2 `test_reports_db.py` 33 → **37** · 합계 실측 갱신(160파일·2106함수·2585수집 → **160파일·2110함수·2589수집**). 리포트가 **집계 범위와 맞지 않는 값을 한 문서에 함께 적지 않는지** 박는다. ⑴ 「연간 누적에서 차지한 비중」의 분모는 `INCLUDE_AS_ACTUAL` 항차만 더한 값인데 분자는 아무 항차나 썼다 — `EXCLUDE` 항차에도 수가 찍혀 같은 문서의 「연간 집계 반영: 연간 반영 안 함」과 어긋났고 **100%를 넘을 수도** 있었다. 사유를 같은 칸에 붙인다(`— (연간 반영 안 함)`) — 리포트는 잘라서 인용되므로 위 행과 떨어져 읽히면 「—」가 「값이 아직 안 나왔다」로 보인다. 🔒 **문구는 새로 짓지 않고** 기존 `INCLUSION_POLICY_LABELS`를 옮겨 적는다. ⚠️ **이슈의 전제 하나는 성립하지 않아 구현하지 않았다** — 「`regulation_year`가 다른 항차」는 없다. 리포트가 `year`를 그 항차의 규제연도로 잡고, 트리거 `048`이 `EXCLUDE OR regulation_year IS NOT NULL`을 강제하기 때문이다. 닿지 않는 조건을 넣지 않고 **그 사실을 검사로** 박았다(2025년 항차에 비중이 정상적으로 찍힌다). ⑵ 정박 절이 연도 전체를 세어 누적(YTD, `started_at <= as_of`)과 어긋났다 — `list_periods_for_year`는 이미 `as_of`를 받고 있었고 리포트 경로만 안 넘기고 있었다. ⑵-b 빈 행의 자릿수를 손으로 적어 (`"0.00"`) 같은 표의 다른 행과 달랐다 — `_display`를 지나게 했다(`DESIGN_SYSTEM §4.2` 거리 0자리·연료 1자리). 🔴 **돌연변이 검사에서 EXCLUDE 검사가 옛 코드로도 통과해 가짜였음이 드러났다** — 집계가 비어 분모가 0이라 종전 가드에 걸렸던 것이다. 집계에 드는 항차를 먼저 만들도록 고쳐 3건 모두 옛 코드에서 실패함을 확인했다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1090) |
| 2026-09-17 | `#1089` | §14.2 `test_auth_api.py` 18 → **21** · 합계 실측 갱신(160파일·2103함수·2582수집 → **160파일·2106함수·2585수집**). `last_login_at`이 **실제 로그인 경로**에서 채워지는지 박는다. 종전에는 이 대입이 개발용 스텁(`auth_dev.py`)에만 있어 운영에서 `GET /auth/me`의 값이 **늘 `null`**이었다 — `git grep "last_login_at =" -- src`가 한 줄만 냈다. 셋을 본다: ⑴ 로그인 시 **응답과 DB 둘 다** 채워지는가(응답만 보면 커밋되지 않은 값도 통과한다) ⑵ **가입도** 채우는가 — 가입은 즉시 로그인 상태가 되므로(`PRD §7.10`) 빼면 **로그인해 있는 사용자가 「로그인한 적 없음」으로** 보인다(`null`은 「한 번도 없었다」로 읽힌다) ⑶ 「마지막」이 **갱신되는가**(두 번째 로그인이 시각을 앞으로 옮기는가). 대입은 라우트마다 흩지 않고 `_issue_session` 한 곳에 둔다 — 세션이 생기는 순간이 곧 로그인한 순간이고, 새 로그인 경로를 더해도 이 함수를 지나므로 빠뜨릴 수 없다. 돌연변이 검사: 대입 한 줄을 빼면 3건 모두 실패한다(실측). `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1089) |
| 2026-09-17 | `#1088` | §14.2 `test_demo_seed_counts.py` 5 → **7** · 합계 실측 갱신(160파일·2101함수·2580수집 → **160파일·2103함수·2582수집**). `clear_demo`가 **지울 수 없는 것을 지우려 들지 않는 것**과 **남긴 항차의 연료를 지키는 것**을 박는다. ⑴ 데모 선박에 위치 스냅샷이 하나 있으면 종전 구현은 `DELETE FROM vessel`에서 FK 위반을 냈고, 호출자가 트랜잭션을 쥐고 있어 **한 척 때문에 전체가 롤백**됐다 — docstring이 약속한 「막히는 것은 억지로 지우지 않고 남긴 수를 돌려준다」와 정반대다. 실측 재현: `IntegrityError: … restricted by the foreign key 'fk_vessel_position_snapshot_vessel'`. ⑵ 계산 이력으로 남긴 항차의 `voyage_fuel_use`가 보존되는가 — 종전에는 전량을 먼저 지워 그 항차가 **연료 0 항차**가 됐다(`assert 0 == 1`로 재현). 🔒 **기존 단언이 결함을 잠그고 있었다** — 「자식 테이블은 참조 제약이 없어 언제나 전량」에서 `voyage_fuel_use`를 빼고 「남긴 항차가 없을 때만 전량」으로 고쳤다. RESTRICT 참조 목록은 손으로 적지 않고 `Base.metadata`에서 끌어낸다 — 이 결함 자체가 손으로 적은 목록이 실제 FK(`vessel`은 **여섯**)와 갈린 것이라, 같은 방식으로 고치면 또 갈린다. 부수 확인: **CUBRID가 FK·트리거 위반을 `sqlalchemy.exc.IntegrityError`로 올린다.** `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1088) |
| 2026-09-18 | `#1072` | §14.2 `test_scenario_adopt_db.py` 17 → **24** · 합계 실측 갱신(160파일·2124함수·2603수집 → **160파일·2131함수·2610수집**). 시나리오 채택이 **계획 연료도 바꾸는지** 박는다. ⑴ 단일 유종은 시나리오 총량 그대로 · 출처 `MODEL_ESTIMATE` ⑵ **★ 두 채택 모드가 같은 계획 연료를 남긴다**(이슈의 완료 기준 — `UPDATE_EXISTING_PLAN`과 `CREATE_NEW_VOYAGE`의 연료 행을 통째로 대조한다) ⑶ 유종 여럿이면 기존 비중대로 안분하고 **합이 시나리오 총량과 정확히 같다** ⑷ 나누어떨어지지 않는 3유종에서도 합이 총량과 같고 **어느 행도 0이 아니다** ⑸ 비중 없는 행(`planned_fuel_ton IS NULL`)은 건드리지 않는다 — `chk_fuel_positive`(046)가 `NULL 아니면 > 0`을 요구해 0으로 덮으면 **채택 자체가 500**이 된다 ⑹ 연료 행이 아예 없는 항차(CSV로 항차만 올린 경우 · `#1095` ⑵)에도 한 행이 생긴다. ⑺ **연료 종류를 알 수 없으면**(원본 항차에 연료 행이 없고 선박 기본 연료도 없다) **채택이 막히지 않고 연료만 건너뛰며** `updated_fields`에서 그 필드가 빠진다 — 처음에 오류로 두었다가 **`#1077`의 무효화 건수 검사 2건이 전체 시험에서 깨져** 고쳤다(그 검사들은 연료와 무관한데 픽스처가 바로 그 상태였다). 🔴 **돌연변이 5종 전부 확인** — 연료 갱신 제거(종전 상태 재현 · 4건 실패) · 잔차 보정 제거 · 비중 0 행도 덮기 · 출처 미기록 · 연료 행 없는 항차 건너뛰기. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1072) |
| 2026-09-18 | `#989` | §14.2 `test_fleet_summary.py` 49 → **52** · `test_request_cache_db.py` 5 → **6** · 합계 실측 갱신(main 반영 뒤 기준 163파일·2197함수·2687수집 → **163파일·2201함수·2691수집**) · §3.11에 `IT-CACHE-005` 추가. 선대 요약의 검증이 두 축으로 늘었다 — ⑴ **파생 표시 2종이 선대 전체 기준**(`limit=1`로 첫 페이지를 잘라도 페이지 밖의 급한 배를 가리킨다 · GT NULL만 센다) ⑵ **배치 프리페치가 캐시 키를 빗나가지 않는다**(집계 단건 5종·진행분 3종 0회 · 배치가 조합별로 정확히 나간다 — 하나라도 빗나가면 N+1로 되돌아간다). 200척 재실측(4,624쿼리·16.4s → 32쿼리·0.57s, 값 동일)을 계약 검사의 근거로 남긴다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#989) |
| 2026-09-18 | `#1095` | §14.2 `test_ytd_cii_service_db.py` 21 → **25** · `test_data_quality_db.py` 13 → **15** · 합계 실측 갱신(160파일·2118함수·2597수집 → **160파일·2124함수·2603수집**). `#1095` ⑵ 잔여분 — **연료 기록이 한 행도 없는 실적 확정 항차**를 서버가 드러내는지 박는다. 집계 루프가 거리는 조건 없이 더하고 연료는 행을 돌며 더하므로 행이 0개면 **분모만 커진다**. ⑴ 경고 `COMPLETED_FUEL_UNFILLED`가 난다 ⑵ 항차 단위 기록이 `fuel_type=None`으로 남아 데이터 점검이 **어느 항차인지** 가리킨다 ⑶ **★ 연료 있는 항차와 섞여도** 드러난다(결정요청 v7 §1.3의 「기준 미달 선박이 A로 표시되는」 경로) ⑷ `EXCLUDE` 항차는 경고하지 않는다 — 반영하지 않기로 한 것에 할 일을 지시하면 거짓 안내다(`#1085`가 같은 이유로 세 경고를 비웠다). 🔴 **돌연변이 4종 전부 확인** — 경고 미발행 · 항차 기록 미발행 · 두 코드를 합치기 · 정책 무시. ⚠️ **실측으로 잔여 결함 하나를 찾아 현행을 사유와 함께 잠갔다** — `completeness_ratio`가 **CO₂로 가중**하므로 CO₂가 0인 이 항차는 분자·분모 어디에도 안 보여 비율이 `1.0000`으로 남는다(「전부 실측」이라는 뜻이다). 가중치를 항차 수로 바꾸는 것은 `PRD §17.4.3` 개정이라 이번 결정(`가′`) 범위 밖이고, 그 자리를 항차 행이 대신 가리킨다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1095) |
| 2026-09-18 | `#1190` | §14.2 `test_voyage_import_db.py` 30 → **35** · `test_not_underway_import_db.py` 10 → **13** · 합계 실측 갱신(160파일·2110함수·2589수집 → **160파일·2118함수·2597수집**). CSV **저장 단계** 실패가 행 오류로 떨어지는지 박는다 — `#1087`이 정박 쪽에서 행 번호를 고칠 때 「`voyage_import.py`에는 이 결함이 없다(저장 루프가 `try/except`를 하지 않아 번호를 다시 셀 일이 없다). 다만 그 때문에 한 행이 실패하면 파일 전체가 실패하며, 별건이라 후속 이슈로 뗀다」고 적어 둔 그 후속이다. ⑴ 재현 파일(3행 중 2행 속력 `10000`)이 **500이 아니라 200 + 행 오류**이고 앞 행·뒤 행이 둘 다 남는다 ⑵ **`dry_run`과 실제 가져오기의 `errors[]`가 같다** — 종전 `dry_run`은 같은 파일에 `imported_count 3 · errors []`로 거짓 통과를 줬다 ⑶ 컬럼 길이는 **escape 뒤**로 센다(`'` 접두가 한 글자 늘린다) ⑷ 정박 `port_name` 길이·좌표 한도. ⚠️ **이슈 본문이 정박 `port_name`을 300자로 적었으나 모델은 `String(200)`이다** — 검사가 `assert limit == 200`으로 그 정정을 박았고, 한도는 본문에서 옮겨 적지 않고 `Voyage.__table__`·`NotUnderwayPeriod.__table__`에서 끌어낸다. 🔴 **새 검사 8건 전부 돌연변이로 확인했다** — 속력 한도를 `DISTANCE`로 되돌리면 2건, 행 단위 `except` 제거·길이 검사 제거·escape 전 측정·`missing_departure` 파싱분 환원·정박 길이 제거·좌표 한도 제거·정박 `except AppError`만 환원에서 각 1건이 실패한다. ⚠️ 저장 단계 실패 검사에서 **「뒤 행이 들어간다」는 단언하지 않는다** — CUBRID가 `-494`에서 트랜잭션을 통째로 되돌려 `conn` fixture의 미커밋 선박 행이 함께 사라지고 뒤 행이 FK로 실패한다(fixture의 성질이며 운영의 동작이 아니다 — 운영에서는 앞 행이 이미 커밋돼 있다). 그 사유를 검사 docstring에 적었다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1190) |
| 2026-09-18 | `#816` | `test_annual_simulation_read_db.py` 39 → **42** · `test_hashing.py` 27 → **28** · 합계 실측 갱신(160파일·2131함수·2610수집 → **160파일·2135함수·2614수집**). 고정하는 것 넷 — ⑴ **`as_of` 절단이 실제로 작동**: 절단 시점 이후 도착한 확정 실적이 스냅숏에 없고 잔여 계획은 남는다(상보 집합 — 같은 절단을 잔여에 쓰면 전멸한다), 같은 요청의 `input_hash`가 `as_of`로 갈린다 ⑵ **미명시 실행의 해시 무변경**(키 없음 — 기존 실행 전부 재현 가능) ⑶ **명시 실행의 재현이 저장된 원본 시각을 재생**(밀리초 경계값 포함) ⑷ **v1 행이 동결 빌더로 재현된다** + v2의 `fuel_types`·`parameter_sources` 4키 구조. ⚠️ 검사 SELECT에 `JSONText` 타입을 붙였다 — 생 SQL은 CUBRID에서 문자열을 돌려주어 `#1058` 이래 같은 함정이 또 나왔다 (#816) |
| 2026-09-18 | `#756` | `test_annual_simulation.py` 69 → **70** · `test_annual_simulation_read_db.py` 42 → **45** · `test_hashing.py` 28 → **29** · 합계 실측 갱신(2135함수·2614수집 → **2140함수·2619수집**). 고정하는 것 — ⑴ **대체 연료 지렛대가 opt-in**: 고른 실행에만 블록·`FUEL_CF_MASS_BASIS` 경고·`input_hash` 키가 있고 미지정은 종전 그대로(선택 키 규약의 네 번째 적용례) ⑵ **CO₂ 변화가 CF 비례·잔여 비중 가중**임을 엔진 단위로 대조(짝대칭 계산) ⑶ **고른 실행의 재현**이 저장된 선택·블록을 재생 ⑷ 모르는 연료는 422(조용히 무시하면 「고른 것처럼」거짓) ⑸ **미선택 실행의 해시 무변경**을 `_input_hash` 직접으로 잠근다 — 서비스 검사는 「고른 해시 ≠ 미고른 해시」만 보므로 **양쪽이 함께 바뀌면 통과한다**(미선택에라도 키를 넣는 돌연변이에서만 잡힌다 · `#363` 첫 판과 같은 결함 유형). ⑵(거리 지렛대)는 PR #962·#1038로 완료돼 이 이슈의 남은 범위는 ⑴뿐이었다 (#756) |
| 2026-09-17 | `#1087` | §14.2 `test_not_underway_import_db.py` 7 → **10** · 합계 실측 갱신(160파일·2098함수·2577수집 → **160파일·2101함수·2580수집**). 정박 구간 CSV의 **저장 단계 오류가 원본 행 번호로** 나가는지 박는다. 종전에는 `enumerate(parsed)`로 번호를 다시 셌는데 `parsed`에는 **파싱에 성공한 행만** 들어 있어, 앞에서 한 행이라도 떨어지면 뒤의 저장 오류가 전부 위쪽 행 번호로 보고됐다 — 사용자는 멀쩡한 줄을 들여다본다. 3행 파싱 실패 + 4행 겹침으로 종전 `[3, 3]` · 지금 `[3, 4]`(실측). `field`도 함께 본다: 종전에는 저장 오류가 종류와 무관하게 `started_at` 고정이라 **연료 문제를 시작 시각 칸에** 붙였다. ⚠️ **`_error_field`의 `details` 갈래는 CSV 경로로 닿지 않는다** — `parse_row`가 `period_type`·`consumer_type`·`fuel_type`을 `create_period`와 같은 기준으로 먼저 보기 때문이다. 닿지 않는 갈래를 검사 없이 두지 않으려고 **순수 함수 단위로** 고정했다(DB 없이 돈다). 체크리스트 4항으로 본 `voyage_import.py`에는 이 결함이 없다 — 저장 루프가 `try/except`를 하지 않아 번호를 다시 셀 일이 없다. 다만 그 때문에 한 행이 실패하면 파일 전체가 실패하며, 별건이라 후속 이슈로 뗀다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1087) |
| 2026-09-17 | `#1079` | §14.2 `test_auth_tokens.py` 23 → **24** · 합계 실측 갱신(160파일·2097함수·2576수집 → **160파일·2098함수·2577수집**). **같은 재설정 토큰으로 동시에 온 요청 둘 중 하나만 성공하는지**를 박는다. 종전 `consume_token`은 `SELECT` → 파이썬에서 `used_at is None` 확인 → 대입이라, 두 요청이 **둘 다 `used_at IS NULL`을 읽고** 통과했다 — 비밀번호가 나중 요청의 값으로 바뀐다. ⚠️ **이 검사는 `conn` fixture를 쓰지 않는다** — `conn`은 트랜잭션 하나를 열어 끝에 롤백하므로 두 요청이 **한 트랜잭션에 들어가** 경쟁 자체가 일어나지 않는다. 세션 둘이 각자 커밋해야 DB의 행 잠금이 실제로 판정한다. 돌연변이 검사: 종전 구현으로 되돌리면 **동시 요청 2건이 둘 다 성공**해 1건 실패한다(실측). CUBRID에 `RETURNING`이 없으므로(`#1058`) 조건부 `UPDATE`의 `rowcount`로 성공을 판정하고 소유자는 따로 읽는다 — `token_hash`에 유니크 인덱스가 있어 두 행을 만나지 않는다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1079) |
| 2026-09-17 | `#1076` | §14.2 `test_calculations_query_db.py` 3 → **4** · 합계 실측 갱신(160파일·2096함수·2575수집 → **160파일·2097함수·2576수집**). `GET /calculations`의 `meta.needs_recalc_total`(`API_SPEC §1.9`)이 **받은 페이지가 아니라 필터 전체**를 세는지 박는다 — 세 가지다: ⑴ `limit=1`로 한 건만 받아도 2가 나오는가(페이지를 셌다면 1이다) ⑵ 커서로 다음 페이지를 받아도 값이 같은가(페이지마다 달라지면 화면이 그 수를 「이 선박의 낡은 계산 수」로 말할 수 없다) ⑶ `type` 필터를 풀면 다른 종류의 낡은 계산이 더해지는가. 종전에는 화면이 받은 20건만 세어 **21번째 행부터 낡아 있어도 머리에 「0건」**이 나갔다. 프론트엔드는 `CalculationHistory.test.tsx`(+4)·`ReportsView.test.tsx`(+3)에 「더 보기」 실패 시 행 유지·재시도·선박 목록 실패와 「없음」 구분을 고정했다 — §14 인벤토리는 **백엔드 pytest만** 세므로 합계에는 들어가지 않는다 (#1076) |
| 2026-09-18 | `#1104` · `#1081` ⑷⑤⑥ | **v1.26 — §10을 실제 CI로 재작성 · §3.25~3.27 신설 · §14.3~14.5 갱신.** ⑴ §10이 `test.yml` 5단계·`requirements.txt`·`canonical_rng_vector.py`를 적고 있었으나 **셋 다 존재한 적이 없었다** — 실제 `ci.yml` 4잡(CUBRID 서비스 컨테이너·커버리지 게이트·PDF 폰트) + `pr-title.yml` + 주간 `audit.yml`·uv.lock·`test_rng_reproducibility.py` 기준으로 다시 썼다(#1104). ⑵ #513(데이터 점검)·#363(실적 보정계수)·#433(목표 역산)의 절이 없어 §3.25~3.27을 신설했다 — 같은 시기 #768·#989는 절이 있었다(#1081 ⑹). ⑶ §14.3 계획분 7행의 대응 이슈(#58~#66·#105)가 전부 CLOSED라 계획분이 비었다고 박히게 고치고, 이름이 바뀐 6쌍은 §14.4로 옮겼다(#1081 ⑷). ⑷ §14.5 계획분의 #443·#444(CLOSED)를 실제 잔여 #673·#756으로 재표기했다(#1081 ⑸). 절 신설·재작성이라 `AGENTS §4.3`에 따라 버전을 올린다 (#1104 · #1081) |
| 2026-09-18 | `#673` | **§3.5 IT-IMPORT 5케이스를 CSV·행 오류 계약으로 재작성** · §14.2 `test_parameter_migrations.py` 12 → **13** · `test_parameter_import_db.py` **16함수 신규 등재** · 합계 실측 갱신(160파일·2140함수·2619수집 → **161파일·2157함수·2636수집**). 고정하는 것 — ⑴ 🔴 **전부 아니면 전무**: 한 행이라도 걸리면 아무것도 들어가지 않는다(IT-IMPORT-005 · `§8.2`와 정반대). ⑵ **`dry_run`과 실제 적재가 같은 판정**(#1190 규약 재사용 — errors[] 원본 행 번호·필드·사유). ⑶ **개정 = 이행 행 보존 + 활성 전환**(`DB_SCHEMA §7.2` · 054가 전역 유니크를 활성-유니크 트리거로 교체). ⑷ `a_decimal`은 서버가 `parse_imo_scientific`으로 계산해 §9.3 불변식이 깨지지 않는다. ⑸ 연료는 제자리 갱신 + `content_hash` 재계산 — **CF를 시드와 다른 값으로 올려야** 재계산 누락 돌연변이가 잡힌다(같은 값이면 해시도 같아 검출 불가 — 실측). 🔴 **돌연변이 5종 확인** — dry_run 저장 · 원자성 게이트 제거 · 이행 전환 누락 · content_hash 미재계산 · 저장소 활성 필터 제거, 전부 대응 검사 실패. §3.5 재작성은 케이스의 의도(중복·형식·해시·롤백)를 지키고 판정 모양만 실제 계약에 맞춘 것 — 구 JSON 명세의 409·422 기대는 행 오류로 옮겨졌다. 케이스 표 재작성이라 `AGENTS §4.3`에 따라 판본을 올린다 (#673) |
| 2026-09-18 | `#966` | §14.2 `test_weather_fallback_db.py` 14 → **17** · `test_scenario_compare_db.py` 5 → **6** · `test_vessel_spec_bounds.py` 서술 보강(함수 3 그대로 · parametrized +7) · 합계 실측 갱신(**161파일·2161함수·2647수집**). 잠그는 것 — ⑴ **CB 있음/없음/범위 밖 세 경우의 경고 조합**(결정요청 v9 D-3 「가」): 없으면 `CB_ESTIMATED`, 있으면 무경고, 범위 밖이면 `CB_OUT_OF_RANGE`(실측값이라 추정 아님) ⑵ **상한은 반개구간** — 컨테이너선 [0.55, 0.75)의 0.75는 범위 밖 ⑶ **저장된 CB가 시나리오 생산 경로를 흐른다**(`vessel.block_coefficient` → `_resolve_weather` → 경고) — 컬럼이 없던 시절엔 이 경고가 나올 수 없었다 ⑷ 방형계수 입력 경계(0.001~1 — 물리 범위). `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#966) |
| 2026-09-18 | `#1246` | §14.2 `test_db_session_param_convert.py` 11 → **13** · 합계 실측 갱신(161파일·2161함수·2647수집 → **161파일·2163함수·2649수집**). 추가된 2종 — 치환 관측(`cast=`/`bool=` 카운트가 DEBUG 로그로 남는가 · 깨끗한 문장은 로그가 없는가). 함께: conftest 변환기가 **프로덕션 훅 우선 + 테스트 전용 2층**으로 통합됐다(§5 행 서술 갱신). `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1246) |
| 2026-09-18 | `#827` ⑵ | §14.2 `test_structured_logs.py` **7함수 신규 등재**(볼륨 소유자 결함 방어 검사 포함) · 합계 실측 갱신(#1246 반영 뒤 기준 161파일·2163함수·2649수집 → **162파일·2170함수·2656수집**). 고정하는 것 — ⑴ **쿼리스트링·요청 본문이 로그에 없다**(토큰·비밀번호 유출 원천 차단 — 접근 로그는 요약만) ⑵ 접근 요약의 JSON 키 약속 ⑶ **5xx 접근은 ERROR** — Starlette이 Exception 핸들러를 사용자 미들웨어 바깥(최외곽)에 두므로 미들웨어가 예외를 올리며 남긴다(없으면 본앱의 500에 접근 기록이 없다 — 실측) ⑷ 예외 기록 `exc` 스택 ⑸ uvicorn.access는 우리 것과 중복이라 WARNING으로 내린다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#827) |
| 2026-09-19 | `#1203` | §14.2 `test_login_backoff.py` **6함수(수집 10) 신규 등재** · 합계 실측 갱신(#827 반영 뒤 기준 162파일·2170함수·2656수집 → **163파일·2176함수·2666수집**). 고정하는 것 — ⑴ **곡선**(5회까지 0초·6회째 0.4초·지수·상한 6.4초 — 순수 함수로 직접) ⑵ 🔴 **시간 존재 오라클 차단**: 있는 계정(가입 API로 생성)과 없는 계정을 같은 횟수 실패시켜 매 시도의 지연이 같음을 라우트 수준에서 대조 ⑶ 성공 즉시 초기화·15분 경과 구제 ⑷ 지연이 응답 형태(코드·문구)를 바꾸지 않음. IP 한도(분 10)는 검사에서 넉넉히 올려 백오프 축만 본다(미들웨어 순서는 그대로). 돌연변이 2종(없는 계정 미카운트·지연 미적용) 검출. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1203) |
| 2026-09-19 | `#1242` | §14.2 `test_chat_tools_db.py` 9 → **12** · `test_chat_store_db.py` 6 → **7** · `test_chat_api_db.py` 15 → **17** · 합계 실측 갱신(**163파일·2182함수·2672수집**). 고정하는 것 — ⑴ **검색의 고유 일치가 세션 귀속으로 저장된다**(둘 이상은 저장하지 않는다 — 몰래 고르지 않는다) ⑵ **locked 턴(화면이 넘긴 요청)은 검색이 세션을 못 바꾼다** ⑶ **같은 턴의 이후 도구가 귀속을 즉시 쓴다** — 계산 도구가 「어느 선박인지」 오류 없이 돌았다는 것이 증거 ⑷ 응답 `vessel_resolved` 불린(**식별자 미노출** §16.3.1) ⑸ **선박 SQL 삭제에 SET NULL** — 대화는 남고 귀속만 푼다(생 SQL로 판정 — ORM identity map의 옛 속성 함정). 돌연변이는 PR 본문 참조. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1242) |
| 2026-09-19 | `#1243` | §3.18 `IT-CHAT-062`·`063` · §3.24 `IT-CHATDB-010`·`011` 신설 · §14.2 `test_chat_tools_db.py` 12 → **14** · `test_chat_api_db.py` 17 → **19** · 합계 실측 갱신(**163파일·2186함수·2676수집**). #1242 위계를 다듬는 것 넷 — ⑴ 🔴 **요청값은 세션 귀속을 바꾸지 않는다**(정정 — 요청은 그 턴에서만 이긴다. 다음 턴의 대답이 조용히 달라지면 안 된다) ⑵ `run_tool`이 `ToolOutcome(envelope, resolved_vessel_id)`를 돌려준다 — 저장 책임은 턴 루프 한 곳 ⑶ **2척은 오류 봉투**(「N척이 일치합니다. 화면에서 선박을 고른 뒤…」) — 애매한 것을 몰래 고르지 않는다 ⑷ 도구 설명 문구를 서버가 실제로 하는 말로. 프론트: `vessel_resolved=false` 답에 「선박을 먼저 골라」 안내(성질 단언 — 문구 전문 아님). 돌연변이는 PR 본문 참조. `AGENTS §4.3`상 행 갱신·케이스 신설이라 버전은 올리지 않는다 (#1243) |
| 2026-09-19 | `#1244` | §3.18 `IT-CHAT-064` 신설 · §14.2 `test_llm_guard.py` 14 → **18** · `test_chat_api_db.py` 19 → **21** · 합계 실측 갱신(**163파일·2192함수·2682수집**). 고정하는 것 — ⑴ **이전 답의 수치를 다시 쓰면 통과**(저장된 assistant 메시지는 전부 저장 시점에 검증을 통과했다 — 폐기분은 저장 안 됨) ⑵ **파생 수치는 여전히 폐기**(4.98·5.05가 있어도 0.07은 금지 — 빼기도 계산) ⑶ **user 메시지 수치는 허용하지 않는다**(사용자가 지어낸 수가 「검증된 답」이 되는 것 방지) ⑷ **날짜·시간 오탐 제거**(`2026-09-18`이 쪼개져 폐기되던 실측 결함) ⑸ `_RULES` 프롬프트 첫 줄을 이력 인용과 정합 ⑹ **user 수치가 검증을 통과하지 않는다**를 라우트 수준에서 잠금. 돌연변이는 PR 본문 참조. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1244) |
| 2026-09-19 | `#1245` | §3.18 `IT-CHAT-065` 신설 · §14.2 `test_chat_api_db.py` 21 → **23** · 합계 실측 갱신(**163파일·2194함수·2684수집**). 턴 시간 상한 45초 — **임의값이 아니라 두 정본 값(LLM 단일 30초·최악 4회 왕복 ≈ 2분)에서 나온 컷오프**다(`PRD §16.1` p95≤2초는 정상 경로 SLO이고 이것은 최악 경로 가드). `asyncio.timeout`으로 본문을 감싸고 `TimeoutError` → 폐기 문구(무엇이 일어났는지만). 검사는 모듈 기본값 패치(0.05초)+자는 공급자로 재현 — 운영 상한을 그대로 쓰면 검사가 45초를 기다린다. 돌연변이는 PR 본문 참조. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1245) |
| 2026-09-19 | `#1287` | §14.2 `test_doc_cross_refs.py` 7 → **8함수** · 합계 실측 갱신(163파일·2194함수·2684수집 → **163파일·2195함수·2685수집**). **정본 변경 이력의 커밋 열이 비어 있지 않은지**를 본다. `AGENTS §4.1`이 「squash merge로 해시가 재작성되므로 PR 번호를 적는다」로 정한 자리인데 `DESIGN_SYSTEM`에 `#___`가 **네 행** 남아 있었다(`#1266`·`#1264`·`#1265`·`#1283`). 네 번 연속으로 빈 이유는 채우는 시점이 **머지 뒤**여서다 — 그때는 PR이 닫히고 작업이 끝난 것처럼 보이고, 각 PR 본문에 「머지 후 채운다」를 적어 두었는데도 넘어갔다. 그리고 **비어 있어도 아무것도 실패하지 않았다**: 이 파일의 다른 검사는 참조가 실재하는지를 보는데 `#___`는 참조가 아니라 **빈칸**이라 걸리지 않는다(`#1052`의 죽은 토큰·`#1167`의 파싱 실패한 `outline`과 같은 유형 — 화면도 검사도 멀쩡한데 값만 없다). 날짜로 시작하는 **표 행만** 보므로 `AGENTS §7`이 PR 본문 서식을 설명하며 산문에 쓰는 `#___`는 대상이 아니다. 번호가 **맞는지**는 보지 않는다(`AGENTS §4.4`) — 사라지는 것만 막는다. 여덟 정본 전부를 훑는다(652행). 함수 추가라 버전은 올리지 않는다(`AGENTS §4.3`) (#1286) |
| 2026-09-19 | `#1291` | §14.2 `test_compose_env_wiring.py` 11 → **12함수** · 합계 실측 갱신(163파일·2195함수·2685수집 → **163파일·2196함수·2686수집**). 고정하는 것은 **본보기에 적는 것과 컨테이너에 닿는 것이 다른 일이라는 사실**이다. `INITIAL_OFFICE_EMAILS`(`#672`)가 `.env.example`·`.env.app.example`·`docs/OPERATIONS.md` 어디에도 없어 배포가 빈 값으로 떴고, 그 상태에서 새 DB는 **사무직 0명**이 된다 — 승격 API도 사무직 전용이라 화면으로는 아무도 풀 수 없다. ⚠️ **가드가 초록불인 채 비어 있었다**: `test_env_example_documents_every_variable_the_app_reads`의 정규식이 `env.get("리터럴")`만 봤고 `role_bootstrap.py`는 `env.get(ENV_NAME)`으로 **상수를 경유해** 읽는다 — 오류 문구가 같은 이름을 쓰므로 상수로 두는 편이 옳고, 그래서 이 변수는 잡히지 않았다. 같은 모듈 안의 `NAME = "ENV_VAR"`를 풀어 세게 넓혔더니 **두 번째 누락**(`ALLOW_IRREVERSIBLE_DOWNGRADE`)이 함께 드러났다(`DB_SCHEMA §8.1.2`가 「`.env`에 넣지 않는다」고 정하므로 값 없는 주석 행으로 등재). ⚠️ **본보기만 고쳤다면 배포는 그대로 고장 난 채였다**: OCI 분리 토폴로지가 쓰는 `docker-compose.prod.app.yml`의 `backend`에는 `env_file:`이 없고 `environment:` 목록만 주입되는데 그 목록에 이 키가 없어 `.env`에 채워도 앱은 빈 값을 본다 — `#508`이 `MAIL_BACKEND`에서 겪은 그 함정이고, 그때 만든 검사 둘은 `docker-compose.yml`·`docker-compose.prod.yml`만 봐서 **분리 토폴로지 파일은 어느 검사에도 걸려 있지 않았다.** 그래서 「본보기가 적는 값이 그 compose에서 실제로 쓰이는가」를 새로 고정한다 — `environment:`에 있는가가 아니라 **쓰이는가**로 판정한다(`CUBRID_HOST`는 `x-cubrid-url` 앵커, `BACKEND_IMAGE`는 `image:`에서 쓰이고 셋 다 환경변수로 들어가지 않는 것이 맞다). 돌연변이 검사: 본보기에서 그 행을 지우면 앞의 검사가, compose에서 주입 줄을 지우면 뒤의 검사가 각각 그 변수 이름을 지목하며 실패한다 (#1290) |
| 2026-09-19 | `#1240` | §14.2 `test_seed_data.py` 17 → **18함수** · 합계 실측 갱신(163파일·2196함수·2686수집 → **163파일·2197함수·2687수집**). 규제 개정 재적재가 8개 `fuel_type.source_ref`를 `MEPC.364(79)`로 복구하는지 고정했다. 부트스트랩 마이그레이션의 값만 검사하면 `seed_all()`이 낡은 출처로 되돌려도 통과하므로, 과거 문자열로 훼손한 뒤 재적재 결과를 직접 조회한다. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1240) |
| 2026-09-19 | `#1308` | §4.7 `AT-AUTH-017`을 역할 3종 기준으로 확장 — 관리자(`ADMIN`) 도입으로 계정 관리 2경로가 사무직에서 관리자로 넘어간다(`#672`의 역할 2종을 대체). 케이스에 **관리자 전용 경로**(`API_SPEC §1.2` 새 표) · **경계별로 갈리는 `FORBIDDEN_ROLE` 정본 문구** · 마지막 사무직 → **마지막 관리자**(대상 역할 무관) · `INITIAL_OFFICE_EMAILS` → **`INITIAL_ADMIN_EMAILS`**(옛 이름이 남아 있으면 기동 거부) · 마이그레이션 057(트리거를 `ADMIN` 포함 3종으로 재생성)을 추가했다. §14.2 `test_roles_db.py` 13 → **15** · `test_dev_auth.py` 7 → **8** · 합계 실측 갱신(163파일·2201함수·2691수집 → **163파일·2204함수·2697수집**) — 관리자 전용 경로 표 ↔ 소스 대조와 「계정 관리 2경로가 더는 사무직 전용이 아니다」 두 검사, 그리고 **dev-login이 관리자 스텁을 강등하지 않는다**를 더했다. TC ID는 재번호하지 않고 같은 번호에 범위를 넓혀 적는다(`AGENTS §4.1`의 취지와 같다 — 번호를 밀면 기존 참조가 어긋난다). 케이스 내용 확장이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1301) |
| 2026-09-20 | `#1310` | **변경 이력 표의 풀리지 않은 병합 조각 두 줄(`>>>>>>> origin/` · 그 다음 줄 `main`)을 지웠다** — PR `#1259`(`#1203`)가 충돌을 풀며 남긴 것으로, 표가 그 줄에서 끊겨 뒤의 행들이 문단으로 렌더됐는데 어떤 검사도 실패하지 않았다. 재발 방지로 §14.2 `test_tracked_files_are_text.py` 2 → **4함수** · 합계 실측 갱신(main 반영 뒤 기준 163파일·2204함수·2697수집 → **163파일·2206함수·2699수집**). 가드 둘 — ⑴ 병합 표시 줄 머리(도입 직후 `>>>>>>>` 줄을 실제로 잡았다) ⑵ **표 행 사이에 낀 표가 아닌 한 줄**(`main` 조각은 병합 표시 모양이 아니라 ⑴이 못 잡는다 — 독립 검토가 찾았다). 행 삭제·함수 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1309) |
| 2026-09-20 | `#1312` | §14.2 `test_demo_up_script.py` 24 → **28함수** · 합계 실측 갱신(163파일·2206함수·2699수집 → **163파일·2210함수·2705수집**). `demo_up.sh` 2단계가 실패 원인을 말하게 한 것을 고정한다 — 포트를 쥔 **다른** 컨테이너 이름 짚기(가짜 docker로 실제 실행) · 컨테이너 이름·포트 ↔ compose 대조 · `compose up` 실패 메시지 보존 · healthy인데 호스트 포트가 빈 상태 감지. 돌연변이 2종(우리 컨테이너 필터 제거 · 로그를 `/dev/null`로) 검출. 함수 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1294) |
| 2026-09-20 | `#1315` | §3.23 `IT-COV-010`(면제 목록 항목 수 상한) 신설 · §14.2 `test_coverage_floor_script.py` 9 → **10** · 합계 실측 갱신(163파일·2210함수·2705수집 → **163파일·2211함수·2709수집**) · `test_suite_lock_db.py` 행 — **실행 잠금을 되살렸다.** `#1058` CUBRID 전환에서 advisory lock이 없어 `_hold_suite_lock()`이 no-op이 됐고 잠금 검사 2건이 사유를 적어 skip돼 있었다 — 호스트 파일 잠금(`fcntl.flock` · 대상 DB별 파일 · 실행이 죽으면 OS가 푼다)으로 대체하고 skip을 걷었다(함수 수는 3 그대로). 이슈의 「SAVEPOINT 롤백 전환」은 `conn`이 이미 트랜잭션 롤백이고, 커밋하는 TestClient 검사 33파일을 한 번에 묶는 방식은 연결 루프가 갈려 실측으로 실패해 이 행에 없다. 케이스 신설·함수 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1250) |
| 2026-09-20 | `#1317` | §5.1 `DB-CHK-022`(호출부호 형식 트리거) 신설 · §14.2 **`test_vessel_call_sign_db.py` 신설 7함수**(14건 수집) · `test_vessels_api.py` 62 → **71** · `test_migration_guard.py` 18 → **19** · 합계 실측 갱신(163파일·2211함수·2709수집 → **164파일·2228함수·2759수집**). 고정하는 것은 **대조 키가 조용히 갈리지 않는다**는 사실이다 — 스키마가 strip · upper로 접고 형식(RR No.19.55 4~7자 · No.19.50 앞 두 글자)을 422로 돌려주는지, DB 트리거 `trg_chk_call_sign_ins/upd`가 API를 거치지 않은 행도 막는지(8자는 `VARCHAR(7)`이 먼저 거부한다 — 실측), 등록 → 수정 → 조회 HTTP 왕복이 실제 컬럼에서 접힌 값을 돌려주는지(`#433`의 교훈). 「앞 두 글자 모두 숫자 불가」는 DB가 아니라 API만 보는 **의도한 느슨함**이라 그 경계도 검사로 고정했다. 행 갱신이라 버전은 올리지 않는다 (#1197) |
| 2026-09-20 | `#1318` | §3.10 `IT-EXPORT-010` 신설 · §14.2 `test_reports.py` 54 → **67함수** · `test_reports_db.py` 37 → **39함수** · `test_data_export_db.py` 26 → **30함수** · 합계 실측 갱신(164파일·2228함수·2759수집 → **164파일·2247함수·2800수집**). CSV 수치 열 선언(`API_SPEC §8.1`·`§8.5` v1.39)을 고정한다 — 선언된 열의 `-12.5`는 접두 없이 나가고(이슈의 완료 기준), 선언 없는 열·문자열 열의 `-1+1+cmd\|…`는 종전대로 막히며, 선언된 열에 숫자 아닌 값이 오면 문자열 규칙으로 되돌아간다(원문이 그대로 나가는 경로가 없다). 라벨(제목·머리글·각주)은 선언과 무관하게 막힌다. 실제 문서는 수치를 싣는 표 전부에 선언이 있고 선언된 열의 값이 숫자·`—`뿐임을 DB 테스트가 본다. 종전 `test_negative_numbers_also_get_the_prefix`는 **`sanitize` 함수의 성질**(문자열 규칙에는 음수 예외가 없다)로 뜻을 좁혀 남겼다. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1247) |
| 2026-09-20 | `#1319` | §5.1 `DB-CHK-023`(계획 거리 출처 트리거) 신설 · §14.2 **`test_voyage_distance_source_db.py` 신설 6함수**(11건 수집) · `test_voyages_api.py` 28 → **35** · `test_voyage_import_db.py` 35 → **36**(CSV 거리는 `USER_INPUT`) · `test_scenario_adopt_db.py` 24 → **25**(채택은 출처를 `null`로) · `test_migration_guard.py` 19 → **20**(059 REGENERABLE) · 합계 실측 갱신(164파일·2247함수·2800수집 → **165파일·2263함수·2822수집**). 고정하는 것은 **「추정값입니다」가 거짓말이 되지 않는다**는 사실이다 — 두 값 밖은 스키마(422)와 트리거(REJECT) 두 층이 막는지, 스키마의 값 목록과 트리거의 값 목록이 같은지, 좌표 추정으로 저장한 항차의 거리만 고치면 출처가 「모른다」로 돌아가는지(옛 출처가 새 숫자에 남으면 직접 고친 값에 「추정」이 붙는다), 출처 없는 생성·채택이 직접 입력으로도 추정으로도 적히지 않는지. 행 갱신이라 버전은 올리지 않는다 (#1256) |
| 2026-09-20 | `#1320` | §14.2 **`test_weather_source_sync.py` 신설 3함수** · 합계 실측 갱신(165파일·2263함수·2822수집 → **167파일·2266함수·2825수집**). 잠그는 것은 **`weather_snapshot.source` 값 사슬**이다 — 코드 상수 `SOURCE_*` ⊆ `TECH_SPEC §7.1` 값 표(정본) = `DB_SCHEMA §2.13` 행. 어댑터가 정상 경로에서 처음부터 저장해 온 `open_meteo_marine+forecast`가 두 문서의 3값 목록에 없었고, 이 컬럼은 CHECK·트리거 어디에도 없어 DB가 알려 주지도 않았다(`DB_SCHEMA §7.4`). `test_warning_codes_sync.py`와 같은 틀이며 뜻(설명 열)은 대조하지 않는다. `#968`은 코드 동작을 바꾸지 않았다(정본을 구현에 맞춤 — `TECH_SPEC §7.1`·`§7.3` v1.14). 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#968) |
| 2026-09-20 | `#1355` | §14.2 `test_auth_tokens.py` 24 → **27함수** · 합계 실측 갱신(166파일·2266함수·2825수집 → **167파일·2269함수·2828수집**). **`POST /auth/password-reset/confirm`이 토큰을 보기 전에 Argon2 해싱을 하던 순서**를 고쳤다 — 이 경로는 미인증이고 인증 버킷 밖(기본 300회/분)이라 아무 토큰이나 실어 보내면 전부 해싱(약 60 ms · 64 MiB · 동시 4)을 태웠고 응답은 어차피 400이었다. 이제 정책 검사(길이)만 앞에 두고 `consume_token`이 성공한 뒤에야 해싱한다. **응답(422·400·200)과 문구는 종전 그대로다** — 상태 코드는 `#1326`이 따로 다룬다. `verify-email/confirm`은 해싱이 없어 같은 문제가 없다. 검사는 응답이 아니라 **`hash_password_async` 호출 횟수**를 센다(위조 0 · 만료 0 · 유효 1 · 재사용 시 그대로 1) — 응답만 보면 순서를 되돌려도 통과한다. 돌연변이 검사: 종전 순서로 되돌리면 3건 모두 실패(실측). 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1327) |
| 2026-09-20 | `#1357` | **TEST_PLAN.md 465행 미폐쇄 코드펜스를 닫았다** — 501행에 빠진 ` ``` `를 넣어 `### 2.4 RNG 재현성`~`### 2.8 Layer 변환`(502~553행)이 코드블록 안에 파묻혀 있던 것을 산문으로 되돌렸다. 펜스가 홀수(25개)라 `_prose_lines()`가 마지막 마커(1492행) 이후 EOF까지 전부 "펜스 안"으로 건너뛰어, 그 사각지대(1492~2184행, 전체의 약 32%) 안의 참조 오류가 CI를 통과하고 있었다. §14.2 `test_doc_cross_refs.py`에 **「정본 md의 코드펜스가 홀수로 끝나면 실패」** 가드 1함수 신설 8 → **9함수** — 재발 시 사각지대 자체가 다시 생기지 않게 막는다. 드러난 유일한 끊긴 참조(본 파일 2144행, `#1084` 행 안 — 존재하지 않는 절 번호 3.3)는 **인용을 지웠다** — `AGENTS.md` §3의 하위 절은 3.1·3.2·3.2.1~3.2.3뿐이라 그 절은 존재한 적이 없고, 문장(「실제 HTTP로 받아 본다」)에 맞는 절도 AGENTS에 없어 다른 절로 바꾸면 추측이 된다. **변경 이력 행은 기록이라 원문을 지우지 않되**, 끊긴 절 포인터는 그대로 두면 다음 사람이 또 막히므로 그 행 안에 정정 취지를 남겼다. `#876` 행(2048행, 원 2047행)의 `` `rating: string \| null` `` · `#1174` 행(`DESIGN_SYSTEM.md` 1254행)의 `` `size="inline" \| "default" \| "large"` `` — 인라인 코드 안 파이프가 이스케이프 없이 GFM 표 열 구분자로 읽혀 표가 깨지던 것을 `\|`로 이스케이프했다(내용 변경 없음, 표시 결함만 정정). 표 열 수 검사는 추가하지 않았다 — 셀 안에 의도된 인용 파이프(1797행의 병합 충돌 예시 등)와 이스케이프 누락을 구분하려면 파서가 필요해 비용 대비 얻는 것이 적다. 합계 실측 갱신(166파일·2269함수·2828수집 → **166파일·2270함수·2829수집**) (#1324) |
| 2026-09-20 | `#1361` | §14.2 `test_annual_simulation_read_db.py` 45 → **46함수** · 합계 실측 갱신(166파일·2270함수·2829수집 → **166파일·2271함수·2830수집**). 잠그는 것은 **`§6.3` 「이 실행에 쓴 항차」의 PLAN 행이 계산과 같은 값을 보이는가**다 — `IN_PROGRESS`·`INCLUDE_AS_PLAN` 항차에 실적 일부(1200 nm·40 t)를 넣고 실행한 뒤 목록의 PLAN 행이 계획값(3000 nm·250 t)이고, 그 값이 응답 `deterministic.planned_W_capacity_nm`(×DWT)·`planned_M_gco2`(×CF×10⁶)와 같은지 본다. 종전 조회는 모든 행에 「실적이 있으면 실적」을 적용해 계산에 쓰지 않은 값을 근거 화면에 실었다. 돌연변이 검사: `_snapshot_voyage_view`의 `kind` 분기를 끄면(모든 행을 실적 우선으로) `1200.0 == 3000.0`으로 실패(실측). 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1337) |
| 2026-09-20 | `#1362` | §14.2 **`test_dbschema_head_sync.py` 신설 3함수** · 합계 실측 갱신(166파일·2271함수·2830수집 → **166파일·2274함수·2833수집**). 잠그는 것은 **`DB_SCHEMA`가 alembic head를 따라오는가**다 — 헤더가 v1.33까지 올라가 있어도 §8.1.0 그래프는 `051`에서, §7.4 트리거 합계는 148(`051` 시점)에서, §2.6은 `052`·`053` 이전에 멈춰 있었고 헤더 판본으로는 그 낡음이 보이지 않았다. 셋 다 DB 없이 마이그레이션 파일·ORM에서 센다. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1342) |
| 2026-09-20 | `#1304` | §14.2 `test_compose_env_wiring.py` 12 → **13** · `test_db_target_guard.py` 20 → **22** · `test_demo_up_script.py` 28 → **29함수** · 합계 실측 갱신(166파일·2270함수·2829수집 → **166파일·2274함수·2836수집**). 고정하는 것은 **`#1058` CUBRID 전환이 문서·설정에 남긴 자국**이다(`#1207` · `#1305`). ⑴ `docker-compose.yml`이 정본 여덟 중 `UIFLOW.md` **하나만** 마운트하지 않아 컨테이너 안에서 `test_doc_cross_refs.py`가 「파일 없음」으로 죽었다 — 그 가드의 `TARGETS` **첫 항목이 `UIFLOW`**이고, 가드가 태어난 이유 자체가 *「`DESIGN_SYSTEM`이 존재한 적도 없는 `UIFLOW` 절을 6종 참조한다」*(`#583`)였다. ⚠️ **호스트에서 돌리면 파일이 제자리에 있어 초록으로 통과하므로 어긋남이 드러나는 경로가 사실상 없다.** 새 검사는 목록을 베끼지 않고 `TARGETS`를 **읽어 와** 대조한다 — 베껴 두면 갈릴 자리를 하나 더 만든다. ⑵ `tests/db_target.py`가 막을 때 내미는 명령이 `createdb -U cii`·`postgresql+asyncpg://…:5432`였다 — **CUBRID에 없어 안내대로 따라 하면 실패한다.** ⚠️ **이 문구는 가드가 걸릴 때만 보이므로 틀려도 CI가 영원히 초록이다**: 막힌 사람은 「막혔다」까지만 보고하지 「안내받은 명령도 안 된다」까지 가지 않는다. 새 검사는 `db_target.py`의 **실행 줄**(독스트링·주석 제외)과 `README` 「로컬에서 테스트를 돌리는 법」의 **코드펜스**를 함께 본다 — 산문은 옛 이름을 **설명하려고** 쓰므로 제외한다(`test_db_backup_script.py`가 같은 선을 긋고, `test_doc_cross_refs.py`가 코드펜스를 건너뛰는 것과 방향만 반대인 같은 판단이다). ⑶ `DATABASE_URL` 표기를 `cubrid+pycubrid://`로 통일했다 — `aiopycubrid`는 **배포본이 아니라** `sqlalchemy-cubrid`가 싣는 async 방언 이름이고 DBAPI는 `pycubrid` 하나다(`entry_points`와 두 dialect 소스를 직접 읽어 확인). 🔴 **그 변경이 `demo_up.sh`를 깨뜨릴 뻔했다** — 인라인 파이썬 두 곳이 `create_async_engine(os.environ["DATABASE_URL"])`로 **원문을 그대로** 넘기는데, `src/`의 세 호출부만 확인해 그 둘을 놓쳤다(리뷰가 잡았다). `test_async_engines_normalize_the_database_url`이 **스크립트의 모든 `create_async_engine` 줄**을 훑게 해 같은 누락을 막는다 — 호출부를 하나씩 세는 방식이면 다음에 늘어나는 호출을 또 놓친다. `AGENTS §4.3`상 인벤토리 행 갱신이라 버전은 올리지 않는다 (#1207 · #1305) |
| 2026-09-20 | `#1358` | §3.12 `IT-GEO-009`~`015` 신설 · §14.2 `test_port_geocoding_db.py` 8 → **15함수** · 합계 실측 갱신(167파일·2278함수·2840수집 → **167파일·2285함수·2847수집**). **`#1335`** — 종전 라우트가 요청마다 `NominatimProvider()`를 새로 만들어, 어댑터 인스턴스 안의 락·직전 호출 시각이 매번 초기화되고 `IT-GEO-008`은 한 인스턴스만 보아 이를 잡지 못했다(감사 실측: 요청별 5회가 0.001초 안에 나감). 제공자는 `api/main.py`가 `app.state.geocode_provider`에 하나 두고(`rate_limiter`와 같은 자리) 라우트가 꺼내 쓴다. `009`~`011`은 어댑터에 끼운 **가짜 시계**로 보므로 실제로 기다리지 않고 네트워크로 나가지 않는다. **`#1364`** — 그 수정만으로는 조회가 직렬화되면서 **커넥션 풀이 고갈된다.** 캐시를 보는 SELECT가 트랜잭션을 열어 커넥션을 체크아웃한 상태로 외부를 기다리므로, 줄 길이만큼 커넥션이 쌓이고 기본 풀(5+10)이 마르면 좌표 조회와 무관한 요청까지 30초 뒤 실패한다. 이제 **캐시에서 못 찾은 순간 트랜잭션을 닫고**(커넥션 반납) 바깥으로 나가며 저장만 새 트랜잭션으로 한다 — `IT-GEO-012`가 **커넥션 1개짜리 엔진**으로 그것을 직접 본다(쥐고 있으면 `pool_timeout` 초과). 차례 대기에는 상한 5초를 두어(`MAX_WAIT_SECONDS`) 넘으면 `LOOKUP_FAILED`이고(`013`), 커넥션을 놓는 사이 다른 요청이 같은 이름을 먼저 저장할 수 있으므로 `UNIQUE(query)` 충돌을 정상 경로로 받아 먼저 저장된 행을 읽어 돌려준다(`014`). 트랜잭션을 닫는 설계라 미커밋 변경을 들고 부르면 거부한다(`015`). 돌연변이 4종(제공자 요청마다 생성 · 커넥션 반납 제거 · 대기 상한 제거 · `UNIQUE` 충돌 처리 제거) **4/4 검출**. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1335 · #1364) |
| 2026-09-20 | `#1376` | §14.2 `test_reports.py` 67 → **69** · `test_reports_db.py` 39 → **40함수** · 합계 실측 갱신(167파일·2285함수·2847수집 → **167파일·2288함수·2850수집**). 잠그는 것은 **PDF 렌더링이 이벤트 루프를 막지 않는다**는 것이다 — `write_pdf()`는 순수 CPU 작업이고 1초 안팎이 걸리는데 `async` 라우트에서 그대로 불렀다(감사 실측: 10 ms 틱이 최대 548 ms 정지). 이제 `render_pdf_async`가 `anyio.to_thread`로 내보내며, **동시 상한은 1**이다(`MAX_CONCURRENT_RENDERS`). 상한을 1로 둔 근거는 실측이다 — 120행 표를 예열 후 동시에 돌리면 1건 0.46초 · 2건 1.56초 · 4건 8.12초 · 8건 23.77초로, **4건을 동시에 돌리면 줄 세울 때(약 1.84초)보다 4.4배 느리다**(WeasyPrint가 거의 순수 파이썬이라 GIL을 놓지 않는다). 메모리도 동시 1건당 약 +14 MiB 는다. 근거 표는 `reports/pdf.py` 모듈 docstring에 남겼다 — 다음 사람이 「상한을 올리면 빨라지겠지」로 되돌리지 않게 하기 위함이다. 함께 **렌더 전에 DB 트랜잭션을 닫는다**(`#1364`와 같은 근거) — 수집은 읽기만 하지만 읽기도 트랜잭션을 열어 커넥션을 체크아웃한 채로 두므로, 렌더링이 줄을 서면 그 시간만큼 커넥션이 묶여 리포트와 무관한 요청까지 30초 뒤 실패한다. 검사는 실제 WeasyPrint를 부르지 않는다(폰트·렌더러 없는 환경에서도 돌고 검사가 1초씩 늘지 않는다). 돌연변이 3종(스레드 이관 제거 · 상한 1→4 · 렌더 전 세션 반납 제거) **3/3 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1363) |
| 2026-09-20 | `#1378` | §14.2 `test_layer1_context.py` 7 → **9함수** · 합계 실측 갱신(167파일·2288함수·2850수집 → **167파일·2290함수·2852수집**). 잠그는 것은 **Layer 1 파생값도 적용 지점 안에서 난다**는 것이다 — `TECH_SPEC §1.2.1`이 *「Layer 1 값에서 새 값을 만드는 코드는 반드시 진입점 안에 둔다」*로 정했는데 세 곳이 밖에 있었다(⑶ 연말 예상의 `ratio_to_required` · 「D등급 진입까지 n일」의 `area_now`·`area_past`). 밖에서 계산하면 기본 정밀도(`prec=28`)로 잘려 정본과 **27번째 자리부터 갈린다**(실측 `…012600` vs `…012581`). **검사는 값이 아니라 계산 시점의 정밀도를 본다** — 응답 자릿수(5자리 · 정수 일수)에서는 차이가 드러나지 않아 값만 단언하면 아무것도 잠그지 못한다. `_project_layer1`은 `project_deterministic` 호출 시점의 `prec`을, `_days_to_target_arithmetic`은 `attained_cii`를 읽는 순간(곱셈 직전)의 `prec`을 본다. 앞의 검사에는 **`prec=28`로 계산해도 같은 값이면 실패**하는 단언을 함께 넣었다 — 그 조건이 깨지면 검사가 잠그는 것이 없어진다. 돌연변이(데코레이터 2개 제거) **2/2 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1372) |
| 2026-09-20 | `#1379` | §14.2 `test_compose_env_wiring.py` 13 → **16** · `test_mail.py` 21 → **24함수** · 합계 실측 갱신(167파일·2290함수·2852수집 → **167파일·2296함수·2860수집**). 잠그는 것은 **OCI 분리 토폴로지 compose의 두 구멍**이다 — `SMTP_PORT`를 `${SMTP_PORT:-}`로 넘겨 `MAIL_BACKEND=smtp` 전환 시 `int("")`로 기동이 실패했고(`source.get("SMTP_PORT", "587")`은 **키가 있으면** 기본값을 쓰지 않는다 — compose가 넘긴 빈 문자열에서도 키는 있다), `LOG_FILE`이 없어 `docs/OPERATIONS.md §8.2.1`의 장애 대응 절차가 app-01에서 「No such file」로 끝났다. **둘 다 단일 호스트 `docker-compose.prod.yml`에는 있었고 분리 토폴로지 파일만 빠져 있었다** — 그 절차가 지시하는 `cii-backend` 컨테이너를 만드는 것이 바로 그 파일이다. 검사는 **문서와 compose의 로그 경로 일치**까지 본다(갈리면 절차가 조용히 빗나간다). 함께 SMTP **465를 implicit TLS로** 붙인다(`use_tls=True` · `start_tls=False` · `RFC 8314 §3.3`) — 종전에는 `start_tls`만 넘겨 465가 **어떤 설정으로도 동작하지 않았다**(false면 평문, true면 이미 TLS인 연결에 STARTTLS). 빈 포트는 compose와 앱 **양쪽**에서 막는다 — 한쪽만 고치면 `.env`에 직접 적는 경로나 다음 compose 파일이 같은 함정을 되풀이한다. 돌연변이 4종 **4/4 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1331) |
| 2026-09-20 | `#1381` | §14.2 `test_login_backoff.py` 6 → **9** · `test_reports.py` 69 → **70함수** · 합계 실측 갱신(167파일·2296함수·2860수집 → **167파일·2300함수·2864수집**). 정리 둘이다. ⑴ **로그인 실패 백오프 표가 비워지지 않았다** — 만료 항목은 `_current()`가 **그 이메일을 다시 조회할 때만** `pop`하는데, 자격 증명 스터핑은 대개 **매번 다른 이메일**로 오므로 다시 조회되는 일이 없어 재시작 전까지 쌓인다. `MAX_TRACKED_EMAILS`(10,000)를 넘으면 만료분을 먼저 쓸어내고, 그래도 넘으면 **가장 오래된 것부터** 버린다 — 지연이 필요한 쪽은 지금 두드리고 있는 이메일이다. 상한을 낮게 잡으면 **공격자가 상한을 이용해 자기 항목을 밀어내므로** 「정상 사용을 깨지 않을 만큼 큰가」도 검사로 못 박았다. ⑵ **`iter_csv`의 `document.validate()`가 죽어 있었다** — 제너레이터 본문 안이라 첫 조각을 요구받을 때 도는데, 그때는 `StreamingResponse`가 이미 상태 코드와 헤더를 내보낸 뒤다. 예외가 나도 오류 응답이 될 수 없고 전송이 끊길 뿐이라 **사용자는 깨진 파일을 받는다.** 지우지 않고 **앞으로 옮겨** 라우트가 `iter_csv(document)`를 평가하는 시점(=응답 시작 전)에 돌게 했고, 본문은 `_iter_csv_chunks`로 나눴다. 검사는 **반복하지 않아도 터지는가**를 본다. 함께 `iter_table_csv` 주석의 *「연도 전체 항차를 메모리에 쌓지 않는다」*를 사실에 맞췄다 — 지금 호출부(`services/data_export.py`)는 행을 리스트로 통째로 만든다. 행까지 흘리려면 **응답을 쓰는 동안 DB 세션이 열려 있어야 하는데 `#1363`·`#1364`가 바로 그 반대 방향으로 옮긴 참**이라, 커서 기반 조회와 함께 판단할 일로 남겼다. 돌연변이 2종 **2/2 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1368) |
| 2026-09-20 | `#1382` | §14 인벤토리 **수치 변화 없음** — **프론트엔드 검사만 바뀌었다**(§14는 백엔드 pytest만 센다 · `#820`·`#890`·`#892` 선례). 고치는 것은 **미참조 `export` 가드 자신의 신뢰도**다 — `frontend/src/moduleBoundary.test.ts`가 파일 본문을 그대로 훑어 **주석 속 이름도 참조로 셌다.** 렌더 소비처가 0곳인 `ComingSoon`이 다른 파일의 **설명 문장**에 이름이 나온다는 이유로 미참조 목록에 걸리지 않았고, `KEPT`에 등재되어 봐준 것이 아니라 **탐지기가 못 본 것**이었다. 위험한 것은 죽은 코드 하나가 아니라 **앞으로 진짜 죽은 코드가 생겨도 누군가의 설명 주석에 같은 이름이 우연히 등장하면 조용히 놓친다**는 것이다(`AGENTS §7`의 「잡이 돌지만 아무것도 막지 않는 상태가 가장 나쁘다」와 같은 자리). `withoutCommentsAndStrings()`로 **주석과 문자열 내용**을 지운 사본에서 참조를 센다 — 문자열도 지우는 이유는 `screens.test.ts`의 `source.includes('ComingSoon')`이 **페이지 파일 본문에 그 낱말이 있는지**를 보는 것이지 컴포넌트를 부르는 것이 아니기 때문이다. 문자열을 지워 새로 드러나는 것은 **`ComingSoon` 하나뿐**임을 임시 적용으로 실측했다. 문자열 내용을 봐야 하는 검사(「항차 상태 이름표는 하나다」 — `IN_PROGRESS: '…'` 패턴)는 원문 사본 `RAW`를 쓴다. `ComingSoon`은 `KEPT`에 `#594` 판정 사유와 함께 올렸다. 돌연변이 2종 **2/2 검출** — 제거 원복 · **주석에만 이름이 있는 죽은 export 추가**(이 이슈의 완료 기준을 직접 재는 확인으로, 종전 코드에서는 통과했다). 프론트 116파일 **1817 passed** · `lint`·`build` 통과 (#1351) |
| 2026-09-20 | `#1383` | §14.2 `test_seed_migration.py` 8 → **11함수** · 합계 실측 갱신(167파일·2300함수·2864수집 → **167파일·2303함수·2867수집**). 잠그는 것은 **두 적재 경로가 갈라지는 순간**이다 — `DB_SCHEMA §8.1.1`이 *「`tests/test_seed_migration.py`가 양쪽을 매 실행 대조한다」*고 적는데 실제로는 Z·기준선·d-vector 셋만 봤다. 그 사각지대에서 `simulation_parameter.version`이 마이그레이션 `"2026.08"` · `seed.py` `"1.0"`으로 **갈린 채 남아 있었다**. 그 값은 `parameters_used.simulation_profile.version`으로 `parameter_hash`에 들어가므로, 적재 순서에 따라 재현(`TECH_SPEC §5.4`)이 실패한다. **`version`을 수치와 별개로 단언한다** — 행의 수치가 같아도 이 사고는 일어나므로 값 비교에 묻히면 안 된다. 함께 **연료 CF 8행 · 기상 10행**도 대조 대상에 넣어 위 문장을 참으로 만들었다(CF는 값 자체를 `test_seed_data.py`가, 행별 해시를 `test_fuel_type_content_hash.py`가 보지만 **갈라짐**을 보는 것은 이 파일뿐이다). 값은 `"1.0"`으로 맞췄다 — 실측상 다섯 표가 전부 `"1.0"`이고 `fuel_type.version`의 `server_default`도 `'1.0'`이라, 반대로 맞추면 53행의 version이 바뀌어 저장된 `calculation_run`의 재현이 전부 깨진다(결정요청 v3 §2-B M-8의 권장 `"2026.08"`과 다르며 그 사유를 PR 본문에 적었다). 돌연변이 2종 **2/2 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1370) |
| 2026-09-20 | `#1385` | §14.2 `test_voyage_cii_service.py` 18 → **19함수** · 합계 실측 갱신(167파일·2303함수·2867수집 → **167파일·2304함수·2871수집**). 잠그는 것은 **경계 CII가 서버에서 온다**는 것이다 — 화면이 `required_cii × d`로 다시 만들면 **이중 반올림**이 되어 411,120건 중 87건에서 끝자리가 갈렸다. 서버 쪽은 4종이 **6자리**로 실리는지를(`attained_cii`·`required_cii`와 같은 자릿수) 정본 픽스처 값으로 보고, 화면 쪽은 **끝자리가 갈리는 실제 조합**을 고정한다(`(1.851449 × 0.888771).toFixed(3) === '1.646'`인데 서버 정본은 `1.645`). 서버가 싣지 않은 옛 이력에서 종전 경로로 되살리는 것도 함께 본다. ⚠️ **기존 가드 둘이 이번 변경을 잡았다** — `test_response_contract_db`가 계약 키 5행을, `test_dbschema_json_example_sync`가 **손 스텁에 `boundaries`가 없다**는 것을(그래서 `DB_SCHEMA §2.5` 예시도 함께 갱신해야 함을) 드러냈다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1371) |
| 2026-09-20 | `#1387` | §14.2 **`test_audit_enum_sync.py` 신설 6함수** · 합계 실측 갱신(167파일·2304함수·2871수집 → **168파일·2310함수·2877수집**). 잠그는 것은 **`audit_log.action`·`entity_type` 값 사슬**이다 — `코드 리터럴 == AUDIT_ACTIONS(+DB_BACKUP) == DB_SCHEMA §2.14 행`을 **양방향으로** 본다. 한쪽만 보면 목록이 코드보다 앞서거나 뒤처진 채 통과한다. `DB_BACKUP`은 `migration_guard`가 **상수 이름으로** 넣어 `action="…"` 리터럴로 잡히지 않으므로 따로 확인한다. 돌연변이 2종(문서에서 한 값 제거 · 상수에 쓰지 않는 값 추가) **2/2 검출** — 뒤엣것은 리터럴 대조와 문서 대조 **둘 다** 실패한다. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1343) |
| 2026-09-20 | `#1388` | §14.2 `test_structured_logs.py` → **`test_structured_logs_db.py`**(파일명만 · 합계 불변). 검사 하나(`test_request_body_never_reaches_the_log`)가 `/api/v1/auth/login`을 실제로 불러 **DB를 쓰는데** 접미사가 없어, DB 없이 돌리는 묶음에 섞여 `ConnectionRefusedError`로 혼자 실패했다 — 그 실패는 **코드가 아니라 실행 방식**을 가리키는데 이름이 그 사실을 말하지 않았다 (`#1350`). 함께 가드 둘이 늘었다(함수 수는 기존 파일 안에서 바뀌지 않았다) — ⑴ **`.woff2`가 이름만이 아니라 실제로 woff2인가**(매직 `wOF2`). `scripts/build_fonts.py`가 `flavor`를 서브셋터에만 넘겨 **비압축 TrueType이 `.woff2` 이름으로** 커밋돼 있었고(한글 2종 각 2.8MB), `format('woff2')`로 선언돼 렌더는 되므로 **파일 크기 말고는 드러나는 자리가 없었다**(고친 뒤 5.68MB → 1.35MB · 글리프 14,102개 유지) ⑵ **마이그레이션 downgrade 분류 검사가 f-string SQL을 본다** — `ast.Constant`만 보던 탓에 `056`이 분류 없이 통과했다. 넓히자 `050`이 오검출돼(FK 절의 `ON DELETE RESTRICT`) `DELETE` → `DELETE FROM`으로 좁혔다. `test_issue_matrix.py`의 레이어 라벨 목록은 열두 종 → **열세 종**(`layer:backlog` 복귀 — 주석이 「남긴다」고 적으면서 정작 빠져 있었다). 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1350) |
| 2026-09-20 | `#1389` | §14.2 `test_fleet_summary.py` 52 → **54** · `test_layer_conversion.py` 6 → **7** · `test_scenario_adopt_db.py` 25 → **26함수** · 합계 실측 갱신(168파일·2310함수·2877수집 → **168파일·2314함수·2881수집**). 네 가지를 잠근다 (`#1349`). ⑴ **끝난 규제연도에는 「앞으로 n일」이 없다** — 남은 일수를 `as_of`의 연도로만 재서 2026-01-10에 2025년을 조회하면 「D 진입까지 70일」이 나왔다(실측). 경계 함수(`_days_left_in_year`)를 직접 단언한다 — 그 함수 하나가 결함의 소재이고 산식 쪽은 이미 다른 검사가 덮는다. ⑵ **재현 응답의 `feedback.requested`가 `bool`이다** — 생 SQL에 타입이 없어 CUBRID의 `Boolean`→`SMALLINT`가 `0`/`1`로 올라왔고, 종전 검사는 `==`라 **`1 == True`가 통과**했다. `is True`로 바꾼다. ⑶ **시나리오 채택이 한 트랜잭션이다** — `create_voyage`가 안에서 커밋해 새 항차가 먼저 확정됐고, 뒤 단계가 실패하면 **채택 기록 없는 DRAFT 항차**가 남았다. 남은 행이 아니라 **커밋 횟수**로 단언한다(하네스가 바깥 트랜잭션 안이라 중간 커밋이 격리를 벗어나지 않아 행으로는 구분되지 않는다). ⑷ **변환 손실을 float의 이진값과 잰다** — `Decimal(str(f))`는 `str(float)`이 주는 **가장 짧은 십진 표기**와 비교해 `0.1`의 손실이 `0`으로 나왔다. 「손실을 숨기지 않는다」는 선언이 그 자리에서 깨져 있었다. 돌연변이 3종 **3/3 검출**. ⚠️ 다섯 번째 항목(서버 6자리 → 화면 3자리 **이중 반올림**)은 **모든 CII 필드의 계약을 바꾸는 결정**이라 `#1349`에 남겼다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1349) |
| 2026-09-20 | `#1390` | §14.2 **`test_doc_cross_refs.py` 중복 행 삭제** · 그 행 9 → **10함수** · `test_testplan_sync.py` 10 → **11함수** · 합계 실측 갱신(168파일·2314함수·2881수집 → **168파일·2316함수·2883수집**). 둘 다 **기존 검사가 구조적으로 잡을 수 없던 형태**다. ⑴ `DESIGN_SYSTEM §7.2`가 사이드바 순서의 소관을 `UIFLOW §2.2`로 인용했는데 그 절은 **화면 ↔ 계층 매핑**이고 순서 표는 `§2.2.1`이다 — 위임받은 절로 갔는데 **찾는 표가 없는 자리**에 도착한다. `test_절_참조가_전부_실재한다`는 **그 절이 있는가**만 보므로 `§2.2`도 실재해 통과했다 (`#1341`) ⑵ §14.2에 `test_doc_cross_refs.py` 행이 **둘**이었고 한쪽에만 `#1324`가 신설한 홀수 펜스 가드 문장이 있었다 — 파일별 수를 dict으로 모아 **뒤 행이 앞 행을 덮으므로**, 두 행이 같은 수를 적으면 대조도 합계도 통과한다 (`#1380`). 돌연변이 2종 **2/2 검출**. ⚠️ `DESIGN_SYSTEM §7.2`의 「항목이 7개 이하」(실제 9)는 **디자인 담당 소관**이라 손대지 않고 확인 요청만 올렸다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1341 · #1380) |
| 2026-09-20 | `#1391` | §14.2 **`test_hash_fields_doc_sync.py` 신설 5함수** · 합계 실측 갱신(168파일·2316함수·2883수집 → **169파일·2321함수·2890수집**). 잠그는 것은 **해시 입력 키 집합 ↔ `TECH_SPEC §5.3`**이다 — 세 집합(`INPUT_FIELDS` 11 · `SCENARIO_INPUT_FIELDS` 12 · `ANNUAL_INPUT_FIELDS` 10)을 **문서에서 읽어** 코드와 맞춘다. `test_hashing.py`가 이미 코드 쪽 목록과 순서를 잠그지만 **그 검사는 문서를 보지 않는다** — 실제로 `#363`·`#816`·`#756` ⑴이 키를 셋 늘리는 동안 `§5.3`의 기능③ 목록은 일곱으로 남아 있었다. ⚠️ **주석 뒤를 버리고 읽는다**: 따옴표는 주석 안에도 남아, 키를 주석 처리하면 「목록에서 뺐다」가 드러나지 않는다 — 돌연변이 4종 중 **이 형태만 처음에 통과했다**. **선택 키 셋이 「선택」이라고 적혀 있는가**도 함께 본다. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1344) |
| 2026-09-20 | `#1392` | §14.2 `test_validation_messages.py` 12 → **14** · `test_auth_failure_paths.py` 6 → **7함수** · 합계 실측 갱신(169파일·2321함수·2890수집 → **169파일·2324함수·2893수집**). 잠그는 것은 `API_SPEC §1.4` 두 줄이다 (`#1366`). ⑴ **JSON 파싱 오류·잘못된 Content-Type이 422**라는 것 — 표는 400으로 적었고 `§1.3.2`는 422로 적어 **한 문서 안에서 갈려 있었다**. ⑵ **CSRF 403이 새 토큰을 실어 주지 않는다** — 「재시도한다」는 규정이 서버에서 성립하지 않는다. ⚠️ 첫 검사는 `cookies.delete("csrf")`로 상황을 만들었는데 **그 줄을 지워도 통과했다**(403은 쿠키가 아니라 **헤더 부재**로 난다). 실패 뒤 **세션이 멀쩡한 조회 2종을 불러도 토큰이 돌아오지 않는다**를 직접 단언하도록 바꿨고, `/auth/me`가 쿠키를 다시 주는 돌연변이가 그것을 검출한다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1366) |
| 2026-09-20 | `#1393` | §14.2 **`test_readme_deploy_sync.py` 신설 4함수** · 합계 실측 갱신(169파일·2324함수·2893수집 → **170파일·2328함수·2897수집**). 잠그는 것은 **`README` 배포 절 ↔ 실제 운영·코드**다 (`#1339`). 종전 도입부가 *「nginx가 …같은 오리진이 된다 — 그래서 백엔드에 CORS 설정이 없다」*로 **단일 호스트 경로만** 설명했는데, 실제 운영은 **OCI 2-VM 분리 + Cloudflare Pages**이고 `api/main.py`가 `CORS_ALLOW_ORIGINS`로 미들웨어를 붙인다 — 그 값이 없으면 화면이 API를 부르지 못한다(`docs/OPERATIONS.md §9.7`이 실제 장애로 등재). ⚠️ **문장을 통째로 묶지 않는다**(`AGENTS §4.6`) — 정정 각주가 인용하는 형태(「…는 사실이 아니다」)를 걸러 내고 **단정만** 찾으며, 가리키는 compose 파일이 **실재하는지**까지 본다. ⚠️ **절을 못 찾으면 나머지 셋이 「빈 문자열에 없다」로 조용히 통과**하므로 절 길이부터 단언한다. 돌연변이 3종 **3/3 검출**. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1339) |
| 2026-09-20 | `#1394` | §14.2 `test_voyages_api.py` 35 → **37함수** · 합계 실측 갱신(170파일·2328함수·2897수집 → **170파일·2330함수·2899수집**). 잠그는 것은 **항차 메모의 길이 상한**이다 (`#1348`). `PRD §10.2` ⑵가 0~1000자를 정해 뒀는데 **코드에 상한이 없었다** — DB가 `TEXT`라 컬럼은 받지만 **받는 것과 받아도 되는 것은 다르다**. 경계 **1000은 통과 · 1001은 422**를 함께 보고 `field_label`이 「메모」인지까지 본다(오류가 어느 칸을 가리키는지가 화면에 그대로 나간다). 돌연변이 2종(상한 제거 · 1000 → **1001** 한 칸) **2/2 검출** — 뒤엣것이 없으면 상한을 아무 큰 값으로 두어도 「막힌다」 검사만으로는 드러나지 않는다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1348) |
| 2026-09-20 | `#1396` | §14.2 **`test_calculation_filter_enum_sync.py` 신설 4함수** · `test_calculations_api.py` 12 → **15** · `test_fleet_reduction_db.py` 11 → **15함수** · 합계 실측 갱신(170파일·2330함수·2899수집 → **171파일·2341함수·2917수집**). 잠그는 것은 둘이다 (`#1367`). ⑴ **잘못된 필터가 빈 목록이 아니라 422**라는 것 — 그리고 **형식 검증이 존재 검증이 아니라는 것**(형식이 맞는 해시로 못 찾으면 200 + 빈 목록)을 함께 본다. 이것이 없으면 「해시 필터는 늘 422」로 지나치게 좁혀도 통과한다. ⑵ **감축 계획 목록이 자를 때 그 사실을 말한다**는 것 — 한 페이지·커서 이어받기·마지막 페이지·깨진 커서 넷. 돌연변이 4종 **4/4 검출**이며 그중 keyset 비교 `<` → **`<=`**(커서 행이 다시 나온다)는 **경계 한 칸**이라 「페이지가 나뉜다」 검사만으로는 드러나지 않는다. ⚠️ 페이지네이션 검사는 **표를 먼저 비운다** — 표 전체의 순서를 보는 것이라 남의 행이 섞이면 단언할 수 없다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1367) |
| 2026-09-20 | `#1397` | §14.2 `test_data_export_db.py` 30 → **32함수** · 합계 실측 갱신(171파일·2341함수·2917수집 → **171파일·2343함수·2921수집**). 잠그는 것은 **내보낸 파일이 추정 거리와 직접 입력을 구분한다**는 것이다 (`#1354` ⑵). ⚠️ **`null`은 빈 칸**이라는 것까지 본다 — 「모른다」를 `USER_INPUT`으로 채우면 `PRD §0.3`이 금하는 거짓말이 된다. 새 열이 **왕복 구간(앞 7열)을 밀어내지 않는지**도 함께 단언한다. 돌연변이 2종(행에서 값 제거 · 열을 왕복 구간 안으로 이동) **2/2 검출**이며 뒤엣것은 **14 failed**로 크게 드러난다. ⚠️ 검사를 쓰다 `_insert_voyage` 헬퍼의 INSERT 열 목록이 고정이라 **새 값이 들어가지 않는 것**을 발견해 함께 고쳤다 — **기본값은 `None`**이다(`USER_INPUT`을 기본으로 두면 출처를 넣지 않은 항차가 직접 입력으로 보인다). 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1354) |
| 2026-09-20 | `#1398` | §14.2 **`test_retention_policy_sync.py` 신설 2함수** · `test_purge_expired_script.py` 7 → **8함수** · 합계 실측 갱신(171파일·2343함수·2921수집 → **172파일·2346함수·2924수집**). 잠그는 것은 **보존 정책 ↔ 지우는 경로**다 (`#1347`). ⑴ 보존일이 `DB_SCHEMA §4.3`과 같은가 ⑵ **정본이 「삭제」라 적은 표에 지우는 경로가 있는가** — ⑵가 이 이슈를 만든 형태 자체를 막는다(`§4.3`이 30일 삭제를 적는 동안 **지우는 경로가 아예 없었다**). `weather_snapshot` 정리는 ⚠️ **참조 표 둘**을 함께 본다: `voyage_scenario`가 `ON DELETE SET NULL`이라 막지 않고 조용히 링크만 끊는다. `NOT IN`에 NULL이 섞이면 **한 행도 못 지운다**는 것까지 단언한다. 종전 검사 둘을 **성질로 넓혔다**(`AGENTS §4.6`) — 만료 열을 `expires_at` 리터럴로 찾던 것을 「시각으로 자른다」로, 대상 표 전체를 비교하던 것을 「실패한 표가 나머지를 세우지 않는다」로(**대상이 하나 늘 때마다 깨지던 자리**). 돌연변이 3종 **3/3 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1347) |
| 2026-09-20 | `#1399` | §14.2 `test_chat_api_db.py` 23 → **25함수** · 합계 실측 갱신(172파일·2346함수·2924수집 → **172파일·2348함수·2926수집**). 잠그는 것은 **`data`의 키 집합**이다 (`#1365`). 종전 계약 검사는 **값 몇 개만** 보아 `API_SPEC §15.1` 표에 없는 키가 늘어도 통과했다 — **「빠진 키」는 화면이 깨져 드러나지만 「늘어난 키」는 아무 데서도 드러나지 않는다**(`tool_output_count`가 정확히 그렇게 남아 있었다). **폐기한 턴도 같은 키**인지 함께 본다 — 폐기 경로는 `_result(...)`를 여러 자리에서 따로 부르므로 한 자리만 고치면 「어떤 답은 키가 다른」 상태가 된다. 돌연변이 2종 **2/2 검출**. ⚠️ 작업 중 `_result` 호출부 한 자리(`[], []` 리터럴)를 놓쳤는데 **`ruff`는 통과하고 `IT-CHAT-065`만 실패했다** — 그 검사가 없었으면 45초 상한 경로가 조용히 500이 됐다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1365) |
| 2026-09-20 | `#1400` | §14.2 `test_cii_current_db.py` 38 → **40함수** · 합계 실측 갱신(172파일·2348함수·2926수집 → **172파일·2350함수·2928수집**). 잠그는 것은 **연도를 선언하지 않은 진행 항차가 ⑵에 남는다**는 것이다 (`#1336`). `chk_year_policy`상 `regulation_year IS NULL`은 반드시 `EXCLUDE`이고 `PRD §8.1.2`상 `IN_PROGRESS + EXCLUDE`는 합법인데, `InProgressState.for_year`가 `None != 2026`으로 **상태 전체를 비워** 선박이 `UNDER_WAY`인데 카드가 사라지고 `meta.simulated`도 내려갔다 — `#1085`가 이미 「⑴만 비우고 ⑵는 남긴다」로 판단한 자리를 뒤에서 되돌리고 있었다. ⚠️ **⑴까지 되살리지 않는지**를 함께 본다. 다만 **「`for_year`를 통째로 없애는」 과잉 수정은 이 파일이 잡지 못하고** `test_in_progress_year_scope_db.py`(`#815`)가 **3건**으로 잡는다 — 돌연변이 검사를 한 파일로만 돌리면 검출됐다고 오판한다. 그 사실을 새 검사 docstring에 적어 두었다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1336) |
| 2026-09-20 | `#1401` | §14.2 `test_not_underway_crud_db.py` 32 → **33** · `test_not_underway_api_db.py` 6 → **8함수** · 합계 실측 갱신(172파일·2350함수·2928수집 → **172파일·2353함수·2931수집**). 셋을 잠근다 (`#1333`). ⑴ **귀속 연도가 UTC 기준**인가 — `2027-01-01 03:00+09:00`(= `2026-12-31 18:00Z`)이 **2026년**으로 잡히는지 본다. ⑵ **시간대 없는 시각이 422**인가(`POST`·`PATCH` 둘 다) ⑶ **귀속 항차가 이 선박의 살아 있는 항차**인가. 돌연변이 5종 **5/5 검출**이나 ⚠️ **둘을 처음에 놓쳤다** — `update_period`의 검사 제거가 통과해 **PATCH 경로 검사**를 더했고, 그 짝으로 **`null` 클리어까지 막는 과잉 수정**도 함께 잠갔다(한쪽만 있으면 「고치는 경로를 안 보거나」 「지우는 것까지 막거나」 중 하나를 놓친다). 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1333) |
| 2026-09-20 | `#1402` | §14.2 **`test_voyage_input_validation_db.py` 신설 6함수** · 합계 실측 갱신(172파일·2353함수·2931수집 → **173파일·2359함수·2938수집**). 잠그는 것은 **`API_SPEC §1.4`가 4xx를 정한 자리에서 500이 나거나 조용히 통과하던 다섯**이다 (`#1332`). ⚠️ **빈 목록이 가장 조용하다** — 필터 오타가 200 + 빈 배열로 돌아오면 화면에서 「그런 항차가 없다」와 같은 모양이 된다. ⚠️ **필터는 「거르는 쪽과 걸러지는 쪽」을 함께 본다** — 「빈 목록이 온다」만 보면 필터가 늘 0건을 내도 통과한다. ⚠️ **HTTP로 본다** — `test_voyages_api.py`는 저장소를 대역으로 갈아 끼워 **FK가 없으므로 500이 나던 경로를 재현할 수 없다**(`#433`의 교훈). 돌연변이 5종 **5/5 검출**이며, 그중 하나는 처음에 **내 코드가 죽은 가지**여서 다른 자리(`vessel_repo.get_by_id`의 `is_deleted` 필터)로 옮겨 잡았다. 같은 PR에서 대역 검사 둘도 고쳤다 — `_FakeSession`이 새 의존성을 몰라 터졌고(`#1350`의 교훈), `fake_list_active`가 **필터를 무시**해 「필터를 넘겼는데 안 걸린다」가 그 파일에서 드러나지 않았다. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1332) |
| 2026-09-20 | `#1403` | §14.2 **`test_voyage_transition_canon_sync.py` 신설 4함수** · `test_audit_actions_db.py` 9 → **11함수** · 합계 실측 갱신(173파일·2359함수·2938수집 → **174파일·2365함수·2945수집**). 둘을 잠근다 (`#1328`). ⑴ **확정 뒤의 전환이 기록된다** — 그리고 ⚠️ **기록 대상을 넓히지 않았는지도 함께 본다**(그 검사가 없으면 「모든 전환을 기록한다」로 만족시킬 수 있고, `record_voyage_confirm`이 세운 판단이 무너진다). ⑵ **코드 ↔ `PRD §8.1` 상태도 ↔ `API_SPEC §3.5` 표**가 같다 — 세 곳이 같은 것을 말하는데 **아무도 대조하지 않아** `DRAFT → CANCELLED`가 코드·화면에만 있었다. **어느 쪽이 틀렸다고 단정하지 않는다**: 갈렸다는 사실을 드러내고 판단은 사람이 한다. ⚠️ 파서가 `[*] --> DRAFT`를 전환으로 세지 않는지와 **읽은 집합이 비어 있지 않은지**를 먼저 본다. 돌연변이 4종 **4/4 검출**이며 **두 쌍이 서로의 반대쪽**을 잡는다(기록 누락 ↔ 과잉 기록 · 정본에서 뺌 ↔ 코드에 더함). 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1328) |
| 2026-09-20 | `#1404` | §14.2 **`test_validation_message_canon_sync.py` 신설 6함수** · 합계 실측 갱신(174파일·2365함수·2945수집 → **175파일·2371함수·2951수집**). 잠그는 것은 **VAL 문구 정본 틀 ↔ 실제 422 응답**이다 (`#1329`). 표는 문장이 아니라 **틀**이므로 글자 비교가 아니라 **틀이 만드는 모양**을 본다. ⚠️ **두 입구(JSON·CSV)가 같은 말을 하는지**도 본다 — 한 규칙에 두 문장이 있으면 사용자에게는 두 규칙이다. ⚠️ **정본이 없는 문구를 들고 있지 않은지**까지 본다(`PRD §17.3`이 그랬다). 함께 `test_error_message_language.py`를 넓혔다 — `snake_case`만 찾던 동안 `from`·`to`·`sort`·`got`·`cursor`·`limit`·`seed`가 **밑줄이 없다는 이유로** 빠져나갔고(감사 4건 외에 **8건을 더 찾았다**), 허용 집합은 **정본 라벨에서 유도한다**(손으로 적으면 두 곳이 갈린다). ⚠️ 종전 검사 하나(`test_error_points_at_the_row_the_user_sees`)의 단언을 **행 번호로 좁혔다**(`AGENTS §4.6` — 정본 인용 표시가 없어 「테스트가 낡은」 경우다). 돌연변이 3종 **3/3 검출**. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1329) |
| 2026-09-20 | `#1406` | §14.2 **`test_auth_token_copy_sync.py` 신설 5함수** · 합계 실측 갱신(175파일·2371함수·2951수집 → **176파일·2376함수·2959수집**). 잠그는 것은 **토큰 경로의 문구·상태 코드 ↔ 정본**이다 (`#1326`). 문구는 `PRD §6.3` 표에서 **읽어서** 대조한다 — 검사에 문장을 또 적으면 정본이 바뀔 때 **한 곳만 고쳐도 검사가 낡은 문장을 지킨다**. ⚠️ **두 상수가 같은 문장이 아닌지**도 본다: 같은 상수를 가리키면 대조가 통과하고 **그 상태가 바로 종전의 결함**이었다. ⚠️ 상태는 **헬퍼 시그니처**로 본다 — 호출 모양(`_error(request, 502, …`)만 찾으면 **뒤쪽 인자로 넘길 때 빠져나간다**(돌연변이 4종 중 이 형태만 처음에 통과했다). 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1326) |
| 2026-09-20 | `#1408` | §14.2 `test_annual_simulation_read_db.py` 46 → **47함수** · 합계 실측 갱신(176파일·2376함수·2959수집 → **176파일·2377함수·2960수집**). 잠그는 것은 **확정분과 잔여분이 상보**라는 것이다 (`#1323`). 종전에는 잔여를 `도착 예정 > as_of`로 잘라 **도착 예정이 지난 `INCLUDE_AS_PLAN` 항차가 어느 쪽에도 들지 않았다**(실측 등급 **D → C**). ⚠️ **집합이 아니라 개수를 센다** — 「잔여에 들어왔다」만 보면 **확정분이 같은 항차를 함께 세는 이중 계상**을 놓치고, `PRD §12`의 연말 예상은 두 집합이 **상보일 때만** 성립한다. 돌연변이 2종(절단 복원 · 정책 필터 제거) **2/2 검출**이며 **두 방향이 서로의 반대쪽**을 잡는다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1323) |
| 2026-09-20 | `#1409` | §14.2 **`test_weather_limits_canon_sync.py` 신설 4함수** · 합계 실측 갱신(176파일·2377함수·2960수집 → **177파일·2381함수·2974수집**). `TECH_SPEC §3.3.2`의 Hs↔BN 표가 **바로 위의 산식과 맞지 않았다** — 표를 손으로 베끼는 대신 `beaufort_number`를 돌려 경계를 얻어 대조하므로 산식이 바뀌면 문서가 낡았다는 사실이 **여기서 먼저** 드러난다. ⚠️ 표만 맞추고 **문장**을 두면 읽는 사람은 문장을 읽으므로 「적용 한계」 문장의 숫자도 함께 보며, 정정 각주가 옛 문구를 **인용**하는 것은 정상이라 `#1345`를 적은 줄은 제외한다(`#1339` README 검사와 같은 규칙) (#1345) |
| 2026-09-20 | `#1410` | §14.2 **`test_simulation_speed_canon_sync.py` 신설 10함수** · 합계 실측 갱신(177파일·2381함수·2974수집 → **178파일·2391함수·2984수집**). 문구만 맞추면 **다음 사람이 코드를 고칠 때 문서가 조용히 낡으므로** 정본의 주장 셋을 **엔진을 돌려** 확인한다 — 속도 폭을 10배로 늘려도 분위수·등급확률이 그대로인가, **연료 폭은 달라지는가**(대조군이 없으면 엔진이 죽어 있어도 통과한다), `SPEED` 행이 `parameter_hash`에 실리는가. `§12.6`의 ±1kn이 프로파일에서 오지 않는다는 것은 **`analyze_sensitivity` 서명에 `profile`이 없다**로 못 박는다 — 호출 모양 정규식은 인자 순서가 바뀔 때 놓친다(`#1326`에서 그 형태를 놓쳤다). 돌연변이 5종 **5/5 검출** (#1346) |
| 2026-09-20 | `#1411` | §14.2 **`test_progress_distance_cap_db.py` 신설 15함수** · 합계 실측 갱신(178파일·2391함수·2984수집 → **179파일·2406함수·2999수집**). ⚠️ **픽스처가 실제로 넘치는지 먼저 본다** — 넘치지 않는 입력이면 나머지가 **상한이 없어도 전부 통과**한다. 거리가 **정확히** 계획값인지와 **`Decimal` 정밀도 문맥에 기대지 않는지**(`prec=8`)를 함께 보며, 네 곳(⑴ YTD · ⑵ 항차 구간값 · 선대 요약 · 리포트)이 같은 값을 말하는지와 **HTTP 응답**까지 덮는다. ⚠️ **종전 검사 둘이 「값이 무한히 자란다」에 기대고 있었다** — `test_cii_current_db`·`test_fleet_summary`의 진행 중 항차가 3,000nm(14kn로 8.9일)라 비교 시점 둘이 **모두 상한 뒤**로 가 값이 같아졌다. 단언을 약화시키지 않고 **계획 거리를 늘려 원래 보려던 구간을 되돌렸다**(상한 전이면 값이 종전과 같다). 돌연변이 5종 **5/5 검출** (#1321) |
| 2026-09-20 | `#1412` | §14.2 **`test_chat_tool_defects_db.py` 신설 11함수(14수집)** · 합계 실측 갱신(179파일·2406함수·2999수집 → **180파일·2417함수·3013수집**). 네 결함이 서로 다른 층인데 **한 화면에서 같이 드러난다.** ⚠️ **⑵와 ⑶은 함께 고쳐야 한다** — ⑶만 고치면 **화면과 같은 `1.2%`가 전부 폐기**되고 ⑵만 고치면 지어낸 `7%`가 **여전히 무검사**다. ⑷는 **화면 경로가 남기는지를 먼저** 본다(대조군이 없으면 `0 == 0`으로 **엔진이 죽어도 통과**한다). 돌연변이 7종 **7/7 검출**, 그중 둘은 **과잉 수정 쪽**을 막는다 — 무시 목록 전체 삭제(정상 응답 폐기)와 화면 경로 저장 중단(계산 이력 소실). **한 방향만 보는 검사는 고치다 더 나빠진 것을 통과시킨다** (#1334) |
| 2026-09-20 | `#1413` | §14.2 **`test_erasure_paths_db.py` 신설 13함수** · 합계 실측 갱신(180파일·2417함수·3013수집 → **181파일·2430함수·3027수집**). ⚠️ **저장소 함수만 보면 라우트가 끊겨도 통과한다** — 돌연변이(탈퇴 라우트에서 호출 한 줄 제거)가 **처음에 빠져나갔고**, HTTP 검사 3건을 더해 잡았다(`#1321`·`#433`과 같은 자리). 기한 삭제가 **살아 있는 대화까지 지우지 않는지**도 함께 본다 — 새 경로가 생겼다고 넓어지면 사용자가 쓰는 중에 사라진다. 서비스 이름은 문서가 아니라 **compose 파일에서 읽어** 대조한다. 함께 `test_audit_actions_db.py`의 정리 SQL을 고쳤다 — PostgreSQL `::text` 캐스트라 CUBRID에서 **한 행도 지우지 못했고**(`app_user.id`는 대시 없는 hex 32자, `audit_log.user_id`는 `str(uuid)`), 그 실행은 통과하고 **다음 실행이 깨졌다**. CI는 매번 새 DB라 드러나지 않는다. 돌연변이 6종 **6/6 검출** (#1330) |
| 2026-09-20 | `#1419` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`fleet-reduction/apiProvider.test.ts` +3). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **「계획이 N개뿐」과 「아직 다 주지 않았다」가 다른 모양인가**다 (`#1395`). `#1367`이 서버에 커서를 붙인 뒤 화면은 `meta.has_more`를 읽지 않아 **첫 페이지만 받고 그 사실을 말하지 않았다** — 21번째 계획이 셀렉트에 뜨지 않았고 화면은 그것이 전부인 것처럼 보였다. 이 자리는 `<select>`라 `reports/apiProvider.listVoyages`(`#627`)와 같은 판단을 따른다 — **「더 보기」가 아니라 끝까지 부른다**(셀렉트는 한 번 열린다). ⚠️ **무한 루프를 페이지 상한으로 막지 않는다** — 임의의 상한은 그 너머를 **조용히 자르고**, 화면은 전부 보여 준다고 주장하면서 일부를 감춘다. 대신 **커서가 전진하지 않으면 중단**한다(서버가 같은 커서를 다시 주는 것은 계약 위반이고 그때만 무한해진다). 구버전 서버(`meta` 없음)가 한 번만 부르는지도 함께 본다 (#1395) |
| 2026-09-20 | `#1428` | §14.2 **`test_audit_log_read_db.py` 신설 12함수** · **§14.5 `IT-AUDIT-002` 면제 행 삭제** · 합계 실측 갱신(181파일·2430함수·3027수집 → **182파일·2442함수·3039수집**). 면제 행은 *「감사 로그를 읽는 경로가 아직 없다」*고 적은 것이고 **이 PR이 그 이유를 없앴다** — `tests/test_case_id_sync.py`가 「이미 테스트가 있는데 면제 표에 남아 있다」로 잡았다. ⚠️ **이 검사는 자기 행만 본다** — `audit_log`는 세션 seed·다른 검사가 함께 쓰는 표이고 삭제하지 않으므로 전체 건수를 단언하면 **실행 순서에 따라 깨진다**. 시각도 **벌려** 심는다(같은 시각이면 정렬 단언이 커서 2차 키에 기대는 우연이 된다). ⚠️ **현장직 403은 여기서 보지 않는다** — `test_roles_db.py`가 `API_SPEC §1.2` 표의 모든 경로를 두드리며 이 경로도 그 목록에 넣었다. **역할 하네스를 두 곳에 두면 한쪽만 고쳐진다** (#1241) |
| 2026-09-20 | `#1429` | §14.2 **`test_annual_impact_db.py` 신설 13함수** · 합계 실측 갱신(182파일·2442함수·3039수집 → **183파일·2455함수·3052수집**). 정본 출력 표의 **한 행이 통째로 비어** 있던 자리다. 고정하는 것은 ⑴ **항차 CII와 다른 값인가**(항차 등급을 그대로 `after.rating`에 넣는 구현이 통과하지 못한다) ⑵ **`before`가 `§2.14` ⑶과 글자 그대로 같은가**(조립이 둘이면 두 화면이 다른 숫자를 낸다) ⑶ 거리가 길수록 더 끌리는가(부호가 뒤집히면 화면이 정반대를 말한다) ⑷ 기초 자료가 없으면 `null`인가 ⑸ **해시가 바뀌지 않는가**다. ⚠️ **단일 유종만 보면 질량가중 CF의 차이가 드러나지 않는다** — 돌연변이(첫 유종의 CF)가 그렇게 빠져나갔고 **순서를 뒤집어** 보는 검사로 잡았다. ⚠️ 또 다른 돌연변이는 **제 가드가 죽은 갈래**임을 드러냈다(분모 0의 `ValueError`가 이미 덮는다) — 지웠다. 돌연변이 5종 **5/5 검출** (#1338) |
| 2026-09-20 | `#1474` | §14.2 `test_url_normalize.py` 4 → **5함수** · 합계 실측 갱신(183파일·2455함수·3052수집 → **183파일·2456함수·3053수집**). 잠그는 것은 **URL 인코딩된 CUBRID 비밀번호의 `%xx`가 Alembic ConfigParser interpolation으로 오해되지 않는가**다(`#1201`). GitHub Actions secret 누락을 채운 뒤 `deploy-app`가 실제 Alembic 단계까지 갔고, 그 자리에서 `invalid interpolation syntax`가 드러났다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1201) |
| 2026-09-20 | `#1476` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`reports/ReportsView.test.tsx` +7). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **보고서가 상단바의 선박·항차 선택을 따르는가**다 (`#1414` · `DESIGN_SYSTEM §7.2` 🔒 「패널 간 유기적 데이터 연동」) — 셸 선택이 초깃값이 되는지, 여기서 바꾸면 셸로 되돌아가는지, 상단바에서 지우면 따라 비우는지, 셸이 삭제된 배를 기억하면 비우고 안내하는지, **완료 전 항차는 채우지 않고 이유를 말하는지**. ⚠️ **「지웠을 때 따른다」는 「있다가 비었다」만 본다** — 셸 밖 렌더(기존 검사 8건)에서는 늘 비어 있으므로 「비었다」로 비우면 사용자가 고른 값이 사라진다. 기존 8건이 그대로 통과하는 것이 그 확인이다. 돌연변이 6종 **6/6 검출** (#1414) |
| 2026-09-20 | `#1477` | §14.2 **`test_zz_roundtrip.py` 4 → 5함수** · 합계 실측 갱신(183파일·2456함수·3053수집 → **183파일·2457함수·3054수집**). 운영 DB가 수동 seed(2026-09-15)로 63행을 먼저 받은 뒤 `alembic_version`이 `1c444a5c4819`에 머물러 있어, 첫 자동 배포의 `upgrade head`가 `6c7496c4d122`를 처음 돌며 `uq_fuel_type_code`에 걸린 결함(#1201)의 회귀 테스트다. `stamp`로 그 상태를 재현하며, 수정 없이는 운영 로그와 동일한 `IntegrityError`로 실패한다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1201) |
| 2026-09-20 | `#1478` | §14.2 **`test_compose_env_wiring.py` 16 → 17함수** · 합계 실측 갱신(183파일·2457함수·3054수집 → **183파일·2458함수·3055수집**). 첫 자동 배포가 `APP_ENV` 없이 compose 기본값 `production`으로 떨어져 SMTP 기동 가드에서 죽은 결함(#1201)의 배선 가드다 — `deploy.yml`이 시크릿 읽기·`.env` 렌더·`console` 폴백 세 곳을 고정한다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1201) |
| 2026-09-20 | `#1480` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`vessel-detail/VesselDetail.test.tsx` +5 · `voyage-management/VoyagePanel.test.tsx` +1). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **실시간 CII 입구가 페이지 머리에 있는가**와 **진행 중 항차가 없을 때 누르면 말풍선이 왜·어디서를 말하는가**다 (`#1415` · `DESIGN_SYSTEM §14` v2.15 예외). 말풍선은 누르기 전에 없고, 다시 누르기 · `Escape`(초점이 버튼으로) · 바깥 누르기로 닫힌다. 문구는 표시 문구라 문장이 아니라 **두 사실**(없다 · 항차 기록)을 본다(`AGENTS §4.6`). ⚠️ **jsdom은 레이아웃을 계산하지 않는다** — 「스크롤 없이 보인다」 대신 「`header.vd__head` 안에 있다」를 단언했고, 배치는 화면 확인(1920 · 라이트/다크)으로 봤다. CSV 형식 안내가 접힌 `<details>` 안에 있는지도 함께 본다. 돌연변이 7종 **7/7 검출** (#1415) |
| 2026-09-21 | `#1481` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`realtime-cii/RealtimeCiiView.test.tsx` +2 · `scenario-comparison/ScenarioComparison.test.tsx` +1 · `realtime-cii/warningText.sync.test.ts` 대상 교체). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **면책이 결과 화면에 한 번만 나오는가**다 (`#1416` · `DESIGN_SYSTEM §13` 🔒) — 실시간 CII·항로 비교의 경고 목록이 `REFERENCE_ONLY`를 `displayWarnings()`로 거르는지, 면책과 무관한 경고는 남는지, 면책뿐이면 경고 목록을 그리지 않는지. ⚠️ **종전 항로 비교 검사가 중복을 단언하고 있었다**(「참고용 예측값입니다. 규제 제출용이 아닙니다」가 **보인다**) — 결함을 정상으로 고정한 검사라 뒤집었다. 배너 문구는 정본(`PRD §6.3`)이라 문장이 아니라 **나오는 횟수**를 본다. 실시간 CII의 화면 맞춤 `REFERENCE_ONLY` 문구를 지우며 `warningText.sync.test.ts`의 「화면 맞춤이 공유 맵보다 먼저」 검사를 남은 항목(`COMPLETED_NO_FUEL`)으로 옮겼다. 돌연변이 4종 **4/4 검출** (#1416) |
| 2026-09-21 | `#1482` | §14.2 **`test_deploy_frontend_origin.py` 신설 4함수** · 합계 실측 갱신(183파일·2458함수·3055수집 → **184파일·2462함수·3059수집**). 클라우드 배포가 화면과 API를 **같은 오리진**에 두는지 잠근다(`#1322`). ⚠️ **되돌림이 조용한 것이 핵심이다** — `VITE_API_BASE_URL`을 절대 주소로 한 글자만 되돌리면 혼합 콘텐츠·`Secure` 쿠키 거부·`SameSite=Lax` 세 겹이 한꺼번에 돌아오는데, **배포는 성공하고 `/health`도 200이며 CORS preflight도 통과한다.** 종전 「배포 검증 결과」가 정확히 그 셋만 확인하고 **로그인 성공 항목이 없어**, 로그인 버튼을 눌러 봐야 드러나는 상태였다. 돌연변이 8종 **7종 검출** — 미검출 ⑥(`new URL(path, base)`)은 **동치 변형**이며, `URL.pathname`이 언제나 `/`로 시작해 base 경로가 버려진다는 사실이 **원래 주석의 거짓 근거를 드러냈다**(`AGENTS §2.1`). 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1322) |
| 2026-09-21 | `#1484` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`annual-simulation/AnnualSimulation.test.tsx` +5). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **기본값 있는 입력을 접어도 그 사실이 보이는가**다 (`#1418`) — 네 칸(반복 횟수·seed·실적 보정·대체 연료)이 접힌 「고급 설정」 안에 있고 목표 등급은 밖에 있는지, 요약이 「기본값으로 실행 / n개 바꿈」을 적는지, **반복 횟수 위반이면 펼쳐서 사유를 보이는지**(접힌 칸의 오류는 보이지 않는다), 재현 정보에서 seed 줄과 「이 seed로 다시 실행」은 밖에 남고 스냅샷·계산 이력만 접히는지(`PRD §12.4.3` · `#1053` 40번), seed 안내가 칸 안(placeholder)에 있으면서 `sr-only` 힌트로 낭독에 남는지(`Field`의 `hintHidden`). ⚠️ **이 행은 `#1484`가 머지된 뒤에 적었다** — 그 PR의 마지막 푸시에 들어가지 못했다(`AGENTS §4.1`은 PR을 연 뒤 **그 PR 안에서** 적게 한다). `#1286`이 같은 형태의 누락을 고친 선례이며, 여기서는 다음 PR(`#1487`)이 함께 싣는다. 돌연변이 4종 **4/4 검출** (#1418) |
| 2026-09-21 | `#1487` | §14.2 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`display/format.test.ts` +3 · **`display/timestamp.sync.test.ts` 신설 2**). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **기준 시각을 화면이 직접 포맷하지 않는가**다 (`#1420`) — `formatTimestamp()`가 초를 내지 않고(대시보드 주석의 판단을 올린 것), 브라우저 시간대와 무관하게 **KST**로 적으며(`DESIGN_SYSTEM §11` 「수집 시각(KST)」 · 날짜 경계도 함께 본다), `Date`와 문자열이 같은 결과를 낸다. ⚠️ **가드는 소스를 읽는다** — 형식이 같아지는 순간 두 경로(공용 함수 · 화면이 직접 부른 `toLocaleString`)의 결과가 같아져 **렌더 검사로는 구분되지 않는다**(`#1292`가 문구 사본을 소스로 잡은 것과 같은 이유). 잡는 것은 **날짜·시각을 만드는 호출**뿐이라 `MAX_ROWS.toLocaleString('ko-KR')` 같은 숫자 포맷은 대상이 아니다. 돌연변이 3종 **3/3 검출** (#1420) |
| 2026-09-21 | `#1488` | §14.2 **`test_deploy_demo_seed.py` 신설 4함수** · 합계 실측 갱신(184파일·2462함수·3059수집 → **185파일·2466함수·3063수집**). 배포가 데모 데이터를 **수동 트리거로만** 적재하는지 잠근다(`#1485`). ⚠️ **전제가 틀려 있었다** — 「데모 데이터는 `development`·`test`에서만 적재된다」가 아니라 `seed_demo()`는 **환경을 보지 않고**, 가드는 `seed_demo_user()`(시연 계정) 한 항목 안에만 있다. 배포본에 선박이 0척이던 진짜 원인은 가드가 아니라 **호출 누락**이었다(`deploy.yml`이 부르던 `cii_platform.db.*`는 규제 파라미터 시드 한 줄뿐). 넷을 잠근다 — ⑴ **적재** 호출이 있는가 ⑵ `SEED_DEMO` 조건 안에 있는가 ⑶ `--clear`가 제 입력 뒤에 있는가 ⑷ `--clear` 진입점이 있는가(적재는 덮어쓰지 않는데 시드 시각이 **적재일 기준 상대값**이라 지우고 넣어야 갱신된다 · `#792`). 돌연변이 6종 **6/6 검출** — ①(적재 호출만 지우고 `--clear`는 남긴다)이 1차에 빠져나갔다. 「모듈명이 파일에 있는가」로 보면 **행을 지울 줄만 알고 넣을 줄은 모르는 배포**가 초록으로 통과한다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1485) |
| 2026-09-21 | `#1489` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`fleet/mapCaption.sync.test.ts` **신설 2** · `fleet/FleetMap.test.tsx` +1 · `voyage-cii/VoyageCiiForm.test.tsx` +1). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **안내를 줄여도 사실이 남는가**다 (`#1421`) — 속력 안내가 CII·계획 속력·도착 예정 시각 셋을 모두 말하고(`#1263`이 넣은 두 사실이 축약으로 사라지던 자리다) 입력칸의 설명으로 닿는지, 지도 캡션이 육지와 굵은 테두리를 둘 다 말하는지. **그리고 두 그림의 캡션이 갈리지 않는지**를 새로 본다 — `DESIGN_SYSTEM §9.5` 🔒가 「개략도도 같은 문장을 쓴다」로 닫았는데 지도는 배를 「표」라 부르고 있었다. 자산 유무로 두 그림이 갈려 **한 사용자에게는 하나만 보이므로** 화면을 아무리 봐도 드러나지 않고, 두 캡션이 각자의 파일에 박혀 있어 **한쪽만 고치는 편집이 양쪽 테스트를 모두 통과**했다(`#1091`의 사슬 마지막 칸이 비어 있던 것과 같은 유형). 주석을 먼저 걷어낸 뒤 대조한다 — 두 파일 모두 본문보다 주석에서 「테두리」를 훨씬 자주 말한다. 문구가 아니라 **사실과 동일성**을 보므로 표현은 바꿔도 된다(`AGENTS §4.6`) (#1489) |
| 2026-09-21 | `#1491` | §14.2 **`test_tour_gate.py` 신설 14 · `test_tour_login_db.py` 신설 10함수** · 합계 실측 갱신(185파일·2466함수·3063수집 → **187파일·2490함수·3088수집**). 둘러보기 세션(`#1486`)의 가드다. 🔴 **fail-closed가 핵심** — `TOUR_ACCESS_CODE`가 비면 정답 코드를 넣어도 거절한다. 가입 게이트는 둘 다 비면 **통과**시키므로 그 패턴을 베끼면 **미설정 배포에서 누구나 관리자 세션**을 받는다. 라우트 쪽은 다섯을 더 잠근다 — 스텁이 `POST /auth/login`으로 열리지 않는다 · 재호출이 같은 UUID를 재사용한다 · 강등을 되돌린다 · **탈퇴(`is_deleted`)를 되살린다**(라우트가 PK로 가져와 그 열을 보지 않아, 되살리지 않으면 **탈퇴한 계정이 살아 있는 세션**을 갖는다) · **스텁이 「마지막 관리자」 계수에 들지 않는다**(코드를 비우면 닿을 수 없는 행이라, 세면 역할을 되돌릴 사람이 없어질 수 있다). 돌연변이 5종 중 **3종 검출** — 나머지 둘(`compare_digest`→`==` · 강등 복구 무조건 대입)은 **값 결과가 같은 동치 변형**이라 검사로 가를 수 없다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1486) |
| 2026-09-21 | `#1493` | §14.2 **`test_deploy_env_rendering.py` 신설 3함수** · 합계 실측 갱신(187파일·2490함수·3088수집 → **188파일·2493함수·3091수집**). 배포가 렌더하는 `.env`가 **compose가 쓰는 값을 빠뜨리지 않는지** 본다(`#1475`). 체인은 세 고리인데(`본보기 → compose → deploy.yml의 .env 렌더`) 검사는 **둘까지만** 있었다 — `#1290`이 첫 고리를 메우고 멈췄고, 그래서 `INITIAL_ADMIN_EMAILS`가 본보기에도 compose `environment:`에도 있는데 **배포가 쓰지 않아 항상 빈 값**이었다. ⚠️ **`cat > .env`가 통째로 덮어쓰므로** app-01에 손으로 적어도 다음 배포가 지운다. ⚠️ **증상이 환경에 따라 갈린다** — `production`이면 기동 거부로 로그에 남지만 **`staging`이면 조용히 관리자 0명으로 뜬다**. 배포 기본값이 `staging`이라(`#1478`) 더 조용한 쪽이었고, `role_bootstrap` 독스트링이 그 공백을 미리 적어 두었다. 옛 이름 `INITIAL_OFFICE_EMAILS`를 **렌더하지 않는 것**도 함께 본다(`#1301` — 렌더하면 이름 변경을 알리는 기동 거부가 무의미해진다). 돌연변이 3종 **3/3 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1475) |
| 2026-09-21 | `#1490` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`layout/AppShell.test.tsx` +2 · `layout/AccountMenu.test.tsx` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **상단바가 `§7.2` 배치를 벗어나지 않는가**다 (`#1422`) — `DESIGN_SYSTEM §7.2` 🔒이 상단바를 「전역 컨텍스트(선박·항차) · 알림 · 계정」으로 닫아 두었는데 테마·한/EN 토글 둘이 그 밖에 있었고, 계정 메뉴 안으로 옮겼다. **자리 하나를 지목하지 않는다** — 「테마 토글이 상단바에 없다」로만 적으면 다음에 새 컨트롤이 같은 자리에 붙을 때 아무것도 걸리지 않는다(`§16` 항목 17이 겹침 순서에서 적은 구조다). 상단바 안의 `radiogroup`이 **전부 계정 패널 안에 있는지**를 본다. 옮긴 뒤 **죽지 않았는지**도 함께 본다 — 패널 안에서 테마가 실제로 바뀌고 패널은 열린 채로 남는지, 보이는 라벨이 `aria-labelledby`로 그룹 이름을 맡는지. 돌연변이 3종 **3/3 검출** (#1422) |
| 2026-09-21 | `#1492` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`vessel-registration/VesselRegistration.test.tsx` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **등록 폼의 입력 순서**다 (`#1423`) — 첫 입력이 `imo-number`이고 샘플 선택이 **선종 뒤 · 제원 앞**인지, 샘플을 골라도 **먼저 적은 IMO·선명이 살아남는지**. **자리 하나가 아니라 셋의 앞뒤 관계를 본다** — 「샘플이 첫 칸이 아니다」로만 적으면 **맨 아래로 내려가도 통과**하는데 거기는 안 된다: `applySample`이 선종·제원 여섯 칸을 **조건 없이 덮고 샘플에 값이 없는 칸은 비우므로**, 제원을 다 입력한 뒤에 만나면 그 입력이 통째로 사라진다. 첫 섹션일 때는 안전했던 동작이 **자리를 옮기는 것만으로 파괴적으로 바뀌는** 경우다. 이슈 체크리스트가 적었던 「등록 버튼 위」로 내리는 돌연변이가 여기서 걸린다. 돌연변이 3종 **3/3 검출**. 정본은 바뀌지 않는다 — `UIFLOW 1-2`는 샘플 선택의 **존재**만 규정하고 순서를 정하지 않는다(`#982`) (#1423) |
| 2026-09-21 | `#1494` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`vessel-management/listRules.test.ts` +4 · `vessel-management/VesselManagement.test.tsx` +3). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **칩과 정렬이 같은 것을 세는가**다 (`#1424`) — 미비 선박만 보려면 정렬밖에 없던 자리에 「제원 미비 n」 토글 칩을 뒀는데, 둘이 다른 기준을 쓰면 **「제원 미비 먼저」로 맨 위에 온 배가 필터에서는 빠진다.** 같은 함수를 부르는지가 아니라 **결과가 같은 집합인지**를 본다. **0척에서도 칩이 남아 있고 눌러도 막다른 곳이 아닌지**도 본다: 자리가 사라지면 「그런 기능이 없다」로 읽히고(`§16` 항목 10의 상단바 종 버튼과 같은 판단), `disabled`는 초점 순서에서 빼 있다는 사실까지 지운다(`§14`) — 대신 한 줄이 없다는 사실과 되돌아가는 방법을 말한다(`#1415`가 「비활성 대신 누른 자리에서 답」으로 정한 방향). ⚠️ `#1288`(0건에 위험색을 달지 않는다)은 **이 칩에서 성립하지 않는다** — 색으로 말하는 것이 심각도가 아니라 눌렸는가뿐이라 걷어낼 색이 없다. 0척 글자색을 `--text-muted`로 낮추려다 **`tokens.sync.test.ts`가 막았고**(faint는 문자색 금지 — `§16` 항목 1 ⓐ) 그 자리에서 위 판단으로 바꿨다. 돌연변이 4종 **4/4 검출** (#1424) |
| 2026-09-21 | `#1497` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`auth/AuthShell.test.tsx` +1). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **로그인 면책이 폼 뒤에 오는가**다 (`#1425`) — 카드 맨 위라 로그인하러 온 사람의 첫 시선이 로그인 버튼이 아니라 네 줄짜리 고지에 갔다. `compareDocumentPosition`으로 **DOM 순서**를 본다: 화면 순서와 낭독 순서가 같은 것이 요점이라 CSS가 아니라 문서 순서를 재는 쪽이 맞다. **카드 안**에 있는지도 함께 본다 — 밖으로 내면 회원가입 링크 뒤의 꼬리말로 읽힌다. **문구는 보지 않는다**: `PRD §0.3` 정본이라 이 검사가 잠글 것이 아니고, 노출 여부는 종전 검사가 이미 본다. 정본은 바뀌지 않는다 — `UIFLOW §0`은 면책이 **있을 것**만 요구하고 위치를 정하지 않으며 `DESIGN_SYSTEM §13`의 「결과 화면 하단」은 결과 화면 규정이다. 돌연변이 2종 **2/2 검출** (#1425) |
| 2026-09-21 | `#1499` | **변경 이력 복구 — 이 행은 `#1522`가 늦게 싣는다.** `#1488` 행 되살림(`#1489` PR이 마지막 줄 자리에 덮어썼다) · `#1489` 행의 `#<PR>` → 번호 · 밀린 `#1490`·`#1492`·`#1494`·`#1497` 네 행 추가. 변경 이력만 고친 PR이라 자기 행을 싣지 않았다 — `AGENTS §4.1`(`#1522`)이 그런 PR도 자기 행을 싣도록 정했다(`#142` 선례) |
| 2026-09-21 | `#1500` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`i18n/labelEn.test.tsx` **신설 5** · `i18n/labelEn.sync.test.ts` **신설 2**). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **영문 보조 라벨이 한국어 모드에 나오지 않는가**다 (`#1426`) — `DESIGN_SYSTEM §3` 🔒과 `PRD §4`는 「한국어 기본 + 영문 **약어** 병기」인데 화면의 영문 47곳은 `Dashboard`·`Distance`·`Vessel Name`처럼 **약어가 아닌 일반 단어**였다(순수 약어는 한 건도 없었고, 약어는 단위 칩과 한국어 라벨 안에 산다). **지우는 것이 아니라 조건부로 그리는 것**이라 영어 모드가 여전히 영어로 나오는지를 같은 무게로 본다 — 그러지 않으면 이 변경이 `#1215` 토글을 조용히 망가뜨린다. 화면 이름은 데이터에 영어 이름이 있어 **언어에 맞는 하나**를 고르고(종전에는 언어와 무관하게 한국어가 주 제목이라 영어 모드에서도 제목만 한국어로 남았다 — 토글이 닿지 않던 자리다), 폼·섹션 라벨은 한국어가 하드코딩이라 영어 모드에서만 영문을 남긴다. **소스 가드를 함께 둔다** — 걷은 자리가 13곳이라, 한 곳을 되돌려도 그 화면 검사만 통과하면 아무것도 걸리지 않는다(`#1091`의 사슬 마지막 칸과 같은 유형). 영문 보조 클래스(`…title-en`·`…label-en`)를 쓰는 파일은 전부 `useShowsLabelEn` 게이트를 써야 한다. **예외 목록을 두지 않는다** — 게이트가 필요 없는 자리는 클래스를 아예 쓰지 않는 쪽으로 고쳤다(`#748`이 밟은 길을 피한다). 돌연변이 3종 **3/3 검출**(게이트 제거 · 게이트를 상수로 바꿔치기 · 제목을 두 언어로 되돌리기). 죽은 CSS 5개를 함께 걷었다 (#1426) |
| 2026-09-21 | `#1502` | §14.2 **`test_tour_login_db.py` 10 → 12함수** · 합계 실측 갱신(188파일·2493함수·3091수집 → **188파일·2495함수·3093수집**). 🔴 **둘러보기 계정을 비밀번호 재설정으로 영구 탈취할 수 있던 우회로**를 잠근다(`#1495`). 스텁 계정은 Argon2 형식이 아닌 해시로 `POST /auth/login`을 막아 두는데, 재설정은 **이메일로만 계정을 찾고 해시 형식을 보지 않아** 스텁에도 토큰을 발급했고 확정되면 Argon2 해시가 되어 **그때부터 비밀번호로 열린다** — `TOUR_ACCESS_CODE`를 비워도 닫히지 않는다. ⚠️ **응답이 계정 없을 때와 같아야 한다**는 것도 함께 단언한다 — 다르게 내면 「이 주소는 스텁」이 드러나고 그것이 이 라우트가 지키려는 계정 존재 비노출과 같은 성질의 누출이다. 두 번째 검사는 **이미 바뀐 해시를 다음 로그인이 되돌리는지**다(막기 전에 바뀐 행이 배포본에 남아 있을 수 있다). 돌연변이 4종 **4/4 검출** — 과잉 수정(재설정 응답을 다르게 내기)도 잡힌다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1495) |
| 2026-09-21 | `#1503` | §14.2 **`test_deploy_frontend_origin.py` 4 → 6함수** · 합계 실측 갱신(188파일·2495함수·3093수집 → **188파일·2497함수·3095수집**). 🔴 **`API_ORIGIN`이 IP 리터럴이 아닌지**와 **배포가 그 값을 시크릿에서 렌더하는지**를 잠근다(`#1496`). Cloudflare 공식 문서가 *「Workers 서브리퀘스트는 URL로만 보낼 수 있고 IP로는 보낼 수 없다」*로 적는데 `#1322`가 IP를 박아 두었고, 토큰이 등록돼 프런트가 처음 배포된 직후 **실측에서 `error code: 1003`(Direct IP access not allowed)으로 403**이 났다. ⚠️ **이것도 조용하다** — 배포는 성공하고 화면은 200으로 뜬다(정적 자산은 Pages가 그대로 내준다). 끊기는 것은 `/api/*`뿐이라 `#1322` 이전(혼합 콘텐츠)과 **화면에서 구분되지 않는다**. 터널 호스트명은 커밋 시점에 알 수 없으므로 저장소에는 자리표시자만 두고, **미설정이거나 IP처럼 보이면 배포가 멈춘다.** 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1496) |
| 2026-09-21 | `#1504` | §14.2 **`test_compose_env_wiring.py` 17 → 18함수** · 합계 실측 갱신(188파일·2497함수·3095수집 → **188파일·2498함수·3096수집**). **`deploy.yml`이 요구하는 시크릿이 `OPERATIONS.md §5` 표에 있는지**를 보는 가드다 — `#1201`(필수 9종)·`#1479`(`CLOUDFLARE_API_TOKEN`)·`#1496`(`API_ORIGIN`)이 **전부 같은 모양**이었다: 워크플로는 값을 요구하는데 등록 목록에 이름이 없었다. ⚠️ **산문은 보지 않는다** — `API_ORIGIN`은 `§3.5` 본문에 설명까지 있었지만 `§5` 표에 없었고, 등록하는 사람이 여는 것은 그 표다. 돌연변이(표에서 행 제거) 검출 확인. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1496) |
| 2026-09-21 | `#1505` | §14.2 **`test_tour_policy_db.py` 신설 7함수** · 합계 실측 갱신(188파일·2498함수·3096수집 → **189파일·2505함수·3103수집**). 둘러보기를 **로그인 화면 상시 버튼**으로 열면서(`TOUR_PUBLIC`) 그 세션을 **읽기 전용**으로 묶은 건이다. ⚠️ **가드를 라우트 의존성이 아니라 인증 미들웨어에 걸었다** — 쓰기 라우트 상당수가 `get_current_user`를 주입받지 않아(예: `vessels.py`는 `require_csrf`만) 의존성으로 걸면 **새 라우트가 늘 때마다 조용히 빠진다**. ⚠️ **민감 조회는 메서드로 걸리지 않는다** — `GET /auth/users`(가입자 이메일)·`GET /audit-logs`는 별도 차단 목록으로 막는다. 검사는 **양방향**이다 — 읽기 200과 대조군(일반 관리자 통과)이 없으면 「전부 막은 구현」이 통과한다. 돌연변이(미들웨어 가드 제거) **4/7 검출**. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1486) |
| 2026-09-21 | `#1501` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`fleet-reduction/FleetReduction.test.tsx` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **감축 계획 표의 선박명이 한 줄로 고정되고, 잘려도 이름을 잃지 않는가**다 (`#1427`) — 「샘플 로로 여객선 (25,000 GT)」이 넉 줄로 꺾여 행 높이가 들쭉날쭉했고, 감속률 슬라이더가 행마다 다른 높이에 놓였다. CSS는 jsdom에서 계산되지 않아 「보이는 줄 수」를 잴 수 없으므로, 규격을 지는 클래스가 이름 칸에 붙어 있는지와 **접근성 이름·`title`이 전체 이름인지**를 본다 — 뒤엣것이 말줄임의 진짜 위험이다. `title`은 `#1424`에서 툴팁을 거부한 것과 모순이 아니다: 말줄임은 그리기일 뿐 DOM을 자르지 않아 이름이 툴팁에만 있는 정보가 아니다. 돌연변이 3종 **3/3 검출**(CSS 규칙만 지우는 것은 `deadCss`가 잡는다). ⚠️ **이 행은 `#1501`이 머지된 뒤에 적었다** — 그 PR의 마지막 푸시에 들어가지 못했다(`AGENTS §4.1`). `#1484`→`#1487` 선례대로 다음 PR(`#1417`)이 함께 싣는다. (#1427) |
| 2026-09-21 | `#1507` | §14.2 **`test_tour_policy_db.py` 7 → 9함수** · 합계 실측 갱신(2505함수·3103수집 → **2507함수·3105수집**). 🔴 **배포에서 공개 둘러보기가 열리지 않았다** — `TourLoginRequest.code`의 `min_length=1`이 빈 코드를 **스키마에서 먼저 잘라** `tour_is_public()` 판정까지 닿지 못했다. 화면의 상시 버튼이 보내는 모양이 바로 그것이라 버튼이 조용히 죽었다. 하한을 없애되 **꺼진 상태에서 빈 코드가 거절되는 것**을 함께 고정한다 — 그 짝이 없으면 하한 제거가 문을 여는 변경으로 읽힌다. 행 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1486) |
| 2026-09-21 | `#1508` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`scenario-comparison/ScenarioComparison.test.tsx` +5 · `scenario-comparison/requestRules.test.ts` +3). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **항로 비교 입력이 필수·위치·고급 셋으로 갈리고, 접힌 고급의 상태가 겉에서 보이는가**다 (`#1417`) — 13칸이 `<fieldset>` 없이 한 평면에 놓여 비워도 되는 칸과 비우면 계산이 안 되는 칸이 같은 무게였다. 요약이 「기본 규칙으로 계산 / n개 입력함」을 말하고(`#1418`과 같은 판단 — 기상 모델은 빈 칸이 아니라 `NONE`이 기본이라 따로 센다), 고급 칸에 오류가 나면 스스로 펼치는지, 목적항이 `#1454`대로 필수가 아니라 위치 묶음에 있는지, 결과 카드에 계약 코드(`SLOW_STEAMING`)가 없는지를 본다. ⚠️ **jsdom은 닫힌 `<details>` 안의 칸도 찾아 준다** — 라벨로 칸을 찾는 기존 검사 31곳이 펼치지 않고도 통과한 이유라, 접힘·자동 펼침·겉의 표시를 따로 잠근다. 화면 확인에서 `<details>` 자체의 `display: grid`를 Chromium이 안쪽 배치에 쓰지 않아 칸이 한 줄로 쌓인 것을 안쪽 `div`로 옮겨 고쳤다. 돌연변이 4종 **4/4 검출**. ⚠️ **이 행은 `#1508`이 머지된 뒤에 적었다** — PR 번호는 PR을 연 뒤에야 생기므로, 이후로는 **각 PR이 직전 PR의 행을 싣는다**(`#1453` PR이 싣는다) (#1417) 〔`#1522` — 「직전 PR이 싣는다」 방식은 폐기했다. 행은 그 PR 자신이 싣는다(`AGENTS §4.1`)〕 |
| 2026-09-21 | `#1509` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`annual-simulation/AnnualSimulation.test.tsx` +1 · `annual-simulation/targetDefault.sync.test.ts` 신설 3). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **연간 시뮬레이션의 목표 등급 기본값이 `C`이고, 그 값이 `PRD §12.2` 표·예시와 같은가**다 (`#1453`) — 화면은 `B`를 기본으로 두었고 PRD는 표와 예시가 서로 달랐다. 기본값을 한 상수(`TARGET_DEFAULT`)가 소유하고, 선택 칸의 초깃값과 요청 본문의 `target_rating`이 그 값을 쓰는지, 소스 가드가 PRD의 표 행과 예시 JSON을 읽어 상수와 대조하는지를 본다. 돌연변이 3종 **3/3 검출**. ⚠️ **이 행은 `#1509`가 머지된 뒤 `#1455` PR이 싣는다** — 각 PR이 직전 PR의 행을 싣는 규칙이다 (#1453) 〔`#1522` — 「직전 PR이 싣는다」 방식은 폐기했다. 행은 그 PR 자신이 싣는다(`AGENTS §4.1`)〕 |
| 2026-09-21 | `#1510` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`pages/SignupPage.test.tsx` 신설 2 · `features/auth/disclaimerScreens.sync.test.ts` 신설 5). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **회원가입 화면에 면책 문구가 켜져 있고, 인증 화면들이 켜는 면책이 `UIFLOW §0` 표와 같은가**다 (`#1455`) — `0-1`이 「면책 문구」를 구성 요소로 적는데 화면은 로그인에만 켜 두었고, `AuthShell` 주석도 「로그인 화면만」이라 **코드와 주석은 맞고 정본과만 달라** 어떤 검사에도 걸리지 않았다. 화면 검사는 면책이 카드 안·가입 버튼 뒤에 있고(`#1425`와 같은 자리) 소개 블록은 없는지를, 소스 가드는 `UIFLOW §0` 행마다 「면책 문구」 유무와 그 화면 파일의 `disclaimer` 깃발을 **양방향**으로 대조한다 — 정본이 적지 않은 비밀번호 찾기·이메일 인증에 켜는 것도 어긋남이다. 돌연변이 3종 **3/3 검출**. ⚠️ **이 행은 `#1510`이 머지된 뒤 `#1498` PR이 싣는다** — 각 PR이 직전 PR의 행을 싣는 규칙이다 (#1455) 〔`#1522` — 「직전 PR이 싣는다」 방식은 폐기했다. 행은 그 PR 자신이 싣는다(`AGENTS §4.1`)〕 |
| 2026-09-21 | `#1512` | §14 인벤토리 수치 변화 없음 — `test_doc_cross_refs.py` **10함수 그대로**, 기존 검사 `test_변경_이력에_PR_번호가_비어_있지_않다`를 넓혔다 (`#1498`). 종전 검사는 커밋 열에서 `#___`라는 **문자열 하나**를 찾아, `#1489`의 행이 초안 이름표 `#<PR>`을 단 채 main에 들어갔을 때 통과했다. 이제 **성질**을 본다 — ① `#` 뒤에는 숫자가 온다(`#___` · `#<PR>` · `#TBD` · `PR #`) ② 칸이 `#숫자` 또는 커밋 해시를 가리킨다(빈 칸 · `—`). 여덟 정본의 기존 변경 이력 801행(초기 커밋 해시 · `PR #423` 표기 · `⑵`·`(2차)`·`후속` 꼬리 포함)이 모두 통과한다. 돌연변이 7종 **7/7 검출**, 정상 꼬리 대조군은 통과. ⚠️ **행이 사라지는 덮어쓰기는 여전히 잡지 않는다** — 행 수가 그대로라 현재 파일만 보는 검사로는 원리상 볼 수 없고, PR diff를 보는 워크플로가 필요하다(`#1498` 체크리스트 5 · 열린 채로 둔다). ⚠️ **이 행은 `#1513`이 싣기로 했으나 그 PR의 충돌 해결에서 빠졌다 — 바로 위 경고의 실례다.** `#1451` PR이 다시 싣는다 (#1498) |
| 2026-09-21 | `#1513` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`styles/grid.sync.test.ts` 신설 3). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **셸 폭 산술이 Figma 변수끼리, 그리고 `DESIGN_SYSTEM §7.1`과 닫히는가**다 (`#1450`) — `§7.1`은 외곽 여백 0을 전제한 `240 + 24 + 1656`, Figma `grid/content-width` · `grid/margin`은 `#707` 이전 값(1680 · 32)이었고, 두 변수는 코드가 읽지 않아 어긋남이 화면에 드러나지 않았다. 가드는 `margin + gnb + gutter + content + margin = frame-width` · `§7.1` 그리드 표 세 행 · 산술 문장을 본다. 돌연변이 3종 **3/3 검출**. ⚠️ **이 행은 `#1513`이 머지된 뒤 `#1451` PR이 싣는다** (#1450) |
| 2026-09-21 | `#1514` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`fleet-reduction/layout.sync.test.ts` 신설 2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **감축 계획의 1단 전환점이 표 최소 폭에서 계산한 값보다 작지 않은가**다 (`#1451`) — 종전 1100은 표와 무관하게 다른 화면에서 온 값이라 약 1100~1350 구간에서 7/12 칸이 열 6개 표(`min-width: 560px`)보다 좁아 가로 스크롤이 났다. 가드는 셸 토큰(`§7.1`) · 카드 안여백 · 테두리 · 그리드 gap에서 두 단이 되는 가장 좁은 뷰포트를 다시 계산해 **세로 스크롤바 폭(15px)까지** 전환점(1365)이 품는지, 그리고 `frame-min`(1440)에서는 두 단인지 본다. 돌연변이 4종 **4/4 검출**(1100 복귀 · 표 640 · 과잉 1500 · 스크롤바 미반영 1360). ⚠️ **이 행은 `#1514`가 머지된 뒤 `#1498` PR이 싣는다** (#1451) |
| 2026-09-21 | `#1518` | §14.2 **`test_changelog_rows_script.py` 신설 8함수**(11수집) · 합계 실측 갱신(189파일·2507함수·3105수집 → **190파일·2515함수·3116수집**). 고정하는 것은 **정본 변경 이력 행이 PR에서 사라지면 CI가 막는가**다 (`#1498`) — `test_doc_cross_refs.py`는 현재 파일만 보므로 **덮어쓰기**(`#1488` — 행 수가 그대로)와 **충돌 해결에서 빠진 행**(`#1512` — base에 없던 행)을 원리상 볼 수 없었다. `scripts/check_changelog_rows.py`가 행을 (날짜, 커밋 열)로 식별해 base 대비 줄어든 행과 PR 커밋에 있었는데 결과에 없는 행을 찾고, CI `lint` 잡(이미 required)의 한 단계로 `fetch-depth: 0`에서 돈다. 실제 이력에 돌려 `#1489`와 `#1513`의 두 사고를 잡고 정상 PR 셋은 통과하는 것을 확인했다. 머지 뒤 첫 PR에서 그 단계가 실행돼 통과했다. 돌연변이 5종 **5/5 검출**. ⚠️ **이 행은 `#1518`이 머지된 뒤 `#1452` PR이 싣는다 — 이제 이 행이 빠지면 그 가드가 잡는다** (#1498) |
| 2026-09-21 | `#1520` | §14.2 함수 수 갱신 — `test_parameters_api_db.py` 15 → **20** · `test_audit_log_read_db.py` 12 → **15** · `test_parameter_import_db.py` 16 → **17** · 합계 실측 갱신(190파일·2515함수·3116수집 → **190파일·2524함수·3125수집** — `#1518` 머지 뒤 기준). 고정하는 것 셋이다 (`#1515`) — ⑴ **`?active`의 기본이 종전과 같은 목록**이고 `false`만 이행 행을 여는가. 여는 쪽이 계산으로 새면 대체된 기준선으로 등급이 나오므로, 저장소 갈래(인자 없음)가 여전히 활성만인지 **동작으로**, `active_only=`를 넘기는 곳이 조회 서비스 하나뿐인지 **소스를 훑어** 본다 — 개정이 한 번도 없던 DB에서는 동작 검사가 아무것도 못 잡는다(`#834`가 같은 자리를 같은 방법으로 잠갔다) ⑵ 감사 `actor`가 이름·이메일로 풀리고 **탈퇴 계정도** 풀리며 못 찾으면 `null`인가 ⑶ 적재 감사 `details.source_refs`가 고유·정렬 목록인가. §14.2 표 갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1515) |
| 2026-09-21 | `#1541` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`scenario-comparison/ScenarioComparison.test.tsx` +5 · `voyage-cii/vesselCatalog.test.ts` +1 · `vessel-management/listRules.test.ts` +1). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **항로 비교 입력칸이 고른 배의 제원으로 채워지는가**다 (`#1538`) — 종전에는 `initialFormState()`의 고정 데모 값(12.8 kn · 26.88 t/일)이라 어느 배를 골라도 같았고, 그대로 비교하면 다른 배의 숫자로 계산한 결과가 그 배 이름으로 나왔다. 셸의 선박 목록 응답에 이미 있는 제원 세 칸을 `VesselOption.spec`으로 싣고, 제원을 모르는 선택지(`undefined`)와 값이 빈 배(`null` — 칸을 비운다)를 가른다. 배마다 한 번만 채워 같은 배에서 고친 칸은 남고, ⚠️ 배를 바꾸면 앞 배의 값이 남지 않는지를 본다. 선박 관리 경고는 서버 동작(`_resolve_reference_speed` · `_resolve_base_daily_foc`)대로 기준속도가 비면 「실패」, 일일 연료만 비면 「직접 입력」으로 갈랐다. 돌연변이 6종 **6/6 검출**. ⚠️ **이 행은 `#1541`이 머지된 뒤 `#1539` PR이 싣는다** (#1538) |
| 2026-09-21 | `#1543` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`annual-simulation/annualRules.test.ts` +3 · `annual-simulation/AnnualSimulation.test.tsx` 1 수정). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **연간 등급 관리의 「목표까지 줄여야 하는 양」이 `DESIGN_SYSTEM §4.2`대로 적히는가**다 (`#1539`) — 종전에는 서버의 그램 값(`required_cut_gco2`)을 그대로 `2785954859 g`로 적어 자릿수를 세어야 읽혔고, 연료는 2자리(`894.65 t`)였다. `reductionCutText`가 g → t를 **소수점 이동(여섯 자리)**으로 하고 `DISPLAY_DIGITS` · `DISPLAY_UNITS` · `formatGrouped`로 `2,786.0 tCO₂` · `894.7 t`를 만든다. 1톤 미만의 앞자리 0과, ⚠️ 부동소수로 나누면 뭉개지는 반올림 경계(`1149999.9999999999 g` → `1.1 tCO₂`)를 문자열로 본다(`§4.1`). 돌연변이 4종 **4/4 검출**. ⚠️ **이 행은 `#1543`이 머지된 뒤 `#1540` PR이 싣는다** (#1539) |
| 2026-09-21 | `#1545` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`realtime-cii/RealtimeCiiView.test.tsx` +3 · `voyage-management/VoyagePanel.test.tsx` +3 · `vessel-detail/VesselDetail.actuals.test.tsx` 신설 +2 · `voyage-management/voyageRules.test.ts` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **실시간 CII에서 그 항차 실적 입력까지 한 번에 닿는가**다 (`#1540`) — 종전에는 실시간 CII가 「도착 실적을 입력하면 확정됩니다」라고 말하면서 입력 경로가 없어, 선박 상세로 돌아가 항차 목록에서 같은 항차를 찾아야 했다. 「이 항차 실적 입력」이 `voyageActualsPath`(`/vessels/<선박>?actuals=<항차 id>`)로 가고, `VesselDetail`이 그 값을 `VoyagePanel`에 넘겨 **진행 중 · 완료 항차면**(`canEnterActuals`) 폼을 연 채 시작해 첫 칸에 초점을 둔다. 남은 거리 0이면 채움 버튼이다. 보내는 쪽과 받는 쪽이 쿼리 이름으로 이어지므로 경로 문자열을 **값으로** 고정하고, 주소 값이 패널까지 닿는지를 패널 대역으로 따로 본다. 돌연변이 8종 **8/8 검출**. ⚠️ **이 행은 `#1545`가 머지된 뒤 `#1549` PR이 싣는다** (#1540) |
| 2026-09-21 | `#1550` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`data-quality/DataQuality.test.tsx` +2 · `voyage-management/VoyagePanel.test.tsx` +6). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **데이터 점검의 항차 행이 그 항차 카드로 데려가는가**다 (`#1549`) — 종전에는 모든 행이 선박 상세 맨 위로 가서 페이지 중간의 항차를 다시 찾아야 했다. 항차 행은 `voyageActualsPath`로 가고(경로를 값으로 고정), 선박 단위 행은 선박 상세 그대로다. 받는 쪽은 `#1540`이 입력 가능한 항차에만 주던 스크롤·초점을 **모든 상태로** 넓혀, 입력을 못 여는 항차는 카드 자체(`tabIndex=-1` — 데려온 카드만)에 초점을 둔다. 데려갈 항차가 목록에 없으면 다음 페이지 유무에 따라 말하고, 목록을 못 받았으면 오류만 말한다. 돌연변이 9종 **9/9 검출**. ⚠️ **이 행은 `#1550`이 머지된 뒤 `#1551` PR이 싣는다** (#1549) |
| 2026-09-21 | `#1552` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`voyage-management/voyageRules.test.ts` +15 · 1 수정 · `voyage-management/VoyagePanel.test.tsx` +7). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것 둘이다 (`#1551`) — ⑴ **항차 카드마다 채움 버튼이 많아야 하나이고 맨 앞인가.** `primaryAction`이 정방향 다음 전환 · 실적이 모자라면 「실적 입력」 · 그 밖은 없음을 고르고, 실적이 아닌 사유(기준연도)로 막히면 「실적 입력」을 주 버튼으로 두지 않는다. 「실적 입력」은 열리면 채움을 내리고, 취소는 텍스트 버튼 「이 항차 취소」다 ⑵ **실적 확정 가드를 누르기 전에 보는가.** `actualsShortage`가 서버 `_guard_actual_data`와 같은 조건(완료 → 확정: 연료 실적 **전부** > 0 · 실제 거리 > 0, 0은 입력이 아니다)을 두어 종전의 「눌러 보고 422」를 없앴다. 돌연변이 13종 중 **12/12 검출 · 동치 1**(주 전환과 다른 비취소 전환이 함께 있는 상태가 전환표에 없어 순서 돌연변이는 구별할 수 없다). ⚠️ **이 행은 `#1552`가 머지된 뒤 `#1553` PR이 싣는다** (#1551) |
| 2026-09-21 | `#1554` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`annual-simulation/annualRules.test.ts` +5 · `annual-simulation/AnnualSimulation.test.tsx` +4). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **연간 등급 관리가 어느 배 · 어느 조건으로 계산했는지 화면에 적는가**다 (`#1553`) — 종전에는 대상 선박이 상단바 전역 선택인데 이름이 입력에도 결과에도 없어, 결과 카드만 보고는 어느 배의 숫자인지 알 수 없었다. 실행 조건 머리에 읽기 전용 대상 선박(`targetVesselText` — 미선택 · 목록 오는 중 · 이름 모름을 가르고 id를 내보이지 않는다), 결과 맨 위에 「이 결과의 조건」 한 줄(`resultConditionsText`). ⚠️ 결과 줄은 **실행 시점의 값**이다 — 목표 등급은 실행 뒤 바꿔도 결과를 지우지 않으므로(`#1094`) 지금 고른 값을 적으면 결과와 어긋난다. 돌연변이 8종 **8/8 검출**. ⚠️ **이 행은 `#1554`가 머지된 뒤 `#1555` PR이 싣는다** (#1553) |
| 2026-09-21 | `#1567` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 바뀌었다**(`realtime-cii/realtimeRules.test.ts` +7 · −1 · `realtime-cii/RealtimeCiiView.test.tsx` +5). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **실시간 CII가 연말 예상을 한 곳에서 한 문장으로 말하는가**다 (`#1555`) — 종전에는 YTD 카드의 「현재 누적 → 연말 예상」 전이(등급의 방향)와 연말 예상 카드의 추세 문구(값의 방향)가 떨어진 두 자리에서 「유지」와 「나빠진다」로 어긋났다. YTD 카드는 현재 누적 등급만, 연말 예상 카드는 `projectionSentence`가 등급과 값을 한 문장으로 적는다(값은 `§4.3` ▲▼ · 부호, 차이는 **표시 3자리에서** `subtractFixed`로 — 원본 차를 반올림하면 화면 두 값과 말이 어긋나는 경계를 값으로 고정했다). YTD 「기준 대비」는 스케일 바를 그릴 때 바 마커 한 곳에만 둔다. 쓰지 않게 된 `RATING_TRANSITION_TEXT`와 그 검사 1건을 지웠다. 돌연변이 10종 **10/10 검출**. ⚠️ **이 행은 `#1567`이 머지된 뒤 `#1569` PR이 싣는다** (#1555) |
| 2026-09-21 | `#1570` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`fleet/fleetRules.test.ts` +8 · `fleet/FleetDashboard.test.tsx` +5). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **대시보드 경고 배너가 한 주제만 말하고 카드가 등급을 되풀이하지 않는가**다 (`#1569`) — 종전 배너 부제 「가장 임박 — … · D등급까지 N일」은 위험 선박(이미 D · E)이 아닌 배를 정의상 늘 가리켰고, 위험 0척이라 배너가 없는 날에는 함께 사라졌다. 요약 행의 「D등급 진입 임박」 칸(`summary.soonest_d_entry` · `daysValueText`)으로 옮기고 ⚠️ 배너 없는 날에도 보이는 것을 고정했다. 이미 D 이하 카드의 「D등급 이하」는 `showsDaysToD`가 걷고 다른 사유 5종은 남긴다. ⚠️ 첫 푸시에서 픽스처의 `risk_reasons: []`가 `never[]`로 추론돼 `tsc -b`(CI 빌드)가 TS2322로 막혔다 — vitest는 타입을 보지 않고 로컬 `tsc --noEmit -p .`는 검사 파일을 포함하지 않아 놓쳤다. `string[]`로 고친 뒤 통과. 돌연변이 7종 **7/7 검출**. ⚠️ **이 행은 `#1570`이 머지된 뒤 `#1571` PR이 싣는다** (#1569) |
| 2026-09-21 | `#1572` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`vessel-detail/CiiHistoryChart.test.tsx` +4). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **선박 상세가 올해 누적 CII를 한 번만 말하는가**다 (`#1571`) — 종전에는 올해 값이 「올해 누적」 카드 · 차트 막대 라벨 · 연도별 표에 세 번 나왔다. 올해(`IN_PROGRESS`) 막대 라벨은 등급 + 「진행 중」(값 없음, 확정된 해는 값), 연도별 표는 「표로 보기」 `<details>` 안(기본 닫힘)이고 차트 `aria-label`이 그 이름을 가리킨다. 차트가 없으면 표를 펼치고, 연료 표는 접지 않는다. 돌연변이 7종 **7/7 검출**. ⚠️ **이 행은 `#1572`가 머지된 뒤 `#1573` PR이 싣는다** (#1571) |
| 2026-09-21 | `#1574` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`fleet/fleetRules.test.ts` +2 · `fleet/UnconfirmedVoyages.test.tsx` 신설 +6 · `fleet/FleetDashboard.test.tsx` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **대시보드가 실적 확정 전 항차의 개수와 입구를 첫 화면에 보이는가**다 (`#1573`) — 종전에는 그 목록이 데이터 점검 표 안에만 있었다. `unconfirmedVoyages`가 `GET /fleet/data-quality`의 `UNCONFIRMED` 중 항차 있는 것만 서버 순서로 · 중복 없이 고르고, 카드는 선대 요약 **바로 다음**에 5건까지 `voyageActualsPath` 입구를 그린다. 0건이면 그리지 않고, 조회 실패는 0건과 섞지 않고 한 줄로 말하며 대시보드 나머지를 막지 않는다. 돌연변이 9종 **9/9 검출**. ⚠️ **이 행은 `#1574`가 머지된 뒤 `#1576` PR이 싣는다** (#1573) |
| 2026-09-21 | `#1577` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`voyage-cii/formRules.test.ts` +10 · `voyage-cii/VoyageCiiForm.test.tsx` +8 · `voyage-management/apiProvider.test.ts` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **CII 예측이 상단에서 고른 항차의 계획 조건으로 입력칸을 채우는가**다 (`#1576`) — 종전에는 선박만 따르고 칸은 비어 있었다. `prefillFromVoyage`가 작성 중 · 계획 확정 항차만 거리 · 속력 · 연료 · 연료량을 채우고(빈 계획값은 비움), 연료가 여러 종이면 연료 칸을 비우고 종 수를 돌려준다. 폼은 항해 중 · 완료 항차와 조회 실패를 안내하고, 항차가 칸을 채우지 않았을 때만 선박 기본 연료를 넣으며, 같은 항차에서 고친 칸을 덮지 않고 늦게 온 앞 항차의 응답을 버린다. `fetchVoyage`는 `GET /voyages/{id}`를 `toVoyage`로 읽는다. 돌연변이 10종 **10/10 검출** · 살아남은 1종은 죽은 가드라 제거 (#1576) |
| 2026-09-21 | `#1579` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`components/DisclaimerBanner.test.tsx` 신설 +3 · `fleet/FleetDashboard.test.tsx` +1 · `vessel-detail/VesselDetail.test.tsx` +1 · `reports/ReportsView.test.tsx` +1 · `annual-simulation/annualRules.test.ts` +3 · `annual-simulation/apiProvider.test.ts` +2 · `annual-simulation/AnnualSimulation.test.tsx` +1). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **결과 화면의 고지가 하단 면책 배너를 되풀이하지 않는가**다 (`#1578`). 대시보드 · 선박 상세의 `PRD §6.3` 「추정값 사용」 문장은 배너 한 칸의 둘째 문장(`DisclaimerBanner estimate`)이고, 보고서 안내는 「내부 보고용입니다」만 말한다. 연간 등급 결과 위 고지(`DESIGN_SYSTEM §11` 화면 단위 고지)는 「예측값」을 걷고 추정의 전제와 기준 시각(`meta.as_of` · `formatTimestamp`)을 말하며, provider는 `meta.as_of`가 없으면 키를 만들지 않는다. 돌연변이 10종 **10/10 검출** (#1578) |
| 2026-09-21 | `#1581` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`data-quality/DataQuality.test.tsx` +4 · 1 수정 · `annual-simulation/AnnualSimulation.test.tsx` +1 · 1 보강). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **표 안에서 같은 안내를 줄마다 되풀이하지 않는가**다 (`#1580`). 데이터 점검 CII 영향 칸은 짧은 말과 사유별 고정 표시(「비교 불가*」 · 「계산 불가**」)만 두고, 그 표에 나온 사유만 정해진 순서로 표 아래 한 번 적는다. 모르는 사유 코드는 칸에 그대로 · 각주 없음. 연간 등급 민감도는 `NO_REMAINING_VOYAGES`면 표와 `interaction_note` 없이 안내 한 줄, 잔여가 있으면 표와 설명 그대로. 돌연변이 9종 **9/9 검출** (#1580) |
| 2026-09-22 | `#1582` | AT-AUTH-001에 **없는 계정 로그인의 가짜 해시 검증 호출** 단언 추가 · §14 `test_auth_api.py` 21 → **22함수** · 합계 실측 갱신(2524함수·3125수집 → **2525함수·3126수집**). `API_SPEC §1.2`가 「같은 소요시간」을 로그인 하나로 좁히면서 그 보증의 근거가 `verify_dummy_async` 호출 하나가 됐다 — 호출을 지워도 응답 문구는 같아 기존 「구분 불가」 검사는 통과한다(돌연변이로 확인). 벽시계 비교는 CI 부하에 흔들려 호출을 단언한다 (#1405) |
| 2026-09-22 | `#1587` | §14 `test_db_session_param_convert.py` 13 → **15함수** · 합계 실측 갱신(2525함수·3126수집 → **2527함수·3128수집**). 변환기 치환 단언 3건을 **「고쳐 쓰지 않는다」**로 바꾸고 소스 가드 2종(`src/`의 `.is_(True/False)` 호출 · `CAST(:이름 AS …)`)을 더했다. 치환을 걷기 전에 **스위트 전체를 세었다** — 기준 `cast=71 bool=16` 중 운영 경로는 `auth.py` 세 곳뿐, 나머지는 테스트 생 SQL·단위 검사 문장이었다. 합계는 `conftest.py`가 스위트 끝에 찍는다 (#1316) |
| 2026-09-22 | `#1588` | §3.13에 **IT-REPORT-005(G5 미반영 고지)** · IT-REPORT-003 기대 결과의 낡은 「이상 없음」→「해당 없음」(`#1052` ⓶이 09-18에 바꾼 판정어 — 코드·`PRD §25.3`은 이미 「해당 없음」) · §14 `test_reports_db.py` 40 → **41함수** · 합계 실측 갱신(2527함수·3128수집 → **2528함수·3129수집**) (#762) |
| 2026-09-22 | `#1589` | §14 `test_dashboard_seed.py` 18 → **21함수** · 합계 실측 갱신(2528함수·3129수집 → **2531함수·3132수집**). 관찰 대상 선박(벌크 30,000)에 **파생 확정 항차**를 더해 실적 보정계수 표본을 채운 것을 잠근다 — 표본 수 · 대시보드 분포 **전체**(기존 검사가 부등식이라 한 칸이 움직여도 통과했다) · 보정계수 `1.037681`. 반영 전에 변경 전/후를 실행으로 재어 불변 셋(분포·위험 2척 · Fixture 1 비적중 · 분포 비고정)을 확인했다 (#1299) |
| 2026-09-22 | `#1591` | §10.1 `lint` 행에 **변경 이력 삭제 감지** 단계(`fetch-depth: 0` · 직전 푸시 head · 라벨) · §14 `test_changelog_rows_script.py` 8 → **16함수** · 합계 실측 갱신(2531함수·3132수집 → **2539함수·3140수집**) · 「직전 PR이 싣는다」 3행(`#1508`~`#1510`)에 폐기 각주 · 빠진 `#1499` 행. 검사 키를 **커밋 열 참조**로 바꿔 정상 편집 셋(날짜 정정 · 꼬리 · 자기 행 날짜)의 오탐을 없애고, 리베이스로 푼 충돌에서 자기 행이 빠지는 **사각**을 직전 head로 잡는 것을 고정한다 (#1522) |
| 2026-09-22 | `#1586` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`parameters/yearCatalog.test.ts` +6 · `parameters/yearScope.sync.test.ts` 신설 +8 · `data-quality/DataQuality.test.tsx` +1 · `voyage-cii/VoyageCiiForm.test.tsx` · `scenario-comparison/ScenarioComparison.test.tsx` 기대 순서 수정 · `reports/reportRules.test.ts` −5 이동). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **연도 선택지가 모든 화면에서 최신 연도부터이고, 조회 화면만 올해까지인가**다 (`#1584`). 규칙은 `yearCatalog.displayYears` 한 곳이고 `useYearOptions(…, { throughCurrentYear })`가 적용한다. `yearScope.sync.test`가 훅을 부르는 화면마다 조회(데이터 점검 · 보고서 · CSV 내보내기 · 감축 계획) · 계획(CII 예측 · 연간 등급 · 항로 비교) 중 어느 쪽인지 잠그고, 어느 쪽에도 없는 화면을 잡는다. 돌연변이 10종 **10/10 검출** (#1584) |
| 2026-09-22 | `#1599` | **변경 이력 행 보충 — `#1586`(`#1584`)의 행을 싣는다** (`#1597`). `#1586`은 `#1591`(`AGENTS §4.1` 「행은 그 PR 자신이 싣는다」)보다 늦게 머지됐는데 종전 방식대로 「다음 PR이 싣는다」로 남겨 두어 자기 행이 없었다. `#1591`이 `#1509` · `#1499` 행을 채운 방식과 같다. 검사 변화 없음 (#1597) |
| 2026-09-22 | `#1601` | §14.2에 **`test_api_spec_request_fields_sync.py`(19함수) 신설** · 합계 실측 갱신(190파일·2551함수·3159수집 → **191파일·2570함수·3198수집**). `API_SPEC` 요청 표 8곳 ↔ 요청 스키마를 양방향·필수 여부까지 대조하고 모든 요청 모델이 어느 대조에든 드는지 본다 (#1523) |
| 2026-09-22 | `#1603` | §14 `test_chat_tools.py` 10 → **11함수** · `test_chat_explain.py` 8 → **9함수** · 합계 실측 갱신(2570함수·3198수집 → **2572함수·3200수집**). 챗봇 도구 `run_annual_simulation` → `project_year_end` — 확률 시뮬레이션이 아니라 결정론 연말 예상이라는 것을 이름·설명으로 잠그고, 용어 풀이가 「연말 예상」과 「목표 달성 확률」을 숫자 없이 가르는지 본다 (#1534) |
| 2026-09-22 | `#1605` | §14 `test_dashboard_seed.py` 21 → **22함수** · `test_demo_seed_counts.py` 7 → **8** · `test_demo_up_script.py` 29 → **35** · 합계 실측 갱신(2572함수·3200수집 → **2580함수·3212수집**). 시연 시드의 완료 항차 11건을 `CONFIRMED`로 바꾸면서 **완료 항차를 두 상태로 센다** — 확정 전은 벌크 50k 2026-01 하나이고 데이터 점검 이상치와 같은 항차다. `clear_demo`의 저장 계획 전량 삭제와 `demo_up.sh --reseed`를 함께 잠근다 (#1536) |
| 2026-09-22 | `#1606` | §3.13에 **IT-REPORT-006**(진행 중 / 실적 확정 전 두 행) · §14 `test_data_quality_db.py` 15 → **19함수** · `test_reports_db.py` 41 → **43** · 합계 실측 갱신(2580함수·3212수집 → **2586함수·3218수집**). 완결성의 분자·분모·제외 내역(검산 · 한 축 귀속)과 자체 점검의 「진행 중」/「실적 확정 전」 두 행 · 확정 전 건수가 데이터 점검과 같은지를 잠근다 (#1532) |
| 2026-09-22 | `#1609` | §14 `test_changelog_rows_script.py` 16 → **18함수** · 합계 실측 갱신(2586함수·3218수집 → **2588함수·3220수집**). `#1591`이 키를 참조 집합으로 바꾸며 같은 PR의 여러 행(⑼·⑽)이 한 키가 됐고, 「PR 커밋에 있던 행」 검사가 있었나/없나만 봐서 **하나가 빠져도 통과**했다(부분 회귀 · 코드 검토에서 재현). 개수로 보게 고친 것을 잠근다 (#1607) |
| 2026-09-22 | `#1610` | §14 `test_demo_up_script.py` 35 → **36함수** · 합계 실측 갱신(2588함수·3220수집 → **2589함수·3222수집**). `--reseed`가 계산 이력이 참조해 **지우지 못한 행**을 화면에 알리는지(0행이면 조용) 실제 bash로 잠근다 — 그 행은 시각·제원이 갱신되지 않는다 (#1608) |
| 2026-09-22 | `#1612` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`voyage-management/voyageRules.test.ts` +4 · `voyage-management/VoyagePanel.test.tsx` +5 · 1 수정). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **되돌리기 어려운 전환이 한 번 더 묻는가**다 (`#1598` · `API_SPEC §3.5`). `transitionCaution`이 서버 허용 전환 전체 중 확정 되돌리기 · 취소 · 보관만 묻고, 확인 줄은 초점을 「그만두기」에 먼저 두며 그만두기 · Escape는 누른 버튼으로 초점을 돌려준다. 정방향 전환은 바로 간다. 돌연변이 12종 **12/12 검출** (#1598) |
| 2026-09-22 | `#1614` | §14 인벤토리 수치 변화 없음 — **프론트엔드 검사만 늘었다**(`assistant/AssistantOverlay.test.tsx` +7 · `assistant/launcherReserve.sync.test.ts` +2). §14는 백엔드 pytest만 세므로 합계가 바뀌지 않는다. 고정하는 것은 **챗봇 패널이 어느 배로 계산하는지 말하고, 넓은 화면에서 본문을 덮지 않는가**다 (`#1613`). 선박명은 패널에만 보이고 요청에는 id만 간다 · 이름이 없으면 id를 보이지 않는다 · 예시 질문은 입력칸에만 채우고 보내지 않는다 · 패널 폭과 셸이 비우는 폭이 같은 변수다. 돌연변이 10종 **10/10 검출** (#1613) |
| 2026-09-23 | `#1698` | §14 `test_chat_api_db.py` 25 → **27** · `test_llm_provider.py` 10 → **15** · 합계 실측 갱신(2589함수·3222수집 → **2596함수·3232수집**). `GET /chat/status`(로그인·불린·키 비노출)와 자리표시자 키 503, LLM 연결 설정(자리표시자·모르는 인증 방식·기본값 불변·환경변수 이동·버킷 분리)을 잠근다. 수집 수 3232는 `#1535` 브랜치에서 `pytest --collect-only`로 센 값이다 (#1535) |
| 2026-09-23 | `#1702` | §14 `test_chat_tools.py` 11 → **13** · `test_chat_tools_db.py` 14 → **19** · 합계 실측 갱신(2596함수·3232수집 → **2603함수·3239수집**). 도구 `explain_screen_result`가 화면의 실행을 **저장된 값 그대로** 읽는지(항차·시나리오 순서·연간 확률), 다른 선박의 실행을 거절하는지, 없는 실행의 id를 문구에 싣지 않는지, 확률에 화면 백분율을 병기하는지를 잠근다. `project_year_end`는 두 블록(`year_end_projection`·`ytd`)으로 단언을 바꿨다 (#1533) |
| 2026-09-23 | `#1706` | §14 `test_chat_api_db.py` 27 → **29** · 합계 실측 갱신(2603함수·3239수집 → **2605함수·3241수집**). 만료된 대화로 이어 물으면 404이고 **외부 모델 호출 0회·메시지 0건**인지, 만료 경계(`expires_at` = 지금은 만료 · 시간대 없는 값은 UTC)가 청소 조건과 같은지를 잠근다 (#1632) |
| 2026-09-23 | `#1708` | §14 `test_windows_env.py` **신설(5함수)** · 합계 실측 갱신(191파일·2605함수·3241수집 → **192파일·2610함수·3247수집**). Windows 새 환경에서만 깨지던 셋(시간대 데이터 · 변경 이력 스크립트의 Git 출력 인코딩 · 픽스처 생성기의 콘솔 출력)을 Linux에서 좁은 로캘로 재현해 잠근다 (#1665) |
| 2026-09-23 | `#1714` | §14 `test_voyage_cii_service.py` 24 → **28** · `test_data_quality.py` 13 → **14** · `test_fleet_reduction.py` 14 → **15** · 합계 실측 갱신(2610함수·3247수집 → **2616함수·3261수집**). 응답 직렬화 절사를 비율·물리량으로 넓힌 것을 잠근다 — **필드마다** 「전송 절사 → 표시 반올림」 = 「원값 직접 반올림」(결정론 무작위 + 경계값), 반올림으로 남는 필드 = 전송이 표시와 같은 필드뿐, 모든 전송 필드에 표시 자릿수가 적혀 있는지. 종전 「비율·물리량은 반올림 그대로」 단언과 시나리오 앵커 8개·예시 `0.98758`을 절사값으로 바꿨다 (#1600) |
| 2026-09-23 | `#1710` | §14 `test_chat_api_db.py` 29 → **30** · `test_chat_tools_db.py` 19 → **24** · 합계 실측 갱신(2616함수·3261수집 → **2622함수·3267수집**). 도구 `lookup_regulation`이 시드 표의 값을 출처와 함께 그대로 주는지(설정 화면과 같은 조회 서비스), 선박 없이도 도는지, 표에 없는 연도를 다른 해로 채우지 않는지, 모르는 선종·연료를 고정 문구로 거절하는지, 표 값을 인용한 답이 수치 가드를 통과하는지를 잠근다 (#1703) |
| 2026-09-23 | `#1730` | §14 `test_demo_up_script.py` 36 → **38** · 합계 실측 갱신(2622함수·3267수집 → **2624함수·3269수집**). `--check`가 `dev-login`·계산 호출(둘 다 쓰기)을 하지 않는지, 그 두 호출이 6단계의 비-`--check` 분기 안에만 있는지 본다. 수정 전 스크립트로는 첫 검사가 실패한다(실측) (#1639) |
| 2026-09-23 | `#1717` | §14 `test_operations_pages_commands.py` **신설(2함수)** · 합계 실측 갱신(192파일·2622함수·3267수집 → **193파일·2624함수·3269수집**). 수동 Pages 배포 문서가 낡은 별도 오리진·위치 인자 명령으로 돌아가지 않게 잠근다 (#1669) |
| 2026-09-23 | `#1733` | §14 `test_cii_current_db.py` 41 → **42** · 합계 실측 갱신(2622함수·3267수집 → **2623함수·3268수집**). 정박 구간의 연료·배출 몫이 응답에 실리는지(구간만 있고 연료가 없으면 0 · 40t × CF 3.114 = 124.56 tCO₂ · 전체 몫을 넘지 않음) 본다. 응답 계약 목록에도 두 필드를 등재했다 (#1658) |
| 2026-09-23 | `#1760` | §14 `test_workflow_action_pins.py` **신설(3함수)** · 합계 실측 갱신. 워크플로 액션 **18곳을 커밋 SHA로 고정**하고 그것이 되돌려지지 않게 잠갔다(`#1638` · `F-12` 결정). 태그는 움직이므로 「검토한 코드와 실행되는 코드가 같다」를 태그에 맡길 수 없고, 이 저장소의 배포 워크플로는 **GHCR 쓰기 권한과 SSH 개인키**를 쥐고 돈다. 갱신 경로는 막히지 않는다 — Dependabot이 SHA 형식을 읽고 새 SHA로 PR을 연다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1638) |
| 2026-09-23 | `#1721` | **§3.15 위치 스냅샷 · AIS 수집 절 머리의 데모 선박 전제 정정** (`#1662`) — 「5척 모두 합성 IMO」 → 3척 합성 · 2척 실존(항차는 시드가 만든 것). `PRD §21` `[#764]`와 같은 정정이다. 문서 정정이라 버전은 올리지 않는다 (#1662) |
| 2026-09-23 | `#1739` | §14 `test_request_instants.py` **신설(4함수 · 파라미터라이즈로 18수집)** · 합계 실측 갱신(192파일·2622함수·3267수집 → **193파일·2626함수·3285수집**). 항차·시나리오·연간 시뮬레이션의 요청 시각에 **시간대를 요구**하고 UTC로 맞춘다(`API_SPEC §1.11` 신설). 같은 규칙을 CSV 경로는 `#906`이, not under way JSON 경로는 `#1333`이 이미 세웠고 **세 경로만 남아 있었다** — 시간대 없는 값은 읽는 쪽에 따라 다른 순간이라, 배포 호스트의 시간대가 항차 순서·연간 귀속·`as_of` 경계를 바꾼다(`§1.10` 재현성 계약이 서버 설정에 달린다). DB 없이 도는 스키마 경계 검사이며, 한 필드를 `datetime`으로 되돌리는 돌연변이에 **5건이 실패**해 가드가 동작함을 확인했다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1627) |
| 2026-09-23 | `#1749` | **§1.1·§1.5·§1.7의 픽스처 현황을 실제 저장소와 맞춤** (`#1666`). ⑴ **`§1.7` 소관 콜아웃이 정반대를 적고 있었다** — *「생성기와 `tests/fixtures/` 파일은 `#45`에서 만든다. 현재 저장소에 둘 다 없으며, 픽스처를 글자로 대조하는 코드도 0곳이다」*. 셋 다 있다: `scripts/gen_fixtures.py` · 픽스처 5개 · 대조 검사 3개(`test_layer1_fixtures.py`). 같은 종류의 문장을 `§1.2`에서는 `#195`가 이미 지웠고 **이 자리만 남아 있었다** ⑵ `§1.1` 디렉터리 트리가 **없는 픽스처 9개**(`tanker_80000` · `container_50000` · `capacity/` 2 · `api/` 3 · `weather/` 3)를 싣고 **있는 것 하나**(`csv/voyage_import_sample.csv`)를 빠뜨렸다 — 실측으로 교체했다 ⑶ `conftest.py` 주석의 `DB session`·`httpx client`는 실재하지 않는 이름이라 `§1.6` 참조로 바꿨다 ⑷ **`§1.5` Fixture 4는 파일이 없다** — 문자열 `capacity_separation`이 나오는 곳은 이 문서 자신뿐이고, 같은 것을 `test_capacity_rules.py` 19함수가 인라인 값으로 검증한다. 그 사실을 각주로 적고 JSON은 규칙 설명으로 남겼다. 코드·픽스처 값은 건드리지 않았다. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1666) |
| 2026-09-23 | `#1759` | §14 `test_position_snapshot_db.py` **+1함수** · 합계 실측 갱신. **더 오래된 관측이 현재 위치를 덮지 못하는지** 본다(`#1628` · `F-8`). 종전에는 파이썬이 `position_updated_at`을 읽어 비교한 뒤 ORM으로 덮어, 두 적재가 교차하면 **먼저 읽은 오래된 관측이 나중에 커밋되어** 배가 뒤로 갔다. 비교를 `WHERE`로 옮겼으므로 **읽기와 쓰기 사이가 없다** — 두 연결을 띄우지 않는 이유가 그것이며, 조건 자체를 순서대로 불러 확인한다. 같은 시각도 덮지 않는 것(같은 값이다)을 함께 단언한다. 돌연변이(조건 제거) **2건 검출**. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1628) |
| 2026-09-23 | `#1752` | §6 성능 표에 **`PERF-005` 행** · §14 `test_benchmarks.py` 4 → **5함수** · 합계 실측 갱신. `PRD §16.1`의 성능 목표 다섯 중 **초기 페이지 로드만** CI 판정 밖이었다(`#1617`). 200척을 만들어 `GET /fleet/summary`를 100회 재고(warm-up 10회 · `gc.disable()` — 기존 넷과 같은 조건) 끝나면 IMO 대역으로 모아 지운다. **지워졌는지도 단언한다** — 남으면 뒤따르는 검사의 선대 수치가 흔들린다(`PERF-002`가 시나리오·계산 이력에 대해 하는 것과 같다). 로컬 실측 **p95 190.91 ms**(목표 3,000 ms). `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1617) |
| 2026-09-23 | `#1755` | §14 `test_auth_tokens.py` 27 → **28** · 합계 실측 갱신(2634함수·3269수집 → **2635함수·3270수집**). 같은 용도의 인증 토큰 재발급을 **사용자 행 잠금**으로 직렬화한다(`#1630` · `F-8` 결정). 두 요청이 같은 옛 상태를 보고 각자 무효화·발급을 끝내면 **활성 토큰이 두 개** 남는데, 토큰 행은 아직 없으므로 잠글 수 없어 **부모인 사용자 행**을 `SELECT … FOR UPDATE`로 잡는다(`routes/auth._lock_admin_users` 선례). 두 연결을 교차시키는 실제 동시성 검사로 확인했다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1630) |
| 2026-09-23 | `#1713` | **§1.6 재작성 — 「픽스처와 테스트 격리」** (`#1583` · 결정요청 v3 `E-9` 안 「다」). 저장소에 없는 `db_session`·`httpx_client`(「PostgreSQL test container」) 예시를 걷고, `tests/conftest.py`에 실재하는 `migrated_db` · `conn` · `app_fresh_engine` · `load_fixture` · `require_disposable_target` · `_hold_suite_lock`으로 표를 다시 썼다. 두 정리 방식, **커밋하는 검사를 롤백으로 바꾸지 않는 이유**(`#1250` `D-18`), 실행 잠금의 한계, 대상 DB 가드(`#691`)를 한 절에 모았다. 표의 이름은 새 가드 `tests/test_testplan_fixture_names.py`가 `conftest.py`와 대조한다. `§14.2`의 「§5 인프라 · 테스트 격리」 라벨 두 곳을 실제 절(`§1.6`)로 맞췄다 — `§5`는 DB 제약 테스트다. §14에 `test_testplan_fixture_names.py` 행(2함수) · 합계 실측 갱신(192파일·2622함수·3267수집 → **193파일·2624함수·3269수집**). 절 재작성이라 `AGENTS §4.3`상 **v1.27 → v1.28** (#1583) |
| 2026-09-23 | `#1762` | §14 `test_deploy_sha_pinning.py` **신설(4함수)** · 합계 실측 갱신. 배포 워크플로의 원격 두 호스트가 `main` 대신 **이 실행의 커밋**을 받아 가게 하고(`#1633`), 받은 것이 다르면 배포를 멈추게 했다. 종전에는 이미지에 `GITHUB_SHA`를 붙이면서 원격은 브랜치를 받아, **빌드 뒤 머지된 코드가 이미지와 함께 돌 수 있었다.** 멈추면 이전 컨테이너가 남으므로 서비스는 살아 있다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1633) |
| 2026-09-23 | `#1762` | §14 `test_deploy_sha_pinning.py` **신설(4함수)** · 합계 실측 갱신. 배포 워크플로의 원격 두 호스트가 `main` 대신 **이 실행의 커밋**을 받아 가게 하고(`#1633`), 받은 것이 다르면 배포를 멈추게 했다. 종전에는 이미지에 `GITHUB_SHA`를 붙이면서 원격은 브랜치를 받아, **빌드 뒤 머지된 코드가 이미지와 함께 돌 수 있었다.** 멈추면 이전 컨테이너가 남으므로 서비스는 살아 있다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1633) |
| 2026-09-23 | `#1795` | §14 `test_deploy_remote_script_syntax.py` **신설(3함수)** · 합계 실측 갱신(2643함수·3278수집 → **2646함수·3281수집**). `#1762`가 넣은 줄에서 **닫는 큰따옴표가 빠져** 2026-09-23 운영 배포가 멈췄다 — 열린 문자열이 세 줄 뒤까지 삼켜 파싱이 어긋났고 괄호가 있는 줄에서 터졌다. `deploy-db` 실패로 `deploy-app`이 skipped 돼 **서비스는 그대로였다**(오류가 `docker compose up` 전에 났다). `test_deploy_sha_pinning.py`는 **SHA 고정 패턴이 있는지만** 보므로 잡지 못했다 — heredoc 본문을 셸로 읽는 검사가 없었다. 돌연변이(따옴표 제거)로 운영과 **같은 메시지**가 나오는 것을 확인했다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1794) |
| 2026-09-23 | `#1802` | §14 `test_doc_version_sync.py` 3 → **4함수** · 합계 실측 갱신(2646함수·3281수집 → **2647함수·3282수집**). README 문서 구조 표를 고친 PR 일곱이 README 변경 이력에 행을 싣지 않았는데, 기존 검사는 **표의 최종 상태**만 봐서 잡지 못했다. 현재 판본마다 그 문서·판본을 적은 행이 있는지 본다 — 돌연변이(행 삭제) 2종 검출. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1779) |
| 2026-09-23 | `#1808` | §14 `test_annual_simulation_read_db.py` 47 → **50** · `test_cii_current_db.py` 42 → **43** · `test_hashing.py` 29 → **30함수** · `test_hash_fields_doc_sync.py` 선택 키 파라미터 +1 · 합계 실측 갱신(2647함수·3282수집 → **2652함수·3288수집**). 고정하는 것은 **같은 화면의 두 숫자가 같은 사실(이미 쓴 정박 연료)을 같게 세는가**다 — ⑶ 확정분의 정박 CO₂ = ⑴ `not_underway_co2_ton` · `as_of` 뒤의 정박은 빠진다 · 스냅샷에 남고 재현된다 · 기록이 없으면 NULL이고 해시가 종전과 같다. 돌연변이(확정분 가산 제거) 2건 검출 (#1803) |
| 2026-09-23 | `#1816` | §14 `test_voyage_list_order_db.py`(4함수) 등재 · 합계 실측 갱신(198파일·2652함수·3288수집 → **199파일·2656함수·3294수집**). 등록 순서와 출항 순서를 일부러 반대로 넣어 정렬 키 자체를 검증한다 — 돌연변이(`created_at desc`로만 뒤집기) 4건 검출 (#1806) |
| 2026-09-23 | `#1817` | §14 `test_annual_simulation_read_db.py` 50 → **54함수** · 합계 실측 갱신(2656함수·3294수집 → **2660함수·3298수집**). 한 트랜잭션 안의 실행은 `created_at`이 같아 **시각이 아니라 정렬 규약**을 단언한다 (#1805) |
| 2026-09-23 | `#1822` | §3.16에 `IT-MAP-006`·`007` · §14 `test_fleet_route_db.py` 5 → **7함수** · 합계 실측 갱신(2660함수·3298수집 → **2662함수·3300수집**). 지도의 방향이 항로 비교의 입사각과 **같은 함수·같은 값**인지를 본다 — 화면이 따로 계산하면 두 화면이 다른 방향을 말할 수 있다 (#1804) |
| 2026-09-23 | `#1825` | §14 `test_dashboard_seed.py` 22 → **23함수** · 합계 실측 갱신(2662함수·3300수집 → **2663함수·3301수집**). 벌크 50k의 기록 위치(대한해협 · 적재 10일 전)가 5일 전 출항한 진행 중 항차보다 **앞선 시각**이었다 — 기록 위치를 보간 없이 시각과 함께 보이는 화면(`#1672` 결정 A)에서 「출항 전에 항해 중」이 된다. 돌연변이(옛 좌표·시각)로 검출을 확인했다 (#1672) |
| 2026-09-23 | `#1828` | §14 `test_demo_seed_counts.py` 8 → **9함수** · 합계 실측 갱신(2663함수·3301수집 → **2664함수·3302수집**). `#1672`가 고친 시드 위치가 이미 적재한 DB에 들어가지 않았다 — 상태 UPDATE는 `underway_state IS NULL`일 때만이고 초기화는 그것을 비우지 않았다. 돌연변이(초기화 루프 제거) 검출 (#1826) |
| 2026-09-23 | `#1829` | §14 `test_cii_current_db.py` 43 → **54함수** · `test_response_contract_db.py` `/cii/current` 계약에 `drivers`·`drivers[].key`·`drivers[].delta_cii` · 합계 실측 갱신(2664함수·3302수집 → **2675함수·3317수집**). 고정하는 것은 **분해의 합이 응답의 두 문자열 차이와 정확히 같은가**다 — 각 단계 누적값을 먼저 절사한 뒤 빼야 성립하고, 차이를 따로 절사하면 깨진다(돌연변이로 확인). 확정분 집합이 갈리는 상태는 실측에서 만들 수 없어 엔진을 직접 불러 `BASIS_DIFFERENCE`의 자리와 값을 잠근다. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1673) |
| 2026-09-23 | `#1830` | **v1.29 — §4.11 「올해 누적 CII 추이 API」 신설** · §14 `test_cii_ytd_series_db.py`(17함수) 등재 · `test_response_contract_db.py` 계약 표에 `§2.18` 항목(수집 +1) · 합계 실측 갱신(199파일·2675함수·3317수집 → **200파일·2692함수·3335수집**). 지키는 것은 **끝점 동치**다 — 추이의 마지막 실적 점이 `§2.14` `ytd`와, 마지막 계획 점이 `year_end_projection`과 문자 단위로 같아야 한다. 구현이 같은 조립·같은 엔진을 부르므로 구성상 같지만, 정렬하다 항차 하나를 빠뜨리는 종류의 어긋남은 화면이 멀쩡한 채 값만 갈린다. 데모 벌크선 기준값(8.979906 · 8.213830 · 8.965893)을 문자로 박았다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올린다 (#1671) |
| 2026-09-24 | `#1838` | §1.2 `[ORACLE-C-1b]` 각주의 `PRD §14.2` 응답 예시 인용 `0.98758` → **`0.98757`** + 사유 한 줄. `#1714`(`#1600`)가 비율도 전송 자릿수로 절사하며 PRD 예시를 고쳤는데 이 인용은 옛 값 그대로였다 — 읽는 사람이 존재하지 않는 예시를 근거로 삼는다. 픽스처 값 `0.987579`·등급 `C`는 그대로다. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1809) |
| 2026-09-24 | `#1852` | §14 `test_not_underway_crud_db.py` 33 → **36함수** · 합계 실측 갱신(2692함수·3335수집 → **2695함수·3385수집** — 수집 수는 `origin/main` 실측 3382에 이 PR의 +3이며, 종전 3335는 `#1830` 이후 갱신되지 않은 값이었다). 같은 선박의 정박 구간 겹침 검사를 **선박 행 잠금**으로 직렬화한다(`#1629` · `F-8` 결정). 두 연결을 실제로 교차시켜 생성·수정·CSV 가져오기 세 경로에서 **하나만 남고 다른 하나는 409**인지 본다. ⚠️ **교차 시점은 서비스 호출이 끝난 뒤가 아니라 겹침 조회 직후(커밋 전)다** — `create_period`는 스스로 커밋하므로 호출 뒤에 두 번째 세션을 띄우면 잠금 유무와 무관하게 409가 나 돌연변이가 안 보인다(2026-09-22 시도의 미검출 형태 · 정황). 저장소 `find_overlapping`을 감싸 첫 세션만 조회 직후 0.5초 머물게 했다. `conn` 픽스처는 한 연결이라 쓰지 않는다. 돌연변이(잠금 줄 제거)는 로컬 DB가 내려가 있어 실측하지 못했고 CI가 처음 돈다. `AGENTS §4.3`상 행 갱신이라 버전은 올리지 않는다 (#1629) |
| 2026-09-24 | `#1847` | §14.2 `test_dashboard_seed.py` 행의 시연 분포 `A0 B1 C1 D1 E2` → **`A1 B0 C1 D1 E2`**. `#1807`이 STAR SKIPPER의 DWT를 원 출처 값(12,979 · 종전 칸에는 GT 9,520이 들어가 있었다)으로 고쳐 2026 등급이 B → A가 됐고, 같은 PR이 단언(`test_watch_vessel_third_voyage_leaves_the_dashboard_unchanged`)을 갱신했다 — 설명 안의 수치는 가드가 보지 않아 따로 맞췄다. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1807) |
| 2026-09-24 | `#1851` | §3.7 **`IT-AUDIT-004`**(감사 기록 실패 시 원본도 남지 않는다) 신설 · §14.2 `test_audit_actions_db.py` 11 → **16** · `test_voyage_cii_api.py` 32 → **33** · `test_scenario_compare_api.py` 36 → **37** · `test_voyages_api.py` 37 → **38** · 합계 실측 갱신(200파일·2692함수·3335수집 → **200파일·2700함수·3390수집** — 수집 수는 `main`에서 이미 3382였다(`#1830` 뒤 병합분의 파라미터화 · 이 PR 몫은 +8)). 잠그는 것은 **원본과 감사가 하나로 확정되는가**다 (`#1625` · `F-7` 결정). 종전에는 서비스가 원본을 커밋한 **뒤** 라우트가 감사를 따로 커밋해, 감사 INSERT가 실패하면 사용자는 500을 보는데 DB에는 `CONFIRMED`·`calculation_run`이 남았다 — 그 표들은 삭제가 막혀 되돌릴 수 없다. 네 경로마다 `insert_event`를 예외로 바꿔 상태·계산 이력·감사 **셋 다 없는지** 보고, 가짜 세션 검사는 커밋이 **한 번**(종전 둘)인지와 감사 실패 시 0번인지를 센다. **기록 대상이 아닌 전환도 라우트가 커밋하는지** 함께 잠갔다 — 커밋을 서비스에서 라우트로 옮기며 생길 수 있는 구멍이다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1625) |
| 2026-09-24 | `#1850` | §3.1에 **`IT-STATE-009`**(동시 쓰기의 직렬화) 신설 · §14 `test_voyage_row_lock_db.py`(5함수) 등재 · 합계 실측 갱신(200파일·2692함수·3335수집 → **201파일·2697함수·3387수집** — 수집 수는 종전 기재가 낡아 있어 main 실측 3382에 5를 더한 값이다). 항차의 다섯 쓰기 경로가 같은 옛 상태를 읽고 둘 다 통과하던 것을 항차 행 잠금으로 닫았다(`#1626` · `F-8`). 검사의 요점은 **교차 시점**이다 — 서비스가 스스로 커밋하므로 첫 세션의 `commit`을 갈아 끼워 커밋 직전에 머물게 해야 돌연변이가 보인다. 채택은 예외가 아니라 **나중 채택이 남는 것**이 기대값이라 다른 넷과 단언이 다르다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1626) |
| 2026-09-24 | `#1849` | **v1.30 — §3.28 「공개 해상 경로망 위의 바닷길」 신설**(`test_sea_route.py` 17함수 · `#1300` E-6) · §4.2에 `AT-SC-005` 우회 경유지 행 · §14 `test_scenario_compare_api.py` 36 → **45함수** · 합계 실측 갱신(201파일·2708함수·3398수집(#1625·#1629·#1626 머지 뒤) → **202파일·2734함수·3425수집**). 절 신설이라 버전을 올린다(`AGENTS §4.3`) (#1300) |
| 2026-09-24 | `#1854` | §14.2 **`test_trigger_ddl.py`(10함수) 등재** · `test_zz_roundtrip.py` 5 → **7** · 합계 실측 갱신(202파일·2734함수·3425수집 → **203파일·2746함수·3437수집**). CUBRID가 같은 이름의 트리거를 두 번 만드는 것을 막지 않고 중복이 생기면 이름으로는 지울 수 없어(`-503`) 롤백 왕복이 `048` 근처에서 끊기던 결함(`#1373` · 결정요청 v6 `D-20`)의 검사다. 트리거를 만들고 지우는 마이그레이션 14개가 전부 공용 `db/trigger_ddl.py`(있으면 만들지 않고 · 없으면 지우지 않는다)를 지나게 했고, 그 헬퍼의 다섯 계약을 가짜 `op`로 DB 없이 고정했다(리뷰 반영 — upgrade의 교체 `replace_trigger`는 지우지 못하면 멈추고 downgrade만 관용한다는 방향, `-503`의 `errno` 판별). 기대 집합을 세는 스텁은 `tests/migration_stub.py`로 빼 `test_dbschema_head_sync`와 공유하며, `db_trigger` 조회에 만든−지운 집합으로 답해 헬퍼를 지나는 DROP도 실제처럼 집계된다. 왕복 파일에는 **왕복을 돌리기 전에** 보는 둘을 더했다 — 중복 트리거 0건(헬퍼의 `-503` 관용이 중복을 「없음」으로 읽을 수 있어 따로 세야 한다) · head DB의 트리거 이름 집합 = 마이그레이션이 만든다고 적은 집합(합계 160은 `test_dbschema_head_sync`가 보고, 상쇄되는 차이는 여기서만 보인다). 행 추가·갱신이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1373) |
