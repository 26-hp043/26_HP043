"""속도 기반 연료 추정 — cubic speed model (#75).

TECH_SPEC §4 cubic speed model. 기능②(시나리오 비교, #57)이 직항/우회/감속
시나리오의 ``fuel_ton``을 계산할 때 쓴다. 아직 항해하지 않은 가상 경로이므로
연료를 입력받지 않고 **추정**해야 한다.

대조 — 기능①(#55)은 ``fuel_uses[].fuel_ton``을 **입력**으로 받으므로 이 함수를
쓰지 않는다. 반환 타입은 ``Decimal``이다 (TECH_SPEC §4.3 [ORACLE-S-2 정정] — Layer 1
정밀도 경계 명확화).
"""

from __future__ import annotations

from decimal import Decimal

from cii_platform.calc.precision import layer1_context, validate_layer1_result

#: TECH_SPEC §4.4 — weather_model=NONE일 때의 기상 보정 계수.
DEFAULT_WEATHER_FACTOR = Decimal("1.0")

#: 시간 환산 상수 (24시간 = 1일).
_HOURS_PER_DAY = Decimal("24")

#: VAL-009 최소 속도 (PRD §9.1, TECH_SPEC §4.2). 0이 아니라 1.0kn 경계.
MIN_SPEED_KN = Decimal("1.0")


@layer1_context
def estimate_fuel_ton(
    *,
    distance_nm: Decimal,
    speed_kn: Decimal,
    reference_speed_kn: Decimal,
    base_daily_foc_ton: Decimal,
    weather_factor: Decimal | None = None,
) -> Decimal:
    """cubic speed model로 연료 소모량(ton)을 추정한다 (#75, TECH_SPEC §4.1).

    .. code-block:: text

        duration_days = distance_nm / speed_kn / 24
        speed_factor  = (speed_kn / reference_speed_kn) ** 3
        fuel_ton      = base_daily_foc_ton × speed_factor × weather_factor × duration_days

    **가드 조건** (TECH_SPEC §4.2) — 위반 시 ``ValueError``:

    - ``speed_kn`` >= 1.0 (VAL-009). 경계 1.0kn은 허용.
    - ``reference_speed_kn`` > 0
    - ``distance_nm`` > 0 (VAL-002)
    - ``base_daily_foc_ton`` > 0
    - ``weather_factor`` > 0 — ``None``이면 :data:`DEFAULT_WEATHER_FACTOR`
      (TECH_SPEC §4.4, weather_model=NONE)

    큐빅 모델은 **총 연료량**만 산정한다. 연료 비율 배분은 호출부 책임이다
    (TECH_SPEC §4.3 — "총 연료 소모량을 산정한 후 연료 비율로 배분한다").

    :returns: 추정 연료 소모량(ton). ``Decimal``이며 Layer 1 컨텍스트 안에서 계산된다.
    """
    if weather_factor is None:
        weather_factor = DEFAULT_WEATHER_FACTOR

    if speed_kn < MIN_SPEED_KN:
        raise ValueError(f"speed_kn must be >= 1.0 (VAL-009): got {speed_kn}")
    if reference_speed_kn <= 0:
        raise ValueError(f"reference_speed_kn must be > 0: got {reference_speed_kn}")
    if distance_nm <= 0:
        raise ValueError(f"distance_nm must be > 0 (VAL-002): got {distance_nm}")
    if base_daily_foc_ton <= 0:
        raise ValueError(f"base_daily_foc_ton must be > 0: got {base_daily_foc_ton}")
    if weather_factor <= 0:
        raise ValueError(f"weather_factor must be > 0: got {weather_factor}")

    # 정수 지수 3 — Decimal ** Decimal 이 아니라 Decimal ** int라 §1.2.2 _decimal_power
    # 제약(분수 지수)과 무관하게 정확하다.
    speed_ratio = speed_kn / reference_speed_kn
    speed_factor = speed_ratio**3
    duration_days = distance_nm / speed_kn / _HOURS_PER_DAY

    fuel_ton = base_daily_foc_ton * speed_factor * weather_factor * duration_days
    return validate_layer1_result(fuel_ton, "fuel_ton")
