import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type { CapacityBasis } from '../voyage-cii/types'
import type { PositionPayload } from './positionRules'
import type { CiiYear, VesselDetail, VesselDetailProvider, VesselSpec } from './types'

/**
 * 선박 상세 provider — `GET /vessels/{id}` + `GET /vessels/{id}/cii-history`.
 *
 * ## 두 호출을 병렬로 한다
 *
 * 서로 의존하지 않으므로 순차로 하면 대기 시간이 두 배가 된다. 한쪽이 실패하면
 * 화면 전체가 실패한다 — 제원 없이 이력만, 또는 그 반대로 반쪽 화면을 그리면
 * 사용자가 무엇이 빠졌는지 알 수 없다.
 *
 * ## 수치를 되돌리지 않는다
 *
 * CII 값은 문자열이다(`API_SPEC §1.7`). `parseFloat`으로 되돌리면 Layer 1이
 * `Decimal`로 지킨 정밀도가 사라진다.
 */

export class VesselDetailError extends Error {
  /** 404 — 없는 선박. 화면이 「불러오기 실패」와 다르게 표시한다. */
  readonly notFound: boolean

  /**
   * 422 `details[].field` — 화면이 해당 입력창 아래에 붙인다 (`#369`).
   *
   * 서버 문구를 다시 쓰지 않는다. 상태 조합 거부는 **어느 조합이 왜 안 되는지**를
   * 서버가 더 정확히 알고 있고(`services/vessel.py`), 화면 사본이 갈라졌을 때
   * 사용자에게 사실을 전하는 유일한 경로다.
   */
  readonly field?: string

  constructor(
    message: string,
    options?: { notFound?: boolean; field?: string; cause?: unknown },
  ) {
    super(message, { cause: options?.cause })
    this.name = 'VesselDetailError'
    this.notFound = options?.notFound ?? false
    this.field = options?.field
  }
}

interface ServerError {
  error?: { message?: string; details?: Array<{ field?: string; message?: string }> }
}

interface ServerVessel {
  id: string
  name: string
  imo_number: string
  ship_type: string
  deadweight: number | string | null
  gross_tonnage: number | string | null
  reference_speed_kn: number | string | null
  reference_daily_foc_ton: number | string | null
  default_fuel_type: string | null
  underway_state: string | null
  detail_status: string | null
  current_lat: number | string | null
  current_lon: number | string | null
  position_updated_at: string | null
}

interface ServerYear {
  regulation_year: number
  status: string
  data_available: boolean
  reason: string | null
  attained_cii: string | null
  required_cii: string | null
  rating: string | null
  voyage_count: number
  total_distance_nm: string | null
  total_fuel_ton: string | null
}

/** 숫자로 와도 문자열로 통일한다 — 화면은 표시만 하므로 형을 하나로 둔다. */
function asText(value: number | string | null): string | null {
  return value === null || value === undefined ? null : String(value)
}

function toSpec(raw: ServerVessel): VesselSpec {
  return {
    id: raw.id,
    name: raw.name,
    imoNumber: raw.imo_number,
    shipType: raw.ship_type,
    deadweight: asText(raw.deadweight),
    grossTonnage: asText(raw.gross_tonnage),
    referenceSpeedKn: asText(raw.reference_speed_kn),
    referenceDailyFocTon: asText(raw.reference_daily_foc_ton),
    defaultFuelType: raw.default_fuel_type,
    underwayState:
      raw.underway_state === 'UNDER_WAY' || raw.underway_state === 'NOT_UNDER_WAY'
        ? raw.underway_state
        : null,
    detailStatus: raw.detail_status,
    lat: asText(raw.current_lat),
    lon: asText(raw.current_lon),
    positionUpdatedAt: raw.position_updated_at,
  }
}

function toYear(raw: ServerYear): CiiYear {
  return {
    regulationYear: raw.regulation_year,
    status: raw.status === 'CONFIRMED' ? 'CONFIRMED' : 'IN_PROGRESS',
    dataAvailable: raw.data_available,
    reason: raw.reason,
    attainedCii: raw.attained_cii,
    requiredCii: raw.required_cii,
    rating: raw.rating as CiiYear['rating'],
    voyageCount: raw.voyage_count,
    totalDistanceNm: raw.total_distance_nm,
    totalFuelTon: raw.total_fuel_ton,
  }
}

export function createApiVesselDetailProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): VesselDetailProvider {
  const get = async (path: string): Promise<Record<string, unknown>> => {
    let response: Response
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'application/json', ...csrfHeaders() },
      })
    } catch (cause) {
      throw new VesselDetailError('서버에 연결하지 못했습니다.', { cause })
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new VesselDetailError('세션이 만료되었습니다.')
    }
    if (response.status === 404) {
      throw new VesselDetailError('선박을 찾을 수 없습니다.', { notFound: true })
    }
    if (!response.ok) {
      throw new VesselDetailError(`불러오지 못했습니다 (HTTP ${response.status}).`)
    }
    return (await response.json()) as Record<string, unknown>
  }

  /** 변경 호출 — `credentials`·CSRF 배선을 `get`과 같게 둔다 (`#307` 선례). */
  const send = async (path: string, body: unknown): Promise<Record<string, unknown>> => {
    let response: Response
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          ...csrfHeaders(),
        },
        body: JSON.stringify(body),
      })
    } catch (cause) {
      throw new VesselDetailError('서버에 연결하지 못했습니다.', { cause })
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new VesselDetailError('세션이 만료되었습니다.')
    }

    const parsed = (await response.json().catch(() => null)) as
      | (Record<string, unknown> & ServerError)
      | null

    if (response.status === 404) {
      throw new VesselDetailError('선박을 찾을 수 없습니다.', { notFound: true })
    }
    if (!response.ok) {
      const detail = parsed?.error?.details?.[0]
      throw new VesselDetailError(
        parsed?.error?.message ?? `저장하지 못했습니다 (HTTP ${response.status}).`,
        { field: detail?.field },
      )
    }
    return parsed ?? {}
  }

  return {
    async updatePosition(vesselId: string, payload: PositionPayload): Promise<VesselSpec> {
      const body = await send(`/vessels/${vesselId}/position`, payload)
      const vessel = (body.data ?? null) as ServerVessel | null
      if (!vessel) throw new VesselDetailError('응답 형식이 올바르지 않습니다.')
      return toSpec(vessel)
    },

    async load(vesselId: string): Promise<VesselDetail> {
      const [vesselBody, historyBody] = await Promise.all([
        get(`/vessels/${vesselId}`),
        get(`/vessels/${vesselId}/cii-history`),
      ])

      const vessel = (vesselBody.data ?? null) as ServerVessel | null
      const history = (historyBody.data ?? null) as
        | { transport_capacity_basis?: string; years?: ServerYear[] }
        | null
      const meta = (historyBody.meta ?? {}) as { as_of?: string }

      if (!vessel || !history) {
        throw new VesselDetailError('응답 형식이 올바르지 않습니다.')
      }

      /*
       * 축이 없으면 단위를 만들 수 없다. `DESIGN_SYSTEM §4.1`이 고정 문자열을
       * 금지하므로 임의로 `DWT`를 채우지 않는다 — 크루즈선에 `DWT`가 표시되면
       * 화면은 깨지지 않고 내용만 틀린다.
       */
      const basis = history.transport_capacity_basis
      if (basis !== 'DWT' && basis !== 'GT') {
        throw new VesselDetailError('표시 단위의 축을 확인할 수 없습니다.')
      }

      return {
        vessel: toSpec(vessel),
        capacityBasis: basis as CapacityBasis,
        years: (history.years ?? []).map(toYear),
        asOf: meta.as_of ?? '',
      }
    },
  }
}
