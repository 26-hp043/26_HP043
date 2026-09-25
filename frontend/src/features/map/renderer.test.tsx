// @vitest-environment jsdom
import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MapRendererHost, type MapRenderer } from './renderer'

describe('MapRendererHost', () => {
  it('renderer를 마운트하고 모델을 갱신한 뒤 해제한다', async () => {
    const update = vi.fn()
    const destroy = vi.fn()
    const mount = vi.fn(() => ({ update, destroy }))
    const renderer: MapRenderer<{ mode: 'fleet'; value: number }> = { mount }
    const loadRenderer = vi.fn(async () => renderer)
    const view = render(
      <MapRendererHost ariaLabel="지도" model={{ mode: 'fleet', value: 1 }} loadRenderer={loadRenderer} />,
    )
    await vi.waitFor(() => expect(mount).toHaveBeenCalledTimes(1))

    view.rerender(
      <MapRendererHost ariaLabel="지도" model={{ mode: 'fleet', value: 2 }} loadRenderer={loadRenderer} />,
    )
    expect(update).toHaveBeenLastCalledWith({ mode: 'fleet', value: 2 })

    view.unmount()
    expect(destroy).toHaveBeenCalledTimes(1)
  })

  it('해제 뒤 끝난 dynamic import는 renderer를 마운트하지 않는다', async () => {
    type Model = { mode: 'comparison'; value: number }
    let resolve!: (renderer: MapRenderer<Model>) => void
    const mount = vi.fn()
    const loadRenderer = () => new Promise<MapRenderer<Model>>((done) => { resolve = done })
    const view = render(<MapRendererHost ariaLabel="지도" model={{ mode: 'comparison', value: 1 }} loadRenderer={loadRenderer} />)
    view.unmount()
    resolve({ mount })
    await Promise.resolve()
    expect(mount).not.toHaveBeenCalled()
  })

  it('dynamic import 실패를 error event로 전달한다', async () => {
    const onEvent = vi.fn()
    const failure = new Error('chunk load failed')
    render(
      <MapRendererHost
        ariaLabel="지도"
        model={{ mode: 'playback' }}
        loadRenderer={() => Promise.reject(failure)}
        onEvent={onEvent}
      />,
    )
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({ type: 'error', error: failure }))
  })

  it('renderer의 ready와 selection을 엔진 중립 이벤트로 전달한다', () => {
    const onEvent = vi.fn()
    const renderer: MapRenderer<{ mode: 'playback' }> = {
      mount(_target, _model, emit) {
        emit({ type: 'ready' })
        emit({ type: 'selection', id: 'bearing:30' })
        return { update: vi.fn(), destroy: vi.fn() }
      },
    }
    render(
      <MapRendererHost
        ariaLabel="지도"
        model={{ mode: 'playback' }}
        renderer={renderer}
        onEvent={onEvent}
      />,
    )
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([
      { type: 'ready' },
      { type: 'selection', id: 'bearing:30' },
    ])
  })
})
