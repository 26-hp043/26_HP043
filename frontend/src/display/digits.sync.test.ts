/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DISPLAY_DIGITS } from './format'

/**
 * `DISPLAY_DIGITS` ↔ `DESIGN_SYSTEM §4.2` 자릿수 표 드리프트 가드 (#633).
 *
 * ## 같은 사고가 두 번 났다
 *
 * `#592`는 **표에 행이 없어** 화면이 `231.64 일`을 냈고, `#633`은 **표에 행이 없어**
 * 같은 DWT가 `6,405.77`과 `6405.77`로 갈렸다. 둘 다 「규정 공백 → 구현이 제각각」이며,
 * 규정을 신설해 닫았지만 **다음 공백을 막는 것은 아무것도 없었다.**
 *
 * 이 파일이 두 방향을 함께 본다.
 *
 * * 문서에 행이 생겼는데 구현이 따라오지 않은 경우 — 매핑에 없는 항목에서 실패한다
 * * 구현이 바뀌었는데 문서가 그대로인 경우 — 자릿수 대조에서 실패한다
 *
 * `warningMessage.sync.test.ts`가 `API_SPEC §1.6`에 대해 하는 일과 같은 방식이다.
 *
 * ## 문구가 아니라 자릿수만 본다
 *
 * 「근거」 열은 자유 서술이라 대조 대상이 아니다. 표의 **항목과 자릿수**만 읽는다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const DESIGN_SYSTEM = join(HERE, '..', '..', '..', 'DESIGN_SYSTEM.md')

/**
 * 문서의 항목 이름 → `DISPLAY_DIGITS` 키.
 *
 * **이 표가 비면 가드가 조용해지므로** 아래에서 커버리지를 함께 단언한다.
 * `§4.1`의 CII 3자리는 이 표에 없다(다른 절 소관)이라 여기서 대조하지 않는다.
 */
const KEY_BY_LABEL: Readonly<Record<string, keyof typeof DISPLAY_DIGITS>> = {
  '연료 소모량': 'fuelTon',
  '항해거리': 'distanceNm',
  'CO₂ 배출량': 'co2Ton',
  '시간 (hour)': 'durationHours',
  '일수 (day)': 'days',
  '평균 속력': 'speedKn',
  '용량 (DWT·GT)': 'capacity',
  '확률': 'percent',
}

/** `§4.2` 「소수 자릿수」 표에서 (항목, 자릿수)를 뽑는다. */
function digitsInSpec(): Map<string, number> {
  const text = readFileSync(DESIGN_SYSTEM, 'utf-8')
  const start = text.indexOf('**소수 자릿수 🔒**')
  const end = text.indexOf('**단위 표기 🔒**', start)
  expect(start, '`§4.2` 소수 자릿수 표를 찾지 못했다').toBeGreaterThan(-1)
  expect(end, '`§4.2` 단위 표기 표를 찾지 못했다').toBeGreaterThan(start)

  const rows = new Map<string, number>()
  for (const line of text.slice(start, end).split('\n')) {
    // | 항목 | 자릿수 | 예 | 근거 |  — 자릿수 칸은 `0` 또는 `백분율 1` 형태다
    const m = /^\|\s*([^|]+?)\s*\|\s*(?:백분율\s*)?(\d+)\s*\|/.exec(line)
    if (!m) continue
    if (m[1] === '항목') continue
    rows.set(m[1], Number(m[2]))
  }
  return rows
}

describe('DISPLAY_DIGITS가 DESIGN_SYSTEM §4.2와 어긋나지 않는다', () => {
  it('표 파싱 자체가 실패하지 않았다', () => {
    // 정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다.
    expect(digitsInSpec().size).toBeGreaterThanOrEqual(7)
  })

  it('문서의 모든 항목이 구현에 매핑돼 있다', () => {
    // 표에 행이 생겼는데 구현이 따라오지 않은 경우를 잡는다 — `#592`·`#633`이
    // 그 반대(구현이 먼저 갈린 경우)였고, 이제는 양쪽이 걸린다.
    const unmapped = [...digitsInSpec().keys()].filter((label) => !(label in KEY_BY_LABEL))
    expect(unmapped, `§4.2에 새 항목이 생겼다: ${unmapped.join(', ')}`).toEqual([])
  })

  it('자릿수가 문서와 같다', () => {
    for (const [label, digits] of digitsInSpec()) {
      const key = KEY_BY_LABEL[label]
      expect(DISPLAY_DIGITS[key], `${label}(${key})`).toBe(digits)
    }
  })

  it('용량은 천단위 구분자 「적용」 쪽에 있다 (#633)', () => {
    const text = readFileSync(DESIGN_SYSTEM, 'utf-8')
    const start = text.indexOf('**천단위 구분자 🔒**')
    const section = text.slice(start, start + 800)
    const applied = section.split('| **미적용**')[0]
    expect(applied).toContain('용량')
  })
})
