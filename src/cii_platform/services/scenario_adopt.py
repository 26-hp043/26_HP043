"""시나리오 채택 (API_SPEC §5.2, #58).

비교 결과 중 하나를 **항차의 계획값으로 반영**한다. 비교(`§5.1`)가 「무엇이 나은가」를
보여 주는 데서 끝나면 그 판단이 운항에 닿지 않는다 — 이 엔드포인트가 그 마지막 한
걸음이다.

## 계획을 바꾸는 조작이다

그래서 **아직 계획 단계인 항차만** 받는다(`DRAFT`·`PLANNED`). 출항한 뒤에 계획값을
갈아 끼우면 `PRD §8.3`의 값 우선순위가 「실적이 있는데 계획이 나중에 바뀐」 상태를
만나고, 계획 대비 실적 비교(`#363` 피드백 루프)의 기준선이 사라진다.

`PRD §8.1.1` 상태 머신은 **상태 전환**을 규정하지 그 상태에서 무엇을 고칠 수 있는지는
말하지 않는다. 그 빈칸을 여기서 보수적으로 메운다 — 나중에 넓히는 것은 쉽고, 좁히는
것은 이미 바뀐 데이터를 되돌려야 한다.

## 채택은 항차당 하나다

같은 항차에 두 시나리오가 채택돼 있으면 「무엇이 반영됐나」에 답할 수 없다. 새로
채택하면 그 항차의 이전 채택을 내린다.

## 계산 결과를 무효화한다

`API_SPEC §5.2`가 「채택 시 해당 Voyage의 계산 결과는 무효화되고 재계산 필요 표시가
설정된다(`PRD §8.4`)」고 규정한다. 표시는 `calculation_run.needs_recalc`이며
false→true 플립만 허용된다(마이그레이션 024 가드).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update

from cii_platform.db.models.voyage_scenario import VoyageScenario
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError
from cii_platform.services.voyage import create_voyage

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

#: ``API_SPEC §5.2`` — 지원 모드. 기본값은 ``UPDATE_EXISTING_PLAN``이다
#: (``UPDATE_EXISTING``이 아니다 — 이슈 본문이 특히 짚은 지점).
MODE_UPDATE = "UPDATE_EXISTING_PLAN"
MODE_CREATE = "CREATE_NEW_VOYAGE"
ADOPT_MODES: tuple[str, ...] = (MODE_UPDATE, MODE_CREATE)

#: 계획값을 바꿀 수 있는 상태. 모듈 docstring 참조.
PLANNING_STATUSES: frozenset[str] = frozenset({"DRAFT", "PLANNED"})

#: 채택이 바꾸는 항차 필드 (``API_SPEC §5.2`` 응답 ``updated_fields``).
UPDATED_FIELDS: tuple[str, ...] = (
    "planned_distance_nm",
    "planned_speed_kn",
    "planned_arrival_at",
)


async def _load_scenario(session: AsyncSession, scenario_id: UUID) -> VoyageScenario:
    stmt = select(VoyageScenario).where(
        VoyageScenario.id == scenario_id, VoyageScenario.is_deleted.is_(False)
    )
    scenario = (await session.execute(stmt)).scalars().first()
    if scenario is None:
        raise NotFoundError(f"시나리오를 찾을 수 없습니다: {scenario_id}")
    return scenario


def _arrival_at(voyage, scenario) -> datetime | None:
    """출발 예정 시각 + 소요 시간 = 도착 예정 시각.

    **출발 시각을 모르면 도착 시각도 모른다.** 지금 시각으로 채우면 계획이 「지금
    출발한다」로 바뀌는데, 그것은 시나리오가 말한 적 없는 값이다.
    """
    if voyage.planned_departure_at is None:
        return None
    from datetime import timedelta

    return voyage.planned_departure_at + timedelta(hours=float(scenario.duration_hours))


async def _clear_previous_adoption(session: AsyncSession, voyage_id: UUID) -> None:
    """그 항차의 이전 채택을 내린다 (모듈 docstring 참조)."""
    await session.execute(
        update(VoyageScenario)
        .where(VoyageScenario.voyage_id == voyage_id, VoyageScenario.is_adopted.is_(True))
        .values(is_adopted=False)
    )


async def adopt_scenario(
    session: AsyncSession,
    scenario_id: UUID,
    *,
    target_voyage_id: UUID,
    adopt_mode: str = MODE_UPDATE,
    departure_port_name: str | None = None,
    arrival_port_name: str | None = None,
    planned_departure_at: datetime | None = None,
) -> dict[str, object]:
    """시나리오를 항차 계획에 반영한다 (``API_SPEC §5.2``). 없으면 404.

    ``CREATE_NEW_VOYAGE``는 ``target_voyage_id``를 **원본**으로 삼아 새 항차를 만든다.
    §5.2가 그 모드에서 항구·출발 시각을 「추가 필요」로 적고 있어 세 값을 함께 받으며,
    **없으면 거부한다** — 기본값을 지어내면 사용자가 넣지 않은 계획이 생긴다.

    :raises StateTransitionError: 계획 단계가 아닌 항차에 반영하려 할 때.
    """
    if adopt_mode not in ADOPT_MODES:
        raise ValidationError(
            f"지원하지 않는 채택 모드입니다: {adopt_mode}. "
            f"{' · '.join(ADOPT_MODES)} 중 하나여야 합니다.",
            field="adopt_mode",
            field_label="채택 모드",
        )

    scenario = await _load_scenario(session, scenario_id)
    target = await voyage_repo.get_by_id(session, target_voyage_id)
    if target is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {target_voyage_id}")

    if target.vessel_id != scenario.vessel_id:
        # 다른 배의 시나리오를 반영하면 그 계획은 이 배의 제원으로 계산된 것이 아니다.
        raise ValidationError(
            "시나리오와 항차의 선박이 다릅니다.",
            field="target_voyage_id",
            field_label="대상 항차",
        )

    if adopt_mode == MODE_CREATE:
        voyage = await _create_from_scenario(
            session,
            scenario,
            source=target,
            departure_port_name=departure_port_name,
            arrival_port_name=arrival_port_name,
            planned_departure_at=planned_departure_at,
        )
        voyage_id = UUID(str(voyage["id"]))
    else:
        if target.status not in PLANNING_STATUSES:
            raise StateTransitionError(
                f"계획 단계 항차에만 반영할 수 있습니다 (현재 상태: {target.status}). "
                f"허용 상태: {' · '.join(sorted(PLANNING_STATUSES))}"
            )
        target.planned_distance_nm = scenario.distance_nm
        target.planned_speed_kn = scenario.speed_kn
        target.planned_arrival_at = _arrival_at(target, scenario)
        voyage_id = target.id

    await _clear_previous_adoption(session, voyage_id)
    scenario.is_adopted = True
    scenario.voyage_id = voyage_id

    # `API_SPEC §5.2` — 계획이 바뀌었으므로 그 항차의 계산 결과는 더 이상 현행이 아니다.
    marked = await voyage_repo.mark_calculations_needing_recalc(session, voyage_id)

    await session.commit()
    return {
        "voyage_id": str(voyage_id),
        "adopted_scenario_type": scenario.scenario_type,
        "updated_fields": list(UPDATED_FIELDS),
        "invalidated_calculation_runs": marked,
    }


async def _create_from_scenario(
    session: AsyncSession,
    scenario,
    *,
    source,
    departure_port_name: str | None,
    arrival_port_name: str | None,
    planned_departure_at: datetime | None,
) -> dict[str, object]:
    """시나리오 계획으로 **새 항차**를 만든다 (``API_SPEC §5.2`` ``CREATE_NEW_VOYAGE``).

    항구·출발 시각을 요구하는 이유는 §5.2가 그렇게 적어서만이 아니다 — 시나리오는
    거리·속도·연료만 갖고 있어 **어디서 어디로 언제 떠나는지를 모른다.** 원본 항차의
    값을 몰래 복사하면 사용자는 「새 항차를 만들었는데 옛 일정이 붙어 있는」 것을
    나중에 발견한다.
    """
    missing = [
        name
        for name, value in (
            ("departure_port_name", departure_port_name),
            ("arrival_port_name", arrival_port_name),
            ("planned_departure_at", planned_departure_at),
        )
        if value is None
    ]
    if missing:
        raise ValidationError(
            f"{MODE_CREATE}에는 다음 값이 필요합니다: {', '.join(missing)}",
            field=missing[0],
            field_label="신규 항차 정보",
        )

    from datetime import timedelta

    return await create_voyage(
        session,
        source.vessel_id,
        voyage_no=None,
        departure_port_name=departure_port_name,
        departure_lat=None,
        departure_lon=None,
        arrival_port_name=arrival_port_name,
        arrival_lat=None,
        arrival_lon=None,
        planned_distance_nm=scenario.distance_nm,
        planned_speed_kn=scenario.speed_kn,
        planned_departure_at=planned_departure_at,
        planned_arrival_at=planned_departure_at + timedelta(hours=float(scenario.duration_hours)),
        regulation_year=source.regulation_year,
        # 연료는 시나리오의 추정값이다 — 계획 연료로 넣되 출처를 남긴다.
        fuel_uses=[
            {
                "fuel_type": source_fuel,
                "planned_fuel_ton": scenario.fuel_ton,
                "source": "MODEL_ESTIMATE",
            }
            for source_fuel in (await _source_fuel_type(session, source),)
        ],
        notes=None,
        created_from="FEATURE_2_ADOPTED",
    )


async def _source_fuel_type(session: AsyncSession, source) -> str:
    """원본 항차의 연료 코드. 없으면 선박 기본 연료.

    시나리오 행에는 연료 **종류**가 없다(`DB_SCHEMA §2.4`는 양만 갖는다). 종류를
    지어내면 CF가 달라져 **채택 전후의 CO₂가 어긋난다.**
    """
    fuel_uses = await voyage_repo.list_fuel_uses(session, source.id)
    if fuel_uses:
        return fuel_uses[0].fuel_type

    from cii_platform.db.repositories import vessel as vessel_repo

    vessel = await vessel_repo.get_by_id(session, source.vessel_id)
    if vessel is None or not vessel.default_fuel_type:
        raise ValidationError(
            "새 항차에 쓸 연료 종류를 알 수 없습니다. 원본 항차나 선박에 기본 연료가 필요합니다.",
            field="target_voyage_id",
            field_label="대상 항차",
        )
    return vessel.default_fuel_type
