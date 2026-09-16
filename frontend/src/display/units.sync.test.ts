/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DISPLAY_UNITS, DISPLAY_UNIT_DAILY_FUEL } from './format'

/**
 * `DISPLAY_UNITS` ↔ `DESIGN_SYSTEM §4.2` 「단위 표기 🔒」 표 드리프트 가드.
 *
 * ## 자릿수에는 가드가 있었고 단위에는 없었다
 *
 * `digits.sync.test.ts`가 같은 절의 **자릿수** 표를 잠그면서 *「다음 공백을 막는 것은
 * 아무것도 없었다」*고 적었는데, **바로 옆 단위 표가 그 공백이었다.**
 *
 * 실제로 같은 사고가 났다 — `reference_daily_foc_ton`이 표에 없어 화면마다 `t`와
 * `t/일`로 갈렸고, `#592`가 입력만 통일하면서 **정본에 등재하지 못한 채** 남겼다.
 * `ScenarioComparison.tsx`가 그 사실을 주석으로 들고 있었지만 주석은 실패하지 않는다.
 *
 * 두 방향을 함께 본다.
 *
 * * 문서에 행이 생겼는데 구현이 따라오지 않은 경우 — 매핑 커버리지에서 실패한다
 * * 구현이 바뀌었는데 문서가 그대로인 경우 — 값 대조에서 실패한다
 *
 * ## 「근거」 열은 보지 않는다
 *
 * 자유 서술이라 대조 대상이 아니다. 표의 **항목과 단위 문자열**만 읽는다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const DESIGN_SYSTEM = join(HERE, '..', '..', '..', 'DESIGN_SYSTEM.md')

/**
 * 문서의 항목 이름 → 구현의 단위 문자열.
 *
 * 「일일 연료소모량」은 `DISPLAY_UNITS`의 키가 아니라 **파생 상수**다 — `t`와 `일`을
 * 조합하므로 따로 박지 않는다(`§4.2` 「리터럴 금지 🔒」). 여기서 함께 대조해야
 * 조합이 끊겼을 때 잡힌다.
 *
 * **이 표가 비면 가드가 조용해지므로** 아래에서 커버리지를 함께 단언한다.
 */
const UNIT_BY_LABEL: Readonly<Record<string, string>> = {
  '연료 소모량': DISPLAY_UNITS.fuel,
  '일일 연료소모량': DISPLAY_UNIT_DAILY_FUEL,
  'CO₂ 배출량': DISPLAY_UNITS.co2,
  '항해거리': DISPLAY_UNITS.distance,
  '시간': DISPLAY_UNITS.duration,
  '일수': DISPLAY_UNITS.day,
  '평균 속력': DISPLAY_UNITS.speed,
}

/** `§4.2` 「단위 표기」 표에서 (항목, 단위)를 뽑는다. */
function unitsInSpec(): Map<string, string> {
  const text = readFileSync(DESIGN_SYSTEM, 'utf-8')
  const start = text.indexOf('**단위 표기 🔒**')
  const end = text.indexOf('**반올림 🔒**', start)
  expect(start, '`§4.2` 단위 표기 표를 찾지 못했다').toBeGreaterThan(-1)
  expect(end, '`§4.2` 반올림 절을 찾지 못했다 — 표의 끝을 정할 수 없다').toBeGreaterThan(start)

  const rows = new Map<string, string>()
  for (const line of text.slice(start, end).split('\n')) {
    // | 항목 | `단위` | 근거 |  — 단위 칸은 백틱으로 감싼다
    const m = /^\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|/.exec(line)
    if (!m) continue
    if (m[1] === '항목') continue
    rows.set(m[1], m[2])
  }
  return rows
}

describe('DISPLAY_UNITS가 DESIGN_SYSTEM §4.2와 어긋나지 않는다', () => {
  it('표 파싱 자체가 실패하지 않았다', () => {
    // 정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다.
    expect(unitsInSpec().size).toBeGreaterThanOrEqual(7)
  })

  it('문서의 모든 항목이 구현에 매핑돼 있다', () => {
    const unmapped = [...unitsInSpec().keys()].filter((label) => !(label in UNIT_BY_LABEL))
    expect(unmapped, `§4.2 단위 표에 새 항목이 생겼다: ${unmapped.join(', ')}`).toEqual([])
  })

  it('단위 문자열이 문서와 같다', () => {
    for (const [label, unit] of unitsInSpec()) {
      expect(UNIT_BY_LABEL[label], `${label}`).toBe(unit)
    }
  })

  /*
   * 일일 연료소모량은 **질량이 아니라 질량유량**이다(`DB_SCHEMA`: `ton/day`).
   * 총량과 같은 `t`로 적으면 차원을 잃어 「총량인지 일당인지」가 라벨에만 남는다.
   */
  it('일일 연료소모량이 연료 소모량과 다른 단위다', () => {
    expect(DISPLAY_UNIT_DAILY_FUEL).not.toBe(DISPLAY_UNITS.fuel)
  })

  /*
   * **조합이 끊기면 잡는다.** `t`나 `일`이 바뀌었는데 파생이 따라오지 않거나,
   * 누군가 파생을 리터럴로 되돌린 경우다 — `§4.2` 「리터럴로 박지 않는다 🔒」.
   */
  it('일일 연료소모량이 두 단위에서 파생된다', () => {
    expect(DISPLAY_UNIT_DAILY_FUEL).toBe(`${DISPLAY_UNITS.fuel}/${DISPLAY_UNITS.day}`)
  })
})
