// @vitest-environment jsdom
import '../../test/renderSetup'

import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FleetVessel } from './types'

/**
 * 좌표 없는 선박을 **조용히 빼지 않는다** (`#1103`).
 *
 * 지도는 좌표가 있는 선박만 그린다. 4척 중 1척이 미입력이면 3척만 찍히는데, 그림만
 * 보면 **그 3척이 선대 전부로** 읽힌다. 개략도(`PositionChart`)는 이 사실을 이미
 * 적고 있었고 이 지도만 아무 말도 하지 않았다.
 *
 * ## `maplibre-gl`을 대역으로 바꾼다
 *
 * jsdom에는 WebGL이 없어 실제 지도는 뜨지 않는다(`FleetDashboard.test.tsx`가 아예
 * `FleetMap`을 통째로 대역으로 바꾸는 이유다). 여기서 보려는 것은 **지도 자체가
 * 아니라 지도 옆의 안내**이므로, 지도를 대역으로 두고 그 안내만 본다.
 */
/**
 * 만들어진 지도를 기록한다 (`#1645`) — 「그때 만들어졌는가 · 정리됐는가」를 보려면
 * 인스턴스가 필요하다. 모의 안에서 `globalThis`를 거치는 것은 `vi.mock` 팩토리가
 * 호이스팅되어 파일 상단의 값을 가져다 쓸 수 없기 때문이다.
 */
type FakeMapRecord = {
  remove: ReturnType<typeof vi.fn>
  on: ReturnType<typeof vi.fn>
  addLayer: ReturnType<typeof vi.fn>
  addSource: ReturnType<typeof vi.fn>
  options: { style?: { sources?: Record<string, { attribution?: string }> } }
}
const mapsCreated = (): FakeMapRecord[] =>
  ((globalThis as { __fleetMaps?: FakeMapRecord[] }).__fleetMaps ??= [])
type FakeMarkerRecord = { element: HTMLElement; remove: ReturnType<typeof vi.fn> }
const markersCreated = (): FakeMarkerRecord[] =>
  ((globalThis as { __fleetMarkers?: FakeMarkerRecord[] }).__fleetMarkers ??= [])

vi.mock('maplibre-gl', () => {
  class FakeMap {
    touchZoomRotate = { disableRotation: vi.fn() }
    addControl = vi.fn()
    on = vi.fn()
    getSource = vi.fn().mockReturnValue(undefined)
    getLayer = vi.fn().mockReturnValue(undefined)
    addSource = vi.fn()
    addLayer = vi.fn()
    setPaintProperty = vi.fn()
    getZoom = vi.fn().mockReturnValue(0)
    fitBounds = vi.fn()
    remove = vi.fn()
    options: unknown
    constructor(options: unknown) {
      this.options = options
      const registry = (globalThis as { __fleetMaps?: unknown[] })
      registry.__fleetMaps ??= []
      registry.__fleetMaps.push(this)
    }
  }
  class FakeMarker {
    element: unknown
    setLngLat = vi.fn().mockReturnThis()
    addTo = vi.fn().mockReturnThis()
    remove = vi.fn()
    constructor(options: { element?: unknown }) {
      // 마커 DOM 노드를 기록한다 — 「항로 응답이 와도 같은 노드로 남는가」를 보려면 필요하다.
      this.element = options?.element
      const registry = (globalThis as { __fleetMarkers?: unknown[] })
      registry.__fleetMarkers ??= []
      registry.__fleetMarkers.push(this)
    }
  }
  class FakeBounds {
    extend = vi.fn()
  }
  return {
    Map: FakeMap,
    Marker: FakeMarker,
    LngLatBounds: FakeBounds,
    NavigationControl: class {},
    addProtocol: vi.fn(),
  }
})
vi.mock('pmtiles', () => ({ Protocol: class { tile = vi.fn() } }))
vi.mock('@protomaps/basemaps', () => ({ layers: () => [], namedFlavor: () => ({}) }))

const { FleetMap, ROUTE_ATTRIBUTION, ROUTE_PARTIAL_TEXT, ROUTE_UNAVAILABLE_TEXT } = await import('./FleetMap')

/*
 * 항로선은 서버에서 온다 (`#1300`). 기본 대역은 **아무 경로도 묻지 않는 배**(항차 없음)라
 * `fetch`가 불리지 않지만, 안전하게 빈 응답을 둔다 — 실제 네트워크로 나가지 않게.
 */
function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}
const SEA_LINE = {
  data: {
    coordinates: [
      [129.0333, 35.1],
      [129.2, 35],
      [103.85, 1.2833],
    ],
    length_nm: 2552.14,
    legs: 1,
    source: 'searoute/marnet',
  },
}
afterEach(() => {
  vi.unstubAllGlobals()
})

function vessel(id: string, lat: string | null, lon: string | null): FleetVessel {
  return {
    id,
    name: `선박 ${id}`,
    imoNumber: `900000${id}`,
    lat,
    lon,
    ytdRating: 'C',
    riskReasons: [],
  } as unknown as FleetVessel
}

describe('선대 지도 — 좌표 없는 선박 (#1103)', () => {
  it('일부가 빠지면 몇 척이 빠졌는지 적는다', () => {
    render(
      <FleetMap
        vessels={[
          vessel('1', '35.1', '129.0'),
          vessel('2', '34.0', '128.0'),
          vessel('3', '33.0', '127.0'),
          vessel('4', null, null),
        ]}
      />,
    )

    // 개략도와 **같은 문구**다 — 두 화면이 같은 사실을 다르게 말하면 안 된다.
    expect(screen.getByText(/위치 미기록 1척은 표시되지 않았습니다 — 4척 중 3척/)).toBeTruthy()
  })

  it('결측을 접근성 트리에도 넣는다 — 눈으로 보는 쪽에만 있으면 낭독은 못 듣는다', () => {
    render(<FleetMap vessels={[vessel('1', '35.1', '129.0'), vessel('2', null, null)]} />)

    const label = screen.getByRole('img').getAttribute('aria-label') ?? ''
    expect(label).toContain('선박 1척의 현재 위치 지도')
    expect(label).toContain('좌표가 없는 1척은 빠져 있습니다')
  })

  it('전부 빠지면 빈 지도를 띄우지 않는다 — 빈 바다는 「선박이 없다」로 읽힌다', () => {
    render(<FleetMap vessels={[vessel('1', null, null), vessel('2', null, null)]} />)

    expect(screen.getByText(/위치가 기록된 선박이 없습니다/)).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
  })

  /**
   * 좌표가 **나중에** 들어오면 지도가 그때 생긴다 (`#1645`).
   *
   * 종전에는 지도 초기화가 의존성 없는 effect라 **마운트 때 한 번만** 돌았다. 좌표가
   * 한 척도 없으면 캔버스 자체가 그려지지 않아 그 한 번이 헛돌았고, 위치가 들어와
   * 캔버스가 나타나도 effect가 다시 돌지 않아 **새로고침해야 지도가 보였다.**
   *
   * 실제로 이 순서가 난다 — 선대 조회가 먼저 오고 위치 갱신이 뒤따르거나
   * (`#1624` 위치 이력), 현장직이 위치를 막 입력한 직후가 그렇다.
   */
  it('좌표가 나중에 들어오면 지도를 그때 만든다 (#1645)', () => {
    mapsCreated().length = 0

    const { rerender } = render(
      <FleetMap vessels={[vessel('1', null, null), vessel('2', null, null)]} />,
    )
    // 캔버스가 없으니 지도도 없다 — 여기까지는 종전과 같다.
    expect(screen.queryByRole('img')).toBeNull()
    expect(mapsCreated()).toHaveLength(0)

    rerender(<FleetMap vessels={[vessel('1', '35.1', '129.0'), vessel('2', null, null)]} />)

    expect(screen.getByRole('img')).toBeTruthy()
    // 종전에는 여기서 0이었다 — 캔버스는 생겼는데 지도는 만들어지지 않았다.
    expect(mapsCreated()).toHaveLength(1)
  })

  it('좌표가 사라지면 지도를 정리한다 — 인스턴스가 남지 않는다 (#1645)', () => {
    mapsCreated().length = 0

    const { rerender } = render(<FleetMap vessels={[vessel('1', '35.1', '129.0')]} />)
    expect(mapsCreated()).toHaveLength(1)

    rerender(<FleetMap vessels={[vessel('1', null, null)]} />)

    expect(screen.getByText(/위치가 기록된 선박이 없습니다/)).toBeTruthy()
    expect(mapsCreated()[0].remove).toHaveBeenCalled()
  })

  it('기본 캡션은 점선이 항해 계획이 아니라는 것과 굵은 테두리의 뜻을 둘 다 말한다 (#1421 · #1300)', () => {
    const { container } = render(<FleetMap vessels={[vessel('1', '35.1', '129.0')]} />)

    const hint = container.querySelector('.fleetmap__hint')?.textContent ?? ''
    // 정본 문구 (DESIGN_SYSTEM §9.5 「항로선은 공개 해상 경로망 위의 바닷길이다」 · ⚠️ 개발
    // 임시안 · §16 항목 21) — 「실제 항해 계획이 아니다」는 고지의 뜻이라 문장이 바뀌어도
    // 남아야 한다. 선이 경로망 위의 바닷길이 되면서(#1300) 「육지를 가로지른다」는 더 이상
    // 사실이 아니다 — 그 말이 되살아나면 캡션이 거짓이다.
    expect(hint).toMatch(/항해 계획이 아닙니다/)
    expect(hint).not.toMatch(/육지/)
    // 스스로 설명되지 않는 유일한 표식 — 말의 순서는 바뀌어도 된다
    expect(hint).toMatch(/테두리/)
    expect(hint).toMatch(/굵/)
  })

  it('전부 좌표가 있으면 아무 말도 하지 않는다 — 없는 문제를 만들지 않는다', () => {
    render(<FleetMap vessels={[vessel('1', '35.1', '129.0'), vessel('2', '34.0', '128.0')]} />)

    expect(screen.queryByText(/표시되지 않았습니다/)).toBeNull()
    const label = screen.getByRole('img').getAttribute('aria-label') ?? ''
    expect(label).not.toContain('빠져 있습니다')
  })
})

/**
 * 항로선은 공개 해상 경로망 위의 바닷길이다 (`#1300`).
 *
 * 선을 화면이 만들지 않고 서버(`API_SPEC §3.11`)에서 받는다. 잠그는 것은 셋 — ⑴ 진행 중
 * 항차의 두 점을 서버에 묻는다 ⑵ 직항·우회 두 레이어가 **선의 결**로 갈린다(색 단독 금지 ·
 * `§14`) ⑶ 못 받으면 선을 지어내지 않고 그 사실을 적는다.
 */
describe('선대 지도 — 해상 경로망 항로선 (#1300)', () => {
  const underway = () =>
    ({
      ...vessel('1', '35.1', '129.0'),
      route: { departureLat: '35.1', departureLon: '129.0333', arrivalLat: '1.2833', arrivalLon: '103.85' },
    }) as FleetVessel

  /** 대역 지도의 `load`를 울린다 — 실제 지도는 타일이 오면 스스로 울린다. */
  function fireLoad() {
    const map = mapsCreated().at(-1)!
    const onLoad = map.on.mock.calls.find((call) => call[0] === 'load')?.[1] as () => void
    act(() => onLoad())
  }

  it('진행 중 항차의 두 점을 서버에 묻는다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse(SEA_LINE))
    vi.stubGlobal('fetch', fetchImpl)

    render(<FleetMap vessels={[underway()]} />)

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    const url = String(fetchImpl.mock.calls[0][0])
    expect(url).toContain('/ports/sea-route?')
    expect(url).toContain('from_lon=129.0333')
    expect(url).toContain('to_lat=1.2833')
  })

  it('직항과 우회는 같은 색, 다른 결의 두 레이어다 — 색만으로 가르지 않는다 (§14)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(SEA_LINE)))
    mapsCreated().length = 0

    render(<FleetMap vessels={[underway()]} />)
    fireLoad()

    const map = mapsCreated()[0]
    const layerIds = () => map.addLayer.mock.calls.map((call) => (call[0] as { id: string }).id)
    await waitFor(() =>
      expect(layerIds()).toEqual(expect.arrayContaining(['routes', 'routes-detour'])),
    )
    const layers = map.addLayer.mock.calls.map((call) => call[0] as { id: string; paint: Record<string, unknown> })
    const direct = layers.find((layer) => layer.id === 'routes')!
    const detour = layers.find((layer) => layer.id === 'routes-detour')!
    // 직항은 `§9.5` 🔒 그대로다.
    expect(direct.paint['line-dasharray']).toEqual([2, 1.5])
    expect(detour.paint['line-dasharray']).not.toEqual(direct.paint['line-dasharray'])
    expect(detour.paint['line-color']).toEqual(direct.paint['line-color'])
    expect(detour.paint['line-width']).toEqual(direct.paint['line-width'])
  })

  it('선을 못 받으면 지어내지 않고 그 사실을 적는다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 503)))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    render(<FleetMap vessels={[underway()]} />)

    expect(await screen.findByText(ROUTE_UNAVAILABLE_TEXT)).toBeTruthy()
    // 이유는 콘솔이 갖는다 — `console.error`가 아니다(#1616 가드는 error만 실패로 본다).
    expect(warn).toHaveBeenCalledWith('[seaRoute]', expect.any(String), expect.anything())
  })

  it('못 받았을 때의 문장은 호출부가 바꿀 수 있다 — 선박을 그리지 않는 화면에서 「위치만」은 거짓이다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 503)))
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    render(<FleetMap vessels={[underway()]} routeUnavailableText="경로를 그리지 못했습니다." />)

    expect(await screen.findByText('경로를 그리지 못했습니다.')).toBeTruthy()
    expect(screen.queryByText(ROUTE_UNAVAILABLE_TEXT)).toBeNull()
  })

  it('항로 응답이 와도 마커 DOM 노드는 같은 노드로 남는다 — 마커와 항로선은 다른 effect다', async () => {
    let release: (value: Response) => void = () => undefined
    const pending = new Promise<Response>((resolve) => {
      release = resolve
    })
    vi.stubGlobal('fetch', vi.fn(async () => pending))
    mapsCreated().length = 0
    markersCreated().length = 0

    render(<FleetMap vessels={[underway()]} />)
    fireLoad()

    await waitFor(() => expect(markersCreated()).toHaveLength(1))
    const before = markersCreated()[0]
    const node = before.element

    // 이제 항로선이 도착한다 — 마커를 다시 만들 이유가 없다.
    await act(async () => {
      release(jsonResponse(SEA_LINE))
      await pending
    })
    await waitFor(() => expect(mapsCreated()[0].addLayer).toHaveBeenCalled())

    expect(markersCreated()).toHaveLength(1)
    expect(markersCreated()[0].element).toBe(node)
    expect(before.remove).not.toHaveBeenCalled()
  })

  it('받았으면 그 문장이 없다 — 없는 문제를 만들지 않는다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(SEA_LINE))
    vi.stubGlobal('fetch', fetchImpl)

    render(<FleetMap vessels={[underway()]} />)

    await waitFor(() => expect(fetchImpl).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByText(ROUTE_UNAVAILABLE_TEXT)).toBeNull()
  })

  it('실패 뒤 재시도 신호가 바뀌면 못 받은 선만 다시 묻고, 받으면 실패 문장이 사라진다 (#1856)', async () => {
    let healthy = false
    const fetchImpl = vi.fn(async () => (healthy ? jsonResponse(SEA_LINE) : jsonResponse({}, 503)))
    vi.stubGlobal('fetch', fetchImpl)
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    const { rerender } = render(<FleetMap vessels={[underway()]} retryToken={0} />)
    expect(await screen.findByText(ROUTE_UNAVAILABLE_TEXT)).toBeTruthy()
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    // 같은 신호로 다시 그려도 묻지 않는다 — 폭주 방지.
    rerender(<FleetMap vessels={[underway()]} retryToken={0} />)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    // 서버가 회복됐고 사용자가 「다시 시도」를 눌렀다.
    healthy = true
    rerender(<FleetMap vessels={[underway()]} retryToken={1} />)
    await waitFor(() => expect(screen.queryByText(ROUTE_UNAVAILABLE_TEXT)).toBeNull())
    expect(fetchImpl).toHaveBeenCalledTimes(2)

    // 받은 선은 다음 재시도에서 다시 묻지 않는다.
    rerender(<FleetMap vessels={[underway()]} retryToken={2} />)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('우회만 실패하면 직항 선은 남고, 문장은 「전부 못 받음」과 다르다 (#1856)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) =>
        String(input).includes('via_lat') ? jsonResponse({}, 404) : jsonResponse(SEA_LINE),
      ),
    )
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    mapsCreated().length = 0
    const ends = { departureLat: 35.1, departureLon: 129.0333, arrivalLat: 1.2833, arrivalLon: 103.85 }

    render(
      <FleetMap
        vessels={[vessel('1', '35.1', '129.0')]}
        routes={[
          { ...ends, name: '직항', kind: 'DIRECT' },
          { ...ends, name: '우회', kind: 'DETOUR', via: { lat: 21.3, lon: -157.87 } },
        ]}
      />,
    )
    fireLoad()

    expect(await screen.findByText(ROUTE_PARTIAL_TEXT)).toBeTruthy()
    // 일부 실패 문장은 전부 실패 문장과 다르다 — 받은 선이 그려져 있으니 「위치만」은 거짓이다.
    expect(ROUTE_PARTIAL_TEXT).not.toBe(ROUTE_UNAVAILABLE_TEXT)
    expect(screen.queryByText(ROUTE_UNAVAILABLE_TEXT)).toBeNull()
    const map = mapsCreated()[0]
    await waitFor(() => {
      const data = map.addSource.mock.calls.at(-1)?.[1] as {
        data: { features: { properties: { kind: string } }[] }
      }
      expect(data.data.features.map((feature) => feature.properties.kind)).toEqual(['DIRECT'])
    })
  })

  it('경로망 출처가 지도 스타일의 소스에 실린다 — 「© OpenStreetMap」과 나란히', () => {
    mapsCreated().length = 0
    render(<FleetMap vessels={[vessel('1', '35.1', '129.0')]} />)

    const sources = mapsCreated()[0].options.style?.sources ?? {}
    expect(sources.protomaps?.attribution).toBe('© OpenStreetMap')
    expect(sources.routes?.attribution).toBe(ROUTE_ATTRIBUTION)
    expect(ROUTE_ATTRIBUTION).toMatch(/EUPL-1\.2/)
    expect(ROUTE_ATTRIBUTION).toMatch(/Apache-2\.0/)
  })
})
