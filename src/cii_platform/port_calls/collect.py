"""공적 재항 기록 수집기 (`#1197` B단계) — ``python -m cii_platform.port_calls.collect``.

호출부호가 있는 선박마다 항만청별로 공공데이터를 받아 ``port_call_record``에 넣는다.
**조회 경로(API)에서 부르지 않는다** — 바깥 서비스의 지연·장애가 화면 응답에 섞이지 않게
따로 돌린다(``provider.PortCallProvider`` 계약 · ``ais/provider.py``와 같은 규칙).

## 한 곳이 실패해도 나머지를 받는다

(선박, 항만청) 한 쌍의 실패는 그 쌍만 건너뛰고 기록한다(``PRD §16.2`` 오류 격리). 한 항만청의
장애가 다른 선박의 대조까지 비우지 않게 한다. 실패가 하나라도 있으면 종료 코드 1이다 — 운영
로그에서 「조용히 반쯤 받았다」를 가리기 위해서다.

## 무엇을 바꾸지 않나

항차·정박 구간·선박 제원은 읽지도 쓰지도 않는다. 받은 기록은 데이터 점검이 **견주기만** 한다
(``PRD §17.1``).

진입점을 패키지 안에 둔 이유는 ``db.demo_seed``와 같다 — 운영 이미지는 wheel만 설치하므로
``scripts/``를 배포 절차의 명령으로 쓸 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx

from cii_platform.db.repositories import port_call as port_call_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.port_calls.authorities import PORT_AUTHORITIES
from cii_platform.port_calls.mof_vessel_ops import PortCallApiError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.port_calls.provider import PortCallProvider

#: 기본 조회 기간 — 오늘(KST)부터 거슬러 올라가는 일수. 시연 대상 두 척의 기록(`#1197` 09-23
#: 코멘트 §2 · 2025-08 ~ 2026-09)을 덮는다.
DEFAULT_LOOKBACK_DAYS = 400
_KST = ZoneInfo("Asia/Seoul")


@dataclass
class CollectResult:
    """수집 결과 — 넣은 수 · 갱신한 수 · 실패한 (호출부호, 항만청, 사유)."""

    inserted: int = 0
    updated: int = 0
    failures: list[tuple[str, str, str]] = field(default_factory=list)


async def collect(
    session: AsyncSession,
    provider: PortCallProvider,
    *,
    start: date,
    end: date,
    authorities: Sequence[str] = tuple(PORT_AUTHORITIES),
    call_signs: Sequence[str] | None = None,
    fetched_at: datetime | None = None,
) -> CollectResult:
    """호출부호가 있는 활성 선박 × 항만청마다 받아 저장한다.

    ``call_signs``를 주면 그 호출부호만 받는다. 호출부호가 없는 선박은 대상이 아니다 — 질의
    키가 호출부호라 물을 방법이 없고, 선박명으로 잇지 않는다(``PRD §15.1`` 제약 ⑵).
    """
    stamp = fetched_at or datetime.now(UTC)
    wanted = {sign.strip().upper() for sign in call_signs} if call_signs else None
    signs = sorted(
        {
            vessel.call_sign
            for vessel in await vessel_repo.list_all_active(session)
            if vessel.call_sign and (wanted is None or vessel.call_sign in wanted)
        }
    )
    result = CollectResult()
    for sign in signs:
        for authority in authorities:
            try:
                calls = await provider.fetch(
                    call_sign=sign, port_authority_code=authority, start=start, end=end
                )
            except (PortCallApiError, httpx.HTTPError) as exc:
                # 예외 문구에 키가 없다(`PortCallApiError` · URL을 싣지 않는다). httpx 오류는
                # 요청 URL을 문구에 담을 수 있어 **종류 이름만** 남긴다.
                reason = str(exc) if isinstance(exc, PortCallApiError) else type(exc).__name__
                result.failures.append((sign, authority, reason))
                continue
            for call in calls:
                # 호출부호는 선택 조건이다 — 응답이 다른 배를 섞어 주면 저장하지 않는다.
                if call.call_sign != sign:
                    continue
                if await port_call_repo.upsert_port_call(session, call, fetched_at=stamp):
                    result.inserted += 1
                else:
                    result.updated += 1
    return result


def _parse_date(text: str) -> date:
    return date.fromisoformat(text)


async def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - 프로세스 진입점
    """엔진을 열어 수집하고 한 트랜잭션으로 저장한다. 종료 코드를 돌려준다."""
    import argparse

    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import create_async_engine

    from cii_platform.config import DATABASE_URL
    from cii_platform.db.url import normalize_to_async
    from cii_platform.port_calls.mof_vessel_ops import MofVesselOpsProvider, load_service_key

    today = datetime.now(_KST).date()
    parser = argparse.ArgumentParser(prog="python -m cii_platform.port_calls.collect")
    parser.add_argument(
        "--start",
        type=_parse_date,
        default=today - timedelta(days=DEFAULT_LOOKBACK_DAYS),
        help=f"입항일 시작(YYYY-MM-DD) · 기본 오늘-{DEFAULT_LOOKBACK_DAYS}일",
    )
    parser.add_argument("--end", type=_parse_date, default=today, help="입항일 끝 · 기본 오늘")
    parser.add_argument(
        "--authority",
        action="append",
        choices=sorted(PORT_AUTHORITIES),
        help="항만청코드(여러 번) · 기본 11개 전부",
    )
    parser.add_argument("--call-sign", action="append", help="이 호출부호만(여러 번)")
    args = parser.parse_args(argv)

    key = load_service_key()
    if not key:
        print("DATA_GO_KR_SERVICE_KEY가 비어 있다 — 수집하지 않는다")
        return 2

    engine = create_async_engine(normalize_to_async(DATABASE_URL), poolclass=pool.NullPool)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client, engine.begin() as conn:
            from sqlalchemy.ext.asyncio import AsyncSession

            session = AsyncSession(bind=conn)
            result = await collect(
                session,
                MofVesselOpsProvider(key, client),
                start=args.start,
                end=args.end,
                authorities=args.authority or tuple(PORT_AUTHORITIES),
                call_signs=args.call_sign,
            )
            await session.flush()
    finally:
        await engine.dispose()

    print(f"신규 {result.inserted}건 · 갱신 {result.updated}건 · 실패 {len(result.failures)}쌍")
    for sign, authority, reason in result.failures:
        print(f"  실패 {sign} {authority}: {reason}")
    return 1 if result.failures else 0


if __name__ == "__main__":  # pragma: no cover - 프로세스 진입점
    import asyncio
    import sys

    sys.exit(asyncio.run(main()))
