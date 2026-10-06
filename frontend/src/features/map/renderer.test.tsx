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

  /*
   * 한 지도의 실패가 **다른 지도 instance로 번지지 않는다** (`#1469`).
   *
   * 한 화면에 지도가 둘 놓일 수 있다 — 항로 비교의 결과 지도와 항만 장면, 선박 상세의
   * 위치 지도와 개략도가 그렇다. `mount`가 던지면 host가 그것을 **자기 `emit`으로만**
   * 돌리므로(위 `mount` 의 try/catch) 다른 host의 세션은 건드리지 않아야 한다.
   *
   * ⚠️ **`emit`이 host 안에 갇히는지가 요점이다.** 종전에는 이 사실을 재는 검사가 없어,
   * 실패 하나가 공용 상태를 거쳐 다른 지도를 내리더라도 **두 지도를 함께 띄운 검사가
   * 없으니** 아무도 알아채지 못했다. 실패한 쪽은 자기 `onEvent`로 오류를 받고, 성한 쪽은
   * 마운트된 채 `update`를 계속 받는다.
   */
  it('한 지도의 mount 실패가 다른 지도 instance에 번지지 않는다 (#1469)', async () => {
    type Model = { mode: 'fleet'; value: number }
    const brokenEvents: string[] = []
    const healthyEvents: string[] = []
    const update = vi.fn()
    const destroy = vi.fn()

    const broken: MapRenderer<Model> = {
      mount() {
        const error = new Error('WebGL unavailable')
        error.name = 'webgl-unavailable'
        throw error
      },
    }
    const healthy: MapRenderer<Model> = {
      mount(_target, _model, emit) {
        emit({ type: 'ready' })
        return { update, destroy }
      },
    }

    const view = render(
      <>
        <MapRendererHost
          ariaLabel="깨진 지도"
          model={{ mode: 'fleet', value: 1 }}
          renderer={broken}
          onEvent={(event) => brokenEvents.push(event.type)}
        />
        <MapRendererHost
          ariaLabel="성한 지도"
          model={{ mode: 'fleet', value: 1 }}
          renderer={healthy}
          onEvent={(event) => healthyEvents.push(event.type)}
        />
      </>,
    )

    // 실패는 자기 host에만 닿는다.
    await vi.waitFor(() => expect(brokenEvents).toContain('error'))
    expect(healthyEvents).toEqual(['ready'])
    expect(healthyEvents).not.toContain('error')

    // 성한 쪽은 **살아 있다** — 실패 뒤에도 모델 갱신을 계속 받는다.
    view.rerender(
      <>
        <MapRendererHost
          ariaLabel="깨진 지도"
          model={{ mode: 'fleet', value: 2 }}
          renderer={broken}
          onEvent={(event) => brokenEvents.push(event.type)}
        />
        <MapRendererHost
          ariaLabel="성한 지도"
          model={{ mode: 'fleet', value: 2 }}
          renderer={healthy}
          onEvent={(event) => healthyEvents.push(event.type)}
        />
      </>,
    )
    expect(update).toHaveBeenLastCalledWith({ mode: 'fleet', value: 2 })
    expect(destroy).not.toHaveBeenCalled()

    // 두 지도가 모두 화면에 남는다 — 실패한 쪽도 자리를 비우지 않는다(대체 정보가 그 안에 놓인다).
    expect(view.getByLabelText('깨진 지도')).toBeTruthy()
    expect(view.getByLabelText('성한 지도')).toBeTruthy()

    view.unmount()
    expect(destroy).toHaveBeenCalledTimes(1)
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

/*
 * 지도 호스트는 **그림이 아니라 묶음**이다 (#2128 ⑵).
 *
 * `role="img"`는 하위 트리를 통째로 presentational로 만든다 — 그 안의 버튼은 보조기술에
 * 버튼으로 닿지 않는다. 그런데 렌더러는 마커·항만 핀 **버튼**을 이 호스트 안에 붙인다
 * (`#1831` · `#1933`). 이름(`aria-label`)과 설명(`aria-describedby`)은 그대로 호스트가 갖는다.
 */
describe('MapRendererHost — 안에 붙는 조작이 보조기술에 닿는다 (#2128)', () => {
  it('렌더러가 호스트 안에 붙인 버튼의 조상에 role="img"가 없다', () => {
    let button: HTMLButtonElement | null = null
    const renderer: MapRenderer<{ mode: 'fleet' }> = {
      mount(target) {
        button = document.createElement('button')
        button.setAttribute('aria-label', '선박 1')
        target.append(button)
        return { update: vi.fn(), destroy: vi.fn() }
      },
    }
    const view = render(
      <>
        <p id="hint">설명</p>
        <MapRendererHost ariaLabel="지도" ariaDescribedBy="hint" model={{ mode: 'fleet' }} renderer={renderer} />
      </>,
    )

    // 이 파일은 공통 뒷정리를 쓰지 않는다 — 앞 검사의 DOM이 남으므로 자기 container 안에서 찾는다.
    const attached = view.container.querySelector('button')!
    expect(attached).toBe(button)
    expect(attached.closest('[role="img"]')).toBeNull()
    // 이름과 설명은 잃지 않는다 — 이름이 읽히려면 호스트에 역할이 있어야 한다(`§12`).
    const host = attached.parentElement!
    expect(host.getAttribute('aria-label')).toBe('지도')
    expect(host.getAttribute('role')).not.toBeNull()
    expect(host.getAttribute('aria-describedby')).toBe('hint')
  })
})
