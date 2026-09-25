// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { loadHarborRenderer } from './harborRenderer'

const spies = vi.hoisted(() => ({ geometryDispose: vi.fn(), materialDispose: vi.fn(), rendererDispose: vi.fn(), contextLoss: vi.fn(), controlsDispose: vi.fn(), observerDisconnect: vi.fn() }))

vi.mock('three', () => {
  class Vector3 { x: number; y: number; z: number; constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z } }
  class Object3D {
    children: Object3D[] = []
    position = { x: 0, y: 0, z: 0, set(x: number, y: number, z: number) { this.x = x; this.y = y; this.z = z } }
    rotation = { x: 0 }
    add(child: Object3D) { this.children.push(child) }
    traverse(callback: (object: Object3D) => void) { callback(this); this.children.forEach((child) => child.traverse(callback)) }
  }
  class Scene extends Object3D { background: unknown }
  class Geometry { dispose = spies.geometryDispose; setFromPoints() { return this } }
  class Material { dispose = spies.materialDispose }
  class Mesh extends Object3D { geometry: Geometry; material: Material; constructor(geometry: Geometry, material: Material) { super(); this.geometry = geometry; this.material = material } }
  class PerspectiveCamera extends Object3D { aspect = 1; lookAt() {}; updateProjectionMatrix() {} }
  class WebGLRenderer { domElement = document.createElement('canvas'); setPixelRatio() {}; setSize() {}; render() {}; dispose = spies.rendererDispose; forceContextLoss = spies.contextLoss }
  return { Vector3, Scene, Group: Object3D, Mesh, PerspectiveCamera, WebGLRenderer, BoxGeometry: Geometry, PlaneGeometry: Geometry, BufferGeometry: Geometry, MeshStandardMaterial: Material, LineBasicMaterial: Material, Line: Mesh, HemisphereLight: Object3D, Color: class {}, Texture: class {} }
})

vi.mock('three/addons/controls/OrbitControls.js', () => ({
  OrbitControls: class { enableDamping = false; object: unknown; constructor(object: unknown) { this.object = object } addEventListener() {}; update() {}; dispose = spies.controlsDispose },
}))
vi.mock('./quality', () => ({
  mapQualityPolicy: () => ({ tier: 'high', globe: true, harbor3d: true, pixelRatioCap: 2, buildingStride: 1, animate: true, reason: null }),
}))

class FakeResizeObserver {
  private readonly callback: () => void
  constructor(callback: () => void) { this.callback = callback }
  observe() { this.callback() }
  disconnect = spies.observerDisconnect
}

const DATA = {
  metadata: { attribution: '© OpenStreetMap contributors', bbox: [129, 35, 130, 36] },
  buildings: [{ coordinates: [[129, 35], [129.1, 35], [129.1, 35.1]], heightMeters: 20 }],
  roads: [{ coordinates: [[129, 35], [129.2, 35.2]] }],
}

beforeEach(() => {
  Object.values(spies).forEach((spy) => spy.mockClear())
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(DATA), { status: 200 })))
})

describe('Harbor renderer lazy product boundary', () => {
  it('iframe 없이 Three scene과 한계·저작자 표시를 마운트한다', async () => {
    const target = document.createElement('div')
    const emit = vi.fn()
    const renderer = await loadHarborRenderer()
    const session = renderer.mount(target, { mode: 'playback', port: 'busan' }, emit)
    await vi.waitFor(() => expect(emit).toHaveBeenCalledWith({ type: 'ready' }))
    expect(target.querySelector('iframe')).toBeNull()
    expect(target.querySelector('canvas')).not.toBeNull()
    expect(target.textContent).toMatch(/OpenStreetMap.*접안 위치.*수심.*항해 가능성/)
    expect(target.getAttribute('aria-label')).toContain('부산 북항')
    session.destroy()
  })

  it('port update와 destroy가 이전 scene 자원을 정리한다', async () => {
    const target = document.createElement('div')
    const renderer = await loadHarborRenderer()
    const session = renderer.mount(target, { mode: 'playback', port: 'busan' }, () => undefined)
    await vi.waitFor(() => expect(target.querySelector('canvas')).not.toBeNull())
    session.update({ mode: 'playback', port: 'singapore' })
    await vi.waitFor(() => expect(target.getAttribute('aria-label')).toContain('싱가포르'))
    expect(spies.rendererDispose).toHaveBeenCalled()
    expect(spies.contextLoss).toHaveBeenCalled()
    expect(spies.geometryDispose).toHaveBeenCalled()
    expect(spies.materialDispose).toHaveBeenCalled()
    expect(spies.controlsDispose).toHaveBeenCalled()
    expect(spies.observerDisconnect).toHaveBeenCalled()
    session.destroy()
    expect(target.childElementCount).toBe(0)
  })

  it('reduced motion에서는 animation frame을 만들지 않는다', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
    const renderer = await loadHarborRenderer()
    const target = document.createElement('div')
    renderer.mount(target, { mode: 'playback', port: 'busan' }, () => undefined)
    await vi.waitFor(() => expect(target.querySelector('canvas')).not.toBeNull())
    expect(requestAnimationFrame).not.toHaveBeenCalled()
  })
})
