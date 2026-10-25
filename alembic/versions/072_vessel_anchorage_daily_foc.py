"""vessel.anchorage_daily_foc_ton — 묘박 중 일일 연료의 저장 칸 (#2561)

Revision ID: 072
Revises: 071
Create Date: 2026-10-26

왜 필요한가
-----------
항로 비교에 선석 가용 시각을 넣으면, 선석보다 일찍 닿는 시나리오는 묘박하며 기다린다
(#2561 결정 D8 「다」). 그 대기 연료를 내려면 **묘박 중 하루에 태우는 연료**가 필요하다.
묘박 중에는 주기관을 끄고 발전기·보일러만 돌아 하루 소비가 배마다 거의 일정하다 —
항차마다 넣을 값이 아니라 **배의 성질**이므로 선박 제원에 둔다(결정 D3 「가」). 비교
화면은 이번 비교에만 다른 값을 넣을 수 있다.

비슷해 보이는 정박 구간 기록(``not_underway_fuel_use`` · ``DB_SCHEMA §2.18``)은 **실제로 태운
연료를 사후에 적는 실적**이라 기준값으로 쓸 수 없다.

**선택 입력**이다. ``NULL``은 「미입력」이고, 선석 시각을 넣은 비교에서 대기 시간은 내되
대기 연료와 대기 포함 CII는 「계산 못 함」으로 둔다 — 없는 값을 0으로 지어 넣지 않는다.
기본값을 두지 않는 이유는 대표값의 근거를 찾지 못했기 때문이다(결정요청 v3 §14).

값 범위는 기준 일일 연료와 같은 양이라 같은 자릿수다(``NUMERIC(8,2)`` · ``validation/bounds.py``
``DAILY_FOC``). 집행은 071 패턴의 트리거가 한다(CUBRID는 CHECK를 보관조차 하지 않는다 · §7.4).
트리거는 공용 ``db/trigger_ddl.py``를 지난다 — 있으면 만들지 않고 없으면 지우지 않는다(`#1373`).

사전 검사가 없는 이유 — 071과 같다. **열을 이 리비전이 만든다.** 만든 직후의 값은 전부
``NULL``이라 트리거가 막을 기존 행이 있을 수 없다.
"""

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, existing_triggers

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None

_TABLE = "vessel"
_COLUMN = "anchorage_daily_foc_ton"

#: 046의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자.
_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")

_CONDITION = f"new.{_COLUMN} IS NULL OR new.{_COLUMN} > 0"


def _trigger_name(event: str) -> str:
    return f"trg_chk_anchorage_foc_{event.lower()[:3]}"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} NUMERIC(8,2)")
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
