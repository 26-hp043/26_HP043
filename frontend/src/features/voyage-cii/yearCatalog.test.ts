import { afterEach, describe, expect, it, vi } from 'vitest'

import { selectableYears } from './formRules'
import { DEMO_VESSELS } from './referenceTable'
import {
  YearCatalogError,
  createApiYearCatalog,
  createDemoYearCatalog,
  createYearCatalog,
} from './yearCatalog'

/**
 * 규제연도 선택지 provider (#534).
 *
 * 이슈의 완료 기준을 그대로 옮긴다.
 *
 * * 실 API 모드에서 고정표에 없는 선박도 연도를 받는다 — 이것이 3척이 계산 불가였던 원인
 * * demo 모드에서는 8/8 데모와 같은 화면이 나온다 — 고정표 그대로
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

describe('demo 카탈로그', () => {
  it('고정표를 그대로 감싼다 — 8/8 데모 경로가 바뀌지 않는다', async () => {
    const vesselId = DEMO_VESSELS[0].id

    const rows = await createDemoYearCatalog().listYears(vesselId)

    expect(rows).toEqual(selectableYears(vesselId))
    expect(rows.length).toBeGreaterThan(0)
  })

  it('고정표에 없는 선박은 빈 목록이다 — demo 모드의 종전 동작 그대로', async () => {
    const rows = await createDemoYearCatalog().listYears(CONTAINER_VESSEL_ID)

    expect(rows).toEqual([])
  })
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

    // 같은 선박이 demo 경로에서는 빈 목록이었다. 두 값이 갈리는 것이 이 이슈의 전부다.
    expect(await createDemoYearCatalog().listYears(CONTAINER_VESSEL_ID)).toEqual([])
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
  it('VITE_USE_API 미설정이면 demo를 쓴다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createYearCatalog({} as ImportMetaEnv).listYears(CONTAINER_VESSEL_ID)

    expect(spy).not.toHaveBeenCalled()
    expect(rows).toEqual([])
  })

  it('VITE_USE_API=true면 실 API를 쓴다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    const rows = await createYearCatalog({ VITE_USE_API: 'true' } as unknown as ImportMetaEnv).listYears(
      CONTAINER_VESSEL_ID,
    )

    expect(spy).toHaveBeenCalledTimes(1)
    expect(rows).toEqual([2023, 2026, 2030])
  })

  it('문자열 "false"를 참으로 읽지 않는다', async () => {
    const spy = mockFetch(() => jsonResponse(OK_BODY))

    await createYearCatalog({ VITE_USE_API: 'false' } as unknown as ImportMetaEnv).listYears(
      CONTAINER_VESSEL_ID,
    )

    expect(spy).not.toHaveBeenCalled()
  })
})
