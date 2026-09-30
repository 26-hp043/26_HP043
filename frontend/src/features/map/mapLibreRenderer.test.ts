// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const maps = vi.hoisted(() => [] as Array<Record<string, ReturnType<typeof vi.fn>>>)
const markerRecords = vi.hoisted(() => [] as Array<{ element: HTMLElement; remove: ReturnType<typeof vi.fn> }>)
const boundsCoordinates = vi.hoisted(() => [] as Array<readonly [number, number]>)
const resizeCallbacks = vi.hoisted(() => [] as Array<() => void>)
const projectionFailure = vi.hoisted(() => ({ enabled: false }))
const mapOptions = vi.hoisted(() => [] as Array<Record<string, unknown>>)
const vesselLayers = vi.hoisted(() => ({ created: 0, destroy: [] as Array<ReturnType<typeof import('vitest')['vi']['fn']>> }))
vi.mock('./vesselLayer', () => ({
  createGlobeVesselLayer: () => {
    vesselLayers.created += 1
    const destroy = vi.fn()
    vesselLayers.destroy.push(destroy)
    return { update: vi.fn(), destroy }
  },
}))
vi.mock('maplibre-gl', () => {
  class Map {
    touchZoomRotate = { disableRotation: vi.fn(), enableRotation: vi.fn() }
    dragRotate = { enable: vi.fn(), disable: vi.fn() }
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
    constructor(options: Record<string, unknown> = {}) {
      maps.push(this as unknown as Record<string, ReturnType<typeof vi.fn>>)
      mapOptions.push(options)
    }
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
const { projectionToggleText } = await import('./projectionToggle')
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
    mapOptions.length = 0
    vesselLayers.created = 0
    vesselLayers.destroy.length = 0
    window.localStorage.removeItem('bluelog.map.projection')
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
    /*
     * `#2051`에서 패딩이 **변마다** 갈렸다. 모바일 값 24는 그대로이고, 덮는
     * 오버레이가 없으므로 네 변이 모두 같다 — 왼쪽만 오버레이만큼 더 밀린다.
     */
    expect(map.fitBounds).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ padding: { top: 24, bottom: 24, right: 24, left: 24 } }),
    )
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

  /**
   * 지구본 ↔ 평면 전환 (#1976 · 09-27 사용자 결정).
   *
   * ⑴ `low`가 아니면 버튼이 있고 처음은 지구본 ⑵ 누르면 투영과 함께 기울기·회전·3D 선체가
   * 따라 바뀐다 ⑶ 고른 방식을 기억해 다음에 그 방식으로 연다 ⑷ `low`에는 버튼이 없다.
   */
  const toggleOf = (map: Record<string, ReturnType<typeof vi.fn>>) => {
    const control = map.addControl.mock.calls
      .map(([c]) => c as { onAdd?: () => HTMLElement })
      .find((c) => typeof c.onAdd === 'function' && c.constructor.name === 'ProjectionToggleControl')
    const element = control?.onAdd?.()
    return element?.querySelector('button') ?? null
  }
  const fireLoad = (map: Record<string, ReturnType<typeof vi.fn>>) => {
    const load = map.on.mock.calls.find(([name]) => name === 'load')
    if (!load) throw new Error('load 처리기가 등록되지 않았다')
    ;(load[1] as () => void)()
  }
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

  it('버튼이 있고 처음은 지구본 — 누르면 평면으로, 다시 누르면 지구본으로 (#1976)', () => {
    const session = mapLibreRenderer.mount(document.createElement('div'), model('fleet'), vi.fn())
    const map = maps[0]
    expect(mapOptions[0]).toMatchObject({ pitch: 18, dragRotate: true })
    fireLoad(map)
    expect(map.setProjection).toHaveBeenLastCalledWith({ type: 'globe' })
    const button = toggleOf(map)!
    /*
     * 문구는 **표시 문구**라 리터럴로 적지 않는다(`AGENTS §4.6` · `#1992`) — `#1940` ⑥에서
     * 디자인 확정을 기다리는 중이라 바뀔 수 있다. 지키려는 것은 「**누르면 무엇이 되는가**를
     * 말한다」이므로, 문구를 만드는 함수에서 기대값을 가져온다.
     */
    const globeLabel = button.getAttribute('aria-label')
    expect(globeLabel).toBe(projectionToggleText('globe').name)

    button.click()
    expect(map.setProjection).toHaveBeenLastCalledWith({ type: 'mercator' })
    expect((map.dragRotate as unknown as { disable: ReturnType<typeof vi.fn> }).disable).toHaveBeenCalled()
    expect(map.easeTo).toHaveBeenLastCalledWith({ pitch: 0, bearing: 0, animate: false })
    expect(window.localStorage.getItem('bluelog.map.projection')).toBe('mercator')
    const mercatorLabel = button.getAttribute('aria-label')
    expect(mercatorLabel).toBe(projectionToggleText('mercator').name)
    // 두 상태의 문구가 **서로 다르다** — 같으면 무엇이 되는지 알 수 없다.
    expect(mercatorLabel).not.toBe(globeLabel)

    button.click()
    expect(map.setProjection).toHaveBeenLastCalledWith({ type: 'globe' })
    expect(map.easeTo).toHaveBeenLastCalledWith({ pitch: 18, animate: false })
    expect(window.localStorage.getItem('bluelog.map.projection')).toBe('globe')
    // 두 번 누르면 처음 문구로 돌아온다.
    expect(button.getAttribute('aria-label')).toBe(globeLabel)
    session.destroy()
  })

  it('출처 컨트롤을 두지 않는다 — 출처는 지도 아래 펼친 한 줄이 맡는다 (#1853 ③)', () => {
    const session = mapLibreRenderer.mount(document.createElement('div'), model('fleet'), vi.fn())
    expect(mapOptions[0]).toMatchObject({ attributionControl: false })
    session.destroy()
  })

  it('고른 방식(평면)을 기억해 다음에는 평면으로 연다 (#1976)', () => {
    window.localStorage.setItem('bluelog.map.projection', 'mercator')
    const session = mapLibreRenderer.mount(document.createElement('div'), model('fleet'), vi.fn())
    const map = maps[0]
    expect(mapOptions[0]).toMatchObject({ pitch: 0, dragRotate: false })
    fireLoad(map)
    expect(map.setProjection).toHaveBeenLastCalledWith({ type: 'mercator' })
    expect(toggleOf(map)!.getAttribute('aria-label')).toBe(projectionToggleText('mercator').name)
    session.destroy()
  })

  it('low 기기에는 버튼이 없고 평면 그대로다 — 지금 판단을 지킨다 (#1976)', () => {
    window.localStorage.setItem('bluelog.map.projection', 'globe')
    const session = mapLibreRenderer.mount(document.createElement('div'), { ...model('fleet'), qualityTier: 'low' as const }, vi.fn())
    const map = maps[0]
    fireLoad(map)
    expect(toggleOf(map)).toBeNull()
    expect(map.setProjection).not.toHaveBeenCalled()
    expect(mapOptions[0]).toMatchObject({ pitch: 0 })
    session.destroy()
  })

  it('평면으로 바꾸면 3D 선체를 걷고, 지구본으로 오면 다시 올린다 (#1976)', async () => {
    const vessels = [{ id: 'v1' }] as unknown as NonNullable<Parameters<typeof mapLibreRenderer.mount>[1]['vessels']>
    const session = mapLibreRenderer.mount(document.createElement('div'), { ...model('fleet'), vessels }, vi.fn())
    const map = maps[0]
    fireLoad(map)
    await flush()
    expect(vesselLayers.created).toBe(1)

    const button = toggleOf(map)!
    button.click()
    expect(vesselLayers.destroy[0]).toHaveBeenCalledTimes(1)
    button.click()
    await flush()
    expect(vesselLayers.created).toBe(2)
    session.destroy()
  })

  it('선체를 불러오는 사이 평면으로 바꾸면 올리지 않는다 (#1976)', async () => {
    const vessels = [{ id: 'v1' }] as unknown as NonNullable<Parameters<typeof mapLibreRenderer.mount>[1]['vessels']>
    const session = mapLibreRenderer.mount(document.createElement('div'), { ...model('fleet'), vessels }, vi.fn())
    const map = maps[0]
    fireLoad(map)
    toggleOf(map)!.click()
    await flush()
    expect(vesselLayers.created).toBe(0)
    session.destroy()
  })
})

/**
 * 지도를 덮는 오버레이를 범위 계산이 센다 (#2051).
 *
 * ## 왜 사각형을 세워 두고 보나
 *
 * jsdom은 배치를 계산하지 않아 `getBoundingClientRect()`가 전부 0이다. 그래서 진짜
 * 겹침은 브라우저에서 재고(PR 본문의 실측), 여기서는 **규칙이 사각형을 어떻게
 * 읽는가**를 잠근다 — 세로로 겹치면 세고, 안 겹치면 세지 않고, 절반을 넘기지 않는다.
 */
describe('지도를 덮는 오버레이 (#2051)', () => {
  beforeEach(() => {
    /*
     * 위 `describe`의 `beforeEach`는 그 블록 안에서만 돈다. 여기서도 지도 기록을
     * 비우고, **앞 검사가 붙여 둔 오버레이를 걷는다** — 남으면 「덮는 것이 없으면」
     * 검사가 앞 검사의 패널을 보고 거짓 초록을 낸다.
     */
    maps.length = 0
    document.body.innerHTML = ''
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resizeCallbacks.push(callback) }
      observe() {}
      disconnect() {}
    })
  })

  function rect(box: { left: number; right: number; top: number; bottom: number }) {
    return () =>
      ({
        ...box,
        width: box.right - box.left,
        height: box.bottom - box.top,
        x: box.left,
        y: box.top,
        toJSON: () => box,
      }) as DOMRect
  }

  /** 1440 대시보드를 본뜬 자리 — 지도는 가로 1000, 패널은 왼쪽 위에 360이다. */
  function stage(panel: { left: number; right: number; top: number; bottom: number } | null) {
    const target = document.createElement('div')
    Object.defineProperty(target, 'clientWidth', { value: 1000 })
    target.getBoundingClientRect = rect({ left: 100, right: 1100, top: 50, bottom: 650 })
    document.body.append(target)
    if (panel) {
      const overlay = document.createElement('aside')
      overlay.setAttribute('data-map-overlay', '')
      overlay.getBoundingClientRect = rect(panel)
      document.body.append(overlay)
    }
    return target
  }

  function fitPadding(target: HTMLElement) {
    const session = mapLibreRenderer.mount(target, model('fleet'), vi.fn())
    const map = maps[0]
    const load = map.on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    load()
    const call = map.fitBounds.mock.calls[0]
    session.destroy()
    return call?.[1]?.padding as { top: number; bottom: number; left: number; right: number }
  }

  it('⚠️ 왼쪽 패딩이 패널을 센다 — 나머지 세 변은 그대로다', () => {
    /*
     * 패널 오른쪽 끝(476)에서 지도 왼쪽 끝(100)을 뺀 376이 가려진 띠이고,
     * 거기에 종전 간격 48을 더한다. 이 값이 없으면 선박이 패널 밑에 깔린다.
     */
    const padding = fitPadding(stage({ left: 116, right: 476, top: 66, bottom: 634 }))
    expect(padding.left).toBe(48 + 376)
    expect(padding.top).toBe(48)
    expect(padding.bottom).toBe(48)
    expect(padding.right).toBe(48)
  })

  it('덮는 것이 없으면 네 변이 종전 값이다', () => {
    expect(fitPadding(stage(null))).toEqual({ top: 48, bottom: 48, left: 48, right: 48 })
  })

  it('⚠️ 패널이 지도 **아래**로 내려가면 세지 않는다 (1100 이하)', () => {
    /*
     * 좁은 화면에서 패널은 지도 위가 아니라 아래에 선다. 세로로 겹치지 않는 것을
     * 보고 가른다 — 전환점 숫자를 여기 적으면 CSS가 바뀔 때 조용히 갈린다.
     */
    const padding = fitPadding(stage({ left: 116, right: 476, top: 700, bottom: 1000 }))
    expect(padding.left).toBe(48)
  })

  it('접힌 패널은 접힌 만큼만 센다', () => {
    // 접으면 버튼만 남는다(`.fleet__panel--closed`는 `inline-size: auto`).
    const padding = fitPadding(stage({ left: 116, right: 236, top: 66, bottom: 106 }))
    expect(padding.left).toBe(48 + 136)
  })

  it('⚠️ 가리는 폭이 지도의 절반을 넘지 못한다', () => {
    /*
     * 이 값이 잘못 커지면 `fitBounds`가 들어갈 자리를 잃고 지도가 엉뚱한 배율로
     * 튄다 — 뭉쳐 보이는 것보다 나쁜 고장이라 위쪽을 막아 둔다.
     */
    const padding = fitPadding(stage({ left: 116, right: 1090, top: 66, bottom: 634 }))
    expect(padding.left).toBe(48 + 500)
  })

  it('표시 이름은 지도가 갖는다 — 화면 클래스를 읽지 않는다', () => {
    /*
     * `.fleet__panel`을 여기서 읽으면 지도 어댑터가 대시보드를 아는 셈이 된다.
     * 덮는 쪽이 지도의 표시를 다는 방향이어야 `architecture.test.ts`와 어긋나지 않는다.
     */
    const overlay = document.createElement('aside')
    overlay.className = 'fleet__panel'
    overlay.getBoundingClientRect = rect({ left: 116, right: 476, top: 66, bottom: 634 })
    const target = stage(null)
    document.body.append(overlay)
    expect(fitPadding(target).left).toBe(48)
  })
})

/**
 * 데이터가 오기 전에 지도를 움직여도 한 번은 맞춘다 (#2051).
 *
 * ⚠️ 종전 조건은 `map.getZoom() === INITIAL_ZOOM`이라 **부동소수 정확 비교**였다.
 * 사용자가 항로가 오기 전에 지도를 한 번이라도 끌면 조건이 거짓이 되어 범위 맞추기가
 * 통째로 건너뛰어졌고, 그때는 초기 `center: [127, 30]` `zoom: 2`(인도~일본)에 남았다.
 */
describe('범위 맞추기가 도는 조건 (#2051)', () => {
  beforeEach(() => {
    /*
     * 위 `describe`의 `beforeEach`는 그 블록 안에서만 돈다. 여기서도 지도 기록을
     * 비우고, **앞 검사가 붙여 둔 오버레이를 걷는다** — 남으면 「덮는 것이 없으면」
     * 검사가 앞 검사의 패널을 보고 거짓 초록을 낸다.
     */
    maps.length = 0
    document.body.innerHTML = ''
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resizeCallbacks.push(callback) }
      observe() {}
      disconnect() {}
    })
  })

  function mount(bounds: readonly (readonly [number, number])[]) {
    const target = document.createElement('div')
    Object.defineProperty(target, 'clientWidth', { value: 1000 })
    const session = mapLibreRenderer.mount(
      target,
      { ...model('fleet'), routes: { ...model('fleet').routes, bounds } },
      vi.fn(),
    )
    const map = maps[0]
    const load = map.on.mock.calls.find(([name]) => name === 'load')?.[1] as () => void
    return { map, load, session, target }
  }

  it('⚠️ 줌이 움직여 있어도 한 번은 맞춘다', () => {
    const { map, load, session } = mount([])
    // 사용자가 데이터 전에 확대해 둔 상태.
    map.getZoom.mockReturnValue(4.000000000000001)
    load()
    expect(map.fitBounds).not.toHaveBeenCalled()

    // 항로가 이제 도착한다.
    session.update({ ...model('fleet'), routes: { ...model('fleet').routes, bounds: [[129, 35] as const] } })
    expect(map.fitBounds).toHaveBeenCalledTimes(1)
    session.destroy()
  })

  it('사용자가 지도를 직접 움직였으면 더는 끌어가지 않는다', () => {
    const { map, load, session } = mount([])
    load()
    const moveStart = map.on.mock.calls.find(([name]) => name === 'movestart')?.[1] as (
      event: { originalEvent?: unknown },
    ) => void
    expect(moveStart, 'movestart를 듣지 않습니다').toBeTypeOf('function')
    moveStart({ originalEvent: new MouseEvent('mousedown') })

    session.update({ ...model('fleet'), routes: { ...model('fleet').routes, bounds: [[129, 35] as const] } })
    expect(map.fitBounds).not.toHaveBeenCalled()
    session.destroy()
  })

  it('프로그램이 옮긴 이동은 사용자 조작으로 세지 않는다', () => {
    /*
     * `originalEvent`가 없는 `movestart`는 `easeTo`·`resize` 같은 내부 이동이다.
     * 그것까지 세면 늦게 온 항로가 영영 맞춰지지 않는다.
     */
    const { map, load, session } = mount([])
    load()
    const moveStart = map.on.mock.calls.find(([name]) => name === 'movestart')?.[1] as (
      event: { originalEvent?: unknown },
    ) => void
    moveStart({})

    session.update({ ...model('fleet'), routes: { ...model('fleet').routes, bounds: [[129, 35] as const] } })
    expect(map.fitBounds).toHaveBeenCalledTimes(1)
    session.destroy()
  })
})
