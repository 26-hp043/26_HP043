/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import blueLogRaw from '../design/tokens/BlueLog.tokens.json?raw'
import lightRaw from '../design/tokens/Light.tokens.json?raw'
import darkRaw from '../design/tokens/Dark.tokens.json?raw'

/**
 * 토큰 동기화 가드.
 *
 * `src/styles/tokens.generated.css`는 `src/design/tokens/*.json`에서 생성한다
 * (`npm run build:tokens`). **JSON만 고치고 생성을 잊으면 화면은 옛 색을 쓰면서
 * 아무도 모른다** — 빌드도 테스트도 통과하기 때문이다.
 *
 * 그래서 값 대조를 테스트로 고정한다. `TEST_PLAN` 동기화 가드와 같은 취지다:
 * **드리프트에 신호를 붙인다.**
 *
 * JSON은 `?raw`로 읽지만 **CSS는 `node:fs`로 읽는다** — vitest는 CSS 처리를 끄고
 * 있어(`test.css` 기본값) `?raw`를 붙여도 빈 문자열이 돌아온다. 조용히 빈 값이
 * 들어오면 이 가드가 아무것도 검사하지 않게 되므로 파일을 직접 읽는다.
 * 타입 참조는 이 파일에만 붙여, 앱 코드에는 node 전역이 노출되지 않게 한다.
 */

interface FlatToken {
  value: unknown
  type?: string
}

function flatten(
  node: Record<string, unknown>,
  path: string[] = [],
  out: Record<string, FlatToken> = {},
): Record<string, FlatToken> {
  for (const [key, value] of Object.entries(node)) {
    if (key.startsWith('$')) continue
    if (value && typeof value === 'object' && '$value' in value) {
      const token = value as Record<string, unknown>
      out[[...path, key].join('.')] = {
        value: token.$value,
        type: token.$type as string | undefined,
      }
    } else if (value && typeof value === 'object') {
      flatten(value as Record<string, unknown>, [...path, key], out)
    }
  }
  return out
}

/** CSS 주석을 걷어낸다 — 규칙 검사가 설명 문장에 걸리지 않게 한다. */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** 별칭 계층. 생성물이 아니라 손으로 쓰는 파일이며 fallback 체인이 여기 있다. */
const aliasCss = readFileSync(
  new URL('./tokens.css', import.meta.url),
  'utf-8',
)

const css = readFileSync(
  new URL('./tokens.generated.css', import.meta.url),
  'utf8',
)

const parse = (raw: string) => flatten(JSON.parse(raw) as Record<string, unknown>)

const primitives = parse(blueLogRaw)
const light = parse(lightRaw)
const dark = parse(darkRaw)

/** `cii.a.fill` → `--cii-a-fill` */
const cssName = (path: string) => `--${path.replace(/\./g, '-')}`

const hexOf = (token: FlatToken) =>
  (token.value as { hex?: string }).hex?.toLowerCase()

/** 지정한 선택자 블록의 본문만 떼어낸다. */
function blockAfter(marker: string): string {
  const start = css.indexOf(marker)
  expect(start, `${marker} 블록이 생성물에 없습니다`).toBeGreaterThan(-1)
  const open = css.indexOf('{', start)
  const end = css.indexOf('\n}', open)
  return css.slice(open, end)
}

const rootBlock = blockAfter('\n:root {')
const darkBlock = blockAfter(":root[data-theme='dark'] {")

const REGENERATE = '`npm run build:tokens`를 실행하십시오.'

/**
 * **정본이 이름을 적은 토큰은 실재해야 한다** (`#1022` · `#1052` 조사).
 *
 * `§9.5` 🔒가 지도 항로선을 `--semantic-info`로 정해 두었는데 **그 토큰이 존재한 적이
 * 없었다.** 코드는 규격대로 그 이름을 읽고 언제나 빈 문자열을 받아 리터럴로 떨어졌다 —
 * **잠긴 규격이 지켜지지 않는데 아무것도 실패하지 않았다.**
 *
 * 값이 맞는지를 보는 가드는 여럿 있었지만, **이름이 실재하는지**를 보는 것이 없었다.
 * 잠갔다는 것이 지켜지고 있다는 뜻은 아니다.
 */
/**
 * **CSS가 가리키는 커스텀 프로퍼티가 실재한다** (`#1052`).
 *
 * 위 검사는 **정본이 이름을 적은 것**만 본다. 그 그물에 걸리지 않는 자리가 있었다 —
 * `FleetMap.css` 하나에서만 **일곱 개**가 아무 데도 닿지 않았고(`--space-2` ·
 * `--radius-md` · `--radius-sm` · `--font-size-sm` · `--font-size-xs` ·
 * `--font-weight-bold` · `--surface-default`), 파일 머리말은 *「값은 전부 토큰에서
 * 온다」*고 적고 있었다. 저장소 전체로는 **네 파일 열 군데**였다.
 *
 * `var(--없는-것)`은 **오류가 아니라 선언 무효**다. 화면이 깨지지 않고 브라우저
 * 기본값으로 조용히 그려진다 — 죽은 CSS·규칙 없는 클래스와 같은 성질이다.
 *
 * **대체값이 있으면 넘긴다** — `var(--x, 12px)`은 없을 때 무엇을 쓸지 적어 둔 것이다.
 */
/*
 * 포커스 링은 `outline`으로 그린다 — 2026-09-18 확정 ⓐ (`#1167`).
 *
 * 종전 토큰 `--focus-ring`은 **`box-shadow` 값**(`0 0 0 3px …`)이었는데 11개
 * 규칙이 그것을 `outline: var(--focus-ring)`으로 쓰고 있었다. `outline` 단축은
 * `width | style | color`만 받으므로 값이 넷이면 **파싱에 실패해 선언이 통째로
 * 버려진다** — 20개 선택자에 **포커스 링이 아예 없었다**(`§14` 위반).
 *
 * **이것도 「화면이 안 깨지는 결함」이다.** 링이 없어도 화면은 정상으로 보이고,
 * 키보드로 다니는 사람에게만 드러난다. 그래서 가드가 없으면 또 남는다.
 *
 * 세 가지를 잠근다.
 *
 * ⑴ `--focus-ring`을 되살리지 않는다 — 이름을 바꾼 이유가 **잘못 쓰면 즉시
 *    드러나게** 하려는 것이라, 옛 이름이 돌아오면 그 장치가 무너진다
 * ⑵ `--focus-outline`을 `box-shadow`에 넣지 않는다 — 방향만 반대인 같은 실수다
 * ⑶ 링을 그리는 규칙은 `outline-offset`을 함께 갖는다 — 라이트에서 링 색과
 *    Primary 채움색이 **둘 다 `#1a365d`**라 틈이 없으면 「버튼이 커졌다」로 읽힌다
 */
describe('포커스 링은 outline이다 (#1167)', () => {
  function allCss(dir: URL, out: URL[] = []): URL[] {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, dir)
      if (entry.isDirectory()) allCss(child, out)
      else if (entry.name.endsWith('.css')) out.push(child)
    }
    return out
  }

  /** 주석을 걷어낸다 — 이력을 적어 둔 문장이 선언으로 읽히면 헛되이 실패한다. */
  const bodies = () =>
    allCss(new URL('../', import.meta.url)).map((f) => ({
      name: f.pathname.split('/').slice(-2).join('/'),
      css: readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''),
    }))

  it('옛 이름 `--focus-ring`이 되살아나지 않는다', () => {
    const back = bodies().filter(({ css }) => css.includes('--focus-ring'))
    expect(back.map((b) => b.name)).toEqual([])
  })

  it('`--focus-outline`을 `box-shadow`에 넣지 않는다', () => {
    const wrong = bodies().filter(({ css }) => /box-shadow:[^;]*--focus-outline/.test(css))
    expect(wrong.map((b) => b.name)).toEqual([])
  })

  it('링을 그리는 규칙은 `outline-offset`을 함께 갖는다', () => {
    /*
     * 선언 두 줄이 **붙어 있는지**를 본다. 규칙 단위로 파싱하지 않는 것은 CSS
     * 파서를 만드는 것이 목적이 아니기 때문이다 — 저장소의 관례가 두 줄을
     * 나란히 적는 것이고, 떨어뜨려 적으면 이 검사가 알려 준다.
     */
    const missing: string[] = []
    for (const { name, css } of bodies()) {
      for (const m of css.matchAll(/( *)outline: var\(--focus-outline\);\n(.*)/g)) {
        if (!m[2].includes('outline-offset')) missing.push(name)
      }
    }
    expect([...new Set(missing)]).toEqual([])
  })

  it('토큰이 `outline` 단축으로 파싱되는 모양이다', () => {
    const tokens = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8')
    const m = /--focus-outline:\s*([^;]+);/.exec(tokens.replace(/\/\*[\s\S]*?\*\//g, ''))
    expect(m, '--focus-outline 선언을 찾지 못했습니다').toBeTruthy()
    // `width | style | color` 셋이다 — 넷이면 `outline`이 통째로 버려진다.
    expect(m![1].trim()).toMatch(/^\S+\s+(solid|dashed|dotted|double)\s+\S+$/)
  })
})

describe('CSS가 가리키는 커스텀 프로퍼티가 실재한다 (#1052)', () => {
  function cssFiles(dir: URL, out: URL[] = []): URL[] {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, dir)
      if (entry.isDirectory()) cssFiles(child, out)
      else if (entry.name.endsWith('.css')) out.push(child)
    }
    return out
  }

  it('정의되지 않은 토큰을 참조하지 않는다', () => {
    const files = cssFiles(new URL('../', import.meta.url))
    const declared = new Set<string>()
    const referenced = new Map<string, Set<string>>()

    for (const file of files) {
      const body = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
      for (const [, name] of body.matchAll(/(--[\w-]+)\s*:/g)) declared.add(name)
      // 닫는 괄호가 바로 오는 것만 센다 — 쉼표가 오면 대체값이 있다.
      for (const [, name] of body.matchAll(/var\(\s*(--[\w-]+)\s*\)/g)) {
        const at = referenced.get(name) ?? new Set<string>()
        at.add(file.pathname.split('/src/')[1] ?? file.pathname)
        referenced.set(name, at)
      }
    }

    const orphans = [...referenced]
      .filter(([name]) => !declared.has(name))
      .map(([name, where]) => `${name} :: ${[...where].sort().join(', ')}`)

    expect(
      orphans.sort(),
      '없는 토큰을 가리키면 그 선언이 통째로 무효가 된다 — 브라우저 기본값으로 조용히 그려진다.',
    ).toEqual([])
  })
})

describe('정본이 적은 토큰 이름이 실재한다 (#1022)', () => {
  const designSystem = readFileSync(new URL('../../../DESIGN_SYSTEM.md', import.meta.url), 'utf8')

  /** 저장소 전체의 커스텀 프로퍼티 **정의**. 기능 CSS의 국지 정의까지 센다. */
  function definedEverywhere(): Set<string> {
    const found = new Set<string>()
    const walk = (dir: URL): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, dir)
        if (entry.isDirectory()) walk(child)
        else if (entry.name.endsWith('.css')) {
          for (const [, name] of readFileSync(child, 'utf8').matchAll(/(--[\w-]+)\s*:/g)) {
            found.add(name)
          }
        }
      }
    }
    walk(new URL('../', import.meta.url))
    return found
  }

  /**
   * 정본이 **일부러** 이름만 남긴 것. 넣으려면 왜 없어도 되는지 함께 적는다.
   *
   * 앞의 셋은 `#747`이 폐기한 이름이고, 정본은 「폐기했다」는 사실을 적기 위해
   * 이름을 쓴다 — 실재하면 오히려 틀린 것이라 별도 가드가 부재를 잠그고 있다.
   */
  const RETIRED: Readonly<Record<string, string>> = {
    '--text-faint': '#747이 폐기 — 부재를 다른 가드가 잠근다',
    '--color-text-faint': '#747이 폐기 — 부재를 다른 가드가 잠근다',
    '--border-faint': '#747이 폐기 — 생성하지 않기로 한 것(PR #928)',
    // `§9.5`가 **존재한 적 없는 이름을 가리키고 있었다**는 사실을 적기 위해 쓴다
    // (`#1052` 정정). 실재하면 오히려 틀린 것이다.
    '--surface-default': '§9.5 정정 기록 — 존재한 적 없던 이름',
    // `#1167` 개명 기록 — `box-shadow` 값이던 옛 포커스 링 토큰이다. 11개 규칙이
    // 그것을 `outline:`에 넣어 **20개 선택자에 링이 없었고**, 잘못 쓰면 즉시
    // 드러나도록 `--focus-outline`으로 바꿨다. 정본이 그 이력을 적고 있다.
    '--focus-ring': '#1167 개명 기록 — `--focus-outline`으로 바뀌었다',
  }

  /**
   * ⚠️ 실재해야 하는데 없는 것. 근거가 아니라 **미제**다.
   *
   * `#1052`에서 `--surface-default`가 여기 있었다 — `§9.5`가 정한 마커 그림자가
   * 그려지지 않던 자리다. 해소돼 목록이 비었다. **비어 있는 것이 정상이다.**
   */
  const UNRESOLVED: Readonly<Record<string, string>> = {}

  it('본문이 적은 토큰 이름이 CSS에 정의돼 있다', () => {
    const defined = definedEverywhere()
    const named = new Set([...designSystem.matchAll(/`(--[\w-]+)`/g)].map((m) => m[1]))
    const missing = [...named].filter(
      (name) => !defined.has(name) && !(name in RETIRED) && !(name in UNRESOLVED),
    )
    expect(
      missing.sort(),
      '정본이 이름을 적었는데 정의가 없다. 잠긴 규격이 조용히 안 지켜지는 자리다.',
    ).toEqual([])
  })

  it('두 목록이 낡지 않았다 — 생겼으면 뺀다', () => {
    const defined = definedEverywhere()
    const stale = [...Object.keys(RETIRED), ...Object.keys(UNRESOLVED)].filter((n) =>
      defined.has(n),
    )
    expect(stale, `정의가 생겼으니 목록에서 빼세요: ${stale.join(', ')}`).toEqual([])
  })

  it('§9.5가 정한 항로선 토큰이 실재한다 (#1022)', () => {
    /* 이 한 줄이 없어서 리터럴 `#1f6feb`가 1년 가까이 실제 색이었다. */
    expect(designSystem).toContain('--semantic-info')
    expect(rootBlock).toContain('--semantic-info:')
    expect(darkBlock).toContain('--semantic-info:')
  })
})

describe('디자인 토큰 — JSON과 생성 CSS가 일치한다', () => {
  it('라이트 색 토큰이 :root에 모두 있다', () => {
    const mismatched = Object.entries(light)
      .filter(([path, token]) => !rootBlock.includes(`${cssName(path)}: ${hexOf(token)};`))
      .map(([path, token]) => `${cssName(path)}: ${hexOf(token)}`)

    expect(
      mismatched,
      `Light.tokens.json과 tokens.generated.css가 어긋납니다. ${REGENERATE}`,
    ).toEqual([])
  })

  it('다크 색 토큰이 [data-theme=dark]에 모두 있다', () => {
    const mismatched = Object.entries(dark)
      .filter(([path, token]) => !darkBlock.includes(`${cssName(path)}: ${hexOf(token)};`))
      .map(([path, token]) => `${cssName(path)}: ${hexOf(token)}`)

    expect(
      mismatched,
      `Dark.tokens.json과 tokens.generated.css가 어긋납니다. ${REGENERATE}`,
    ).toEqual([])
  })

  it('두 테마의 색 토큰 키 집합이 같다', () => {
    // 한쪽에만 있으면 그 테마에서 정의되지 않은 색이 생겨 화면이 깨진다.
    expect(Object.keys(light).sort()).toEqual(Object.keys(dark).sort())
  })

  it('치수 토큰(spacing·radius·target·icon)이 생성물에 있다', () => {
    const missing = Object.keys(primitives).filter(
      (path) => !css.includes(`${cssName(path)}:`),
    )
    expect(missing, `누락된 치수 토큰: ${missing.join(', ')}. ${REGENERATE}`).toEqual([])
  })

  it('생성물을 직접 고치지 말라는 경고가 남아 있다', () => {
    expect(css).toContain('이 파일은 생성물이다')
  })
})

describe('테마 규칙 — 3-상태', () => {
  it('명시적 라이트 선택이 OS 다크를 이긴다', () => {
    expect(css).toContain('@media (prefers-color-scheme: dark)')
    expect(css).toContain(":root:not([data-theme='light'])")
  })

  it('라이트 팔레트가 속성 없는 기본 :root에 있다', () => {
    /*
     * 색을 미디어 쿼리나 [data-theme] 안에서만 정의하면, 속성이 없는 기본 상태에서
     * 그 색이 적용되지 않아 한쪽 테마의 글자가 다른 테마의 바탕 위에 얹힌다.
     */
    const missing = Object.keys(light).filter(
      (path) => !rootBlock.includes(`${cssName(path)}:`),
    )
    expect(missing, `기본 :root에 없는 색 토큰: ${missing.join(', ')}`).toEqual([])
  })
})

describe('폰트 fallback — DESIGN_SYSTEM §3 (#485)', () => {
  it('지정 폰트는 생성 토큰에서 온다 — 별칭이 이름을 다시 적지 않는다', () => {
    expect(css).toContain("--fontFamilies-sans: 'Noto Sans KR'")
    expect(aliasCss).toContain('--font-sans: var(--fontFamilies-sans)')
  })

  it('fallback 체인이 §3이 정한 그대로다', () => {
    /*
     * §3 원문 — 「**Noto Sans KR** (한글 우선) → fallback
     * `system-ui, "Malgun Gothic", sans-serif`」.
     */
    expect(aliasCss).toContain(
      "--font-sans: var(--fontFamilies-sans), system-ui, 'Malgun Gothic', sans-serif;",
    )
  })

  it('선언부에 Pretendard가 남아 있지 않다', () => {
    /*
     * v1.2까지의 지정 폰트다. §3이 「팀 환경 확보 문제로 교체했다」로 적으며
     * v2.0에서 걷어냈는데 체인에 남아 있으면, **Noto Sans KR이 없고 Pretendard가
     * 설치된 장비에서 구 폰트로 렌더된다** — 교체 자체가 무효가 된다.
     *
     * **주석은 보지 않는다.** 왜 걷어냈는지를 파일에 적어 두는 것이 이 규칙을
     * 되돌리지 않게 하는 근거인데, 원문 전체를 훑으면 그 설명 자체가 실패가 된다.
     */
    const declarations = stripComments(aliasCss) + stripComments(css)
    expect(declarations).not.toContain('Pretendard')
  })
})

/**
 * 문자로 쓰는 시맨틱 색의 대비 가드 — `DESIGN_SYSTEM §0.2` 제약 1 (`#485`).
 *
 * ## 왜 값을 눈으로 보지 않고 계산하는가
 *
 * `--color-danger`(#e53e3e)는 라이트에서 **4.13:1**, `--color-warning`(#d97b14)은
 * **3.09:1**이다. 둘 다 4.5:1에 못 미치는데 **화면이 깨지지 않아** 오래 남아 있었다.
 * 다크에서는 통과하므로 다크 모드 검수로도 드러나지 않았다.
 *
 * 그래서 문자 전용 별칭(`--color-*-text`)을 두었고, **그 값이 실제로 통과하는지를
 * 계산으로 건다.** 나중에 누가 「시맨틱 색으로 되돌리자」며 값을 바꾸면 여기서 걸린다.
 */
function relativeLuminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const linear = channels.map((c) =>
    c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('문자용 시맨틱 색 대비 — §0.2 제약 1 (#485)', () => {
  /** 라이트 `--surface-card`. 오류 문구·배지가 얹히는 바탕이다. */
  const LIGHT_SURFACE = '#ffffff'

  const declared = (name: string): string => {
    // 별칭은 `tokens.css`에 있다 — 생성물(`css`)이 아니라 `aliasCss`를 본다.
    const found = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(aliasCss)
    expect(found, `${name}이 tokens.css에 hex로 선언돼 있지 않다`).not.toBeNull()
    return (found as RegExpExecArray)[1].toLowerCase()
  }

  it('--color-danger-text가 흰 바탕에서 4.5:1을 넘는다', () => {
    const value = declared('--color-danger-text')
    expect(contrast(value, LIGHT_SURFACE)).toBeGreaterThanOrEqual(4.5)
  })

  it('--color-warning-text가 흰 바탕에서 4.5:1을 넘는다', () => {
    const value = declared('--color-warning-text')
    expect(contrast(value, LIGHT_SURFACE)).toBeGreaterThanOrEqual(4.5)
  })

  /*
   * 종전 값을 그대로 다시 넣는 것을 막는다. 「시맨틱 토큰이 있는데 왜 별칭을
   * 쓰나」는 합리적인 의문이고, 답은 **그 값이 문자로 쓸 수 없다**는 것이다.
   */
  it('생성 토큰의 Danger·Warning은 문자로 쓰기에 모자란다 — 별칭이 필요한 이유', () => {
    expect(contrast('#e53e3e', LIGHT_SURFACE)).toBeLessThan(4.5)
    expect(contrast('#d97b14', LIGHT_SURFACE)).toBeLessThan(4.5)
  })
})

/**
 * 중립 면 위의 대비 — `DESIGN_SYSTEM §0.2` 제약 1 · `§2.2`.
 *
 * ## 왜 면(surface)에 가드를 거는가
 *
 * 종전 가드는 **문자색만** 봤다. 그런데 대비는 두 값의 관계이고, 지금까지
 * **바닥이 움직이지 않는다고 가정**하고 있었다.
 *
 * 그 가정이 실제로 깨졌다. `#699`가 `--text-faint`를 문자에서 걷어내면서
 * 면적·비활성에는 남겼고 그 근거가 **「비텍스트 3:1을 넘는다」**였는데, 그 근거는
 * 면 값에 매달려 있다. 라이트 중립이 `§2.2` 쿨톤으로 정렬될 때 `--surface-inset`
 * 위 값이 **3.26 → 3.08**로 내려왔다. 통과하지만 **여섯 조합 중 가장 빠듯한
 * 자리**이고, 면을 한 단만 더 어둡게 잡으면 여기가 먼저 깨진다.
 *
 * 그때 깨지는 것은 색이 아니라 **`#699`가 남긴 예외 세 자리의 정당성**이다.
 * 화면은 멀쩡히 그려지므로 눈으로는 잡히지 않는다 — `#620`·`#699`가 겪은 것과
 * 같은 형태다.
 *
 * ## 무엇을 거는가
 *
 * 세 면 × 두 테마 × 세 문자 토큰. `§16 항목 3`(중립색 팔레트)이 열려 있어
 * **이 값들은 앞으로도 움직인다.** 움직여도 좋되, 기준을 밟으면 여기서 멈춘다.
 */
describe('중립 면 위 대비 — §2.2 · §16 항목 3', () => {
  const SURFACES = ['surface.card', 'surface.page', 'surface.inset'] as const

  /** `--text-muted`는 문서의 `text-faint`다 — 위 블록의 경고 참조. */
  const ROLES = [
    { key: 'text.primary', label: '본문', min: 4.5, basis: '§0.2 제약 1' },
    { key: 'text.secondary', label: '보조 문자', min: 4.5, basis: '§0.2 제약 1' },
    { key: 'text.muted', label: 'faint(면적·비활성)', min: 3, basis: '비텍스트 3:1' },
  ] as const

  const THEMES = [
    ['라이트', light],
    ['다크', dark],
  ] as const

  for (const [themeName, tokens] of THEMES) {
    for (const surface of SURFACES) {
      for (const role of ROLES) {
        it(`${themeName} — ${role.label}가 ${surface} 위에서 ${role.min}:1을 넘는다 (${role.basis})`, () => {
          const bg = hexOf(tokens[surface])
          const fg = hexOf(tokens[role.key])
          expect(bg, `${surface}가 ${themeName} 토큰에 없습니다`).toBeTruthy()
          expect(fg, `${role.key}가 ${themeName} 토큰에 없습니다`).toBeTruthy()
          expect(contrast(fg as string, bg as string)).toBeGreaterThanOrEqual(role.min)
        })
      }
    }
  }

  /*
   * 면과 카드가 **구분돼 보이는지**는 대비비로 잴 수 없다. 색상(hue)차가 명도차를
   * 대신하기 때문이다 — 웜 `#f2f2ef`는 흰 카드와 명도비 1.12로 쿨 `#f4f6f9`(1.08)
   * 보다 큰데도 더 밋밋하게 읽혔다. 그래서 여기서는 **명도가 아니라 「페이지가
   * 카드와 다른 값이다」**만 건다. 같아지면 카드가 사라진다.
   */
  it('페이지 배경과 카드 면이 같은 값이 아니다', () => {
    for (const [themeName, tokens] of THEMES) {
      expect(
        hexOf(tokens['surface.page']),
        `${themeName}에서 페이지와 카드가 같은 값이면 카드가 면으로 보이지 않는다`,
      ).not.toBe(hexOf(tokens['surface.card']))
    }
  })
})

describe('시맨틱 색을 문자색으로 쓰지 않는다 — §0.2 제약 1 (#620)', () => {
  /**
   * `#485` ⑤가 문자 전용 별칭을 만들고 **두 곳만** 옮겼고, `#620`이 나머지 33곳을
   * 옮겼다. 이 가드는 **다시 들어오는 것**을 막는다 — 새 화면이 무심코
   * `color: var(--color-danger)`를 쓰면 라이트에서 4.13:1이 되는데, **화면이 깨지지
   * 않아** 그 상태가 오래 남는다(실제로 그랬다).
   *
   * **면적 색은 보지 않는다.** `background`·`border`는 비텍스트라 3:1이면 충분하고,
   * 문자 전용 별칭으로 바꾸면 면적이 어두워져 등급 색과 충돌한다.
   */
  const OFFENDERS = ['--semantic-danger', '--color-danger', '--color-warning']

  function cssFiles(dir: string): string[] {
    const out: string[] = []
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules') continue
        out.push(...cssFiles(full))
      } else if (entry.name.endsWith('.css')) {
        out.push(full)
      }
    }
    return out
  }

  const HERE = fileURLToPath(new URL('.', import.meta.url))
  const files = cssFiles(join(HERE, '..'))

  it('훑을 CSS 파일을 실제로 찾았다', () => {
    // 수집이 깨지면 아래 대조가 전부 무의미해진다 — 그것부터 막는다.
    expect(files.length).toBeGreaterThanOrEqual(15)
  })

  it('color 선언에 시맨틱 원본 색이 없다', () => {
    // `border-color:`·`background-color:`는 앞에 `-`가 있어 걸리지 않는다.
    const pattern = new RegExp(
      `(?<![-\\w])color:\\s*var\\((${OFFENDERS.join('|')})\\)`,
    )
    const hits: string[] = []
    for (const file of files) {
      readFileSync(file, 'utf-8')
        .split('\n')
        .forEach((line, i) => {
          if (pattern.test(line)) hits.push(`${file}:${i + 1}  ${line.trim()}`)
        })
    }
    expect(hits, `문자 전용 별칭(--color-*-text)으로 바꾸세요:\n${hits.join('\n')}`).toEqual(
      [],
    )
  })

  it('면적 색은 원본을 그대로 쓴다 — 바꾸면 등급 색과 충돌한다', () => {
    const area = new RegExp(
      `(background|border)[a-z-]*:\\s*[^;]*var\\((${OFFENDERS.join('|')})\\)`,
    )
    const kept = files.filter((f) => area.test(readFileSync(f, 'utf-8')))
    expect(kept.length).toBeGreaterThan(0)
  })
})

describe('faint 계열을 문자색으로 쓰지 않는다 — §2.2 · §16 항목 1 ⓐ', () => {
  /**
   * **이름이 같아 보이는 것이 다른 값이다.** 생성 토큰 `--text-muted`는 문서의
   * `text-muted`가 아니라 **`text-faint`**(`#8b8a83` / dark `#6b7686`)이며,
   * 라이트 3.08~3.46:1 · 다크 3.47~4.11:1로 **양쪽 모두 §0.2 제약 1(4.5:1) 미달**이다.
   *
   * 그런데 이 값을 문자색으로 쓰는 자리가 **53곳**이었다 — 대시보드·실시간 CII·
   * 선박 상세의 라벨과 캡션이 전부 여기 걸려 있었다. `#620`이 시맨틱 색에서 겪은 것과
   * 같은 형태다: **화면이 깨지지 않아** 아무도 못 잡는다.
   *
   * 이 가드는 다시 들어오는 것을 막는다. 값을 바꾸는 길(§16-1 ⓑ)로는 닫히지 않는다 —
   * `#647380`의 `4.86:1`은 흰 카드 위 값이고 `--surface-inset` 위에서는 `4.34:1`이다.
   *
   * ## 허용하는 자리 둘 — 문자가 아니다
   *
   * ⑴ **면적** — `background`는 아예 보지 않는다. 비텍스트 3:1 기준이다
   * ⑵ **비활성** — `:disabled` · `--disabled`. WCAG 1.4.3이 비활성 요소를 제외한다
   *
   * 아이콘 두 개(`--color`가 `stroke: currentcolor`로 흘러가는 자리)는 문자가 아니라
   * 그래픽이므로 이름으로 예외를 둔다. **선택자를 적어 두면 새 자리가 조용히
   * 늘어나지 않는다** — 늘리려면 이 목록을 고쳐야 하고, 그건 리뷰에 걸린다.
   */
  /*
   * `--color-text-faint`는 `#747`에서 **폐기**되고 용도별로 쪼개졌다.
   * 그래도 목록에 남겨 둔다 — **되살아나는 것**을 잡아야 하기 때문이다.
   */
  const FAINT = [
    '--color-text-faint',
    '--color-text-disabled',
    '--color-surface-muted',
    '--text-muted',
  ]
  const ICON_EXCEPTIONS = ['.app-shell__util-icon', '.app-shell__iconbtn', '.history__swatch']

  // 위 describe의 수집기는 그 블록 안에 갇혀 있다. 같은 규칙으로 다시 모은다.
  function collect(dir: string): string[] {
    const out: string[] = []
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules') continue
        out.push(...collect(full))
      } else if (entry.name.endsWith('.css')) {
        out.push(full)
      }
    }
    return out
  }

  const HERE = fileURLToPath(new URL('.', import.meta.url))
  const files = collect(join(HERE, '..'))

  it('훑을 CSS 파일을 실제로 찾았다', () => {
    expect(files.length).toBeGreaterThanOrEqual(15)
  })

  function faintTextHits(file: string): string[] {
    const hits: string[] = []
    let selector = ''
    let pending: string[] = []
    readFileSync(file, 'utf-8')
      .split('\n')
      .forEach((raw, i) => {
        const line = raw.trim()
        if (line.endsWith('{')) {
          pending.push(line.slice(0, -1).trim())
          selector = pending.join(' ')
          pending = []
        } else if (line.endsWith(',') && !line.startsWith('/') && !line.includes(':')) {
          pending.push(line)
        }
        const decl = new RegExp(
          `^(color|fill)\\s*:\\s*var\\((${FAINT.join('|')})\\)\\s*;`,
        ).exec(line)
        if (!decl) return
        if (/:disabled|--disabled/.test(selector)) return
        if (ICON_EXCEPTIONS.some((s) => selector.includes(s))) return
        hits.push(`${file}:${i + 1}  ${selector} { ${line} }`)
      })
    return hits
  }

  it('color·fill 선언에 faint 계열이 없다 (비활성·아이콘 제외)', () => {
    const hits = files.flatMap(faintTextHits)
    expect(
      hits,
      `라벨·캡션·힌트는 --color-text-muted(=--text-secondary, 6.49:1)를 씁니다:\n${hits.join('\n')}`,
    ).toEqual([])
  })

  it('`--color-text-faint`가 폐기됐다 — 용도별 토큰으로 쪼개졌다 (#747)', () => {
    /*
     * 이름만 `text`이고 **글자에 쓰이는 자리는 하나도 없었다.** 남은 용도가
     * 비활성과 면적뿐이라 그 둘로 갈랐다. 이름을 되살리면 「문자에 써도 되는
     * 토큰」이라는 오해가 함께 돌아온다.
     */
    const tokens = readFileSync(join(HERE, 'tokens.css'), 'utf-8')
    expect(tokens).not.toMatch(/^\s*--color-text-faint:/m)
    expect(tokens).toMatch(/^\s*--color-text-disabled:/m)
    expect(tokens).toMatch(/^\s*--color-surface-muted:/m)
  })

  it('쪼갠 토큰이 각자 실제로 쓰인다', () => {
    const all = files.map((f) => readFileSync(f, 'utf-8')).join('\n')
    // 비활성 — `:disabled` 규칙 안에서 쓰인다.
    expect(all).toMatch(/var\(--color-text-disabled\)/)
    // 면적 — `background` 계열로 쓰인다.
    expect(all).toMatch(/background[a-z-]*:\s*var\(--color-surface-muted\)/)
  })

  it('세 번째 토큰은 선언과 사용이 함께 간다 — 한쪽만 있으면 실패한다 (#747)', () => {
    /*
     * `rlatnals4114`의 2026-09-10 확정 문서가 이름을 부른 토큰 셋 중 **하나는 만들지 않았다.** 아이콘
     * stroke·테두리 용도인데 그 자리가 저장소에 **0곳**이고, 같은 날 `#831`이
     * 참조 0건 토큰 10개를 걷어낸 참이었다. 바로 뒤에 참조 0건 토큰을 새로
     * 만들면 같은 규율이 한 PR 안에서 반대로 간다.
     *
     * 그래서 「지금 만들지 않는다」가 아니라 **「선언과 사용이 함께 간다」**를
     * 잠근다 — 미룬 것을 잠그면 쓸 자리가 생겼을 때 가드를 지워야 하고, 지우는
     * 순간 판단이 사라진다. 이 형태면 쓸 자리가 생기는 날 **선언 한 줄을 더하는
     * 것만으로** 통과하고, 소비처 없이 되살리면 그때 걸린다.
     *
     * ## 주석을 걷어내는 두 자리는 성격이 다르다
     *
     * - `all` 쪽은 **실측으로 무는 것을 확인했다.** 다른 CSS가 주석으로
     *   `var(--border-faint)를 쓸 예정`이라고만 적어도, 걷어내지 않으면 그 문장이
     *   **사용으로 읽혀** 이 가드가 헛되이 실패한다
     * - `tokens.css` 쪽은 **선제 조치다.** 지금 설명문은 `이름(용도)는` 꼴이고
     *   블록 주석 줄이 `*`로 시작해 걷어내지 않아도 통과한다 — 확인했다.
     *   `이름: 값` 꼴 예시가 한 줄 들어오는 순간 자기 설명을 선언으로 읽는다
     *
     * `#831`·`#829`·`#694`에서 세 번 밟은 함정이라 양쪽 다 먼저 막는다.
     */
    const NAME = '--border-faint'
    const tokens = stripComments(readFileSync(join(HERE, 'tokens.css'), 'utf-8'))
    const all = stripComments(files.map((f) => readFileSync(f, 'utf-8')).join('\n'))

    const declared = new RegExp(`^\\s*${NAME}:`, 'm').test(tokens)
    const used = new RegExp(`var\\(${NAME}[),]`).test(all)

    expect(declared).toBe(used)
  })
})

/**
 * Primary 채움면 위 글자 대비 — `DESIGN_SYSTEM §0.2` 제약 1 (`#717`).
 *
 * ## 종전 가드가 못 보던 자리
 *
 * 위 두 가드는 **문자색 × 중립 면**만 본다. 그런데 `§8`이 정의한 Primary 버튼은
 * 글자가 **브랜드색 면 위**에 얹힌다. 그 조합은 어느 가드에도 걸리지 않았고,
 * 실제로 **아바타가 다크에서 3.76:1**인 채로 남아 있었다.
 *
 * ## `color-mix`를 계산한다
 *
 * 채움면은 다크에서 `color-mix(in srgb, var(--semantic-primary) 70%, var(--surface-page))`다.
 * hex가 아니므로 위쪽 `declared()`처럼 정규식으로 뽑아 쓸 수 없다 — **여기서 직접
 * 계산한다.** 계산하지 않으면 이 자리는 「선언돼 있다」까지만 확인되고 **값이 맞는지는
 * 아무도 안 보는 상태**로 되돌아간다.
 *
 * 지원하는 문법은 이 파일이 실제로 쓰는 두 가지뿐이다 — `var(--x)`와
 * `color-mix(in srgb, <색> N%, <색>)`. 더 넓히지 않는다. CSS 파서를 만드는 것이
 * 목적이 아니라 **세 값이 4.5:1을 넘는지**를 잠그는 것이 목적이다.
 */
describe('Primary 채움면 위 글자 대비 — §0.2 제약 1 (#717)', () => {
  /** `cii.a.fill` 꼴 경로를 CSS 이름으로 바꿔 hex를 찾는 표. */
  const hexTable = (theme: Record<string, FlatToken>): Record<string, string> =>
    Object.fromEntries(
      Object.entries(theme)
        .map(([path, token]) => [cssName(path), hexOf(token)])
        .filter(([, hex]) => typeof hex === 'string'),
    ) as Record<string, string>

  /** 별칭 파일의 한 블록에서 `--name: value;` 를 전부 걷는다. */
  function declarationsIn(marker: string): Record<string, string> {
    const start = aliasCss.indexOf(marker)
    expect(start, `${marker} 블록이 tokens.css에 없습니다`).toBeGreaterThan(-1)
    const body = stripComments(aliasCss.slice(start + marker.length))
    const end = body.indexOf('\n}')
    const found: Record<string, string> = {}
    for (const [, name, value] of body
      .slice(0, end)
      .matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
      found[name] = value.trim()
    }
    return found
  }

  const lightAlias = declarationsIn('\n:root {')
  const darkAlias = {
    ...lightAlias,
    ...declarationsIn("\n:root[data-theme='dark'] {"),
  }

  function mix(a: string, b: string, percent: number): string {
    const at = percent / 100
    const channel = (i: number) =>
      Math.round(
        parseInt(a.slice(i, i + 2), 16) * at + parseInt(b.slice(i, i + 2), 16) * (1 - at),
      )
    return `#${[1, 3, 5].map((i) => channel(i).toString(16).padStart(2, '0')).join('')}`
  }

  function evaluate(expression: string, generated: Record<string, string>, alias: Record<string, string>): string {
    const value = expression.trim()

    if (/^#[0-9a-fA-F]{6}$/.test(value)) return value.toLowerCase()

    const variable = /^var\((--[\w-]+)\)$/.exec(value)
    if (variable) {
      const name = variable[1]
      const resolved = generated[name] ?? alias[name]
      expect(resolved, `${name}을 찾지 못했습니다`).toBeDefined()
      return evaluate(resolved as string, generated, alias)
    }

    const mixed = /^color-mix\(in srgb,\s*(.+?)\s+(\d+)%,\s*(.+)\)$/.exec(value)
    if (mixed) {
      return mix(
        evaluate(mixed[1], generated, alias),
        evaluate(mixed[3], generated, alias),
        Number(mixed[2]),
      )
    }

    throw new Error(`지원하지 않는 색 표현입니다: ${value}`)
  }

  const THEMES = [
    { name: '라이트', generated: hexTable(light), alias: lightAlias },
    { name: '다크', generated: hexTable(dark), alias: darkAlias },
  ]

  it.each(THEMES)('$name — 채움면 위 글자가 4.5:1 이상이다', ({ generated, alias }) => {
    const fill = evaluate(alias['--color-primary-solid'], generated, alias)
    const hover = evaluate(alias['--color-primary-solid-hover'], generated, alias)
    const text = evaluate(alias['--color-on-primary'], generated, alias)

    expect(contrast(text, fill)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(text, hover)).toBeGreaterThanOrEqual(4.5)
  })

  /*
   * #829 ⑵ — **링크 문자색**이 네 면 위에서 4.5:1을 넘는다.
   *
   * 종전에는 `--color-primary`를 그대로 글자로 썼고, 다크에서 popover 3.39 ·
   * card 3.76 · inset 4.10 · page 4.44로 **네 면 모두 미달**이었다. 바로 위
   * 채움면 검사가 같은 색을 「면」으로 쓸 때만 보고 있어, **글자로 쓰는 경로가
   * 그대로 남아 있었다.**
   */
  const TEXT_SURFACES = ['--surface-card', '--surface-page', '--surface-inset', '--surface-popover']

  it.each(THEMES)('$name — 링크 문자색이 네 면 위에서 4.5:1 이상이다', ({ generated, alias }) => {
    const link = evaluate(alias['--color-link'], generated, alias)
    for (const surface of TEXT_SURFACES) {
      expect(
        contrast(link, generated[surface]),
        `${surface} 위 링크 대비`,
      ).toBeGreaterThanOrEqual(4.5)
    }
  })

  /*
   * #829 ⑴ — 포커스 링에 **알파를 넣지 않는다.**
   *
   * `45%` 알파 한 줄이 8개 면 조합을 전부 무너뜨렸다(2.03~2.50). 색 자체는 옳았고
   * 불투명이면 라이트 12.14 · 다크 4.82로 통과한다. 반투명이 배경과 섞이면서
   * 실효 대비가 떨어진 것이라, **투명도가 다시 들어오는 것**을 막는다.
   */
  it('포커스 링이 반투명이 아니다', () => {
    const value = lightAlias['--focus-outline']
    expect(value, '--focus-outline을 찾지 못했습니다').toBeDefined()
    expect(value).not.toMatch(/transparent|color-mix|rgba?\(|\/\s*\d/)
  })

  /*
   * #829 ⑶ — **폼 컨트롤 테두리**가 양면에서 3:1을 넘는다.
   *
   * 입력칸은 **면으로 식별되지 않는다.** 컨트롤 면(`surface-inset`)과 패널
   * 면(`surface-card`)의 대비가 라이트 `1.12` · 다크 `1.09`라 테두리가 유일한
   * 경계이고, `1.4.11`의 비텍스트 `3:1`이 그대로 걸린다.
   *
   * **양면을 모두 잰다.** 테두리는 안쪽 면과 바깥 면 사이에 놓이므로 한쪽만 보면
   * 통과 판정이 틀린다 — 종전 `--color-border-strong`은 라이트에서 안쪽 `1.42` ·
   * 바깥 `1.60`으로 **둘 다** 미달이었다.
   *
   * ⚠️ 라이트 여유가 `0.08`뿐이다(`3.08`). `--text-muted`를 가리키는 **임시**이며
   * 정본 값은 Figma 소관이다(`tokens.css`의 선언부 주석 참조). 이 검사는 그 교체
   * 뒤에도 유효하다 — **무엇을 가리키든 3:1을 지켜야 한다**를 잠근다.
   */
  /*
   * #829 ⑷ — **「등급 없음」 배지의 문자**가 배지 면 위에서 4.5:1을 넘는다.
   *
   * 그 배지는 등급 문자를 그리지 않는다 — `—` 하나다. 그래서 등급 채널이 아니고
   * (`§0.2` 제약 2), 종전 `--cii-none-text`는 **다크에서 3.79**로 미달이었다.
   *
   * **토큰 이름이 아니라 실제 대비를 잰다.** `#748`이 `.warn`에서 이름 기반 가드를
   * 쓰다 등급 문자가 **있는** 자리까지 시맨틱으로 바꿔 놓은 선례가 있다 — 이름은
   * 맥락을 모른다. 여기서는 CSS가 실제로 무엇을 가리키든 **읽히는가**만 본다.
   */
  const noneBadgeCss = readFileSync(
    join(fileURLToPath(new URL('.', import.meta.url)), '../features/fleet/FleetDashboard.css'),
    'utf-8',
  )

  it.each(THEMES)('$name — 등급 없음 배지의 문자가 4.5:1 이상이다', ({ generated, alias }) => {
    const rule = /\.vessel__mark--none\s*\{([\s\S]*?)\}/.exec(noneBadgeCss)
    expect(rule, '.vessel__mark--none 규칙을 찾지 못했습니다').not.toBeNull()

    const decl = /(?:^|;|\*\/)\s*color\s*:\s*([^;]+);/.exec((rule as RegExpExecArray)[1])
    expect(decl, '배지의 color 선언을 찾지 못했습니다').not.toBeNull()

    const text = evaluate((decl as RegExpExecArray)[1].trim(), generated, alias)
    const bg = evaluate(generated['--cii-none-bg'], generated, alias)
    expect(
      contrast(text, bg),
      '등급 없음 배지 문자 — 1.4.3 4.5:1 (#829 ⑷)',
    ).toBeGreaterThanOrEqual(4.5)
  })

  /*
   * `#1170` ⑴ — **같은 배지의 테두리도 등급 축이 아니다.**
   *
   * `#829` ⑷가 문자를 중립으로 옮기면서 **두 줄 아래 `border`는 그대로 두었다.**
   * `--cii-none-border`는 배지면 위 라이트 `1.51` · 다크 `1.72`로 `1.4.11`의 `3:1`에
   * 미달이었고, 그보다 먼저 `§0.2` 제약 2에 걸린다 — 이 배지는 등급 문자를 그리지
   * 않으므로(`VesselMark.tsx`가 `—` 하나만 낸다) 등급 채널이 아니다. `#1168`이
   * `.vessel--risk`에서 걷어낸 것과 같은 결함이다.
   *
   * 두 가지를 함께 본다: **등급 토큰이 아닐 것**과 **양면에서 3:1일 것**. 앞엣것만
   * 보면 중립이되 안 보이는 값으로 갈 수 있고, 뒤엣것만 보면 대비를 넘기는 등급
   * 색으로 되돌아갈 수 있다 — `#748`이 이름 기반 가드로 밟은 함정이다.
   */
  const NONE_FACES = ['--cii-none-bg', '--surface-card']

  it.each(THEMES)('$name — 등급 없음 배지 테두리가 등급 축 밖이고 3:1 이상이다 (#1170)', ({
    generated,
    alias,
  }) => {
    const rule = /\.vessel__mark--none\s*\{([\s\S]*?)\n\}/.exec(noneBadgeCss)
    expect(rule, '.vessel__mark--none 규칙을 찾지 못했습니다').not.toBeNull()

    const decl = /(?:^|;|\*\/)\s*border\s*:\s*([^;]+);/.exec((rule as RegExpExecArray)[1])
    expect(decl, '배지의 border 선언을 찾지 못했습니다').not.toBeNull()

    const shorthand = (decl as RegExpExecArray)[1]
    const color = /var\(\s*(--[\w-]+)\s*\)\s*$/.exec(shorthand.trim())
    expect(color, `테두리 색을 토큰으로 읽지 못했습니다: ${shorthand}`).not.toBeNull()

    const name = (color as RegExpExecArray)[1]
    expect(
      /^--cii-/.test(name),
      `등급 없음 배지 테두리가 등급 토큰(${name})이다 — 이 배지는 등급 문자를 그리지 않는다 (§0.2 제약 2 · #1170)`,
    ).toBe(false)

    const value = evaluate(`var(${name})`, generated, alias)
    for (const face of NONE_FACES) {
      expect(
        contrast(value, evaluate(generated[face] ?? `var(${face})`, generated, alias)),
        `${face} 위 배지 테두리 — 1.4.11 비텍스트 3:1 (#1170 ⑴)`,
      ).toBeGreaterThanOrEqual(3)
    }
  })

  /*
   * `#1202` — **경계가 테두리뿐인 컨트롤은 네 면에서 3:1이다.**
   *
   * `#829` ⑶이 폼 컨트롤에서, `#1170` ⑴이 배지에서 같은 판단을 내렸는데 **범위가
   * 그 둘이라 나머지가 남았다.** 세 번 연 자리다. 그래서 이번에는 **토큰 이름이
   * 아니라 역할로** 잠근다 — 이슈 본문이 `--color-border-strong`으로 범위를 잡았다가
   * 더 나쁜 `--border-default`(라이트 최소 `1.15`) 아홉 곳을 놓쳤던 것이 그 증거다.
   *
   * 역할의 표식은 둘이다 — `cursor: pointer`이고, **테두리 색이 배경색과 다르다**.
   * 뒤엣것이 「아웃라인」의 정의다. 테두리와 배경이 같은 색이면 채움 버튼이고, 그쪽은
   * 식별을 **면**이 지므로 재는 대상이 다르다(면 대 주변). 여기서 함께 재면 규칙이
   * 둘 섞인다.
   *
   * 토큰은 네 면 어디에 놓여도 `3:1`을 넘어야 한다 — 실제 면을 소스에서 알 수 없으므로
   * **가장 빠듯한 쪽으로 판정한다**(`§0.2` 제약 6의 규율).
   *
   * 예외 목록을 두지 않는다 — 아웃라인 컨트롤이 쓰는 색 토큰이 전부 통과한다. 목록이
   * 생기는 순간 「예외로 넣으면 된다」가 되고, 그것이 `#748`이 밟은 길이다.
   */
  const POINTER_RULE = /([^{}]*)\{([^}]*cursor:\s*pointer[^}]*)\}/g

  function controlBorders(): { where: string; token: string }[] {
    const found: { where: string; token: string }[] = []
    for (const file of cssFilesUnder(CSS_ROOT)) {
      const body = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
      for (const [, selector, rule] of body.matchAll(POINTER_RULE)) {
        const decl = /border(?:-color)?:\s*[^;]*var\(\s*(--[\w-]+)\s*\)/.exec(rule)
        if (decl === null) continue
        // 채움 버튼(테두리색 = 배경색)은 면이 식별을 지므로 이 검사의 역할이 아니다.
        const fill = /background(?:-color)?:\s*var\(\s*(--[\w-]+)\s*\)/.exec(rule)
        if (fill !== null && fill[1] === decl[1]) continue
        found.push({
          where: `${file.slice(CSS_ROOT.length)} :: ${selector.trim().split('\n')[0].trim()}`,
          token: decl[1],
        })
      }
    }
    return found
  }

  it('컨트롤 테두리를 토큰으로 그리는 자리가 실제로 있다', () => {
    // 정규식이 헛돌면 아래가 공집합 통과가 된다 — 먼저 잠근다.
    expect(controlBorders().length).toBeGreaterThan(10)
  })

  it.each(THEMES)('$name — 컨트롤 테두리가 네 면에서 3:1 이상이다 (#1202)', ({
    generated,
    alias,
  }) => {
    const offenders: string[] = []
    for (const { where, token } of controlBorders()) {
      const color = evaluate(`var(${token})`, generated, alias)
      for (const surface of TEXT_SURFACES) {
        const ratio = contrast(color, generated[surface])
        if (ratio < 3) offenders.push(`${where} — ${token} on ${surface} = ${ratio.toFixed(2)}`)
      }
    }
    expect(offenders, '경계가 테두리뿐인 컨트롤 — 1.4.11 비텍스트 3:1 (#1202)').toEqual([])
  })

  /*
   * `#1296` — **채움 Primary 컨트롤의 경계는 테두리가 맡는다** (2026-09-22 확정 · `DESIGN_SYSTEM §14`).
   *
   * 다크 채움면(`#385c8d`)은 주변과 `2.35`~`2.78`이고, 면을 띄우면 그 위 글자(`5.60`)가
   * `4.5` 밑으로 내려간다. 그래서 면이 아니라 **테두리로** `3:1`을 채운다.
   *
   * 역할의 표식 — 채움면(`--color-primary-solid`)을 칠하고, **테두리를 선언하거나 누를 수
   * 있는**(`cursor: pointer`) 규칙이다. 테두리 없는 채움(계정 메뉴의 머리글자 원 — 버튼 안의
   * 장식)과 비활성(`cursor: progress`)은 표식에 걸리지 않는다. 예외 목록을 두지 않는다.
   *
   * 종전의 `transparent` · `none` · 면과 같은 토큰은 모두 **테두리가 없는 것과 같다.**
   */
  const FILL_RULE = /([^{}]*)\{([^}]*background(?:-color)?:\s*var\(\s*--color-primary-solid\s*\)[^}]*)\}/g

  function primaryFillControls(): { where: string; rule: string }[] {
    const found: { where: string; rule: string }[] = []
    for (const file of cssFilesUnder(CSS_ROOT)) {
      const body = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
      for (const [, selector, rule] of body.matchAll(FILL_RULE)) {
        const hasBorder = /(^|;|\s)border(?:-color)?\s*:/.test(rule)
        const pressable = /cursor:\s*pointer/.test(rule)
        if (!hasBorder && !pressable) continue
        found.push({
          where: `${file.slice(CSS_ROOT.length)} :: ${selector.trim().split('\n')[0].trim()}`,
          rule,
        })
      }
    }
    return found
  }

  it('채움 Primary 컨트롤은 테두리를 `--color-primary-solid-border`로 그린다 (#1296)', () => {
    const controls = primaryFillControls()
    // 정규식이 헛돌면 공집합 통과가 된다 — 지금 다섯 자리가 있다.
    expect(controls.length).toBeGreaterThanOrEqual(5)
    const offenders = controls
      .filter(({ rule }) => !/border(?:-color)?:[^;]*var\(\s*--color-primary-solid-border\s*\)/.test(rule))
      .map(({ where }) => where)
    expect(offenders, '채움 Primary 컨트롤의 경계는 테두리가 맡는다 (#1296)').toEqual([])
  })

  it.each(THEMES)('$name — 채움 Primary 테두리가 네 면에서 3:1 이상이다 (#1296)', ({ generated, alias }) => {
    const border = evaluate('var(--color-primary-solid-border)', generated, alias)
    for (const surface of TEXT_SURFACES) {
      expect(contrast(border, generated[surface]), `${surface} 위 채움 Primary 테두리`).toBeGreaterThanOrEqual(3)
    }
  })

  it('다크 채움면은 여전히 주변과 3:1이 안 된다 — 테두리가 필요한 이유 (#1296)', () => {
    /*
     * 이 사실이 바뀌면(면을 띄우는 파생 · Figma 값 변경) 테두리 규칙을 다시 볼 때다.
     * 그때 글자 대비(위 「채움면 위 글자」 검사)도 함께 움직인다.
     */
    const dark = THEMES.find((t) => t.name === '다크')
    expect(dark, '다크 테마를 찾지 못했습니다').toBeDefined()
    const { generated, alias } = dark as (typeof THEMES)[number]
    const fill = evaluate(alias['--color-primary-solid'], generated, alias)
    expect(contrast(fill, generated['--surface-card'])).toBeLessThan(3)
  })

  /*
   * `#985` — **개략도의 해안선은 장식이 아니다.**
   *
   * 베이스맵 자산이 없는 환경에서는 `PositionChart`가 대신 뜬다. 거기서 육지·바다는
   * 배경처럼 보이지만 **배 위치를 읽는 좌표계 자체**라, `§14` 갈래 표의 「위치를 읽는
   * 기준틀」로 `3:1`이 걸린다.
   *
   * 종전에는 셋이 전부 1.1~1.3이었다 — 육지면 대 바다 `1.15` · 윤곽 대 육지면 `1.23`.
   * **셋 다 토큰이라 값이 맞는지 보는 가드는 있었어도, 서로 갈리는지 보는 것은
   * 없었다.** 한 토큰만 재면 이 상태가 통과한다.
   *
   * 그래서 **두 대비를 함께** 본다: 윤곽 대 바다(카드 안의 면)와 윤곽 대 육지 채움.
   * 앞엣것만 보면 육지 안쪽에서 선이 사라지고, 뒤엣것만 보면 바다 위에서 사라진다.
   */
  const CHART_CSS = readFileSync(
    fileURLToPath(new URL('../features/fleet/PositionChart.css', import.meta.url)),
    'utf-8',
  )

  it.each(THEMES)('$name — 개략도 해안선이 바다·육지 양쪽에서 3:1 이상이다 (#985)', ({
    generated,
    alias,
  }) => {
    const rule = /\.position-chart__land\s*\{([\s\S]*?)\n\}/.exec(CHART_CSS)
    expect(rule, '.position-chart__land 규칙을 찾지 못했습니다').not.toBeNull()
    const body = (rule as RegExpExecArray)[1]

    const fill = /(?:^|;|\*\/)\s*fill:\s*var\(\s*(--[\w-]+)\s*\)/.exec(body)
    const stroke = /(?:^|;|\*\/)\s*stroke:\s*var\(\s*(--[\w-]+)\s*\)/.exec(body)
    expect(fill, '육지 채움 토큰을 읽지 못했습니다').not.toBeNull()
    expect(stroke, '해안선 토큰을 읽지 못했습니다').not.toBeNull()

    const line = evaluate(`var(${(stroke as RegExpExecArray)[1]})`, generated, alias)
    const land = evaluate(`var(${(fill as RegExpExecArray)[1]})`, generated, alias)
    // 그림은 카드 안에 놓인다 — 바다는 `--surface-inset`이다.
    const sea = generated['--surface-inset']

    expect(contrast(line, sea), '해안선 대 바다 — §14 「위치를 읽는 기준틀」').toBeGreaterThanOrEqual(3)
    expect(contrast(line, land), '해안선 대 육지 채움').toBeGreaterThanOrEqual(3)
  })

  const CONTROL_FACES = ['--surface-inset', '--surface-card']

  /** `#1202` 가드가 쓰는 CSS 목록. */
  const CSS_ROOT = fileURLToPath(new URL('..', import.meta.url))

  function cssFilesUnder(dir: string, out: string[] = []): string[] {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules') cssFilesUnder(join(dir, entry.name), out)
      } else if (entry.name.endsWith('.css')) {
        out.push(join(dir, entry.name))
      }
    }
    return out
  }

  it.each(THEMES)('$name — 폼 컨트롤 테두리가 양면에서 3:1 이상이다', ({ generated, alias }) => {
    const value = alias['--color-border-control']
    expect(value, '--color-border-control을 찾지 못했습니다').toBeDefined()
    const border = evaluate(value, generated, alias)
    for (const face of CONTROL_FACES) {
      expect(
        contrast(border, generated[face]),
        `${face} 위 컨트롤 테두리 — 1.4.11 비텍스트 3:1 (#829 ⑶)`,
      ).toBeGreaterThanOrEqual(3)
    }
  })

  /*
   * `#1169` — **면적 채널이 문자 계조를 다시 빌려 쓰는 것**을 막는다.
   *
   * 위 `3:1`은 값이 무엇이든 지켜지는지만 본다. 그런데 `#829` ⑶이 여기에 놓았던
   * 임시 별칭은 `3:1`을 **넘기면서도** 문제였다 — `--text-muted`를 빌려 쓴 탓에
   * 라이트 여유가 `0.08`뿐이었고 웜/쿨도 어긋났다. 대비 검사만으로는 안 잡힌다.
   *
   * 2026-09-18 확정 O가 Figma `border/control`(`#6f7c8f`)을 줘서 끊었다. 되돌아가는
   * 것을 막기 위해 **참조 사슬에 문자 토큰이 끼는지**를 본다 — 값이 아니라 출처를
   * 잠근다. `--color-surface-muted`는 대상이 아니다(그 토큰은 `#829` ⑴이 문자에서
   * 쪼개 낸 면적 별칭이고, 같은 값을 쓰는 것이 그 결정의 내용이다).
   */
  it.each(THEMES)('$name — 폼 컨트롤 경계가 문자 토큰을 참조하지 않는다 (#1169)', ({
    generated,
    alias,
  }) => {
    const seen = new Set<string>(['--color-border-control'])
    let name = '--color-border-control'

    for (;;) {
      const raw = alias[name] ?? generated[name]
      expect(raw, `${name}을 찾지 못했습니다`).toBeDefined()

      const ref = /^var\(\s*(--[\w-]+)\s*\)$/.exec(raw.trim())
      if (ref === null) break

      name = ref[1]
      expect(seen.has(name), `${name}에서 참조가 순환한다`).toBe(false)
      seen.add(name)

      expect(
        /^--(?:color-)?text-/.test(name),
        `폼 컨트롤 경계가 문자 토큰(${name})을 참조한다 — 면적·경계 채널은 자기 값을 갖는다 (#1169)`,
      ).toBe(false)
    }

    expect(name, '참조 사슬이 생성 토큰에 닿지 않았다').toBe('--border-control')
  })

  it.each(THEMES)('$name — 포커스 링이 네 면 위에서 3:1 이상이다', ({ generated, alias }) => {
    // `3px solid <색>`에서 색만 꺼낸다 — `#1167`로 `outline` 단축이 됐다.
    const ring = /3px\s+solid\s+(.+)$/.exec(alias['--focus-outline'])
    expect(ring, '포커스 링 색을 읽지 못했습니다').not.toBeNull()
    const color = evaluate((ring as RegExpExecArray)[1], generated, alias)
    for (const surface of TEXT_SURFACES) {
      // WCAG 1.4.11 Non-text Contrast — 비텍스트는 3:1이다.
      expect(contrast(color, generated[surface]), `${surface} 위 포커스 링`).toBeGreaterThanOrEqual(3)
    }
  })

  /*
   * `§0.2` **제약 6** — 문자 토큰의 대비는 **가장 어두운 표면** 기준으로 잰다 (`#747`).
   *
   * `§16` 항목 1이 여태 닫히지 않은 이유가 이것이다. 대안으로 적힌 `#647380`의
   * `4.86:1`은 **흰 카드 위** 값이었고, `--surface-inset` 위에서는 `4.34`로 미달이다.
   * 한 표면만 보고 통과 판정을 내리면 **가장 빠듯한 자리를 놓친다.**
   */
  const TEXT_TOKENS = [
    '--color-text',
    '--color-text-muted',
    '--color-link',
    '--color-danger-text',
    '--color-warning-text',
  ]

  /*
   * **제외** — 둘 다 문자가 아니다.
   *
   * - `--color-text-disabled` — WCAG 1.4.3이 비활성 요소를 대비 요구에서 **명시적으로 제외**
   * - `--color-surface-muted` — 면적. 1.4.11의 3:1이 기준이고 위 `면적` 검사가 본다
   */
  it.each(THEMES)('$name — 모든 문자 토큰이 모든 표면에서 4.5:1 이상이다', ({ generated, alias }) => {
    const failures: string[] = []
    for (const token of TEXT_TOKENS) {
      const value = alias[token] ?? generated[token]
      expect(value, `${token}을 찾지 못했습니다`).toBeDefined()
      const color = evaluate(value as string, generated, alias)
      for (const surface of TEXT_SURFACES) {
        const ratio = contrast(color, generated[surface])
        if (ratio < 4.5) failures.push(`${token} on ${surface} = ${ratio.toFixed(2)}`)
      }
    }
    expect(failures).toEqual([])
  })

  it.each(THEMES)('$name — 면적용 토큰이 비텍스트 3:1을 넘는다', ({ generated, alias }) => {
    // 글자가 아니므로 4.5가 아니라 1.4.11의 3:1이다.
    const color = evaluate(alias['--color-surface-muted'], generated, alias)
    for (const surface of TEXT_SURFACES) {
      expect(contrast(color, generated[surface]), `${surface} 위`).toBeGreaterThanOrEqual(3)
    }
  })

  it('다크에서 카드 그림자를 쓰지 않는다 — `§5` (#747 2-2)', () => {
    /*
     * 어두운 배경 위의 검은 그림자는 거의 보이지 않고, 보이는 만큼은 얼룩으로 보인다.
     * 종전 코드가 정본과 **정반대**를 하고 있었다.
     */
    for (const name of ['--shadow-lv1', '--shadow-lv2']) {
      expect(darkAlias[name], `다크 ${name}`).toBe('none')
      expect(lightAlias[name], `라이트 ${name}은 그림자가 있어야 한다`).not.toBe('none')
    }
  })

  it('오버레이 그림자는 다크에서도 none이 아니다', () => {
    // 떠 있는 면은 무엇 위에 뜰지 모른다 — 표면색만으로 분리되지 않는다.
    expect(darkAlias['--shadow-overlay'], '--shadow-overlay를 찾지 못했습니다').toBeDefined()
    expect(darkAlias['--shadow-overlay']).not.toBe('none')
  })

  /*
   * ## 이 가드는 한 번 틀렸다 (`#608`에서 고침)
   *
   * 종전 형태는 **선언 문자열만** 비교했다.
   *
   * ```ts
   * expect(darkAlias[name]).toBe(lightAlias[name])   // 둘 다 'var(--color-primary)'
   * ```
   *
   * 두 줄을 다크에서 덮지 않는 것은 맞았는데, **값이 가리키는 `--semantic-primary`가
   * 다크에서 덮인다**(`#1a365d` → `#4a7cc0`). 별칭 한 겹 아래에서 갈라지는 것을
   * 문자열 비교가 볼 수 없어, 「테마 불변」이라 적어 놓고 **실제로는 테마마다 다른**
   * 상태가 그대로 통과했다.
   *
   * 드러난 것은 `#608`이 그 색면 위에 흰 글자를 얹으면서다 — 다크에서 `4.25:1`이었다.
   *
   * ## 그래서 무엇을 잠그는가
   *
   * 「같은 선언인가」가 아니라 **「판 위 글자가 읽히는가」**를 잠근다. 확정값이 어떤
   * 형태로 오든(불변이든, 테마별이든, 시안 색이든) 이 단언은 그대로 유효하다.
   * 불변 여부만 잠갔다면 확정이 테마별로 오는 순간 가드를 지워야 한다.
   */
  it.each(THEMES)(
    '$name — 브랜드 판 위 글자가 4.5:1 이상이다 (#608 · 종전 가드가 놓친 자리)',
    ({ generated, alias }) => {
      const from = evaluate(alias['--brand-gradient-from'], generated, alias)
      const to = evaluate(alias['--brand-gradient-to'], generated, alias)
      // 판 위 글자는 `AuthShell.css`가 `--color-on-primary`로 고정한다.
      // 「브랜드색 면 위의 글자」용 토큰이라 양 테마에서 모두 밝다.
      const text = evaluate(alias['--color-on-primary'], generated, alias)

      // 보조 문자는 같은 색을 78%로 눌러 쓴다(`--auth-brand-muted`).
      // 알파는 판 위에 얹히므로 **면과 섞은 결과**가 실제 색이다.
      const muted = (surface: string) => mix(text, surface, 78)

      // 그러데이션이므로 **양 끝 모두** 넘어야 한다. 중간은 두 값 사이에 있다.
      for (const surface of [from, to]) {
        expect(contrast(text, surface)).toBeGreaterThanOrEqual(4.5)
        expect(contrast(muted(surface), surface)).toBeGreaterThanOrEqual(4.5)
      }
    },
  )

  it.each(THEMES)(
    '$name — 브랜드 판의 바깥 경계가 인지된다 (#941 · 확정 3-4)',
    ({ generated, alias }) => {
      /*
       * 확정 3-4가 미리 지적한 자리다 — *「다크 모드에서 판과 카드가 붙어 보일 수
       * 있습니다. 판이 딥네이비이고 카드가 거의 검정이면 경계가 사라집니다」*.
       * 실측하니 다크에서 판↔페이지가 `2.34`였다.
       *
       * ## 잠그는 것은 「선이 있는가」가 아니다
       *
       * 라이트는 판과 페이지 대비가 `11.21`이라 선이 필요 없다. 선의 존재를 잠그면
       * **필요 없는 테마에까지 선을 강제**하게 된다. 잠그는 것은 **경계가 인지되는가**다 —
       * 판과 페이지가 스스로 갈리거나, 아니면 그 사이의 선이 페이지와 갈리거나.
       *
       * 확정값(`#933`)이 어떤 밝기로 오든 이 단언은 그대로 유효하다.
       */
      const panel = evaluate(alias['--brand-gradient-from'], generated, alias)
      const page = evaluate('var(--surface-page)', generated, alias)
      const edge = evaluate(alias['--brand-panel-edge'], generated, alias)

      // 비텍스트 경계 기준 (`§0.2` · WCAG 1.4.11).
      const perceivable =
        contrast(panel, page) >= 3 || contrast(edge, page) >= 3

      expect(
        perceivable,
        `판 ${panel} ↔ 페이지 ${page} = ${contrast(panel, page).toFixed(2)}, ` +
          `선 ${edge} ↔ 페이지 = ${contrast(edge, page).toFixed(2)}`,
      ).toBe(true)
    },
  )

  it('다크 브랜드 비율은 확정값이다 — 60% · 45% (2026-09-12 확정 M · #933)', () => {
    /*
     * 2026-09-12 확정 M — **현행 `60%`·`45%`를 유지한다.** 확정 G(`80%`·`68%`)는 판 위
     * 글자를 흰색으로 놓고 계산해 폐기됐다(실제 글자는 `--color-on-primary`).
     *
     * 비율을 값으로 잠근다. 위 대비 가드가 「읽히는가」를 보지만, 그것만으로는
     * **다른 비율로 바꿔도 통과**할 수 있다 — 확정된 것은 결과가 아니라 이 값이다.
     */
    const dark = declarationsIn("\n:root[data-theme='dark'] {")
    expect(dark['--brand-gradient-from']).toContain('60%')
    expect(dark['--brand-gradient-to']).toContain('45%')
    // 도출 규칙이 바뀌었다는 사실이 토큰 주석에 남아 있어야 한다 — 주석은 낡는다.
    expect(aliasCss).toContain('확정 M')
  })

  it('`--cii-none-bg`가 중립 표면과 같다 (#747 2-3)', () => {
    /*
     * 「none 등급」은 등급이 없다는 뜻이지 고유한 색을 가진 등급이 아니다.
     * 종전 라이트 값 `#f2f2ef`는 **종전 웜 페이지색**이라 쿨톤 위에서 떴다.
     */
    for (const theme of THEMES) {
      expect(theme.generated['--cii-none-bg'], `${theme.name}`).toBe(
        theme.generated['--surface-inset'],
      )
    }
  })

  it('두 다크 블록이 같은 값을 선언한다 — 한쪽만 고치면 OS 다크와 명시 다크가 갈린다', () => {
    const media = declarationsIn("\n  :root:not([data-theme='light']) {")
    for (const name of [
      '--color-primary-solid',
      '--color-primary-solid-hover',
      '--color-on-primary',
      '--color-link',
    ]) {
      expect(media[name], `@media 블록에 ${name}이 없습니다`).toBe(
        declarationsIn("\n:root[data-theme='dark'] {")[name],
      )
    }
  })

  /*
   * 되돌림 방지 — 「`--color-primary`를 그냥 쓰면 되지 않나」로 돌아가는 것을 막는다.
   * 그 조합이 실제로 미달이라는 사실을 여기 숫자로 남긴다.
   */
  it('다크 --semantic-primary 위에는 쓸 만한 문자색이 없다', () => {
    const g = hexTable(dark)
    for (const name of ['--surface-card', '--text-primary']) {
      expect(contrast(g[name], g['--semantic-primary'])).toBeLessThan(4.5)
    }
    expect(contrast('#ffffff', g['--semantic-primary'])).toBeLessThan(4.5)
  })
})

describe('오버레이 면은 그림자와 테두리를 함께 쓴다 — §5 (2026-09-11 확정 A ⑶)', () => {
  /*
   * 다크에서는 검은 그림자가 거의 보이지 않아 **실제 분리는 테두리와 표면색이 담당한다.**
   * 그런데 테두리는 그림자 토큰이 아니라 **컴포넌트가 가진다** — 지금은 `AccountMenu`와
   * 본문 바로가기가 각자 갖고 있다. 다음 모달·토스트가 그림자 토큰만 가져다 쓰면
   * **다크에서 분리가 사라지고 라이트에서는 멀쩡해 보인다.** 라이트에서 눈으로 보고
   * 통과시키게 되는 결함이라 소스로 막는다.
   */
  function cssFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : cssFiles(full)
      return entry.name.endsWith('.css') ? [full] : []
    })
  }

  const ROOT = fileURLToPath(new URL('..', import.meta.url))
  const rules = cssFiles(ROOT)
    .filter((file) => !file.endsWith('tokens.css') && !file.endsWith('tokens.generated.css'))
    .flatMap((file) =>
      [...stripComments(readFileSync(file, 'utf-8')).matchAll(/([^{}]*)\{([^}]*)\}/g)].map(
        ([, selector, body]) => ({ where: `${file.slice(ROOT.length)} :: ${selector.trim()}`, body }),
      ),
    )
  const overlays = rules.filter(({ body }) => /box-shadow\s*:[^;]*var\(--shadow-overlay\)/.test(body))

  it('오버레이 그림자를 쓰는 규칙을 실제로 찾았다', () => {
    // 수집이 깨지면 아래 검사가 빈 목록으로 통과한다. 지금 쓰는 곳은 둘이다.
    expect(overlays.length).toBeGreaterThanOrEqual(2)
  })

  it('오버레이 그림자를 쓰는 규칙은 테두리를 함께 선언한다', () => {
    const missing = overlays
      .filter(({ body }) => !/(^|[;\s])border(-width)?\s*:\s*(?!none|0\b)[^;]+/.test(body))
      .map(({ where }) => where)
    expect(missing).toEqual([])
  })
})

describe('등급 색을 비-등급 맥락에서 쓰지 않는다 — §0.2 제약 2 (#748)', () => {
  /**
   * `§0.2` 제약 2: 등급 색(`--cii-*`)은 항상 A~E 문자 또는 등급 축 라벨과 함께 나타난다.
   *
   * `.warn` 선대 경고 배너는 "시정조치계획 대상 위험 선박 N척" 문구를 쓰며
   * 등급 문자가 없다. 이전에 `--cii-e-*` 토큰을 써서 제약을 위반했으므로
   * 시맨틱 Danger 토큰으로 교체하고 이 가드로 재진입을 막는다.
   */
  const fleetCss = readFileSync(
    join(fileURLToPath(new URL('.', import.meta.url)), '../features/fleet/FleetDashboard.css'),
    'utf-8',
  )

  /*
   * **반대 방향도 막는다** (`#748` 되돌림).
   *
   * 위 가드가 「등급 색을 비-등급 맥락에 쓰지 않는다」를 잠그자, `#748`이 그 방향으로
   * 가다 **등급 문자가 있는 자리까지** 시맨틱으로 바꿔 놓았다 — `.vessel__mark-grade--e`
   * (바로 그 클래스 안에 `<b>E</b>`가 있다) · `.dist__group-label--e b` · `.action--critical`
   * (문구가 「E등급 1년차 —」다). 형제 `--a`~`--d`는 등급 토큰인데 `--e`만 빠져
   * `§15` 접두어 규약도 함께 어겼다.
   *
   * **이름이 아니라 계열의 일관성을 본다.** 「이 클래스는 등급 채널인가」는 이름으로
   * 알 수 없지만, **다섯 등급이 같은 채널을 쓰는가**는 알 수 있다. 하나만 다르면
   * 그것이 사고다 — 다섯을 한꺼번에 바꾸는 것은 의도된 개정이라 이 검사가 막지 않는다.
   */
  const GRADE_SERIES = ['.dist__group-label--', '.vessel__mark-grade--']

  it.each(GRADE_SERIES)('%s 계열 다섯 등급이 같은 채널을 쓴다', (prefix) => {
    const used = new Map<string, string>()
    for (const grade of ['a', 'b', 'c', 'd', 'e']) {
      const rule = new RegExp(`\\${prefix}${grade}\\b[^{]*\\{([^}]*)\\}`).exec(fleetCss)
      expect(rule, `${prefix}${grade} 규칙을 찾지 못했다`).not.toBeNull()
      const token = /var\((--[\w-]+)\)/.exec((rule as RegExpExecArray)[1])
      expect(token, `${prefix}${grade}에 토큰 참조가 없다`).not.toBeNull()
      used.set(grade, (token as RegExpExecArray)[1])
    }

    // `--cii-{등급}-text`처럼 등급만 다른 한 계열이어야 한다.
    const shapes = new Set([...used.values()].map((t) => t.replace(/-[a-e]-/, '-{grade}-')))
    expect(
      [...shapes],
      `등급별로 다른 채널을 쓴다: ${[...used].map(([g, t]) => `${g}=${t}`).join(' · ')}`,
    ).toHaveLength(1)
  })

  it('.warn 배너에 --cii-* 등급 토큰이 없다', () => {
    // .warn { … } 블록만 추출한다 (중괄호 중첩 없음).
    const warnBlock = fleetCss.match(/\.warn\s*\{([^}]+)\}/)
    expect(warnBlock, '.warn 규칙을 찾지 못했다 — 선택자가 바뀐 경우 이 테스트도 갱신하세요').not.toBeNull()
    expect(
      warnBlock![1],
      '.warn 배너에 --cii-* 토큰이 있습니다. §0.2 제약 2 위반 — 시맨틱 Danger 토큰(--color-danger 등)으로 바꾸세요',
    ).not.toMatch(/--cii-/)
  })

  /*
   * 위험 테두리는 **위험 축**이다 — 2026-09-18 확정 ⓐ (`#1168`).
   *
   * `.vessel--risk`가 붙는 조건은 등급이 아니라 `isAtRisk()`이고, 그 사유는 둘이다
   * (`E_THIS_YEAR` · `D_THIRD_YEAR`). 종전에는 `--cii-e-border`를 써서 **마크에
   * `D`가 찍힌 행에 등급 E 색 테두리**가 붙었다 — `§0.2` 제약 2가 「등급 색은 A~E
   * 문자와 **함께**」라고 한 그 어긋남이다.
   *
   * **사유 둘이 같은 테두리를 공유한다는 것 자체가 등급 축이 아니라는 증거다.**
   * 위 `.warn` 검사와 같은 규율이며, 다른 점은 이쪽이 「문자가 없어서」가 아니라
   * **「문자가 있는데 다른 등급이어서」** 걸린다는 것이다.
   *
   * 종전 값은 대비도 모자랐다 — `--cii-e-border`는 카드 위에서 라이트 `2.67` ·
   * 다크 `2.17`로 `1.4.11` 비텍스트 `3:1` 미달이었다. 보조 채널로 세운 선이 정작
   * 보이지 않았다.
   */
  /*
   * `#1052` ⓥ — **선택자 하나가 아니라 「위험을 뜻하는 선택자 전부」를 본다.**
   *
   * `#1168`이 `.vessel--risk`만 잠갔더니 같은 결함이 **개략도에 그대로 남아 있었다**
   * (`.position-chart__dot--risk`가 `--cii-e-fill`). 이름으로 한 곳을 찍는 가드는
   * 그 한 곳만 지킨다 — `#1202`가 토큰 이름으로 범위를 잡았다가 더 나쁜 자리를
   * 놓친 것과 같은 꼴이다.
   *
   * 그래서 저장소 전체에서 `--risk`로 끝나는 선택자를 걷어 한꺼번에 본다. 새 화면이
   * 같은 이름 규칙으로 위험 표시를 넣으면 **등재 없이도** 이 검사에 들어온다.
   */
  /** `#1052` ⓥ 가드가 훑을 CSS 목록. 이 describe 안에는 walker가 없어 새로 둔다. */
  const RISK_ROOT = fileURLToPath(new URL('..', import.meta.url))

  function riskCssFiles(dir: string, out: string[] = []): string[] {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules') riskCssFiles(join(dir, entry.name), out)
      } else if (entry.name.endsWith('.css')) {
        out.push(join(dir, entry.name))
      }
    }
    return out
  }

  it('위험을 뜻하는 선택자에 --cii-* 등급 토큰이 없다 (#1168 · #1052 ⓥ)', () => {
    const offenders: string[] = []
    for (const file of riskCssFiles(RISK_ROOT)) {
      const body = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
      for (const [, selector, rule] of body.matchAll(/([^{}]*--risk[^{}]*)\{([^}]*)\}/g)) {
        if (/--cii-/.test(rule)) {
          offenders.push(`${file.slice(RISK_ROOT.length)} :: ${selector.trim()}`)
        }
      }
    }
    expect(
      offenders,
      '위험 표시에 --cii-* 토큰이 있습니다. 이 선은 등급이 아니라 위험(E_THIS_YEAR · D_THIRD_YEAR)을 뜻합니다 — 시맨틱을 쓰세요',
    ).toEqual([])
  })

  it('그 검사가 실제로 무언가를 보고 있다', () => {
    // 선택자 이름 규칙이 바뀌면 위 검사가 **공집합 통과**가 된다.
    const found = riskCssFiles(RISK_ROOT).flatMap((file) => [
      ...readFileSync(file, 'utf-8').matchAll(/[^{}]*--risk[^{}]*\{/g),
    ])
    expect(found.length).toBeGreaterThanOrEqual(2)
  })
})
