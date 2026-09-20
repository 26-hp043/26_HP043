"""남은 열거형·정합 CHECK 23건을 트리거로 되살린다 (`#1058`)

Revision ID: 048
Revises: 047
Create Date: 2026-09-16

무엇이 남아 있었나
------------------
``046``이 값 범위 37건을 트리거로 옮기면서 **열거형 허용값 23건은 뒤로 미뤘다.**
결정요청 §7의 권장안 **나**가 그 갈래였다 — 「사용자가 보는 숫자를 바꾸는 것부터
걸고, 열거형은 정본에 명시한다」.

미룬 쪽도 **지금 처리하기로 했다**(사용자 지시, 2026-09-16). 정본에 「DB에서 강제하지
않는다」를 적는 대신 **실제로 막는다** — 적어 두는 것보다 막는 것이 낫고, 남은 일정
안에 들어간다.

무엇을 막는가
-------------
23건은 성질이 셋이다.

**⑴ 허용값 열거 17건** — ``status`` · ``period_type`` · ``consumer_type`` ·
``calculation_type`` · ``role`` 등. 어긋나면 **계산값이 아니라 분류가 틀린다.**
연간 집계가 그 항차를 어느 갈래로도 세지 못하고 조용히 빠진다.

**⑵ 조합 정합 4건** — ``chk_vessel_state_pair`` · ``chk_vessel_position_pair`` ·
``chk_year_policy`` · ``chk_status_policy``. 한 열만 보면 멀쩡한데 **둘을 같이 보면
모순인 상태**를 막는다. ``UIFLOW v2.0 §2-4``의 표가 그 조합을 규정한다. 반쪽 상태가
들어가면 화면이 그릴 수 없는 선박이 생긴다.

**⑶ 형식 2건** — ``chk_capacity_rule``(``'DWT'``·``'GT'`` 또는 ``'fixed %'``).

왜 조건을 다시 쓰지 않는가
--------------------------
23건 전부 ``1c444a5c4819``의 CHECK 본문을 **기계로 뽑아** 열 참조에만 ``new.`` 를
붙였다. 손으로 옮겨 적으면 선언과 집행이 갈린다 — 특히 ``chk_status_policy``처럼
분기가 넷인 조건은 옮겨 적다 한 갈래를 빠뜨려도 **아무도 모른다.**

예약어는 인용한다
-----------------
``variable`` · ``source`` · ``status`` · ``role``은 CUBRID 예약어다. 인용하지 않으면
구문 오류가 난다. ``new."status"``가 트리거 안에서 동작하는 것은 빈 테이블로
확인했다.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


#: (원래 CHECK 이름, 테이블, ``new.`` 를 붙인 조건). ``046``과 같은 모양이다.
#: 앞머리 ``trg_chk_``는 ``cubrid_errors``가 ``IntegrityError``로 옮기는 표식이다.
ENUM_AND_PAIR_CHECKS: tuple[tuple[str, str, str], ...] = (
    # ── 허용값 열거 ─────────────────────────────────────────────────────────
    (
        "chk_capacity_rule",
        "cii_reference_line",
        "new.capacity_rule IN ('DWT','GT') OR new.capacity_rule LIKE 'fixed %'",
    ),
    ("chk_sim_param_bound_type", "simulation_parameter", "new.bound_type IN ('FACTOR','DELTA')"),
    ("chk_sim_param_distribution", "simulation_parameter", "new.distribution IN ('TRIANGULAR')"),
    (
        "chk_sim_param_variable",
        "simulation_parameter",
        "new.\"variable\" IN ('DISTANCE','FUEL','SPEED')",
    ),
    (
        "chk_detail_status_allowed",
        "vessel",
        "new.detail_status IS NULL OR new.detail_status IN "
        "('SAILING','IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')",
    ),
    (
        "chk_underway_state_allowed",
        "vessel",
        "new.underway_state IS NULL OR new.underway_state IN ('UNDER_WAY','NOT_UNDER_WAY')",
    ),
    ("chk_user_token_purpose", "user_token", "new.purpose IN ('EMAIL_VERIFY', 'PASSWORD_RESET')"),
    (
        "chk_vessel_position_snapshot_source",
        "vessel_position_snapshot",
        "new.\"source\" IN ('MANUAL','AIS','SIMULATED')",
    ),
    (
        "chk_voyage_policy",
        "voyage",
        "new.annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN','INCLUDE_AS_ACTUAL')",
    ),
    (
        "chk_voyage_status",
        "voyage",
        'new."status" IN '
        "('DRAFT','PLANNED','IN_PROGRESS','COMPLETED','CONFIRMED','CANCELLED','ARCHIVED')",
    ),
    (
        "chk_calculation_type",
        "calculation_run",
        "new.calculation_type IN "
        "('VOYAGE_ESTIMATE','SCENARIO','ANNUAL_DETERMINISTIC','ANNUAL_MONTE_CARLO')",
    ),
    ("chk_chat_message_role", "chat_message", "new.\"role\" IN ('USER','ASSISTANT')"),
    (
        "chk_not_underway_period_type",
        "not_underway_period",
        "new.period_type IN ('IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')",
    ),
    (
        "chk_fuel_source",
        "voyage_fuel_use",
        "new.\"source\" IN ('USER_INPUT','MODEL_ESTIMATE','IMPORT','SAMPLE')",
    ),
    ("chk_scenario_rating", "voyage_scenario", "new.estimated_rating IN ('A','B','C','D','E')"),
    (
        "chk_scenario_risk",
        "voyage_scenario",
        "new.risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",
    ),
    (
        "chk_scenario_type",
        "voyage_scenario",
        "new.scenario_type IN ('DIRECT','DETOUR','SLOW_STEAMING')",
    ),
    ("chk_target_rating", "annual_simulation_run", "new.target_rating IN ('A','B','C','D')"),
    (
        "chk_not_underway_consumer_type",
        "not_underway_fuel_use",
        "new.consumer_type IN ('MAIN_ENGINE','AUX_ENGINE','OIL_FIRED_BOILER','OTHER')",
    ),
    # ── 조합 정합 — 한 열만 보면 멀쩡한데 둘을 같이 보면 모순인 상태 ─────────
    (
        "chk_vessel_state_pair",
        "vessel",
        "(new.underway_state IS NULL AND new.detail_status IS NULL) "
        "OR (new.underway_state IS NOT NULL AND new.detail_status IS NOT NULL "
        "AND (new.underway_state = 'UNDER_WAY' AND new.detail_status = 'SAILING' "
        "OR new.underway_state = 'NOT_UNDER_WAY' AND new.detail_status IN "
        "('IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')))",
    ),
    (
        "chk_vessel_position_pair",
        "vessel",
        "(new.current_lat IS NULL AND new.current_lon IS NULL) "
        "OR (new.current_lat IS NOT NULL AND new.current_lon IS NOT NULL "
        "AND new.position_updated_at IS NOT NULL)",
    ),
    (
        "chk_year_policy",
        "voyage",
        "new.annual_inclusion_policy = 'EXCLUDE' OR new.regulation_year IS NOT NULL",
    ),
    (
        "chk_status_policy",
        "voyage",
        "(new.\"status\" = 'DRAFT' AND new.annual_inclusion_policy = 'EXCLUDE') "
        "OR (new.\"status\" IN ('PLANNED','IN_PROGRESS') "
        "AND new.annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN')) "
        "OR (new.\"status\" IN ('COMPLETED','CONFIRMED') "
        "AND new.annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_ACTUAL')) "
        "OR (new.\"status\" IN ('CANCELLED','ARCHIVED') "
        "AND new.annual_inclusion_policy = 'EXCLUDE')",
    ),
)

_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")


def _trigger_name(check_name: str, event: str) -> str:
    return f"trg_{check_name}_{event.lower()[:3]}"


def _existing_triggers() -> set[str]:
    """지금 있는 트리거 이름 (`#1373`)."""
    rows = op.get_bind().execute(sa.text("SELECT name FROM db_trigger")).fetchall()
    return {row[0] for row in rows}


def upgrade() -> None:
    """열거형·정합 제약을 트리거로 건다.

    ⚠️ **이미 있으면 만들지 않는다** (`#1373`). CUBRID는 **같은 이름의 트리거를 중복
    생성하도록 허용**하는데(실측: 있는 이름으로 `CREATE TRIGGER`가 성공하고 카탈로그가
    한 줄 는다), **중복이 생기면 그 이름으로는 `DROP TRIGGER`가 「없다」(errno -503)로
    답해 어느 쪽도 지울 수 없다.** 그 상태가 되면 이 마이그레이션의 `downgrade()`가
    영구히 막히고, 롤백 왕복 검사가 그 자리에서 끊긴다.
    """
    have = _existing_triggers()
    for check_name, table, condition in ENUM_AND_PAIR_CHECKS:
        for event in _EVENTS:
            name = _trigger_name(check_name, event)
            if name in have:
                continue
            op.execute(
                f"CREATE TRIGGER {name} BEFORE {event} ON {table} "
                f"IF NOT ({condition}) EXECUTE REJECT"
            )


def downgrade() -> None:
    """건 것만 내린다 — 데이터를 한 행도 지우지 않는다(``046``과 같은 판단).

    ⚠️ **없는 것은 넘어간다** (`#1373`). 다운그레이드는 가드를 *걷어내는* 방향이므로
    대상이 이미 없는 것을 실패로 볼 이유가 없다. 종전에는 46건을 무조건 지우다가 한
    건에서 `-503`이 나면 **마이그레이션 전체가 그 자리에서 멈췄고**, alembic이 리비전을
    내리지 못해 DB가 `048`에 갇혔다.

    🔴 **이것은 응급 조치다.** 같은 패턴(트리거를 이름으로 지우는 downgrade)이
    `046`·`047`·`049`·`050`·`051`·`055`·`057`·`059`·`a7d3e9b14f26`에도 있다. 공용 헬퍼로
    묶을지는 `#1373`에서 판단한다 — 여기서는 **실제로 막고 있던 한 곳만** 연다.
    """
    have = _existing_triggers()
    for check_name, _table, _condition in ENUM_AND_PAIR_CHECKS:
        for event in _EVENTS:
            name = _trigger_name(check_name, event)
            if name not in have:
                continue
            _drop_tolerating_missing(name)


#: CUBRID가 「그런 트리거가 없다」로 답할 때의 표시 (`errno=-503`).
_NOT_FOUND = "was not found"


def _drop_tolerating_missing(name: str) -> None:
    """트리거를 지우되 **「없다」는 답은 넘어간다** (`#1373`).

    카탈로그(`db_trigger`)에 이름이 있는데도 `DROP TRIGGER`가 `-503`으로 답하는 상태가
    실재한다 — **같은 이름이 둘 이상일 때** 이름으로는 어느 쪽도 지목되지 않는다(실측).
    그 한 건 때문에 46건짜리 루프 전체가 멈추면 리비전이 내려가지 못해 DB가 `048`에
    갇히고, 다음 실행부터는 롤백 왕복 검사가 매번 같은 자리에서 끊긴다.

    **지우려는 대상이 결과적으로 없는 것**은 이 함수의 목적(가드를 걷어낸다)에 어긋나지
    않으므로 넘어간다. 다른 오류는 그대로 올린다 — 조용히 삼키면 이 응급 조치가 진짜
    실패까지 가린다.
    """
    try:
        op.execute(f"DROP TRIGGER {name}")
    except sa.exc.DatabaseError as exc:  # pragma: no cover - CUBRID 상태 의존
        if _NOT_FOUND not in str(exc):
            raise
