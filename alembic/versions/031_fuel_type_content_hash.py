"""fuel_type CF seed의 content_hash 적재

Revision ID: 031
Revises: 030
Create Date: 2026-08-15

이슈 #154 · 마이그레이션 017이 ``NULL``로 남긴 ``fuel_type.content_hash`` 8행을
채운다.

017은 왜 비워 두었는가
----------------------
017(#83 · PR #147)은 이 컬럼을 **의도적으로** ``NULL``로 두고 사유를 주석에 남겼다 —
"무엇을 해싱하는가"(행 단위 vs 8행 집합, canonical JSON 규칙)가 정본에 없었고, 그
규칙을 정하는 것은 ``#42``였다. 규칙을 임의 선점하면 ``AGENTS.md`` §3 위반이므로
보류했다. **누락이 아니다.**

``#42``(PR #131)가 ``src/cii_platform/calc/hash.py``에 규약을 확정하면서 선행
조건이 해소됐다.

무엇을 해싱하는가 — 행 단위, ``{code, cf}``
-------------------------------------------
``DB_SCHEMA`` §8.3.1에 확정 내용을 기록했다. 요지는 둘이다.

**⑴ 행 단위다.** 컬럼이 행마다 있으므로 집합 해시면 8행이 같은 값을 갖는다(같은 값의
8중 중복). ``§2.9``가 ``effective_from``을 「OTHER 연료용」으로 정의해 9번째 행이
추가될 수 있는데, 집합 해시라면 그때 기존 8행을 전부 다시 써야 한다. 세트 전체의
추적은 ``calculation_run.parameter_hash``가 이미 한다(``TECH_SPEC`` §5.2) — 여기까지
집합이면 같은 일을 두 곳에서 한다. 행 단위여야 **어느 행이 바뀌었는지**를 짚을 수
있고, ``version`` 갱신 없이 ``cf``만 UPDATE되는 드리프트가 이 컬럼이 잡을 대상이다.

**⑵ 대상 필드는 ``{code, cf}``다.** ``TECH_SPEC`` §5.2.1이 ``parameters_used``의
``fuel_types[]`` 원소를 이미 그렇게 규정하고 있다. 여기서 다른 필드 집합을 쓰면 같은
엔티티에 canonical 규약이 두 벌 생긴다(``hash.py``의 ``compute_scenario_input_hash``
주석이 경계하는 상황). 같은 집합을 쓰면 과거 ``calculation_run``이 쓴 CF가 현재 행과
같은지를 해시로 대조할 수 있다.

제외: ``display_name``·``unit``(표시·고정 기본값이지 규제값이 아님) ·
``id``·``created_at``·``updated_at``(운영 메타) · ``is_active``(운영 상태) ·
``version``(내용이 아니라 내용 세트의 라벨. §8.3이 둘을 나란히 두므로 서로를 포함하면
순환이다).

왜 값을 리터럴로 박는가
-----------------------
017이 세운 원칙을 지킨다 — **마이그레이션은 ``src/`` 상수를 import하지 않는다**
(PR #147 구현 결정 2). 마이그레이션은 과거 한 시점의 스냅샷이라 가변 상수를 참조하면
과거 동작이 소급 변경된다.

대신 ``tests/test_fuel_type_content_hash.py``가 **``src/``의 살아 있는 규약으로
재계산해 DB 값과 대조**한다. 두 경로가 독립적이므로 그 대조가 실질적인 검증이 된다 —
누군가 ``canonical_json``을 바꾸면 테스트가 깨져 드리프트가 드러난다.

산출 레시피 (재현용)
--------------------
.. code-block:: python

    from decimal import Decimal
    from cii_platform.calc.hash import compute_parameter_hash
    compute_parameter_hash({"code": "HFO", "cf": Decimal("3.114000")})
    # canonical_json → '{"cf":"3.114","code":"HFO"}'
    # → 'sha256:fa0bb459...'

``LPG_PROPANE``의 canonical이 ``{"cf":"3",...}``인 것은 ``3.000000``을
``normalize()``가 정수로 펴기 때문이며 ``TECH_SPEC`` §5.1.2 ``[ORACLE-C-2]``가 정한
동작이다 — 같은 값이 표기에 따라 다른 해시를 내지 않게 하는 것이 그 규칙의 목적이다.

``version``은 건드리지 않는다
-----------------------------
``§8.3``은 CF 값이 **바뀔 때** ``version``과 ``content_hash``를 함께 갱신하도록
규정한다. 이번 작업은 CF 값을 바꾸지 않고 비어 있던 추적 컬럼만 채우므로 ``version``은
``'1.0'`` 그대로 둔다.
"""

import sqlalchemy as sa

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


# code → content_hash. 위 「산출 레시피」로 재현할 수 있으며, 그 재현을
# tests/test_fuel_type_content_hash.py가 매 실행 검증한다.
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

# 경량 테이블 선언 — 실제 컬럼 정의는 002가 소유한다(017과 같은 방식).
_fuel_type = sa.table(
    "fuel_type",
    sa.column("code", sa.String),
    sa.column("content_hash", sa.String),
)


def upgrade() -> None:
    """8행의 ``content_hash``를 채운다.

    ``code``로 한정한 UPDATE 8회다. 017이 넣은 행만 대상이며, 운영 중 추가된 행이
    있어도 건드리지 않는다 — 그 행들의 해시는 삽입 주체가 채울 몫이다.
    """
    for code, content_hash in CONTENT_HASHES:
        op.execute(
            _fuel_type.update()
            .where(_fuel_type.c.code == op.inline_literal(code))
            .values(content_hash=op.inline_literal(content_hash))
        )


def downgrade() -> None:
    """017 직후 상태(``content_hash IS NULL``)로 되돌린다.

    ``code``를 이 마이그레이션이 채운 8종으로 한정한다. 무조건
    ``SET content_hash = NULL``로 쓸면 운영 중 다른 경로로 채워진 행의 값까지
    지운다 — downgrade는 자기가 한 일만 되돌려야 한다.
    """
    codes = [code for code, _ in CONTENT_HASHES]
    op.execute(_fuel_type.update().where(_fuel_type.c.code.in_(codes)).values(content_hash=None))
