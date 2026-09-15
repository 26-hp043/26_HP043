/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { daysToDText } from './fleetRules'
import type { DaysReason } from './types'

/**
 * `daysToDText()` ↔ `API_SPEC §2.8` `days_to_d_reason` 표 드리프트 가드 (`#1091`).
 *
 * ## 무엇이 문제였나
 *
 * 화면은 사유 **4종**만 알았고(`types.ts` `DaysReason`), 서버는 `#431`이 추가한
 * `NO_RECENT_DATA`·`NOT_WORSENING`까지 **6종**을 냈다. 모르는 사유는 `default`로
 * 떨어져 **「실적 없음」**이 붙었다 — **실적이 있는 선박에 없다고 말한 것**이다.
 *
 * `NOT_WORSENING`은 「최근 운항 강도가 경계보다 효율적」이라는 뜻이라 **A~C 선박
 * 대부분이 이 사유**다. 가장 흔한 상태가 가장 나쁜 문구로 보였다.
 *
 * ## 왜 서버 쪽 가드가 못 잡았나
 *
 * `tests/test_fleet_summary.py`는 **`API_SPEC` 표 ↔ 파이썬 상수**를 대조한다. 화면이
 * 그 코드를 아는지는 보지 않는다 — 사슬의 마지막 칸이 비어 있었다.
 *
 * ## 여기서 보는 것
 *
 * ⑴ 정본 표의 사유가 **전부** 사람 말로 나간다(폴백 `—`로 떨어지지 않는다)
 * ⑵ 사유마다 **다른** 문구를 쓴다 — 뭉치면 구분이 사라진다
 * ⑶ 모르는 사유는 **뜻을 지어내지 않는다**(`—`) — 종전 폴백이 「실적 없음」이었다
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const API_SPEC = join(HERE, '..', '..', '..', '..', 'API_SPEC.md')

/** `§2.8`의 `days_to_d_reason` 표에서 첫 열의 값만 뽑는다. */
function reasonsInSpec(): string[] {
  const text = readFileSync(API_SPEC, 'utf-8')
  const start = text.indexOf('#### `days_to_d` — 「D등급 진입까지 n일」')
  const end = text.indexOf('#### `unavailable_reason`', start)
  expect(start, '`API_SPEC §2.8`의 `days_to_d` 절을 찾지 못했다').toBeGreaterThan(-1)
  expect(end, '`unavailable_reason` 절을 찾지 못했다').toBeGreaterThan(start)

  const reasons: string[] = []
  for (const line of text.slice(start, end).split('\n')) {
    const m = /^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|/.exec(line)
    if (m) reasons.push(m[1])
  }
  return reasons
}

describe('대시보드 「D등급까지」가 서버 사유를 전부 안다 (#1091)', () => {
  it('절 파싱 자체가 실패하지 않았다', () => {
    // 이 단언이 없으면 정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다.
    expect(reasonsInSpec()).toHaveLength(6)
  })

  it('정본의 사유가 하나도 폴백으로 떨어지지 않는다', () => {
    const unknown = reasonsInSpec().filter(
      (reason) => daysToDText(null, reason as DaysReason) === '—',
    )
    expect(
      unknown,
      `화면이 모르는 사유다 — fleetRules.ts와 types.ts에 넣을 것: ${unknown.join(', ')}`,
    ).toEqual([])
  })

  it('사유마다 다른 문구를 쓴다 — 같은 말로 뭉치지 않는다', () => {
    const texts = reasonsInSpec().map((reason) => daysToDText(null, reason as DaysReason))
    expect(new Set(texts).size).toBe(texts.length)
  })

  it('실적이 있는 두 사유를 「실적 없음」이라 말하지 않는다 — 이 이슈가 고친 것이다', () => {
    /*
     * 종전에는 둘 다 `default`로 떨어져 「실적 없음」이었다. `NO_RECENT_DATA`는
     * **실적은 있는데 최근 30일이 빈** 것이고, `NOT_WORSENING`은 **실적이 있고 심지어
     * 좋은** 것이다 — 둘 다 「없다」가 아니다.
     */
    expect(daysToDText(null, 'NO_RECENT_DATA')).not.toBe('실적 없음')
    expect(daysToDText(null, 'NOT_WORSENING')).not.toBe('실적 없음')
    expect(daysToDText(null, 'NO_DATA')).toBe('실적 없음')
  })

  it('숫자를 만들지 않는다 — 「곧 진입한다」로 읽히면 안 된다', () => {
    // `NOT_WORSENING`은 「0일」이 아니라 「해당 없음」이다(`API_SPEC §2.8` 각주).
    expect(daysToDText(null, 'NOT_WORSENING')).not.toMatch(/\d/)
    expect(daysToDText(null, 'NO_RECENT_DATA')).not.toMatch(/\d/)
  })

  it('모르는 사유는 뜻을 지어내지 않는다', () => {
    // 정본에 없는 값이 오면 중립 표시다. 종전 폴백(「실적 없음」)은 틀린 쪽을
    // 맞는 것처럼 보이게 했다.
    expect(daysToDText(null, 'WHAT_IS_THIS' as DaysReason)).toBe('—')
    expect(daysToDText(null, null)).toBe('—')
  })
})
