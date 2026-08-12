"""선박 저장소 — 쿼리만 담당한다 (TECH_SPEC §16).

비즈니스 판단(없을 때 무엇을 할지, 어떤 오류를 던질지)은 여기 두지 않는다. 그건
``services``의 몫이다. 이 모듈은 **찾으면 반환하고 없으면 ``None``**을 준다.
"""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy import or_, select, tuple_

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
    stmt = select(Vessel).where(Vessel.id == vessel_id, Vessel.is_deleted.is_(False))
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_active_by_imo(session: AsyncSession, imo_number: str) -> Vessel | None:
    """활성 선박을 IMO 번호로 조회한다 (#50, soft delete 제외).

    ``idx_vessel_imo`` partial unique 인덱스(WHERE ``is_deleted = false``)를 탄다
    (DB_SCHEMA §2.1). 중복 체크의 기준이 "soft delete 제외"인 이유 — 삭제된 IMO는
    재등록 가능(이슈 #50 완료 기준).
    """
    stmt = select(Vessel).where(
        Vessel.imo_number == imo_number,
        Vessel.is_deleted.is_(False),
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
    stmt = select(Vessel).where(Vessel.is_deleted.is_(False))

    if ship_type is not None:
        stmt = stmt.where(Vessel.ship_type == ship_type)

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(or_(Vessel.name.ilike(pattern), Vessel.imo_number.like(pattern)))

    if cursor is not None:
        # 행 값 비교. (name, id) > (:name, :id) 를 한 번에 표현한다 —
        # OR 조건으로 풀어 쓰면 인덱스를 타지 못하는 형태가 되기 쉽다.
        stmt = stmt.where(tuple_(Vessel.name, Vessel.id) > (cursor.name, cursor.vessel_id))

    stmt = stmt.order_by(Vessel.name, Vessel.id).limit(limit + 1)
    return list((await session.execute(stmt)).scalars().all())
