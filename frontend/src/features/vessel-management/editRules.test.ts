import { describe, expect, it } from 'vitest'
import type { Vessel } from '../vessel-registration/types'
import {
  EDIT_FIELD,
  clearAttemptNotice,
  isEmptyPatch,
  recalcNotice,
  toEditState,
  toUpdateRequest,
  validateEdit as validateEditWith,
  type VesselEditState,
} from './editRules'

/**
 * #510 — 선박 수정 폼 규칙.
 *
 * 여기서 잠그는 것은 **PATCH의 의미**다. `services/vessel.py:230`가
 * *「`None`은 "이 필드는 안 바꾼다"다 (…) GT를 지우는 기능은 PATCH에 없다」*로
 * 규정하므로, 화면이 그와 다르게 동작하면 사용자는 「저장했는데 안 바뀐다」를 겪는다.
 */

function vessel(overrides: Partial<Vessel> = {}): Vessel {
  return {
    id: '00000000-0000-4000-8000-000000000001',
    imo_number: '0000001',
    name: '샘플 벌크선',
    ship_type: 'BULK_CARRIER',
    gross_tonnage: 30000,
    deadweight: 50000,
    default_fuel_type: null,
    reference_speed_kn: null,
    reference_daily_foc_ton: null,
    is_cii_applicable_hint: true,
    underway_state: null,
    detail_status: null,
    current_lat: null,
    current_lon: null,
    position_updated_at: null,
    created_at: null,
    updated_at: null,
    ...overrides,
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
const validateEdit = (state: VesselEditState) => validateEditWith(state, FUELS)

function state(overrides: Partial<VesselEditState> = {}): VesselEditState {
  return { ...toEditState(vessel()), ...overrides }
}

describe('toEditState — 서버 값을 폼으로', () => {
  it('null 제원은 빈 칸이 된다', () => {
    const s = toEditState(vessel())
    expect(s.referenceSpeedKn).toBe('')
    expect(s.referenceDailyFocTon).toBe('')
    expect(s.defaultFuelType).toBe('')
  })

  it('숫자에 천단위 구분자를 넣지 않는다 — 다시 파싱되는 값이다', () => {
    // `50,000`이 들어가면 `Number('50,000')`이 NaN이라 건드리지도 않은 칸이 오류가 된다.
    expect(toEditState(vessel()).deadweight).toBe('50000')
    expect(toEditState(vessel()).grossTonnage).toBe('30000')
  })
})

describe('validateEdit — 등록과 다른 규칙', () => {
  it('선명을 비우면 오류다 — PATCH에서는 조용히 무시되기 때문이다', () => {
    expect(validateEdit(state({ name: '   ' }))).toHaveProperty(EDIT_FIELD.name)
  })

  it('선종을 비우면 오류다', () => {
    expect(validateEdit(state({ shipType: '' }))).toHaveProperty(EDIT_FIELD.shipType)
  })

  it('알 수 없는 선종은 서버 422를 기다리지 않고 화면에서 잡는다 (VAL-004)', () => {
    expect(validateEdit(state({ shipType: 'NO_SUCH_TYPE' }))).toHaveProperty(
      EDIT_FIELD.shipType,
    )
  })

  it('제원은 비어도 오류가 아니다 — 선택 입력이다 (PRD §20 O-11)', () => {
    expect(validateEdit(state({ grossTonnage: '', deadweight: '' }))).toEqual({})
  })

  it('제원에 0 이하를 넣으면 오류다 (VAL-002)', () => {
    expect(validateEdit(state({ deadweight: '0' }))).toHaveProperty(EDIT_FIELD.deadweight)
    expect(validateEdit(state({ referenceSpeedKn: '-1' }))).toHaveProperty(
      EDIT_FIELD.referenceSpeedKn,
    )
  })

  it('숫자로 읽을 수 없는 제원은 오류다', () => {
    expect(validateEdit(state({ grossTonnage: '삼만' }))).toHaveProperty(
      EDIT_FIELD.grossTonnage,
    )
  })

  it('알 수 없는 연료 종류는 오류다', () => {
    expect(validateEdit(state({ defaultFuelType: 'NO_SUCH_FUEL' }))).toHaveProperty(
      EDIT_FIELD.defaultFuelType,
    )
  })
})

describe('toUpdateRequest — 바뀐 것만 싣는다', () => {
  it('아무것도 바꾸지 않으면 빈 본문이다', () => {
    const patch = toUpdateRequest(vessel(), state())
    expect(patch).toEqual({})
    expect(isEmptyPatch(patch)).toBe(true)
  })

  it('바꾼 필드만 들어간다', () => {
    const patch = toUpdateRequest(vessel(), state({ name: '새 이름' }))
    expect(patch).toEqual({ name: '새 이름' })
  })

  it('같은 값을 다시 넣어도 싣지 않는다 — GT 재전송은 hint 재산정을 부른다', () => {
    // `services/vessel.py:271` — gross_tonnage가 주어지면 is_cii_applicable_hint를
    // 매번 다시 계산한다. 바뀌지 않은 값을 보낼 이유가 없다.
    expect(toUpdateRequest(vessel(), state({ grossTonnage: '30000' }))).toEqual({})
  })

  it('imo_number는 어떤 경우에도 본문에 없다 (API_SPEC §2.4)', () => {
    // 서버 스키마가 `extra="forbid"`이고 `imo_number`를 갖지 않는다.
    const patch = toUpdateRequest(vessel(), state({ name: '새 이름' }))
    expect(patch).not.toHaveProperty('imo_number')
  })

  it('빈 칸은 키를 넣지 않는다 — null을 보내도 서버에서 「안 바꾼다」다', () => {
    const patch = toUpdateRequest(
      vessel({ deadweight: 50000 }),
      state({ deadweight: '' }),
    )
    expect(patch).not.toHaveProperty('deadweight')
  })

  it('없던 값을 새로 채우면 실린다', () => {
    const patch = toUpdateRequest(vessel(), state({ referenceDailyFocTon: '18.5' }))
    expect(patch).toEqual({ reference_daily_foc_ton: 18.5 })
  })
})

describe('clearAttemptNotice — 지울 수 없다는 사실을 알린다', () => {
  it('값이 있던 칸을 비우면 안내한다', () => {
    const notice = clearAttemptNotice(vessel(), state({ deadweight: '' }))
    expect(notice).not.toBeNull()
    expect(notice).toContain('재화중량톤수(DWT)')
    expect(notice).toContain('저장되지 않습니다')
  })

  it('원래 비어 있던 칸은 안내하지 않는다 — 지우려 한 것이 아니다', () => {
    expect(clearAttemptNotice(vessel(), state({ referenceSpeedKn: '' }))).toBeNull()
  })

  it('여러 칸을 비우면 전부 이름을 적는다', () => {
    const source = vessel({ reference_speed_kn: 16.5 })
    const notice = clearAttemptNotice(
      source,
      { ...toEditState(source), deadweight: '', referenceSpeedKn: '' },
    )
    expect(notice).toContain('재화중량톤수(DWT)')
    expect(notice).toContain('기준속도')
  })
})

describe('recalcNotice — 재계산이 걸리는 변경 (PRD §8.4, #283)', () => {
  it('DWT를 바꾸면 안내한다', () => {
    expect(recalcNotice(vessel(), state({ deadweight: '52000' }))).not.toBeNull()
  })

  it('GT를 바꾸면 안내한다', () => {
    expect(recalcNotice(vessel(), state({ grossTonnage: '31000' }))).not.toBeNull()
  })

  it('선명만 바꾸면 안내하지 않는다 — 계산 입력이 아니다', () => {
    expect(recalcNotice(vessel(), state({ name: '새 이름' }))).toBeNull()
  })

  it('같은 값을 다시 넣으면 안내하지 않는다 — 서버도 표시를 만들지 않는다', () => {
    expect(recalcNotice(vessel(), state({ deadweight: '50000' }))).toBeNull()
  })
})

describe('validateEdit — 주입된 목록이 판정을 정한다 (#542)', () => {
  it('목록에 없으면 거부된다', () => {
    expect(validateEditWith(state({ defaultFuelType: 'HFO' }), [])).toHaveProperty(
      EDIT_FIELD.defaultFuelType,
    )
  })

  it('목록에 있으면 통과한다 — 고정표에 없던 코드라도 마찬가지다', () => {
    expect(
      validateEditWith(state({ defaultFuelType: 'AMMONIA' }), [
        { code: 'AMMONIA', displayName: '암모니아' },
      ]),
    ).not.toHaveProperty(EDIT_FIELD.defaultFuelType)
  })
})
