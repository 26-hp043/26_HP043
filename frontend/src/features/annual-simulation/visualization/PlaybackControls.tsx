import { useEffect, useId, useState } from 'react'
import type { PlaybackCameraMode } from './followCamera'
import type { PlaybackSpeed, SimulationPlaybackController, SimulationPlaybackState } from './playbackController'

interface PlaybackControlsProps {
  readonly controller: SimulationPlaybackController
  readonly cameraMode: PlaybackCameraMode
  readonly onCameraModeChange: (mode: PlaybackCameraMode) => void
  readonly onResetView: () => void
  readonly viewMode: '2d' | '2.5d'
  readonly onViewModeChange: (mode: '2d' | '2.5d') => void
}

function formatTime(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** 제품 통합 전에도 독립 검증할 수 있는 접근 가능한 playback controls다. */
export function PlaybackControls({
  controller, cameraMode, onCameraModeChange, onResetView, viewMode, onViewModeChange,
}: PlaybackControlsProps) {
  const [observed, setObserved] = useState<{ controller: SimulationPlaybackController; state: SimulationPlaybackState }>(() => ({
    controller, state: controller.getState(),
  }))
  if (observed.controller !== controller) {
    setObserved({ controller, state: controller.getState() })
  }
  const state = observed.controller === controller ? observed.state : controller.getState()
  const statusId = useId()
  useEffect(() => {
    return controller.subscribe((next) => setObserved({ controller, state: next }))
  }, [controller])
  const available = state.status === 'available'
  const keyboard = (event: React.KeyboardEvent<HTMLElement>) => {
    if (!available || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return
    if (event.key === ' ') {
      event.preventDefault()
      if (state.motion === 'playing') controller.pause()
      else controller.play()
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault()
      controller.seek(state.timeMs + (event.key === 'ArrowRight' ? 5_000 : -5_000))
    } else if (event.key === 'Home') {
      event.preventDefault()
      controller.reset()
    }
  }
  const status = available
    ? `${state.motion === 'playing' ? '재생 중' : '일시정지'} ${formatTime(state.timeMs)} / ${formatTime(state.durationMs)}, ${state.speed}배속`
    : '항로 좌표가 없어 재생할 수 없습니다.'

  return <section aria-label="항로 재생 제어" aria-describedby={statusId} tabIndex={0} onKeyDown={keyboard}>
    <button type="button" disabled={!available} aria-describedby={statusId} onClick={() => {
      if (!available) return
      if (state.motion === 'playing') controller.pause()
      else controller.play()
    }}>
      {available && state.motion === 'playing' ? '일시정지' : '재생'}
    </button>
    <button type="button" disabled={!available} aria-describedby={statusId} onClick={() => controller.restart()}>처음부터 재생</button>
    <label>재생 위치
      <input type="range" min={0} max={available ? state.durationMs : 1} value={available ? state.timeMs : 0}
        disabled={!available} aria-valuetext={available ? formatTime(state.timeMs) : '사용할 수 없음'}
        onChange={(event) => controller.seek(Number(event.target.value))} />
    </label>
    <label>재생 속도
      <select disabled={!available} value={available ? state.speed : 1}
        onChange={(event) => controller.setSpeed(Number(event.target.value) as PlaybackSpeed)}>
        {[0.5, 1, 2, 4].map((speed) => <option key={speed} value={speed}>{speed}배</option>)}
      </select>
    </label>
    <label>카메라
      <select disabled={!available} value={cameraMode} onChange={(event) => onCameraModeChange(event.target.value as PlaybackCameraMode)}>
        <option value="overview">전체 항로</option><option value="follow">선박 따라가기</option>
      </select>
    </label>
    <button type="button" disabled={!available} aria-describedby={statusId} onClick={onResetView}>전체 항로로 복귀</button>
    <fieldset disabled={!available}><legend>지도 보기</legend>
      {(['2d', '2.5d'] as const).map((mode) => <label key={mode}>
        <input type="radio" name="playback-view" checked={viewMode === mode} onChange={() => onViewModeChange(mode)} />{mode}
      </label>)}
    </fieldset>
    <p id={statusId} role="status" aria-live="polite">{status}</p>
    <small>단축키: Space 재생/일시정지, ←/→ 5초 이동, Home 처음으로</small>
  </section>
}
