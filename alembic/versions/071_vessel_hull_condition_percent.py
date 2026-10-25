"""vessel.hull_condition_percent — 선체·추진 상태 보정(%)의 저장 칸 (#2561)

Revision ID: 071
Revises: 070
Create Date: 2026-10-25

왜 필요한가
-----------
항로 비교의 연료 추정(``PRD §11.4.1`` cubic speed model)은 선체가 깨끗한 배를 전제한다.
실제 배는 파울링으로 같은 속력에 연료를 더 쓰고(+), 선체 청소·프로펠러 연마·절감장치로
덜 쓴다(−) — SEEMP(``MEPC.395(82)``) 5.3.10~5.3.13. 그 차이를 선사가 자기 배의 성능
감시로 아는 **%로 직접 넣는다**(#2561 결정 D2 「가」). 오손 등급에서 %로 가는 권위 있는
식은 없다 — 등급을 고르면 %를 채우는 방식은 하지 않는다.

**선택 입력**이다. ``NULL``은 「미입력」이고 계산은 0%로 한다 — 0을 넣은 것과 결과는
같지만 화면은 둘을 구분해 보인다.

값 범위는 도메인 범위다(−30 ~ +100 · ``validation/bounds.py`` ``HULL_CONDITION_PERCENT``).
집행은 055 패턴의 트리거가 한다(CUBRID는 CHECK를 보관조차 하지 않는다 · §7.4). 트리거는
공용 ``db/trigger_ddl.py``를 지난다 — 있으면 만들지 않고 없으면 지우지 않는다(`#1373`).

사전 검사가 없는 이유 — 062와 달리 **열을 이 리비전이 만든다.** 만든 직후의 값은 전부
``NULL``이라 트리거가 막을 기존 행이 있을 수 없다.
"""

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, existing_triggers

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None

_TABLE = "vessel"
_COLUMN = "hull_condition_percent"

#: 046의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자.
_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")

_CONDITION = f"new.{_COLUMN} IS NULL OR (new.{_COLUMN} >= -30 AND new.{_COLUMN} <= 100)"


def _trigger_name(event: str) -> str:
    return f"trg_chk_hull_condition_{event.lower()[:3]}"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} NUMERIC(5,2)")
    # 이미 있으면 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
    have = existing_triggers(op)
    for event in _EVENTS:
        create_trigger(
            op,
            _trigger_name(event),
            f"BEFORE {event} ON {_TABLE} IF NOT ({_CONDITION}) EXECUTE REJECT",
            existing=have,
        )


def downgrade() -> None:
    """건 것만 되돌린다 — 데이터는 한 행도 바꾸지 않는다(구조만 REGENERABLE).

    없는 것은 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
    """
    have = existing_triggers(op)
    for event in _EVENTS:
        drop_trigger(op, _trigger_name(event), existing=have)
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {_COLUMN}")
