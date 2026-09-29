/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { dirOf, srcKey } from '../test/srcPaths'
import { compounds, specificity, stronger } from './specificity'

/**
 * **변종 클래스가 기본 규칙에 특이도로 지지 않는가** (`#2047`).
 *
 * ## 무엇이 어긋나 있었나
 *
 * ```css
 * .rp__actions button { background: var(--surface-card); }   ← 0-1-1
 * .rp__primary        { background: var(--semantic-primary); } ← 0-1-0 · 진다
 * ```
 *
 * 보고서의 「PDF 내려받기」에 `.rp__primary`가 정확히 붙어 있었고, 소스 순서로도
 * 나중이었다. 그런데 **나중이 이기는 것은 특이도가 같을 때뿐**이라 세 줄이 통째로
 * 버려졌고, 주 동작이 나머지 둘과 똑같이 그려졌다. 코드는 「PDF가 주 동작」이라고
 * 적고 있었지만 **읽는 사람에게만** 그랬다.
 *
 * `#1770` · `#2015`가 같은 갈래다 — 가드가 선언의 **존재**만 보고 **이기는가**를
 * 보지 않았다. 여기서는 특이도를 계산해 견준다.
 *
 * ## 어떻게 「같은 요소」를 아나
 *
 * 두 규칙이 부딪치려면 **같은 요소에 둘 다 닿아야** 한다. 그래서 JSX를 태그 스택으로
 * 훑어 요소마다 `(태그, 자기 클래스, 조상 클래스)`를 모으고, 그 요소에 닿는 규칙만
 * 서로 견준다. 저장소 전체 규칙을 짝지으면 1,483건이 나오는데 대부분 **서로 만나지
 * 않는** 규칙이다.
 *
 * ## 세 가지를 걸러야 남는 것이 결함이다
 *
 * 걸러 가며 잰 수다 — 1,483 → **7**.
 *
 * | 거르는 것 | 왜 | 남은 수 |
 * |---|---|---|
 * | 같은 요소에 닿는 짝만 | 만나지 않으면 부딪치지 않는다 | 156 |
 * | **상태(의사클래스)가 같은 짝만** | `:hover`·`:disabled`는 **원래 더 세야** 한다 | 21 |
 * | **값이 다른 짝만** | 같은 값을 다시 적는 것은 해가 없다 | 12 |
 * | **`.문맥 .변종` 꼴 제외** | 변종을 문맥으로 한정한 것은 **의도된** 재정의다 | 7 |
 *
 * 남은 7 중 둘이 `#2047`이 고친 자리이고, **셋이 새로 드러난 결함**이다(아래 예외
 * 목록). 나머지 둘은 이 검사가 못 보는 것의 표시다.
 */
const SRC = dirOf(import.meta.url, '..')

/**
 * 아직 고치지 않은 짝과 **그 이유**.
 *
 * ⚠️ 「목록에 있으니 괜찮다」가 아니다. 셋은 **결함이고 후속 이슈가 있다** — 여기 적힌
 * 것은 「이 PR의 범위가 아니다」이지 「문제가 없다」가 아니다.
 */
const EXEMPT: Readonly<Record<string, string>> = {
  'features/data-quality/DataQuality.css|.dq__tile dd|.dq__hint':
    '같은 파일이 `.dq__tile dd.dq__hint`로 **이미 덧댔다** — 문맥 안에서는 이기고 있다',
  'features/not-underway/NotUnderwayPanel.css|.nu__row-actions button:hover|.nu__danger:hover':
    '⚠️ **결함 · 후속 `#2061`** — 행 삭제 버튼의 hover가 기본 hover(파랑)에 져서 위험색이 나오지 않는다. 실측(1440 라이트)에서 취소 버튼과 `color`·`border-color`가 **모두 `rgb(26,54,93)`**로 같다',
  'features/scenario-comparison/ScenarioComparison.css|.scenario-table th|.scenario-table__corner':
    '⚠️ **결함 · 후속 `#2062`** — 표 모서리 칸이 caption(12)을 잃고 **body(15)**로 그려진다(실측). 주석이 적어 둔 「시나리오 이름과 같은 무게로 읽히지 않게」가 정확히 반대로 나온다',
  'features/scenario-comparison/ScenarioComparison.css|.scenario-table th|.scenario-table__scenario':
    '⚠️ **결함 · 후속 `#2062`** — 시나리오 머리 칸의 `vertical-align: bottom`이 **`middle`**에 진다(실측). 이름이 두 줄이 되는 칸이 생기면 머리 줄이 어긋난다',
  'features/scenario-comparison/ScenarioComparison.css|.scenario-table tbody tr:last-child > *|.scenario-table__scenario':
    '거짓 양성 — 이 검사는 `thead`/`tbody`를 가르지 않는다. 대상은 `thead`의 칸이라 `tbody` 규칙이 닿지 않는다',
}

function walk(dir: string, ext: RegExp, skipTest: boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : walk(path, ext, skipTest)
    if (!ext.test(name)) return []
    if (skipTest && /\.test\.tsx?$/.test(name)) return []
    return [path]
  })
}

function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '')
}

type Rule = { file: string; selector: string; decls: Map<string, string> }

function cssRules(): Rule[] {
  const out: Rule[] = []
  for (const path of walk(SRC, /\.css$/, false)) {
    const source = code(readFileSync(path, 'utf8'))
    for (const found of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const decls = new Map<string, string>()
      for (const part of found[2].split(';')) {
        const colon = part.indexOf(':')
        if (colon > 0) decls.set(part.slice(0, colon).trim(), part.slice(colon + 1).trim())
      }
      if (decls.size === 0) continue
      for (const selector of found[1].split(',')) {
        const trimmed = selector.trim()
        if (trimmed === '' || trimmed.startsWith('@') || trimmed.includes('%')) continue
        out.push({ file: srcKey(SRC, path), selector: trimmed, decls })
      }
    }
  }
  return out
}

type Element = { tag: string; classes: Set<string>; ancestors: Set<string> }

/**
 * JSX를 **태그 스택**으로 훑어 요소마다 자기 클래스와 조상 클래스를 모은다.
 *
 * 소문자 태그만 센다 — 대문자는 컴포넌트라 여기서 DOM 모양을 알 수 없다. 속성 끝은
 * 중괄호와 따옴표를 세며 찾는다(`onChange={(e) => …}`의 화살표에서 끊기지 않게).
 */
function elementsOf(source: string): Element[] {
  const text = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
  const out: Element[] = []
  const stack: { tag: string; classes: string[] }[] = []
  let i = 0
  while (i < text.length) {
    if (text[i] === '<' && text[i + 1] === '/') {
      const end = text.indexOf('>', i)
      if (end < 0) break
      const name = text.slice(i + 2, end).trim()
      if (stack.length > 0 && stack[stack.length - 1].tag === name) stack.pop()
      i = end + 1
      continue
    }
    const open = /^<([a-z][\w-]*)(?=[\s/>])/.exec(text.slice(i))
    if (open === null) {
      i += 1
      continue
    }
    let k = i + open[0].length
    let depth = 0
    let selfClosing = false
    while (k < text.length) {
      const c = text[k]
      if (c === '"' || c === "'" || c === '`') {
        const quote = c
        k += 1
        while (k < text.length && text[k] !== quote) k += text[k] === '\\' ? 2 : 1
      } else if (c === '{') depth += 1
      else if (c === '}') depth -= 1
      else if (c === '>' && depth === 0) {
        selfClosing = text[k - 1] === '/'
        break
      }
      k += 1
    }
    const attrs = text.slice(i + open[0].length, k)
    const className = /className="([^"]*)"/.exec(attrs)
    const classes = className === null ? [] : className[1].split(/\s+/).filter(Boolean)
    if (classes.length > 0) {
      out.push({
        tag: open[1],
        classes: new Set(classes),
        ancestors: new Set(stack.flatMap((frame) => frame.classes)),
      })
    }
    if (!selfClosing) stack.push({ tag: open[1], classes })
    i = k + 1
  }
  return out
}

const PSEUDO = /:[a-z-]+(\([^)]*\))?/g
const BARE_CLASS = /^\.[\w-]+(:[a-z-]+(\([^)]*\))?)*$/

/** 마지막 조각의 의사클래스 — 상태가 다르면 견줄 짝이 아니다. */
function state(selector: string): string {
  const tail = compounds(selector).at(-1) ?? ''
  return (tail.match(PSEUDO) ?? []).sort().join('')
}

/** 이 선택자가 이 요소에 닿는가. `#id`·`::`·`[attr]`은 추적하지 않으므로 뺀다. */
function reaches(selector: string, element: Element): boolean {
  if (/[#[]|::/.test(selector)) return false
  const parts = compounds(selector)
  const tail = parts.at(-1) ?? ''
  const tailTag = /^[a-z][\w-]*/.exec(tail)
  if (tailTag !== null && tailTag[0] !== element.tag) return false
  for (const cls of tail.match(/\.[\w-]+/g) ?? []) {
    if (!element.classes.has(cls.slice(1))) return false
  }
  for (const part of parts.slice(0, -1)) {
    for (const cls of part.match(/\.[\w-]+/g) ?? []) {
      if (!element.ancestors.has(cls.slice(1))) return false
    }
  }
  return true
}

describe('변종 클래스가 기본 규칙에 특이도로 지지 않는다 (#2047)', () => {
  const rules = cssRules()

  it('규칙과 요소를 실제로 읽었다 — 파서가 조용히 0건을 내지 않게', () => {
    expect(rules.length).toBeGreaterThan(500)
    const elements = walk(SRC, /\.tsx$/, true).flatMap((p) => elementsOf(readFileSync(p, 'utf8')))
    expect(elements.length).toBeGreaterThan(300)
  })

  it('같은 요소에 닿는 짝 중 변종이 지는 것이 없다', () => {
    const losers = new Map<string, string>()
    for (const path of walk(SRC, /\.tsx$/, true)) {
      for (const element of elementsOf(readFileSync(path, 'utf8'))) {
        const hit = rules.filter((r) => reaches(r.selector, element))
        for (const base of hit) {
          for (const variant of hit) {
            if (base.selector === variant.selector) continue
            // 변종은 **바른 클래스 하나**다 — 그것이 문맥을 갖지 않는다는 뜻이다.
            if (!BARE_CLASS.test(variant.selector)) continue
            if (state(base.selector) !== state(variant.selector)) continue
            // `.문맥 .변종` — 변종 자신을 문맥으로 한정한 것은 **의도된** 재정의다.
            const variantClass = /^\.([\w-]+)/.exec(variant.selector)?.[1] ?? ''
            const baseTail = compounds(base.selector).at(-1) ?? ''
            if ((baseTail.match(/\.[\w-]+/g) ?? []).some((c) => c.slice(1) === variantClass)) continue
            // 같은 값을 다시 적는 것은 해가 없다.
            const clash = [...variant.decls.keys()].filter(
              (k) => base.decls.has(k) && base.decls.get(k) !== variant.decls.get(k),
            )
            if (clash.length === 0) continue
            if (!stronger(specificity(base.selector), specificity(variant.selector))) continue
            losers.set(`${variant.file}|${base.selector}|${variant.selector}`, clash.join(','))
          }
        }
      }
    }
    const unexplained = [...losers.keys()].filter((key) => EXEMPT[key] === undefined)
    expect(unexplained).toEqual([])
  })

  it('예외 목록에 죽은 항목이 없다 — 고쳤으면 지운다', () => {
    const live = new Set<string>()
    for (const path of walk(SRC, /\.tsx$/, true)) {
      for (const element of elementsOf(readFileSync(path, 'utf8'))) {
        const hit = rules.filter((r) => reaches(r.selector, element))
        for (const base of hit) {
          for (const variant of hit) {
            if (base.selector === variant.selector) continue
            if (!BARE_CLASS.test(variant.selector)) continue
            if (state(base.selector) !== state(variant.selector)) continue
            const variantClass = /^\.([\w-]+)/.exec(variant.selector)?.[1] ?? ''
            const baseTail = compounds(base.selector).at(-1) ?? ''
            if ((baseTail.match(/\.[\w-]+/g) ?? []).some((c) => c.slice(1) === variantClass)) continue
            const clash = [...variant.decls.keys()].some(
              (k) => base.decls.has(k) && base.decls.get(k) !== variant.decls.get(k),
            )
            if (!clash) continue
            if (!stronger(specificity(base.selector), specificity(variant.selector))) continue
            live.add(`${variant.file}|${base.selector}|${variant.selector}`)
          }
        }
      }
    }
    expect(Object.keys(EXEMPT).filter((key) => !live.has(key))).toEqual([])
  })

  it('보고서 동작 버튼은 타입 선택자로 걸지 않는다 — #2047이 고친 자리', () => {
    const reports = readFileSync(join(SRC, 'features/reports/ReportsView.css'), 'utf8')
    expect(code(reports)).not.toMatch(/\.rp__actions\s+button/)
    expect(code(reports)).toMatch(/\.rp__action\s*\{/)
  })
})
