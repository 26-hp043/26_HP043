/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

/**
 * 자산 없는 개략도의 최대 폭 — CSS · `DESIGN_SYSTEM §9.5` · 이름표 크기가 한 값이다 (#1883).
 *
 * `§9.5`(v2.28 · `#1821`)가 상한을 `1,049px`로 적으며 **기하에서 계산했다**(이름표가 뷰박스
 * 유저 단위라 화면 크기 = `LABEL_FONT × 박스 폭 / 480`). 2026-09-25에 지도 자산을 막고 1440 ·
 * 1920에서 실측해 폭 1,049 · 이름표 17.5px로 같음을 확인했다. 셋 중 하나만 바뀌면 이름표가
 * `§3` 범위(13~18) 밖으로 나가거나 문서가 틀린 값을 말한다 — 그것을 여기서 잡는다.
 */
const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf-8')

const css = read('./FleetDashboard.css')
const chart = read('./PositionChart.tsx')
const doc = read('../../../../DESIGN_SYSTEM.md')

function cssMaxWidth(): number {
  const match = /\.fleet__chartbox \.position-chart\s*\{[^}]*max-inline-size:\s*(\d+)px/.exec(css)
  expect(match, 'FleetDashboard.css에서 개략도 최대 폭을 찾지 못했다').not.toBeNull()
  return Number(match![1])
}

function constant(name: string): number {
  const match = new RegExp(`const ${name} = (\\d+)`).exec(chart)
  expect(match, `PositionChart.tsx에서 ${name}을 찾지 못했다`).not.toBeNull()
  return Number(match![1])
}

describe('자산 없는 개략도의 최대 폭 (#1883 · §9.5)', () => {
  it('CSS 상한이 §9.5가 적은 값과 같다', () => {
    const documented = /상한은 `([\d,]+)px`/.exec(doc)
    expect(documented, 'DESIGN_SYSTEM §9.5에서 「상한은 `…px`」를 찾지 못했다').not.toBeNull()
    expect(cssMaxWidth()).toBe(Number(documented![1].replace(/,/g, '')))
  })

  it('그 폭에서 이름표가 §3 범위(13~18px) 안이다 — 실측 17.5px', () => {
    const rendered = (constant('LABEL_FONT') * cssMaxWidth()) / constant('VIEW_W')
    expect(rendered).toBeGreaterThanOrEqual(13)
    expect(rendered).toBeLessThanOrEqual(18)
    expect(Math.round(rendered * 10) / 10).toBe(17.5)
  })
})
