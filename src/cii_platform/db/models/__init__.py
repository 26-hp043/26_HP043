"""SQLAlchemy ORM 모델.

DB_SCHEMA.md의 테이블에 대응하는 ORM 모델을 정의하는 자리다. DB 관련 코드를
``db`` 트리로 응집하기 위해 저장소(``db.repositories``)와 같은 레이어에 둔다.

본 이슈(#100)는 빈 패키지와 역할만 확정한다. ``Base`` 클래스 정의와
``alembic/env.py``의 ``target_metadata`` 연결은 후행 이슈 #101(SQLAlchemy ORM
모델 정의 및 Alembic 연결)에서 수행한다.

계층 규칙은 TECH_SPEC §16 참조.
"""
