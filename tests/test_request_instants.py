"""요청 본문의 시각은 시간대를 요구하고 UTC로 맞춘다 (`API_SPEC §1.11` · `#1627`).

## 이 파일이 보는 것

⑴ **시간대 없는 값은 스키마에서 걸린다** — 라우트·서비스에 닿기 전이다. 닿으면
   서버 세션 시간대로 해석돼 **조용히 다른 순간**이 저장된다.
⑵ **서로 다른 offset이 같은 순간이면 같은 값이 된다** — `input_hash`·로그·비교가
   표기에 흔들리지 않는다.
⑶ **경로마다 규칙이 같다** — 항차 생성·수정·실적, 시나리오 채택, 연간 시뮬레이션.
   `#1333`이 not under way를, `#906`이 CSV를 같은 규칙으로 맞췄고 여기가 나머지다.

DB를 켜지 않고 도는 검사다 — 스키마 경계만 보므로 모델을 직접 만든다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from cii_platform.api.schemas.annual_simulation import AnnualSimulationRequest
from cii_platform.api.schemas.scenario_compare import ScenarioAdoptRequest
from cii_platform.api.schemas.voyage import (
    VoyageActualsRequest,
    VoyageCreateRequest,
    VoyageUpdateRequest,
)

NAIVE = "2026-06-01T09:00:00"
KST = "2026-06-01T09:00:00+09:00"
UTC_SAME = "2026-06-01T00:00:00Z"


def _create(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "voyage_no": "V-2026-001",
        "departure_port_name": "Busan",
        "arrival_port_name": "Rotterdam",
        "planned_distance_nm": "11000",
        "planned_speed_kn": "14",
        "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "800"}],
    }
    base.update(over)
    return base


#: (모델, 필드) — 같은 규칙이 걸려야 하는 자리 전부.
CASES = [
    pytest.param(VoyageCreateRequest, "planned_departure_at", _create, id="생성-출항"),
    pytest.param(VoyageCreateRequest, "planned_arrival_at", _create, id="생성-도착"),
    pytest.param(VoyageUpdateRequest, "planned_departure_at", dict, id="수정-출항"),
    pytest.param(VoyageUpdateRequest, "planned_arrival_at", dict, id="수정-도착"),
    pytest.param(VoyageActualsRequest, "actual_departure_at", dict, id="실적-출항"),
    pytest.param(VoyageActualsRequest, "actual_arrival_at", dict, id="실적-도착"),
    pytest.param(
        ScenarioAdoptRequest,
        "planned_departure_at",
        lambda **o: {"target_voyage_id": "00000000-0000-4000-8000-0000000000a1", **o},
        id="채택-출항",
    ),
    pytest.param(
        AnnualSimulationRequest,
        "as_of",
        lambda **o: {
            "vessel_id": "00000000-0000-4000-8000-0000000000a1",
            "regulation_year": 2026,
            "target_rating": "C",
            **o,
        },
        id="연간-as_of",
    ),
]


@pytest.mark.parametrize(("model", "field", "payload"), CASES)
def test_naive_datetime_is_rejected(model, field, payload) -> None:
    """시간대 없는 시각은 422로 가는 `ValidationError`다 (`API_SPEC §1.11`)."""
    with pytest.raises(ValidationError) as caught:
        model(**payload(**{field: NAIVE}))

    errors = [e for e in caught.value.errors() if e["loc"] == (field,)]
    assert errors, f"{field}에 대한 오류가 아니다: {caught.value.errors()}"
    # 어느 칸이 왜 틀렸는지가 응답에 실린다 — 「시간대가 필요하다」가 그 이유다.
    assert errors[0]["type"] == "timezone_aware"


@pytest.mark.parametrize(("model", "field", "payload"), CASES)
def test_offsets_are_normalised_to_utc(model, field, payload) -> None:
    """같은 순간이면 offset이 달라도 같은 UTC 값이 된다."""
    kst = getattr(model(**payload(**{field: KST})), field)
    utc = getattr(model(**payload(**{field: UTC_SAME})), field)

    assert kst == utc
    assert kst.tzinfo == UTC
    assert kst.utcoffset() == timedelta(0)


def test_aware_value_keeps_the_instant() -> None:
    """표기만 옮긴다 — 순간을 바꾸지 않는다."""
    request = VoyageCreateRequest(**_create(planned_departure_at=KST))

    assert request.planned_departure_at == datetime(
        2026, 6, 1, 9, 0, tzinfo=timezone(timedelta(hours=9))
    )
    assert request.planned_departure_at.isoformat() == "2026-06-01T00:00:00+00:00"


def test_none_is_still_allowed() -> None:
    """빈 값은 그대로 빈 값이다 — 시간대 규칙이 선택 필드를 필수로 만들지 않는다."""
    request = VoyageCreateRequest(**_create())

    assert request.planned_departure_at is None
    assert request.planned_arrival_at is None
