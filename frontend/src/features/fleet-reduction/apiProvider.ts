import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type {
  Adjustment,
  EvaluateRequest,
  EvaluateResult,
  FleetReductionProvider,
  Prices,
  Rating,
  SavedPlanSummary,
  Target,
  VesselResult,
} from './types'

/**
 * 함대 감축 계획 실 API provider — `API_SPEC §2.17` · #513.
 *
 * **서버 오류 문구를 그대로 올린다** — 422의 필드 라벨(「감속률」 등)이 사용자가 고칠 칸을 가리킨다.
 */

export class FleetReductionError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'FleetReductionError'
  }
}

type Json = Record<string, unknown>

function body(request: EvaluateRequest): Json {
  // 빈 단가 칸은 보내지 않는다 — 서버가 「0달러」로 받으면 비용 칸이 0으로 채워진다.
  const filled = (m: Record<string, string>) =>
    Object.fromEntries(Object.entries(m).filter(([, v]) => v.trim() !== ''))
  return {
    regulation_year: request.regulationYear,
    target: request.target,
    adjustments: request.adjustments
      .filter((a) => a.percent > 0)
      .map((a) => ({ vessel_id: a.vesselId, speed_reduction_percent: a.percent })),
    prices: {
      charter_usd_per_day: filled(request.prices.charterUsdPerDay),
      fuel_usd_per_ton: filled(request.prices.fuelUsdPerTon),
    },
  }
}

function toVessel(raw: Json): VesselResult {
  const projection = (value: unknown) => {
    const p = value as { attained_cii: string; rating: Rating } | undefined
    return p ? { attainedCii: p.attained_cii, rating: p.rating } : null
  }
  return {
    vesselId: String(raw.vessel_id),
    vesselName: String(raw.vessel_name),
    unavailableReason: (raw.unavailable_reason as string | null) ?? null,
    before: projection(raw.before),
    after: projection(raw.after),
    targetRating: (raw.target_rating as Rating | undefined) ?? null,
    meetsTarget: (raw.meets_target as boolean | undefined) ?? null,
    extraDays: (raw.extra_days as string | undefined) ?? null,
    fuelSavedTon: (raw.fuel_saved_ton as string | undefined) ?? null,
    skippedVoyages: (raw.skipped_voyages as number | undefined) ?? 0,
    requiredCutFuelTon: (raw.required_cut_fuel_ton as string | null | undefined) ?? null,
    achievable: (raw.achievable as boolean | undefined) ?? null,
  }
}

function toResult(data: Json): EvaluateResult {
  const costs = data.costs as Json
  const dist = data.rating_distribution as {
    before: Record<Rating, number>
    after: Record<Rating, number>
  }
  return {
    regulationYear: Number(data.regulation_year),
    target: data.target as Target,
    targetMet: (data.target_met as boolean | null) ?? null,
    vessels: (data.vessels as Json[]).map(toVessel),
    distribution: dist,
    costs: {
      extraDays: String(costs.extra_days),
      charterLoss: (costs.charter_loss as string | null) ?? null,
      fuelSaving: (costs.fuel_saving as string | null) ?? null,
      net: (costs.net as string | null) ?? null,
      missingCharterRates: (costs.missing_charter_rates as string[]) ?? [],
      missingFuelPrices: (costs.missing_fuel_prices as string[]) ?? [],
    },
    warnings: (data.warnings as string[]) ?? [],
  }
}

function toPrices(raw: unknown): Prices {
  const p = (raw ?? {}) as { charter_usd_per_day?: Json; fuel_usd_per_ton?: Json }
  const strings = (m: Json | undefined) =>
    Object.fromEntries(Object.entries(m ?? {}).map(([k, v]) => [k, String(v)]))
  return {
    charterUsdPerDay: strings(p.charter_usd_per_day),
    fuelUsdPerTon: strings(p.fuel_usd_per_ton),
  }
}

function toPlan(raw: Json): SavedPlanSummary {
  return {
    planId: String(raw.plan_id),
    planName: String(raw.plan_name),
    regulationYear: Number(raw.regulation_year),
    target: raw.target as Target,
    adjustments: ((raw.adjustments as Json[]) ?? []).map(
      (a): Adjustment => ({
        vesselId: String(a.vessel_id),
        percent: Number(a.speed_reduction_percent),
      }),
    ),
    prices: toPrices(raw.prices),
    createdAt: (raw.created_at as string | null) ?? null,
  }
}

export function createApiFleetReductionProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): FleetReductionProvider {
  async function call(path: string, init: RequestInit): Promise<Json> {
    let response: Response
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        credentials: 'include',
        ...init,
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          ...csrfHeaders(),
        },
      })
    } catch (cause) {
      throw new FleetReductionError('함대 감축 계획 서버에 연결하지 못했습니다.', { cause })
    }
    if (response.status === 401) {
      redirectToLogin()
      throw new FleetReductionError(SESSION_EXPIRED_MESSAGE)
    }
    const payload = (await response.json().catch(() => ({}))) as {
      data?: unknown
      error?: { message?: string }
    }
    if (!response.ok) {
      throw new FleetReductionError(
        payload.error?.message ?? `요청을 처리하지 못했습니다 (HTTP ${response.status}).`,
      )
    }
    return payload as Json
  }

  return {
    async evaluate(request) {
      const res = await call('/fleet/reduction-plans/evaluate', {
        method: 'POST',
        body: JSON.stringify(body(request)),
      })
      return toResult(res.data as Json)
    },
    async save(request) {
      const res = await call('/fleet/reduction-plans', {
        method: 'POST',
        body: JSON.stringify({ ...body(request), plan_name: request.planName }),
      })
      return toPlan(res.data as Json)
    },
    async list() {
      const res = await call('/fleet/reduction-plans', { method: 'GET' })
      return ((res.data as Json[]) ?? []).map(toPlan)
    },
  }
}
