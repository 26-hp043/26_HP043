// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const disposed = vi.hoisted(() => ({ geometry: vi.fn(), material: vi.fn(), renderer: vi.fn(), render: vi.fn(), add: vi.fn() }))
vi.mock('three', () => {
  class VectorLike { set = vi.fn() }
  class Scene { add = disposed.add; remove = vi.fn() }
  class Mesh {
    position = new VectorLike()
    scale = new VectorLike()
    rotation = new VectorLike()
    constructor(_geometry: unknown, _material: unknown) {}
  }
  return {
    Scene, Mesh, Camera: class { projectionMatrix = { fromArray: vi.fn() } }, HemisphereLight: class {},
    // 화면 좌표에 그리므로 정사영 카메라다 (`#1917`).
    OrthographicCamera: class {
      left = 0; right = 1; top = 0; bottom = 1
      updateProjectionMatrix = vi.fn()
    },
    DirectionalLight: class { position = new VectorLike() },
    ConeGeometry: class { dispose = disposed.geometry },
    CylinderGeometry: class {
      dispose = disposed.geometry
      rotateX = vi.fn()
      scale = vi.fn()
      constructor(..._args: number[]) {}
    },
    // 선체는 저장소 소유 정점 배열이다 (`#1917` · `vesselGeometry.ts`). 형상 자체는
    // 그 파일의 검사가 보고, 여기서는 layer가 버퍼를 만들고 버리는 흐름만 본다.
    BufferGeometry: class {
      setAttribute = vi.fn()
      computeVertexNormals = vi.fn()
      dispose = disposed.geometry
    },
    BufferAttribute: class { constructor(_array: unknown, _itemSize: number) {} },
    // 배는 부품 여럿을 담은 Group이다 (`#1935` · `vesselParts.ts`) — 실험이 쓰던 방식이다.
    Group: class {
      position = new VectorLike()
      scale = new VectorLike()
      rotation = new VectorLike()
      visible = true
      add = vi.fn()
    },
    BoxGeometry: class { dispose = disposed.geometry; constructor(..._args: number[]) {} },
    MeshStandardMaterial: class {
      color = { setStyle: vi.fn() }
      dispose = disposed.material
    },
    MeshBasicMaterial: class { dispose = disposed.material },
    WebGLRenderer: class { autoClear = true; resetState = vi.fn(); render = disposed.render; dispose = disposed.renderer },
    DoubleSide: 2,
    MathUtils: { degToRad: (degree: number) => degree * Math.PI / 180 },
  }
})
vi.mock('maplibre-gl', () => ({
  MercatorCoordinate: { fromLngLat: () => ({ x: 0.5, y: 0.5, z: 0, meterInMercatorCoordinateUnits: () => 0.001 }) },
}))

const { createGlobeVesselLayer } = await import('./vesselLayer')

describe('Three 선박 custom layer', () => {
  beforeEach(() => { for (const mock of Object.values(disposed)) mock.mockClear() })

  it.each(['fleet', 'comparison', 'playback'] as const)('%s mode가 같은 lifecycle을 사용한다', (mode) => {
    /*
     * 배는 **지도 위에 얹은 our 캔버스**에 그린다 (`#1917`).
     *
     * MapLibre의 GL 컨텍스트를 공유하던 종전 방식은 layer가 붙고 `render()`가 돌아도
     * 화면에 아무것도 나오지 않았다(globe·mercator 모두 실측). 그래서 여기서 보는 것은
     * ⑴ 캔버스를 지도 컨테이너에 붙이는가 ⑵ 지도의 `render`마다 함께 그리는가
     * ⑶ 자리를 `map.project()`로 잡는가 ⑷ 버릴 때 캔버스와 GPU 자원을 되돌리는가다.
     */
    const project = vi.fn(() => ({ x: 120, y: 80 }))
    const handlers = new Map<string, () => void>()
    const container = document.createElement('div')
    const fakeMap = {
      project,
      getBearing: () => 0,
      getPitch: () => 18,
      getCanvas: () => ({ width: 800, height: 500, clientWidth: 400, clientHeight: 250 }),
      getCanvasContainer: () => container,
      on: (event: string, handler: () => void) => { handlers.set(event, handler) },
      off: (event: string) => { handlers.delete(event) },
    }

    const controller = createGlobeVesselLayer(fakeMap as never, {
      mode, vessels: [{ id: 'ship', coordinate: [129, 35], heading: 90 }],
    })

    expect(container.querySelector('canvas.fleetmap__vessels')).not.toBeNull()
    expect(handlers.has('render')).toBe(true)
    expect(project).toHaveBeenCalled()
    expect(disposed.render).toHaveBeenCalled()

    // 지도가 다시 그리면 자리를 다시 잡는다 — 관성 이동 중에 배가 미끄러지지 않는다.
    project.mockClear()
    handlers.get('render')?.()
    expect(project).toHaveBeenCalled()

    controller.update({ mode, vessels: [{ id: 'ship', coordinate: [130, 36], heading: 180 }] })
    controller.destroy()

    expect(container.querySelector('canvas.fleetmap__vessels')).toBeNull()
    expect(handlers.has('render')).toBe(false)
    expect(disposed.geometry).toHaveBeenCalled()
    expect(disposed.material).toHaveBeenCalled()
    expect(disposed.renderer).toHaveBeenCalled()
  })
})

/**
 * 지구 반대편 선박을 숨긴다 (`#1937`).
 *
 * 지구본을 돌리면 **반대편 배가 그대로 보였다** — `map.project()`가 구 뒷면의 점도 화면
 * 좌표를 돌려주는데, 그리는 쪽에 앞뒤 판정이 없었다. 여기서 보는 것은 ⑴ MapLibre의
 * 판정을 쓰는가 ⑵ 가려지면 **그리지 않는가**다.
 */
describe('지구 반대편 가림', () => {
  const baseMap = (extra: Record<string, unknown> = {}) => ({
    project: vi.fn(() => ({ x: 120, y: 80 })),
    getBearing: () => 0,
    getPitch: () => 18,
    getCenter: () => ({ lng: 129, lat: 35 }),
    getCanvas: () => ({ width: 800, height: 500, clientWidth: 400, clientHeight: 250 }),
    getCanvasContainer: () => document.createElement('div'),
    on: vi.fn(),
    off: vi.fn(),
    ...extra,
  })

  it('MapLibre가 가렸다고 하면 그리지 않는다', () => {
    const isLocationOccluded = vi.fn(() => true)
    const fakeMap = baseMap({ transform: { isLocationOccluded } })
    const controller = createGlobeVesselLayer(fakeMap as never, {
      mode: 'fleet', vessels: [{ id: 'ship', coordinate: [-51, -35], heading: 0 }],
    })
    expect(isLocationOccluded).toHaveBeenCalled()
    // 가려진 배의 자리는 묻지 않는다 — 그릴 일이 없다.
    expect(fakeMap.project).not.toHaveBeenCalled()
    controller.destroy()
  })

  it('앞면이면 자리를 잡아 그린다', () => {
    const fakeMap = baseMap({ transform: { isLocationOccluded: () => false } })
    const controller = createGlobeVesselLayer(fakeMap as never, {
      mode: 'fleet', vessels: [{ id: 'ship', coordinate: [129, 35], heading: 0 }],
    })
    expect(fakeMap.project).toHaveBeenCalled()
    controller.destroy()
  })

  it('MapLibre 판정이 없으면 각거리로 가른다', () => {
    // 내부 구현에 기대지 않는다 — 없거나 바뀌어도 반대편 배가 되살아나지 않아야 한다.
    const fakeMap = baseMap()
    const controller = createGlobeVesselLayer(fakeMap as never, {
      mode: 'fleet', vessels: [{ id: 'ship', coordinate: [-51, -35], heading: 0 }],
    })
    expect(fakeMap.project).not.toHaveBeenCalled()
    controller.destroy()
  })
})

