# TECH_SPEC — CII 예측 및 운항 의사결정 보조 플랫폼

| 항목 | 내용 |
|---|---|
| 문서명 | TECH_SPEC.md |
| 버전 | v1.3 |
| 상태 | Oracle Review + 외부 리뷰 반영 + 서비스 레이어 아키텍처 확정 (#100) + 재현성 계약 명문화 (#102) |
| 최종 수정일 | 2026-07-18 |
| 상위 문서 | `PRD.md` v3.1 |
| 후속 문서 | `API_SPEC.md`, `DB_SCHEMA.md`, `TEST_PLAN.md` |

---

## 0. 범위 및 목적

본 문서는 PRD v3.1에서 TECH_SPEC으로 연기된 기술 항목의 구현 명세를 정의한다.

| 항목 | PRD 참조 |
|---|---|
| 이중 정밀도 계산 엔진 | §9.3.1 |
| Monte Carlo RNG 및 재현성 | §12.4.3 |
| Townsin–Kwon 기상 보정 모델 | §11.4.2, COR-4 |
| Cubic speed model 상세 | §11.4.1 |
| 파라미터 content hash 직렬화 | §7.6 |
| input_hash 결정적 직렬화 | §7.7 |
| 대권거리 계산 | §15.2 |
| 기상 데이터 어댑터 인터페이스 | §15.3 |
| 스냅샷 격리 | §8.4 (ORACLE-R-5) |
| 오류 전파 및 검증 | §9.1 (VAL-001~010), §12.1~12.2, §16.4 |

> 코드 모듈 구조와 계층 간 호출 규칙(서비스 레이어 아키텍처)은 §16에서 정의한다.

---

## 1. 이중 정밀도 계산 엔진

### 1.1 아키텍처 개요

```
┌─────────────────────────────────────────────────┐
│  Layer 1: Deterministic CII Engine (Decimal)     │
│  ─────────────────────────────────────────────── │
│  • attained_CII, required_CII, rating boundary   │
│  • CO₂ 배출량                                     │
│  • bit-exact 재현성 보장                          │
│  • Python Decimal (precision ≥ 30)               │
└────────────────────┬────────────────────────────┘
                     │ CII 결과값 전달 (Decimal → float 변환 시점 명시)
┌────────────────────▼────────────────────────────┐
│  Layer 2: Monte Carlo Engine (float64)           │
│  ─────────────────────────────────────────────── │
│  • 삼각분포 샘플링, 반복, 집계                     │
│  • rating probability, P10/P50/P90               │
│  • seed + RNG 알고리즘 = 4 유효숫자 재현성        │
│  • IEEE 754 double (float64)                     │
└─────────────────────────────────────────────────┘
```

> **[ORACLE-S-2 정정]** Layer 1↔Layer 2 경계에서 Decimal→float 변환은 **명시적인 변환 지점**에서만 수행한다. Layer 1 함수는 Decimal을 반환하고, Layer 2 진입점에서 float로 변환한다. 중간 계산 과정에서 암시적 float 변환을 허용하지 않는다.

### 1.2 Layer 1: Deterministic CII Engine

#### 1.2.1 Decimal 컨텍스트

```python
from decimal import Decimal, getcontext, ROUND_HALF_UP

getcontext().prec = 30        # 최소 30자리 유효숫자
getcontext().rounding = ROUND_HALF_UP
```

| 설정 | 값 | 근거 |
|---|---|---|
| precision | 30 | `14479E10` = 144,790,000,000,000 (15자리) 계산 시 오차 방지 |
| rounding | ROUND_HALF_UP | 화면 표시 반올림과 일관성 |

#### 1.2.2 분수 지수 연산

`CII_ref = a × Capacity^(-c)`에서 `c`가 분수(예: 0.622)이므로 Decimal의 `**` 연산을 사용할 수 없다. 다음 변환을 사용한다:

```python
def decimal_power(base: Decimal, exp: Decimal) -> Decimal:
    """
    base^exp = exp(ln(base) * exp)
    Decimal.ln()와 Decimal.exp()를 순차적으로 호출.
    precision은 getcontext().prec를 따른다.
    """
    return (base.ln() * exp).exp()
```

| 연산 | Decimal 메서드 | 정밀도 |
|---|---|---|
| ln(x) | `x.ln()` | context.prec |
| exp(x) | `x.exp()` | context.prec |
| sqrt(x) | `x.sqrt()` | context.prec |

> **주의**: Decimal의 ln/exp는 해당 context precision 내에서 정확하다. 동일 precision 설정을 사용하는 동일 언어 구현체 내에서는 bit-exact 재현성을 보장한다. 언어 간(예: Python ↔ Java) cross-platform bit-exact 재현은 보장하지 않는다.

#### 1.2.3 Fixture 1 검증 수식

> **[ORACLE-S-4 정정]** 중간 계산값의 산술 오류를 수정했다. 최종 결과값은 동일하다.

```text
입력:
  ship_type = BULK_CARRIER, DWT = 50,000, year = 2026
  fuel = HFO (CF = 3.114), fuel_consumed = 80 ton, distance = 1,000 nm

Layer 1 계산:
  M = 80 × 1,000,000 × 3.114 = 249,120,000 gCO₂
  W = 50,000 × 1,000 = 50,000,000 dwt·nm
  attained_CII = 249,120,000 / 50,000,000 = 4.9824 gCO₂/dwt·nm

  CII_ref = 4745 × 50,000^(-0.622)
    ln(50,000) = Decimal('10.819778284410286...')
    10.819778284410286 × 0.622 = 6.729902092903198...
    exp(6.729902092903198) = Decimal('837.065307...')
    CII_ref = 4745 / 837.065307 = Decimal('5.668613856...')

  required_CII_2026:
    Z = 11% → (1 - 0.11) = 0.89
    required_CII = 5.668613856 × 0.89 = Decimal('5.045066331...')

  boundaries:
    superior = 5.045066331 × 0.86 = 4.338757045
    lower    = 5.045066331 × 0.94 = 4.742362351
    upper    = 5.045066331 × 1.06 = 5.347770311
    inferior = 5.045066331 × 1.18 = 5.953178271

  rating: attained_CII (4.9824) ≤ upper (5.347770311) → C
```

#### 1.2.4 Capacity 결정 규칙 (이중 분리)

> **[EXT-P0-1]** IMO G1과 G2는 서로 다른 capacity 개념을 사용한다. 단일 `get_effective_capacity()`를 두 함수로 분리한다.

```python
def resolve_transport_capacity(vessel) -> Decimal:
    """
    G1 (MEPC.352(78)): attained CII transport work용 capacity.
    항상 선박의 실제 DWT 또는 GT를 반환한다. fixed override 없음.
    """
    if vessel.ship_type in DWT_BASED_SHIP_TYPES:
        return Decimal(str(vessel.deadweight))
    else:
        return Decimal(str(vessel.gross_tonnage))

def resolve_reference_capacity(vessel, reference_line) -> Decimal:
    """
    G2 (MEPC.353(78)): reference CII 공식용 capacity.
    reference_line.capacity_rule에 따라 fixed 값을 사용할 수 있다.
    """
    rule = reference_line.capacity_rule  # "DWT", "GT", "fixed 279000"
    if rule.startswith("fixed "):
        return Decimal(rule.split(" ")[1])
    elif rule == "DWT":
        return Decimal(str(vessel.deadweight))
    elif rule == "GT":
        return Decimal(str(vessel.gross_tonnage))
    else:
        raise ValueError(f"Unknown capacity_rule: {rule}")
```

`transport_capacity`는 W(transport work) 계산에만, `reference_capacity`는 CII_ref 계산에만 적용된다. `condition_expr`(예: `DWT ≥ 279,000`)는 실제 DWT/GT로 평가하여 어느 파라미터 행을 선택할지 결정한다.

> **오차 예시**: 300,000 DWT 벌크캐리어에서 fixed 279,000을 W에 잘못 적용하면 attained CII가 +7.5% 과대 산정된다.

#### 1.2.5 Layer 1 출력 가드

> **[ORACLE-MISS-2 추가]** 모든 Layer 1 최종 결과값은 저장·전달 전에 유한성 검증을 수행한다.

```python
def validate_layer1_result(value: Decimal, name: str) -> Decimal:
    """Layer 1 출력값이 finite한지 검증."""
    if not value.is_finite():
        raise ValueError(
            f"Layer 1 result '{name}' is not finite: {value}. "
            f"Check input parameters for NaN/Infinity propagation."
        )
    return value
```

검증 대상: `attained_CII`, `required_CII`, `superior_boundary`, `lower_boundary`, `upper_boundary`, `inferior_boundary`, `co2_emission_g`.

### 1.3 Layer 2: Monte Carlo Engine

상세 사양은 §2를 참조.

---

## 2. Monte Carlo RNG 및 재현성

### 2.1 RNG 알고리즘 선택

> **[ORACLE-C-1 정정]** `numpy.random.default_rng()`는 PCG64( not PCG64DXSM)를 사용한다. PCG64DXSM을 명시적으로 생성해야 한다.

| 항목 | 사양 | 근거 |
|---|---|---|
| 난수 생성기 | NumPy `Generator` with **PCG64DXSM** BitGenerator | NumPy 권장 업그레이드 경로. 통계적 품질 향상 |
| API | `numpy.random.Generator(numpy.random.PCG64DXSM(seed))` | **`default_rng()` 사용 금지** — default_rng는 PCG64를 생성함 |
| 정밀도 | IEEE 754 double (float64) | Decimal 대비 ~100배 빠름. p95 < 3초 목표 충족 |
| 삼각분포 | `Generator.triangular(left, mode, right, size)` | SciPy `scipy.stats.triang`과 parameterization이 다르므로 혼용 금지 |

> **참조**: NumPy NEP 19에 따라 Generator API는 버전 간 bit-for-bit 호환성을 보장하지 않는다. 따라서 동일 NumPy 버전 내에서의 재현성을 보장하며, `model_version`에 버전을 명시한다.

### 2.2 Seed 정책

#### 2.2.1 Seed 생성 및 저장

```python
import secrets
import json
import platform
import numpy as np

def create_rng(seed: int | None = None) -> tuple[np.random.Generator, dict]:
    """
    PCG64DXSM 기반 Generator 생성.
    default_rng()를 사용하면 PCG64가 생성되므로 주의.
    """
    if seed is None:
        seed = secrets.randbits(128)

    # [ORACLE-C-1] 명시적으로 PCG64DXSM BitGenerator 생성
    rng = np.random.Generator(np.random.PCG64DXSM(seed))

    metadata = {
        "seed_entropy": f"{seed:#034x}",     # 128-bit hex
        "bit_generator": "PCG64DXSM",        # [ORACLE-C-1] hardcoded string
        "numpy_version": np.__version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    return rng, metadata
```

#### 2.2.2 Seed 저장 스키마

`CalculationRun.result_json` 내 `rng_metadata` 필드:

```json
{
  "rng_metadata": {
    "seed_entropy": "0x000000000000000000000000003039",
    "bit_generator": "PCG64DXSM",
    "numpy_version": "2.1.0",
    "python_version": "3.12.4",
    "platform": "Linux-6.5.0-x86_64"
  }
}
```

#### 2.2.3 병렬 스트림

Monte Carlo를 병렬화하는 경우 `SeedSequence.spawn`을 사용한다:

```python
parent_ss = np.random.SeedSequence(seed)
child_seeds = parent_ss.spawn(n_workers)
# [ORACLE-C-1] 각 worker도 PCG64DXSM 사용
streams = [np.random.Generator(np.random.PCG64DXSM(s)) for s in child_seeds]
```

spawn tree 구조를 `rng_metadata.spawn_tree`에 기록한다.

> **주의**: 병렬 Monte Carlo에서 부동소수점 비결정성을 방지하기 위해, 각 worker의 결과를 배열로 수집한 후 단일 스레드에서 deterministic reduction(pairwise summation, 고정된 index 순서)으로 집계한다.

### 2.3 삼각분포 샘플링

#### 2.3.1 규격

```python
def sample_triangular(rng, plan_value: float, params: dict) -> float:
    """
    params = {
        "min_ratio": 0.90,   # min = plan_value × min_ratio
        "mode": None,        # None이면 plan_value
        "max_ratio": 1.15,   # max = plan_value × max_ratio
    }
    """
    # [ORACLE-S-1] plan_value = 0 방지
    if plan_value <= 0:
        raise ValueError(
            f"plan_value must be > 0 for triangular sampling, got {plan_value}"
        )

    mode = params.get("mode") or plan_value
    left = plan_value * params["min_ratio"]
    right = plan_value * params["max_ratio"]

    # 물리적 가드 (§12.4.1)
    left = max(left, 0.0)
    if left > mode:
        left = mode
    if right < mode:
        right = mode

    return float(rng.triangular(left, mode, right))
```

#### 2.3.2 변수별 분포 파라미터

| 변수 | min_ratio | mode | max_ratio | 추가 가드 |
|---|---|---|---|---|
| 거리 (nm) | 0.97 | plan | 1.05 | min > 0 |
| 연료 (ton) | 0.90 | plan | 1.15 | min > 0 |
| 속도 (kn) | — | plan | — | min = max(plan - 1, 1.0), max = plan + 1 |

> 속도는 min/max를 ratio가 아닌 절대 오프셋(`plan ± 1kn`)으로 정의하며, 최소값 floor는 1.0kn이다.

#### 2.3.3 SciPy 혼용 금지

| 라이브러리 | API | Parameterization |
|---|---|---|
| NumPy (사용) | `rng.triangular(left, mode, right)` | `left ≤ mode ≤ right` |
| SciPy (금지) | `scipy.stats.triang.rvs(c, loc, scale)` | `c = (mode - left) / (right - left)`, `loc = left`, `scale = right - left` |

동일 seed로 두 라이브러리를 사용하면 결과가 다르다. NumPy `Generator.triangular`만 사용한다.

### 2.4 Rounding 정책

| 단계 | 정밀도 | Rounding |
|---|---|---|
| Monte Carlo 내부 (샘플링, CII 계산) | float64 | 변환 없음 |
| Monte Carlo 집계 (rating probability) | float64 → Decimal 변환 | 소수점 4자리 ROUND_HALF_UP |
| 최종 사용자 표시 (결정론 CII) | Decimal | PRD §9.3 표시 기준 |

```python
from decimal import Decimal, ROUND_HALF_UP

def round_probability(p: float) -> Decimal:
    return Decimal(str(p)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
```

### 2.5 재현성 검증

#### 2.5.1 Canonical Test Vector

CI에서 실행하는 환경 검증 스크립트:

```python
# canonical_rng_vector.py
import numpy as np

CANONICAL_SEED = 12345
EXPECTED_UNIFORM_5 = [
    0.9320816903198763,
    0.3375056011176768,
    0.21698197019501064,
    0.3527062497665462,
    0.5501051021142127,
]  # numpy==2.1.0, PCG64DXSM(seed=12345) 기반 실측값 — NumPy 2.1.0에서 검증 완료

def validate():
    # [ORACLE-C-1] PCG64DXSM 명시적 생성
    rng = np.random.Generator(np.random.PCG64DXSM(CANONICAL_SEED))
    draws = [float(rng.random()) for _ in range(5)]
    for i, (actual, expected) in enumerate(zip(draws, EXPECTED_UNIFORM_5)):
        assert abs(actual - expected) < 1e-15, (
            f"RNG mismatch at index {i}: {actual} != {expected}. "
            f"NumPy version or platform may have changed."
        )
```

#### 2.5.2 환경 핀닝

재현성이 필요한 환경에서는 다음을 고정한다:

| 항목 | 방법 |
|---|---|
| NumPy 버전 | `requirements.txt`에 `numpy==2.1.0` 명시 |
| Python 버전 | Docker 이미지 또는 pyenv로 고정 |
| OS/Arch | Docker 컨테이너 사용 권장 |
| BLAS/LAPACK | Monte Carlo 내부에 BLAS 의존 연산이 없으므로 영향 없음 |

---

## 3. Townsin–Kwon 기상 보정 모델 (TOWNSIN_KWON_ALPHA)

### 3.1 개요

본 모델은 기상(파고, 풍속)이 선박 속도에 미치는 영향을 경험식으로 추정하여 `weather_factor`를 산정한다. PRD §11.4.2에서 `MAY` 우선순위로 지정되었으며, 구현 시 `실험 모델` 배지를 표시해야 한다.

| 항목 | 내용 |
|---|---|
| 모델명 | TOWNSIN_KWON_ALPHA |
| 원논문 | Townsin, R.L. & Kwon, Y.J. (1982), "Approximate formulae for the speed loss due to added resistance in wind and waves", RINA Transactions |
| 단순화 참조 | Kwon, Y.J. (2008), "Speed loss due to added resistance in wind and waves", The Naval Architect, RINA (March 2008) |
| 적용 범위 | MVP: head sea (β = 0°) 우선. 임의 입사각은 향후 확장 |

### 3.2 기본 수식

Townsin–Kwon 모델의 속도 손실률:

```text
ΔV/V (%) = Cβ × CU × Cform
```

| 기호 | 의미 | 단위 |
|---|---|---|
| ΔV/V | 속도 손실률 | % |
| Cβ | 방향 감소 계수 (wave heading angle) | 무차원 |
| CU | 속도 감소 계수 (Beaufort Number, ship type) | 무차원 |
| Cform | 선형 계수 (block coefficient 기반) | 무차원 |

`weather_factor` 변환:

```text
weather_factor = 1 / (1 - ΔV/V / 100)
```

> 속도 손실이 있으면 항해 시간이 길어지고, 결과적으로 연료 소모가 증가한다. cubic speed model에서 `weather_factor > 1.0`으로 반영된다.
>
> **[ORACLE-S-3 가드]** `ΔV/V ≥ 100%`인 경우 분모가 0 이하가 되어 `weather_factor`가 음수 또는 무한대가 된다. §3.5 알고리즘에서 `delta_v_pct >= 100` 검사로 차단한다.

### 3.3 계수 테이블

#### 3.3.1 Cβ (방향 감소 계수)

| Wave heading β | Cβ |
|---|---|
| 0° (head sea) | 1.000 |
| 30° | 0.810 |
| 60° | 0.529 |
| 90° (beam sea) | 0.250 |
| 120° | 0.471 |
| 150° | 0.690 |
| 180° (following sea) | 0.500 |

> MVP에서는 β = 0° (head sea)를 기본으로 한다. 사용자가 wave heading을 입력하지 않으면 Cβ = 1.0을 적용한다.

#### 3.3.2 CU (속도 감소 계수)

CU는 Beaufort Number(BN)와 선종에 따라 달라진다. Kwon (2008)을 참고한 자체 단순화 계수 (실험 모델):

| Ship type | CU 공식 |
|---|---|
| Bulk carrier | CU = 0.5 × BN + 0.5 |
| Tanker | CU = 0.7 × BN |
| Container ship | CU = 0.6 × BN + 0.2 |
| General cargo | CU = 0.5 × BN + 0.5 |
| LNG carrier | CU = 0.7 × BN |

BN(Beaufort Number)은 파고(Hs)로부터 변환한다:

```text
BN = round(3.5 × √Hs)    where Hs in meters
```

> **[ORACLE-M-1 주의]** 위 `round()`는 Python 내장 함수로 banker's rounding(round half to even)을 사용한다. 예: `round(2.5)` → 2. 시스템 전체 rounding 정책(ROUND_HALF_UP)과 다르지만, 경험식 정확도(±20%) 대비 무시 가능한 수준이다.

| Hs (m) | BN | 설명 |
|---|---|---|
| 0.0 – 0.5 | 0–2 | 잔잔함 |
| 0.5 – 1.5 | 2–4 | 약간 거침 |
| 1.5 – 3.0 | 4–5 | 보통 |
| 3.0 – 5.0 | 5–6 | 거침 |
| 5.0 – 7.0 | 6–8 | 매우 거침 |
| > 7.0 | 8+ | 폭풍 |

> **적용 한계**: BN > 8 (Hs > ~7m)에서는 경험식의 신뢰도가 급격히 저하된다. BN > 8인 경우 계산을 중단하고 `기상 조건이 너무 가혹하여 모델을 적용할 수 없습니다` 경고를 표시한다.

#### 3.3.3 Cform (선형 계수)

| Ship type | CB (block coefficient) 범위 | Cform |
|---|---|---|
| Bulk carrier | CB ≥ 0.75 | 0.90 |
| Tanker | CB ≥ 0.75 | 0.90 |
| Container ship | 0.55 ≤ CB < 0.75 | 1.10 |
| General cargo | CB ≥ 0.70 | 0.95 |
| LNG carrier | 0.70 ≤ CB < 0.80 | 1.00 |

> CB를 모를 경우 선종별 기본값을 사용한다: Bulk/Tanker = 0.80, Container = 0.65, General cargo = 0.75, LNG = 0.75.

### 3.4 입력 변수

| 변수 | 기호 | 단위 | 소스 | 필수 |
|---|---|---|---|---|
| 유의파고 | Hs | m | Open-Meteo Marine API / 샘플 | Y |
| 파향 | β | degree | 사용자 입력 (기본 0°) | N |
| Beaufort Number | BN | — | Hs에서 변환 또는 풍속에서 산정 | 자동 |
| Block coefficient | CB | — | 선박 제원 (선택) | N |
| Ship type | — | — | Vessel.ship_type | Y |

### 3.5 계산 알고리즘

```python
def towns_in_kwon_weather_factor(
    hs_m: float,
    ship_type: str,
    wave_heading_deg: float = 0.0,
    block_coefficient: float | None = None,
) -> float:
    """
    Townsin-Kwon 경험식 기반 weather_factor 계산.
    반환값이 > 1.0이면 기상으로 인한 속도 손실 존재.
    """
    # 1. 입력 검증
    if hs_m < 0:
        raise ValueError("Hs must be >= 0")

    # 2. Beaufort Number 산정
    bn = round(3.5 * (hs_m ** 0.5))
    if bn > 8:
        raise ValueError(
            f"BN={bn} (Hs={hs_m}m). Model unreliable above BN 8."
        )

    # 3. Cβ 계산 (선형 보간)
    cbeta = _interpolate_cbeta(wave_heading_deg)

    # 4. CU 계산
    cu = _cu_formula(ship_type, bn)

    # 5. Cform 계산
    cb_default = _default_cb(ship_type)
    cb = block_coefficient or cb_default
    cform = _cform(ship_type, cb)

    # 6. 속도 손실률
    delta_v_pct = cbeta * cu * cform

    # 7. weather_factor 변환 (ORACLE-S-3 가드)
    if delta_v_pct >= 100:
        raise ValueError(
            f"Speed loss {delta_v_pct:.1f}% >= 100%. "
            f"Invalid weather input or model breakdown."
        )
    weather_factor = 1.0 / (1.0 - delta_v_pct / 100.0)

    return weather_factor
```

### 3.6 한계 및 주의사항

| 항목 | 설명 |
|---|---|
| 적용 범위 | head sea 기준. 임의 입사각은 Kwon (2008) 단순화 표의 Cβ 사용 |
| BN > 8 | 계산 불가. 경고 표시 후 NONE 모델 fallback |
| CB 미입력 | 선종별 기본값 사용, `선형 계수가 추정값입니다` 경고 |
| 정확도 | 경험식이므로 ±20% 오차 가능성. `실험 모델` 배지 필수 |
| shallow water | 본 모델은 심해 기준. 수심 효과는 미포함 |
| 해류 | MVP 제외 |

---

## 4. Cubic Speed Model 상세

### 4.1 기본 수식

```text
base_foc_per_day = vessel.reference_daily_foc_ton
speed_factor = (scenario_speed_kn / vessel.reference_speed_kn)^3
weather_factor = get_weather_factor(...)   # §3 참조
duration_days = scenario_distance_nm / scenario_speed_kn / 24
fuel_ton = base_foc_per_day × speed_factor × weather_factor × duration_days
```

### 4.2 가드 조건

| 조건 | 검증 규칙 | 실패 시 |
|---|---|---|
| scenario_speed_kn > 0 | VAL-009: 최소 1.0kn | 계산 중단, 오류 표시 |
| reference_speed_kn > 0 | Vessel 검증 | 계산 중단, 선박 제원 입력 요청 |
| scenario_distance_nm > 0 | VAL-002 | 계산 중단 |
| transport_capacity > 0 | VAL-010 | 계산 중단 |
| weather_factor > 0 | NONE 모델 시 1.0 보장 | — |

### 4.3 다중 연료 처리

> **[ORACLE-S-2 정정]** 반환 타입을 `float`에서 `Decimal`로 변경하여 Layer 1 정밀도 경계를 명확히 했다.
>
> **[ORACLE-M-6 정정]** `fuel_breakdown` 반환값을 명시적으로 정의했다.

```python
from decimal import Decimal

def calculate_voyage_co2(
    vessel,
    fuel_uses: list[dict],  # [{"fuel_type": "HFO", "fuel_ton": 60.0, "cf": 3.114}, ...]
) -> tuple[Decimal, dict[str, Decimal]]:
    """
    다중 연료 CO₂ 배출량 계산 (Layer 1 — Decimal 반환).

    Returns:
        total_co2_g: 총 CO₂ 배출량 (gCO₂, Decimal)
        fuel_breakdown: 연료별 CO₂ 배출량 ({"HFO": Decimal, "LNG": Decimal, ...})
    """
    total_co2_g = Decimal("0")
    fuel_breakdown: dict[str, Decimal] = {}

    for fuel in fuel_uses:
        fuel_type = fuel["fuel_type"]
        fuel_ton = Decimal(str(fuel["fuel_ton"]))
        cf = Decimal(str(fuel["cf"]))

        co2_g = fuel_ton * Decimal("1000000") * cf
        total_co2_g += co2_g
        fuel_breakdown[fuel_type] = co2_g

    # [ORACLE-MISS-2] 출력 가드
    if not total_co2_g.is_finite() or total_co2_g <= 0:
        raise ValueError(
            f"Invalid CO₂ result: {total_co2_g}. Check fuel inputs."
        )

    return total_co2_g, fuel_breakdown
```

> cubic speed model은 총 연료 소모량을 산정한 후 연료 비율로 배분한다. 연료별로 cubic model을 별도 적용하지 않는다.

### 4.4 기상 보정 미적용 시

`weather_model = NONE`인 경우:

```python
weather_factor = 1.0
fuel_ton = base_foc_per_day × speed_factor × 1.0 × duration_days
```

---

## 5. 파라미터 직렬화 및 해싱

### 5.1 Canonical JSON 직렬화 규격

파라미터 content hash와 input_hash 모두 동일한 직렬화 규칙을 따른다.

#### 5.1.1 직렬화 규칙

> **[ORACLE-C-2 정정]** Decimal trailing zeros로 인한 hash 불일치를 방지하기 위해 `normalize()` 규칙을 추가했다.
>
> **[ORACLE-M-3 정정]** null 처리 규칙을 명확히 했다.
>
> **[ORACLE-M-4 정정]** float 처리를 에러 발생으로 변경했다.

| 규칙 | 설명 |
|---|---|
| 키 정렬 | 모든 JSON 객체 키를 UTF-8 바이트순 오름차순 정렬 |
| 수치 표현 | 모든 수치는 Decimal 문자열로 변환. float 리터럴 **금지** (에러 발생) |
| **Decimal 정규화** | **[ORACLE-C-2]** Decimal 직렬화 전 `normalize()` 적용하여 trailing zeros 제거 (예: `Decimal("3.114000")` → `"3.114"`). normalize 후 지수 표기법인 경우 `format(d, 'f')`로 고정 소수점 변환 |
| null 처리 | **[ORACLE-M-3]** `None` 값은 JSON `null`로 직렬화한다 (필드 자체를 생략하지 않음). `"null"` 문자열이 아님 |
| 배열 정렬 | UUID 배열은 문자열 정렬. 수치 배열은 원래 순서 유지 |
| 공백 | 불필요한 공백 없음 (minified JSON) |
| 인코딩 | UTF-8 |

#### 5.1.2 직렬화 함수

```python
import json
from decimal import Decimal

def _decimal_to_canonical_str(d: Decimal) -> str:
    """
    [ORACLE-C-2] Decimal을 canonical 문자열로 변환.
    normalize()로 trailing zeros 제거 후, 지수 표기를 고정 소수점으로 변환.
    """
    normalized = d.normalize()
    # format 'f' avoids scientific notation (e.g., 1.4405E+11 → 144050000000)
    s = format(normalized, 'f')
    # Remove trailing .0 for integer values
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s

def canonical_json(obj: dict) -> str:
    """
    결정적 JSON 직렬화.
    모든 수치를 Decimal 문자열로 변환 후 정렬.
    """
    def convert(o):
        if isinstance(o, Decimal):
            return _decimal_to_canonical_str(o)
        if isinstance(o, float):
            # [ORACLE-M-4] float는 허용하지 않음 — Decimal 사용 강제
            raise TypeError(
                f"float not allowed in canonical_json: {o}. "
                f"Use Decimal instead."
            )
        if isinstance(o, dict):
            return {k: convert(v) for k, v in sorted(o.items())}
        if isinstance(o, (list, tuple)):
            return [convert(item) for item in o]
        if o is None:
            return None  # [ORACLE-M-3] JSON null
        return o

    return json.dumps(
        convert(obj),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
```

### 5.2 파라미터 Content Hash

```python
import hashlib

def compute_parameter_hash(parameters_used: dict) -> str:
    """
    해당 계산에 사용된 모든 규정 파라미터의 content hash.
    """
    canonical = canonical_json(parameters_used)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

#### 5.2.1 `parameters_used` 스키마

```json
{
  "regulation_year": {
    "year": "2026",
    "z_factor_percent": "11"
  },
  "fuel_types": [
    {
      "code": "HFO",
      "cf": "3.114"
    }
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
}
```

### 5.3 Input Hash

```python
def compute_input_hash(calculation_input: dict) -> str:
    """
    계산 입력값의 content hash.
    필드 목록을 명시적으로 정의하여 불필요한 필드 배제.

    [ORACLE-S-5] weather_factor는 hash 계산 전에 반드시 확정되어야 한다.
    weather_factor가 None인 경우 NONE 모델 기본값 '1.0'으로 간주.
    """
    INPUT_FIELDS = [
        "vessel_id",
        "regulation_year",
        "ship_type",
        "transport_capacity",     # [EXT-P0-1] actual DWT/GT for attained CII W
        "reference_capacity",     # [EXT-P0-1] G2 capacity_rule resolved value for CII_ref
        "distance_nm",
        "speed_kn",
        "fuel_uses",          # [{fuel_type, fuel_ton, cf}]
        "weather_model",
        "weather_factor",     # [ORACLE-S-5] hash 전 반드시 확정
    ]

    filtered = {}
    for k in INPUT_FIELDS:
        if k in calculation_input:
            val = calculation_input[k]
            # [ORACLE-S-5] weather_factor가 None이면 기본값 사용
            if k == "weather_factor" and val is None:
                val = Decimal("1.0")
            filtered[k] = val

    canonical = canonical_json(filtered)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

> **[ORACLE-S-5 주의]** `weather_factor`는 hash 계산 시점에 이미 계산되어 있어야 한다. 기상 데이터 조회가 비동기인 경우, 조회 완료 후 hash를 계산한다. `weather_model = NONE`이면 `weather_factor = 1.0`으로 설정한다.

### 5.4 재현성 계약 (Reproducibility Contract)

> **[#102]** 기상 데이터 갱신과 재현성의 관계를 명확히 정의한다. 상위 근거: PRD §16.2 신뢰성 — "계산 재현성: 동일 입력·동일 파라미터·동일 seed는 동일 결과".

**계약:**

1. **재현성의 단위는 `input_hash`다.** 동일 `input_hash` + 동일 `parameter_hash` + 동일 `model_version`(Monte Carlo는 동일 seed 포함) → 항상 동일 결과.
2. `input_hash`는 **확정된(resolved) `weather_factor`를 포함**한다(§5.3 `INPUT_FIELDS`, [ORACLE-S-5]). 따라서 기상 데이터가 갱신되면 `weather_factor`가 달라져 새로운 `input_hash`가 생성되고, 이는 **별개의 새 계산으로 취급한다. 이것은 의도된 동작(by design)이다.**
3. **"동일 항차 → 동일 결과"는 계약이 아니다.** 같은 항차라도 계산 시점의 기상(캐시 상태)에 따라 `weather_factor`가 달라질 수 있으며, 이때 결과가 달라지는 것은 재현성 위반(버그)이 아니라 **입력이 달라진 것**이다. 재현성 위반은 오직 "동일 `input_hash`인데 결과가 다른 경우"만을 뜻한다.
4. **추적성**: 계산에 사용된 기상 스냅샷은 `calculation_run.weather_snapshot_id`(DB_SCHEMA §2.5 — #103의 `weather_snapshot` 테이블(013) 생성 후 016+ 후속 마이그레이션에서 컬럼 추가)로 기록하여 "이 계산은 어떤 기상 데이터로 실행되었나"를 사후 감사할 수 있다. `weather_factor` 값과 `weather_snapshot_id`는 `result_json`에도 포함한다.
5. **스냅샷 없는 계산도 정상 경로다.** `weather_model = NONE`이거나 캐시 만료 fallback(§7.3) 시 `weather_factor = 1.0`이고 `weather_snapshot_id`는 NULL이다.
6. **재검증 절차**: 과거 계산의 재현은 새 기상 조회 없이 저장된 입력(동일 `weather_factor` 포함)으로 수행한다. 재현 결과가 원본과 불일치하면 `ReproducibilityError`(§12.1)로 처리한다.
7. **계약의 범위(경계)**: 본 계약은 **입력 식별(hashing) 차원**의 재현성을 정의한다. 수치 연산 자체의 결정론 — Layer 1 Decimal bit-exact(§1), Monte Carlo RNG 고정(PCG64DXSM, §2) — 은 본 계약의 **전제조건**이며, NumPy 버전 변경에 따른 난수 재현성 정책은 **#106**에서 별도로 정의한다. 따라서 6항의 `ReproducibilityError`는 입력 동일성이 확인된 뒤 발생한 수치 불일치를 가리키며, 그 근본 원인 규명(numpy 버전·RNG 구현 변경 등)은 #106의 정책을 따른다.

---

## 6. 대권거리 계산

### 6.1 수식

Haversine 공식을 사용한다:

```text
a = sin²(Δlat/2) + cos(lat1) × cos(lat2) × sin²(Δlon/2)
c = 2 × atan2(√a, √(1−a))
distance_nm = R × c

where R = 3440.065 nm (Earth radius in nautical miles)
```

### 6.2 구현

```python
import math

EARTH_RADIUS_NM = 3440.065

def great_circle_distance_nm(
    lat1_deg: float,
    lon1_deg: float,
    lat2_deg: float,
    lon2_deg: float,
) -> float:
    lat1 = math.radians(lat1_deg)
    lat2 = math.radians(lat2_deg)
    dlat = math.radians(lat2_deg - lat1_deg)
    dlon = math.radians(lon2_deg - lon1_deg)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_NM * c
```

### 6.3 정확도 및 제약

| 항목 | 설명 |
|---|---|
| 정확도 | 대권거리는 실제 항로와 다를 수 있음. 화면에 `좌표 기반 추정 거리` 표시 |
| 극지역 | 위도 ±90° 근처에서 오차 증가 가능 |
| 우회 | waypoint 기반 polyline 거리는 다중 대권거리 합산으로 계산 |
| 사용자 입력 우선 | 사용자가 직접 거리를 입력한 경우 대권거리 계산을 수행하지 않음 |

---

## 7. 기상 데이터 어댑터

### 7.1 인터페이스

```python
from abc import ABC, abstractmethod
from datetime import datetime
from dataclasses import dataclass

@dataclass
class WeatherSnapshot:
    lat: float
    lon: float
    fetched_at: datetime
    wave_height_m: float | None
    wave_direction_deg: float | None
    wave_period_s: float | None
    wind_speed_ms: float | None
    wind_direction_deg: float | None
    source: str  # "open_meteo_marine", "open_meteo_forecast", "sample"

class WeatherProvider(ABC):
    @abstractmethod
    def fetch_marine_weather(
        self, lat: float, lon: float, time_range: tuple[datetime, datetime]
    ) -> WeatherSnapshot | None:
        ...

    @abstractmethod
    def fetch_wind_weather(
        self, lat: float, lon: float, time_range: tuple[datetime, datetime]
    ) -> WeatherSnapshot | None:
        ...

    @abstractmethod
    def get_last_snapshot(self, lat: float, lon: float) -> WeatherSnapshot | None:
        ...
```

### 7.2 Open-Meteo 구현

| 데이터 | API 엔드포인트 | 파라미터 |
|---|---|---|
| 파고·파향·주기 | `https://marine-api.open-meteo.com/v1/marine` | `latitude`, `longitude`, `hourly=wave_height,wave_direction,wave_period` |
| 풍속·풍향 | `https://api.open-meteo.com/v1/forecast` | `latitude`, `longitude`, `hourly=wind_speed_10m,wind_direction_10m` |

### 7.3 캐시 정책

| 항목 | 사양 |
|---|---|
| 캐시 key | `(lat_rounded_0.5, lon_rounded_0.5, date, hour_bucket_6h)` |
| 캐시 저장소 | 애플리케이션 메모리 또는 Redis |
| TTL | 24시간 |
| 신선도 평가 | 구간별 독립. 일부 구간이 24h 초과 시 해당 구간만 `weather_factor=1.0` fallback |

```python
def get_weather_factor_for_segment(
    provider: WeatherProvider,
    lat: float,
    lon: float,
    weather_model: str,
    vessel,  # Vessel 객체 (ship_type 등)
) -> float:
    snapshot = provider.get_last_snapshot(lat, lon)
    if snapshot is None:
        return 1.0  # NONE fallback

    age_hours = (datetime.now(timezone.utc) - snapshot.fetched_at).total_seconds() / 3600

    if age_hours > 24:
        return 1.0  # 너무 오래됨 → fallback
    elif age_hours > 6:
        # 경고 표시하되 계산 허용
        pass

    if weather_model == "NONE":
        return 1.0
    elif weather_model == "SIMPLE_RULE":
        return simple_rule_factor(snapshot)
    elif weather_model == "TOWNSIN_KWON_ALPHA":
        return towns_in_kwon_weather_factor(
            hs_m=snapshot.wave_height_m,
            ship_type=vessel.ship_type,
        )
    else:
        raise ValueError(f"Unknown weather model: {weather_model}")
```

---

## 8. SIMPLE_RULE 기상 보정 모델

### 8.1 수식

```text
weather_factor = 1.0 + (Hs × 0.02) + (wind_speed_ms × 0.005)
```

| 입력 | 계수 | 근거 |
|---|---|---|
| 유의파고 Hs (m) | 0.02 | 파고 1m당 약 2% 연료 증가 (업계 경험치) |
| 풍속 (m/s) | 0.005 | 풍속 10m/s당 약 5% 연료 증가 |

### 8.2 가드

> **[ORACLE-M-2 정정]** 음수 기상 입력값으로 인한 비정상 factor 산출을 방지하기 위해 입력 clamping을 추가했다.

```python
def simple_rule_factor(snapshot: WeatherSnapshot) -> float:
    factor = 1.0

    # [ORACLE-M-2] 음수 입력 clamping (API 데이터 오류 방지)
    hs = max(snapshot.wave_height_m or 0.0, 0.0)
    wind = max(snapshot.wind_speed_ms or 0.0, 0.0)

    factor += hs * 0.02
    factor += wind * 0.005

    return min(factor, 2.0)  # 상한 cap: 2배
```

### 8.3 적용 한계

| 항목 | 설명 |
|---|---|
| 정확도 | 매우 단순한 선형 근사. ±30% 오차 가능 |
| 상한 | weather_factor 최대 2.0 (파고 25m + 풍속 100m/s 이상 상황은 비현실적) |
| 용도 | 데모 안정성 확보 및 fallback |

---

## 9. `14405E7` 표기 변환 규격

### 9.1 저장 형식

| 필드 | 타입 | 값 예시 | 설명 |
|---|---|---|---|
| `a_raw` | VARCHAR | `"14405E7"` | IMO 원문 표기 그대로 |
| `a_decimal` | NUMERIC(30,6) | `144050000000.000000` | Decimal 변환값 |

### 9.2 변환 규칙

> **[ORACLE-S-3 정정]** NaN/Infinity 및 비양수 값 검증을 추가했다.

```python
def parse_imo_scientific(raw: str) -> Decimal:
    """
    IMO 표 원문의 E 표기를 Decimal로 변환.
    예: "14405E7" → Decimal("144050000000")
         "14779E10" → Decimal("147790000000000")
    """
    # E 표기를 Decimal이 이해할 수 있는 형태로 변환
    normalized = raw.upper().replace("E", "×10^")
    if "×10^" in normalized:
        mantissa_str, exp_str = normalized.split("×10^")
        mantissa = Decimal(mantissa_str)
        exponent = int(exp_str)
        result = mantissa * (Decimal(10) ** exponent)
    else:
        result = Decimal(raw)

    # [ORACLE-S-3] NaN / Infinity 검증
    if result.is_nan() or result.is_infinite():
        raise ValueError(
            f"Invalid IMO coefficient: '{raw}' → {result} (NaN/Infinity)"
        )

    # [ORACLE-S-3] 비양수 값 검증
    if result <= 0:
        raise ValueError(
            f"IMO coefficient must be > 0: '{raw}' → {result}"
        )

    return result
```

### 9.3 검증

애플리케이션 시작 시 모든 `a_raw`와 `a_decimal`의 일치 여부를 검증한다:

```python
def validate_a_values(session):
    rows = session.query(CIIReferenceLine).all()
    for row in rows:
        parsed = parse_imo_scientific(row.a_raw)
        if parsed != row.a_decimal:
            raise ValueError(
                f"a_raw/a_decimal mismatch for {row.ship_type} "
                f"({row.condition_expr}): {row.a_raw} → {parsed} != {row.a_decimal}"
            )
```

### 9.4 정밀도 한계

| 값 | 자릿수 | 64-bit float 정밀도 | Decimal(30,6) 정밀도 |
|---|---|---|---|
| 144,050,000,000 | 12자리 | ✅ 안전 | ✅ 정확 |
| 144,790,000,000,000 | 15자리 | ⚠️ 한계 근접 | ✅ 정확 |
| 147,790,000,000,000 | 15자리 | ⚠️ 한계 근접 | ✅ 정확 |

> float 변환을 피하고 항상 Decimal로 계산한다. `Capacity^(-c)` 연산 시 Decimal ln/exp를 사용한다.

---

## 10. 모델 버전 관리

### 10.1 `model_version` 포맷

> **[ORACLE-M-5 정정]** 단일 hyphen-delimited 문자열 대신 structured JSON을 사용하여 파싱 오류를 방지한다.

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

DB 저장 시 `model_version` 컬럼은 JSON 문자열로 저장한다 (`TEXT` 또는 `JSONB` 타입).

API 응답에서는 다음과 같이 문자열로 직렬화할 수 있다:

```text
dual-precision-v1_decimal30-pcg64dxsm_numpy2.1.0
```

단, 파싱은 항상 structured JSON 기반으로 수행한다 (문자열 파싱 금지).

### 10.2 버전별 호환성

| model_version 변경 | 기존 결과 영향 | 처리 |
|---|---|---|
| NumPy 마이너 버전 변경 | Monte Carlo 결과 미세 변화 가능 | 기존 CalculationRun 보존, 신규 계산은 새 버전 사용 |
| BitGenerator 변경 | 결과 완전히 상이 | major version bump. 기존 결과 무효화 안 됨 |
| 계산 엔진 로직 변경 (예: rounding 정책) | 결정론 결과 변화 가능 | major version bump. 영향받는 범위 표시 |
| Decimal precision 변경 | 결정론 결과 미세 변화 가능 | precision 값을 model_version에 명시하여 추적 |

---

## 11. 스냅샷 격리 (Snapshot Isolation)

> **[ORACLE-S-6 추가]** PRD §8.4 (ORACLE-R-5)에서 요구하는 연간 시뮬레이션 스냅샷 격리의 계산적 구현을 정의한다.

### 11.1 목적

연간 CII 시뮬레이션 실행 중 항차 데이터 변경(예: COMPLETED → CONFIRMED 전환, 실적 입력)이 시뮬레이션 결과에 영향을 주지 않도록 보장한다.

### 11.2 스냅샷 대상

시뮬레이션 시작 시점에 다음 데이터를 스냅샷으로 복사한다:

| 데이터 | 소스 | 스냅샷 내용 |
|---|---|---|
| 확정 항차 (CONFIRMED) | `Voyage` + `VoyageFuelUse` | actual_distance_nm, actual_fuel_ton (전체) |
| 완료 항차 (COMPLETED) | `Voyage` + `VoyageFuelUse` | actual_distance_nm, actual_fuel_ton (있는 경우) |
| 진행 중 항차 (IN_PROGRESS) | `Voyage` | planned_*, 최신 estimate |
| 계획 항차 (PLANNED) | `Voyage` | planned_distance_nm, planned_speed_kn, planned_fuel_ton |

### 11.3 구현 방식

```python
@dataclass
class SimulationSnapshot:
    """연간 시뮬레이션 시작 시점의 항차 데이터 스냅샷."""
    snapshot_id: str  # UUID
    vessel_id: str
    regulation_year: int
    created_at: datetime
    voyages: list[dict]  # 항차별 완전한 데이터 사본
    input_hash: str      # 스냅샷 시점의 input_hash
    parameter_hash: str  # 스냅샷 시점의 parameter_hash
```

### 11.4 격리 보장

1. **시뮬레이션 시작**: `SimulationSnapshot` 생성 → 메모리 또는 별도 테이블에 저장
2. **시뮬레이션 실행**: 원본 `Voyage` 테이블이 아닌 `SimulationSnapshot.voyages` 사용
3. **시뮬레이션 중 데이터 변경**: 원본 테이블에 반영되지만, 진행 중인 시뮬레이션은 영향받지 않음
4. **시뮬레이션 완료**: 결과 저장. 원본 데이터의 변경 여부는 별도 알림

> `input_hash`와 `parameter_hash`는 스냅샷 생성 시점에 계산되어 `CalculationRun`에 저장된다. 시뮬레이션 재현 시 이 두 hash가 일치하는지 확인한다.

---

## 12. 오류 전파 및 검증 전략

> **[ORACLE-MISS-1 추가]** 계산 엔진에서 발생하는 오류가 API 계층으로 어떻게 전파되는지 정의한다.

### 12.1 오류 분류

| 오류 클래스 | 발생 조건 | API 응답 코드 | 사용자 메시지 |
|---|---|---|---|
| `ValidationError` | VAL-001~010 위반. 필수값 누락, 범위 초과, NaN/Infinity | 422 Unprocessable Entity | 필드별 구체적 오류 문구 |
| `ParameterError` | 규정 파라미터 누락, fuel CF 없음, a_raw/a_decimal 불일치 | 409 Conflict | `해당 연도의 규정 파라미터가 없습니다.` |
| `WeatherFetchError` | 기상 API 실패 + 캐시 없음 | 200 OK + warning (NONE fallback) 또는 422 (사용자 선택) | `최신 기상 데이터를 가져오지 못했습니다.` |
| `CalculationError` | 분모 0, overflow, 유효하지 않은 결과 | 422 Unprocessable Entity | `계산 오류: 입력값을 확인하세요.` |
| `ModelBreakdownError` | BN > 8, ΔV/V ≥ 100% | 422 Unprocessable Entity | `기상 조건이 너무 가혹하여 모델을 적용할 수 없습니다.` |
| `ReproducibilityError` | canonical test vector 불일치 | 500 Internal Server Error | `재현성 검증 실패. 관리자에게 문의하세요.` |

### 12.2 오류 전파 규칙

1. **Layer 1 (Decimal)**: `ValueError` 발생 시 즉시 중단. 부분 결과를 반환하지 않는다.
2. **Layer 2 (Monte Carlo)**: 개별 iteration 실패 시 해당 iteration을 스킵하고 경고 로그. 전체 실패율이 5% 초과 시 `CalculationError`.
3. **Weather Adapter**: 실패 시 `WeatherFetchError`. 호출자가 fallback 정책 결정.
4. **모든 오류**: `warnings_json`에 기록. 계산 성공 시에도 warning이 있을 수 있음.

### 12.3 경고(Warning) 체계

계산은 성공하지만 주의가 필요한 경우 warning을 반환한다:

| Warning 코드 | 조건 | 사용자 메시지 |
|---|---|---|
| `REFERENCE_ONLY` | 모든 계산 결과 | `참고용 예측값입니다. 규제 제출용이 아닙니다.` |
| `WEATHER_STALE` | 기상 캐시 6~24시간 | `오래된 기상 데이터를 사용 중입니다.` |
| `WEATHER_NONE_FALLBACK` | 기상 API 실패, NONE 모델 사용 | `기상 보정 없이 계산했습니다.` |
| `CB_ESTIMATED` | block coefficient 추정값 사용 | `선형 계수가 추정값입니다.` |
| `EXPERIMENTAL_MODEL` | TOWNSIN_KWON_ALPHA 사용 | `실험 모델 기반 결과입니다.` |
| `NON_CII_VESSEL` | GT < 5,000 | `공식 CII 적용 대상이 아닐 수 있습니다.` |
| `COMPLETED_NO_FUEL` | COMPLETED 항차 actual_fuel_ton NULL | `실적이 입력되지 않은 완료 항차입니다. 계획값을 임시 사용 중.` |

---

## 13. 감사 로그 및 성능 검증

> **[ORACLE-MISS-3, MISS-4 추가]**

### 13.1 감사 로그

모든 `CalculationRun` 생성 시 다음을 로그에 기록한다:

| 필드 | 설명 |
|---|---|
| `timestamp` | 계산 실행 시각 (UTC) |
| `user_id` | 실행 사용자 ID |
| `calculation_type` | VOYAGE_ESTIMATE, SCENARIO, ANNUAL_DETERMINISTIC, ANNUAL_MONTE_CARLO |
| `input_hash` | 입력값 hash |
| `parameter_hash` | 파라미터 hash |
| `model_version` | 계산 모델 버전 (structured JSON) |
| `duration_ms` | 계산 소요 시간 (밀리초) |
| `status` | SUCCESS, FAILED, PARTIAL |
| `warnings_count` | 발생한 warning 수 |

파라미터 변경, 항차 확정(CONFIRMED 전환), 계산 실행은 별도 audit log 테이블에 기록한다. 상세 스키마는 `DB_SCHEMA.md`에서 정의한다.

### 13.2 성능 검증

> PRD §16.1의 성능 목표를 CI에서 검증한다.

| 테스트 항목 | 목표 | 검증 방법 |
|---|---|---|
| 일반 CII 계산 | p95 < 1초 | Fixture 1 기반 벤치마크, CI 실행 |
| 기능② 3개 시나리오 비교 | p95 < 5초, 캐시 시 < 2초 | 샘플 선박 3개 시나리오 벤치마크 |
| 기능③ 결정론 계산 | p95 < 1초 | 12개월 항차 데이터 기반 |
| 기능③ Monte Carlo 5,000회 | p95 < 3초 | 단일 선박, 12개월 시뮬레이션 기준 |

> 상세 테스트 케이스는 `TEST_PLAN.md`에서 정의한다. 성능 벤치마크는 CI 파이프라인에 통합하여 회귀를 감지한다.

---

## 14. Oracle Review Corrections (v1.1)

> 본 섹션은 Oracle 기술 검토(2026-07-03)에서 식별된 이슈를 기록하고, 각 이슈의 수정 위치와 상태를 추적한다.

### 14.1 Critical Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| ORACLE-C-1 | `default_rng()`가 PCG64를 생성하지만 spec은 PCG64DXSM 명시. 모순. | §2.1, §2.2.1, §2.2.3, §2.5.1 — `Generator(PCG64DXSM(seed))`로 통일 | **수정 완료** |
| ORACLE-C-2 | Decimal trailing zeros가 canonical hash 불일치 발생. `Decimal("3.114")` ≠ `Decimal("3.114000")` after str(). | §5.1.1 정규화 규칙 추가, §5.1.2 `_decimal_to_canonical_str()` 함수 추가 | **수정 완료** |

### 14.2 Significant Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| ORACLE-S-1 | `plan_value = 0`일 때 `rng.triangular(0, 0, 0)` → ValueError | §2.3.1 — plan_value ≤ 0 guard 추가 | **수정 완료** |
| ORACLE-S-2 | §4.3이 `float(total_co2_g)` 반환하여 Layer 1 Decimal 보장 위반 | §4.3 — 반환 타입 Decimal로 변경, `fuel_breakdown` 정의 | **수정 완료** |
| ORACLE-S-3 | `parse_imo_scientific`이 NaN/Infinity 허용 | §9.2 — `is_nan()`, `is_infinite()`, `<= 0` 검증 추가 | **수정 완료** |
| ORACLE-S-4 | Fixture 1 중간값 `10.8198 × 0.622 = 6.7301...` 산술 오류 (정확값: 6.7299...) | §1.2.3 — 중간값 수정 | **수정 완료** |
| ORACLE-S-5 | INPUT_FIELDS에 weather_factor timing 미명시 | §5.3 — weather_factor hash 전 확정 의무화, None 시 기본값 적용 | **수정 완료** |
| ORACLE-S-6 | PRD §8.4 스냅샷 격리 구현 명실 누락 | §11 (신규) — 스냅샷 격리 섹션 추가 | **수정 완료** |

### 14.3 Minor Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| ORACLE-M-1 | BN round()가 banker's rounding 사용 (ROUND_HALF_UP 불일치) | §3.3.2 — 주석 추가 (경험식 정확도 대비 무시 가능) | **수정 완료** |
| ORACLE-M-2 | SIMPLE_RULE 음수 기상 입력 가드 없음 | §8.2 — `max(x, 0.0)` clamping 추가 | **수정 완료** |
| ORACLE-M-3 | canonical JSON null 처리 모호 ("null" 문자열 vs JSON null) | §5.1.1, §5.1.2 — JSON `null`로 명확화 | **수정 완료** |
| ORACLE-M-4 | canonical_json float 처리가 규칙(금지)과 모순 | §5.1.2 — float 시 `TypeError` 발생으로 변경 | **수정 완료** |
| ORACLE-M-5 | model_version 포맷이 파싱 불가능한 hyphen 문자열 | §10.1 — structured JSON 포맷으로 변경 | **수정 완료** |
| ORACLE-M-6 | §4.3 `fuel_breakdown` 미정의 | §4.3 — `dict[str, Decimal]` 반환값 정의 | **수정 완료** |

### 14.4 Missing Topics

| ID | 누락 항목 | 추가 위치 | 상태 |
|---|---|---|---|
| ORACLE-MISS-1 | 오류 전파 전략 | §12 (신규) — 오류 분류, 전파 규칙, 경고 체계 | **추가 완료** |
| ORACLE-MISS-2 | Layer 1 출력 NaN/Infinity 일반 가드 | §1.2.5 (신규) — `validate_layer1_result()` | **추가 완료** |
| ORACLE-MISS-3 | 감사 로그 명세 | §13.1 (신규) — 감사 로그 필드 정의 | **추가 완료** |
| ORACLE-MISS-4 | 성능 검증 방법 | §13.2 (신규) — CI 벤치마크 정의 | **추가 완료** |

### 14.5 PRD 정렬 검증

| PRD Oracle ID | TECH_SPEC 반영 | 상태 |
|---|---|---|
| ORACLE-C-1 (RNG 명시) | §2 — PCG64DXSM 명시적 생성 | ✅ |
| ORACLE-C-2 (~~capacity_rule W 적용~~ → **REVERTED**) | §1.2.4 — 이중 capacity 함수로 분리 (`resolve_transport_capacity` + `resolve_reference_capacity`) | ✅ 정정 |
| ORACLE-C-3 (speed floor) | §4.2 | ✅ |
| ORACLE-C-4 (COMPLETED fuel 제약) | 비즈니스 규칙 → API_SPEC로 연기 | ⏭️ |
| ORACLE-R-1 (status/policy matrix) | 비즈니스 규칙 → API_SPEC로 연기 | ⏭️ |
| ORACLE-R-2 (parameter hash) | §5.2 | ✅ |
| ORACLE-R-3 (input_hash) | §5.3 | ✅ |
| ORACLE-R-4 (multi-segment cache) | §7.3 | ✅ |
| ORACLE-R-5 (snapshot isolation) | §11 (신규) | ✅ |
| ORACLE-R-6 (performance) | §1.1, §13.2 | ✅ |
| ORACLE-R-7 (14405E7 precision) | §9 | ✅ |
| ORACLE-G-1 (NaN/Inf guard) | §1.2.5 (신규), §3.5 | ✅ |
| ORACLE-G-2 (triangular floor) | §2.3.1, §2.3.2 | ✅ |
| ORACLE-G-5 (multi-fuel) | §4.3 | ✅ |
| ORACLE-G-6 (capacity=0 guard) | §4.2 | ✅ |

### 14.6 검토 요약

- **TECH_SPEC 품질 평가**: v1.0은 구조적으로 건전하나 RNG 모순(C-1)과 hash 비결정성(C-2)이 Critical. v1.1에서 모두 해결.
- **하위 문서 준비도**: v1.1은 API_SPEC, DB_SCHEMA가 참조할 모든 기술 명세를 포함. 오류 분류(§12), 스냅샷 격리(§11), 감사 로그(§13)가 추가되어 하위 문서 작성이 차단 없이 진행 가능.
- **수정 소요**: Critical + Significant 이슈 해결에 약 2~4시간 소요 (문서 수정 기준).

### 14.7 외부 리뷰 반영 (v1.2)

| ID | 이슈 | 위치 | 처리 |
|---|---|---|---|
| EXT-P0-2 | canonical vector “예시값” → 실측값 교체 | §2.5.1 | **수정 완료** — `numpy==2.1.0`, `PCG64DXSM(seed=12345)` 기반 실측값, NumPy 2.1.0에서 교차 검증 완료 |

---

## 15. 하위 문서 의존성

### 15.1 API_SPEC.md 필요 참조

| TECH_SPEC 섹션 | API_SPEC 사용처 |
|---|---|
| §2.2.2 `rng_metadata` | Monte Carlo 응답 스키마 |
| §5.2.1 `parameters_used` | CalculationRun 응답 |
| §5.3 `INPUT_FIELDS` | input_hash 계산 API 명세 |
| §10.1 `model_version` | 응답에 포함되는 모델 버전 |
| §11 스냅샷 격리 | 연간 시뮬레이션 API 엔드포인트 의미론 |
| §12 오류 분류 | API 오류 응답 코드 및 메시지 |
| §12.3 Warning 코드 | API 응답 `warnings` 필드 |

### 15.2 DB_SCHEMA.md 필요 참조

| TECH_SPEC 섹션 | DB_SCHEMA 사용처 |
|---|---|
| §2.2.2 `rng_metadata` | `CalculationRun.result_json` 내 구조 |
| §5.2 `parameter_hash` | `CalculationRun.parameter_version` 컬럼 (SHA-256 hex = `sha256:` prefix + 64 chars) |
| §5.3 `input_hash` | `CalculationRun.input_hash` 컬럼 |
| §9.1 `a_raw` / `a_decimal` | `cii_reference_line` 테이블 (VARCHAR + NUMERIC(30,6)) |
| §10.1 `model_version` | `CalculationRun.model_version` 컬럼 (JSON TEXT) |
| §11.3 `SimulationSnapshot` | 스냅샷 저장 테이블 또는 result_json 내 구조 |
| §13.1 감사 로그 | audit_log 테이블 스키마 |

---

## 16. 서비스 레이어 아키텍처

> **[#100 확정]** 비즈니스 로직·계산·DB 접근·HTTP 처리가 어느 모듈에 위치해야 하는지 규칙을 정의한다. 이 규칙이 없으면 같은 계산 로직이 여러 API에 중복되고, 개발자마다 다른 패턴을 따르게 되어 유지보수성이 무너진다.

### 16.1 계층 개요

요청은 위에서 아래로 흐르고, 각 계층은 바로 아래 계층만 호출한다:

```
사용자 요청
    ↓
[api/routes]        ← HTTP 요청/응답만 (검증, 직렬화). 서비스만 호출.
    ↓
[services]          ← 비즈니스 로직 (계산 흐름, 규칙, fallback·상태 전환 결정)
    ↓         ↘
[calc]              [db/repositories]   ← 서비스가 계산 엔진과 저장소를 조합
 (수학 계산)          (DB 쿼리만)
                        ↓
                     [db/models] (ORM)
                        ↓
                     데이터베이스
```

### 16.2 디렉토리 구조

```
src/cii_platform/
├── errors.py            ← 공통 예외 base (AppError). 레이어 중립.
├── config.py            ← 설정 (DATABASE_URL 등)
├── api/
│   ├── main.py          ← FastAPI app
│   ├── routes/          ← HTTP 요청/응답만
│   ├── schemas/         ← 요청/응답 Pydantic 스키마 (API 표현)
│   └── error_handlers.py ← 예외 → API_SPEC §1.3.2 응답 변환, 핸들러 등록
├── services/            ← 비즈니스 로직
├── calc/                ← CII 계산 엔진 (Layer 1 Decimal / Layer 2 Monte Carlo)
└── db/
    ├── models/          ← SQLAlchemy ORM 모델 (DB 표현)
    └── repositories/    ← DB 접근(쿼리)만
```

### 16.3 계층 간 규칙

| 계층 | 하는 일 | 하지 않는 일 | 호출 가능 대상 |
|---|---|---|---|
| `api/routes` | 요청 검증, 응답 직렬화 | 계산, DB 직접 접근 | `services`만 |
| `services` | 계산 흐름 조율, 비즈니스 규칙, fallback·상태 전환 결정 | HTTP 처리, 원시 SQL | `calc`, `db/repositories` |
| `calc` | 순수 수학 계산 | DB 접근, HTTP, 비즈니스 흐름 | (없음 — 순수 함수) |
| `db/repositories` | DB 쿼리(SELECT/INSERT…) | 비즈니스 로직, 계산 | `db/models` |
| `db/models` | ORM 테이블 정의 | 비즈니스 로직 | (없음) |

- **역방향 의존 금지**: 하위 계층은 상위 계층을 import하지 않는다. 특히 `calc`·`db`·`services`는 `api`를 import하지 않는다.
- ORM 모델은 `db/models`, API 스키마는 `api/schemas`로 분리한다(DB 표현과 API 표현의 혼용 방지).

### 16.4 오류 처리

계층에서 발생한 오류를 API 표준 오류 응답으로 일관되게 변환한다.

- **오류 분류·전파·HTTP status**: §12.1(오류 분류), §12.2(전파 규칙), API_SPEC §1.4(HTTP Status 매핑)를 그대로 따른다. 본 섹션은 값을 재정의하지 않는다.
- **응답 포맷**: API_SPEC §1.3.2(`{"error": {...}, "meta": {...}}`)를 따른다.
- **base 예외 위치**: 공통 base 예외 `AppError`는 레이어 중립 위치인 `src/cii_platform/errors.py`에 둔다. 이유: 예외를 던지는 주체는 하위 계층(`calc`/`services`/`db`)인데, base 예외를 `api`에 두면 하위 계층이 `api`를 import하는 역방향 의존이 생겨 §16.3 규칙을 위반한다.
- **변환 위치**: `api/error_handlers.py`가 `errors.py`를 import하여 `AppError`(및 상속 예외)를 API 응답으로 변환하고, `register_exception_handlers(app)`로 FastAPI app에 등록한다. app 등록 호출은 #49에서 수행한다.
- 구체 예외 6종(§12.1의 `ValidationError` 등)은 각 계산·검증 로직 구현 이슈에서 `AppError`를 상속해 정의한다.

### 16.5 PR 리뷰 체크리스트 — 계층 분리 준수

PR 리뷰 시 다음을 확인한다:

- [ ] `api/routes`가 `services`만 호출하고 `db`·`calc`를 직접 호출하지 않는가
- [ ] `services`가 HTTP 객체(Request/Response)나 원시 SQL을 다루지 않는가
- [ ] `calc`가 DB·HTTP·비즈니스 흐름에 의존하지 않는 순수 함수인가
- [ ] `db/repositories`에 비즈니스 로직(상태 전환 검증, fallback 결정 등)이 섞이지 않았는가
- [ ] 하위 계층(`calc`/`db`/`services`)이 `api`를 import하지 않는가(역방향 의존 없음)
- [ ] 오류가 `AppError` 계열로 던져지고 API 응답 포맷(API_SPEC §1.3.2)을 따르는가

---

## 17. 참고 문헌

1. Townsin, R.L. & Kwon, Y.J. (1982). "Approximate formulae for the speed loss due to added resistance in wind and waves." *RINA Transactions*.
2. Kwon, Y.J. (2008). "Speed loss due to added resistance in wind and waves." *The Naval Architect*, RINA (March 2008).
3. Kwon, Y.J. (1981). *The Effect of Weather on Ship Speed Loss*. PhD Thesis, Newcastle University. http://hdl.handle.net/10443/1579
4. NumPy NEP 19 — "Random number generator policy." https://github.com/numpy/numpy/blob/main/doc/neps/nep-0019-rng-policy.rst
5. IMO Resolution MEPC.353(78) — CII Reference Lines Guidelines (G2).
6. IMO Resolution MEPC.354(78) — CII Rating Guidelines (G4).
7. Open-Meteo Marine API documentation. https://open-meteo.com/en/docs/marine-weather-api

---

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준). 버전 번호 매핑은 커밋 메시지·헤더 기준의 추정을 포함한다.

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-07-03 | `060beb5` | v1.1 최초 작성 |
| 2026-07-03 | `9f8a7eb` | 외부 리뷰 반영 (capacity 규칙 분리 등) |
| 2026-07-04 | `bee61e9` | canonical vector 고정 + 포맷 정리 |
| 2026-07-04 | `ec1bf23` | Oracle 3차 리뷰 반영 (F-006~F-008) → v1.2 |
| 2026-07-14 | `0173105` | annotation 라벨 번호 정규화 (5개 정본 일괄) |
| 2026-07-18 | `11123ad` | 서비스 레이어 아키텍처·모듈 구조 확정 (§16) (#100) → v1.3 |
