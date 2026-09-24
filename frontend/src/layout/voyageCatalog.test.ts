import { describe, expect, it, vi } from 'vitest'
import type { SamplePort } from '../features/ports/samplePorts'
import {
  VoyageCatalogError,
  createApiVoyageCatalog,
  createVoyageCatalog,
  voyageOptionLabel,
  type VoyageOption,
} from './voyageCatalog'

/**
 * #512 — 항차 선택지 provider.
 *
 * `vesselCatalog.ts`(#236)와 같은 경계다 — 화면은 출처를 알지 않고, 조회 경로
 * 전환은 같은 환경변수로 결정된다.
 *
 * ## 조회와 표시 이름을 가른다 (#1812 재작업)
 *
 * `listVoyages`는 저장 코드 원문을 그대로 담아 온다 — 항구 목록과 무관하게 한 번만
 * 돈다. 화면에 보일 문자열은 `voyageOptionLabel`이 그릴 때마다 만든다. 처음에는
 * `listVoyages`가 `ports`를 받아 미리 변환했으나, 그러면 `useSamplePorts()`가 비동기로
 * 늦게 도착할 때마다 항차를 다시 조회하게 되어(상단바 깜빡임 · `ScenarioAdoptPanel`의
 * 선택 유실) 되돌렸다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

const BUSAN: SamplePort = {
  locode: 'KRPUS',
  name: 'BUSAN',
  name_ko: '부산',
  country_code: 'KR',
  lat: 35.1,
  lon: 129.0333,
}
const PORTS: SamplePort[] = [BUSAN]

function option(over: Partial<VoyageOption> = {}): VoyageOption {
  return {
    id: 'v-1',
    voyageNo: null,
    departurePortName: null,
    arrivalPortName: null,
    status: '',
    ...over,
  }
}

describe('voyageOptionLabel — 여러 건이 같은 문자열이 되지 않게 한다', () => {
  it('항차 번호가 있으면 그것이 이름이다', () => {
    expect(voyageOptionLabel(option({ voyageNo: 'V-2026-001' }), [])).toBe('V-2026-001')
  })

  it('번호가 없으면 구간으로 대신한다', () => {
    expect(
      voyageOptionLabel(
        option({ departurePortName: '부산', arrivalPortName: '싱가포르' }),
        [],
      ),
    ).toBe('부산 → 싱가포르')
  })

  it('한쪽 항구만 있으면 나머지를 —로 둔다', () => {
    expect(voyageOptionLabel(option({ departurePortName: '부산' }), [])).toBe('부산 → —')
  })

  it('둘 다 없으면 id 앞자리를 보인다 — 「이름 없는 항차」로 뭉뚱그리지 않는다', () => {
    expect(voyageOptionLabel(option({ id: '0123456789abcdef' }), [])).toBe('01234567')
  })

  // #1812 — 구간이 저장 코드(`BUSAN`)가 아니라 보이는 이름(`부산`)으로 나온다.
  it('저장 코드는 목록에 있으면 보이는 이름으로 바뀐다 — 코드가 그대로 노출되지 않는다', () => {
    const label = voyageOptionLabel(
      option({ departurePortName: 'BUSAN', arrivalPortName: 'SINGAPORE' }),
      PORTS,
    )
    // 부정 단언만 두면 구간이 통째로 빠져도 통과한다 (#1836) — 픽스처의 보이는 이름이
    // 실제로 들어 있는지도 본다(리터럴이 아니라 픽스처 값 · `AGENTS §4.6`).
    expect(label).not.toContain(BUSAN.name)
    expect(label).toContain(BUSAN.name_ko)
  })

  it('목록에 없는 저장값은 입력한 그대로다 — 사전에 없는 이름을 지어내지 않는다', () => {
    expect(voyageOptionLabel(option({ departurePortName: 'ULSAN' }), PORTS)).toBe('ULSAN → —')
  })
})

describe('실 API — GET /vessels/{id}/voyages', () => {
  it('선박 id를 경로에 넣어 부른다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [] }))
    vi.stubGlobal('fetch', fetchImpl)
    await createApiVoyageCatalog('/api/v1').listVoyages('v1')
    const [url] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/vessels/v1/voyages?limit=100')
    vi.unstubAllGlobals()
  })

  it('id가 없는 행은 버린다 — 고를 수 없는 선택지다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ data: [{ voyage_no: 'V-1' }, { id: 'a', voyage_no: 'V-2' }] }),
    )
    vi.stubGlobal('fetch', fetchImpl)
    const options = await createApiVoyageCatalog('/api/v1').listVoyages('v1')
    expect(options).toEqual([
      {
        id: 'a',
        voyageNo: 'V-2',
        departurePortName: null,
        arrivalPortName: null,
        status: '',
      },
    ])
    vi.unstubAllGlobals()
  })

  // #1836 ⑴ — 트림 검사가 `voyageOptionLabel`에서 API 매핑으로 옮겨가며(#1812) 빠졌던
  // 회귀 테스트. 매핑에서 `.trim()`을 지우면 공백 번호가 이름이 되어 빈 옵션이 보인다.
  it('공백뿐인 항차 번호는 없는 것으로 본다 — 빈 옵션이 되지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ data: [{ id: 'a', voyage_no: '   ', status: 'PLANNED' }] })),
    )
    const options = await createApiVoyageCatalog('/api/v1').listVoyages('v1')
    expect(options[0].voyageNo).toBeNull()
    vi.unstubAllGlobals()
  })

  it('data가 배열이 아니면 빈 목록으로 본다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ data: null })))
    await expect(createApiVoyageCatalog('/api/v1').listVoyages('v1')).resolves.toEqual([])
    vi.unstubAllGlobals()
  })

  it('오류 응답은 VoyageCatalogError가 된다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 500)))
    await expect(createApiVoyageCatalog('/api/v1').listVoyages('v1')).rejects.toBeInstanceOf(
      VoyageCatalogError,
    )
    vi.unstubAllGlobals()
  })

  it('네트워크 실패도 VoyageCatalogError가 된다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('failed to fetch')
      }),
    )
    await expect(createApiVoyageCatalog('/api/v1').listVoyages('v1')).rejects.toBeInstanceOf(
      VoyageCatalogError,
    )
    vi.unstubAllGlobals()
  })

  // #1812 — 조회 결과는 저장 코드 원문을 그대로 담는다. 코드→이름 변환은
  // `voyageOptionLabel`이 그릴 때 한다(위 describe 참조).
  it('항차 번호가 없는 행은 구간의 저장 코드 원문을 그대로 담는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          data: [{ id: 'a', departure_port_name: 'BUSAN', arrival_port_name: 'SINGAPORE' }],
        }),
      ),
    )
    const options = await createApiVoyageCatalog('/api/v1').listVoyages('v1')
    expect(options[0]).toEqual({
      id: 'a',
      voyageNo: null,
      departurePortName: 'BUSAN',
      arrivalPortName: 'SINGAPORE',
      status: '',
    })
    vi.unstubAllGlobals()
  })
})

describe('createVoyageCatalog', () => {
  it('환경과 무관하게 실 API를 부른다 — 갈래가 없다 (#542)', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [] }))
    vi.stubGlobal('fetch', fetchImpl)

    await createVoyageCatalog({} as ImportMetaEnv).listVoyages('v1')

    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('true면 실 API를 부른다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [] }))
    vi.stubGlobal('fetch', fetchImpl)
    await createVoyageCatalog({} as ImportMetaEnv).listVoyages('v1')
    expect(fetchImpl).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

/**
 * 커서를 끝까지 따른다 (`#1073`) — 이슈 완료 기준: 항차 25건인 선박에서 25번째 항차를 고를 수 있다.
 */
describe('페이지 따라가기 (#1073)', () => {
  it('25건이면 두 페이지를 이어 받아 25번째가 목록에 있다', async () => {
    const voyage = (n: number) => ({ id: `v${n}`, voyage_no: `NO-${n}`, status: 'PLANNED' })
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        urls.push(url)
        if (url.includes('cursor=c2')) {
          return jsonResponse({ data: [21, 22, 23, 24, 25].map(voyage), meta: { next_cursor: null } })
        }
        return jsonResponse({
          data: Array.from({ length: 20 }, (_, i) => voyage(i + 1)),
          meta: { next_cursor: 'c2' },
        })
      }),
    )
    const rows = await createApiVoyageCatalog('/api/v1').listVoyages('vessel-1')
    expect(rows).toHaveLength(25)
    expect(rows.at(-1)?.id).toBe('v25')
    expect(urls[1]).toContain('cursor=c2')
    vi.unstubAllGlobals()
  })
})
