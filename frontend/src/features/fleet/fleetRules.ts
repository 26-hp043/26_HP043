import type { Rating } from '../voyage-cii/types'
import type { DaysReason, FleetVessel, RiskReason } from './types'

/**
 * 선대 화면의 표시 규칙.
 *
 * ## 판정을 여기서 하지 않는다
 *
 * 위험 선박 판정(`PRD §3.3.7`)과 KPI 집계는 **서버가 확정한다**(`#350`). 화면이 다시
 * 세면 필터·정렬이 붙었을 때 서버와 달라지고, **그 차이는 눈으로 발견되지 않는다.**
 *
 * 그래서 이 모듈은 **정렬과 문구**만 맡는다 — 서버가 관여하지 않는 영역이다.
 */

/** 나쁜 등급이 큰 값이다 — 정렬 비교용. */
const RATING_ORDER: Record<Rating, number> = { A: 0, B: 1, C: 2, D: 3, E: 4 }

/** 서버가 준 `riskReasons`가 비어 있지 않으면 위험 선박이다. 등급으로 재판정하지 않는다. */
export function isAtRisk(vessel: FleetVessel): boolean {
  return vessel.riskReasons.length > 0
}

export type SortKey = 'risk' | 'name' | 'grade'

/** 등급이 없는 선박(실적 없음)은 가장 뒤로 — 나쁜 등급으로 오해되면 안 된다. */
function ratingRank(vessel: FleetVessel): number {
  return vessel.ytdRating === null ? -1 : RATING_ORDER[vessel.ytdRating]
}

/**
 * 선박 목록 정렬.
 *
 * 기본값이 **위험도순**인 것은 이 화면의 목적이 「위험 선박 식별」이기 때문이다
 * (`PRD §2.3` 관제 가능성). 이름순이 기본이면 위험 선박이 목록 아래로 숨는다.
 */
export function sortVessels(vessels: FleetVessel[], key: SortKey): FleetVessel[] {
  const copy = [...vessels]
  if (key === 'name') return copy.sort((a, b) => a.name.localeCompare(b.name))
  if (key === 'grade') return copy.sort((a, b) => ratingRank(b) - ratingRank(a))

  // 위험도순 — ⑴ 규제 트리거 선박 먼저 ⑵ YTD 등급이 나쁜 순 ⑶ 이름
  return copy.sort((a, b) => {
    const risk = Number(isAtRisk(b)) - Number(isAtRisk(a))
    if (risk !== 0) return risk
    const grade = ratingRank(b) - ratingRank(a)
    if (grade !== 0) return grade
    return a.name.localeCompare(b.name)
  })
}

/** 위험 사유 문구. 규제 용어는 `PRD §3.3.7`을 따른다. */
export function riskReasonText(reason: RiskReason): string {
  return reason === 'E_THIS_YEAR'
    ? 'E등급 1년차 — SEEMP Part III 시정조치계획 대상'
    : 'D등급 3년 연속 — SEEMP Part III 시정조치계획 대상'
}

/**
 * 「D등급 진입까지」 표시 문구.
 *
 * **숫자를 못 낸 것과 0일인 것을 같은 문구로 쓰지 않는다.** 서버가 사유를 따로 주는
 * 이유가 여기 있다(`API_SPEC §2.8`).
 */
export function daysToDText(days: number | null, reason: DaysReason | null): string {
  if (days !== null) return `D등급까지 ${days}일`
  switch (reason) {
    case 'ALREADY_AT_OR_BELOW':
      return 'D등급 이하'
    case 'NOT_THIS_YEAR':
      return '올해 중 진입 없음'
    case 'NOT_UNDER_WAY':
      // 정박 중에는 값이 요동쳐 서버가 산정하지 않는다. 그 사실을 그대로 말한다.
      return '정박 중 — 산정 안 함'
    default:
      return '실적 없음'
  }
}

/** 운항 상태 표시. 상태 미기록을 「정박」으로 적지 않는다 — 없는 사실이 된다. */
export function underwayStateText(vessel: FleetVessel): string {
  if (vessel.underwayState === 'UNDER_WAY') return '운항 중'
  if (vessel.underwayState === 'NOT_UNDER_WAY') return '정박 중'
  return '상태 미기록'
}

/**
 * 기준 시각을 「n분 전」으로.
 *
 * 상대 시각만 보여 주면 어느 시점 데이터인지 특정할 수 없으므로, 화면은 **원본
 * 시각도 함께** 노출한다.
 */
export function relativeTime(asOf: string, now: Date): string {
  const minutes = Math.floor((now.getTime() - new Date(asOf).getTime()) / 60_000)
  if (minutes < 1) return '방금'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  return `${Math.floor(hours / 24)}일 전`
}

/**
 * 등급이 없는 선박의 표시 문구 — **사유를 가려 붙인다** (#419).
 *
 * 「실적 없음」(항차를 등록하세요)과 「제원 미비」(DWT/GT를 입력하세요)는 사용자의
 * 다음 행동이 다르다. 하나의 문구로 묶으면 제원이 비어 있는데 항차만 등록하고
 * 「왜 값이 안 나오지」를 겪게 된다.
 */
export function noGradeText(vessel: FleetVessel): string {
  if (vessel.unavailableReason === 'MISSING_SPECS') return '제원 미비'
  if (vessel.unavailableReason === 'CALCULATION_FAILED') return '계산 불가'
  return '실적 없음'
}

/**
 * 경고 배너 문구 — `PRD §6.3` 확정 문구(`#352`).
 *
 * > 대시보드 경고 배너 — 위험 선박 존재 시: `시정조치계획 대상 위험 선박 {n}척`
 *
 * **위험 선박이 없으면 배너를 표시하지 않는다**(같은 절). 0척 배너를 상시 띄우면
 * 경고가 배경이 되어 의미를 잃는다.
 */
export function warningBannerText(atRisk: number): string | null {
  if (atRisk <= 0) return null
  return `시정조치계획 대상 위험 선박 ${atRisk}척`
}

/**
 * 배너 보조 문구 — 가장 임박한 D등급 진입 잔여일수.
 *
 * `#351` 체크리스트가 배너에 요구한 항목이다. 여러 척이면 **가장 짧은 것**을 쓴다 —
 * 가장 먼저 대응해야 하는 값이다.
 */
export function soonestDaysToD(
  vessels: FleetVessel[],
): { name: string; days: number } | null {
  let best: { name: string; days: number } | null = null
  for (const vessel of vessels) {
    if (vessel.daysToD === null) continue
    if (best === null || vessel.daysToD < best.days) {
      best = { name: vessel.name, days: vessel.daysToD }
    }
  }
  return best
}
