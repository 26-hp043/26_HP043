/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import blueLogRaw from '../../design/tokens/BlueLog.tokens.json?raw'

/**
 * 감축 계획 1단 전환점 ↔ 표 최소 폭 드리프트 가드 (`#1451`).
 *
 * ## 왜 필요한가
 *
 * 전환점(1734 · #1689)은 **표 최소 폭에서 계산한 값**이다. 누가 표에 열을 더해 `min-width`를
 * 늘리면 전환점도 함께 올라가야 하는데, 두 값은 같은 파일에서도 50줄 떨어져 있고 어느
 * 검사도 둘을 잇지 않는다 — 종전 1100이 바로 그렇게 표와 무관하게 정해진 값이었다.
 *
 * ## 무엇을 보는가
 *
 * 두 단일 때 7/12 칸이 「표 + 카드 안여백 · 테두리」를 품는 가장 좁은 뷰포트를 셸 토큰
 * (`DESIGN_SYSTEM §7.1`)에서 계산하고, 전환점이 그보다 **스크롤바 폭만큼 넉넉한지** 본다.
 * 반대로 너무 크게 잡아 넓은 화면까지 1단이 되는 것도 막는다 — 기본 프레임(1920)에서는 두 단이어야 한다.
 *
 * ## 이 검사가 못 보는 것 (#1689)
 *
 * `min-width`는 **선언값**이다. 내용이 더 넓으면 표는 선언과 무관하게 넘치는데, jsdom은
 * 레이아웃을 계산하지 않아 여기서는 잴 수 없다 — 종전 560이 실측 760보다 작았던 것을 이
 * 검사는 잡지 못했다. 열 · 문구를 바꾸면 브라우저에서 `scrollWidth`를 다시 재 이 값을 고친다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const CSS = readFileSync(join(HERE, 'FleetReduction.css'), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')

type Leaf = { $value: number }
const tokens = JSON.parse(blueLogRaw) as Record<string, Record<string, Leaf>>
const tok = (group: string, key: string) => {
  const leaf = tokens[group]?.[key]
  if (!leaf) throw new Error(`BlueLog.tokens.json에 ${group}/${key}가 없다`)
  return leaf.$value
}

/** Windows 기본 세로 스크롤바 폭. 미디어 쿼리는 이 폭을 포함한 뷰포트를 본다. */
const SCROLLBAR = 15

function px(pattern: RegExp, what: string): number {
  const match = pattern.exec(CSS)
  if (!match) throw new Error(`FleetReduction.css에서 ${what}를 찾지 못했다`)
  return Number(match[1])
}

const tableMin = px(/\.fr__main\s+\.fr__table\s*\{[^}]*min-width:\s*([0-9]+)px/, '표 최소 폭')
const breakpoint = px(
  /@media\s*\(max-width:\s*([0-9]+)px\)\s*\{\s*\.fr__grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
  '1단 전환점',
)

/**
 * 두 단일 때 왼쪽 칸이 표를 품는 가장 좁은 뷰포트.
 *
 * `.fr__grid`는 12컬럼 + 거터(`#1298`)라, 주 단 폭은 `(W − 11g) × 7/12 + 6g`이다.
 */
function narrowestTwoColumn(): number {
  const gutter = tok('grid', 'gutter')
  const shell = tok('grid', 'margin') * 2 + tok('grid', 'gnb-expanded') + gutter
  const card = tableMin + tok('spacing', 'lg') * 2 + tok('borderWidth', 'default') * 2
  const primary = tok('grid', 'split-primary')
  const columns = tok('grid', 'split-primary') + tok('grid', 'split-secondary')
  const content = ((card - (primary - 1) * gutter) * columns) / primary + (columns - 1) * gutter
  return shell + content
}

describe('감축 계획 두 단은 12컬럼이다 (#1298)', () => {
  it('`fr` 비율이 아니라 `--grid-columns` + `span`으로 나눈다 — 다른 화면과 세로선이 같다', () => {
    const grid = /\.fr__grid\s*\{([^}]*)\}/.exec(CSS)?.[1] ?? ''
    expect(grid).toMatch(/grid-template-columns:\s*repeat\(var\(--grid-columns\)/)
    expect(grid).toMatch(/gap:\s*var\(--grid-gutter\)/)
    expect(CSS).toMatch(/\.fr__main\s*\{[^}]*grid-column:\s*span var\(--grid-split-primary\)/)
    expect(CSS).toMatch(/\.fr__side\s*\{[^}]*grid-column:\s*span var\(--grid-split-secondary\)/)
  })
})

describe('감축 계획 1단 전환점 (#1451)', () => {
  it('두 단이 되는 가장 좁은 폭에서도 표가 7/12 칸에 들어간다', () => {
    expect(breakpoint + 1).toBeGreaterThanOrEqual(narrowestTwoColumn() + SCROLLBAR)
  })

  it('기본 프레임(1920)에서는 두 단이다 — 전환점을 필요 이상으로 올리지 않는다', () => {
    // #1689: 표 실측 최소 폭(760)으로는 1440 · 1600이 1단이다. 1920까지 1단이 되면 7:5가 사라진다.
    expect(breakpoint).toBeLessThan(tok('grid', 'frame-width'))
  })

  it('표 최소 폭을 실측값 아래로 되돌리지 않는다 (#1689)', () => {
    // 2026-09-22 · 1440 · 시연 데이터에서 잰 내용의 최소 폭. 열을 줄이면 다시 재고 함께 고친다.
    expect(tableMin).toBeGreaterThanOrEqual(760)
  })
})
