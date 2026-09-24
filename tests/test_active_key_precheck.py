"""``061`` 사전 검사 — 중복이면 아무것도 바꾸기 전에 멈춘다 (TEST_PLAN §5.6 `DB-SOFT-007` · #1631).

DB 없이 돈다. ``tests/migration_stub.py``의 세는 스텁으로 ``alembic``을 갈아 끼우고, 카탈로그
조회에 「활성 중복 그룹이 있다」로 답하게 한 뒤 ``upgrade()``를 **실제로 부른다** — 소스를
읽지 않는다. 검사가 걷는 순서보다 뒤에 있거나 빠지면 ``047`` 트리거 DROP이 먼저 세어져
드러난다.

문구는 ``duplicate_message``가 조립한다 — 배포 로그는 공개 저장소의 Actions에 남으므로
**값(IMO·이메일)이 문구에 없어야 한다**는 것도 여기서 본다. 실제 CUBRID 위에서 같은 검사가
같은 자리에서 멈추는지는 ``tests/test_zz_active_key_precheck_db.py``가 본다.
"""

from __future__ import annotations

import importlib.util
import re
import types
from pathlib import Path

import pytest
from migration_stub import install

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_MIGRATION = next(_VERSIONS.glob("061_*.py"))

#: 사전 검사의 조회만 알아보는 표지 — ``HAVING COUNT(*) > 1``은 061 안에서 이 조회뿐이다.
_DUPLICATE_QUERY = "HAVING COUNT(*) > 1"


def _load_061(
    monkeypatch: pytest.MonkeyPatch, groups: dict[str, int]
) -> tuple[types.ModuleType, object]:
    """``alembic``을 스텁으로 갈아 끼우고 061을 적재한다. ``groups``는 표별 중복 그룹 수."""
    op = install(monkeypatch)
    real_bind = op.get_bind()

    class Count:
        """``scalar_one()``이 그룹 수를 준다 — 스텁의 ``NullResult``는 늘 0이라 쓰지 않는다."""

        def __init__(self, value: int) -> None:
            self._value = value

        def scalar_one(self) -> int:
            return self._value

    class Bind:
        dialect = real_bind.dialect

        def execute(self, sql, *args, **kwargs):
            text = str(sql)
            if _DUPLICATE_QUERY in text:
                table = next(name for name in groups if f"FROM {name} " in text)
                return Count(groups[table])
            return real_bind.execute(sql, *args, **kwargs)

    monkeypatch.setattr(op, "get_bind", lambda: Bind())
    spec = importlib.util.spec_from_file_location("_precheck_061", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op


def test_duplicates_stop_the_upgrade_before_anything_is_dropped(monkeypatch: pytest.MonkeyPatch):
    """중복이 하나라도 있으면 예외 — 그 전에 ``047`` 트리거를 걷지도, 무엇을 만들지도 않는다."""
    module, op = _load_061(monkeypatch, {"vessel": 2, "app_user": 0})

    with pytest.raises(module.ActiveDuplicatesError) as exc:
        module.upgrade()

    assert op.dropped == [], f"멈추기 전에 트리거를 걷었다: {op.dropped}"
    assert op.created == [], f"멈추기 전에 트리거를 만들었다: {op.created}"
    message = str(exc.value)
    assert "vessel.imo_number 2개" in message
    assert "app_user.email 0개" in message
    assert "OPERATIONS.md §3.6.4" in message


def test_without_duplicates_the_upgrade_proceeds(monkeypatch: pytest.MonkeyPatch):
    """두 표 모두 0이면 검사가 지나가고 ``047`` 트리거 4개를 걷는다 — 늘 멈추는 검사가 아니다."""
    module, op = _load_061(monkeypatch, {"vessel": 0, "app_user": 0})
    # 047이 만든 트리거가 있는 상태에서 시작한다 — 없으면 헬퍼가 지우지 않는다(`#1373`).
    op.live.update(
        module._legacy_trigger_name(prefix, event)
        for *_, prefix in module.ACTIVE_KEYS
        for event in module._EVENTS
    )

    module.upgrade()

    assert sorted(op.dropped) == sorted(
        module._legacy_trigger_name(prefix, event)
        for *_, prefix in module.ACTIVE_KEYS
        for event in module._EVENTS
    )


def test_message_names_counts_and_the_procedure_but_no_values():
    """문구는 그룹 수·절차만 — 값이 들어갈 자리가 아예 없다(배포 로그는 공개 저장소에 남는다)."""
    spec = importlib.util.spec_from_file_location("_precheck_061_message", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    message = module.duplicate_message({"vessel.imo_number": 1, "app_user.email": 3})

    assert "vessel.imo_number 1개" in message
    assert "app_user.email 3개" in message
    assert "§3.6.4" in message
    assert "alembic upgrade head" in message
    # 값을 받는 인자가 없다 — 이메일(`@`)도 IMO(7자리)도 문구에 들어갈 길이 없다.
    assert "@" not in message
    assert re.search(r"\d{7}", message) is None
