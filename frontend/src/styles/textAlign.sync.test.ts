/**
 * 숫자 정렬 규칙이 **셀을 통째로 덮는 규칙을 이기는가** (`#2015`).
 *
 * ## 무엇이 어긋나 있었나
 *
 * `DESIGN_SYSTEM §8`이 「테이블 — 숫자 우측 정렬」을 정하는데, 두 화면에서 **머리글과 값이
 * 서로 반대쪽**에 붙어 있었습니다. 규칙이 없어서가 아니라 **이기지 못해서**였습니다.
 *
 * ```css
 * .regp__table th,
 * .regp__table td { text-align: left; }   ← 0,1,1
 * .regp__num      { text-align: right; }  ← 0,1,0 · 진다
 * ```
 *
 * 그래서 각 파일이 **한쪽에만 덧댔고**(규제 기준값은 `th`, 선박 상세는 `td`), 덧댄 쪽이
 * 서로 반대라 두 화면의 증상이 정확히 뒤집혀 보였습니다.
 *
 * ## 왜 「문구가 있는가」로는 못 잡나
 *
 * `#1770`이 같은 자리였습니다 — 가드가 선언의 **존재**만 보고 **이기는가**를 보지 않아
 * 열두 건이 전부 초록이었습니다. 여기서는 **특정도를 계산해** 비교합니다.
 *
 * ## 무엇을 보는가
 *
 * 한 파일 안에서, 셀을 통째로 덮는 규칙(`… th` · `… td`)이 `text-align: left`를 걸면,
 * 그보다 특정도가 낮은 `text-align: right` 규칙은 **그 셀에 절대 닿지 못합니다.**
 * 셀에 닿을 수 있는 오른쪽 정렬 규칙(마지막 조각이 `th`·`td`이거나 클래스인 것)만 봅니다.
 */

import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { type Specificity, specificity, stronger } from './specificity'

const SRC = join(__dirname, '..')

function cssFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...cssFiles(full))
    else if (name.endsWith('.css')) out.push(full)
  }
  return out
}

type Rule = { selector: string; align: string; specificity: Specificity }

/** 마지막 조각 — `.regp__table td.regp__num` → `td.regp__num`. */
function last(selector: string): string {
  return selector.trim().split(/[\s>+~]+/).pop() ?? ''
}

/** 선택자가 매달린 첫 클래스 — `.annual-sim__table tbody th` → `.annual-sim__table`. */
function block(selector: string): string | null {
  return /\.[\w-]+/.exec(selector)?.[0] ?? null
}

function rules(css: string): Rule[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const out: Rule[] = []
  for (const match of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const align = /(?:^|;)\s*text-align\s*:\s*([a-z-]+)/.exec(match[2])?.[1]
    if (!align) continue
    for (const selector of match[1].split(',')) {
      const trimmed = selector.trim()
      if (!trimmed || trimmed.startsWith('@')) continue
      out.push({ selector: trimmed, align, specificity: specificity(trimmed) })
    }
  }
  return out
}

describe('표의 숫자 정렬은 셀을 덮는 규칙을 이겨야 한다 (#2015)', () => {
  const files = cssFiles(SRC)

  it('훑을 CSS가 있다', () => {
    expect(files.length).toBeGreaterThan(20)
  })

  it.each(files.map((f) => [f.slice(SRC.length + 1), f] as const))(
    '%s — 셀을 덮는 왼쪽 정렬이 오른쪽 정렬을 덮어쓰지 않는다',
    (_name, file) => {
      const parsed = rules(readFileSync(file, 'utf-8'))
      // 셀을 통째로 덮는 왼쪽 정렬 — `… th` · `… td`
      const blanket = parsed.filter((r) => r.align === 'left' && /^(th|td)$/.test(last(r.selector)))
      // 셀에 닿을 수 있는 오른쪽 정렬 — 마지막 조각이 셀이거나 클래스인 것
      const cellRight = parsed.filter(
        (r) => r.align === 'right' && /^(th|td|\.)/.test(last(r.selector)),
      )

      const losers = cellRight.flatMap((right) =>
        blanket
          .filter((left) => stronger(left.specificity, right.specificity))
          // 같은 표 안에서 좁히는 규칙은 **의도된** 덮어쓰기다 —
          // `.x__table tbody th {left}`가 `.x__table th {right}`를 이기는 것은
          // 「행 머리글만 왼쪽」이라는 뜻이다. 잡아야 하는 것은 표 **밖에서** 클래스
          // 하나로 건 정렬이 표 자신의 규칙에 지는 자리다.
          .filter((left) => {
            const owner = block(left.selector)
            return owner === null || !right.selector.includes(owner)
          })
          .map(
            (left) =>
              `${right.selector} {text-align:right} (${right.specificity}) ` +
              `< ${left.selector} {text-align:left} (${left.specificity})`,
          ),
      )

      expect(losers, `선언은 있는데 이기지 못한다:\n  ${losers.join('\n  ')}`).toEqual([])
    },
  )

  it.each(files.map((f) => [f.slice(SRC.length + 1), f] as const))(
    '%s — 머리글과 값이 같은 정렬 규칙을 받는다',
    (_name, file) => {
      const parsed = rules(readFileSync(file, 'utf-8'))
      const rightSelectors = new Set(
        parsed.filter((r) => r.align === 'right').map((r) => r.selector.replace(/\s+/g, ' ')),
      )
      // `… td.num`에 오른쪽 정렬을 걸었으면 `… th.num`도 같이 걸려 있어야 한다.
      // 한쪽만 걸면 머리글과 값이 서로 반대쪽에 붙는다 — 이 이슈의 세 표가 전부 그 모양이었다.
      const lonely: string[] = []
      for (const selector of rightSelectors) {
        const match = /^(.*?)(th|td)(\.[\w-]+)$/.exec(selector)
        if (!match) continue
        const [, prefix, tag, cls] = match
        const twin = `${prefix}${tag === 'td' ? 'th' : 'td'}${cls}`
        if (!rightSelectors.has(twin)) lonely.push(`${selector} — 짝 ${twin} 없음`)
      }
      expect(lonely, `한쪽에만 걸린 정렬:\n  ${lonely.join('\n  ')}`).toEqual([])
    },
  )
})
