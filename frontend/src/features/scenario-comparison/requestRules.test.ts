import { describe, expect, it } from 'vitest'
import { DEMO_VESSELS } from '../voyage-cii/referenceTable'
import {
  FIELD,
  initialFormState,
  toRequest as toRequestWith,
  validateForm as validateFormWith,
  type ComparisonFormState,
} from './requestRules'

/**
 * #511 — 항로 비교 조건 입력 규칙.
 *
 * 이 파일이 잠그는 것은 **「화면이 선박을 고르지 않는다」**는 성질이다. 종전 화면은
 * `vessel_id`를 상수로 박았고 그 값이 demo 고정표에 없어, 데모 모드에서 항로 비교가
 * 아무 입력 없이 언제나 실패했다.
 */


/**
 * 연료 선택지 — 종전 고정표 `FUEL_CF`의 8종과 같은 코드 집합이다 (#542).
 *
 * `validateForm`이 목록을 **인자로 받도록** 바뀌었다. 서버(`GET /parameters/fuel-types`)가
 * 주는 값이므로 화면 규칙이 그 목록을 직접 알지 않는다 — 그 사실을 테스트에서도
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
const validateForm = (state: ComparisonFormState) => validateFormWith(state, FUELS)
const toRequest = (state: ComparisonFormState) => toRequestWith(state, FUELS)



function state(overrides: Partial<ComparisonFormState> = {}): ComparisonFormState {
  return { ...initialFormState(), vesselId: DEMO_VESSELS[0].id, ...overrides }
}

describe('initialFormState — 선박에 기본값을 넣지 않는다', () => {
  it('선박은 비어 있다', () => {
    // 목록을 읽기 전에 아무 배나 골라 두면 종전 버그(고정표에 없는 UUID)가 재발한다.
    expect(initialFormState().vesselId).toBe('')
  })

  it('나머지 조건은 종전 DEMO_REQUEST 값을 그대로 물려받는다', () => {
    const initial = initialFormState()
    expect(initial.regulationYear).toBe('2026')
    expect(initial.baseDistanceNm).toBe('1000')
    expect(initial.baseSpeedKn).toBe('12.8')
    expect(initial.baseDailyFocTon).toBe('26.88')
    expect(initial.fuelType).toBe('HFO')
  })
})

describe('validateForm', () => {
  it('선박을 고르지 않으면 오류다 — 상수로 채우지 않는다', () => {
    expect(validateForm(state({ vesselId: '' }))).toHaveProperty(FIELD.vesselId)
  })

  it('조건이 다 채워져 있으면 오류가 없다', () => {
    expect(validateForm(state())).toEqual({})
  })

  it('거리·속력·일일 연료는 필수이고 0보다 커야 한다 (VAL-002)', () => {
    expect(validateForm(state({ baseDistanceNm: '' }))).toHaveProperty(FIELD.baseDistanceNm)
    expect(validateForm(state({ baseSpeedKn: '0' }))).toHaveProperty(FIELD.baseSpeedKn)
    expect(validateForm(state({ baseDailyFocTon: '-1' }))).toHaveProperty(
      FIELD.baseDailyFocTon,
    )
  })

  it('숫자로 읽을 수 없는 값을 잡는다', () => {
    expect(validateForm(state({ baseDistanceNm: '천' }))).toHaveProperty(
      FIELD.baseDistanceNm,
    )
  })

  it('빈 칸이 0으로 통과하지 않는다 — Number("")는 0이다', () => {
    const errors = validateForm(state({ baseSpeedKn: '' }))
    expect(errors[FIELD.baseSpeedKn]).toContain('입력해')
  })

  it('규제연도는 정수여야 한다', () => {
    expect(validateForm(state({ regulationYear: '2026.5' }))).toHaveProperty(
      FIELD.regulationYear,
    )
  })

  it('알 수 없는 연료는 서버 422를 기다리지 않고 화면에서 잡는다 (VAL-006)', () => {
    expect(validateForm(state({ fuelType: 'ETHANE' }))).toHaveProperty(FIELD.fuelType)
  })

  it('위반을 전부 모아 돌려준다 — 한 번에 고칠 수 있어야 한다', () => {
    const errors = validateForm(
      state({ vesselId: '', baseDistanceNm: '', fuelType: 'ETHANE' }),
    )
    expect(Object.keys(errors).sort()).toEqual(
      [FIELD.vesselId, FIELD.baseDistanceNm, FIELD.fuelType].sort(),
    )
  })
})

describe('toRequest', () => {
  it('문자열 상태를 숫자 요청으로 옮긴다', () => {
    expect(toRequest(state())).toEqual({
      vessel_id: DEMO_VESSELS[0].id,
      regulation_year: 2026,
      base_distance_nm: 1000,
      base_speed_kn: 12.8,
      base_daily_foc_ton: 26.88,
      fuel_type: 'HFO',
    })
  })

  it('검증되지 않은 상태로 부르면 던진다', () => {
    expect(() => toRequest(state({ vesselId: '' }))).toThrow('검증되지 않은')
  })
})


describe('회귀 고정 — 종전 하드코딩 상수가 demo에서 실패했다 (#511)', () => {
  it('고정표에는 …0001 한 척뿐이라 …0003은 없다', () => {
    // 이 대조가 이번 버그의 전부다. 상수 `…0003`은 이 목록에 없었다.
    expect(DEMO_VESSELS.map((v) => v.id)).not.toContain(
      '00000000-0000-4000-8000-000000000003',
    )
  })

  it('선박은 목록에서 골라야 하므로, 고정표에 있는 값이면 검증을 통과한다', () => {
    expect(validateForm(state({ vesselId: DEMO_VESSELS[0].id }))).toEqual({})
  })
})

describe('validateForm — 주입된 목록이 판정을 정한다 (#542)', () => {
  it('목록에 없으면 거부된다', () => {
    expect(validateFormWith(state({ fuelType: 'HFO' }), [])).toHaveProperty(FIELD.fuelType)
  })

  it('목록에 있으면 통과한다 — 고정표에 없던 코드라도 마찬가지다', () => {
    const errors = validateFormWith(state({ fuelType: 'AMMONIA' }), [
      { code: 'AMMONIA', displayName: '암모니아' },
    ])
    expect(errors).not.toHaveProperty(FIELD.fuelType)
  })
})
