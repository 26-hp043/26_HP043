"""cii_reference_line ORM 모델.

DB_SCHEMA.md §2.10 (cii_reference_line) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 010과 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class CiiReferenceLine(Base):
    """CII reference line (G2): 선종별 조건에 따른 기준선."""

    __tablename__ = "cii_reference_line"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    ship_type = sa.Column(sa.String(length=50), nullable=False)
    condition_expr = sa.Column(sa.String(length=200), nullable=False)
    capacity_rule = sa.Column(sa.String(length=50), nullable=False)
    # TECH_SPEC §9: a_raw(IMO 원문 표기) + a_decimal(변환값) 이중 저장.
    a_raw = sa.Column(sa.String(length=50), nullable=False)
    a_decimal = sa.Column(sa.Numeric(precision=30, scale=6), nullable=False)
    c = sa.Column(sa.Numeric(precision=10, scale=6), nullable=False)
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_cii_reference_line"),
        # 🔴 정본 `§2.10 [M-7]`은 「`fixed` 뒤에 **숫자만**」이다 — 종전 `LIKE 'fixed %'`는
        # `fixed abc`도 통과시켰다(`#1058` · 인계 v7 §6). `050`이 집행 트리거를
        # `REGEXP BINARY '^fixed [0-9]+$'`로 좁혔고, **선언도 함께 고친다** — 선언과 집행이
        # 갈리면 다음 사람이 어느 쪽을 믿을지 알 수 없다.
        #
        # `BINARY`가 붙는 이유 — CUBRID의 `REGEXP`는 기본이 대소문자 무시라 `FIXED 12`도
        # 통과한다. 정본의 `~`는 대소문자를 구분한다(실측).
        #
        # ⚠️ 이 CHECK는 **DB에 존재하지 않는다.** CUBRID는 CHECK 선언을 보관조차 하지
        # 않는다 — `ALTER TABLE … DROP CONSTRAINT chk_capacity_rule`이
        # `Constraint "…" not found.`를 낸다(실측 · `DB_SCHEMA §7.4`). 여기 적는 것은
        # **정본이 규정한 규칙의 기록**이고, 집행은 `050`의 트리거가 한다.
        sa.CheckConstraint(
            "capacity_rule IN ('DWT','GT') OR capacity_rule REGEXP BINARY '^fixed [0-9]+$'",
            name="chk_capacity_rule",
        ),
        sa.CheckConstraint("a_decimal > 0", name="chk_a_decimal_positive"),
        # c >= 0: LNG_CARRIER DWT >= 100000은 c = 0.000000이 정상([Oracle 관찰]).
        sa.CheckConstraint("c >= 0", name="chk_c_positive"),
        # §2.10 인덱스 (원문 그대로).
        sa.Index(
            "idx_refline_unique",
            "ship_type",
            "condition_expr",
            unique=True,
        ),
        sa.Index("idx_refline_ship_type", "ship_type"),
    )
