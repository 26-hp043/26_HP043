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

/**
 * 저장한 계획 목록의 커서 페이지네이션 (`#1395` · `#1367` 후속).
 *
 * `#1367`이 서버에 커서를 붙인 뒤 이 화면은 **첫 페이지만 받고 그 사실을 말하지
 * 않았다** — 21번째 계획이 셀렉트에 뜨지 않았고, 화면은 그것이 전부인 것처럼
 * 보였다. 「계획이 N개뿐」과 「아직 다 주지 않았다」가 **같은 모양**이었다.
 *
 * `reports/apiProvider.listVoyages`(`#627`)가 같은 모양의 셀렉트에서 한 판단을
 * 그대로 따른다 — 「더 보기」가 아니라 **끝까지 부른다**.
 */
function planPage(ids: string[], meta: { next_cursor: string | null; has_more: boolean }) {
  return {
    data: ids.map((id) => ({
      plan_id: id,
      plan_name: `계획 ${id}`,
      regulation_year: 2026,
      target: 'NO_AT_RISK',
      adjustments: [],
      prices: null,
      created_at: null,
    })),
    meta,
  }
}

describe('list — 커서 페이지네이션 (#1395)', () => {
  it('페이지를 끝까지 순회해 **전부** 돌려준다', async () => {
    const pages = [
      planPage(['p1', 'p2'], { next_cursor: 'c2', has_more: true }),
      planPage(['p3'], { next_cursor: null, has_more: false }),
    ]
    const seen: string[] = []
    const fetchImpl = vi.fn(async (input: unknown) => {
      seen.push(String(input))
      return jsonResponse(pages[seen.length - 1])
    })

    const plans = await createApiFleetReductionProvider(
      fetchImpl as typeof fetch,
      '/api/v1',
    ).list()

    expect(plans.map((p) => p.planId)).toEqual(['p1', 'p2', 'p3'])
    expect(seen[0]).not.toContain('cursor=')
    expect(seen[1]).toContain('cursor=c2')
  })

  it('⚠️ 커서가 전진하지 않으면 멈춘다 — 페이지 상한으로 막지 않는다', async () => {
    // 임의의 상한을 두면 그 너머를 **조용히 자른다**. 서버가 같은 커서를 다시
    // 주는 것은 계약 위반이고, 그때만 루프가 무한해진다.
    const fetchImpl = vi.fn(async () =>
      jsonResponse(planPage(['p1'], { next_cursor: 'same', has_more: true })),
    )

    const plans = await createApiFleetReductionProvider(
      fetchImpl as typeof fetch,
      '/api/v1',
    ).list()

    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(plans.map((p) => p.planId)).toEqual(['p1', 'p1'])
  })

  it('한 페이지로 끝나면 한 번만 부른다 — 구버전 서버(meta 없음)도 같다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: planPage(['p1'], {
      next_cursor: null,
      has_more: false,
    }).data }))

    const plans = await createApiFleetReductionProvider(
      fetchImpl as typeof fetch,
      '/api/v1',
    ).list()

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(plans).toHaveLength(1)
  })
})
