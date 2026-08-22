"""시뮬레이션 스냅샷에 선박 제원 사본 추가

Revision ID: 037
Revises: 036
Create Date: 2026-08-23

이슈 #493 · **스냅샷에 선박 제원이 없어 재현이 완전하지 않다.**

무엇이 문제였나
----------------
``simulation_snapshot``은 항차만 담았고, 계산에 쓰는 **선박 제원은 살아 있는
``vessel`` 행에서 읽었다.** 그래서 제원을 고치면 **같은 스냅샷·같은 seed로도 결과가
달라진다.**

    reference_speed_kn · reference_daily_foc_ton  → 잔여 계획 항차의 속도–연료 관계
    deadweight · gross_tonnage · ship_type        → CII 분모(transport_capacity)

``input_hash``는 항차만 덮으므로 그 변화가 해시에 드러나지 않는다. 결과적으로
``POST /annual-simulations/{id}/reproduce``가 **해시 검사를 통과한 뒤 값 비교에서
500(REPRODUCIBILITY_ERROR)**을 낸다 — 그 코드는 「엔진·환경이 바뀌었다」는 뜻인데
실제 원인은 **선박 제원 수정**이라 운영자가 잘못된 방향으로 조사하게 된다.

`#493` 본문은 두 필드(``reference_*``)를 들었으나 실측하면 **다섯**이다 —
``_recompute``가 capacity도 살아 있는 행에서 읽는다.

왜 nullable인가
----------------
``simulation_snapshot``은 immutable이다(``trg_snapshot_immutable``). **기존 행에는
값을 넣을 수 없으므로** NOT NULL로 두면 이 마이그레이션 자체가 실패한다.

값이 없는 행은 재현 경로가 **명확한 사유로 끊는다** — `#443` 이전 실행을
``_stored_payload``가 404로 끊는 것과 같은 선례다. 「관리자에게 문의」라는 오진
대신 「제원을 스냅샷하기 전 실행이라 재현할 수 없다」를 말한다.

같은 종류를 이미 한 번 고쳤다
------------------------------
`#378`이 ``voyage_fuel_use``에 CF 스냅샷을 넣은 것과 같은 문제·같은 해법이다 —
계산에 쓴 값을 나중에 물을 수 있어야 한다(``TECH_SPEC §5.4``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "037"
down_revision: str | Sequence[str] | None = "036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "simulation_snapshot",
        sa.Column("vessel_json", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("simulation_snapshot", "vessel_json")
