// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const maps = vi.hoisted(() => [] as Array<Record<string, ReturnType<typeof vi.fn>>>)
const markerRecords = vi.hoisted(() => [] as Array<{ element: HTMLElement; remove: ReturnType<typeof vi.fn> }>)
const boundsCoordinates = vi.hoisted(() => [] as Array<readonly [number, number]>)
const resizeCallbacks = vi.hoisted(() => [] as Array<() => void>)
const projectionFailure = vi.hoisted(() => ({ enabled: false }))
vi.mock('maplibre-gl', () => {
  class Map {
    touchZoomRotate = { disableRotation: vi.fn() }
    addControl = vi.fn()
    on = vi.fn()
    getSource = vi.fn().mockReturnValue(undefined)
    getLayer = vi.fn().mockReturnValue(undefined)
    addSource = vi.fn()
    addLayer = vi.fn()
    setProjection = vi.fn(() => {
      if (projectionFailure.enabled) throw new Error('globe unavailable')
      return this
    })
    getZoom = vi.fn().mockReturnValue(2)
    fitBounds = vi.fn()
    project = vi.fn().mockReturnValue({ x: 2, y: 20 })
    resize = vi.fn().mockReturnThis()
    remove = vi.fn()
    constructor() { maps.push(this as unknown as Record<string, ReturnType<typeof vi.fn>>) }
  }
  class Marker {
    setLngLat = vi.fn().mockReturnThis()
    addTo = vi.fn().mockReturnThis()
    remove = vi.fn()
    constructor(options: { element: HTMLElement }) { markerRecords.push({ element: options.element, remove: this.remove }) }
  }
  return {
    Map, Marker,
    LngLatBounds: class { extend = vi.fn((coordinate: readonly [number, number]) => { boundsCoordinates.push(coordinate) }) },
    NavigationControl: class {}, addProtocol: vi.fn(),
  }
})
vi.mock('pmtiles', () => ({ Protocol: class { tile = vi.fn() } }))
vi.mock('@protomaps/basemaps', () => ({ layers: () => [], namedFlavor: () => ({}) }))

const { mapLibreRenderer } = await import('./mapLibreRenderer')
const data = { type: 'FeatureCollection' as const, features: [] }
const model = (mode: 'fleet' | 'comparison') => ({
  mode, markers: [], routes: { data, attribution: 'source', bounds: [[129, 35] as const] },
  ports: [], qualityTier: 'high' as const,
})

describe('MapLibre renderer adapter', () => {
  beforeEach(() => {
    maps.length = 0
    markerRecords.length = 0
    boundsCoordinates.length = 0
    resizeCallbacks.length = 0
    projectionFailure.enabled = false
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resizeCallbacks.push(callback) }
      observe() {}
      disconnect() {}
    })
  })

  it.each(['fleet', 'comparison'] as const)('%s mode를 mount/update/destroy한다', (mode) => {
    const emit = vi.fn()
    const session = mapLibreRenderer.mount(document.createElement('div'), model(mode), emit)
    const map = maps[0]
    const load = map.on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    load()
    expect(emit).toHaveBeenCalledWith({ type: 'ready' })
    expect(map.addLayer).toHaveBeenCalledTimes(2)
    expect(map.setProjection).toHaveBeenCalledWith({ type: 'globe' })

    session.update(model(mode))
    session.destroy()
    expect(map.remove).toHaveBeenCalledTimes(1)
  })

  it('날짜변경선 bounds·모바일 padding·resize를 globe camera에 반영한다', () => {
    const target = document.createElement('div')
    Object.defineProperty(target, 'clientWidth', { value: 390 })
    const globeModel = {
      ...model('fleet'),
      routes: { ...model('fleet').routes, bounds: [[179, 20], [-179, 21]] as const },
    }
    const session = mapLibreRenderer.mount(target, globeModel, vi.fn())
    const map = maps[0]
    const load = map.on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    load()

    expect(Math.abs(boundsCoordinates[1][0] - boundsCoordinates[0][0])).toBe(2)
    expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ padding: 24 }))
    resizeCallbacks[0]()
    expect(map.resize).toHaveBeenCalledTimes(1)
    session.destroy()
  })

  it('MapLibre 오류를 renderer-neutral error event로 전달한다', () => {
    const emit = vi.fn()
    mapLibreRenderer.mount(document.createElement('div'), model('fleet'), emit)
    const error = new Error('render failed')
    const handler = maps[0].on.mock.calls.find(([name]) => name === 'error')?.[1] as (event: { error: Error }) => void
    handler({ error })
    expect(emit).toHaveBeenCalledWith({ type: 'error', error })
  })

  it('globe projection만 실패하면 Mercator map을 유지한다', () => {
    projectionFailure.enabled = true
    const emit = vi.fn()
    const session = mapLibreRenderer.mount(document.createElement('div'), model('fleet'), emit)
    const load = maps[0].on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    load()
    expect(emit).toHaveBeenCalledWith({ type: 'ready' })
    expect(maps[0].remove).not.toHaveBeenCalled()
    session.destroy()
  })

  it('항만 역할·edge label을 표시하고 destroy 때 marker를 정리한다', () => {
    const target = document.createElement('div')
    Object.defineProperty(target, 'clientWidth', { value: 400 })
    const port = { id: 'KRPUS', role: 'destination' as const, label: '부산', coordinate: [129, 35] as const }
    const session = mapLibreRenderer.mount(target, { ...model('fleet'), ports: [port] }, vi.fn())
    const load = maps[0].on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    load()

    expect(markerRecords[0].element.getAttribute('aria-label')).toContain('도착항')
    expect(markerRecords[0].element.dataset.placement).toBe('start')
    session.destroy()
    expect(markerRecords[0].remove).toHaveBeenCalledTimes(1)
  })
})
