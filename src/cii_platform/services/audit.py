"""감사 로그 서비스 (TECH_SPEC §13.1 · §16, #277).

이벤트별 진입점을 제공한다 — ``api/routes``는 이 모듈만 호출한다(§16.3 계층:
라우트는 저장소를 직접 부르지 않는다). 실제 INSERT는 ``db/repositories/audit_log``
이 담당한다.

**자격 증명 미기록 원칙 (#277)** — ``id_token``·``code``·state·세션 토큰 원문은
``details``에 절대 들어가지 않는다. 실패 사유는 ``reason`` 코드(열거값)로만
남긴다. 이 정책을 호출부마다 반복하지 않게 여기서 한 번 강제한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.db.repositories import audit_log as audit_repo

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def record_login_success(
    session: AsyncSession,
    *,
    user_id: str,
    ip_address: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    """로그인 성공 — ``user_id``는 ``app_user.id``(str)다. commit은 호출부가."""
    await audit_repo.insert_event(
        session,
        action="LOGIN_SUCCESS",
        user_id=user_id,
        details=details,
        ip_address=ip_address,
    )


async def record_login_failure(
    session: AsyncSession,
    *,
    reason: str,
    ip_address: str | None = None,
) -> None:
    """로그인 실패 — ``reason``은 사유 코드만(자격 증명 값 금지)."""
    await audit_repo.insert_event(
        session,
        action="LOGIN_FAILURE",
        details={"reason": reason},
        ip_address=ip_address,
    )


async def record_logout(
    session: AsyncSession,
    *,
    user_id: str,
    ip_address: str | None = None,
) -> None:
    """로그아웃 — 세션 무효화가 실제로 일어났을 때만 기록한다."""
    await audit_repo.insert_event(
        session,
        action="LOGOUT",
        user_id=user_id,
        ip_address=ip_address,
    )


async def record_calculation_run(
    session: AsyncSession,
    *,
    user_id: str | None,
    run_id: UUID,
    input_hash: str,
    parameter_hash: str,
    model_version: dict[str, object],
    duration_ms: int,
    warnings_count: int,
    ip_address: str | None = None,
    calculation_type: str = "VOYAGE_ESTIMATE",
    status: str = "SUCCESS",
) -> None:
    """계산 실행 — TECH_SPEC §13.1 필드 표를 그대로 ``details``에 옮긴다."""
    await audit_repo.insert_event(
        session,
        action="CALCULATION_RUN",
        user_id=user_id,
        entity_type="calculation_run",
        entity_id=run_id,
        details={
            "calculation_type": calculation_type,
            "input_hash": input_hash,
            "parameter_hash": parameter_hash,
            "model_version": model_version,
            "duration_ms": duration_ms,
            "status": status,
            "warnings_count": warnings_count,
        },
        ip_address=ip_address,
    )
