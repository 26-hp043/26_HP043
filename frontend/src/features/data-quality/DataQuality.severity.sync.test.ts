/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 데이터 점검 심각도 색을 CSS에서 잠근다 — `DESIGN_SYSTEM §2.3.1` 🔒.
 *
 * jsdom은 스타일시트를 계산하지 않으므로 화면 검사(`DataQuality.test.tsx`)는 어느 클래스가
 * 붙는지까지만 본다. 그 클래스가 표의 색을 쓰는지는 여기서 규칙 본문을 읽어 확인한다.
 *
 * ⚠️ **선택자별로 따로 보면 안 된다.** 한 요소에는 기본 클래스(`.dq__severity`)와 심각도
 * 클래스(`.dq__severity--anomaly` 등)가 함께 붙고, 우선순위가 같아 **파일에서 뒤에 오는
 * 규칙이 이긴다.** 기본 규칙의 `border-left` 단축 속성이 색 규칙 뒤에 있던 동안(#1767 ~
 * #1940) 표의 칩은 전부 테두리색이었는데, 선택자별 대조는 그것을 통과시켰다. 그래서 요소에
 * 붙는 클래스 전부를 **파일 순서대로** 적용해 마지막 값을 본다.
 */

const CSS = readFileSync(
  join(fileURLToPath(new URL('.', import.meta.url)), 'DataQuality.css'),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '')

/** 파일의 최상위 규칙들 — 이 파일에는 `@media`가 없다(있으면 아래 검사가 먼저 깨진다). */
const RULES = [...CSS.matchAll(/([^{}]+)\{([^}]*)\}/g)].map(([, selector, body]) => ({
  selectors: selector.split(',').map((s) => s.trim()),
  body,
}))

/**
 * 규칙 본문에서 **왼쪽 띠 색을 정하는 마지막 선언**의 색.
 *
 * ⚠️ **4면 단축도 왼쪽 색을 정한다** (`#1993`). 종전에는 `border-left`·`border-left-color`만
 * 읽었는데, `.dq__tile`이 `border: 1px solid var(--color-border)` + `border-left-width: 4px`로
 * 왼쪽 색을 정한다 — 검사에는 **「색 없음」**으로 보였다. 그러면 `.dq__tile`을 색 규칙 뒤로
 * 옮겨 요약 칸이 전부 테두리색이 돼도(`#1990`이 칩에서 고친 것과 같은 결함) `tile(...)`
 * 단언이 통과한다.
 *
 * ⚠️ **색을 해석하지 못한 선언은 `null`로 표시해 실패시킨다.** 종전에는 해석 실패를
 * `undefined`로 흘려 **앞 규칙의 값이 남았다** — 색을 생략했거나(`border-left: 4px solid`)
 * 순서가 다르거나(`border-left: var(--x) solid 4px`) 마지막 `;`가 없으면 조용히 「통과」
 * 쪽으로 갔다. 읽을 수 없는 것을 **읽었다고 하지 않는다**.
 */
function leftColorOf(body: string): string | null | undefined {
  let value: string | null | undefined
  /*
   * `border` · `border-color` 4면 단축과 `border-left` · `border-left-color`를 모두 본다.
   * 폭·굵기만 정하는 `border-left-width`는 색을 정하지 않으므로 대상이 아니다.
   */
  const declarations = /(border(?:-left)?(?:-color)?)\s*:\s*([^;}]+)(?:;|$)/g
  for (const [, property, raw] of body.matchAll(declarations)) {
    const text = raw.trim()
    if (text === '') continue
    if (property.endsWith('-color')) {
      // `border-color: a b c d`는 넷째(왼쪽)가 왼쪽 색이고, 값이 하나면 네 면 모두다.
      const parts = colorParts(text)
      value = parts.length === 0 ? null : (parts[3] ?? parts[1] ?? parts[0])
      continue
    }
    // 단축(`border` · `border-left`) — 색은 폭·스타일과 순서가 자유롭다.
    const colors = colorParts(text)
    value = colors.length === 1 ? colors[0] : null
  }
  return value
}

/** 값에서 색으로 읽히는 토막들 — `var(...)`(중첩 포함) · `#rgb` · 색 이름. */
function colorParts(value: string): string[] {
  const found: string[] = []
  const pattern = /var\((?:[^()]|\([^()]*\))*\)|#[0-9a-f]{3,8}\b|\b(?:transparent|currentcolor|[a-z]+)\b/gi
  for (const [token] of value.matchAll(pattern)) {
    // 폭·스타일 낱말은 색이 아니다.
    if (/^(?:thin|medium|thick|none|hidden|dotted|dashed|solid|double|groove|ridge|inset|outset)$/i.test(token)) continue
    if (/^[\d.]+(?:px|rem|em|%)$/i.test(token)) continue
    found.push(token)
  }
  return found
}

/**
 * 이 선택자가 **우리가 보는 그 요소 자체**를 더 높은 특정도로 겨냥하는가 (`#1993`).
 *
 * 마지막 compound(마지막 결합자 뒤)만 본다 — `.dq__tile dt`는 자손 `dt`를 겨냥하므로
 * 칸의 테두리를 건드리지 않고, `.dq__tile.dq__tile--anomaly`·`.dq__tile:hover`는 같은
 * 요소를 겨냥하며 특정도가 높아 파일 순서를 뒤집는다.
 */
function overSpecific(selector: string, wanted: ReadonlySet<string>): boolean {
  const last = selector.split(/[\s>+~]+/).filter(Boolean).pop() ?? ''
  const classes = [...last.matchAll(/\.[-\w]+/g)].map(([token]) => token)
  if (classes.length === 0) return false
  // 우리 요소에 없는 클래스가 하나라도 있으면 그 규칙은 이 요소에 붙지 않는다.
  if (!classes.every((token) => wanted.has(token))) return false
  // 클래스 말고 남는 것(태그 · `:hover` · `[attr]`)이 있으면 그것도 특정도를 올린다.
  const rest = last.replace(/\.[-\w]+/g, '')
  return classes.length > 1 || rest !== ''
}

/**
 * 클래스 목록이 붙은 요소의 **최종** 왼쪽 띠 색.
 *
 * 단일 클래스 선택자만 따진다(우선순위 동일 → 파일에서 뒤가 이긴다). ⚠️ **복합 선택자가
 * 있으면 실패시킨다** (`#1993`) — `.dq__tile.dq__tile--anomaly`처럼 특정도가 높은 규칙이
 * 생기면 「파일 순서대로 마지막」이라는 이 함수의 전제가 깨지는데, 조용히 틀린 값을
 * 돌려주는 대신 검사가 먼저 붉어지게 한다.
 */
function effectiveLeftColor(classes: string[]): string {
  const wanted = new Set(classes.map((c) => `.${c}`))
  let value: string | null | undefined
  for (const { selectors, body } of RULES) {
    for (const selector of selectors) {
      if (wanted.has(selector)) continue
      expect(
        overSpecific(selector, wanted),
        `\`${selector}\`가 ${classes.join(' ')} 요소를 더 높은 특정도로 겨냥한다 — ` +
          '이 검사는 특정도가 같다고 전제하므로 전제를 다시 세워야 한다 (#1993)',
      ).toBe(false)
    }
    if (!selectors.some((s) => wanted.has(s))) continue
    const found = leftColorOf(body)
    if (found === undefined) continue
    expect(
      found,
      `${selectors.join(', ')}의 왼쪽 띠 선언에서 색을 읽지 못했다 — ` +
        '읽을 수 없는 것을 통과로 넘기지 않는다 (#1993)',
    ).not.toBeNull()
    value = found
  }
  expect(value, `${classes.join(' ')}의 띠 색을 정하는 규칙이 없다`).toBeDefined()
  return value as string
}

const chip = (severity: string) => effectiveLeftColor(['dq__severity', `dq__severity--${severity}`])
const tile = (severity: string) => effectiveLeftColor(['dq__tile', `dq__tile--${severity}`])

describe('파일 전제', () => {
  it('미디어 쿼리가 없다 — 있으면 위 규칙 분해가 틀린다', () => {
    expect(CSS).not.toMatch(/@media|@supports/)
  })
})

describe('심각도 색이 실제로 이긴다 — `§2.3.1` 표 (#1940 후속)', () => {
  it.each([
    ['substituted', 'var(--color-danger)'],
    ['unavailable', 'var(--color-danger)'],
    ['anomaly', 'var(--color-warning)'],
    ['unconfirmed', 'var(--color-text-muted)'],
    ['public_record', 'var(--color-info)'],
  ])('표의 칩 %s = %s — 기본 규칙의 테두리색에 덮이지 않는다', (severity, color) => {
    expect(chip(severity)).toBe(color)
  })

  it.each([
    ['substituted', 'var(--color-danger)'],
    // `unavailable`이 빠져 있었다 (`#1993`) — 칩 쪽 표에는 있는데 요약 칸 표에만 없었다.
    ['unavailable', 'var(--color-danger)'],
    ['anomaly', 'var(--color-warning)'],
    ['unconfirmed', 'var(--color-text-muted)'],
    ['public_record', 'var(--color-info)'],
  ])('요약 칸 %s = %s', (severity, color) => {
    expect(tile(severity)).toBe(color)
  })
})

describe('「공적 기록과 다름」 띠 색 — `§2.3.1` 〔확정〕 2026-09-27 (#1940 ①)', () => {
  it('「실적 확정 전」의 중립과 갈린다 — 임시안(#1197)의 같은 색 짝이 남지 않는다', () => {
    expect(chip('public_record')).not.toBe(chip('unconfirmed'))
    expect(tile('public_record')).not.toBe(tile('unconfirmed'))
  })

  it('경고색(Danger · Warning)을 쓰지 않는다 — 값을 바꾸지 않는 안내다', () => {
    expect(chip('public_record')).not.toMatch(/danger|warning/)
  })
})

/**
 * 「이 값으로 채우기」 버튼의 테두리 — `DESIGN_SYSTEM §2.3.1` 〔확정 2026-10-07 · `#2154`〕.
 *
 * ## 왜 토큰을 잠그나
 *
 * `§8` 텍스트 버튼 항목은 「**Secondary(아웃라인)로 대신하지 않는다**」를 정해 두었고, 그
 * 사유는 `--color-border-strong`이 `1.4.11`에 미달이라는 것이다(라이트 `1.60` · 다크
 * `1.57` · 기준 `3.0`). 이 버튼은 **아웃라인인데도 확정됐다** — 테두리가
 * `--color-border-control`이라 그 사유가 걸리지 않기 때문이다(네 면 최소 `3.77` · `#1169`).
 *
 * 그래서 **그 토큰이 이 버튼의 확정 근거 자체**다. 값이 같은 다른 토큰으로 옮겨 가면 확정이
 * 근거를 잃는데 화면은 그대로여서 드러나지 않는다 — `#1169`가 겪은 꼴이다. 이름을 잠근다.
 */
describe('「이 값으로 채우기」가 통과하는 경계 토큰을 쓴다 (#2154)', () => {
  /**
   * 그 선택자를 **그 자체로** 가진 규칙들의 본문을 모은다.
   *
   * ⚠️ 첫 규칙만 집으면 안 된다 — 이 두 버튼은 공유 규칙(여백·글자)과 각자 규칙(테두리·면)
   * **둘로 나뉘어** 있고, 처음 쓴 검사가 공유 규칙만 보고 테두리를 못 찾았다.
   */
  const bodyOf = (selector: string): string => {
    const bodies = RULES.filter((r) => r.selectors.includes(selector)).map((r) => r.body)
    if (bodies.length === 0) throw new Error(`규칙을 찾지 못했습니다: ${selector}`)
    return bodies.join('\n')
  }

  it('실행 버튼의 테두리는 --color-border-control이다', () => {
    const body = bodyOf('.dq__fill-action')
    expect(body).toMatch(/border:\s*1px solid var\(--color-border-control\)/)
    expect(body).not.toMatch(/--color-border-strong/)
  })

  it('글자는 label이다 — 표 안의 보조 버튼이다', () => {
    expect(bodyOf('.dq__fill-keep')).toMatch(/font-size:\s*var\(--font-size-label\)/)
  })

  it('「그만두기」는 테두리 없는 쌍둥이다 — 두 동작의 무게가 다르다', () => {
    expect(bodyOf('.dq__fill-keep')).toMatch(/border:\s*1px solid transparent/)
  })
})
