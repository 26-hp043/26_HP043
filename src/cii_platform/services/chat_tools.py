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
봉투에는 **우리가 만든 상수만** 담는다. ⚠️ **오류 문구도 마찬가지다** — 도메인 오류의
원문에는 식별자가 흔히 들어 있어, 그대로 넘기면 화이트리스트가 오류 경로로 뚫린다
(아래 :data:`_ERROR_TEXT`). 이 규칙을 어기면(봉투에 선박명을 넣으면)
화이트리스트가 통째로 무의미해지므로, ``tests/test_chat_tools_db.py``가 그것을 막는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.errors import CalculationError, NotFoundError, ParameterError, ValidationError
from cii_platform.services.llm_guard import filter_outbound

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: 도구 이름 — `Q9` 확정 4종.
TOOL_SEARCH_VESSEL = "search_vessel"
TOOL_CALC_VOYAGE_CII = "calc_voyage_cii"
TOOL_COMPARE_SCENARIOS = "compare_scenarios"
#: `#1534`(결정요청 v6 `D-32`) — 이 도구는 몬테카를로 확률이 아니라 **결정론
#: 연말 예상**(확정 실적 + 잔여 계획, `PRD §3.3` ⑶)을 낸다. 종전 이름
#: ``run_annual_simulation``이 `PRD §12`의 확률 시뮬레이션을 가리키고 있었다.
TOOL_PROJECT_YEAR_END = "project_year_end"

TOOL_NAMES: tuple[str, ...] = (
    TOOL_SEARCH_VESSEL,
    TOOL_CALC_VOYAGE_CII,
    TOOL_COMPARE_SCENARIOS,
    TOOL_PROJECT_YEAR_END,
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
                "찾은 선박이 1척이면 이 대화에서 계속 쓴다. "
                "여러 척이면 화면에서 골라야 한다."
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
            "name": TOOL_PROJECT_YEAR_END,
            "description": (
                "연말 예상 등급을 낸다. 확정된 실적에 남은 계획 항차를 더해 외삽하는 "
                "결정론 계산이며, 확률이 아니다."
            ),
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
    if raw is None:
        return datetime.now(UTC).year
    try:
        return int(raw)  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        # `#1334` ⑴ — 「2026년」처럼 오면 `ValueError`다. 종전에는 500이 됐다.
        raise ToolArgumentError("regulation_year") from exc


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


#: 비율로 내려가는 값 — 화면은 **백분율로 보여 준다**.
_GAP_KEY = "next_boundary_gap"

#: 화면의 백분율 자릿수 (`DESIGN_SYSTEM §4.1` · ``DISPLAY_DIGITS.percent`` = 1).
_PERCENT_QUANTUM = Decimal("0.1")


def _with_screen_percent(value: object) -> object:
    """비율 값에 **화면 표기를 덧붙인다** (`#1334` ⑵).

    ``"0.012345"`` → ``"0.012345 (1.2%)"``

    ## 왜 필요한가

    수치 가드(``verify_numbers``)는 도구 응답 **문자열**에서 수치를 찾는다. 화면은
    ``formatPercent(marginRatio)``로 ``1.2%``를 쓰는데 도구는 ``0.012345``만
    줬으므로, 모델이 **화면과 같은 표기로 답하면 폐기됐다**(실측).

    ``_rounded_forms``가 같은 문제를 이미 한 번 겪었다 — *「화면과 같은 자릿수로
    말할 수 없으면 면책이 거짓이 된다」*(``PRD §6.3``). **자릿수는 고쳤는데 단위는
    고치지 않은 것**이라, 같은 해법을 쓴다.

    ## 왜 새 키를 만들지 않는가

    ``PRD §16.3.1`` 화이트리스트는 **키 이름**을 검사한다. 키를 늘리면 *같은 값이 두
    이름으로* 허용 목록에 남는다 — :data:`_PUBLISH_MAP` 주석이 이름 문제에서 이미
    기각한 형태다. 값 하나에 두 표기를 담으면 화이트리스트를 건드리지 않는다.

    ## 왜 가드를 넓히지 않는가

    가드가 ×100 표기를 **무조건** 허용하면 도구가 ``0.07``을 준 답에서 ``7%``도
    통과한다 — **다른 뜻의 수**다. 가드의 원칙은 「막을 것은 표기가 아니라
    **출처**」(``IT-CHAT-008``)이고, 여기서 바꾸는 것은 **출처 쪽**이다.
    """
    try:
        ratio = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):  # pragma: no cover - 문자열 수치만 온다
        return value
    percent = (ratio * 100).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
    return f"{value} ({percent}%)"


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
    gap = picked.get(_GAP_KEY)
    if gap is not None:
        picked[_GAP_KEY] = _with_screen_percent(gap)
    return filter_outbound(picked)


#: 도메인 오류 → **우리가 만든 고정 문구**.
#:
#: ⚠️ **원문을 그대로 넘기면 화이트리스트가 오류 경로로 뚫린다** (2026-09-13 실측).
#:
#: .. code-block:: text
#:
#:     {"error": "선박을 찾을 수 없습니다: 3d56c710-089e-4299-95b3-e48650318d45", ...}
#:                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#:     `PRD §16.3.1`이 `vessel_id`를 **전송 금지**로 둔 값이 그대로 외부 모델로 갔다.
#:
#: 도메인 오류 문구는 식별자를 흔히 담는다 — ``vessel_id``·``voyage_id``·
#: ``ship_type``·연료 코드·항만명이 전부 후보다. **어느 문구가 안전한지 목록으로
#: 관리하는 것은 성립하지 않는다** — 새 오류가 생길 때마다 검토가 필요하고, 빠뜨리면
#: 조용히 샌다(전송은 되돌릴 수 없다).
#:
#: 그래서 **종류별 고정 문구**로 바꾼다. 봉투의 원칙(「우리가 만든 상수만 담는다」)이
#: 오류 칸에도 그대로 선다.
#:
#: **잃는 것** — 구체성이다. 「속력은 1.0 이상이어야 합니다」가 「입력값이 올바르지
#: 않습니다」가 된다. 감수하는 이유는 ⑴ 화면 폼은 여전히 구체적 문구를 그대로 받고
#: (이 경로는 챗봇 전용이다) ⑵ 챗봇의 입력은 **모델이 만든 것**이라 사용자가 고칠
#: 값이 아니며 ⑶ 좁게 시작해 넓히는 것이 반대보다 쉽다(`#120` 화이트리스트와 같은 판단).
class ToolArgumentError(Exception):
    """모델이 보낸 도구 인자를 읽을 수 없다 (`#1334` ⑴).

    **밖으로 나가는 것은 고정 문구 하나**다(:data:`_ERROR_TEXT`) — 어느 인자가
    잘못됐는지도 말하지 않는다. 인자 이름은 모델이 스스로 보낸 것이라 유출은
    아니지만, 문구를 인자마다 만들면 **오류 문구가 값을 실어 나르는 경로**가 하나
    더 생긴다(`#1310`이 화이트리스트가 오류 경로로 뚫린 것을 고쳤다).
    """


def _required_decimal(arguments: dict[str, object], key: str) -> Decimal:
    """필수 숫자 인자. **없거나 숫자가 아니면 봉투로 되돌린다.**"""
    if key not in arguments or arguments[key] is None:
        raise ToolArgumentError(key)
    try:
        return Decimal(str(arguments[key]))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ToolArgumentError(key) from exc


def _optional_decimal(arguments: dict[str, object], key: str) -> Decimal | None:
    """선택 숫자 인자. 없으면 ``None``, **있는데 읽히지 않으면 오류**다.

    읽히지 않는 값을 ``None``으로 삼키면 모델이 보낸 조건이 **조용히 사라진다** —
    그 답은 사용자가 물은 것과 다른 계산의 결과가 된다.
    """
    if key not in arguments or arguments[key] is None:
        return None
    try:
        return Decimal(str(arguments[key]))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ToolArgumentError(key) from exc


def _required_text(arguments: dict[str, object], key: str) -> str:
    if key not in arguments or arguments[key] is None:
        raise ToolArgumentError(key)
    return str(arguments[key])


_ERROR_TEXT: tuple[tuple[type[Exception], str], ...] = (
    (NotFoundError, "요청하신 대상을 찾을 수 없습니다."),
    (ParameterError, "그 조건에 필요한 규정 파라미터가 없습니다."),
    (CalculationError, "이 조건으로는 계산할 수 없습니다."),
    (ValidationError, "입력값이 올바르지 않습니다. 숫자 범위를 확인해 주세요."),
    # `#1334` ⑴ — 모델이 인자를 빼거나 「약 100」·「2026년」처럼 보내는 경우.
    # 종전에는 `KeyError`·`InvalidOperation`·`ValueError`가 잡히지 않아 **턴 전체가
    # 500으로 끊겼고**, 롤백으로 방금 저장한 질문까지 사라졌다.
    (
        ToolArgumentError,
        "도구에 넘길 값이 빠졌거나 숫자로 읽히지 않습니다. 숫자만 넣어 다시 시도해 주세요.",
    ),
)


def _error_text(exc: Exception) -> str:
    """예외 → 고정 문구. **원문을 쓰지 않는다.**

    순서가 있다 — ``ValidationError``를 마지막에 둔다. 하위 클래스 관계가 생기더라도
    더 좁은 것이 먼저 잡히게 한다.
    """
    for kind, text in _ERROR_TEXT:
        if isinstance(exc, kind):
            return text
    # 여기 오면 `run_tool`의 except 절과 이 표가 갈린 것이다 — 그래도 원문은 안 쓴다.
    return "요청을 처리할 수 없습니다."


@dataclass(frozen=True)
class ToolOutcome:
    """도구 하나의 결과 (#1243).

    ``envelope``은 모델에게 가는 봉투 그대로, ``resolved_vessel_id``는 검색의 고유
    일치가 정한 선박 — **호출부(턴 루프)만** 알고 모델에게는 나가지 않는다.
    """

    envelope: str
    resolved_vessel_id: UUID | None = None


async def run_tool(
    session: AsyncSession,
    *,
    name: str,
    arguments: dict[str, object],
    vessel_id: object | None,
    chat_session_id: UUID | None = None,
    vessel_locked: bool = False,
) -> ToolOutcome:
    """도구 하나를 실행하고 **봉투에 담은 문자열**을 돌려준다.

    :param vessel_id: 이 대화가 고른 선박. ``search_vessel``이 정하거나 화면이 준다.
        **모델에게는 넘기지 않는다** — 식별자는 화이트리스트 밖이다.
    :param chat_session_id: 검색의 고유 일치를 **세션 귀속으로 저장**하는 경로
        (#1242). 없으면(단위 검사 등) 저장 없이 결과만 낸다.
    :param vessel_locked: 이 턴에 **화면이 ``vessel_id``를 넘겼다**는 표시 — 세션
        귀속이 화면값을 덮어쓰지 않는다(``API_SPEC §15.1`` 우선순위).

    ## 실패를 자연어로 돌려주지 않는다

    오류는 **봉투의 ``error``**로 간다. 모델이 그것을 읽고 사용자에게 설명한다 —
    서버가 문장을 만들면 같은 말을 두 곳에서 쓰게 된다(`#121` 「에러 처리: API 호출
    실패 시 자연어로 안내」).
    """
    if name not in TOOL_NAMES:
        return ToolOutcome(envelope(name, error="알 수 없는 도구입니다."))

    try:
        if name == TOOL_SEARCH_VESSEL:
            return await _search_vessel(
                session,
                arguments,
                chat_session_id=chat_session_id,
                vessel_locked=vessel_locked,
            )
        if vessel_id is None:
            return ToolOutcome(envelope(name, error="어느 선박인지 먼저 정해야 합니다."))
        if name == TOOL_CALC_VOYAGE_CII:
            return ToolOutcome(await _calc_voyage_cii(session, arguments, vessel_id))
        if name == TOOL_COMPARE_SCENARIOS:
            return ToolOutcome(await _compare_scenarios(session, arguments, vessel_id))
        return ToolOutcome(await _project_year_end(session, arguments, vessel_id))
    except (
        ValidationError,
        NotFoundError,
        ParameterError,
        CalculationError,
        ToolArgumentError,
    ) as exc:
        # ⚠️ **원문을 넘기지 않는다.** 아래 `_ERROR_TEXT` 주석 참조.
        return ToolOutcome(envelope(name, error=_error_text(exc)))


async def _search_vessel(
    session: AsyncSession,
    arguments: dict[str, object],
    *,
    chat_session_id: UUID | None = None,
    vessel_locked: bool = False,
) -> ToolOutcome:
    """⚠️ **이름·식별자를 돌려주지 않는다.** 몇 척인지만 말한다.

    ``PRD §16.3.1``이 선박명·IMO·선박 ID를 전송 금지로 둔다. 검색 결과를 그대로
    돌려주면 **그 금지가 도구 하나로 뚫린다.** 선박을 고르는 것은 서버가 하고, 모델은
    「찾았다」만 안다.

    결과의 귀속은 **호출부(턴 루프)**가 정한다(#1243) — 여기는 ``resolved_vessel_id``로
    알려 주기만 한다. 고유 일치만 정한다. 둘 이상이 걸리면 **화면에서 고르라는 오류
    봉투**를 낸다(#1242의 「모델이 키워드를 좁힌다」에서 변경 — 애매한 것을 몰래
    고르지 않는다는 규율은 그대로). 화면이 ``vessel_id``를 넘긴 턴(``vessel_locked``)은
    귀속을 내지 않는다 — 화면값이 항상 더 최신이다.
    """
    from cii_platform.services import vessel as vessel_service

    keyword = str(arguments.get("name") or "").strip()
    if not keyword:
        return ToolOutcome(envelope(TOOL_SEARCH_VESSEL, error="찾을 이름을 알려 주세요."))
    rows, _ = await vessel_service.list_vessels(session, search=keyword, limit=5)
    if len(rows) >= 2:
        return ToolOutcome(
            envelope(
                TOOL_SEARCH_VESSEL,
                error=f"{len(rows)}척이 일치합니다. 화면에서 선박을 고른 뒤 다시 물어봐 주세요.",
            )
        )
    resolved = UUID(str(rows[0]["id"])) if len(rows) == 1 and not vessel_locked else None
    return ToolOutcome(
        envelope(TOOL_SEARCH_VESSEL, result={"matched": len(rows)}),
        resolved_vessel_id=resolved,
    )


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
        distance_nm=_required_decimal(arguments, "distance_nm"),
        speed_kn=_required_decimal(arguments, "speed_kn"),
        fuel_uses=(
            FuelUseInput(
                fuel_type=_required_text(arguments, "fuel_type"),
                fuel_ton=_required_decimal(arguments, "fuel_ton"),
            ),
        ),
    )
    # `#1334` ⑷ — **저장하지 않는다.** 이 모듈 머리말의 「쓰기 도구를 넣지 않는다」를
    # 읽기 도구가 어기고 있었다(`calculation_run`은 지울 수 없다).
    response = await estimate_voyage_cii(session, payload, persist=False)
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

    payload = ScenarioCompareInput(
        vessel_id=vessel_id,  # type: ignore[arg-type]
        regulation_year=_regulation_year(arguments),
        current_speed_kn=_required_decimal(arguments, "current_speed_kn"),
        fuel_type=_required_text(arguments, "fuel_type"),
        direct_distance_nm=_optional_decimal(arguments, "direct_distance_nm"),
        base_daily_foc_ton=_optional_decimal(arguments, "base_daily_foc_ton"),
    )
    # `#1334` ⑷ — 저장하지 않는다. 위와 같은 이유다.
    response = await compare_scenarios(session, payload, persist=False)
    scenarios = (response.get("data") or {}).get("scenarios") or []  # type: ignore[union-attr]
    # ⚠️ 시나리오를 **순위로 정렬하지 않는다** — 순위화는 No-Advice 금지 항목이다.
    return envelope(
        TOOL_COMPARE_SCENARIOS,
        result={"scenarios": [_publishable(row, _RESULT_KEYS) for row in scenarios]},
    )


async def _project_year_end(
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
            TOOL_PROJECT_YEAR_END,
            error=f"연말 예상을 낼 수 없습니다 (사유 코드: {reason or 'UNKNOWN'}).",
        )
    return envelope(TOOL_PROJECT_YEAR_END, result=_publishable(year_end, _RESULT_KEYS))
