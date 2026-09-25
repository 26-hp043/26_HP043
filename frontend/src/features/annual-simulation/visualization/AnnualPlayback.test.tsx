// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnnualSimulationResult } from '../types'
import { getKnownRouteSource } from '../../map/routeGeometry'
import type { AnnualMapGeometryProvider, MapGeometry } from './model'
import { AnnualPlayback } from './AnnualPlayback'

const rendererSpies = vi.hoisted(() => ({ mount: vi.fn(), destroy: vi.fn() }))
vi.mock('../../map/playbackRenderer', () => ({
  playbackRenderer: {
    mount: (...args: Parameters<typeof rendererSpies.mount>) => {
      rendererSpies.mount(...args)
      const emit = args[2] as (event: { type: 'ready' }) => void
      emit({ type: 'ready' })
      return { update: vi.fn(), destroy: rendererSpies.destroy }
    },
  },
}))

const RESULT: AnnualSimulationResult = {
  simulation_id: 'simulation-1', calculation_run_id: 'calculation-1',
  deterministic: { projected_attained_cii: '5', projected_rating: 'C', completed_voyage_count: 1, remaining_voyage_count: 1, completed_M_gco2: '1', completed_W_capacity_nm: '1', planned_M_gco2: '1', planned_W_capacity_nm: '1' },
  monte_carlo: {
    rng_metadata: { seed_entropy: '1', bit_generator: 'PCG', numpy_version: '2', python_version: '3', platform: 'test' },
    runs: 1, rating_probabilities: { A: '0', B: '0', C: '1', D: '0', E: '0' }, target_success_probability: '1', target_rating: 'C', p10: '5', p50: '5', p90: '5', mean_cii: '5',
  },
  risk_level: 'LOW', sensitivity_analysis: { interaction_note: '' },
  snapshot: { snapshot_id: 'snapshot-1', created_at: '2026-01-01T00:00:00Z', voyage_count: 1 }, warnings: [],
}
const AVAILABLE: MapGeometry = {
  status: 'available', snapshotId: 'snapshot-1', routes: [{
    snapshotVoyageId: 'voyage-1', playbackDurationMs: 10_000,
    vesselName: 'Snapshot호', departureName: '부산', arrivalName: '싱가포르',
    coordinates: [[129, 35], [103, 1]], source: getKnownRouteSource('searoute/marnet')!,
  }],
}
const HUD_PROPS = { projectedYear: '2026', vesselName: 'BlueLog호' } as const

afterEach(cleanup)
beforeEach(() => { rendererSpies.mount.mockClear(); rendererSpies.destroy.mockClear() })

describe('AnnualPlayback 제품 lifecycle', () => {
  it('좌표 unavailable이면 이유를 설명하고 지도와 controls를 만들지 않는다', async () => {
    const provider: AnnualMapGeometryProvider = { load: vi.fn(async (): Promise<MapGeometry> => ({ status: 'unavailable', reason: 'coordinates_not_provided' })) }
    const { container } = render(<AnnualPlayback result={RESULT} geometryProvider={provider} {...HUD_PROPS} />)
    await vi.waitFor(() => expect(provider.load).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(container.textContent).toContain('스냅샷에는 항로 좌표가 없어'))
    expect(screen.queryByRole('region', { name: '항로 재생 제어' })).toBeNull()
    expect(rendererSpies.mount).not.toHaveBeenCalled()
  })

  it('available snapshot 좌표에서 공용 renderer와 controls를 마운트하고 unmount cleanup한다', async () => {
    const provider: AnnualMapGeometryProvider = { load: vi.fn(async () => AVAILABLE) }
    const view = render(<AnnualPlayback result={RESULT} geometryProvider={provider} {...HUD_PROPS} />)
    expect(await screen.findByRole('region', { name: '항로 재생 제어' })).toBeTruthy()
    await vi.waitFor(() => expect(rendererSpies.mount).toHaveBeenCalledOnce())
    expect(rendererSpies.mount.mock.calls[0][1]).toMatchObject({
      mode: 'playback', route: { source: 'provided-coordinates', coordinates: [[129, 35], [103, 1]] },
    })
    const hud = screen.getByRole('complementary', { name: '항로 재생 정보' })
    expect(hud.textContent).toContain('서버 최종 예측 결과 · 재생 위치와 무관')
    expect(hud.textContent).toContain('2026')
    expect(hud.textContent).toContain('5.000')
    expect(hud.textContent).toContain('Snapshot호')
    expect(hud.textContent).toContain('부산')
    expect(hud.textContent).toContain('싱가포르')
    expect(hud.querySelector('[aria-live]')).toBeNull()
    view.unmount()
    expect(rendererSpies.destroy).toHaveBeenCalledOnce()
  })

  it('명시적 fixture autoplay 입력에서만 controller를 재생한다', async () => {
    const provider: AnnualMapGeometryProvider = { load: vi.fn(async () => AVAILABLE) }
    render(<AnnualPlayback result={RESULT} geometryProvider={provider} {...HUD_PROPS} autoPlay />)
    await vi.waitFor(() => expect(rendererSpies.mount).toHaveBeenCalledOnce())
    const model = rendererSpies.mount.mock.calls[0][1] as { controller: { getState(): { motion?: string } } }
    expect(model.controller.getState().motion).toBe('playing')
  })

  it('실행이 바뀌면 이전 요청을 abort하고 늦은 좌표를 표시하지 않는다', async () => {
    let resolveFirst!: (geometry: MapGeometry) => void
    const signals: AbortSignal[] = []
    const provider: AnnualMapGeometryProvider = {
      load: vi.fn((result: AnnualSimulationResult, signal: AbortSignal): Promise<MapGeometry> => {
        signals.push(signal)
        if (result.simulation_id === 'simulation-1') return new Promise<MapGeometry>((resolve) => { resolveFirst = resolve })
        return Promise.resolve({ status: 'unavailable', reason: 'coordinates_not_provided' })
      }),
    }
    const view = render(<AnnualPlayback result={RESULT} geometryProvider={provider} {...HUD_PROPS} />)
    view.rerender(<AnnualPlayback result={{ ...RESULT, simulation_id: 'simulation-2' }} geometryProvider={provider} {...HUD_PROPS} />)
    expect(signals[0].aborted).toBe(true)
    resolveFirst(AVAILABLE)
    await Promise.resolve()
    expect(rendererSpies.mount).not.toHaveBeenCalled()
  })

  it('좌표 오류를 알리고 retry가 새 요청을 만든다', async () => {
    const user = userEvent.setup()
    const load = vi.fn<AnnualMapGeometryProvider['load']>().mockRejectedValueOnce(new Error('좌표 실패')).mockResolvedValueOnce(AVAILABLE)
    render(<AnnualPlayback result={RESULT} geometryProvider={{ load }} {...HUD_PROPS} />)
    await user.click(await screen.findByRole('button', { name: '다시 시도' }))
    expect(await screen.findByRole('region', { name: '항로 재생 제어' })).toBeTruthy()
    expect(load).toHaveBeenCalledTimes(2)
  })
})
