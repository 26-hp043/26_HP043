"""해시 형식 트리거 4개를 ``REGEXP BINARY``로 — 대문자 hex·``SHA256:`` 접두를 막는다 (#2103)

Revision ID: 066
Revises: 065
Create Date: 2026-10-06

무엇이 어긋나 있었나
--------------------
``a7d3e9b14f26``이 ``calculation_run``·``simulation_snapshot``의 ``input_hash``·
``parameter_hash``에 건 트리거 넷은 ``new.{열} REGEXP '^sha256:[0-9a-f]{64}$'``였다.
정본 ``DB_SCHEMA §2.5·§2.7 [S-7]``의 ``~``는 대소문자를 구분하는데 **CUBRID의 ``REGEXP``는
기본이 대소문자 무시**다(``050`` 실측 — ``'FIXED 12' REGEXP '^fixed [0-9]+$'``가 통과).
그래서 ``'SHA256:' || REPEAT('A', 64)``가 네 열 모두 들어갔다 — 2026-10-06 ``cii_test``에서
INSERT 8건이 전부 통과하는 것을 검사로 확인했다(``tests/test_constraint_triggers_db.py``).

왜 막아야 하나
--------------
``calc/hash.py``는 ``hexdigest()``라 **소문자만** 낸다. 대문자가 들어왔다면 그것은 서버
바깥에서 만든 값이고, 재현 대조(``TECH_SPEC §5.4`` — 같은 ``input_hash`` → 같은 결과)에서
같은 입력이 **다른 키**로 갈린다. 두 표는 immutable이라 저장 뒤에는 고칠 수도 없다.

어떻게
------
``050``(``capacity_rule``)·``058``(``call_sign``)이 쓴 ``REGEXP BINARY``를 그대로 쓴다. 조건을
바꾸는 교체이므로 ``upgrade``는 ``replace_trigger``다 — 지운 뒤 그 이름이 남아 있으면 멈춘다
(``#1373`` · ``db/trigger_ddl.py``). 옛 조건을 남긴 채 리비전만 올라가면 안 되기 때문이다.
이름·시점(``BEFORE INSERT``)·개수(4)는 그대로라 ``DB_SCHEMA §7.4`` 합계 176은 바뀌지 않는다.

운영 행에 대한 영향
-------------------
트리거는 ``BEFORE INSERT``뿐이라 **기존 행은 다시 검사되지 않는다.** 두 표는 UPDATE가
막혀 있고(``calculation_run``은 ``needs_recalc`` 플립만 — 해시 열은 건드리지 않는다),
운영에서 해시를 만드는 경로는 전부 ``calc/hash.py``를 지나 소문자만 내므로 거부될 쓰기가
없다.

교체는 트리거마다 DROP 뒤 CREATE이고 배포는 이 동안 백엔드를 멈추지 않는다. 그 짧은 틈에
들어올 수 있는 값도 위 경로의 소문자뿐이라 형식 검사 없이 들어갈 위반 값이 없다
(`050` · `051` · `057`의 교체도 같은 틈을 가졌다).

downgrade
---------
``BINARY`` 없는 옛 조건으로 되돌린다. 데이터를 한 행도 바꾸지 않으므로(구조만 되돌림)
``migration_guard``의 세 분류 어디에도 넣지 않는다 — ``a7d3e9b14f26``·``050``과 같은 판단.
교체는 ``upgrade``와 달리 **관용한다** — 없으면 지우지 않고, 중복이라 지우지 못해도
넘어간다(``drop_trigger``). 롤백이 그 자리에서 갇히는 것이 옛 조건이 남는 것보다 나쁘다.
"""

from __future__ import annotations

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, replace_trigger

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None

#: `DB_SCHEMA §2.5` [S-7] 원문 — `sha256:` + 64 hex. `a7d3e9b14f26.HASH_PATTERN`과 같다.
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: (트리거 이름, 테이블, 열) — `a7d3e9b14f26.HASH_TRIGGERS`와 같아야 한다. 그 리비전이 건
#: 것을 여기서 갈아 끼운다.
HASH_TRIGGERS: tuple[tuple[str, str, str], ...] = (
    ("trg_calcrun_input_hash_format", "calculation_run", "input_hash"),
    ("trg_calcrun_param_hash_format", "calculation_run", "parameter_hash"),
    ("trg_snap_input_hash_format", "simulation_snapshot", "input_hash"),
    ("trg_snap_param_hash_format", "simulation_snapshot", "parameter_hash"),
)


def _body(table: str, column: str, *, binary: bool) -> str:
    operator = "REGEXP BINARY" if binary else "REGEXP"
    return (
        f"BEFORE INSERT ON {table} IF NOT (new.{column} {operator} '{HASH_PATTERN}') EXECUTE REJECT"
    )


def upgrade() -> None:
    """지우고 좁힌 조건으로 다시 만든다 — **지우지 못했으면 멈춘다** (`replace_trigger`)."""
    for name, table, column in HASH_TRIGGERS:
        replace_trigger(op, name, _body(table, column, binary=True))


def downgrade() -> None:
    """`a7d3e9b14f26`의 조건(대소문자 무시)으로 되돌린다 — 데이터는 한 행도 바꾸지 않는다."""
    for name, table, column in HASH_TRIGGERS:
        drop_trigger(op, name)
        create_trigger(op, name, _body(table, column, binary=False))
