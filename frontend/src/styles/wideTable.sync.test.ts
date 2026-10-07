/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 읽히는 하한을 가진 표는 **자기 래퍼 안에서** 가로로 스크롤한다 (`#1655`).
 *
 * ## 페이지 넘침을 막는 줄은 하나였다
 *
 * `#1655`는 1단으로 접힌 뒤 「암묵 열이 생겨 레이아웃이 예상보다 넓어진다」를 의심했다.
 * 브라우저에서 재 보니 그 의심은 빗나갔다 — 0폭 트랙은 `auto-fit`이 **빈 반복 트랙을
 * 접는** 규격 동작이고, 접힌 트랙의 여백도 함께 접히므로 폭을 늘리지 않는다
 * (1366·1100·1024·900·768·520·400 전부 `scrollWidth === innerWidth`).
 *
 * 그 자리에서 실제로 넘침을 막고 있던 것은 **래퍼의 `overflow-x: auto` 한 줄**이었다.
 * 항로 비교 결과 표(`min-inline-size: 520px`)에서 그 줄만 껐을 때 400·520에서 페이지가
 * `633px`로 넘쳤다. 같은 자리에서 `min-width: 0`을 껐을 때는 **아무 일도 없었다**
 * (`minmax(0, 1fr)` 트랙이 이미 하한을 0으로 두기 때문이다) — 그래서 이 검사는
 * `min-width: 0`이 아니라 래퍼를 본다. 무엇이 짐을 지고 있는지 재고 나서 잠근다.
 *
 * ## CSS 한 쪽만 보면 초록으로 남는다
 *
 * 래퍼 규칙이 CSS에 남아 있어도 마크업이 `<table>`을 그 `<div>` **밖으로** 옮기면 표는
 * 그대로 페이지를 넘친다. 그래서 규칙과 **마크업 둘 다** 본다.
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 화면 회귀 가드)
 */

/**
 * 하한 폭을 선언한 표와 그것을 감싸는 래퍼.
 *
 * 하한은 **브라우저에서 잰 값**으로 잡는다는 관례가 각 CSS 주석에 남아 있다(`#1689`).
 * 여기서는 그 값이 얼마인지가 아니라 **하한이 있으면 래퍼도 있는가**를 본다.
 */
const WIDE_TABLES = [
  {
    name: '연간 등급 관리 — 민감도',
    css: 'src/features/annual-simulation/AnnualSimulation.css',
    markup: 'src/features/annual-simulation/AnnualSimulation.tsx',
    table: '.annual-sim__table',
    wrap: '.annual-sim__tablewrap',
  },
  {
    name: '항로 비교 — 시나리오 비교표',
    css: 'src/features/scenario-comparison/ScenarioComparison.css',
    markup: 'src/features/scenario-comparison/ScenarioComparison.tsx',
    table: '.scenario-table',
    wrap: '.scenario-table-wrap',
  },
  /*
   * 「데이터 점검 — 점검 항목」(`.dq__issues`)은 여기 있었다. 10/7 디자인 결정(#2319)으로 점검
   * 항목 표가 할 일 카드(`.dq-task`)로 바뀌어 표 자체가 없어졌다 — 하한 폭을 가진 표가 아니다.
   */
  {
    name: '함대 감축 계획 — 후보 표',
    css: 'src/features/fleet-reduction/FleetReduction.css',
    markup: 'src/features/fleet-reduction/FleetReduction.tsx',
    /* 하한은 카드 안의 표에만 붙는다 — 도구 패널의 같은 표는 좁아도 읽힌다. */
    min: '.fr__table-card .fr__table',
    table: '.fr__table',
    wrap: '.fr__table-wrap',
  },
] as const

function read(file: string): string {
  return readFileSync(join(process.cwd(), file), 'utf-8')
}

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** 선택자가 정확히 일치하는 규칙들의 본문 — 한 파일에 둘 이상일 수 있다. */
function rules(css: string, selector: string): string[] {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return [...css.matchAll(new RegExp(`(^|[\\n,])\\s*${escaped}\\s*(,[^{]*)?\\{([^}]*)\\}`, 'g'))].map(
    (m) => m[3],
  )
}

describe('가로로 넓은 표 (#1655)', () => {
  it.each(WIDE_TABLES)('$name — 표가 읽히는 하한 폭을 선언한다', (t) => {
    const selector = 'min' in t ? t.min : t.table
    const bodies = rules(stripComments(read(t.css)), selector)
    expect(bodies.length, `${selector} 규칙이 없다`).toBeGreaterThan(0)
    expect(
      bodies.some((body) => /min-(width|inline-size):\s*\d/.test(body)),
      `${selector}에 하한 폭이 없다 — 열을 접어 숨기지 않는다는 판단이 사라졌다`,
    ).toBe(true)
  })

  it.each(WIDE_TABLES)('$name — 래퍼가 가로로 스크롤한다', (t) => {
    /*
     * 이 한 줄이 페이지 넘침을 막는다(머리주석의 실측). 없으면 하한 폭이 그대로
     * 페이지 폭이 되어, 좁은 창에서 **화면 전체가** 가로로 밀린다.
     */
    const bodies = rules(stripComments(read(t.css)), t.wrap)
    expect(bodies.length, `${t.wrap} 규칙이 없다`).toBeGreaterThan(0)
    expect(bodies.some((body) => /overflow-x:\s*auto/.test(body))).toBe(true)
  })

  it.each(WIDE_TABLES)('$name — 마크업이 표를 그 래퍼 안에 둔다', (t) => {
    /*
     * 규칙이 남아 있어도 `<table>`이 래퍼 밖으로 나가면 표는 그대로 넘친다. 래퍼
     * `<div>`가 열린 뒤 **닫히기 전에** 표 클래스가 나오는지 본다 — 여는 태그만 세면
     * 다른 카드의 래퍼와 짝이 맞지 않아도 초록이다.
     */
    const markup = read(t.markup)
    const wrapClass = t.wrap.slice(1)
    const tableClass = t.table.slice(1)
    const opens = [...markup.matchAll(new RegExp(`<div className="[^"]*\\b${wrapClass}\\b[^"]*">`, 'g'))]
    expect(opens.length, `${t.wrap}를 쓰는 자리가 없다`).toBeGreaterThan(0)
    expect(
      opens.some((open) => {
        const after = markup.slice(open.index + open[0].length)
        const table = after.search(new RegExp(`className="[^"]*\\b${tableClass}\\b`))
        const close = after.indexOf('</div>')
        return table > -1 && (close === -1 || table < close)
      }),
      `${t.table}이 ${t.wrap} 안에 없다`,
    ).toBe(true)
  })
})
