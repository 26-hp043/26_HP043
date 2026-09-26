import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 선박 행의 두 칸 (#1831).
 *
 * 행은 `카드 링크 | 지도로 가는 띠` 두 칸이다. 띠에 `grid-row`만 주면 **띠가 왼쪽
 * 칸으로 간다** — 격자 자동 배치는 *행이 정해진* 항목을 자동 배치 항목보다 **먼저**
 * 놓기 때문이다. 그러면 핀이 이름 왼쪽에 서고 카드가 오른쪽으로 밀린다(1440 실측:
 * 열 폭 `80px 252px`). 화면이 깨지지는 않아 검사가 없으면 조용히 되돌아간다.
 */
const css = readFileSync(join(import.meta.dirname, 'FleetDashboard.css'), 'utf8')

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`)
  expect(start, `${selector} 규칙이 있다`).toBeGreaterThan(-1)
  return css.slice(start, css.indexOf('}', start))
}

describe('선박 행 — 카드와 지도 띠 두 칸 (#1831)', () => {
  it('행이 두 칸 격자다', () => {
    expect(block('.vessel')).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/)
  })

  it('지도 띠는 **열을 명시한다** — 행만 주면 왼쪽 칸으로 간다', () => {
    const rule = block('.vessel__locate')
    expect(rule).toMatch(/grid-column:\s*2/)
    expect(rule).toMatch(/grid-row:\s*1/)
  })

  it('카드 아래 안내는 두 칸을 가로지른다 — 띠 옆으로 밀리지 않는다', () => {
    expect(block('.vessel__note')).toMatch(/grid-column:\s*1\s*\/\s*-1/)
  })
})
