import type { Prices } from './types'

/**
 * 단가 칸 검증 — 빈칸은 「단가 없음」이라 유효하다(`PRD §12.3.2` 빈칸은 0이 아니다).
 * `min={0}`은 음수 **타이핑을 막지 않으므로** 요청 전에 여기서 거른다(서버는 `ge=0` → 422).
 */
export function isInvalidPrice(value: string): boolean {
  const text = value.trim()
  if (text === '') return false
  const n = Number(text)
  return !Number.isFinite(n) || n < 0
}

export function hasInvalidPrice(prices: Prices): boolean {
  return [...Object.values(prices.charterUsdPerDay), ...Object.values(prices.fuelUsdPerTon)].some(
    isInvalidPrice,
  )
}
