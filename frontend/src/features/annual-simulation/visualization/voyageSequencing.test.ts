// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { getKnownRouteSource } from '../../map/routeGeometry'
import { createVoyageSequence, createVoyageSequencePlaybackController, voyageSequenceAtTime, type VoyageSequenceInput } from './voyageSequencing'

const source = getKnownRouteSource('searoute/marnet')!
const route = (from: number, to: number) => ({ coordinates: [[from, 0], [to, 0]] as const, source })
const voyage = (id: string, index: number, extra: Partial<VoyageSequenceInput> = {}): VoyageSequenceInput => ({
  snapshotVoyageId: id, snapshotIndex: index, route: route(index * 10, index * 10 + 10), playbackDurationMs: 1_000, ...extra,
})

describe('Annual voyage sequencing', () => {
  it('모든 시각이 있으면 timestamp 순서, 동일 timestamp는 snapshot 순서로 결정한다', () => {
    const sequence = createVoyageSequence([
      voyage('late', 2, { startedAt: '2026-03-01T00:00:00Z' }),
      voyage('same-b', 1, { startedAt: '2026-02-01T00:00:00Z' }),
      voyage('same-a', 0, { startedAt: '2026-02-01T00:00:00Z' }),
    ])
    expect(sequence).toMatchObject({ status: 'available', order: 'timestamp' })
    if (sequence.status === 'available') expect(sequence.segments.map((item) => item.snapshotVoyageId)).toEqual(['same-a', 'same-b', 'late'])
  })

  it('날짜 하나라도 없으면 snapshot 순서의 relative timeline이며 날짜를 지어내지 않는다', () => {
    const sequence = createVoyageSequence([
      voyage('second', 1, { startedAt: null }),
      voyage('first', 0, { startedAt: '2026-05-01T00:00:00Z' }),
    ])
    expect(sequence).toMatchObject({ status: 'available', order: 'snapshot', durationMs: 2_000 })
    if (sequence.status === 'available') expect(sequence.segments.map((item) => item.snapshotVoyageId)).toEqual(['first', 'second'])
  })

  it('공백·겹침·연속 경계를 표시하되 상대 playback duration에는 시간을 추정해 더하지 않는다', () => {
    const sequence = createVoyageSequence([
      voyage('a', 0, { startedAt: '2026-01-01T00:00:00Z', endedAt: '2026-01-02T00:00:00Z' }),
      voyage('gap', 1, { startedAt: '2026-01-03T00:00:00Z', endedAt: '2026-01-05T00:00:00Z' }),
      voyage('overlap', 2, { startedAt: '2026-01-04T00:00:00Z', endedAt: '2026-01-06T00:00:00Z' }),
      voyage('touch', 3, { startedAt: '2026-01-06T00:00:00Z', endedAt: '2026-01-07T00:00:00Z' }),
    ])
    if (sequence.status !== 'available') throw new Error('sequence unavailable')
    expect(sequence.segments.map(({ relationToPrevious }) => relationToPrevious)).toEqual(['first', 'gap', 'overlap', 'contiguous'])
    expect(sequence.durationMs).toBe(4_000)
  })

  it('구간 경계는 다음 항차, timeline 끝은 마지막 항차의 끝 위치다', () => {
    const sequence = createVoyageSequence([voyage('a', 0), voyage('b', 1)])
    expect(voyageSequenceAtTime(sequence, 999)).toMatchObject({ snapshotVoyageId: 'a', segmentIndex: 0 })
    expect(voyageSequenceAtTime(sequence, 1_000)).toMatchObject({ snapshotVoyageId: 'b', segmentIndex: 1, segmentProgress: 0, position: [10, 0] })
    expect(voyageSequenceAtTime(sequence, 2_000)).toMatchObject({ snapshotVoyageId: 'b', segmentProgress: 1, position: [20, 0], timelineProgress: 1 })
  })

  it('controller state time을 seek 위치와 current voyage에 즉시 매핑한다', () => {
    const sequence = createVoyageSequence([voyage('a', 0), voyage('b', 1, { playbackDurationMs: 3_000 })])
    const playback = {
      status: 'available' as const, motion: 'paused' as const, timeMs: 2_500, durationMs: 4_000,
      progress: 0.625, speed: 1 as const, position: [0, 0] as const, traveledCoordinates: [[0, 0]] as const,
      activeRouteCoordinates: [[0, 0], [1, 0]] as const, activeRouteProgress: 0.625,
      activeRouteBearing: 90,
    }
    expect(voyageSequenceAtTime(sequence, playback)).toMatchObject({ snapshotVoyageId: 'b', segmentProgress: 0.5, position: [15, 0] })
  })

  it('controller가 전역 progress가 아니라 현재 항차의 좌표와 구간 progress를 전달한다', () => {
    const sequence = createVoyageSequence([
      voyage('east', 0, { route: { ...route(0, 10), coordinates: [[0, 0], [10, 0]] }, playbackDurationMs: 1_000 }),
      voyage('north', 1, { route: { ...route(10, 20), coordinates: [[10, 0], [10, 10]] }, playbackDurationMs: 3_000 }),
    ])
    const controller = createVoyageSequencePlaybackController(sequence)
    controller.seek(2_500)
    expect(controller.getState()).toMatchObject({
      activeRouteCoordinates: [[10, 0], [10, 10]],
      activeRouteProgress: 0.5,
      activeRouteBearing: 0,
      position: [10, 5],
    })
    controller.destroy()
  })

  it('route·duration 결측은 추정 없이 건너뛰고 모두 결측이면 unavailable이다', () => {
    const partial = createVoyageSequence([voyage('good', 0), voyage('no-route', 1, { route: null }), voyage('no-duration', 2, { playbackDurationMs: null })])
    expect(partial).toMatchObject({ status: 'available', skippedVoyageIds: ['no-route', 'no-duration'] })
    expect(createVoyageSequence([voyage('missing', 0, { route: null })])).toEqual({
      status: 'unavailable', reason: 'coordinates_not_provided', skippedVoyageIds: ['missing'],
    })
  })
})
