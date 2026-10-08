"""항차 CSV 묶음·재업로드 규칙을 서비스의 생성 요청과 행 결과로 확인한다 (#2094)."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cii_platform.services import voyage_import as importer

BASE = {
    "voyage_no": "V001",
    "departure_port_name": "Busan",
    "arrival_port_name": "Tokyo",
    "planned_distance_nm": "1000",
    "planned_speed_kn": "13.5",
    "fuel_type": "HFO",
    "planned_fuel_ton": "80",
    "planned_departure_at": "2026-09-12T00:00:00Z",
    "planned_arrival_at": "2026-09-16T00:00:00Z",
}


def row(**changes):
    return {**BASE, **changes}


def content(*rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(BASE))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


@pytest.fixture
def environment(monkeypatch):
    stored = {}

    async def existing(_session, vessel_id, numbers):
        return set(numbers) & set(stored.get(vessel_id, {}))

    async def create(_session, vessel_id, **payload):
        stored.setdefault(vessel_id, {})[payload["voyage_no"]] = payload

    creator = AsyncMock(side_effect=create)
    lock = AsyncMock(return_value=True)
    monkeypatch.setattr(importer, "require_vessel", AsyncMock())
    monkeypatch.setattr(
        importer.param_repo,
        "list_active_fuel_types",
        AsyncMock(return_value=[SimpleNamespace(code="HFO"), SimpleNamespace(code="LNG")]),
    )
    monkeypatch.setattr(
        importer.voyage_repo, "list_existing_numbers", AsyncMock(side_effect=existing)
    )
    monkeypatch.setattr(importer.vessel_repo, "lock_row", lock)
    monkeypatch.setattr(importer, "create_voyage", creator)
    return SimpleNamespace(stored=stored, creator=creator, lock=lock, vessel_id=uuid4())


async def test_mixed_fuels_create_one_voyage_but_count_source_rows(environment):
    result = await importer.import_voyages(
        None,
        environment.vessel_id,
        content=content(row(), row(fuel_type="LNG", planned_fuel_ton="20")),
    )
    assert result["imported_count"] == 2
    assert result["skipped_count"] == 0
    assert result["errors"] == []
    environment.creator.assert_awaited_once()
    payload = environment.creator.await_args.kwargs
    assert payload["planned_distance_nm"] == Decimal("1000")
    assert payload["fuel_uses"] == [
        {"fuel_type": "HFO", "planned_fuel_ton": Decimal("80"), "source": "IMPORT"},
        {"fuel_type": "LNG", "planned_fuel_ton": Decimal("20"), "source": "IMPORT"},
    ]


async def test_reupload_is_rejected_in_dry_run_and_real_import(environment):
    file = content(row(), row(fuel_type="LNG"))
    await importer.import_voyages(None, environment.vessel_id, content=file)
    dry = await importer.import_voyages(None, environment.vessel_id, content=file, dry_run=True)
    real = await importer.import_voyages(None, environment.vessel_id, content=file)
    assert dry["imported_count"] == real["imported_count"] == 0
    assert dry["skipped_count"] == real["skipped_count"] == 2
    assert (
        dry["errors"]
        == real["errors"]
        == [
            {"row": n, "field": "voyage_no", "message": "이미 있는 항차 번호입니다."}
            for n in (2, 3)
        ]
    )  # 정본 문구 (API_SPEC §8.2).
    environment.creator.assert_awaited_once()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("departure_port_name", "Ulsan"),
        ("arrival_port_name", "Osaka"),
        ("planned_distance_nm", "1100"),
        ("planned_speed_kn", "14"),
        ("planned_departure_at", "2026-09-13T00:00:00Z"),
        ("planned_arrival_at", "2026-09-17T00:00:00Z"),
    ],
)
async def test_common_field_mismatch_rejects_the_whole_group(environment, field, value):
    file = content(row(), row(fuel_type="LNG", **{field: value}), row(voyage_no="V002"))
    dry = await importer.import_voyages(None, environment.vessel_id, content=file, dry_run=True)
    real = await importer.import_voyages(None, environment.vessel_id, content=file)
    assert dry["errors"] == real["errors"]
    assert real["imported_count"] == 1
    assert real["skipped_count"] == 2
    assert [error["row"] for error in real["errors"]] == [2, 3]
    assert {error["field"] for error in real["errors"]} == {field}
    assert list(environment.stored[environment.vessel_id]) == ["V002"]


async def test_a_bad_fuel_row_does_not_leave_a_partial_mixed_fuel_voyage(environment):
    result = await importer.import_voyages(
        None,
        environment.vessel_id,
        content=content(row(), row(voyage_no="V002"), row(fuel_type="PLUTONIUM")),
    )
    assert result["imported_count"] == 1
    assert result["skipped_count"] == 2
    assert [error["row"] for error in result["errors"]] == [2, 4]
    assert result["errors"][1]["field"] == "fuel_type"
    assert list(environment.stored[environment.vessel_id]) == ["V002"]


async def test_duplicate_fuel_codes_are_rejected_in_both_modes(environment):
    file = content(row(), row(planned_fuel_ton="20"))
    dry = await importer.import_voyages(None, environment.vessel_id, content=file, dry_run=True)
    real = await importer.import_voyages(None, environment.vessel_id, content=file)
    assert dry["errors"] == real["errors"]
    assert real["imported_count"] == 0
    assert real["skipped_count"] == 2
    environment.creator.assert_not_awaited()


async def test_normalized_numbers_decimals_and_instants_share_one_group(environment):
    file = content(
        row(voyage_no=" V001 "),
        row(
            fuel_type="LNG",
            planned_distance_nm="1000.00",
            planned_speed_kn="13.50",
            planned_departure_at="2026-09-12T09:00:00+09:00",
            planned_arrival_at="2026-09-16T09:00:00+09:00",
        ),
    )
    result = await importer.import_voyages(None, environment.vessel_id, content=file)
    assert result["imported_count"] == 2
    assert result["errors"] == []
    environment.creator.assert_awaited_once()


async def test_missing_departures_and_success_counts_remain_source_row_counts(environment):
    file = content(row(planned_departure_at=""), row(fuel_type="LNG", planned_departure_at=""))
    dry = await importer.import_voyages(None, environment.vessel_id, content=file, dry_run=True)
    real = await importer.import_voyages(None, environment.vessel_id, content=file)
    assert dry["missing_departure_count"] == real["missing_departure_count"] == 2
    assert real["imported_count"] == 2
    environment.creator.assert_awaited_once()


async def test_the_same_number_on_another_vessel_is_independent(environment):
    file = content(row())
    first = await importer.import_voyages(None, environment.vessel_id, content=file)
    second = await importer.import_voyages(None, uuid4(), content=file)
    assert first["imported_count"] == second["imported_count"] == 1
    assert environment.creator.await_count == 2


async def test_a_group_split_by_the_row_limit_is_rejected_as_a_whole(environment, monkeypatch):
    monkeypatch.setattr(importer, "MAX_ROWS", 2)
    file = content(row(), row(voyage_no="V002"), row(fuel_type="LNG"))
    result = await importer.import_voyages(None, environment.vessel_id, content=file)
    assert result["imported_count"] == 1
    assert result["skipped_count"] == 2
    assert result["imported_count"] + result["skipped_count"] == 3
    assert list(environment.stored[environment.vessel_id]) == ["V002"]
    assert {error["row"] for error in result["errors"]} == {2, 4}


async def test_existing_numbers_are_rechecked_after_the_parent_lock(environment):
    async def locked(_session, vessel_id):
        environment.stored.setdefault(vessel_id, {})["V001"] = {}
        return True

    environment.lock.side_effect = locked
    result = await importer.import_voyages(None, environment.vessel_id, content=content(row()))
    assert result["imported_count"] == 0
    assert result["errors"][0]["field"] == "voyage_no"
    environment.lock.assert_awaited_once()
    environment.creator.assert_not_awaited()


async def test_empty_numbers_are_not_merged_into_one_voyage(environment):
    result = await importer.import_voyages(
        None, environment.vessel_id, content=content(row(voyage_no=""), row(voyage_no=""))
    )
    assert result["imported_count"] == 0
    assert result["skipped_count"] == 2
    assert [error["row"] for error in result["errors"]] == [2, 3]
    environment.creator.assert_not_awaited()
