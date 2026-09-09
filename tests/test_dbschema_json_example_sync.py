"""`DB_SCHEMA.md`의 JSONB 예시 ↔ 실제 기록 형태 (#879).

## 왜 필요한가

`§2.7 voyages_json`과 `§2.5 result_json` 예시가 **실제 저장 컬럼과 키 이름부터
달랐다.** `§2.7`은 저장 형태가 아니라 **API 응답(`§6.3` `/snapshot-voyages`)의
모양**을 적고 있었고(`snapshot_voyage_id`·`status_at_snapshot`·`distance_nm`),
`§2.5`는 `rating`·`co2_ton`처럼 **구현에 없는 이름**을 쓰면서 실제 15키 중 12키를
빠뜨렸다. 코드가 실제로 읽는 `kind`("ACTUAL"/"PLAN")는 문서에 아예 없었다.

**값을 한 번 고치는 것으로는 부족하다.** `§2.5`는 스스로 *「복사해 파서에 그대로
넣을 수 있어야 재현성 테스트와 픽스처가 이 예시를 기준으로 삼을 수 있다」*고
적어 두었는데, 그 약속을 지키는지 아무도 세지 않았다. 그래서 예시가 조용히
흘러갔다 — `#151`이 `API_SPEC §5.1`에서 겪은 것과 같은 경로다.

## 무엇을 대조하는가

**키 집합**이다. 값이 아니다.

- 값 대조는 `test_scenario_example_sync.py`(`API_SPEC §5.1`)가 실제 실행으로 한다.
- 여기서 막으려는 것은 **「예시에 있는 이름이 실물에 없다」**와 그 반대다. 이름이
  어긋나면 예시를 복사해 만든 파서가 조용히 `None`을 읽는다.

DB를 띄우지 않는다 — **기록을 만드는 함수를 직접 불러** 그 결과의 키를 센다.
DB를 거치면 시드 상태에 따라 결과가 달라지고, 이 검사가 보려는 것은 저장소가
아니라 **문서와 코드 사이**다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from cii_platform.services.annual_simulation import _snapshot_row
from cii_platform.services.voyage_cii import (
    FuelUseInput,
    VoyageCiiInput,
    _build_data,
)

_SCHEMA = Path(__file__).resolve().parents[1] / "DB_SCHEMA.md"


def _section(start: str, end: str) -> str:
    text = _SCHEMA.read_text(encoding="utf-8")
    return text.split(start, 1)[1].split(end, 1)[0]


def _first_json_block(section: str) -> object:
    match = re.search(r"```json\n(.*?)\n```", section, re.S)
    assert match is not None, "예시 JSON 블록을 찾지 못했다"
    return json.loads(match.group(1))


# ── §2.7 voyages_json ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FuelUse:
    fuel_type: str
    planned_fuel_ton: Decimal
    actual_fuel_ton: Decimal | None
    cf_used: Decimal


def _actual_row() -> dict:
    """확정 실적 한 건을 **실제 기록 함수**로 만든다."""
    voyage = SimpleNamespace(
        id=UUID("00000000-0000-4000-8000-000000000102"),
        voyage_no="2026-01",
        status="COMPLETED",
        annual_inclusion_policy="INCLUDE_AS_ACTUAL",
        planned_distance_nm=Decimal("4200.00"),
        actual_distance_nm=Decimal("4300.00"),
        planned_speed_kn=Decimal("12.00"),
    )
    fuel = _FuelUse("HFO", Decimal("530.0000"), Decimal("620.0000"), Decimal("3.114000"))
    return _snapshot_row(voyage, "ACTUAL", [fuel], {"HFO": Decimal("3.114000")})


def test_voyages_json_example_has_the_stored_keys() -> None:
    """`§2.7` 예시의 키가 실제 기록 형태와 **정확히** 같다."""
    example = _first_json_block(_section("**`voyages_json` 구조:**", "**인덱스:**"))
    assert isinstance(example, list) and example, "예시는 비어 있지 않은 배열이어야 한다"

    actual = _actual_row()
    for index, item in enumerate(example):
        assert set(item) == set(actual), (
            f"§2.7 예시[{index}]의 키가 저장 형태와 다르다. "
            f"예시에만: {sorted(set(item) - set(actual))} · "
            f"실물에만: {sorted(set(actual) - set(item))}"
        )
        for fuel in item["fuel_uses"]:
            assert set(fuel) == set(actual["fuel_uses"][0]), (
                f"§2.7 예시[{index}] fuel_uses의 키가 저장 형태와 다르다. "
                f"예시에만: {sorted(set(fuel) - set(actual['fuel_uses'][0]))} · "
                f"실물에만: {sorted(set(actual['fuel_uses'][0]) - set(fuel))}"
            )


def test_voyages_json_example_documents_kind() -> None:
    """`kind`가 예시와 필드 표에 모두 있다.

    코드가 실제로 읽는 키인데(완료 항차 수·잔여 항차 수·계획 항차 CF 선택) 종전
    문서에는 **없었다.** 키 집합 대조만으로도 걸리지만, 빠졌을 때 **무엇이 빠졌는지**를
    바로 말하기 위해 따로 둔다.
    """
    section = _section("**`voyages_json` 구조:**", "**인덱스:**")
    example = _first_json_block(section)
    assert all("kind" in item for item in example), "예시의 모든 항목에 kind가 있어야 한다"
    assert "| `kind` |" in section, "필드 표에 kind 행이 있어야 한다"
    assert {item["kind"] for item in example} == {"ACTUAL", "PLAN"}, (
        "예시는 두 갈래를 모두 보여야 한다 — 한쪽만 있으면 계획 항차의 null 필드가 드러나지 않는다"
    )


# ── §2.5 VOYAGE_ESTIMATE result_json ─────────────────────────────────────────


def _voyage_estimate_result() -> dict:
    """`PRD §13.1` Fixture 1 한 건을 **실제 응답 조립 함수**로 만든다."""
    payload = VoyageCiiInput(
        vessel_id=UUID("00000000-0000-4000-8000-000000000001"),
        regulation_year=2026,
        distance_nm=Decimal("1000"),
        speed_kn=Decimal("14"),
        fuel_uses=(FuelUseInput("HFO", Decimal("80.0")),),
    )
    layer1 = SimpleNamespace(
        attained_cii=Decimal("4.9824"),
        required_cii=Decimal("5.045066"),
        ratio_to_required=Decimal("0.98758"),
        rating="C",
        margin=Decimal("0.365370"),
        margin_ratio=Decimal("0.0724"),
        total_co2_t=Decimal("249.12"),
        fuel_total_ton=Decimal("80.00"),
        risk_level="MEDIUM",
    )
    return _build_data(
        vessel=SimpleNamespace(ship_type="BULK_CARRIER"),
        reference_line=SimpleNamespace(capacity_rule="DWT", a_decimal="4745", c="0.622"),
        regulation=SimpleNamespace(z_factor_percent="11.0"),
        transport_capacity=Decimal("50000"),
        reference_capacity=Decimal("50000"),
        payload=payload,
        fuel_rows={"HFO": SimpleNamespace(cf="3.114")},
        layer1=layer1,
    )


def _voyage_estimate_section() -> str:
    return _section(
        "**`calculation_type = VOYAGE_ESTIMATE`**",
        "**`calculation_type = ANNUAL_MONTE_CARLO`**",
    )


def test_voyage_estimate_example_has_the_stored_keys() -> None:
    """`§2.5` VOYAGE_ESTIMATE 예시의 키가 실제 `result_json`과 **정확히** 같다."""
    example = _first_json_block(_voyage_estimate_section())
    actual = _voyage_estimate_result()

    assert set(example) == set(actual), (
        "§2.5 VOYAGE_ESTIMATE 예시의 키가 result_json과 다르다. "
        f"예시에만: {sorted(set(example) - set(actual))} · "
        f"실물에만: {sorted(set(actual) - set(example))}"
    )
    documented = set(example["calculation_basis"])
    recorded = set(actual["calculation_basis"])
    assert documented == recorded, (
        "calculation_basis의 키가 다르다. "
        f"예시에만: {sorted(documented - recorded)} · "
        f"실물에만: {sorted(recorded - documented)}"
    )


def test_voyage_estimate_example_keeps_the_number_string_split() -> None:
    """`distance_nm`만 JSON 숫자이고 나머지 수치는 문자열이다 (`API_SPEC §1.7`).

    한 블록 안에 두 타입이 섞이는 것은 의도다 — 입력 에코와 Layer 1 결과는 다른
    계약을 따른다. 예시를 통째로 문자열로 「정리」하면 그 구분이 사라진다.
    """
    example = _first_json_block(_voyage_estimate_section())
    assert isinstance(example["distance_nm"], (int, float))
    for key in ("attained_cii", "required_cii", "co2_emission_ton", "fuel_consumption_ton"):
        assert isinstance(example[key], str), f"{key}는 문자열이어야 한다"


def test_rating_probabilities_example_is_serialized_as_strings() -> None:
    """`rating_probabilities`는 JSON 숫자가 아니라 문자열이다.

    float로 내면 자릿수가 뭉개져 `"0.0"`·`"1.0"`이 된다 — 실제로 그 회귀가 있었다.
    """
    example = _first_json_block(
        _section(
            "**`calculation_type = ANNUAL_MONTE_CARLO`**",
            "**`model_version` JSONB 구조:**",
        )
    )
    probabilities = example["monte_carlo"]["rating_probabilities"]
    assert set(probabilities) == {"A", "B", "C", "D", "E"}
    for rating, value in probabilities.items():
        assert isinstance(value, str), f"{rating} 확률이 문자열이 아니다: {value!r}"
