"""SQLAlchemy declarative base.

모든 ORM 모델은 이 ``Base``를 상속한다. ``Base.metadata``가 스키마의 단일 소스로
``alembic/env.py``의 ``target_metadata``에 연결되어 autogenerate(모델↔DB 비교)에
사용된다.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 ORM 모델의 declarative base."""
