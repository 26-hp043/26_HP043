"""항차 저장소 — 쿼리만 담당한다 (TECH_SPEC §16, #53).

비즈니스 판단은 ``services``의 몫이다. 이 모듈은 **찾으면 반환하고 없으면 ``None``**을 준다.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy import case, func, or_, select, tuple_

from cii_platform.db.models.voyage import Voyage
from cii_platform.db.models.voyage_fuel_use import VoyageFuelUse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

#: API_SPEC §3.1 — 페이지 크기 기본 20, 최대 100 (vessel과 동일).
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

_CURSOR_SEP = "\x00"


class VoyageCursor(NamedTuple):
    """keyset 페이지네이션 커서 — :func:`list_active` 정렬 키의 마지막 값.

    **정렬 키는 넷이다** (`#1806`) — 출항 시각 유무 · 출항 시각 · ``created_at`` · ``id``.
    출항 시각 유무는 ``departure_at``이 ``None``인지로 읽으므로 필드는 셋이다.

    **``created_at``은 ``datetime``이다 (``str``이 아니다).** ``list_active``의
    ``tuple_`` 비교가 ``Voyage.created_at``(``DateTime(timezone=True)``)과 맞붙는데,
    문자열을 넘기면 asyncpg가 그대로 텍스트로 내려보내 PostgreSQL이 거절한다.

    .. code-block:: text

        operator does not exist: timestamp with time zone > character varying

    **이 결함은 커서를 아무도 쓰지 않아 드러나지 않았다** (`#627`) — 화면 두 곳이
    ``?limit=100``만 박고 ``meta.next_cursor``를 버렸다. 서버는 커서를 발급하면서
    **자기가 발급한 커서를 읽지 못하는** 상태였다.

    선박 쪽(``repositories/vessel.py``)이 멀쩡한 이유는 정렬 키가 다르기 때문이다 —
    ``Vessel.name``은 ``varchar``라 문자열 비교가 성립한다. **같은 구조를 복사하면서
    정렬 키의 타입이 달라진 것을 옮기지 않았다.**

    ``voyage_id``는 ``str``로 둔다 — 선박 쪽과 같은 이유다. ``encode_cursor``가
    ``str(voyage.id)``로 인코딩하므로 왕복 계약이 str에 맞춰져 있다.
    """

    created_at: datetime
    voyage_id: str
    #: 출항 시각 = 실제 출항, 없으면 계획 출항. 둘 다 없으면 ``None``(목록 맨 아래 묶음).
    departure_at: datetime | None = None


def departure_key():
    """정렬에 쓰는 출항 시각 — 실제 출항, 없으면 계획 출항 (`#1806`).

    사용자가 항차 표에서 찾는 것은 **가장 최근에 떠난 항차**다. 등록 시각으로 두면 CSV로
    지난 항차를 몰아 넣거나 지난달 항차를 나중에 등록했을 때 항해 순서와 갈린다.
    """
    return func.coalesce(Voyage.actual_departure_at, Voyage.planned_departure_at)


def _newest_departure_first():
    """출항 시각이 **있는** 항차를 먼저, 그 안에서 최신순 · 없는 항차(날짜 없는 초안)는
    맨 아래 (`#1806`). 같은 출항 시각끼리는 ``created_at``·``id`` 내림차순으로 고정한다 —
    「더 보기」로 이어 받아도 겹치거나 빠지지 않게 커서와 **같은 키**를 쓴다."""
    departure = departure_key()
    return (
        case((departure.is_(None), 1), else_=0),
        departure.desc(),
        Voyage.created_at.desc(),
        Voyage.id.desc(),
    )


def encode_cursor(cursor: VoyageCursor) -> str:
    """커서를 URL-safe base64 문자열로 만든다.

    **불투명한 문자열로 내보낸다** — ``API_SPEC §3.1``이 형식을 정하지 않았고, 내부
    구조를 노출하면 클라이언트가 그것에 의존해 정렬 키를 바꿀 수 없게 된다.
    """
    import base64

    departure = "" if cursor.departure_at is None else cursor.departure_at.isoformat()
    raw = (
        f"{departure}{_CURSOR_SEP}{cursor.created_at.isoformat()}{_CURSOR_SEP}{cursor.voyage_id}"
    ).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> VoyageCursor | None:
    """커서를 되돌린다. 형식이 깨졌으면 ``None``.

    **예외를 던지지 않는다.** 잘못된 커서는 사용자가 URL을 손댄 경우가 대부분이고,
    그때 500이 나가면 안 된다. 오류로 볼지 첫 페이지로 볼지는 서비스가 정한다.

    **두 값을 모두 검증한다.** base64가 정상이어도 안에 든 값이 시각·UUID가 아니면
    쿼리 바인딩 단계에서 거절돼 500이 나간다 — 선박 쪽이 `#233`에서 UUID에 대해
    막아 둔 것과 같은 경로이며, 여기서는 시각까지 함께 막는다.
    """
    import base64
    import binascii

    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    # 세 칸이다 (`#1806`). 종전 두 칸 커서(정렬이 바뀌기 전에 받은 것)는 **읽지 않는다** —
    # 다른 정렬의 위치라 이어 받으면 행이 겹치거나 빠진다. 형식 오류(422)로 돌려 첫
    # 페이지부터 다시 받게 한다.
    parts = raw.split(_CURSOR_SEP)
    if len(parts) != 3 or not parts[2]:
        return None
    departure, created_at, voyage_id = parts
    try:
        parsed_at = datetime.fromisoformat(created_at)
        parsed_departure = datetime.fromisoformat(departure) if departure else None
    except ValueError:
        return None
    try:
        UUID(voyage_id)
    except ValueError:
        return None
    return VoyageCursor(created_at=parsed_at, voyage_id=voyage_id, departure_at=parsed_departure)


async def get_by_id(
    session: AsyncSession, voyage_id: UUID, *, for_update: bool = False
) -> Voyage | None:
    """활성 항차 1건을 조회한다 (soft delete 제외).

    ``for_update=True``면 **항차 행을 먼저 잠그고 나서** 읽는다 (`#1626` · `F-8` 결정 ·
    `TECH_SPEC §16.3`). 상태를 보고 판정한 뒤 쓰는 경로(전환 · PATCH · 실적 · 삭제 ·
    시나리오 채택)가 쓴다 — 두 요청이 같은 옛 상태를 읽고 각자 통과하면 종결 상태가
    덮이거나 채택 행이 둘 남는다(`#1796` ⑹·⑺ 실측). 잠금은 호출부가 커밋·롤백할 때 풀린다.

    잠금 문장과 읽기 문장을 **나눈다.** 뒤따르는 ``SELECT``는 READ COMMITTED에서 커밋된
    최신 상태를 준다(`#1796` ⑵) — 한 문장으로 합쳤을 때 대기 뒤 어느 판본이 돌아오는지는
    실측하지 않았다. ``populate_existing``은 같은 세션이 먼저 실어 둔 옛 사본을 새 값으로
    덮기 위해서다. 잠금 쪽은 ``is_deleted``를 보지 않는다 — 다른 요청이 방금 소프트 삭제한
    행도 잠갔다가, 읽기에서 ``None``(404)으로 갈리게 둔다.
    """
    if for_update:
        await session.execute(select(Voyage.id).where(Voyage.id == voyage_id).with_for_update())
    stmt = select(Voyage).where(Voyage.id == voyage_id, Voyage.is_deleted == 0)
    if for_update:
        stmt = stmt.execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_fuel_uses(session: AsyncSession, voyage_id: UUID) -> list[VoyageFuelUse]:
    """항차의 연료 사용 내역을 조회한다. 정렬은 유종순이다 (#867).

    **정렬이 없으면 PostgreSQL이 힙 순서를 준다** — 행 하나를 UPDATE하는 정상
    조작만으로 순서가 바뀐다. 소비처가 「첫 항목」에 의존하고 있어(진행 중 항차의
    대표 유종 — 지금은 :func:`~cii_platform.services.cii_current._voyage_fuel_split`) 그
    순간 CO₂ 기여가 튄다 — 실측에서 HFO CF 3.114가 DIESEL_GAS_OIL 3.206으로
    뒤집혔다. 형제 저장소(``not_underway.list_fuel_uses``)는 처음부터 정렬을
    명시하고 있었고 이쪽만 빠져 있었다.

    ``id``를 2차 키로 두는 이유는 ``idx_fuel_use_unique``가 ``(voyage_id,
    fuel_type)``이라 같은 유종이 둘일 수 없어도, 인덱스가 바뀌었을 때 순서가
    다시 미정이 되지 않게 하기 위해서다.
    """
    stmt = (
        select(VoyageFuelUse)
        .where(VoyageFuelUse.voyage_id == voyage_id)
        .order_by(VoyageFuelUse.fuel_type, VoyageFuelUse.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_fuel_uses_by_voyage_ids(
    session: AsyncSession, voyage_ids: list[UUID]
) -> dict[UUID, list[VoyageFuelUse]]:
    """여러 항차의 연료 사용 내역을 **IN 쿼리 1회**로 조회한다 (#314).

    목록 조회의 N+1(항차마다 ``list_fuel_uses``)을 없앤다. 반환은
    ``{voyage_id: [fuel_use, …]}`` 그룹핑 — 내역이 없는 항차는 키가 없다.

    정렬은 :func:`list_fuel_uses`와 **같은 기준**이다 (#867). 한쪽만 정렬하면
    같은 항차의 ``fuel_uses``가 단건 조회와 목록 조회에서 다른 순서로 나온다.
    """
    if not voyage_ids:
        return {}
    stmt = (
        select(VoyageFuelUse)
        .where(VoyageFuelUse.voyage_id.in_(voyage_ids))
        .order_by(VoyageFuelUse.fuel_type, VoyageFuelUse.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    grouped: dict[UUID, list[VoyageFuelUse]] = {}
    for fuel_use in rows:
        grouped.setdefault(fuel_use.voyage_id, []).append(fuel_use)
    return grouped


async def has_calculation_run_refs(session: AsyncSession, voyage_id: UUID) -> bool:
    """항차를 참조하는 ``calculation_run`` 행이 있는지 (#313).

    ``fk_calculation_run_voyage``는 ON DELETE **RESTRICT**라 참조가 있으면
    물리 DELETE가 ``IntegrityError``(→500)로 실패한다 — 서비스가 미리 409로
    가리기 위한 조회다.
    """
    from cii_platform.db.models.calculation_run import CalculationRun

    # `select(exists()…)`를 쓰지 않는다 — CUBRID는 `EXISTS`를 **select 항목 자리에서
    # 받지 못한다**(WHERE 절 전용). 실측 (`#1058`)::
    #
    #     SELECT EXISTS (SELECT * FROM calculation_run WHERE …)
    #     → Syntax error: unexpected 'EXISTS'  (errno=-493)
    #
    # `LIMIT 1` 한 건 조회로 바꾼다 — 판정이 같고 어느 DB에서나 성립한다.
    stmt = select(CalculationRun.id).where(CalculationRun.voyage_id == voyage_id).limit(1)
    return (await session.scalar(stmt)) is not None


async def list_active(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    limit: int,
    cursor: VoyageCursor | None = None,
    status: str | None = None,
    regulation_year: int | None = None,
    annual_inclusion_policy: str | None = None,
) -> list[Voyage]:
    """활성 항차 목록을 조회한다 (API_SPEC §3.1).

    ``limit + 1``건을 가져온다 — ``has_more`` 판단용.

    ``annual_inclusion_policy``는 `#1332`에서 붙었다 — `§3.1` 표에는 처음부터 있었고
    라우트가 선언하지 않아 **조용히 버려졌다.** 이 모듈은 이미 같은 컬럼으로 거르는
    쿼리를 갖고 있었다(:func:`list_annual_inclusions`).
    """
    stmt = select(Voyage).where(Voyage.vessel_id == vessel_id, Voyage.is_deleted == 0)

    if status is not None:
        stmt = stmt.where(Voyage.status == status)
    if regulation_year is not None:
        stmt = stmt.where(Voyage.regulation_year == regulation_year)
    if annual_inclusion_policy is not None:
        stmt = stmt.where(Voyage.annual_inclusion_policy == annual_inclusion_policy)

    if cursor is not None:
        departure = departure_key()
        if cursor.departure_at is not None:
            # 출항 시각이 있는 묶음의 중간 — 같은 묶음의 뒤쪽 + 출항 시각 없는 묶음 전부.
            stmt = stmt.where(
                or_(
                    departure.is_(None),
                    tuple_(departure, Voyage.created_at, Voyage.id)
                    < (cursor.departure_at, cursor.created_at, cursor.voyage_id),
                )
            )
        else:
            # 이미 맨 아래 묶음(출항 시각 없음) — 그 안에서만 이어 간다.
            stmt = stmt.where(
                departure.is_(None),
                tuple_(Voyage.created_at, Voyage.id) < (cursor.created_at, cursor.voyage_id),
            )

    stmt = stmt.order_by(*_newest_departure_first()).limit(limit + 1)
    return list((await session.execute(stmt)).scalars().all())


async def list_for_export(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int | None = None,
) -> list[Voyage]:
    """내보내기용 — 선박의 활성 항차를 **전부** 조회한다 (`API_SPEC §8.1`, #59).

    :func:`list_active`와 나누는 이유는 **커서가 없다**는 점이다. 목록 화면은 페이지를
    넘기며 읽지만 내보내기는 파일 하나를 만들며, 페이지를 이어 붙이는 책임을 호출부에
    두면 「마지막 페이지를 빠뜨린 파일」이 만들어질 여지가 생긴다.

    상한을 두지 않는다. 조회가 **선박 하나 + (선택) 규제연도 하나**로 이미 한정돼
    있어 한 척이 한 해에 만드는 항차 수를 넘지 않고, 자르면 사용자는 **파일 끝이
    잘린 것을 모른 채** 연간 자료로 쓴다 (가져오기의 1,000행 상한이 잘라 낸 행 수를
    굳이 응답에 남기는 것과 같은 이유다).

    정렬은 :func:`list_active`와 같다(출항 시각 최신순 · 없는 항차는 맨 아래 · `#1806`) —
    화면 순서와 파일 순서가 갈리지 않는다.
    """
    stmt = select(Voyage).where(Voyage.vessel_id == vessel_id, Voyage.is_deleted == 0)
    if regulation_year is not None:
        stmt = stmt.where(Voyage.regulation_year == regulation_year)
    stmt = stmt.order_by(*_newest_departure_first())
    return list((await session.execute(stmt)).scalars().all())


async def list_annual_inclusions(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    policy: str,
    as_of: datetime | None = None,
) -> list[Voyage]:
    """연간 집계에 들어가는 항차를 ``annual_inclusion_policy``로 골라 온다 (#353).

    포함 여부의 정본은 ``PRD §8.1.2`` 매트릭스이며, 그 값이 ``voyage`` 행에 이미
    들어 있다. 따라서 여기서는 ``status``를 다시 해석하지 않고 **정책 컬럼 하나로**
    거른다 — ``status``로 판정하면 같은 규칙이 DB CHECK(``chk_voyage_inclusion``)와
    코드 두 곳에 생긴다.

    **``as_of`` 절단은 「도착 시각」 기준이다** — ``actual_arrival_at``이 있으면 그것을,
    없으면 ``planned_arrival_at``을 쓴다(``COALESCE``). 둘 다 NULL이면 절단하지 않고
    포함한다: 시각을 모르는 행을 «아직 아니다»로 단정할 근거가 없고, ``regulation_year``
    가 이미 연도를 한정하고 있다.

    :param policy: ``INCLUDE_AS_ACTUAL`` 또는 ``INCLUDE_AS_PLAN``. ``EXCLUDE``를
        넘기는 것은 호출부의 실수이므로 막지 않고 그대로 조회한다 — 저장소는 규칙을
        판정하지 않는다(TECH_SPEC §16).
    """
    stmt = select(Voyage).where(
        Voyage.vessel_id == vessel_id,
        Voyage.regulation_year == regulation_year,
        Voyage.annual_inclusion_policy == policy,
        Voyage.is_deleted == 0,
    )

    if as_of is not None:
        arrival_at = func.coalesce(Voyage.actual_arrival_at, Voyage.planned_arrival_at)
        stmt = stmt.where(or_(arrival_at.is_(None), arrival_at <= as_of))

    stmt = stmt.order_by(Voyage.created_at, Voyage.id)
    return list((await session.execute(stmt)).scalars().all())


async def list_annual_inclusions_for_vessels(
    session: AsyncSession,
    *,
    vessel_ids: Sequence[UUID],
    regulation_year: int,
    policy: str,
    as_of: datetime | None = None,
) -> dict[UUID, list[Voyage]]:
    """여러 선박의 :func:`list_annual_inclusions`을 **쿼리 한 번**으로 낸다 (#989 ⑵).

    선대 요약이 선박마다 ``compute_ytd_cii``를 네 번 부르는데, 그 매번 이 조회가
    선박 수만큼 나가는 것이 병목의 대부분이었다(200척 실측 4,624쿼리). WHERE·정렬은
    단건과 **글자로 같다** — 어느 한쪽만 고치면 대시보드 값이 선박 수에 따라 달라진다.

    없는 선박은 키가 없다(``.get(id, [])`` 규약 — :func:`find_in_progress_for_vessels`와 같다).
    """
    if not vessel_ids:
        return {}
    stmt = select(Voyage).where(
        Voyage.vessel_id.in_(list(vessel_ids)),
        Voyage.regulation_year == regulation_year,
        Voyage.annual_inclusion_policy == policy,
        Voyage.is_deleted == 0,
    )

    if as_of is not None:
        arrival_at = func.coalesce(Voyage.actual_arrival_at, Voyage.planned_arrival_at)
        stmt = stmt.where(or_(arrival_at.is_(None), arrival_at <= as_of))

    stmt = stmt.order_by(Voyage.created_at, Voyage.id)
    grouped: dict[UUID, list[Voyage]] = {}
    for voyage in (await session.execute(stmt)).scalars():
        grouped.setdefault(voyage.vessel_id, []).append(voyage)
    return grouped


async def list_remaining_plans(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime | None = None,
) -> list[Voyage]:
    """**잔여 계획** — 정책이 ``INCLUDE_AS_PLAN``인 항차 전부, 날짜로 자르지 않는다 (#1323).

    ⚠️ **도착 예정으로 자르지 않는다** (`#1323`). 종전에는 ``planned_arrival_at >
    as_of``를 걸어 **도착 예정이 지난 ``INCLUDE_AS_PLAN`` 항차가 어느 쪽에도 들지
    않았다** — 확정분 조회는 정책이 ``INCLUDE_AS_ACTUAL``인 것만 보고, 잔여는 이
    조건에서 잘렸다. 지연된 ``IN_PROGRESS``·기한이 지난 ``PLANNED``가 통째로
    사라졌고, 실측에서 연말 예상 등급이 **D → C**로 바뀌었다.

    **정본이 이미 답을 갖고 있다.** ``PRD §12.2``의 ``remaining_voyages`` 행은
    대상을 **상태(``PLANNED``/``IN_PROGRESS``)**로 적고 **날짜로 자르지 않는다** —
    `AGENTS §3.1`상 ``PRD`` > ``API_SPEC``이므로 「도착 예정 > ``as_of``」라 적던
    ``API_SPEC §6.1`` 쪽을 고쳤다.

    그래서 두 집합을 가르는 것은 **정책**이다: 실적이 확정된 것(``INCLUDE_AS_ACTUAL``)과
    아직 계획인 것(``INCLUDE_AS_PLAN``). **예정일이 지났다는 것은 도착했다는 뜻이
    아니다** — 그 상태를 알리는 것은 ``IN_PROGRESS_PAST_ETA`` 경고의 몫이고(`#649`),
    집계에서 빼는 근거가 아니다.

    ``as_of``는 **받되 쓰지 않는다** — 호출부가 확정·잔여에 같은 인자를 넘기는
    모양을 유지해, 어느 한쪽만 시점을 갖는 것처럼 읽히지 않게 한다.
    """
    stmt = select(Voyage).where(
        Voyage.vessel_id == vessel_id,
        Voyage.regulation_year == regulation_year,
        Voyage.annual_inclusion_policy == "INCLUDE_AS_PLAN",
        Voyage.is_deleted == 0,
    )

    stmt = stmt.order_by(Voyage.created_at, Voyage.id)
    return list((await session.execute(stmt)).scalars().all())


async def insert(session: AsyncSession, **fields: object) -> Voyage:
    """새 항차를 INSERT 한다. ``commit``은 호출부가 담당한다."""
    voyage = Voyage(**fields)
    session.add(voyage)
    await session.flush()
    return voyage


async def insert_fuel_use(session: AsyncSession, **fields: object) -> VoyageFuelUse:
    """항차 연료 사용 1건을 INSERT 한다."""
    fuel_use = VoyageFuelUse(**fields)
    session.add(fuel_use)
    await session.flush()
    return fuel_use


async def find_in_progress(session: AsyncSession, vessel_id: UUID) -> Voyage | None:
    """선박의 **진행 중 항차 한 건**을 돌려준다 (#354).

    실시간 화면(``UIFLOW 2-9``)은 「지금 어느 항차를 뛰고 있는가」를 물으며, 그
    답은 하나여야 한다. 선박이 동시에 두 항차를 진행하는 것은 데이터 오류지만
    **여기서 오류로 만들지 않는다** — 조회가 화면을 죽이면 사용자는 값을 볼 수도,
    잘못된 항차를 고칠 수도 없다. 가장 최근 출항분을 고르고 넘어간다.

    정렬 기준이 ``actual_departure_at``인 이유는 실제로 나간 시각이 진행 중 여부를
    가르기 때문이다. 계획 출항 시각으로 고르면 아직 안 나간 항차가 앞설 수 있다.
    NULL은 마지막으로 민다 — 출항 실적이 없는 IN_PROGRESS는 진행량이 0이라
    시뮬레이션 시계가 아무것도 만들지 못한다(``#368`` 경계 처리).
    """
    stmt = (
        select(Voyage)
        .where(
            Voyage.vessel_id == vessel_id,
            Voyage.status == "IN_PROGRESS",
            Voyage.is_deleted == 0,
        )
        .order_by(Voyage.actual_departure_at.desc().nullslast(), Voyage.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def find_in_progress_for_vessels(
    session: AsyncSession, vessel_ids: Sequence[UUID]
) -> dict[UUID, Voyage]:
    """여러 선박의 진행 중 항차를 **쿼리 한 번**으로 모아 온다 (`#763`).

    선대 지도가 항로선을 그리려면 선박마다 진행 중 항차의 출발·도착 좌표가 필요하다.
    :func:`find_in_progress`를 척마다 부르면 200척에 200쿼리가 붙는데, 그 엔드포인트는
    **방금 쿼리 수를 줄여 놓은 자리**다(`#989` — 212쿼리 → 129쿼리). 그래서 한 번에 묻는다.

    선박당 하나만 남긴다 — 고르는 규칙은 :func:`find_in_progress`와 **같다**(실제 출항
    시각 내림차순, NULL은 뒤). 두 경로가 다른 항차를 고르면 같은 화면의 두 값이 서로
    다른 항차를 가리킨다.
    """
    if not vessel_ids:
        return {}
    stmt = (
        select(Voyage)
        .where(
            Voyage.vessel_id.in_(list(vessel_ids)),
            Voyage.status == "IN_PROGRESS",
            Voyage.is_deleted == 0,
        )
        .order_by(Voyage.actual_departure_at.desc().nullslast(), Voyage.id)
    )
    found: dict[UUID, Voyage] = {}
    for voyage in (await session.execute(stmt)).scalars():
        # 정렬이 이미 우선순위라 **먼저 온 것만** 남긴다.
        found.setdefault(voyage.vessel_id, voyage)
    return found


async def mark_calculations_needing_recalc(session: AsyncSession, voyage_id: UUID) -> int:
    """이 항차의 계산 결과에 **재계산 필요 표시**를 남긴다 (`PRD §8.4`, #58).

    선박 단위 함수(``calculation_run.mark_needs_recalc``)와 나눠 두는 이유는 **범위가
    다르기 때문**이다 — 제원 변경은 그 선박의 모든 계산을 흔들지만, 항차 계획 변경은
    그 항차의 계산만 무효로 만든다. 넓게 잡으면 관계없는 계산까지 「다시 해야 한다」로
    표시되어 표시 자체가 무의미해진다.

    ``needs_recalc = false``인 행만 갱신한다 — true→false 되돌림은 가드 트리거(024)가
    거부하고, 이미 표시된 행은 누적 전용이다.
    """
    from sqlalchemy import update

    from cii_platform.db.models.calculation_run import CalculationRun

    result = await session.execute(
        update(CalculationRun)
        .where(
            CalculationRun.voyage_id == voyage_id,
            CalculationRun.needs_recalc == 0,
        )
        .values(needs_recalc=True)
    )
    return result.rowcount or 0
