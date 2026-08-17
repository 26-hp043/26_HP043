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

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.weather import (
    NEUTRAL_FACTOR,
    simple_rule_factor,
    townsin_kwon_weather_factor,
)
from cii_platform.db.repositories import weather as weather_repo
from cii_platform.errors import ModelBreakdownError, ParameterError, WeatherFetchError

if TYPE_CHECKING:
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


# ─── fallback 체인 (PRD §11.6 · TECH_SPEC §7.3, #62) ─────────────────────────

#: ``API_SPEC §1.6`` 경고 코드.
WARNING_WEATHER_STALE = "WEATHER_STALE"
WARNING_WEATHER_NONE_FALLBACK = "WEATHER_NONE_FALLBACK"
WARNING_EXPERIMENTAL_MODEL = "EXPERIMENTAL_MODEL"
WARNING_CB_ESTIMATED = "CB_ESTIMATED"

#: ``PRD §11.6`` — 이 시각을 넘긴 캐시는 「오래됐다」로 표시하고 계산은 허용한다.
STALE_AFTER_HOURS = 6

#: ``PRD §11.6`` — 이 시각을 넘긴 캐시는 쓰지 않는다. 보정 없이 계산한다.
EXPIRED_AFTER_HOURS = 24


@dataclass(frozen=True)
class WeatherResolution:
    """기상 보정의 **결과와 그 근거**.

    ``factor``만 돌려주면 「보정을 했는가·무엇으로 했는가」가 사라진다. 요청한 모델과
    **실제로 적용된 모델**을 나눠 담는 이유가 그것이다 — fallback이 일어나면 둘이
    달라지고, 그 차이가 곧 경고의 근거다.
    """

    factor: Decimal
    model_used: str
    warnings: tuple[str, ...]
    snapshot_id: object | None = None
    synced_at: datetime | None = None


def _age_hours(fetched_at: datetime, now: datetime) -> float:
    return (now - fetched_at).total_seconds() / 3600


async def resolve_with_fallback(
    session: AsyncSession,
    *,
    weather_model: str | None,
    lat: Decimal | float | None,
    lon: Decimal | float | None,
    ship_type: str,
    at: datetime | None = None,
    provider: WeatherProvider | None = None,
    block_coefficient: Decimal | None = None,
    wave_heading_deg: float = 0.0,
) -> WeatherResolution:
    """``PRD §11.6`` 기상 장애 정책을 그대로 옮긴다.

    ====================================  ==========================================
     최신 조회 성공                         최신 값 사용
     실패 + 6시간 이내 캐시                  캐시 사용
     실패 + 6~24시간 캐시                   계산 허용 + ``WEATHER_STALE``
     실패 + 캐시 없음(또는 24시간 초과)      보정 없이 계산 + ``WEATHER_NONE_FALLBACK``
    ====================================  ==========================================

    ## 계산을 멈추지 않는다

    기상은 **보정**이지 계산의 전제가 아니다. 조회가 실패했다고 CII를 못 내면
    「바깥 서비스가 죽으면 우리 서비스도 죽는」 상태가 된다. 그래서 마지막 칸이
    ``NONE`` fallback이며, `API_SPEC §1.4`도 그 경로를 **200 + 경고**로 규정한다
    (422는 사용자가 fallback을 거부한 경우뿐이다, `[ORACLE-C-2]`).

    ## 좌표가 없으면 조회하지 않는다

    기능①(`API_SPEC §4.1`)은 위치를 받지 않는다. 좌표 없이 기상을 물으면 **어느
    바다인지 모르는 채 값을 얻는 것**이라, 요청 모델과 무관하게 보정하지 않는다.

    ## ``WEATHER_STALE``을 6시간 이내에는 붙이지 않는다

    `API_SPEC §1.6`이 이 코드의 조건을 「기상 캐시 6~24시간」으로, 문구를 「오래된
    기상 데이터를 사용 중입니다」로 확정했다. 3시간 전 값에 그 문구를 붙이면 **틀린
    말**이 된다. `PRD §11.6`의 「6시간 이내 캐시 → 캐시 사용, 경고 표시」를 어떤
    코드로 표시할지는 정본에 없어 별도 확인 대상으로 남긴다.
    """
    resolved_at = at or datetime.now(UTC)
    model = weather_model or MODEL_NONE

    if model == MODEL_NONE:
        # 요청이 NONE이면 fallback이 아니다 — 경고 없이 정상 NONE 계산이다.
        return WeatherResolution(NEUTRAL_FACTOR, MODEL_NONE, ())

    if lat is None or lon is None:
        # **요청한 보정이 적용되지 않았다는 사실은 반드시 알린다.** 좌표가 없어
        # 조회 자체가 불가능한 경우도 사용자 입장에서는 「모델을 골랐는데 적용되지
        # 않은」 것이며, 조용히 넘어가면 결과를 보정된 값으로 읽는다.
        return WeatherResolution(NEUTRAL_FACTOR, MODEL_NONE, (WARNING_WEATHER_NONE_FALLBACK,))

    snapshot = None
    warnings: list[str] = []

    if provider is not None:
        try:
            snapshot = await fetch_and_store(
                session, provider, lat=float(lat), lon=float(lon), at=resolved_at
            )
        except WeatherFetchError:
            snapshot = None

    if snapshot is None:
        snapshot, stale_warning = await _fallback_snapshot(
            session, lat=lat, lon=lon, now=resolved_at
        )
        warnings.extend(stale_warning)

    if snapshot is None:
        # 캐시도 없다 — 보정 없이 계산한다. **값을 지어내지 않는다.**
        return WeatherResolution(NEUTRAL_FACTOR, MODEL_NONE, (WARNING_WEATHER_NONE_FALLBACK,))

    factor = await resolve_weather_factor(
        session,
        weather_model=model,
        snapshot=snapshot,
        ship_type=ship_type,
        wave_heading_deg=wave_heading_deg,
        block_coefficient=block_coefficient,
    )

    if model == MODEL_TOWNSIN_KWON:
        # `PRD §11.4.2` — 실험 모델임을 결과에 표시한다.
        warnings.append(WARNING_EXPERIMENTAL_MODEL)
        if block_coefficient is None:
            # 선형 계수가 선박 제원이 아니라 선종 기본값에서 왔다 (`API_SPEC §1.6`).
            warnings.append(WARNING_CB_ESTIMATED)

    return WeatherResolution(
        factor=factor,
        model_used=model,
        warnings=tuple(warnings),
        snapshot_id=getattr(snapshot, "id", None),
        synced_at=getattr(snapshot, "fetched_at", None),
    )


async def _fallback_snapshot(
    session: AsyncSession, *, lat: Decimal | float, lon: Decimal | float, now: datetime
):
    """캐시에서 쓸 수 있는 스냅샷을 고른다. 돌려주는 둘째 값은 붙일 경고다.

    **24시간을 넘긴 값은 쓰지 않는다** (`PRD §11.6`). 이틀 전 파고로 오늘 항해를
    보정하면 보정이 아니라 잡음이다.
    """
    snapshot = await weather_repo.find_last_snapshot(
        session, lat_rounded=round_to_grid(lat), lon_rounded=round_to_grid(lon)
    )
    if snapshot is None:
        return None, []

    age = _age_hours(snapshot.fetched_at, now)
    if age > EXPIRED_AFTER_HOURS:
        return None, []
    if age > STALE_AFTER_HOURS:
        return snapshot, [WARNING_WEATHER_STALE]
    return snapshot, []
