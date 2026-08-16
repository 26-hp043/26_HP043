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
