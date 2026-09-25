import { SESSION_EXPIRED_MESSAGE, csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../../api/base'
import {
  SEVERITIES,
  type CompletenessBreakdown,
  type DataQualityIssue,
  type DataQualityProvider,
  type DataQualitySnapshot,
  type PublicRecord,
  type PublicRecordField,
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

/** `API_SPEC §2.16` `public_record.mismatches[]` (#1197). 옛 서버는 이 필드 자체가 없다. */
interface ServerPublicRecordMismatch {
  field: string
  entered_at: string
  recorded_at: string
  difference_minutes: number
  port_authority_code: string
  port_authority_name: string | null
}

interface ServerPublicRecord {
  source: string
  fetched_at: string
  mismatches: ServerPublicRecordMismatch[]
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
  /** 옛 서버는 필드 자체가 없다 — `PUBLIC_RECORD`가 아닌 행은 `null`이다. */
  public_record?: ServerPublicRecord | null
}

interface ServerBody {
  data?: {
    regulation_year: number
    summary: {
      substituted_count: number
      unavailable_count: number
      anomaly_count: number
      unconfirmed_count: number
      /** 옛 서버는 이 필드가 없다 — 그때는 0으로 읽는다. */
      public_record_count?: number
      anomaly_unjudged_count: number
      completeness_ratio: string | null
      completeness?: ServerCompleteness
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
      completeness?: ServerCompleteness | null
    }>
    issues: ServerIssue[]
  }
}

/** `API_SPEC §2.16` `completeness` (#1532) — 톤 문자열 그대로 옮긴다. */
interface ServerCompleteness {
  total_co2_ton: string
  measured_co2_ton: string
  excluded_unavailable_co2_ton: string
  excluded_substituted_co2_ton: string
  excluded_anomaly_co2_ton: string
}

function toCompleteness(raw: ServerCompleteness | null | undefined): CompletenessBreakdown | null {
  if (!raw) return null
  return {
    totalCo2Ton: raw.total_co2_ton,
    measuredCo2Ton: raw.measured_co2_ton,
    excludedUnavailableCo2Ton: raw.excluded_unavailable_co2_ton,
    excludedSubstitutedCo2Ton: raw.excluded_substituted_co2_ton,
    excludedAnomalyCo2Ton: raw.excluded_anomaly_co2_ton,
  }
}

function toSeverity(raw: string): Severity {
  if ((SEVERITIES as readonly string[]).includes(raw)) return raw as Severity
  throw new DataQualityUnavailableError(`알 수 없는 점검 항목입니다: ${raw}`)
}

/**
 * 공적 기록 대조 (#1197). 필드 하나하나까지 검증하지 않는다 — `cii_impact`를 옮길 때와 같은
 * 방침이다(서버 계약을 믿고 그대로 옮긴다). **필드 자체가 없으면**(옛 서버) `null`이다.
 */
function toPublicRecord(raw: ServerPublicRecord | null | undefined): PublicRecord | null {
  if (!raw) return null
  return {
    source: raw.source,
    fetchedAt: raw.fetched_at,
    mismatches: raw.mismatches.map((m) => ({
      field: m.field as PublicRecordField,
      enteredAt: m.entered_at,
      recordedAt: m.recorded_at,
      differenceMinutes: m.difference_minutes,
      portAuthorityCode: m.port_authority_code,
      portAuthorityName: m.port_authority_name,
    })),
  }
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
    publicRecord: toPublicRecord(raw.public_record),
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
          PUBLIC_RECORD: s.public_record_count ?? 0,
        },
        anomalyUnjudged: s.anomaly_unjudged_count,
        completenessRatio: s.completeness_ratio,
        completeness: toCompleteness(s.completeness) ?? undefined,
        vessels: data.vessels.map((v) => ({
          vesselId: v.vessel_id,
          vesselName: v.vessel_name,
          dataAvailable: v.data_available,
          unavailableReason: v.unavailable_reason,
          ytdAttainedCii: v.ytd_attained_cii,
          ytdRating: v.ytd_rating as Rating | null,
          voyageCount: v.voyage_count,
          completenessRatio: v.completeness_ratio,
          completeness: toCompleteness(v.completeness),
        })),
        issues: data.issues.map(toIssue),
      }
    },
  }
}
