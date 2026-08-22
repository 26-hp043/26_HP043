/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { WARNING_MESSAGE, warningMessage } from './resultRules'

/**
 * `WARNING_MESSAGE` ↔ `API_SPEC §1.6` 표 드리프트 가드 (#630).
 *
 * ## 무엇이 문제였나
 *
 * 이 맵의 머리주석이 *「`API_SPEC §1.6` 표를 그대로 전사했다」*고 적고 있는데,
 * **§1.6 표 자체가 코드가 내는 17종 중 7종을 담고 있지 않았다.** 기능③(연간
 * 시뮬레이션)이 나중에 들어오면서 표를 갱신하지 않은 것이다.
 *
 * 그 결과 연간 시뮬레이션 화면이 `warningMessage()`의 `?? code` 갈래를 타
 * **원문 코드를 그대로 노출**했다.
 *
 * ```
 * SENSITIVITY_ONE_AT_A_TIME
 * NO_REMAINING_VOYAGES
 * ```
 *
 * ## 어떻게 잡나
 *
 * `API_SPEC.md`의 `§1.6` 표를 직접 읽어 코드 집합을 뽑고, 이 맵의 키와 대조한다.
 * `shipTypes.sync.test.ts`가 `capacity.py`를 읽어 선종을 대조하는 것과 같은 방식이다.
 *
 * **문구까지 대조하지는 않는다.** 표의 「사용자 메시지」 열에는 마크다운·괄호 주석이
 * 섞여 있어 정확히 떼어내려면 파서가 필요하고, 그 파서가 깨지면 대조가 조용히
 * 무의미해진다. 여기서는 **어느 쪽에만 있는 코드가 없다**는 것만 본다 — 그것이
 * `#630`을 만든 종류의 드리프트다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const API_SPEC = join(HERE, '..', '..', '..', '..', 'API_SPEC.md')

/** `§1.6` 표에서 첫 열의 코드만 뽑는다. */
function codesInSpec(): Set<string> {
  const text = readFileSync(API_SPEC, 'utf-8')
  const start = text.indexOf('### 1.6')
  const end = text.indexOf('### 1.7', start)
  expect(start, '`API_SPEC §1.6` 절을 찾지 못했다').toBeGreaterThan(-1)
  expect(end, '`API_SPEC §1.7` 절을 찾지 못했다').toBeGreaterThan(start)

  const section = text.slice(start, end)
  const codes = new Set<string>()
  for (const line of section.split('\n')) {
    // 표 행만 본다: | `CODE` | 조건 | 메시지 |
    const m = /^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|/.exec(line)
    if (m) codes.add(m[1])
  }
  return codes
}

describe('WARNING_MESSAGE가 API_SPEC §1.6과 어긋나지 않는다', () => {
  it('절 파싱 자체가 실패하지 않았다', () => {
    // 이 단언이 없으면 정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다.
    expect(codesInSpec().size).toBeGreaterThanOrEqual(10)
  })

  it('§1.6에 있는 코드가 전부 이 맵에 있다', () => {
    const missing = [...codesInSpec()].filter((c) => !(c in WARNING_MESSAGE)).sort()
    expect(missing, `화면에 문구가 없어 원문 코드가 그대로 노출된다: ${missing.join(', ')}`).toEqual(
      [],
    )
  })

  it('이 맵에만 있고 §1.6에 없는 코드가 없다', () => {
    const spec = codesInSpec()
    const extra = Object.keys(WARNING_MESSAGE).filter((c) => !spec.has(c)).sort()
    expect(extra, `정본에 없는 코드에 문구를 붙였다: ${extra.join(', ')}`).toEqual([])
  })

  it('표에 없는 코드가 오면 코드 자체를 보인다 — 조용히 감추지 않는다', () => {
    expect(warningMessage('BRAND_NEW_CODE')).toBe('BRAND_NEW_CODE')
  })
})
