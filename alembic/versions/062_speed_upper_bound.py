"""속력 저장 칸 네 곳에 물리 상한 60 kn을 건다 (#1269 · 결정 G-10)

Revision ID: 062
Revises: 061
Create Date: 2026-09-25

왜 필요한가
-----------
속력 칸의 상한이 **저장 형식(``NUMERIC(6,2)`` → 9,999.99)**뿐이었다. ``120`` kn이 화면·
서버·DB를 모두 통과해 연료 모델에서 속력 배율 1,000이 됐고, 도착 예정 시각과 연간
시뮬레이션까지 흘러갔다. ``PRD §9.1`` VAL-009가 「1.0 이상 **60 이하**」로 개정되며 이
리비전이 DB 층을 맡는다 — 서버 스키마(``api/schemas/bounds.py`` ``MAX_SPEED_KN``)와
화면 규칙이 같은 값을 쓴다.

60은 현역 페리 세계 최고속 HSC Francisco 58.1 kn(Guinness 「Fastest ferry」)을 막지 않는
가장 좁은 값이다. 이 제품은 고속선(``RO_RO_PASSENGER_HSC``)을 등록받는다.

집행은 046 패턴의 트리거가 한다 — CUBRID는 CHECK를 보관조차 하지 않는다(``DB_SCHEMA §7.4``).
모델의 ``CheckConstraint``(``chk_speed_max`` 등)는 다른 엔진에서의 계약이자 문서다.

사전 검사 — 이미 60을 넘는 행이 있으면 바꾸기 전에 멈춘다
----------------------------------------------------------
``BEFORE UPDATE`` 트리거는 **바뀌지 않은 열도 ``new``로 본다.** 이미 60을 넘는 행이 있으면
그 행의 다른 칸(메모·상태)을 고치는 UPDATE까지 거부되고, 사용자는 원인을 모른 채 저장이
막힌다. 그래서 ``061``과 같이 **아무것도 바꾸기 전에 세고, 있으면 멈춘다.** 문구에는 칸별
행 수만 적는다 — 배포 로그가 공개 저장소의 Actions에 남는다. 소프트 삭제 행도 센다(트리거는
그 행의 UPDATE에도 걸린다).
"""

import sqlalchemy as sa

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, existing_triggers

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

#: ``api/schemas/bounds.py``의 ``MAX_SPEED_KN``과 같아야 한다 — 검사가 대조한다.
MAX_SPEED_KN = 60

#: (제약 이름, 테이블, 열, NULL 허용). 제약 이름은 모델의 ``CheckConstraint`` 이름과 같다.
#: ``voyage``·``vessel``의 하한 CHECK가 같은 이름(``chk_speed_positive``)을 쓰는 탓에 046이
#: 항차 쪽에 ``_voyage``를 붙였듯, 여기서도 트리거가 DB 전역에서 유일하도록 이름을 가른다.
SPEED_COLUMNS: tuple[tuple[str, str, str, bool], ...] = (
    ("chk_speed_max", "vessel", "reference_speed_kn", True),
    ("chk_speed_max_voyage", "voyage", "planned_speed_kn", False),
    ("chk_actual_speed_max", "voyage", "actual_avg_speed_kn", True),
    ("chk_scenario_speed_max", "voyage_scenario", "speed_kn", False),
)

_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")


def trigger_name(check_name: str, event: str) -> str:
    """046의 이름 규칙과 같다 — ``chk_speed_max`` + ``INSERT`` → ``trg_chk_speed_max_ins``."""
    return f"trg_{check_name}_{event.lower()[:3]}"


def condition(column: str, nullable: bool) -> str:
    """트리거 조건. NULL 허용 칸은 NULL을 통과시킨다(046 docstring — CHECK와 같은 의미)."""
    bound = f"new.{column} <= {MAX_SPEED_KN}"
    return f"new.{column} IS NULL OR {bound}" if nullable else bound


class SpeedAboveLimitError(RuntimeError):
    """이미 60 kn을 넘는 행이 있어 ``062``를 적용하지 않았다 — DB는 그대로다."""


def above_limit_message(counts: dict[str, int]) -> str:
    """사전 검사가 멈출 때의 문구. ``counts``는 ``{"voyage.planned_speed_kn": 2, …}`` 형태.

    **값과 행 식별자는 넣지 않는다** — 배포 로그가 공개 저장소에 남는다(``061``과 같다).
    """
    counted = " · ".join(f"{key} {count}행" for key, count in counts.items() if count)
    return (
        f"마이그레이션 062를 적용하지 않았다 — 속력이 {MAX_SPEED_KN} kn을 넘는 행이 있다"
        f"({counted}). DB는 그대로다(트리거를 만들지 않았다). 해당 행의 속력을 화면이나 "
        "SQL로 바로잡은 뒤 `alembic upgrade head`를 다시 돌린다(docs/OPERATIONS.md §3.6.5)."
    )


def _count_above(table: str, column: str) -> int:
    return int(
        op.get_bind()
        .execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} > {MAX_SPEED_KN}"))
        .scalar_one()
    )


def upgrade() -> None:
    # 0) 사전 검사 — 아무것도 바꾸기 전에 센다. 하나라도 있으면 멈추고 DB는 그대로다.
    counts = {
        f"{table}.{column}": _count_above(table, column)
        for _name, table, column, _nullable in SPEED_COLUMNS
    }
    if any(counts.values()):
        raise SpeedAboveLimitError(above_limit_message(counts))
    # 1) 트리거 — 이미 있으면 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
    have = existing_triggers(op)
    for check_name, table, column, nullable in SPEED_COLUMNS:
        for event in _EVENTS:
            create_trigger(
                op,
                trigger_name(check_name, event),
                f"BEFORE {event} ON {table} IF NOT ({condition(column, nullable)}) EXECUTE REJECT",
                existing=have,
            )


def downgrade() -> None:
    """건 것만 내린다 — 데이터는 한 행도 바꾸지 않는다(046과 같은 판단).

    없는 것은 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
    """
    have = existing_triggers(op)
    for check_name, _table, _column, _nullable in SPEED_COLUMNS:
        for event in _EVENTS:
            drop_trigger(op, trigger_name(check_name, event), existing=have)
