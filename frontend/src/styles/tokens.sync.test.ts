/// <reference types="node" />
import { readFileSync } from 'node:fs'
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
