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
  /**
   * 항차 시각 4종 (`#873`). 서버가 주는 ISO 8601 문자열 그대로 둔다.
   *
   * **`Date`로 바꾸지 않는다** — 화면이 쓰는 곳은 실적 폼의 초기값뿐이고, 거기서
   * 다시 `datetime-local` 문자열로 내려간다. 중간에 `Date`를 거치면 왕복마다
   * 브라우저 표준시각 해석이 한 번 더 끼어든다.
   */
  plannedDepartureAt: string | null
  plannedArrivalAt: string | null
  actualDepartureAt: string | null
  actualArrivalAt: string | null
  fuelUses: VoyageFuelUse[]
}

/**
 * 생성 폼의 연료 한 줄 (`#636`).
 *
 * 종전에는 `VoyageDraft`가 `fuelType`·`plannedFuelTon`을 **단일 값**으로 들고 있어
 * 화면으로 만든 항차는 **연료가 반드시 한 종**이었다. 서버(`API_SPEC §3.3`
 * `fuel_uses[]`)·스키마(`DB_SCHEMA §2.4` N행)·실적 입력 폼은 이미 다행이었고,
 * **생성 축만 단일로 남아 있었다**(`#610` 잔여).
 */
export interface VoyageFuelDraft {
  fuelType: string
  plannedFuelTon: string
}

/** 생성 폼이 만드는 값 — `API_SPEC §3.3` 요청 본문. */
export interface VoyageDraft {
  voyageNo: string
  departurePortName: string
  arrivalPortName: string
  plannedDistanceNm: string
  plannedSpeedKn: string
  /**
   * 계획 출항·도착 시각 (`#873`). `datetime-local` 값(`2026-06-01T09:00`)이며
   * 빈 문자열은 「보내지 않는다」다.
   *
   * **종전에는 이 두 칸이 화면에 없었다.** 서버는 `§3.3`에서 처음부터 받고
   * 있었는데(`planned_departure_at`·`planned_arrival_at`) 화면이 보내지 않아,
   * 화면으로 만든 항차는 **출항 시각이 영원히 `null`**이었다. 그 항차를
   * 진행 중으로 옮기면 시뮬레이션 시계가 `departure_at is None`에서 곧바로
   * 거리·연료 **0**을 돌려준다(`services/simulation_clock.py:177`) — 누적에
   * 조용히 0으로 기여한다.
   */
  plannedDepartureAt: string
  plannedArrivalAt: string
  /** optional — `INCLUDE_AS_PLAN` 전환 시점에만 필수(`§3.3` [#150]). */
  regulationYear: string
  /** 최소 한 줄 — 서버가 `min_length=1`을 요구한다(`§3.3`). */
  fuelUses: VoyageFuelDraft[]
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
  /**
   * 실제 출항·도착 시각 (`#873`). 서버는 `§3.6`에서 둘 다 받는다.
   *
   * 실적 출항 시각이 계획보다 **먼저 읽힌다**(`services/cii_current.py:429`
   * `actual_departure_at or planned_departure_at`). 도착 실적은 시계의 상한이라,
   * 이 칸이 없으면 「도착 실적을 입력하면 확정됩니다」라는 결과 화면 문구
   * (`voyage-cii/resultRules.ts`)가 **가리키는 입력 칸이 제품에 없는** 상태가 된다.
   */
  actualDepartureAt: string
  actualArrivalAt: string
  /** 연료별 실적. 키는 `fuelType`. 빈 문자열은 「변경 없음」이다. */
  actualFuelTon: Record<string, string>
}
