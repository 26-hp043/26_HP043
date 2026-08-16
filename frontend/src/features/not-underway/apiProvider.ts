import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type {
  FuelUse,
  NotUnderwayProvider,
  Period,
  PeriodDraft,
  PeriodList,
} from './types'

/**
 * not under way 구간 provider — `API_SPEC §2.9~§2.13` (`#370`).
 *
 * ## 서버 오류 문구를 그대로 쓴다
 *
 * 겹침(409)은 **어느 구간과 겹치는지 시각까지** 실어 온다. 화면이 「겹칩니다」로
 * 다시 쓰면 사용자가 기존 기록을 찾아 고칠 수 없다. 422도 마찬가지로 어느 항목이
 * 문제인지 `details[].field`에 실려 온다.
 *
 * ## CF를 보내지 않는다
 *
 * `not_underway_fuel_use.cf_used`는 서버가 계산 시점 값으로 뜬다. 화면이 보내면
 * 사용자가 배출계수를 정하는 셈이 되고, `PRD §8.4`의 「CF 개정 시 과거 계산 보존」이
 * 무너진다.
 *
 * ## 숫자를 문자열로 두지 않는다
 *
 * 기능①·②의 CII 값과 달리 여기 수치(`fuel_ton`·`distance_nm`)는 **Layer 1 계산
 * 결과가 아니라 사용자가 넣은 입력값**이다. 서버도 JSON number로 준다
 * (`API_SPEC §1.7` — 문자열 직렬화는 계산 결과에만 적용된다).
 */

export class NotUnderwayError extends Error {
  /** 422 `details[].field` — 화면이 해당 입력창 아래에 메시지를 붙인다. */
  readonly field?: string

  constructor(message: string, options?: { field?: string; cause?: unknown }) {
    super(message, { cause: options?.cause })
    this.name = 'NotUnderwayError'
    this.field = options?.field
  }
}

interface ServerFuelUse {
  id: string
  consumer_type: string
  fuel_type: string
  fuel_ton: number
  cf_used: number
}

interface ServerPeriod {
  id: string
  vessel_id: string
  regulation_year: number
  period_type: string
  started_at: string
  ended_at: string | null
  port_name: string | null
  distance_nm: number
  fuel_uses: ServerFuelUse[]
}

function toFuelUse(raw: ServerFuelUse): FuelUse {
  return {
    id: raw.id,
    consumerType: raw.consumer_type,
    fuelType: raw.fuel_type,
    fuelTon: raw.fuel_ton,
    cfUsed: raw.cf_used,
  }
}

function toPeriod(raw: ServerPeriod): Period {
  return {
    id: raw.id,
    vesselId: raw.vessel_id,
    regulationYear: raw.regulation_year,
    periodType: raw.period_type,
    startedAt: raw.started_at,
    endedAt: raw.ended_at,
    portName: raw.port_name,
    distanceNm: raw.distance_nm,
    fuelUses: (raw.fuel_uses ?? []).map(toFuelUse),
  }
}

interface ServerError {
  error?: {
    message?: string
    details?: Array<{ field?: string; message?: string }>
  }
}

export function createApiNotUnderwayProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): NotUnderwayProvider {
  const call = async (
    path: string,
    init: RequestInit = {},
  ): Promise<Record<string, unknown> | null> => {
    let response: Response
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        credentials: 'include',
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init.body ? { 'Content-Type': 'application/json' } : {}),
          ...csrfHeaders(),
          ...init.headers,
        },
      })
    } catch (cause) {
      throw new NotUnderwayError('서버에 연결하지 못했습니다.', { cause })
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new NotUnderwayError('세션이 만료되었습니다.')
    }

    const body = (await response.json().catch(() => null)) as
      | (Record<string, unknown> & ServerError)
      | null

    if (!response.ok) {
      const detail = body?.error?.details?.[0]
      throw new NotUnderwayError(
        // 서버 문구가 원인을 가장 정확히 안다 — 겹침이면 상대 구간의 시각까지 담긴다.
        body?.error?.message ?? `요청에 실패했습니다 (HTTP ${response.status}).`,
        { field: detail?.field },
      )
    }
    return body
  }

  const readPeriod = (body: Record<string, unknown> | null): Period => {
    const data = body?.data as ServerPeriod | undefined
    if (!data) throw new NotUnderwayError('응답 형식이 올바르지 않습니다.')
    return toPeriod(data)
  }

  return {
    async list(vesselId: string): Promise<PeriodList> {
      const body = await call(`/vessels/${vesselId}/not-underway-periods`)
      const meta = (body?.meta ?? {}) as {
        period_types?: string[]
        consumer_types?: string[]
        fuel_types?: string[]
      }
      /*
       * 선택지는 서버가 준다. 비어 오면 폼을 그리지 않는다 — 화면이 기본값을 지어
       * 내면 DB CHECK 제약과 갈라지고, 사용자는 저장 단계에서야 거부를 만난다.
       */
      return {
        periods: ((body?.data ?? []) as ServerPeriod[]).map(toPeriod),
        periodTypes: meta.period_types ?? [],
        consumerTypes: meta.consumer_types ?? [],
        fuelTypes: meta.fuel_types ?? [],
      }
    },

    async create(vesselId: string, draft: PeriodDraft): Promise<Period> {
      const body = await call(`/vessels/${vesselId}/not-underway-periods`, {
        method: 'POST',
        body: JSON.stringify({
          period_type: draft.periodType,
          started_at: draft.startedAt,
          ended_at: draft.endedAt,
          port_name: draft.portName,
          distance_nm: Number(draft.distanceNm),
          fuel_uses: draft.fuelUses.map((fu) => ({
            consumer_type: fu.consumerType,
            fuel_type: fu.fuelType,
            fuel_ton: Number(fu.fuelTon),
          })),
          /*
           * `regulation_year`를 보내지 않는다 — 서버가 `started_at`의 연도로 채운다.
           * 연말을 걸치는 구간에서만 판단이 갈리는데, 그 경우를 위해 모든 입력에
           * 연도 칸을 두면 대부분의 사용자가 틀릴 기회를 얻는다.
           */
        }),
      })
      return readPeriod(body)
    },

    async close(periodId: string, endedAt: string): Promise<Period> {
      const body = await call(`/not-underway-periods/${periodId}`, {
        method: 'PATCH',
        body: JSON.stringify({ ended_at: endedAt }),
      })
      return readPeriod(body)
    },

    async remove(periodId: string): Promise<void> {
      await call(`/not-underway-periods/${periodId}`, { method: 'DELETE' })
    },
  }
}
