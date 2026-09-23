import { describe, expect, it } from 'vitest'
import {
  EMPTY_QUERY,
  SHIP_TYPE_OPTIONS,
  activeFilters,
  isFiltered,
  toListOptions,
} from './queryRules'

/**
 * 조회 조건 규칙 (#1783). DOM 없이 고정한다.
 */

describe('조회 옵션으로 옮긴다', () => {
  it('조건이 없으면 파라미터도 없다 — 빈 값을 싣지 않는다', () => {
    expect(toListOptions(EMPTY_QUERY)).toEqual({})
  })

  it('검색어의 앞뒤 공백을 지운다', () => {
    expect(toListOptions({ search: '  알파  ', shipType: '' })).toEqual({ search: '알파' })
  })

  it('공백뿐인 검색어는 조건이 아니다', () => {
    expect(toListOptions({ search: '   ', shipType: '' })).toEqual({})
  })

  it('선종과 커서를 함께 싣는다', () => {
    expect(toListOptions({ search: '', shipType: 'BULK_CARRIER' }, 'c1')).toEqual({
      cursor: 'c1',
      shipType: 'BULK_CARRIER',
    })
  })
})

describe('걸린 조건', () => {
  it('아무것도 안 걸면 비어 있다', () => {
    expect(activeFilters(EMPTY_QUERY, false)).toEqual([])
    expect(isFiltered(EMPTY_QUERY, false)).toBe(false)
  })

  it('검색 · 선종 · 제원 미비를 각각 하나로 센다', () => {
    const filters = activeFilters({ search: '알파', shipType: 'BULK_CARRIER' }, true)
    expect(filters.map((f) => f.key)).toEqual(['search', 'shipType', 'specGap'])
    // 선종은 코드가 아니라 이름으로 적는다 — 코드는 계약값이고 화면은 이름을 쓴다.
    expect(filters[1].label).toContain('벌크선')
  })

  it('제원 미비만 걸어도 걸린 것이다 — 그것만 켜면 목록이 짧아지는 이유가 그 칩뿐이다', () => {
    expect(isFiltered(EMPTY_QUERY, true)).toBe(true)
    expect(activeFilters(EMPTY_QUERY, true).map((f) => f.key)).toEqual(['specGap'])
  })

  it('모르는 선종 코드는 코드를 그대로 적는다 — 빈칸으로 두지 않는다', () => {
    expect(activeFilters({ search: '', shipType: 'NO_SUCH' }, false)[0].label).toContain(
      'NO_SUCH',
    )
  })
})

describe('선종 선택지', () => {
  it('`shipTypes.ts`의 13종을 그대로 쓴다 — 화면이 다시 나열하지 않는다', () => {
    expect(SHIP_TYPE_OPTIONS).toHaveLength(13)
    expect(SHIP_TYPE_OPTIONS.map((o) => o.code)).toContain('BULK_CARRIER')
  })
})
