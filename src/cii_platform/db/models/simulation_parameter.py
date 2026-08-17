"""simulation_parameter ORM 모델.

DB_SCHEMA.md §2.19 참조. 컬럼·제약·인덱스 정의는 마이그레이션 035와 1:1로 일치해야
한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

이슈 #434: ``PRD §12.4.1``이 *"분포 기본값은 ``simulation_parameter``로 관리하며 코드
하드코딩하지 않는다"* 를 요구하는데 **그 테이블이 없었다.** 삼각분포의 min/mode/max는
규제값이 아니라 **모델 가정**이고, 운항 데이터가 쌓이면 조정될 값이라 코드 밖에 둔다.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class SimulationParameter(Base):
    """Monte Carlo 분포 파라미터 1행 — (프로파일, 변수) 조합 하나."""

    __tablename__ = "simulation_parameter"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    #: ``PRD §12.2``의 ``distribution_profile`` 입력값과 같은 어휘.
    profile = sa.Column(sa.String(length=30), nullable=False)
    variable = sa.Column(sa.String(length=20), nullable=False)
    distribution = sa.Column(sa.String(length=20), nullable=False)
    #: ``FACTOR``(계획값의 배수) · ``DELTA``(계획값에 더하는 값).
    #:
    #: ``PRD §12.4.1`` 표에서 거리·연료는 배수(``0.97×plan``)지만 속도는 덧셈
    #: (``plan − 1kn``)이다. 한 컬럼 집합으로 둘을 담으려면 **해석 방식을 행이 스스로
    #: 말해야 한다** — 배수만 지원하면 속도를 표현할 수 없다.
    bound_type = sa.Column(sa.String(length=10), nullable=False)
    min_value = sa.Column(sa.Numeric(precision=10, scale=4), nullable=False)
    #: 최빈값. 계획값 자체이므로 ``FACTOR``면 1.0, ``DELTA``면 0.0이다.
    mode_value = sa.Column(sa.Numeric(precision=10, scale=4), nullable=False)
    max_value = sa.Column(sa.Numeric(precision=10, scale=4), nullable=False)
    #: 물리 하한. 속도만 1.0(kn)을 갖는다 — [ORACLE 삼각분포 가드].
    floor_value = sa.Column(sa.Numeric(precision=10, scale=4), nullable=True)
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    version = sa.Column(sa.String(length=50), nullable=False)
    is_active = sa.Column(sa.Boolean(), server_default=sa.text("true"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_simulation_parameter"),
        sa.CheckConstraint(
            "variable IN ('DISTANCE','FUEL','SPEED')", name="chk_sim_param_variable"
        ),
        # MVP는 삼각분포 하나다. 늘어나면 이 제약과 계산 엔진을 함께 고쳐야 한다.
        sa.CheckConstraint("distribution IN ('TRIANGULAR')", name="chk_sim_param_distribution"),
        sa.CheckConstraint("bound_type IN ('FACTOR','DELTA')", name="chk_sim_param_bound_type"),
        # [ORACLE 삼각분포 가드] — 애플리케이션도 재조정하지만(계산이 파라미터 오타로
        # 죽지 않게), 애초에 위반한 행이 들어오지 않는 편이 낫다.
        sa.CheckConstraint(
            "min_value <= mode_value AND mode_value <= max_value",
            name="chk_sim_param_bounds_ordered",
        ),
        sa.CheckConstraint(
            "floor_value IS NULL OR floor_value > 0", name="chk_sim_param_floor_positive"
        ),
        # 조회는 언제나 (프로파일, 변수) 단위다. 같은 조합이 둘이면 어느 쪽을 쓸지 알 수 없다.
        sa.Index("idx_sim_param_unique", "profile", "variable", unique=True),
    )
