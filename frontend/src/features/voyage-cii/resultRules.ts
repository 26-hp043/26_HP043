import { DISPLAY_DIGITS, formatPercent } from './format'
import type { CapacityBasis, Rating, RiskLevel, VoyageCiiResponse } from './types'

/**
 * 기능① 결과 화면의 표시 규칙 (#136).
 *
 * **컴포넌트에서 분리한 순수 함수 모듈이다.** `formRules.ts`와 같은 이유이며,
 * 여기서는 특히 **문자열 상태를 유지한 채 판단하는 규칙**이 많아 분리 가치가 크다.
 *
 * ⚠️ **Layer 1 값에 `parseFloat`·`Number`를 쓰지 않는다**(`API_SPEC §1.7`
 * `[ORACLE-C-1]` · `#136` 완료 기준). 문자열로 직렬화해 정밀도 손실을 막는 이유가
 * 화면에서 되돌리면 사라진다. 「0보다 큰가」 같은 판단도 문자열로 한다.
 */

/**
 * 결과 영역의 4개 상태 (`#136` 완료 기준).
 *
 * 폼이 아니라 페이지가 들고 있다 — 입력과 결과가 같은 상태를 두고 다투지 않게 한다.
 */
export type ResultState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; response: VoyageCiiResponse }
  | { status: 'error'; message: string }

/**
 * CII 표시 단위. **선종의 capacity 축에서 파생시킨다.**
 *
 * `DESIGN_SYSTEM §4.1` 🔒 — 고정 문자열로 박지 않는다. MVP는 `BULK_CARRIER` 단독이라
 * 화면에 `DWT`만 나오지만, `dwt`를 상수로 두면 **선종이 늘 때 크루즈선에
 * `gCO₂/(DWT·nm)`이 표시된다.** 그 선종은 GT 축이라 분모가 다르다.
 * **화면이 깨지지 않고 내용만 틀리므로 발견이 늦다.**
 *
 * 축 문자열(`DWT`·`GT`)을 그대로 끼워 넣는다 — 응답의 `transport_capacity_basis`가
 * 이미 IMO 원문 표기인 대문자다. 분기표를 만들면 축이 늘 때 갱신을 빠뜨린다.
 *
 * 표기 형식의 근거(`§4.1` 🔒)
 * - **대문자** — IMO 원문 표기
 * - **분모를 괄호로 묶는다** — 없으면 `gCO₂/DWT`에 `nm`을 곱한 것으로 읽힌다
 * - **`t`를 쓰지 않는다** — 재화중량톤수와 실제 적재 무게는 다른 값이다
 *
 * ⚠️ **지표명(`AER`·`cgDIST`)을 값 옆에 병기하지 않는다**(`§4.1` 🔒 · 디자인 28번 ⑵).
 * 단위 문자열에 이미 축이 들어 있어 지표가 무엇인지 드러난다. 그래서 이 모듈은
 * 지표명을 반환하는 함수를 두지 않는다 — 있으면 화면에 붙게 된다.
 */
export function ciiUnit(basis: CapacityBasis): string {
  return `gCO₂/(${basis}·nm)`
}

/** 다음 악화 등급. E는 더 나쁜 등급이 없어 `null`이다(`PRD §3.3.6`). */
export function nextWorseRating(rating: Rating): Rating | null {
  const order: Rating[] = ['A', 'B', 'C', 'D', 'E']
  const index = order.indexOf(rating)
  if (index < 0 || index === order.length - 1) return null
  return order[index + 1]
}

/**
 * 십진 문자열이 0보다 큰지. **`Number`를 거치지 않는다.**
 *
 * 부호를 보고, 남은 숫자에 `0`이 아닌 자리가 하나라도 있으면 양수다.
 */
export function isPositiveDecimalString(value: string): boolean {
  const trimmed = value.trim()
  if (!/^[+-]?\d+(\.\d+)?$/.test(trimmed)) return false
  if (trimmed.startsWith('-')) return false
  return /[1-9]/.test(trimmed)
}

/** 여유율 표기 결과. 문구와 함께 그 문구가 왜 나왔는지를 구분자로 남긴다. */
export type MarginDisplay =
  /** `D 등급까지 7.2%` */
  | { kind: 'ratio'; text: string }
  /** `D 등급까지 0.1% 미만` */
  | { kind: 'below-threshold'; text: string }
  /** `해당 없음 — 최하위 등급` */
  | { kind: 'lowest'; text: string }
  /** 값이 없다. 등급 E가 아닌데 `null`이면 계약이 어긋난 것이다. */
  | { kind: 'unavailable'; text: string }

/**
 * 여유율 문구 — `DESIGN_SYSTEM §2.5 (b)` 🔒.
 *
 * ## 대상 등급을 함께 적는다
 *
 * 「다음 등급까지」만 쓰면 개선·악화 방향이 문구로 갈리지 않는다.
 * `next_worse_boundary_margin`은 **악화 방향**이므로 대상 등급을 적으면 자명해진다.
 *
 * ## 0.1% 미만 예외
 *
 * **0보다 크고 0.1% 미만이면 `0.0%`가 아니라 「0.1% 미만」**으로 적는다.
 * 경계 근처에서 `0.0%`는 이미 등급이 넘어간 것처럼 읽힌다.
 * **0 이하에는 이 예외를 적용하지 않는다** — 경계에 도달했거나 이미 넘은 상태다.
 *
 * ## 등급 E
 *
 * 악화 방향 경계가 없어 여유율이 정의되지 않는다. `#171`이 API 응답 형태를 `null`로
 * 결론지었고 정본 반영은 `#55` 소관이다. **`null`을 전제로 만들되 값이 와도
 * 깨지지 않게 한다** — 등급 E면 값 유무와 무관하게 「해당 없음」이다.
 */
export function marginDisplay(
  rating: Rating,
  marginRatio: string | null,
): MarginDisplay {
  if (rating === 'E') {
    return { kind: 'lowest', text: '해당 없음 — 최하위 등급' }
  }

  const target = nextWorseRating(rating)
  if (target === null || marginRatio === null || marginRatio.trim() === '') {
    return { kind: 'unavailable', text: '여유율 정보 없음' }
  }

  const percent = formatPercent(marginRatio, DISPLAY_DIGITS.percent)

  // 반올림 결과가 0.0인데 원값이 양수면 「0.1% 미만」이다.
  // 0 이하는 예외 대상이 아니므로 반올림값을 그대로 쓴다.
  if (percent === '0.0' && isPositiveDecimalString(marginRatio)) {
    return { kind: 'below-threshold', text: `${target} 등급까지 0.1% 미만` }
  }

  return { kind: 'ratio', text: `${target} 등급까지 ${percent}%` }
}

/**
 * 위험도 라벨 — `DESIGN_SYSTEM §2.5 (b)` 🔒 · `§14`.
 *
 * **한국어를 앞에 둔다** — 좁은 폭에서 잘려도 의미가 남는다.
 * `withIcon`은 **`HIGH`·`CRITICAL` 두 단계에만** `true`다. 단계별로 다른 아이콘을
 * 만들지 않는다 — 4개의 서로 다른 아이콘은 채널만 색에서 형태로 바꾼 4단계 시각
 * 체계라 「4단계 전용 램프 금지」의 취지가 무너진다. 아이콘은 「주의가 필요하다」만
 * 전달하고 정도는 라벨이 담당한다.
 */
export const RISK_LABEL: Readonly<
  Record<RiskLevel, { ko: string; withIcon: boolean }>
> = {
  LOW: { ko: '낮음', withIcon: false },
  MEDIUM: { ko: '보통', withIcon: false },
  HIGH: { ko: '높음', withIcon: true },
  CRITICAL: { ko: '심각', withIcon: true },
}

export function riskLabel(level: RiskLevel): { text: string; withIcon: boolean } {
  const entry = RISK_LABEL[level]
  if (!entry) return { text: level, withIcon: false }
  return { text: `${entry.ko} ${level}`, withIcon: entry.withIcon }
}

/**
 * Warning 코드의 사용자 메시지 — `API_SPEC §1.6` 표를 그대로 전사했다.
 *
 * 문구를 새로 쓰지 않는다(`AGENTS §3`). 코드별 개별 디자인은 8/8 범위 밖이며,
 * 표에 없는 코드가 오면 **코드 자체를 보여 준다** — 조용히 감추면 경고가 사라진다.
 */
export const WARNING_MESSAGE: Readonly<Record<string, string>> = {
  REFERENCE_ONLY: '참고용 예측값입니다. 규제 제출용이 아닙니다.',
  WEATHER_STALE: '오래된 기상 데이터를 사용 중입니다.',
  WEATHER_NONE_FALLBACK: '기상 보정 없이 계산했습니다.',
  CB_ESTIMATED: '선형 계수가 추정값입니다.',
  EXPERIMENTAL_MODEL: '실험 모델 기반 결과입니다.',
  NON_CII_VESSEL: '공식 CII 적용 대상이 아닐 수 있습니다.',
  COMPLETED_NO_FUEL: '실적이 입력되지 않은 완료 항차입니다. 계획값을 임시 사용 중.',
}

export function warningMessage(code: string): string {
  return WARNING_MESSAGE[code] ?? code
}

/**
 * 등급 배지에 쓸 패턴 URL. A는 solid라 패턴이 없다(`DESIGN_SYSTEM §15.1`).
 *
 * `§14` — **패턴 없는 등급 표시는 구현 금지.** 색만으로 A~E를 구분하면 적록색맹에서
 * A(녹)와 E(적)가 무너진다. A가 예외인 것은 「패턴 없음」 자체가 A의 식별 표시이고,
 * 배지에 등급 문자가 항상 함께 놓이기 때문이다.
 */
export function gradePatternUrl(rating: Rating): string | undefined {
  if (rating === 'A') return undefined
  return `url(#grade-${rating.toLowerCase()})`
}
