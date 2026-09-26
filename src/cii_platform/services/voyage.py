"""항차 생성·조회 서비스 (TECH_SPEC §16, #53).

``api/routes``와 ``db/repositories`` 사이에서 비즈니스 규칙을 담당한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import (
    ConflictError,
    NotFoundError,
    ParameterError,
    StateTransitionError,
    ValidationError,
)
from cii_platform.reports.labels import inclusion_policy_label, voyage_status_label
from cii_platform.services.pagination import normalize_limit

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _number(value: Decimal | None) -> float | None:
    """선박 제원과 동일 — Layer 1 값이 아니므로 JSON number."""
    return None if value is None else float(value)


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


def _fuel_use_to_dict(fuel_use) -> dict[str, object]:
    """VoyageFuelUse ORM → API_SPEC §3.1 연료 객체."""
    return {
        "id": str(fuel_use.id),
        "fuel_type": fuel_use.fuel_type,
        "planned_fuel_ton": _number(fuel_use.planned_fuel_ton),
        "actual_fuel_ton": _number(fuel_use.actual_fuel_ton),
        "cf_used": _number(fuel_use.cf_used),
        "source": fuel_use.source,
    }


def to_dict(voyage, fuel_uses: list) -> dict[str, object]:
    """ORM 객체를 API_SPEC §3.1 항차 객체로 옮긴다."""
    return {
        "id": str(voyage.id),
        "vessel_id": str(voyage.vessel_id),
        "voyage_no": voyage.voyage_no,
        "status": voyage.status,
        "departure_port_name": voyage.departure_port_name,
        "departure_lat": _number(voyage.departure_lat),
        "departure_lon": _number(voyage.departure_lon),
        "arrival_port_name": voyage.arrival_port_name,
        "arrival_lat": _number(voyage.arrival_lat),
        "arrival_lon": _number(voyage.arrival_lon),
        "planned_distance_nm": _number(voyage.planned_distance_nm),
        # #1256 — 계획 거리의 출처. None은 「모른다」— 화면은 `COORDINATE_ESTIMATE`일 때만
        # 「좌표 기반 추정 거리」 표시를 붙이고, None에는 아무것도 붙이지 않는다.
        "planned_distance_source": voyage.planned_distance_source,
        "actual_distance_nm": _number(voyage.actual_distance_nm),
        "planned_speed_kn": _number(voyage.planned_speed_kn),
        "actual_avg_speed_kn": _number(voyage.actual_avg_speed_kn),
        "planned_departure_at": _iso(voyage.planned_departure_at),
        "planned_arrival_at": _iso(voyage.planned_arrival_at),
        "actual_departure_at": _iso(voyage.actual_departure_at),
        "actual_arrival_at": _iso(voyage.actual_arrival_at),
        # #1923 — 실제 시각의 출처. None은 「모른다」— 화면은 `PUBLIC_RECORD`일 때만 「공적 기록에서
        # 채움」을 붙이고, None에는 아무것도 붙이지 않는다(계획 거리 출처와 같은 규칙).
        "actual_departure_source": voyage.actual_departure_source,
        "actual_arrival_source": voyage.actual_arrival_source,
        "annual_inclusion_policy": voyage.annual_inclusion_policy,
        "regulation_year": voyage.regulation_year,
        "created_from": voyage.created_from,
        "fuel_uses": [_fuel_use_to_dict(fu) for fu in fuel_uses],
        "notes": voyage.notes,
        "created_at": _iso(voyage.created_at),
    }


def _require_enum(value: str | None, allowed: frozenset[str], *, field: str, label: str) -> None:
    """목록 필터의 값을 열거 집합으로 본다 (`#1332`).

    ⚠️ **빈 목록은 답이 아니다.** 값이 틀리면 맞는 행이 없어 200 + 빈 배열이 돌아오고,
    화면에서는 「그런 항차가 없다」와 **같은 모양**이 된다. 선박 목록의 ``ship_type``은
    처음부터 422였다 — 같은 저장소 안에서 두 경로가 갈려 있었다.
    """
    if value is None or value in allowed:
        return
    raise ValidationError(
        f"{label}는 {' · '.join(sorted(allowed))} 중 하나여야 합니다: {value}",
        field=field,
        field_label=label,
    )


async def require_vessel(session: AsyncSession, vessel_id: UUID):
    """선박이 **실재하고 살아 있는지** 확인한다 (`#1332`).

    종전에는 이 검사가 없어 두 가지가 났다.

    * 없는 UUID로 생성하면 ``fk_voyage_vessel`` 위반이 그대로 올라와 **500**이다 —
      `API_SPEC §1.4`는 404다
    * **삭제된 선박에 항차가 생겼다.** ``GET /vessels/{id}``는 404인데
      ``GET /vessels/{id}/voyages``는 목록을 돌려주고 ``POST``는 201이었다

    대조군은 정박 구간(``services/not_underway._require_vessel``)과 내보내기
    (``services/data_export``)다 — 둘 다 처음부터 404를 냈다.

    ⚠️ **``is_deleted``를 여기서 다시 보지 않는다.** ``vessel_repo.get_by_id``가 이미
    ``is_deleted = 0``을 걸어(`DB_SCHEMA §2.1`의 partial 인덱스와 같은 조건) 삭제된
    행은 ``None``으로 온다 — 한 번 더 쓰면 **도달할 수 없는 가지**가 되고, 읽는
    사람에게 「여기서도 갈릴 수 있다」고 말하게 된다.
    """
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")
    return vessel


async def _require_regulation_year(session: AsyncSession, year: int | None) -> None:
    """``regulation_year``가 규정 파라미터에 **실재하는지** 확인한다 — VAL-005 (`#1332`).

    `API_SPEC §3.3`·`§3.4`가 *「주어지면 VAL-005로 검증한다」*고 적고
    ``schemas/voyage.py``도 *「실재 여부(VAL-005)는 서비스가 본다」*고 적는데 **보는
    자리가 없었다.** 스키마의 범위 검사(2019~2050)는 DB CHECK와 같은 폭이라
    **seed에 없는 2031년 항차가 201로 저장**됐고, `INCLUDE_AS_PLAN` 전환까지 통과한
    뒤 **CII 조회에서 409**가 나 사용자는 서버 문제로 읽었다.

    상태 코드는 `API_SPEC §1.4`의 VAL-005 행 그대로 **409 `PARAMETER_ERROR`**다 —
    사용자가 고칠 수 있는 입력이 아니라 **규정 파라미터가 없는 것**이기 때문이다.
    """
    if year is None:
        return
    if await param_repo.get_regulation_year(session, year) is None:
        raise ParameterError(f"해당 연도의 규정 파라미터가 없습니다: {year}")


async def create_voyage(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    voyage_no: str | None,
    departure_port_name: str,
    departure_lat: Decimal | None,
    departure_lon: Decimal | None,
    arrival_port_name: str,
    arrival_lat: Decimal | None,
    arrival_lon: Decimal | None,
    planned_distance_nm: Decimal,
    planned_speed_kn: Decimal,
    planned_departure_at,
    planned_arrival_at,
    regulation_year: int | None,
    fuel_uses: list[dict],
    notes: str | None,
    created_from: str = "MANUAL",
    planned_distance_source: str | None = None,
    commit: bool = True,
) -> dict[str, object]:
    """항차를 생성한다 (API_SPEC §3.3, #53). 성공 시 201.

    초기 상태: ``status=DRAFT``, ``annual_inclusion_policy=EXCLUDE`` (PRD §8.1.1).

    ``created_from``은 **출처 표시**다(``DB_SCHEMA §2.2``의 5값). 기본은 수기 입력이고,
    CSV 가져오기(#60)는 ``IMPORT``를, 시나리오 채택(#58)은 ``FEATURE_2_ADOPTED``를
    넘긴다 — 나중에 「이 항차는 어디서 왔나」를 물을 수 있어야 하기 때문이다.
    **초기 상태는 출처와 무관하게 같다**: 어느 경로로 들어왔든 연간 집계에 바로
    들어가지 않는다.

    ``planned_distance_source``는 **항차가 아니라 거리 한 값의 출처**다(#1256 ·
    ``PRD §15.2``). ``created_from``이 「이 항차가 어느 경로로 들어왔나」라면 이것은 「그
    숫자가 좌표 추정인가 직접 입력인가」이고, 기본은 ``None`` = 「모른다」다 — 서버는
    호출자가 그 숫자를 어떻게 얻었는지 알 수 없으므로 아는 척하지 않는다.

    :param commit: ``False``면 **커밋하지 않고 flush만** 한다 (`#1349`). 시나리오 채택의
        ``CREATE_NEW_VOYAGE``가 새 항차를 만든 뒤 채택 표시·재계산 표시를 이어서 쓰는데,
        여기서 커밋해 버리면 **뒤 단계가 실패했을 때 채택 기록 없는 DRAFT 항차가 남는다.**
    """
    await require_vessel(session, vessel_id)
    await _require_regulation_year(session, regulation_year)

    # 연료 CF 조회 — 모든 fuel_type이 active여야 한다.
    codes = [fu["fuel_type"] for fu in fuel_uses]

    # 한 요청 안의 중복을 DB 제약 이전에 막는다 (`#636`).
    #
    # ``idx_fuel_use_unique``가 (항차, 유종) 중복을 막지만(`DB_SCHEMA §2.3` [S-2]),
    # 여기서 걸러 내지 않으면 **``IntegrityError``가 그대로 올라와 500**이 된다.
    # `_upsert_fuel_actuals`는 같은 가드를 이미 갖고 있었고 생성 경로만 빠져 있었다 —
    # 화면 폼이 연료를 한 종만 보내(`#610` 잔여) **도달할 수 없는 경로였기 때문**이다.
    # 문구는 그쪽과 같게 둔다: 같은 잘못에 다른 말을 하면 규칙이 둘로 읽힌다.
    if len(set(codes)) != len(codes):
        raise ValidationError(
            "같은 연료 종류가 두 번 들어 있습니다.",
            field="fuel_uses",
            field_label="연료 종류",
        )

    fuel_rows = await param_repo.get_fuel_types_by_codes(session, codes)
    for fu in fuel_uses:
        if fu["fuel_type"] not in fuel_rows:
            raise ValidationError(
                f"알 수 없는 연료 종류입니다: {fu['fuel_type']}",
                field="fuel_uses",
                field_label="연료 종류",
            )

    voyage = await voyage_repo.insert(
        session,
        vessel_id=vessel_id,
        voyage_no=voyage_no,
        status="DRAFT",
        departure_port_name=departure_port_name,
        departure_lat=departure_lat,
        departure_lon=departure_lon,
        arrival_port_name=arrival_port_name,
        arrival_lat=arrival_lat,
        arrival_lon=arrival_lon,
        planned_distance_nm=planned_distance_nm,
        planned_distance_source=planned_distance_source,
        planned_speed_kn=planned_speed_kn,
        planned_departure_at=planned_departure_at,
        planned_arrival_at=planned_arrival_at,
        regulation_year=regulation_year,
        annual_inclusion_policy="EXCLUDE",
        created_from=created_from,
        notes=notes,
    )

    for fu in fuel_uses:
        cf = Decimal(str(fuel_rows[fu["fuel_type"]].cf))
        await voyage_repo.insert_fuel_use(
            session,
            voyage_id=voyage.id,
            fuel_type=fu["fuel_type"],
            planned_fuel_ton=fu["planned_fuel_ton"],
            cf_used=cf,
            source=fu["source"],
        )

    if commit:
        await session.commit()
    else:
        # 호출부가 **같은 트랜잭션 안에서** 뒤 작업을 이어 간다 (`#1349`). 행은 보여야
        # 하므로 flush만 한다 — 커밋은 그쪽이 마지막에 한다.
        await session.flush()

    fuel_use_rows = await voyage_repo.list_fuel_uses(session, voyage.id)
    return to_dict(voyage, fuel_use_rows)


async def get_voyage(session: AsyncSession, voyage_id: UUID) -> dict[str, object]:
    """항차 상세 (API_SPEC §3.2). 없으면 404."""
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")
    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage_id)
    return to_dict(voyage, fuel_uses)


async def list_voyages(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    status: str | None = None,
    regulation_year: int | None = None,
    annual_inclusion_policy: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """항차 목록과 페이지네이션 메타를 반환한다 (API_SPEC §3.1).

    ``annual_inclusion_policy`` 필터는 `#1332`에서 붙었다 — **`§3.1` 표에는 처음부터
    있었고 라우트가 선언하지 않아 FastAPI가 조용히 버렸다.** 「연간 반영 항차만 보기」를
    문서대로 만든 호출자는 **필터가 걸린 줄 알고 전체 목록을 받았다.**

    열거값 둘도 여기서 본다 — 종전에는 오타가 **빈 목록**으로 돌아와 「그런 항차가
    없다」와 구분되지 않았다. 선박 목록의 ``ship_type``은 처음부터 422였다.
    """
    await require_vessel(session, vessel_id)
    _require_enum(status, VOYAGE_STATUSES, field="status", label="상태")
    _require_enum(
        annual_inclusion_policy,
        INCLUSION_POLICIES,
        field="annual_inclusion_policy",
        label="연간 반영 정책",
    )
    # ⚠️ 종전에는 ``min(limit or DEFAULT, MAX)``였다 — **아무것도 막지 않았다** (`#818` ⑵).
    # ``limit=-2``는 ``.limit(-1)``이 되어 PostgreSQL이 500을 냈고, ``limit=-1``은 0행인데
    # ``has_more=true``·``next_cursor=null``이라 **따라갈 커서가 없는 「다음 페이지」**를
    # 냈으며, ``limit=0``은 조용히 20건이었다. 선박·계산 목록은 같은 입력에 422였다.
    page_size = normalize_limit(
        limit, default=voyage_repo.DEFAULT_LIMIT, maximum=voyage_repo.MAX_LIMIT
    )

    parsed_cursor = None
    if cursor is not None:
        parsed_cursor = voyage_repo.decode_cursor(cursor)
        if parsed_cursor is None:
            raise ValidationError(
                "커서 형식이 올바르지 않습니다.",
                field="cursor",
                field_label="커서",
            )

    rows = await voyage_repo.list_active(
        session,
        annual_inclusion_policy=annual_inclusion_policy,
        vessel_id=vessel_id,
        limit=page_size,
        cursor=parsed_cursor,
        status=status,
        regulation_year=regulation_year,
    )

    has_more = len(rows) > page_size
    page = rows[:page_size]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = voyage_repo.encode_cursor(
            voyage_repo.VoyageCursor(
                # `datetime` 그대로 넘긴다 — 문자열로 만들면 되읽을 때 `timestamptz`와
                # 비교할 수 없다(`VoyageCursor` 주석 · `#627`).
                created_at=last.created_at,
                voyage_id=str(last.id),
                # 정렬 첫 키 (`#1806`) — 저장소의 `departure_key`와 같은 규칙이다.
                departure_at=last.actual_departure_at or last.planned_departure_at,
            )
        )

    # fuel_uses를 IN 쿼리 1회로 모은다 — 항차마다 조회하면 페이지 크기만큼
    # 쿼리가 늘어난다(MAX_LIMIT=100 → 최대 101쿼리, #314).
    fuel_uses_by_voyage = await voyage_repo.list_fuel_uses_by_voyage_ids(
        session, [v.id for v in page]
    )
    data = [to_dict(voyage, fuel_uses_by_voyage.get(voyage.id, [])) for voyage in page]

    return data, {"next_cursor": next_cursor, "has_more": has_more}


#: 항차 상태 7종 (`DB_SCHEMA §2.2` ``chk_voyage_status``).
#:
#: 목록 필터의 값을 이 집합으로 검증한다 (`#1332`) — 종전에는 검증이 없어 오타가
#: **빈 목록**으로 돌아왔다. 선박 목록의 ``ship_type``은 처음부터 422였다.
VOYAGE_STATUSES: frozenset[str] = frozenset(
    {"DRAFT", "PLANNED", "IN_PROGRESS", "COMPLETED", "CONFIRMED", "CANCELLED", "ARCHIVED"}
)

#: 연간 반영 정책 3종 (`DB_SCHEMA §2.2` ``chk_voyage_policy``).
INCLUSION_POLICIES: frozenset[str] = frozenset({"EXCLUDE", "INCLUDE_AS_PLAN", "INCLUDE_AS_ACTUAL"})

#: API_SPEC §3.5 — 허용되는 상태 전환 매핑.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"PLANNED", "CANCELLED"}),
    "PLANNED": frozenset({"IN_PROGRESS", "CANCELLED"}),
    "IN_PROGRESS": frozenset({"COMPLETED", "CANCELLED"}),
    "COMPLETED": frozenset({"CONFIRMED"}),
    "CONFIRMED": frozenset({"COMPLETED", "ARCHIVED"}),
    "CANCELLED": frozenset(),
    "ARCHIVED": frozenset(),
}

#: API_SPEC §3.5 — status × annual_inclusion_policy 허용 조합 (PRD §8.1.2).
_POLICY_BY_STATUS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"EXCLUDE"}),
    "PLANNED": frozenset({"EXCLUDE", "INCLUDE_AS_PLAN"}),
    "IN_PROGRESS": frozenset({"EXCLUDE", "INCLUDE_AS_PLAN"}),
    "COMPLETED": frozenset({"EXCLUDE", "INCLUDE_AS_ACTUAL"}),
    "CONFIRMED": frozenset({"EXCLUDE", "INCLUDE_AS_ACTUAL"}),
    "CANCELLED": frozenset({"EXCLUDE"}),
    "ARCHIVED": frozenset({"EXCLUDE"}),
}

#: PATCH로 계획값을 바꿀 수 있는 상태 — 시나리오 반영(#580)과 같은 기준이다.
#: 출항한 뒤 계획을 갈아 끼우면 `PRD §8.3` 값 우선순위가 「실적이 있는데 계획이
#: 나중에 바뀐」 상태가 된다(#865).
PLANNING_STATUSES: frozenset[str] = frozenset({"DRAFT", "PLANNED"})

#: PATCH 가드의 대상 필드 — 계획값 4종과 귀속 연도. `regulation_year`를 바꾸면
#: 그 항차의 배출·거리가 `list_annual_inclusions` 필터를 타고 다른 규제연도로
#: 옮겨 간다. 항구명·좌표·notes는 계산 입력이 아니므로 가드하지 않는다 (#865).
_PLAN_GUARD_FIELDS: frozenset[str] = frozenset(
    {
        "planned_distance_nm",
        "planned_speed_kn",
        "planned_departure_at",
        "planned_arrival_at",
        "regulation_year",
    }
)


async def update_voyage(
    session: AsyncSession,
    voyage_id: UUID,
    **fields,
) -> dict[str, object]:
    """항차를 수정한다 (API_SPEC §3.4, #54). 없으면 404.

    ``fields``는 라우트가 ``model_dump(exclude_unset=True)``로 만든 것 —
    **생략 = 변경 없음, 명시적 ``null`` = 클리어**다 (#312).
    ``regulation_year``를 ``None``으로 지우는 요청은 ``annual_inclusion_policy ≠
    EXCLUDE``인 경우 ``chk_year_policy`` 제약에 걸리므로 거부한다 (#150).
    """
    # 항차 행을 먼저 잠그고 읽는다 (`#1626` · `TECH_SPEC §16.3`) — 아래 상태 판정이 옛
    # 상태 위에서 통과하지 않게. 잠금은 이 함수의 커밋·롤백에서 풀린다.
    voyage = await voyage_repo.get_by_id(session, voyage_id, for_update=True)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")

    if (
        "regulation_year" in fields
        and fields["regulation_year"] is None
        and voyage.annual_inclusion_policy != "EXCLUDE"
    ):
        raise ValidationError(
            "연간에 반영하는 항차는 기준연도를 지울 수 없습니다. "
            "「연간 반영 안 함」으로 바꾼 뒤 지워 주세요.",
            field="regulation_year",
            field_label="기준연도",
        )

    # VAL-005 — 새로 넣는 연도는 규정 파라미터에 실재해야 한다 (`#1332`). `null`로
    # 지우는 요청은 위에서 이미 갈렸으므로 여기서는 값이 있는 경우만 본다.
    if fields.get("regulation_year") is not None:
        await _require_regulation_year(session, fields["regulation_year"])

    # #865 — 확정·진행 등 계획 단계를 벗어난 항차의 계획값·귀속 연도 변경을 거부한다.
    # `scenario_adopt`가 같은 필드를 `PLANNING_STATUSES`로 막는 것과 같은 기준이며,
    # 일반 PATCH에만 가드가 없었다.
    changed_plan_fields = sorted(set(fields) & _PLAN_GUARD_FIELDS)
    # #1256 — 거리 출처는 계산 입력이 아니라 재계산 대상(`changed_plan_fields`)에는 넣지
    # 않지만, **계획 거리에 붙은 표시**라 거리와 같은 상태에서만 바뀐다. 확정된 항차의
    # 거리에 사후로 「추정」을 붙이거나 떼는 길을 열어 두지 않는다.
    guarded_fields = sorted(set(fields) & (_PLAN_GUARD_FIELDS | {"planned_distance_source"}))
    if guarded_fields and voyage.status not in PLANNING_STATUSES:
        raise StateTransitionError(
            f"계획 단계 항차만 계획값을 바꿀 수 있습니다 (현재 상태: {voyage.status}). "
            f"대상 필드: {', '.join(guarded_fields)} · "
            f"허용 상태: {' · '.join(sorted(PLANNING_STATUSES))}"
        )

    # #1256 — 출처는 **숫자에 붙은 표시**다. 거리가 바뀌는데 출처를 말하지 않으면 옛 출처를
    # 새 숫자에 그대로 두지 않고 「모른다」로 돌린다 — 좌표로 채운 항차의 거리를 사람이
    # 고쳤는데 「추정값입니다」가 남아 있으면 `PRD §0.3`이 금하는 거짓말이다. 생성의 기본값
    # (`None`)과 같은 규칙이라, 거리와 출처를 함께 보낸 요청만 출처를 갖는다.
    if "planned_distance_nm" in fields and "planned_distance_source" not in fields:
        fields["planned_distance_source"] = None

    for key, value in fields.items():
        setattr(voyage, key, value)

    if changed_plan_fields:
        # `PRD §8.4` — 항차 계획 변경 → 해당 항차 계산 결과 무효화 후 재계산.
        # `calculation_run.voyage_id`가 항상 NULL인 #817 때문에 지금은 no-op이지만
        # 호출 규약은 이 자리에 있고, #817 해소 시 함께 동작한다.
        await voyage_repo.mark_calculations_needing_recalc(session, voyage.id)

    await session.commit()
    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
    return to_dict(voyage, fuel_uses)


async def transition_voyage(
    session: AsyncSession,
    voyage_id: UUID,
    to_status: str,
    annual_inclusion_policy: str | None = None,
    commit: bool = True,
) -> dict[str, object]:
    """항차 상태를 전환한다 (API_SPEC §3.5, #54). 없으면 404.

    PRD §8.1 상태 머신 + policy 가드를 따른다.

    반환 dict에 ``_from_status``를 실어 보낸다 — **감사 로그의 「변경 전」 값**이다
    (``TECH_SPEC §13.1``, #65). 라우트가 꺼내 쓰고 응답에서 뺀다(``_duration_ms``와
    같은 규약). 서비스가 직접 기록하지 않는 이유는 **주체(user)와 IP가 HTTP 개념**이라
    서비스가 ``request``를 알아야 하기 때문이다(``TECH_SPEC §16.1`` 계층).

    :param commit: ``False``면 **커밋하지 않고 flush만** 한다 (`#1625` · `#1349` 선례).
        라우트가 감사 로그를 넣은 뒤 **한 번의 커밋**으로 상태와 감사를 함께 확정한다 —
        여기서 커밋해 버리면 감사 INSERT가 실패했을 때 **기록 없는 `CONFIRMED`가 남는다**
        (`TECH_SPEC §16.3` 「필수 감사 로그는 원본 변경과 같은 트랜잭션에서 확정한다」).
    """
    # 항차 행을 먼저 잠그고 읽는다 (`#1626` · `TECH_SPEC §16.3`) — 아래 상태 판정이 옛
    # 상태 위에서 통과하지 않게. 잠금은 커밋·롤백에서 풀린다 — `commit=False`면 호출부(라우트)가
    # 감사 기록까지 넣고 커밋할 때다(`#1625`).
    voyage = await voyage_repo.get_by_id(session, voyage_id, for_update=True)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")

    current = voyage.status
    if to_status not in _TRANSITIONS.get(current, frozenset()):
        raise StateTransitionError(f"허용되지 않은 상태 전환입니다: {current} → {to_status}.")

    # ── 정책을 「정하기」만 한다 — 대입은 아래 한 곳에서 상태와 함께 한다 (#688).
    #
    # 여기서 `voyage`에 바로 쓰면 상태와 정책이 **다른 flush에 실린다.** 아래
    # `_guard_actual_data`가 실적 연료를 읽으려 SELECT를 날리는데, SQLAlchemy는
    # 쿼리 직전 세션의 미반영 변경을 자동으로 먼저 쓴다(autoflush). 그 시점에
    # 쌓여 있는 것이 정책 하나뿐이면 다음이 나간다.
    #
    #     UPDATE voyage SET annual_inclusion_policy='INCLUDE_AS_ACTUAL' ...
    #     -- status는 아직 IN_PROGRESS
    #
    # `chk_status_policy`(`DB_SCHEMA §2.2`)는 **두 컬럼의 조합**에 걸린 제약이라
    # 이 중간 상태를 거부하고, `IntegrityError`가 그대로 올라와 **500**이 된다.
    # 그룹을 건너뛰는 유일한 전이가 `IN_PROGRESS → COMPLETED`(`INCLUDE_AS_PLAN` →
    # `INCLUDE_AS_ACTUAL`)이라 거기서만 터졌다 — 그리고 그 경로가 화면의
    # 「항해 완료」 버튼이다.
    #
    # 순서를 바꾸는 것(상태를 먼저 대입)으로도 이 한 번은 막히지만, **두 대입
    # 사이에 조회가 하나라도 더 생기면 재발한다.** 조합 제약에는 두 컬럼을 함께
    # 쓰는 코드가 대응하므로, 대입 자체를 한 자리로 모아 순서에 의존하지 않게 한다.
    new_policy = voyage.annual_inclusion_policy
    if annual_inclusion_policy is not None:
        allowed = _POLICY_BY_STATUS.get(to_status, frozenset())
        if annual_inclusion_policy not in allowed:
            raise StateTransitionError(
                f"「{voyage_status_label(to_status)}」 상태에서는 "
                f"「{inclusion_policy_label(annual_inclusion_policy)}」을 고를 수 없습니다."
            )
        if annual_inclusion_policy != "EXCLUDE" and voyage.regulation_year is None:
            raise StateTransitionError(
                f"「{inclusion_policy_label(annual_inclusion_policy)}」으로 바꾸려면 "
                "기준연도가 필요합니다."
            )
        new_policy = annual_inclusion_policy
    elif len(_POLICY_BY_STATUS.get(to_status, frozenset())) == 1:
        # EXCLUDE-only 상태(CANCELLED·ARCHIVED)는 스펙이 자동 설정을 규정한다
        # (API_SPEC §3.5 「자동 설정」·ORACLE-C-4).
        new_policy = "EXCLUDE"
    elif voyage.annual_inclusion_policy not in _POLICY_BY_STATUS[to_status]:
        # 미지정 = 현행 유지가 원칙이나, 목표 상태가 현행 policy를 허용하지 않으면
        # 조용히 보정하지 않고 명시적 재지정을 요구한다 (#310).
        raise StateTransitionError(
            f"「{voyage_status_label(to_status)}」 상태에서는 지금의 "
            f"「{inclusion_policy_label(voyage.annual_inclusion_policy)}」을 쓸 수 없습니다. "
            "연간 반영 구분을 함께 골라 주세요."
        )

    # 가드는 **전이 전** 항차를 본다 — 위에서 객체를 건드리지 않았으므로 그대로다.
    await _guard_actual_data(session, voyage, to_status)

    voyage.status = to_status
    voyage.annual_inclusion_policy = new_policy
    if commit:
        await session.commit()
    else:
        # 호출부가 **같은 트랜잭션 안에서** 감사 로그를 잇는다 (`#1625`). 상태는 DB에
        # 보여야 하므로 flush만 한다 — 커밋은 그쪽이 마지막에 한다.
        await session.flush()
    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
    return {**to_dict(voyage, fuel_uses), "_from_status": current}


async def _guard_actual_data(session: AsyncSession, voyage, to_status: str) -> None:
    """실적(actual) 가드 — API_SPEC §3.5 전환 규칙 (ORACLE-C-4, #326).

    - ``IN_PROGRESS → COMPLETED``: 최소 1개 ``actual_fuel_ton > 0``
    - ``COMPLETED → CONFIRMED``: 모든 ``actual_fuel_ton > 0`` 및
      ``actual_distance_nm > 0`` (확정은 실적이 완전할 때만)
    """
    if to_status == "COMPLETED":
        fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
        has_actual = any(
            fu.actual_fuel_ton is not None and fu.actual_fuel_ton > 0 for fu in fuel_uses
        )
        if not has_actual:
            raise StateTransitionError(
                "실제 연료량을 한 건 이상 입력해야 「항해 완료」로 바꿀 수 있습니다."
            )

    elif to_status == "CONFIRMED":
        fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
        incomplete = [
            fu.fuel_type
            for fu in fuel_uses
            if fu.actual_fuel_ton is None or fu.actual_fuel_ton <= 0
        ]
        if incomplete:
            raise StateTransitionError(
                f"「실적 확정」 전에 모든 연료의 실제 연료량이 필요합니다 — 미입력: "
                f"{', '.join(incomplete)}."
            )
        if voyage.actual_distance_nm is None or voyage.actual_distance_nm <= 0:
            raise StateTransitionError("「실적 확정」 전에 실제 거리가 필요합니다.")


async def delete_voyage(
    session: AsyncSession,
    voyage_id: UUID,
) -> dict[str, object]:
    """항차를 삭제한다 (API_SPEC §3.7, #54).

    - DRAFT, CANCELLED → hard delete — 단, 계산 이력(``calculation_run``) 참조가
      있으면 ``ConflictError``(409, #313). FK가 RESTRICT라 그대로 지우면 500이 난다
    - COMPLETED, CONFIRMED, ARCHIVED → soft delete
    - PLANNED, IN_PROGRESS → 422 (먼저 CANCELLED로 전환 필요)
    """
    # 항차 행을 먼저 잠그고 읽는다 (`#1626` · `TECH_SPEC §16.3`) — 아래 상태 판정이 옛
    # 상태 위에서 통과하지 않게. 잠금은 이 함수의 커밋·롤백에서 풀린다.
    voyage = await voyage_repo.get_by_id(session, voyage_id, for_update=True)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")

    hard_delete_statuses = {"DRAFT", "CANCELLED"}
    soft_delete_statuses = {"COMPLETED", "CONFIRMED", "ARCHIVED"}

    if voyage.status in hard_delete_statuses:
        if await voyage_repo.has_calculation_run_refs(session, voyage_id):
            raise ConflictError("이 항차를 참조하는 계산 이력이 있어 삭제할 수 없습니다.")
        await session.delete(voyage)
        await session.commit()
        return {"id": str(voyage.id), "deleted": True, "hard_delete": True}

    if voyage.status in soft_delete_statuses:
        voyage.is_deleted = True
        await session.commit()
        return {"id": str(voyage.id), "deleted": True, "hard_delete": False}

    raise StateTransitionError(
        f"상태 {voyage.status}인 항차는 삭제할 수 없습니다. 먼저 CANCELLED로 전환하세요."
    )


#: 실적을 받을 수 있는 상태 (#440).
#:
#: `PRD §8.1` 상태 머신에서 **운항이 시작된 뒤**의 상태들이다. `DRAFT`·`PLANNED`는
#: 아직 뜨지 않은 항차라 실적이 존재할 수 없고, `CANCELLED`·`ARCHIVED`는 종결된
#: 기록이다. `CONFIRMED`를 여기 넣지 않는 이유는 아래 docstring에 있다.
ACTUALS_ALLOWED_STATUSES = frozenset({"IN_PROGRESS", "COMPLETED"})

#: 실제 시각 칸 → 그 출처 칸 (#1923 · `DB_SCHEMA §2.2`). 시각이 바뀌는데 출처를 말하지 않으면
#: 「모른다」(`None`)로 돌린다 — `planned_distance_source`(#1256)와 같은 규칙.
ACTUAL_TIME_SOURCE_FIELDS: dict[str, str] = {
    "actual_departure_at": "actual_departure_source",
    "actual_arrival_at": "actual_arrival_source",
}


def reset_stale_sources(fields: dict[str, object], source_by_value: dict[str, str]) -> None:
    """값이 바뀌는데 출처를 함께 말하지 않은 칸의 출처를 ``None``으로 (#1923 · #1256 규칙).

    옛 「공적 기록에서 채움」이 사람이 고친 새 시각에 그대로 붙어 있으면 `PRD §0.3`이 금하는
    거짓말이다. 값과 출처를 함께 보낸 요청만 출처를 갖는다. 항차 실적과 정박 구간 수정이 같은
    함수를 쓴다 — 규칙이 두 곳에 있으면 한쪽만 고쳐진다.
    """
    for value_key, source_key in source_by_value.items():
        if value_key in fields and source_key not in fields:
            fields[source_key] = None


async def set_actuals(
    session: AsyncSession,
    voyage_id: UUID,
    *,
    fuel_uses: list[dict] | None = None,
    **fields,
) -> dict[str, object]:
    """항차 실적을 입력한다 (`API_SPEC §3.6`, #440). 없으면 404.

    ## 상태를 바꾸지 않는다

    명세가 *"`status`는 변경하지 않는다 (별도 transition 호출 필요)"* 로 못박는다.
    실적 입력과 상태 전환을 한 번에 처리하면 **전환 가드(`PRD §8.1.1`)를 우회하는
    경로**가 생긴다 — `COMPLETED → CONFIRMED`는 모든 실적이 채워졌을 때만 허용되는데,
    같은 요청 안에서 채우고 전환하면 그 검사가 자기 입력을 보고 통과한다.

    ## 어느 상태에서 받는가

    `IN_PROGRESS`·`COMPLETED`만 받는다.

    * `DRAFT`·`PLANNED` — **아직 뜨지 않은 항차에 실적이 있을 수 없다.** 받아 두면
      `PRD §8.3` 값 우선순위가 「PLANNED인데 actual이 있는」 정의되지 않은 상태를
      만난다.
    * `CANCELLED`·`ARCHIVED` — 종결된 기록이다.
    * `CONFIRMED` — **확정된 실적을 조용히 갈아 끼우지 않는다.** 확정은 연말 DCS 보고의
      근거이므로, 고쳐야 한다면 `COMPLETED`로 되돌리는 전환을 명시적으로 거쳐야 한다.

    ## 계획값을 지우지 않는다

    `PRD §8.4` — *"실제 연료 사용량 입력: 계획값과 실제값을 **모두 보존**하고 실제값
    우선 사용"*. 그래서 `planned_fuel_ton`은 건드리지 않고 `actual_fuel_ton`만 쓴다.
    계획 대비 실적 차이가 `#363` 피드백 루프의 입력이라, 계획값을 잃으면 그 비교가
    영영 불가능해진다.

    같은 이유로 **`calculation_run`을 무효화하지 않는다.** `§8.4`가 무효화를 규정한
    것은 「항차 계획 변경」이지 실적 입력이 아니다. 실적은 다음 조회 때 값 우선순위가
    자동으로 집어 간다.

    ## CF snapshot

    새로 생기는 연료 행에는 **지금 시점의 CF**를 박는다(`#378`). 기존 행의
    ``cf_used``는 그대로 둔다 — 실적을 나중에 입력했다고 그때의 CF로 과거 계산이
    바뀌면 재현성이 깨진다.
    """
    # 항차 행을 먼저 잠그고 읽는다 (`#1626` · `TECH_SPEC §16.3`) — 아래 상태 판정이 옛
    # 상태 위에서 통과하지 않게. 잠금은 이 함수의 커밋·롤백에서 풀린다.
    voyage = await voyage_repo.get_by_id(session, voyage_id, for_update=True)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")

    if voyage.status not in ACTUALS_ALLOWED_STATUSES:
        raise StateTransitionError(
            f"{voyage.status} 상태의 항차에는 실적을 입력할 수 없습니다. "
            f"허용: {', '.join(sorted(ACTUALS_ALLOWED_STATUSES))}."
        )

    # #1923 — 시각을 고치면서 출처를 말하지 않으면 「모른다」로 돌린다(#1256과 같은 규칙).
    reset_stale_sources(fields, ACTUAL_TIME_SOURCE_FIELDS)
    for key, value in fields.items():
        setattr(voyage, key, value)

    if fuel_uses:
        await _apply_fuel_actuals(session, voyage_id=voyage.id, fuel_uses=fuel_uses)

    await session.commit()
    fuel_use_rows = await voyage_repo.list_fuel_uses(session, voyage.id)
    return to_dict(voyage, fuel_use_rows)


async def _apply_fuel_actuals(
    session: AsyncSession,
    *,
    voyage_id: UUID,
    fuel_uses: list[dict],
) -> None:
    """유종별 실적을 기존 행에 얹거나 새 행으로 넣는다.

    ``idx_fuel_use_unique``가 (항차, 유종) 중복을 막는다(`DB_SCHEMA §2.3` [S-2]) —
    중복이 생기면 **CO₂가 이중 산정**된다. 그래서 유종을 키로 갱신·삽입을 가른다.
    """
    codes = [item["fuel_type"] for item in fuel_uses]
    if len(set(codes)) != len(codes):
        # 한 요청 안의 중복은 DB 제약 이전에 막는다 — 어느 쪽이 이겼는지 알 수 없는
        # 결과를 만들지 않는다.
        raise ValidationError(
            "같은 연료 종류가 두 번 들어 있습니다.",
            field="fuel_uses",
            field_label="연료 종류",
        )

    fuel_rows = await param_repo.get_fuel_types_by_codes(session, codes)
    existing = {row.fuel_type: row for row in await voyage_repo.list_fuel_uses(session, voyage_id)}

    for item in fuel_uses:
        code = item["fuel_type"]
        if code not in fuel_rows:
            raise ValidationError(
                f"알 수 없는 연료 종류입니다: {code}",
                field="fuel_uses",
                field_label="연료 종류",
            )

        row = existing.get(code)
        if row is not None:
            # 계획값은 그대로 둔다 (`PRD §8.4`). `cf_used`도 그대로 둔다 — 이 열은
            # **기록**이다(#832). 확정 실적은 그때 실제로 그 계수로 배출했고(#863),
            # 계획 항차의 예측은 계산 실행 시점의 활성 CF를 쓰므로 이 열을 덮어쓸
            # 필요가 없다. 덮으면 그때의 기록이 사라진다.
            row.actual_fuel_ton = item["actual_fuel_ton"]
            if item.get("source") is not None:
                row.source = item["source"]
            continue

        await voyage_repo.insert_fuel_use(
            session,
            voyage_id=voyage_id,
            fuel_type=code,
            actual_fuel_ton=item["actual_fuel_ton"],
            cf_used=Decimal(str(fuel_rows[code].cf)),
            source=item.get("source") or "USER_INPUT",
        )
