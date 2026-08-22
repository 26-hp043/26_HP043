"""자료 내보내기 (API_SPEC §8.1, #59).

**가져오기(`§8.2`)의 반대 방향이 열린다.** `PRD §5.1`의 「연도별 항차 이력 축적
(CSV 가져오기·**내보내기**)」 MUST 중 남아 있던 절반이다.

여기서 잠그는 것은 넷이다.

1. **내보낸 파일을 그대로 다시 가져올 수 있다** — 앞 일곱 열이 `§8.2` 필수 컬럼과
   이름이 같고, 뒤에 붙은 열은 가져오기가 무시한다. 깨지면 「내보내서 고쳐서 다시
   넣는」 동선이 사라지는데, 그 사실이 **오류 없이** 조용히 드러난다
2. **채울 수 없는 열을 만들지 않는다** — `attained_cii`·`rating`은 항차 행에서 뽑을
   근거가 없다(`calculation_run.voyage_id`가 항상 NULL). 빈 칸으로 두면 「아직 계산
   안 됨」으로 읽히지만 실제로는 영원히 채워지지 않는다
3. **Excel이 한글을 깨뜨리지 않는다** — UTF-8 BOM + CRLF
4. **수식 주입이 내보내기로 새어 나가지 않는다** — 가져올 때 `'`가 붙었더라도, 다른
   경로로 들어온 값이 그대로 파일에 실릴 수 있다

케이스 (`TEST_PLAN §3.4`): IT-EXPORT-001 ~ IT-EXPORT-008
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.reports.csv_export import BOM, iter_table_csv
from cii_platform.services.data_export import (
    EXPORT_TYPES,
    ROUNDTRIP_COLUMNS,
    VOYAGE_COLUMNS,
    build_export,
)
from cii_platform.services.voyage_import import REQUIRED_COLUMNS, import_voyages


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> UUID:
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight) "
            "VALUES (:id, :imo, 'EXPORT TEST', 'BULK_CARRIER', 50000)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


async def _insert_voyage(session, vessel_id: UUID, **overrides) -> UUID:
    """항차 1건 + 연료 1건. 서비스를 거치지 않는 이유는 **실적·시각까지 채우기** 위해서다."""
    voyage_id = overrides.pop("voyage_id", None) or uuid4()
    fields = {
        "id": voyage_id,
        "vessel_id": vessel_id,
        "voyage_no": "V-2026-001",
        "status": "DRAFT",
        "regulation_year": None,
        "departure_port_name": "Busan",
        "arrival_port_name": "Rotterdam",
        "planned_distance_nm": Decimal("11200.00"),
        "planned_speed_kn": Decimal("13.50"),
        "actual_distance_nm": None,
        "actual_avg_speed_kn": None,
        "actual_departure_at": None,
        "actual_arrival_at": None,
        "notes": None,
        "annual_inclusion_policy": "EXCLUDE",
    }
    fields.update(overrides)
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, voyage_no, status, regulation_year, "
            "  departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "  actual_distance_nm, actual_avg_speed_kn, actual_departure_at, actual_arrival_at, "
            "  notes, annual_inclusion_policy, created_from) "
            "VALUES (:id, :vessel_id, :voyage_no, :status, :regulation_year, "
            "  :departure_port_name, :arrival_port_name, :planned_distance_nm, :planned_speed_kn, "
            "  :actual_distance_nm, :actual_avg_speed_kn, :actual_departure_at, "
            "  :actual_arrival_at, "
            "  :notes, :annual_inclusion_policy, 'MANUAL')"
        ),
        fields,
    )
    return voyage_id


async def _insert_fuel(session, voyage_id: UUID, **overrides) -> None:
    fields = {
        "voyage_id": voyage_id,
        "fuel_type": "HFO",
        "planned_fuel_ton": Decimal("850.0000"),
        "actual_fuel_ton": None,
        "cf_used": Decimal("3.114000"),
        "source": "USER_INPUT",
    }
    fields.update(overrides)
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "  (voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
            "VALUES (:voyage_id, :fuel_type, :planned_fuel_ton, :actual_fuel_ton, "
            "  :cf_used, :source)"
        ),
        fields,
    )


def _render(table) -> str:
    return "".join(iter_table_csv(list(table.columns), table.rows))


def _parse(rendered: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(rendered.lstrip(BOM), newline="")))


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-001 — 왕복
# ─────────────────────────────────────────────────────────────────────────────


def test_roundtrip_columns_match_import_required_columns():
    """IT-EXPORT-001 — 항차 표의 앞 일곱 열이 `§8.2` 필수 컬럼과 **이름·순서가 같다**.

    이름을 여기 다시 적지 않고 **가져오기 상수와 대조**한다. 전사하면 `§8.2`가 컬럼을
    하나 늘렸을 때 이 테스트가 옛 이름을 계속 통과시킨다.
    """
    assert ROUNDTRIP_COLUMNS == REQUIRED_COLUMNS
    assert VOYAGE_COLUMNS[1:8] == REQUIRED_COLUMNS
    # 뒤쪽 열이 필수 7종을 가리지 않는다 — 같은 이름이 두 번 나오면 DictReader가
    # 뒤엣것으로 덮어써서 왕복이 조용히 어긋난다.
    assert len(set(VOYAGE_COLUMNS)) == len(VOYAGE_COLUMNS)


@pytest.mark.asyncio
async def test_exported_file_can_be_imported_again(session, vessel_id):
    """IT-EXPORT-001 — 내보낸 CSV를 **그대로** 다시 가져오면 항차가 만들어진다.

    이 이슈의 판단 지점이었다. 깨져도 오류가 나지 않고 「필수 컬럼이 없습니다」로만
    보이므로, 사람이 눈으로 열을 대조하는 것으로는 지켜지지 않는다.
    """
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_fuel(session, voyage_id)

    table = await build_export(session, vessel_id, type="voyages")
    rendered = _render(table)

    target = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight) "
            "VALUES (:id, :imo, 'ROUNDTRIP TARGET', 'BULK_CARRIER', 50000)"
        ),
        {"id": target, "imo": f"9{target.int % 1000000:06d}"},
    )

    result = await import_voyages(session, target, content=rendered.encode("utf-8"))

    assert result["imported_count"] == 1, result["errors"]
    assert result["errors"] == []

    stored = (
        await session.execute(
            text(
                "SELECT voyage_no, planned_distance_nm, planned_speed_kn, created_from "
                "FROM voyage WHERE vessel_id = :vid"
            ),
            {"vid": target},
        )
    ).one()
    assert stored.voyage_no == "V-2026-001"
    assert stored.planned_distance_nm == Decimal("11200.00")
    assert stored.planned_speed_kn == Decimal("13.50")
    # 왕복해도 **출처는 IMPORT다** — 원본의 MANUAL을 물려받지 않는다.
    assert stored.created_from == "IMPORT"


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-002 — 채울 수 없는 열을 두지 않는다
# ─────────────────────────────────────────────────────────────────────────────


def test_voyage_table_has_no_cii_columns():
    """IT-EXPORT-002 — 항차 표에 `attained_cii`·`rating`이 **없다**.

    `calculation_run.voyage_id`가 항상 NULL이라 어떤 항차의 계산인지 되짚을 수 없고,
    「항차 하나의 CII」는 정본에 정의된 양도 아니다(`PRD §8.1.2` — CII는 연간
    집계량). 열을 두고 비워 놓으면 「아직 계산 안 됨」으로 읽힌다.
    """
    assert "attained_cii" not in VOYAGE_COLUMNS
    assert "rating" not in VOYAGE_COLUMNS
    assert "estimated_rating" not in VOYAGE_COLUMNS
    # 반대 방향 — CO₂는 연료 × CF로 **계산할 수 있으므로** 싣는다. 둘을 함께 빼면
    # 「어려우니 다 뺐다」가 되고 파일의 쓸모가 사라진다.
    assert "co2_ton" in VOYAGE_COLUMNS


@pytest.mark.asyncio
async def test_calculation_run_is_never_linked_to_a_voyage(session, vessel_id):
    """IT-EXPORT-002 — 위 판단의 **전제**를 직접 잠근다.

    언젠가 `voyage_id`를 채우게 되면 이 단언이 깨지고, 그때 항차 표에 CII를 실을지
    다시 판단하게 된다. 전제를 적어만 두면 조건이 바뀐 것을 아무도 모른다.
    """
    linked = await session.scalar(
        text("SELECT count(*) FROM calculation_run WHERE voyage_id IS NOT NULL")
    )
    assert linked == 0


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-003 — Excel 호환 (BOM · CRLF)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_starts_with_bom_and_uses_crlf(session, vessel_id):
    """IT-EXPORT-003 — 첫 바이트가 BOM이고 줄바꿈이 CRLF다 (RFC 4180 §2).

    BOM이 없으면 한국어 Windows Excel이 CP949로 읽어 **한글이 전부 깨진다.**
    """
    voyage_id = await _insert_voyage(session, vessel_id, departure_port_name="부산")
    await _insert_fuel(session, voyage_id)

    rendered = _render(await build_export(session, vessel_id, type="voyages"))

    assert rendered.startswith(BOM)
    assert rendered.encode("utf-8").startswith(b"\xef\xbb\xbf")
    assert "\r\n" in rendered
    # LF 단독이 남아 있지 않다 — 한 줄이라도 섞이면 구형 Excel이 그 줄부터 어긋난다.
    assert rendered.replace("\r\n", "").count("\n") == 0
    assert "부산" in rendered


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-004 — 수식 주입
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
async def test_formula_injection_is_escaped_on_export(session, vessel_id, prefix):
    """IT-EXPORT-004 — 위험한 시작 문자 네 종이 `'`로 escape된다.

    가져오기가 이미 막지만 **그 경로로만 값이 들어오는 것이 아니다** — 수기 등록·
    시드·직접 INSERT가 있다. 내보내는 자리에서 한 번 더 본다.
    """
    payload = f'{prefix}HYPERLINK("http://evil/","click")'
    voyage_id = await _insert_voyage(session, vessel_id, notes=payload)
    await _insert_fuel(session, voyage_id)

    rendered = _render(await build_export(session, vessel_id, type="voyages"))
    # **파싱해서 본다.** 원문에 큰따옴표가 있어 CSV가 셀을 인용하므로, 문자열
    # 포함 검사로 보면 escape가 되어도 실패하고 안 되어도 실패한다.
    cell = _parse(rendered)[0]["notes"]

    assert cell == f"'{payload}"
    assert not cell.startswith(prefix)


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-005 — 값의 모양
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_values_keep_precision_and_carry_kst_offset(session, vessel_id):
    """IT-EXPORT-005 — 숫자는 지수 표기를 만들지 않고, 시각은 KST 오프셋을 단다."""
    voyage_id = await _insert_voyage(
        session,
        vessel_id,
        planned_distance_nm=Decimal("10000.00"),
        actual_departure_at=datetime(2026, 2, 10, 7, 0, tzinfo=UTC),
    )
    await _insert_fuel(session, voyage_id, planned_fuel_ton=Decimal("850.0000"))

    row = _parse(_render(await build_export(session, vessel_id, type="voyages")))[0]

    assert row["planned_distance_nm"] == "10000.00"
    assert "E" not in row["planned_distance_nm"].upper()
    # 07:00 UTC = 16:00 KST. 오프셋이 붙어 있어 기계도 정확히 읽는다 (#646).
    assert row["actual_departure_at"] == "2026-02-10T16:00:00+09:00"
    # 비어 있는 값은 **빈 칸**이다 — `—`·`N/A`를 넣으면 숫자 열에 문자가 섞인다.
    assert row["actual_distance_nm"] == ""


@pytest.mark.asyncio
async def test_co2_uses_actual_fuel_when_present(session, vessel_id):
    """IT-EXPORT-005 — CO₂는 **실적이 있으면 실적**(`PRD §8.3` · `services/report.py`)."""
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_fuel(
        session,
        voyage_id,
        planned_fuel_ton=Decimal("100.0000"),
        actual_fuel_ton=Decimal("120.0000"),
        cf_used=Decimal("3.114000"),
    )

    row = _parse(_render(await build_export(session, vessel_id, type="voyages")))[0]

    assert Decimal(row["co2_ton"]) == Decimal("120.0000") * Decimal("3.114000")


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-006 — 한 행 = 항차 × 연료
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_fuel_voyage_splits_into_rows_that_stay_identifiable(session, vessel_id):
    """IT-EXPORT-006 — 연료가 둘이면 행이 둘이고, `voyage_id`가 같다.

    나뉜 사실이 파일에서 보여야 한다 — 보이지 않으면 받은 사람이 항차 수를 두 배로
    센다.
    """
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_fuel(session, voyage_id, fuel_type="HFO")
    await _insert_fuel(session, voyage_id, fuel_type="DIESEL_GAS_OIL", cf_used=Decimal("3.206000"))

    rows = _parse(_render(await build_export(session, vessel_id, type="voyages")))

    assert len(rows) == 2
    assert {row["fuel_type"] for row in rows} == {"HFO", "DIESEL_GAS_OIL"}
    assert {row["voyage_id"] for row in rows} == {str(voyage_id)}


@pytest.mark.asyncio
async def test_voyage_without_fuel_still_gets_a_row(session, vessel_id):
    """IT-EXPORT-006 — 연료를 아직 넣지 않은 항차도 **빠지지 않는다.**

    빼면 파일의 항차 수가 화면과 달라지고, 연료가 비었다는 사실이 사라진다.
    """
    await _insert_voyage(session, vessel_id, voyage_no="V-NO-FUEL")

    rows = _parse(_render(await build_export(session, vessel_id, type="voyages")))

    assert [row["voyage_no"] for row in rows] == ["V-NO-FUEL"]
    assert rows[0]["fuel_type"] == ""
    assert rows[0]["co2_ton"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-007 — 필터·파라미터
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_year_filters_voyages_by_regulation_year(session, vessel_id):
    """IT-EXPORT-007 — `year`는 `voyage.regulation_year`를 거른다."""
    kept = await _insert_voyage(
        session,
        vessel_id,
        voyage_no="V-2026",
        status="CONFIRMED",
        regulation_year=2026,
        annual_inclusion_policy="INCLUDE_AS_ACTUAL",
    )
    await _insert_fuel(session, kept)
    dropped = await _insert_voyage(
        session,
        vessel_id,
        voyage_no="V-2025",
        status="CONFIRMED",
        regulation_year=2025,
        annual_inclusion_policy="INCLUDE_AS_ACTUAL",
    )
    await _insert_fuel(session, dropped)

    table = await build_export(session, vessel_id, type="voyages", year=2026)

    assert [row[1] for row in table.rows] == ["V-2026"]
    assert table.filename_stem == "voyages_2026"
    # 연도를 주지 않으면 파일명에 연도가 붙지 않는다 — 붙이면 없는 한정을 주장한다.
    assert (await build_export(session, vessel_id, type="voyages")).filename_stem == "voyages"


@pytest.mark.asyncio
async def test_unknown_type_is_rejected_not_silently_defaulted(session, vessel_id):
    """IT-EXPORT-007 — `type` 오타는 **거부**다. 기본값으로 되돌리지 않는다."""
    with pytest.raises(ValidationError) as exc:
        await build_export(session, vessel_id, type="voyage")

    assert "voyages" in str(exc.value)
    # 세 값 모두 받아들여진다 — 「voyages만 되고 나머지는 501」이 아니다.
    for export_type in EXPORT_TYPES:
        table = await build_export(session, vessel_id, type=export_type)
        assert table.type == export_type
        assert len(table.columns) > 0


@pytest.mark.asyncio
async def test_missing_vessel_is_404_not_an_empty_file(session):
    """IT-EXPORT-007 — 없는 선박은 404다.

    빈 표를 돌려주면 **오타 난 UUID와 항차가 없는 선박이 같아 보인다.**
    """
    with pytest.raises(NotFoundError):
        await build_export(session, uuid4(), type="voyages")


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-008 — JSON 형식
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_json_form_carries_the_same_values_as_csv(session, vessel_id):
    """IT-EXPORT-008 — `format=json`은 **같은 표**를 열 이름과 함께 낸다.

    두 형식이 다른 경로로 값을 만들면 한쪽만 고쳐지는 날이 온다.
    """
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_fuel(session, voyage_id)

    table = await build_export(session, vessel_id, type="voyages")
    as_dicts = table.as_dicts()
    from_csv = _parse(_render(table))

    assert (
        as_dicts == from_csv
        or [{key: value for key, value in row.items()} for row in as_dicts] == from_csv
    )
    # 직렬화 가능해야 한다 — Decimal·datetime이 남아 있으면 라우트에서 500이 된다.
    json.dumps(as_dicts, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# IT-EXPORT-008 — 계산 이력 · 시뮬레이션
# ─────────────────────────────────────────────────────────────────────────────


_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64


async def _insert_calculation_run(session, vessel_id: UUID, **overrides) -> UUID:
    run_id = overrides.pop("run_id", None) or uuid4()
    fields = {
        "id": run_id,
        "vessel_id": vessel_id,
        "calculation_type": "VOYAGE_ESTIMATE",
        "input_hash": _HASH_A,
        "parameter_hash": _HASH_B,
        "model_version": json.dumps({"formula": "v1.0"}),
        "result_json": json.dumps(
            {
                "attained_cii": "5.320000",
                "required_cii": "5.100000",
                "estimated_rating": "C",
                "co2_emission_ton": "2646.9",
                "risk_level": "WARNING",
            }
        ),
        "parameters_used": json.dumps({}),
        "warnings_json": json.dumps(["REFERENCE_ONLY"]),
        "duration_ms": 12,
        "created_at": datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    await session.execute(
        text(
            "INSERT INTO calculation_run (id, vessel_id, calculation_type, input_hash, "
            "  parameter_hash, model_version, result_json, parameters_used, warnings_json, "
            "  duration_ms, created_at) "
            "VALUES (:id, :vessel_id, :calculation_type, :input_hash, :parameter_hash, "
            "  CAST(:model_version AS jsonb), CAST(:result_json AS jsonb), "
            "  CAST(:parameters_used AS jsonb), CAST(:warnings_json AS jsonb), "
            "  :duration_ms, :created_at)"
        ),
        fields,
    )
    return run_id


@pytest.mark.asyncio
async def test_calculations_export_reads_the_stored_result(session, vessel_id):
    """IT-EXPORT-008 — 계산 이력은 `result_json`을 **다시 계산하지 않고** 그대로 읽는다.

    재계산하면 그 사이 파라미터가 바뀌었을 때 **내보냈을 뿐인데 값이 달라진다.**
    """
    run_id = await _insert_calculation_run(session, vessel_id)

    rows = _parse(_render(await build_export(session, vessel_id, type="calculations")))

    assert len(rows) == 1
    assert rows[0]["calculation_run_id"] == str(run_id)
    assert rows[0]["attained_cii"] == "5.320000"
    assert rows[0]["estimated_rating"] == "C"
    assert rows[0]["input_hash"] == _HASH_A
    # 재현성 계약의 세 값이 모두 실린다 — 없으면 파일로 재현 확인을 할 수 없다.
    assert rows[0]["parameter_hash"] == _HASH_B
    assert "formula" in rows[0]["model_version"]


@pytest.mark.asyncio
async def test_scenario_run_keeps_identifiers_and_leaves_value_cells_empty(session, vessel_id):
    """IT-EXPORT-008 — 시나리오 비교는 결과가 여러 안이라 한 행에 담기지 않는다.

    행을 빼면 이력이 **파일에서 사라진다.** 식별자·해시는 남기고 값 칸만 비운다 —
    `calculation_type` 열이 그 이유를 말한다.
    """
    await _insert_calculation_run(
        session,
        vessel_id,
        calculation_type="SCENARIO",
        result_json=json.dumps({"scenarios": [], "summary": {}}),
    )

    rows = _parse(_render(await build_export(session, vessel_id, type="calculations")))

    assert rows[0]["calculation_type"] == "SCENARIO"
    assert rows[0]["input_hash"] == _HASH_A
    assert rows[0]["attained_cii"] == ""


@pytest.mark.asyncio
async def test_calculations_year_filters_by_creation_year_in_kst(session, vessel_id):
    """IT-EXPORT-008 — `calculations`의 `year`만 뜻이 다르다 — **만든 해**(KST)다.

    `calculation_run`에는 규제연도 열이 없다(`DB_SCHEMA §2.5`). 경계를 UTC로 자르면
    한국 사용자가 「1월 1일 오전에 만든 계산이 작년으로 잡힌다」를 겪는다 — 아래
    `2025-12-31T16:00Z`가 정확히 그 시각(KST 2026-01-01 01:00)이다.
    """
    await _insert_calculation_run(
        session,
        vessel_id,
        created_at=datetime(2025, 12, 31, 16, 0, tzinfo=UTC),
    )

    assert len((await build_export(session, vessel_id, type="calculations", year=2026)).rows) == 1
    assert len((await build_export(session, vessel_id, type="calculations", year=2025)).rows) == 0


@pytest.mark.asyncio
async def test_simulations_export_carries_run_and_result(session, vessel_id):
    """IT-EXPORT-008 — 시뮬레이션은 실행 행과 결과 본문을 한 행으로 합친다."""
    calc_id = await _insert_calculation_run(
        session,
        vessel_id,
        calculation_type="ANNUAL_MONTE_CARLO",
        result_json=json.dumps(
            {
                "deterministic": {"projected_attained_cii": "5.40", "projected_rating": "D"},
                "monte_carlo": {"target_success_probability": "0.62", "p50": "5.38"},
                "risk_level": "DANGER",
                "warnings": [],
            }
        ),
    )
    snapshot_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO simulation_snapshot "
            "  (id, vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
            "VALUES (:id, :vid, 2026, CAST('[]' AS jsonb), :ih, :ph)"
        ),
        {"id": snapshot_id, "vid": vessel_id, "ih": _HASH_A, "ph": _HASH_B},
    )
    sim_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO annual_simulation_run "
            "  (id, calculation_run_id, vessel_id, regulation_year, target_rating, "
            "   simulation_runs, snapshot_id) "
            "VALUES (:id, :cid, :vid, 2026, 'C', 10000, :sid)"
        ),
        {"id": sim_id, "cid": calc_id, "vid": vessel_id, "sid": snapshot_id},
    )

    rows = _parse(_render(await build_export(session, vessel_id, type="simulations", year=2026)))

    assert len(rows) == 1
    assert rows[0]["simulation_run_id"] == str(sim_id)
    assert rows[0]["target_rating"] == "C"
    assert rows[0]["simulation_runs"] == "10000"
    assert rows[0]["projected_rating"] == "D"
    assert rows[0]["target_success_probability"] == "0.62"
    # 다른 연도를 물으면 비어 있다 — `regulation_year`로 거른다.
    assert len((await build_export(session, vessel_id, type="simulations", year=2025)).rows) == 0


# ─────────────────────────────────────────────────────────────────────────────
# HTTP 계약 — 라우트가 실제로 붙어 있고 인증 뒤에 있다
# ─────────────────────────────────────────────────────────────────────────────


def test_route_is_registered_with_the_spec_parameters() -> None:
    """`API_SPEC §8.1` 그대로 — `GET /vessels/{vessel_id}/export`, `type`은 **필수**.

    서비스만 있고 라우터를 등록하지 않아도 위의 테스트는 전부 통과한다. `app.routes`가
    아니라 **OpenAPI 문서**를 읽는 이유는 이 FastAPI 판이 라우터를 감싸서
    ``app.routes``에 하위 경로가 드러나지 않기 때문이다 (`#634`에서 겪었다).
    """
    from cii_platform.api.main import app

    paths = app.openapi()["paths"]
    # 검사 대상이 실제로 있다 — 경로 표기가 바뀌면 아래 단언이 조용히 사라진다.
    assert len(paths) > 20

    operation = paths["/api/v1/vessels/{vessel_id}/export"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}

    assert params["type"]["required"] is True
    assert params["year"]["required"] is False
    assert params["format"]["required"] is False


def test_export_is_behind_the_auth_wall() -> None:
    """세션 없이 부르면 401이다 — 항차·계산 이력이 공개 경로로 새지 않는다."""
    from fastapi.testclient import TestClient

    from cii_platform.api.main import app

    with TestClient(app, base_url="https://testserver") as client:
        resp = client.get(f"/api/v1/vessels/{uuid4()}/export?type=voyages")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_disposition_names_the_file_after_type_and_year() -> None:
    """`attachment; filename="voyages_2026.csv"` (`§8.1` 응답 예시).

    ASCII `filename`과 UTF-8 `filename*`을 **둘 다** 보낸다 (RFC 6266 §4.3) —
    리포트(`§8.3`)와 같은 규칙이며, 한쪽만 보내는 습관을 남기면 선박명을 붙이는 날
    깨진다.
    """
    from cii_platform.api.routes.exports import _disposition
    from cii_platform.services.data_export import ExportTable

    table = ExportTable(type="voyages", year=2026, columns=VOYAGE_COLUMNS, rows=[])
    disposition = _disposition(table)

    assert disposition.startswith('attachment; filename="voyages_2026.csv"')
    assert "filename*=UTF-8''voyages_2026.csv" in disposition
