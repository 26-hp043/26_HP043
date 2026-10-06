"""알림 — 지금 걸려 있는 상태 목록 (`API_SPEC §2.19` · `DESIGN_SYSTEM §16` 항목 10 · #2204).

## 발생 기록이 아니다

알림은 **서버가 이미 판정한 상태를 모은 것**이다. 해결되면 다음 조회에서 사라진다. 읽음 ·
안 읽음 · 발생 시각을 저장하지 않으며 새 테이블이 없다(rlatnals4114 2026-10-06 결정). 그래서
「언제 생겼는가」를 말하지 않는다 — 말할 근거가 없다.

## 판정을 새로 만들지 않는다

넷 다 **다른 화면이 이미 쓰는 판정**을 그대로 옮긴다. 여기서 다시 판정하면 대시보드와 종
버튼의 수가 갈릴 자리가 생긴다.

- ``CORRECTIVE_ACTION`` 시정조치계획 대상 · ``RISK`` — 선대 요약 ``actions[]``
  (`§2.8` · `PRD §3.3.7`)
- ``D_ENTRY_SOON`` D등급 진입 임박 · ``RISK`` — 선대 요약 ``days_to_d``. 값이 있으면 **올해
  안에** 진입한다는 뜻이다(연말을 넘으면 ``NOT_THIS_YEAR``로 ``null``). 새 기준 일수를 두지 않는다
- ``UNCONFIRMED_VOYAGE`` 실적 확정 전 항차 · ``CHECK`` — 데이터 점검 ``issues[]``의
  ``UNCONFIRMED`` (`§2.16`)
- ``ESTIMATED_VALUES`` 실측이 아닌 값이 든 선박 · ``CHECK`` — 데이터 점검 ``issues[]``의
  ``SUBSTITUTED`` · ``UNAVAILABLE`` · ``ANOMALY``. 선박마다 한 줄

단계는 둘이다 — ``RISK``(규제 의무가 걸린 것) · ``CHECK``(자료 정리). 순서는 단계 → 종류 → 서버가
준 순서다. 화면은 다시 정렬하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from cii_platform.services.data_quality import (
    SEVERITY_ANOMALY,
    SEVERITY_SUBSTITUTED,
    SEVERITY_UNAVAILABLE,
    SEVERITY_UNCONFIRMED,
    get_fleet_data_quality,
)
from cii_platform.services.fleet_summary import compute_fleet_rows
from cii_platform.services.simulation_clock import resolve_as_of

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

LEVEL_RISK = "RISK"
LEVEL_CHECK = "CHECK"

KIND_CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
KIND_D_ENTRY_SOON = "D_ENTRY_SOON"
KIND_UNCONFIRMED_VOYAGE = "UNCONFIRMED_VOYAGE"
KIND_ESTIMATED_VALUES = "ESTIMATED_VALUES"

#: 「실측이 아닌 값이 들어갔다」에 드는 데이터 점검 심각도. ``PUBLIC_RECORD``(공적 기록과 다른
#: 시각)는 값이 계산에 들어간 것이 아니라 대조 결과라 넣지 않는다.
_ESTIMATED_SEVERITIES = frozenset({SEVERITY_SUBSTITUTED, SEVERITY_UNAVAILABLE, SEVERITY_ANOMALY})


def _item(
    kind: str,
    level: str,
    *,
    vessel_id: str,
    vessel_name: str,
    reason: str | None = None,
    days: int | None = None,
    voyage_id: str | None = None,
    voyage_no: str | None = None,
    count: int | None = None,
) -> dict[str, object]:
    """알림 한 줄. 문구는 화면이 만든다 — 서버는 종류와 재료만 준다."""
    return {
        "kind": kind,
        "level": level,
        "vessel_id": vessel_id,
        "vessel_name": vessel_name,
        "reason": reason,
        "days": days,
        "voyage_id": voyage_id,
        "voyage_no": voyage_no,
        "count": count,
    }


async def get_notifications(
    session: AsyncSession,
    *,
    regulation_year: int | None = None,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """지금 걸려 있는 알림 (``API_SPEC §2.19``).

    **선박이 0척이면 빈 목록이다** — 선대 요약 · 데이터 점검과 같은 이유로 오류가 아니다.
    """
    resolved = resolve_as_of(as_of)
    year = regulation_year if regulation_year is not None else resolved.year

    rows, actions = await compute_fleet_rows(session, year=year, resolved=resolved)
    quality = await get_fleet_data_quality(session, regulation_year=year)

    items: list[dict[str, object]] = []

    for action in actions:
        items.append(
            _item(
                KIND_CORRECTIVE_ACTION,
                LEVEL_RISK,
                vessel_id=str(action["vessel_id"]),
                vessel_name=str(action["vessel_name"]),
                reason=str(action["reason"]),
            )
        )

    # 남은 일수가 짧은 순 — 대시보드 「D등급 진입 임박」 칸(`soonest_d_entry`)과 같은 기준이다.
    soon = [row for row in rows if row["days_to_d"] is not None]
    soon.sort(key=lambda r: (r["days_to_d"], str(r["name"]), str(r["vessel_id"])))  # type: ignore[arg-type, return-value]
    for row in soon:
        items.append(
            _item(
                KIND_D_ENTRY_SOON,
                LEVEL_RISK,
                vessel_id=str(row["vessel_id"]),
                vessel_name=str(row["name"]),
                days=int(row["days_to_d"]),  # type: ignore[call-overload]
            )
        )

    issues = quality["issues"]
    assert isinstance(issues, list)

    seen_voyages: set[str] = set()
    for issue in issues:
        if issue["severity"] != SEVERITY_UNCONFIRMED or issue["voyage_id"] is None:
            continue
        voyage_id = str(issue["voyage_id"])
        if voyage_id in seen_voyages:
            continue
        seen_voyages.add(voyage_id)
        items.append(
            _item(
                KIND_UNCONFIRMED_VOYAGE,
                LEVEL_CHECK,
                vessel_id=str(issue["vessel_id"]),
                vessel_name=str(issue["vessel_name"]),
                voyage_id=voyage_id,
                voyage_no=issue["voyage_no"],
            )
        )

    # 선박마다 한 줄 — 항차마다 내면 한 배가 목록을 채운다. 수는 데이터 점검의 해당 행 수다.
    estimated: dict[str, dict[str, object]] = {}
    for issue in issues:
        if issue["severity"] not in _ESTIMATED_SEVERITIES:
            continue
        vessel_id = str(issue["vessel_id"])
        entry = estimated.get(vessel_id)
        if entry is None:
            estimated[vessel_id] = _item(
                KIND_ESTIMATED_VALUES,
                LEVEL_CHECK,
                vessel_id=vessel_id,
                vessel_name=str(issue["vessel_name"]),
                count=1,
            )
        else:
            entry["count"] = int(entry["count"]) + 1  # type: ignore[call-overload]
    items.extend(estimated.values())

    risk = sum(1 for item in items if item["level"] == LEVEL_RISK)
    return {
        "as_of": resolved.isoformat(),
        "regulation_year": year,
        "counts": {"risk": risk, "check": len(items) - risk, "total": len(items)},
        "items": items,
    }
