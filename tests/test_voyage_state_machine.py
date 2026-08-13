"""Voyage 상태 머신 종합 테스트 (#302 로직 고정, #318).

서비스 계층(``transition_voyage``·``delete_voyage``)을 직접 호출해
``_TRANSITIONS`` 매트릭스 전체와 policy 가드·삭제 경로를 잠근다.
#302(#54)가 테스트 없이 머지된 빚을 갚는 파일이다.

중복 제거 — 다른 PR이 이미 잠근 동작은 여기 두지 않는다:
- policy 미지정 유지·명시적 재지정 요구(#310) → PR #323의 테스트
- hard delete 409 가드(#313) → PR #324의 테스트

범위 밖(PR 본문에 기록):
- API_SPEC §3.5의 실적 가드(IN_PROGRESS→COMPLETED 최소 1개 actual_fuel_ton>0,
  COMPLETED→CONFIRMED 전 실적 완전성)는 서비스에 아직 구현돼 있지 않다.
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

import pytest

from cii_platform.errors import NotFoundError, StateTransitionError
from cii_platform.services import voyage as svc

_ALL_STATUSES = [
    "DRAFT",
    "PLANNED",
    "IN_PROGRESS",
    "COMPLETED",
    "CONFIRMED",
    "CANCELLED",
    "ARCHIVED",
]

#: API_SPEC §3.5 전환 규칙 표의 허용 전환 전부.
_ALLOWED_TRANSITIONS = {
    ("DRAFT", "PLANNED"),
    ("DRAFT", "CANCELLED"),
    ("PLANNED", "IN_PROGRESS"),
    ("PLANNED", "CANCELLED"),
    ("IN_PROGRESS", "COMPLETED"),
    ("IN_PROGRESS", "CANCELLED"),
    ("COMPLETED", "CONFIRMED"),
    ("CONFIRMED", "COMPLETED"),
    ("CONFIRMED", "ARCHIVED"),
}


class _StubVoyage:
    """``to_dict``가 읽는 속성 전부를 가진 항차 스텁."""

    def __init__(
        self,
        status: str = "DRAFT",
        annual_inclusion_policy: str = "EXCLUDE",
        regulation_year: int | None = None,
    ) -> None:
        self.id = uuid4()
        self.vessel_id = UUID("00000000-0000-4000-8000-000000000001")
        self.voyage_no = "V-TEST-001"
        self.status = status
        self.departure_port_name = "Busan"
        self.departure_lat = None
        self.departure_lon = None
        self.arrival_port_name = "Rotterdam"
        self.arrival_lat = None
        self.arrival_lon = None
        self.planned_distance_nm = None
        self.actual_distance_nm = None
        self.planned_speed_kn = None
        self.actual_avg_speed_kn = None
        self.planned_departure_at = None
        self.planned_arrival_at = None
        self.actual_departure_at = None
        self.actual_arrival_at = None
        self.annual_inclusion_policy = annual_inclusion_policy
        self.regulation_year = regulation_year
        self.created_from = "MANUAL"
        self.notes = None
        self.is_deleted = False
        self.created_at = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)


class _StubSession:
    """``commit``·``delete``만 기록하는 세션 스텁."""

    def __init__(self) -> None:
        self.commits = 0
        self.deleted: list = []

    async def commit(self) -> None:
        self.commits += 1

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)


def _install(monkeypatch: pytest.MonkeyPatch, voyage: _StubVoyage) -> _StubSession:
    """서비스가 보는 저장소를 스텁으로 교체하고 세션 스텁을 반환한다."""

    async def fake_get_by_id(_session, voyage_id):
        return voyage if voyage_id == voyage.id else None

    async def fake_list_fuel_uses(_session, _voyage_id):
        return []

    async def fake_has_refs(_session, _voyage_id):
        return False

    monkeypatch.setattr(svc.voyage_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(svc.voyage_repo, "list_fuel_uses", fake_list_fuel_uses)
    monkeypatch.setattr(svc.voyage_repo, "has_calculation_run_refs", fake_has_refs)
    return _StubSession()


# --- 전환 매트릭스 --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    sorted(_ALLOWED_TRANSITIONS),
    ids=[f"{a}__to__{b}" for a, b in sorted(_ALLOWED_TRANSITIONS)],
)
async def test_allowed_transition_succeeds(monkeypatch, from_status, to_status):
    """허용 전환 9종 — 상태가 바뀐다 (API_SPEC §3.5 규칙 표)."""
    voyage = _StubVoyage(status=from_status, regulation_year=2026)
    session = _install(monkeypatch, voyage)
    result = await svc.transition_voyage(session, voyage.id, to_status)
    assert result["status"] == to_status
    assert voyage.status == to_status


@pytest.mark.parametrize("from_status", _ALL_STATUSES)
@pytest.mark.parametrize("to_status", _ALL_STATUSES)
async def test_disallowed_transition_is_rejected(monkeypatch, from_status, to_status):
    """허용 밖 전환·자기 전환은 전부 StateTransitionError(422)."""
    if (from_status, to_status) in _ALLOWED_TRANSITIONS:
        pytest.skip("허용 전환은 test_allowed_transition_succeeds가 담당")
    voyage = _StubVoyage(status=from_status)
    session = _install(monkeypatch, voyage)
    with pytest.raises(StateTransitionError):
        await svc.transition_voyage(session, voyage.id, to_status)


# --- policy 가드 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_status", "from_policy", "to_status"),
    [
        ("IN_PROGRESS", "INCLUDE_AS_PLAN", "CANCELLED"),
        ("CONFIRMED", "INCLUDE_AS_ACTUAL", "ARCHIVED"),
    ],
)
async def test_policy_omitted_auto_excludes_for_exclude_only(
    monkeypatch, from_status, from_policy, to_status
):
    """EXCLUDE-only 상태로의 전환은 자동 EXCLUDE (API_SPEC §3.5 「자동 설정」)."""
    voyage = _StubVoyage(from_status, from_policy, regulation_year=2026)
    session = _install(monkeypatch, voyage)
    result = await svc.transition_voyage(session, voyage.id, to_status)
    assert result["annual_inclusion_policy"] == "EXCLUDE"


@pytest.mark.parametrize(
    ("from_status", "to_status", "policy"),
    [
        ("IN_PROGRESS", "COMPLETED", "INCLUDE_AS_PLAN"),
        ("DRAFT", "PLANNED", "INCLUDE_AS_ACTUAL"),
        ("IN_PROGRESS", "CANCELLED", "INCLUDE_AS_ACTUAL"),
        ("CONFIRMED", "ARCHIVED", "INCLUDE_AS_PLAN"),
    ],
)
async def test_invalid_policy_for_target_is_rejected(monkeypatch, from_status, to_status, policy):
    """목표 상태가 허용하지 않는 policy 명시 지정 → 422 (PRD §8.1.2 매트릭스)."""
    voyage = _StubVoyage(from_status, "EXCLUDE", regulation_year=2026)
    session = _install(monkeypatch, voyage)
    with pytest.raises(StateTransitionError):
        await svc.transition_voyage(session, voyage.id, to_status, policy)


async def test_include_policy_requires_regulation_year(monkeypatch):
    """regulation_year 없이 INCLUDE_AS_PLAN 지정 → 422 (#150 가드)."""
    voyage = _StubVoyage("DRAFT", "EXCLUDE", regulation_year=None)
    session = _install(monkeypatch, voyage)
    with pytest.raises(StateTransitionError):
        await svc.transition_voyage(session, voyage.id, "PLANNED", "INCLUDE_AS_PLAN")


async def test_explicit_valid_policy_applied(monkeypatch):
    """연도가 있으면 명시적 INCLUDE_AS_PLAN이 적용된다."""
    voyage = _StubVoyage("DRAFT", "EXCLUDE", regulation_year=2026)
    session = _install(monkeypatch, voyage)
    result = await svc.transition_voyage(session, voyage.id, "PLANNED", "INCLUDE_AS_PLAN")
    assert result["annual_inclusion_policy"] == "INCLUDE_AS_PLAN"


# --- 삭제 경로 ------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["DRAFT", "CANCELLED"])
async def test_hard_delete_statuses(monkeypatch, status):
    """DRAFT·CANCELLED → hard delete (참조 없음)."""
    voyage = _StubVoyage(status)
    session = _install(monkeypatch, voyage)
    result = await svc.delete_voyage(session, voyage.id)
    assert result["hard_delete"] is True
    assert session.deleted == [voyage]


@pytest.mark.parametrize("status", ["COMPLETED", "CONFIRMED", "ARCHIVED"])
async def test_soft_delete_statuses(monkeypatch, status):
    """COMPLETED·CONFIRMED·ARCHIVED → soft delete (감사 보존)."""
    voyage = _StubVoyage(status)
    session = _install(monkeypatch, voyage)
    result = await svc.delete_voyage(session, voyage.id)
    assert result["hard_delete"] is False
    assert voyage.is_deleted is True


@pytest.mark.parametrize("status", ["PLANNED", "IN_PROGRESS"])
async def test_active_statuses_reject_delete(monkeypatch, status):
    """PLANNED·IN_PROGRESS → 422 — 먼저 CANCELLED로 전환 필요."""
    voyage = _StubVoyage(status)
    session = _install(monkeypatch, voyage)
    with pytest.raises(StateTransitionError):
        await svc.delete_voyage(session, voyage.id)


async def test_unknown_voyage_404s(monkeypatch):
    """존재하지 않는 항차 → NotFoundError (전환·삭제 공통)."""
    voyage = _StubVoyage()
    session = _install(monkeypatch, voyage)
    with pytest.raises(NotFoundError):
        await svc.delete_voyage(session, uuid4())
    with pytest.raises(NotFoundError):
        await svc.transition_voyage(session, uuid4(), "PLANNED")
