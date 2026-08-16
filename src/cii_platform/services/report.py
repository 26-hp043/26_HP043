"""리포트 데이터 수집 (PRD §25, API_SPEC §8.3~§8.4, #361).

**계산하지 않는다.** 수치는 ``#353``(YTD 엔진) · ``#354``(3종 값) · ``#355``(연도별
이력)이 이미 만든다. 이 모듈이 하는 일은 그것들을 모아 **문서 모델**로 옮기는 것이다.

리포트가 값을 다시 계산하면 화면과 문서가 갈리고, 그때 어느 쪽이 맞는지 판단할 근거가
없다 — 「보고서에는 B인데 화면에는 C」가 되는 순간 두 값 모두 못 믿게 된다.

## 시나리오 사후 비교는 인용만 한다

``PRD §25.2.1``이 *"저장된 이력을 그대로 인용한다 — 리포트 생성 시점에 재계산하지
않는다. 재계산하면 파라미터 개정·기상 갱신으로 과거 비교 근거가 바뀐다"* 를 요구한다.
저장된 ``voyage_scenario`` 행을 그대로 읽고, **이력이 없으면 그 섹션을 생략한다** —
없는 비교를 만들지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from cii_platform.calc.capacity import capacity_axis
from cii_platform.calc.precision import LAYER1_ROUNDING
from cii_platform.db.models.voyage_scenario import VoyageScenario
from cii_platform.db.repositories import not_underway as not_underway_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError
from cii_platform.reports.document import (
    VOYAGE_CII_NOTE,
    KeyValueSection,
    ReportDocument,
    TableSection,
)
from cii_platform.services.cii_current import get_current_cii
from cii_platform.services.cii_history import list_cii_history
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import compute_ytd_cii

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: 항차 완료 리포트의 대상 상태 (``PRD §25.2``).
#: **진행 중 항차는 대상이 아니다** — 실적이 확정되지 않은 값으로 보고서를 만들면
#: 같은 항차의 리포트가 시점마다 달라진다.
REPORTABLE_STATUSES = ("COMPLETED", "CONFIRMED")

_DIGITS = {"cii": 6, "ratio": 5, "distance_nm": 2, "fuel_ton": 2, "co2_ton": 2, "hours": 2}


def _publish(value: Decimal | None, kind: str) -> str:
    """``API_SPEC §1.7`` 문자열 직렬화. 없으면 ``—``다 — 빈칸은 열이 밀린 것으로 읽힌다."""
    if value is None:
        return "—"
    return str(Decimal(value).quantize(Decimal(1).scaleb(-_DIGITS[kind]), rounding=LAYER1_ROUNDING))


def _text(value: object) -> str:
    return "—" if value is None or value == "" else str(value)


def _iso(value) -> str:
    return "—" if value is None else value.isoformat()


# ─── 항차 완료 리포트 (PRD §25.2) ────────────────────────────────────────────


async def _scenario_section(session: AsyncSession, voyage) -> TableSection | None:
    """시나리오 사후 비교 (``PRD §25.2.1``).

    *"이 항차에서 감속했다면 등급이 어떻게 달라졌는가"* 를 보이는 섹션이다.

    **저장된 값을 그대로 인용한다.** 재계산하면 파라미터 개정·기상 갱신으로 과거
    비교 근거가 바뀐다. 이력이 없으면 ``None`` — 없는 비교를 만들지 않는다.
    """
    rows = (
        (
            await session.execute(
                select(VoyageScenario)
                .where(
                    VoyageScenario.voyage_id == voyage.id,
                    VoyageScenario.is_deleted.is_(False),
                )
                .order_by(VoyageScenario.created_at, VoyageScenario.id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None

    table = TableSection(
        title="시나리오 사후 비교",
        headers=["시나리오", "거리 (nm)", "속력 (kn)", "소요 (h)", "연료 (t)", "CII", "예상 등급"],
        rows=[
            [
                f"{row.scenario_name}{' (채택)' if row.is_adopted else ''}",
                _publish(row.distance_nm, "distance_nm"),
                _publish(row.speed_kn, "distance_nm"),
                _publish(row.duration_hours, "hours"),
                _publish(row.fuel_ton, "fuel_ton"),
                _publish(row.cii_value, "cii"),
                _text(row.estimated_rating),
            ]
            for row in rows
        ],
        # `PRD §11` 중립 비교 원칙 — 우선순위를 부여하지 않는다.
        note=(
            "항차 착수 전 저장된 비교 이력을 그대로 인용했습니다(재계산하지 않음). "
            "시스템은 수치만 비교하며 최종 운항 판단은 사용자에게 있습니다."
        ),
    )
    table.validate()
    return table


async def build_voyage_report(
    session: AsyncSession, voyage_id: UUID, *, as_of: datetime | None = None
) -> ReportDocument:
    """항차 완료 리포트 (``PRD §25.2``).

    진행 중 항차는 422다 — 상태가 잘못된 것이지 요청 형식이 틀린 것이 아니므로
    ``StateTransitionError``를 쓴다(``API_SPEC §1.4``와 같은 축).
    """
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None or voyage.is_deleted:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")
    if voyage.status not in REPORTABLE_STATUSES:
        raise StateTransitionError(
            f"완료되지 않은 항차는 리포트 대상이 아닙니다 (현재 상태: {voyage.status}). "
            "항차를 완료 처리한 뒤 다시 시도해 주세요."
        )

    vessel = await vessel_repo.get_by_id(session, voyage.vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {voyage.vessel_id}")

    resolved = resolve_as_of(as_of)
    year = voyage.regulation_year or resolved.year
    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)

    # YTD는 「이 항차가 연간 누적에서 차지한 비중」을 내기 위해 필요하다.
    ytd = await compute_ytd_cii(session, vessel_id=vessel.id, regulation_year=year)

    voyage_co2_g = sum(
        (
            (fu.actual_fuel_ton or fu.planned_fuel_ton or Decimal(0))
            * Decimal(1_000_000)
            * Decimal(fu.cf_used)
            for fu in fuel_uses
        ),
        Decimal(0),
    )
    voyage_co2_t = voyage_co2_g / Decimal(1_000_000)

    share = "—"
    if ytd.total_co2_t and ytd.total_co2_t > 0:
        share = f"{(voyage_co2_t / ytd.total_co2_t * 100).quantize(Decimal('0.1'))}%"

    document = ReportDocument(
        title=f"항차 완료 리포트 — {vessel.name} {voyage.voyage_no or ''}".strip(),
        slug=f"voyage-report-{voyage.id}",
        meta=[
            ("선박", vessel.name),
            ("IMO", vessel.imo_number),
            ("규제연도", str(year)),
            ("생성 시각", resolved.isoformat()),
        ],
        sections=[
            KeyValueSection(
                title="항차 요약",
                rows=[
                    ("항차 번호", _text(voyage.voyage_no)),
                    ("상태", _text(voyage.status)),
                    ("출발", _text(voyage.departure_port_name)),
                    ("도착", _text(voyage.arrival_port_name)),
                    ("출항 (실적)", _iso(voyage.actual_departure_at)),
                    ("입항 (실적)", _iso(voyage.actual_arrival_at)),
                    ("거리 — 계획", _publish(voyage.planned_distance_nm, "distance_nm")),
                    ("거리 — 실적", _publish(voyage.actual_distance_nm, "distance_nm")),
                    ("속력 — 계획", _publish(voyage.planned_speed_kn, "distance_nm")),
                    ("속력 — 실적 평균", _publish(voyage.actual_avg_speed_kn, "distance_nm")),
                    ("연간 집계 반영", _text(voyage.annual_inclusion_policy)),
                ],
            ),
            KeyValueSection(
                title="CII 기여도",
                rows=[
                    ("항차 CO₂ 배출량 (t)", _publish(voyage_co2_t, "co2_ton")),
                    ("연간 누적 CO₂ (t)", _publish(ytd.total_co2_t, "co2_ton")),
                    ("연간 누적에서 차지한 비중", share),
                    ("연간 누적 CII", _publish(ytd.attained_cii, "cii")),
                    ("연간 기준 CII", _publish(ytd.required_cii, "cii")),
                    ("연간 누적 등급", _text(ytd.rating)),
                    ("표시 단위", f"gCO₂/({capacity_axis(vessel.ship_type)}·nm)"),
                ],
                # COR-1 — 항차 단위 CII는 등급 지표가 아니다.
                note=VOYAGE_CII_NOTE,
            ),
            TableSection(
                title="연료 내역",
                headers=["유종", "계획 (t)", "실적 (t)", "CF snapshot", "배출량 (tCO₂)", "출처"],
                rows=[
                    [
                        fu.fuel_type,
                        _publish(fu.planned_fuel_ton, "fuel_ton"),
                        _publish(fu.actual_fuel_ton, "fuel_ton"),
                        str(fu.cf_used),
                        _publish(
                            (fu.actual_fuel_ton or fu.planned_fuel_ton or Decimal(0))
                            * Decimal(fu.cf_used),
                            "co2_ton",
                        ),
                        _text(fu.source),
                    ]
                    for fu in fuel_uses
                ]
                # 연료 기록이 없는 항차도 있다. 빈 표 대신 사유 한 줄을 둔다 —
                # 빈 표는 「아직 안 불러왔다」로 읽힌다.
                or [["—", "—", "—", "—", "—", "기록 없음"]],
            ),
        ],
        warnings=list(ytd.warnings),
    )

    scenarios = await _scenario_section(session, voyage)
    if scenarios is not None:
        document.sections.append(scenarios)

    document.validate()
    return document


# ─── 연간 실적 리포트 (PRD §25.3) ────────────────────────────────────────────

#: 정박 유형의 한국어 이름. ``#370``의 화면 라벨과 같은 표를 서버에도 둔다 —
#: 문서는 화면 코드를 부를 수 없다.
_PERIOD_LABELS = {
    "IN_PORT": "접안",
    "AT_ANCHOR": "묘박",
    "DRIFTING": "표류",
    "STS": "STS 이송",
    "CANAL_TRANSIT": "운하 통과",
    "DRYDOCK": "드라이독",
}


async def _not_underway_section(
    session: AsyncSession, *, vessel_id: UUID, year: int
) -> TableSection:
    """not under way 기여 — 유형별 연료(분자)와 거리(분모) (``PRD §25.3``).

    ``MEPC.412(84)`` §4.2가 ``Dt``를 *"both under way and not under way"* 로 정의하므로
    정박 구간의 이동 거리도 분모에 들어간다. 접안·묘박은 0이고 운하 통과·표류·STS만
    값이 있어, 유형별로 나눠야 그 차이가 보인다.
    """
    periods = await not_underway_repo.list_periods_for_year(
        session, vessel_id=vessel_id, regulation_year=year
    )

    by_type: dict[str, dict[str, Decimal | int]] = {}
    for period in periods:
        bucket = by_type.setdefault(
            period.period_type, {"count": 0, "distance": Decimal(0), "fuel": Decimal(0)}
        )
        bucket["count"] = int(bucket["count"]) + 1
        bucket["distance"] = Decimal(bucket["distance"]) + Decimal(period.distance_nm)
        for fuel_use in await not_underway_repo.list_fuel_uses(session, period.id):
            bucket["fuel"] = Decimal(bucket["fuel"]) + Decimal(fuel_use.fuel_ton)

    rows = [
        [
            _PERIOD_LABELS.get(period_type, period_type),
            str(bucket["count"]),
            _publish(Decimal(bucket["distance"]), "distance_nm"),
            _publish(Decimal(bucket["fuel"]), "fuel_ton"),
        ]
        for period_type, bucket in sorted(by_type.items())
    ]

    return TableSection(
        title="not under way 기여",
        headers=["구간 유형", "건수", "이동 거리 (nm)", "연료 (t)"],
        # 기록이 없는 것은 오류가 아니다 — 「0건」이 아니라 그 사실을 적는다.
        rows=rows or [["기록 없음", "0", "0.00", "0.00"]],
        note=(
            "정박 구간의 연료는 CII 분자에, 이동 거리는 분모에 포함됩니다"
            " (MEPC.412(84) §4.2). 접안·묘박의 이동 거리 0은 정상값입니다."
        ),
    )


async def build_annual_report(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    year: int | None = None,
    as_of: datetime | None = None,
) -> ReportDocument:
    """연간 실적 리포트 (``PRD §25.3``).

    연중 언제든 생성 가능하다 — 생성 시점 기준 YTD와 확정 연도 이력을 함께 싣는다.
    """
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None or vessel.is_deleted:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")

    resolved = resolve_as_of(as_of)
    target_year = year if year is not None else resolved.year
    if not 2019 <= target_year <= 2100:
        raise ValidationError(
            "규제연도는 2019~2100 범위여야 합니다.", field="year", field_label="규제연도"
        )

    # 3종 값은 `#354`가 이미 만든다 — 여기서 다시 계산하면 화면과 문서가 갈린다.
    current, current_meta = await get_current_cii(
        session, vessel_id, year=target_year, as_of=resolved
    )
    history = await list_cii_history(
        session, vessel_id=vessel_id, to_year=target_year, as_of=resolved
    )

    ytd = current["ytd"]
    projection = current["year_end_projection"]

    sections: list[KeyValueSection | TableSection] = [
        KeyValueSection(
            title=f"{target_year}년 누적 (YTD)",
            rows=[
                ("실적 CII (attained)", _text(ytd["attained_cii"])),
                ("기준 CII (required)", _text(ytd["required_cii"])),
                ("현재 누적 기준 예상 등급", _text(ytd["rating"])),
                ("위험도", _text(ytd["risk_level"])),
                ("누적 거리 (nm)", _text(ytd["total_distance_nm"])),
                ("누적 연료 (t)", _text(ytd["total_fuel_ton"])),
                ("누적 CO₂ (t)", _text(ytd["total_co2_ton"])),
                ("항차 수", _text(ytd["voyage_count"])),
                ("표시 단위", f"gCO₂/({current['transport_capacity_basis']}·nm)"),
            ],
            note=(
                "연중 누적 예측값이며 공식 등급이 아닙니다. "
                "공식 등급은 연말 DCS 보고·검증 후 확정됩니다."
            ),
        ),
        TableSection(
            title="연도별 추이",
            headers=[
                "연도",
                "상태",
                "실적 CII",
                "기준 CII",
                "등급",
                "항차 수",
                "거리 (nm)",
                "연료 (t)",
            ],
            rows=[
                [
                    str(row["regulation_year"]),
                    "진행 중" if row["status"] == "IN_PROGRESS" else "확정",
                    _text(row["attained_cii"]),
                    _text(row["required_cii"]),
                    _text(row["rating"]),
                    _text(row["voyage_count"]),
                    _text(row["total_distance_nm"]),
                    _text(row["total_fuel_ton"]),
                ]
                for row in history["years"]
            ],
        ),
        await _not_underway_section(session, vessel_id=vessel_id, year=target_year),
    ]

    # 연말 예상은 **가정과 함께** 싣는다 (`PRD §3.3` ⑶). 값만 실으면 확정값처럼 읽힌다.
    if projection["data_available"]:
        assumptions = projection["assumptions"]
        sections.append(
            KeyValueSection(
                title="연말 예상",
                rows=[
                    ("예상 CII", _text(projection["attained_cii"])),
                    ("연말 예상 등급", _text(projection["rating"])),
                    ("산출 방식", "지금까지의 일평균이 연말까지 이어진다고 가정"),
                    ("경과 일수", _text(assumptions["elapsed_days"])),
                    ("잔여 일수", _text(assumptions["remaining_days"])),
                    ("일평균 거리 (nm)", _text(assumptions["daily_distance_nm"])),
                    ("일평균 연료 (t)", _text(assumptions["daily_fuel_ton"])),
                ],
                note="가정이 바뀌면 값이 바뀝니다. 확정값이 아닙니다.",
            )
        )
    else:
        sections.append(
            KeyValueSection(
                title="연말 예상",
                # 사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.
                rows=[("산출 여부", "산출하지 않음"), ("사유", _text(projection["reason"]))],
            )
        )

    document = ReportDocument(
        title=f"연간 실적 리포트 — {vessel.name} ({target_year})",
        slug=f"annual-report-{vessel_id}-{target_year}",
        meta=[
            ("선박", vessel.name),
            ("IMO", vessel.imo_number),
            ("선종", vessel.ship_type),
            ("기준 시각", str(current_meta["as_of"])),
        ],
        sections=sections,
        warnings=list(current["warnings"]),
    )
    document.validate()
    return document
