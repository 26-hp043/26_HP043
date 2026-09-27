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
 */

const CSS = readFileSync(
  join(fileURLToPath(new URL('.', import.meta.url)), 'DataQuality.css'),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '')

/** 그 선택자를 포함하는 규칙들의 `border-left-color` 값. 둘 이상이면 모두 같아야 한다. */
function stripeColor(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const values = [...CSS.matchAll(/([^{}]+)\{([^}]*)\}/g)]
    .filter(([, sel]) => new RegExp(`${escaped}(?![\\w-])`).test(sel))
    .map(([, , body]) => /border-left-color:\s*([^;]+);/.exec(body)?.[1].trim())
    .filter((v): v is string => Boolean(v))
  expect(values.length, `${selector}의 띠 색 규칙이 없다`).toBeGreaterThan(0)
  expect(new Set(values).size, `${selector}의 띠 색이 규칙마다 다르다`).toBe(1)
  return values[0]
}

describe('「공적 기록과 다름」 띠 색 — `§2.3.1` 〔확정〕 2026-09-27 (#1940 ①)', () => {
  it('Info다 — 요약 칸과 목록의 심각도 표시가 같은 색', () => {
    expect(stripeColor('.dq__tile--public_record')).toBe('var(--color-info)')
    expect(stripeColor('.dq__severity--public_record')).toBe('var(--color-info)')
  })

  it('「실적 확정 전」의 중립과 갈린다 — 임시안(#1197)의 같은 색 짝이 남지 않는다', () => {
    expect(stripeColor('.dq__severity--public_record')).not.toBe(
      stripeColor('.dq__severity--unconfirmed'),
    )
  })

  it('경고색(Danger · Warning)을 쓰지 않는다 — 값을 바꾸지 않는 안내다', () => {
    expect(stripeColor('.dq__severity--public_record')).not.toMatch(/danger|warning/)
  })
})
