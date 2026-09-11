import { SCREEN_BY_ID } from '../../screens'
import type { InclusionPolicy, VoyageDraft } from '../voyage-management/types'
import type { VoyageCiiRequest, VoyageCiiResponse } from './types'

/**
 * 기능① 결과 화면의 사용자 액션 3종 — 규칙 (`PRD §10.5` · #891).
 *
 * | 액션 | 무엇 |
 * |---|---|
 * | 계획 저장 | 이 계산의 거리·속력·연료로 **계획 항차(`PLANNED`)**를 만든다 |
 * | 연간 시뮬레이터에서 보기 | 같은 선박·연도로 기능③ 화면에 간다 |
 * | CSV 다운로드 | **이 계산 한 건**을 서버 내보내기로 받는다 |
 *
 * 화면(`VoyageCiiActions.tsx`)은 이 순수 함수를 부르고 상태만 옮긴다.
 */

/** 계획 저장에 사용자가 더 넣어야 하는 값 — 기능① 입력에는 없다. */
export interface PlanSaveForm {
  voyageNo: string
  departurePortName: string
  arrivalPortName: string
  /** `datetime-local` 값. */
  plannedDepartureAt: string
  /** 연간 시뮬레이션에 반영할지 — `INCLUDE_AS_PLAN` / `EXCLUDE`. */
  includeInAnnual: boolean
}

export function initialPlanSaveForm(): PlanSaveForm {
  return {
    voyageNo: '',
    departurePortName: '',
    arrivalPortName: '',
    plannedDepartureAt: '',
    // 기본은 반영이다 — `PRD §5.1` 「기능① 계획 저장 → 기능③ 반영」 MUST.
    includeInAnnual: true,
  }
}

export type PlanSaveErrors = Partial<Record<keyof PlanSaveForm, string>>

/**
 * 출발항·도착항·출항 예정 시각은 **필수**다.
 *
 * 기능②의 「새 항차로 채택」과 같은 규율이다(`services/scenario_adopt.py`) — 계산은 거리·
 * 속력·연료만 알아 **어디서 어디로 언제 떠나는지를 모른다.** 출항 시각이 없으면 그 항차를
 * 진행 중으로 옮겼을 때 시뮬레이션 시계가 누적을 **조용히 0**으로 만든다(`#873`).
 */
export function validatePlanSave(form: PlanSaveForm): PlanSaveErrors {
  const errors: PlanSaveErrors = {}
  if (!form.departurePortName.trim()) errors.departurePortName = '출발항을 입력하세요.'
  if (!form.arrivalPortName.trim()) errors.arrivalPortName = '도착항을 입력하세요.'
  if (!form.plannedDepartureAt.trim()) {
    errors.plannedDepartureAt = '출항 예정 시각을 입력하세요.'
  } else if (Number.isNaN(new Date(form.plannedDepartureAt).getTime())) {
    errors.plannedDepartureAt = '출항 예정 시각을 읽을 수 없습니다.'
  }
  return errors
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/**
 * 도착 예정 시각 = 출항 + 거리 ÷ 속력 (시간).
 *
 * 기능②의 채택이 도착 시각을 같은 식으로 채운다(`scenario_adopt.py` —
 * `planned_departure_at + duration_hours`). 도착 시각이 없으면 진행 중 항차의 시계가
 * 도착 예정일을 경계로 쓰지 못한다(`#649`). **분 단위로 자른다** — `datetime-local`이
 * 초 칸을 따로 그리지 않게(`voyageRules.fromIsoInstant`와 같은 이유).
 */
export function plannedArrivalFrom(
  departureLocal: string,
  distanceNm: number,
  speedKn: number,
): string {
  const departure = new Date(departureLocal)
  if (Number.isNaN(departure.getTime()) || !(speedKn > 0)) return ''
  const arrival = new Date(departure.getTime() + (distanceNm / speedKn) * 3_600_000)
  return (
    `${arrival.getFullYear()}-${pad(arrival.getMonth() + 1)}-${pad(arrival.getDate())}` +
    `T${pad(arrival.getHours())}:${pad(arrival.getMinutes())}`
  )
}

/** 계산 요청 + 추가 입력 → `POST /vessels/{id}/voyages` 초안 (`voyage-management`와 같은 모양). */
export function planDraftFrom(request: VoyageCiiRequest, form: PlanSaveForm): VoyageDraft {
  const departure = form.plannedDepartureAt.trim()
  return {
    voyageNo: form.voyageNo.trim(),
    departurePortName: form.departurePortName.trim(),
    arrivalPortName: form.arrivalPortName.trim(),
    plannedDistanceNm: String(request.distance_nm),
    plannedSpeedKn: String(request.speed_kn),
    plannedDepartureAt: departure,
    plannedArrivalAt: plannedArrivalFrom(departure, request.distance_nm, request.speed_kn),
    // `INCLUDE_AS_PLAN` 전환에는 기준연도가 필수다(`API_SPEC §3.5` [#150]). 계산의 연도를 쓴다.
    regulationYear: String(request.regulation_year),
    fuelUses: request.fuel_uses.map((fu) => ({
      fuelType: fu.fuel_type,
      plannedFuelTon: String(fu.fuel_ton),
    })),
  }
}

/**
 * `PLANNED` 전환에 실을 집계 정책.
 *
 * **계획 저장과 연간 반영은 별개다** — `API_SPEC §3.3` [#150]이 「연간 반영을 선택할 때만
 * `INCLUDE_AS_PLAN`을 지정한다」고 적는다. 그래서 사용자가 고르게 두고, 기본은 반영이다
 * (`PRD §5.1` 「기능① 계획 저장 → 기능③ 반영」 MUST).
 */
export function planPolicy(form: PlanSaveForm): InclusionPolicy {
  return form.includeInAnnual ? 'INCLUDE_AS_PLAN' : 'EXCLUDE'
}

/**
 * 연간 시뮬레이터로 가는 주소 — **연도를 쿼리로 싣는다** (`PRD §10.5` 「해당 선박·연도로」).
 *
 * 선박은 셸이 들고 있으므로 싣지 않는다(`#484` · `#535`). 연도는 그 화면이 쿼리를 읽어
 * 선택지에 있으면 고른다 — 없으면 그 화면의 기본값(`pickDefaultYear`)으로 떨어진다.
 */
export function annualSimulatorPath(request: VoyageCiiRequest): string {
  return `${SCREEN_BY_ID.ANNUAL_GRADE.path}?year=${request.regulation_year}`
}

/**
 * CSV 다운로드 쿼리 — **이 계산 한 건**을 서버가 만든다 (`API_SPEC §8.1` `calculation_run_id`).
 *
 * 화면에서 CSV를 만들지 않는다. 수식 주입 방어·BOM·CRLF 규칙(`TECH_SPEC §19.2`)이 서버
 * 한 곳에 있고, 두 벌이 되면 한쪽만 고쳐진다(`reports/csv_export.py`).
 */
export function csvExportQuery(response: VoyageCiiResponse): string {
  return `type=calculations&calculation_run_id=${encodeURIComponent(response.calculation_run_id)}&format=csv`
}

/** 서버가 파일 이름을 주지 않을 때의 대체 이름. */
export function csvFallbackName(response: VoyageCiiResponse): string {
  return `calculations_${response.calculation_run_id.slice(0, 8)}.csv`
}
