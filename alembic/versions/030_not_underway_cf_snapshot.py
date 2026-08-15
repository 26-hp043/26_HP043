"""not under way 연료의 CF 스냅샷

Revision ID: 030
Revises: 029
Create Date: 2026-08-15

이슈 #378 · ``not_underway_fuel_use``에 ``cf_used``를 추가해, CF가 개정돼도 과거
실적의 CII가 변하지 않게 한다.

지금은 두 연료 갈래의 CF 출처가 다르다
--------------------------------------
``#353`` YTD 집계는 두 테이블에서 연료를 읽는데 CF 경로가 서로 다르다.

===========================  ===================================================
테이블                        CF 출처
===========================  ===================================================
``voyage_fuel_use``          ``cf_used`` 컬럼 (NOT NULL) — 계산 시점 snapshot
``not_underway_fuel_use``    없음 → ``fuel_type.cf`` **현재값**을 조회
===========================  ===================================================

``voyage_fuel_use``는 마이그레이션 006에서 만들어질 때부터 스냅샷 컬럼을 갖고
있었고(``DB_SCHEMA`` §2.3), ``#345``의 DDL이 그것을 따라가지 않았다.

그대로 두면 무슨 일이 생기는가
------------------------------
``PRD`` §8.4는 *"연료 CF 변경: 변경 이후 계산에만 적용. 과거 계산은 snapshot 보존"*
을 규정한다. 지금 구조에서는 CF가 개정되면 **같은 연도·같은 선박 안에서 항차 연료는
옛 CF로, not under way 연료는 새 CF로** 계산된다. snapshot 보존이 절반만 적용되어,
개정 전에 본 YTD와 개정 후 다시 조회한 YTD가 **같은 실적인데 다른 값**을 낸다.

``fuel_type``에 ``version``·``effective_from``이 있다는 것 자체가 개정을 전제한
설계라는 뜻이다.

왜 「둘 다 현재값」으로 통일하지 않는가
--------------------------------------
``fuel_type.cf`` 현재값으로 통일하면 두 갈래가 항상 일치하지만 ``cf_used``의 존재
이유를 무시하고 ``PRD`` §8.4를 정면으로 위반한다. 기능①(``voyage_cii``)의 계산
근거와도 어긋난다. **맞추는 방향은 스냅샷 쪽이다.**

백필이 무손실인 근거
--------------------
``fuel_type``은 ``code``가 PK인 단일 행 테이블이라 CF **이력**을 따로 보관하지
않는다. 즉 현재 `cf`가 곧 기록 시점의 값이며, 아직 CF 개정이 일어난 적이 없다.
따라서 현재값으로 채우는 백필은 무손실이다. 이 조건은 착수 전에 확인했다.

NOT NULL로 두는 이유는 ``voyage_fuel_use.cf_used``와 같다 — NULL을 허용하면 집계
때마다 「snapshot 있음/없음」 분기가 생기고, 그 분기가 곧 지금 고치려는 이중 경로다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "030"
down_revision: str | Sequence[str] | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 백필 전에는 NULL을 허용해야 한다 — 기존 행에 채울 값이 아직 없다.
    op.add_column(
        "not_underway_fuel_use",
        sa.Column("cf_used", sa.Numeric(precision=10, scale=6), nullable=True),
    )
    # 기존 행 백필. fuel_type FK가 NO ACTION이라 참조 무결성이 보장되므로
    # 매칭되지 않는 행은 없다.
    op.execute(
        """
        UPDATE not_underway_fuel_use nufu
           SET cf_used = ft.cf
          FROM fuel_type ft
         WHERE ft.code = nufu.fuel_type
           AND nufu.cf_used IS NULL;
        """
    )
    op.alter_column("not_underway_fuel_use", "cf_used", nullable=False)
    # voyage_fuel_use.cf_used와 같은 이유 — CF는 물리적으로 항상 양수다(#96 선례).
    op.execute(
        "ALTER TABLE not_underway_fuel_use "
        "ADD CONSTRAINT chk_nufu_cf_used_positive CHECK (cf_used > 0);"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE not_underway_fuel_use DROP CONSTRAINT IF EXISTS chk_nufu_cf_used_positive;"
    )
    op.drop_column("not_underway_fuel_use", "cf_used")
