"""항차 실제 출항·도착 시각과 정박 구간 시작·끝 시각의 출처 열 넷 (#1923)

Revision ID: 064
Revises: 063
Create Date: 2026-09-26

왜 필요한가
-----------
데이터 점검의 「공적 기록과 다름」(``PRD §17.4.4``)에서 사용자가 「이 값으로 채우기」를 누르면
공적 재항 기록의 시각이 항차·정박 구간에 들어간다. 그 값이 **어디서 왔는지**가 행에 남아야
한다 — 사람이 넣은 값과 공적 기록에서 옮긴 값이 같은 칸에 같은 모양으로 있으면 나중에
「이 시각은 누가 정했나」에 답할 수 없다. ``059``의 계획 거리 출처(#1256)와 같은 모양이다 —
**출처는 항차가 아니라 숫자 하나에 붙은 표시**다.

.. code-block:: text

    voyage.actual_departure_source         항차 실제 출항 시각의 출처
    voyage.actual_arrival_source           항차 실제 도착 시각의 출처
    not_underway_period.started_at_source  정박 구간 시작 시각의 출처
    not_underway_period.ended_at_source    정박 구간 끝 시각의 출처

    USER_INPUT     사람이 직접 넣은 값
    PUBLIC_RECORD  공적 재항 기록(``port_call_record``)에서 「이 값으로 채우기」로 옮긴 값

**``NULL``은 「모른다」다.** 기존 행은 전부 ``NULL``로 남기고 backfill하지 않는다 — 저장된
시각이 공적 기록과 같다고 ``PUBLIC_RECORD``로 되채우면 같은 값을 손으로 넣은 사람에게도
「공적 기록에서 채움」이 붙는다(``PRD §0.3``). 사람이 시각을 다시 고치면 서비스가 ``NULL``로
돌린다(``services/voyage.py`` · ``services/not_underway.py`` — ``059``의 규칙 그대로).

집행은 트리거다(CUBRID는 CHECK를 보관조차 하지 않는다 · ``DB_SCHEMA §7.4``). 이름 규칙은
``059``와 같다 — 열마다 ``trg_chk_<열>_ins``·``_upd``.

downgrade
---------
건 것만 되돌린다 — 열을 지우면 그 사이 저장된 출처 표시가 사라지지만, 그 상태는 **이
마이그레이션 이전과 같은 「모른다」**라 계산도 등급도 바뀌지 않는다(``migration_guard``
``REGENERABLE``). 시각 값 자체는 건드리지 않는다.
"""

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None

#: (표, 열) — 출처 열 넷. 값 집합은 넷이 같다.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("voyage", "actual_departure_source"),
    ("voyage", "actual_arrival_source"),
    ("not_underway_period", "started_at_source"),
    ("not_underway_period", "ended_at_source"),
)

#: 046의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자.
_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")

#: `api/schemas/voyage.py`의 `ACTUAL_TIME_SOURCES`와 같은 집합이어야 한다 — 갈리면 API가
#: 받은 값을 DB가 REJECT해 500이 된다(`tests/test_public_record_fill_db.py`가 대조).
_ALLOWED = "('USER_INPUT', 'PUBLIC_RECORD')"


def _trigger_name(column: str, event: str) -> str:
    return f"trg_chk_{column}_{event.lower()[:3]}"


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(30)")
        condition = f"new.{column} IS NULL OR new.{column} IN {_ALLOWED}"
        # 이미 있으면 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
        for event in _EVENTS:
            create_trigger(
                op,
                _trigger_name(column, event),
                f"BEFORE {event} ON {table} IF NOT ({condition}) EXECUTE REJECT",
            )


def downgrade() -> None:
    """건 것만 되돌린다 — 시각 값은 한 행도 바꾸지 않는다(구조만 REGENERABLE).

    없는 것은 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
    """
    for table, column in reversed(_COLUMNS):
        for event in _EVENTS:
            drop_trigger(op, _trigger_name(column, event))
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
