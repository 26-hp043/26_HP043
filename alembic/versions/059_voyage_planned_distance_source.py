"""voyage.planned_distance_source — 계획 거리가 좌표 추정인지 직접 입력인지 (#1256)

Revision ID: 059
Revises: 058
Create Date: 2026-09-20

왜 필요한가
-----------
``PRD §15.2``는 대권거리를 「좌표 기반 추정 거리」라고 **표시하라**고 정한다. 값이 만들어지는
순간(입력 칸 · 결과 화면)에는 지켜지는데(#1052 ⓷), **저장된 항차에는 그 사실이 남지 않았다** —
``voyage``에 거리 출처 컬럼이 없어 화면의 ``estimated`` 상태가 저장과 함께 사라졌다.
``PRD §15.2``가 「저장 뒤에도 밝히려면 스키마 개정이 선행된다」고 미뤄 둔 자리가 이 컬럼이다.

값은 둘이면 충분하다 —

.. code-block:: text

    USER_INPUT           사용자가 직접 넣은 값(화면 입력 · CSV 가져오기)
    COORDINATE_ESTIMATE  두 좌표의 대권거리로 채운 값(API_SPEC §3.9)

**``NULL``은 「모른다」다.** 기존 행은 전부 ``NULL``로 남긴다 — 저장된 거리가 두 좌표의
대권거리와 비슷하다고 추정으로 되채우면 **같은 값을 직접 입력한 사람에게도 「추정값입니다」가
붙는다.** ``PRD §0.3``이 금하는 종류의 거짓말이라 backfill을 하지 않는다(이슈 본문).

집행은 트리거다(CUBRID는 CHECK를 보관조차 하지 않는다 · ``DB_SCHEMA §7.4``). 이름 규칙은
``046``·``055``·``058``과 같다. 값 목록을 트리거에 박는 것은 ``044``·``057``(``app_user.role``)과
같은 형태다.

downgrade
---------
건 것만 되돌린다 — 컬럼을 지우면 그 사이 저장된 출처 표시가 사라지지만, 그 상태는 **이
마이그레이션 이전과 같은 「모른다」**라 계산도 등급도 바뀌지 않는다(``migration_guard``
``REGENERABLE`` 항목 참조).
"""

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None

_TABLE = "voyage"
_COLUMN = "planned_distance_source"

#: 046의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자.
_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")

#: `api/schemas/voyage.py`의 `DISTANCE_SOURCES`와 같은 집합이어야 한다 — 갈리면 API가
#: 받은 값을 DB가 REJECT해 500이 된다(`tests/test_voyage_distance_source_db.py`가 대조).
_CONDITION = f"new.{_COLUMN} IS NULL OR new.{_COLUMN} IN ('USER_INPUT', 'COORDINATE_ESTIMATE')"


def _trigger_name(event: str) -> str:
    return f"trg_chk_planned_distance_source_{event.lower()[:3]}"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} VARCHAR(30)")
    # 이미 있으면 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
    for event in _EVENTS:
        create_trigger(
            op,
            _trigger_name(event),
            f"BEFORE {event} ON {_TABLE} IF NOT ({_CONDITION}) EXECUTE REJECT",
        )


def downgrade() -> None:
    """건 것만 되돌린다 — 데이터는 한 행도 바꾸지 않는다(구조만 REGENERABLE).

    없는 것은 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
    """
    for event in _EVENTS:
        drop_trigger(op, _trigger_name(event))
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {_COLUMN}")
