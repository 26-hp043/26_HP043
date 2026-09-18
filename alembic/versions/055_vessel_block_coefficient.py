"""vessel.block_coefficient — 기상 보정 선형 계수(CB)의 저장 칸 (#966)

Revision ID: 055
Revises: 054
Create Date: 2026-09-18

왜 필요한가
-----------
Townsin–Kwon 기상 보정의 선형 계수(CB)는 **선박 제원**이다(``TECH_SPEC §3.4``).
그런데 ``vessel``에 칸이 없어 모든 실행이 선종 기본값(``calc/weather.py``의
``DEFAULT_CB``)으로 계산됐고 ``CB_ESTIMATED`` 경고가 100% 켜졌다 — 항상 붙는
경고는 경고가 아니다.

**선택 입력**이다(결정요청 v9 회신 D-3 「가」). 넣으면 실측값, 안 넣으면 지금처럼
선종 기본값 + ``CB_ESTIMATED``.

값 범위는 물리 범위다 — 방형계수는 양수이고 1을 넘지 않는다(체적 비율).
집행은 046 패턴의 트리거가 한다(CUBRID는 CHECK를 보관조차 하지 않는다 · §7.4).
"""

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None

_TABLE = "vessel"
_COLUMN = "block_coefficient"

#: 046의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자.
_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")

_CONDITION = f"new.{_COLUMN} IS NULL OR (new.{_COLUMN} > 0 AND new.{_COLUMN} <= 1)"


def _trigger_name(event: str) -> str:
    return f"trg_chk_block_coefficient_{event.lower()[:3]}"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} NUMERIC(4,3)")
    for event in _EVENTS:
        op.execute(
            f"CREATE TRIGGER {_trigger_name(event)} "
            f"BEFORE {event} ON {_TABLE} "
            f"IF NOT ({_CONDITION}) EXECUTE REJECT"
        )


def downgrade() -> None:
    """건 것만 되돌린다 — 데이터는 한 행도 바꾸지 않는다(구조만 REGENERABLE)."""
    for event in _EVENTS:
        op.execute(f"DROP TRIGGER {_trigger_name(event)}")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {_COLUMN}")
