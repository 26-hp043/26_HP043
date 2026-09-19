"""규제 파라미터 CSV 적재 (#673 · API_SPEC §7.5) — **DB로 돈다**.

잠그는 것 — 케이스 ID는 `TEST_PLAN §3.5`의 ``IT-IMPORT-001``~``005``를 따르고,
계약은 결정요청 v9 회신 「가」(사무직 전용 · CSV · OTHER 연료 생성 포함)다.

1. **새 연도·개정 연도** — 개정은 기존 활성 행을 끄고 새 행을 넣는다(`DB_SCHEMA
   §7.2` · `054`). 이행 행이 남는 것이 정상 상태다 (``IT-IMPORT-001``)
2. **전부 아니면 전무** — 한 행이라도 걸리면 아무것도 들어가지 않는다
   (``IT-IMPORT-005``). ``§8.2`` 항차 CSV의 부분 성공과 정반대 계약이다
3. **``dry_run``은 실제 적재와 같은 판정** — 같은 파일의 ``errors[]``가 같다
   (#1190 규약 재사용)
4. **행 검증** — ``a_raw`` 비숫자(``IT-IMPORT-003``) · 파일 안 키 중복
   (``IT-IMPORT-002``) · ``OTHER`` 적용 시작일 필수(``PRD §3.4.2``)
5. **``fuel_type``은 제자리 갱신 + ``content_hash`` 재계산** (``IT-IMPORT-004`` —
   ``DB_SCHEMA §8.3.1`` 산출 규약 그대로)
6. **사무직 전용** — 현장직은 ``403 FORBIDDEN_ROLE``, 적재는 감사 로그에 남는다
"""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.calc.hash import compute_parameter_hash

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"
IMPORT_URL = f"{API_V1_PREFIX}/parameters/import"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_imports(app_fresh_engine):
    """각 검사가 남긴 적재 행을 치운다 — ``migrated_db``는 스키마만 맞춘다.

    개정 검사는 **시드 행의 활성 상태를 바꾼다**(이행 행으로 끔). 지우고 되살리지
    않으면 다음 실행에서 「2027이 목록에 없다」로 떨어진다. ``test_roles_db``의
    ``_cleanup``과 같은 자리·같은 방법이다.
    """
    yield
    from decimal import Decimal

    from cii_platform.calc.hash import compute_parameter_hash
    from cii_platform.db.seed import _CF_ROWS
    from cii_platform.db.session import get_sessionmaker

    # live DB의 출처 표기 — `seed.py`의 SOURCE_FUEL_TYPE("IMO 2018 Guidelines")과
    # 갈라져 있다(마이그레이션 6c7496c4d122가 MEPC.364(79)로 적재 · #87/#140 정정).
    # 되돌리는 값은 **살아 있는 DB**를 기준으로 한다(test_fuel_type_seed가 잠근 값).
    _live_source_ref = "MEPC.364(79)"

    async with get_sessionmaker()() as s:
        for table in ("regulation_year", "cii_reference_line", "cii_rating_boundary"):
            await s.execute(text(f"DELETE FROM {table} WHERE version LIKE 'import.%'"))
            await s.execute(text(f"UPDATE {table} SET is_active = 1 WHERE version = '1.0'"))
        await s.execute(text("DELETE FROM fuel_type WHERE code = 'OTHER'"))
        # 🔴 연료는 제자리 갱신이라 **값**이 흔들린다 — version만 되돌리면 안 되고
        # CF·content_hash를 시드로 되돌린다. 그대로 두면 아무 상관 없는 검사(시나리오
        # 예시 동기화)가 다음 실행에서 깨진다(실측 — HFO 3.114→3.12로 CO₂가 움직였다).
        for code, display_name, cf in _CF_ROWS:
            await s.execute(
                text(
                    "UPDATE fuel_type SET cf = :cf, display_name = :dn, "
                    "source_ref = :sr, version = '1.0', effective_from = NULL, "
                    "content_hash = :ch WHERE code = :code"
                ),
                {
                    "cf": Decimal(cf),
                    "dn": display_name,
                    "sr": _live_source_ref,
                    "ch": compute_parameter_hash({"code": code, "cf": Decimal(cf)}),
                    "code": code,
                },
            )
        await s.execute(text("DELETE FROM audit_log WHERE \"action\" = 'PARAMETER_IMPORT'"))
        await s.commit()


@pytest.fixture
def client(migrated_db, app_fresh_engine, monkeypatch: pytest.MonkeyPatch):
    # 이메일은 실행마다 고유하게 — migrated_db는 스키마만 맞추고 데이터를 지우지
    # 않으므로 재실행에서 같은 주소가 409가 된다(test_roles_db의 _cleanup와 같은 문제).
    office = f"param-office-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("INITIAL_OFFICE_EMAILS", office)
    with TestClient(app, base_url=_BASE) as c:
        resp = c.post(f"{API_V1_PREFIX}/auth/signup", json={"email": office, "password": PASSWORD})
        assert resp.status_code == 201, resp.text
        yield c


@pytest.fixture
def field_client(migrated_db, app_fresh_engine, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INITIAL_OFFICE_EMAILS", raising=False)
    with TestClient(app, base_url=_BASE) as c:
        resp = c.post(
            f"{API_V1_PREFIX}/auth/signup",
            json={
                "email": f"param-field-{uuid4().hex[:8]}@example.com",
                "password": PASSWORD,
            },
        )
        assert resp.status_code == 201, resp.text
        yield c


def _csv(header: str, *rows: str) -> bytes:
    buf = io.StringIO()
    buf.write(header + "\r\n")
    for row in rows:
        buf.write(row + "\r\n")
    return buf.getvalue().encode("utf-8")


def _post(client: TestClient, body: bytes, type_: str, *, dry_run: bool = False) -> dict:
    resp = client.post(
        f"{IMPORT_URL}?dry_run={str(dry_run).lower()}",
        files={"file": ("parameters.csv", body, "text/csv")},
        data={"type": type_},
        headers={"X-CSRF-Token": client.cookies["csrf"]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


_REGULATION_HEADER = "year,z_factor_percent,effective_from,source_ref"


# ── ⑴ 새 행·개정 (IT-IMPORT-001) ─────────────────────────────────────────────


async def test_new_year_is_imported_and_audited(client, conn):
    data = _post(
        client,
        _csv(
            _REGULATION_HEADER,
            "2031,17.9,2030-01-01,MEPC.400(83) amendment",
        ),
        "regulation_years",
    )
    assert data["imported_count"] == 1
    assert data["replaced_count"] == 0
    assert data["errors"] == []
    assert data["dry_run"] is False

    rows = (
        await conn.execute(
            text(
                'SELECT "year", z_factor_percent, version, is_active FROM regulation_year '
                'WHERE "year" = 2031'
            )
        )
    ).all()
    assert len(rows) == 1
    assert str(rows[0].z_factor_percent) == "17.9000"
    assert rows[0].version.startswith("import."), rows[0].version
    assert rows[0].is_active == 1

    audits = (
        await conn.execute(
            text(
                "SELECT user_id, entity_type, details_json FROM audit_log "
                "WHERE \"action\" = 'PARAMETER_IMPORT'"
            ),
        ),
    )[0].all()
    assert len(audits) == 1, "적재가 감사 로그에 남지 않았다"
    assert audits[0].user_id is not None
    assert audits[0].entity_type == "regulation_years"
    details = audits[0].details_json
    if isinstance(details, str):  # 생 SQL은 JSONText 없이 문자열로 온다 (#1058)
        import json

        details = json.loads(details)
    assert details["imported_count"] == 1


async def test_revision_deactivates_the_old_row_and_keeps_history(client, conn):
    """개정 — 기존 활성 행은 이행 행으로 남고 새 행이 현행이 된다 (DB_SCHEMA §7.2)."""
    data = _post(
        client,
        _csv(
            _REGULATION_HEADER,
            "2027,14.5,2027-01-01,MEPC.400(83) 2026 update",
        ),
        "regulation_years",
    )
    assert data["imported_count"] == 1
    assert data["replaced_count"] == 1, "기존 활성 행을 대체했다는 표시가 없다"

    rows = (
        await conn.execute(
            text(
                "SELECT z_factor_percent, is_active FROM regulation_year "
                'WHERE "year" = 2027 ORDER BY is_active'
            )
        )
    ).all()
    assert len(rows) == 2, "개정 이행 행이 남지 않았다"
    assert rows[0].is_active == 0, "이행 행의 값이 보존되지 않았다"
    assert str(rows[0].z_factor_percent) == "13.6250"  # 시드의 2027 값(MEPC.400(83))
    assert rows[1].is_active == 1
    assert str(rows[1].z_factor_percent) == "14.5000"

    # 조회 API는 활성 행만 내준다 — 같은 연도가 두 번 나오면 현행을 가릴 수 없다
    listed = client.get(f"{API_V1_PREFIX}/parameters/regulation-years").json()["data"]
    year_2027 = [row for row in listed if row["year"] == 2027]
    assert [row["z_factor_percent"] for row in year_2027] == ["14.5000"]


# ── ⑵ 전부 아니면 전무 (IT-IMPORT-005) ───────────────────────────────────────


async def test_one_bad_row_rolls_back_everything(client, conn):
    data = _post(
        client,
        _csv(
            _REGULATION_HEADER,
            "2031,17.9,2030-01-01,MEPC.400(83) amendment",
            "2032,abc,2031-01-01,MEPC.400(83) amendment",  # 둘째 행 — z가 숫자가 아니다
            "2033,21.0,2032-01-01,MEPC.400(83) amendment",
        ),
        "regulation_years",
    )
    assert data["imported_count"] == 0
    assert data["errors"] == [
        {"row": 3, "field": "z_factor_percent", "message": "숫자로 읽을 수 없습니다: abc"}
    ]
    # 앞의 멀쩡한 행도 들어가지 않았다 — 전부 아니면 전무
    count = (
        await conn.execute(
            text('SELECT count(*) FROM regulation_year WHERE "year" IN (2031, 2032, 2033)')
        )
    ).scalar()
    assert count == 0


async def test_dry_run_and_real_import_agree_on_errors(client, conn):
    """같은 파일의 ``dry_run``과 실제 적재가 같은 판정을 낸다 (#1190 규약)."""
    body = _csv(
        _REGULATION_HEADER,
        "2031,17.9,2030-01-01,MEPC.400(83) amendment",
        "2031,18.0,2030-01-01,MEPC.400(83) amendment",  # 파일 안 키 중복 (IT-IMPORT-002)
    )
    dry = _post(client, body, "regulation_years", dry_run=True)
    real = _post(client, body, "regulation_years")
    assert dry["errors"] == real["errors"]
    assert dry["errors"][0]["row"] == 3
    assert dry["errors"][0]["field"] == "year"
    count = (
        await conn.execute(text('SELECT count(*) FROM regulation_year WHERE "year" = 2031'))
    ).scalar()
    assert count == 0


async def test_dry_run_imports_nothing_but_counts(client, conn):
    body = _csv(_REGULATION_HEADER, "2031,17.9,2030-01-01,MEPC.400(83) amendment")
    dry = _post(client, body, "regulation_years", dry_run=True)
    assert dry == {
        "table": "regulation_years",
        "imported_count": 1,
        "replaced_count": 0,
        "errors": [],
        "dry_run": True,
    }
    count = (
        await conn.execute(text('SELECT count(*) FROM regulation_year WHERE "year" = 2031'))
    ).scalar()
    assert count == 0, "dry_run이 저장했다"
    audits = (
        await conn.execute(
            text("SELECT count(*) FROM audit_log WHERE \"action\" = 'PARAMETER_IMPORT'")
        )
    ).scalar()
    assert audits == 0, "dry_run은 감사 로그에 남지 않는다 — 적재가 일어나지 않았다"


# ── ⑶ 행 검증 ────────────────────────────────────────────────────────────────


_REF_HEADER = "ship_type,condition_expr,capacity_rule,a_raw,c,source_ref"


async def test_reference_line_a_raw_must_be_an_imo_coefficient(client):
    """``IT-IMPORT-003`` — ``a_raw``가 숫자가 아니면 행 오류 (422가 아니라 errors[])."""
    data = _post(
        client,
        _csv(
            _REF_HEADER,
            "BULK_CARRIER,__test__,DWT,not-a-number,0.622,TEST",
        ),
        "reference_lines",
    )
    assert data["imported_count"] == 0
    assert data["errors"][0]["field"] == "a_raw"


async def test_reference_line_computes_a_decimal_from_a_raw(client, conn):
    """``a_decimal``은 서버가 ``parse_imo_scientific``으로 계산한다 (TECH_SPEC §9.2~9.3)."""
    data = _post(
        client,
        _csv(_REF_HEADER, "GAS_CARRIER,__test__,DWT,14405E7,0.4550,TEST"),
        "reference_lines",
    )
    assert data["imported_count"] == 1
    row = (
        await conn.execute(
            text(
                "SELECT a_raw, a_decimal, is_active FROM cii_reference_line "
                "WHERE condition_expr = '__test__'"
            )
        )
    ).one()
    assert row.a_raw == "14405E7"
    assert str(row.a_decimal) == "144050000000.000000"
    assert row.is_active == 1


async def test_reference_line_revision_keeps_history_and_active_is_unique(client, conn):
    _post(
        client,
        _csv(_REF_HEADER, "GAS_CARRIER,__rev__,DWT,4745E3,0.622,TEST"),
        "reference_lines",
    )
    data = _post(
        client,
        _csv(_REF_HEADER, "GAS_CARRIER,__rev__,DWT,4800E3,0.622,TEST"),
        "reference_lines",
    )
    assert data["replaced_count"] == 1
    rows = (
        await conn.execute(
            text(
                "SELECT a_raw, is_active FROM cii_reference_line "
                "WHERE condition_expr = '__rev__' ORDER BY is_active"
            )
        )
    ).all()
    assert [(row.a_raw, row.is_active) for row in rows] == [("4745E3", 0), ("4800E3", 1)]
    # 계산이 읽는 목록은 활성 행만 — 이행 행이 섞이면 안 된다 (054의 계약)
    listed = client.get(
        f"{API_V1_PREFIX}/parameters/reference-lines", params={"ship_type": "GAS_CARRIER"}
    ).json()["data"]
    revs = [row for row in listed if row["condition_expr"] == "__rev__"]
    assert [row["a_raw"] for row in revs] == ["4800E3"]


async def test_rating_boundary_d_order_is_a_row_error(client):
    data = _post(
        client,
        _csv(
            "ship_type,condition_expr,capacity_basis,d1,d2,d3,d4,source_ref",
            "BULK_CARRIER,__test__,DWT,0.94,0.86,1.06,1.18,TEST",
        ),
        "rating_boundaries",
    )
    assert data["imported_count"] == 0
    assert data["errors"][0]["field"] == "d1"


async def test_unknown_ship_type_is_a_row_error(client):
    data = _post(
        client,
        _csv(_REF_HEADER, "BULK_CARIER,__test__,DWT,4745E3,0.622,TEST"),  # 오타
        "reference_lines",
    )
    assert data["errors"][0]["field"] == "ship_type"


async def test_bad_capacity_rule_is_a_row_error(client):
    data = _post(
        client,
        _csv(_REF_HEADER, "BULK_CARRIER,__test__,fixed abc,4745E3,0.622,TEST"),
        "reference_lines",
    )
    assert data["errors"][0]["field"] == "capacity_rule"


# ── ⑷ fuel_type — 제자리 갱신 + OTHER 생성 ──────────────────────────────────


_FUEL_HEADER = "code,display_name,cf,source_ref,effective_from"


async def test_fuel_cf_update_recomputes_content_hash(client, conn):
    """``IT-IMPORT-004`` — 갱신 뒤 ``content_hash``가 산출 규약대로 재계산된다.

    CF는 **시드와 다른 값**으로 올린다 — 같은 값이면 재계산 여부가 해시에 드러나지
    않아 돌연변이(재계산 누락)가 조용히 통과한다(실측).
    """
    data = _post(
        client,
        _csv(_FUEL_HEADER, "HFO,Heavy Fuel Oil,3.120000,MEPC.364(79) update,"),
        "fuel_types",
    )
    assert data["imported_count"] == 1
    assert data["replaced_count"] == 1, "기존 HFO 행을 제자리에서 갱신했다"

    row = (
        await conn.execute(
            text("SELECT cf, content_hash, version, updated_at FROM fuel_type WHERE code = 'HFO'")
        )
    ).one()
    from decimal import Decimal

    assert row.content_hash == compute_parameter_hash({"code": "HFO", "cf": Decimal(str(row.cf))})
    assert row.version.startswith("import.")
    assert row.updated_at is not None, "fuel_type의 제자리 갱신은 updated_at이 움직인다(§7.2 예외)"
    # 행은 하나다 — fuel_type에는 이행 행이 쌓이지 않는다
    count = (await conn.execute(text("SELECT count(*) FROM fuel_type WHERE code = 'HFO'"))).scalar()
    assert count == 1


async def test_other_fuel_creation_requires_effective_from(client, conn):
    """``PRD §3.4.2`` — OTHER는 CF 출처 메모와 적용 시작일이 필수다."""
    data = _post(
        client,
        _csv(_FUEL_HEADER, "OTHER,사용자 정의 연료,3.050000,선사 제공 증빙,"),
        "fuel_types",
    )
    assert data["imported_count"] == 0
    assert data["errors"][0]["field"] == "effective_from"

    created = _post(
        client,
        _csv(_FUEL_HEADER, "OTHER,사용자 정의 연료,3.050000,선사 제공 증빙,2026-10-01"),
        "fuel_types",
    )
    assert created["imported_count"] == 1
    assert created["replaced_count"] == 0

    # 화면의 연료 선택지(GET /parameters/fuel-types 기본=활성)에 OTHER가 나온다
    listed = client.get(f"{API_V1_PREFIX}/parameters/fuel-types").json()["data"]
    assert "OTHER" in {row["code"] for row in listed}


# ── ⑸ 권한·파일 단위 ─────────────────────────────────────────────────────────


def test_field_role_is_403(field_client):
    body = _csv(_REGULATION_HEADER, "2031,17.9,2030-01-01,X")
    resp = field_client.post(
        IMPORT_URL,
        files={"file": ("parameters.csv", body, "text/csv")},
        data={"type": "regulation_years"},
        headers={"X-CSRF-Token": field_client.cookies["csrf"]},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_unknown_type_is_422(client):
    body = _csv(_REGULATION_HEADER, "2031,17.9,2030-01-01,X")
    resp = client.post(
        IMPORT_URL,
        files={"file": ("parameters.csv", body, "text/csv")},
        data={"type": "vessels"},
        headers={"X-CSRF-Token": client.cookies["csrf"]},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "type"


def test_missing_required_column_is_422(client):
    resp = client.post(
        IMPORT_URL,
        files={"file": ("parameters.csv", b"year,z_factor_percent\r\n2031,17.9\r\n", "text/csv")},
        data={"type": "regulation_years"},
        headers={"X-CSRF-Token": client.cookies["csrf"]},
    )
    assert resp.status_code == 422
    assert "필수 컬럼" in resp.json()["error"]["message"]
