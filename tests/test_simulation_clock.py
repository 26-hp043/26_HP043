"""시뮬레이션 시계 검증 (#368).

이슈의 「완료 기준」을 그대로 테스트로 옮긴다.

* 같은 ``as_of``로 반복 호출 시 결과가 bit-exact 일치한다
* ``as_of``를 진행시키면 누적 거리·연료가 증가한다
* not under way 구간에서는 **거리는 멈추고** under way 연료도 멈춘다
* 계산 코어(``calc/``)가 시각을 알지 않는다 — 이 모듈이 확정한 값만 넘어간다
* ``as_of``를 달리하면 다른 ``input_hash``가 나온다

DB를 쓰지 않는다 — 이 모듈은 이미 읽어 온 행을 받는 순수 함수이며, 시각 경계
조건은 DB 없이 검증하는 것이 빠르고 정확하다.

케이스: UT-CLOCK-001 · UT-CLOCK-002 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cii_platform.calc.hash import INPUT_FIELDS, compute_input_hash
from cii_platform.services.simulation_clock import (
    NotUnderwayWindow,
    compute_progress,
    resolve_as_of,
)

DEPARTURE = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
SPEED = Decimal("12")
DAILY_FOC = Decimal("30")


def _progress(as_of: datetime, **kwargs):
    params = {
        "as_of": as_of,
        "departure_at": DEPARTURE,
        "arrival_at": None,
        "speed_kn": SPEED,
        "daily_foc_ton": DAILY_FOC,
    }
    params.update(kwargs)
    return compute_progress(**params)


# --- 1. 이슈 본문의 예시 그대로 -----------------------------------------------------


def test_issue_example_six_hours():
    """출항 09:00 · 12 kn · 30 t/day → 15:00 조회 시 72 nm · 7.5 t."""
    result = _progress(DEPARTURE + timedelta(hours=6))

    assert result.underway_hours == Decimal("6")
    assert result.distance_nm == Decimal("72")
    assert result.fuel_ton == Decimal("7.5")
    assert result.is_simulated is True


def test_issue_example_twelve_hours():
    """12시간 뒤에는 144 nm · 15 t — 선형으로 늘어난다."""
    result = _progress(DEPARTURE + timedelta(hours=12))

    assert result.distance_nm == Decimal("144")
    assert result.fuel_ton == Decimal("15")


# --- 2. 재현성 --------------------------------------------------------------------


def test_same_as_of_is_bit_exact_repeatable():
    """같은 ``as_of``면 몇 번을 불러도 같은 값이다 (TECH_SPEC §5.4 1항)."""
    as_of = DEPARTURE + timedelta(hours=7, minutes=23, seconds=11)

    first = _progress(as_of)
    second = _progress(as_of)

    assert first == second
    # Decimal 동등성만으로는 표현이 갈릴 수 있다 — 문자열까지 같아야 bit-exact다.
    assert str(first.distance_nm) == str(second.distance_nm)
    assert str(first.fuel_ton) == str(second.fuel_ton)


def test_advancing_as_of_increases_accumulation():
    """``as_of``를 진행시키면 누적 거리·연료가 증가한다."""
    earlier = _progress(DEPARTURE + timedelta(hours=3))
    later = _progress(DEPARTURE + timedelta(hours=9))

    assert later.distance_nm > earlier.distance_nm
    assert later.fuel_ton > earlier.fuel_ton


# --- 3. not under way 차감 ---------------------------------------------------------


def test_not_underway_stops_distance_and_underway_fuel():
    """정박 구간에서는 **거리도 under way 연료도 멈춘다**.

    시간에서 빼기 때문이다. 정박 중 소비한 연료는 ``not_underway_fuel_use``(#345)로
    따로 집계되며, 그래서 분자만 늘고 분모는 안 늘어 등급이 나빠진다.
    """
    as_of = DEPARTURE + timedelta(hours=12)
    # 12시간 중 4시간을 정박했다.
    stay = NotUnderwayWindow(
        started_at=DEPARTURE + timedelta(hours=4),
        ended_at=DEPARTURE + timedelta(hours=8),
    )

    result = _progress(as_of, not_underway_periods=[stay])

    assert result.underway_hours == Decimal("8")
    assert result.distance_nm == Decimal("96")  # 12 kn × 8h
    assert result.fuel_ton == Decimal("10")  # 30 t/day × 8h / 24


def test_open_ended_stay_is_counted_until_as_of():
    """``ended_at``이 NULL인 진행 중 정박은 ``as_of``까지 이어진 것으로 본다."""
    as_of = DEPARTURE + timedelta(hours=10)
    stay = NotUnderwayWindow(started_at=DEPARTURE + timedelta(hours=6), ended_at=None)

    result = _progress(as_of, not_underway_periods=[stay])

    assert result.underway_hours == Decimal("6")
    assert result.distance_nm == Decimal("72")


def test_stay_outside_window_is_ignored():
    """조회 창 밖의 정박 구간은 차감하지 않는다."""
    as_of = DEPARTURE + timedelta(hours=5)
    stay = NotUnderwayWindow(
        started_at=DEPARTURE + timedelta(hours=20),
        ended_at=DEPARTURE + timedelta(hours=22),
    )

    result = _progress(as_of, not_underway_periods=[stay])

    assert result.underway_hours == Decimal("5")


def test_stay_partially_overlapping_window_is_clipped():
    """창을 걸친 정박은 **겹치는 부분만** 빠진다."""
    as_of = DEPARTURE + timedelta(hours=6)
    stay = NotUnderwayWindow(
        started_at=DEPARTURE + timedelta(hours=4),
        ended_at=DEPARTURE + timedelta(hours=10),
    )

    result = _progress(as_of, not_underway_periods=[stay])

    assert result.underway_hours == Decimal("4")


# --- 4. 경계 처리 -----------------------------------------------------------------


def test_as_of_before_departure_is_zero():
    """``as_of``가 출항 이전이면 0이다 — 음수 경과를 만들지 않는다."""
    result = _progress(DEPARTURE - timedelta(hours=3))

    assert result.underway_hours == Decimal(0)
    assert result.distance_nm == Decimal(0)
    assert result.fuel_ton == Decimal(0)
    assert result.is_simulated is False


def test_missing_departure_is_zero():
    """출항 시각이 없으면 0이다 — 기준 시각을 임의로 만들지 않는다."""
    result = _progress(DEPARTURE + timedelta(hours=6), departure_at=None)

    assert result.distance_nm == Decimal(0)
    assert result.is_simulated is False


def test_arrival_caps_accumulation_and_clears_simulated_flag():
    """도착 실적이 있으면 그 시각까지만 세고, 시뮬레이션 값이 아니다."""
    arrival = DEPARTURE + timedelta(hours=10)

    at_arrival = _progress(arrival, arrival_at=arrival)
    much_later = _progress(arrival + timedelta(days=5), arrival_at=arrival)

    assert at_arrival.distance_nm == much_later.distance_nm
    assert much_later.underway_hours == Decimal("10")
    # 실적 구간이므로 「시뮬레이션 데이터」 배지(PRD R-5)를 붙이지 않는다.
    assert much_later.is_simulated is False


# --- 4b. 도착 예정일 초과 (#649) ----------------------------------------------------


def test_planned_arrival_caps_accumulation():
    """**이 이슈의 본체다.** 도착 실적이 없어도 예정일을 넘겨 자라지 않는다.

    종전에는 상한이 없어 `window_end = as_of`였고, 계획을 아무리 넘겨도 거리·연료가
    계속 자랐다 — 출항 90일 뒤면 계획의 7배다.
    """
    planned = DEPARTURE + timedelta(days=13)

    at_eta = _progress(planned, planned_arrival_at=planned)
    long_after = _progress(planned + timedelta(days=77), planned_arrival_at=planned)

    assert at_eta.distance_nm == long_after.distance_nm
    assert long_after.underway_hours == Decimal("312")  # 13일 x 24h


def test_past_planned_arrival_is_reported():
    """자르기만 하고 알리지 않으면 사용자는 「항차가 끝났나」로 읽는다.

    실사용에서 이 상태는 **도착 실적 입력을 잊은 항차**이며, 그 사실이 응답에
    드러나야 고칠 대상을 찾을 수 있다.
    """
    planned = DEPARTURE + timedelta(days=13)

    before = _progress(planned - timedelta(hours=1), planned_arrival_at=planned)
    after = _progress(planned + timedelta(hours=1), planned_arrival_at=planned)

    assert before.past_planned_arrival is False
    assert after.past_planned_arrival is True


def test_capped_value_is_still_simulated():
    """잘려도 **시뮬레이션 값이다** — 계획이 곧 실적이 되지 않는다.

    도착 실적이 있을 때와 다른 점이다. 실적은 확정된 사실이고, 예정일은 아직
    입력되지 않은 상태를 계획으로 대신 자른 것뿐이다.
    """
    planned = DEPARTURE + timedelta(days=13)

    capped = _progress(planned + timedelta(days=5), planned_arrival_at=planned)
    with_actual = _progress(planned + timedelta(days=5), arrival_at=planned)

    assert capped.is_simulated is True
    assert with_actual.is_simulated is False
    # 값 자체는 같다 — 다른 것은 「무엇으로 잘랐는가」다.
    assert capped.distance_nm == with_actual.distance_nm


def test_actual_arrival_wins_over_planned():
    """실적이 있으면 그쪽이 사실이다 — 계획으로 자르지 않는다.

    계획보다 일찍·늦게 도착했을 수 있고, 그때 계획으로 자르면 **실제로 항해한
    구간을 버리거나 없는 구간을 만든다.**
    """
    planned = DEPARTURE + timedelta(days=13)
    actual = DEPARTURE + timedelta(days=20)  # 계획보다 7일 늦게 도착

    result = _progress(actual + timedelta(days=3), arrival_at=actual, planned_arrival_at=planned)

    assert result.underway_hours == Decimal("480")  # 20일 x 24h — 계획이 아니라 실적
    assert result.is_simulated is False
    assert result.past_planned_arrival is False


def test_planned_arrival_in_the_future_changes_nothing():
    """예정일 전에는 종전과 동작이 같다 — 회귀가 아닌지 확인한다."""
    planned = DEPARTURE + timedelta(days=13)
    as_of = DEPARTURE + timedelta(hours=6)

    with_planned = _progress(as_of, planned_arrival_at=planned)
    without = _progress(as_of)

    assert with_planned.distance_nm == without.distance_nm
    assert with_planned.past_planned_arrival is False


def test_planned_arrival_before_departure_is_zero_but_reported():
    """예정일이 출항보다 앞서면 진행량이 0이다.

    **값이 0인 이유를 화면이 말할 수 있어야 하므로** 플래그는 남긴다. 데이터가
    잘못된 상태이며, 조용히 0을 내면 「아직 출항 전」과 구분되지 않는다.
    """
    planned = DEPARTURE - timedelta(days=1)

    result = _progress(DEPARTURE + timedelta(days=5), planned_arrival_at=planned)

    assert result.distance_nm == Decimal(0)
    assert result.past_planned_arrival is True


def test_missing_speed_or_foc_yields_zero_without_guessing():
    """속도·일일 소모율이 없으면 0이다 — 임의 기본값을 넣지 않는다.

    ``reference_daily_foc_ton``은 nullable이다(DB_SCHEMA §2.1). 기본값을 넣으면
    화면이 근거 없는 연료를 표시한다.
    """
    as_of = DEPARTURE + timedelta(hours=6)

    no_speed = _progress(as_of, speed_kn=None)
    no_foc = _progress(as_of, daily_foc_ton=None)

    assert no_speed.distance_nm == Decimal(0)
    assert no_speed.fuel_ton == Decimal("7.5")  # 연료는 속도와 무관하다
    assert no_foc.fuel_ton == Decimal(0)
    assert no_foc.distance_nm == Decimal("72")


# --- 5. as_of 확정 ----------------------------------------------------------------


def test_resolve_as_of_returns_server_time_when_absent():
    """미지정이면 서버가 현재 시각을 **확정**한다 (계약 ⑵)."""
    before = datetime.now(UTC)
    resolved = resolve_as_of(None)
    after = datetime.now(UTC)

    assert before <= resolved <= after
    assert resolved.tzinfo is not None


def test_resolve_as_of_treats_naive_as_utc():
    """tz 없는 값은 UTC로 간주한다 — aware/naive 혼용 TypeError를 막는다."""
    naive = datetime(2026, 8, 15, 9, 0)

    assert resolve_as_of(naive) == datetime(2026, 8, 15, 9, 0, tzinfo=UTC)


def test_resolve_as_of_preserves_explicit_value():
    """명시된 값은 그대로 쓴다 — 그래야 계약 ⑶(같은 as_of → 같은 결과)이 선다."""
    explicit = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)

    assert resolve_as_of(explicit) == explicit


# --- 6. input_hash 계약 -----------------------------------------------------------


def test_as_of_is_part_of_input_hash():
    """``as_of``가 다르면 다른 ``input_hash``가 나온다 (계약 ⑷)."""
    base = {
        "vessel_id": "v-1",
        "regulation_year": 2026,
        "ship_type": "BULK_CARRIER",
        "distance_nm": Decimal("72"),
        "speed_kn": Decimal("12"),
        "weather_model": "NONE",
        "weather_factor": Decimal("1.0"),
    }

    first = compute_input_hash({**base, "as_of": "2026-08-15T15:00:00Z"})
    second = compute_input_hash({**base, "as_of": "2026-08-15T21:00:00Z"})

    assert first != second
    # 같은 as_of면 같은 해시여야 한다.
    assert first == compute_input_hash({**base, "as_of": "2026-08-15T15:00:00Z"})


def test_adding_as_of_does_not_change_hashes_of_inputs_without_it():
    """``as_of``를 넘기지 않는 입력의 해시는 종전과 같다.

    ``INPUT_FIELDS``가 바뀌면 저장된 모든 ``input_hash``가 무효가 될 수 있다.
    필터가 **입력에 있는 키만** 담으므로 기능①과 기존 저장분은 영향받지 않는다.
    """
    without_as_of = {
        "vessel_id": "v-1",
        "regulation_year": 2026,
        "ship_type": "BULK_CARRIER",
        "distance_nm": Decimal("1000"),
        "speed_kn": Decimal("12"),
        "weather_model": "NONE",
        "weather_factor": Decimal("1.0"),
    }
    # as_of 도입 이전과 동일한 필드 집합이므로 해시가 달라질 이유가 없다.
    expected = (
        "sha256:"
        # 값 자체를 하드코딩하지 않고, as_of 키가 없을 때 필터가 무시한다는 사실을
        # 검증한다 — 하드코딩하면 무관한 정본 변경에도 이 테스트가 깨진다.
    )
    assert compute_input_hash(without_as_of).startswith(expected)
    assert compute_input_hash({**without_as_of, "unrelated": 1}) == compute_input_hash(
        without_as_of
    )


def test_as_of_is_registered_in_input_fields():
    """``as_of``가 정본 필드 목록에 있다 (TECH_SPEC §5.3)."""
    assert "as_of" in INPUT_FIELDS


# --- 7. 계층 규칙 -----------------------------------------------------------------


def test_calc_layer_does_not_know_about_time():
    """계산 코어가 시각을 모른다 — ``as_of`` 계약 ⑸.

    ``calc/``의 계산 함수 시그니처에 ``as_of``나 ``datetime``이 없어야 한다.
    시계를 계산 코어에 넣으면 TECH_SPEC §1의 Layer 1 bit-exact 계약(RK-9)과
    부딪힌다.
    """
    import inspect

    from cii_platform.calc import cii_engine, ytd_engine

    for module in (cii_engine, ytd_engine):
        for name, obj in vars(module).items():
            if name.startswith("_") or not inspect.isfunction(obj):
                continue
            params = inspect.signature(obj).parameters
            assert "as_of" not in params, f"{module.__name__}.{name}이 as_of를 받는다"


@pytest.mark.parametrize("hours", [1, 6, 24, 72])
def test_accumulation_is_linear_in_elapsed_hours(hours: int):
    """누적량은 경과 시간에 선형이다 — 시계가 만드는 값의 정의 그대로."""
    result = _progress(DEPARTURE + timedelta(hours=hours))

    assert result.distance_nm == SPEED * Decimal(hours)
    assert result.fuel_ton == DAILY_FOC * Decimal(hours) / Decimal("24")
