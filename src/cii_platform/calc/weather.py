"""기상 보정 모델 — TOWNSIN_KWON_ALPHA · SIMPLE_RULE (TECH_SPEC §3 · §8, #61).

**순수 함수만 둔다.** DB도 HTTP도 여기 없다 — 계수는 인자로 받고, 기상 값도 인자로
받는다. `#434`가 Monte Carlo 분포를 테이블에서 읽어 엔진에 넘긴 것과 같은 구성이다.

## 두 모델의 성격이 다르다

===================  ======================================================
 TOWNSIN_KWON_ALPHA   경험식(`Townsin & Kwon 1982` · `Kwon 2008`). **실험 모델**이며
                      적용 범위 밖에서는 **계산을 중단한다**
 SIMPLE_RULE          선형 근사(±30%). **데모 안정성용 fallback**이라 중단하지 않고
                      입력을 clamp하고 상한을 씌운다
===================  ======================================================

그래서 음수 입력의 처리가 서로 다르다 — 앞은 `ValueError`, 뒤는 `max(x, 0)`이다
(`TECH_SPEC §3.5` · `§8.2` `[ORACLE-M-2]`). **한쪽 규칙을 다른 쪽에 옮기지 말 것.**
경험식에서 음수를 조용히 0으로 바꾸면 「데이터가 이상하다」는 신호가 사라지고,
fallback에서 예외를 던지면 fallback이 아니게 된다.

## 반환값은 ``Decimal``이다

``weather_factor``는 연료 추정(`calc.fuel_estimator`)의 곱셈 인자이자
``input_hash``의 재료다(`TECH_SPEC §5.3` `[ORACLE-S-5]`). 두 곳 모두 Layer 1이라
``float``로 넘기면 그 자리에서 정밀도가 갈린다.

**단, Beaufort Number만은 `float` 연산이다.** `§3.3.2`가 `round(3.5 × √Hs)`를
파이썬 내장 `round`(banker's rounding)로 명시하고 `[ORACLE-M-1]`이 그 차이를 알면서
허용했다 — 경험식 오차(±20%) 대비 무시할 수준이라는 판단이다. 여기서 `Decimal.sqrt`로
바꾸면 **정본이 확정한 값과 다른 BN이 나올 수 있다.**
"""

from __future__ import annotations

import math
from decimal import Decimal

#: ``TECH_SPEC §3.3.1`` Cβ — 파향별 방향 감소 계수. 사이값은 선형 보간한다.
CBETA_TABLE: tuple[tuple[int, Decimal], ...] = (
    (0, Decimal("1.000")),
    (30, Decimal("0.810")),
    (60, Decimal("0.529")),
    (90, Decimal("0.250")),
    (120, Decimal("0.471")),
    (150, Decimal("0.690")),
    (180, Decimal("0.500")),
)

#: ``TECH_SPEC §3.3.3`` Cform — 선종별 선형 계수.
CFORM: dict[str, Decimal] = {
    "BULK_CARRIER": Decimal("0.90"),
    "TANKER": Decimal("0.90"),
    "CONTAINER_SHIP": Decimal("1.10"),
    "GENERAL_CARGO_SHIP": Decimal("0.95"),
    "LNG_CARRIER": Decimal("1.00"),
}

#: ``TECH_SPEC §3.3.3`` — 각 Cform이 성립하는 CB 범위. ``None``은 상한 없음.
#:
#: **범위를 벗어나도 거부하지 않는다.** 정본이 그 경우의 대체값을 정하지 않았고,
#: 임의로 다른 선종의 값을 빌려 오면 그 사실이 결과에 드러나지 않는다. 대신
#: :func:`cform_applies` 로 물어볼 수 있게 두어, 경고를 낼지는 호출부가 정한다.
CFORM_CB_RANGE: dict[str, tuple[Decimal, Decimal | None]] = {
    "BULK_CARRIER": (Decimal("0.75"), None),
    "TANKER": (Decimal("0.75"), None),
    "CONTAINER_SHIP": (Decimal("0.55"), Decimal("0.75")),
    "GENERAL_CARGO_SHIP": (Decimal("0.70"), None),
    "LNG_CARRIER": (Decimal("0.70"), Decimal("0.80")),
}

#: ``TECH_SPEC §3.3.3`` — CB를 모를 때의 선종별 기본값.
DEFAULT_CB: dict[str, Decimal] = {
    "BULK_CARRIER": Decimal("0.80"),
    "TANKER": Decimal("0.80"),
    "CONTAINER_SHIP": Decimal("0.65"),
    "GENERAL_CARGO_SHIP": Decimal("0.75"),
    "LNG_CARRIER": Decimal("0.75"),
}

#: ``TECH_SPEC §3.3.2`` — 경험식의 적용 상한. 넘으면 계산하지 않는다.
MAX_BEAUFORT_NUMBER = 8

#: ``TECH_SPEC §8.1`` SIMPLE_RULE 계수.
SIMPLE_RULE_HS_COEFFICIENT = Decimal("0.02")
SIMPLE_RULE_WIND_COEFFICIENT = Decimal("0.005")

#: ``TECH_SPEC §8.3`` — SIMPLE_RULE 상한. 파고 25m·풍속 100m/s 이상은 비현실적이다.
SIMPLE_RULE_MAX_FACTOR = Decimal("2.0")

#: ``TECH_SPEC §7.1`` — 기상 보정을 하지 않을 때의 값.
NEUTRAL_FACTOR = Decimal("1.0")


def beaufort_number(hs_m: float) -> int:
    """유의파고 → Beaufort Number (``TECH_SPEC §3.3.2``).

    ``BN = round(3.5 × √Hs)``. 반올림은 **파이썬 내장 `round`**이며 짝수 반올림이다
    (`round(2.5) == 2`) — `[ORACLE-M-1]`이 시스템 전역 정책(`ROUND_HALF_UP`)과 다름을
    알고도 허용했다. 여기서 정책을 통일하면 정본이 확정한 값과 달라진다.
    """
    if hs_m < 0:
        raise ValueError(f"Hs must be >= 0: got {hs_m}")
    return round(3.5 * math.sqrt(hs_m))


def interpolate_cbeta(wave_heading_deg: float) -> Decimal:
    """파향 → Cβ. 표에 없는 각도는 **이웃 두 점의 선형 보간**이다 (``§3.3.1``).

    표를 그대로만 쓰면 45°가 30°나 60° 중 하나로 스냅되어, 각도가 1° 달라질 때
    계수가 계단처럼 뛴다. 보간이 없으면 그 계단이 곧 결과의 불연속이 된다.

    **음수·360° 초과 각도는 0~360으로 접는다.** 파향은 방위각이라 `-30°`와 `330°`가
    같은 방향이고, 거부하면 정상 입력이 막힌다. 180°를 넘는 각(예: 210°)은 대칭이라
    `360 - x`로 접는다 — 표가 0~180만 정의하기 때문이다.
    """
    angle = float(wave_heading_deg) % 360.0
    if angle > 180.0:
        angle = 360.0 - angle

    previous_deg, previous_value = CBETA_TABLE[0]
    for degree, value in CBETA_TABLE:
        if angle == degree:
            return value
        if angle < degree:
            span = Decimal(degree - previous_deg)
            ratio = (Decimal(str(angle)) - Decimal(previous_deg)) / span
            return previous_value + (value - previous_value) * ratio
        previous_deg, previous_value = degree, value
    return previous_value


def townsin_kwon_weather_factor(
    *,
    hs_m: float,
    ship_type: str,
    cu_a: Decimal,
    cu_b: Decimal,
    wave_heading_deg: float = 0.0,
    block_coefficient: Decimal | None = None,
) -> Decimal:
    """``TECH_SPEC §3.5`` 알고리즘.

    ``cu_a``·``cu_b``는 ``CU = cu_a × BN + cu_b``의 계수이며 **테이블에서 온다**
    (`weather_model_parameter`, 마이그레이션 019). 코드에 박지 않는 이유는 `#434`와
    같다 — 값이 바뀌면 계산 결과가 달라지는데 코드에 있으면 그 변경이 배포에 묶인다.

    **계수가 없는 선종은 계산하지 않는다** — 13종 중 정의된 것은 5종뿐이고
    (``§3.3.2``·``§3.3.3``), 없는 선종에 다른 선종의 값을 빌려 쓰면 **그 사실이
    결과에 드러나지 않는다.**

    ``block_coefficient``는 Cform 값을 **고르지 않는다.** ``§3.3.3`` 표는 선종당 한
    값이고 CB 범위는 그 값이 성립하는 조건이다. 범위를 벗어난 선박의 대체값을 정본이
    정하지 않았으므로 여기서는 판단하지 않고, :func:`cform_applies`로 물어볼 수 있게만
    둔다(``§3.6`` 한계).

    :raises ValueError: 파고 음수 · BN 상한 초과 · 속도 손실 100% 이상 · 미지원 선종.
        서비스 계층이 이 예외를 ``ModelBreakdownError``로 옮긴다(``TECH_SPEC §12.2``).
    """
    if ship_type not in CFORM:
        raise ValueError(
            f"Townsin-Kwon 계수가 정의되지 않은 선종입니다: {ship_type}. "
            f"지원 선종: {', '.join(sorted(CFORM))}"
        )

    bn = beaufort_number(hs_m)
    if bn > MAX_BEAUFORT_NUMBER:
        raise ValueError(
            f"BN={bn} (Hs={hs_m}m). 경험식의 적용 범위(BN {MAX_BEAUFORT_NUMBER})를 넘었습니다."
        )

    cbeta = interpolate_cbeta(wave_heading_deg)
    cu = cu_a * Decimal(bn) + cu_b
    cform = CFORM[ship_type]

    delta_v_pct = cbeta * cu * cform
    if delta_v_pct >= 100:
        raise ValueError(
            f"속도 손실 {delta_v_pct:.1f}% ≥ 100%. 기상 입력이 잘못되었거나 모델이 무너졌습니다."
        )

    return NEUTRAL_FACTOR / (NEUTRAL_FACTOR - delta_v_pct / Decimal(100))


def cform_applies(ship_type: str, block_coefficient: Decimal | None) -> bool:
    """이 선박의 CB가 ``Cform``이 성립하는 범위 안인지 (``TECH_SPEC §3.3.3``).

    범위를 벗어나도 계산은 된다 — 정본이 대체값을 정하지 않았기 때문이다. 다만
    **그 결과가 표의 조건 밖이라는 사실**은 알 수 있어야 하므로, 판단을 값으로
    돌려준다. 경고를 낼지는 호출부가 정한다.

    CB를 모르면(``None``) 선종 기본값을 쓰므로 항상 범위 안이다.
    """
    if ship_type not in CFORM_CB_RANGE:
        return False
    cb = block_coefficient if block_coefficient is not None else DEFAULT_CB[ship_type]
    low, high = CFORM_CB_RANGE[ship_type]
    return cb >= low and (high is None or cb < high)


def simple_rule_factor(*, hs_m: float | None, wind_speed_ms: float | None) -> Decimal:
    """``TECH_SPEC §8`` — 선형 근사 fallback.

    **중단하지 않는다.** 이 모델의 용도가 「데모 안정성 확보 및 fallback」(``§8.3``)이라,
    입력이 이상하면 예외가 아니라 clamp로 답한다(``§8.2`` `[ORACLE-M-2]`) — API가
    음수 파고를 주는 일이 실제로 있고, 그때 계산이 멈추면 fallback이 fallback이 아니다.

    상한 2.0도 같은 취지다(``§8.3``). 파고 25m·풍속 100m/s를 넘는 입력은 데이터
    오류일 가능성이 높은데, 그 값을 그대로 곱하면 연료 추정이 통째로 비현실적이 된다.
    """
    hs = max(Decimal(str(hs_m or 0.0)), Decimal(0))
    wind = max(Decimal(str(wind_speed_ms or 0.0)), Decimal(0))

    factor = NEUTRAL_FACTOR + hs * SIMPLE_RULE_HS_COEFFICIENT + wind * SIMPLE_RULE_WIND_COEFFICIENT
    return min(factor, SIMPLE_RULE_MAX_FACTOR)
