import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import {
  SEVERITIES,
  type DataQualityIssue,
  type DataQualityProvider,
  type DataQualitySnapshot,
  type Rating,
  type Severity,
} from './types'

/**
 * 데이터 점검 실 API provider — `GET /fleet/data-quality` (`API_SPEC §2.16` · #513).
 *
 * **모르는 심각도는 버리지 않고 오류로 낸다.** 조용히 버리면 서버가 새 심각도를 더한 날
 * 그 건수가 화면에서 사라져 「해당 없음」으로 읽힌다 — 이 화면이 막으려는 바로 그 형태다.
 */

export class DataQualityUnavailableError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'DataQualityUnavailableError'
  }
}

interface ServerIssue {
  severity: string
  vessel_id: string
  vessel_name: string
  voyage_id: string | null
  voyage_no: string | null
  codes: string[]
  cii_impact: {
    attained_cii: string
    attained_cii_without: string
    delta: string
    rating: string | null
    rating_without: string | null
  } | null
  cii_impact_reason: string | null
}

interface ServerBody {
  data?: {
    regulation_year: number
    summary: {
      substituted_count: number
      unavailable_count: number
      anomaly_count: number
      unconfirmed_count: number
      anomaly_unjudged_count: number
      completeness_ratio: string | null
    }
    vessels: Array<{
      vessel_id: string
      vessel_name: string
      data_available: boolean
      unavailable_reason: string | null
      ytd_attained_cii: string | null
      ytd_rating: string | null
      voyage_count: number
      completeness_ratio: string | null
    }>
    issues: ServerIssue[]
  }
}

function toSeverity(raw: string): Severity {
  if ((SEVERITIES as readonly string[]).includes(raw)) return raw as Severity
  throw new DataQualityUnavailableError(`알 수 없는 점검 항목입니다: ${raw}`)
}

function toIssue(raw: ServerIssue): DataQualityIssue {
  return {
    severity: toSeverity(raw.severity),
    vesselId: raw.vessel_id,
    vesselName: raw.vessel_name,
    voyageId: raw.voyage_id,
    voyageNo: raw.voyage_no,
    codes: raw.codes,
    cii: raw.cii_impact
      ? {
          attainedCii: raw.cii_impact.attained_cii,
          attainedCiiWithout: raw.cii_impact.attained_cii_without,
          delta: raw.cii_impact.delta,
          rating: raw.cii_impact.rating as Rating | null,
          ratingWithout: raw.cii_impact.rating_without as Rating | null,
        }
      : null,
    ciiReason: raw.cii_impact_reason,
  }
}

export function createApiDataQualityProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): DataQualityProvider {
  return {
    async load(regulationYear?: number): Promise<DataQualitySnapshot> {
      const query = regulationYear === undefined ? '' : `?regulation_year=${regulationYear}`
      let response: Response
      try {
        response = await fetchImpl(`${baseUrl}/fleet/data-quality${query}`, {
          method: 'GET',
          credentials: 'include',
          headers: { Accept: 'application/json', ...csrfHeaders() },
        })
      } catch (cause) {
        throw new DataQualityUnavailableError('데이터 점검 서버에 연결하지 못했습니다.', { cause })
      }
      if (response.status === 401) {
        redirectToLogin()
        throw new DataQualityUnavailableError(SESSION_EXPIRED_MESSAGE)
      }
      if (!response.ok) {
        throw new DataQualityUnavailableError(
          `데이터 점검 결과를 불러오지 못했습니다 (HTTP ${response.status}).`,
        )
      }
      const data = ((await response.json()) as ServerBody).data
      if (!data) {
        throw new DataQualityUnavailableError('데이터 점검 응답 형식이 올바르지 않습니다.')
      }
      const s = data.summary
      return {
        regulationYear: data.regulation_year,
        counts: {
          SUBSTITUTED: s.substituted_count,
          UNAVAILABLE: s.unavailable_count,
          ANOMALY: s.anomaly_count,
          UNCONFIRMED: s.unconfirmed_count,
        },
        anomalyUnjudged: s.anomaly_unjudged_count,
        completenessRatio: s.completeness_ratio,
        vessels: data.vessels.map((v) => ({
          vesselId: v.vessel_id,
          vesselName: v.vessel_name,
          dataAvailable: v.data_available,
          unavailableReason: v.unavailable_reason,
          ytdAttainedCii: v.ytd_attained_cii,
          ytdRating: v.ytd_rating as Rating | null,
          voyageCount: v.voyage_count,
          completenessRatio: v.completeness_ratio,
        })),
        issues: data.issues.map(toIssue),
      }
    },
  }
}
