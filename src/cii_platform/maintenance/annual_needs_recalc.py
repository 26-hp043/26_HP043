"""저장 연간 실행의 낡음 표시 소급 처리 (#2373).

``python -m cii_platform.maintenance.annual_needs_recalc``로 돌린다.

#2304(PR #2372)는 이후의 항차·정박 변경과 **같은 트랜잭션으로** ``calculation_run.needs_recalc``를
세운다. 과거 변경 이벤트는 소급해 실행되지 않으므로, 그 배포 **전에** 입력이 바뀐 저장 실행은
표시가 없다. 이 도구가 그 한 구간을 **한 번** 메운다.

## 무엇을 견주나 (``PRD §8.4`` ``[#2304]`` 각주)

실행이 들고 있는 스냅샷(``simulation_snapshot``)과, **같은 선박·연도·그 실행의 기준 시각**으로
지금 다시 모은 입력이다. 지금 입력은 새로 조립하지 않고 실행 경로가 쓰는 함수
(:func:`~cii_platform.services.annual_simulation.collect_annual_inputs`)를 그대로 부른다 —
조립이 둘이면 「바뀌었다」가 입력의 차이인지 조립의 차이인지 가를 수 없다.

* 항차 — 집합(추가·제외), 구분(확정/계획), 상태, 연간 반영 정책, 계획·실적 거리, 계획 속력,
  연료 종류별 계획·실적 연료량
* 정박·묘박 몫 — 이동 거리, 연료 종류별 연료량
* 선박 제원 — ``VESSEL_SNAPSHOT_FIELDS`` 다섯

견주지 **않는** 것: 연료 CF 값(``PRD §8.4`` 「연료 CF 변경은 변경 이후 계산에만 적용한다」),
메모·출처·항차 번호 같은 표시 문구(스냅샷에 없거나 계산 입력이 아니다).

## 기준 시각

저장된 ``annual_simulation_run.as_of``다. 명시하지 않고 돌린 실행은 컬럼이 비어 있어
**스냅샷을 뜬 시각**(``simulation_snapshot.created_at``)을 쓴다 — 그때 서버가 확정한 ``as_of``와
같은 시각이다(ms 단위 차이는 무시할 만하다).

## 견줄 수 없는 실행은 건드리지 않는다 (결정 2)

``needs_recalc``는 0→1로만 바뀌고 가드 트리거가 되돌림을 막는다 — **잘못 세운 표시는 지울 수
없다.** 근거가 모자라면 표시하지 않고 목록으로 보고한다(나중에 언제든 표시할 수 있다).

* 제원 스냅샷이 없다 — 마이그레이션 037 이전 실행
* 정박 스냅샷이 비어 있는데 지금은 정박 기록이 있다 — 060 이전 실행인지 이후에 추가된 것인지
  가를 수 없다. (**다른 항목에서 이미 차이가 확인됐으면** 이 불확실성과 무관하게 대상이다.)
* 지금 입력을 모을 수 없다 — 선박이 없거나 연료 종류가 비활성이다

* 스냅샷이 **규칙 변경 이전**에 만들어졌다 — :data:`SNAPSHOT_RULE_CUTOFF` 아래 참조 (#2491)

## 스냅샷 규칙 변경 이전의 실행 (#2491)

스냅샷에 담기는 항차 집합의 규칙이 저장 실행이 만들어진 뒤에 두 번 바뀌었다.

* ``66fde107`` — #816(PR #1213) · 2026-09-18 04:31 KST 머지: ``as_of``가 확정 항차를 자름
* ``572fc3d7`` — #1323(PR #1408) · 2026-09-20 15:17 KST 머지: 도착 예정 지난 계획 항차 복귀

도구는 **지금 규칙**으로 모은 입력과 견주므로, 이 시각 이전의 실행은 데이터가 바뀌지 않았어도
「항차 지금 새로 포함됨 / 포함되지 않음」으로 잡혀 대상이 된다. 두 머지 뒤 배포까지의 시차를
넉넉히 덮도록 기준을 2026-09-21 00:00 KST로 잡았고, 그 이전에 만든 스냅샷은 견줄 수 없는
실행으로 둔다. (이미 표시된 실행은 그대로 먼저 판정한다.)

## 기본은 미리 보기

쓰기는 ``--apply``일 때만이다. 적용은 **승인한 미리 보기 JSON**(``--approved``)이 필수이고, 그
목록의 대상 실행만 표시한다 — 미리 보기와 적용은 별개 실행이라 적용 때 다시 평가하면 승인한
목록과 달라질 수 있다. 적용하면 **표시할 실행 번호 목록을 파일로 먼저 남기고**(복구 자료) 그
뒤에 표시한다. 표시는 ``needs_recalc``만 세팅하고 결과·스냅샷은 건드리지 않는다.

진입점을 패키지 안에 둔 이유는 ``db.demo_seed`` · ``port_calls.collect``와 같다 — 운영 이미지는
wheel만 설치하므로 ``scripts/``를 배포 절차의 명령으로 쓸 수 없다.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from cii_platform.db.repositories import calculation_run as calc_run_repo
from cii_platform.db.types import JSONText, UuidText
from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.services.annual_simulation import (
    VESSEL_SNAPSHOT_FIELDS,
    _load_vessel,
    _vessel_from_snapshot,
    _vessel_snapshot_payload,
    collect_annual_inputs,
)
from cii_platform.services.simulation_clock import resolve_as_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

#: 판정 결과. 문자열 그대로 JSON·표에 나간다.
STATUS_TARGET = "TARGET"  # 입력이 달라졌다 — 표시 대상
STATUS_ALREADY = "ALREADY_MARKED"  # 이미 needs_recalc = 1
STATUS_CURRENT = "CURRENT"  # 입력이 같다
STATUS_UNCOMPARABLE = "UNCOMPARABLE"  # 견줄 수 없다 — 건드리지 않는다

#: 이 시각 **이전**에 만든 스냅샷은 지금 규칙으로 모은 항차 집합과 견줄 수 없다 (#2491).
#: 근거는 모듈 머리말. aware끼리 비교한다 — DB의 UTC naive 값은 ``resolve_as_of``로 맞춘다.
SNAPSHOT_RULE_CUTOFF = datetime(2026, 9, 21, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))

#: 미리 보기 JSON의 형식 버전. 적용이 읽을 때 확인한다 (#2491).
REPORT_FORMAT_VERSION = 1

_PRE_CUTOFF_REASON = (
    "스냅샷 규칙 변경(#816 · #1323) 이전 실행 — 지금 규칙으로 모은 항차 집합과 견줄 수 없음"
)

_STATUS_LABEL = {
    STATUS_TARGET: "대상",
    STATUS_ALREADY: "이미 표시됨",
    STATUS_CURRENT: "바뀌지 않음",
    STATUS_UNCOMPARABLE: "견줄 수 없음",
}


@dataclass
class RunCheck:
    """저장 연간 실행 1건의 판정."""

    simulation_id: str
    calculation_run_id: str
    vessel_id: str
    vessel: str
    regulation_year: int
    as_of: str
    status: str
    #: 스냅샷을 만든 시각(UTC ISO) — 규칙 변경 이전 여부를 사람이 가늠하는 자료 (#2491).
    snapshot_created_at: str = ""
    #: ``STATUS_TARGET``의 차이 목록 — 「항목: 저장 → 지금」.
    differences: list[str] = field(default_factory=list)
    #: ``STATUS_UNCOMPARABLE``의 사유 (대상인데 불확실한 항목이 있었으면 그것도 싣는다).
    reasons: list[str] = field(default_factory=list)


# ─── 견주기 (순수 함수) ───────────────────────────────────────────────────────


def _num(value: object) -> str | None:
    """숫자 문자열을 자릿수 표기와 무관하게 같은 꼴로 맞춘다 (``100`` · ``100.000``)."""
    if value is None:
        return None
    return format(Decimal(str(value)).normalize(), "f")


def _voyage_view(row: dict) -> dict[str, object]:
    """스냅샷 항차 한 줄에서 **견줄 항목만** 남긴다. ``cf_used``·``voyage_no``는 뺀다."""
    fuels: dict[str, dict[str, str | None]] = {}
    for fuel_use in row.get("fuel_uses") or []:
        fuels[fuel_use["fuel_type"]] = {
            "planned_fuel_ton": _num(fuel_use.get("planned_fuel_ton")),
            "actual_fuel_ton": _num(fuel_use.get("actual_fuel_ton")),
        }
    return {
        "kind": row.get("kind"),
        "status": row.get("status"),
        "annual_inclusion_policy": row.get("annual_inclusion_policy"),
        "planned_distance_nm": _num(row.get("planned_distance_nm")),
        "actual_distance_nm": _num(row.get("actual_distance_nm")),
        "planned_speed_kn": _num(row.get("planned_speed_kn")),
        "fuel_uses": fuels,
    }


def _not_underway_view(payload: dict | None) -> dict[str, object] | None:
    if payload is None:
        return None
    return {
        "distance_nm": _num(payload.get("distance_nm") or "0"),
        "fuel_uses": {
            fuel_use["fuel_type"]: _num(fuel_use["fuel_ton"])
            for fuel_use in payload.get("fuel_uses") or []
        },
    }


def diff_voyages(stored: list[dict], current: list[dict]) -> list[str]:
    """저장 항차 집합과 지금 항차 집합의 차이."""
    before = {row["voyage_id"]: row for row in stored}
    after = {row["voyage_id"]: row for row in current}
    out: list[str] = []
    for voyage_id in sorted(after.keys() - before.keys()):
        out.append(f"항차 {after[voyage_id].get('voyage_no') or voyage_id}: 지금 새로 포함됨")
    for voyage_id in sorted(before.keys() - after.keys()):
        out.append(f"항차 {before[voyage_id].get('voyage_no') or voyage_id}: 지금은 포함되지 않음")
    for voyage_id in sorted(before.keys() & after.keys()):
        old, new = _voyage_view(before[voyage_id]), _voyage_view(after[voyage_id])
        label = after[voyage_id].get("voyage_no") or voyage_id
        for key in old:
            if key == "fuel_uses":
                continue
            if old[key] != new[key]:
                out.append(f"항차 {label} {key}: {old[key]} → {new[key]}")
        old_fuels, new_fuels = old["fuel_uses"], new["fuel_uses"]
        for fuel_type in sorted(set(old_fuels) | set(new_fuels)):
            if fuel_type not in old_fuels:
                out.append(f"항차 {label} 연료 {fuel_type}: 지금 새로 있음")
            elif fuel_type not in new_fuels:
                out.append(f"항차 {label} 연료 {fuel_type}: 지금은 없음")
            else:
                for key in ("planned_fuel_ton", "actual_fuel_ton"):
                    if old_fuels[fuel_type][key] != new_fuels[fuel_type][key]:
                        out.append(
                            f"항차 {label} 연료 {fuel_type} {key}: "
                            f"{old_fuels[fuel_type][key]} → {new_fuels[fuel_type][key]}"
                        )
    return out


def diff_not_underway(stored: dict | None, current: dict | None) -> list[str]:
    """정박·묘박 몫의 차이. 둘 다 비어 있으면 차이가 없다."""
    old, new = _not_underway_view(stored), _not_underway_view(current)
    if old == new:
        return []
    if old is None or new is None:
        return [
            f"정박 몫: {'없음' if old is None else '있음'} → {'없음' if new is None else '있음'}"
        ]
    out: list[str] = []
    if old["distance_nm"] != new["distance_nm"]:
        out.append(f"정박 몫 distance_nm: {old['distance_nm']} → {new['distance_nm']}")
    for fuel_type in sorted(set(old["fuel_uses"]) | set(new["fuel_uses"])):
        before, after = old["fuel_uses"].get(fuel_type), new["fuel_uses"].get(fuel_type)
        if before != after:
            out.append(f"정박 몫 연료 {fuel_type} fuel_ton: {before} → {after}")
    return out


def diff_vessel(stored: dict, current: dict) -> list[str]:
    out = []
    for name in VESSEL_SNAPSHOT_FIELDS:
        old = stored.get(name)
        new = current.get(name)
        # ship_type은 코드 문자열이라 숫자로 읽지 않는다.
        left, right = (old, new) if name == "ship_type" else (_num(old), _num(new))
        if left != right:
            out.append(f"제원 {name}: {left} → {right}")
    return out


# ─── 평가 ────────────────────────────────────────────────────────────────────


_LIST_SQL = (
    "SELECT r.id AS simulation_id, r.calculation_run_id, r.vessel_id, r.regulation_year, "
    "       r.as_of, c.needs_recalc, s.created_at AS snapshot_created_at, "
    "       s.voyages_json, s.vessel_json, s.not_underway_json, v.name AS vessel_name "
    "FROM annual_simulation_run r "
    "JOIN calculation_run c ON c.id = r.calculation_run_id "
    "JOIN simulation_snapshot s ON s.id = r.snapshot_id "
    "LEFT JOIN vessel v ON v.id = r.vessel_id "
    "ORDER BY s.created_at, r.id"
)


async def _stored_runs(session: AsyncSession):
    # raw SQL에는 컬럼 타입이 붙지 않아 JSON·식별자·불리언을 `.columns()`로 지정한다 (`#1058`).
    statement = sa.text(_LIST_SQL).columns(
        simulation_id=UuidText(),
        calculation_run_id=UuidText(),
        vessel_id=UuidText(),
        needs_recalc=sa.Boolean(),
        voyages_json=JSONText(),
        vessel_json=JSONText(),
        not_underway_json=JSONText(),
    )
    return (await session.execute(statement)).all()


async def check_run(session: AsyncSession, row) -> RunCheck:
    """실행 1건을 지금 입력과 견준다. 쓰지 않는다."""
    created_at = resolve_as_of(row.snapshot_created_at)
    as_of = resolve_as_of(row.as_of or row.snapshot_created_at)
    check = RunCheck(
        simulation_id=str(row.simulation_id),
        calculation_run_id=str(row.calculation_run_id),
        vessel_id=str(row.vessel_id),
        vessel=row.vessel_name or "(선박 없음)",
        regulation_year=row.regulation_year,
        as_of=as_of.isoformat(),
        status=STATUS_CURRENT,
        snapshot_created_at=created_at.isoformat(),
    )
    if row.needs_recalc:
        check.status = STATUS_ALREADY
        return check
    if created_at < SNAPSHOT_RULE_CUTOFF:
        check.status = STATUS_UNCOMPARABLE
        check.reasons.append(_PRE_CUTOFF_REASON)
        return check
    if row.vessel_json is None:
        check.status = STATUS_UNCOMPARABLE
        check.reasons.append("제원 스냅샷 없음 (마이그레이션 037 이전 실행)")
        return check

    try:
        live_vessel = await _load_vessel(session, row.vessel_id)
        vessel_json = _vessel_snapshot_payload(live_vessel)
        # 실행 경로(`load_projection_context`)와 같은 순서 — 제원은 사본으로 고정한 뒤 넘긴다.
        current = await collect_annual_inputs(
            session,
            vessel=_vessel_from_snapshot(vessel_json),
            vessel_id=row.vessel_id,
            year=row.regulation_year,
            as_of=as_of,
        )
    except (NotFoundError, ValidationError) as exc:
        check.status = STATUS_UNCOMPARABLE
        check.reasons.append(f"지금 입력을 모을 수 없음 — {exc}")
        return check

    check.differences += diff_vessel(row.vessel_json, vessel_json)
    check.differences += diff_voyages(row.voyages_json or [], current.voyages_json)
    stored_nu = row.not_underway_json
    if stored_nu is None and current.not_underway_json is not None:
        # NULL은 「정박 기록이 없었다」와 「060 이전」이 같은 값이다 — 가를 수 없다.
        check.reasons.append(
            "정박 스냅샷이 비어 있는데 지금은 정박 기록이 있음 "
            "(060 이전 실행인지 이후 추가인지 구분 불가)"
        )
    else:
        check.differences += diff_not_underway(stored_nu, current.not_underway_json)

    if check.differences:
        check.status = STATUS_TARGET
    elif check.reasons:
        check.status = STATUS_UNCOMPARABLE
    return check


async def evaluate(session: AsyncSession, *, vessel_id: UUID | None = None) -> list[RunCheck]:
    """저장 연간 실행을 하나씩 열어 판정한다. 쓰지 않는다."""
    checks = []
    for row in await _stored_runs(session):
        if vessel_id is not None and UUID(str(row.vessel_id)) != vessel_id:
            continue
        checks.append(await check_run(session, row))
    return checks


async def apply(session: AsyncSession, checks: Sequence[RunCheck]) -> int:
    """``STATUS_TARGET``인 실행의 ``needs_recalc``를 세운다. 커밋은 호출부가 한다."""
    marked = 0
    for check in checks:
        if check.status == STATUS_TARGET:
            marked += await calc_run_repo.mark_run_needs_recalc(
                session, UUID(check.calculation_run_id)
            )
    return marked


@dataclass
class ApprovalSplit:
    """승인 목록과 지금 판정을 맞춘 결과 (#2491)."""

    #: 승인 목록에 있고 지금도 대상 — 표시한다.
    to_mark: list[RunCheck] = field(default_factory=list)
    #: 지금 대상이지만 승인 목록 밖 — 표시하지 않는다.
    outside: list[RunCheck] = field(default_factory=list)
    #: 승인 목록에 있지만 지금은 대상이 아님(또는 사라짐) — 건너뛴다. 실행 번호.
    changed: list[str] = field(default_factory=list)


def load_approved(path: str) -> set[str]:
    """승인한 미리 보기 JSON에서 대상(TARGET) 실행 번호(simulation_id)를 읽는다.

    형식 버전이 다르거나 ``runs``가 없으면 ``ValueError`` — 모르는 형식을 추측해 읽지 않는다.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("format_version") != REPORT_FORMAT_VERSION:
        raise ValueError(
            f"승인 목록의 형식 버전이 맞지 않음 (필요 {REPORT_FORMAT_VERSION}) — "
            "이 도구의 미리 보기 --json 출력을 쓴다"
        )
    runs = data.get("runs")
    if not isinstance(runs, list):
        raise ValueError("승인 목록에 runs가 없음")
    return {str(run["simulation_id"]) for run in runs if run.get("status") == STATUS_TARGET}


def split_by_approval(checks: Sequence[RunCheck], approved: set[str]) -> ApprovalSplit:
    """지금 판정을 승인 목록과 맞춘다. 쓰지 않는다."""
    split = ApprovalSplit()
    now_target = set()
    for check in checks:
        if check.status != STATUS_TARGET:
            continue
        now_target.add(check.simulation_id)
        (split.to_mark if check.simulation_id in approved else split.outside).append(check)
    split.changed = sorted(approved - now_target)
    return split


async def apply_approved(
    session: AsyncSession,
    checks: Sequence[RunCheck],
    approved: set[str],
    recovery_path: str,
) -> tuple[ApprovalSplit, int]:
    """승인 목록 안의 대상만 표시한다. 복구 자료를 **먼저** 남긴다. 커밋은 호출부가 한다."""
    split = split_by_approval(checks, approved)
    write_recovery_file(recovery_path, split.to_mark)
    return split, await apply(session, split.to_mark)


# ─── 출력 ────────────────────────────────────────────────────────────────────


def summarize(checks: Sequence[RunCheck]) -> dict[str, int]:
    counts = {status: 0 for status in _STATUS_LABEL}
    for check in checks:
        counts[check.status] += 1
    return counts


def format_table(checks: Sequence[RunCheck]) -> str:
    """사람이 읽는 표 — 대상과 견줄 수 없는 실행은 항목·사유를 줄마다 적는다."""
    lines = [f"{'상태':<8}  {'실행 번호':<36}  {'연도':>4}  {'스냅샷 생성(UTC)':<32}  선박"]
    for check in checks:
        lines.append(
            f"{_STATUS_LABEL[check.status]:<8}  {check.simulation_id:<36}  "
            f"{check.regulation_year:>4}  {check.snapshot_created_at:<32}  {check.vessel}"
        )
        for item in check.differences:
            lines.append(f"{'':<8}    · {item}")
        for item in check.reasons:
            lines.append(f"{'':<8}    ? {item}")
    counts = summarize(checks)
    lines.append("")
    lines.append(
        "합계 "
        + " · ".join(f"{_STATUS_LABEL[status]} {counts[status]}건" for status in _STATUS_LABEL)
    )
    return "\n".join(lines)


def report_json(checks: Sequence[RunCheck], *, applied: bool, marked: int) -> dict[str, object]:
    return {
        "format_version": REPORT_FORMAT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "apply" if applied else "dry-run",
        "marked": marked,
        "counts": summarize(checks),
        "runs": [asdict(check) for check in checks],
    }


def write_recovery_file(path: str, checks: Sequence[RunCheck]) -> list[str]:
    """적용 **전에** 표시할 실행 번호를 파일로 남긴다 (복구 자료). 대상 번호 목록을 돌려준다.

    ``needs_recalc``는 되돌릴 수 없으므로 이 목록이 「무엇을 표시했나」의 유일한 기록이다.
    """
    targets = [check for check in checks if check.status == STATUS_TARGET]
    payload = {
        "issue": 2373,
        "created_at": datetime.now(UTC).isoformat(),
        "calculation_run_ids": [check.calculation_run_id for check in targets],
        "runs": [asdict(check) for check in targets],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    return payload["calculation_run_ids"]


# ─── 진입점 ──────────────────────────────────────────────────────────────────


def parse_args(argv: Sequence[str] | None = None):
    """인자를 읽는다. ``--apply``에 ``--approved``가 없으면 DB를 열기 전에 거부한다 (#2491)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m cii_platform.maintenance.annual_needs_recalc",
        description="저장 연간 실행의 낡음 표시 소급 처리 (#2373) — 기본은 미리 보기",
    )
    parser.add_argument("--apply", action="store_true", help="대상 실행에 needs_recalc를 세운다")
    parser.add_argument(
        "--recovery-file",
        default=None,
        help="--apply 때 표시 전에 대상 번호를 남길 파일 (기본 ./annual_needs_recalc_<UTC>.json)",
    )
    parser.add_argument(
        "--json", dest="json_path", default=None, help="JSON 보고 경로 (- = 표준출력)"
    )
    parser.add_argument("--vessel-id", type=UUID, default=None, help="이 선박의 실행만")
    parser.add_argument(
        "--approved",
        default=None,
        help="--apply 필수: 승인한 미리 보기 JSON. 이 파일의 대상 실행만 표시한다",
    )
    args = parser.parse_args(argv)
    if args.apply and not args.approved:
        parser.error("--apply는 --approved <승인한 미리 보기 JSON>이 필요하다")
    return args


async def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - 프로세스 진입점
    """엔진을 열어 견주고(기본), ``--apply``면 승인 목록의 대상만 표시한다. 종료 코드를 돌려준다."""
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from cii_platform.config import DATABASE_URL
    from cii_platform.db.url import normalize_to_async

    args = parse_args(argv)
    approved: set[str] = set()
    if args.apply:
        try:
            approved = load_approved(args.approved)
        except (OSError, ValueError, KeyError) as exc:
            print(f"승인 목록을 읽을 수 없음 — {exc}", file=sys.stderr)
            return 2

    engine = create_async_engine(normalize_to_async(DATABASE_URL), poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            session = AsyncSession(bind=conn)
            checks = await evaluate(session, vessel_id=args.vessel_id)
            marked = 0
            if args.apply:
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                path = args.recovery_file or f"annual_needs_recalc_{stamp}.json"
                split, marked = await apply_approved(session, checks, approved, path)
                ids = [check.calculation_run_id for check in split.to_mark]
                print(f"복구 자료: {path} (표시할 대상 {len(ids)}건)")
                print("대상 calculation_run 번호: " + (", ".join(ids) or "(없음)"))
                await session.commit()
                for check in split.outside:
                    print(f"승인 목록 밖 — 표시하지 않음: {check.simulation_id} ({check.vessel})")
                for simulation_id in split.changed:
                    print(f"승인 뒤 상태가 바뀜 — 건너뜀: {simulation_id}")
    finally:
        await engine.dispose()

    print(format_table(checks))
    print(f"{'표시했다' if args.apply else '미리 보기 — 쓰지 않았다'}: {marked}건")
    if args.json_path:
        text = json.dumps(
            report_json(checks, applied=args.apply, marked=marked), ensure_ascii=False, indent=2
        )
        if args.json_path == "-":
            print(text)
        else:
            with open(args.json_path, "w", encoding="utf-8") as handle:
                handle.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - 프로세스 진입점
    import asyncio

    sys.exit(asyncio.run(main()))
