import { describe, expect, it } from 'vitest'
import { formatCapacity } from '../../display/format'
import { applicabilityHint, numberOrMissing } from './resultRules'
import type { Vessel } from './types'

function vessel(overrides: Partial<Vessel> = {}): Vessel {
  return {
    id: '00000000-0000-4000-8000-0000000000a1',
    imo_number: '9440001',
    name: 'PACIFIC STAR',
    ship_type: 'BULK_CARRIER',
    gross_tonnage: null,
    deadweight: null,
    default_fuel_type: null,
    reference_speed_kn: null,
    reference_daily_foc_ton: null,
    is_cii_applicable_hint: false,
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

describe('applicabilityHint', () => {
  it('「미해당」의 두 원인을 같은 말로 덮지 않는다', () => {
    // GT 미입력으로 인한 미해당과, GT가 있는데도 미해당인 경우는 사용자가 할 일이 다르다.
    const missing = applicabilityHint(vessel({ gross_tonnage: null }))
    const judged = applicabilityHint(vessel({ gross_tonnage: 3000 }))
    expect(missing).not.toBe(judged)
  })

  it('GT 미입력이면 채우면 다시 판정된다는 사실을 알린다', () => {
    // 표시 문구라 리터럴로 단언하지 않는다(`AGENTS §4.6`) — 지키려는 성질만 본다.
    expect(applicabilityHint(vessel({ gross_tonnage: null }))).toContain('총톤수')
  })

  it('대상이면 다음에 할 일을 알린다', () => {
    const hint = applicabilityHint(vessel({ is_cii_applicable_hint: true }))
    expect(hint).toContain('항차')
  })

  it('임계값을 화면에 박지 않는다 — 판정 기준은 서버 소관이다', () => {
    // 숫자가 문구에 있으면 서버 기준이 바뀔 때 화면만 낡는다.
    for (const v of [vessel(), vessel({ gross_tonnage: 3000 }), vessel({ is_cii_applicable_hint: true })]) {
      expect(applicabilityHint(v)).not.toMatch(/5,?000/)
    }
  })

  it('화면이 GT로 다시 판정하지 않는다 — 서버 값을 따른다', () => {
    // GT가 5,000을 넘는데 서버가 false를 줬다면 그대로 「미해당」으로 말한다.
    const hint = applicabilityHint(vessel({ gross_tonnage: 90000, is_cii_applicable_hint: false }))
    expect(hint).toBe(applicabilityHint(vessel({ gross_tonnage: 3000 })))
  })
})

describe('numberOrMissing', () => {
  it('없는 값을 빈 칸으로 두지 않는다', () => {
    expect(numberOrMissing(null)).toBe('미입력')
  })

  it('0은 미입력이 아니다', () => {
    expect(numberOrMissing(0)).not.toBe('미입력')
  })

  it('천 단위를 구분해 읽기 쉽게 만든다', () => {
    expect(numberOrMissing(50000)).toBe('50,000')
  })
})

/*
 * 용량 자릿수가 다른 화면과 같다 (#822).
 *
 * 종전 `numberOrMissing`은 `value.toLocaleString('ko-KR')`이라 **소수를 그대로 살렸다.**
 * 시드의 `6405.77`이 이 화면에서는 `6,405.77`, 선박 관리·상세에서는 `6,406`이었다.
 *
 * `DESIGN_SYSTEM §4.2`가 그 결함을 이름으로 지목하고 있다 —
 * *"용량에 자릿수 규정이 없어 같은 값이 화면마다 달랐다 (#633)"*.
 * **`#633`의 수정 대상에서 이 화면이 빠져 있었다.**
 */
describe('numberOrMissing — 용량 자릿수 (#822)', () => {
  it('소수를 살리지 않는다 — `DISPLAY_DIGITS.capacity`는 0자리다', () => {
    // 시드의 실제 DWT 값이다 (`demo_seed.py`).
    expect(numberOrMissing(6405.77)).toBe('6,406')
  })

  it('다른 화면의 포매터와 같은 답을 낸다', () => {
    // 같은 값을 두 경로로 그리면 반드시 같아야 한다 — 그것이 이 결함의 본질이다.
    expect(numberOrMissing(6405.77)).toBe(formatCapacity('6405.77'))
    expect(numberOrMissing(50000)).toBe(formatCapacity('50000'))
  })

  it('천단위 구분자를 유지한다 — `GROUPED_FIELDS`', () => {
    expect(numberOrMissing(1234567)).toBe('1,234,567')
  })

  it('`0`은 「미입력」이 아니다', () => {
    expect(numberOrMissing(0)).toBe('0')
  })
})
