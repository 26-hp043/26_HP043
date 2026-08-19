"""데모 선박 합성 IMO를 체크섬 유효 값으로 정합

Revision ID: 036
Revises: 035
Create Date: 2026-08-19

이슈 #525 · 데모 선박 4척 중 **합성 IMO 2척이 체크섬을 만족하지 않았다.**

체크섬 규칙은 앞 6자리에 ``7·6·5·4·3·2``를 곱한 합의 1의 자리가 7번째 자리와
같아야 한다는 것이다.

    0000001  기대 0 / 실제 1  ❌   샘플 벌크선
    0000002  기대 0 / 실제 2  ❌   샘플 로로 여객선
    9448839  기대 9 / 실제 9  ✅   STAR SKIPPER      (실선 · 제원 조사 회신분)
    9633862  기대 2 / 실제 2  ✅   DONGJIN ENDURANCE (실선)

실수가 아니라 **고려 대상이 아니었던 것**이다. ``018``의 주석이 적었듯 합성값의 목적은
「IMO가 실제로 발급하지 않는 대역(0으로 시작)을 써서 **실선과 충돌할 수 없게** 한다」
였고, 그 목적은 지켜졌다.

왜 지금 바꾸는가
----------------
``#510``(선박 관리 화면)에서 IMO 체크섬 검증 도입을 검토했을 때, **지금 넣으면 자체
데모 데이터를 등록할 수 없게 되는 것**이 드러났다. 검증 도입은 ``API_SPEC §2.3``
개정이 선행되는 별개 사안이지만, **데이터를 규격에 맞춰 두는 것은 지금 할 수 있고
미룰수록 쌓인다.**

두 조건은 함께 만족할 수 있다
------------------------------
0으로 시작하면서 체크섬이 맞는 7자리는 **100,000개** 있다. ``0000012``·``0000024``가
「실선 대역 밖」과 「체크섬 유효」를 동시에 만족한다.

왜 상수 교체만으로는 부족한가
------------------------------
``#451``이 데모 seed를 마이그레이션에서 분리한 뒤 적재 경로가
``ON CONFLICT DO NOTHING``이다 — 여러 번 돌려도 행이 늘지 않지만 **덮어쓰지도
않는다**. 지우고 다시 넣는 것도 막힌다. ``calculation_run``은 UPDATE·DELETE가
트리거로 차단된 보존 대상이고(``DB_SCHEMA §7.3``), 그 이력이 참조하는 선박은
``RESTRICT``에 걸려 지워지지 않는다.

**그래서 이미 적재된 DB는 이 마이그레이션이 고친다.**

롤백 영향이 낮은 이유
---------------------
컬럼 추가·삭제가 아니라 **값 UPDATE**이고, ``calculation_run``은 ``vessel_id``(UUID)를
참조하지 IMO 문자열을 참조하지 않는다. **UUID가 바뀌지 않으므로 계산 이력의 무결성을
건드리지 않는다.** ``downgrade()``도 값 되돌리기라 FK 영향이 없다.

``src/`` 상수를 import하지 않는다
---------------------------------
마이그레이션은 과거 한 시점의 스냅샷이다. 상수를 참조하면 값이 바뀔 때 이
마이그레이션의 동작이 **소급 변경**된다(``032``·``035`` 주석과 같은 판단). 값을
여기에 그대로 적는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "036"
down_revision: str | Sequence[str] | None = "035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``(선박 UUID, 종전 IMO, 새 IMO)``.
#:
#: **UUID로 대상을 정한다.** IMO로 찾으면 사용자가 등록한 실선이 우연히 같은 값을
#: 가졌을 때 그 행을 고치게 된다 — 0으로 시작하는 대역이라 가능성은 낮지만,
#: 데모 데이터를 고치는 마이그레이션이 사용자 데이터를 건드릴 여지를 두지 않는다.
_RENUMBER: tuple[tuple[str, str, str], ...] = (
    ("00000000-0000-4000-8000-000000000001", "0000001", "0000012"),
    ("00000000-0000-4000-8000-000000000004", "0000002", "0000024"),
)


def _apply(pairs: tuple[tuple[str, str, str], ...], *, reverse: bool) -> None:
    """``vessel.imo_number``를 바꾼다.

    **종전 값이 그대로일 때만 바꾼다.** 누군가 손으로 고쳐 두었다면 그 의도를 덮지
    않는다 — 조용히 남의 데이터를 바꾸는 것보다 안 바뀌는 편이 낫다.

    데모 데이터가 없는 DB(운영 배포)에서는 대상 행이 없어 **아무 일도 하지 않는다.**
    ``#451``이 데모 적재를 별도 명령으로 분리했으므로 그쪽이 정상 경로다.
    """
    vessel = sa.table(
        "vessel",
        sa.column("id", sa.dialects.postgresql.UUID(as_uuid=False)),
        sa.column("imo_number", sa.String),
    )
    for vessel_id, old, new in pairs:
        source, target = (new, old) if reverse else (old, new)
        op.execute(
            vessel.update()
            .where(sa.column("id") == sa.cast(vessel_id, vessel.c.id.type))
            .where(sa.column("imo_number") == source)
            .values(imo_number=target)
        )


def upgrade() -> None:
    _apply(_RENUMBER, reverse=False)


def downgrade() -> None:
    _apply(_RENUMBER, reverse=True)
