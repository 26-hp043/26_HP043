"""app_user.role — 관리자(ADMIN)를 값에 더한다

Revision ID: 057
Revises: 056
Create Date: 2026-09-19

`044`가 `role`을 만들며 값을 **두 개로 못 박았다.** 그 제약은 CHECK가 아니라 트리거
(`trg_app_user_role_ins`·`_upd`)에 있다 — CUBRID가 `ADD CONSTRAINT … CHECK`를 구문으로
받기만 하고 검사하지 않아 `#1058`이 옮긴 자리다.

그래서 `ADMIN`은 **애플리케이션을 고치는 것만으로는 DB에 들어가지 않는다.** 이 마이그레이션이
없으면 `PATCH /auth/users/{id}/role`이 `ADMIN`을 쓰는 순간 트리거가 REJECT하고, 화면에는
역할 변경 실패로만 보인다. 열도 값도 그대로 두고 **트리거 두 개만 다시 만든다.**

## downgrade가 데이터를 바꾼다

옛 트리거는 `ADMIN`을 거부하므로, 트리거를 되돌리기 **전에** 관리자를 내려야 한다. 내리는
곳은 현장직이 아니라 **사무직**이다 — `ADMIN`은 `OFFICE`의 상위집합이라(`#1301`) 사무직으로
내리는 것이 그 계정이 하던 일 중 「계정 관리」만 잃는 최소 변경이다. 현장직으로 내리면 업무
13경로까지 함께 닫혀, 되돌림이 **의도보다 넓게** 작동한다.

누가 관리자였는지는 그 순간 사라지고 다시 `upgrade`해도 돌아오지 않는다 — `044`가
「누가 현장직이었는지」에 대해 가진 것과 같은 성질이라 `IRREVERSIBLE`에 같이 둔다
(`db/migration_guard.py`). 잠기지는 않는다: `INITIAL_ADMIN_EMAILS`에 든 계정은 다음
로그인에서 다시 관리자가 된다.
"""

from __future__ import annotations

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, replace_trigger

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None

#: 트리거 이름은 `044`가 정한 것을 그대로 쓴다 — 이름이 갈리면 `044`의 downgrade가
#: 없는 트리거를 지우려다 선다.
_EVENTS = ("INSERT", "UPDATE")


def _recreate(values: str, *, strict: bool) -> None:
    """두 트리거를 `values`로 다시 만든다.

    `CREATE OR REPLACE TRIGGER`를 쓰지 않는다 — CUBRID에 그 구문이 없다. 지우고 만드는
    사이에 다른 연결이 쓰면 검사 없이 지나가지만, 마이그레이션은 배포 절차 안에서 단독으로
    돈다(`docs/OPERATIONS.md §3.3`).

    트리거 DDL은 `db/trigger_ddl.py`를 지난다 (`#1373`). 중복 상태(같은 이름이 둘 이상)에서는
    이름으로 지울 수 없어 옛 값 목록이 남는데, 그때의 처리가 방향마다 다르다 —
    `strict`(upgrade)는 **멈춘다**(`replace_trigger` — `ADMIN`을 받지 못하는 트리거를 남긴 채
    배포가 성공으로 끝나면 안 된다), downgrade는 **관용한다**(롤백이 갇히지 않게 · `D-20`).
    """
    for event in _EVENTS:
        name = f"trg_app_user_role_{event.lower()[:3]}"
        body = (
            f"BEFORE {event} ON app_user "
            # `role`은 CUBRID 예약어다 — 인용하지 않으면 `unexpected 'role'`로 선다 (#1058).
            f'IF NOT (new."role" IN ({values})) EXECUTE REJECT'
        )
        if strict:
            replace_trigger(op, name, body)
        else:
            drop_trigger(op, name)
            create_trigger(op, name, body)


def upgrade() -> None:
    _recreate("'OFFICE', 'FIELD', 'ADMIN'", strict=True)


def downgrade() -> None:
    # 관리자를 사무직으로 내리기 전에 끊는다 — 무엇이든 바꾸기 전이어야 한다 (#819).
    guard_irreversible_downgrade("057")
    # 순서 — **값을 먼저 맞추고(ADMIN → OFFICE) 그 다음 트리거를 좁힌다.** 이 UPDATE는
    # 새 값이 'OFFICE'라 어느 순서로 해도 트리거를 통과하지만(트리거는 새 값만 본다),
    # 좁힌 뒤에 남은 'ADMIN' 행이 있으면 그 행을 건드리는 이후의 모든 UPDATE가 거부된다.
    # 「맞추는 일」을 먼저 끝내 두면 좁힌 순간 표 안에 규칙 밖 값이 없다.
    op.execute("""UPDATE app_user SET "role" = 'OFFICE' WHERE "role" = 'ADMIN'""")
    _recreate("'OFFICE', 'FIELD'", strict=False)
