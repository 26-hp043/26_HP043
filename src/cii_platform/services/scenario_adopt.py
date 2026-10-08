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

## 계획 연료도 함께 바꾼다 (#1072)

종전에는 `UPDATE_EXISTING_PLAN`이 거리·속력·도착시각만 바꾸고 **계획 연료를 그대로
두었다.** 같은 시나리오인데 `CREATE_NEW_VOYAGE`는 시나리오 연료를 쓰므로 **채택 방식에
따라 연간 결과가 갈렸다** — 우회(거리↑) 시나리오는 「새 거리 + 옛 연료」가 되어 CII가
실제보다 좋게, 감속(연료↓) 시나리오는 나쁘게 나왔다.

화면이 도달하는 경로는 `UPDATE_EXISTING_PLAN` 하나뿐인데(`UIFLOW 2-2` · `#580`) 그쪽이
틀린 쪽이었다. 화면이 보여 준 개선이 사용자 데이터에서 재현되지 않는 자리 —
`PRD §2.3` 「계산 가능성」이 깨진다.

## 계산 결과를 무효화한다

`API_SPEC §5.2`가 「채택 시 해당 Voyage의 계산 결과는 무효화되고 재계산 필요 표시가
설정된다(`PRD §8.4`)」고 규정한다. 표시는 `calculation_run.needs_recalc`이며
false→true 플립만 허용된다(마이그레이션 024 가드).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update

from cii_platform.calc.precision import layer1_context
from cii_platform.db.models.voyage_scenario import VoyageScenario
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError
from cii_platform.services.voyage import PLANNING_STATUSES, create_voyage
from cii_platform.validation.bounds import VOYAGE_FUEL

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

#: ``API_SPEC §5.2`` — 지원 모드. 기본값은 ``UPDATE_EXISTING_PLAN``이다
#: (``UPDATE_EXISTING``이 아니다 — 이슈 본문이 특히 짚은 지점).
MODE_UPDATE = "UPDATE_EXISTING_PLAN"
MODE_CREATE = "CREATE_NEW_VOYAGE"
ADOPT_MODES: tuple[str, ...] = (MODE_UPDATE, MODE_CREATE)

#: 계획값을 바꿀 수 있는 상태. 모듈 docstring 참조.
# PLANNING_STATUSES는 services/voyage.py에서 import한다 — #865에서 PATCH 가드가
# 같은 상수를 쓰며, 두 경로의 기준이 갈리면 한쪽만 막힌다.

#: 채택이 바꾸는 항차 필드 (``API_SPEC §5.2`` 응답 ``updated_fields``).
#:
#: ``planned_fuel_ton``은 항차 행이 아니라 ``voyage_fuel_use``의 열이지만 **사용자가
#: 「무엇이 바뀌었나」로 읽는 단위**라 같은 목록에 둔다 (#1072).
FIELD_PLANNED_FUEL = "planned_fuel_ton"

FIELD_PLANNED_ARRIVAL = "planned_arrival_at"

UPDATED_FIELDS: tuple[str, ...] = (
    "planned_distance_nm",
    "planned_speed_kn",
    FIELD_PLANNED_ARRIVAL,
    FIELD_PLANNED_FUEL,
)

#: 시나리오가 준 연료의 출처. ``CREATE_NEW_VOYAGE``가 쓰는 값과 **같다** — 두 경로가
#: 같은 값을 남겨야 「채택 방식에 따라 결과가 갈리지 않는다」가 성립한다 (#1072).
SOURCE_MODEL_ESTIMATE = "MODEL_ESTIMATE"

#: ``voyage_fuel_use.planned_fuel_ton``은 ``NUMERIC(12,4)``다 (`schemas/bounds.py`).
_FUEL_STEP = VOYAGE_FUEL["ge"]


async def _load_scenario(session: AsyncSession, scenario_id: UUID) -> VoyageScenario:
    stmt = select(VoyageScenario).where(
        VoyageScenario.id == scenario_id, VoyageScenario.is_deleted == 0
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
        .where(VoyageScenario.voyage_id == voyage_id, VoyageScenario.is_adopted == 1)
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
    # 대상 항차 행을 먼저 잠그고 읽는다 (`#1626` · `TECH_SPEC §16.3`). 「항차당 채택 하나」는
    # 아래 `_clear_previous_adoption` → 자기 행 채택이 **항차 행 잠금 안에서** 순서대로
    # 일어나는 것으로 지킨다 — 잠금 없이 두 채택이 교차하면 해제 UPDATE가 둘 다 0건이고
    # 채택 행이 둘 남는다(`#1796` ⑺ 실측). 시나리오 행은 잠그지 않는다(불변식의 단위가
    # 항차다). `CREATE_NEW_VOYAGE`도 같은 갈래를 탄다 — 원본 항차의 연료 행을 읽는 동안
    # 원본이 바뀌지 않게 하는 데 같은 잠금이 든다. 선박 행은 그 갈래가 **항차보다 먼저**
    # 잠근다(`#1860` → `#1868`) — 새 항차 INSERT(`#1860` ⑻)도, 모든 모드가 지나는
    # `voyage`·`voyage_scenario` UPDATE(`#1868` ⑽-b)도 FK 검사로 선박 S를 요구하므로,
    # 선박 X를 쥔 채 이 항차를 참조하는 구간을 넣는 정박 구간 생성과 교착하지 않게
    # 순서를 선박 → 항차로 맞춘 것이다. 종전에는 CREATE 갈래만 여기서 따로 잠갔다.
    target = await voyage_repo.get_by_id(session, target_voyage_id, for_update=True)
    if target is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {target_voyage_id}")

    if target.vessel_id != scenario.vessel_id:
        # 다른 배의 시나리오를 반영하면 그 계획은 이 배의 제원으로 계산된 것이 아니다.
        raise ValidationError(
            "시나리오와 항차의 선박이 다릅니다.",
            field="target_voyage_id",
            field_label="대상 항차",
        )

    updated_fields = list(UPDATED_FIELDS)
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
        # 거리 출처는 「모른다」로 돌린다 (#1256). `voyage_scenario` 행은 직항 거리가 좌표
        # 대권거리였는지 입력값이었는지를 갖고 있지 않고(`scenario_compare._resolve_direct_distance`
        # 의 분기는 저장되지 않는다), 옛 출처를 새 숫자에 남기면 거짓말이다(`update_voyage`와
        # 같은 규칙).
        target.planned_distance_source = None
        target.planned_speed_kn = scenario.speed_kn
        # 출항 예정 시각이 없으면 도착 예정 시각은 **건드리지 않는다** — 종전에는 `None`으로
        # 덮어써 사용자가 적어 둔 값이 지워지고도 「바꿨다」고 보고됐다 (#2091).
        arrival_at = _arrival_at(target, scenario)
        if arrival_at is None:
            updated_fields.remove(FIELD_PLANNED_ARRIVAL)
        else:
            target.planned_arrival_at = arrival_at
        # 연료도 바꾼다 (#1072) — 종전에는 이 줄이 없어 「새 거리 + 옛 연료」가 남았다.
        if not await _apply_scenario_fuel(session, target, scenario):
            # 넣을 연료 종류를 몰라 건너뛴 경우다. **바꾸지 않은 것을 바꿨다고 적지 않는다.**
            updated_fields.remove(FIELD_PLANNED_FUEL)
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
        "updated_fields": updated_fields,
        "invalidated_calculation_runs": marked,
    }


@layer1_context
def _fuel_shares(total: Decimal, weights: list[Decimal]) -> dict[int, Decimal]:
    """시나리오 총량을 비중대로 나눈 **행 번호 → 몫**. 비중이 0인 행은 들어 있지 않다.

    규칙은 :func:`_apply_scenario_fuel`의 「0을 넣지 않는다」·「총량을 정확히 보존한다」다 —
    돌려주는 몫은 **전부 최소 저장 단위(``0.0001`` t) 이상**이고 **합은 총량과 같다.**

    ``total``은 ``voyage_scenario.fuel_ton``(``NUMERIC(12,4)`` · ``chk_scenario_fuel_positive``)
    이라 **``0.0001`` 이상이고 4자리 격자 위에 있다.** 격자 밖 값은 이 함수가 받지 않는다 —
    「합 = 총량」을 격자 위에서 만들 수 없기 때문이다(`#2275`).

    ## 보통 갈래 — 4자리 반올림 + 잔차 흡수

    몫을 4자리로 반올림하고, 잔차는 비중이 가장 큰 행이 흡수한다. 반올림으로 0이 된 몫은
    ``0.0001``로 올린다. 총량이 넉넉하면 흡수한 행도 ``0.0001`` 이상이라 그대로 끝난다.

    ## 작은 총량 갈래 — ``0.0001`` 단위로 채운다

    총량이 작으면 잔차를 흡수한 행이 ``0.0001`` 아래로 내려간다(총량이 「양수 비중 행 수 ×
    0.0001」보다 작을 때는 반드시, 그 두 배 아래에서도 비중에 따라). 종전에는 그 행을 다시
    ``0.0001``로 올려 **합이 총량을 넘었다**(`#2275`). 지금은 총량을 ``0.0001`` 단위 수로 보고
    비중이 큰 행부터(같으면 앞 행부터) 채운다 —

    - 단위 수가 양수 비중 행 수보다 적으면 **앞에서부터 한 단위씩** 주고 **몫이 0이 되는 행은
      결과에서 뺀다**(``chk_fuel_positive``가 0을 거부한다) — 그 행의 계획값은
      :func:`_apply_scenario_fuel`이 ``NULL``로 비운다
    - 그렇지 않으면 **모든 행이 한 단위씩** 받고, 남는 단위를 비중대로 내림해 나눈 뒤 나머지를
      소수부가 큰 행부터 한 단위씩 더 준다

    보통 갈래가 ``0.0001`` 이상으로 끝나는 입력은 이 갈래를 타지 않으므로 종전 결과가 그대로다.

    몫은 **나눗셈으로 새로 만들어 저장하는 값**이라 Layer 1 컨텍스트 안에서 낸다
    (`#2254` · `TECH_SPEC §1.2.1`). :func:`_apply_scenario_fuel`은 코루틴이라 데코레이터를
    달 수 없다 — 컨텍스트가 코루틴 객체를 만드는 동안에만 걸리고 본문이 도는 동안에는
    풀려 있다.
    """
    if total < _FUEL_STEP or total != total.quantize(_FUEL_STEP):
        raise ValueError(f"시나리오 연료 총량이 저장 형식(0.0001 t 격자)의 값이 아니다: {total}")
    weight_sum = sum(weights)
    positive = [index for index, weight in enumerate(weights) if weight > 0]
    shares: dict[int, Decimal] = {}
    for index in positive:
        share = (total * weights[index] / weight_sum).quantize(_FUEL_STEP, rounding=ROUND_HALF_UP)
        shares[index] = max(share, _FUEL_STEP)

    # 잔차는 비중이 가장 큰 행이 흡수한다.
    anchor = max(positive, key=lambda index: (weights[index], -index))
    shares[anchor] += total - sum(shares.values())
    if shares[anchor] >= _FUEL_STEP:
        return shares

    # 작은 총량 갈래 — 흡수한 행이 최소 저장 단위 아래로 내려갔다.
    ranked = sorted(positive, key=lambda index: (-weights[index], index))
    units = int(total / _FUEL_STEP)
    if units < len(positive):
        return {index: _FUEL_STEP for index in ranked[:units]}
    positive_sum = sum(weights[index] for index in positive)
    exact = {index: (units - len(positive)) * weights[index] / positive_sum for index in positive}
    counts = {index: int(exact[index]) for index in positive}
    leftover = units - len(positive) - sum(counts.values())
    by_fraction = sorted(
        positive, key=lambda index: (counts[index] - exact[index], -weights[index], index)
    )
    for index in by_fraction[:leftover]:
        counts[index] += 1
    return {index: _FUEL_STEP * (1 + counts[index]) for index in positive}


async def _apply_scenario_fuel(session: AsyncSession, target, scenario) -> bool:
    """채택한 시나리오의 연료량을 항차의 **계획 연료**로 옮긴다 (#1072).

    돌려주는 값은 **실제로 바꿨는가**다. 응답 ``updated_fields``가 그 값을 따라간다 —
    바꾸지 않았는데 바꿨다고 적으면 사용자가 확인할 수 없는 거짓이 된다.

    ## 유종이 여럿이면 기존 비중대로 안분한다

    시나리오 행에는 연료 **종류**가 없다(`DB_SCHEMA §2.4`는 양만 갖는다). 그래서 종류는
    항차가 이미 가진 것을 그대로 두고 **양만** 시나리오 값으로 바꾼다. 비중을 유지하면
    채택 전후로 **CF 혼합이 바뀌지 않아** CO₂ 차이가 오직 연료량에서만 나온다 — 종류를
    지어내거나 한 유종에 몰아넣으면 그 차이에 CF 변화가 섞여 시나리오가 말한 개선과
    다른 수가 남는다.

    ## 0을 넣지 않는다

    ``chk_fuel_positive``(마이그레이션 046)가 ``planned_fuel_ton IS NULL OR > 0``을
    강제한다. 그래서:

    - **비중이 0이거나 비어 있는 행은 건드리지 않는다.** 원래 값(``NULL`` 또는 옛 값)을
      그대로 두고, 시나리오 총량은 **양수 비중을 가진 행들에만** 나눈다. 0으로 덮으면
      트리거가 거부해 채택 자체가 500이 된다
    - 반올림으로 0.0000이 되는 몫은 최소 저장 단위(``0.0001``)로 올린다
    - 총량이 너무 작아 몫을 받지 못한 양수 비중 행은 **``NULL``로 비운다** — 0은 거부되고
      옛 값을 두면 총량이 보존되지 않는다(`#2275`)

    ## 총량을 정확히 보존한다

    4자리로 반올림한 몫을 그대로 더하면 합이 시나리오 총량과 어긋난다. **가장 비중이 큰
    행에 잔차를 얹어** 합을 총량과 같게 맞춘다. 총량이 작아 그 행이 ``0.0001`` 아래로
    내려가면 **``0.0001`` 단위로 비중이 큰 행부터 채워** 합을 맞춘다 — 이때 몫을 받지
    못한 양수 비중 행은 **계획값을 ``NULL``로 비워** 양수 비중이던 행 전체의 계획 연료 합이
    총량과 같게 한다(`#2275`). 비중이 0이거나 원래 비어 있던 행은 종전대로 건드리지 않는다.
    순서는 ``list_fuel_uses``(유종순 · `#867`)를 따르므로 같은 입력이면 같은 결과가 나온다.
    """
    rows = await voyage_repo.list_fuel_uses(session, target.id)
    total = Decimal(scenario.fuel_ton)

    if not rows:
        # 연료 행이 아예 없는 항차다 — CSV로 항차만 먼저 올린 경우에 실제로 나온다
        # (`#1095` ⑵). `CREATE_NEW_VOYAGE`와 **같은 규칙**으로 종류를 정해 한 행을 만든다:
        # 그러지 않으면 이 경로만 「연료가 안 바뀌는」 종전 상태로 남는다.
        #
        # 🔴 **종류를 모르면 채택을 막지 않는다.** 원본 항차에도 연료가 없고 선박에 기본
        # 연료도 없으면 넣을 종류가 없는데, 그 때문에 거리·속력·도착시각 갱신까지 거부하면
        # **사용자가 하려던 일 전체가 막힌다** — 채택의 본체는 계획값 갱신이다. 연료만
        # 건너뛰고 그 사실을 `updated_fields`로 알린다. (`CREATE_NEW_VOYAGE`는 다르다 —
        # 연료 종류 없이 **새 항차를 만들 수 없어** 거기서는 오류가 맞다.)
        fuel_type = await _source_fuel_type(session, target, required=False)
        if fuel_type is None:
            return False
        fuel_rows = await param_repo.get_fuel_types_by_codes(session, (fuel_type,))
        if fuel_type not in fuel_rows:
            # 비활성으로 내려간 연료다 — 새 계획값에 죽은 코드를 심지 않는다.
            return False
        await voyage_repo.insert_fuel_use(
            session,
            voyage_id=target.id,
            fuel_type=fuel_type,
            planned_fuel_ton=total,
            actual_fuel_ton=None,
            cf_used=Decimal(str(fuel_rows[fuel_type].cf)),
            source=SOURCE_MODEL_ESTIMATE,
        )
        return True

    weights = [Decimal(row.planned_fuel_ton or 0) for row in rows]
    if sum(weights) <= 0:
        # 비중이 될 값이 하나도 없다 — 기존 혼합이 **없으므로** 균등이 중립적인 선택이다.
        weights = [Decimal(1)] * len(rows)

    shares = _fuel_shares(total, weights)
    for index, row in enumerate(rows):
        if index in shares:
            row.planned_fuel_ton = shares[index]
            row.source = SOURCE_MODEL_ESTIMATE
        elif weights[index] > 0:
            # 비중은 있었는데 총량이 너무 작아 몫을 받지 못한 행이다 — 옛 계획값을 두면 항차의
            # 계획 연료 합이 「옛 값 + 총량」이 된다. NULL로 비운다(`chk_fuel_positive`는 NULL을
            # 받는다 · `#2275`).
            row.planned_fuel_ton = None
            row.source = SOURCE_MODEL_ESTIMATE
    return True


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
        # 「모른다」(#1256) — 시나리오 행에는 직항 거리가 좌표 추정이었는지가 남아 있지 않다.
        planned_distance_source=None,
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
        # **여기서 커밋하지 않는다** (`#1349`). 호출부가 이어서 채택 표시·재계산 표시를
        # 쓰고 마지막에 한 번 커밋한다 — 종전에는 새 항차가 먼저 확정돼, 뒤 단계가
        # 실패하면 **채택 기록 없는 DRAFT 항차**가 남았다.
        commit=False,
    )


async def _source_fuel_type(session: AsyncSession, source, *, required: bool = True) -> str | None:
    """원본 항차의 연료 코드. 없으면 선박 기본 연료.

    ``required=False``면 알 수 없을 때 오류 대신 ``None``을 돌려준다 (#1072) —
    호출부가 「연료만 건너뛴다」를 고를 수 있어야 하는 자리가 있다.

    시나리오 행에는 연료 **종류**가 없다(`DB_SCHEMA §2.4`는 양만 갖는다). 종류를
    지어내면 CF가 달라져 **채택 전후의 CO₂가 어긋난다.**
    """
    fuel_uses = await voyage_repo.list_fuel_uses(session, source.id)
    if fuel_uses:
        return fuel_uses[0].fuel_type

    vessel = await vessel_repo.get_by_id(session, source.vessel_id)
    if vessel is None or not vessel.default_fuel_type:
        if not required:
            return None
        raise ValidationError(
            "새 항차에 쓸 연료 종류를 알 수 없습니다. 원본 항차나 선박에 기본 연료가 필요합니다.",
            field="target_voyage_id",
            field_label="대상 항차",
        )
    return vessel.default_fuel_type
