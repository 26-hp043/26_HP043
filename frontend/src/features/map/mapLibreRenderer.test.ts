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
    // #1831 — 「이 배를 보여 달라」가 쓰는 둘. `once`는 멈춘 뒤에 알리기 위한 것이다.
    once = vi.fn()
    easeTo = vi.fn().mockReturnThis()
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
    // 워커 주소 고정 (`#1909`) — 어댑터가 지도를 만들기 전에 부른다.
    setWorkerUrl: vi.fn(),
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

  /**
   * 「이 배를 보여 달라」 (#1831).
   *
   * 좌측 패널의 행에서 배를 고르면 지도가 그 배로 옮겨 간 **뒤** 카드가 열려야 한다 —
   * 화면 밖의 마커에 카드만 뜨면 무엇에 붙은 카드인지 알 수 없다. 그래서 옮기는 것과
   * 「열어라」를 한 길로 묶는다: 모델의 `focus`가 바뀌면 옮기고, **멈춘 뒤** `selection`을
   * 낸다. 마커를 직접 누른 경우도 같은 `selection`으로 들어오므로 **두 입구가 한 길**이다.
   *
   * ⚠️ **멈추기 전에 알리면 안 된다.** 마커 DOM의 자리는 지도가 움직임을 반영한 뒤라야
   * 제 값이고, 그 전에 재면 카드가 옛 자리에 붙는다.
   */
  it('focus가 바뀌면 그 좌표로 옮기고, 멈춘 뒤에 selection을 낸다 (#1831)', () => {
    const emit = vi.fn()
    const base = model('fleet')
    const session = mapLibreRenderer.mount(document.createElement('div'), base, emit)
    const map = maps[0]
    const load = map.on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    load()
    emit.mockClear()

    session.update({ ...base, focus: { id: 'v1', coordinate: [129, 35] as const, nonce: 1 } })
    expect(map.easeTo).toHaveBeenCalledWith({ center: [129, 35], animate: false })
    expect(emit).not.toHaveBeenCalledWith({ type: 'selection', id: 'v1' })

    const moveend = map.once.mock.calls.find(([name]) => name === 'moveend')?.[1] as () => void
    moveend()
    expect(emit).toHaveBeenCalledWith({ type: 'selection', id: 'v1' })
    session.destroy()
  })

  /**
   * 같은 배를 **다시** 눌러도 열려야 하므로 `nonce`가 신호다 — id만 보면 두 번째 누름이
   * 아무 일도 하지 않는다. 반대로 같은 `nonce`로 모델이 다시 와도(다른 이유로 갱신될 때)
   * 지도가 다시 튀어서는 안 된다.
   */
  it('같은 nonce로 모델이 다시 오면 옮기지 않는다 (#1831)', () => {
    const emit = vi.fn()
    const base = model('fleet')
    const focus = { id: 'v1', coordinate: [129, 35] as const, nonce: 7 }
    const session = mapLibreRenderer.mount(document.createElement('div'), base, emit)
    const map = maps[0]
    const load = map.on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    load()

    session.update({ ...base, focus })
    expect(map.easeTo).toHaveBeenCalledTimes(1)
    session.update({ ...base, focus, ports: [] })
    expect(map.easeTo).toHaveBeenCalledTimes(1)

    session.update({ ...base, focus: { ...focus, nonce: 8 } })
    expect(map.easeTo).toHaveBeenCalledTimes(2)
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
