"""규제값 적재의 ``condition_expr`` 검증 (#2087 · API_SPEC §7.5) — **DB 없이 돈다**.

적재가 조건식을 빈 값·길이로만 보아, 엔진이 못 읽는 식이 활성 행으로 들어가면 그 선종의
CII 계산이 전부 409가 됐다. 잠그는 것은 셋이다.

1. **문법은 엔진과 같은 함수로 판정한다** — ``parse_condition``이 읽는 식만 통과한다
2. **적재 뒤의 선종별 활성 행이 전 구간을 빈틈·겹침 없이 덮는다** — ``dry_run``도 같다
3. ``a_raw`` 변환값의 소수 자릿수

DB에 닿는 쪽(실제 적재가 아무것도 바꾸지 않는다)은 ``test_parameter_import_db.py``가 본다.
"""

from __future__ import annotations

import pytest

from cii_platform.calc.capacity import ConditionInterval, parse_condition
from cii_platform.db.seed import SEED_RATING_BOUNDARIES, SEED_REFERENCE_LINES
from cii_platform.services import parameter_import
from cii_platform.services.parameter_import import (
    _parse_rating_boundary,
    _parse_reference_line,
    import_parameters,
    partition_problem,
)
from cii_platform.services.voyage_import import RowError

_REF_HEADER = "ship_type,condition_expr,capacity_rule,a_raw,c,source_ref"


def _ref_row(**overrides: str) -> dict[str, str]:
    row = {
        "ship_type": "BULK_CARRIER",
        "condition_expr": "DWT >= 279000",
        "capacity_rule": "fixed 279000",
        "a_raw": "4745",
        "c": "0.622",
        "source_ref": "TEST",
    }
    return {**row, **overrides}


# ── ⑴ 문법 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("condition_expr", "expected"),
    [
        ("all", ConditionInterval(None, 0, None)),
        ("DWT >= 279000", ConditionInterval("DWT", 279000, None)),
        ("GT < 30000", ConditionInterval("GT", 0, 30000)),
        ("65000 <= DWT < 100000", ConditionInterval("DWT", 65000, 100000)),
    ],
)
def test_parse_condition_reads_the_three_shapes(condition_expr, expected):
    assert parse_condition(condition_expr) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "DWT ≥ 279000",  # 이슈의 완료 기준 — 부등호가 한 글자다
        "DWT >= 279,000",
        "DWT > 279000",
        "dwt >= 279000",
        "__test__",
        "ALL",
    ],
)
def test_a_condition_the_engine_cannot_read_is_a_row_error(bad):
    for parse, row in (
        (_parse_reference_line, _ref_row(condition_expr=bad)),
        (
            _parse_rating_boundary,
            {
                "ship_type": "BULK_CARRIER",
                "condition_expr": bad,
                "capacity_basis": "DWT",
                "d1": "0.86",
                "d2": "0.94",
                "d3": "1.06",
                "d4": "1.18",
                "source_ref": "TEST",
            },
        ),
    ):
        with pytest.raises(RowError) as raised:
            parse(row)
        assert raised.value.field == "condition_expr"
        # 엔진도 같은 식을 못 읽는다 — 두 판정이 갈리면 이 검사가 의미를 잃는다.
        with pytest.raises(ValueError, match="Unsupported condition_expr"):
            parse_condition(bad)


def test_an_empty_range_is_a_row_error():
    with pytest.raises(RowError) as raised:
        _parse_reference_line(_ref_row(condition_expr="100000 <= DWT < 65000"))
    assert raised.value.field == "condition_expr"


def test_a_valid_condition_is_kept_as_written():
    item = _parse_reference_line(_ref_row())
    assert item["condition_expr"] == "DWT >= 279000"
    assert item["key"] == ("BULK_CARRIER", "DWT >= 279000")


# ── ⑵ 구간 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rows", [SEED_REFERENCE_LINES, SEED_RATING_BOUNDARIES])
def test_every_seed_ship_type_is_a_clean_partition(rows):
    """시드가 통과하지 못하면 판정이 틀린 것이다 — 시드는 엔진 검사가 이미 잠근다."""
    for ship_type in {row.ship_type for row in rows}:
        conditions = [row.condition_expr for row in rows if row.ship_type == ship_type]
        assert partition_problem(conditions) is None, ship_type


@pytest.mark.parametrize(
    ("conditions", "needle"),
    [
        (["DWT >= 279000"], "279000 미만"),
        (["DWT < 279000"], "279000 이상"),
        (["DWT < 65000", "DWT >= 100000"], "65000 이상 100000 미만"),
        (["DWT < 279000", "DWT >= 279000", "DWT >= 300000"], "겹칩니다"),
        (["DWT < 100000", "65000 <= DWT < 100000", "DWT >= 100000"], "겹칩니다"),
        (["all", "DWT >= 279000"], "'all'"),
        (["DWT < 30000", "GT >= 30000"], "서로 다른 축"),
        (["DWT < 279000", "DWT ≥ 279000"], "읽을 수 없는"),
        ([], "활성 행이 없습니다"),
    ],
)
def test_partition_problem_names_the_gap_or_overlap(conditions, needle):
    problem = partition_problem(conditions)
    assert problem is not None
    assert needle in problem


def test_partition_ignores_the_order_rows_arrive_in():
    assert partition_problem(["DWT >= 100000", "DWT < 65000", "65000 <= DWT < 100000"]) is None


# ── ⑵-b 적재 경로에서 — dry_run이 실제 적재와 같은 판정을 낸다 ─────────────────


def _csv(*rows: str) -> bytes:
    return ("\r\n".join([_REF_HEADER, *rows]) + "\r\n").encode("utf-8")


async def _never_listed(_session, _ship_type):
    raise AssertionError("구간 판정이 기존 활성 행을 읽었다 — 파일에 든 선종은 파일만 본다")


async def _dry_run(monkeypatch, *rows: str) -> dict[str, object]:
    """선종 단위 대체(#2172) — 판정은 **파일의 행만** 본다. 기존 활성 행을 읽으면 실패한다."""
    monkeypatch.setitem(parameter_import._PARTITIONED, "reference_lines", _never_listed)
    # 세션은 쓰이지 않는다 — dry_run은 DB를 읽지도 쓰지도 않는다.
    return await import_parameters(None, kind="reference_lines", content=_csv(*rows), dry_run=True)


async def test_replacing_both_bands_with_the_same_keys_keeps_the_partition(monkeypatch):
    data = await _dry_run(
        monkeypatch,
        "BULK_CARRIER,DWT >= 279000,fixed 279000,4800,0.622,TEST",
        "BULK_CARRIER,DWT < 279000,DWT,4745,0.622,TEST",
    )
    assert data["errors"] == []
    assert data["imported_count"] == 2


async def test_moving_a_boundary_is_accepted_when_the_file_covers_every_band(monkeypatch):
    """경계값 개정(#2172) — 옛 밴드는 선종 단위로 꺼지므로 겹치지 않는다.

    종전(#2087)에는 키가 다른 옛 행이 활성으로 남는다고 보아 같은 파일을 거부했다.
    """
    data = await _dry_run(
        monkeypatch,
        "BULK_CARRIER,DWT >= 300000,fixed 300000,4745,0.622,TEST",
        "BULK_CARRIER,DWT < 300000,DWT,4745,0.622,TEST",
    )
    assert data["errors"] == []
    assert data["imported_count"] == 2


async def test_splitting_all_into_two_bands_is_accepted(monkeypatch):
    """⑴ 'all' 한 행 → 두 밴드. 종전에는 기존 'all'과 합쳐져 거부됐다."""
    data = await _dry_run(
        monkeypatch,
        "TANKER,DWT >= 100000,DWT,5247,0.610,TEST",
        "TANKER,DWT < 100000,DWT,5247,0.610,TEST",
    )
    assert data["errors"] == []
    assert data["imported_count"] == 2


async def test_merging_two_bands_into_all_is_accepted(monkeypatch):
    """⑵ 두 밴드 → 'all' 한 행. 종전에는 기존 두 밴드와 겹쳐 거부됐다."""
    data = await _dry_run(monkeypatch, "BULK_CARRIER,all,DWT,4745,0.622,TEST")
    assert data["errors"] == []
    assert data["imported_count"] == 1


async def test_a_file_with_only_one_band_of_a_ship_type_is_rejected(monkeypatch):
    """파일에 든 선종은 그 선종의 **모든 구간**을 담아야 한다 — 한 밴드만 올리면 빈틈이다."""
    data = await _dry_run(
        monkeypatch,
        "BULK_CARRIER,DWT >= 279000,fixed 279000,4800,0.622,TEST",
    )
    assert data["imported_count"] == 0
    assert [(error["row"], error["field"]) for error in data["errors"]] == [(2, "condition_expr")]
    assert "BULK_CARRIER" in data["errors"][0]["message"]
    assert "279000 미만을 덮는 행이 없습니다" in data["errors"][0]["message"]


async def test_overlapping_bands_inside_the_file_are_rejected(monkeypatch):
    data = await _dry_run(
        monkeypatch,
        "BULK_CARRIER,all,DWT,4745,0.622,TEST",
        "BULK_CARRIER,DWT >= 279000,fixed 279000,4745,0.622,TEST",
    )
    assert data["imported_count"] == 0
    assert "겹칩니다" in data["errors"][0]["message"]


async def test_a_file_that_leaves_a_gap_is_rejected_on_its_first_row(monkeypatch):
    data = await _dry_run(
        monkeypatch,
        "GAS_CARRIER,DWT < 65000,DWT,8104,0.639,TEST",
        "GAS_CARRIER,DWT >= 100000,DWT,14405E7,2.071,TEST",
    )
    assert [(error["row"], error["field"]) for error in data["errors"]] == [(2, "condition_expr")]
    assert "65000 이상 100000 미만" in data["errors"][0]["message"]


async def test_a_row_error_is_reported_without_a_partition_error_on_top(monkeypatch):
    """행이 빠진 채로 구간을 보면, 고치면 사라질 「빈틈」을 함께 보고하게 된다."""
    data = await _dry_run(
        monkeypatch,
        "GAS_CARRIER,DWT < 65000,DWT,8104,0.639,TEST",
        "GAS_CARRIER,DWT ≥ 65000,DWT,14405E7,2.071,TEST",
    )
    assert [(error["row"], error["field"]) for error in data["errors"]] == [(3, "condition_expr")]


# ── ⑶ a_raw 변환값의 소수 자릿수 ─────────────────────────────────────────────


def test_a_decimal_beyond_six_places_is_a_row_error():
    with pytest.raises(RowError) as raised:
        _parse_reference_line(_ref_row(a_raw="1.2345678"))
    assert raised.value.field == "a_raw"


def test_a_decimal_within_six_places_passes():
    assert str(_parse_reference_line(_ref_row(a_raw="9.827"))["a_decimal"]) == "9.827"
