import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 마커 그림자 — `DESIGN_SYSTEM §9.5` 🔒 「렌더러와 무관하게 모든 마커에 건다」 (`#1302`).
 *
 * 타일 지도(`FleetMap`)와 개략도(`PositionChart`)가 **같은 그림자**를 쓴다. 종전에는 지도에만
 * 있고 개략도에는 없었는데, 규격이 적용 범위를 말하지 않아 그것이 의도인지 누락인지 판정할
 * 문장이 없었다. 이제는 한쪽이 빠지거나 값이 갈리면 여기서 실패한다.
 */
const read = (file: string) =>
  readFileSync(join(process.cwd(), 'src/features/fleet', file), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')

function filterOf(css: string, selector: string): string | null {
  for (const [, selectors, body] of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    if (!selectors.split(',').map((s) => s.trim()).includes(selector)) continue
    const m = /(?:^|;)\s*filter:\s*([^;]+)/.exec(body)
    if (m) return m[1].trim()
  }
  return null
}

describe('마커 그림자는 두 렌더러가 같다 (§9.5 · #1302)', () => {
  const map = filterOf(read('FleetMap.css'), '.fleetmap__marker svg')
  const chart = filterOf(read('PositionChart.css'), '.position-chart__ship')

  it('타일 지도 마커에 그림자가 있다', () => {
    expect(map).toMatch(/^drop-shadow\(/)
  })

  it('개략도 마커도 같은 그림자를 쓴다', () => {
    expect(chart).toBe(map)
  })

  it('개략도가 그 클래스를 실제 마커에 건다', () => {
    const tsx = readFileSync(join(process.cwd(), 'src/features/fleet/PositionChart.tsx'), 'utf-8')
    expect(tsx).toMatch(/className="position-chart__ship"/)
  })
})
