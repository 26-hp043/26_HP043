"""CSV Fixture 4 검증 (#48).

TEST_PLAN §1.5 · §3.4 (IT-CSV-001, 005~007). ``voyage_import_sample.csv``가 필수
컬럼 7종(API_SPEC §8.2)을 포함하고 formula injection 4종(``=``·``@``·``+``·``-`` prefix)을
담고 있는지 확인한다. **CSV 파싕·escape 동작 자체는 #60(CSV 가져오기) 소관이다.**
"""

import csv
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "csv" / "voyage_import_sample.csv"

#: API_SPEC §8.2가 요구하는 필수 컬럼 7종.
REQUIRED_COLUMNS: set[str] = {
    "voyage_no",
    "departure_port_name",
    "arrival_port_name",
    "planned_distance_nm",
    "planned_speed_kn",
    "fuel_type",
    "planned_fuel_ton",
}

#: 이슈 #48 · TEST_PLAN §3.4 IT-CSV-001, 005~007이 요구하는 formula injection prefix.
INJECTION_PREFIXES: tuple[str, ...] = ("=", "@", "+", "-")


def _read_rows() -> list[dict[str, str]]:
    with FIXTURE.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_fixture_has_all_required_columns() -> None:
    """필수 컬럼 7종이 헤더에 모두 있다 (API_SPEC §8.2, #48)."""
    with FIXTURE.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert REQUIRED_COLUMNS.issubset(set(reader.fieldnames or []))


def test_fixture_contains_five_normal_rows() -> None:
    """이슈 #48 완료 기준 — 정상 항차 데이터 5행."""
    rows = _read_rows()
    normal = [r for r in rows if not r["voyage_no"].startswith(INJECTION_PREFIXES)]
    assert len(normal) == 5


def test_fixture_contains_four_formula_injection_vectors() -> None:
    """formula injection 4종 prefix (=, @, +, -) — IT-CSV-001/005/006/007 (#48)."""
    rows = _read_rows()
    injections = [r["voyage_no"] for r in rows if r["voyage_no"].startswith(INJECTION_PREFIXES)]
    found_prefixes = {cell[0] for cell in injections}
    assert found_prefixes == set(INJECTION_PREFIXES)
    assert len(injections) == 4
