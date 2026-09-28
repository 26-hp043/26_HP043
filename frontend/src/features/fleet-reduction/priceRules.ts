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

/**
 * 채운 단가 칸이 하나라도 있는가 (#2020).
 *
 * 직전 계획에서 단가를 이어받았다고 말하려면 **이어받은 값이 실제로 있어야** 한다 — 단가 없이
 * 저장한 계획을 이어받고 「이어받았습니다」라고 적으면, 빈 칸을 보는 사용자에게 거짓이 된다.
 */
export function hasAnyPrice(prices: Prices): boolean {
  return [...Object.values(prices.charterUsdPerDay), ...Object.values(prices.fuelUsdPerTon)].some(
    (value) => value.trim() !== '',
  )
}
