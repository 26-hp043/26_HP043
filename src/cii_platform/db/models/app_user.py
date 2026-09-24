"""app_user ORM 모델 (#273).

DB_SCHEMA.md §2.15 (app_user) 참조. **`email`이 로그인 ID이자 식별 기준**이다 (#413).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText

#: 역할 3종 (#672 · #1301 · `PRD §20 O-14` · `API_SPEC §1.2`). 앞의 둘은 **직군 이름**이다 —
#: 이 제품의 실제 사용자 구분(선사 사무실 ↔ 선박 승무원)과 맞고, 「관리자/일반」보다 무엇을
#: 하는 사람인지가 드러난다.
#:
#: - ``FIELD`` 현장직 — 실적을 넣고 지금 상태를 본다(항차 · 정박 · 위치 · 계산 · 비교)
#: - ``OFFICE`` 사무직 — 기준값을 정하고 대외 산출물을 만든다(선박 제원 · 연간 시뮬레이션 ·
#:   시나리오 채택 · 리포트 · 함대 감축 계획 · 파라미터 적재)
#: - ``ADMIN`` 관리자 — 사무직이 하는 일에 **계정 관리**가 더해진다(계정 목록 · 타인 역할 지정)
#:
#: **``ADMIN``은 ``OFFICE``의 상위집합이다** (#1301). 관리자가 업무를 못 하면 계정 하나로
#: 시연·운영이 되지 않는다 — 판정은 ``auth/dependencies.require_office``가 한 곳에서 한다.
#:
#: 계정 관리를 직군에서 떼어낸 이유는 **사무직끼리 서로를 강등할 수 있었기 때문**이다
#: (마지막 한 명만 보호됐다). 「누가 계정을 관리하는가」가 「누가 리포트를 내는가」와 같은
#: 권한에 묶여 있을 이유가 없다.
#:
#: 역할은 **행위 권한**이지 소유권이 아니다. `User`는 여전히 어떤 운영 데이터의 소유자도
#: 아니다(`PRD §7.10`) — 세 역할 모두 같은 선박·항차를 본다.
ROLE_OFFICE = "OFFICE"
ROLE_FIELD = "FIELD"
ROLE_ADMIN = "ADMIN"
ROLES: frozenset[str] = frozenset({ROLE_OFFICE, ROLE_FIELD, ROLE_ADMIN})

#: 사무직 전용 경로를 지나갈 수 있는 역할 (#1301). 「사무직 이상」을 이 이름 하나로 묶어,
#: ``role == ROLE_OFFICE`` 비교가 코드 곳곳에 흩어지지 않게 한다 — 그 비교가 흩어지면
#: ``ADMIN``을 더할 때 **한 곳을 빠뜨려도 조용히** 통과하거나 막힌다.
OFFICE_OR_ABOVE: frozenset[str] = frozenset({ROLE_OFFICE, ROLE_ADMIN})


class AppUser(Base):
    """사용자 — 이메일·비밀번호 인증 주체 (#414)."""

    __tablename__ = "app_user"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    email = sa.Column(sa.String(length=320), nullable=False)
    #: Argon2id 해시. **평문 비밀번호는 저장하지 않는다** (`DB_SCHEMA §2.15`).
    password_hash = sa.Column(sa.String(length=255), nullable=False)
    #: 이메일 인증 완료 시각. NULL이면 미인증 — **미인증도 로그인은 허용한다**
    #: (`PRD §7.10`). 토큰 발급·검증은 #408 소관이다.
    email_verified_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    display_name = sa.Column(sa.String(length=100), nullable=True)
    #: 현장직·사무직·관리자 (#672 · #1301 · `DB_SCHEMA §2.15`). 기본값은 현장직 — 새 계정은
    #: 좁게 시작하고 **관리자가** 넓혀 준다. 마이그레이션 044가 기존 행을 전부 사무직으로
    #: 채웠고, 057이 값 트리거에 ``ADMIN``을 더했다.
    #:
    #: **값 제약은 CHECK가 아니라 트리거가 지킨다** (``trg_app_user_role_ins``·``_upd``) —
    #: CUBRID가 CHECK를 구문으로 받기만 하고 검사하지 않기 때문이다(`#1058`). 새 역할 값을
    #: 더하려면 마이그레이션이 그 트리거를 다시 만들어야 한다.
    role = sa.Column(sa.String(length=10), server_default=ROLE_FIELD, nullable=False)
    last_login_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    is_deleted = sa.Column(sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False)
    #: 활성 키 (#1631 · 061). 활성 행이면 `email`의 사본, 탈퇴(소프트 삭제)한 행이면 NULL —
    #: 그 위의 유니크 인덱스 `uq_app_user_email_active`가 「활성 행 안에서만 유일」을 DB에서
    #: 강제한다. **앱은 이 열을 쓰지 않는다** — 값은 061의 트리거
    #: `trg_app_user_email_active_ins`·`_upd`가 `is_deleted`에 따라 채운다(`Vessel.imo_active`와
    #: 같은 구조).
    email_active = sa.Column(sa.String(length=320), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        # 이메일 형식 검증은 Pydantic 스키마에서 수행한다. CUBRID는 regex CHECK를
        # 지원하지 않으므로 DB 레벨 제약은 제거한다 (#1058).
        # `email`이 로그인 ID이자 유일 키다 (#413 · `DB_SCHEMA §2.15`).
        # 종전에는 `google_sub`이 유일 키였고 email에는 unique를 걸지 않았는데,
        # 그 근거(「구글 계정의 이메일은 변경될 수 있다」)는 구글 위임을
        # 그만두면서 전제 자체가 사라졌다.
        # 유일성은 **활성 행 안에서만** 성립한다. PostgreSQL의 부분 유니크 인덱스를
        # CUBRID가 지원하지 않아 `047`이 트리거로 옮겼으나, 트리거의 `NOT EXISTS`는 미커밋
        # 행을 못 봐 동시 가입에서 중복이 남았다(`#1631`). `061`이 그 트리거를 걷고 활성 키
        # 열 `email_active`의 유니크 인덱스로 옮겼다 — 아래 `uq_app_user_email_active`.
        # `idx_app_user_email`은 로그인 조회용이다 (`#1058`).
        sa.Index(
            "idx_app_user_email",
            "email",
        ),
        sa.Index(
            "uq_app_user_email_active",
            "email_active",
            unique=True,
        ),
    )
