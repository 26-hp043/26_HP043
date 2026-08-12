#!/usr/bin/env python
"""IMO 규제 파라미터 seed 실행 스크립트 (#33).

``python scripts/seed.py``로 실행한다. 대상 DB는 ``DATABASE_URL`` 환경변수를 따르며,
미설정 시 ``cii_platform.config``의 기본값을 쓴다.

seed 데이터와 적재 로직은 ``cii_platform.db.seed``에 있다 — 이 파일은 진입점일 뿐이다.
재실행해도 결과가 같다(upsert). 스키마는 미리 ``alembic upgrade head``로 만들어 둔다.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# src 레이아웃을 sys.path에 추가하여 editable 설치 없이도 import할 수 있게 한다
# (alembic/env.py·tests/conftest.py와 동일 정책).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cii_platform.config import DATABASE_URL  # noqa: E402
from cii_platform.db.seed import seed_all  # noqa: E402
from cii_platform.db.url import normalize_to_asyncpg  # noqa: E402


async def main() -> None:
    """엔진을 열고 단일 트랜잭션으로 seed를 적재한다."""
    # URL 정규화는 alembic/env.py·tests/conftest.py·db/session.py와 같은 함수를
    # 공유한다 (#234). 사본을 두면 앱만 분기가 빠지는 일이 다시 생긴다.
    engine = create_async_engine(normalize_to_asyncpg(DATABASE_URL), poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            counts = await seed_all(conn)
    finally:
        # 성공·실패와 무관하게 커넥션을 반납한다.
        await engine.dispose()

    for table, count in counts.items():
        print(f"{table}: {count}행 적재(upsert)")


if __name__ == "__main__":
    asyncio.run(main())
