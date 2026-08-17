import { describe, expect, it } from 'vitest'
import {
  FIELD,
  NAME_MAX_LENGTH,
  initialFormState,
  selectableFuels,
  specGapNotice,
  toFormErrors,
  toRequest,
  validateForm,
  type VesselFormState,
} from './formRules'
import { VesselRegistrationError } from './provider'

/**
 * 선박 등록 폼 규칙 (#441).
 *
 * 경계값을 **함수 인자로** 넣는다. 화면 조작으로는 「7자리인지 7자리 이상인지」,
 * 「`> 0`인지 `>= 0`인지」를 정확히 찌르기 어렵다(`#135` formRules.test.ts와 같은 이유).
 */

function state(overrides: Partial<VesselFormState> = {}): VesselFormState {
  return {
    ...initialFormState(),
    imoNumber: '9440001',
    name: 'PACIFIC STAR',
    shipType: 'BULK_CARRIER',
    ...overrides,
  }
}

describe('initialFormState', () => {
  it('선종에 기본값을 넣지 않는다 — 고른 것과 기본값이 구분되어야 한다', () => {
    expect(initialFormState().shipType).toBe('')
  })

  it('모든 칸이 비어 있다', () => {
    expect(Object.values(initialFormState()).every((value) => value === '')).toBe(true)
  })
})

describe('validateForm — 필수 3항목', () => {
  it('통과하는 최소 입력에는 오류가 없다', () => {
    expect(validateForm(state())).toEqual({})
  })

  it('IMO 번호가 비면 잡는다', () => {
    expect(validateForm(state({ imoNumber: '' }))).toHaveProperty(FIELD.imoNumber)
  })

  it('IMO 번호는 정확히 7자리다 (VAL-003)', () => {
    // 6자리·8자리·문자 혼합 모두 거부. 서버 Pydantic 패턴 `^\d{7}$`와 같은 규칙이다.
    expect(validateForm(state({ imoNumber: '944000' }))).toHaveProperty(FIELD.imoNumber)
    expect(validateForm(state({ imoNumber: '94400012' }))).toHaveProperty(FIELD.imoNumber)
    expect(validateForm(state({ imoNumber: '944000A' }))).toHaveProperty(FIELD.imoNumber)
    expect(validateForm(state({ imoNumber: '9440001' }))).not.toHaveProperty(FIELD.imoNumber)
  })

  it('선행 0이 있는 IMO도 통과한다 — 문자열로 다루는 이유다', () => {
    expect(validateForm(state({ imoNumber: '0123456' }))).not.toHaveProperty(FIELD.imoNumber)
  })

  it('선명은 1~100자다 (VAL-001)', () => {
    expect(validateForm(state({ name: '' }))).toHaveProperty(FIELD.name)
    expect(validateForm(state({ name: 'A'.repeat(NAME_MAX_LENGTH) }))).not.toHaveProperty(
      FIELD.name,
    )
    expect(validateForm(state({ name: 'A'.repeat(NAME_MAX_LENGTH + 1) }))).toHaveProperty(
      FIELD.name,
    )
  })

  it('공백만 있는 선명은 입력이 아니다', () => {
    expect(validateForm(state({ name: '   ' }))).toHaveProperty(FIELD.name)
  })

  it('선종을 고르지 않으면 잡는다', () => {
    expect(validateForm(state({ shipType: '' }))).toHaveProperty(FIELD.shipType)
  })

  it('13종에 없는 선종은 서버 422를 기다리지 않고 잡는다 (VAL-004 방어선)', () => {
    expect(validateForm(state({ shipType: 'BULK_CARIER' }))).toHaveProperty(FIELD.shipType)
  })
})

describe('validateForm — 제원은 선택 입력이다', () => {
  it('제원이 전부 비어도 오류가 아니다 (PRD §20 O-11)', () => {
    // **이 이슈의 핵심 계약**이다. 폼이 제원을 필수로 막으면 명세가 열어 둔 등록을
    // 화면이 막는다 — `vessel.deadweight`는 `DB_SCHEMA §2.1`상 nullable이다.
    const errors = validateForm(
      state({ deadweight: '', grossTonnage: '', referenceSpeedKn: '', defaultFuelType: '' }),
    )
    expect(errors).toEqual({})
  })

  it('값이 있으면 0보다 커야 한다 (VAL-002)', () => {
    expect(validateForm(state({ deadweight: '0' }))).toHaveProperty(FIELD.deadweight)
    expect(validateForm(state({ deadweight: '-1' }))).toHaveProperty(FIELD.deadweight)
    expect(validateForm(state({ grossTonnage: '0' }))).toHaveProperty(FIELD.grossTonnage)
    expect(validateForm(state({ referenceSpeedKn: '0' }))).toHaveProperty(
      FIELD.referenceSpeedKn,
    )
    expect(validateForm(state({ referenceDailyFocTon: '0' }))).toHaveProperty(
      FIELD.referenceDailyFocTon,
    )
  })

  it('0과 빈 칸을 구분한다 — 빈 칸은 「모른다」이고 0은 위반이다', () => {
    expect(validateForm(state({ deadweight: '' }))).not.toHaveProperty(FIELD.deadweight)
    expect(validateForm(state({ deadweight: '0' }))).toHaveProperty(FIELD.deadweight)
  })

  it('숫자로 읽을 수 없는 값을 통과시키지 않는다', () => {
    expect(validateForm(state({ deadweight: '오만톤' }))).toHaveProperty(FIELD.deadweight)
  })

  it('연료 마스터에 없는 코드는 거부한다', () => {
    expect(validateForm(state({ defaultFuelType: 'PLUTONIUM' }))).toHaveProperty(
      FIELD.defaultFuelType,
    )
    expect(validateForm(state({ defaultFuelType: 'HFO' }))).not.toHaveProperty(
      FIELD.defaultFuelType,
    )
  })

  it('위반을 전부 모아 돌려준다 — 왕복을 만들지 않는다', () => {
    const errors = validateForm(
      state({ imoNumber: '', name: '', shipType: '', deadweight: '-1' }),
    )
    expect(Object.keys(errors).sort()).toEqual(
      [FIELD.imoNumber, FIELD.name, FIELD.shipType, FIELD.deadweight].sort(),
    )
  })
})

describe('specGapNotice — 계산할 수 없다는 사실을 알린다', () => {
  it('DWT 기반 선종에서 DWT가 비면 안내한다', () => {
    expect(specGapNotice(state({ shipType: 'BULK_CARRIER', deadweight: '' }))).not.toBeNull()
  })

  it('DWT 기반 선종에 GT만 넣어도 안내가 유지된다 — 축이 다르면 계산되지 않는다', () => {
    // 「DWT 또는 GT 하나라도 있으면 된다」로 안내하면 틀린 안내가 된다(`PRD §3.3.3`).
    const notice = specGapNotice(
      state({ shipType: 'BULK_CARRIER', deadweight: '', grossTonnage: '25000' }),
    )
    expect(notice).not.toBeNull()
  })

  it('GT 기반 선종은 GT를 본다', () => {
    expect(
      specGapNotice(state({ shipType: 'CRUISE_PASSENGER', grossTonnage: '', deadweight: '50000' })),
    ).not.toBeNull()
    expect(
      specGapNotice(state({ shipType: 'CRUISE_PASSENGER', grossTonnage: '90000' })),
    ).toBeNull()
  })

  it('축에 해당하는 값이 있으면 안내하지 않는다', () => {
    expect(specGapNotice(state({ shipType: 'TANKER', deadweight: '50000' }))).toBeNull()
  })

  it('선종을 고르지 않았으면 안내하지 않는다 — 무엇이 필요한지 아직 정해지지 않았다', () => {
    expect(specGapNotice(state({ shipType: '', deadweight: '' }))).toBeNull()
  })

  it('안내가 등록을 막는 말로 읽히지 않는다', () => {
    // 표시 문구라 리터럴로 단언하지 않는다(`AGENTS §4.6`). 지키려는 성질만 본다 —
    // 「등록은 된다」와 「CII는 계산되지 않는다」가 함께 있어야 한다.
    const notice = specGapNotice(state({ shipType: 'BULK_CARRIER', deadweight: '' })) ?? ''
    expect(notice).toContain('등록')
    expect(notice).toContain('CII')
  })
})

describe('toRequest', () => {
  it('빈 선택 입력은 키를 넣지 않는다', () => {
    const request = toRequest(state())
    expect(request).toEqual({
      imo_number: '9440001',
      name: 'PACIFIC STAR',
      ship_type: 'BULK_CARRIER',
    })
    expect('deadweight' in request).toBe(false)
    expect('default_fuel_type' in request).toBe(false)
  })

  it('값이 있는 선택 입력은 숫자로 넣는다 — Layer 1 문자열이 아니다', () => {
    const request = toRequest(
      state({
        grossTonnage: '25000',
        deadweight: '50000.5',
        referenceSpeedKn: '14',
        referenceDailyFocTon: '35',
        defaultFuelType: 'HFO',
      }),
    )
    expect(request.gross_tonnage).toBe(25000)
    expect(request.deadweight).toBe(50000.5)
    expect(request.reference_speed_kn).toBe(14)
    expect(request.reference_daily_foc_ton).toBe(35)
    expect(request.default_fuel_type).toBe('HFO')
  })

  it('앞뒤 공백을 잘라 보낸다', () => {
    const request = toRequest(state({ imoNumber: ' 9440001 ', name: '  PACIFIC STAR  ' }))
    expect(request.imo_number).toBe('9440001')
    expect(request.name).toBe('PACIFIC STAR')
  })

  it('검증하지 않은 상태로 부르면 던진다', () => {
    expect(() => toRequest(state({ shipType: '' }))).toThrow()
    expect(() => toRequest(state({ imoNumber: '' }))).toThrow()
  })
})

describe('toFormErrors', () => {
  it('필드가 있는 오류는 그 입력창에 붙인다', () => {
    const error = new VesselRegistrationError('VALIDATION_ERROR', '값이 올바르지 않습니다.', 'deadweight')
    expect(toFormErrors(error)).toEqual({ deadweight: '값이 올바르지 않습니다.' })
  })

  it('중복 IMO(409)는 IMO 입력창에 붙인다 — 서버는 field를 주지 않는다', () => {
    // 폼 상단 배너로 두면 「어디를 고쳐야 하는지」가 사라진다.
    const error = new VesselRegistrationError('CONFLICT', '이미 등록된 IMO 번호입니다: 9440001')
    expect(toFormErrors(error)).toEqual({
      [FIELD.imoNumber]: '이미 등록된 IMO 번호입니다: 9440001',
    })
  })

  it('화면에 입력창이 없는 필드 경로는 폼 상단으로 보낸다', () => {
    const error = new VesselRegistrationError('VALIDATION_ERROR', '알 수 없는 필드', 'imos_number')
    expect(toFormErrors(error)).toEqual({ [FIELD.form]: '알 수 없는 필드' })
  })

  it('데모 모드 실패도 폼 상단에 보인다', () => {
    const error = new VesselRegistrationError('DEMO_UNAVAILABLE', '데모에서는 등록할 수 없습니다.')
    expect(toFormErrors(error)).toEqual({ [FIELD.form]: '데모에서는 등록할 수 없습니다.' })
  })

  it('provider 밖의 오류도 삼키지 않는다', () => {
    expect(toFormErrors(new Error('boom'))).toEqual({ [FIELD.form]: 'boom' })
    expect(toFormErrors('문자열')[FIELD.form]).toBeTruthy()
  })
})

describe('selectableFuels', () => {
  it('연료 마스터 8종을 그대로 순회한다', () => {
    expect(selectableFuels()).toHaveLength(8)
    expect(selectableFuels().map((fuel) => fuel.code)).toContain('HFO')
  })
})
