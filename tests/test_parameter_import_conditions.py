"""규제값 적재의 ``condition_expr`` 검증 (#2087 · API_SPEC §7.5) — **DB 없이 돈다**.

적재가 조건식을 빈 값·길이로만 보아, 엔진이 못 읽는 식이 활성 행으로 들어가면 그 선종의
CII 계산이 전부 409가 됐다. 잠그는 것은 셋이다.

1. **문법은 엔진과 같은 함수로 판정한다** — ``parse_condition``이 읽는 식만 통과한다
2. **적재 뒤의 선종별 활성 행이 전 구간을 빈틈·겹침 없이 덮는다** — ``dry_run``도 같다
3. ``a_raw`` 변환값의 소수 자릿수

DB에 닿는 쪽(실제 적재가 아무것도 바꾸지 않는다)은 ``test_parameter_import_db.py``가 본다.
"""

from __future__ import annotations

from types import SimpleNamespace

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


def _existing(*conditions: str):
    async def listed(_session, _ship_type):
        return [SimpleNamespace(condition_expr=condition) for condition in conditions]

    return listed


def _csv(*rows: str) -> bytes:
    return ("\r\n".join([_REF_HEADER, *rows]) + "\r\n").encode("utf-8")


async def _dry_run(monkeypatch, existing, *rows: str) -> dict[str, object]:
    monkeypatch.setitem(parameter_import._PARTITIONED, "reference_lines", _existing(*existing))
    # 세션은 쓰이지 않는다 — dry_run은 조회 함수(위 대역)만 부르고 아무것도 쓰지 않는다.
    return await import_parameters(None, kind="reference_lines", content=_csv(*rows), dry_run=True)


async def test_replacing_a_row_with_the_same_key_keeps_the_partition(monkeypatch):
    data = await _dry_run(
        monkeypatch,
        ["DWT >= 279000", "DWT < 279000"],
        "BULK_CARRIER,DWT >= 279000,fixed 279000,4800,0.622,TEST",
    )
    assert data["errors"] == []
    assert data["imported_count"] == 1


async def test_moving_a_boundary_leaves_the_old_row_active_and_is_rejected(monkeypatch):
    """키가 다른 옛 행은 꺼지지 않는다 — 그대로 넣으면 구간이 겹쳐 계산이 409가 된다."""
    data = await _dry_run(
        monkeypatch,
        ["DWT >= 279000", "DWT < 279000"],
        "BULK_CARRIER,DWT >= 300000,fixed 300000,4745,0.622,TEST",
    )
    assert data["imported_count"] == 0
    assert [(error["row"], error["field"]) for error in data["errors"]] == [(2, "condition_expr")]
    assert "BULK_CARRIER" in data["errors"][0]["message"]
    assert "겹칩니다" in data["errors"][0]["message"]


async def test_a_file_that_leaves_a_gap_is_rejected_on_its_first_row(monkeypatch):
    data = await _dry_run(
        monkeypatch,
        [],
        "GAS_CARRIER,DWT < 65000,DWT,8104,0.639,TEST",
        "GAS_CARRIER,DWT >= 100000,DWT,14405E7,2.071,TEST",
    )
    assert [(error["row"], error["field"]) for error in data["errors"]] == [(2, "condition_expr")]
    assert "65000 이상 100000 미만" in data["errors"][0]["message"]


async def test_a_row_error_is_reported_without_a_partition_error_on_top(monkeypatch):
    """행이 빠진 채로 구간을 보면, 고치면 사라질 「빈틈」을 함께 보고하게 된다."""
    data = await _dry_run(
        monkeypatch,
        [],
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
