import { describe, expect, it } from 'vitest'
import { hasAnyPrice, hasInvalidPrice, hasVisiblePrice, isInvalidPrice } from './priceRules'

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

/** 이어받은 단가가 실제로 있는가 (#2020) — 공백뿐인 칸은 없는 것이다. */
describe('채운 단가 칸이 있는가', () => {
  it('용선료·연료 어느 쪽이든 한 칸이라도 채우면 있다', () => {
    expect(hasAnyPrice({ charterUsdPerDay: { v1: '15000' }, fuelUsdPerTon: {} })).toBe(true)
    expect(hasAnyPrice({ charterUsdPerDay: {}, fuelUsdPerTon: { HFO: '600' } })).toBe(true)
  })

  it('비었거나 공백뿐이면 없다', () => {
    expect(hasAnyPrice({ charterUsdPerDay: {}, fuelUsdPerTon: {} })).toBe(false)
    expect(hasAnyPrice({ charterUsdPerDay: { v1: '  ' }, fuelUsdPerTon: { HFO: '' } })).toBe(false)
  })
})

describe('보이는 칸의 단가 (#2020)', () => {
  it('⚠️ 지금 선대에 없는 선박의 용선료만 있으면 보이는 단가가 없다', () => {
    const prices = { charterUsdPerDay: { gone: '15000' }, fuelUsdPerTon: {} }
    expect(hasAnyPrice(prices)).toBe(true)
    expect(hasVisiblePrice(prices, ['v1'])).toBe(false)
  })

  it('선대에 있는 선박의 용선료나 연료 단가가 있으면 보인다', () => {
    expect(hasVisiblePrice({ charterUsdPerDay: { v1: '15000' }, fuelUsdPerTon: {} }, ['v1'])).toBe(true)
    expect(hasVisiblePrice({ charterUsdPerDay: {}, fuelUsdPerTon: { HFO: '600' } }, [])).toBe(true)
    expect(hasVisiblePrice({ charterUsdPerDay: { v1: ' ' }, fuelUsdPerTon: {} }, ['v1'])).toBe(false)
  })
})
