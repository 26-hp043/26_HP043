"""기상 조회·보정 서비스 (TECH_SPEC §3 · §7 · §8, #61).

조회(어댑터) · 저장(저장소) · 계산(순수 모델)을 **엮기만** 한다. 세 가지가 각각
다른 모듈에 있는 이유는 **바뀌는 이유가 서로 다르기** 때문이다 — 외부 API 형식,
DB 스키마, 경험식은 함께 바뀌지 않는다.

## 이 모듈이 정하지 않는 것

**신선도 정책이 여기 없다.** `TECH_SPEC §7.3`의 24시간 TTL·6시간 경고와
`WEATHER_STALE`·`WEATHER_NONE_FALLBACK` 경고는 `#62`(fallback 체인)의 몫이다.
여기서는 「조회하면 저장하고, 값을 주면 factor를 낸다」까지만 한다 — 정책이 섞이면
`#62`가 이 모듈을 고쳐야 하고, 그때 조회·저장까지 함께 흔들린다.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.weather import (
    NEUTRAL_FACTOR,
    simple_rule_factor,
    townsin_kwon_weather_factor,
)
from cii_platform.db.repositories import weather as weather_repo
from cii_platform.errors import ModelBreakdownError, ParameterError

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.weather.open_meteo import WeatherObservation, WeatherProvider

#: ``API_SPEC §4.1`` weather_model enum.
MODEL_NONE = "NONE"
MODEL_SIMPLE_RULE = "SIMPLE_RULE"
MODEL_TOWNSIN_KWON = "TOWNSIN_KWON_ALPHA"

#: ``weather_model_parameter.model_version`` — 계수를 담고 있는 모델 이름.
COEFFICIENT_MODEL_VERSION = "TOWNSIN_KWON_ALPHA"

#: ``TECH_SPEC §7.3`` 캐시 격자 — 0.5° 단위로 반올림한다.
GRID_DEGREES = Decimal("0.5")


def round_to_grid(value: Decimal | float) -> Decimal:
    """좌표를 캐시 격자(0.5°)로 반올림한다 (``TECH_SPEC §7.3``).

    **격자를 쓰는 이유는 캐시 적중률**이다. 항로상의 좌표는 매번 조금씩 다르므로
    원좌표로 캐시하면 같은 해역을 지나면서도 매번 새로 조회하게 된다.

    컬럼이 ``NUMERIC(4,1)``이라(``DB_SCHEMA §2.13``) 소수 한 자리로 떨어져야 한다 —
    0.5 격자가 그 정밀도와 맞는다.
    """
    decimal_value = Decimal(str(value))
    return (decimal_value / GRID_DEGREES).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    ) * GRID_DEGREES


def _decimal_or_none(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


async def fetch_and_store(
    session: AsyncSession,
    provider: WeatherProvider,
    *,
    lat: float,
    lon: float,
    at: datetime,
):
    """기상을 조회해 스냅샷으로 남기고 그 행을 돌려준다.

    **조회한 것은 반드시 남긴다.** 계산에 쓴 기상 값을 나중에 물을 수 있어야 하고
    (``TECH_SPEC §5.4``), 남기지 않으면 같은 계산을 재현할 수 없다.

    ``commit``은 호출부가 한다 — 이 조회는 보통 계산 트랜잭션 안에서 일어나고,
    여기서 커밋하면 계산이 실패해도 스냅샷만 남는다.

    :raises WeatherFetchError: 어댑터가 올린다. 여기서 잡지 않는다 — fallback 여부는
        호출자가 정한다(``TECH_SPEC §12.2`` 3항).
    """
    observation: WeatherObservation = await provider.fetch(lat, lon, at)
    return await weather_repo.insert_snapshot(
        session,
        lat=Decimal(str(observation.lat)),
        lon=Decimal(str(observation.lon)),
        lat_rounded=round_to_grid(observation.lat),
        lon_rounded=round_to_grid(observation.lon),
        fetched_at=observation.fetched_at,
        wave_height_m=_decimal_or_none(observation.wave_height_m),
        wave_direction_deg=_decimal_or_none(observation.wave_direction_deg),
        wave_period_s=_decimal_or_none(observation.wave_period_s),
        wind_speed_ms=_decimal_or_none(observation.wind_speed_ms),
        wind_direction_deg=_decimal_or_none(observation.wind_direction_deg),
        source=observation.source,
    )


async def load_coefficients(session: AsyncSession, ship_type: str) -> tuple[Decimal, Decimal]:
    """``CU = cu_a × BN + cu_b``의 계수를 테이블에서 읽는다 (마이그레이션 019).

    **코드에 박지 않는 이유는 `#434`와 같다** — 값이 바뀌면 계산 결과가 달라지는데
    코드에 있으면 그 변경이 배포에 묶인다.

    :raises ParameterError: 그 선종의 계수가 없을 때. 사용자가 입력으로 고칠 수 없는
        서버 데이터 문제라 422가 아니라 409다(``errors.ParameterError``).
    """
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(
                "SELECT key, value FROM weather_model_parameter "
                "WHERE model_version = :version AND key IN (:a, :b)"
            ),
            {
                "version": COEFFICIENT_MODEL_VERSION,
                "a": f"cu_a.{ship_type}",
                "b": f"cu_b.{ship_type}",
            },
        )
    ).all()
    values = {row.key: Decimal(row.value) for row in rows}

    cu_a = values.get(f"cu_a.{ship_type}")
    cu_b = values.get(f"cu_b.{ship_type}")
    if cu_a is None or cu_b is None:
        raise ParameterError(
            f"이 선종의 기상 모델 계수가 없습니다: {ship_type}. "
            "기상 보정 없이 계산하거나 파라미터를 적재하세요."
        )
    return cu_a, cu_b


async def resolve_weather_factor(
    session: AsyncSession,
    *,
    weather_model: str | None,
    snapshot,
    ship_type: str,
    wave_heading_deg: float = 0.0,
    block_coefficient: Decimal | None = None,
) -> Decimal:
    """모델·스냅샷 → ``weather_factor`` (``TECH_SPEC §7.1`` 디스패치).

    ``snapshot``이 없거나 모델이 ``NONE``이면 ``1.0``이다 — 보정하지 않는다는 뜻이고,
    ``input_hash``도 그 값으로 계산된다(``§5.3`` `[ORACLE-S-5]`).

    **경험식의 실패를 그대로 올리지 않는다.** `calc` 계층은 `ValueError`를 던지는데
    (`TECH_SPEC §12.2` 1항), 그대로 두면 500이 된다. 적용 범위를 벗어난 것은 서버
    오류가 아니므로 ``ModelBreakdownError``(422)로 옮긴다.
    """
    model = weather_model or MODEL_NONE
    if model == MODEL_NONE or snapshot is None:
        return NEUTRAL_FACTOR

    if model == MODEL_SIMPLE_RULE:
        return simple_rule_factor(
            hs_m=_float_or_none(snapshot.wave_height_m),
            wind_speed_ms=_float_or_none(snapshot.wind_speed_ms),
        )

    if model == MODEL_TOWNSIN_KWON:
        hs = _float_or_none(snapshot.wave_height_m)
        if hs is None:
            # 파고가 없으면 이 모델은 성립하지 않는다. 0으로 채우면 「잔잔한 바다」가
            # 되어 보정이 사라지고, 그 사실이 결과에 드러나지 않는다.
            raise ModelBreakdownError("파고 데이터가 없어 기상 보정 모델을 적용할 수 없습니다.")
        cu_a, cu_b = await load_coefficients(session, ship_type)
        try:
            return townsin_kwon_weather_factor(
                hs_m=hs,
                ship_type=ship_type,
                cu_a=cu_a,
                cu_b=cu_b,
                wave_heading_deg=wave_heading_deg,
                block_coefficient=block_coefficient,
            )
        except ValueError as exc:
            raise ModelBreakdownError(
                f"기상 조건이 너무 가혹하여 모델을 적용할 수 없습니다. ({exc})"
            ) from exc

    raise ModelBreakdownError(f"알 수 없는 기상 모델입니다: {model}")


def _float_or_none(value) -> float | None:
    return None if value is None else float(value)
