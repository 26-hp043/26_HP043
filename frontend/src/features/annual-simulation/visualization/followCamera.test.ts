import { describe, expect, it, vi } from 'vitest'
import { createFollowCameraController } from './followCamera'

describe('follow camera controller', () => {
  it('follow에서 위치와 방위를 반영하고 reduced motion이면 애니메이션하지 않는다', () => {
    const follow = vi.fn()
    let interaction: () => void = () => undefined
    const controller = createFollowCameraController({
      follow, showOverview: vi.fn(), subscribeUserInteraction: (listener) => { interaction = listener; return vi.fn() },
    }, { reducedMotion: true })
    controller.setMode('follow')
    controller.update([2, 0], [[1, 0], [2, 0]])
    expect(follow).toHaveBeenCalledWith([2, 0], 90, false)
    interaction()
    expect(controller.getMode()).toBe('overview')
  })

  it('reset은 overview를 복원하고 destroy는 interaction listener를 정리한다', () => {
    const cleanup = vi.fn()
    const showOverview = vi.fn()
    const controller = createFollowCameraController({ follow: vi.fn(), showOverview, subscribeUserInteraction: () => cleanup }, { reducedMotion: false })
    controller.setMode('follow')
    controller.resetView()
    expect(controller.getMode()).toBe('overview')
    expect(showOverview).toHaveBeenCalledOnce()
    controller.destroy()
    expect(cleanup).toHaveBeenCalledOnce()
  })
})
