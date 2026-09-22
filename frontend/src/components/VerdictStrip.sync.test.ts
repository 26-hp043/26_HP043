/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 결론 띠의 크기 규칙을 CSS에서 잠근다 — `DESIGN_SYSTEM §8.6` 🔒 (#1700 · #1711).
 *
 * jsdom은 스타일시트를 계산하지 않아 화면 검사로는 「보조가 주보다 작다」를 볼 수
 * 없다. 규칙 본문을 읽어 대조한다. #1700이 연간 등급 관리에 두었던 가드를 부품으로
 * 옮겼다 — 부품을 쓰는 모든 화면이 한 번에 잠긴다.
 */

const CSS = readFileSync(
  join(fileURLToPath(new URL('.', import.meta.url)), 'VerdictStrip.css'),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '')

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`(^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(CSS)
  if (!match) throw new Error(`규칙이 없다: ${selector}`)
  return match[2]
}

describe('결론 띠 — `DESIGN_SYSTEM §8.6` 🔒', () => {
  it('주 결론은 `display` 크기다', () => {
    expect(rule('.verdict-strip__value')).toMatch(/font-size:\s*var\(--font-size-display\)/)
  })

  it('⚠️ 보조는 `display`가 아니다 — 주 결론 크기로 커지면 위반이다', () => {
    const body = rule('.verdict-strip__sub-value')
    expect(body).not.toMatch(/--font-size-display/)
    expect(body).toMatch(/font-size:\s*var\(--font-size-h2\)/)
  })

  it('위험도 pill의 면은 중립이다 — 경고색은 글자에만 (`§2.3` · `§2.5 (b)`)', () => {
    expect(rule('.verdict-strip__risk')).not.toMatch(/warning|danger/)
  })
})
