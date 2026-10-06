"""활성-유니크 트리거 6개가 비활성 행을 통과시키게 — ``new.is_active = 0 OR NOT EXISTS`` (#2104)

Revision ID: 067
Revises: 066
Create Date: 2026-10-06

무엇이 어긋나 있었나
--------------------
``054``가 ``regulation_year``·``cii_reference_line``·``cii_rating_boundary``에 건 활성-유니크
트리거 여섯의 조건은 이것이었다::

    IF EXISTS (SELECT 1 FROM <표> WHERE <키> = new.<키> AND is_active = 1 AND id <> new.id)
    EXECUTE REJECT

``new.is_active``가 조건에 없다. 그래서 **같은 키의 활성 행이 하나라도 있으면 쓰려는 행이
비활성이어도 거부된다** — 이행 행(``is_active = 0``)을 INSERT하거나, 이미 있는 이행 행의
다른 열을 UPDATE하는 것이 전부 막혔다(2026-10-06 ``cii_test``에서 세 표 모두 실측).
``054`` docstring과 ``DB_SCHEMA §2.10``은 「**활성 행끼리만** 유일하다」고 적는데, 집행은
「활성 행이 있으면 같은 키는 아무것도 못 쓴다」였다.

지금까지 드러나지 않은 것은 운영의 두 쓰기 경로가 그 좁은 조건을 우연히 피해 가기
때문이다 — ``services/parameter_import._apply_versioned``는 기존 활성 행을 **먼저** 끄고
(UPDATE · 자기 자신은 ``id <> new.id``로 빠진다) 새 활성 행을 넣으며, ``db/seed._upsert_active``는
활성 행만 갱신하거나 없을 때만 넣는다. 둘 다 「활성 행이 있는 키에 비활성 행을 쓰는」
모양이 아니다. 그러나 정본이 허용하는 상태를 DB가 거부하고 있었고, 검사
(``tests/test_parameter_migrations.py``)는 그 한 순서만 보고 있었다.

어떻게
------
``047``이 소프트 삭제에 쓴 모양을 그대로 가져온다 — 삭제된 행은 언제나 통과,
활성 행끼리만 ``NOT EXISTS``::

    IF NOT (new.is_active = 0 OR NOT EXISTS (SELECT 1 FROM <표>
            WHERE <키> = new.<키> AND is_active = 1 AND id <> new.id))
    EXECUTE REJECT

옛 조건이 참이던 쓰기 중 **새 조건도 참인 것은 ``new.is_active <> 0``인 것뿐**이다. 즉 이
교체는 거부 집합을 **좁히기만** 한다 — 전에 통과하던 쓰기는 전부 그대로 통과한다
(적재 순서 「끄기 → flush → 넣기」·seed의 upsert 포함). 활성 행 둘은 여전히 거부된다 —
INSERT도, 이행 행을 ``is_active = 1``로 되살리는 UPDATE도(``047`` ⑥과 같은 판단).

조건을 바꾸는 교체이므로 ``upgrade``는 ``replace_trigger``다 — 지운 뒤 그 이름이 남아 있으면
멈춘다(``#1373`` · ``db/trigger_ddl.py`` · ``066``·``050`` 선례). 이름·시점(``BEFORE INSERT``·
``BEFORE UPDATE``)·개수(6)는 그대로라 ``DB_SCHEMA §7.4`` 합계 176은 바뀌지 않는다.

운영 행에 대한 영향
-------------------
트리거는 ``BEFORE INSERT``·``BEFORE UPDATE``라 **기존 행은 다시 검사되지 않는다** — 저장된
행이 새 조건에 걸릴 일이 없다. 교체는 트리거마다 DROP 뒤 CREATE이고 그 틈에 들어오는 쓰기는
검사 없이 통과하는데, 세 표에 쓰는 경로는 관리자 적재(``POST /parameters/import``)와 seed
뿐이라 그 틈에 활성 행 둘이 생길 경합은 없다(``066``의 교체도 같은 틈을 가졌다).

downgrade
---------
``054``의 조건으로 되돌린다. 데이터를 한 행도 바꾸지 않으므로(구조만 되돌림)
``migration_guard``의 세 분류 어디에도 넣지 않는다 — ``066``·``050``과 같은 판단. 되돌린 뒤에는
이행 행 INSERT·UPDATE가 다시 거부되지만 **이미 들어간 이행 행은 그대로 남는다**(다시 검사되지
않으므로). 교체는 ``upgrade``와 달리 관용한다 — 없으면 지우지 않고, 중복이라 지우지 못해도
넘어간다(``drop_trigger``). 롤백이 그 자리에서 갇히는 것이 옛 조건이 남는 것보다 나쁘다.
"""

from __future__ import annotations

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, replace_trigger

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None

#: (테이블, 유일성의 키 열) — ``054.ACTIVE_UNIQUE``의 (테이블, 키)와 같아야 한다. 그 리비전이
#: 건 것을 여기서 갈아 끼운다(사본 대조는 ``tests/test_parameter_migrations.py``가 잠근다).
#: ``year``는 CUBRID 예약어라 겹따옴표로 감싼다(``054`` 실측).
ACTIVE_UNIQUE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("regulation_year", ('"year"',)),
    ("cii_reference_line", ("ship_type", "condition_expr")),
    ("cii_rating_boundary", ("ship_type", "condition_expr")),
)

_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")


def _trigger_name(table: str, event: str) -> str:
    """``054._trigger_name``과 같다 — 이벤트 접두사는 앞 세 글자."""
    return f"trg_{table}_active_unique_{event.lower()[:3]}"


def _exists(table: str, keys: tuple[str, ...]) -> str:
    """같은 키의 **다른** 활성 행이 있는가 — ``054._condition``과 같다."""
    joined = " AND ".join(f"{key} = new.{key}" for key in keys)
    return f"EXISTS (SELECT 1 FROM {table} WHERE {joined} AND is_active = 1 AND id <> new.id)"


def _body(table: str, keys: tuple[str, ...], event: str, *, allow_inactive: bool) -> str:
    if allow_inactive:
        condition = f"NOT (new.is_active = 0 OR NOT {_exists(table, keys)})"
    else:
        condition = _exists(table, keys)
    return f"BEFORE {event} ON {table} IF {condition} EXECUTE REJECT"


def upgrade() -> None:
    """지우고 비활성 행을 통과시키는 조건으로 다시 만든다 — **지우지 못했으면 멈춘다**."""
    for table, keys in ACTIVE_UNIQUE:
        for event in _EVENTS:
            replace_trigger(
                op, _trigger_name(table, event), _body(table, keys, event, allow_inactive=True)
            )


def downgrade() -> None:
    """``054``의 조건(비활성 행도 거부)으로 되돌린다 — 데이터는 한 행도 바꾸지 않는다."""
    for table, keys in ACTIVE_UNIQUE:
        for event in _EVENTS:
            name = _trigger_name(table, event)
            drop_trigger(op, name)
            create_trigger(op, name, _body(table, keys, event, allow_inactive=False))
