"""app_user ORM 모델 (#273).

DB_SCHEMA.md §2.15 (app_user) 참조. **`email`이 로그인 ID이자 식별 기준**이다 (#413).
"""

import uuid

from datetime import datetime, timezone

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText

#: 역할 2종 (#672 · `PRD §20 O-14` · `API_SPEC §1.2`). **직군 이름**이다 — 이 제품의 실제
#: 사용자 구분(선사 사무실 ↔ 선박 승무원)과 맞고, 「관리자/일반」보다 무엇을 하는 사람인지가
#: 드러난다.
#:
#: - ``OFFICE`` 사무직 — 기준값을 정하고 대외 산출물을 만든다(선박 제원 · 연간 시뮬레이션 ·
#:   시나리오 채택 · 리포트 · 함대 감축 계획 · 타인 역할 지정)
#: - ``FIELD`` 현장직 — 실적을 넣고 지금 상태를 본다(항차 · 정박 · 위치 · 계산 · 비교)
#:
#: 역할은 **행위 권한**이지 소유권이 아니다. `User`는 여전히 어떤 운영 데이터의 소유자도
#: 아니다(`PRD §7.10`) — 두 역할 모두 같은 선박·항차를 본다.
ROLE_OFFICE = "OFFICE"
ROLE_FIELD = "FIELD"
ROLES: frozenset[str] = frozenset({ROLE_OFFICE, ROLE_FIELD})


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
    #: 사무직·현장직 (#672 · `DB_SCHEMA §2.15`). 기본값은 현장직 — 새 계정은 좁게 시작하고
    #: 사무직이 넓혀 준다. 마이그레이션 044가 **기존 행은 전부 사무직**으로 채웠다.
    role = sa.Column(sa.String(length=10), server_default=ROLE_FIELD, nullable=False)
    last_login_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    is_deleted = sa.Column(sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        # 이메일 형식 검증은 Pydantic 스키마에서 수행한다. CUBRID는 regex CHECK를
        # 지원하지 않으므로 DB 레벨 제약은 제거한다 (#1058).
        # `email`이 로그인 ID이자 유일 키다 (#413 · `DB_SCHEMA §2.15`).
        # 종전에는 `google_sub`이 유일 키였고 email에는 unique를 걸지 않았는데,
        # 그 근거(「구글 계정의 이메일은 변경될 수 있다」)는 구글 위임을
        # 그만두면서 전제 자체가 사라졌다.
        sa.Index(
            "idx_app_user_email",
            "email",
            unique=True,
        ),
    )
