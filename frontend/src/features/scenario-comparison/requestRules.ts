import { isKnownFuel, type FuelOption } from '../parameters/fuelCatalog'
import type { WeatherModel } from '../voyage-cii/types'
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
  /**
   * `PRD §11.2` DETOUR — *"사용자가 우회율 또는 우회 거리 직접 입력"*.
   *
   * **빈 칸이 「서버 기본」이다.** `API_SPEC §5.1`이 미지정 시 `direct x 1.05`를
   * 규정하므로, 화면이 1.05를 미리 채우면 **같은 규칙이 두 곳**이 되어 서버가
   * 기본값을 바꿀 때 화면만 옛 값을 보낸다.
   */
  detourDistanceNm: string
  /** `PRD §11.2` SLOW_STEAMING — *"사용자가 조정 가능"*. 빈 칸은 서버 기본. */
  slowSpeedKn: string
  /** `API_SPEC §5.1` enum. 빈 문자열이 아니라 `NONE`이 기본이다 (아래 주석 참조). */
  weatherModel: string
  /** `PRD §11.3` 현재 위치. 기상 조회의 유일한 입력이다 (#892 주석 참조). */
  currentLat: string
  currentLon: string
}

/**
 * `API_SPEC §5.1` `weather_model` enum 3종.
 *
 * 서버 `WeatherModel`(`api/schemas/voyage_cii.py:22`)과 같은 값이다. 화면이 목록을
 * 따로 들고 있는 이유는 이 enum에 조회 엔드포인트가 없기 때문이다 — 연료·연도와
 * 달리 DB 테이블이 아니라 코드 리터럴이다.
 */
export const WEATHER_MODELS: ReadonlyArray<{ code: WeatherModel; label: string }> = [
  { code: 'NONE', label: '사용 안 함' },
  { code: 'SIMPLE_RULE', label: '간이 규칙 (SIMPLE_RULE)' },
  { code: 'TOWNSIN_KWON_ALPHA', label: 'Townsin-Kwon (실험 모델)' },
]

/** 오류 맵의 키. 서버 `details[0].field`와 같은 이름을 쓴다. */
export const FIELD = {
  vesselId: 'vessel_id',
  regulationYear: 'regulation_year',
  baseDistanceNm: 'direct_distance_nm',
  baseSpeedKn: 'current_speed_kn',
  baseDailyFocTon: 'base_daily_foc_ton',
  fuelType: 'fuel_type',
  detourDistanceNm: 'detour_distance_nm',
  slowSpeedKn: 'slow_speed_kn',
  weatherModel: 'weather_model',
  currentLat: 'current_lat',
  currentLon: 'current_lon',
  form: '__form__',
} as const

export type FormErrors = Record<string, string>

/**
 * `PRD §9.1` VAL-009 — 감속 속도의 하한.
 *
 * 서버 `services/scenario_compare.py`의 `MIN_SPEED_KN`과 같은 값이다. 화면이 이
 * 숫자를 따로 드는 이유는 조회 경로가 없어서이며, 값이 갈리면 화면이 통과시킨
 * 입력을 서버가 422로 되돌린다.
 */
export const MIN_SPEED_KN = 1.0

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
    /*
     * 선택 입력 넷은 **비운다.** 값을 미리 넣으면 그것이 서버 기본과 다를 때
     * 사용자가 고르지 않은 조건으로 계산된다 (`API_SPEC §5.1` 기본값 표).
     */
    detourDistanceNm: '',
    slowSpeedKn: '',
    currentLat: '',
    currentLon: '',
    // 기상만 빈 칸이 아니다 — 셀렉트에는 「미선택」이 없고 `NONE`이 그 자리다.
    weatherModel: 'NONE',
  }
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
 * 선택 입력 한 칸의 검증. **빈 칸은 오류가 아니다** — 서버 기본값을 쓴다는 뜻이다.
 *
 * `min`은 하한값이고 `inclusive`가 그 값을 포함하는지 정한다. 두 규칙이 갈리기
 * 때문이다: 우회 거리는 VAL-002(`> 0`), 감속 속력은 VAL-009(`>= 1.0`).
 */
function checkOptionalBound(
  raw: string,
  field: string,
  label: string,
  errors: FormErrors,
  { min, inclusive }: { min: number; inclusive: boolean },
): void {
  const trimmed = raw.trim()
  if (trimmed === '') return
  const value = toNumber(trimmed)
  if (value === null) {
    errors[field] = `${label}을(를) 숫자로 입력해 주세요.`
    return
  }
  if (inclusive ? value < min : !(value > min)) {
    errors[field] = inclusive
      ? `${label}은(는) ${min} 이상이어야 합니다.`
      : `${label}은(는) ${min}보다 커야 합니다.`
  }
}

/**
 * 현재 좌표 두 칸 (VAL-007 · `API_SPEC:572`).
 *
 * **한쪽만 넣은 상태를 화면에서 잡는다.** `API_SPEC §5.1`이 *"`current_lat`과
 * `current_lon`은 **함께** 지정"* 을 422로 규정하므로, 보내 놓고 422를 받는 대신
 * 여기서 막는다 — 두 칸 중 어느 쪽이 빈지는 화면이 이미 알고 있다.
 */
function checkCoordinates(state: ComparisonFormState, errors: FormErrors): void {
  const pairs = [
    { raw: state.currentLat, field: FIELD.currentLat, label: '현재 위도', limit: 90 },
    { raw: state.currentLon, field: FIELD.currentLon, label: '현재 경도', limit: 180 },
  ]
  const filled = pairs.filter((pair) => pair.raw.trim() !== '')
  if (filled.length === 1) {
    const missing = pairs.find((pair) => pair.raw.trim() === '')!
    errors[missing.field] = `${missing.label}도 함께 입력해 주세요. 위도·경도는 둘 다 필요합니다.`
  }
  for (const pair of filled) {
    const value = toNumber(pair.raw)
    if (value === null) {
      errors[pair.field] = `${pair.label}를 숫자로 입력해 주세요.`
    } else if (value < -pair.limit || value > pair.limit) {
      errors[pair.field] = `${pair.label}는 -${pair.limit} ~ ${pair.limit} 범위여야 합니다.`
    }
  }
}

/**
 * 조건을 검증한다. 위반을 전부 모아 반환한다.
 *
 * 서버는 첫 오류를 `message`로 쓰고 나머지를 `details`에 담는데, 화면은 필드마다
 * 붙여야 하므로 전 필드를 동시에 본다(기능①·선박 등록과 같은 규칙).
 */
export function validateForm(
  state: ComparisonFormState,
  fuels: readonly FuelOption[],
): FormErrors {
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
  } else if (!isKnownFuel(state.fuelType, fuels)) {
    // VAL-006의 화면 쪽 방어선. 셀렉트로는 도달하지 않으나 오래된 상태가 남았을 때
    // 서버 422를 기다리지 않고 여기서 잡는다.
    errors[FIELD.fuelType] = `알 수 없는 연료 종류입니다: ${state.fuelType}`
  }

  // VAL-002 — 우회 거리는 양수. 직항보다 짧아도 막지 않는다: `PRD §11.2`가
  // 「거리 증가」를 정의로 적을 뿐 하한을 직항으로 규정하지 않았고, 서버도 막지
  // 않는다. 화면만 막으면 서버 계약과 갈린다.
  checkOptionalBound(state.detourDistanceNm, FIELD.detourDistanceNm, '우회 거리', errors, {
    min: 0,
    inclusive: false,
  })
  // VAL-009 — floor는 1.0kn. `> 0`이 아니다 (`PRD §9.1`).
  checkOptionalBound(state.slowSpeedKn, FIELD.slowSpeedKn, '감속 속력', errors, {
    min: MIN_SPEED_KN,
    inclusive: true,
  })
  checkCoordinates(state, errors)

  if (!WEATHER_MODELS.some((model) => model.code === state.weatherModel)) {
    // 셀렉트로는 도달하지 않는다. 연료와 같은 이유의 방어선이다.
    errors[FIELD.weatherModel] = `알 수 없는 기상 모델입니다: ${state.weatherModel}`
  }

  return errors
}

/**
 * 검증을 통과한 상태를 요청으로 바꾼다.
 *
 * @throws 검증되지 않은 상태로 부르면 `Error`. 항상 `validateForm()` 뒤에 부른다.
 */
export function toRequest(
  state: ComparisonFormState,
  fuels: readonly FuelOption[],
): ScenarioComparisonRequest {
  const errors = validateForm(state, fuels)
  if (Object.keys(errors).length > 0) {
    throw new Error('검증되지 않은 폼 상태입니다. validateForm()을 먼저 호출하십시오.')
  }
  const request: ScenarioComparisonRequest = {
    vessel_id: state.vesselId.trim(),
    regulation_year: Number(state.regulationYear),
    base_distance_nm: Number(state.baseDistanceNm),
    base_speed_kn: Number(state.baseSpeedKn),
    base_daily_foc_ton: Number(state.baseDailyFocTon),
    fuel_type: state.fuelType,
  }
  /*
   * 선택 입력은 **채운 칸만 싣는다.**
   *
   * 빈 칸을 `0`이나 `null`로 보내면 서버 기본값 규칙(`API_SPEC §5.1`)이 발동하지
   * 않는다 — `detour_distance_nm: 0`은 「기본을 쓰라」가 아니라 「0마일로 우회하라」이고
   * VAL-002에 걸려 422가 된다. **키를 아예 넣지 않는 것**이 「미지정」의 표현이다.
   */
  const optionalNumbers = [
    ['detour_distance_nm', state.detourDistanceNm],
    ['slow_speed_kn', state.slowSpeedKn],
    ['current_lat', state.currentLat],
    ['current_lon', state.currentLon],
  ] as const
  for (const [key, raw] of optionalNumbers) {
    if (raw.trim() !== '') request[key] = Number(raw)
  }
  // `NONE`은 보내지 않는다 — 서버 기본이 `NONE`이고(`API_SPEC §5.1`), 명시해도
  // 결과가 같다. 보내지 않는 쪽이 「기상을 쓰지 않는 요청」임이 본문에 드러난다.
  if (state.weatherModel !== 'NONE') {
    request.weather_model = state.weatherModel as WeatherModel
  }
  return request
}

/**
 * 고른 기상 모델이 **실제로 적용되는지** 판정한다.
 *
 * ## 왜 필요한가 — 좌표가 없으면 보정이 통째로 건너뛴다
 *
 * `services/weather.py:276-280`이 좌표 없는 요청을 `NEUTRAL_FACTOR`(보정 1.0)로
 * 되돌리고 `WEATHER_NONE_FALLBACK` 경고만 붙인다. 실 API로 측정한 결과가 그대로다
 * (선박 `…0003` · 1000nm · 26.88t/일 · 2026):
 *
 * ```
 * 모델 없음                  fuel_ton 87.50   attained_cii 42.535870
 * SIMPLE_RULE + 좌표 없음    fuel_ton 87.50   attained_cii 42.535870   <- 같다
 * SIMPLE_RULE + 35N 140E     fuel_ton 94.22   attained_cii 45.802625
 * ```
 *
 * 결과에 붙는 `WEATHER_NONE_FALLBACK` 배너만으로는 **계산이 끝난 뒤에야** 알 수
 * 있다. 누르기 전에 알려 준다.
 */
export function weatherNeedsCoordinates(state: ComparisonFormState): boolean {
  return (
    state.weatherModel !== 'NONE' &&
    (state.currentLat.trim() === '' || state.currentLon.trim() === '')
  )
}

/**
 * 선박 목록이 비었을 때의 안내.
 *
 * demo 모드에서는 고정표가 1척을 주므로 사실상 실 API에서만 나온다 — 선박을 아직
 * 등록하지 않은 상태다(`UIFLOW 1-1`). **비교 버튼을 눌러 보게 두지 않는다.**
 */
export const NO_VESSEL_MESSAGE =
  '등록된 선박이 없어 비교할 대상이 없습니다. 선박을 먼저 등록해 주세요.'
