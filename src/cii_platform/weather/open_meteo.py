"""Open-Meteo 기상 조회 (TECH_SPEC §7.2, #61).

## 두 엔드포인트를 함께 부른다

파고는 Marine API, 풍속은 Forecast API다(``§7.2`` 표). 한 곳에서 둘 다 주지 않으므로
호출이 둘이며, **한쪽이 실패해도 다른 쪽 값은 쓴다** — 파고만 있으면
``TOWNSIN_KWON_ALPHA``가 돌고, 풍속만 있으면 ``SIMPLE_RULE``이 부분적으로 돈다.
둘 다 실패해야 조회 실패다.

## 시간을 고르는 규칙

Open-Meteo는 **시간별 배열**을 준다(``hourly.time`` + 값 배열). 우리가 필요한 것은
특정 시각의 값이므로 **그 시각에 가장 가까운 정시**를 고른다. 배열 첫 값을 쓰면
「오늘 0시의 파고로 오후 항해를 보정」하는 일이 생긴다.

## 타임아웃 5초

이슈(`#61`)가 정한 값이다. 기상 조회는 **계산의 부속**이라, 여기서 오래 붙잡으면
계산 요청 전체가 느려진다. 실패는 `#62`의 fallback 체인이 받는다 — 이 모듈은
**실패를 숨기지 않고 그대로 올린다.**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from cii_platform.errors import WeatherFetchError

#: ``TECH_SPEC §7.2`` — 파고·파향·주기.
MARINE_ENDPOINT = "https://marine-api.open-meteo.com/v1/marine"

#: ``TECH_SPEC §7.2`` — 풍속·풍향.
WIND_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

#: 조회 타임아웃(초). `#61` 완료 기준.
TIMEOUT_SECONDS = 5.0

#: ``weather_snapshot.source``에 남길 출처 (``DB_SCHEMA §2.13``).
SOURCE_MARINE = "open_meteo_marine"
SOURCE_WIND = "open_meteo_forecast"
SOURCE_MERGED = "open_meteo_marine+forecast"


@dataclass(frozen=True)
class WeatherObservation:
    """한 지점·한 시각의 기상 (``TECH_SPEC §7.1``의 ``WeatherSnapshot`` dataclass).

    ORM 모델(`db.models.weather_snapshot.WeatherSnapshot`)과 이름을 나눈 이유는
    **저장 형태와 조회 결과를 구분하기 위해서**다. 이 값은 아직 저장되지 않았고,
    저장 여부와 무관하게 계산에 쓸 수 있다.
    """

    lat: float
    lon: float
    fetched_at: datetime
    wave_height_m: float | None = None
    wave_direction_deg: float | None = None
    wave_period_s: float | None = None
    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    source: str = SOURCE_MERGED

    @property
    def is_empty(self) -> bool:
        """쓸 수 있는 값이 하나도 없는가. 빈 관측은 저장하지 않는다."""
        return all(
            value is None
            for value in (
                self.wave_height_m,
                self.wave_direction_deg,
                self.wave_period_s,
                self.wind_speed_ms,
                self.wind_direction_deg,
            )
        )


class WeatherProvider(Protocol):
    """기상 조회의 경계 (``TECH_SPEC §7.1``).

    테스트가 갈아 끼울 수 있게 프로토콜로 둔다 — **CI는 네트워크를 쓰지 않는다.**
    실 API를 부르는 테스트는 외부 서비스의 가용성에 결과가 묶여, 실패했을 때
    우리 코드가 틀린 것인지 알 수 없다.
    """

    async def fetch(self, lat: float, lon: float, at: datetime) -> WeatherObservation: ...


def _nearest_index(times: list[str], at: datetime) -> int | None:
    """``at``에 가장 가까운 정시의 인덱스. 배열이 비면 ``None``.

    Open-Meteo의 ``time``은 ``2026-08-18T00:00`` 형태(UTC, 초 없음)다.
    """
    best: tuple[float, int] | None = None
    for index, raw in enumerate(times):
        try:
            moment = datetime.fromisoformat(raw).replace(tzinfo=UTC)
        except ValueError:
            continue
        distance = abs((moment - at).total_seconds())
        if best is None or distance < best[0]:
            best = (distance, index)
    return None if best is None else best[1]


def _pick(payload: dict, key: str, index: int) -> float | None:
    """``hourly[key][index]``를 float로. 없으면 ``None``.

    **비어 있는 것과 0을 구분한다.** Open-Meteo는 값이 없는 시간대에 ``null``을 주고,
    그것을 0으로 바꾸면 「파고 0m의 잔잔한 바다」가 되어 보정이 사라진다.
    """
    values = (payload.get("hourly") or {}).get(key)
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    return None if value is None else float(value)


class OpenMeteoProvider:
    """Open-Meteo 실 호출 구현.

    ``client_factory``를 주입할 수 있게 둔다 — 테스트는 `httpx.MockTransport`를 실은
    클라이언트를 넣는다. 기본값은 매 호출마다 새 클라이언트를 만든다: 연결 재사용보다
    **요청 간 상태가 남지 않는 것**이 중요하고, 기상 조회는 계산당 한두 번이다.
    """

    def __init__(
        self,
        *,
        client_factory=None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))

    async def fetch(self, lat: float, lon: float, at: datetime) -> WeatherObservation:
        """파고·풍속을 조회해 하나로 합친다.

        :raises WeatherFetchError: 두 엔드포인트가 **모두** 실패했을 때.
        """
        marine = await self._get(
            MARINE_ENDPOINT,
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": "wave_height,wave_direction,wave_period",
            },
        )
        wind = await self._get(
            WIND_ENDPOINT,
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": "wind_speed_10m,wind_direction_10m",
            },
        )

        if marine is None and wind is None:
            raise WeatherFetchError(
                "기상 데이터를 가져오지 못했습니다. 네트워크 또는 외부 서비스 상태를 확인하세요."
            )

        observation = WeatherObservation(
            lat=lat,
            lon=lon,
            fetched_at=datetime.now(UTC),
            source=_source_of(marine, wind),
        )
        if marine is not None:
            index = _nearest_index((marine.get("hourly") or {}).get("time") or [], at)
            if index is not None:
                observation = _replace(
                    observation,
                    wave_height_m=_pick(marine, "wave_height", index),
                    wave_direction_deg=_pick(marine, "wave_direction", index),
                    wave_period_s=_pick(marine, "wave_period", index),
                )
        if wind is not None:
            index = _nearest_index((wind.get("hourly") or {}).get("time") or [], at)
            if index is not None:
                observation = _replace(
                    observation,
                    wind_speed_ms=_pick(wind, "wind_speed_10m", index),
                    wind_direction_deg=_pick(wind, "wind_direction_10m", index),
                )

        if observation.is_empty:
            raise WeatherFetchError(
                "기상 응답에 쓸 수 있는 값이 없습니다. 요청한 좌표·시각을 확인하세요."
            )
        return observation

    async def _get(self, url: str, params: dict) -> dict | None:
        """한 엔드포인트 조회. **실패를 예외가 아니라 ``None``으로 돌려준다.**

        둘 중 하나만 실패해도 나머지는 쓸 수 있어야 하므로, 개별 실패를 여기서
        예외로 만들면 호출부가 매번 잡아야 한다. 「둘 다 실패」의 판단은 호출부에 있다.
        """
        try:
            async with self._client_factory() as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None


def _source_of(marine: dict | None, wind: dict | None) -> str:
    if marine is not None and wind is not None:
        return SOURCE_MERGED
    return SOURCE_MARINE if marine is not None else SOURCE_WIND


def _replace(observation: WeatherObservation, **changes) -> WeatherObservation:
    from dataclasses import replace

    return replace(observation, **changes)
