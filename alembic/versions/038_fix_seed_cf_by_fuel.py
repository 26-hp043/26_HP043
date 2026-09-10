"""데모 시드 정박 연료의 cf_used를 연료별 정본 CF로 정정

Revision ID: 038
Revises: 037
Create Date: 2026-09-10

이슈 #797 · **데모 시드가 연료 종류와 무관하게 HFO CF를 찍었다.**

무엇이 문제였나
----------------
``demo_seed``의 정박 연료 적재부가 **행의 ``fuel_type``을 보지 않고** 상수 하나
(``HFO_CF = 3.114000``)를 찍었다. ``SEED_PERIOD_FUELS`` 8건 중 **6건이
``DIESEL_GAS_OIL``**이라, 정본 ``3.206``이어야 할 값이 ``3.114``로 얼어 있었다.

바로 위 항차 연료 적재부는 연료 종류를 함께 찍어 정합했다 — 정박 쪽만 어긋났다.

왜 사소하지 않은가
------------------
**「원문 대조를 마친 CF 표」가 무력화된다.** ``fuel_type`` 8행은 ``MEPC.364(79)``를
출처로 갖고 ``031``이 ``content_hash``까지 적재해 개정을 추적한다. 그런데 계산에
들어가는 것은 그 표가 아니라 **적재 시점에 얼린 스냅샷**이므로, 표를 아무리 정확히
관리해도 데모 값은 틀린 채로 남는다.

스냅샷을 얼리는 설계 자체는 옳다 — ``PRD §8.4``가 요구하고, 규정이 개정돼도 과거
실적이 변하지 않게 한다. **문제는 얼린 값이 처음부터 틀렸다는 것이다.**

왜 마이그레이션인가
--------------------
``demo_seed``는 **멱등이라 기존 행을 덮지 않는다**(``ON CONFLICT DO NOTHING``).
시드 코드를 고쳐도 **이미 적재된 환경의 6행은 그대로 남는다.** 새로 만든 DB만
맞고 기존 DB는 틀린 상태가 되어, 같은 화면이 환경마다 다른 값을 낸다.

왜 시드 행만 건드리는가
------------------------
⚠️ **전체 테이블을 정정하면 안 된다.** ``PRD §8.4``상 **규정 개정 뒤의 과거 실적은
``fuel_type.cf``와 달라도 정상**이다. 그것까지 덮으면 이 마이그레이션이 바로 그
「소급 변경」을 저지르게 된다.

그래서 **시드가 넣은 고정 UUID 8행만** 겨냥한다. 그 행들은 데모 데이터이고 개정
이력이 없으므로 정본과 같아야 한다.

되돌리기
--------
``downgrade``는 **비운다.** 되돌릴 「옛 값」이 틀린 값이고, 그것을 복원하는 것은
데이터를 다시 망가뜨리는 일이다. 스키마 변경이 없어 되돌릴 구조도 없다.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None

#: ``demo_seed.SEED_PERIOD_FUELS``의 고정 id. 값을 여기 복제하지 않고 **범위만** 적는다 —
#: CF 값 자체는 ``fuel_type`` 표에서 읽는다.
_SEED_PERIOD_FUEL_IDS = tuple(f"00000000-0000-4000-8000-0000000003{n:02d}" for n in range(1, 9))


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE not_underway_fuel_use AS u
               SET cf_used = ft.cf
              FROM fuel_type AS ft
             WHERE ft.code = u.fuel_type
               AND u.id = ANY(CAST(:ids AS uuid[]))
               AND u.cf_used <> ft.cf
            """
        ).bindparams(sa.bindparam("ids", value=list(_SEED_PERIOD_FUEL_IDS)))
    )


def downgrade() -> None:
    """되돌리지 않는다 — 옛 값이 틀린 값이다."""
