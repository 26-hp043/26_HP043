"""자료 내보내기 (API_SPEC §8.1, #59).

**가져오기(`§8.2`)의 반대 방향이다.** `#60`이 넣는 경로를 열었고 여기서 꺼내는 경로를
연다. `PRD §5.1`의 「연도별 항차 이력 축적(CSV 가져오기·**내보내기**)」 MUST 중 남아
있던 절반이다.

## 내보낸 파일을 그대로 다시 가져올 수 있다

항차 표의 앞쪽 일곱 열은 **가져오기 필수 컬럼 7종과 이름이 같다**(`§8.2`). 뒤에
붙는 실적·집계 열은 가져오기가 읽지 않으므로(``parse_row``가 7종만 본다) 무시된다 —
즉 **내보내서 고쳐서 다시 넣는** 동선이 성립한다.

⚠️ 다만 **연료가 둘 이상인 항차는 행이 나뉜다**(한 행 = 항차 × 연료). 나뉜 파일을
그대로 가져오면 가져오기는 1행을 1항차로 읽으므로 **같은 항차 번호로 여러 항차**가
만들어진다. ``voyage_id`` 열이 맨 앞에 있어 나뉜 사실 자체는 파일에서 보인다.

## CII 등급을 항차 행에 싣지 않는다

`API_SPEC §8.1`의 최초 예시 헤더에는 ``attained_cii``·``rating``이 있었으나 **채울
근거가 없다.**

1. ``calculation_run.voyage_id``는 열은 있지만 **항상 NULL**이다 — 계산을 만드는 두
   자리(``insert_voyage_estimate``·``insert_scenario``)가 모두 ``None``을 넣는다.
   어떤 항차의 계산인지 되짚을 방법이 없다.
2. 「항차 하나의 CII」는 **정본에 정의된 양이 아니다.** CII는 연간 집계량이고
   (`PRD §8.1.2`), 항차 완료 리포트조차 「연간 누적 CII」만 싣는다.

빈 칸으로 두면 「아직 계산 안 됨」으로 읽히지만 실제로는 **영원히 채워지지 않는
칸**이다. 그래서 열 자체를 두지 않는다 (`#449` — 계산할 수 없을 때 그럴듯한 값을
만들지 않는다).

## 시각은 KST 오프셋을 붙인 ISO 8601이다

``2026-02-10T16:00:00+09:00``. 오프셋이 있어 기계가 정확히 읽고, 한국 사용자가
스프레드시트에서 열었을 때 **자기 시각으로** 보인다. UTC ISO로 두면 후자가 깨지고
(`#646`), 오프셋 없는 현지 시각으로 두면 전자가 깨진다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from cii_platform.db.repositories import annual_simulation as sim_repo
from cii_platform.db.repositories import calculation_run as calc_run_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: ``API_SPEC §8.1`` ``type`` 파라미터가 허용하는 값. **필수다** — 기본값을 두면
#: 사용자가 `calculations`를 받으려다 항차 파일을 받고도 알아채지 못한다.
EXPORT_TYPES: tuple[str, ...] = ("voyages", "calculations", "simulations")

#: ``API_SPEC §8.1`` ``format`` 파라미터. 기본은 ``csv``.
EXPORT_FORMATS: tuple[str, ...] = ("csv", "json")

#: 시각 표기 기준. `#646`과 같은 이유로 KST다.
_EXPORT_TIMEZONE = ZoneInfo("Asia/Seoul")

#: 계산 이력을 한 번에 가져올 상한. ``list_runs``가 커서 기반이라 상한이 필요하다.
#: 선박 하나의 이력이 이 수를 넘으면 **잘린 사실을 열로 알린다**(``_CALC_LIMIT`` 각주).
_CALC_LIMIT = 10_000

#: 항차 표 — 앞 일곱 열이 ``§8.2`` 필수 컬럼과 **이름이 같다**(왕복).
VOYAGE_COLUMNS: tuple[str, ...] = (
    "voyage_id",
    "voyage_no",
    "departure_port_name",
    "arrival_port_name",
    "planned_distance_nm",
    "planned_speed_kn",
    "fuel_type",
    "planned_fuel_ton",
    "status",
    "regulation_year",
    "annual_inclusion_policy",
    "created_from",
    "actual_distance_nm",
    "actual_avg_speed_kn",
    "planned_departure_at",
    "planned_arrival_at",
    "actual_departure_at",
    "actual_arrival_at",
    "actual_fuel_ton",
    "cf_used",
    "co2_ton",
    "notes",
)

#: ``§8.2`` 필수 컬럼 7종이 항차 표 **앞쪽에** 그대로 있다는 약속.
#: :mod:`cii_platform.services.voyage_import`\ 의 ``REQUIRED_COLUMNS``와 대조된다.
ROUNDTRIP_COLUMNS: tuple[str, ...] = VOYAGE_COLUMNS[1:8]

CALCULATION_COLUMNS: tuple[str, ...] = (
    "calculation_run_id",
    "calculation_type",
    "created_at",
    "input_hash",
    "parameter_hash",
    "model_version",
    "duration_ms",
    "needs_recalc",
    "attained_cii",
    "required_cii",
    "ratio_to_required",
    "estimated_rating",
    "co2_emission_ton",
    "fuel_consumption_ton",
    "distance_nm",
    "risk_level",
    "warnings",
)

SIMULATION_COLUMNS: tuple[str, ...] = (
    "simulation_run_id",
    "calculation_run_id",
    "created_at",
    "regulation_year",
    "target_rating",
    "simulation_runs",
    "snapshot_id",
    "projected_attained_cii",
    "projected_rating",
    "risk_level",
    "target_success_probability",
    "p10",
    "p50",
    "p90",
    "completed_voyage_count",
    "remaining_voyage_count",
    "warnings",
)

COLUMNS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "voyages": VOYAGE_COLUMNS,
    "calculations": CALCULATION_COLUMNS,
    "simulations": SIMULATION_COLUMNS,
}


@dataclass(frozen=True)
class ExportTable:
    """내보낼 표 하나. 렌더링(CSV/JSON)은 라우트가 정한다."""

    type: str
    year: int | None
    columns: tuple[str, ...]
    rows: list[list[str]]

    @property
    def filename_stem(self) -> str:
        """``voyages_2026`` · ``voyages`` (``API_SPEC §8.1`` 응답 예시)."""
        return self.type if self.year is None else f"{self.type}_{self.year}"

    def as_dicts(self) -> list[dict[str, str]]:
        """``format=json`` 응답용. 열 이름을 행마다 붙인다."""
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]


def _cell(value: object) -> str:
    """값 하나를 셀 문자열로.

    ``None``은 **빈 칸**이다 — ``—``·``N/A`` 같은 표기는 사람이 읽는 문서의 것이고,
    자료 파일에 넣으면 숫자 열에 문자열이 섞여 다시 가져올 수 없다.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        # `True`/`False`가 아니라 소문자다 — JSON·CSV 양쪽에서 같게 읽힌다.
        return "true" if value else "false"
    if isinstance(value, Decimal):
        # 지수 표기를 만들지 않는다. `1E+4`는 스프레드시트가 다시 읽을 수는 있어도
        # 사람이 원본 값으로 알아보지 못하고, 가져오기의 `Decimal()`에도 그대로
        # 들어가 값이 바뀐 것처럼 보인다.
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(_EXPORT_TIMEZONE).isoformat()
    if isinstance(value, (dict, list)):
        # `model_version`·`warnings` 같은 JSONB 열. 한 셀에 담되 **원문 그대로**다.
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _row(values: list[object]) -> list[str]:
    return [_cell(value) for value in values]


async def _require_vessel(session: AsyncSession, vessel_id: UUID) -> None:
    """선박이 없으면 404다.

    빈 표를 돌려주면 **오타 난 UUID와 항차가 없는 선박이 같아 보인다** — 받은 사람은
    「이 배는 올해 항차가 없구나」로 읽는다.
    """
    if await vessel_repo.get_by_id(session, vessel_id) is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")


async def _voyage_rows(session: AsyncSession, vessel_id: UUID, year: int | None) -> list[list[str]]:
    """항차 × 연료. ``year``는 ``voyage.regulation_year``로 거른다."""
    voyages = await voyage_repo.list_for_export(session, vessel_id=vessel_id, regulation_year=year)
    fuel_by_voyage = await voyage_repo.list_fuel_uses_by_voyage_ids(
        session, [voyage.id for voyage in voyages]
    )

    rows: list[list[str]] = []
    for voyage in voyages:
        fuel_uses = sorted(fuel_by_voyage.get(voyage.id, []), key=lambda fu: fu.fuel_type)
        # 연료가 한 건도 없는 항차도 **행을 남긴다.** 빼면 파일의 항차 수가 화면과
        # 달라지고, 연료를 아직 넣지 않았다는 사실이 파일에서 사라진다.
        for fuel_use in fuel_uses or [None]:
            rows.append(_voyage_row(voyage, fuel_use))
    return rows


def _voyage_row(voyage, fuel_use) -> list[str]:
    planned_ton = None if fuel_use is None else fuel_use.planned_fuel_ton
    actual_ton = None if fuel_use is None else fuel_use.actual_fuel_ton
    cf_used = None if fuel_use is None else fuel_use.cf_used

    # `services/report.py`와 **같은 식**이다 — 실적이 있으면 실적, 없으면 계획
    # (`PRD §8.3`). 두 곳에 다른 식이 있으면 리포트와 파일의 CO₂가 갈린다.
    co2_ton: Decimal | None = None
    if cf_used is not None:
        used_ton = actual_ton if actual_ton is not None else planned_ton
        if used_ton is not None:
            co2_ton = Decimal(used_ton) * Decimal(cf_used)

    return _row(
        [
            voyage.id,
            voyage.voyage_no,
            voyage.departure_port_name,
            voyage.arrival_port_name,
            voyage.planned_distance_nm,
            voyage.planned_speed_kn,
            None if fuel_use is None else fuel_use.fuel_type,
            planned_ton,
            voyage.status,
            voyage.regulation_year,
            voyage.annual_inclusion_policy,
            voyage.created_from,
            voyage.actual_distance_nm,
            voyage.actual_avg_speed_kn,
            voyage.planned_departure_at,
            voyage.planned_arrival_at,
            voyage.actual_departure_at,
            voyage.actual_arrival_at,
            actual_ton,
            cf_used,
            co2_ton,
            voyage.notes,
        ]
    )


async def _calculation_rows(
    session: AsyncSession, vessel_id: UUID, year: int | None
) -> list[list[str]]:
    """계산 이력.

    ⚠️ **``year``의 뜻이 다른 둘과 다르다.** ``calculation_run``에는 규제연도 열이
    없어(`DB_SCHEMA §2.5`) ``created_at``의 연도로 거른다 — 「그 해에 만든 계산」이지
    「그 해를 대상으로 한 계산」이 아니다. 경계는 KST다.

    시나리오 비교(``SCENARIO``) 실행은 결과가 여러 안이라 **한 행에 담기지 않는다.**
    식별자·해시만 싣고 값 칸은 비운다 — ``calculation_type`` 열이 그 이유를 말한다.
    """
    runs = await calc_run_repo.list_runs(session, limit=_CALC_LIMIT, vessel_id=vessel_id)
    if year is not None:
        runs = [run for run in runs if run.created_at.astimezone(_EXPORT_TIMEZONE).year == year]

    rows: list[list[str]] = []
    # 저장소가 최신순으로 주지만 **파일은 실행 순서**여야 한다.
    for run in sorted(runs, key=lambda r: (r.created_at, r.id)):
        result = run.result_json if isinstance(run.result_json, dict) else {}
        rows.append(
            _row(
                [
                    run.id,
                    run.calculation_type,
                    run.created_at,
                    run.input_hash,
                    run.parameter_hash,
                    run.model_version,
                    run.duration_ms,
                    run.needs_recalc,
                    result.get("attained_cii"),
                    result.get("required_cii"),
                    result.get("ratio_to_required"),
                    result.get("estimated_rating"),
                    result.get("co2_emission_ton"),
                    result.get("fuel_consumption_ton"),
                    result.get("distance_nm"),
                    result.get("risk_level"),
                    run.warnings_json,
                ]
            )
        )
    return rows


async def _simulation_rows(
    session: AsyncSession, vessel_id: UUID, year: int | None
) -> list[list[str]]:
    """연간 시뮬레이션 실행.

    ``#443`` 이전 실행은 ``result_json``에 결과 본문이 없다. 조회(`§6.2`)는 그 행을
    404로 끊지만 **내보내기는 끊지 않는다** — 한 행 때문에 파일 전체가 실패하면
    사용자는 어느 행인지 알아낼 방법이 없다. 값 칸을 비우고 식별자는 남긴다.
    """
    pairs = await sim_repo.list_for_export(session, vessel_id=vessel_id, regulation_year=year)

    rows: list[list[str]] = []
    for run, calc in pairs:
        payload = calc.result_json if isinstance(calc.result_json, dict) else {}
        deterministic = payload.get("deterministic") or {}
        monte_carlo = payload.get("monte_carlo") or {}
        rows.append(
            _row(
                [
                    run.id,
                    run.calculation_run_id,
                    run.created_at,
                    run.regulation_year,
                    run.target_rating,
                    run.simulation_runs,
                    run.snapshot_id,
                    deterministic.get("projected_attained_cii"),
                    deterministic.get("projected_rating"),
                    payload.get("risk_level"),
                    monte_carlo.get("target_success_probability"),
                    monte_carlo.get("p10"),
                    monte_carlo.get("p50"),
                    monte_carlo.get("p90"),
                    deterministic.get("completed_voyage_count"),
                    deterministic.get("remaining_voyage_count"),
                    payload.get("warnings"),
                ]
            )
        )
    return rows


async def build_export(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    type: str,
    year: int | None = None,
) -> ExportTable:
    """내보낼 표를 만든다 (``API_SPEC §8.1``).

    ``type``을 **조용히 기본값으로 되돌리지 않는다** — 오타(`voyage`)를 `voyages`로
    받아들이면 사용자는 자기가 무엇을 받았는지 모른다.
    """
    if type not in EXPORT_TYPES:
        raise ValidationError(
            f"지원하지 않는 자료 종류입니다: {type}. "
            f"{' · '.join(EXPORT_TYPES)} 중 하나여야 합니다.",
            field="type",
            field_label="자료 종류",
        )

    await _require_vessel(session, vessel_id)

    if type == "voyages":
        rows = await _voyage_rows(session, vessel_id, year)
    elif type == "calculations":
        rows = await _calculation_rows(session, vessel_id, year)
    else:
        rows = await _simulation_rows(session, vessel_id, year)

    return ExportTable(type=type, year=year, columns=COLUMNS_BY_TYPE[type], rows=rows)
