"""기상 데이터 어댑터 (TECH_SPEC §7, #61).

**바깥 세계로 나가는 쪽**이라 별도 패키지로 둔다 — `mail/`(SMTP)·`reports/`(PDF·CSV)와
같은 자리다. `api/`는 들어오는 HTTP를 다루고, 여기는 나가는 HTTP를 다룬다.

`#61` 이슈 본문은 `api/weather.py`를 제안했으나 그 자리는 요청 처리 계층이며,
어댑터를 섞으면 `api/`가 두 방향을 함께 갖게 된다(`TECH_SPEC §16.1` 계층).
"""

from cii_platform.weather.open_meteo import (
    MARINE_ENDPOINT,
    WIND_ENDPOINT,
    OpenMeteoProvider,
    WeatherObservation,
    WeatherProvider,
)

__all__ = [
    "MARINE_ENDPOINT",
    "WIND_ENDPOINT",
    "OpenMeteoProvider",
    "WeatherObservation",
    "WeatherProvider",
]
