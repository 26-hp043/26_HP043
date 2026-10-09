/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * 중립 단계 체계 — `DESIGN_SYSTEM §2.2` (`#2383`).
 *
 * ## 무엇이 바뀌었나
 *
 * 종전에는 중립색이 **값 목록**이었다. 새 글자 · 면 조합이 생길 때마다 대비를 다시 재야 했고,
 * 그래서 대비 결함이 한 건씩 따로 잡혔다(`#699` · `#747` · `#829` · `#1169` · `#2147`).
 * 지금은 회색 **12단**이 단계마다 용도를 갖고, 의미 토큰(`surface.*` · `text.*` · `border.*`)은
 * 값이 아니라 **단계의 이름**을 가리킨다(Radix · Vercel Geist와 같은 방식).
 *
 * ## 이 파일이 보는 것 — 조합이 아니라 규칙
 *
 * 1. 두 테마 모두 12단과 `panel`이 있다
 * 2. 단계가 한 방향으로 진다(라이트는 숫자가 클수록 어둡고, 다크는 밝다) — 「몇 단계 떨어진
 *    두 색」이 대비를 갖는다는 보장은 이 순서 위에서만 성립한다
 * 3. **글자 단(11 · 12)은 모든 바탕 면 위 4.5:1, 비텍스트 단(9 · 10)은 3:1** — 바탕 면은
 *    `surface.*`가 실제로 가리키는 단계다. 새 화면이 「11단 글자를 바탕 면에」 놓으면 대비를
 *    다시 잴 필요가 없다
 * 4. 중립 의미 토큰은 전부 별칭이다 — hex를 직접 들면 단계 밖의 색이 생긴다
 * 5. 의미 토큰이 **자기 용도의 단계**를 가리킨다 — 글자 토큰이 경계 단을 빌리지 않는다
 *    (`#1169`가 겪은 「경계가 글자 계조를 빌려 쓴」 결함의 반대 방향도 막는다)
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const TOKENS = join(HERE, '..', 'design', 'tokens')

type Node = { [key: string]: Node | unknown }
type Token = { $type: string; $value: { hex: string } | string; $description?: string }

function load(theme: 'Light' | 'Dark'): Node {
  return JSON.parse(readFileSync(join(TOKENS, `${theme}.tokens.json`), 'utf-8')) as Node
}

function token(tree: Node, path: string): Token {
  let node: unknown = tree
  for (const key of path.split('.')) node = (node as Node)[key]
  if (!node) throw new Error(`토큰이 없다: ${path}`)
  return node as Token
}

function hexOf(tree: Node, path: string, depth = 0): string {
  if (depth > 5) throw new Error(`별칭이 돈다: ${path}`)
  const value = token(tree, path).$value
  if (typeof value === 'string') {
    const ref = /^\{(.+)\}$/.exec(value)
    if (!ref) throw new Error(`${path}의 값을 읽을 수 없다: ${value}`)
    return hexOf(tree, ref[1], depth + 1)
  }
  return value.hex.toLowerCase()
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

const STEPS = Array.from({ length: 12 }, (_, i) => `gray.${i + 1}`)

/** 의미 토큰 → 허용되는 단계. 용도가 정한다(`§2.2` 단계 표). */
const ROLE_STEPS: Record<string, readonly string[]> = {
  'surface.page': ['gray.1'],
  'surface.inset': ['gray.2'],
  'surface.card': ['gray.panel'],
  'surface.popover': ['gray.panel', 'gray.4'],
  'border.default': ['gray.6'],
  'border.strong': ['gray.7'],
  'border.control': ['gray.9'],
  'text.muted': ['gray.10'],
  'text.secondary': ['gray.11'],
  'text.primary': ['gray.12'],
}

describe.each(['Light', 'Dark'] as const)('중립 단계 체계 — %s (DESIGN_SYSTEM §2.2 · #2383)', (theme) => {
  const tree = load(theme)
  const surfaces = [...new Set(Object.keys(ROLE_STEPS).filter((k) => k.startsWith('surface.')).map((k) => hexOf(tree, k)))]

  it('12단과 panel이 있고 단계마다 용도가 적혀 있다', () => {
    for (const step of [...STEPS, 'gray.panel']) {
      const t = token(tree, step)
      expect(t.$type, step).toBe('color')
      expect(t.$description, `${step}에 용도가 없다`).toBeTruthy()
    }
  })

  it('단계가 한 방향으로 진다 — 대비 보장은 이 순서 위에서만 성립한다', () => {
    const lum = STEPS.map((s) => luminance(hexOf(tree, s)))
    for (let i = 0; i < lum.length - 1; i += 1) {
      if (theme === 'Light') expect(lum[i], `${STEPS[i]} → ${STEPS[i + 1]}`).toBeGreaterThanOrEqual(lum[i + 1])
      else expect(lum[i], `${STEPS[i]} → ${STEPS[i + 1]}`).toBeLessThanOrEqual(lum[i + 1])
    }
  })

  it.each([
    ['gray.12', 4.5],
    ['gray.11', 4.5],
    ['gray.10', 3],
    ['gray.9', 3],
  ] as const)('%s는 모든 바탕 면 위에서 %s:1을 넘는다', (step, min) => {
    const fg = hexOf(tree, step)
    for (const bg of surfaces) {
      expect(contrast(fg, bg), `${step} ${fg} 대 ${bg}`).toBeGreaterThanOrEqual(min)
    }
  })

  it.each(Object.entries(ROLE_STEPS))('%s는 별칭이고 자기 용도의 단계를 가리킨다', (path, allowed) => {
    const value = token(tree, path).$value
    expect(typeof value, `${path}가 hex를 직접 든다 — 단계 밖의 색이 생긴다`).toBe('string')
    const ref = /^\{(.+)\}$/.exec(value as string)?.[1]
    expect(allowed, `${path} → ${ref}`).toContain(ref)
  })
})

/**
 * 정본 단계 표 ↔ 원본 JSON — 표가 옛 값을 들고 남지 않게 (`#2149`가 `§2.2` 표에서 겪은 일).
 */
describe('DESIGN_SYSTEM §2.2.1 단계 표 = 원본 JSON (#2383)', () => {
  const doc = readFileSync(join(HERE, '..', '..', '..', 'DESIGN_SYSTEM.md'), 'utf-8')
  const section = doc.slice(doc.indexOf('#### 2.2.1'), doc.indexOf('#### 2.2.2'))
  const rows = [...section.matchAll(/^\| (\d+|panel) \|[^|]*\|[^|]*\| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \|/gm)]
  const light = load('Light')
  const dark = load('Dark')

  it('표를 실제로 읽었다 — 12단 + panel', () => {
    expect(rows.map((r) => r[1])).toEqual([...STEPS.map((s) => s.split('.')[1]), 'panel'])
  })

  it.each(rows.map((r) => [r[1], r[2], r[3]] as const))('%s단 — 표의 값이 원본과 같다', (step, l, d) => {
    expect(hexOf(light, `gray.${step}`)).toBe(l)
    expect(hexOf(dark, `gray.${step}`)).toBe(d)
  })
})
