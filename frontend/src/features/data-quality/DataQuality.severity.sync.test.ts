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

/** 단축 속성 `border-left: 4px solid X`에서 색 X, 또는 `border-left-color: X`. */
function leftColorOf(body: string): string | undefined {
  let value: string | undefined
  for (const [, prop, raw] of body.matchAll(/(border-left(?:-color)?)\s*:\s*([^;]+);/g)) {
    const v = raw.trim()
    value = prop === 'border-left-color' ? v : (/(var\([^)]+\)|#[0-9a-f]+)\s*$/i.exec(v)?.[1] ?? value)
  }
  return value
}

/** 클래스 목록이 붙은 요소의 **최종** 왼쪽 띠 색 — 단일 클래스 선택자만 따진다(우선순위 동일). */
function effectiveLeftColor(classes: string[]): string {
  const wanted = new Set(classes.map((c) => `.${c}`))
  let value: string | undefined
  for (const { selectors, body } of RULES) {
    if (!selectors.some((s) => wanted.has(s))) continue
    value = leftColorOf(body) ?? value
  }
  expect(value, `${classes.join(' ')}의 띠 색을 정하는 규칙이 없다`).toBeDefined()
  return value!
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
