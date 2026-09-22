/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 입력-결과 2단 — `DESIGN_SYSTEM §8.7` 〔권장〕을 따르는 화면들을 한 표로 대조한다 (#1711).
 *
 * 화면별 테스트는 자기 화면만 보므로, 한 화면만 360에서 벗어나거나 sticky를 잃어도
 * 잡지 못한다(`riskColor.test.ts`와 같은 이유). 새 화면이 이 틀을 쓰면 표에 한 줄 더한다.
 */
const SCREENS = [
  {
    name: 'CII 예측',
    file: 'src/pages/CiiForecastPage.css',
    grid: '.cii-forecast-page__split',
    input: '.cii-forecast-page__split > .voyage-cii-form',
  },
  {
    name: '연간 등급 관리',
    file: 'src/features/annual-simulation/AnnualSimulation.css',
    grid: '.annual-sim',
    input: '.annual-sim__form',
  },
  {
    // #1745 — 종전에는 `§7.1` 7:5에 1900 접힘이었다. 결과가 표 하나가 되며 이 틀로 옮겼다.
    name: '항로 비교',
    file: 'src/features/scenario-comparison/ScenarioComparison.css',
    grid: '.scenario-comparison',
    input: '.scenario-comparison__form',
  },
] as const

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** 미디어 쿼리 밖, 선택자가 정확히 일치하는 첫 규칙의 본문. */
function topRule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`(^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css)
  if (!match) throw new Error(`규칙이 없다: ${selector}`)
  return match[2]
}

function media1100(css: string): string {
  return /@media \(max-width: 1100px\) \{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
}

describe('입력-결과 2단 — DESIGN_SYSTEM §8.7', () => {
  it.each(SCREENS)('$name — 입력 기둥은 `--grid-input-column` 고정 폭이다', (s) => {
    const css = stripComments(readFileSync(join(process.cwd(), s.file), 'utf-8'))
    expect(topRule(css, s.grid)).toMatch(
      /grid-template-columns:\s*var\(--grid-input-column\)\s+minmax\(0,\s*1fr\)/,
    )
    expect(css).not.toMatch(/--grid-split-(primary|secondary)/)
  })

  it.each(SCREENS)('$name — 입력은 따라오고, 창보다 길면 기둥 안에서 스크롤한다', (s) => {
    const css = stripComments(readFileSync(join(process.cwd(), s.file), 'utf-8'))
    const body = topRule(css, s.input)
    expect(body).toMatch(/position:\s*sticky/)
    expect(body).toMatch(/max-block-size:/)
    expect(body).toMatch(/overflow-y:\s*auto/)
  })

  it.each(SCREENS)('$name — 1100 이하에서 한 단으로 접히고 따라오지 않는다', (s) => {
    const media = media1100(stripComments(readFileSync(join(process.cwd(), s.file), 'utf-8')))
    const esc = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    expect(media).toMatch(new RegExp(`${esc(s.grid)}\\s*\\{[^}]*grid-template-columns:\\s*minmax\\(0,\\s*1fr\\)`))
    expect(media).toMatch(new RegExp(`${esc(s.input)}\\s*\\{[^}]*position:\\s*static`))
  })
})
