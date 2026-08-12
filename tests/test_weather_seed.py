"""Townsin-Kwon weather_model_parameter seed 상수 검증 (#35).

DB가 없어도 검증 가능한 부분 — 019 마이그레이션의 ``SEED_WEATHER_PARAMS`` 상수가
TECH_SPEC §3.3 표와 일치하는지 잠근다. 실 INSERT·회귀는 DB 의존 테스트
(``test_seed_data.py``)가 다룬다.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

#: 019 마이그레이션 파일 경로 — ``alembic.versions`` 패키지가 pytest path에 없으므로
#: 파일에서 직접 로드한다.
MIGRATION_PATH = (
    Path(__file__).parent.parent / "alembic" / "versions" / "019_seed_weather_model_parameter.py"
)

#: TECH_SPEC §3.3 — Kwon (2008) 단순화 기반 선종별 CU 계수.
#: ``CU = a × BN + b`` 선형 형태로 일반화. (a, b) 튜플.
EXPECTED_CU_COEFFICIENTS: dict[str, tuple[Decimal, Decimal]] = {
    "BULK_CARRIER": (Decimal("0.5"), Decimal("0.5")),
    "TANKER": (Decimal("0.7"), Decimal("0")),
    "CONTAINER_SHIP": (Decimal("0.6"), Decimal("0.2")),
    "GENERAL_CARGO_SHIP": (Decimal("0.5"), Decimal("0.5")),
    "LNG_CARRIER": (Decimal("0.7"), Decimal("0")),
}

_SHIP_TYPES = set(EXPECTED_CU_COEFFICIENTS)


@pytest.fixture(scope="module")
def seed_rows() -> list[dict[str, object]]:
    """019 마이그레이션 파일에서 SEED_WEATHER_PARAMS를 가져온다."""
    spec = importlib.util.spec_from_file_location("seed_019", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.SEED_WEATHER_PARAMS)


def test_seed_covers_five_ship_types_with_a_b_pairs(seed_rows: list[dict[str, object]]) -> None:
    """5개 선종이 cu_a·cu_b 쌍으로 들어있다 (총 10행, #35 완료 기준)."""
    assert len(seed_rows) == 10
    a_keys = {r["key"] for r in seed_rows if str(r["key"]).startswith("cu_a.")}
    b_keys = {r["key"] for r in seed_rows if str(r["key"]).startswith("cu_b.")}
    assert a_keys == {f"cu_a.{s}" for s in _SHIP_TYPES}
    assert b_keys == {f"cu_b.{s}" for s in _SHIP_TYPES}


@pytest.mark.parametrize("ship_type,expected", list(EXPECTED_CU_COEFFICIENTS.items()))
def test_cu_coefficients_match_tech_spec_3_3(
    ship_type: str, expected: tuple[Decimal, Decimal], seed_rows: list[dict[str, object]]
) -> None:
    """TECH_SPEC §3.3 선종별 CU 계수 (a, b)가 seed에 정확히 들어있다 (#35)."""
    a_row = next(r for r in seed_rows if r["key"] == f"cu_a.{ship_type}")
    b_row = next(r for r in seed_rows if r["key"] == f"cu_b.{ship_type}")
    assert Decimal(str(a_row["value"])) == expected[0]
    assert Decimal(str(b_row["value"])) == expected[1]


def test_all_rows_use_townsinkwon_alpha_model_version(seed_rows: list[dict[str, object]]) -> None:
    """모든 행의 model_version이 TOWNSIN_KWON_ALPHA다 (DB_SCHEMA §2.12)."""
    assert all(r["model_version"] == "TOWNSIN_KWON_ALPHA" for r in seed_rows)


def test_source_ref_points_to_tech_spec_3_3(seed_rows: list[dict[str, object]]) -> None:
    """source_ref가 값이 인쇄된 문서(TECH_SPEC §3.3)를 가리킨다 (DB_SCHEMA §2.12)."""
    for row in seed_rows:
        ref = str(row["source_ref"])
        has_section = "TECH_SPEC" in ref and "3.3" in ref
        assert has_section, f"source_ref가 TECH_SPEC §3.3을 안 가리킴: {ref}"


def test_keys_are_unique_per_model_version(seed_rows: list[dict[str, object]]) -> None:
    """(model_version, key) UNIQUE 제약(§2.12 [S-5]) — 중복 key가 없어야 한다."""
    keys = [(r["model_version"], r["key"]) for r in seed_rows]
    assert len(keys) == len(set(keys))
