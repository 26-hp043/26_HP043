// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSimulationPlaybackController } from './playbackController'
import { PlaybackControls } from './PlaybackControls'

const coordinates = [[0, 0], [10, 0]] as const

afterEach(cleanup)

function renderControls(coordinatesInput: typeof coordinates | null = coordinates) {
  const controller = createSimulationPlaybackController({ coordinates: coordinatesInput, durationMs: 10_000 })
  const onCameraModeChange = vi.fn()
  const onResetView = vi.fn()
  const view = render(<PlaybackControls controller={controller} cameraMode="overview" onCameraModeChange={onCameraModeChange}
    onResetView={onResetView} viewMode="2.5d" onViewModeChange={vi.fn()} />)
  return { controller, onCameraModeChange, onResetView, view }
}

describe('PlaybackControls', () => {
  it('keyboard로 play/pause, seek, reset을 수행하고 상태를 live region에 표시한다', () => {
    const { controller } = renderControls()
    const controls = screen.getByRole('region', { name: '항로 재생 제어' })
    fireEvent.keyDown(controls, { key: ' ' })
    expect(controller.getState()).toMatchObject({ motion: 'playing' })
    controller.pause()
    fireEvent.keyDown(controls, { key: 'ArrowRight' })
    expect(controller.getState()).toMatchObject({ timeMs: 5_000 })
    fireEvent.keyDown(controls, { key: 'Home' })
    expect(controller.getState()).toMatchObject({ timeMs: 0 })
    expect(screen.getByRole('status').getAttribute('aria-live')).toBe('polite')
    controller.destroy()
  })

  it('seek/speed/follow/reset/view controls를 pointer로 조작한다', async () => {
    const user = userEvent.setup()
    const { controller, onCameraModeChange, onResetView } = renderControls()
    fireEvent.change(screen.getByRole('slider', { name: '재생 위치' }), { target: { value: '7000' } })
    await user.selectOptions(screen.getByRole('combobox', { name: '재생 속도' }), '2')
    await user.selectOptions(screen.getByRole('combobox', { name: '카메라' }), 'follow')
    await user.click(screen.getByRole('button', { name: '전체 항로로 복귀' }))
    expect(controller.getState()).toMatchObject({ timeMs: 7_000, speed: 2 })
    expect(onCameraModeChange).toHaveBeenCalledWith('follow')
    expect(onResetView).toHaveBeenCalledOnce()
    controller.destroy()
  })

  it('좌표가 없으면 모든 scene control을 disabled하고 unavailable을 알린다', () => {
    renderControls(null)
    expect(screen.getAllByRole('button').every((button) => button.hasAttribute('disabled'))).toBe(true)
    expect(screen.getByRole('status').textContent).toContain('항로 좌표가 없어')
  })
})
