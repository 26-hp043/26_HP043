import { describe, expect, it, vi } from 'vitest'
import type { FleetLoadOptions, FleetSnapshot, FleetVessel } from '../fleet/types'
import {
  MAX_GRADE_PAGES,
  gradeCellOf,
  gradeRank,
  loadGradeTable,
  type GradeTable,
} from './gradeLookup'

/**
 * 올해 누적 등급 조회표 (#2018).
 *
 * 선박 관리 목록은 등급을 `/vessels`가 아니라 `/fleet/summary`(대시보드와 같은 경로)에서
 * 받아 **선박 번호로 찾아 붙인다.** 여기서 지키는 것은 셋이다.
 *
 * 1. 끝 페이지까지 받고, 뒤 페이지에 첫 페이지의 `as_of`를 넣는다 — 시점이 섞이지 않는다
 * 2. 커서를 쓰는 동안 정렬을 바꾸지 않는다 — 다른 `sort`의 커서는 422다(`API_SPEC §2.8`)
 * 3. 받지 못함 · 받는 중 · 요약에 없음 · 계산 못 함 · 값 있음을 **서로 다른 상태**로 둔다
 */

function fleetVessel(overrides: Partial<FleetVessel> & { id: string }): FleetVessel {
  return {
    name: overrides.id,
    shipType: 'BULK_CARRIER',
    imoNumber: '9000001',
    underwayState: null,
    detailStatus: null,
    lat: null,
    lon: null,
    positionUpdatedAt: null,
    route: null,
    courseDeg: null,
    isCiiApplicableHint: true,
    grossTonnage: 30000,
    dataAvailable: true,
    unavailableReason: null,
    ytdAttainedCii: '5.123456',
    ytdRequiredCii: '5.000000',
    ytdRating: 'C',
    riskLevel: null,
    riskReasons: [],
    daysToD: null,
    daysToDReason: null,
    ...overrides,
  }
}

function snapshot(
  vessels: FleetVessel[],
  page: { asOf?: string; nextCursor?: string | null; hasMore?: boolean } = {},
): FleetSnapshot {
  return {
    asOf: page.asOf ?? '2026-09-28T00:00:00Z',
    regulationYear: 2026,
    counts: {
      total: vessels.length,
      underWay: 0,
      notUnderWay: 0,
      unknownState: 0,
      ratingDistribution: { A: 0, B: 0, C: 0, D: 0, E: 0 },
      atRisk: 0,
      noData: 0,
      missingGrossTonnage: 0,
      soonestDEntry: null,
    },
    vessels,
    nextCursor: page.nextCursor ?? null,
    hasMore: page.hasMore ?? false,
    actions: [],
  }
}

describe('조회표 조립 — 끝 페이지까지, 시점을 고정해서', () => {
  it('뒤 페이지를 첫 페이지의 as_of로 받고, 정렬을 바꾸지 않는다', async () => {
    const calls: FleetLoadOptions[] = []
    const load = vi.fn(async (options: FleetLoadOptions = {}) => {
      calls.push(options)
      if (options.cursor === undefined) {
        return snapshot([fleetVessel({ id: 'a' })], {
          asOf: '2026-09-28T01:02:03Z',
          nextCursor: 'c1',
          hasMore: true,
        })
      }
      if (options.cursor === 'c1') {
        return snapshot([fleetVessel({ id: 'b', ytdRating: 'E' })], {
          asOf: '2026-09-28T09:99:99Z',
          nextCursor: 'c2',
          hasMore: true,
        })
      }
      return snapshot([fleetVessel({ id: 'c', ytdRating: 'A' })])
    })

    const table = await loadGradeTable({ load })

    expect(calls).toHaveLength(3)
    // 첫 요청에는 시점을 넣지 않는다 — 서버가 정한 시점을 받아 뒤에 고정한다.
    expect(calls[0].asOf).toBeUndefined()
    expect(calls.slice(1).map((c) => c.asOf)).toEqual(['2026-09-28T01:02:03Z', '2026-09-28T01:02:03Z'])
    // 커서를 쓰는 동안 정렬이 한 가지다.
    expect(new Set(calls.map((c) => c.sort)).size).toBe(1)
    expect(calls.slice(1).map((c) => c.cursor)).toEqual(['c1', 'c2'])
    // 표의 시점은 첫 페이지의 것이다.
    expect(table.asOf).toBe('2026-09-28T01:02:03Z')
    expect([...table.byId.keys()]).toEqual(['a', 'b', 'c'])
  })

  it('has_more가 참이어도 커서가 없으면 멈춘다 — 같은 페이지를 되풀이하지 않는다', async () => {
    const load = vi.fn(async () =>
      snapshot([fleetVessel({ id: 'a' })], { hasMore: true, nextCursor: null }),
    )
    await loadGradeTable({ load })
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('같은 커서가 다시 오면 멈추고 던진다 — 끝없이 요청하지 않는다', async () => {
    const load = vi.fn(async () =>
      snapshot([fleetVessel({ id: 'a' })], { hasMore: true, nextCursor: 'loop' }),
    )
    await expect(loadGradeTable({ load })).rejects.toThrow()
    // 첫 페이지 + `loop` 한 번. 두 번째 `loop`에서 멈춘다.
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('페이지 수가 상한을 넘으면 던진다 — 커서가 매번 달라도 끝이 있다', async () => {
    let n = 0
    const load = vi.fn(async () => {
      n += 1
      return snapshot([fleetVessel({ id: `v${n}` })], { hasMore: true, nextCursor: `c${n}` })
    })
    await expect(loadGradeTable({ load })).rejects.toThrow()
    expect(load).toHaveBeenCalledTimes(MAX_GRADE_PAGES)
  })

  it('뒤 페이지가 실패하면 표를 내지 않는다 — 반쪽 표는 뒤 배를 「요약에 없음」으로 만든다', async () => {
    const load = vi.fn(async (options: FleetLoadOptions = {}) => {
      if (options.cursor === undefined) {
        return snapshot([fleetVessel({ id: 'a' })], { nextCursor: 'c1', hasMore: true })
      }
      throw new Error('boom')
    })
    await expect(loadGradeTable({ load })).rejects.toThrow()
  })
})

describe('칸 상태 — 다섯 가지를 섞지 않는다', () => {
  const ready = (entries: FleetVessel[]): GradeTable => ({
    status: 'ready',
    asOf: '2026-09-28T00:00:00Z',
    byId: new Map(entries.map((v) => [v.id, v])),
  })

  it('받는 중 · 받지 못함은 선박과 무관하게 그 상태다', () => {
    expect(gradeCellOf({ status: 'loading' }, 'a').kind).toBe('loading')
    expect(gradeCellOf({ status: 'failed' }, 'a').kind).toBe('failed')
  })

  it('요약에 없는 선박은 「받지 못함」도 「계산 못 함」도 아니다', () => {
    const cell = gradeCellOf(ready([fleetVessel({ id: 'a' })]), 'z')
    expect(cell.kind).toBe('absent')
  })

  it('서버가 값을 내지 못한 선박은 사유를 그대로 싣는다', () => {
    const table = ready([
      fleetVessel({
        id: 'a',
        dataAvailable: false,
        unavailableReason: 'MISSING_SPEC',
        ytdRating: null,
        ytdAttainedCii: null,
        ytdRequiredCii: null,
      }),
    ])
    expect(gradeCellOf(table, 'a')).toEqual({ kind: 'unavailable', reason: 'MISSING_SPEC' })
  })

  it('값이 있으면 등급과 누적·기준 CII를 문자열 그대로 싣는다 (API_SPEC §1.7)', () => {
    const cell = gradeCellOf(ready([fleetVessel({ id: 'a', ytdRating: 'D' })]), 'a')
    expect(cell).toEqual({
      kind: 'rated',
      rating: 'D',
      attainedCii: '5.123456',
      requiredCii: '5.000000',
    })
  })

  it('등급이 없는데 data_available이 참인 응답도 값 있음으로 치지 않는다', () => {
    const cell = gradeCellOf(ready([fleetVessel({ id: 'a', ytdRating: null })]), 'a')
    expect(cell.kind).toBe('unavailable')
  })
})

describe('등급순의 값 — 나쁜 등급이 앞, 등급이 없으면 null', () => {
  it('E가 A보다 앞이다', () => {
    const rank = (rating: 'A' | 'E') =>
      gradeRank({ kind: 'rated', rating, attainedCii: null, requiredCii: null })
    expect(rank('E')!).toBeLessThan(rank('A')!)
  })

  it('등급이 없는 상태는 모두 null이다 — 나쁜 등급으로 섞지 않는다', () => {
    expect(gradeRank({ kind: 'loading' })).toBeNull()
    expect(gradeRank({ kind: 'failed' })).toBeNull()
    expect(gradeRank({ kind: 'absent' })).toBeNull()
    expect(gradeRank({ kind: 'unavailable', reason: 'NO_DATA' })).toBeNull()
  })
})
