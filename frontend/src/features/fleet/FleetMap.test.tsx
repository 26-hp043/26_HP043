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
/**
 * 만들어진 지도를 기록한다 (`#1645`) — 「그때 만들어졌는가 · 정리됐는가」를 보려면
 * 인스턴스가 필요하다. 모의 안에서 `globalThis`를 거치는 것은 `vi.mock` 팩토리가
 * 호이스팅되어 파일 상단의 값을 가져다 쓸 수 없기 때문이다.
 */
type FakeMapRecord = { remove: ReturnType<typeof vi.fn> }
const mapsCreated = (): FakeMapRecord[] =>
  ((globalThis as { __fleetMaps?: FakeMapRecord[] }).__fleetMaps ??= [])

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
    constructor() {
      const registry = (globalThis as { __fleetMaps?: unknown[] })
      registry.__fleetMaps ??= []
      registry.__fleetMaps.push(this)
    }
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

  it('기본 캡션은 점선이 육지를 가로지른다는 것과 굵은 테두리의 뜻을 둘 다 말한다 (#1421)', () => {
    const { container } = render(<FleetMap vessels={[vessel('1', '35.1', '129.0')]} />)

    const hint = container.querySelector('.fleetmap__hint')?.textContent ?? ''
    // 점선이 실제 항로가 아닌 **이유**
    expect(hint).toMatch(/육지/)
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
