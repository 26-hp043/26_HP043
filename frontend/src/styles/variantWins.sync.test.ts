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
  'features/scenario-comparison/ScenarioComparison.css|.scenario-table tbody tr:last-child > *|.scenario-table__scenario':
    '거짓 양성 — 이 검사는 `thead`/`tbody`를 가르지 않는다. 대상은 `thead`의 칸이라 `tbody` 규칙이 닿지 않는다',
  'features/scenario-comparison/ScenarioComparison.css|.scenario-table tbody tr:last-child > *|.scenario-table__cell':
    '거짓 양성 — **의도된 구조적 재정의**다(`#2062`). 마지막 행의 테두리를 지우는 규칙은 `tr:last-child`로 범위를 좁혀 특이도가 `0-2-2`이고, `.scenario-table__cell`(`0-1-0`)보다 항상 세므로 소스 순서와 무관하게 이긴다. `.scenario-table__cell`이 이 행의 셀에도 클래스를 달면서(§표 전체 `th`·`td`가 이 클래스를 공유한다) 검사에 처음 잡혔을 뿐, `border-block-end`가 마지막 행에서 사라지는 동작은 클래스를 달기 전과 같다(실측 — `getComputedStyle().borderBottomWidth` 전후 동일)',
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

const NOT = /:not\(([^)]*)\)/g

/** 한 조각이 **요구하는** 클래스와 **배제하는** 클래스. */
function demands(compound: string): { required: string[]; excluded: string[] } {
  const excluded = [...compound.matchAll(NOT)].flatMap((m) => m[1].match(/\.[\w-]+/g) ?? [])
  const required = compound.replace(NOT, '').match(/\.[\w-]+/g) ?? []
  return { required: required.map((c) => c.slice(1)), excluded: excluded.map((c) => c.slice(1)) }
}

/**
 * 이 선택자가 이 요소에 닿는가. `#id`·`::`·`[attr]`은 추적하지 않으므로 뺀다.
 *
 * ⚠️ `:not()` 안의 클래스는 **요구가 아니라 배제**다. 가려내지 않으면 `#2148`이 넣은
 * `.nav-link:not(.nav-link--active):hover`가 활성 항목에도 닿는 것으로 읽혀,
 * **고친 자리가 고쳐지지 않은 것으로** 보인다.
 */
function reaches(selector: string, element: Element): boolean {
  const need = needsOf(selector)
  if (need === null) return false
  if (need.tag !== null && need.tag !== element.tag) return false
  if (need.required.some((cls) => !element.classes.has(cls))) return false
  if (need.excluded.some((cls) => element.classes.has(cls))) return false
  return need.ancestors.every((cls) => element.ancestors.has(cls))
}

/** 선택자가 요소에 요구하는 것. 추적하지 않는 선택자(`#id`·`::`·`[attr]`)는 `null`. */
type Needs = { tag: string | null; required: string[]; excluded: string[]; ancestors: string[] }

/*
 * 선택자를 푸는 일은 **선택자마다 한 번**이면 된다 (`#2250`). 종전에는 `reaches`가 불릴
 * 때마다 — 요소 수 × 규칙 수만큼 — 같은 선택자를 다시 쪼개고 정규식을 다시 돌렸다.
 * 답은 선택자 문자열에만 달려 있으므로 기억해 두어도 판정이 달라지지 않는다.
 */
const needsCache = new Map<string, Needs | null>()

function needsOf(selector: string): Needs | null {
  const cached = needsCache.get(selector)
  if (cached !== undefined) return cached
  let need: Needs | null = null
  if (!/[#[]|::/.test(selector)) {
    const parts = compounds(selector)
    const tail = parts.at(-1) ?? ''
    const { required, excluded } = demands(tail)
    need = {
      tag: /^[a-z][\w-]*/.exec(tail)?.[0] ?? null,
      required,
      excluded,
      ancestors: parts.slice(0, -1).flatMap((part) => demands(part).required),
    }
  }
  needsCache.set(selector, need)
  return need
}

/*
 * 아래 세 검사가 **같은 훑기**를 나눠 쓴다 (`#2250`).
 *
 * 종전에는 「지는 짝이 없다」와 「예외 목록에 죽은 항목이 없다」가 각각 `src/`의 모든
 * `.tsx`를 읽고 요소 × 규칙 짝을 처음부터 다시 견줬다 — 두 검사가 모으는 것은 **같은
 * 열쇠 집합**인데도. CI에서 각각 3.0~3.6초 · 3.1~5.2초가 걸렸고, 뒤의 것이 기본 시한
 * 5초를 넘겨 `frontend` 잡이 붉어졌다(실행 37502647298).
 *
 * 한 번 계산해 기억한다. 검사 파일은 실행마다 새로 불려 오므로 이 기억이 **다음
 * 실행으로 넘어가지 않는다** — 소스를 고친 뒤 낡은 답을 볼 일이 없다.
 */
let elementsMemo: Element[] | undefined

function allElements(): Element[] {
  elementsMemo ??= walk(SRC, /\.tsx$/, true).flatMap((p) => elementsOf(readFileSync(p, 'utf8')))
  return elementsMemo
}

let losingPairsMemo: Map<string, string> | undefined

/**
 * 같은 요소에 닿는 짝 중 **변종이 지는** 것 — 열쇠는 `파일|바탕|변종`, 값은 부딪친 속성.
 *
 * 한 번 계산한 답을 기억한다. 기억된 뒤에는 `rules` 인자를 다시 보지 않으므로, 이 파일의
 * 규칙 표 하나로만 부른다 — 다른 규칙 집합을 넘기면 낡은 답이 돌아온다.
 */
function losingPairs(rules: Rule[]): Map<string, string> {
  if (losingPairsMemo !== undefined) return losingPairsMemo
  const losers = new Map<string, string>()
  for (const element of allElements()) {
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
  losingPairsMemo = losers
  return losers
}

/*
 * 기본 5초를 쓰지 않는다 (`#2250`). 훑기를 한 번으로 줄인 뒤에도 그 한 번은 요소 × 규칙
 * 짝을 견주는 계산이라 **트리가 커지는 만큼** 늘고, 다른 240여 검사 파일과 코어를 나눠
 * 쓰는 CI에서는 흔들린다(같은 커밋의 두 실행이 3.1초 · 5.2초였다). 30초는 그 폭을
 * 덮고도 **진짜 멈춤은 여전히 드러내는** 값이다 — 전역 시한은 올리지 않는다. 셋 중
 * 어느 검사가 먼저 돌아도 그 검사가 훑기 값을 치르므로 셋 모두에 준다.
 */
const SCAN_TIMEOUT_MS = 30_000

describe('변종 클래스가 기본 규칙에 특이도로 지지 않는다 (#2047)', () => {
  const rules = cssRules()

  it('규칙과 요소를 실제로 읽었다 — 파서가 조용히 0건을 내지 않게', { timeout: SCAN_TIMEOUT_MS }, () => {
    expect(rules.length).toBeGreaterThan(500)
    expect(allElements().length).toBeGreaterThan(300)
  })

  it('같은 요소에 닿는 짝 중 변종이 지는 것이 없다', { timeout: SCAN_TIMEOUT_MS }, () => {
    const unexplained = [...losingPairs(rules).keys()].filter((key) => EXEMPT[key] === undefined)
    expect(unexplained).toEqual([])
  })

  it('예외 목록에 죽은 항목이 없다 — 고쳤으면 지운다', { timeout: SCAN_TIMEOUT_MS }, () => {
    const live = new Set(losingPairs(rules).keys())
    expect(Object.keys(EXEMPT).filter((key) => !live.has(key))).toEqual([])
  })

  /**
   * **상태 규칙이 변종을 덮지 않는가** (`#2148`).
   *
   * 위 검사는 **상태가 같은 짝**만 견준다 — `:hover`는 바탕 규칙보다 세야 하니 그것이
   * 맞다. 그런데 그 세기가 **변종에도 그대로 간다.**
   *
   * ```css
   * .nav-link:hover   { color: var(--text-primary); }  ← 0-2-0
   * .nav-link--active { color: var(--color-link); }    ← 0-1-0 · 진다
   * ```
   *
   * 마우스를 올린 동안 활성 항목이 **활성으로 보이지 않는다.** 멈춘 화면에서는
   * 멀쩡하고 스크린숏에도 안 남는다 — 손이 올라가 있을 때만 틀린다.
   *
   * 변종이 **상태를 말하는** 것일 때(활성·비활성·선택됨) 이것은 곧 상태의 소실이다.
   * 고치는 길은 둘이고 **둘 다 통과한다** — 상태 규칙에서 변종을 빼거나(`:not()`),
   * 변종 자신의 상태 규칙을 적거나.
   *
   * ## 여기서는 JSX를 보지 않는다
   *
   * 위 두 검사는 요소마다 「이 규칙이 닿는가」를 JSX에서 확인하는데, `className`이
   * **정적 문자열일 때만** 보인다. 토글의 선택된 칸은 `className={`…${on ? …}`}`로
   * 붙어 **그 눈에 띄지 않는다** — 실제로 이 결함 셋 중 둘이 그렇게 빠져나갔다.
   *
   * 그래서 이 검사는 **스타일시트만** 읽는다. `.블록--이름`이 `.블록`을 함께 단다는
   * 것은 이 저장소의 BEM 표기가 보장하므로, 같은 파일 안의 두 규칙만으로 충분하다.
   */
  it('`:hover`가 변종의 상태 색을 덮지 않는다 (#2148)', () => {
    const STATE = /:(?:hover|focus|focus-visible|active)\b/
    const losers = new Map<string, string>()

    for (const variant of rules) {
      const named = /^\.([\w-]+--[\w-]+)$/.exec(variant.selector)
      if (named === null) continue
      const variantClass = named[1]

      for (const base of rules) {
        if (base.file !== variant.file) continue
        const tail = compounds(base.selector).at(-1) ?? ''
        if (!STATE.test(tail)) continue

        const { required, excluded } = demands(tail)
        // 이미 빼 두었다 — `.블록:not(.블록--이름):hover`.
        if (excluded.includes(variantClass)) continue
        // 그 변종이 **특수화하는 바로 그 블록**을 거는 규칙만 본다.
        if (!required.some((cls) => variantClass.startsWith(`${cls}--`))) continue

        const clash = [...variant.decls.keys()].filter(
          (k) => base.decls.has(k) && base.decls.get(k) !== variant.decls.get(k),
        )
        if (clash.length === 0) continue
        if (stronger(specificity(variant.selector), specificity(base.selector))) continue

        // 변종 자신의 상태 규칙이 그 값을 되찾고 있으면 소실이 아니다.
        const restored = rules.some(
          (r) =>
            r.file === variant.file &&
            r.selector !== base.selector &&
            state(r.selector) === state(base.selector) &&
            demands(compounds(r.selector).at(-1) ?? '').required.includes(variantClass) &&
            clash.every((k) => r.decls.has(k)),
        )
        if (restored) continue

        losers.set(`${variant.file}|${base.selector}|${variant.selector}`, clash.join(','))
      }
    }

    expect([...losers.keys()].sort()).toEqual([])
  })

  it('보고서 동작 버튼은 타입 선택자로 걸지 않는다 — #2047이 고친 자리', () => {
    const reports = readFileSync(join(SRC, 'features/reports/ReportsView.css'), 'utf8')
    expect(code(reports)).not.toMatch(/\.rp__actions\s+button/)
    expect(code(reports)).toMatch(/\.rp__action\s*\{/)
  })
})
