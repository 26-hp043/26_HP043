"""데이터 점검 판정 — 이상치 · 배출량 · 완결성 (``PRD §17.4.1`` ~ ``§17.4.3`` · #513).

**순수 함수만 둔다** (``TECH_SPEC §16.3``). 무엇을 집계에 넣었는지는 ``services``가
정하고, 여기는 **값이 주어졌을 때의 판정**만 한다.

이상치는 계산에서 빼지 않는다
----------------------------
``PRD §17.1``이 계획값과 실측값을 덮어쓰지 않는다고 정했다. 이상치 판정은 **표시**를 위한
것이지 보정이 아니다 — 여기서 「틀렸으니 버린다」를 하면, 입력 실수가 아니라 실제로 기상이
나빴던 항차가 조용히 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cii_platform.calc.fuel_estimator import MIN_SPEED_KN, estimate_fuel_ton
from cii_platform.calc.precision import layer1_context

#: ``PRD §17.4.1`` ⑴ — 실적 연료 ÷ 모델 기대 연료의 **하한**. 이보다 작으면 이상치.
#:
#: ±40%는 디자인 명세 검토(2026-08-17)가 제시한 폭이며 2026-09-13 사용자 결정으로
#: 확정했다. 입력 실수(톤↔kg · 자릿수)는 대개 **수배** 차이라 이 폭 밖으로 나가고,
#: 기상·흘수 차이로 인한 정상 편차는 대개 안에 든다.
FUEL_MODEL_LOWER = Decimal("0.6")
#: ``PRD §17.4.1`` ⑴ — 같은 비의 **상한**.
FUEL_MODEL_UPPER = Decimal("1.4")
#: ``PRD §17.4.1`` ⑵ — 기록 시각으로 낸 평균 속력이 기준 속력의 이 배수를 넘으면 이상치.
SPEED_REFERENCE_MULTIPLIER = Decimal("1.5")
#: ``PRD §17.4.1`` ⑶ — 기록 속력과 시각으로 낸 속력이 이 비율 이상 벌어지면 이상치.
SPEED_MISMATCH_TOLERANCE = Decimal("0.3")

#: 이상치 사유 코드 (``API_SPEC §2.16``).
ANOMALY_FUEL_VS_MODEL = "FUEL_VS_MODEL"
ANOMALY_SPEED_ABOVE_REFERENCE = "SPEED_ABOVE_REFERENCE"
ANOMALY_SPEED_MISMATCH = "SPEED_MISMATCH"

#: ``PRD §3.3.2`` — 연료 톤 × CF(tCO₂/t) → g.
_GRAMS_PER_TON = Decimal("1000000")


@dataclass(frozen=True)
class VoyageObservation:
    """이상치 판정에 쓰는 **실측값만**.

    계획값을 넣지 않는다. 대체된 값(``PRD §8.3``)으로 이상치를 판정하면 **계획이
    이상한 것**을 실적이 이상한 것으로 보고한다 — 대체된 축은 호출부가 ``None``으로 넘긴다.

    :param distance_nm: 실적 거리. 대체됐으면 ``None``.
    :param fuel_ton: 실적 연료 합계. **유종 하나라도** 실적이 비었으면 ``None`` —
        일부만 더하면 모델보다 적게 쓴 것처럼 보인다.
    :param recorded_speed_kn: 기록된 평균 속력.
    :param sailing_hours: 실제 출항~도착 시간. 시각이 하나라도 없거나 0 이하면 ``None``.
    :param reference_speed_kn: 선박 기준 속력(제원).
    :param reference_daily_foc_ton: 선박 기준 일일 연료소모량(제원).
    """

    distance_nm: Decimal | None
    fuel_ton: Decimal | None
    recorded_speed_kn: Decimal | None
    sailing_hours: Decimal | None
    reference_speed_kn: Decimal | None
    reference_daily_foc_ton: Decimal | None


@dataclass(frozen=True)
class AnomalyJudgement:
    """판정 결과.

    ``judged``가 ``False``면 **세 검사 중 하나도 돌릴 수 없었다**는 뜻이다. 이상치
    0건과 섞으면 「제원이 없는 선박은 늘 깨끗하다」가 된다 — 호출부가 따로 센다.
    """

    codes: tuple[str, ...]
    judged: bool
    #: 실적 연료 ÷ 모델 기대 연료. 검사 ⑴을 못 돌렸으면 ``None``.
    fuel_ratio: Decimal | None
    #: 거리 ÷ 항해시간. 시각이 없으면 ``None``.
    implied_speed_kn: Decimal | None


@layer1_context
def judge_anomaly(obs: VoyageObservation) -> AnomalyJudgement:
    """세 검사를 **돌릴 수 있는 것만** 돌린다 (``PRD §17.4.1``).

    ⑴ 연료 ÷ 모델 기대 연료가 ``[0.6, 1.4]`` 밖 — 모델은 ``PRD §11.4.1`` cubic speed
       model 그 자체다(``estimate_fuel_ton``). 두 벌로 두면 항로 비교와 다른 기대값이 나온다.
    ⑵ 시각으로 낸 속력 > 기준 속력 × 1.5
    ⑶ 기록 속력과 시각으로 낸 속력의 차이 ≥ 기록 속력 × 30%

    ⑴의 속력은 **기록 속력을 먼저** 쓰고, 없으면 시각으로 낸 속력을 쓴다.
    """
    codes: list[str] = []
    judged = False

    implied: Decimal | None = None
    if obs.distance_nm is not None and obs.sailing_hours is not None and obs.sailing_hours > 0:
        implied = obs.distance_nm / obs.sailing_hours

    fuel_ratio: Decimal | None = None
    speed = obs.recorded_speed_kn if obs.recorded_speed_kn is not None else implied
    if (
        obs.distance_nm is not None
        and obs.distance_nm > 0
        and obs.fuel_ton is not None
        and speed is not None
        and speed >= MIN_SPEED_KN
        and obs.reference_speed_kn is not None
        and obs.reference_speed_kn > 0
        and obs.reference_daily_foc_ton is not None
        and obs.reference_daily_foc_ton > 0
    ):
        expected = estimate_fuel_ton(
            distance_nm=obs.distance_nm,
            speed_kn=speed,
            reference_speed_kn=obs.reference_speed_kn,
            base_daily_foc_ton=obs.reference_daily_foc_ton,
        )
        fuel_ratio = obs.fuel_ton / expected
        judged = True
        if fuel_ratio < FUEL_MODEL_LOWER or fuel_ratio > FUEL_MODEL_UPPER:
            codes.append(ANOMALY_FUEL_VS_MODEL)

    if implied is not None and obs.reference_speed_kn is not None and obs.reference_speed_kn > 0:
        judged = True
        if implied > obs.reference_speed_kn * SPEED_REFERENCE_MULTIPLIER:
            codes.append(ANOMALY_SPEED_ABOVE_REFERENCE)

    if implied is not None and obs.recorded_speed_kn is not None and obs.recorded_speed_kn > 0:
        judged = True
        if abs(implied - obs.recorded_speed_kn) >= obs.recorded_speed_kn * SPEED_MISMATCH_TOLERANCE:
            codes.append(ANOMALY_SPEED_MISMATCH)

    return AnomalyJudgement(
        codes=tuple(codes), judged=judged, fuel_ratio=fuel_ratio, implied_speed_kn=implied
    )


def co2_grams(fuel: list[tuple[Decimal, Decimal]]) -> Decimal:
    """``(연료 톤, CF)`` 목록의 CO₂ 질량(g) — ``PRD §3.3.2`` ``M = Σ fuel × 1,000,000 × CF``."""
    return sum((ton * cf * _GRAMS_PER_TON for ton, cf in fuel), Decimal(0))


def completeness_ratio(measured_g: Decimal, total_g: Decimal) -> Decimal | None:
    """데이터 완결성 — 누적 CO₂ 중 **실측으로 계산된 비율** (``PRD §17.4.3``).

    ``total_g``가 0 이하면 ``None``이다. 배출이 없는 것을 「100% 완결」로 적으면
    **데이터가 없는 선박이 가장 깨끗해 보인다.**
    """
    if total_g <= 0:
        return None
    return measured_g / total_g
