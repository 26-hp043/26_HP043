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
from cii_platform.errors import ValidationError
from cii_platform.services.pagination import normalize_limit

#: 저장소가 실제로 남기는 ``audit_log.action`` 값 (`#1343`).
#:
#: **한 곳에 모아 두는 이유** — 종전에는 함수마다 문자열이 박혀 있어 `DB_SCHEMA §2.14`의
#: 목록과 갈려도 아무것도 깨지지 않았다. 실제로 **5개가 문서에 없고 4개는 문서에만**
#: 있었다(`PARAMETER_CHANGE`·`VOYAGE_TRANSITION`·`IMPORT`·`EXPORT`). `#1241`(감사 로그
#: 조회 화면)이 그 목록으로 필터를 만들면 **없는 값으로 거르고 있는 값을 빠뜨린다.**
#:
#: 대부분은 이 모듈이 남기지만 ``PARAMETER_IMPORT``는 `services/parameter_import.py`가
#: 직접 넣는다. 값의 **정의**는 여기 한 곳에 둔다 — 쓰는 자리가 갈려도 목록은 하나여야
#: `DB_SCHEMA §2.14`와 대조할 수 있다.
#:
#: ⚠️ ``DB_BACKUP``은 여기 없다 — `db/migration_guard.py`가 남기며, 서비스 계층을 거치지
#: 않는다(마이그레이션 실행 중이라 세션이 다르다). 문서 목록에는 함께 적는다.
AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "LOGIN_SUCCESS",
        "LOGIN_FAILURE",
        "LOGOUT",
        "PASSWORD_CHANGE",
        "ACCOUNT_DELETE",
        "CHAT_DELETE",
        "ROLE_CHANGE",
        "CALCULATION_RUN",
        "VOYAGE_CONFIRM",
        # `#1328` — 확정 뒤 **정정·보관** 전환. `PRD §8.1.1`·`API_SPEC §3.5`가
        # 「audit log 필수」로 정한 둘이며, `#1343`이 이 자리를 비워 두고 이 이슈를
        # 가리켰다(계획값을 목록에 미리 적지 않는다).
        "VOYAGE_TRANSITION",
        # `#1923` — 공적 재항 기록의 시각을 「이 값으로 채우기」로 항차·정박 구간에 옮긴 것.
        # 되돌리기 전환(`VOYAGE_TRANSITION`)은 상태만 말하고 **어떤 값이 어떤 값으로** 바뀌었는지는
        # 어느 행에도 없었다 — 이 액션이 그 자리다.
        "VOYAGE_ACTUALS_FILL",
        "CHAT_MESSAGE",
        "CHAT_TOOL_CALL",
        "PARAMETER_IMPORT",
    }
)

#: 저장소가 실제로 쓰는 ``audit_log.entity_type`` 값 (`#1343`).
AUDIT_ENTITY_TYPES: frozenset[str] = frozenset(
    {"app_user", "calculation_run", "chat_session", "voyage"}
)

if TYPE_CHECKING:
    from datetime import datetime
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


async def record_chat_delete(
    session: AsyncSession,
    *,
    user_id: str,
    session_id: UUID,
    ip_address: str | None = None,
) -> None:
    """대화 삭제 (`#1330`) — ``PRD §16.3`` GDPR 유사 삭제 요청.

    **지운 행은 되짚을 수 없으므로 이 기록이 유일한 근거다.** 삭제 요청에 응했다는
    사실을 나중에 증명해야 하는 것이 이 규정의 성질이고, 그 증명은 지워진 대화
    안에 있을 수 없다.

    ``entity_id``에 대화 id를 남긴다 — **대화 내용은 남기지 않는다.** 무엇을 지웠는지
    본문으로 적으면 「지웠다」가 감사 로그에서 거짓이 된다.
    """
    await audit_repo.insert_event(
        session,
        action="CHAT_DELETE",
        user_id=user_id,
        entity_type="chat_session",
        entity_id=str(session_id),
        ip_address=ip_address,
    )


async def record_account_delete(
    session: AsyncSession,
    *,
    user_id: str,
    revoked_sessions: int,
    purged_chat_sessions: int = 0,
    ip_address: str | None = None,
) -> None:
    """탈퇴 (#506) — soft delete.

    **행을 지우지 않으므로 이 기록이 곧 「언제 탈퇴했는가」의 답**이다.
    `app_user`에 탈퇴 시각 컬럼이 없어(`is_deleted` 불리언뿐) 여기가 유일한 시점
    근거다.

    ``purged_chat_sessions``는 **지운 대화 수**다 (`#1330`). 지운 행은 되짚을 수
    없으므로 **몇 건을 지웠는지가 유일한 기록**이다 — 삭제 요청에 응했다는 사실을
    나중에 증명해야 하는 것이 GDPR 유사 삭제의 성질이다.
    """
    await audit_repo.insert_event(
        session,
        action="ACCOUNT_DELETE",
        user_id=user_id,
        details={
            "revoked_sessions": revoked_sessions,
            "purged_chat_sessions": purged_chat_sessions,
        },
        ip_address=ip_address,
    )


async def record_role_change(
    session: AsyncSession,
    *,
    actor_user_id: str,
    target_user_id: UUID,
    role_before: str,
    role_after: str,
    ip_address: str | None = None,
) -> None:
    """역할 변경 (#672) — 누가 누구를 무엇에서 무엇으로.

    역할은 리포트·연간 시뮬레이션·계정 관리의 문이다. 문이 열리고 닫힌 기록이 없으면
    「이 계정이 언제부터 사무직이었나」에 답할 수 없다. ``entity_id``가 대상, ``user_id``가
    행위자다 — 자기 자신을 바꿔도 둘 다 적힌다.
    """
    await audit_repo.insert_event(
        session,
        action="ROLE_CHANGE",
        user_id=actor_user_id,
        entity_type="app_user",
        entity_id=target_user_id,
        details={"role_before": role_before, "role_after": role_after},
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
    (``API_SPEC §6.4`` reproduce)은 새 ``calculation_run`` 행을 만들지 않고 원본의
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


async def record_voyage_transition(
    session: AsyncSession,
    *,
    user_id: str | None,
    voyage_id: UUID,
    from_status: str,
    to_status: str,
    annual_inclusion_policy: str,
    ip_address: str | None = None,
) -> None:
    """확정 뒤의 상태 전환 — `PRD §8.1.1`·`API_SPEC §3.5`가 「audit log 필수」로 정한 둘.

    ## 왜 이 둘만인가

    `CONFIRMED`는 **되돌릴 수 없는 선언**이고 그 시점의 실적이 연말 DCS 보고의
    근거가 된다(:func:`record_voyage_confirm`). 그 선언을 **되돌리거나 닫는** 두
    전환이 여기 해당한다.

    * ``CONFIRMED → COMPLETED`` — 오류 정정 목적만 허용(`PRD §8.1.1`)
    * ``CONFIRMED → ARCHIVED`` — 보관

    기록이 없으면 **확정된 실적을 되돌려 고친 뒤 다시 확정**했을 때 로그에는
    「확정」 두 건만 남고 **누가 언제 되돌렸는지**가 사라진다. 그 공백이 바로
    감사 로그가 있어야 하는 이유다.

    ⚠️ **다른 전환은 여전히 기록하지 않는다.** `PLANNED → IN_PROGRESS` 등은
    되돌릴 수 있고 정본이 지목하지도 않았다 — 기록 대상을 넓히는 것은 감사 로그를
    늘리는 일이 아니라 **무엇이 중요한지를 흐리는 일**이다(`record_voyage_confirm`의
    판단 그대로).

    종전에는 `TECH_SPEC §13.1`(「항차 확정」 하나)만 근거로 삼아 확정만 기록했다.
    `AGENTS §3.1`상 **`PRD` > `TECH_SPEC`**이므로 상위 정본에 맞춘다 (`#1328`).
    """
    await audit_repo.insert_event(
        session,
        action="VOYAGE_TRANSITION",
        user_id=user_id,
        entity_type="voyage",
        entity_id=voyage_id,
        details={
            "from_status": from_status,
            "to_status": to_status,
            "annual_inclusion_policy": annual_inclusion_policy,
        },
        ip_address=ip_address,
    )


async def record_voyage_actuals_fill(
    session: AsyncSession,
    *,
    user_id: str | None,
    voyage_id: UUID,
    fill: dict[str, object],
    ip_address: str | None = None,
) -> None:
    """공적 기록으로 채우기 (`#1923` · `PRD §17.4.4` · `API_SPEC §3.12`).

    ## 왜 따로 기록하는가

    확정 항차를 되돌려 채우면 `VOYAGE_TRANSITION`이 남지만 그 행은 **상태와 정책만** 말한다.
    「출항 시각이 06:45에서 18:45로 바뀌었고 그 값은 부산 항만청 2026년 029차 기항의
    공적 기록에서 왔다」는 어느 행에도 없었다 — 완료 항차는 되돌리기도 없어 **아무 기록도**
    남지 않았다. 사용자가 손으로 고친 것과 공적 기록에서 옮긴 것을 나중에 가를 수 있어야
    「공적 기록도 신고값이다」(`PRD §17.4.4` 각주)가 뜻을 갖는다.

    ``fill``은 서비스(`services/public_record_fill.py`)가 만든 ``details`` — 칸 · 이전 값 · 새 값 ·
    공적 기록 키(항만청 · 입항연도 · 입항 차수 · ``fetched_at``) · 되돌린 상태. 원문 시각은
    ISO 문자열이다. **필수 감사**라 원본 변경과 같은 트랜잭션에서 커밋한다(`TECH_SPEC §13.1` ·
    `#1625`) — 라우트가 이 함수 뒤에 한 번 커밋한다.
    """
    await audit_repo.insert_event(
        session,
        action="VOYAGE_ACTUALS_FILL",
        user_id=user_id,
        entity_type="voyage",
        entity_id=voyage_id,
        details=fill,
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


# ---------------------------------------------------------------------------
# 조회 (`#1241` · ``API_SPEC §16.1``)
# ---------------------------------------------------------------------------
#
# ⚠️ **쌓기만 하고 읽는 경로가 없었다.** 누가 언제 무엇을 적재했는지 확인하려면
# DB 직접 조회뿐이었다 — `#673`이 `PARAMETER_IMPORT`로 사용자·시각·행 수·판본을
# 남기게 해 두었는데, 그 기록에 닿을 방법이 제품 안에 없었다.


def _actor_to_dict(user) -> dict[str, object] | None:
    """``actor`` 블록 — ``{display_name, email}`` 또는 행위자를 못 찾으면 ``None`` (`#1515`).

    ``user_id``(UUID)만으로는 「누가 올렸나」에 답이 되지 않는다. 이름·이메일 둘만
    싣는다 — 역할·탈퇴 여부 같은 **현재 상태**는 감사 행의 일부가 아니다.
    """
    if user is None:
        return None
    return {"display_name": user.display_name, "email": user.email}


def _event_to_dict(row, actor=None) -> dict[str, object]:
    """행 하나를 ``API_SPEC §16.1`` ``data[]`` 항목으로 바꾼다.

    ⚠️ **``details_json``을 그대로 싣는다 — 거르지 않는다.** 감사는 **사실만** 적는
    자리이고(`TECH_SPEC §13.1`), 자격 증명은 **애초에 들어가지 않는다**: 이 모듈의
    기록 함수들이 담는 것은 수·상태·식별자뿐이다. 여기서 다시 거르면 **거르는
    규칙이 두 곳**에 생기고, 나중에 한쪽만 고쳐지면 「걸렀다」가 거짓이 된다.

    ``user_id``는 그대로 두고 ``actor``를 **덧붙인다** — 필터(``?user_id=``)와 이어
    붙일 키가 사라지면 안 된다.
    """
    return {
        "id": str(row.id),
        "timestamp": row.timestamp.isoformat() if row.timestamp is not None else None,
        "action": row.action,
        "user_id": row.user_id,
        "actor": _actor_to_dict(actor),
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id) if row.entity_id is not None else None,
        "details": row.details_json,
        "ip_address": row.ip_address,
    }


async def list_events(
    session: AsyncSession,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """감사 로그 목록과 페이지네이션 메타 (`API_SPEC §16.1` · `#1241`).

    ``action``은 **아는 값만 받는다** — 오타를 빈 목록으로 돌려주면 사용자는
    「그런 사건이 없다」로 읽는다. 목록은 :data:`AUDIT_ACTIONS` 하나이며
    `DB_SCHEMA §2.14`와 ``tests/test_audit_enum_sync.py``가 대조한다.
    """
    if action is not None and action not in AUDIT_ACTIONS:
        raise ValidationError(
            f"알 수 없는 감사 활동입니다: {action}",
            field="action",
            field_label="활동",
        )

    page_size = normalize_limit(
        limit, default=audit_repo.DEFAULT_LIMIT, maximum=audit_repo.MAX_LIMIT
    )

    parsed = None
    if cursor is not None:
        parsed = audit_repo.decode_cursor(cursor)
        if parsed is None:
            raise ValidationError(
                "커서 형식이 올바르지 않습니다.", field="cursor", field_label="커서"
            )

    rows = await audit_repo.list_events(
        session,
        limit=page_size,
        cursor=parsed,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        since=since,
        until=until,
    )

    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = (
        audit_repo.encode_cursor(audit_repo.AuditCursor(page[-1].timestamp, page[-1].id))
        if has_more and page
        else None
    )
    # 행위자는 **한 페이지 분을 한 번에** 푼다 — 행마다 물으면 페이지 크기만큼 왕복이
    # 생긴다. 탈퇴 계정도 돌아온다(`get_actors`).
    actors = await audit_repo.get_actors(
        session, [row.user_id for row in page if row.user_id is not None]
    )
    # `next_cursor`는 **다음 페이지가 있을 때만** 채운다 — 늘 채우면 클라이언트가
    # 같은 커서를 반복해 무한 루프에 빠진다 (`§1.9`와 같은 규약).
    return [_event_to_dict(row, actors.get(row.user_id)) for row in page], {
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
