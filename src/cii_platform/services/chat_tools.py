"""챗봇 도구 4종 (`#121` · `Q9` ⓐ).

## 쓰기 도구를 넣지 않는다

`#121` 본문은 ``create_voyage``를 도구 목록에 적었으나 **빼기로 정했다**(`Q9`).

- 실험 기능(MAY)이 **데이터를 만드는 경로**를 갖는 것은 ``PRD §16.2`` 장애 격리
  정신과 어긋난다. 챗봇이 죽었을 때 **「만들다 만 항차」**가 남으면 격리가 아니다.
- 항차 생성은 입력이 많다. 자연어로 받으면 **오입력 위험이 화면보다 크다** —
  화면이 더 나은 도구인 작업이다.
- 필요해지면 나중에 도구를 더하는 건 쉽다. 반대로 **잘못 만들어진 항차를 되돌리는
  것은 사용자 일**이다.

## ⚠️ 봉투와 도메인 값을 가른다

``services/llm_guard.filter_outbound``는 **도메인 값**에만 건다. 도구 응답의 구조
봉투(``ok``·``error``·``tool``)는 화이트리스트 대상이 **아니다** — 그것까지 목록에
넣으면 ``PRD §16.3.1``이 「선사 기밀을 막는 목록」이 아니라 「응답 스키마」가 되고,
목록의 뜻이 흐려진다.

경계는 하나다 — **선박·항차·연료·조직에서 온 값은 전부 도메인**이고 필터를 지난다.
봉투에는 **우리가 만든 상수만** 담는다. 이 규칙을 어기면(봉투에 선박명을 넣으면)
화이트리스트가 통째로 무의미해지므로, ``tests/test_chat_tools_db.py``가 그것을 막는다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.errors import CalculationError, NotFoundError, ParameterError, ValidationError
from cii_platform.services.llm_guard import filter_outbound

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: 도구 이름 — `Q9` 확정 4종.
TOOL_SEARCH_VESSEL = "search_vessel"
TOOL_CALC_VOYAGE_CII = "calc_voyage_cii"
TOOL_COMPARE_SCENARIOS = "compare_scenarios"
TOOL_RUN_ANNUAL_SIMULATION = "run_annual_simulation"

TOOL_NAMES: tuple[str, ...] = (
    TOOL_SEARCH_VESSEL,
    TOOL_CALC_VOYAGE_CII,
    TOOL_COMPARE_SCENARIOS,
    TOOL_RUN_ANNUAL_SIMULATION,
)


def tool_schemas() -> list[dict[str, object]]:
    """모델에게 주는 도구 목록.

    **설명은 한국어로 적는다** — 사용자가 한국어로 묻고, 모델이 도구를 고르는 근거가
    이 설명이다. 영어로 적으면 한 번 더 번역해 판단하게 된다.
    """
    return [
        {
            "name": TOOL_SEARCH_VESSEL,
            "description": (
                "선박을 이름으로 찾아 이 대화에서 쓸 수 있게 한다. "
                "⚠️ 선박명·IMO·식별자는 돌려주지 않는다 — 몇 척을 찾았는지만 알려 준다. "
                "계산 도구는 찾은 선박을 서버가 알아서 쓴다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "선박 이름 일부"}},
                "required": ["name"],
            },
        },
        {
            "name": TOOL_CALC_VOYAGE_CII,
            "description": (
                "한 항차의 CII를 추정한다(기능①). 거리·속도·연료를 받아 attained/required와 "
                "등급을 돌려준다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "distance_nm": {"type": "number", "description": "항해 거리(해리)"},
                    "speed_kn": {"type": "number", "description": "평균 속력(노트)"},
                    "fuel_type": {"type": "string", "description": "유종 코드 (예: HFO)"},
                    "fuel_ton": {"type": "number", "description": "연료 소모량(톤)"},
                    "regulation_year": {"type": "integer", "description": "규제 연도"},
                },
                "required": ["distance_nm", "speed_kn", "fuel_type", "fuel_ton"],
            },
        },
        {
            "name": TOOL_COMPARE_SCENARIOS,
            "description": (
                "속도 시나리오 셋을 비교한다(기능②). "
                "⚠️ 어느 쪽이 더 낫다고 말하지 않는다 — 수치만 돌려준다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "current_speed_kn": {"type": "number"},
                    "fuel_type": {"type": "string"},
                    "direct_distance_nm": {"type": "number"},
                    "base_daily_foc_ton": {"type": "number"},
                    "regulation_year": {"type": "integer"},
                },
                "required": ["current_speed_kn", "fuel_type"],
            },
        },
        {
            "name": TOOL_RUN_ANNUAL_SIMULATION,
            "description": "연말 등급 예상을 낸다(기능③). 지금까지의 실적에서 연말을 내다본다.",
            "input_schema": {
                "type": "object",
                "properties": {"regulation_year": {"type": "integer"}},
                "required": [],
            },
        },
    ]


def _regulation_year(arguments: dict[str, object]) -> int:
    """모델이 연도를 말하지 않으면 **올해**로 본다.

    상수로 박지 않는다 — 해가 바뀌면 틀린 해를 계산하고, 그 사실이 화면 어디에도
    드러나지 않는다. ``cii_current``가 ``as_of.year``로 같은 판단을 한다.
    """
    raw = arguments.get("regulation_year")
    return datetime.now(UTC).year if raw is None else int(raw)


def envelope(
    tool: str, *, result: dict[str, object] | None = None, error: str | None = None
) -> str:
    """도구 응답을 봉투에 담아 **문자열**로 만든다.

    문자열로 만드는 이유 — 수학 검증 가드(``verify_numbers``)가 **도구 응답의 수치를
    문자열에서 찾는다.** 구조를 유지한 채 넘기면 가드가 볼 수 있는 형태가 아니다.

    ``result``는 :func:`~cii_platform.services.llm_guard.filter_outbound`를 **이미
    지난 값**이어야 한다 — 이 함수는 필터하지 않는다(봉투의 책임이 아니다).
    """
    body: dict[str, object] = {"tool": tool, "ok": error is None}
    if error is not None:
        body["error"] = error
    if result is not None:
        body["result"] = result
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


#: API 응답 필드명 → ``PRD §16.3.1`` 화이트리스트 이름.
#:
#: ⚠️ **이름이 갈려 있다.** 정본은 개념 이름(``rating``·``next_boundary_gap``)으로
#: 적혀 있고 API 응답은 구현 이름(``estimated_rating``·
#: ``next_worse_boundary_margin_ratio``)을 쓴다. **경계에서 맞춘다** — 화이트리스트를
#: 넓히는 쪽은 고르지 않았다. 목록에 구현 이름을 더하면 *같은 값이 두 이름으로* 허용
#: 목록에 남고, 나중에 API 필드명을 바꿀 때 정본까지 따라 바뀌어야 한다.
_PUBLISH_MAP: dict[str, str] = {
    "attained_cii": "attained_cii",
    "required_cii": "required_cii",
    "rating": "rating",
    "estimated_rating": "rating",
    "risk_level": "risk_level",
    "next_worse_boundary_margin_ratio": "next_boundary_gap",
}


#: 도구가 내보내는 값 — **모든 도구가 같은 묶음을 쓴다.**
#:
#: 도구마다 다른 묶음을 고르면 「이 도구는 위험도를 주고 저 도구는 안 준다」가 되어
#: 모델이 없는 값을 찾다가 왕복을 더 쓴다(``PRD §16.1`` 가드 2 · 호출 상한).
_RESULT_KEYS: tuple[str, ...] = (
    "attained_cii",
    "required_cii",
    "rating",
    "estimated_rating",
    "risk_level",
    "next_worse_boundary_margin_ratio",
)


def _publishable(payload: dict[str, object], keys: tuple[str, ...]) -> dict[str, object]:
    """응답에서 화이트리스트 대상 값만 뽑아 **이름을 맞춘 뒤** 필터를 태운다.

    :param keys: **API 응답 쪽 필드명**. :data:`_PUBLISH_MAP`이 정본 이름으로 옮긴다.

    필터를 마지막에 거는 것이 중요하다 — 옮긴 뒤에 걸어야 ``filter_outbound``가
    **실제로 나가는 이름**을 본다. 옮기기 전에 걸면 통과한 이름과 나가는 이름이 달라
    가드가 헛돈다.
    """
    picked = {
        _PUBLISH_MAP[key]: payload[key]
        for key in keys
        if key in _PUBLISH_MAP and payload.get(key) is not None
    }
    return filter_outbound(picked)


async def run_tool(
    session: AsyncSession,
    *,
    name: str,
    arguments: dict[str, object],
    vessel_id: object | None,
) -> str:
    """도구 하나를 실행하고 **봉투에 담은 문자열**을 돌려준다.

    :param vessel_id: 이 대화가 고른 선박. ``search_vessel``이 정하거나 화면이 준다.
        **모델에게는 넘기지 않는다** — 식별자는 화이트리스트 밖이다.

    ## 실패를 자연어로 돌려주지 않는다

    오류는 **봉투의 ``error``**로 간다. 모델이 그것을 읽고 사용자에게 설명한다 —
    서버가 문장을 만들면 같은 말을 두 곳에서 쓰게 된다(`#121` 「에러 처리: API 호출
    실패 시 자연어로 안내」).
    """
    if name not in TOOL_NAMES:
        return envelope(name, error="알 수 없는 도구입니다.")

    try:
        if name == TOOL_SEARCH_VESSEL:
            return await _search_vessel(session, arguments)
        if vessel_id is None:
            return envelope(name, error="어느 선박인지 먼저 정해야 합니다.")
        if name == TOOL_CALC_VOYAGE_CII:
            return await _calc_voyage_cii(session, arguments, vessel_id)
        if name == TOOL_COMPARE_SCENARIOS:
            return await _compare_scenarios(session, arguments, vessel_id)
        return await _run_annual_simulation(session, arguments, vessel_id)
    except (ValidationError, NotFoundError, ParameterError, CalculationError) as exc:
        # 도메인 오류는 사용자에게 설명할 수 있는 것이다 — 문구를 그대로 넘긴다.
        return envelope(name, error=str(exc))


async def _search_vessel(session: AsyncSession, arguments: dict[str, object]) -> str:
    """⚠️ **이름·식별자를 돌려주지 않는다.** 몇 척인지만 말한다.

    ``PRD §16.3.1``이 선박명·IMO·선박 ID를 전송 금지로 둔다. 검색 결과를 그대로
    돌려주면 **그 금지가 도구 하나로 뚫린다.** 선박을 고르는 것은 서버가 하고, 모델은
    「찾았다」만 안다.
    """
    from cii_platform.services import vessel as vessel_service

    keyword = str(arguments.get("name") or "").strip()
    if not keyword:
        return envelope(TOOL_SEARCH_VESSEL, error="찾을 이름을 알려 주세요.")
    rows, _ = await vessel_service.list_vessels(session, search=keyword, limit=5)
    return envelope(TOOL_SEARCH_VESSEL, result={"matched": len(rows)})


async def _calc_voyage_cii(
    session: AsyncSession, arguments: dict[str, object], vessel_id: object
) -> str:
    from cii_platform.services.voyage_cii import (
        FuelUseInput,
        VoyageCiiInput,
        estimate_voyage_cii,
    )

    payload = VoyageCiiInput(
        vessel_id=vessel_id,  # type: ignore[arg-type]
        regulation_year=_regulation_year(arguments),
        distance_nm=Decimal(str(arguments["distance_nm"])),
        speed_kn=Decimal(str(arguments["speed_kn"])),
        fuel_uses=(
            FuelUseInput(
                fuel_type=str(arguments["fuel_type"]),
                fuel_ton=Decimal(str(arguments["fuel_ton"])),
            ),
        ),
    )
    response = await estimate_voyage_cii(session, payload)
    data = response.get("data") or {}
    return envelope(
        TOOL_CALC_VOYAGE_CII,
        result=_publishable(
            data,  # type: ignore[arg-type]
            _RESULT_KEYS,
        ),
    )


async def _compare_scenarios(
    session: AsyncSession, arguments: dict[str, object], vessel_id: object
) -> str:
    from cii_platform.services.scenario_compare import ScenarioCompareInput, compare_scenarios

    def _decimal(key: str) -> Decimal | None:
        raw = arguments.get(key)
        return None if raw is None else Decimal(str(raw))

    payload = ScenarioCompareInput(
        vessel_id=vessel_id,  # type: ignore[arg-type]
        regulation_year=_regulation_year(arguments),
        current_speed_kn=Decimal(str(arguments["current_speed_kn"])),
        fuel_type=str(arguments["fuel_type"]),
        direct_distance_nm=_decimal("direct_distance_nm"),
        base_daily_foc_ton=_decimal("base_daily_foc_ton"),
    )
    response = await compare_scenarios(session, payload)
    scenarios = (response.get("data") or {}).get("scenarios") or []  # type: ignore[union-attr]
    # ⚠️ 시나리오를 **순위로 정렬하지 않는다** — 순위화는 No-Advice 금지 항목이다.
    return envelope(
        TOOL_COMPARE_SCENARIOS,
        result={"scenarios": [_publishable(row, _RESULT_KEYS) for row in scenarios]},
    )


async def _run_annual_simulation(
    session: AsyncSession, arguments: dict[str, object], vessel_id: object
) -> str:
    from cii_platform.services.cii_current import get_current_cii

    # ⚠️ ``data``에는 ``vessel_name``이 들어 있다 — **통째로 넘기지 않는다.**
    # ⑶ 블록만 꺼내 필터를 태운다.
    data, _meta = await get_current_cii(
        session,
        vessel_id,  # type: ignore[arg-type]
        year=_regulation_year(arguments),
    )
    year_end = data.get("year_end_projection") or {}
    if not isinstance(year_end, dict) or not year_end.get("data_available"):
        # 못 낸 사유는 **코드 그대로** 넘긴다. 서버가 문장을 만들지 않는다.
        reason = (year_end or {}).get("reason") if isinstance(year_end, dict) else None
        return envelope(
            TOOL_RUN_ANNUAL_SIMULATION,
            error=f"연말 예상을 낼 수 없습니다 (사유 코드: {reason or 'UNKNOWN'}).",
        )
    return envelope(TOOL_RUN_ANNUAL_SIMULATION, result=_publishable(year_end, _RESULT_KEYS))
