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


async def record_password_change(
    session: AsyncSession,
    *,
    user_id: str,
    revoked_sessions: int,
    ip_address: str | None = None,
) -> None:
    """비밀번호 변경 (#506) — 로그인 상태에서의 교체.

    `TECH_SPEC §13.1`이 로그인 이벤트 3종을 기록 대상으로 두는 것과 같은 근거다 —
    **계정을 넘길 수 있는 사건**이므로 「누가 언제」에 답할 수 있어야 한다.
    무효화된 세션 수를 함께 남긴다: 본인이 모르는 기기가 있었는지 사후에 드러난다.

    **자격 증명은 절대 기록하지 않는다**(`TECH_SPEC §13.1` [#277]) — 옛 비밀번호도
    새 비밀번호도 해시조차 남기지 않는다.
    """
    await audit_repo.insert_event(
        session,
        action="PASSWORD_CHANGE",
        user_id=user_id,
        details={"revoked_sessions": revoked_sessions},
        ip_address=ip_address,
    )


async def record_account_delete(
    session: AsyncSession,
    *,
    user_id: str,
    revoked_sessions: int,
    ip_address: str | None = None,
) -> None:
    """탈퇴 (#506) — soft delete.

    **행을 지우지 않으므로 이 기록이 곧 「언제 탈퇴했는가」의 답**이다.
    `app_user`에 탈퇴 시각 컬럼이 없어(`is_deleted` 불리언뿐) 여기가 유일한 시점
    근거다.
    """
    await audit_repo.insert_event(
        session,
        action="ACCOUNT_DELETE",
        user_id=user_id,
        details={"revoked_sessions": revoked_sessions},
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
    details_extra: dict[str, object] | None = None,
) -> None:
    """계산 실행 — TECH_SPEC §13.1 필드 표를 그대로 ``details``에 옮긴다.

    ``details_extra``는 §13.1 표에 **덧붙이는** 구분 표식이다 (#869). 재현 검증
    (``§6.4 reproduce``)은 새 ``calculation_run`` 행을 만들지 않고 원본의
    ``run_id``를 그대로 쓰므로, 표식이 없으면 **원본 실행과 구분되지 않는다.**
    같은 스트림에 변형을 플래그로 구분하는 것은 §13.1 자신의 방식이다 — 스텁
    dev-login이 ``dev_login`` 플래그로 구분된다.

    표의 필드는 덮어쓸 수 없다 — 덧붙인 키가 표와 겹치면 표 쪽이 이긴다.
    """
    details: dict[str, object] = dict(details_extra or {})
    details.update(
        {
            "calculation_type": calculation_type,
            "input_hash": input_hash,
            "parameter_hash": parameter_hash,
            "model_version": model_version,
            "duration_ms": duration_ms,
            "status": status,
            "warnings_count": warnings_count,
        }
    )
    await audit_repo.insert_event(
        session,
        action="CALCULATION_RUN",
        user_id=user_id,
        entity_type="calculation_run",
        entity_id=run_id,
        details=details,
        ip_address=ip_address,
    )


async def record_voyage_confirm(
    session: AsyncSession,
    *,
    user_id: str | None,
    voyage_id: UUID,
    from_status: str,
    annual_inclusion_policy: str,
    ip_address: str | None = None,
) -> None:
    """항차 확정 — ``TECH_SPEC §13.1``이 계산 실행·파라미터 변경과 함께 지목한 사건.

    ## 왜 확정만 기록하는가

    확정(``CONFIRMED``)은 **되돌릴 수 없는 선언**이다. 그 시점의 실적이 연말 DCS
    보고의 근거가 되고, 이후 실적 수정은 상태 가드가 막는다(``API_SPEC §3.6``).
    「누가 언제 이 항차를 확정했나」에 답할 수 없으면 그 근거의 출처가 사라진다.

    다른 전환(``PLANNED → IN_PROGRESS`` 등)은 되돌릴 수 있고 정본이 지목하지도
    않았다. **기록 대상을 넓히는 것은 감사 로그를 늘리는 일이 아니라 무엇이 중요한지를
    흐리는 일**이라, 정본이 든 것만 남긴다.

    ``details``에 **변경 전/후를 함께** 담는다 — 「무엇에서 무엇으로」가 없으면 로그가
    「확정됐다」만 말하고, 어떤 상태를 거쳐 왔는지는 다시 조회해야 알 수 있다.
    """
    await audit_repo.insert_event(
        session,
        action="VOYAGE_CONFIRM",
        user_id=user_id,
        entity_type="voyage",
        entity_id=voyage_id,
        details={
            "from_status": from_status,
            "to_status": "CONFIRMED",
            "annual_inclusion_policy": annual_inclusion_policy,
        },
        ip_address=ip_address,
    )


def content_digest(text: str) -> str:
    """본문의 지문 (`#120`).

    ⚠️ **감사 로그에 원문을 남기지 않는다.** ``audit_log``는 **지우지 않는 기록**이고
    ``chat_message``는 **90일 뒤 지우는 기록**이다(``PRD §16.3``). 같은 내용을 두 곳에
    넣으면 삭제 요청이 왔을 때 **한쪽을 지울 수 없어 요구를 만족시킬 수 없다.**

    해시로 남기면 「같은 내용이었나」는 대조할 수 있고 원문은 90일 뒤 사라진다.
    """
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def record_chat_message(
    session: AsyncSession,
    *,
    user_id: str | None,
    session_id: UUID,
    role: str,
    content: str,
    ip_address: str | None = None,
) -> None:
    """챗봇 메시지 한 건 (`#120` 완료 기준 「모든 에이전트 호출이 audit_log에 기록됨」).

    **본문 대신 해시와 길이**를 담는다 — 위 :func:`content_digest` 참조. 본문은
    ``chat_message.content``에 있고 90일 뒤 지워진다.
    """
    await audit_repo.insert_event(
        session,
        action="CHAT_MESSAGE",
        user_id=user_id,
        entity_type="chat_session",
        entity_id=session_id,
        details={
            "role": role,
            "content_sha256": content_digest(content),
            "content_length": len(content),
        },
        ip_address=ip_address,
    )


async def record_chat_tool_call(
    session: AsyncSession,
    *,
    user_id: str | None,
    session_id: UUID,
    tool_name: str,
    arguments_digest: str,
    calculation_run_id: UUID | None = None,
    status: str = "SUCCESS",
    ip_address: str | None = None,
) -> None:
    """챗봇이 도구를 부른 것 한 건 (`#120` 가드레일 표 「감사 추적성」).

    ## 인자를 해시로 남기는 이유

    도구 인자에 **선박 데이터가 들어 있다.** 외부 전송을 화이트리스트로 좁혀
    놓고(``PRD §16.3.1``) 내부 감사 로그에 원문을 쌓으면, **지우지 못하는 저장소가
    하나 더 느는 것**이라 `§16.3` 삭제 정책과 정면으로 부딪친다.

    ## 재현은 `calculation_run`을 따라간다

    ``calculation_run_id``만 있으면 「그때 무엇을 근거로 답했나」에 완전히 답할 수
    있다 — **계산 원본은 이미 정본 경로에 있으므로 챗봇이 중복 보관할 이유가 없다**
    (`#120` 아키텍처 — 에이전트는 API 클라이언트일 뿐 계산 원본을 만들지 않는다).
    """
    details: dict[str, object] = {
        "tool_name": tool_name,
        "arguments_sha256": arguments_digest,
        "status": status,
    }
    if calculation_run_id is not None:
        details["calculation_run_id"] = str(calculation_run_id)
    await audit_repo.insert_event(
        session,
        action="CHAT_TOOL_CALL",
        user_id=user_id,
        entity_type="chat_session",
        entity_id=session_id,
        details=details,
        ip_address=ip_address,
    )
