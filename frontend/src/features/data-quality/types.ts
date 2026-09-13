/**
 * 데이터 점검 — `GET /fleet/data-quality` (`API_SPEC §2.16` · `UIFLOW 2-11` · #513).
 *
 * 수치는 **문자열 그대로** 둔다(`API_SPEC §1.7`). 화면은 표시만 한다.
 */

/** `DESIGN_SYSTEM §2.3.1` 표 순서 — 서버가 이 순서로 정렬해 준다. */
export const SEVERITIES = ['SUBSTITUTED', 'UNAVAILABLE', 'ANOMALY', 'UNCONFIRMED'] as const
export type Severity = (typeof SEVERITIES)[number]

export type Rating = 'A' | 'B' | 'C' | 'D' | 'E'

/** 그 항차를 뺀 누적 CII와의 차이 (`PRD §17.4.2`). */
interface CiiImpact {
  attainedCii: string
  attainedCiiWithout: string
  /** 누적 − 뺀 누적. **양수면 이 항차가 누적 CII를 높이고 있다** */
  delta: string
  rating: Rating | null
  ratingWithout: Rating | null
}

export interface DataQualityIssue {
  severity: Severity
  vesselId: string
  vesselName: string
  /** 선박 단위 문제(계산 불가)면 `null` */
  voyageId: string | null
  voyageNo: string | null
  /** 사유 코드 — 대체 `FUEL:HFO`·`DISTANCE` · 이상치 `FUEL_VS_MODEL` 등 */
  codes: string[]
  cii: CiiImpact | null
  /** `cii`가 `null`인 이유. 선박 단위 문제면 이것도 `null` */
  ciiReason: string | null
}

interface DataQualityVessel {
  vesselId: string
  vesselName: string
  dataAvailable: boolean
  unavailableReason: string | null
  ytdAttainedCii: string | null
  ytdRating: Rating | null
  voyageCount: number
  /** 0~1 비율 문자열. 배출이 없거나 계산할 수 없으면 `null` */
  completenessRatio: string | null
}

export interface DataQualitySnapshot {
  regulationYear: number
  counts: Record<Severity, number>
  /** 이상치를 **판정하지 못한** 항차 수 — 0건과 섞지 않는다 */
  anomalyUnjudged: number
  completenessRatio: string | null
  vessels: DataQualityVessel[]
  issues: DataQualityIssue[]
}

export interface DataQualityProvider {
  load(regulationYear?: number): Promise<DataQualitySnapshot>
}
