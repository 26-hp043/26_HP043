"""달력 끝의 시각은 UTC로 옮길 수 없으면 검증 오류다 — DB 없이 보는 쪽 (`#2474`).

``0001-01-01T00:00:00+09:00``은 UTC로 0년, ``9999-12-31T23:59:59-05:00``은 10000년이라
``astimezone(UTC)``가 ``OverflowError``를 낸다. Pydantic은 이 예외를 검증 오류로 바꾸지
않고 그대로 올려 **500**이 됐고, CSV 들여오기는 파일 전체가 실패했다.

여기서는 입구 셋을 본다 — 요청 스키마(422가 될 ``ValidationError``) · 두 CSV 파서(행
오류) · 쿼리 ``as_of``를 확정하는 ``resolve_as_of``(도메인 ``ValidationError``). 실제 HTTP
응답은 ``test_calendar_edge_instants_api_db.py``가 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from cii_platform.api.schemas.annual_simulation import AnnualSimulationRequest
from cii_platform.api.schemas.not_underway import (
    NotUnderwayPeriodCreateRequest,
    NotUnderwayPeriodUpdateRequest,
)
from cii_platform.api.schemas.voyage import VoyageCreateRequest
from cii_platform.errors import ValidationError
from cii_platform.services import not_underway_import, voyage_import
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.validation.instants import OUT_OF_RANGE_MESSAGE, to_utc
from cii_platform.validation.messages import korean_message

#: UTC로 옮기면 달력 범위를 넘는 두 값 — 이슈가 실행으로 확인한 그대로다.
EDGES = [
    pytest.param("0001-01-01T00:00:00+09:00", id="0001년+09:00"),
    pytest.param("9999-12-31T23:59:59-05:00", id="9999년-05:00"),
]

#: 같은 달력 끝이라도 UTC로 와서 옮길 것이 없으면 그대로 받는다 — 대조군.
EDGES_IN_UTC = ["0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z"]


@pytest.mark.parametrize("raw", EDGES)
def test_to_utc_turns_overflow_into_a_korean_value_error(raw: str) -> None:
    with pytest.raises(ValueError, match="범위를 벗어나는 시각") as caught:
        to_utc(datetime.fromisoformat(raw))
    # 원인은 남긴다 — 로그에서 「무엇이 넘쳤나」를 볼 수 있게.
    assert isinstance(caught.value.__cause__, OverflowError)


@pytest.mark.parametrize("raw", EDGES_IN_UTC)
def test_calendar_edges_already_in_utc_pass(raw: str) -> None:
    moment = datetime.fromisoformat(raw)
    assert to_utc(moment) == moment


def _voyage(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "voyage_no": "V-EDGE",
        "departure_port_name": "Busan",
        "arrival_port_name": "Rotterdam",
        "planned_distance_nm": "11000",
        "planned_speed_kn": "14",
        "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "800"}],
    }
    base.update(over)
    return base


SCHEMA_CASES = [
    pytest.param(VoyageCreateRequest, "planned_departure_at", _voyage, id="항차-Instant"),
    pytest.param(
        AnnualSimulationRequest,
        "as_of",
        lambda **o: {
            "vessel_id": "00000000-0000-4000-8000-0000000000a1",
            "regulation_year": 2026,
            "target_rating": "C",
            **o,
        },
        id="연간-Instant",
    ),
    pytest.param(
        NotUnderwayPeriodCreateRequest,
        "started_at",
        lambda **o: {"period_type": "AT_ANCHOR", "started_at": "2026-08-10T00:00:00Z", **o},
        id="정박-생성",
    ),
    pytest.param(NotUnderwayPeriodUpdateRequest, "ended_at", dict, id="정박-수정"),
]


@pytest.mark.parametrize("raw", EDGES)
@pytest.mark.parametrize(("model", "field", "payload"), SCHEMA_CASES)
def test_schema_rejects_with_a_validation_error_not_overflow(model, field, payload, raw) -> None:
    """🔴 종전에는 ``OverflowError``가 그대로 올라왔다 — 오류 처리기가 500으로 바꿨다."""
    with pytest.raises(PydanticValidationError) as caught:
        model(**payload(**{field: raw}))

    errors = [e for e in caught.value.errors() if e["loc"] == (field,)]
    assert errors, caught.value.errors()
    assert errors[0]["type"] == "value_error"
    # 422 응답의 필드 문구 — 직접 만든 검증기의 한국어 문구가 그대로 나간다.
    assert korean_message(errors[0], "출항 예정 시각") == OUT_OF_RANGE_MESSAGE


def test_not_underway_keeps_the_offset_it_was_given() -> None:
    """정박 구간은 표기를 UTC로 바꾸지 않는다 — 범위 검사만 더했다(응답·해시 불변)."""
    request = NotUnderwayPeriodCreateRequest(
        period_type="AT_ANCHOR", started_at="2026-08-10T09:00:00+09:00"
    )
    assert request.started_at.utcoffset() is not None
    assert request.started_at.isoformat() == "2026-08-10T09:00:00+09:00"


def _voyage_row(**over: str) -> dict[str, str]:
    row = {
        "voyage_no": "V-EDGE",
        "departure_port_name": "Busan",
        "arrival_port_name": "Rotterdam",
        "planned_distance_nm": "11000",
        "planned_speed_kn": "14",
        "fuel_type": "HFO",
        "planned_fuel_ton": "800",
    }
    row.update(over)
    return row


@pytest.mark.parametrize("raw", EDGES)
@pytest.mark.parametrize("column", ["planned_departure_at", "planned_arrival_at"])
def test_voyage_csv_turns_it_into_a_row_error(column: str, raw: str) -> None:
    """🔴 종전에는 ``OverflowError``가 ``RowError``로 바뀌지 않아 파일 전체가 실패했다."""
    with pytest.raises(voyage_import.RowError) as caught:
        voyage_import.parse_row(_voyage_row(**{column: raw}), {"HFO"})
    assert caught.value.field == column
    assert caught.value.message == OUT_OF_RANGE_MESSAGE


def _period_row(**over: str) -> dict[str, str]:
    row = {
        "period_type": "AT_ANCHOR",
        "started_at": "2026-08-10T00:00:00Z",
        "ended_at": "",
        "fuel_type": "HFO",
        "distance_nm": "0",
    }
    row.update(over)
    return row


@pytest.mark.parametrize("raw", EDGES)
@pytest.mark.parametrize("column", ["started_at", "ended_at"])
def test_not_underway_csv_turns_it_into_a_row_error(column: str, raw: str) -> None:
    """🔴 종전에는 시작 시각이 ``utc_year``에서 ``OverflowError``로 터졌다."""
    with pytest.raises(not_underway_import.RowError) as caught:
        not_underway_import.parse_row(_period_row(**{column: raw}), {"HFO"})
    assert caught.value.field == column
    assert caught.value.message == OUT_OF_RANGE_MESSAGE


@pytest.mark.parametrize("raw", EDGES)
def test_resolve_as_of_raises_a_domain_validation_error(raw: str) -> None:
    """쿼리 ``as_of``는 ``Instant``를 지나지 않는다 — 확정하는 자리가 422로 돌린다."""
    with pytest.raises(ValidationError) as caught:
        resolve_as_of(datetime.fromisoformat(raw))
    assert caught.value.field == "as_of"
    assert caught.value.message == OUT_OF_RANGE_MESSAGE


def test_resolve_as_of_still_normalises_ordinary_values() -> None:
    """대조군 — 평범한 값은 종전대로 UTC로 맞춘다."""
    moment = datetime.fromisoformat("2026-06-01T09:00:00+09:00")
    assert resolve_as_of(moment) == datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
