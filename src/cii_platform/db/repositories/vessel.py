"""선박 저장소 — 쿼리만 담당한다 (TECH_SPEC §16).

비즈니스 판단(없을 때 무엇을 할지, 어떤 오류를 던질지)은 여기 두지 않는다. 그건
``services``의 몫이다. 이 모듈은 **찾으면 반환하고 없으면 ``None``**을 준다.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy import or_, select, tuple_, update

from cii_platform.db.models.vessel import Vessel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: API_SPEC §2.1 — 페이지 크기 기본 20, 최대 100.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: 커서 인코딩 구분자. 선박명에 등장할 수 없는 제어문자를 쓴다.
_CURSOR_SEP = "\x00"


class Cursor(NamedTuple):
    """keyset 페이지네이션 커서 — 정렬 키 ``(name, id)``의 마지막 값.

    **offset이 아니라 keyset을 쓰는 이유**: offset은 앞 페이지에서 행이 삭제되면
    다음 페이지가 한 건을 건너뛴다. 정렬 키를 그대로 담으면 그 문제가 없다.
    """

    name: str
    vessel_id: str


def encode_cursor(cursor: Cursor) -> str:
    """커서를 URL-safe base64 문자열로 만든다.

    **불투명한 문자열로 내보내는 이유**: API_SPEC §2.1이 ``cursor``를 「페이지네이션
    커서」로만 규정하고 형식을 정하지 않았다. 내부 구조를 노출하면 클라이언트가
    그것에 의존하게 되어 정렬 키를 바꿀 수 없게 된다.
    """
    raw = f"{cursor.name}{_CURSOR_SEP}{cursor.vessel_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> Cursor | None:
    """커서를 되돌린다. 형식이 깨졌으면 ``None``.

    **예외를 던지지 않는다.** 잘못된 커서는 사용자가 URL을 손댄 경우가 대부분이고,
    그때 500이 나가면 안 된다. 오류로 볼지 첫 페이지로 볼지는 서비스가 정한다.

    **``vessel_id``가 UUID 형식인지 검증한다 (#233).** base64는 정상이더라도
    안에 든 값이 UUID가 아니면 asyncpg가 쿼리 바인딩 단계에서 거절해 500이 나간다.
    ``Vessel.id``가 ``postgresql.UUID(as_uuid=True)``인데, asyncpg 방언의 bind
    processor가 ``None``이라 문자열이 그대로 드라이버로 내려가기 때문이다. 그 경로를
    여기서 막아 서비스의 422 변환(``_parse_cursor``)이 동작하게 한다.

    ``Cursor.vessel_id``를 ``UUID``로 바꾸지 않고 ``str``으로 유지한다 —
    ``encode_cursor``가 ``str(page[-1].id)``로 인코딩하므로 왕복 계약이 str에 맞춰져
    있고, ``list_active``의 ``tuple_`` 비교도 str 그대로 바인딩한다(UUID 객체로
    바꾸면 타입이 달라져 정렬 비교가 깨진다).
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    name, sep, vessel_id = raw.partition(_CURSOR_SEP)
    if not sep or not vessel_id:
        return None
    # UUID 형식 검증 — 잘못된 값이 DB까지 내려가 500이 나는 것을 막는다 (#233).
    try:
        UUID(vessel_id)
    except ValueError:
        return None
    return Cursor(name=name, vessel_id=vessel_id)


async def get_by_id(session: AsyncSession, vessel_id: UUID) -> Vessel | None:
    """활성 선박 1건을 조회한다.

    **soft delete된 행은 제외한다.** ``vessel``의 인덱스가 전부
    ``WHERE is_deleted = false`` partial이므로(DB_SCHEMA §2.1) 조회도 같은 조건을
    써야 인덱스를 타고, 무엇보다 삭제된 선박으로 계산이 되면 안 된다.
    """
    stmt = select(Vessel).where(Vessel.id == vessel_id, Vessel.is_deleted == 0)
    return (await session.execute(stmt)).scalar_one_or_none()


async def lock_row(session: AsyncSession, vessel_id: UUID) -> bool:
    """선박 행 하나를 ``SELECT … FOR UPDATE``로 **잠근다** (`#1629` · `TECH_SPEC §16.3`).

    「이 선박의 자식 행을 읽고 판정한 뒤 쓴다」는 경로가 판정 **전에** 부른다. 판정과
    쓰기 사이에 다른 요청이 끼면 **둘 다 같은 옛 상태를 보고** 통과한다 — 겹치는 정박
    구간이 둘 남는 형태다(`#1796` 실측: READ COMMITTED에서 미커밋 INSERT는 보이지 않고
    대기도 없다). 자식 행(구간)은 아직 없으므로 잠글 수 없고 **부모인 선박 행**을
    잡는다 — `services/auth_token.issue_token`이 사용자 행에 하는 것과 같은 도구다.

    삭제 여부를 보지 않는다 — 존재 판정은 :func:`get_by_id`의 몫이고, 이 함수는 행이
    있으면 잡을 뿐이다. 잠금은 호출부가 커밋·롤백할 때 함께 풀린다(트랜잭션 경계는
    바꾸지 않는다). CUBRID는 ``NOWAIT``·``SKIP LOCKED``가 없고 서버 기본이
    ``lock_timeout=-1``이라 앞 요청이 끝날 때까지 **기다린다**.

    :returns: 행을 잡았으면 ``True``. 없는 행에는 잠금이 걸리지 않으므로 ``False``다.
    """
    stmt = select(Vessel.id).where(Vessel.id == vessel_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def update_current_position_if_newer(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    lat: Decimal,
    lon: Decimal,
    observed_at: datetime,
    underway_state: str | None = None,
    detail_status: str | None = None,
) -> bool:
    """**더 새 관측일 때만** 현재 위치를 덮는다 (`#1628` · `TECH_SPEC §16.3`).

    비교와 쓰기를 **한 문장 안에서** 한다. 종전에는 파이썬이 읽어 비교한 뒤 ORM으로
    덮었는데, 두 적재가 교차하면 **먼저 읽은 오래된 관측이 나중에 커밋되어** 현재
    위치를 과거로 되돌린다 — 화면에서는 배가 뒤로 간다. 배치가 겹쳐 돌거나 재전송이
    섞이면 실제로 일어나는 순서다.

    :returns: 실제로 덮었으면 ``True``. 더 오래된(또는 같은) 관측이면 ``False``이며
        **오류가 아니다** — 늦게 온 옛 값을 버리는 것이 이 함수의 일이다.

    운항 상태 두 축은 **함께** 적는다(026 `chk_vessel_state_pair`가 한쪽만 바뀐 상태를
    거부한다). 둘 다 ``None``이면 상태는 건드리지 않는다.
    """
    values: dict[str, object] = {
        "current_lat": lat,
        "current_lon": lon,
        "position_updated_at": observed_at,
    }
    if underway_state is not None and detail_status is not None:
        values["underway_state"] = underway_state
        values["detail_status"] = detail_status

    stmt = (
        update(Vessel)
        .where(
            Vessel.id == vessel_id,
            Vessel.is_deleted == 0,
            # `IS NULL`이거나 더 오래된 것일 때만 — 같은 시각은 덮지 않는다(같은 값이다).
            or_(Vessel.position_updated_at.is_(None), Vessel.position_updated_at < observed_at),
        )
        .values(**values)
    )
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0


async def find_active_by_imo(session: AsyncSession, imo_number: str) -> Vessel | None:
    """활성 선박을 IMO 번호로 조회한다 (#50, soft delete 제외).

    ``idx_vessel_imo`` partial unique 인덱스(WHERE ``is_deleted = false``)를 탄다
    (DB_SCHEMA §2.1). 중복 체크의 기준이 "soft delete 제외"인 이유 — 삭제된 IMO는
    재등록 가능(이슈 #50 완료 기준).
    """
    stmt = select(Vessel).where(
        Vessel.imo_number == imo_number,
        Vessel.is_deleted == 0,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert(session: AsyncSession, **fields: object) -> Vessel:
    """새 선박을 INSERT 한다 (#50).

    **``commit``은 호출부가 담당한다.** 트랜잭션 경계를 서비스가 잡도록 두기
    위해서다 — 여러 변경이 한 트랜잭션에 묶여야 할 때 repo가 직접 ``commit``하면
    부분 커밋이 된다. ``flush``만 해서 ``server_default``(``id`` · ``created_at``)
    값을 채운 뒤 ORM 객체를 돌려준다.
    """
    vessel = Vessel(**fields)
    session.add(vessel)
    await session.flush()
    return vessel


async def list_all_active(session: AsyncSession) -> list[Vessel]:
    """활성 선박 **전부**를 ``(name, id)`` 순으로 (선대 요약 · #772).

    선대 요약은 ``summary``·``actions``가 **선대 전체** 기준이라 선박을 자를 수 없다
    (`API_SPEC §2.8`). 종전에는 ``list_active(limit=200)``을 잘라 써서 201번째 선박부터
    집계에서 **조용히** 빠졌다. 페이지는 서비스가 계산 뒤에 자른다.
    """
    stmt = select(Vessel).where(Vessel.is_deleted == 0).order_by(Vessel.name, Vessel.id)
    return list((await session.execute(stmt)).scalars().all())


async def list_active(
    session: AsyncSession,
    *,
    limit: int,
    cursor: Cursor | None = None,
    ship_type: str | None = None,
    search: str | None = None,
) -> list[Vessel]:
    """활성 선박 목록을 조회한다 (API_SPEC §2.1).

    정렬 기준을 ``(name, id)``로 두는 이유: 화면의 선박 선택지가 이 순서로 그려지는데,
    정렬이 없으면 PostgreSQL이 물리적 순서로 돌려주어 **같은 데이터에서도 요청마다
    순서가 달라질 수 있다.** ``id``를 2차 키로 두어 동명 선박에서도 순서가 고정되고,
    그래야 keyset 커서가 성립한다.

    **``limit + 1``건을 가져온다.** 호출부가 「다음 페이지가 있는가」를 별도 COUNT
    쿼리 없이 판단할 수 있게 하기 위해서다 — 초과분은 호출부가 잘라낸다.

    ``search``는 선박명 부분일치 또는 IMO 번호 부분일치다. 선박명 쪽은 003이 만든
    ``idx_vessel_name``(pg_trgm GIN)이 받는다.
    """
    stmt = select(Vessel).where(Vessel.is_deleted == 0)

    if ship_type is not None:
        stmt = stmt.where(Vessel.ship_type == ship_type)

    if search:
        # % · _ · \ 를 패턴 메타문자가 아닌 리터럴로 이스케이프한다 (#237).
        # 순서가 중요한데, backslash를 먼저 두 배로 만들어야 뒤의 %·_ 치환 시
        # 새로 생긴 backslash가 다시 이스케이프 대상이 되지 않는다.
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                Vessel.name.ilike(pattern, escape="\\"),
                Vessel.imo_number.like(pattern, escape="\\"),
            )
        )

    if cursor is not None:
        # 행 값 비교. (name, id) > (:name, :id) 를 한 번에 표현한다 —
        # OR 조건으로 풀어 쓰면 인덱스를 타지 못하는 형태가 되기 쉽다.
        stmt = stmt.where(tuple_(Vessel.name, Vessel.id) > (cursor.name, cursor.vessel_id))

    stmt = stmt.order_by(Vessel.name, Vessel.id).limit(limit + 1)
    return list((await session.execute(stmt)).scalars().all())
