import { routeGeometryAtProgress, type RouteCoordinate, type RouteGeometry } from '../../map/routeGeometry'
import type { SimulationPlaybackState } from './playbackController'
import { createSimulationPlaybackController, type SimulationPlaybackController } from './playbackController'

export interface VoyageSequenceInput {
  readonly snapshotVoyageId: string
  readonly snapshotIndex: number
  readonly route?: RouteGeometry | null
  /** 시각화용 상대 재생 길이. 실제 항해 시간으로 저장하거나 표시하지 않는다. */
  readonly playbackDurationMs?: number | null
  readonly startedAt?: string | null
  readonly endedAt?: string | null
}

type VoyageBoundaryRelation = 'first' | 'contiguous' | 'gap' | 'overlap' | 'unknown'

interface VoyageSequenceSegment {
  readonly snapshotVoyageId: string
  readonly route: RouteGeometry
  readonly startMs: number
  readonly endMs: number
  readonly durationMs: number
  readonly relationToPrevious: VoyageBoundaryRelation
}

type VoyageSequence =
  | {
      readonly status: 'unavailable'
      readonly reason: 'coordinates_not_provided'
      readonly skippedVoyageIds: readonly string[]
    }
  | {
      readonly status: 'available'
      readonly order: 'timestamp' | 'snapshot'
      readonly durationMs: number
      readonly segments: readonly VoyageSequenceSegment[]
      readonly skippedVoyageIds: readonly string[]
    }

interface VoyageSequencePosition {
  readonly snapshotVoyageId: string
  readonly segmentIndex: number
  readonly segmentProgress: number
  readonly timelineProgress: number
  readonly timeMs: number
  readonly position: RouteCoordinate
  readonly traveledCoordinates: readonly RouteCoordinate[]
  readonly bearing: number
}

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

function relation(previous: VoyageSequenceInput | undefined, current: VoyageSequenceInput): VoyageBoundaryRelation {
  if (!previous) return 'first'
  const previousEnd = timestamp(previous.endedAt)
  const currentStart = timestamp(current.startedAt)
  if (previousEnd === null || currentStart === null) return 'unknown'
  if (currentStart > previousEnd) return 'gap'
  if (currentStart < previousEnd) return 'overlap'
  return 'contiguous'
}

/** 스냅샷 항차를 실제 시간 추정 없이 하나의 시각화 전용 상대 timeline으로 만든다. */
export function createVoyageSequence(inputs: readonly VoyageSequenceInput[]): VoyageSequence {
  const skippedVoyageIds: string[] = []
  const usable = inputs.filter((input) => {
    const usableRoute = input.route !== null && input.route !== undefined && input.route.coordinates.length >= 2
    const usableDuration = input.playbackDurationMs !== null && input.playbackDurationMs !== undefined
      && Number.isFinite(input.playbackDurationMs) && input.playbackDurationMs > 0
    if (!usableRoute || !usableDuration) skippedVoyageIds.push(input.snapshotVoyageId)
    return usableRoute && usableDuration
  })
  if (usable.length === 0) return { status: 'unavailable', reason: 'coordinates_not_provided', skippedVoyageIds }

  const allTimestamped = usable.every((input) => timestamp(input.startedAt) !== null)
  const ordered = [...usable].sort((left, right) => {
    if (allTimestamped) {
      const difference = timestamp(left.startedAt)! - timestamp(right.startedAt)!
      if (difference !== 0) return difference
    }
    return left.snapshotIndex - right.snapshotIndex || left.snapshotVoyageId.localeCompare(right.snapshotVoyageId)
  })
  let cursor = 0
  const segments = ordered.map((input, index): VoyageSequenceSegment => {
    const durationMs = input.playbackDurationMs!
    const segment = {
      snapshotVoyageId: input.snapshotVoyageId,
      route: input.route!,
      startMs: cursor,
      endMs: cursor + durationMs,
      durationMs,
      relationToPrevious: relation(ordered[index - 1], input),
    }
    cursor = segment.endMs
    return segment
  })
  return {
    status: 'available', order: allTimestamped ? 'timestamp' : 'snapshot',
    durationMs: cursor, segments, skippedVoyageIds,
  }
}

/** #1444 controller의 time snapshot을 현재 항차·위치·구간 progress로 즉시 투영한다. */
export function voyageSequenceAtTime(
  sequence: VoyageSequence,
  playback: number | Extract<SimulationPlaybackState, { readonly status: 'available' }>,
): VoyageSequencePosition | null {
  if (sequence.status === 'unavailable') return null
  const requested = typeof playback === 'number' ? playback : playback.timeMs
  if (!Number.isFinite(requested)) return null
  const timeMs = Math.min(sequence.durationMs, Math.max(0, requested))
  const segmentIndex = timeMs === sequence.durationMs
    ? sequence.segments.length - 1
    : sequence.segments.findIndex(({ endMs }) => timeMs < endMs)
  const segment = sequence.segments[segmentIndex]
  const segmentProgress = (timeMs - segment.startMs) / segment.durationMs
  const geometry = routeGeometryAtProgress(segment.route.coordinates, segmentProgress)
  return {
    snapshotVoyageId: segment.snapshotVoyageId, segmentIndex, segmentProgress,
    timelineProgress: timeMs / sequence.durationMs, timeMs,
    position: geometry.position, traveledCoordinates: geometry.traveledCoordinates,
    bearing: geometry.bearing,
  }
}

/** #1444 controller의 clock을 유지하면서 #1445 다중 항차 위치로 투영한다. */
export function createVoyageSequencePlaybackController(sequence: VoyageSequence): SimulationPlaybackController {
  if (sequence.status === 'unavailable') {
    return createSimulationPlaybackController({ coordinates: null, durationMs: 1 })
  }
  const timeline = createSimulationPlaybackController({ coordinates: [[0, 0], [1, 0]], durationMs: sequence.durationMs })
  const project = (state: SimulationPlaybackState): SimulationPlaybackState => {
    if (state.status === 'unavailable') return state
    const position = voyageSequenceAtTime(sequence, state)
    if (!position) return { status: 'unavailable', reason: 'coordinates_not_provided' }
    const segment = sequence.segments[position.segmentIndex]
    return {
      ...state,
      position: position.position,
      traveledCoordinates: position.traveledCoordinates,
      activeRouteCoordinates: segment.route.coordinates,
      activeRouteProgress: position.segmentProgress,
      activeRouteBearing: position.bearing,
    }
  }
  return {
    getState: () => project(timeline.getState()),
    subscribe(listener) { return timeline.subscribe((state) => listener(project(state))) },
    play: () => timeline.play(), pause: () => timeline.pause(), seek: (time) => timeline.seek(time),
    reset: () => timeline.reset(), restart: () => timeline.restart(), setSpeed: (speed) => timeline.setSpeed(speed),
    destroy: () => timeline.destroy(),
  }
}
