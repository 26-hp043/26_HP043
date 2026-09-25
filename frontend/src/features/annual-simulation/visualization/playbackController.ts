import { routeGeometryAtProgress, type RouteCoordinate } from '../../map/routeGeometry'

export type PlaybackSpeed = 0.5 | 1 | 2 | 4

export type SimulationPlaybackState =
  | { readonly status: 'unavailable'; readonly reason: 'coordinates_not_provided' }
  | {
      readonly status: 'available'
      readonly motion: 'playing' | 'paused'
      readonly timeMs: number
      readonly durationMs: number
      readonly progress: number
      readonly speed: PlaybackSpeed
      readonly position: RouteCoordinate
      readonly traveledCoordinates: readonly RouteCoordinate[]
      readonly activeRouteCoordinates: readonly RouteCoordinate[]
      readonly activeRouteProgress: number
      readonly activeRouteBearing: number
    }

interface PlaybackClock {
  now(): number
  requestFrame(callback: () => void): number
  cancelFrame(id: number): void
  isHidden(): boolean
  subscribeVisibility(callback: () => void): () => void
}

interface PlaybackControllerOptions {
  readonly coordinates?: readonly RouteCoordinate[] | null
  readonly durationMs: number
  readonly initialSpeed?: PlaybackSpeed
  readonly clock?: PlaybackClock
}

export interface SimulationPlaybackController {
  getState(): SimulationPlaybackState
  subscribe(listener: (state: SimulationPlaybackState) => void): () => void
  play(): void
  pause(): void
  seek(timeMs: number): void
  reset(): void
  restart(): void
  setSpeed(speed: PlaybackSpeed): void
  destroy(): void
}

function browserClock(): PlaybackClock {
  return {
    now: () => performance.now(),
    requestFrame: (callback) => requestAnimationFrame(callback),
    cancelFrame: (id) => cancelAnimationFrame(id),
    isHidden: () => document.visibilityState === 'hidden',
    subscribeVisibility: (callback) => {
      document.addEventListener('visibilitychange', callback)
      return () => document.removeEventListener('visibilitychange', callback)
    },
  }
}

/** API simulation time과 분리된 시각화 전용 playback state machine이다. */
export function createSimulationPlaybackController(options: PlaybackControllerOptions): SimulationPlaybackController {
  const coordinates = options.coordinates
  if (!coordinates || coordinates.length < 2) {
    const unavailable = { status: 'unavailable', reason: 'coordinates_not_provided' } as const
    return {
      getState: () => unavailable,
      subscribe: () => () => undefined,
      play: () => undefined,
      pause: () => undefined,
      seek: () => undefined,
      reset: () => undefined,
      restart: () => undefined,
      setSpeed: () => undefined,
      destroy: () => undefined,
    }
  }
  if (!Number.isFinite(options.durationMs) || options.durationMs <= 0) throw new Error('playback duration은 0보다 커야 합니다.')

  const clock = options.clock ?? browserClock()
  const durationMs = options.durationMs
  let speed = options.initialSpeed ?? 1
  let timeMs = 0
  let motion: 'playing' | 'paused' = 'paused'
  let anchorTime = 0
  let anchorWall = 0
  let hiddenAt: number | null = null
  let frame: number | null = null
  let destroyed = false
  const listeners = new Set<(state: SimulationPlaybackState) => void>()

  const state = (): SimulationPlaybackState => {
    const progress = timeMs / durationMs
    const geometry = routeGeometryAtProgress(coordinates, progress)
    return {
      status: 'available', motion, timeMs, durationMs, progress, speed,
      position: geometry.position, traveledCoordinates: geometry.traveledCoordinates,
      activeRouteCoordinates: coordinates, activeRouteProgress: progress,
      activeRouteBearing: geometry.bearing,
    }
  }
  const notify = () => {
    const snapshot = state()
    for (const listener of listeners) listener(snapshot)
  }
  const cancel = () => {
    if (frame !== null) clock.cancelFrame(frame)
    frame = null
  }
  const schedule = () => {
    if (!destroyed && motion === 'playing' && !clock.isHidden() && frame === null) frame = clock.requestFrame(tick)
  }
  const sync = () => {
    if (motion !== 'playing') return
    const effectiveNow = hiddenAt ?? clock.now()
    timeMs = Math.min(durationMs, anchorTime + (effectiveNow - anchorWall) * speed)
    if (timeMs === durationMs) motion = 'paused'
  }
  function tick() {
    frame = null
    if (destroyed || motion !== 'playing') return
    sync()
    notify()
    schedule()
  }
  const visibilityCleanup = clock.subscribeVisibility(() => {
    if (clock.isHidden()) {
      hiddenAt = clock.now()
      cancel()
      return
    }
    if (hiddenAt !== null) {
      anchorWall += clock.now() - hiddenAt
      hiddenAt = null
    }
    schedule()
  })
  const reanchor = () => {
    anchorTime = timeMs
    anchorWall = hiddenAt ?? clock.now()
  }

  return {
    getState: state,
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    play() {
      if (destroyed || motion === 'playing') return
      if (timeMs === durationMs) timeMs = 0
      motion = 'playing'
      reanchor()
      notify()
      schedule()
    },
    pause() {
      if (destroyed || motion === 'paused') return
      sync()
      motion = 'paused'
      cancel()
      notify()
    },
    seek(nextTimeMs) {
      if (destroyed || !Number.isFinite(nextTimeMs)) return
      timeMs = Math.min(durationMs, Math.max(0, nextTimeMs))
      reanchor()
      notify()
    },
    reset() {
      if (destroyed) return
      motion = 'paused'
      timeMs = 0
      cancel()
      reanchor()
      notify()
    },
    restart() {
      if (destroyed) return
      timeMs = 0
      motion = 'playing'
      reanchor()
      notify()
      schedule()
    },
    setSpeed(nextSpeed) {
      if (destroyed || speed === nextSpeed) return
      sync()
      speed = nextSpeed
      reanchor()
      notify()
    },
    destroy() {
      if (destroyed) return
      destroyed = true
      cancel()
      visibilityCleanup()
      listeners.clear()
    },
  }
}
