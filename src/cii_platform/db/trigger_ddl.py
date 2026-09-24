"""트리거 DDL을 멱등하게 — **있으면 만들지 않고, 없으면 지우지 않는다** (`#1373`).

## 왜 필요한가

**CUBRID는 같은 이름의 트리거를 두 번 만드는 것을 막지 않는다.** 실측이다 — 있는 이름으로
``CREATE TRIGGER``를 다시 치면 성공하고 ``db_trigger``가 한 줄 는다(160 → 161). 그리고
**중복이 생기면 그 이름으로는 어느 쪽도 지울 수 없다**::

    SELECT count(*) FROM db_trigger WHERE name = 'trg_chk_status_policy_upd'   → 2
    DROP TRIGGER trg_chk_status_policy_upd
      → Trigger "dba.trg_chk_status_policy_upd" was not found. (errno=-503)

``dba.`` 접두를 붙이거나 따옴표로 감싸도 같다. 한 번 중복이 생기면 그 DB는 **이름 기반으로는
영구히 회복되지 않는다** — 다시 만드는 수밖에 없다(`README` 「테스트 DB 복구」).

마이그레이션이 ``CREATE TRIGGER``를 무조건 치면 ``upgrade``가 두 번 도는 순간(끊긴 왕복의
재시도 · 부분 실패 뒤 재실행) 중복이 생기고, 그 뒤의 ``downgrade``는 ``DROP TRIGGER``에서
``-503``을 받아 그 리비전에 갇힌다. 2026-09-20 CI에서 PR 10건 중 3건이 이 경로로 빨갰고,
그중 하나는 프런트엔드 파일 하나만 바꾼 PR이었다.

## 무엇을 하는가

두 방향 모두 **카탈로그(``db_trigger``)를 먼저 본다.**

- :func:`create_trigger` — 이름이 이미 있으면 만들지 않는다. 중복이 **생기지 않는다.**
- :func:`drop_trigger` — 이름이 없으면 지우지 않는다. 다운그레이드는 가드를 *걷어내는*
  방향이라 대상이 이미 없는 것을 실패로 볼 이유가 없다.

카탈로그에 있는데도 ``DROP``이 ``-503``으로 답하면(중복 상태) **경고를 남기고 넘어간다** —
``048``이 `#1386`에서 택한 것과 같은 판단이다. 그 자리에서 멈추면 롤백 전체가 그 리비전에
갇히고, 넘어가면 트리거가 하나 남을 뿐이다(그 위에서 ``upgrade``가 다시 돌아도
:func:`create_trigger`가 있는 이름을 건너뛰므로 셋이 되지 않는다). 남은 중복은
``tests/test_zz_roundtrip.py``의 중복 단언이 잡는다.

**``upgrade``에서 조건을 바꾸는 교체는 다르다** — :func:`replace_trigger`는 지운 뒤에도 그
이름이 남아 있으면 멈춘다. 배포가 옛 조건을 남긴 채 성공으로 끝나면 안 되기 때문이다.
관용은 ``downgrade``(롤백이 갇히지 않게)에만 둔다.

## ``op``를 인자로 받는 이유

``from alembic import op``를 여기서 하지 않는다. 검사가 마이그레이션 모듈의 ``op``를
**갈아 끼워** 돌리기 때문이다 — ``tests/test_migration_guard.py``는 ``op``에 닿는 순간 실패하는
대역으로 가드의 배선을 보고, ``tests/test_dbschema_head_sync.py``·``test_zz_roundtrip.py``는
``op.execute``의 SQL만 세는 스텁으로 DB 없이 트리거 수를 센다. 이 모듈이 제 ``op``를 갖고
있으면 그 셋이 전부 진짜 alembic에 닿아 헛돈다.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

_log = logging.getLogger(__name__)

#: CUBRID가 「그런 트리거가 없다」로 답할 때의 오류 번호와 문구.
NOT_FOUND_ERRNO = -503
NOT_FOUND = "was not found"

#: 중복 상태에서 ``upgrade``가 멈출 때 가리키는 절.
RECOVERY_DOC = "README 「테스트 DB 복구」"


def _is_not_found(exc: sa.exc.DatabaseError) -> bool:
    """``-503``인가 — 드라이버가 ``errno``를 주면 그것으로, 아니면 문구로 본다."""
    errno = getattr(getattr(exc, "orig", None), "errno", None)
    return errno == NOT_FOUND_ERRNO or NOT_FOUND in str(exc)


def existing_triggers(op: Any) -> set[str]:
    """지금 DB에 있는 트리거 이름. ``db_trigger``에는 **사용자 트리거만** 들어 있다."""
    rows = op.get_bind().execute(sa.text("SELECT name FROM db_trigger")).fetchall()
    return {row[0] for row in rows}


def create_trigger(op: Any, name: str, body: str, *, existing: set[str] | None = None) -> bool:
    """``CREATE TRIGGER {name} {body}`` — **이미 있으면 만들지 않는다.**

    ``body``는 이름 뒤의 나머지 전부다(``BEFORE INSERT ON vessel IF NOT (…) EXECUTE REJECT``).
    ``existing``을 주면 카탈로그를 다시 묻지 않고 그 집합을 쓰며, 만든 이름을 거기 더한다 —
    한 마이그레이션이 수십 개를 만들 때 조회 한 번으로 끝내기 위해서다.

    만들었으면 ``True``, 건너뛰었으면 ``False``.
    """
    have = existing if existing is not None else existing_triggers(op)
    if name in have:
        return False
    op.execute(f"CREATE TRIGGER {name} {body}")
    have.add(name)
    return True


def drop_trigger(op: Any, name: str, *, existing: set[str] | None = None) -> bool:
    """``DROP TRIGGER {name}`` — **없으면 지우지 않는다.**

    카탈로그에 있는데도 ``-503``이 오면(같은 이름이 둘 이상 — 모듈 docstring) 경고를 남기고
    넘어간다. 다른 오류는 그대로 올린다 — 조용히 삼키면 진짜 실패까지 가린다.

    지웠으면 ``True``, 건너뛰었거나 지우지 못했으면 ``False``.
    """
    have = existing if existing is not None else existing_triggers(op)
    if name not in have:
        return False
    try:
        op.execute(f"DROP TRIGGER {name}")
    except sa.exc.DatabaseError as exc:
        if not _is_not_found(exc):
            raise
        _log.warning(
            "트리거 %s가 db_trigger에는 있는데 DROP TRIGGER가 「없다」(-503)로 답했습니다 — "
            "같은 이름이 둘 이상인 상태로 보입니다(#1373). 이름으로는 지울 수 없으므로 "
            "넘어갑니다. %s대로 DB를 다시 만드십시오.",
            name,
            RECOVERY_DOC,
        )
        return False
    have.discard(name)
    return True


def replace_trigger(op: Any, name: str, body: str) -> None:
    """지우고 같은 이름으로 다시 만든다 — **지우지 못했으면 멈춘다.**

    ``050``·``051``·``057``처럼 조건을 바꾸는 ``upgrade``가 쓴다. CUBRID에는
    ``CREATE OR REPLACE TRIGGER``가 없어 지우고 만드는데, 중복 상태에서는 :func:`drop_trigger`가
    ``-503``을 넘어가고 :func:`create_trigger`가 「있으면 건너뜀」으로 조용히 끝나 **옛 조건이
    그대로 남은 채 리비전만 올라간다.** 배포 경로(``upgrade head``)가 그것을 성공으로 보고하면
    안 되므로, 지운 뒤 카탈로그를 다시 물어 그 이름이 남아 있으면 :class:`RuntimeError`를
    올린다 — 복구는 DB를 다시 만드는 것뿐이라 그 절을 가리킨다.

    ``downgrade`` 쪽은 이 함수를 쓰지 않는다. 롤백이 그 자리에서 갇히는 것이 옛 조건이 남는
    것보다 나쁘므로(결정요청 v6 ``D-20``), 거기서는 :func:`drop_trigger` + :func:`create_trigger`로
    관용한다.
    """
    drop_trigger(op, name)
    if name in existing_triggers(op):
        raise RuntimeError(
            f"트리거 {name}를 지우지 못했습니다 — db_trigger에 같은 이름이 둘 이상이라 이름으로는 "
            f"지울 수 없는 상태입니다(#1373). 옛 조건을 남긴 채 진행하지 않습니다. "
            f"{RECOVERY_DOC}대로 DB를 다시 만든 뒤 upgrade를 다시 실행하십시오."
        )
    create_trigger(op, name, body)
