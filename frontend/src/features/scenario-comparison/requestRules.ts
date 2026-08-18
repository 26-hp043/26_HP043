import { FUEL_CF } from '../voyage-cii/referenceTable'
import type { ScenarioComparisonRequest } from './types'

/**
 * 항로 비교 조건 입력 규칙 (#511).
 *
 * ## 왜 상수를 걷어냈는가
 *
 * 종전 화면은 `DEMO_REQUEST` 상수 하나를 마운트 즉시 provider에 넘겼다. 그 상수의
 * `vessel_id`가 `…0003`이었는데 demo 고정표(`referenceTable.ts`의 `DEMO_VESSELS`)에는
 * `…0001` 한 척뿐이라, **데모 모드에서 항로 비교는 아무 입력 없이 언제나 실패**했다
 * (`demoProvider.ts:92` → `지원하지 않는 선박입니다.`).
 *
 * 상수를 `…0001`로 바꾸는 것으로는 풀리지 않는다. 그 배는 `reference_speed_kn`이
 * 비어 있어 **실 API가 422를 낸다**(`services/scenario_compare.py:466`). 종전 주석이
 * 그 사실을 알고 `…0003`을 고른 것이었다 — **어느 상수를 골라도 한쪽이 깨진다.**
 *
 * 그래서 상수를 고르지 않는다. **선박을 provider의 목록에서 읽고 조건을 사용자가
 * 넣는다.** `PRD §11.4` 연료 예측 모델의 ⑴ 사용자 입력이 원래 그 자리다.
 *
 * ## 자동 실행하지 않는다
 *
 * 마운트 시 계산을 걸지 않는다. 사용자가 조건을 정하기 전의 계산은 **누구의 질문도
 * 아니고**, 실패하면 화면이 오류로 시작한다 — 이번 이슈가 정확히 그 상태였다.
 */

/** 입력 폼 상태. 전부 문자열이다 — 입력창의 값이 곧 상태다. */
export interface ComparisonFormState {
  vesselId: string
  regulationYear: string
  baseDistanceNm: string
  baseSpeedKn: string
  baseDailyFocTon: string
  fuelType: string
}

/** 오류 맵의 키. 서버 `details[0].field`와 같은 이름을 쓴다. */
export const FIELD = {
  vesselId: 'vessel_id',
  regulationYear: 'regulation_year',
  baseDistanceNm: 'direct_distance_nm',
  baseSpeedKn: 'current_speed_kn',
  baseDailyFocTon: 'base_daily_foc_ton',
  fuelType: 'fuel_type',
  form: '__form__',
} as const

export type FormErrors = Record<string, string>

/**
 * 초기 조건.
 *
 * 선박만 비운다 — 나머지는 종전 `DEMO_REQUEST`가 쓰던 값을 그대로 옮겼다.
 * `PRD §13.1` Fixture 1과 이어지는 값이라 기능①에서 본 수치가 `직항`으로 다시 나온다.
 *
 * **선박에는 기본값을 넣지 않는다.** 목록을 읽기 전에 아무 배나 골라 두면 사용자가
 * 고른 것과 기본값을 구분할 수 없고, 그 배가 목록에 없으면 종전 버그가 재발한다.
 */
export function initialFormState(): ComparisonFormState {
  return {
    vesselId: '',
    regulationYear: '2026',
    baseDistanceNm: '1000',
    baseSpeedKn: '12.8',
    // 1000nm / 14kn ≈ 2.98일 · 총 80t → 일일 26.88t (#139 계약)
    baseDailyFocTon: '26.88',
    fuelType: 'HFO',
  }
}

/** 연료 종류 선택지. `FUEL_CF` 8종을 순회한다 — 화면에 코드를 다시 적지 않는다. */
export function selectableFuels(): Array<{ code: string; displayName: string }> {
  return Object.entries(FUEL_CF).map(([code, { displayName }]) => ({ code, displayName }))
}

/**
 * 십진 문자열을 숫자로. 읽을 수 없으면 `null`.
 *
 * `Number('')`이 `0`이라 빈 칸이 「0 입력」으로 통과한다. 거리·속력에서 그 차이는
 * 검증을 통째로 무력화한다.
 */
function toNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

/** 필수 양수 한 칸의 검증 (VAL-002 — `API_SPEC §11`). */
function checkRequiredPositive(
  raw: string,
  field: string,
  label: string,
  errors: FormErrors,
): void {
  const trimmed = raw.trim()
  if (trimmed === '') {
    errors[field] = `${label}을(를) 입력해 주세요.`
    return
  }
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
 * 조건을 검증한다. 위반을 전부 모아 반환한다.
 *
 * 서버는 첫 오류를 `message`로 쓰고 나머지를 `details`에 담는데, 화면은 필드마다
 * 붙여야 하므로 전 필드를 동시에 본다(기능①·선박 등록과 같은 규칙).
 */
export function validateForm(state: ComparisonFormState): FormErrors {
  const errors: FormErrors = {}

  if (state.vesselId.trim() === '') {
    errors[FIELD.vesselId] = '선박을 선택해 주세요.'
  }

  const year = toNumber(state.regulationYear)
  if (year === null || !Number.isInteger(year)) {
    errors[FIELD.regulationYear] = '규제연도를 4자리 숫자로 입력해 주세요.'
  }

  checkRequiredPositive(state.baseDistanceNm, FIELD.baseDistanceNm, '직항 거리', errors)
  checkRequiredPositive(state.baseSpeedKn, FIELD.baseSpeedKn, '현재 속력', errors)
  checkRequiredPositive(
    state.baseDailyFocTon,
    FIELD.baseDailyFocTon,
    '기준 일일 연료소모량',
    errors,
  )

  if (state.fuelType.trim() === '') {
    errors[FIELD.fuelType] = '연료 종류를 선택해 주세요.'
  } else if (!FUEL_CF[state.fuelType]) {
    // VAL-006의 화면 쪽 방어선. 셀렉트로는 도달하지 않으나 오래된 상태가 남았을 때
    // 서버 422를 기다리지 않고 여기서 잡는다.
    errors[FIELD.fuelType] = `알 수 없는 연료 종류입니다: ${state.fuelType}`
  }

  return errors
}

/**
 * 검증을 통과한 상태를 요청으로 바꾼다.
 *
 * @throws 검증되지 않은 상태로 부르면 `Error`. 항상 `validateForm()` 뒤에 부른다.
 */
export function toRequest(state: ComparisonFormState): ScenarioComparisonRequest {
  const errors = validateForm(state)
  if (Object.keys(errors).length > 0) {
    throw new Error('검증되지 않은 폼 상태입니다. validateForm()을 먼저 호출하십시오.')
  }
  return {
    vessel_id: state.vesselId.trim(),
    regulation_year: Number(state.regulationYear),
    base_distance_nm: Number(state.baseDistanceNm),
    base_speed_kn: Number(state.baseSpeedKn),
    base_daily_foc_ton: Number(state.baseDailyFocTon),
    fuel_type: state.fuelType,
  }
}

/**
 * 선박 목록이 비었을 때의 안내.
 *
 * demo 모드에서는 고정표가 1척을 주므로 사실상 실 API에서만 나온다 — 선박을 아직
 * 등록하지 않은 상태다(`UIFLOW 1-1`). **비교 버튼을 눌러 보게 두지 않는다.**
 */
export const NO_VESSEL_MESSAGE =
  '등록된 선박이 없어 비교할 대상이 없습니다. 선박을 먼저 등록해 주세요.'
