import type {
  ActualsDraft,
  InclusionPolicy,
  ManagedVoyage,
  VoyageDraft,
  VoyageStatus,
} from './types'

/**
 * 항차 상태·전환·실적 입력 규칙 — `API_SPEC §3.5`·`§3.6` (`#610`).
 *
 * ## 서버가 정본이다. 여기는 사본이다
 *
 * 전환 허용표는 `services/voyage.py`의 `_TRANSITIONS`가 소유한다. 화면이 사본을
 * 두는 이유는 **갈 수 없는 곳을 버튼으로 내지 않기 위해서**다. 어긋나면 서버가
 * 422로 막으므로 안전 쪽으로 틀리지만, 어긋난 채로 두면 사용자가 눌러 보고서야
 * 안 된다는 것을 안다.
 *
 * ## 화면이 미리 막는 것과 서버에 맡기는 것
 *
 * **미리 막는 것** — 상태만 보면 알 수 있는 것(전환 가능 여부, 실적 폼 노출).
 * **서버에 맡기는 것** — 데이터를 봐야 아는 것(중복 연료, 겹침). 서버 문구가
 * 원인을 더 정확히 안다(`not-underway/apiProvider.ts`와 같은 규율).
 *
 * 다만 **전환 가드 두 개는 예외로 미리 본다** — 실적 없이 `COMPLETED`로 가려는 것과
 * 기준연도 없이 연간 반영을 켜려는 것이다. 둘 다 화면이 이미 값을 쥐고 있고,
 * 눌러서 422를 받는 것보다 버튼 옆에 사유를 적어 두는 편이 낫다.
 */

/** `services/voyage.py` `_TRANSITIONS`의 사본. */
const TRANSITIONS: Record<VoyageStatus, readonly VoyageStatus[]> = {
  DRAFT: ['PLANNED', 'CANCELLED'],
  PLANNED: ['IN_PROGRESS', 'CANCELLED'],
  IN_PROGRESS: ['COMPLETED', 'CANCELLED'],
  COMPLETED: ['CONFIRMED'],
  CONFIRMED: ['COMPLETED', 'ARCHIVED'],
  CANCELLED: [],
  ARCHIVED: [],
}

/** `API_SPEC §3.5` status × annual_inclusion_policy 허용 조합. */
const POLICY_BY_STATUS: Record<VoyageStatus, readonly InclusionPolicy[]> = {
  DRAFT: ['EXCLUDE'],
  PLANNED: ['EXCLUDE', 'INCLUDE_AS_PLAN'],
  IN_PROGRESS: ['EXCLUDE', 'INCLUDE_AS_PLAN'],
  COMPLETED: ['EXCLUDE', 'INCLUDE_AS_ACTUAL'],
  CONFIRMED: ['EXCLUDE', 'INCLUDE_AS_ACTUAL'],
  CANCELLED: ['EXCLUDE'],
  ARCHIVED: ['EXCLUDE'],
}

/** 화면에 쓰는 상태 이름. API enum을 그대로 내보이지 않는다(`#529`와 같은 부류). */
export const STATUS_LABELS: Record<VoyageStatus, string> = {
  DRAFT: '작성 중',
  PLANNED: '계획 확정',
  IN_PROGRESS: '항해 중',
  COMPLETED: '항해 완료',
  CONFIRMED: '실적 확정',
  CANCELLED: '취소됨',
  ARCHIVED: '보관됨',
}

export const POLICY_LABELS: Record<InclusionPolicy, string> = {
  EXCLUDE: '연간 반영 안 함',
  INCLUDE_AS_PLAN: '연간 반영 — 계획',
  INCLUDE_AS_ACTUAL: '연간 반영 — 실적',
}

/** 그 상태에서 갈 수 있는 곳. 순서는 표시 순서다. */
export function nextStatuses(status: VoyageStatus): readonly VoyageStatus[] {
  return TRANSITIONS[status] ?? []
}

/**
 * 실적 폼을 열 수 있는가 — `API_SPEC §3.6` 상태별 허용.
 *
 * `DRAFT`·`PLANNED`는 **아직 뜨지 않은 항차**라 실적이 있을 수 없다. `CONFIRMED`는
 * 연말 DCS 보고의 근거라 조용히 갈아 끼우지 않는다. 폼을 비활성으로 두지 않고
 * **아예 내지 않는다** — 열려 있는데 저장이 거부되면 그게 더 나쁘다.
 */
export function canEnterActuals(status: VoyageStatus): boolean {
  return status === 'IN_PROGRESS' || status === 'COMPLETED'
}

/**
 * 전환 요청에 `annual_inclusion_policy`를 실어야 하는가.
 *
 * ## 여기가 데모 동선이 끊기는 자리다
 *
 * `§3.5` — 생략하면 **현행 값을 유지**한다. 그런데 목표 상태가 현행 policy를
 * 허용하지 않으면 서버는 **자동 보정하지 않고 422로 거부**한다.
 *
 * `INCLUDE_AS_PLAN`으로 계획을 잡아 둔 항차를 `IN_PROGRESS → COMPLETED`로 옮기면
 * 정확히 그 경우다 — `COMPLETED`는 `INCLUDE_AS_ACTUAL`만 받는다. 화면이 아무것도
 * 안 보내면 **마지막 한 걸음에서 막힌다.**
 *
 * @returns 보내야 할 policy. `null`이면 생략(현행 유지)이 맞다.
 */
export function policyForTransition(
  current: InclusionPolicy,
  to: VoyageStatus,
): InclusionPolicy | null {
  const allowed = POLICY_BY_STATUS[to]
  if (allowed.includes(current)) return null

  // 계획으로 잡아 둔 것은 실적으로 이어 간다. 그 외에는 반영을 끈다.
  if (current === 'INCLUDE_AS_PLAN' && allowed.includes('INCLUDE_AS_ACTUAL')) {
    return 'INCLUDE_AS_ACTUAL'
  }
  return 'EXCLUDE'
}

/**
 * 전환을 막는 사유 — 없으면 `null`.
 *
 * `§3.5` 가드 중 **화면이 값을 이미 쥐고 있는 두 가지**만 본다.
 */
export function transitionBlocker(
  voyage: ManagedVoyage,
  to: VoyageStatus,
): string | null {
  if (!nextStatuses(voyage.status).includes(to)) {
    return `${STATUS_LABELS[voyage.status]}에서는 갈 수 없는 상태입니다.`
  }

  // IN_PROGRESS → COMPLETED: 최소 1개 actual_fuel_ton > 0 (ORACLE-C-4)
  if (to === 'COMPLETED' && voyage.status === 'IN_PROGRESS') {
    const hasActual = voyage.fuelUses.some(
      (use) => use.actualFuelTon !== null && use.actualFuelTon > 0,
    )
    if (!hasActual) return '실적 연료를 먼저 입력해야 항해를 완료할 수 있습니다.'
  }

  // policy를 켜는 전환은 regulation_year가 있어야 한다 (#150)
  const policy = policyForTransition(voyage.inclusionPolicy, to)
  const effective = policy ?? voyage.inclusionPolicy
  if (effective !== 'EXCLUDE' && voyage.regulationYear === null) {
    return '연간 반영을 하려면 기준연도가 필요합니다.'
  }

  return null
}

/** 숫자 입력 한 칸을 읽는다. 빈 문자열은 `null`(미입력)이다. */
function readNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : Number.NaN
}

export type FieldErrors = Record<string, string>

export function hasErrors(errors: FieldErrors): boolean {
  return Object.keys(errors).length > 0
}

/**
 * 생성 폼 검증 — `API_SPEC §3.3`.
 *
 * 서버가 거부할 것을 미리 잡는 것이 아니라 **사용자가 다시 입력하지 않게** 하는
 * 것이 목적이다. 서버만 아는 것(`VAL-005` 기준연도 실재 여부)은 서버에 맡긴다.
 */
export function validateDraft(draft: VoyageDraft): FieldErrors {
  const errors: FieldErrors = {}

  if (draft.voyageNo.trim() === '') errors.voyageNo = '항차 번호를 입력해 주세요.'
  if (draft.departurePortName.trim() === '') errors.departurePortName = '출발항을 입력해 주세요.'
  if (draft.arrivalPortName.trim() === '') errors.arrivalPortName = '도착항을 입력해 주세요.'

  const distance = readNumber(draft.plannedDistanceNm)
  if (distance === null) errors.plannedDistanceNm = '계획 거리를 입력해 주세요.'
  else if (Number.isNaN(distance) || distance <= 0) {
    errors.plannedDistanceNm = '계획 거리는 0보다 커야 합니다.'
  }

  const speed = readNumber(draft.plannedSpeedKn)
  if (speed === null) errors.plannedSpeedKn = '계획 속력을 입력해 주세요.'
  else if (Number.isNaN(speed) || speed < 1) {
    // 서버가 실적 속력에 두는 하한과 같다 (§3.6 VALIDATION_ERROR).
    errors.plannedSpeedKn = '계획 속력은 1.0 kn 이상이어야 합니다.'
  }

  const fuel = readNumber(draft.plannedFuelTon)
  if (fuel === null) errors.plannedFuelTon = '계획 연료를 입력해 주세요.'
  else if (Number.isNaN(fuel) || fuel <= 0) {
    errors.plannedFuelTon = '계획 연료는 0보다 커야 합니다.'
  }

  if (draft.fuelType.trim() === '') errors.fuelType = '연료 종류를 선택해 주세요.'

  const year = readNumber(draft.regulationYear)
  if (year !== null && (Number.isNaN(year) || !Number.isInteger(year))) {
    errors.regulationYear = '기준연도는 연도 네 자리입니다.'
  }

  return errors
}

/**
 * 실적 폼 검증 — `API_SPEC §3.6`.
 *
 * **모든 항목이 선택이다.** 생략은 「변경 없음」이고, 실거리만 먼저 알고 연료가
 * 나중에 오는 경우가 실제로 있다. 그래서 「비어 있음」은 오류가 아니다 —
 * 값이 들어왔을 때 그 값이 서버 제약을 어기는지만 본다.
 */
export function validateActuals(draft: ActualsDraft): FieldErrors {
  const errors: FieldErrors = {}

  const distance = readNumber(draft.actualDistanceNm)
  if (distance !== null && (Number.isNaN(distance) || distance <= 0)) {
    errors.actualDistanceNm = '실제 거리는 0보다 커야 합니다.'
  }

  const speed = readNumber(draft.actualAvgSpeedKn)
  if (speed !== null && (Number.isNaN(speed) || speed < 1)) {
    errors.actualAvgSpeedKn = '실제 평균 속력은 1.0 kn 이상이어야 합니다.'
  }

  for (const [fuelType, raw] of Object.entries(draft.actualFuelTon)) {
    const ton = readNumber(raw)
    if (ton !== null && (Number.isNaN(ton) || ton <= 0)) {
      errors[`actualFuelTon.${fuelType}`] = '실적 연료는 0보다 커야 합니다.'
    }
  }

  return errors
}

/** 실적 폼에서 실제로 보낼 것만 추린다. 빈 칸은 키 자체를 넣지 않는다. */
export function actualsPayload(draft: ActualsDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {}

  const distance = readNumber(draft.actualDistanceNm)
  if (distance !== null && !Number.isNaN(distance)) payload.actual_distance_nm = distance

  const speed = readNumber(draft.actualAvgSpeedKn)
  if (speed !== null && !Number.isNaN(speed)) payload.actual_avg_speed_kn = speed

  const fuelUses = Object.entries(draft.actualFuelTon)
    .map(([fuelType, raw]) => ({ fuelType, ton: readNumber(raw) }))
    .filter((row) => row.ton !== null && !Number.isNaN(row.ton))
    .map((row) => ({
      fuel_type: row.fuelType,
      actual_fuel_ton: row.ton,
      source: 'USER_INPUT',
    }))

  if (fuelUses.length > 0) payload.fuel_uses = fuelUses

  return payload
}
