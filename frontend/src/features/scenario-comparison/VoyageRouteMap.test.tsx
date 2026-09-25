// @vitest-environment jsdom
import '../../test/renderSetup'

import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * 항로 비교의 지도 — 선이 하나 또는 둘이다 (`#1300`).
 *
 * `FleetMap`은 대역이다 — 여기서 보는 것은 지도가 아니라 **지도에 무엇을 넘기는가**다.
 * 우회 경유지가 있을 때만 우회 선(`kind: 'DETOUR'` · `via`)이 더해지고, 캡션이 두 선을
 * 설명한다. 좌표가 빠지면 아무것도 그리지 않는다(`#1265`).
 */
vi.mock('../fleet/basemap', () => ({ hasBasemap: async () => true }))
vi.mock('../map/renderer', () => ({
  MapRendererHost: (props: {
    model: { routes: { data: { features: unknown[] } }; ports: unknown[] }
    ariaLabel: string
    ariaDescribedBy?: string
  }) => (
    <div
      data-testid="map"
      data-routes={JSON.stringify(props.model.routes.data.features)}
      data-ports={JSON.stringify(props.model.ports)}
      aria-label={props.ariaLabel}
      aria-describedby={props.ariaDescribedBy}
    />
  ),
}))
vi.mock('../map/mapLibreRenderer', () => ({ mapLibreRenderer: {}, MapLibreMapModel: {} }))

const { VoyageRouteMap } = await import('./VoyageRouteMap')

const ENDS = { currentLat: '35.1', currentLon: '129.0333', destinationLat: '1.2833', destinationLon: '103.85' }

interface RouteFeature {
  properties: { name: string; kind: 'DIRECT' | 'DETOUR' }
  geometry: { coordinates: [number, number][] }
}

function routesOf(map: HTMLElement): RouteFeature[] {
  return JSON.parse(map.getAttribute('data-routes') ?? '[]') as RouteFeature[]
}

let failMode: 'none' | 'all' | 'detour'

beforeEach(() => {
  failMode = 'none'
  vi.stubGlobal('fetch', vi.fn(async (input: unknown) => {
    const url = new URL(String(input), 'https://x')
    if (url.pathname.includes('/ports/samples')) {
      return { ok: true, status: 200, json: async () => ({ data: [] }) } as Response
    }
    const detour = url.searchParams.has('via_lat')
    if (failMode === 'all' || (failMode === 'detour' && detour)) {
      return { ok: false, status: 503, json: async () => ({}) } as Response
    }
    const coordinates = [
      [Number(url.searchParams.get('from_lon')), Number(url.searchParams.get('from_lat'))],
      ...(detour ? [[Number(url.searchParams.get('via_lon')), Number(url.searchParams.get('via_lat'))]] : []),
      [Number(url.searchParams.get('to_lon')), Number(url.searchParams.get('to_lat'))],
    ]
    return { ok: true, status: 200, json: async () => ({ data: { coordinates, length_nm: 1, legs: detour ? 2 : 1, source: 'searoute/marnet' } }) } as Response
  }))
})

afterEach(() => vi.unstubAllGlobals())

describe('항로 비교 지도 — 선의 수 (#1300)', () => {
  it('경유지가 없으면 직항 선 하나이고, 캡션이 경로망 위의 경로라고 말한다', async () => {
    render(<VoyageRouteMap {...ENDS} destinationName="SINGAPORE" />)

    const map = await screen.findByTestId('map')
    await waitFor(() => expect(routesOf(map)).toHaveLength(1))
    const routes = routesOf(map)
    expect(routes).toHaveLength(1)
    expect(routes[0].properties).toMatchObject({ kind: 'DIRECT', name: 'SINGAPORE' })
    expect(routes[0].geometry.coordinates[0]).toEqual([129.0333, 35.1])
    // 정본 문구 (DESIGN_SYSTEM §9.5 「항로선은 공개 해상 경로망 위의 바닷길이다」 · ⚠️ 개발 임시안 ·
    // §16 항목 21) — 낱말이 아니라 뜻을 본다: 경로망 위의 선이며 항해 계획이 아니라는 것.
    expect(document.body.textContent).toMatch(/경로망/)
    expect(document.body.textContent).toMatch(/항해 계획이 아닙니다/)
    expect(document.body.textContent).not.toMatch(/최단 경로/)
    expect(map.getAttribute('aria-label')).toMatch(/항해 계획이 아닙니다/)
    expect(document.getElementById(map.getAttribute('aria-describedby') ?? '')?.textContent).toMatch(/CII 계산 거리/)
  })

  it('경유지가 있으면 우회 선이 하나 더 있고 경유지를 지난다', async () => {
    render(
      <VoyageRouteMap
        {...ENDS}
        detourWaypointLat="21.3"
        detourWaypointLon="-157.87"
        detourWaypointName="HONOLULU"
      />,
    )

    const map = await screen.findByTestId('map')
    await waitFor(() => expect(routesOf(map)).toHaveLength(2))
    const routes = routesOf(map)
    expect(routes).toHaveLength(2)
    expect(routes[1].properties).toMatchObject({ kind: 'DETOUR' })
    expect(routes[1].properties.name).toContain('HONOLULU')
    expect(JSON.stringify(routes[1].geometry.coordinates)).toContain('[-157.87,21.3]')
    const ports = JSON.parse(map.getAttribute('data-ports') ?? '[]') as Array<{ role: string; label: string }>
    expect(ports).toEqual(expect.arrayContaining([
      expect.objectContaining({ role: 'departure' }),
      expect.objectContaining({ role: 'destination', label: '목적항' }),
      expect.objectContaining({ role: 'waypoint', label: 'HONOLULU' }),
    ]))
    expect(document.body.textContent).toMatch(/우회/)
    expect(document.body.textContent).toMatch(/항해 계획이 아닙니다/)
  })

  it('선을 못 받았을 때의 문장은 이 화면의 것이다 — 선박을 그리지 않으니 「위치만 표시」가 아니다', async () => {
    failMode = 'all'
    render(<VoyageRouteMap {...ENDS} />)
    await screen.findByTestId('map')
    await waitFor(() => expect(document.body.textContent).toMatch(/불러오지 못했습니다/))
    const text = document.body.textContent ?? ''
    expect(text.length).toBeGreaterThan(0)
    expect(text).not.toMatch(/위치만/)
    // 표가 차이를 말한다는 것은 남는다 — 지도가 빠져도 화면이 답을 잃지 않는다.
    expect(text).toMatch(/표/)
  })

  it('선 일부만 못 받았을 때의 문장도 이 화면의 것이다 — 「위치만 표시」가 아니고 전부 실패와 다르다 (#1856)', async () => {
    failMode = 'detour'
    render(<VoyageRouteMap {...ENDS} detourWaypointLat="21.3" detourWaypointLon="-157.87" />)
    await screen.findByTestId('map')
    await waitFor(() => expect(document.body.textContent).toMatch(/일부를 불러오지 못했습니다/))
    const partial = document.body.textContent ?? ''
    // 넘기지 않으면 선대 기본 문장(「…위치만 표시합니다」)이 이 화면에 뜬다 — 선박이 없는 화면이라 거짓이다.
    expect(partial.length).toBeGreaterThan(0)
    expect(partial).not.toMatch(/위치만/)
    expect(partial).not.toContain('위치만 표시')
    expect(partial).toMatch(/표/)
  })

  it('경유지 좌표가 반쪽이면 우회 선을 그리지 않는다 — 반쪽 좌표는 위치가 아니다', async () => {
    render(<VoyageRouteMap {...ENDS} detourWaypointLat="21.3" />)

    const map = await screen.findByTestId('map')
    await waitFor(() => expect(routesOf(map)).toHaveLength(1))
  })

  it('양 끝 좌표가 빠지면 아무것도 그리지 않는다 (#1265)', async () => {
    const { container } = render(
      <VoyageRouteMap {...ENDS} destinationLat="" detourWaypointLat="21.3" detourWaypointLon="-157.87" />,
    )
    // 자산 판정이 끝나도 지도는 없다 — 좌표 없음은 정상 상태다.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(container.querySelector('[data-testid="map"]')).toBeNull()
  })
})
