import { withEunNeun } from '../../display/josa'
import { isKnownFuel, type FuelOption } from '../parameters/fuelCatalog'
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
  blockCoefficient: string
  callSign: string
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
  blockCoefficient: 'block_coefficient',
  callSign: 'call_sign',
  /** 어느 입력창에도 붙지 않는 오류. 폼 상단에 표시한다. */
  form: '__form__',
} as const

/**
 * 접는 제원 묶음의 칸들 (#1783).
 *
 * `FIELD`의 순서를 따로 적는 것이 아니라 **그 묶음에 실제로 그려진 칸**을 적는다 —
 * 접힌 겉이 「몇 칸 중 몇 칸을 채웠나」를 말하려면 분모가 화면과 같아야 한다.
 *
 * 키는 **폼 상태의 이름**이다(요청 본문 이름이 아니다). 오류는 `FIELD[키]`로 찾는다 —
 * `FIELD`의 키가 곧 폼 상태의 키이고 값이 요청 본문 경로다.
 */
export const SPEC_FIELDS = [
  'deadweight',
  'grossTonnage',
  'referenceSpeedKn',
  'referenceDailyFocTon',
  'blockCoefficient',
  'callSign',
  'defaultFuelType',
] as const satisfies readonly (keyof VesselFormState)[]

/**
 * 비워 두면 무엇이 막히는가 — 접힌 겉에 적는 한 줄 (#1783).
 *
 * ⚠️ **사실관계는 `vessel-management/listRules.blockedReasons`가 정본이고, 그 문장은
 * `#630`이 실측으로 고친 것이다** — 종전에는 「연간 시뮬레이션이 실패합니다」로 적었는데
 * 실제로는 200으로 돌고 감속 민감도만 조용히 0이 된다. 여기서 다시 적는 것은 등록
 * 시점에는 아직 선박이 없어 그 함수를 부를 대상이 없기 때문이고, **묶음을 통째로
 * 비웠을 때**(= 기준속도도 비었을 때)의 결과를 적는다.
 *
 * 접어 두고 이 줄이 없으면, 사용자는 **나중에 선박 관리에서** 같은 경고를 만난다.
 */
export const SPEC_SKIP_CONSEQUENCE =
  '비워 두어도 등록됩니다 — 대신 그 선박은 CII 등급을 산출할 수 없고, 항로 비교가 ' +
  '실패하며, 연간 시뮬레이션의 감속 민감도가 나오지 않습니다. 선박 관리에서 나중에 ' +
  '채울 수 있습니다.'

/** 접힌 겉에 적는 이름 — 채운 칸 수를 함께 적는다 (`#1417` 「고급 설정」과 같은 꼴). */
export function specSummary(filled: number, total: number): string {
  return filled === 0
    ? `제원 · 선택 입력 ${total}칸`
    : `제원 · 선택 입력 ${total}칸 중 ${filled}칸 채움`
}

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
    blockCoefficient: '',
    callSign: '',
  }
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

/**
 * DB 컬럼 `NUMERIC(precision, scale)`이 **담을 수 있는** 양수 범위 (`#860`).
 *
 * 서버 스키마(`api/schemas/vessel.py`의 `_storable`)와 **같은 식**이다. 종전에는 화면도
 * 서버도 `> 0`만 봐서 `1e-7`이 통과했고, DB가 `0.00`으로 반올림한 뒤 CHECK 제약에 걸려
 * **500**이 났다. 한쪽만 막으면 다른 쪽이 통과시키므로 두 층이 같은 경계를 쓴다.
 *
 * 도메인 하한(「DWT 최소 100톤」 등)이 아니라 **저장 형식**에서 나온 경계다.
 */
export function storableRange(precision: number, scale: number): { min: number; max: number } {
  const min = 10 ** -scale
  return { min, max: 10 ** (precision - scale) - min }
}

/**
 * 속력의 물리 상한(kn) — `PRD §9.1` VAL-009 (#1269). 서버 `api/schemas/bounds.py`의
 * `MAX_SPEED_KN`·DB 트리거(`062`)와 같은 값이다.
 *
 * 저장 형식의 상한(9,999.99)은 「운항할 수 없는 값」을 하나도 막지 못했다 — `120`kn이
 * 도착 예정 시각과 연간 시뮬레이션까지 흘러갔다. 60은 현역 페리 세계 최고속(58.1kn)을
 * 막지 않는 가장 좁은 값이다. 항차·실시간 CII·시나리오 비교 화면도 이 값을 쓴다.
 */
export const MAX_SPEED_KN = 60

/** 필드별 저장 범위 — `db/models/vessel.py`의 `Numeric(...)`과 같다. */
export const STORABLE = {
  tonnage: storableRange(12, 2),
  // 하한은 저장 형식(0.01 · VAL-002), 상한은 VAL-009의 물리 상한이다 (#1269).
  speed: { min: storableRange(6, 2).min, max: MAX_SPEED_KN },
  dailyFoc: storableRange(8, 2),
  // #966 — 방형계수는 저장 범위 위에 물리 범위(1 이하)가 더 좁힌다. `cbRange`가 그 상한을
  // 담는다 — 서버 스키마(_CB)와 같은 값이다.
  cb: storableRange(4, 3),
} as const

/** 방형계수의 물리 상한 — 체적 비율은 1을 넘지 않는다 (#966). */
export const CB_MAX = 1

/**
 * 호출부호(call sign)의 모양 (#1197) — ITU 전파규칙 `RR No. 19.55`의 선박국 네 형식은 전부
 * **영문 대문자·숫자 4~7자**에 든다. 서버 스키마(`api/schemas/vessel.py` `_CALL_SIGN`)·DB
 * 트리거(마이그레이션 058)와 **같은 식**이다 — 한쪽만 다르면 화면이 통과시킨 값을 서버가
 * 422로 돌려보내거나 그 반대가 된다.
 */
const CALL_SIGN_PATTERN = /^[A-Z0-9]{4,7}$/

/**
 * 호출부호를 서버와 **같은 모양**으로 접는다 — 앞뒤 공백을 지우고 대문자로. 비면 `null`.
 *
 * 서버도 같은 정규화를 하므로 화면이 안 해도 저장 결과는 같다. 그래도 여기서 하는 이유는
 * 검증 문구가 **접은 값** 기준이어야 하기 때문이다 — `hlxq`를 「대문자여야 한다」로 막으면
 * 서버가 받아 주는 입력을 화면이 거부한다.
 */
export function normalizeCallSign(raw: string): string | null {
  const value = raw.trim().toUpperCase()
  return value === '' ? null : value
}

/**
 * 호출부호 한 칸의 검증. 비어 있으면 오류가 아니다(선택 입력).
 *
 * 문구는 서버 검증기(`_normalize_call_sign`)와 **글자 그대로 같다** — 서버 422가 같은 칸에
 * 붙을 때 화면 검증과 다른 말을 하지 않게. 「앞 두 글자가 모두 숫자가 아니다」(`RR No. 19.50`)
 * 까지만 보고 그 이상의 세부(문자 뒤 0·1 금지)는 보지 않는다 — 서버와 같은 느슨함이다.
 *
 * **등록·수정 두 폼이 함께 쓴다** (`checkOptionalPositive`와 같은 이유).
 */
export function checkCallSign(raw: string, field: string, errors: Record<string, string>): void {
  const value = normalizeCallSign(raw)
  if (value === null) return
  if (!CALL_SIGN_PATTERN.test(value)) {
    errors[field] = '호출부호는 영문 대문자와 숫자 4~7자여야 합니다.'
    return
  }
  if (/^\d{2}/.test(value)) {
    errors[field] = '호출부호의 앞 두 글자는 모두 숫자일 수 없습니다.'
  }
}

/**
 * 선택 입력 한 칸의 검증. 비어 있으면 오류가 아니고, 값이 있으면 저장 범위 안이어야 한다.
 *
 * **등록·수정 두 폼이 함께 쓴다** (`#860`). 종전에는 `vessel-management/editRules.ts`에
 * 같은 함수가 한 벌 더 있었다 — 한쪽만 고치면 수정 화면이 다시 뚫린다. 수정 폼이 등록
 * 폼을 재사용하지 않는 이유(PATCH의 「빈 칸 = 안 바꾼다」)는 이 한 칸 검사와 무관하다.
 */
export function checkOptionalPositive(
  raw: string,
  field: string,
  label: string,
  errors: Record<string, string>,
  range: { min: number; max: number },
): void {
  const trimmed = raw.trim()
  if (trimmed === '') return
  const value = toNumber(trimmed)
  if (value === null) {
    errors[field] = `${label}을(를) 숫자로 입력해 주세요.`
    return
  }
  // VAL-002 — 0 이하는 종전 문구를 그대로 쓴다(사용자에게 가장 흔한 실수다).
  if (!(value > 0)) {
    errors[field] = `${withEunNeun(label)} 0보다 커야 합니다.`
    return
  }
  // `#860` — 0보다 크지만 DB가 담을 수 없는 값. 서버는 같은 경계로 422를 낸다.
  if (value < range.min || value > range.max) {
    errors[field] =
      `${withEunNeun(label)} ${range.min.toLocaleString('ko-KR')} 이상 ` +
      `${range.max.toLocaleString('ko-KR', { maximumFractionDigits: 2 })} 이하로 입력해 주세요.`
  }
}

/**
 * 폼 전체를 검증한다. **위반을 전부 모아 반환한다.**
 *
 * 서버는 첫 오류를 `message`로 쓰고 나머지는 `details`에 담는데, 화면은 필드마다
 * 붙여야 하므로 전 필드를 동시에 본다. 규칙 출처는 `API_SPEC §2.3` 검증 규칙 표다.
 */
export function validateForm(
  state: VesselFormState,
  fuels: readonly FuelOption[],
): FormErrors {
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

  checkOptionalPositive(
    state.grossTonnage,
    FIELD.grossTonnage,
    '총톤수(GT)',
    errors,
    STORABLE.tonnage,
  )
  checkOptionalPositive(
    state.deadweight,
    FIELD.deadweight,
    '재화중량톤수(DWT)',
    errors,
    STORABLE.tonnage,
  )
  checkOptionalPositive(
    state.referenceSpeedKn,
    FIELD.referenceSpeedKn,
    '기준속도',
    errors,
    STORABLE.speed,
  )
  checkOptionalPositive(
    state.referenceDailyFocTon,
    FIELD.referenceDailyFocTon,
    '기준 일일 연료소모량',
    errors,
    STORABLE.dailyFoc,
  )
  checkOptionalPositive(
    state.blockCoefficient,
    FIELD.blockCoefficient,
    '방형계수(CB)',
    errors,
    STORABLE.cb,
  )
  // #966 — 물리 상한(1)은 저장 범위 밖 검사와 별개 문구로 알린다.
  {
    const cb = toNumber(state.blockCoefficient.trim())
    if (cb !== null && cb > CB_MAX) {
      errors[FIELD.blockCoefficient] = `${withEunNeun('방형계수(CB)')} 1 이하로 입력해 주세요.`
    }
  }
  // #1197 — 호출부호(선택). 공공데이터 교차 대조의 키.
  checkCallSign(state.callSign, FIELD.callSign, errors)

  // 목록을 못 받은 상태(로딩·실패)에서는 연료 검사를 보류한다 (`#1100` ⑴) — 서버가 최종 판정한다.
  if (state.defaultFuelType !== '' && fuels.length > 0 && !isKnownFuel(state.defaultFuelType, fuels)) {
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

  // #966 — 방형계수(선택). 빈 칸은 키를 넣지 않는다(위 규칙과 같다).
  const blockCoefficient = toNumber(state.blockCoefficient)
  if (blockCoefficient !== null) request.block_coefficient = blockCoefficient

  const referenceDailyFocTon = toNumber(state.referenceDailyFocTon)
  if (referenceDailyFocTon !== null) request.reference_daily_foc_ton = referenceDailyFocTon

  // #1197 — 호출부호(선택). 접은 값을 싣고, 빈 칸은 키를 넣지 않는다(위 규칙과 같다).
  const callSign = normalizeCallSign(state.callSign)
  if (callSign !== null) request.call_sign = callSign

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
  FIELD.blockCoefficient,
  FIELD.callSign,
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
