/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 감축 계획은 **분할하지 않는다** — `DESIGN_SYSTEM §7.1` v2.25 (#1756 · #1757).
 *
 * ## 이 파일이 보던 것과 지금 보는 것
 *
 * 종전에는 **1단 전환점(1734) ↔ 표 최소 폭**의 드리프트를 봤다(`#1451` · `#1689`) — 두 단일
 * 때 7/12 칸이 표를 품는지를 셸 토큰에서 계산해 대조했다. `#1757`이 결론을 `§8.6` 띠로 올리고
 * 표를 전폭으로 바꾸면서 **두 단 자체가 없어졌고, 전환점도 없어졌다.** 그 계산은 지킬 대상이
 * 사라졌다.
 *
 * 대신 **되돌아오지 않는지**를 본다. 다음 사람이 오른쪽에 카드를 하나 놓고 싶어질 때
 * `--grid-split-*`를 다시 부르는 것이 가장 쉬운 길인데, 그러면 `§7.1` v2.25의 「분할하지 않는
 * 화면」에서 조용히 빠져나온다 — 화면은 깨지지 않고 결론 띠 옆이 다시 기둥이 된다.
 * `styles/inputColumn.sync.test.ts`가 입력-결과 2단 화면에 같은 가드를 두고 있다.
 *
 * ## 표 최소 폭은 그대로 지킨다
 *
 * 분할이 없어져도 표가 좁아질 수 있는 아래 한계는 남는다. `#1689`가 브라우저에서 잰 **760**을
 * 밑돌면, 좁은 창에서 열이 서로를 밀어 내용이 겹친다. 열 · 문구를 바꾸면 다시 재고 함께 고친다.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url))
const CSS = readFileSync(join(HERE, 'FleetReduction.css'), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')

describe('감축 계획은 분할하지 않는다 — DESIGN_SYSTEM §7.1 v2.25 (#1756)', () => {
  it('12컬럼 7:5를 쓰지 않는다 — 결론 띠 옆에 기둥을 다시 세우지 않는다', () => {
    expect(CSS).not.toMatch(/--grid-split-(primary|secondary)/)
    expect(CSS).not.toMatch(/\.fr__(grid|main|side)\b/)
  })

  it('1단 전환점이 없다 — 어느 폭에서든 한 단이다', () => {
    /*
     * 종전 `@media (max-width: 1734px) { .fr__grid { grid-template-columns: minmax(0, 1fr) } }`.
     * 폭에 따라 단 수가 바뀌는 규칙이 남아 있으면 분할이 되살아난 것이다.
     */
    expect(CSS).not.toMatch(/grid-template-columns:\s*repeat\(var\(--grid-columns\)/)
  })

  it('좁아지면 표가 그 자리에서 가로로 스크롤한다 — 열을 접어 숨기지 않는다', () => {
    expect(/\.fr__table-wrap\s*\{[^}]*overflow-x:\s*auto/.test(CSS)).toBe(true)
  })

  it('표 최소 폭을 실측값(760) 아래로 되돌리지 않는다 (#1689)', () => {
    const match = /\.fr__table-card\s+\.fr__table\s*\{[^}]*min-width:\s*([0-9]+)px/.exec(CSS)
    expect(match, 'FleetReduction.css에서 표 최소 폭을 찾지 못했다').not.toBeNull()
    expect(Number(match![1])).toBeGreaterThanOrEqual(760)
  })
})
