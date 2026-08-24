import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString } from '../../display/format'
import type { Rating } from '../voyage-cii/types'
import type {
  DaysReason,
  FleetVessel,
  RiskReason,
  UnavailableReason,
  UnderwayState,
} from './types'

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

/** 표시 순서. `RATING_ORDER`는 정렬 키라 열거에 쓸 수 없다. */
const RATINGS: readonly Rating[] = ['A', 'B', 'C', 'D', 'E']

/** 서버가 준 `riskReasons`가 비어 있지 않으면 위험 선박이다. 등급으로 재판정하지 않는다. */
export function isAtRisk(vessel: { riskReasons: readonly RiskReason[] }): boolean {
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
 *
 * 자릿수·단위는 `§4.2`가 소유한다 (#592). 종전에는 서버 값을 템플릿에 그대로 끼워
 * 넣고 `일`을 리터럴로 붙였다 — 규정이 없어 그럴 수밖에 없었고, 서버가 소수를 보내면
 * 대시보드 카드에 `12.4일`이 나갈 자리였다.
 */
export function daysToDText(days: number | null, reason: DaysReason | null): string {
  if (days !== null) {
    const text = formatDecimalString(String(days), DISPLAY_DIGITS.days)
    return `D등급까지 ${text}${DISPLAY_UNITS.day}`
  }
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

/**
 * YTD CII 표시 문구 — `DESIGN_SYSTEM §4.1` 🔒.
 *
 * §4.1이 CII를 **소수 3자리 고정**으로 정하고 그 이유로 「자릿수 가변 금지, 정렬
 * 붕괴」를 든다. 목록은 값이 세로로 쌓이는 자리라 자릿수가 흔들리면 소수점이 어긋나
 * 그 취지가 바로 깨진다.
 *
 * **종전에는 서버 원본 문자열을 그대로 냈다** — `8.9799` · `21.7250`처럼 4자리로
 * 나갔고, 같은 값을 3자리로 내는 CII 예측·연간 등급 화면과 어긋났다.
 *
 * ## 문구 함수가 자릿수까지 맡는 이유
 *
 * 화면에서 `formatDecimalString`을 직접 부르면 **널 가드를 호출부마다 다시 써야
 * 하고**, vitest에 DOM 환경이 없어 그 선택을 검증할 수 없다. 이 모듈이 이미
 * `daysToDText`·`unavailableText`로 표시 문구를 맡고 있으므로 같은 자리에 둔다.
 *
 * 단위는 붙이지 않는다. CII 단위는 선종의 capacity 축에서 갈리는데(`§4.1` 🔒)
 * 선대 요약 응답에는 그 축이 없다 — 없는 값을 화면이 지어내지 않는다.
 */
export function ytdCiiText(value: string | null): string {
  // 포매터는 십진 문자열이 아니면 던진다. 「없음」은 포맷 대상이 아니다.
  if (value === null) return '—'
  return formatDecimalString(value, DISPLAY_DIGITS.cii)
}

/**
 * 값이 없는 선박의 **짧은 표시 문구** — `#419`.
 *
 * 목록 한 줄에 들어가야 하므로 짧게 쓰고, 사용자가 할 일은
 * {@link unavailableHint}가 문장으로 말한다.
 */
export function unavailableText(reason: UnavailableReason | null): string {
  switch (reason) {
    case 'MISSING_SPEC':
      return '제원 미입력'
    case 'NO_PARAMETERS':
      return '기준값 없음'
    case 'CALCULATION_ERROR':
      return '계산 실패'
    default:
      return '실적 없음'
  }
}

/**
 * 값이 없는 선박에 대해 **사용자가 할 일** — `#419`.
 *
 * 사유를 셋으로 나눈 이유가 여기에 있다. 「실적 없음」은 항차를 등록하면 풀리고,
 * 「제원 미입력」은 선박 정보를 채워야 풀리며, 「기준값 없음」은 **사용자가 할 수 있는
 * 것이 없다** — 이것을 「항차를 등록하세요」로 안내하면 해도 안 되는 일을 시키는 것이다.
 */
export function unavailableHint(reason: UnavailableReason | null): string {
  switch (reason) {
    case 'MISSING_SPEC':
      return '선박 제원(선종·DWT·GT)으로 계산할 수 없습니다. 선박 정보를 확인하세요.'
    case 'NO_PARAMETERS':
      return '이 선종의 규정 기준값이 등록되지 않았습니다. 운영자에게 문의하세요.'
    case 'CALCULATION_ERROR':
      return '계산 중 오류가 발생했습니다. 운영자에게 문의하세요.'
    default:
      return '올해 집계할 항차 실적이 없습니다. 항차를 등록하면 값이 표시됩니다.'
  }
}

/** 운항 상태 표시. 상태 미기록을 「정박」으로 적지 않는다 — 없는 사실이 된다. */
export function underwayStateText(vessel: { underwayState: UnderwayState | null }): string {
  if (vessel.underwayState === 'UNDER_WAY') return '운항 중'
  if (vessel.underwayState === 'NOT_UNDER_WAY') return '정박 중'
  return '상태 미기록'
}

/**
 * `detail_status` 7값의 화면 표기 — `UIFLOW 2-4`가 정한 표 그대로다.
 *
 * | 값 | 표기 | 계산상 구분 |
 * |---|---|---|
 * | `SAILING` | 항해 중 | UNDER_WAY |
 * | `IN_PORT` | 접안 | NOT_UNDER_WAY |
 * | `AT_ANCHOR` | 묘박 | 〃 |
 * | `DRIFTING` | 표류 | 〃 |
 * | `STS` | 선박 간 이적 | 〃 |
 * | `CANAL_TRANSIT` | 운하 통과 | 〃 |
 * | `DRYDOCK` | 드라이독 | 〃 |
 *
 * **화면이 코드를 그대로 내보내고 있었다.** 중소선사 운항관리자에게 `CANAL_TRANSIT`은
 * 읽을 말이 아니다 — `#529`가 화면에서 걷어낸 내부 참조와 같은 부류다.
 *
 * 계산은 `underway_state`(2값)만 보고 화면은 이 7값을 표시한다. 두 축을 나눈 이유는
 * `#346`에 있다.
 *
 * 모르는 값은 **코드를 그대로** 돌려준다(`shipTypeLabel`과 같은 판단). 서버가 여덟
 * 번째 상태를 먼저 추가할 수 있고, 그때 빈칸을 내면 상태가 없는 것처럼 읽힌다.
 */
const DETAIL_STATUS_TEXT: Readonly<Record<string, string>> = {
  SAILING: '항해 중',
  IN_PORT: '접안',
  AT_ANCHOR: '묘박',
  DRIFTING: '표류',
  STS: '선박 간 이적',
  CANAL_TRANSIT: '운하 통과',
  DRYDOCK: '드라이독',
}

/**
 * 서버 원시 문자열 → `UnderwayState` (#719).
 *
 * `GET /vessels`는 `underway_state`를 **문자열**로 준다(`Vessel` 타입). 선대 요약은
 * 이미 좁혀진 값을 주지만 선박 관리는 그렇지 않다. 화면이 각자 `as`로 단언하면
 * **모르는 값이 조용히 「운항 중」으로 흘러든다** — 여기서 한 번만 좁히고,
 * 아는 두 값이 아니면 `null`(상태 미기록)로 떨어뜨린다.
 */
export function toUnderwayState(code: string | null): UnderwayState | null {
  return code === 'UNDER_WAY' || code === 'NOT_UNDER_WAY' ? code : null
}

export function detailStatusText(code: string | null): string | null {
  if (code === null) return null
  return DETAIL_STATUS_TEXT[code] ?? code
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

/* ── 등급 분포 스택 바 ────────────────────────────────────────────── */

export interface DistributionSegment {
  rating: Rating
  count: number
  /** 집계된 선박 수 대비 비율. 폭이자 §10.2의 8% 판정 기준이다. */
  percent: number
}

/**
 * `§10.2`가 등급 확률 스택 바에 정한 임계를 **선대 등급 분포에도 쓴다.**
 *
 * 두 바는 뜻하는 값이 다르지만(확률 vs 척수) **형태가 같다** — 가로 스택 바에
 * 등급 문자를 넣는다. 임계를 따로 정하면 같은 모양이 화면마다 다른 폭에서
 * 글자를 감추게 된다.
 */
export const INLINE_LABEL_MIN_PERCENT = 8

/**
 * 등급 분포를 스택 바 구간으로 만든다.
 *
 * **0척인 등급은 구간을 만들지 않는다** — 폭 0인 조각은 그리는 의미가 없고,
 * 등급이 없다는 사실은 `zeroRatings()`가 따로 말한다. 감추는 것이 아니라
 * **다른 형태로 옮기는 것**이다.
 *
 * 분모는 **집계된 선박 수**다. 산출 불가(`noData`)는 등급이 없으므로 분포에
 * 들어갈 수 없고, 분모에 넣으면 모든 구간이 실제보다 작아 보인다.
 */
export function gradeDistributionSegments(
  distribution: Readonly<Record<Rating, number>>,
): DistributionSegment[] {
  const total = RATINGS.reduce((sum, rating) => sum + distribution[rating], 0)
  if (total === 0) return []
  return RATINGS.filter((rating) => distribution[rating] > 0).map((rating) => ({
    rating,
    count: distribution[rating],
    percent: (distribution[rating] / total) * 100,
  }))
}

/** 0척인 등급. 바에서 빠지므로 화면이 이 목록을 따로 낸다. */
/**
 * 다섯 등급을 **A→E 순서 그대로**, 0척인 것까지 함께 낸다.
 *
 * `gradeDistributionSegments()`는 0척을 뺀다 — 폭 0인 막대 조각을 그릴 수 없기
 * 때문이고, 그 판단은 막대에서 여전히 맞다.
 *
 * **픽토그램은 사정이 다르다.** 막대와 달리 자리를 차지하지 않고도 「A 0척」을
 * 같은 줄에 적을 수 있고, 그러면 **등급 축이 A부터 E까지 끊기지 않는다.**
 * 종전처럼 「B · D · E」만 서 있으면 A와 C가 어디쯤인지 세어 봐야 안다.
 */
export function distributionSlots(
  distribution: Record<Rating, number>,
): { rating: Rating; count: number }[] {
  return RATINGS.map((rating) => ({ rating, count: distribution[rating] ?? 0 }))
}

export function zeroRatings(distribution: Readonly<Record<Rating, number>>): Rating[] {
  return RATINGS.filter((rating) => distribution[rating] === 0)
}

/** 구간 안에 문자를 담는가 (`§10.2` — 8%는 경계를 포함한다). */
export function showsInlineLabel(percent: number): boolean {
  return percent >= INLINE_LABEL_MIN_PERCENT
}

/**
 * 바 전체의 접근성 이름.
 *
 * 구간마다 이름을 붙여도 **바 자체가 무엇인지**는 따로 말해야 한다. 좁은 구간은
 * 화면에서 글자가 빠지므로, 여기서 전체를 한 번 읽어 주면 값이 사라지지 않는다.
 */
export function distributionAria(segments: readonly DistributionSegment[]): string {
  if (segments.length === 0) return '집계된 등급이 없습니다'
  return segments.map((seg) => `${seg.rating}등급 ${seg.count}척`).join(', ')
}

/**
 * 픽토그램(배 한 척 = 마크 하나)으로 그릴 수 있는 최대 척수.
 *
 * **세는 것이 일이 되면 픽토그램은 진다.** 스무 척 남짓까지는 낱개가 형태로 읽히지만
 * 그 위로는 「몇 개인지 세기」가 되고, 그때는 비율을 바로 보여 주는 막대가 낫다.
 *
 * MVP 대상이 중소선사라 대부분 이 아래지만, 늘었을 때 화면이 무너지지 않게 갈라 둔다.
 */
export const PICTOGRAM_MAX_VESSELS = 24

export function usesPictogram(segments: readonly DistributionSegment[]): boolean {
  return segments.reduce((sum, seg) => sum + seg.count, 0) <= PICTOGRAM_MAX_VESSELS
}

/**
 * GT가 없는 선박 수.
 *
 * 선박 카드마다 붙는 「GT 미입력」 배지(`ApplicabilityBadge`)의 합이다. 종전에는
 * **배마다 따로 보일 뿐 선대 단위로는 어디에도 없었다** — 몇 척이 그 상태인지
 * 알려면 목록을 세어야 했다.
 *
 * `grossTonnage`는 `number | string | null`이다. 서버가 소수를 문자열로 내리는
 * 자리라 빈 문자열도 없는 것으로 본다 — `Number('')`이 `0`이라 숫자로 바꿔
 * 판정하면 **GT 0인 배와 구분이 사라진다.**
 */
export function missingGrossTonnageCount(vessels: FleetVessel[]): number {
  return vessels.filter(
    (vessel) => vessel.grossTonnage === null || vessel.grossTonnage === '',
  ).length
}
