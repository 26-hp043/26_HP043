/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { dirOf, srcKey } from '../test/srcPaths'

/**
 * **컨트롤에 글자 크기 규칙이 닿는지** 센다 (`DESIGN_SYSTEM §3` · `#2046`).
 *
 * ## 값이 아니라 「있는가」를 본다
 *
 * `#2046`의 결함은 값이 틀린 것이 아니라 **선언이 없는 것**이었다. `global.css`가
 * `input·select·button·textarea`에 `font-family: inherit`를 걸어 두었으나 `font-size`는
 * 걸지 않았고, 컨트롤은 글자 크기를 상속하지 않으므로 Chrome 기본값 `13.33px`이
 * 그대로 그려졌다. **선언을 찾아 값을 비교하는 검사는 이것을 영영 못 본다** — 비교할
 * 선언이 없기 때문이다.
 *
 * `#2015`(특이도에 짐) · `#2038`(뷰박스 단위)과 같은 갈래의 세 번째다. 규칙은 정본에
 * 있는데 **화면까지 오지 못한** 자리다.
 *
 * ## 왜 컨트롤 높이로 가르나
 *
 * 「무엇이 컨트롤인가」를 선택자 이름으로 가르려 하면 `__control` · `__submit` ·
 * `__button` · `select` · `input[type=…]`까지 목록이 끝나지 않고, 새 이름이 생기면
 * 조용히 빠진다.
 *
 * 그런데 이 저장소는 **폼 줄의 컨트롤 높이를 한 값으로** 쓰고 있다 — 입력칸도 제출
 * 버튼도 그 값이다. 그래서 「그 높이를 선언한 규칙」이 곧 「컨트롤을 그리는 규칙」이고,
 * 이름을 몰라도 빠짐없이 모인다. `#2046` 실측에서 **스물둘 중 여덟**이 `font-size`를
 * 빠뜨리고 있었다.
 *
 * ⚠️ 그 높이는 `#2150`에서 리터럴 `40px`에서 토큰 `--target-row`로 옮겨 갔다. **이
 * 검사가 그 리터럴을 눈으로 삼고 있었으므로** 함께 옮긴다 — 토큰으로 바꾸던 PR에서
 * 아래 「규칙을 실제로 읽었다」가 0건으로 붉어져 바로 드러났다. 눈이 값에 묶여 있으면
 * 값이 움직일 때 검사가 조용히 빈손이 된다.
 *
 * ⚠️ 폼 줄 밖의 컨트롤(`--target-button` · `.sort select` 꼴의 작은 것들)은 이 검사가
 * 세지 않는다. 그쪽은 아래 둘째 검사가 **클래스 기준**으로 받는다.
 */
const SRC = dirOf(import.meta.url, '..')

/**
 * 글자를 **자기가 그리지 않는** 줄 — 면제와 그 사유.
 *
 * `.app-shell__nav-link`는 `[아이콘][레이블][태그]`를 담는 상자이고, `AppShell.tsx`에서
 * 직접 글자를 받지 않는다(자식이 모두 `<span>`이다). 레이블과 태그가 각각 크기를
 * 선언하므로 **크기 없는 글자가 생기지 않는다.** 상자에 `font-size`를 적는 것은 아무
 * 글자에도 닿지 않는 장식이 된다.
 */
const EXEMPT: Record<string, string> = {
  'layout/AppShell.css — .app-shell__nav-link':
    '글자를 직접 받지 않는 상자 — 레이블·태그가 각자 크기를 선언한다',
}

/** 위 사유가 「각자 선언한다」고 지목한 쪽. 아래 검사가 이 지목을 확인한다. */
const BEARS_TEXT = ['app-shell__nav-label', 'app-shell__nav-tag']

/** 폼 줄의 컨트롤 높이(`--target-row` · `§8`). 이 토큰이 바뀌면 여기도 함께 간다. */
const CONTROL_HEIGHT = /(?:block-size|height):\s*var\(--target-row\)/

function walk(dir: string, ext: RegExp, skipTest: boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : walk(path, ext, skipTest)
    if (!ext.test(name)) return []
    if (skipTest && /\.test\.tsx?$/.test(name)) return []
    return [path]
  })
}

/** 주석을 걷는다 — 설명문 안의 낱말이 근거가 되지 않게 (`deadCss.test.ts`와 같은 이유). */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '')
}

type Rule = { file: string; selector: string; body: string }

function cssRules(): Rule[] {
  const out: Rule[] = []
  for (const path of walk(SRC, /\.css$/, false)) {
    const source = code(readFileSync(path, 'utf8'))
    for (const found of source.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
      out.push({ file: srcKey(SRC, path), selector: found[1].trim().replace(/\s+/g, ' '), body: found[2] })
    }
  }
  return out
}

describe('컨트롤이 §3 글자 크기를 선언한다 (#2046)', () => {
  const rules = cssRules()

  it('규칙을 실제로 읽었다 — 파서가 조용히 0건을 내지 않게', () => {
    // 이 줄이 없으면 아래 검사가 「없으니 통과」로 초록을 낸다.
    expect(rules.filter((r) => CONTROL_HEIGHT.test(r.body)).length).toBeGreaterThan(15)
  })

  it('폼 줄 높이를 선언한 규칙은 font-size도 선언한다', () => {
    const naked = rules
      .filter((r) => CONTROL_HEIGHT.test(r.body))
      .filter((r) => !/font-size\s*:/.test(r.body))
      .map((r) => `${r.file} — ${r.selector}`)
      .filter((key) => !(key in EXEMPT))
    expect(naked).toEqual([])
  })

  /**
   * 면제의 **근거를 검사한다** (`#2150`).
   *
   * 위 면제는 「글자를 그리는 쪽이 따로 있다」에 기대고 있다. 그 기댄 자리가 조용히
   * 사라지면 면제는 거짓이 되는데, 면제는 그대로 초록을 낸다 — `#2156`에서 사유가
   * 다른 검사에 말없이 기대고 있던 것과 같은 모양이다. 그래서 **사유가 지목한 클래스**가
   * 실제로 크기를 선언하는지를 여기서 받는다.
   */
  it('면제가 지목한 글자 쪽이 실제로 크기를 선언한다 (#2150)', () => {
    const silent = BEARS_TEXT.filter(
      (cls) =>
        !rules.some((r) => r.selector === `.${cls}` && /font-size\s*:/.test(r.body)),
    )
    expect(silent).toEqual([])
  })
})

/**
 * 높이를 따로 정하지 않는 컨트롤은 **클래스**로 받는다.
 *
 * 위 검사는 폼 줄 가족만 본다. 셸의 유틸리티 셀렉트나 목록의 정렬 셀렉트처럼 더 작은
 * 컨트롤은 그 가족이 아니므로, 화면이 붙인 클래스가 `font-size`를 갖는지를 본다.
 *
 * ## ⚠️ 클래스가 없는 컨트롤은 이 검사가 답하지 않는다
 *
 * `.rp select` 꼴의 조상 선택자로만 그려지는 컨트롤이 남아 있다. 그것이 크기를 받는지는
 * **캐스케이드를 풀어야** 알 수 있는데, 소스만으로 푸는 것을 두 번 시도해 보고 둘 다
 * 거짓을 냈다 —
 *
 * ⑴ **같은 폴더의 CSS만** 보면 다른 폴더에 있는 진짜 근거를 놓친다. `card.css`의
 *    `.sort select`가 대시보드의 셀렉트를 덮고 있는데 「없음」으로 셌다
 * ⑵ **import + 공용 `styles/`**로 넓히면 이번에는 **아무 데나 있는 `.sort select`가
 *    근거로 잡혀**, CSS가 한 줄도 없는 2.5D 재생 컨트롤이 「덮임」으로 초록을 냈다
 *
 * 진짜 답은 브라우저의 계산값이고 jsdom은 배치를 하지 않는다. **틀린 초록을 내느니
 * 세지 않는다** — 이 한계를 적어 두는 것이 이 검사가 할 수 있는 정직한 일이다.
 * 클래스를 붙이는 쪽으로 옮겨 가면 아래 검사가 자동으로 받는다.
 */
const CONTROL_TAG = /<(input|select|textarea)(?=[\s/>])/g

/** 글자를 그리지 않는 컨트롤 — 크기를 정할 글자가 없다. */
const NO_TEXT = new Set(['checkbox', 'radio', 'range', 'file', 'color', 'hidden', 'image'])

/** JSX 주석과 doc 주석 안의 예제가 세어지지 않게 걷는다. */
function tsxCode(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

/**
 * 태그의 **진짜 끝**까지 간다.
 *
 * ⚠️ `[^>]*?`로 자르면 `onChange={(e) => …}`의 화살표에서 태그가 끊긴다 — 처음 쓴 검사가
 * 그래서 `className`을 못 보고 멀쩡한 컨트롤을 「클래스 없음」으로 셌다. 중괄호와
 * 따옴표를 세며 넘어간다.
 */
function attrsOf(source: string, start: number): string {
  let depth = 0
  for (let i = start; i < source.length; i += 1) {
    const c = source[i]
    if (c === '"' || c === "'" || c === '`') {
      const quote = c
      i += 1
      while (i < source.length && source[i] !== quote) i += source[i] === '\\' ? 2 : 1
      continue
    }
    if (c === '{') depth += 1
    else if (c === '}') depth -= 1
    else if (c === '>' && depth === 0) return source.slice(start, i)
  }
  return source.slice(start)
}

describe('클래스로 그려지는 컨트롤도 크기를 갖는다 (#2046)', () => {
  const css = walk(SRC, /\.css$/, false)
    .map((p) => code(readFileSync(p, 'utf8')))
    .join('\n')

  function declaresFontSize(cls: string): boolean {
    const escaped = cls.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&')
    const rule = new RegExp(`([^{}]*\\.${escaped}(?![\\w-])[^{}]*)\\{([^}]*)\\}`, 'g')
    for (const found of css.matchAll(rule)) if (/font-size\s*:/.test(found[2])) return true
    return false
  }

  const found: { file: string; classes: string[] }[] = []
  for (const path of walk(SRC, /\.tsx$/, true)) {
    const source = tsxCode(readFileSync(path, 'utf8'))
    for (const tag of source.matchAll(CONTROL_TAG)) {
      const attrs = attrsOf(source, tag.index + tag[0].length)
      const type = /type="([a-z]+)"/.exec(attrs)
      if (type !== null && NO_TEXT.has(type[1])) continue
      const className = /className="([^"]*)"/.exec(attrs)
      if (className === null) continue
      found.push({
        file: srcKey(SRC, path),
        classes: className[1].split(/\s+/).filter(Boolean),
      })
    }
  }

  it('클래스를 가진 컨트롤을 실제로 찾았다 — 파서가 조용히 0건을 내지 않게', () => {
    expect(found.length).toBeGreaterThan(40)
  })

  it('붙은 클래스 중 하나가 font-size를 선언한다', () => {
    // 한 요소에 여럿이면 **하나만 가져도** 된다 — 캐스케이드가 그렇게 동작한다
    // (`acc__input acc__input--select`).
    const naked = found
      .filter((c) => c.classes.length > 0 && !c.classes.some(declaresFontSize))
      .map((c) => `${c.file} — ${c.classes.join(' ')}`)
    expect([...new Set(naked)]).toEqual([])
  })
})
