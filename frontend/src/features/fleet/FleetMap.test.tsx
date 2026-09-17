// @vitest-environment jsdom
import '../../test/renderSetup'

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

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
vi.mock('maplibre-gl', () => {
  class FakeMap {
    touchZoomRotate = { disableRotation: vi.fn() }
    addControl = vi.fn()
    on = vi.fn()
    getSource = vi.fn().mockReturnValue(undefined)
    addSource = vi.fn()
    addLayer = vi.fn()
    setPaintProperty = vi.fn()
    getZoom = vi.fn().mockReturnValue(0)
    fitBounds = vi.fn()
    remove = vi.fn()
  }
  class FakeMarker {
    setLngLat = vi.fn().mockReturnThis()
    addTo = vi.fn().mockReturnThis()
    remove = vi.fn()
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

const { FleetMap } = await import('./FleetMap')

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

  it('전부 좌표가 있으면 아무 말도 하지 않는다 — 없는 문제를 만들지 않는다', () => {
    render(<FleetMap vessels={[vessel('1', '35.1', '129.0'), vessel('2', '34.0', '128.0')]} />)

    expect(screen.queryByText(/표시되지 않았습니다/)).toBeNull()
    const label = screen.getByRole('img').getAttribute('aria-label') ?? ''
    expect(label).not.toContain('빠져 있습니다')
  })
})
