"""TECH_SPEC §16.3의 import·직접 DB 접근 경계 (#2101).

AST로 절대·상대·함수 안 import와 문자열을 명시한 동적 import를 확인한다.
임의 문자열 조합/런타임 반영까지 해석하는 Python 분석기는 아니다.
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "src/cii_platform"
_LOWER = {"calc", "db", "services", "validation"}
# TECH_SPEC §16.3의 D-4 예외. 계산/시나리오/새 업무 라우트는 여기에 없다.
_DIRECT_DB_ROUTES = {
    "auth": "계정·세션·역할·탈퇴와 연관된 정리",
    "auth_dev": "개발 로그인 계정·세션",
    "auth_tokens": "메일 인증·재설정 토큰과 계정",
    "audit_logs": "감사 조회(현재는 서비스로 조회)",
    "chat": "대화 이력·세션과 인증 사용자",
}
_DI_IMPORTS = {
    "cii_platform.db.session.get_session",
    "sqlalchemy.ext.asyncio.AsyncSession",
}


def _targets(tree, package):
    dynamic_functions = {"__import__"}
    importlib_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            for alias in node.names:
                yield node.lineno, module if alias.name == "*" else f"{module}.{alias.name}"
                if module == "importlib" and alias.name == "import_module":
                    dynamic_functions.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        dynamic = isinstance(function, ast.Name) and function.id in dynamic_functions
        dynamic |= (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in importlib_names
            and function.attr == "import_module"
        )
        argument = node.args[0]
        if dynamic and isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            target = argument.value
            if target.startswith("."):
                package_kw = next((k.value for k in node.keywords if k.arg == "package"), None)
                target = resolve_name(
                    target,
                    package_kw.value if isinstance(package_kw, ast.Constant) else package,
                )
            yield node.lineno, target


def _violations(source, module, *, is_package=False):
    tree = ast.parse(source)
    package = module if is_package else module.rsplit(".", 1)[0]
    findings = []
    parts = module.split(".")
    is_lower = len(parts) > 1 and parts[1] in _LOWER
    is_route = module == "cii_platform.api.routes" or module.startswith("cii_platform.api.routes.")
    route = module.rsplit(".", 1)[-1]
    direct_allowed = is_route and route in _DIRECT_DB_ROUTES
    for line, target in _targets(tree, package):
        if is_lower and (target == "cii_platform.api" or target.startswith("cii_platform.api.")):
            findings.append((line, "하위→API", target))
        if is_route and (target == "cii_platform.calc" or target.startswith("cii_platform.calc.")):
            findings.append((line, "라우트→계산", target))
        is_db = target == "cii_platform.db" or target.startswith("cii_platform.db.")
        is_sql = target == "sqlalchemy" or target.startswith("sqlalchemy.")
        if is_route and (is_db or is_sql) and target not in _DI_IMPORTS and not direct_allowed:
            findings.append((line, "라우트→DB", target))
    if is_route and not direct_allowed:
        # 주입 세션의 직접 메소드 호출을 본다. 별칭을 붙여도 같은 세션이다.
        sessions = {"session"}
        session_types = {"AsyncSession"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy.ext.asyncio":
                session_types.update(
                    a.asname or a.name for a in node.names if a.name == "AsyncSession"
                )
            if (
                isinstance(node, ast.arg)
                and node.annotation
                and any(
                    isinstance(n, ast.Name) and n.id in session_types
                    for n in ast.walk(node.annotation)
                )
            ):
                sessions.add(node.arg)
        changed = True
        while changed:
            changed = False
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in sessions
                ):
                    for name in node.targets:
                        if isinstance(name, ast.Name) and name.id not in sessions:
                            sessions.add(name.id)
                            changed = True
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver = node.func.value
                if (
                    isinstance(receiver, ast.Name)
                    and receiver.id in sessions
                    and node.func.attr not in {"commit", "rollback"}
                ):
                    findings.append((node.lineno, "라우트 세션 직접 접근", node.func.attr))
    return findings


def test_repository_obeys_layer_boundaries():
    findings = []
    actual_routes = {p.stem for p in (_ROOT / "api/routes").glob("*.py")}
    assert set(_DIRECT_DB_ROUTES) <= actual_routes, "없는 라우트가 DB 예외 목록에 남았다"
    for area in [*sorted(_LOWER), "api/routes"]:
        for path in (_ROOT / area).rglob("*.py"):
            parts = path.relative_to(_ROOT.parent).with_suffix("").parts
            is_package = parts[-1] == "__init__"
            module = ".".join(parts[:-1] if is_package else parts)
            findings.extend(
                (str(path.relative_to(_ROOT)), *f)
                for f in _violations(path.read_text(), module, is_package=is_package)
            )
    assert not findings, findings


@pytest.mark.parametrize(
    "source",
    [
        "from cii_platform.api.field_labels import field_label",
        "import cii_platform.api as upper",
        "from cii_platform import api",
        "from ..api import schemas",
        "def helper():\n from cii_platform.api import error_handlers",
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            " from cii_platform.api import schemas"
        ),
        "import importlib as loader\nloader.import_module('cii_platform.api.schemas')",
        (
            "from importlib import import_module as load\n"
            "load('..api', package='cii_platform.services')"
        ),
        "__import__('cii_platform.api')",
    ],
)
def test_lower_reverse_imports_are_rejected(source):
    assert _violations(source, "cii_platform.services.example")


@pytest.mark.parametrize(
    "source",
    [
        "from cii_platform.db.models.voyage import Voyage",
        "from ...db.repositories import voyage as repo",
        "import sqlalchemy as sa",
        "from sqlalchemy import select",
        "async def endpoint(session):\n await session.execute('SELECT 1')",
        "async def endpoint(session):\n other = session\n await other.add(object())",
        (
            "from sqlalchemy.ext.asyncio import AsyncSession as Session\n"
            "async def endpoint(conn: Session):\n await conn.scalar('SELECT 1')"
        ),
    ],
)
def test_new_business_route_direct_db_access_is_rejected(source):
    assert _violations(source, "cii_platform.api.routes.calculations")


def test_route_session_injection_and_atomic_commit_are_allowed():
    source = """from sqlalchemy.ext.asyncio import AsyncSession
from cii_platform.db.session import get_session
from cii_platform.services import audit
async def endpoint(session: AsyncSession):
 await audit.record(session)
 await session.commit()
 await session.rollback()
"""
    assert not _violations(source, "cii_platform.api.routes.scenarios")


@pytest.mark.parametrize("route", sorted(_DIRECT_DB_ROUTES))
def test_explicit_auth_audit_chat_exceptions_are_allowed(route):
    source = (
        "from cii_platform.db.repositories import audit_log\n"
        "from sqlalchemy import select\nasync def endpoint(session):\n"
        " await session.execute(select(1))"
    )
    assert not _violations(source, f"cii_platform.api.routes.{route}")


@pytest.mark.parametrize("route", ["auth_extra", "chat_reports", "audit_other"])
def test_similar_route_name_does_not_inherit_exception(route):
    assert _violations(
        "from cii_platform.db.models.app_user import AppUser", f"cii_platform.api.routes.{route}"
    )


def test_route_cannot_import_calculation_engine_directly():
    assert _violations(
        "from cii_platform.calc.cii import attained_cii", "cii_platform.api.routes.calculations"
    )
