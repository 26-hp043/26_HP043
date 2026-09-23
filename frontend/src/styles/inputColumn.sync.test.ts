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
  {
    // #1768 — 종전에는 조건이 전폭, 문서가 그 아래였다. 누르기 전 첫 화면의 40%가 빈 면.
    name: '보고서',
    file: 'src/features/reports/ReportsView.css',
    grid: '.rp__split',
    input: '.rp__form',
  },
] as const

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** 미디어 쿼리 밖, 선택자가 정확히 일치하는 최상위 규칙들 — 파일에 나온 순서대로. */
function topRules(css: string, selector: string): { at: number; body: string }[] {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(^|\\n)${escaped}\\s*\\{([^}]*)\\}`, 'g')
  const out: { at: number; body: string }[] = []
  for (let m = re.exec(css); m !== null; m = re.exec(css)) {
    out.push({ at: m.index, body: m[2] })
  }
  return out
}

/** 미디어 쿼리 밖, 선택자가 정확히 일치하는 첫 규칙의 본문. */
function topRule(css: string, selector: string): string {
  const [first] = topRules(css, selector)
  if (first === undefined) throw new Error(`규칙이 없다: ${selector}`)
  return first.body
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

  /**
   * 1100 블록이 기본 규칙보다 **뒤에** 있는가 (#1770).
   *
   * 위 검사는 블록 **안에 그 줄이 적혀 있는지**만 본다. 특정도가 같으므로 순서가
   * 승부를 가르는데, `#1745`가 항로 비교를 이 틀로 옮기며 블록을 종전 자리에 둔 채
   * 기본 규칙을 그 아래에 새로 적었다 — 네 줄 중 **격자 하나만 듣고** 입력은 접힌
   * 뒤에도 `sticky`로 남아 결과를 덮었다. 그런데도 열두 건이 전부 초록이었다.
   *
   * **마지막 선언을 본다** — 같은 선택자의 규칙이 한 파일에 둘 이상 있을 수 있다
   * (`.annual-sim__form`이 실제로 그렇다: 배치는 위, 면은 아래). 이기는 것은 마지막
   * 하나이므로 그것이 블록보다 앞에 있어야 한다.
   */
  const OVERRIDDEN = [
    { of: 'grid', props: ['grid-template-columns'] },
    { of: 'input', props: ['position', 'max-block-size', 'overflow-y'] },
  ] as const

  it.each(SCREENS)('$name — 1100 블록이 기본 규칙보다 뒤에 있다', (s) => {
    const css = stripComments(readFileSync(join(process.cwd(), s.file), 'utf-8'))
    const media = css.indexOf('@media (max-width: 1100px)')
    expect(media, '1100 블록이 없다').toBeGreaterThan(-1)

    for (const { of, props } of OVERRIDDEN) {
      const selector = of === 'grid' ? s.grid : s.input
      for (const prop of props) {
        const declares = new RegExp(`(^|[\\s;])${prop}\\s*:`)
        const last = topRules(css, selector).filter((rule) => declares.test(rule.body)).pop()
        expect(last, `${selector}에 \`${prop}\`을 정하는 규칙이 없다`).toBeTruthy()
        expect(
          last?.at,
          `${selector}의 \`${prop}\` 기본 선언이 1100 블록보다 뒤에 있다 — 특정도가 같아 미디어가 진다`,
        ).toBeLessThan(media)
      }
    }
  })
})
