import { FUEL_CF } from '../voyage-cii/referenceTable'
import { VesselRegistrationError } from './provider'
import { capacityAxisOf, findShipType } from './shipTypes'
import type { VesselCreateRequest } from './types'

/**
 * 선박 등록 폼의 상태·검증·요청 변환 (#441).
 *
 * **컴포넌트에서 분리한 순수 함수 모듈이다.** 이유는 기능①(`voyage-cii/formRules.ts`)과
 * 같다 — 경계 조건(`> 0`인지 `>= 0`인지, 7자리인지 7자리 이상인지)을 화면 조작으로는
 * 정확히 찌르기 어렵다. 함수를 직접 부르면 경계값 자체를 인자로 넣을 수 있다.
 *
 * 저장소에 `@testing-library/react`·`jsdom`이 없고, 이 이슈로 들이지 않는다.
 *
 * ## 숫자 필드도 문자열로 들고 있다
 *
 * `<input type="number">`의 `value`는 문자열이고 `-`·`1.`처럼 숫자로 변환되지 않는
 * 중간 상태가 있다. 상태를 `number`로 두면 지우는 동안 `NaN` 오류가 깜빡인다.
 * **변환은 제출 시점에 한 번만** 한다.
 *
 * ## 제원을 필수로 막지 않는다
 *
 * `PRD §20 O-11`이 「IMO 조회 실패 시 수동 입력 허용」으로 이 경로를 열었고
 * `vessel.deadweight`는 nullable이다(`DB_SCHEMA §2.1`). 폼이 제원을 필수로 만들면
 * **명세가 열어 둔 등록을 화면이 막는다.**
 *
 * 대신 `specGapNotice()`가 「등록은 되지만 CII는 계산되지 않는다」를 알린다 — `#419`가
 * 선대 요약에 `unavailable_reason=MISSING_SPEC`을 넣은 것과 같은 말을 등록 시점에 한다.
 */

/** 폼 상태. 전부 문자열이다(위 docstring 참조). */
export interface VesselFormState {
  imoNumber: string
  name: string
  shipType: string
  grossTonnage: string
  deadweight: string
  defaultFuelType: string
  referenceSpeedKn: string
  referenceDailyFocTon: string
}

/**
 * 필드별 오류 메시지.
 *
 * 키는 **요청 본문 기준 경로**다. 서버의 `details[0].field`가 그 형태로 오므로
 * (`api/error_handlers.py _field_path()`) 화면 검증과 서버 오류를 한 맵에 병합한다.
 */
export type FormErrors = Record<string, string>

/** 요청 본문 기준 필드 경로. 입력창과 1:1로 대응한다. */
export const FIELD = {
  imoNumber: 'imo_number',
  name: 'name',
  shipType: 'ship_type',
  grossTonnage: 'gross_tonnage',
  deadweight: 'deadweight',
  defaultFuelType: 'default_fuel_type',
  referenceSpeedKn: 'reference_speed_kn',
  referenceDailyFocTon: 'reference_daily_foc_ton',
  /** 어느 입력창에도 붙지 않는 오류. 폼 상단에 표시한다. */
  form: '__form__',
} as const

/** 이름 길이 상한 (VAL-001, `API_SPEC §2.3`). */
export const NAME_MAX_LENGTH = 100

/** IMO 번호 형식 (VAL-003). 서버 Pydantic 패턴·DB `chk_imo_format`과 같은 규칙이다. */
const IMO_PATTERN = /^\d{7}$/

/**
 * 초기 폼 상태. **전부 빈 문자열이다.**
 *
 * 선종에 기본값을 넣지 않는다 — 13종 중 하나가 미리 선택돼 있으면 사용자가 고른 것과
 * 기본값을 구분할 수 없고, 등록은 되돌리기 어려운 조작이다.
 */
export function initialFormState(): VesselFormState {
  return {
    imoNumber: '',
    name: '',
    shipType: '',
    grossTonnage: '',
    deadweight: '',
    defaultFuelType: '',
    referenceSpeedKn: '',
    referenceDailyFocTon: '',
  }
}

/** 연료 종류 선택지. `FUEL_CF` 8종을 순회한다 — 화면에 코드를 적지 않는다. */
export function selectableFuels(): Array<{ code: string; displayName: string }> {
  return Object.entries(FUEL_CF).map(([code, { displayName }]) => ({ code, displayName }))
}

/**
 * 십진 문자열을 숫자로. 숫자로 읽을 수 없으면 `null`.
 *
 * `Number('')`이 `0`이라 빈 칸이 「0 입력」으로 통과한다. 선택 입력에서는 그 차이가
 * 특히 중요하다 — 빈 칸은 「모른다」이고 `0`은 **VAL-002 위반**이다.
 */
function toNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

/** 선택 입력 한 칸의 검증. 비어 있으면 오류가 아니고, 값이 있으면 `> 0`이어야 한다. */
function checkOptionalPositive(
  raw: string,
  field: string,
  label: string,
  errors: FormErrors,
): void {
  const trimmed = raw.trim()
  if (trimmed === '') return
  const value = toNumber(trimmed)
  if (value === null) {
    errors[field] = `${label}을(를) 숫자로 입력해 주세요.`
    return
  }
  // VAL-002 — 서버 스키마도 `gt=0`이다.
  if (!(value > 0)) {
    errors[field] = `${label}은(는) 0보다 커야 합니다.`
  }
}

/**
 * 폼 전체를 검증한다. **위반을 전부 모아 반환한다.**
 *
 * 서버는 첫 오류를 `message`로 쓰고 나머지는 `details`에 담는데, 화면은 필드마다
 * 붙여야 하므로 전 필드를 동시에 본다. 규칙 출처는 `API_SPEC §2.3` 검증 규칙 표다.
 */
export function validateForm(state: VesselFormState): FormErrors {
  const errors: FormErrors = {}

  const imo = state.imoNumber.trim()
  if (imo === '') {
    errors[FIELD.imoNumber] = 'IMO 번호를 입력해 주세요.'
  } else if (!IMO_PATTERN.test(imo)) {
    // VAL-003
    errors[FIELD.imoNumber] = 'IMO 번호는 숫자 7자리입니다.'
  }

  const name = state.name.trim()
  if (name === '') {
    errors[FIELD.name] = '선명을 입력해 주세요.'
  } else if (name.length > NAME_MAX_LENGTH) {
    // VAL-001
    errors[FIELD.name] = `선명은 ${NAME_MAX_LENGTH}자 이내로 입력해 주세요.`
  }

  if (state.shipType === '') {
    errors[FIELD.shipType] = '선종을 선택해 주세요.'
  } else if (findShipType(state.shipType) === undefined) {
    // VAL-004의 화면 쪽 방어선. 셀렉트로는 도달하지 않으나 오래된 상태가 남았을 때
    // 서버 422를 기다리지 않고 여기서 잡는다.
    errors[FIELD.shipType] = `알 수 없는 선종입니다: ${state.shipType}`
  }

  checkOptionalPositive(state.grossTonnage, FIELD.grossTonnage, '총톤수(GT)', errors)
  checkOptionalPositive(state.deadweight, FIELD.deadweight, '재화중량톤수(DWT)', errors)
  checkOptionalPositive(state.referenceSpeedKn, FIELD.referenceSpeedKn, '기준속도', errors)
  checkOptionalPositive(
    state.referenceDailyFocTon,
    FIELD.referenceDailyFocTon,
    '기준 일일 연료소모량',
    errors,
  )

  if (state.defaultFuelType !== '' && !FUEL_CF[state.defaultFuelType]) {
    errors[FIELD.defaultFuelType] = `알 수 없는 연료 종류입니다: ${state.defaultFuelType}`
  }

  return errors
}

/**
 * 제원이 비어 CII를 계산할 수 없는 상태를 알린다. 문제가 없으면 `null`.
 *
 * **오류가 아니다.** 등록은 되며(`PRD §20 O-11`), 계산만 되지 않는다. 그래서 반환값을
 * `FormErrors`에 넣지 않는다 — 오류 맵에 들어가면 제출이 막히거나 오류처럼 보인다.
 *
 * ## 어느 축을 보는지가 선종에 달려 있다
 *
 * DWT 기반 선종에 GT만 넣어도 CII는 계산되지 않는다(`PRD §3.3.3`). 「DWT 또는 GT
 * 하나라도 있으면 된다」로 안내하면 **틀린 안내**가 된다 — 축은 `shipTypes.ts`가 갖고,
 * 그 대응은 `shipTypes.sync.test.ts`가 `capacity.py`에 대해 잠근다.
 *
 * 선종을 아직 고르지 않았으면 안내하지 않는다 — 무엇이 필요한지 아직 정해지지 않았다.
 */
export function specGapNotice(state: VesselFormState): string | null {
  const axis = capacityAxisOf(state.shipType)
  if (axis === null) return null

  const raw = axis === 'DWT' ? state.deadweight : state.grossTonnage
  if (raw.trim() !== '') return null

  const label = axis === 'DWT' ? '재화중량톤수(DWT)' : '총톤수(GT)'
  return (
    `${label}을 비워 두면 등록은 되지만 이 선박의 CII를 계산할 수 없습니다. ` +
    '선박 정보에서 나중에 채울 수 있습니다.'
  )
}

/**
 * 검증을 통과한 상태를 요청 본문으로 바꾼다.
 *
 * **빈 선택 입력은 키를 넣지 않는다.** `null`로 보내도 서버 결과는 같지만
 * (`VesselCreateRequest`의 기본값이 `None`), 요청 본문에 `null`이 늘어서면 「지운다」와
 * 「안 보낸다」의 구분이 흐려진다 — 그 구분이 실제로 다른 곳이 수정(`API_SPEC §2.4`
 * PATCH)이므로, 등록에서부터 같은 규칙으로 둔다.
 *
 * @throws 검증되지 않은 상태로 부르면 `Error`. 항상 `validateForm()` 뒤에 부른다.
 */
export function toRequest(state: VesselFormState): VesselCreateRequest {
  const imo = state.imoNumber.trim()
  const name = state.name.trim()
  if (imo === '' || name === '' || state.shipType === '') {
    throw new Error('검증되지 않은 폼 상태입니다. validateForm()을 먼저 호출하십시오.')
  }

  const request: VesselCreateRequest = {
    imo_number: imo,
    name,
    ship_type: state.shipType,
  }

  // 키를 문자열로 돌리지 않고 하나씩 적는다 — 동적 대입은 타입을 잃고,
  // 그러면 요청 본문에 없는 필드를 넣어도 컴파일이 통과한다(`extra="forbid"` 422).
  const grossTonnage = toNumber(state.grossTonnage)
  if (grossTonnage !== null) request.gross_tonnage = grossTonnage

  const deadweight = toNumber(state.deadweight)
  if (deadweight !== null) request.deadweight = deadweight

  const referenceSpeedKn = toNumber(state.referenceSpeedKn)
  if (referenceSpeedKn !== null) request.reference_speed_kn = referenceSpeedKn

  const referenceDailyFocTon = toNumber(state.referenceDailyFocTon)
  if (referenceDailyFocTon !== null) request.reference_daily_foc_ton = referenceDailyFocTon

  if (state.defaultFuelType !== '') {
    request.default_fuel_type = state.defaultFuelType
  }

  return request
}

/** 화면에 입력창이 있는 필드 경로. 여기 없는 경로의 오류는 폼 상단으로 보낸다. */
const FIELD_PATHS: ReadonlySet<string> = new Set([
  FIELD.imoNumber,
  FIELD.name,
  FIELD.shipType,
  FIELD.grossTonnage,
  FIELD.deadweight,
  FIELD.defaultFuelType,
  FIELD.referenceSpeedKn,
  FIELD.referenceDailyFocTon,
])

/**
 * provider 오류를 필드별 메시지 맵으로 바꾼다.
 *
 * ## 중복 IMO(409)를 IMO 입력창에 붙인다
 *
 * 서버 `ConflictError`는 `field`를 담지 않는다(`errors.py:119`) — 리소스 단위 충돌이라
 * 필드 개념이 없기 때문이다. 그러나 사용자가 고칠 수 있는 유일한 값은 IMO 번호이므로
 * 화면은 그 입력창에 붙인다. **폼 상단 배너로 두면 「어디를 고쳐야 하는지」가 사라진다.**
 *
 * `VesselRegistrationError`가 아닌 오류도 삼키지 않는다 — 화면이 조용히 아무 반응도
 * 하지 않는 것이 가장 나쁘다.
 */
export function toFormErrors(error: unknown): FormErrors {
  if (error instanceof VesselRegistrationError) {
    if (error.code === 'CONFLICT') {
      return { [FIELD.imoNumber]: error.message }
    }
    if (error.field && FIELD_PATHS.has(error.field)) {
      return { [error.field]: error.message }
    }
    return { [FIELD.form]: error.message }
  }
  return {
    [FIELD.form]:
      error instanceof Error ? error.message : '등록 중 알 수 없는 오류가 발생했습니다.',
  }
}
