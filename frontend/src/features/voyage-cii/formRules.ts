import { isKnownFuel, type FuelOption } from '../parameters/fuelCatalog'
import type { VoyageCiiRequest } from './types'
import { VoyageCiiError } from './provider'

/**
 * 기능① 입력 폼의 상태·검증·요청 변환 (#135).
 *
 * **컴포넌트에서 분리한 순수 함수 모듈이다.** 이유는 `rules.ts`와 같다 — 경계 조건을
 * 정확히 잠그기 위해서다. `speed_kn >= 1.0`을 `> 1.0`으로 잘못 써도 화면을 통한
 * 조작으로는 그 차이를 드러내는 입력을 만들기 어렵다. 함수를 직접 호출하면
 * 경계값 자체를 인자로 넣을 수 있다.
 *
 * 부수적으로 **컴포넌트 테스트 도구 없이 검증 규칙을 테스트할 수 있다** —
 * 저장소에 `@testing-library/react`·`jsdom`이 없고, 이 이슈 때문에 들이지 않는다.
 *
 * ⚠️ **입력값을 `Number`로 다루는 것은 요청까지다.** 요청 필드
 * (`distance_nm`·`speed_kn`·`fuel_ton`)는 `API_SPEC §4.1`상 숫자 타입이다.
 * **응답의 Layer 1 값은 문자열**이며 `format.ts`가 다룬다 — 두 방향을 혼동하지 말 것.
 */

/**
 * 폼 상태. **숫자 필드도 문자열로 들고 있다.**
 *
 * `<input type="number">`의 `value`는 문자열이고, 빈 칸·`-`·`1.`처럼 숫자로 변환되지
 * 않는 중간 상태가 존재한다. 상태를 `number`로 두면 그 순간마다 `NaN`이 되어
 * 사용자가 지우는 동안 오류가 깜빡인다. **변환은 제출 시점에 한 번만** 한다.
 */
export interface VoyageCiiFormState {
  vesselId: string
  regulationYear: string
  distanceNm: string
  speedKn: string
  fuelType: string
  fuelTon: string
}

/**
 * 필드별 오류 메시지.
 *
 * 키는 **요청 본문 기준 경로**다 — `VoyageCiiError.field`가 그 형태로 오기 때문에
 * (`fuel_uses[0].fuel_ton`) 클라이언트 검증과 provider 오류를 같은 맵에 병합할 수 있다.
 * 화면은 이 맵 하나만 읽는다.
 */
export type FormErrors = Record<string, string>

/** 요청 본문 기준 필드 경로. 화면의 입력창과 1:1로 대응한다. */
export const FIELD = {
  distanceNm: 'distance_nm',
  speedKn: 'speed_kn',
  fuelType: 'fuel_uses[0].fuel_type',
  fuelTon: 'fuel_uses[0].fuel_ton',
  /** 어느 입력창에도 붙지 않는 오류. 폼 상단에 표시한다. */
  form: '__form__',
} as const

/**
 * 초기 폼 상태. **전부 빈 문자열이다.**
 *
 * 종전에는 선박·연도를 고정표(`referenceTable.ts`)의 첫 항목으로 채웠다. `#542`가
 * 그 표를 없앴고, 두 값의 출처는 이미 서버로 옮겨져 있다 — 선박은 셸의 전역 선택
 * (`#484` · `#535`), 연도는 `yearCatalog`(`#534`)가 채운다.
 *
 * 여기서 값을 지어내면 **서버에 없는 UUID를 가리키는 초기 상태**가 만들어진다.
 * `#543`이 정확히 그 결함이었다.
 */
export function initialFormState(): VoyageCiiFormState {
  return {
    vesselId: '',
    regulationYear: '',
    distanceNm: '',
    speedKn: '',
    fuelType: '',
    fuelTon: '',
  }
}

/**
 * 십진 문자열을 숫자로 바꾼다. 숫자로 읽을 수 없으면 `null`.
 *
 * `Number('')`이 `0`, `Number(' ')`도 `0`이라 빈 칸이 「0 입력」으로 통과한다.
 * 그러면 「거리를 입력해 주세요」가 아니라 「0보다 커야 합니다」가 떠서 원인이
 * 잘못 전달된다. 빈 칸을 먼저 걸러 내는 이유다.
 */
function toNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

/**
 * 연도 목록을 받았을 때 **셀렉트에 무엇이 선택돼 있을지** 정한다.
 *
 * 1. 이미 고른 해가 새 목록에도 있으면 **유지한다** — 선박을 바꿀 때마다 되돌아가면
 *    사용자가 방금 고른 값을 잃는다(`#534`가 정한 규칙).
 * 2. 없으면 **올해**를 고른다. 목록에 올해가 없으면 **가장 최근 해**로 떨어진다.
 *
 * ## 왜 첫 항목이면 안 되는가
 *
 * 종전에는 `rows[0]`이었다. 목록이 오름차순이고 CII 규제가 2023년에 시작하므로
 * **항상 2023이 걸렸다.** 이것은 보기 문제가 아니라 **결과가 달라지는 문제**다 —
 * `required_CII = CII_ref × (1 − Z_year/100)`에서 `Z_year`가 해마다 커지므로 기준값이
 * 다르고 등급 판정이 바뀐다. 연도를 건드리지 않은 사용자는 3년 전 기준으로 계산된
 * 등급을 보게 된다. 대시보드가 「2026년 누적(YTD) 기준」이라 화면 간 표기도 어긋났다.
 *
 * ## ⚠️ 이것은 계산이 아니라 폼 편의값이다
 *
 * `PRD §3.3.8`이 「계산 코어는 시각을 모른다」를 정하고 `as_of`를 명시 입력으로 승격한
 * 것은 **계산** 이야기다. 여기서 정하는 것은 **사용자가 화면에 들어왔을 때 셀렉트에
 * 무엇이 선택돼 있는가**이며, 서버로 보내는 값은 여전히 사용자가 고른
 * `regulation_year` 그대로다. 화면이 시각을 참고해 기본 선택을 정하는 것과, 계산이
 * 시각에 의존하는 것은 다른 일이다 — **이 주석을 「화면이 시각을 알면 안 된다」로 읽고
 * 되돌리지 말 것.**
 *
 * 그래서 `new Date()`를 이 함수 안에서 부르지 않고 **인자로 받는다.** 컴포넌트가
 * 시각을 읽고 순수 함수는 그 값을 쓰기만 하므로, 테스트가 어느 해로든 고정할 수 있다.
 *
 * 목록이 비면 빈 문자열이다 — **값을 지어내지 않는다.**
 *
 * @param rows   서버가 준 규제연도 목록
 * @param currentYear 호출부가 읽은 올해 (`new Date().getFullYear()`)
 * @param previous 지금 골라져 있는 값. 없으면 빈 문자열
 */
export function pickDefaultYear(
  rows: readonly number[],
  currentYear: number,
  previous = '',
): string {
  if (rows.length === 0) return ''
  if (previous !== '' && rows.includes(Number(previous))) return previous
  if (rows.includes(currentYear)) return String(currentYear)
  /*
   * 정렬에 기대지 않고 최댓값을 고른다. 실 API는 오름차순으로 주지만(`apiProvider`가
   * `.sort()` 한다) 그것은 이 함수가 강제할 수 없는 조건이고, 순서가 뒤집히면
   * `rows[rows.length - 1]`은 **가장 오래된 해**를 조용히 고른다 — 지금 고치는 버그와
   * 같은 모양이다.
   */
  return String(Math.max(...rows))
}

/**
 * 폼 전체를 검증한다. **위반을 전부 모아 반환한다.**
 *
 * `demoProvider.validateRequest()`는 첫 위반에서 즉시 `throw`하므로 거리와 연료량이
 * 둘 다 잘못돼도 하나만 보인다. 사용자가 고치고 제출하면 다음 오류가 뜨는 왕복이
 * 생긴다. 화면 검증은 그 왕복을 없애기 위해 전 필드를 동시에 본다.
 *
 * provider 검증을 대체하는 것이 아니다 — provider는 요청 형태에 대한 방어선으로
 * 그대로 남고, 화면 검증을 통과한 요청은 provider도 통과한다.
 *
 * 규칙 출처는 `API_SPEC §11`이며 문구는 `demoProvider`와 맞춘다.
 */
export function validateForm(
  state: VoyageCiiFormState,
  fuels: readonly FuelOption[],
): FormErrors {
  const errors: FormErrors = {}

  const distance = toNumber(state.distanceNm)
  if (distance === null) {
    errors[FIELD.distanceNm] = '항해거리를 입력해 주세요.'
  } else if (!(distance > 0)) {
    // VAL-002
    errors[FIELD.distanceNm] = '항해거리는 0보다 커야 합니다.'
  }

  const speed = toNumber(state.speedKn)
  if (speed === null) {
    errors[FIELD.speedKn] = '평균 속력을 입력해 주세요.'
  } else if (!(speed >= 1.0)) {
    // VAL-009 — PRD §9.1이 > 0이 아니라 ≥ 1.0으로 규정한다
    errors[FIELD.speedKn] = '속도는 1.0노트 이상이어야 합니다.'
  }

  if (state.fuelType === '') {
    errors[FIELD.fuelType] = '연료 종류를 선택해 주세요.'
  } else if (!isKnownFuel(state.fuelType, fuels)) {
    // VAL-006. 셀렉트로 구현하면 도달하지 않으나, 오래된 상태가 남았을 때의 방어선이다.
    // 목록을 인자로 받는 이유는 `fuelCatalog.ts`의 `isKnownFuel` 주석에 있다 (#542).
    errors[FIELD.fuelType] = `알 수 없는 연료 종류입니다: ${state.fuelType}`
  }

  const fuelTon = toNumber(state.fuelTon)
  if (fuelTon === null) {
    errors[FIELD.fuelTon] = '연료 사용량을 입력해 주세요.'
  } else if (!(fuelTon > 0)) {
    // VAL-002
    errors[FIELD.fuelTon] = '연료 사용량은 0보다 커야 합니다.'
  }

  if (state.vesselId === '') {
    errors[FIELD.form] = '선박을 선택해 주세요.'
  }
  if (toNumber(state.regulationYear) === null) {
    errors[FIELD.form] = '규제연도를 선택해 주세요.'
  }

  return errors
}

/**
 * 검증을 통과한 폼 상태를 요청 객체로 바꾼다.
 *
 * **계약에 확정된 필드만 넣는다**(#135 완료 기준). `weather_model`은 8/8 UI가
 * 수집하지 않으므로 요청에서도 생략한다 — 서버 기본값 `NONE`이다.
 *
 * 단일 연료 입력을 **길이 1의 배열**로 매핑한다. 화면에 행 추가·삭제를 만들지
 * 않을 뿐 계약은 배열이며, 다중 행은 8/8 이후 작업이다.
 *
 * 필드명은 `fuel_ton`이다 — `planned_fuel_ton`은 항차 생성(`API_SPEC §3.3`)의
 * 필드로 계산 요청(`§4.1`)과 다르다.
 *
 * @throws 검증되지 않은 상태로 호출하면 `Error`. 항상 `validateForm()` 뒤에 부른다.
 */
export function toRequest(state: VoyageCiiFormState): VoyageCiiRequest {
  const regulationYear = toNumber(state.regulationYear)
  const distanceNm = toNumber(state.distanceNm)
  const speedKn = toNumber(state.speedKn)
  const fuelTon = toNumber(state.fuelTon)

  if (
    regulationYear === null ||
    distanceNm === null ||
    speedKn === null ||
    fuelTon === null
  ) {
    throw new Error('검증되지 않은 폼 상태입니다. validateForm()을 먼저 호출하십시오.')
  }

  return {
    vessel_id: state.vesselId,
    regulation_year: regulationYear,
    distance_nm: distanceNm,
    speed_kn: speedKn,
    fuel_uses: [{ fuel_type: state.fuelType, fuel_ton: fuelTon }],
  }
}

/**
 * provider 오류를 필드별 메시지 맵으로 바꾼다.
 *
 * `VoyageCiiError.field`는 **요청 본문 기준 경로**라 `FIELD` 상수와 그대로 맞는다.
 * `field`가 없거나 화면에 대응 입력창이 없는 경로면 폼 상단에 붙인다.
 *
 * `VoyageCiiError`가 아닌 오류도 삼키지 않고 폼 상단에 표시한다 — 데모 중 화면이
 * 조용히 아무 반응도 하지 않는 것이 가장 나쁘다.
 *
 * 실제 API 연결(`#138`) 후에도 **화면은 계속 `VoyageCiiError`를 받는다.**
 * 서버의 `field`·`field_label`은 `apiProvider`가 변환해 넘긴다 — 화면이 서버 응답
 * 형태를 직접 다루면 provider 경계가 무너진다.
 */
const FIELD_PATHS: ReadonlySet<string> = new Set([
  FIELD.distanceNm,
  FIELD.speedKn,
  FIELD.fuelType,
  FIELD.fuelTon,
])

export function toFormErrors(error: unknown): FormErrors {
  if (error instanceof VoyageCiiError) {
    if (error.field && FIELD_PATHS.has(error.field)) {
      return { [error.field]: error.message }
    }
    return { [FIELD.form]: error.message }
  }
  return {
    [FIELD.form]:
      error instanceof Error ? error.message : '계산 중 알 수 없는 오류가 발생했습니다.',
  }
}
