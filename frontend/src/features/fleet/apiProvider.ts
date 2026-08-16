import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import type { FleetProvider, FleetSnapshot, FleetVessel } from './types'

/**
 * 선대 요약 실 API provider — `GET /fleet/summary` (`API_SPEC §2.8` · `#350`).
 *
 * ## 화면에 임시값을 심지 않는다
 *
 * 이 화면에는 한때 가상 선박 10척이 프론트엔드에 하드코딩돼 있었다. 그럴듯해
 * 보이지만 **아무 데이터도 없는 상태**였고, 화면만 보고는 그 값이 어디서 왔는지 알
 * 수 없다. 걷어내고 **서버가 주는 것만 그린다.**
 *
 * ## 수치를 되돌리지 않는다
 *
 * 응답의 CII 값은 문자열이다(`API_SPEC §1.7`). `parseFloat`으로 되돌리면 Layer 1이
 * `Decimal`로 지킨 정밀도가 그 순간 사라진다. 화면은 표시만 하므로 문자열 그대로 쓴다.
 */

/** 서버가 이 엔드포인트를 주지 못하는 상태. 화면이 「데이터 없음」과 구분해 쓴다. */
export class FleetUnavailableError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'FleetUnavailableError'
  }
}

interface ServerVessel {
  vessel_id: string
  name: string
  ship_type: string
  imo_number: string
  underway_state: string | null
  detail_status: string | null
  current_lat: string | null
  current_lon: string | null
  position_updated_at: string | null
  data_available: boolean
  ytd_attained_cii: string | null
  ytd_required_cii: string | null
  ytd_rating: string | null
  risk_level: string | null
  risk_reasons: string[]
  days_to_d: number | null
  days_to_d_reason: string | null
}

interface ServerSummary {
  total: number
  under_way: number
  not_under_way: number
  unknown_state: number
  rating_distribution: Record<string, number>
  at_risk: number
  no_data: number
}

interface ServerBody {
  data?: {
    as_of?: string
    regulation_year?: number
    summary?: ServerSummary
    vessels?: ServerVessel[]
    actions?: Array<{
      vessel_id: string
      vessel_name: string
      severity: string
      reason: string
      message: string
    }>
  }
}

function toVessel(raw: ServerVessel): FleetVessel {
  return {
    id: raw.vessel_id,
    name: raw.name,
    shipType: raw.ship_type,
    imoNumber: raw.imo_number,
    underwayState:
      raw.underway_state === 'UNDER_WAY' || raw.underway_state === 'NOT_UNDER_WAY'
        ? raw.underway_state
        : null,
    detailStatus: raw.detail_status,
    lat: raw.current_lat,
    lon: raw.current_lon,
    positionUpdatedAt: raw.position_updated_at,
    dataAvailable: raw.data_available,
    ytdAttainedCii: raw.ytd_attained_cii,
    ytdRequiredCii: raw.ytd_required_cii,
    ytdRating: raw.ytd_rating as FleetVessel['ytdRating'],
    riskLevel: raw.risk_level as FleetVessel['riskLevel'],
    riskReasons: (raw.risk_reasons ?? []) as FleetVessel['riskReasons'],
    daysToD: raw.days_to_d,
    daysToDReason: raw.days_to_d_reason as FleetVessel['daysToDReason'],
  }
}

/** 등급 분포는 A~E 다섯 키가 항상 있어야 화면이 0을 표시할 수 있다. */
function toDistribution(raw: Record<string, number> | undefined) {
  return { A: 0, B: 0, C: 0, D: 0, E: 0, ...(raw ?? {}) }
}

export function createApiFleetProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): FleetProvider {
  return {
    async load(): Promise<FleetSnapshot> {
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/fleet/summary`, {
          method: 'GET',
          credentials: 'include',
          headers: { Accept: 'application/json', ...csrfHeaders() },
        })
      } catch (cause) {
        throw new FleetUnavailableError('선대 현황 서버에 연결하지 못했습니다.', { cause })
      }

      // 세션 만료는 화면이 처리할 문제가 아니다 — 로그인으로 보낸다(기능①과 동일).
      if (response.status === 401) {
        redirectToLogin()
        throw new FleetUnavailableError('세션이 만료되었습니다.')
      }

      if (!response.ok) {
        throw new FleetUnavailableError(
          `선대 현황을 불러오지 못했습니다 (HTTP ${response.status}).`,
        )
      }

      const body = (await response.json()) as ServerBody
      const data = body.data
      /*
       * `as_of`가 없으면 형식 오류다. 이 값은 「어느 시점 데이터인가」를 특정하는
       * 유일한 근거이고(`TECH_SPEC §5.4.1`), 없으면 기준 시각을 표시할 수 없다.
       */
      if (!data?.as_of) {
        throw new FleetUnavailableError('선대 현황 응답 형식이 올바르지 않습니다.')
      }

      const summary = data.summary
      return {
        asOf: data.as_of,
        regulationYear: data.regulation_year ?? new Date(data.as_of).getFullYear(),
        counts: {
          total: summary?.total ?? 0,
          underWay: summary?.under_way ?? 0,
          notUnderWay: summary?.not_under_way ?? 0,
          unknownState: summary?.unknown_state ?? 0,
          ratingDistribution: toDistribution(summary?.rating_distribution),
          atRisk: summary?.at_risk ?? 0,
          noData: summary?.no_data ?? 0,
        },
        vessels: (data.vessels ?? []).map(toVessel),
        actions: (data.actions ?? []).map((a) => ({
          vesselId: a.vessel_id,
          vesselName: a.vessel_name,
          severity: a.severity === 'critical' ? 'critical' : 'warning',
          reason: a.reason as FleetSnapshot['actions'][number]['reason'],
          message: a.message,
        })),
      }
    },
  }
}
