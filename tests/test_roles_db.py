"""사무직·현장직 역할 (#672) — **DB로 돈다**.

`PRD §20 O-14`가 「역할 2종 도입」으로 바뀌었다. 여기서 잠그는 것은 다섯이다.

1. **새 계정은 현장직**이고, `INITIAL_ADMIN_EMAILS`에 든 이메일만 가입·로그인에서 관리자가 된다
   — 새 DB에서 관리자 0명이 되지 않게(`auth/role_bootstrap.py`)
2. **현장직은 사무직 전용 경로에서 `403 FORBIDDEN_ROLE`** — CSRF의 403과 코드가 다르다
3. **사무직 전용 경로 목록은 `API_SPEC §1.2` 표와 소스가 같다** — 한쪽만 바뀌면 여기서 걸린다
4. **마지막 사무직은 탈퇴도 강등도 못 한다** — 0명이 되면 아무도 되돌릴 수 없다
5. **역할 변경은 감사 로그에 남는다** — 리포트·계정 관리의 문이 언제 열리고 닫혔는가

케이스: AT-AUTH-017 (`TEST_PLAN §4.7`)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.api.routes.auth import LAST_ADMIN_MESSAGE
from cii_platform.auth import role_bootstrap
from cii_platform.auth.dependencies import (
    ADMIN_ONLY_MESSAGE,
    OFFICE_ONLY_MESSAGE,
    AuthenticationError,
    RoleForbiddenError,
    require_admin,
    require_office,
)
from cii_platform.db.types import JSONText, UuidText
from cii_platform.errors import ERROR_HTTP_STATUS

_BASE = "https://testserver"
_ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery"

#: `_user_payload`의 키 — `/auth/me` 계약(`test_response_contract_db.py`)과 같다.
USER_KEYS = frozenset({"id", "email", "display_name", "role", "email_verified_at", "last_login_at"})


@pytest.fixture
def client(migrated_db, app_fresh_engine, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INITIAL_ADMIN_EMAILS", raising=False)
    with TestClient(app, base_url=_BASE) as c:
        yield c


async def _cleanup(emails: list[str]) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        for email in emails:
            await s.execute(
                text(
                    "DELETE FROM user_session WHERE user_id IN "
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": email},
            )
            # 가입하면 확인 토큰이 함께 생긴다. `fk_user_token_user`가 살아 있어
            # 토큰을 남겨 두면 계정 삭제가 막히고, **정리가 조용히 실패해 다음 실행이
            # `409 이미 가입된 이메일`로 떨어진다** (`#1058` — CUBRID에서 드러났다).
            await s.execute(
                text(
                    "DELETE FROM user_token WHERE user_id IN "
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": email},
            )
            await s.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_type = 'app_user' AND entity_id IN "
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": email},
            )
            await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


async def _role_in_db(email: str) -> str | None:
    """DB를 직접 읽는다 — 응답만 보면 detached 함정(#279)을 못 잡는다."""
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        return (
            await s.execute(text('SELECT "role" FROM app_user WHERE email = :e'), {"e": email})
        ).scalar_one_or_none()


async def _role_changes_for(user_id: str) -> list[dict]:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        rows = await s.execute(
            text(
                # `action`·`timestamp`는 둘 다 CUBRID 예약어다 (`#1058`).
                "SELECT user_id, details_json FROM audit_log "
                "WHERE \"action\" = 'ROLE_CHANGE' AND entity_id = :id "
                'ORDER BY "timestamp"'
                # `entity_id`는 `CHAR(32)`다. API가 주는 대시 형식을 생 SQL에 그대로
                # 실으면 **오류 없이 0건**이 온다 — 타입을 붙여야 맞는다 (`#1058`).
            )
            .bindparams(bindparam("id", type_=UuidText()))
            # raw SQL에는 컬럼 타입이 붙지 않아 `JSONText`의 result processor가 돌지
            # 않는다 — 붙이지 않으면 **문자열**이 와서 dict 비교가 어긋난다 (`#1058`).
            .columns(details_json=JSONText()),
            {"id": user_id},
        )
        return [dict(r._mapping) for r in rows]


async def _demote_other_admin_users(keep: list[str]) -> list[UUID]:
    """``keep`` 밖의 관리자를 전부 현장직으로 내리고 **되돌릴 id**를 돌려준다.

    「마지막 관리자」 상황은 만들어서 본다 — 다른 검사가 남긴 관리자가 있으면 409가 나지
    않는다. 끝나면 :func:`_restore_office` 로 되돌린다 (#1301).
    """
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        # CUBRID 세 가지 (`#1058`) — ⑴ `role`은 예약어라 인용한다 ⑵ `<> ALL(:x)`·
        # `= ANY(:x)`는 PostgreSQL 배열 문법이고 pycubrid는 목록을 한 파라미터로 묶어
        # 보내지 못한다 — 자리표시자를 직접 펼친다 ⑶ `is_deleted`는 SMALLINT다.
        keep_ph = ", ".join(f":keep{i}" for i in range(len(keep))) or "NULL"
        rows = await s.execute(
            text(
                f"""SELECT id FROM app_user WHERE "role" = 'ADMIN' AND is_deleted = 0 """
                f"AND email NOT IN ({keep_ph})"
            ),
            {f"keep{i}": v for i, v in enumerate(keep)},
        )
        ids = [r[0] for r in rows]
        if ids:
            id_ph = ", ".join(f":id{i}" for i in range(len(ids)))
            await s.execute(
                text(f"""UPDATE app_user SET "role" = 'FIELD' WHERE id IN ({id_ph})"""),
                {f"id{i}": v for i, v in enumerate(ids)},
            )
        await s.commit()
    return ids


async def _restore_office(ids: list[UUID]) -> None:
    from cii_platform.db.session import get_sessionmaker

    if not ids:
        return
    async with get_sessionmaker()() as s:
        # `role` 예약어 인용 + `= ANY(:ids)` 배열 문법 제거 (`#1058`).
        # ⚠️ 이 함수는 `finally`에서 돈다 — 여기서 터지면 **뒤따르는 계정 정리가
        # 통째로 건너뛰어져**, 다음 실행이 `409 이미 가입된 이메일`로 떨어진다.
        id_ph = ", ".join(f":id{i}" for i in range(len(ids)))
        await s.execute(
            text(f"""UPDATE app_user SET "role" = 'OFFICE' WHERE id IN ({id_ph})"""),
            {f"id{i}": v for i, v in enumerate(ids)},
        )
        await s.commit()


def _signup(client: TestClient, email: str) -> dict:
    resp = client.post(f"{API_V1_PREFIX}/auth/signup", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _login(client: TestClient, email: str) -> dict:
    resp = client.post(f"{API_V1_PREFIX}/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


# --- 1. 최초 사무직 --------------------------------------------------------------------


def test_parse_initial_admin_emails_normalises_like_signup():
    """쉼표 목록 · 공백 · 대소문자 — 가입이 소문자로 정규화하므로 목록도 같은 규칙이다."""
    parsed = role_bootstrap.parse_initial_admin_emails(" Office@BlueLog.kr, b@x.io ,, ")
    assert parsed == frozenset({"office@bluelog.kr", "b@x.io"})
    assert role_bootstrap.parse_initial_admin_emails(None) == frozenset()
    assert role_bootstrap.is_initial_admin(
        "OFFICE@bluelog.kr", {"INITIAL_ADMIN_EMAILS": "office@bluelog.kr"}
    )
    assert not role_bootstrap.is_initial_admin(
        "x@bluelog.kr", {"INITIAL_ADMIN_EMAILS": "office@bluelog.kr"}
    )


def test_production_refuses_to_start_without_an_initial_admin(monkeypatch: pytest.MonkeyPatch):
    """조용히 관리자 0명으로 뜨면 첫 사용자가 계정 관리를 열 때에야 드러난다 — 기동에서 끊는다."""
    from cii_platform import config

    monkeypatch.setattr(config, "_ENV", "production")
    with pytest.raises(RuntimeError, match="INITIAL_ADMIN_EMAILS"):
        role_bootstrap.validate_initial_admin({})
    role_bootstrap.validate_initial_admin({"INITIAL_ADMIN_EMAILS": "office@bluelog.kr"})

    monkeypatch.setattr(config, "_ENV", "development")
    role_bootstrap.validate_initial_admin({})


def test_real_app_lifespan_runs_the_initial_admin_check(monkeypatch: pytest.MonkeyPatch):
    """배선 — `lifespan`에서 호출을 빠뜨리면 위 검사는 통과하고 이것만 실패한다."""
    from cii_platform import config

    monkeypatch.setattr(config, "_ENV", "production")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://bluelog.example")
    monkeypatch.setenv("SIGNUP_ALLOWED_DOMAINS", "bluelog.kr")
    monkeypatch.delenv("INITIAL_ADMIN_EMAILS", raising=False)
    with pytest.raises(RuntimeError, match="INITIAL_ADMIN_EMAILS"), TestClient(app):
        pass  # pragma: no cover - 진입 자체가 실패한다


async def test_new_signup_is_field_and_initial_admin_email_is_admin(client, monkeypatch):
    """새 계정은 현장직, 목록에 든 이메일만 **관리자** — 응답과 DB 둘 다 본다 (#1301)."""
    field_email = "role-new@example.com"
    admin_email = "role-initial@example.com"
    try:
        assert _signup(client, field_email)["role"] == "FIELD"
        assert await _role_in_db(field_email) == "FIELD"

        monkeypatch.setenv("INITIAL_ADMIN_EMAILS", " Role-Initial@example.com ")
        assert _signup(client, admin_email)["role"] == "ADMIN"
        assert await _role_in_db(admin_email) == "ADMIN"
    finally:
        await _cleanup([field_email, admin_email])


async def test_login_promotes_an_initial_admin_email_and_audits_once(client, monkeypatch):
    """044 이전 가입자·화면에서 강등된 계정도 목록에 있으면 로그인에서 **관리자**가 된다."""
    email = "role-promote@example.com"
    try:
        user = _signup(client, email)
        assert user["role"] == "FIELD"

        monkeypatch.setenv("INITIAL_ADMIN_EMAILS", email)
        assert _login(client, email)["role"] == "ADMIN"
        assert await _role_in_db(email) == "ADMIN"
        changes = await _role_changes_for(user["id"])
        assert [c["details_json"] for c in changes] == [
            {"role_before": "FIELD", "role_after": "ADMIN"}
        ]
        assert changes[0]["user_id"] == user["id"]

        # 이미 관리자면 다시 쓰지 않는다 — 「ADMIN → ADMIN」이 쌓이면 실제 변경을 못 찾는다
        _login(client, email)
        assert len(await _role_changes_for(user["id"])) == 1
    finally:
        await _cleanup([email])


# --- 2·3. 사무직 전용 경로 ---------------------------------------------------------------


def _documented_office_only() -> set[str]:
    """`API_SPEC §1.2` 「사무직 전용 경로」 표를 읽는다 — 정본이 목록의 주인이다."""
    doc = (_ROOT / "API_SPEC.md").read_text(encoding="utf-8")
    start = doc.index("**사무직 전용 경로**")
    block = doc[start:].split("\n\n", 2)[1]
    rows = re.findall(r"^\| `([A-Z]+) (/[^`]+)` \|", block, flags=re.M)
    assert rows, "API_SPEC §1.2의 사무직 전용 경로 표를 읽지 못했다"
    return {f"{m} {re.sub(r'\{[^}]*\}', '{}', p)}" for m, p in rows}


def _office_only_in_source() -> set[str]:
    """``require_office``가 걸린 라우트를 소스에서 모은다.

    `test_auth_wiring._mutating_routes`와 같은 방식이다 — FastAPI 객체를 훑는 코드는
    ``include_router`` 래퍼에 가려 0개를 검사하고도 통과할 수 있다.
    """
    return _guarded_in_source("require_office")


def _guarded_in_source(guard: str) -> set[str]:
    """``routes/*.py``에서 ``guard``가 인자로 걸린 라우트를 모은다 (#1301에서 갈라냈다)."""
    routes_dir = _ROOT / "src" / "cii_platform" / "api" / "routes"
    found: set[str] = set()
    for path in sorted(routes_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prefix = ""
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "router" for t in node.targets
            ):
                for kw in getattr(node.value, "keywords", []):
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if guard not in ast.unparse(node.args):
                continue
            for deco in node.decorator_list:
                func = getattr(deco, "func", None)
                method = getattr(func, "attr", "").upper()
                if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                    continue
                if deco.args and isinstance(deco.args[0], ast.Constant):
                    route = re.sub(r"\{[^}]*\}", "{}", f"{prefix}{deco.args[0].value}")
                    found.add(f"{method} {route}")
    return found


def _documented_admin_only() -> set[str]:
    """`API_SPEC §1.2` 「관리자 전용 경로」 표를 읽는다 (#1301) — 사무직 표와 같은 규약이다."""
    doc = (_ROOT / "API_SPEC.md").read_text(encoding="utf-8")
    start = doc.index("**관리자 전용 경로**")
    block = doc[start:].split("\n\n", 2)[1]
    rows = re.findall(r"^\| `([A-Z]+) (/[^`]+)` \|", block, flags=re.M)
    assert rows, "API_SPEC §1.2의 관리자 전용 경로 표를 읽지 못했다"
    return {f"{m} {re.sub(r'\{[^}]*\}', '{}', p)}" for m, p in rows}


def _admin_only_in_source() -> set[str]:
    """``require_admin``이 걸린 라우트를 소스에서 모은다.

    :func:`_office_only_in_source`와 같은 방식이다.
    """
    return _guarded_in_source("require_admin")


def test_admin_only_routes_match_the_api_spec_table():
    """정본 표 ↔ 소스 (#1301). 계정 관리를 관리자에서 도로 빼면 여기서 걸린다."""
    documented = _documented_admin_only()
    in_source = _admin_only_in_source()
    assert in_source, "require_admin이 걸린 라우트를 하나도 찾지 못했다 — 검사가 가짜다"
    assert documented == in_source, (
        f"정본에만: {sorted(documented - in_source)}\n소스에만: {sorted(in_source - documented)}"
    )


def test_account_management_is_not_office_only_any_more():
    """계정 관리 둘이 **사무직 표에 남아 있지 않다** (#1301).

    위 두 대조는 각자의 표와 소스가 같은지만 본다 — 둘 다 옮기면서 사무직 표에 그대로
    두면 두 표에 함께 있게 되고, 그때도 각 대조는 통과한다.
    """
    overlap = _documented_office_only() & _documented_admin_only()
    assert not overlap, f"두 표에 함께 있는 경로: {sorted(overlap)}"
    assert "GET /auth/users" in _documented_admin_only()


def test_office_only_routes_match_the_api_spec_table():
    """정본 표 ↔ 소스. 한쪽에만 있으면 여기서 걸린다 — 라우트를 늘리면 표도 늘린다."""
    documented = _documented_office_only()
    in_source = _office_only_in_source()
    assert in_source, "require_office가 걸린 라우트를 하나도 찾지 못했다 — 검사가 가짜다"
    assert documented == in_source, (
        f"정본에만: {sorted(documented - in_source)}\n소스에만: {sorted(in_source - documented)}"
    )


def test_forbidden_role_is_a_403_with_its_own_code():
    """CSRF와 같은 403이지만 코드가 다르다 — 화면이 `error.code`로 가른다."""
    assert ERROR_HTTP_STATUS["FORBIDDEN_ROLE"] == 403
    err = RoleForbiddenError()
    assert err.code == "FORBIDDEN_ROLE"
    assert err.http_status == 403
    assert err.message == OFFICE_ONLY_MESSAGE
    # 관리자 전용은 **같은 코드에 다른 문구**다 (#1301) — 사무직이 여기서 막혔을 때
    # 「사무직 계정만 할 수 있습니다」를 읽으면 자기가 사무직인데 그 말을 듣게 된다.
    admin_err = RoleForbiddenError(ADMIN_ONLY_MESSAGE)
    assert admin_err.code == "FORBIDDEN_ROLE"
    assert admin_err.message == ADMIN_ONLY_MESSAGE
    assert ADMIN_ONLY_MESSAGE != OFFICE_ONLY_MESSAGE


def test_require_office_is_fail_closed():
    """세션 사용자가 없으면(배선 어김) 통과가 아니라 401이다 — `require_csrf`와 같은 판단."""
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    request = Request(scope)
    with pytest.raises(AuthenticationError):
        require_office(request)
    # 관리자 가드도 같은 규율이다 (#1301).
    with pytest.raises(AuthenticationError):
        require_admin(request)


#: 현장직으로 두드려 볼 사무직 전용 경로 — 표의 경로에 실제 값을 넣은 것.
#: 의존성이 본문 검증보다 먼저 돌므로 본문은 비워도 403이 난다.
_PROBE = [
    ("POST", "/vessels", {}),
    ("PATCH", f"/vessels/{uuid4()}", {}),
    ("DELETE", f"/vessels/{uuid4()}", None),
    ("POST", "/annual-simulations", {}),
    ("POST", f"/annual-simulations/{uuid4()}/reproduce", {}),
    ("POST", f"/scenarios/{uuid4()}/adopt", {}),
    ("GET", f"/voyages/{uuid4()}/report", None),
    ("GET", f"/vessels/{uuid4()}/annual-report", None),
    ("POST", "/fleet/reduction-plans/evaluate", {}),
    ("POST", "/fleet/reduction-plans", {}),
    ("GET", "/fleet/reduction-plans", None),
    ("GET", f"/fleet/reduction-plans/{uuid4()}", None),
    ("POST", "/parameters/import", {}),
    ("GET", "/audit-logs", None),
]

#: 사무직으로 두드려 볼 **관리자 전용** 경로 (#1301). 계정 관리 둘이 여기로 옮겨 왔다.
_ADMIN_PROBE = [
    ("GET", "/auth/users", None),
    ("PATCH", f"/auth/users/{uuid4()}/role", {"role": "OFFICE"}),
]


def test_probe_list_covers_every_documented_route():
    """위 목록이 표를 전부 두드리는가 — 표가 늘었는데 여기가 안 늘면 검사가 좁아진다."""
    probed = {f"{m} {re.sub(r'/[0-9a-f-]{36}', '/{}', p)}" for m, p, _ in _PROBE}
    assert probed == _documented_office_only()


async def test_field_user_gets_403_forbidden_role_on_every_office_only_route(client):
    """현장직 — 표의 경로 전부에서 **403 · `FORBIDDEN_ROLE` · 정본 문구**."""
    email = "role-field@example.com"
    try:
        _signup(client, email)
        for method, path, body in _PROBE:
            resp = client.request(
                method, f"{API_V1_PREFIX}{path}", json=body, headers=_csrf(client)
            )
            assert resp.status_code == 403, f"{method} {path}: {resp.status_code} {resp.text}"
            assert resp.json()["error"]["code"] == "FORBIDDEN_ROLE", f"{method} {path}"
            assert resp.json()["error"]["message"] == OFFICE_ONLY_MESSAGE
        # 관리자 전용도 막힌다 — 문구는 다르다 (#1301)
        for method, path, body in _ADMIN_PROBE:
            resp = client.request(
                method, f"{API_V1_PREFIX}{path}", json=body, headers=_csrf(client)
            )
            assert resp.status_code == 403, f"{method} {path}: {resp.status_code} {resp.text}"
            assert resp.json()["error"]["message"] == ADMIN_ONLY_MESSAGE
        # 두 역할 모두인 경로는 그대로 지나간다 — 항차·위치·계산은 현장의 주 업무다
        assert client.get(f"{API_V1_PREFIX}/vessels").status_code == 200
        assert client.get(f"{API_V1_PREFIX}/parameters/regulation-years").status_code == 200
    finally:
        await _cleanup([email])


async def test_user_list_and_role_update_share_the_user_contract(client, monkeypatch):
    """관리자 — 목록·역할 변경 응답은 `/auth/me`와 같은 사용자 계약이다 (`#753` 계약 표)."""
    office = "role-office-a@example.com"
    other = "role-office-target@example.com"
    try:
        monkeypatch.setenv("INITIAL_ADMIN_EMAILS", office)
        me = _signup(client, office)
        assert me["role"] == "ADMIN"
        monkeypatch.delenv("INITIAL_ADMIN_EMAILS")
        with TestClient(app, base_url=_BASE) as second:
            target = _signup(second, other)

        listed = client.get(f"{API_V1_PREFIX}/auth/users")
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert set(body["meta"]) >= {"request_id", "timestamp"}
        by_email = {row["email"]: row for row in body["data"]}
        assert {office, other} <= by_email.keys()
        for row in body["data"]:
            assert set(row) == USER_KEYS, row
            assert "password_hash" not in row
        assert by_email[other]["role"] == "FIELD"
        assert body["data"] == sorted(body["data"], key=lambda r: r["email"])

        changed = client.patch(
            f"{API_V1_PREFIX}/auth/users/{target['id']}/role",
            json={"role": "OFFICE"},
            headers=_csrf(client),
        )
        assert changed.status_code == 200, changed.text
        assert set(changed.json()["data"]) == USER_KEYS
        assert changed.json()["data"]["role"] == "OFFICE"
        assert await _role_in_db(other) == "OFFICE"
        changes = await _role_changes_for(target["id"])
        assert [c["details_json"] for c in changes] == [
            {"role_before": "FIELD", "role_after": "OFFICE"}
        ]
        assert changes[0]["user_id"] == me["id"], "행위자는 바꾼 사람이다"

        # 같은 값이면 쓰지 않는다 — 감사 로그가 늘지 않는다
        again = client.patch(
            f"{API_V1_PREFIX}/auth/users/{target['id']}/role",
            json={"role": "OFFICE"},
            headers=_csrf(client),
        )
        assert again.status_code == 200
        assert len(await _role_changes_for(target["id"])) == 1

        # 모르는 역할은 422, 없는 계정은 404 — DB 트리거에 닿아 500이 되지 않는다.
        # `#1301` 전에는 이 자리가 `ADMIN`이었다 — 이제 유효한 값이라 쓸 수 없다.
        bad = client.patch(
            f"{API_V1_PREFIX}/auth/users/{target['id']}/role",
            json={"role": "SUPERUSER"},
            headers=_csrf(client),
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
        missing = client.patch(
            f"{API_V1_PREFIX}/auth/users/{uuid4()}/role",
            json={"role": "FIELD"},
            headers=_csrf(client),
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup([office, other])


# --- 4·5. 마지막 사무직 ------------------------------------------------------------------


async def test_last_admin_cannot_be_demoted_or_deleted(client, monkeypatch):
    """관리자가 하나면 그 하나는 탈퇴도 강등도 못 한다. 둘이면 서로 바꿀 수 있다 (#1301)."""
    solo = "role-last@example.com"
    second = "role-second@example.com"
    demoted: list[UUID] = []
    try:
        monkeypatch.setenv("INITIAL_ADMIN_EMAILS", f"{solo},{second}")
        me = _signup(client, solo)
        demoted = await _demote_other_admin_users(keep=[solo])

        # ⑴ 자기 강등 → 409
        resp = client.patch(
            f"{API_V1_PREFIX}/auth/users/{me['id']}/role",
            json={"role": "FIELD"},
            headers=_csrf(client),
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "CONFLICT"
        assert resp.json()["error"]["message"] == LAST_ADMIN_MESSAGE
        assert await _role_in_db(solo) == "ADMIN"

        # ⑵ 탈퇴 → 409, 계정은 그대로
        gone = client.delete(f"{API_V1_PREFIX}/auth/me", headers=_csrf(client))
        assert gone.status_code == 409, gone.text
        assert gone.json()["error"]["message"] == LAST_ADMIN_MESSAGE
        assert await _role_in_db(solo) == "ADMIN"
        assert client.get(f"{API_V1_PREFIX}/auth/me").status_code == 200, "세션이 살아 있다"

        # ⑶ 관리자가 하나 더 생기면 강등도 탈퇴도 된다
        with TestClient(app, base_url=_BASE) as other:
            other_me = _signup(other, second)
            assert other_me["role"] == "ADMIN"
            resp = other.patch(
                f"{API_V1_PREFIX}/auth/users/{me['id']}/role",
                json={"role": "FIELD"},
                headers=_csrf(other),
            )
            assert resp.status_code == 200, resp.text
            assert await _role_in_db(solo) == "FIELD"
            changes = await _role_changes_for(me["id"])
            assert changes[-1]["details_json"] == {"role_before": "ADMIN", "role_after": "FIELD"}
            assert changes[-1]["user_id"] == other_me["id"]

            # 이제 solo는 현장직 — 관리자 전용 경로가 막힌다(세션 캐시가 아니라 DB 역할이다)
            assert client.get(f"{API_V1_PREFIX}/auth/users").status_code == 403

            # 마지막이 된 second는 탈퇴 못 한다
            gone = other.delete(f"{API_V1_PREFIX}/auth/me", headers=_csrf(other))
            assert gone.status_code == 409
    finally:
        await _restore_office(demoted)
        await _cleanup([solo, second])


# --- 마이그레이션 --------------------------------------------------------------------------


async def test_migration_044_marks_existing_accounts_office(migrated_db):
    """044 이전에 있던 계정은 전부 사무직이 된다 — 그래야 아무도 잃지 않는다.

    ``conn`` fixture는 단일 트랜잭션이라 alembic 서브프로세스가 그 사이에 스키마를 바꿀 수
    없다 — `test_app_user_migration.py`처럼 **별도 커밋**으로 한다.
    """
    from conftest import run_alembic

    from cii_platform.db.session import get_engine, get_sessionmaker

    email = "role-migration@example.com"
    sessionmaker = get_sessionmaker()
    try:
        down = run_alembic("downgrade", "043")
        assert down.returncode == 0, down.stderr
        async with sessionmaker() as s:
            await s.execute(
                text("INSERT INTO app_user (email, password_hash) VALUES (:e, 'x')"),
                {"e": email},
            )
            await s.commit()
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr
        async with sessionmaker() as s:
            role = (
                await s.execute(text('SELECT "role" FROM app_user WHERE email = :e'), {"e": email})
            ).scalar_one()
        assert role == "OFFICE"
    finally:
        restore = run_alembic("upgrade", "head")
        assert restore.returncode == 0, restore.stderr
        async with sessionmaker() as s:
            await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
            await s.commit()
        await get_engine().dispose()
