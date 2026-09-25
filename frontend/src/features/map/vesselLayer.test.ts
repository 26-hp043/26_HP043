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
    ConeGeometry: class { dispose = disposed.geometry },
    MeshStandardMaterial: class { dispose = disposed.material },
    MeshBasicMaterial: class { dispose = disposed.material },
    WebGLRenderer: class { autoClear = true; resetState = vi.fn(); render = disposed.render; dispose = disposed.renderer },
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
    const controller = createGlobeVesselLayer({ mode, vessels: [{ id: 'ship', coordinate: [129, 35], heading: 90 }] })
    const triggerRepaint = vi.fn()
    const gl = { canvas: document.createElement('canvas') } as unknown as WebGL2RenderingContext
    controller.layer.onAdd?.({ triggerRepaint } as never, gl)
    controller.layer.render(gl, { modelViewProjectionMatrix: new Float32Array(16) } as never)
    controller.update({ mode, vessels: [{ id: 'ship', coordinate: [130, 36], heading: 180 }] })
    controller.layer.onRemove?.({} as never, gl)
    expect(disposed.render).toHaveBeenCalled()
    // light 외에 전달한 vessel mesh가 scene에 추가된다.
    expect(disposed.add.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(disposed.geometry).toHaveBeenCalledTimes(2)
    expect(disposed.material).toHaveBeenCalledTimes(2)
    expect(disposed.renderer).toHaveBeenCalledOnce()
  })
})
