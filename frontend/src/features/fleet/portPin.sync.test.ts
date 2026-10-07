import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 항구 핀은 **배 마커보다 작다** — `DESIGN_SYSTEM §9.5` 〔확정 2026-10-07 · `#2154`〕.
 *
 * ## 무엇을 막는가
 *
 * 배가 항구에 있으면 두 표시가 **겹친다.** 작은 쪽이 핀이어야 배가 읽히므로, 절이 정한
 * 것은 값이 아니라 **관계**다(치수는 `§0.2`대로 Figma 소관). 그래서 값을 박지 않고
 * **핀 < 마커**를 단언한다 — 값을 박으면 Figma가 둘을 함께 키울 때 이 검사가 규격 대신
 * 옛 값을 지킨다.
 *
 * 종전에는 `§9.5`가 모양(무채색 원형)만 정해 크기·테두리가 개발 임시안이었고, 그동안
 * 이 관계를 지키는 검사가 없었다.
 */
const CSS = readFileSync(join(process.cwd(), 'src/features/fleet/FleetMap.css'), 'utf-8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

function pxOf(selector: string, prop: string): number {
  const rule = new RegExp(`${selector.replace('.', '\\.')}\\s*\\{([^}]*)\\}`).exec(CSS)
  expect(rule, `규칙을 찾지 못했습니다: ${selector}`).not.toBeNull()
  const value = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*(\\d+)px`).exec(rule![1])
  expect(value, `${selector}의 ${prop}이 px 숫자가 아닙니다`).not.toBeNull()
  return Number(value![1])
}

describe('항구 핀이 배 마커보다 작다 (#2154)', () => {
  const pin = pxOf('.fleetmap__port', 'width')
  const marker = pxOf('.fleetmap__marker svg', 'width')

  it('둘을 실제로 읽었다 — 파서가 조용히 0을 내지 않게', () => {
    expect(pin).toBeGreaterThan(0)
    expect(marker).toBeGreaterThan(0)
  })

  it('핀이 마커보다 작다', () => {
    expect(pin).toBeLessThan(marker)
  })

  it('핀은 정원이다 — 폭과 높이가 같다', () => {
    expect(pxOf('.fleetmap__port', 'height')).toBe(pin)
  })

  it('핀에 등급 토큰을 쓰지 않는다 — 배가 아니다 (§9.5)', () => {
    const rule = /\.fleetmap__port\s*\{([^}]*)\}/.exec(CSS)
    expect(rule).not.toBeNull()
    expect(rule![1]).not.toMatch(/--cii-/)
  })
})
