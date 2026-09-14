import { describe, expect, it } from 'vitest'
import { hasInvalidPrice, isInvalidPrice } from './priceRules'

/** 단가 칸 검증 (#1069) — 빈칸은 「단가 없음」, 음수·비숫자만 잘못된 값이다. */
describe('단가 칸 검증', () => {
  it('빈칸·0·양수는 유효하다 — 빈칸은 0이 아니라 「단가 없음」(`PRD §12.3.2`)', () => {
    for (const v of ['', '  ', '0', '12000', '612.5']) expect(isInvalidPrice(v)).toBe(false)
  })

  it('⚠️ 음수·비숫자는 잘못된 값이다 — 서버는 `ge=0`으로 422를 낸다', () => {
    for (const v of ['-5', '-0.1', 'abc', '1,000']) expect(isInvalidPrice(v)).toBe(true)
  })

  it('용선료·연료 단가 어느 한 칸이라도 잘못되면 전체가 잘못이다', () => {
    expect(hasInvalidPrice({ charterUsdPerDay: { v1: '100' }, fuelUsdPerTon: { HFO: '-1' } })).toBe(true)
    expect(hasInvalidPrice({ charterUsdPerDay: { v1: '' }, fuelUsdPerTon: { HFO: '600' } })).toBe(false)
  })
})
