import { describe, expect, it } from 'vitest'
import { routeStyle } from './routeStyles'

describe('mode별 항로 스타일', () => {
  it('직항과 우회를 색 외 dash와 텍스트로 구분한다', () => {
    const direct = routeStyle('comparison-direct')
    const detour = routeStyle('comparison-detour')
    expect(direct.colorToken).toBe(detour.colorToken)
    expect(direct.dash).not.toEqual(detour.dash)
    expect(direct.text).not.toBe(detour.text)
  })

  it('playback 진행·잔여를 width·opacity·dash·텍스트로 구분한다', () => {
    const traveled = routeStyle('playback-traveled')
    const remaining = routeStyle('playback-remaining')
    expect([traveled.width, traveled.opacity, traveled.dash, traveled.text])
      .not.toEqual([remaining.width, remaining.opacity, remaining.dash, remaining.text])
  })

  it('세 mode 모두 dark mode 대응 CSS token만 사용하고 hard-coded color가 없다', () => {
    const roles = ['fleet-current', 'comparison-direct', 'comparison-detour', 'playback-traveled', 'playback-remaining'] as const
    expect(roles.map((role) => routeStyle(role).colorToken)).toEqual(roles.map(() => '--semantic-info'))
  })
})
