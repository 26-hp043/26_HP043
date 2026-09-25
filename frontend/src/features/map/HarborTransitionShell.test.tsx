// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MapRendererEvent } from './renderer'
import { HarborTransitionShell } from './HarborTransitionShell'

const harbor = vi.hoisted(() => ({ mount: vi.fn(), destroy: vi.fn(), emit: null as ((event: MapRendererEvent) => void) | null }))
vi.mock('./harborRenderer', () => ({
  loadHarborRenderer: vi.fn(async () => ({
    mount: (...args: unknown[]) => {
      harbor.mount(...args)
      harbor.emit = args[2] as (event: MapRendererEvent) => void
      return { update: vi.fn(), destroy: harbor.destroy }
    },
  })),
}))

afterEach(() => { cleanup(); harbor.mount.mockClear(); harbor.destroy.mockClear(); harbor.emit = null; history.replaceState(null, '', location.href) })

function setup() {
  let globeEmit: ((event: MapRendererEvent) => void) | null = null
  const result = render(<HarborTransitionShell renderGlobe={(onEvent) => {
    globeEmit = onEvent
    return <button type="button" onClick={() => onEvent({ type: 'selection', id: 'port:departure:KRPUS' })}>부산항</button>
  }} />)
  return { ...result, emit: (event: MapRendererEvent) => globeEmit?.(event) }
}

describe('globe-HarborScene 전환 shell', () => {
  it('지원 항만 selection에서만 Harbor를 lazy mount하고 복귀하면 globe DOM 상태와 focus를 보존한다', async () => {
    const user = userEvent.setup()
    setup()
    const portButton = screen.getByRole('button', { name: '부산항' })
    portButton.focus()
    await user.click(portButton)
    expect(await screen.findByRole('region', { name: '부산 북항 상세 장면' })).toBeTruthy()
    expect(harbor.mount).toHaveBeenCalledOnce()
    harbor.emit?.({ type: 'ready' })
    await vi.waitFor(() => expect(screen.getByRole('status').textContent).toContain('준비'))
    fireEvent.popState(window)
    await vi.waitFor(() => expect(screen.queryByRole('region', { name: '부산 북항 상세 장면' })).toBeNull())
    expect(harbor.destroy).toHaveBeenCalledOnce()
    await vi.waitFor(() => expect(document.activeElement).toBe(portButton))
  })

  it('싱가포르를 열고 load failure를 상태와 retry로 복구한다', async () => {
    const user = userEvent.setup()
    const view = setup()
    view.emit({ type: 'selection', id: 'port:destination:SGSIN' })
    expect(await screen.findByRole('region', { name: '싱가포르 항만 상세 장면' })).toBeTruthy()
    harbor.emit?.({ type: 'error', error: new Error('WebGL 실패') })
    await vi.waitFor(() => expect(screen.getByRole('status').textContent).toContain('표시하지 못했습니다'))
    await user.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(harbor.destroy).toHaveBeenCalledOnce()
    expect(harbor.mount).toHaveBeenCalledTimes(2)
  })

  it('알 수 없는 항만에는 장면을 추정해 열지 않는다', () => {
    const view = setup()
    view.emit({ type: 'selection', id: 'port:destination:UNKNOWN' })
    expect(harbor.mount).not.toHaveBeenCalled()
    expect(screen.queryByText('전체 항로로 돌아가기')).toBeNull()
  })

  it('항만이 열린 채 unmount되면 현재 history entry의 Harbor 표식을 제거한다', async () => {
    history.replaceState({ beforeHarbor: true }, '', location.href)
    const view = setup()
    view.emit({ type: 'selection', id: 'port:departure:KRPUS' })
    expect(await screen.findByRole('region', { name: '부산 북항 상세 장면' })).toBeTruthy()
    expect(history.state.bluelogHarbor).toBe('busan')
    view.unmount()
    expect(history.state).toEqual({ beforeHarbor: true })
    expect(harbor.destroy).toHaveBeenCalledOnce()
  })
})
