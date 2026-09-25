import { describe, expect, it, vi } from 'vitest'
import { createSimulationPlaybackController, type PlaybackSpeed } from './playbackController'

function fakeClock() {
  let now = 0
  let hidden = false
  let frameId = 0
  const frames = new Map<number, () => void>()
  const visibility = new Set<() => void>()
  return {
    clock: {
      now: () => now,
      requestFrame: (callback: () => void) => { frameId += 1; frames.set(frameId, callback); return frameId },
      cancelFrame: (id: number) => { frames.delete(id) },
      isHidden: () => hidden,
      subscribeVisibility: (callback: () => void) => { visibility.add(callback); return () => visibility.delete(callback) },
    },
    advance(ms: number) { now += ms; const pending = [...frames.values()]; frames.clear(); pending.forEach((callback) => callback()) },
    setHidden(value: boolean) { hidden = value; visibility.forEach((callback) => callback()) },
    pendingFrames: () => frames.size,
    visibilityListeners: () => visibility.size,
  }
}

const COORDINATES = [[0, 0], [10, 0]] as const

describe('Simulation playback controller', () => {
  it('실제 좌표가 없으면 unavailable이고 playback time을 만들지 않는다', () => {
    const controller = createSimulationPlaybackController({ coordinates: null, durationMs: 10_000 })
    controller.play()
    expect(controller.getState()).toEqual({ status: 'unavailable', reason: 'coordinates_not_provided' })
  })

  it('play/pause는 누적 frame이 아니라 clock 기준으로 drift 없이 시간을 계산한다', () => {
    const fake = fakeClock()
    const controller = createSimulationPlaybackController({ coordinates: COORDINATES, durationMs: 10_000, clock: fake.clock })
    controller.play()
    fake.advance(1_000)
    fake.advance(1_500)
    expect(controller.getState()).toMatchObject({ motion: 'playing', timeMs: 2_500, progress: 0.25, position: [2.5, 0] })
    controller.pause()
    fake.advance(2_000)
    expect(controller.getState()).toMatchObject({ motion: 'paused', timeMs: 2_500 })
  })

  it('seek/reset/restart가 위치와 timeline을 즉시 같은 snapshot으로 알린다', () => {
    const fake = fakeClock()
    const listener = vi.fn()
    const controller = createSimulationPlaybackController({ coordinates: COORDINATES, durationMs: 8_000, clock: fake.clock })
    controller.subscribe(listener)
    controller.seek(4_000)
    expect(listener).toHaveBeenLastCalledWith(expect.objectContaining({ timeMs: 4_000, progress: 0.5, position: [5, 0] }))
    controller.reset()
    expect(controller.getState()).toMatchObject({ motion: 'paused', timeMs: 0, progress: 0 })
    controller.restart()
    expect(controller.getState()).toMatchObject({ motion: 'playing', timeMs: 0 })
  })

  it.each([0.5, 1, 2, 4] as PlaybackSpeed[])('%sx 속도를 지원하고 변경 전 시간을 잃지 않는다', (speed) => {
    const fake = fakeClock()
    const controller = createSimulationPlaybackController({ coordinates: COORDINATES, durationMs: 10_000, clock: fake.clock })
    controller.play()
    fake.advance(1_000)
    controller.setSpeed(speed)
    fake.advance(1_000)
    expect(controller.getState()).toMatchObject({ speed, timeMs: 1_000 + 1_000 * speed })
  })

  it('background 동안 시간을 건너뛰지 않고 visible 복귀 뒤 이어서 간다', () => {
    const fake = fakeClock()
    const controller = createSimulationPlaybackController({ coordinates: COORDINATES, durationMs: 10_000, clock: fake.clock })
    controller.play()
    fake.advance(1_000)
    fake.setHidden(true)
    fake.advance(30_000)
    controller.pause()
    expect(controller.getState()).toMatchObject({ timeMs: 1_000, motion: 'paused' })
    controller.play()
    fake.setHidden(false)
    fake.advance(1_000)
    expect(controller.getState()).toMatchObject({ timeMs: 2_000, motion: 'playing' })
  })

  it('끝에서 정지하고 destroy가 RAF와 visibility listener를 정리한다', () => {
    const fake = fakeClock()
    const controller = createSimulationPlaybackController({ coordinates: COORDINATES, durationMs: 1_000, clock: fake.clock })
    controller.play()
    fake.advance(2_000)
    expect(controller.getState()).toMatchObject({ timeMs: 1_000, progress: 1, motion: 'paused' })
    controller.restart()
    expect(fake.pendingFrames()).toBe(1)
    controller.destroy()
    expect(fake.pendingFrames()).toBe(0)
    expect(fake.visibilityListeners()).toBe(0)
  })
})
