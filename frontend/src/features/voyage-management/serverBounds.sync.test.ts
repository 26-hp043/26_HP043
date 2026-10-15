/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { NOT_UNDERWAY_DISTANCE_RANGE, NOT_UNDERWAY_FUEL_RANGE } from '../not-underway/periodRules'
import { storableRange } from '../vessel-registration/formRules'
import { DISTANCE_RANGE, FUEL_RANGE } from '../voyage-cii/formRules'
import {
  FUTURE_ACTUAL_TOLERANCE_MINUTES,
  STORED_YEAR_MAX,
  STORED_YEAR_MIN,
  allowedRegulationYears,
  regulationYearHint,
} from './voyageRules'

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

  it('실적 시각의 시계 여유 — 서버 services/voyage.py FUTURE_ACTUAL_TOLERANCE와 같다 (#2420)', () => {
    const voyagePy = readFileSync(
      new URL('../../../../src/cii_platform/services/voyage.py', import.meta.url),
      'utf-8',
    )
    const match = /^FUTURE_ACTUAL_TOLERANCE\s*=\s*timedelta\(minutes=(\d+)\)$/m.exec(voyagePy)
    expect(match, 'FUTURE_ACTUAL_TOLERANCE 선언 꼴이 바뀌었습니다').not.toBeNull()
    expect(FUTURE_ACTUAL_TOLERANCE_MINUTES).toBe(Number(match![1]))
  })

  /*
   * #2420 결정 1 — 「넣을 수 있는 해」는 서버 `spanned_utc_years`의 판정을 화면이 한 번 더 한다. 같은 사례
   * 파일을 서버 검사(`tests/test_voyage_regulation_year_attribution_db.py`)도 읽는다 — 한쪽만 바뀌면
   * 어느 한쪽이 실패한다. 안내 문구는 표시 문구라(`AGENTS §4.6`) 해가 들어 있는지·덧붙임이 있는지만 본다.
   */
  const cases = (
    JSON.parse(
      readFileSync(
        new URL('../../../../tests/fixtures/regulation_year/attribution_cases.json', import.meta.url),
        'utf-8',
      ),
    ) as {
      cases: {
        name: string
        departure: string | null
        arrival: string | null
        years: number[] | null
        kst_differs: boolean
      }[]
    }
  ).cases

  it('사례 파일이 비어 있지 않다', () => {
    expect(cases.length).toBeGreaterThanOrEqual(5)
  })

  it.each(cases)('넣을 수 있는 해 — $name', (c) => {
    expect(allowedRegulationYears(c.departure, c.arrival)).toEqual(c.years)
    const hint = regulationYearHint(c.departure, c.arrival)
    if (c.years === null) {
      expect(hint).toBeNull()
      return
    }
    for (const year of c.years) expect(hint).toContain(String(year))
    // 한국 시각과 UTC의 해가 갈리는 시각이 끼었을 때만 UTC를 따른다는 이유를 덧붙인다
    const plain = regulationYearHint('2026-05-10T00:00:00Z', null)!
    expect(hint!.includes('UTC')).toBe(c.kst_differs)
    expect(plain.includes('UTC')).toBe(false)
  })
})
