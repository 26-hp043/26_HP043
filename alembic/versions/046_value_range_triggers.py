"""값 범위 CHECK 제약을 CUBRID에서 강제되는 트리거로 되살린다 (`#1058`)

Revision ID: 046
Revises: 045
Create Date: 2026-09-16

무엇이 막히지 않고 있었나
-------------------------
**CUBRID 11.4.6은 CHECK 제약을 구문으로 받기만 하고 검사하지 않는다.** 실측이며
``a7d3e9b14f26``의 docstring이 그 측정을 담고 있다.

    CREATE TABLE _t2 (n INT, CONSTRAINT chk_n CHECK (n > 0))   → Committed
    INSERT INTO _t2 VALUES (-5)                                → row affected
    SELECT n FROM _t2                                          → -5

통합 마이그레이션 ``1c444a5c4819``는 CHECK를 **60개** 적어 두었다. 문법상 살아 있으나
**하나도 막지 않는다.** ``a7d3e9b14f26``이 재현성 계약과 참조 정합에 직결되는 9가지
(해시 형식 4 · 참조 정합 3 · 불변성 2)를 트리거로 되살렸으나, **값 범위 검증은 손대지
않은 채** 남아 있었다.

그 사실은 ``tests/conftest.py``의 ``_CUBRID_SKIP_FILES``가 8파일을 통째로 건너뛰어
**아무도 보지 못하는 상태**였다. 건너뛰기를 걷고 돌리자 ``Failed: DID NOT RAISE
IntegrityError``가 38건 나왔다 — 실측이다.

무엇을 되살리는가 — 값 범위 37건 + ORM에만 있던 1건
---------------------------------------------------
60개 중 **값의 범위·순서를 정하는 37개**를 되살린다. 지금은 아래가 그대로 들어간다.

* ``fuel_type.cf = -1`` → **CII 배출량이 음수**가 된다. ``cf``는 배출계수다.
* ``regulation_year.z_factor_percent = -2`` → 감축률이 음수라 요구 CII가
  **기준선보다 커진다.**
* 위경도 범위 밖 좌표 → 지도·거리 계산이 어긋난다.
* 음수 거리·연료·속력 → CII 분모·분자가 뒤집힌다.

**열거형 허용값 23개(``IN (…)``)는 이 리비전에 넣지 않는다.** 앱이 Enum으로 좁히고
있고, 어긋나도 계산값이 아니라 분류가 틀린다. `#1058` 결정요청 §7의 권장안 **나**가
그 갈래다 — 남은 23개는 뒤따르는 리비전이 맡는다.

``chk_gt_positive``는 CHECK 목록에 **없던 것**을 더한 것이다. ORM
(``db/models/vessel.py:75``)은 선언하는데 통합 마이그레이션이 빠뜨려 DB에 없었다 —
``gross_tonnage``는 GT 기준 CII의 **분모**라 값 범위 묶음에 함께 넣는다.

왜 CHECK를 지우지 않는가
------------------------
``1c444a5c4819``의 CHECK 60개를 그대로 둔다. 지우면 **PostgreSQL로 되돌릴 때**
제약이 통째로 사라지고, 정본(``DB_SCHEMA §2.x``)이 규정한 DDL과도 멀어진다.
CUBRID에서 검사되지 않을 뿐 **선언으로서는 맞다.** 트리거가 그 선언을 집행한다.

왜 예외 갈래를 함께 손보는가
----------------------------
트리거 거부는 ``pycubrid.exceptions.DatabaseError``(errno=-517)로 온다 —
PostgreSQL에서 같은 위반은 ``IntegrityError``였다. 이름이 ``trg_chk_``로 시작하는
트리거의 거부만 ``IntegrityError``로 옮긴다:
``src/cii_platform/db/cubrid_errors.py``.

NULL은 통과한다
---------------
``IF NOT (조건)``에서 조건이 ``NULL``이면 ``NOT NULL``도 ``NULL``이라 참이 아니므로
거부하지 않는다 — **CHECK와 같은 의미**다. 빈 테이블로 확인했다::

    lat NULL      → OK
    lat 999       → rejected by trigger
"""

from __future__ import annotations

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


#: (원래 CHECK 이름, 테이블, ``new.`` 를 붙인 조건).
#:
#: 조건은 ``1c444a5c4819``의 CHECK 본문을 그대로 옮기되 열 참조에 ``new.``만 붙였다 —
#: 트리거 상관명이다. 조건을 다시 쓰지 않는다: 다시 쓰면 선언과 집행이 갈린다.
#:
#: 트리거 이름은 ``trg_<원래 CHECK 이름>_<ins|upd>``다. ``trg_chk_`` 앞머리가
#: ``cubrid_errors``가 보는 표식이므로 **앞머리를 바꾸지 않는다.**
VALUE_RANGE_CHECKS: tuple[tuple[str, str, str], ...] = (
    # ── 규제 파라미터 — 사용자가 보는 CII 숫자를 직접 만든다 ──────────────────
    (
        "chk_d_order",
        "cii_rating_boundary",
        "new.d1 < new.d2 AND new.d2 < new.d3 AND new.d3 < new.d4",
    ),
    ("chk_a_decimal_positive", "cii_reference_line", "new.a_decimal > 0"),
    ("chk_c_positive", "cii_reference_line", "new.c >= 0"),
    ("chk_cf_positive", "fuel_type", "new.cf > 0"),
    ("chk_z_factor_nonneg", "regulation_year", "new.z_factor_percent >= 0"),
    # ── 시뮬레이션 분포 — 어긋나면 Monte Carlo가 조용히 다른 분포를 쓴다 ──────
    (
        "chk_sim_param_floor_positive",
        "simulation_parameter",
        "new.floor_value IS NULL OR new.floor_value > 0",
    ),
    (
        "chk_sim_param_bounds_ordered",
        "simulation_parameter",
        "new.min_value <= new.mode_value AND new.mode_value <= new.max_value",
    ),
    # ── 선박 제원 — CII의 분모다 ─────────────────────────────────────────────
    ("chk_dwt_positive", "vessel", "new.deadweight IS NULL OR new.deadweight > 0"),
    # ORM(`db/models/vessel.py:75`)에만 있고 DB에 없던 것. GT 기준 CII의 분모다.
    ("chk_gt_positive", "vessel", "new.gross_tonnage IS NULL OR new.gross_tonnage > 0"),
    (
        "chk_speed_positive",
        "vessel",
        "new.reference_speed_kn IS NULL OR new.reference_speed_kn > 0",
    ),
    (
        "chk_vessel_lat_range",
        "vessel",
        "new.current_lat IS NULL OR new.current_lat BETWEEN -90 AND 90",
    ),
    (
        "chk_vessel_lon_range",
        "vessel",
        "new.current_lon IS NULL OR new.current_lon BETWEEN -180 AND 180",
    ),
    # ── 위치 이력 ───────────────────────────────────────────────────────────
    ("chk_vessel_position_snapshot_lat", "vessel_position_snapshot", "new.lat BETWEEN -90 AND 90"),
    (
        "chk_vessel_position_snapshot_lon",
        "vessel_position_snapshot",
        "new.lon BETWEEN -180 AND 180",
    ),
    (
        "chk_vessel_position_snapshot_cog",
        "vessel_position_snapshot",
        "new.cog_deg IS NULL OR (new.cog_deg >= 0 AND new.cog_deg < 360)",
    ),
    (
        "chk_vessel_position_snapshot_nav_status",
        "vessel_position_snapshot",
        "new.nav_status IS NULL OR (new.nav_status >= 0 AND new.nav_status <= 15)",
    ),
    (
        "chk_vessel_position_snapshot_sog",
        "vessel_position_snapshot",
        "new.sog_kn IS NULL OR new.sog_kn >= 0",
    ),
    # ── 항차 — 거리·속력이 CII 분모다 ───────────────────────────────────────
    ("chk_distance_positive", "voyage", "new.planned_distance_nm > 0"),
    ("chk_speed_positive_voyage", "voyage", "new.planned_speed_kn >= 1.0"),
    (
        "chk_actual_dist_positive",
        "voyage",
        "new.actual_distance_nm IS NULL OR new.actual_distance_nm > 0",
    ),
    (
        "chk_actual_speed_positive",
        "voyage",
        "new.actual_avg_speed_kn IS NULL OR new.actual_avg_speed_kn >= 1.0",
    ),
    (
        "chk_dep_lat_range",
        "voyage",
        "new.departure_lat IS NULL OR new.departure_lat BETWEEN -90 AND 90",
    ),
    (
        "chk_dep_lon_range",
        "voyage",
        "new.departure_lon IS NULL OR new.departure_lon BETWEEN -180 AND 180",
    ),
    (
        "chk_arr_lat_range",
        "voyage",
        "new.arrival_lat IS NULL OR new.arrival_lat BETWEEN -90 AND 90",
    ),
    (
        "chk_arr_lon_range",
        "voyage",
        "new.arrival_lon IS NULL OR new.arrival_lon BETWEEN -180 AND 180",
    ),
    (
        "chk_regulation_year_range",
        "voyage",
        "new.regulation_year IS NULL OR new.regulation_year BETWEEN 2019 AND 2050",
    ),
    # ── 연료 사용량 ─────────────────────────────────────────────────────────
    (
        "chk_fuel_positive",
        "voyage_fuel_use",
        "new.planned_fuel_ton IS NULL OR new.planned_fuel_ton > 0",
    ),
    (
        "chk_actual_fuel_positive",
        "voyage_fuel_use",
        "new.actual_fuel_ton IS NULL OR new.actual_fuel_ton > 0",
    ),
    # ── 시나리오 ────────────────────────────────────────────────────────────
    ("chk_scenario_distance_positive", "voyage_scenario", "new.distance_nm > 0"),
    ("chk_scenario_duration_positive", "voyage_scenario", "new.duration_hours > 0"),
    ("chk_scenario_fuel_positive", "voyage_scenario", "new.fuel_ton > 0"),
    ("chk_scenario_speed_positive", "voyage_scenario", "new.speed_kn >= 1.0"),
    # ── 연간 시뮬레이션 ─────────────────────────────────────────────────────
    ("chk_sim_runs_positive", "annual_simulation_run", "new.simulation_runs > 0"),
    # ── 정박 구간 ───────────────────────────────────────────────────────────
    ("chk_nup_distance_non_negative", "not_underway_period", "new.distance_nm >= 0"),
    (
        "chk_not_underway_period_time_order",
        "not_underway_period",
        "new.ended_at IS NULL OR new.ended_at > new.started_at",
    ),
    ("chk_nufu_cf_used_positive", "not_underway_fuel_use", "new.cf_used > 0"),
    ("chk_not_underway_fuel_positive", "not_underway_fuel_use", "new.fuel_ton > 0"),
    # ── 대화 세션 ───────────────────────────────────────────────────────────
    ("chk_chat_session_expires", "chat_session", "new.expires_at > new.created_at"),
)

#: 트리거를 거는 이벤트. CHECK는 INSERT와 UPDATE 양쪽에서 걸리므로 둘 다 건다.
_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")


def _trigger_name(check_name: str, event: str) -> str:
    """``chk_cf_positive`` + ``INSERT`` → ``trg_chk_cf_positive_ins``.

    ``voyage``와 ``vessel``이 둘 다 ``chk_speed_positive``라는 **같은 이름**의 CHECK를
    갖는다(정본 그대로다). CHECK는 테이블마다 이름 공간이 나뉘지만 **CUBRID의 트리거는
    DB 전역에서 유일**해야 하므로, 목록에서 항차 쪽을 ``chk_speed_positive_voyage``로
    구분해 두었다.
    """
    return f"trg_{check_name}_{event.lower()[:3]}"


def upgrade() -> None:
    """값 범위 제약을 트리거로 건다."""
    for check_name, table, condition in VALUE_RANGE_CHECKS:
        for event in _EVENTS:
            op.execute(
                f"CREATE TRIGGER {_trigger_name(check_name, event)} "
                f"BEFORE {event} ON {table} "
                f"IF NOT ({condition}) EXECUTE REJECT"
            )


def downgrade() -> None:
    """건 것만 내린다 — 다시 upgrade하면 같은 것이 돌아온다.

    **데이터를 한 행도 지우지 않는다.** 트리거만 떼므로 ``migration_guard``의 세
    분류(IRREVERSIBLE·EPHEMERAL·REGENERABLE) 어디에도 넣지 않고
    ``guard_irreversible_downgrade``도 부르지 않는다 — 그 셋은 **데이터 손실**을
    가르는 분류다. ``a7d3e9b14f26``이 같은 판단을 했다.
    """
    for check_name, _table, _condition in VALUE_RANGE_CHECKS:
        for event in _EVENTS:
            op.execute(f"DROP TRIGGER {_trigger_name(check_name, event)}")
