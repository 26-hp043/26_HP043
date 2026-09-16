"""app_user.role — 사무직(OFFICE)·현장직(FIELD) 역할 2종

Revision ID: 044
Revises: 043
Create Date: 2026-09-15

이슈 #672 · ``PRD §5.2`` · ``§7.10`` · ``§20 O-14`` · ``API_SPEC §1.2`` · ``DB_SCHEMA §2.15``.

무엇을 바꾸나
--------------
``app_user``에 ``role`` 열을 더한다. 값은 둘뿐이다.

- ``OFFICE`` 사무직 — 기준값을 정하고 대외 산출물을 만든다(선박 제원 · 연간 시뮬레이션 실행 ·
  시나리오 채택 · 리포트 · 함대 감축 계획 · 계정 역할 지정)
- ``FIELD`` 현장직 — 실적을 넣고 지금 상태를 본다(항차 · 정박 · 위치 · 계산 · 비교)

**기존 행은 전부 ``OFFICE``로 채운다.** 이 마이그레이션이 돌기 전까지는 전원이 전 기능을 쓰고
있었으므로(``API_SPEC §1.2`` 「권한 분리 없음」), 그대로 두어야 아무도 잃지 않는다. 열의
기본값은 ``FIELD``다 — **새로 가입하는 계정**은 현장직으로 시작하고, 사무직은 기존 사무직이
지정한다(``PATCH /auth/users/{id}/role``). 최초 사무직은 ``INITIAL_OFFICE_EMAILS``가 정한다
(``auth/role_bootstrap.py``).

되돌리기
--------
``downgrade``는 열을 지운다. 누가 현장직이었는지가 사라지고, 다시 ``upgrade``하면 **전원이
사무직**이 된다 — 잠기는 쪽이 아니라 열리는 쪽으로 틀리지만, 지정 기록 자체는 되살릴 근거가
없다. ``IRREVERSIBLE``로 분류한다(``db/migration_guard.py``).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("role", sa.String(length=10), server_default="FIELD", nullable=False),
    )
    # CHECK를 걸지 않는다 (`#1058` · `DB_SCHEMA §7.4`). CUBRID는 `ALTER TABLE …
    # ADD CONSTRAINT … CHECK`를 **구문으로 받기만 하고 검사하지 않는다** — 걸어 두면
    # 「적혀 있으니 막힌다」고 읽히는데 실제로는 아무 값이나 들어간다.
    #
    # 대신 트리거로 막는다. `role`은 값 범위가 아니라 **권한**이라 `§7.4`가 애플리케이션
    # 계층에 맡긴 값 범위 CHECK와 성질이 다르다 — 틀린 값이 들어가면 `role == "OFFICE"`가
    # 거짓이 되어 닫히는 쪽으로 틀리지만, 그때는 **사무직이 조용히 현장직이 된다.**
    for event in ("INSERT", "UPDATE"):
        op.execute(
            f"CREATE TRIGGER trg_app_user_role_{event.lower()[:3]} BEFORE {event} ON app_user "
            # `role`은 CUBRID 예약어다 — 인용하지 않으면 `unexpected 'role'`로 선다 (#1058).
            "IF NOT (new.\"role\" IN ('OFFICE', 'FIELD')) EXECUTE REJECT"
        )
    # 지금까지 전원이 전 기능을 쓰고 있었다 — 기존 계정은 전부 사무직으로 둔다(#672).
    # `role`은 CUBRID 예약어라 인용한다 (#1058) — `action`·`timestamp`와 같은 목록이다.
    op.execute("""UPDATE app_user SET "role" = 'OFFICE'""")


def downgrade() -> None:
    # 누가 현장직이었는지가 사라진다 — 프로덕션에서는 막는다 (#819).
    guard_irreversible_downgrade("044")
    for event in ("INSERT", "UPDATE"):
        op.execute(f"DROP TRIGGER trg_app_user_role_{event.lower()[:3]}")
    op.drop_column("app_user", "role")
