// @vitest-environment jsdom
import '../../test/renderSetup'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { targetDescription, useGradeBoundaries } from './gradeBoundaries'

/*
 * 목표 등급 카드의 한 줄 풀이 (#2201 · `DESIGN_SYSTEM §8.4`). 경계는 서버가 싣는 값을 옮기기만
 * 한다 — 화면이 `d`를 곱하지 않는다(`#1371`).
 */
const BOUNDARIES = { superior: '4.1234', lower: '4.5', upper: '5.0', inferior: '5.75' }

function ok(boundaries: Record<string, string> | null) {
  return {
    ok: true,
    json: async () => ({
      data: {
        boundaries:
          boundaries === null
            ? null
            : {
                superior_boundary: boundaries.superior,
                lower_boundary: boundaries.lower,
                upper_boundary: boundaries.upper,
                inferior_boundary: boundaries.inferior,
              },
      },
    }),
  } as Response
}

describe('targetDescription', () => {
  it('A~D는 각자의 위쪽 경계를 이 배의 숫자로 적는다', () => {
    expect(targetDescription('A', BOUNDARIES)).toMatch(/^연말 CII 4\.\d+ 이하$/)
    expect(targetDescription('B', BOUNDARIES)).toContain('4.5')
    expect(targetDescription('C', BOUNDARIES)).toContain('5.0')
    expect(targetDescription('D', BOUNDARIES)).toContain('5.75')
  })

  it('경계를 못 받으면 판정식의 경계 이름으로 — 카드를 비우지 않는다', () => {
    expect(targetDescription('A', null)).toBe('연말 CII가 기준 × d1 이하')
    expect(targetDescription('D', null)).toBe('연말 CII가 기준 × d4 이하')
  })
})

describe('useGradeBoundaries', () => {
  it('이 배 · 이 연도의 경계를 받아 온다', async () => {
    const fetchImpl = vi.fn(async () => ok(BOUNDARIES))
    const { result } = renderHook(() => useGradeBoundaries('v1', '2026', fetchImpl, '/api'))
    await waitFor(() => expect(result.current).toEqual(BOUNDARIES))
    expect(String((fetchImpl.mock.calls[0] as unknown[])[0])).toBe('/api/vessels/v1/cii/ytd-series?year=2026')
  })

  it('선박이 없으면 부르지 않고 null', () => {
    const fetchImpl = vi.fn(async () => ok(BOUNDARIES))
    const { result } = renderHook(() => useGradeBoundaries(null, '2026', fetchImpl, '/api'))
    expect(result.current).toBeNull()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('실패 · 경계 없음(제원 미비)은 null', async () => {
    const failing = vi.fn(async () => ({ ok: false }) as Response)
    const empty = vi.fn(async () => ok(null))
    const a = renderHook(() => useGradeBoundaries('v1', '2026', failing, '/api'))
    const b = renderHook(() => useGradeBoundaries('v1', '2026', empty, '/api'))
    await waitFor(() => expect(failing).toHaveBeenCalled())
    await waitFor(() => expect(empty).toHaveBeenCalled())
    expect(a.result.current).toBeNull()
    expect(b.result.current).toBeNull()
  })

  it('⚠️ 배를 바꾸면 옛 배의 숫자를 보이지 않는다', async () => {
    const fetchImpl = vi.fn(async (url: string) =>
      url.includes('/v1/') ? ok(BOUNDARIES) : new Promise<Response>(() => {}),
    )
    const { result, rerender } = renderHook(
      ({ id }) => useGradeBoundaries(id, '2026', fetchImpl as unknown as typeof fetch, '/api'),
      { initialProps: { id: 'v1' } },
    )
    await waitFor(() => expect(result.current).toEqual(BOUNDARIES))
    rerender({ id: 'v2' })
    expect(result.current).toBeNull()
  })
})
