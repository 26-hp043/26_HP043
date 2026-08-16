"""app_user를 자체 ID/PW 인증으로 전환 (#414)

Revision ID: 033
Revises: 032
Create Date: 2026-08-17

`PRD §20 O-14` · `DB_SCHEMA §2.15`(#413 개정) 기준. 구글 OIDC를 제거하고 제품이
이메일·비밀번호를 직접 관리한다.

바꾸는 것
---------
- ``google_sub`` 삭제 · ``idx_app_user_google_sub`` 삭제
- ``password_hash`` VARCHAR(255) NOT NULL 추가
- ``email_verified_at`` TIMESTAMPTZ NULL 추가
- ``idx_app_user_email``을 **UNIQUE로 재생성** — 자체 인증에서 이메일이 로그인 ID다

기존 행을 삭제한다
------------------
``password_hash``가 NOT NULL인데 구글로 만들어진 기존 행에는 비밀번호가 없다.
실사용자가 없는 개발 단계이고 ``app_user``의 실제 행은 dev-login 스텁 계정뿐이므로
**삭제**를 택했다. 임시 해시를 넣고 강제 재설정을 거는 것은 실사용자가 있을 때의
정공법이며 지금은 과잉이다.

⚠️ **``downgrade()``는 삭제한 행을 복원하지 못한다.** 컬럼과 인덱스는 되돌리지만
사용자 데이터는 되돌아오지 않는다. dev-login은 스텁 계정을 고정 UUID로 다시 만들기
때문에(``auth_dev.py``) 개발 환경에서는 문제가 되지 않는다.

``src/`` 상수를 import하지 않는다
---------------------------------
017(#83)이 세우고 031·032가 따른 원칙이다 — 마이그레이션은 과거 한 시점의
스냅샷이며, ``src/``를 참조하면 그 상수가 바뀔 때 이 마이그레이션의 동작이 소급
변경된다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "033"
down_revision: str | Sequence[str] | None = "032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 세션은 app_user를 FK CASCADE로 참조한다. 사용자를 지우면 세션도 함께
    # 사라지므로 별도 정리가 필요 없다.
    op.execute("DELETE FROM app_user")

    op.drop_index("idx_app_user_google_sub", table_name="app_user")
    op.drop_column("app_user", "google_sub")

    # NOT NULL 컬럼을 빈 테이블에 추가하므로 server_default가 필요 없다.
    op.add_column(
        "app_user",
        sa.Column("password_hash", sa.String(length=255), nullable=False),
    )
    op.add_column(
        "app_user",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # email을 유일 키로 승격한다. partial(WHERE is_deleted = false)이라
    # soft delete된 계정과 같은 이메일로 다시 가입할 수 있다.
    op.drop_index("idx_app_user_email", table_name="app_user")
    op.create_index(
        "idx_app_user_email",
        "app_user",
        ["email"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    """컬럼·인덱스를 되돌린다. **사용자 행은 복원되지 않는다.**

    ``upgrade``와 대칭으로 **행을 먼저 지운다.** ``google_sub``는 NOT NULL인데
    033 이후에 만들어진 계정에는 그 값이 없다 — 되돌릴 때 채워 넣을 근거가 없으므로
    임의 값을 만들어 넣지 않는다.

    이 대칭을 처음에 빠뜨려 ``NotNullViolationError``가 났다. 「upgrade 시점에는
    테이블이 비어 있다」는 전제를 downgrade에도 적용한 것이 원인이며, downgrade는
    **계정이 쌓인 뒤에** 실행된다.
    """
    op.execute("DELETE FROM app_user")

    op.drop_index("idx_app_user_email", table_name="app_user")
    op.create_index(
        "idx_app_user_email",
        "app_user",
        ["email"],
        postgresql_where=sa.text("is_deleted = false"),
    )

    op.drop_column("app_user", "email_verified_at")
    op.drop_column("app_user", "password_hash")

    # google_sub은 NOT NULL이었다. 되돌린 뒤 기존 행이 없으므로(upgrade에서 삭제)
    # server_default 없이 추가해도 안전하다.
    op.add_column(
        "app_user",
        sa.Column("google_sub", sa.String(length=255), nullable=False),
    )
    op.create_index(
        "idx_app_user_google_sub",
        "app_user",
        ["google_sub"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
