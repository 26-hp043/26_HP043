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
/**
 * 항차 시각의 화면 ↔ 서버 다리 (`#873`).
 *
 * ## 왜 다리가 필요한가
 *
 * 화면 입력은 `<input type="datetime-local">`이라 값이 **표준시각 정보가 없는
 * 벽시계 문자열**(`2026-06-01T09:00`)이고, 서버는 `datetime`을 받아 UTC로 저장한다.
 * 그대로 보내면 「9시」가 어느 지역의 9시인지 서버가 알 수 없다.
 *
 * ## 브라우저의 표준시각으로 읽는다
 *
 * `new Date('2026-06-01T09:00')`은 **지역 시각**으로 해석된다(뒤에 `Z`가 없을 때의
 * ECMAScript 규정). 사용자가 「9시에 출항」이라고 적을 때 뜻하는 것이 자기 지역의
 * 9시이므로 그 해석이 맞다. UTC로 고정해 읽으면 한국 사용자의 입력이 9시간 어긋난다.
 */
export function toIsoInstant(local: string): string | null {
  const trimmed = local.trim()
  if (trimmed === '') return null
  const parsed = new Date(trimmed)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

/**
 * 서버가 준 ISO 문자열을 `datetime-local` 값으로 되돌린다 (`#873`).
 *
 * **분까지만 남긴다.** `datetime-local`은 초를 포함한 값도 받지만, 넣으면 브라우저가
 * 초 칸을 하나 더 그려 폼의 칸 모양이 항차마다 달라진다.
 *
 * 읽을 수 없으면 빈 문자열이다 — 폼이 「값 없음」으로 시작하는 것이 **틀린 시각을
 * 보여 주는 것보다 낫다.**
 */
export function toLocalInput(iso: string | null): string {
  if (iso === null || iso.trim() === '') return ''
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}` +
    `T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
  )
}

/**
 * 출항·도착 시각 한 쌍을 본다 (`#873`).
 *
 * 읽을 수 없는 값과 **도착이 출항보다 빠른 것**을 잡는다. 뒤쪽은 서버가 막지 않는데,
 * 그 상태로 진행 중이 되면 시뮬레이션 시계가 경과 시간을 음수로 계산해 **0으로
 * 잘린다**(`services/simulation_clock.py`) — 값이 틀리는 것이 아니라 조용히 0이
 * 되므로 사용자는 원인을 알 수 없다.
 */
function checkInstantPair(
  departure: string,
  arrival: string,
  keys: { departure: string; arrival: string },
  errors: FieldErrors,
): void {
  const from = departure.trim() === '' ? null : toIsoInstant(departure)
  const to = arrival.trim() === '' ? null : toIsoInstant(arrival)

  if (departure.trim() !== '' && from === null) {
    errors[keys.departure] = '출항 시각을 날짜와 시각으로 입력해 주세요.'
  }
  if (arrival.trim() !== '' && to === null) {
    errors[keys.arrival] = '도착 시각을 날짜와 시각으로 입력해 주세요.'
  }
  if (from !== null && to !== null && to <= from) {
    errors[keys.arrival] = '도착 시각은 출항 시각보다 뒤여야 합니다.'
  }
}

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

  /*
   * 연료는 여러 줄이다 (`#636`).
   *
   * **줄마다 오류 키를 분리한다** — `plannedFuelTon.0`처럼. 한 키에 몰면 세 줄 중
   * 어느 줄이 틀렸는지 화면이 가리키지 못하고, 사용자는 전부 다시 본다.
   */
  if (draft.fuelUses.length === 0) {
    // 서버가 `min_length=1`을 요구한다(`§3.3`). 저장 단계에서야 거부되면
    // 사용자는 무엇을 지웠는지 이미 잊었다.
    errors.fuelUses = '연료를 한 종 이상 입력해 주세요.'
  }

  draft.fuelUses.forEach((fu, index) => {
    const fuel = readNumber(fu.plannedFuelTon)
    if (fuel === null) errors[`plannedFuelTon.${index}`] = '계획 연료를 입력해 주세요.'
    else if (Number.isNaN(fuel) || fuel <= 0) {
      errors[`plannedFuelTon.${index}`] = '계획 연료는 0보다 커야 합니다.'
    }
    if (fu.fuelType.trim() === '') {
      errors[`fuelType.${index}`] = '연료 종류를 선택해 주세요.'
    }
  })

  /*
   * 같은 유종이 두 번 있으면 **서버가 422로 거부한다**(`services/voyage.py` ·
   * `idx_fuel_use_unique`). 화면이 먼저 잡는 이유는 판정을 흉내 내려는 것이 아니라
   * **어느 줄이 겹쳤는지 화면만 알기 때문**이다 — 서버 오류에는 줄 번호가 없다.
   */
  const seen = new Map<string, number>()
  draft.fuelUses.forEach((fu, index) => {
    const code = fu.fuelType.trim()
    if (code === '') return
    if (seen.has(code)) {
      errors[`fuelType.${index}`] = '같은 연료 종류가 두 번 있습니다. 한 줄로 합쳐 주세요.'
      return
    }
    seen.set(code, index)
  })

  const year = readNumber(draft.regulationYear)
  if (year !== null && (Number.isNaN(year) || !Number.isInteger(year))) {
    errors.regulationYear = '기준연도는 연도 네 자리입니다.'
  }

  /*
   * 시각 두 칸은 **필수가 아니다** (`#873`). `API_SPEC §3.3`이 optional로 규정하고,
   * 화면이 서버보다 엄격해지면 CSV·API로 만든 항차와 화면으로 만든 항차의 계약이
   * 갈린다. 비어 있는 것은 오류가 아니고, **들어온 값이 앞뒤가 맞는지만** 본다.
   *
   * 대신 폼이 「없으면 누적에 0으로 기여한다」를 안내 문구로 말한다 — 규칙을 바꾸지
   * 않고 결과를 알린다.
   */
  checkInstantPair(
    draft.plannedDepartureAt,
    draft.plannedArrivalAt,
    { departure: 'plannedDepartureAt', arrival: 'plannedArrivalAt' },
    errors,
  )

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

  checkInstantPair(
    draft.actualDepartureAt,
    draft.actualArrivalAt,
    { departure: 'actualDepartureAt', arrival: 'actualArrivalAt' },
    errors,
  )

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

  /*
   * 시각 두 칸 (`#873`). **빈 칸은 키 자체를 넣지 않는다** — `§3.6`에서 생략은
   * 「변경 없음」이고 명시적 `null`은 「지움」이라, 빈 칸을 `null`로 보내면 이미
   * 넣어 둔 시각이 지워진다.
   */
  const departure = toIsoInstant(draft.actualDepartureAt)
  if (departure !== null) payload.actual_departure_at = departure

  const arrival = toIsoInstant(draft.actualArrivalAt)
  if (arrival !== null) payload.actual_arrival_at = arrival

  return payload
}
