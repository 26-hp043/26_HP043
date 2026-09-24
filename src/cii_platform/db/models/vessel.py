"""vessel ORM 모델.

DB_SCHEMA.md §2.1 (vessel) 참조. 컬럼·제약·인덱스 정의는 마이그레이션 003과 1:1로
일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class Vessel(Base):
    """선박."""

    __tablename__ = "vessel"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    imo_number = sa.Column(sa.String(length=7), nullable=False)
    name = sa.Column(sa.String(length=100), nullable=False)
    ship_type = sa.Column(sa.String(length=50), nullable=False)
    gross_tonnage = sa.Column(sa.Numeric(precision=12, scale=2), nullable=True)
    deadweight = sa.Column(sa.Numeric(precision=12, scale=2), nullable=True)
    default_fuel_type = sa.Column(sa.String(length=30), nullable=True)
    reference_speed_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    reference_daily_foc_ton = sa.Column(sa.Numeric(precision=8, scale=2), nullable=True)
    # 방형계수(CB) — 기상 보정(Townsin–Kwon)의 선형 계수 (#966 · 055). 선택 입력:
    # 넣으면 실측값, 안 넣으면 선종 기본값 + CB_ESTIMATED 경고. 범위는 물리 범위다
    # (체적 비율 — 양수, 1 이하). 선언의 집행은 055의 트리거가 한다.
    block_coefficient = sa.Column(sa.Numeric(precision=4, scale=3), nullable=True)
    # 호출부호(call sign) — 공공데이터 교차 대조의 키 (#1197 A단계 · 058). 선택 입력:
    # 해양수산부_선박운항정보 API가 IMO가 아니라 호출부호로 질의하므로 없으면 그 배는
    # 대조 대상이 아닐 뿐 계산은 그대로다. ITU RR No.19.55상 4~7자·영대문자+숫자.
    # 재배정되는 값이라 UNIQUE를 걸지 않는다. 형식 집행은 058의 트리거가 한다.
    call_sign = sa.Column(sa.String(length=7), nullable=True)
    is_cii_applicable_hint = sa.Column(
        sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False
    )
    is_deleted = sa.Column(sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False)
    # 활성 키 (#1631 · 061). 활성 행이면 `imo_number`의 사본, 소프트 삭제된 행이면 NULL —
    # 그 위의 유니크 인덱스 `uq_vessel_imo_active`가 「활성 행 안에서만 유일」을 DB에서
    # 강제한다(CUBRID 유니크 인덱스는 NULL을 여러 개 허용한다 — 061 실측). **앱은 이 열을
    # 쓰지 않는다.** 값은 061의 트리거 `trg_vessel_imo_active_ins`·`_upd`가 `is_deleted`에
    # 따라 채운다 — 여기서 대입해도 트리거가 바로잡는다. flush 뒤 이 속성은 갱신 전 값
    # (None) 그대로이므로 읽지 않는다.
    imo_active = sa.Column(sa.String(length=7), nullable=True)
    # 현재 위치·운항 상태 (마이그레이션 026 · #346). 전부 NULL 허용 — 위치를 모르는
    # 미갱신 선박(기존 3척 포함)도 정상 조회돼야 한다.
    # 계산 축(2값) — CII 집계는 「항해 중이냐」 이진 판단만 한다.
    underway_state = sa.Column(sa.String(length=20), nullable=True)
    # 화면 축(7값) — SAILING을 제외한 6값은 not_underway_period.period_type(025)과 1:1.
    detail_status = sa.Column(sa.String(length=20), nullable=True)
    current_lat = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    current_lon = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    # 위치가 있으면 필수 — 화면이 「위치 갱신 시각」을 표시한다(UIFLOW §2-8).
    position_updated_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    # updated_at 자동 갱신은 열 속성 ON UPDATE CURRENT_DATETIME(마이그레이션 049 · DB_SCHEMA §7.2)이
    # 담당한다 — CUBRID에는 갱신 트리거가 없다(재귀에 걸린다).
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_vessel"),
        # [S-1] / §7.1: default_fuel_type → fuel_type(code), ON UPDATE CASCADE, ON DELETE NO ACTION.
        # §2.1 검증 제약 (원문 그대로).
        #
        # `chk_imo_format`은 여기 없다 — PostgreSQL 전용 `~` 정규식이라 CUBRID가 받지
        # 않아 전환(`9ddeb22`)에서 뺐다. 그때 **이 주석 줄과 다음 줄이 붙어**
        # `chk_gt_positive`가 주석 안으로 들어가 함께 죽었다 — 의도한 삭제는 하나인데
        # 둘이 사라졌다. 형제 제약(`chk_dwt_positive`·`chk_speed_positive`)은 살아
        # 있으므로 되살려 나란히 둔다 (`#1058`).
        #
        # CUBRID가 CHECK를 **강제하지 않는다**는 사실은 `DB_SCHEMA §7.4`에 있다.
        # 여기 적힌 것은 다른 엔진에서의 계약이자 문서이지 배포의 방어가 아니다.
        sa.CheckConstraint("gross_tonnage IS NULL OR gross_tonnage > 0", name="chk_gt_positive"),
        sa.CheckConstraint("deadweight IS NULL OR deadweight > 0", name="chk_dwt_positive"),
        sa.CheckConstraint(
            "reference_speed_kn IS NULL OR reference_speed_kn > 0", name="chk_speed_positive"
        ),
        # #1269 — 속력의 물리 상한(VAL-009). 선언은 문서이고 집행은 062 트리거가 한다(§7.4).
        sa.CheckConstraint(
            "reference_speed_kn IS NULL OR reference_speed_kn <= 60", name="chk_speed_max"
        ),
        # #966 — 방형계수의 물리 범위. 선언은 문서이고 집행은 055 트리거가 한다(§7.4).
        sa.CheckConstraint(
            "block_coefficient IS NULL OR (block_coefficient > 0 AND block_coefficient <= 1)",
            name="chk_block_coefficient_range",
        ),
        # #1197 — `call_sign` 형식 CHECK는 `chk_imo_format`과 같은 이유로 여기 없다(`~`
        # 정규식은 CUBRID가 받지 않는다). 집행은 058의 트리거 `trg_chk_call_sign_ins/upd`.
        # 026 (#346) — 운항 상태 2축·위치 제약. 마이그레이션과 1:1.
        sa.CheckConstraint(
            "underway_state IS NULL OR underway_state IN ('UNDER_WAY','NOT_UNDER_WAY')",
            name="chk_underway_state_allowed",
        ),
        sa.CheckConstraint(
            "detail_status IS NULL OR detail_status IN "
            "('SAILING','IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')",
            name="chk_detail_status_allowed",
        ),
        # 정합 규칙 — 둘 다 NULL 또는 유효 조합(SAILING↔UNDER_WAY, 나머지↔NOT_UNDER_WAY).
        # IS NOT NULL 가드가 필요하다 — NULL 비교는 UNKNOWN을 반환하고 CHECK는
        # FALSE일 때만 거부하므로, 가드 없이는 반쪽 상태(한 축만 설정)가 통과한다.
        sa.CheckConstraint(
            "(underway_state IS NULL AND detail_status IS NULL) "
            "OR (underway_state IS NOT NULL AND detail_status IS NOT NULL AND ("
            "underway_state = 'UNDER_WAY' AND detail_status = 'SAILING' "
            "OR underway_state = 'NOT_UNDER_WAY' AND detail_status IN "
            "('IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')))",
            name="chk_vessel_state_pair",
        ),
        sa.CheckConstraint(
            "current_lat IS NULL OR current_lat BETWEEN -90 AND 90",
            name="chk_vessel_lat_range",
        ),
        sa.CheckConstraint(
            "current_lon IS NULL OR current_lon BETWEEN -180 AND 180",
            name="chk_vessel_lon_range",
        ),
        sa.CheckConstraint(
            "(current_lat IS NULL AND current_lon IS NULL) "
            "OR (current_lat IS NOT NULL AND current_lon IS NOT NULL "
            "AND position_updated_at IS NOT NULL)",
            name="chk_vessel_position_pair",
        ),
        # §2.1 인덱스. soft delete 호환 — **활성 행 안에서만 유일**이다.
        #
        # PostgreSQL 시절에는 `WHERE is_deleted = false`인 부분 유니크 인덱스였는데
        # **CUBRID에는 조건이 붙는 인덱스가 없다** (`#1058`). `047`은 유일성을 트리거로
        # 옮겼으나 트리거의 `NOT EXISTS`는 미커밋 행을 못 봐 동시 등록에서 중복이 남았다
        # (`#1631` 실측). `061`이 그 트리거를 걷고 활성 키 열 `imo_active`의 **유니크
        # 인덱스**로 옮겼다 — 아래 `uq_vessel_imo_active`. `idx_vessel_imo`는 조회용이다.
        sa.Index(
            "idx_vessel_imo",
            "imo_number",
        ),
        sa.Index(
            "uq_vessel_imo_active",
            "imo_active",
            unique=True,
        ),
        sa.Index(
            "idx_vessel_ship_type",
            "ship_type",
        ),
        sa.Index(
            "idx_vessel_name",
            "name",
        ),
    )
