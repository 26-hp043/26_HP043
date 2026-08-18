import { describe, expect, it } from 'vitest'
import { DEMO_VESSELS } from '../voyage-cii/referenceTable'
import {
  FIELD,
  initialFormState,
  selectableFuels,
  toRequest,
  validateForm,
  type ComparisonFormState,
} from './requestRules'

/**
 * #511 — 항로 비교 조건 입력 규칙.
 *
 * 이 파일이 잠그는 것은 **「화면이 선박을 고르지 않는다」**는 성질이다. 종전 화면은
 * `vessel_id`를 상수로 박았고 그 값이 demo 고정표에 없어, 데모 모드에서 항로 비교가
 * 아무 입력 없이 언제나 실패했다.
 */

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

describe('selectableFuels', () => {
  it('FUEL_CF 8종을 그대로 순회한다 — 화면에 코드를 다시 적지 않는다', () => {
    const codes = selectableFuels().map((f) => f.code)
    expect(codes).toContain('HFO')
    expect(codes).toContain('LNG')
    expect(codes).toHaveLength(8)
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
