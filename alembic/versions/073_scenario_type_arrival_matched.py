"""voyage_scenario.scenario_type — 도착시각 맞춤 2종(DIRECT_JIT · DETOUR_JIT)을 값에 더한다

Revision ID: 073
Revises: 072
Create Date: 2026-10-26

`048`이 ``scenario_type``의 값을 **셋으로 못 박았다**(``trg_chk_scenario_type_ins``·``_upd``).
CUBRID가 CHECK를 검사하지 않아 `#1058`이 트리거로 옮긴 자리다(§7.4).

#2561 결정 D1 「가」 — 항로 비교에 선석 가용 시각을 넣으면 「직항 · 도착시각 맞춤」과
「우회 · 도착시각 맞춤」 두 장이 붙는다. 비교는 시나리오마다 ``voyage_scenario`` 한 행을
저장하고 채택(``POST /scenarios/{id}/adopt``)이 그 행을 가리키므로, 이 마이그레이션이 없으면
선석 시각을 넣은 비교가 저장 단계에서 트리거에 REJECT되어 500이 된다. 열은 그대로 두고
**트리거 두 개만 다시 만든다**(`057`과 같은 모양).

## downgrade가 데이터를 지운다

옛 트리거는 새 두 값을 거부한다. 트리거를 좁히기 **전에** 그 행을 지워야 한다 — 남겨 두면
그 행을 건드리는 다음 UPDATE(채택 표시 · 항차 연결 해제)가 REJECT된다. 옛 값으로 바꿔 둘
자리가 없다: 도착시각 맞춤 행의 속력은 선석 시각에서 나온 값이라 「직항」으로 이름만 바꾸면
직항이 아닌 속력을 직항이라고 부르게 된다.

지운 행은 다시 ``upgrade``해도 돌아오지 않는다 — `057`이 관리자 지정에 대해 가진 것과 같은
성질이라 ``IRREVERSIBLE``에 둔다(``db/migration_guard.py``). 계산 이력(``calculation_run``)의
``result_json``은 그 시나리오를 그대로 갖고 있어 리포트의 사후 비교는 남는다 — 채택할 행만
사라진다.
"""

from __future__ import annotations

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, replace_trigger

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None

#: 트리거 이름은 `048`이 정한 것을 그대로 쓴다 — 이름이 갈리면 `048`의 downgrade가
#: 없는 트리거를 지우려다 선다.
_EVENTS = ("INSERT", "UPDATE")

_WIDE = "'DIRECT','DETOUR','SLOW_STEAMING','DIRECT_JIT','DETOUR_JIT'"
_NARROW = "'DIRECT','DETOUR','SLOW_STEAMING'"


def _recreate(values: str, *, strict: bool) -> None:
    """두 트리거를 ``values``로 다시 만든다 — 방향마다 중복 상태의 처리가 다르다(`057`과 같다).

    ``strict``(upgrade)는 **멈춘다**(``replace_trigger`` — 새 값을 받지 못하는 트리거를 남긴 채
    배포가 성공으로 끝나면 안 된다), downgrade는 **관용한다**(롤백이 갇히지 않게 · `D-20`).
    """
    for event in _EVENTS:
        name = f"trg_chk_scenario_type_{event.lower()[:3]}"
        body = (
            f"BEFORE {event} ON voyage_scenario "
            f"IF NOT (new.scenario_type IN ({values})) EXECUTE REJECT"
        )
        if strict:
            replace_trigger(op, name, body)
        else:
            drop_trigger(op, name)
            create_trigger(op, name, body)


def upgrade() -> None:
    _recreate(_WIDE, strict=True)


def downgrade() -> None:
    # 행을 지우기 전에 끊는다 — 무엇이든 바꾸기 전이어야 한다 (#819).
    guard_irreversible_downgrade("073")
    # 순서 — **행을 먼저 지우고 그 다음 트리거를 좁힌다**(`057`과 같은 이유). 좁힌 뒤에 남은
    # 행이 있으면 그 행을 건드리는 이후의 모든 UPDATE가 거부된다.
    op.execute("DELETE FROM voyage_scenario WHERE scenario_type IN ('DIRECT_JIT','DETOUR_JIT')")
    _recreate(_NARROW, strict=False)
