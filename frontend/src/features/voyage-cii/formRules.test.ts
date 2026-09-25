import { describe, expect, it } from 'vitest'
import {
  FIELD,
  initialFormState,
  toFormErrors,
  toRequest,
  validateForm as validateFormWith,
  effectiveFuelTon,
  voyageHours,
  type VoyageCiiFormState,
  pickDefaultYear,
  prefillFromVoyage,
} from './formRules'
import { VoyageCiiError } from './provider'

/**
 * `#135` 입력 폼의 검증·변환 규칙 테스트.
 *
 * 컴포넌트 렌더 테스트가 아니다 — 저장소에 `@testing-library/react`·`jsdom`이 없고
 * 이 이슈 때문에 들이지 않는다. 검증 규칙을 순수 함수로 분리한 것이 그 대가를
 * 치르지 않기 위해서다.
 */

/**
 * 모든 검증을 통과하는 상태. 각 테스트는 여기서 한 필드만 무너뜨린다.
 *
 * 값은 임의가 아니라 **`#132` 계약 fixture의 데모 시나리오**다 —
 * 거리 1,000 nm · HFO 80 t. 아래 「데모 시나리오」 테스트가 이 입력으로
 * 계약 기대값이 그대로 나오는지 확인한다.
 */
function validState(): VoyageCiiFormState {
  return {
    ...initialFormState(),
    // 고정표가 사라져(#542) 초기 상태가 비어 있다. 유효 상태는 여기서 채운다.
    vesselId: '00000000-0000-4000-8000-000000000001',
    regulationYear: '2026',
    distanceNm: '1000',
    speedKn: '14.2',
    fuelType: 'HFO',
    fuelTon: '80',
  }
}


/**
 * 연료 선택지 — 종전 고정표 `FUEL_CF`의 8종과 같은 코드 집합이다 (#542).
 *
 * 검증 함수가 목록을 **인자로 받도록** 바뀌었다. 서버(`GET /parameters/fuel-types`)가
 * 주는 값이므로 화면 규칙이 목록을 직접 알지 않는다 — 그 사실을 테스트에서도
 * 같은 모양으로 둔다.
 */
const FUELS: ReadonlyArray<{ code: string; displayName: string }> = [
  { code: 'HFO', displayName: '고유황유' },
  { code: 'LFO', displayName: '저유황유' },
  { code: 'MDO', displayName: '경유' },
  { code: 'MGO', displayName: '선박용 경유' },
  { code: 'LNG', displayName: '액화천연가스' },
  { code: 'LPG_PROPANE', displayName: '프로판' },
  { code: 'LPG_BUTANE', displayName: '부탄' },
  { code: 'METHANOL', displayName: '메탄올' },
]

/**
 * 목록을 채워 넘기는 얇은 래퍼. 기존 호출부를 그대로 두기 위한 것이며,
 * **주입 자체가 판정을 바꾼다는 사실은 아래 「주입된 목록이 판정을 정한다」가 잠근다.**
 */
const validateForm = (state: VoyageCiiFormState) => validateFormWith(state, FUELS)




describe('initialFormState', () => {
  it('전부 비어 있다 — 값을 지어내지 않는다 (#542)', () => {
    // 종전에는 선박·연도를 고정표 첫 항목으로 채웠고, 그 UUID가 서버에 없어
    // 초기 상태가 존재하지 않는 배를 가리켰다(#543). 선박은 셸(#535), 연도는
    // yearCatalog(#534)가 채운다.
    expect(initialFormState()).toEqual({
      vesselId: '',
      regulationYear: '',
      distanceNm: '',
      speedKn: '',
      fuelType: '',
      fuelTon: '',
      // 연료 입력 방식은 종전과 같은 「총량」으로 시작한다 (#1718).
      fuelMode: 'TOTAL',
      dailyFuelTon: '',
    })
  })

  it('그 상태로는 제출되지 않는다 — 선박 안내가 붙는다 (#1093 ⑶)', () => {
    const errors = validateForm(initialFormState())
    expect(errors[FIELD.vesselId]).toBe('선박을 선택해 주세요.')
    /*
     * ⚠️ 종전에는 둘 다 `FIELD.form` 한 칸을 써서 **연도 오류가 선박 오류를 덮었다.**
     * 이제 키가 갈렸고, **선박을 고르기 전에는 연도 오류를 내지 않는다** — 선박이
     * 비면 연도 목록을 조회조차 하지 않으므로 고를 칸이 화면에 없다.
     */
    expect(errors[FIELD.regulationYear]).toBeUndefined()
  })
})

describe('validateForm — 빈 칸', () => {
  it('빈 칸은 "0보다 커야 합니다"가 아니라 "입력해 주세요"로 안내한다', () => {
    // Number('')는 0이라 빈 칸을 먼저 거르지 않으면 원인이 잘못 전달된다.
    const errors = validateForm({
      ...validState(),
      distanceNm: '',
      speedKn: '  ',
      fuelTon: '',
    })
    // 지키려는 것은 문구가 아니라 **세 칸이 각자 자기 원인을 말하는 것**이다.
    // 하나로 뭉뚱그리면 사용자는 어느 칸이 문제인지 모른다.
    const messages = [errors[FIELD.distanceNm], errors[FIELD.speedKn], errors[FIELD.fuelTon]]
    expect(messages.every((message) => (message ?? '').length > 0)).toBe(true)
    expect(new Set(messages).size).toBe(3)
  })

  it('숫자로 읽히지 않는 값도 빈 칸과 같은 안내로 처리한다', () => {
    const blank = validateForm({ ...validState(), distanceNm: '' })
    const text = validateForm({ ...validState(), distanceNm: 'abc' })
    expect(text[FIELD.distanceNm]).toBe(blank[FIELD.distanceNm])
  })
})

describe('validateForm — 경계값', () => {
  it('유효한 상태는 오류가 0건이다', () => {
    expect(validateForm(validState())).toEqual({})
  })

  it.each([
    ['0', true],
    ['-1', true],
    ['0.0001', false],
  ])('distance_nm = %s → 오류 %s (VAL-002: > 0)', (value, shouldFail) => {
    const errors = validateForm({ ...validState(), distanceNm: value })
    expect(FIELD.distanceNm in errors).toBe(shouldFail)
  })

  it.each([
    ['0.9', true],
    ['0.999', true],
    ['1', false],
    ['1.0', false],
    ['1.1', false],
  ])('speed_kn = %s → 오류 %s (VAL-009: >= 1.0)', (value, shouldFail) => {
    // 경계가 > 0이 아니라 >= 1.0이다. 1.0 자체는 통과해야 한다.
    const errors = validateForm({ ...validState(), speedKn: value })
    expect(FIELD.speedKn in errors).toBe(shouldFail)
  })

  it.each([
    ['0', true],
    ['-5', true],
    ['0.01', false],
  ])('fuel_ton = %s → 오류 %s (VAL-002: > 0)', (value, shouldFail) => {
    const errors = validateForm({ ...validState(), fuelTon: value })
    expect(FIELD.fuelTon in errors).toBe(shouldFail)
  })

  it('속력 1.0 미만은 0보다 커도 거부되고, 빈 칸과 다른 안내를 낸다', () => {
    // 「입력해 주세요」와 「1.0 이상이어야」는 사용자가 할 일이 다르다.
    const tooSlow = validateForm({ ...validState(), speedKn: '0.5' })
    const blank = validateForm({ ...validState(), speedKn: '' })
    expect((tooSlow[FIELD.speedKn] ?? '').length).toBeGreaterThan(0)
    expect(tooSlow[FIELD.speedKn]).not.toBe(blank[FIELD.speedKn])
  })
})

describe('validateForm — 연료 종류', () => {
  it('미선택은 선택 안내를 낸다', () => {
    const errors = validateForm({ ...validState(), fuelType: '' })
    expect((errors[FIELD.fuelType] ?? '').length).toBeGreaterThan(0)
  })

  it('지원 목록에 없는 코드는 거부된다 (VAL-006)', () => {
    const errors = validateForm({ ...validState(), fuelType: 'ETHANE' })
    expect(errors[FIELD.fuelType]).toContain('알 수 없는 연료 종류')
  })

  it('주어진 목록의 코드는 모두 통과한다', () => {
    // 종전에는 `FUEL_CF` 키를 순회했다. 목록이 서버에서 오므로(#542) 순회 대상도
    // 주입된 목록이다 — 고정표를 다시 읽으면 옮긴 의미가 없다.
    for (const { code } of FUELS) {
      expect(validateForm({ ...validState(), fuelType: code })).toEqual({})
    }
  })
})

describe('validateForm — 동시 표시', () => {
  it('여러 필드가 잘못되면 전부 모아서 반환한다', () => {
    // provider는 첫 위반에서 throw하므로 하나만 보인다. 화면 검증은 왕복을 없앤다.
    const errors = validateForm({
      ...validState(),
      distanceNm: '0',
      speedKn: '0',
      fuelType: '',
      fuelTon: '0',
    })
    expect(Object.keys(errors).sort()).toEqual(
      [FIELD.distanceNm, FIELD.speedKn, FIELD.fuelType, FIELD.fuelTon].sort(),
    )
  })
})

describe('toRequest', () => {
  it('fuel_uses는 길이 1의 배열이다', () => {
    const request = toRequest(validState())
    expect(request.fuel_uses).toHaveLength(1)
    expect(request.fuel_uses[0]).toEqual({ fuel_type: 'HFO', fuel_ton: 80 })
  })

  it('문자열 상태를 숫자 필드로 변환한다', () => {
    const request = toRequest(validState())
    expect(request.distance_nm).toBe(1000)
    expect(request.speed_kn).toBe(14.2)
    expect(request.regulation_year).toBe(2026)
    expect(typeof request.distance_nm).toBe('number')
    expect(typeof request.speed_kn).toBe('number')
    expect(typeof request.fuel_uses[0].fuel_ton).toBe('number')
  })

  it('계약에 확정된 필드만 포함한다 — weather_model은 넣지 않는다', () => {
    // 8/8 UI는 weather_model을 수집하지 않는다. 서버 기본값 NONE이다.
    expect(Object.keys(toRequest(validState())).sort()).toEqual([
      'distance_nm',
      'fuel_uses',
      'regulation_year',
      'speed_kn',
      'vessel_id',
    ])
  })

  it('필드명은 fuel_ton이다 — planned_fuel_ton이 아니다', () => {
    // planned_fuel_ton은 항차 생성(API_SPEC §3.3)의 필드로 계산 요청과 다르다.
    const keys = Object.keys(toRequest(validState()).fuel_uses[0])
    expect(keys).toContain('fuel_ton')
    expect(keys).not.toContain('planned_fuel_ton')
  })

  it('검증되지 않은 상태로 부르면 조용히 NaN을 만들지 않고 던진다', () => {
    expect(() => toRequest({ ...validState(), distanceNm: '' })).toThrow()
  })

})


describe('toFormErrors', () => {
  it('field가 있는 provider 오류는 해당 입력창으로 간다', () => {
    const error = new VoyageCiiError(
      'VALIDATION_ERROR',
      '연료 사용량은 0보다 커야 합니다.',
      'fuel_uses[0].fuel_ton',
    )
    expect(toFormErrors(error)).toEqual({
      [FIELD.fuelTon]: '연료 사용량은 0보다 커야 합니다.',
    })
  })

  it('field가 없는 오류는 폼 상단으로 간다', () => {
    const error = new VoyageCiiError('CALCULATION_ERROR', '계산 결과가 유효하지 않습니다.')
    expect(toFormErrors(error)).toEqual({
      [FIELD.form]: '계산 결과가 유효하지 않습니다.',
    })
  })

  it('화면에 대응 입력창이 없는 경로는 폼 상단으로 간다', () => {
    const error = new VoyageCiiError('VALIDATION_ERROR', '연료 사용량을 1건 이상 입력해 주세요.', 'fuel_uses')
    expect(toFormErrors(error)).toEqual({
      [FIELD.form]: '연료 사용량을 1건 이상 입력해 주세요.',
    })
  })

  it('VoyageCiiError가 아닌 오류도 삼키지 않는다', () => {
    // 데모 중 화면이 조용히 아무 반응도 하지 않는 것이 가장 나쁘다.
    expect(toFormErrors(new TypeError('boom'))).toEqual({ [FIELD.form]: 'boom' })
    expect(toFormErrors('문자열')[FIELD.form]).toContain('알 수 없는 오류')
  })


})

describe('validateForm — 주입된 목록이 판정을 정한다 (#542)', () => {
  /*
   * 종전 `!FUEL_CF[code]`는 화면이 고정표를 직접 읽는 구조였다. 서버가 연료를
   * 추가·비활성화해도 화면 판정은 그대로여서, 사용자는 **고른 뒤 저장 단계에서야**
   * 거부를 만났다. 목록이 판정을 정한다는 사실을 여기서 잠근다.
   */
  it('목록에 없으면 거부된다 — 코드 자체는 유효해도 마찬가지다', () => {
    const errors = validateFormWith({ ...validState(), fuelType: 'HFO' }, [])
    expect(errors[FIELD.fuelType]).toContain('알 수 없는 연료 종류')
  })

  it('목록에 있으면 통과한다 — 고정표에 없던 코드라도 마찬가지다', () => {
    const errors = validateFormWith({ ...validState(), fuelType: 'AMMONIA' }, [
      { code: 'AMMONIA', displayName: '암모니아' },
    ])
    expect(errors).toEqual({})
  })
})

/**
 * 규제연도 기본 선택 (`pickDefaultYear`).
 *
 * 종전에는 `rows[0]`이라 **항상 2023**이 걸렸다. 목록이 오름차순이고 CII 규제가
 * 2023년에 시작하기 때문이다. 보기 문제가 아니라 결과가 달라지는 문제였다 —
 * `Z_year`가 해마다 커져 `required_CII`가 다르고 등급 판정이 바뀐다.
 *
 * 올해를 **인자로 받는** 이유가 여기서 드러난다. 함수가 `new Date()`를 부르면
 * 아래 단언들을 해가 바뀔 때마다 고쳐야 한다.
 */
describe('pickDefaultYear — 규제연도 기본 선택', () => {
  /** 실제 적재된 규제연도 8개. */
  const YEARS = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]

  it('올해가 목록에 있으면 올해를 고른다', () => {
    expect(pickDefaultYear(YEARS, 2026)).toBe('2026')
    expect(pickDefaultYear(YEARS, 2023)).toBe('2023')
    expect(pickDefaultYear(YEARS, 2030)).toBe('2030')
  })

  it('첫 항목을 고르지 않는다 — 이 버그의 본체', () => {
    // rows[0]으로 돌아가면 여기서 걸린다.
    expect(pickDefaultYear(YEARS, 2026)).not.toBe('2023')
  })

  it('올해가 목록에 없으면 가장 최근 해로 떨어진다', () => {
    // 목록이 아직 올해를 담지 못한 경우. 과거로 떨어지면 3년 전 기준으로 계산된다.
    expect(pickDefaultYear(YEARS, 2031)).toBe('2030')
    expect(pickDefaultYear(YEARS, 2022)).toBe('2030')
  })

  it('정렬 순서에 기대지 않는다', () => {
    // 실 API는 오름차순으로 주지만 이 함수가 강제할 수 있는 조건이 아니다.
    // 순서가 뒤집혔을 때 마지막 항목을 고르면 가장 오래된 해가 조용히 걸린다.
    expect(pickDefaultYear([2030, 2029, 2028], 2031)).toBe('2030')
    expect(pickDefaultYear([2025, 2030, 2023], 2031)).toBe('2030')
  })

  it('이미 고른 해가 목록에 있으면 유지한다', () => {
    // 선박을 바꿀 때마다 되돌아가면 사용자가 방금 고른 값을 잃는다.
    expect(pickDefaultYear(YEARS, 2026, '2024')).toBe('2024')
  })

  it('이미 고른 해가 목록에 없으면 올해로 간다', () => {
    expect(pickDefaultYear(YEARS, 2026, '2019')).toBe('2026')
  })

  it('목록이 비면 값을 지어내지 않는다', () => {
    // 올해를 넣어 두면 서버가 지원하지 않는 해로 요청이 나간다.
    expect(pickDefaultYear([], 2026)).toBe('')
    expect(pickDefaultYear([], 2026, '2024')).toBe('')
  })

  it('문자열 비교로 놓치지 않는다 — 목록은 숫자다', () => {
    expect(pickDefaultYear([2026], 2026, '2026')).toBe('2026')
  })
})

describe('prefillFromVoyage — 상단 항차의 계획값 (#1576)', () => {
  const voyage = (over: Record<string, unknown> = {}) => ({
    status: 'PLANNED',
    plannedDistanceNm: 2300,
    plannedSpeedKn: 14,
    fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 331 }],
    ...over,
  })

  it('계획 확정 · 연료 1종 — 거리 · 속력 · 연료 · 연료량을 채운다', () => {
    expect(prefillFromVoyage(voyage())).toEqual({
      fields: { distanceNm: '2300', speedKn: '14', fuelType: 'HFO', fuelTon: '331' },
      multiFuelCount: null,
    })
  })

  it('작성 중도 채운다 — 항해 전이다', () => {
    expect(prefillFromVoyage(voyage({ status: 'DRAFT' }))).not.toBeNull()
  })

  it.each(['IN_PROGRESS', 'COMPLETED', 'CONFIRMED', 'CANCELLED', 'ARCHIVED'])(
    '%s는 채우지 않는다 — 항해 전 조건이 아니다',
    (status) => {
      expect(prefillFromVoyage(voyage({ status }))).toBeNull()
    },
  )

  it('⚠️ 연료가 여러 종이면 연료 칸을 비우고 종 수를 돌려준다 — 한 칸에 더하면 CO₂가 틀린다', () => {
    const r = prefillFromVoyage(
      voyage({
        fuelUses: [
          { fuelType: 'HFO', plannedFuelTon: 300 },
          { fuelType: 'MDO', plannedFuelTon: 31 },
        ],
      }),
    )
    expect(r).toEqual({
      fields: { distanceNm: '2300', speedKn: '14', fuelType: '', fuelTon: '' },
      multiFuelCount: 2,
    })
  })

  it('계획값이 빈 칸은 비운다 — 앞 항차의 값을 남기지 않는다', () => {
    const r = prefillFromVoyage(
      voyage({ plannedSpeedKn: null, fuelUses: [{ fuelType: 'HFO', plannedFuelTon: null }] }),
    )
    expect(r?.fields).toEqual({ distanceNm: '2300', speedKn: '', fuelType: 'HFO', fuelTon: '' })
  })

  it('연료 기록이 없으면 연료 칸을 비우고 여러 종으로 치지 않는다', () => {
    expect(prefillFromVoyage(voyage({ fuelUses: [] }))).toEqual({
      fields: { distanceNm: '2300', speedKn: '14', fuelType: '', fuelTon: '' },
      multiFuelCount: null,
    })
  })
})

/**
 * 연료 입력 방식 (#1718).
 *
 * 계약은 그대로다 — 방식이 무엇이든 요청은 `fuel_uses[0].fuel_ton` 하나다. 화면이
 * 바꾸는 것은 **그 값을 어떻게 얻는가**뿐이고, 여기서 그 셈과 검증을 잠근다.
 */
describe('연료 입력 방식 (#1718)', () => {
  function base(): VoyageCiiFormState {
    return {
      ...initialFormState(),
      vesselId: 'v-1',
      regulationYear: '2026',
      distanceNm: '1000',
      speedKn: '12',
      fuelType: 'HFO',
    }
  }

  it('총량은 넣은 값을 그대로 보낸다 — 종전과 같다', () => {
    const state = { ...base(), fuelTon: '80' }
    expect(effectiveFuelTon(state)).toBe(80)
    expect(toRequest(state).fuel_uses).toEqual([{ fuel_type: 'HFO', fuel_ton: 80 }])
  })

  it('하루 × 항해일은 거리 ÷ 속력으로 환산한다 — 1000nm · 12kn · 23.04t/일 → 80.0t', () => {
    const state = { ...base(), fuelMode: 'DAILY' as const, dailyFuelTon: '23.04' }
    // 1000 / 12 = 83.333h → 3.4722일 × 23.04 = 80.0t
    expect(effectiveFuelTon(state)).toBeCloseTo(80, 3)
    expect(toRequest(state).fuel_uses[0].fuel_ton).toBeCloseTo(80, 3)
  })

  it('제원에서 채우기는 선박의 기준 일일 연료를 쓴다 — 없으면 값이 없다', () => {
    const state = { ...base(), fuelMode: 'VESSEL' as const }
    expect(effectiveFuelTon(state, '23.04')).toBeCloseTo(80, 3)
    expect(effectiveFuelTon(state, null)).toBeNull()
  })

  it('⚠️ 속도 보정을 하지 않는다 — 속력이 기준속력과 달라도 같은 하루치를 곱한다', () => {
    /*
     * `PRD §11.4.1` cubic speed model은 기능②의 것이다. 화면이 흉내 내면 같은 이름의
     * 값이 서버와 다르게 나온다. 속력은 항해시간으로만 들어온다 — 거리 ÷ 속력.
     */
    const slow = { ...base(), speedKn: '10', fuelMode: 'DAILY' as const, dailyFuelTon: '23.04' }
    expect(effectiveFuelTon(slow)).toBeCloseTo((23.04 * (1000 / 10)) / 24, 3)
  })

  it('거리·속력이 없으면 환산하지 않는다 — 0으로 지어내지 않는다', () => {
    const state = { ...base(), distanceNm: '', fuelMode: 'DAILY' as const, dailyFuelTon: '23.04' }
    expect(voyageHours(state.distanceNm, state.speedKn)).toBeNull()
    expect(effectiveFuelTon(state)).toBeNull()
    expect(validateFormWith(state, FUELS)[FIELD.fuelTon]).toContain('항해거리')
  })

  it('하루 연료도 총량과 같은 규칙이다 — 비었거나 0 이하면 같은 자리에 오류가 선다', () => {
    const empty = { ...base(), fuelMode: 'DAILY' as const }
    expect(validateFormWith(empty, FUELS)[FIELD.fuelTon]).toContain('입력해 주세요')
    const zero = { ...base(), fuelMode: 'DAILY' as const, dailyFuelTon: '0' }
    expect(validateFormWith(zero, FUELS)[FIELD.fuelTon]).toContain('0보다 커야')
  })

  it('제원이 없는 선박에서 「제원에서 채우기」를 고르면 사유가 오류로 선다', () => {
    const state = { ...base(), fuelMode: 'VESSEL' as const }
    expect(validateFormWith(state, FUELS, null)[FIELD.fuelTon]).toContain('기준 일일 연료소모량')
    expect(validateFormWith(state, FUELS, '23.04')[FIELD.fuelTon]).toBeUndefined()
  })

  it('방식을 바꿔도 다른 방식의 값은 지워지지 않는다 — 상태가 둘 다 들고 있다', () => {
    const state = { ...base(), fuelTon: '80', fuelMode: 'DAILY' as const, dailyFuelTon: '23.04' }
    expect(effectiveFuelTon({ ...state, fuelMode: 'TOTAL' })).toBe(80)
    expect(effectiveFuelTon(state)).toBeCloseTo(80, 3)
  })
})

describe('속력 상한 60kn — VAL-009 (#1269)', () => {
  it('60은 통과하고 60.01은 막는다 — 종전에는 이 화면만 상한이 없었다', () => {
    expect(validateForm({ ...validState(), speedKn: '60' })[FIELD.speedKn]).toBeUndefined()
    expect(validateForm({ ...validState(), speedKn: '60.01' })[FIELD.speedKn]).toBeDefined()
  })
})
