"""fuel_type CF seed의 content_hash 적재 (CUBRID 전환에서 유실된 031을 되살린다)

Revision ID: 045
Revises: 044
Create Date: 2026-09-16

무엇이 빠져 있었나
------------------
PostgreSQL 시절 ``017``이 ``fuel_type.content_hash`` 8행을 **의도적으로** ``NULL``로
두었고(무엇을 해싱하는지가 정본에 없었다), ``031``이 ``#42``의 규약 확정 뒤 그 값을
채웠다.

CUBRID 전환이 001~042를 ``1c444a5c4819``로 합치면서 **``017``의 동작만 옮기고
``031``을 빠뜨렸다.** 시드 마이그레이션 ``6c7496c4d122``의 주석이 그 자취다 —
「``content_hash``·``effective_from``을 NULL로 두는 이유는 017의 주석 그대로다」.

그 결과 ``fuel_type`` 8행이 전부 ``content_hash IS NULL``로 남았다(로컬 실측:
``SELECT COUNT(*), SUM(CASE WHEN content_hash IS NULL THEN 1 ELSE 0 END)`` → ``8 8``).
``DB_SCHEMA §8.3.1``이 규정한 드리프트 탐지 수단이 **통째로 비어 있었다** —
``version`` 갱신 없이 ``cf``만 UPDATE되는 변화를 잡을 것이 없다.

왜 시드 마이그레이션을 고치지 않는가
------------------------------------
``6c7496c4d122``는 이미 적용된 마이그레이션이다. 거기서 값을 채우면 **새로 만드는
DB만** 맞고 이미 올라간 DB는 ``NULL``로 남는다. ``017 → 031``이 밟은 순서를 그대로
따라 **뒤에 붙인다** — 새 DB와 기존 DB가 같은 상태로 모인다.

값의 출처
---------
``031``의 리터럴을 그대로 옮긴다. 산출 규약은 ``DB_SCHEMA §8.3.1``이고, 재현은
``tests/test_fuel_type_content_hash.py::test_content_hash_matches_live_convention``이
매 실행 검증한다 — 리터럴과 살아 있는 해시 함수가 갈라지면 거기서 잡힌다.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


#: code → content_hash. `031`의 값을 그대로 옮겼다 (`DB_SCHEMA §8.3.1`).
CONTENT_HASHES: tuple[tuple[str, str], ...] = (
    ("DIESEL_GAS_OIL", "sha256:f566fbf2dbd2c09455e2255a598486a71dd870cb5c0b2fb3215626f3b8c80619"),
    ("LFO", "sha256:365ef3f51386c92e1d429ae9a36d8cb7b9dd9a2f78169c0a1fc727979f3d3486"),
    ("HFO", "sha256:fa0bb45993735ee22cde1b56c3af2e08da30b0237a025d33fd9e4041e564d597"),
    ("LPG_PROPANE", "sha256:994d7200fa00fa90329701792332cd310eb36877d2a3ccac223bded044e600ba"),
    ("LPG_BUTANE", "sha256:097f3bdefe24d80925f5f7895cba945fd9af6fbddbfaa9cf3a56878e46ddcb56"),
    ("LNG", "sha256:3315f260ec4b5019570f15c85e9516cd95c9aab0fb7c6f6c27d2c2e99eeb664d"),
    ("METHANOL", "sha256:9ddc014067877aa2c60ac26c1f97023a424b64ca08e9e2402910e70acc6a4e9a"),
    ("ETHANOL", "sha256:4a302f370c4ad2d82f1e69609978e16d894ea85a7c2d796a48eee010c73127a5"),
)

# 경량 테이블 선언 — 실제 컬럼 정의는 `1c444a5c4819`가 소유한다(시드와 같은 방식).
_fuel_type = sa.table(
    "fuel_type",
    sa.column("code", sa.String),
    sa.column("content_hash", sa.String),
)


def upgrade() -> None:
    """8행의 ``content_hash``를 채운다.

    ``code``로 한정한 UPDATE 8회다. 시드가 넣은 행만 대상이며, 운영 중 추가된 행이
    있어도 건드리지 않는다 — 그 행들의 해시는 삽입 주체가 채울 몫이다.
    """
    for code, content_hash in CONTENT_HASHES:
        op.execute(
            _fuel_type.update()
            .where(_fuel_type.c.code == op.inline_literal(code))
            .values(content_hash=op.inline_literal(content_hash))
        )


def downgrade() -> None:
    """시드 직후 상태(``content_hash IS NULL``)로 되돌린다.

    ``code``를 이 마이그레이션이 채운 8종으로 한정한다. 무조건
    ``SET content_hash = NULL``로 쓸면 운영 중 다른 경로로 채워진 행의 값까지
    지운다 — downgrade는 자기가 한 일만 되돌려야 한다.

    ``guard_irreversible_downgrade``를 부르지 않는다. 다시 upgrade하면 같은 값이
    돌아오므로 되돌릴 수 없는 손실이 아니다 — ``migration_guard``의 ``REGENERABLE``에
    등록한다.
    """
    codes = [code for code, _ in CONTENT_HASHES]
    op.execute(_fuel_type.update().where(_fuel_type.c.code.in_(codes)).values(content_hash=None))
