"""함대 감축 계획 — 감속 · 추가 항해일 · 비용 요약 (``PRD §12.3.2`` · ``UIFLOW 2-10`` · #513).

**순수 함수만 둔다** (``TECH_SPEC §16.3``). 어느 선박의 어느 항차를 넣을지는 ``services``가
정한다.

감속만 다룬다 — 거리를 바꾸지 않는다
------------------------------------
``PRD §12.3.1``이 잔여 계획 **거리를 고정**했고, ``UIFLOW 2-10``의 비용 요약이 「추가 항해일」·
「용선료 손실」을 두는 것도 같은 전제다(항차를 취소하면 항해일이 줄지 늘지 않는다). 그래서
조정은 **속력을 낮추는 비율** 하나다.

연료는 cubic speed model로 다시 낸다
-----------------------------------
``fuel ∝ speed² × distance``(``PRD §11.4.1`` · ``TECH_SPEC §4.1``). ``calc/annual_simulation``
의 속도 민감도(``_shift_speed``)와 **같은 식·같은 적용 조건**이다 — 두 벌로 두면 연간 등급
관리의 「속력 −1kn」과 이 화면의 감속이 같은 선박에서 다른 연료를 낸다.

**Monte Carlo를 부르지 않는다** (``UIFLOW 2-10``) — 슬라이더를 움직일 때마다 5,000회를 선대
규모로 돌 수 없다. 결정론(``§12.3``)만 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from cii_platform.calc.annual_simulation import RemainingVoyage
from cii_platform.calc.fuel_estimator import MIN_SPEED_KN

#: ``PRD §12.3.2`` — 감속률 상한(%). 이보다 크면 요청 검증에서 막는다.
#:
#: 50%면 12kn 선박이 6kn다 — 슬로 스티밍의 실무 하한(대개 기준의 60~70%)을 이미 넘는다.
#: 상한이 없으면 99%에서 속력이 1kn로 잘려(``MIN_SPEED_KN``) 연료가 거의 0이 되고,
#: 화면은 「이만큼 줄이면 A등급」이라는 **운항할 수 없는 답**을 낸다.
MAX_REDUCTION_PERCENT = Decimal(50)

#: ``PRD §12.3.2`` 목표.
TARGET_NO_AT_RISK = "NO_AT_RISK"
TARGET_ALL_C_OR_BETTER = "ALL_C_OR_BETTER"
TARGETS: tuple[str, ...] = (TARGET_NO_AT_RISK, TARGET_ALL_C_OR_BETTER)

_HOURS_PER_DAY = Decimal(24)


@dataclass(frozen=True)
class PlannedLeg:
    """잔여 계획 항차 하나 — 유종별 연료를 **나눠** 든다.

    :class:`RemainingVoyage`는 연료를 유효 CF 하나로 합쳐 들고 있어(`#812`) 유종별 연료비를
    낼 수 없다. 이 값은 같은 스냅샷 행에서 만들고, 서비스가 두 목록의 순서를 맞춘다.
    """

    distance_nm: Decimal
    speed_kn: Decimal | None
    fuel_ton_by_type: Mapping[str, Decimal]


@dataclass(frozen=True)
class Slowdown:
    """한 선박에 감속률을 적용한 결과."""

    #: 연료를 다시 낸 잔여 계획 — ``project_deterministic``에 그대로 넣는다.
    remaining: list[RemainingVoyage]
    #: 늘어난 항해 일수 합계.
    extra_days: Decimal
    #: 유종별 절감 톤. **감속하지 않은 항차는 0이다.**
    fuel_saved_ton_by_type: dict[str, Decimal]
    #: 제원이 없어 **감속을 적용하지 못한** 항차 수 — 조용히 0% 취급하면 「줄였는데 그대로」가 된다.
    skipped_voyages: int


def _applicable(voyage: RemainingVoyage) -> bool:
    """``calc/annual_simulation._has_speed_model``과 같은 조건 — 둘이 갈리면 안 된다(`#630`)."""
    return (
        voyage.speed_kn is not None
        and voyage.reference_speed_kn is not None
        and voyage.base_daily_foc_ton is not None
    )


def apply_slowdown(
    remaining: Sequence[RemainingVoyage],
    legs: Sequence[PlannedLeg],
    reduction_percent: Decimal,
) -> Slowdown:
    """잔여 계획 항차마다 속력을 ``reduction_percent``만큼 낮춘다 (``PRD §12.3.2`` ⑴~⑶).

    .. code-block:: text

        v'        = max(v × (1 − p/100), 1.0kn)
        fuel'     = fuel × (v'/v)²                      ← cubic model, 거리 고정
        extra_day = distance/(v'×24) − distance/(v×24)

    :raises ValueError: 두 목록 길이가 다르거나 감속률이 범위 밖일 때.
    """
    if len(remaining) != len(legs):
        raise ValueError(f"remaining({len(remaining)})과 legs({len(legs)})의 길이가 다르다")
    if reduction_percent < 0 or reduction_percent > MAX_REDUCTION_PERCENT:
        raise ValueError(
            f"reduction_percent must be 0~{MAX_REDUCTION_PERCENT}: {reduction_percent}"
        )

    factor = Decimal(1) - reduction_percent / Decimal(100)
    shifted: list[RemainingVoyage] = []
    extra_days = Decimal(0)
    saved: dict[str, Decimal] = {}
    skipped = 0

    for voyage, leg in zip(remaining, legs, strict=True):
        if reduction_percent == 0:
            shifted.append(voyage)
            continue
        if not _applicable(voyage):
            skipped += 1
            shifted.append(voyage)
            continue
        speed = Decimal(str(voyage.speed_kn))
        new_speed = max(speed * factor, MIN_SPEED_KN)
        ratio = (new_speed / speed) ** 2
        shifted.append(
            RemainingVoyage(
                distance_nm=voyage.distance_nm,
                fuel_ton=float(Decimal(str(voyage.fuel_ton)) * ratio),
                cf=voyage.cf,
                speed_kn=float(new_speed),
                reference_speed_kn=voyage.reference_speed_kn,
                base_daily_foc_ton=voyage.base_daily_foc_ton,
            )
        )
        extra_days += leg.distance_nm / (new_speed * _HOURS_PER_DAY) - leg.distance_nm / (
            speed * _HOURS_PER_DAY
        )
        for fuel_type, ton in leg.fuel_ton_by_type.items():
            saved[fuel_type] = saved.get(fuel_type, Decimal(0)) + ton * (Decimal(1) - ratio)

    return Slowdown(
        remaining=shifted,
        extra_days=extra_days,
        fuel_saved_ton_by_type=saved,
        skipped_voyages=skipped,
    )


@dataclass(frozen=True)
class CostSummary:
    """비용 요약 (``UIFLOW 2-10`` 네 칸 · ``PRD §12.3.2`` ⑷).

    **단가가 비면 그 칸은 ``None``이다 — 0으로 채우지 않는다.** 0이면 「손익 영향 없음」으로
    읽힌다. 어느 단가가 비었는지는 ``missing_*``가 말한다.
    """

    extra_days: Decimal
    charter_loss_usd: Decimal | None
    fuel_saving_usd: Decimal | None
    net_usd: Decimal | None
    missing_charter_rates: tuple[str, ...]
    missing_fuel_prices: tuple[str, ...]


def summarize_costs(
    *,
    extra_days_by_vessel: Mapping[str, Decimal],
    fuel_saved_by_type: Mapping[str, Decimal],
    charter_usd_per_day: Mapping[str, Decimal],
    fuel_usd_per_ton: Mapping[str, Decimal],
) -> CostSummary:
    """용선료 손실 · 연료비 절감 · 순손익 (``PRD §12.3.2`` ⑷).

    .. code-block:: text

        용선료 손실 = Σ(선박별 추가 항해일 × 그 선박 일일 용선료)
        연료비 절감 = Σ(유종별 절감 톤 × 그 유종 단가)
        순손익      = 연료비 절감 − 용선료 손실

    **추가 항해일이 0인 선박·절감 톤이 0인 유종은 단가가 없어도 된다** — 곱할 것이 없다.
    값이 있는데 단가가 없으면 그 칸 전체가 ``None``이다(일부만 더하면 손실이 작아 보인다).
    """
    extra_total = sum(extra_days_by_vessel.values(), Decimal(0))

    missing_charter = tuple(
        sorted(
            v
            for v, days in extra_days_by_vessel.items()
            if days > 0 and v not in charter_usd_per_day
        )
    )
    charter_loss = (
        None
        if missing_charter
        else sum(
            (days * charter_usd_per_day[v] for v, days in extra_days_by_vessel.items() if days > 0),
            Decimal(0),
        )
    )

    missing_fuel = tuple(
        sorted(t for t, ton in fuel_saved_by_type.items() if ton > 0 and t not in fuel_usd_per_ton)
    )
    fuel_saving = (
        None
        if missing_fuel
        else sum(
            (ton * fuel_usd_per_ton[t] for t, ton in fuel_saved_by_type.items() if ton > 0),
            Decimal(0),
        )
    )

    net = None if charter_loss is None or fuel_saving is None else fuel_saving - charter_loss
    return CostSummary(
        extra_days=extra_total,
        charter_loss_usd=charter_loss,
        fuel_saving_usd=fuel_saving,
        net_usd=net,
        missing_charter_rates=missing_charter,
        missing_fuel_prices=missing_fuel,
    )


def target_rating_for(target: str, *, prior_ratings: Sequence[str | None]) -> str:
    """선박마다 **넘지 말아야 할 등급** (``PRD §12.3.2`` ⑸).

    - ``ALL_C_OR_BETTER`` → ``C``
    - ``NO_AT_RISK`` → ``D`` — 단 직전 2개 연도가 확정 D면 ``C``(올해도 D면 3년 연속, ``§3.3.7``)
    """
    if target == TARGET_ALL_C_OR_BETTER:
        return "C"
    if target == TARGET_NO_AT_RISK:
        if len(prior_ratings) == 2 and all(r == "D" for r in prior_ratings):
            return "C"
        return "D"
    raise ValueError(f"unknown target: {target}")


def meets_target(rating: str, target_rating: str) -> bool:
    """``rating``이 ``target_rating`` 이상인가 — A가 가장 좋다."""
    order = "ABCDE"
    return order.index(rating) <= order.index(target_rating)
