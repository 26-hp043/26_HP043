"""SQLAlchemy declarative base.

모든 ORM 모델은 이 ``Base``를 상속한다. ``Base.metadata``가 스키마의 단일 소스로
``alembic/env.py``의 ``target_metadata``에 연결되어 autogenerate(모델↔DB 비교)에
사용된다.

주: 이슈 #101 본문의 ``declarative_base()``는 SQLAlchemy 1.x API이며, 본 프로젝트는
SQLAlchemy 2.0(pyproject: ``sqlalchemy[asyncio]>=2.0``)이므로 동등한 2.0 방식인
``DeclarativeBase`` 상속으로 정의한다 (기능 동일: ``Base.metadata`` 제공).
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 ORM 모델의 declarative base."""
