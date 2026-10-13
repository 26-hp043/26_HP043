/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { NOT_UNDERWAY_DISTANCE_RANGE, NOT_UNDERWAY_FUEL_RANGE } from '../not-underway/periodRules'
import { storableRange } from '../vessel-registration/formRules'
import { DISTANCE_RANGE, FUEL_RANGE } from '../voyage-cii/formRules'
import { STORED_YEAR_MAX, STORED_YEAR_MIN } from './voyageRules'

/**
 * 항차·항로 비교·정박 구간의 입력 범위 — 화면 ↔ 서버 `validation/bounds.py` 대조 (#2457).
 *
 * 화면이 범위를 옮겨 적으므로 **서버 값이 바뀌면 CI가 실패하게** 한다. 원본은 `bounds.py`의
 * 선언 한 줄씩이며, 거리·연료는 `storable(precision, scale)`의 두 인자에서 화면과 같은 식
 * (`storableRange`)으로 범위를 만들어 비교한다. `specBounds.sync.test.ts`와 같은 취지다.
 */

const boundsPy = readFileSync(
  new URL('../../../../src/cii_platform/validation/bounds.py', import.meta.url),
  'utf-8',
)

function declaration(name: string): string {
  const match = new RegExp(`^${name}\\s*=\\s*(.+)$`, 'm').exec(boundsPy)
  expect(match, `${name} 선언을 찾지 못했습니다`).not.toBeNull()
  return match![1].trim()
}

function storableOf(name: string): { min: number; max: number } {
  const match = /^storable\((\d+),\s*(\d+)\)$/.exec(declaration(name))
  expect(match, `${name}이 storable(p, s) 꼴이 아닙니다`).not.toBeNull()
  return storableRange(Number(match![1]), Number(match![2]))
}

describe('화면 범위 ↔ 서버 validation/bounds.py (#2457)', () => {
  it('거리 DISTANCE — 항차 · 항로 비교 · CII 예측이 쓰는 화면 범위와 같다', () => {
    expect(DISTANCE_RANGE).toEqual(storableOf('DISTANCE'))
  })

  it('항차 연료 VOYAGE_FUEL', () => {
    expect(FUEL_RANGE).toEqual(storableOf('VOYAGE_FUEL'))
  })

  it('정박 연료 NOT_UNDERWAY_FUEL', () => {
    expect(NOT_UNDERWAY_FUEL_RANGE).toEqual(storableOf('NOT_UNDERWAY_FUEL'))
  })

  it('정박 거리 NOT_UNDERWAY_DISTANCE — 하한 0(허용), 상한은 NUMERIC(12,2)의 최댓값', () => {
    const match = /^\{"ge":\s*Decimal\((\d+)\),\s*"le":\s*largest\((\d+),\s*(\d+)\)\}$/.exec(
      declaration('NOT_UNDERWAY_DISTANCE'),
    )
    expect(match, 'NOT_UNDERWAY_DISTANCE 꼴이 바뀌었습니다').not.toBeNull()
    expect(NOT_UNDERWAY_DISTANCE_RANGE).toEqual({
      min: Number(match![1]),
      max: storableRange(Number(match![2]), Number(match![3])).max,
    })
  })

  it('저장 규제연도 2019~2050 — 조회 상한(2100)과 다르다', () => {
    expect(STORED_YEAR_MIN).toBe(Number(declaration('MIN_REGULATION_YEAR')))
    expect(STORED_YEAR_MAX).toBe(Number(declaration('MAX_STORED_REGULATION_YEAR')))
    expect(STORED_YEAR_MAX).toBeLessThan(Number(declaration('MAX_REGULATION_YEAR')))
  })
})
