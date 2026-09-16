"""SQLAlchemy declarative base.

모든 ORM 모델은 이 ``Base``를 상속한다. ``Base.metadata``가 스키마의 단일 소스로
``alembic/env.py``의 ``target_metadata``에 연결되어 autogenerate(모델↔DB 비교)에
사용된다.
"""

from sqlalchemy.orm import DeclarativeBase

#: 모든 FK의 ``ON UPDATE`` 동작 (`#1058`).
#:
#: **CUBRID의 FK는 ON UPDATE를 항상 가지며, 기본이 RESTRICT다.** 카탈로그를 반영하면
#: 모든 FK가 그렇게 나온다 — 실측이다::
#:
#:     inspect(engine).get_foreign_keys("annual_simulation_run")
#:     → {'ondelete': 'RESTRICT', 'onupdate': 'RESTRICT'}   (세 FK 모두)
#:
#: 그런데 ORM은 ``ondelete``만 적고 있었다. 그래서 ``compare_metadata``가 FK 하나마다
#: ``remove_fk``(DB에 있다) + ``add_fk``(모델에 없다) 쌍을 냈고, 그것이
#: ``test_orm_schema_sync``가 보던 불일치 **61건의 대부분**이었다.
#:
#: 고치는 방향은 **모델이 사실을 적는 쪽**이다. 비교에서 ``onupdate``를 빼면 drift는
#: 0이 되지만, DB가 실제로 강제하는 동작이 모델 어디에도 적히지 않는다.
#:
#: DDL로 내보내도 안전하다 — CUBRID는 ``ON UPDATE``에 ``RESTRICT``·``NO ACTION``·
#: ``SET …``을 받고 ``CASCADE``만 거부한다(실측)::
#:
#:     … ON DELETE RESTRICT ON UPDATE RESTRICT   → Execute OK
#:     … ON UPDATE CASCADE                       → Syntax error: unexpected 'CASCADE',
#:                                                 expecting NO or RESTRICT or SET
#:
#: ⚠️ 그래서 **전환 전의 ``onupdate="CASCADE"``는 되살릴 수 없다.** 연료 코드를 개명하면
#: 전파되는 대신 막힌다(``a7d3e9b14f26``의 판단 그대로 — 여는 쪽이 아니라 닫는 쪽이다).
FK_ON_UPDATE = "RESTRICT"


class Base(DeclarativeBase):
    """모든 ORM 모델의 declarative base."""
