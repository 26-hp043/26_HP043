import { FUEL_CF } from '../voyage-cii/referenceTable'
import { findShipType } from '../vessel-registration/shipTypes'
import type { Vessel } from '../vessel-registration/types'
import type { VesselUpdateRequest } from './provider'

/**
 * 선박 수정 폼 규칙 (#510).
 *
 * 컴포넌트에서 분리한 이유는 `vessel-registration/formRules.ts`와 같다 — 저장소에
 * `@testing-library/react`·`jsdom`이 없어 **컴포넌트 안의 분기는 아무도 검사하지 않는다.**
 *
 * ## 등록 폼을 재사용하지 않은 이유
 *
 * PATCH는 POST와 **의미가 다르다.** `services/vessel.py:230` docstring이 규정한다 —
 *
 * > `None`은 "이 필드는 안 바꾼다"다 (…) **GT를 지우는 기능은 PATCH에 없다**
 *
 * 등록 폼의 `toRequest()`는 「빈 칸 = 키 생략」인데, 그것을 그대로 쓰면 사용자가 값을
 * 지웠을 때 **아무 일도 일어나지 않고 화면은 성공을 표시한다.** 그 상태를 오류가 아닌
 * **경고**로 드러내야 해서 규칙을 따로 둔다.
 *
 * ## IMO는 폼에 없다
 *
 * 서버 `VesselUpdateRequest`가 `imo_number`를 **아예 받지 않는다**
 * (`api/schemas/vessel.py:47` — `extra="forbid"`). 읽기 전용으로 보여만 준다.
 */

/** 수정 폼 상태. 전부 문자열이다 — 입력창의 값이 곧 상태다. */
export interface VesselEditState {
  name: string
  shipType: string
  grossTonnage: string
  deadweight: string
  defaultFuelType: string
  referenceSpeedKn: string
  referenceDailyFocTon: string
}

/** 오류 맵의 키. 서버 `details[0].field`와 같은 이름을 쓴다. */
export const EDIT_FIELD = {
  name: 'name',
  shipType: 'ship_type',
  grossTonnage: 'gross_tonnage',
  deadweight: 'deadweight',
  defaultFuelType: 'default_fuel_type',
  referenceSpeedKn: 'reference_speed_kn',
  referenceDailyFocTon: 'reference_daily_foc_ton',
  form: '__form__',
} as const

export type EditErrors = Record<string, string>

/** 이름 길이 상한 (VAL-001, `API_SPEC §2.3`). */
export const NAME_MAX_LENGTH = 100

/** 숫자를 입력창 문자열로. `null`은 빈 칸이다. */
function numberToInput(value: number | null): string {
  return value === null ? '' : String(value)
}

/**
 * 서버가 준 선박을 폼 상태로 옮긴다.
 *
 * **표시용 포맷(천단위 구분자)을 넣지 않는다.** 입력창의 값은 그대로 다시 파싱되므로,
 * `50,000`을 넣으면 `Number('50,000')`이 `NaN`이 되어 사용자가 건드리지도 않은 칸이
 * 오류가 된다.
 */
export function toEditState(vessel: Vessel): VesselEditState {
  return {
    name: vessel.name,
    shipType: vessel.ship_type,
    grossTonnage: numberToInput(vessel.gross_tonnage),
    deadweight: numberToInput(vessel.deadweight),
    defaultFuelType: vessel.default_fuel_type ?? '',
    referenceSpeedKn: numberToInput(vessel.reference_speed_kn),
    referenceDailyFocTon: numberToInput(vessel.reference_daily_foc_ton),
  }
}

/** 십진 문자열을 숫자로. 읽을 수 없으면 `null`. `Number('')`이 `0`인 함정을 피한다. */
function toNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

/** 선택 입력 한 칸의 검증. 비면 오류가 아니고, 값이 있으면 `> 0`이어야 한다(VAL-002). */
function checkOptionalPositive(
  raw: string,
  field: string,
  label: string,
  errors: EditErrors,
): void {
  const trimmed = raw.trim()
  if (trimmed === '') return
  const value = toNumber(trimmed)
  if (value === null) {
    errors[field] = `${label}을(를) 숫자로 입력해 주세요.`
    return
  }
  if (!(value > 0)) {
    errors[field] = `${label}은(는) 0보다 커야 합니다.`
  }
}

/**
 * 수정 폼을 검증한다. 위반을 전부 모아 반환한다.
 *
 * 등록과 달리 **선명·선종이 비어 있으면 오류**다 — PATCH에서 빈 값은 「안 바꾼다」로
 * 처리되지만, 사용자가 선명을 지우고 저장한 뒤 선명이 그대로인 것은 설명되지 않는
 * 동작이다. 지우려는 의도를 오류로 되돌려 준다.
 */
export function validateEdit(state: VesselEditState): EditErrors {
  const errors: EditErrors = {}

  const name = state.name.trim()
  if (name === '') {
    errors[EDIT_FIELD.name] = '선명을 입력해 주세요. 선명은 비울 수 없습니다.'
  } else if (name.length > NAME_MAX_LENGTH) {
    errors[EDIT_FIELD.name] = `선명은 ${NAME_MAX_LENGTH}자 이내로 입력해 주세요.`
  }

  if (state.shipType === '') {
    errors[EDIT_FIELD.shipType] = '선종을 선택해 주세요. 선종은 비울 수 없습니다.'
  } else if (findShipType(state.shipType) === undefined) {
    errors[EDIT_FIELD.shipType] = `알 수 없는 선종입니다: ${state.shipType}`
  }

  checkOptionalPositive(state.grossTonnage, EDIT_FIELD.grossTonnage, '총톤수(GT)', errors)
  checkOptionalPositive(state.deadweight, EDIT_FIELD.deadweight, '재화중량톤수(DWT)', errors)
  checkOptionalPositive(
    state.referenceSpeedKn,
    EDIT_FIELD.referenceSpeedKn,
    '기준속도',
    errors,
  )
  checkOptionalPositive(
    state.referenceDailyFocTon,
    EDIT_FIELD.referenceDailyFocTon,
    '기준 일일 연료소모량',
    errors,
  )

  if (state.defaultFuelType !== '' && !FUEL_CF[state.defaultFuelType]) {
    errors[EDIT_FIELD.defaultFuelType] = `알 수 없는 연료 종류입니다: ${state.defaultFuelType}`
  }

  return errors
}

/** 폼에서 「값을 지우려 한」 제원 칸의 한국어 라벨 목록. */
const CLEARABLE: ReadonlyArray<{ key: keyof VesselEditState; label: string }> = [
  { key: 'grossTonnage', label: '총톤수(GT)' },
  { key: 'deadweight', label: '재화중량톤수(DWT)' },
  { key: 'defaultFuelType', label: '기본 연료' },
  { key: 'referenceSpeedKn', label: '기준속도' },
  { key: 'referenceDailyFocTon', label: '기준 일일 연료소모량' },
]

/** 원본 선박에서 그 칸이 값을 갖고 있었는가. */
function hadValue(vessel: Vessel, key: keyof VesselEditState): boolean {
  switch (key) {
    case 'grossTonnage':
      return vessel.gross_tonnage !== null
    case 'deadweight':
      return vessel.deadweight !== null
    case 'defaultFuelType':
      return vessel.default_fuel_type !== null && vessel.default_fuel_type !== ''
    case 'referenceSpeedKn':
      return vessel.reference_speed_kn !== null
    case 'referenceDailyFocTon':
      return vessel.reference_daily_foc_ton !== null
    default:
      return false
  }
}

/**
 * 「지울 수 없다」를 알린다. 지우려 한 칸이 없으면 `null`.
 *
 * **오류가 아니라 경고다.** 저장은 되고 그 칸만 그대로 남는다. 오류로 만들면 다른
 * 칸의 정당한 수정까지 막힌다.
 *
 * 근거 — `services/vessel.py:230` *「`None`은 "이 필드는 안 바꾼다"다 (…) GT를 지우는
 * 기능은 PATCH에 없다」*. 서버에 그 경로가 없으므로 화면이 만들어 낼 수도 없다.
 */
export function clearAttemptNotice(vessel: Vessel, state: VesselEditState): string | null {
  const attempted = CLEARABLE.filter(
    ({ key, label: _label }) => hadValue(vessel, key) && state[key].trim() === '',
  ).map(({ label }) => label)

  if (attempted.length === 0) return null
  return (
    `${attempted.join(' · ')}을(를) 비웠지만 저장되지 않습니다. ` +
    '이 항목은 값을 바꿀 수만 있고 지울 수는 없습니다. ' +
    '값을 바꾸려면 새 값을 입력해 주세요.'
  )
}

/**
 * CII 재계산이 걸리는 변경인가.
 *
 * `services/vessel.py:255`가 DWT·GT가 **실제로 바뀌면** `mark_needs_recalc`를 부른다
 * (`PRD §8.4`, `#283`). 저장 전에 알려 주지 않으면 사용자는 이력이 「재계산 필요」로
 * 바뀐 이유를 알 수 없다.
 */
export function recalcNotice(vessel: Vessel, state: VesselEditState): string | null {
  const gt = toNumber(state.grossTonnage)
  const dwt = toNumber(state.deadweight)
  const gtChanged = gt !== null && gt !== vessel.gross_tonnage
  const dwtChanged = dwt !== null && dwt !== vessel.deadweight
  if (!gtChanged && !dwtChanged) return null
  return (
    '총톤수·재화중량톤수를 바꾸면 이 선박의 기존 계산 결과에 ' +
    '「재계산 필요」 표시가 붙습니다. 저장된 값 자체는 바뀌지 않습니다.'
  )
}

/**
 * 검증을 통과한 상태를 PATCH 본문으로 바꾼다.
 *
 * **바뀐 것만 싣는다.** 전부 실어 보내도 서버 결과는 대체로 같지만 두 가지가 달라진다 —
 *
 * 1. `ship_type`을 같은 값으로 재전송해도 서버가 `!= vessel.ship_type`으로 걸러
 *    재검증을 건너뛰므로 무해하지만, **`gross_tonnage` 재전송은 `is_cii_applicable_hint`
 *    재산정을 매번 돌린다**(`services/vessel.py:271`).
 * 2. 요청 본문이 「무엇을 바꾸려 했는가」의 기록이 된다. 전부 실으면 그 정보가 사라진다.
 *
 * 빈 칸은 키를 넣지 않는다 — 서버에서 `None`은 「안 바꾼다」이므로 결과가 같고,
 * `clearAttemptNotice()`가 그 사실을 사용자에게 이미 알린다.
 */
export function toUpdateRequest(vessel: Vessel, state: VesselEditState): VesselUpdateRequest {
  const patch: VesselUpdateRequest = {}

  const name = state.name.trim()
  if (name !== '' && name !== vessel.name) patch.name = name

  if (state.shipType !== '' && state.shipType !== vessel.ship_type) {
    patch.ship_type = state.shipType
  }

  const gt = toNumber(state.grossTonnage)
  if (gt !== null && gt !== vessel.gross_tonnage) patch.gross_tonnage = gt

  const dwt = toNumber(state.deadweight)
  if (dwt !== null && dwt !== vessel.deadweight) patch.deadweight = dwt

  const fuel = state.defaultFuelType.trim()
  if (fuel !== '' && fuel !== vessel.default_fuel_type) patch.default_fuel_type = fuel

  const speed = toNumber(state.referenceSpeedKn)
  if (speed !== null && speed !== vessel.reference_speed_kn) patch.reference_speed_kn = speed

  const foc = toNumber(state.referenceDailyFocTon)
  if (foc !== null && foc !== vessel.reference_daily_foc_ton) {
    patch.reference_daily_foc_ton = foc
  }

  return patch
}

/** 보낼 것이 하나도 없는가. 「저장」을 눌러도 요청을 만들지 않기 위해 쓴다. */
export function isEmptyPatch(patch: VesselUpdateRequest): boolean {
  return Object.keys(patch).length === 0
}
