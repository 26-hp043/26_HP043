/**
 * 항차 관리 화면이 쓰는 형태 — `API_SPEC §3.1`~`§3.6` (`#610`).
 *
 * ## 왜 `VoyageOption`을 재사용하지 않는가
 *
 * `GET /vessels/{id}/voyages`를 부르는 곳이 이미 둘이다.
 *
 * | 소비처 | 필요한 것 |
 * |---|---|
 * | `layout/voyageCatalog.ts` | 상단바 셀렉트 — `id` · 표시 이름 · `status` |
 * | `features/reports/apiProvider.ts` | 보고서 대상 — 위 + `regulationYear` · 출도착항 · `reportable` |
 * | 여기 | 위 + 계획값 · 실적값 · 연료 사용 |
 *
 * **같은 엔드포인트지만 필요한 투영이 다르다.** 하나로 합치면 상단바 셀렉트가
 * 쓰지도 않을 연료 배열을 들고 다니게 된다. 대신 **이름을 다르게** 준다 —
 * 위 두 곳이 이미 `VoyageOption`이라는 같은 이름을 서로 다른 모양으로 쓰고 있어,
 * 세 번째로 같은 이름을 얹으면 import 한 줄만 보고는 무엇인지 알 수 없다.
 */

/** `API_SPEC §3.5` 상태. 서버의 CHECK 제약과 같은 집합이다. */
export type VoyageStatus =
  | 'DRAFT'
  | 'PLANNED'
  | 'IN_PROGRESS'
  | 'COMPLETED'
  | 'CONFIRMED'
  | 'CANCELLED'
  | 'ARCHIVED'

/** `API_SPEC §3.5` 연간 반영 정책 (`PRD §8.1.2`). */
export type InclusionPolicy = 'EXCLUDE' | 'INCLUDE_AS_PLAN' | 'INCLUDE_AS_ACTUAL'

/**
 * 연료 한 줄.
 *
 * 계획과 실적을 **한 객체에 둘 다** 담는다 — `PRD §8.4`가 둘을 모두 보존하라고
 * 정했고, 화면도 나란히 보여 주어야 계획 대비 실적이 읽힌다.
 */
export interface VoyageFuelUse {
  fuelType: string
  plannedFuelTon: number | null
  actualFuelTon: number | null
}

export interface ManagedVoyage {
  id: string
  voyageNo: string | null
  status: VoyageStatus
  inclusionPolicy: InclusionPolicy
  regulationYear: number | null
  departurePortName: string | null
  arrivalPortName: string | null
  plannedDistanceNm: number | null
  plannedSpeedKn: number | null
  actualDistanceNm: number | null
  actualAvgSpeedKn: number | null
  fuelUses: VoyageFuelUse[]
}

/** 생성 폼이 만드는 값 — `API_SPEC §3.3` 요청 본문. */
export interface VoyageDraft {
  voyageNo: string
  departurePortName: string
  arrivalPortName: string
  plannedDistanceNm: string
  plannedSpeedKn: string
  /** optional — `INCLUDE_AS_PLAN` 전환 시점에만 필수(`§3.3` [#150]). */
  regulationYear: string
  fuelType: string
  plannedFuelTon: string
}

/**
 * 실적 폼이 만드는 값 — `API_SPEC §3.6` 요청 본문.
 *
 * **계획값 항목이 없다.** 요청 본문에 `planned_*`가 없는 것이 계약이고,
 * 화면도 같은 규율을 지킨다(`PRD §8.4` 계획값 보존).
 */
export interface ActualsDraft {
  actualDistanceNm: string
  actualAvgSpeedKn: string
  /** 연료별 실적. 키는 `fuelType`. 빈 문자열은 「변경 없음」이다. */
  actualFuelTon: Record<string, string>
}
