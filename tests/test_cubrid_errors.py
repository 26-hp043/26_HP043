"""``db/cubrid_errors.py`` — 드라이버 errno·메시지를 ``IntegrityError``로 가르는 규칙 (#1631).

DB 없이 돈다. 여기 적은 메시지 원문은 CUBRID 11.4.6 + pycubrid 1.7.1 실측이다 — 061의
활성 키 트리거는 행을 넣은 **뒤에** 자기 행을 갱신하므로 유니크 위반이 트리거 액션
안에서 나고(``-528``), 직접 위반(``-670``)과 문장은 같되 번호가 다르다.

**잠그는 것** — ⑴ ``-528``은 유니크 위반 문구가 있을 때만 무결성 위반이다(트리거 액션이
다른 이유로 실패한 것까지 중복으로 오인하지 않는다) ⑵ 인덱스 이름을 그대로 돌려준다 —
라우트·서비스가 「어느 유니크인가」로 409 여부를 가른다.
"""

from __future__ import annotations

from cii_platform.db.cubrid_errors import (
    TRIGGER_ACTION_ERRNO,
    _is_integrity_violation,
    violated_unique_index,
)

#: 실측 원문 (2026-09-24 · `cii` 개발 DB · probe 표). 인덱스 이름만 실제 것으로 바꿨다.
_TRIGGER_ACTION_UNIQUE = (
    'Error evaluating action for "dba.trg_vessel_imo_active_ins", Operation would have caused '
    "one or more unique constraint violations. INDEX uq_vessel_imo_active(B+tree: 1|4096|4097) "
    "ON CLASS dba.vessel(CLASS_OID: 0|218|5). key: '9300001'(OID: 0|5825|6). "
    "(errno=-528, description='Error evaluating action', sqlstate='HY000')"
)
_DIRECT_UNIQUE = (
    "Operation would have caused one or more unique constraint violations. "
    "INDEX uq_app_user_email_active(B+tree: 1|4096|4097) "
    "ON CLASS dba.app_user(CLASS_OID: 0|218|5). key: 'a@example.com'(OID: 0|5825|6). "
    "(errno=-670, description='Unique constraint violation', sqlstate='23000')"
)
_TRIGGER_ACTION_OTHER = (
    'Error evaluating action for "dba.trg_something_ins", Missing value for attribute "name". '
    "(errno=-528, description='Error evaluating action', sqlstate='HY000')"
)


class _Driver(Exception):
    """드라이버 예외 흉내 — 규칙은 ``str()``만 본다."""


def test_trigger_action_unique_violation_is_an_integrity_violation():
    assert TRIGGER_ACTION_ERRNO == -528
    assert _is_integrity_violation(_Driver(_TRIGGER_ACTION_UNIQUE)) is True


def test_trigger_action_failing_for_another_reason_is_not_translated():
    """같은 -528이라도 유니크 문구가 없으면 그대로 올린다 — 중복으로 오인하지 않는다."""
    assert _is_integrity_violation(_Driver(_TRIGGER_ACTION_OTHER)) is False
    assert violated_unique_index(_Driver(_TRIGGER_ACTION_OTHER)) is None


def test_violated_unique_index_names_the_index_for_both_shapes():
    """직접 위반(-670)과 트리거 액션 안 위반(-528)에서 같은 이름을 집는다."""
    assert violated_unique_index(_Driver(_TRIGGER_ACTION_UNIQUE)) == "uq_vessel_imo_active"
    assert violated_unique_index(_Driver(_DIRECT_UNIQUE)) == "uq_app_user_email_active"


def test_violated_unique_index_is_none_without_an_exception():
    assert violated_unique_index(None) is None
