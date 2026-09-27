/**
 * `content-width` 토큰의 **설명문이 값과 맞는가** (`#1528`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 디자인 토큰 동기화 검사)
 *
 * ## 무엇이 어긋나 있었나
 *
 * 값은 `1608`인데 설명문은 `"1920 - GNB 240"`(= 1680)이었다. `#1513`이 넣은 설명문을
 * `#1514`의 Figma 재내보내기가 되돌린 것으로 보인다(정황).
 *
 * **설명문을 읽는 검사가 없어 조용했다.** 값만 보는 검사는 통과하고, 산식을 믿고 읽은
 * 사람은 1680을 기대한다 — `§7.1` 🔒의 산술은 `24+240+24+1608+24=1920`이다.
 *
 * ⚠️ **이 파일은 Figma 내보내기다.** 설명문의 정본은 Figma 변수이고, 여기 고친 값은
 * 다음 내보내기가 되돌릴 수 있다. 그때 이 검사가 빨개져 **드리프트가 드러난다** —
 * 그것이 이 검사의 목적이다.
 */

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const tokens = JSON.parse(
  readFileSync(join(__dirname, '../design/tokens/BlueLog.tokens.json'), 'utf-8'),
) as Record<string, unknown>

/** 중첩 객체에서 그 이름의 토큰을 찾는다. */
function findToken(node: unknown, name: string): { $value?: unknown; $description?: string } | null {
  if (typeof node !== 'object' || node === null) return null
  const entries = Object.entries(node as Record<string, unknown>)
  for (const [key, value] of entries) {
    if (key === name && typeof value === 'object' && value !== null && '$value' in value) {
      return value as { $value?: unknown; $description?: string }
    }
    const found = findToken(value, name)
    if (found) return found
  }
  return null
}

describe('content-width 토큰 (#1528)', () => {
  const token = findToken(tokens, 'content-width')

  it('토큰이 있다', () => {
    expect(token).not.toBeNull()
  })

  it('설명문의 산식이 값과 같다', () => {
    /*
     * 설명문에서 숫자를 뽑아 `첫 값 - 나머지`로 계산한다. 종전 `"1920 - GNB 240"`은
     * 1680이 되어 값 1608과 어긋났다 — 그 어긋남을 여기서 잡는다.
     */
    const description = token?.$description ?? ''
    const numbers = [...description.matchAll(/\d+/g)].map((match) => Number(match[0]))
    expect(numbers.length, `설명문에 숫자가 없다: ${description}`).toBeGreaterThan(1)
    const computed = numbers.slice(1).reduce((total, value) => total - value, numbers[0])
    expect(computed).toBe(token?.$value)
  })
})
