"""not under way 구간의 이동 거리

Revision ID: 028
Revises: 027
Create Date: 2026-08-15

이슈 #353 · ``MEPC.412(84)`` §4.2: CII 분모 ``Dt``에 **not under way 구간의 이동
거리도 들어간다.** 025는 구간과 연료만 기록하고 거리 컬럼이 없어 그 값을 담을 곳이
없었다.

왜 필요한가 — 원문 대조 결과
----------------------------
``MEPC.412(84)``(2026-05-01 채택)가 G1 ``§4.2``를 통째로 교체하며 다음을 명시했다.

    "The supply-based transport work (Ws) is defined as the product of a ship's
    capacity and the total distance travelled **(both under way and not under way)**
    in a given calendar year"

구판 ``MEPC.352(78)`` ``§4.2``에는 이 한정어가 **없었다**(*"the distance travelled
in a given calendar year"*). 한정어가 없어 「under way만」으로 읽었던 것이 본
프로젝트의 종전 전제였고, 개정본 대조로 정정했다.

⚠️ **오차 방향** — 이 거리를 빼면 분모가 과소해져 ``CII = M/W``가 과대해지고
**등급이 실제보다 나쁘게** 표시된다. 정박·묘박은 이동이 0이라 무해하지만
**운하 통과**(수에즈 약 104 nm · 파나마 약 44 nm)·**표류**·**STS**는 거리가 발생한다.

왜 별도 컬럼인가
----------------
``lat``·``lon``은 구간의 **시작 위치 한 점**이라 이동 거리를 유도할 수 없다. 종료
위치를 추가해 대권거리로 계산하는 대안은, 운하 통과처럼 **직선이 아닌 경로**에서
실제 이동 거리와 크게 달라져 쓸 수 없다(수에즈는 굴곡 수로다). DCS가 보고하는 값이
「실제 이동 거리」이므로 그 값을 그대로 받는다.

``NOT NULL DEFAULT 0``인 이유
-----------------------------
대부분의 구간(접안·묘박·드라이독)은 이동이 0이며, 그것이 **정상값**이지 미입력이
아니다. NULL을 허용하면 집계할 때마다 ``COALESCE``가 필요하고, 「모름」과 「0」이
섞여 합계가 조용히 달라진다. 기존 025 행도 전부 0으로 채워진다 — 025 시점에는
이동 거리 개념 자체가 없었으므로 0이 사실에 가장 가깝다.

``027``(``#347`` 대시보드 시드)이 먼저 not under way 샘플 행을 넣으므로, 이 컬럼이
추가될 때 그 행들은 전부 ``0``이 된다. 운하 통과 샘플에 실제 거리를 채우는 것은
``#347`` 후속이며, 입력 경로 자체는 ``#370`` 소관이다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "028"
down_revision: str | Sequence[str] | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "not_underway_period",
        sa.Column(
            "distance_nm",
            sa.Numeric(precision=12, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    # 음수 이동 거리는 없다. voyage.actual_distance_nm과 달리 0이 정상값이므로
    # > 0 이 아니라 >= 0 이다.
    op.execute(
        "ALTER TABLE not_underway_period ADD CONSTRAINT chk_nup_distance_non_negative "
        "CHECK (distance_nm >= 0);"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE not_underway_period DROP CONSTRAINT IF EXISTS chk_nup_distance_non_negative;"
    )
    op.drop_column("not_underway_period", "distance_nm")
