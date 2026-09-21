import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  YearCatalogError,
  createApiYearCatalog,
  createYearCatalog,
  displayYears,
} from './yearCatalog'

/**
 * 규제연도 선택지 provider (#534).
 *
 * 이슈의 완료 기준을 그대로 옮긴다.
 *
 * * 실 API 모드에서 고정표에 없는 선박도 연도를 받는다 — 이것이 3척이 계산 불가였던 원인
 * * 성공·실패 경로가 모두 테스트로 잠긴다
 */

/** `demo_seed`가 넣는 선박 중 고정표에 **없는** UUID. 이 값이 이번 결함의 핵심이다. */
const CONTAINER_VESSEL_ID = '00000000-0000-4000-8000-000000000002'

const OK_BODY = {
  data: [
    { year: 2026, z_factor_percent: '11.0000' },
    { year: 2023, z_factor_percent: '5.0000' },
    { year: 2030, z_factor_percent: '21.5000' },
  ],
}

function mockFetch(impl: (...args: unknown[]) => Promise<unknown> | unknown) {
  const spy = vi.fn(impl)
  vi.stubGlobal('fetch', spy)
  return spy
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})


describe('실 API 카탈로그', () => {
  it('GET /parameters/regulation-years 를 부른다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    await createApiYearCatalog().listYears(CONTAINER_VESSEL_ID)

    expect(String(spy.mock.calls[0][0])).toBe('/api/v1/parameters/regulation-years')
  })

  it('고정표에 없는 선박도 연도를 받는다 — #534가 고치는 상태', async () => {
    mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createApiYearCatalog().listYears(CONTAINER_VESSEL_ID)

    // 종전 demo 경로에서는 이 선박이 빈 목록이었다. 두 값이 갈리는 것이 #534의
    // 전부였고, 갈릴 경로 자체가 #542로 사라졌다.
    expect(rows.length).toBeGreaterThan(0)
  })

  it('오름차순으로 정렬한다 — 서버 순서에 기대지 않는다', async () => {
    mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createApiYearCatalog().listYears(CONTAINER_VESSEL_ID)

    expect(rows).toEqual([2023, 2026, 2030])
  })

  it('연도가 아닌 행은 버린다', async () => {
    mockFetch(() =>
      jsonResponse({ data: [{ year: 2026 }, { year: '2027' }, { year: null }, {}] }),
    )

    const rows = await createApiYearCatalog().listYears(CONTAINER_VESSEL_ID)

    expect(rows).toEqual([2026])
  })

  it('data가 배열이 아니면 빈 목록이다', async () => {
    mockFetch(() => jsonResponse({ data: null }))

    const rows = await createApiYearCatalog().listYears(CONTAINER_VESSEL_ID)

    expect(rows).toEqual([])
  })

  it('선박이 바뀌어도 다시 부르지 않는다 — 답이 선박과 무관하다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))
    const catalog = createApiYearCatalog()

    await catalog.listYears(CONTAINER_VESSEL_ID)
    await catalog.listYears('00000000-0000-4000-8000-000000000003')
    await catalog.listYears('00000000-0000-4000-8000-000000000004')

    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('실패는 붙들지 않는다 — 다음 호출에서 다시 시도한다', async () => {
    let attempt = 0
    const spy = mockFetch(() => {
      attempt += 1
      return attempt === 1 ? Promise.reject(new Error('boom')) : jsonResponse(OK_BODY)
    })
    const catalog = createApiYearCatalog()

    await expect(catalog.listYears(CONTAINER_VESSEL_ID)).rejects.toBeInstanceOf(YearCatalogError)
    expect(await catalog.listYears(CONTAINER_VESSEL_ID)).toEqual([2023, 2026, 2030])
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('HTTP 오류는 YearCatalogError로 옮긴다', async () => {
    mockFetch(() => jsonResponse({}, 500))

    await expect(createApiYearCatalog().listYears(CONTAINER_VESSEL_ID)).rejects.toBeInstanceOf(
      YearCatalogError,
    )
  })

  it('네트워크 실패도 YearCatalogError로 옮긴다', async () => {
    mockFetch(() => Promise.reject(new Error('boom')))

    await expect(createApiYearCatalog().listYears(CONTAINER_VESSEL_ID)).rejects.toBeInstanceOf(
      YearCatalogError,
    )
  })
})

describe('전환 스위치', () => {
  it('환경과 무관하게 실 API를 쓴다 — 갈래가 없다 (#542)', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createYearCatalog({} as ImportMetaEnv).listYears(CONTAINER_VESSEL_ID)

    expect(spy).toHaveBeenCalledTimes(1)
    expect(rows.length).toBeGreaterThan(0)
  })

  it('실 API를 쓴다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createYearCatalog({} as ImportMetaEnv).listYears(
      CONTAINER_VESSEL_ID,
    )

    expect(spy).toHaveBeenCalledTimes(1)
    expect(rows).toEqual([2023, 2026, 2030])
  })

})

/**
 * 화면에 내놓는 연도 선택지 (#1584). 종전 `reportRules.yearOptions`(#635)의 검사를
 * 옮겨 왔다 — 규칙이 보고서 한 화면에서 모든 화면으로 넓어졌다.
 */
describe('연도 선택지 — 최신 연도부터 · 조회 화면은 올해까지', () => {
  /** `GET /parameters/regulation-years`가 주는 값 (현재 seed 기준). */
  const SERVER_YEARS = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]

  it('조회 화면은 미래 연도를 넣지 않는다 — 실적이 있을 수 없는 해다', () => {
    expect(displayYears(SERVER_YEARS, 2026)).toEqual([2026, 2025, 2024, 2023])
  })

  it('계획 화면(`null`)은 미래 연도를 남기고 순서만 최신부터다', () => {
    expect(displayYears(SERVER_YEARS, null)).toEqual([2030, 2029, 2028, 2027, 2026, 2025, 2024, 2023])
  })

  it('서버 순서에 기대지 않는다', () => {
    expect(displayYears([2025, 2023, 2024], 2026)).toEqual([2025, 2024, 2023])
    expect(displayYears([2025, 2023, 2024], null)).toEqual([2025, 2024, 2023])
  })

  it('개수를 자르지 않는다 — 규제연도가 늘면 선택지도 는다', () => {
    expect(displayYears(SERVER_YEARS, 2030)).toHaveLength(8)
  })

  it('목록이 비면 선택지도 비운다 — 기본값을 지어내지 않는다', () => {
    expect(displayYears([], 2026)).toEqual([])
    expect(displayYears([], null)).toEqual([])
  })

  it('입력 배열을 바꾸지 않는다', () => {
    const rows = [2023, 2024]
    displayYears(rows, null)
    expect(rows).toEqual([2023, 2024])
  })
})
