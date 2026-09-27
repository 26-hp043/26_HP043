import { describe, expect, it } from 'vitest'
import { getKnownRouteSource } from './routeGeometry'
import { routeDisclosure } from './routeDisclosure'

const SOURCE = getKnownRouteSource('searoute/marnet')!

describe('공용 항로 disclosure', () => {
  it.each(['fleet', 'comparison', 'playback'] as const)('%s 문구에 필수 네 의미를 모두 표시한다', (mode) => {
    const disclosure = routeDisclosure({ mode, source: SOURCE, kinds: ['DIRECT'] })
    expect(disclosure.visibleText).toContain('표시용')
    expect(disclosure.visibleText).toContain('실제 항해 계획이 아닙니다')
    expect(disclosure.visibleText).toContain('CII 계산 거리의 근거가 아니며')
    expect(disclosure.visibleText).toContain('AIS 실제 운항 궤적이 아닙니다')
    expect(disclosure.accessibleText).toBe(disclosure.visibleText)
  })

  it('출처와 사용자가 선택한 우회 경유점의 의미를 분리한다', () => {
    const text = routeDisclosure({ mode: 'comparison', source: SOURCE, kinds: ['DIRECT', 'DETOUR'] }).visibleText
    expect(text).toContain(SOURCE.label)
    expect(text).toContain('사용자가 선택한 경유점')
    expect(text).not.toContain('출처가 선택한 경유점')
  })

  it('우회가 있으면 어느 결이 어느 선인지 이름을 적는다 (#1853 ① · 디자인 확정)', () => {
    const text = routeDisclosure({ mode: 'comparison', source: SOURCE, kinds: ['DIRECT', 'DETOUR'] }).visibleText
    // 직항은 긴 점선, 우회는 짧은 점선 — 매칭을 「꺾인 쪽이 우회」라는 추론에 맡기지 않는다
    expect(text).toMatch(/직항선\(긴 점선\)/)
    expect(text).toMatch(/우회선\(짧은 점선\)/)
    expect(text).toContain('실제 항해 계획이 아닙니다')
  })

  it('SeaRoute 실패를 GREAT_CIRCLE fallback으로 설명하지 않는다', () => {
    const text = routeDisclosure({ mode: 'fleet', source: SOURCE, kinds: ['DIRECT'] }).visibleText
    expect(text).not.toMatch(/GREAT_CIRCLE|대권선|fallback/i)
  })

  it('계획 waypoint는 SeaRoute 우회와 구분하고 실제 운항 결과로 오인시키지 않는다', () => {
    const text = routeDisclosure({
      mode: 'playback', source: SOURCE, kinds: ['DIRECT'],
      derivation: { kind: 'WAYPOINT', waypoints: [
        { order: 1, coordinate: [129, 35] }, { order: 2, coordinate: [103, 1] },
      ] },
    }).visibleText
    expect(text).toMatch(/명시적으로 제공한 계획 waypoint 순서/)
    expect(text).toMatch(/실제 운항 결과가 아닙니다/)
    expect(text).toMatch(/AIS 실제 운항 궤적이 아닙니다/)
    expect(text).not.toMatch(/사용자가 선택한 경유점/)
  })
})
