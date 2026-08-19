import { describe, expect, it } from 'vitest'
import {
  EMPTY_CONTEXT,
  STORAGE_KEY,
  displayName,
  isVesselQueryPath,
  isVesselScopedPath,
  loadStored,
  navigationFor,
  readContext,
  readFromPath,
  readFromQuery,
  saveStored,
  selectVessel,
  selectVoyage,
  vesselPath,
  voyagePath,
  withContextQuery,
} from './globalContext'

/**
 * #512 — 상단바 전역 컨텍스트 규칙.
 *
 * 여기서 잠그는 것은 **「상단바가 별도 상태를 소유하지 않는다」**는 성질이다.
 * 계층 라우트(`#348`)가 이미 선박 범위를 표현하므로, 상단바가 자기 상태를 갖는
 * 순간 두 곳이 갈리고 갈렸을 때 어느 쪽이 맞는지 알 수 없게 된다.
 */

const VESSEL = '00000000-0000-4000-8000-000000000001'
const VOYAGE = '00000000-0000-4000-8000-0000000000f1'

/** `sessionStorage` 대역. 테스트가 실제 저장소를 건드리지 않게 한다. */
function fakeStorage(initial: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(initial))
  return {
    get length() {
      return map.size
    },
    clear: () => map.clear(),
    getItem: (k: string) => map.get(k) ?? null,
    key: (i: number) => [...map.keys()][i] ?? null,
    removeItem: (k: string) => void map.delete(k),
    setItem: (k: string, v: string) => void map.set(k, v),
  } as Storage
}

describe('readFromPath — 경로가 정본이다', () => {
  it('선박 상세 경로에서 선박을 읽는다', () => {
    expect(readFromPath(`/vessels/${VESSEL}`)).toEqual({
      vesselId: VESSEL,
      voyageId: null,
    })
  })

  it('실시간 CII 경로에서 선박과 항차를 함께 읽는다', () => {
    expect(readFromPath(`/vessels/${VESSEL}/voyages/${VOYAGE}`)).toEqual({
      vesselId: VESSEL,
      voyageId: VOYAGE,
    })
  })

  it('계층 밖 화면에서는 아무것도 읽지 않는다', () => {
    expect(readFromPath('/dashboard')).toEqual(EMPTY_CONTEXT)
    expect(readFromPath('/reports')).toEqual(EMPTY_CONTEXT)
  })

  it('선박 관리 목록(/vessels)은 특정 선박을 가리키지 않는다', () => {
    // 세그먼트가 하나 짧아 `/vessels/:vesselId`에 매칭되지 않는다.
    expect(readFromPath('/vessels')).toEqual(EMPTY_CONTEXT)
  })
})

describe('isVesselScopedPath', () => {
  it('계층 화면 두 곳만 참이다', () => {
    expect(isVesselScopedPath(`/vessels/${VESSEL}`)).toBe(true)
    expect(isVesselScopedPath(`/vessels/${VESSEL}/voyages/${VOYAGE}`)).toBe(true)
    expect(isVesselScopedPath('/dashboard')).toBe(false)
    expect(isVesselScopedPath('/route-comparison')).toBe(false)
  })
})

describe('경로 생성', () => {
  it('선박·항차 경로를 screens.ts 상수에서 만든다', () => {
    expect(vesselPath(VESSEL)).toBe(`/vessels/${VESSEL}`)
    expect(voyagePath(VESSEL, VOYAGE)).toBe(`/vessels/${VESSEL}/voyages/${VOYAGE}`)
  })

  it('만든 경로를 다시 읽으면 같은 값이 나온다', () => {
    expect(readFromPath(voyagePath(VESSEL, VOYAGE))).toEqual({
      vesselId: VESSEL,
      voyageId: VOYAGE,
    })
  })
})

describe('selectVessel — 선박을 바꾸면 항차를 버린다', () => {
  it('다른 배를 고르면 항차 선택이 사라진다', () => {
    // 남겨 두면 「다른 배의 항차」 조합이 만들어지고 그 경로는 404가 난다.
    const before = { vesselId: VESSEL, voyageId: VOYAGE }
    expect(selectVessel(before, 'other')).toEqual({ vesselId: 'other', voyageId: null })
  })

  it('같은 배를 다시 고르면 항차를 유지한다', () => {
    const before = { vesselId: VESSEL, voyageId: VOYAGE }
    expect(selectVessel(before, VESSEL)).toBe(before)
  })

  it('선택을 비우면 둘 다 사라진다', () => {
    expect(selectVessel({ vesselId: VESSEL, voyageId: VOYAGE }, null)).toEqual(
      EMPTY_CONTEXT,
    )
  })
})

describe('selectVoyage — 선박 없이는 항차를 고를 수 없다', () => {
  it('선박이 없으면 아무 일도 하지 않는다', () => {
    const before = EMPTY_CONTEXT
    expect(selectVoyage(before, VOYAGE)).toBe(before)
  })

  it('선박이 있으면 항차만 바꾼다', () => {
    expect(selectVoyage({ vesselId: VESSEL, voyageId: null }, VOYAGE)).toEqual({
      vesselId: VESSEL,
      voyageId: VOYAGE,
    })
  })
})

describe('navigationFor — 계층 밖에서는 화면을 튀게 하지 않는다', () => {
  it('대시보드에서 배를 골라도 이동하지 않는다', () => {
    // 보던 화면이 튀면 사용자가 하려던 일이 끊긴다. 고른 것은 기억만 해 둔다.
    expect(navigationFor('/dashboard', { vesselId: VESSEL, voyageId: null })).toBeNull()
  })

  it('선박 상세에서 다른 배를 고르면 그 배의 상세로 간다', () => {
    expect(
      navigationFor(`/vessels/${VESSEL}`, { vesselId: 'other', voyageId: null }),
    ).toBe('/vessels/other')
  })

  it('항차까지 고르면 실시간 CII로 간다', () => {
    expect(
      navigationFor(`/vessels/${VESSEL}`, { vesselId: VESSEL, voyageId: VOYAGE }),
    ).toBe(`/vessels/${VESSEL}/voyages/${VOYAGE}`)
  })

  it('선박을 비우면 이동하지 않는다 — 갈 곳이 없다', () => {
    expect(navigationFor(`/vessels/${VESSEL}`, EMPTY_CONTEXT)).toBeNull()
  })
})

describe('저장 — 화면 전환 후에도 유지된다', () => {
  it('저장한 것을 그대로 읽는다', () => {
    const storage = fakeStorage()
    saveStored({ vesselId: VESSEL, voyageId: VOYAGE }, storage)
    expect(loadStored(storage)).toEqual({ vesselId: VESSEL, voyageId: VOYAGE })
  })

  it('저장된 것이 없으면 빈 컨텍스트다', () => {
    expect(loadStored(fakeStorage())).toEqual(EMPTY_CONTEXT)
  })

  it('형태가 다른 값은 없는 것으로 본다 — 지어내지 않는다', () => {
    expect(loadStored(fakeStorage({ [STORAGE_KEY]: 'not json' }))).toEqual(EMPTY_CONTEXT)
    expect(loadStored(fakeStorage({ [STORAGE_KEY]: '{"vesselId":42}' }))).toEqual(
      EMPTY_CONTEXT,
    )
  })

  it('저장소가 없어도 던지지 않는다 — 편의 기능이다', () => {
    expect(loadStored(undefined)).toEqual(EMPTY_CONTEXT)
    expect(() => saveStored({ vesselId: VESSEL, voyageId: null }, undefined)).not.toThrow()
  })
})

describe('displayName — 목록에 없는 id를 감추지 않는다', () => {
  const options = [{ id: VESSEL, displayName: '샘플 벌크선' }]

  it('아는 선박은 이름으로 보인다', () => {
    expect(displayName(options, VESSEL)).toBe('샘플 벌크선')
  })

  it('모르는 id는 id 그대로 보인다', () => {
    // 「알 수 없는 선박」으로 뭉뚱그리면 목록이 아직 안 온 것과 삭제된 배가
    // 구분되지 않는다.
    expect(displayName(options, 'gone')).toBe('gone')
  })

  it('선택하지 않았으면 null이다', () => {
    expect(displayName(options, null)).toBeNull()
  })
})

/**
 * #484 B안 — 컨텍스트를 쿼리에 담는다.
 *
 * 여기서 잠그는 것은 **「평면 경로 화면도 주소만으로 선택을 복원할 수 있다」**는
 * 성질이다. `sessionStorage` 기억만으로는 새로고침은 살아남아도 **링크 공유**가
 * 성립하지 않고, 다른 탭에서 열면 다른 배를 보게 된다.
 */
describe('#484 쿼리 컨텍스트', () => {
  const FORECAST = '/voyage-cii'
  const COMPARISON = '/route-comparison'
  const ANNUAL = '/annual-grade'
  const DASHBOARD = '/dashboard'

  describe('isVesselQueryPath', () => {
    it.each([FORECAST, COMPARISON, ANNUAL])('%s는 쿼리로 컨텍스트를 담는다', (path) => {
      expect(isVesselQueryPath(path)).toBe(true)
    })

    it('계층 경로는 쿼리 화면이 아니다 — 경로가 정본이다', () => {
      expect(isVesselQueryPath(`/vessels/${VESSEL}`)).toBe(false)
    })

    it('대시보드는 쿼리 화면이 아니다 — 선박 범위를 갖지 않는다', () => {
      expect(isVesselQueryPath(DASHBOARD)).toBe(false)
    })
  })

  describe('readFromQuery', () => {
    it('선박·항차를 읽는다', () => {
      expect(readFromQuery(`?vessel_id=${VESSEL}&voyage_id=${VOYAGE}`)).toEqual({
        vesselId: VESSEL,
        voyageId: VOYAGE,
      })
    })

    it('빈 값은 없는 것으로 본다 — 지어내지 않는다', () => {
      expect(readFromQuery('?vessel_id=')).toEqual(EMPTY_CONTEXT)
    })

    it('쿼리가 없으면 빈 컨텍스트다', () => {
      expect(readFromQuery('')).toEqual(EMPTY_CONTEXT)
    })

    it('선박 없이 항차만 있으면 항차도 버린다 — 다른 배의 항차를 가리키게 된다', () => {
      expect(readFromQuery(`?voyage_id=${VOYAGE}`)).toEqual(EMPTY_CONTEXT)
    })
  })

  describe('withContextQuery', () => {
    it('선택을 쿼리에 싣는다', () => {
      expect(withContextQuery(FORECAST, '', { vesselId: VESSEL, voyageId: null })).toBe(
        `${FORECAST}?vessel_id=${VESSEL}`,
      )
    })

    it('선택을 지우면 쿼리에서도 뺀다', () => {
      expect(withContextQuery(FORECAST, `?vessel_id=${VESSEL}`, EMPTY_CONTEXT)).toBe(FORECAST)
    })

    it('선박을 지우면 항차도 함께 빠진다', () => {
      const before = `?vessel_id=${VESSEL}&voyage_id=${VOYAGE}`
      expect(withContextQuery(FORECAST, before, EMPTY_CONTEXT)).toBe(FORECAST)
    })

    it('다른 쿼리 파라미터는 보존한다 — #513의 severity가 사라지면 안 된다', () => {
      const result = withContextQuery(ANNUAL, '?severity=HIGH', {
        vesselId: VESSEL,
        voyageId: null,
      })
      expect(result).toContain('severity=HIGH')
      expect(result).toContain(`vessel_id=${VESSEL}`)
    })
  })

  describe('readContext — 어느 쪽이 이기는가', () => {
    const remembered = { vesselId: 'remembered-vessel', voyageId: null }

    it('계층 화면에서는 경로가 이긴다', () => {
      const result = readContext(`/vessels/${VESSEL}`, `?vessel_id=other`, remembered)
      expect(result.vesselId).toBe(VESSEL)
    })

    it('쿼리 화면에서는 쿼리가 기억을 이긴다', () => {
      const result = readContext(FORECAST, `?vessel_id=${VESSEL}`, remembered)
      expect(result.vesselId).toBe(VESSEL)
    })

    it('쿼리가 비면 기억해 둔 값으로 내려간다 — 사이드바로 들어온 경우다', () => {
      expect(readContext(FORECAST, '', remembered)).toEqual(remembered)
    })

    it('그 밖 화면은 기억해 둔 값이다', () => {
      expect(readContext(DASHBOARD, '', remembered)).toEqual(remembered)
    })
  })

  describe('navigationFor — 쿼리 화면', () => {
    it('머무른 채 주소만 갱신한다 — 화면이 튀지 않는다', () => {
      const target = navigationFor(FORECAST, { vesselId: VESSEL, voyageId: null }, '')
      expect(target).toBe(`${FORECAST}?vessel_id=${VESSEL}`)
    })

    it('이미 같은 값이면 이동하지 않는다 — 히스토리를 더럽히지 않는다', () => {
      const search = `?vessel_id=${VESSEL}`
      expect(navigationFor(FORECAST, { vesselId: VESSEL, voyageId: null }, search)).toBeNull()
    })

    it('계층 화면의 규칙은 그대로다', () => {
      const target = navigationFor(`/vessels/${VESSEL}`, { vesselId: 'v-2', voyageId: null })
      expect(target).toBe('/vessels/v-2')
    })

    it('대시보드에서는 여전히 이동하지 않는다', () => {
      expect(navigationFor(DASHBOARD, { vesselId: VESSEL, voyageId: null }, '')).toBeNull()
    })
  })
})
