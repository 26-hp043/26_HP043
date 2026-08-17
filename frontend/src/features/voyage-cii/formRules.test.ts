import { describe, expect, it } from 'vitest'
import {
  FIELD,
  filterSupportedVessels,
  initialFormState,
  selectableFuels,
  selectableVessels,
  selectableYears,
  toFormErrors,
  toRequest,
  validateForm,
  type VoyageCiiFormState,
} from './formRules'
import { DEMO_VESSELS, FIXED_PARAMETERS, FUEL_CF, type DemoVessel } from './referenceTable'
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
    distanceNm: '1000',
    speedKn: '14.2',
    fuelType: 'HFO',
    fuelTon: '80',
  }
}

describe('filterSupportedVessels', () => {
  // 규칙 자체를 잠그는 테스트다. selectableVessels()만 부르면 현재 데이터가 1척이라
  // 필터를 지워도 통과한다 — 즉 아무것도 검사하지 않는다.
  const inTable: DemoVessel = {
    id: 'vessel-in-table',
    displayName: '고정표에 있는 배',
    shipType: 'BULK_CARRIER',
    transportCapacity: '50000',
    transportCapacityBasis: 'DWT',
    referenceCapacity: '50000',
    referenceCapacityRule: 'DWT',
  }
  const notInTable: DemoVessel = { ...inTable, id: 'vessel-not-in-table', displayName: '없는 배' }

  it('고정표에 없는 선박은 선택지에서 빠진다', () => {
    const result = filterSupportedVessels(
      [inTable, notInTable],
      [{ vesselId: 'vessel-in-table' }],
    )
    expect(result.map((v) => v.id)).toEqual(['vessel-in-table'])
  })

  it('고정표가 비면 선택지도 비운다 — 계산할 수 없는 배를 내보이지 않는다', () => {
    expect(filterSupportedVessels([inTable, notInTable], [])).toEqual([])
  })

  it('한 선박에 연도가 여러 행이어도 선택지는 1건이다', () => {
    const result = filterSupportedVessels(
      [inTable],
      [{ vesselId: 'vessel-in-table' }, { vesselId: 'vessel-in-table' }],
    )
    expect(result).toHaveLength(1)
  })

  it('선택지 순서는 DEMO_VESSELS 순서를 따른다', () => {
    const result = filterSupportedVessels(
      [notInTable, inTable],
      [{ vesselId: 'vessel-in-table' }, { vesselId: 'vessel-not-in-table' }],
    )
    expect(result.map((v) => v.id)).toEqual(['vessel-not-in-table', 'vessel-in-table'])
  })
})

describe('selectableVessels', () => {
  it('FIXED_PARAMETERS에 조합이 있는 선박만 고를 수 있다', () => {
    const supported = new Set(FIXED_PARAMETERS.map((p) => p.vesselId))
    for (const vessel of selectableVessels()) {
      expect(supported.has(vessel.id)).toBe(true)
    }
  })

  it('선택지가 DEMO_VESSELS보다 많아지지 않는다', () => {
    expect(selectableVessels().length).toBeLessThanOrEqual(DEMO_VESSELS.length)
  })

  it('모든 선택지가 계산 가능한 연도를 최소 1개 갖는다', () => {
    // 이것이 UNSUPPORTED_VESSEL·UNSUPPORTED_YEAR에 UI로 도달할 수 없다는 근거다.
    for (const vessel of selectableVessels()) {
      expect(selectableYears(vessel.id).length).toBeGreaterThan(0)
    }
  })

  it('고정표에 없는 선박은 연도가 0개다', () => {
    expect(selectableYears('00000000-0000-4000-8000-00000000ffff')).toEqual([])
  })
})

describe('selectableFuels', () => {
  it('FUEL_CF 전 항목을 순회한다', () => {
    expect(selectableFuels().map((f) => f.code).sort()).toEqual(Object.keys(FUEL_CF).sort())
  })

  it('표시명이 비어 있지 않다', () => {
    for (const fuel of selectableFuels()) {
      expect(fuel.displayName.length).toBeGreaterThan(0)
    }
  })
})

describe('initialFormState', () => {
  it('선박과 연도는 채워지고 나머지는 비어 있다', () => {
    const state = initialFormState()
    expect(state.vesselId).not.toBe('')
    expect(state.regulationYear).not.toBe('')
    expect(state.distanceNm).toBe('')
    expect(state.speedKn).toBe('')
    expect(state.fuelType).toBe('')
    expect(state.fuelTon).toBe('')
  })

  it('초기 상태의 선박·연도 조합은 그 자체로 유효하다', () => {
    const state = initialFormState()
    expect(validateForm(state)[FIELD.form]).toBeUndefined()
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

  it('FUEL_CF 8종은 모두 통과한다', () => {
    for (const code of Object.keys(FUEL_CF)) {
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
    expect(request.regulation_year).toBe(FIXED_PARAMETERS[0].year)
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

  it('demo provider가 이 요청을 그대로 받아들인다', async () => {
    // 화면 검증을 통과한 요청은 provider 검증도 통과해야 한다.
    const { createDemoProvider } = await import('./demoProvider')
    await expect(createDemoProvider().estimate(toRequest(validState()))).resolves.toBeDefined()
  })
})

describe('데모 시나리오 — 폼 입력이 #132 계약 기대값을 낸다', () => {
  // 폼 → 요청 → provider 경로 전체가 계약과 어긋나지 않는지 잠근다.
  // demoProvider.test.ts는 요청 객체를 직접 만들지만, 이 테스트는 폼 상태에서 출발한다.
  it('거리 1,000 nm · HFO 80 t → 4.982400 · C · MEDIUM', async () => {
    const { createDemoProvider } = await import('./demoProvider')
    const response = await createDemoProvider().estimate(toRequest(validState()))

    expect(response.data.attained_cii).toBe('4.982400')
    expect(response.data.required_cii).toBe('5.045066')
    expect(response.data.estimated_rating).toBe('C')
    expect(response.data.risk_level).toBe('MEDIUM')
    expect(response.data.co2_emission_ton).toBe('249.12')
    expect(response.data.next_worse_boundary_margin).toBe('0.365370')
  })

  it('속력만 바꾸면 결과가 바뀌지 않는다', async () => {
    // speed_kn은 Layer 1 계산의 피연산자가 아니다(types.ts 주석 · #132 계약).
    // 화면의 속력 보조 문구가 사실인지 확인한다.
    const { createDemoProvider } = await import('./demoProvider')
    const provider = createDemoProvider()

    const slow = await provider.estimate(toRequest({ ...validState(), speedKn: '1.0' }))
    const fast = await provider.estimate(toRequest({ ...validState(), speedKn: '25' }))

    expect(slow.data.attained_cii).toBe(fast.data.attained_cii)
    expect(slow.data.estimated_rating).toBe(fast.data.estimated_rating)
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

  it('demoProvider가 실제로 던지는 field가 전부 입력창에 매핑된다', async () => {
    const { createDemoProvider } = await import('./demoProvider')
    const provider = createDemoProvider()
    const base = toRequest(validState())

    const broken = [
      { ...base, distance_nm: 0 },
      { ...base, speed_kn: 0.5 },
      { ...base, fuel_uses: [{ fuel_type: 'HFO', fuel_ton: 0 }] },
      { ...base, fuel_uses: [{ fuel_type: 'ETHANE', fuel_ton: 80 }] },
    ]

    for (const request of broken) {
      const errors = await provider.estimate(request).then(
        () => ({}) as Record<string, string>,
        (error: unknown) => toFormErrors(error),
      )
      const [key] = Object.keys(errors)
      expect(key).toBeDefined()
      // 폼 상단이 아니라 개별 입력창에 붙어야 한다.
      expect(key).not.toBe(FIELD.form)
    }
  })
})
