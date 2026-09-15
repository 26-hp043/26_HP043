import { describe, expect, it, vi } from 'vitest'
import { FleetReductionError, createApiFleetReductionProvider } from './apiProvider'

/**
 * 함대 감축 계획 provider — `API_SPEC §2.17` 계약 고정 (#513).
 *
 * 핵심은 둘이다. ⑴ **빈 단가 칸을 보내지 않는다** — 보내면 서버가 0달러로 받아 비용 칸이 0으로
 * 채워진다 ⑵ **서버 오류 문구를 그대로** 올린다 — 422의 필드 라벨이 고칠 칸을 가리킨다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RESULT = {
  data: {
    regulation_year: 2026,
    target: 'NO_AT_RISK',
    target_met: false,
    vessels: [
      {
        vessel_id: 'v1',
        vessel_name: 'MV One',
        speed_reduction_percent: '10.0',
        unavailable_reason: null,
        before: { attained_cii: '8.9711', rating: 'E' },
        after: { attained_cii: '8.0909', rating: 'E' },
        target_rating: 'D',
        meets_target: false,
        extra_days: '1.52',
        fuel_saved_ton: '125.78',
        skipped_voyages: 0,
        remaining_voyage_count: 2,
        required_cut_fuel_ton: '305.50',
        achievable: true,
      },
      { vessel_id: 'v2', vessel_name: 'MV Empty', speed_reduction_percent: '0.0', unavailable_reason: 'NO_DATA' },
    ],
    rating_distribution: {
      before: { A: 0, B: 0, C: 0, D: 0, E: 1 },
      after: { A: 0, B: 0, C: 0, D: 0, E: 1 },
    },
    costs: {
      currency: 'USD',
      extra_days: '1.52',
      charter_loss: null,
      fuel_saving: '75468.00',
      net: null,
      fuel_saved_ton_by_type: { HFO: '125.78' },
      missing_charter_rates: ['v1'],
      missing_fuel_prices: [],
    },
    warnings: [],
  },
  meta: {},
}

describe('createApiFleetReductionProvider', () => {
  it('⚠️ 빈 단가 칸과 0% 선박은 보내지 않는다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown, _init?: RequestInit) => jsonResponse(RESULT))
    const provider = createApiFleetReductionProvider(fetchImpl as typeof fetch, '/api/v1')

    await provider.evaluate({
      regulationYear: 2026,
      target: 'NO_AT_RISK',
      adjustments: [
        { vesselId: 'v1', percent: 10 },
        { vesselId: 'v2', percent: 0 },
      ],
      prices: { charterUsdPerDay: { v1: '', v2: '15000' }, fuelUsdPerTon: { HFO: '600', LNG: ' ' } },
    })

    const [url, init] = fetchImpl.mock.calls[0]
    expect(String(url)).toBe('/api/v1/fleet/reduction-plans/evaluate')
    expect(JSON.parse(String(init?.body))).toEqual({
      regulation_year: 2026,
      target: 'NO_AT_RISK',
      adjustments: [{ vessel_id: 'v1', speed_reduction_percent: 10 }],
      prices: { charter_usd_per_day: { v2: '15000' }, fuel_usd_per_ton: { HFO: '600' } },
    })
  })

  it('계산하지 못한 선박은 사유만 들고, 비용의 빈칸은 null 그대로 둔다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) => jsonResponse(RESULT))
    const result = await createApiFleetReductionProvider(fetchImpl as typeof fetch, '/api/v1').evaluate({
      regulationYear: 2026,
      target: 'NO_AT_RISK',
      adjustments: [],
      prices: { charterUsdPerDay: {}, fuelUsdPerTon: {} },
    })

    expect(result.vessels[1]).toMatchObject({ unavailableReason: 'NO_DATA', before: null, after: null })
    expect(result.costs.charterLoss).toBeNull()
    expect(result.costs.missingCharterRates).toEqual(['v1'])
  })

  it('저장은 plan_name을 싣고, 목록은 단가를 문자열로 돌려준다', async () => {
    const plan = {
      plan_id: 'p1',
      plan_name: '9월안',
      regulation_year: 2026,
      target: 'ALL_C_OR_BETTER',
      adjustments: [{ vessel_id: 'v1', speed_reduction_percent: '10' }],
      prices: { charter_usd_per_day: { v1: '15000' }, fuel_usd_per_ton: { HFO: '600' } },
      created_at: '2026-09-13T14:00:00+00:00',
    }
    const fetchImpl = vi.fn(async (_input: unknown, init?: RequestInit) =>
      init?.method === 'GET' ? jsonResponse({ data: [plan] }) : jsonResponse({ data: plan }, 201),
    )
    const provider = createApiFleetReductionProvider(fetchImpl as typeof fetch, '/api/v1')

    const saved = await provider.save({
      regulationYear: 2026,
      target: 'ALL_C_OR_BETTER',
      adjustments: [{ vesselId: 'v1', percent: 10 }],
      prices: { charterUsdPerDay: {}, fuelUsdPerTon: {} },
      planName: '9월안',
    })
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toMatchObject({ plan_name: '9월안' })
    expect(saved.adjustments).toEqual([{ vesselId: 'v1', percent: 10 }])

    const listed = await provider.list()
    expect(listed[0].prices).toEqual({ charterUsdPerDay: { v1: '15000' }, fuelUsdPerTon: { HFO: '600' } })
  })

  it('⚠️ 서버 오류 문구를 그대로 올린다 — 422 라벨이 고칠 칸을 가리킨다', async () => {
    const fetchImpl = vi.fn(async (_input: unknown) =>
      jsonResponse({ error: { code: 'VALIDATION_ERROR', message: '감속률: 50 이하여야 합니다.' } }, 422),
    )

    await expect(
      createApiFleetReductionProvider(fetchImpl as typeof fetch, '/api/v1').evaluate({
        regulationYear: 2026,
        target: 'NO_AT_RISK',
        adjustments: [],
        prices: { charterUsdPerDay: {}, fuelUsdPerTon: {} },
      }),
    ).rejects.toThrow(new FleetReductionError('감속률: 50 이하여야 합니다.'))
  })
})
