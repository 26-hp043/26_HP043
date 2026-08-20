import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  FuelCatalogError,
  createApiFuelCatalog,
  createFuelCatalog,
  isKnownFuel,
} from './fuelCatalog'

/**
 * 연료 선택지 provider (#542 · #558).
 *
 * 잠그는 것은 세 가지다.
 *
 * * 실 API 모드에서 **서버 목록**이 온다 — 네 화면이 고정표를 읽던 것이 이번 결함이다
 * * demo 모드에서는 8/8 데모와 같은 화면이 나온다 — 고정표 그대로
 * * 성공·실패·재사용 경로가 모두 테스트로 잠긴다
 *
 * 화면 배선(`useFuelOptions`)은 DOM 환경이 없어 단언하지 않는다(`#557`). 그래서
 * 판정에 쓰이는 부분은 전부 순수 함수로 빼 두었다 — `isKnownFuel`이 그것이다.
 */

const OK_BODY = {
  data: [
    { code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 'tCO₂/t', is_active: true },
    { code: 'LNG', display_name: '액화천연가스', cf: '2.750', unit: 'tCO₂/t', is_active: true },
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
  it('서버 목록을 code·displayName으로 옮긴다', async () => {
    mockFetch(async () => jsonResponse(OK_BODY))

    const rows = await createApiFuelCatalog().listFuels()

    expect(rows).toEqual([
      { code: 'HFO', displayName: '고유황유' },
      { code: 'LNG', displayName: '액화천연가스' },
    ])
  })

  it('활성 필터를 화면에서 다시 걸지 않는다 — 서버 기본값이 활성만이다', async () => {
    // `routes/parameters.py`의 `active` 기본값이 `True`다. 화면이 또 거르면
    // 거르는 규칙이 두 곳이 되고, 한쪽만 바뀌면 목록이 갈린다.
    const spy = mockFetch(async () => jsonResponse(OK_BODY))

    await createApiFuelCatalog().listFuels()

    const [url] = spy.mock.calls[0] as unknown as [string]
    expect(url).toContain('/parameters/fuel-types')
    expect(url).not.toContain('active=')
  })

  it('성공한 조회는 한 번만 보낸다 — 네 화면이 같은 목록을 부른다', async () => {
    const spy = mockFetch(async () => jsonResponse(OK_BODY))
    const catalog = createApiFuelCatalog()

    await catalog.listFuels()
    await catalog.listFuels()

    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('실패는 붙들지 않는다 — 일시적 오류가 영구 실패로 굳지 않는다', async () => {
    let call = 0
    mockFetch(async () => {
      call += 1
      return call === 1 ? jsonResponse(null, 500) : jsonResponse(OK_BODY)
    })
    const catalog = createApiFuelCatalog()

    await expect(catalog.listFuels()).rejects.toBeInstanceOf(FuelCatalogError)
    await expect(catalog.listFuels()).resolves.toHaveLength(2)
  })

  it('네트워크 실패를 FuelCatalogError로 바꾼다', async () => {
    mockFetch(async () => {
      throw new Error('offline')
    })

    await expect(createApiFuelCatalog().listFuels()).rejects.toBeInstanceOf(FuelCatalogError)
  })
})

describe('createFuelCatalog — 갈래가 하나다 (#542)', () => {
  it('환경과 무관하게 서버를 부른다', async () => {
    // 종전에는 `VITE_USE_API`로 demo 고정표와 갈렸다. 데모 폐기 후 갈래가 없다.
    const spy = mockFetch(async () => jsonResponse(OK_BODY))

    await createFuelCatalog({} as ImportMetaEnv).listFuels()

    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('cf를 노출하지 않는다 — 화면이 계산에 쓸 수 있는 상태를 만들지 않는다', async () => {
    mockFetch(async () => jsonResponse(OK_BODY))

    const rows = await createFuelCatalog({} as ImportMetaEnv).listFuels()

    expect(Object.keys(rows[0]).sort()).toEqual(['code', 'displayName'])
  })
})

describe('isKnownFuel — 검증이 목록을 인자로 받는 이유', () => {
  it('목록에 있으면 참', () => {
    expect(isKnownFuel('HFO', [{ code: 'HFO', displayName: '고유황유' }])).toBe(true)
  })

  it('목록이 비면 무엇도 통과하지 않는다 — 로딩 중 제출을 막는 성질이다', () => {
    expect(isKnownFuel('HFO', [])).toBe(false)
  })
})
