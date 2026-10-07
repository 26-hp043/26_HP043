import { describe, expect, it } from 'vitest'
import { routeStyle } from './routeStyles'

describe('mode별 항로 스타일', () => {
  it('직항과 우회를 색 외 dash와 텍스트로도 구분한다', () => {
    const direct = routeStyle('comparison-direct')
    const detour = routeStyle('comparison-detour')
    // 10/7(#2315) — 두 길을 한눈에 가르려 색도 달라졌다. 색만으로 가르지 않도록 결·글은 여전히 달라야 한다.
    expect(direct.colorToken).not.toBe(detour.colorToken)
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
    // 색은 hex가 아니라 테마(라이트·다크)가 다시 정의하는 CSS custom property여야 한다.
    const themeTokens = ['--semantic-info', '--semantic-primary', '--color-warning-text']
    for (const role of roles) expect(themeTokens).toContain(routeStyle(role).colorToken)
  })
})
