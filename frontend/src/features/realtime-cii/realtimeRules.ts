import type { Rating, RealtimeCii, YtdValues } from './types'

/**
 * 실시간 CII 화면 규칙 (`#357`).
 *
 * 컴포넌트에서 분리한 이유는 이 저장소의 다른 feature와 같다 — **판정은 DOM 없이
 * 검증할 수 있어야 한다.** vitest에 DOM 환경이 없다.
 */

/**
 * 폴링 간격 (ms).
 *
 * **60초로 정한 근거.** 값은 시계에 따라 연속적으로 변하지만, 사람이 보는 화면에서
 * 의미 있게 달라지는 단위는 시간이다 — 14 kn · 30 t/day인 배가 1분에 만드는 것은
 * 0.23 nm와 0.02 t이고, 소수 6자리 CII의 끝자리에서나 보인다. 더 짧게 잡으면
 * 서버 부하만 늘고 화면은 같아 보인다.
 *
 * 반대로 더 길게 잡으면 「정박을 시작했는데 화면이 한참 그대로」가 된다. 정박은
 * 등급을 실제로 움직이는 사건이라 그 지연이 이 화면의 목적을 깎는다.
 */
export const POLL_INTERVAL_MS = 60_000

/**
 * 「없는 것」의 사유 문구.
 *
 * **사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.** 서버가 준 코드를 사람 말로
 * 옮기되, 모르는 코드가 오면 코드를 그대로 보여 준다 — 빈칸보다 낫다.
 */
export const PROJECTION_REASONS: Readonly<Record<string, string>> = {
  NO_BASIS:
    '올해 실적이 아직 없어 연말 예상을 산출할 수 없습니다. 항차 실적을 입력하면 계산됩니다.',
  YEAR_COMPLETE: '해당 연도가 끝나 연말 예상 대신 확정 누적값을 보시면 됩니다.',
}

/**
 * 경고 코드의 사람 말.
 *
 * `SIMULATION_NO_FUEL_*`는 **행동을 안내해야 한다.** 「값이 안 변한다」로만 적으면
 * 사용자는 기다리고, 실제로는 제원을 채워야 한다.
 */
export const WARNING_TEXT: Readonly<Record<string, string>> = {
  REFERENCE_ONLY: '본 화면의 값은 참고용 예측값이며 규제 제출용 공식 결과가 아닙니다.',
  SIMULATION_NO_FUEL_RATE:
    '선박에 기준 일일 연료소모량이 등록되지 않아 진행 중 항차분이 누적에 반영되지 않았습니다. 선박 제원을 입력해 주세요.',
  SIMULATION_NO_FUEL_TYPE:
    '진행 중 항차의 연료 종류를 알 수 없어 진행분이 누적에 반영되지 않았습니다. 항차에 연료를 입력하거나 선박 기본 연료를 지정해 주세요.',
  COMPLETED_NO_FUEL:
    '완료된 항차 일부에 실적 연료가 없어 계획값으로 대신 계산했습니다.',
  // `#649` — 이 화면이 진행 중 항차의 누적을 보여 주는 자리다. 예정일에서 잘렸는데
  // 그 사실이 없으면 사용자는 값이 멈춘 것을 「항차가 끝났나」로 읽는다.
  IN_PROGRESS_PAST_ETA:
    '진행 중 항차가 도착 예정일을 지났습니다. 누적은 예정일까지만 반영했으며, 도착 실적을 입력하면 확정됩니다.',
  // --- CII 적용 대상 (`#653`) ---
  //
  // 이 화면은 선박 하나의 값을 실시간으로 보여 주는 자리라, 그 값이 규제상
  // 무의미할 수 있다는 사실이 **여기 없으면 어디에도 없다**.
  NON_CII_VESSEL: '공식 CII 적용 대상이 아닐 수 있습니다.',
  CII_APPLICABILITY_UNKNOWN:
    '총톤수(GT)가 없어 공식 CII 적용 대상 여부를 판정할 수 없습니다. 선박 제원에 총톤수를 입력해 주세요.',
}

export function warningText(code: string): string {
  return WARNING_TEXT[code] ?? code
}

export function projectionReason(code: string | null): string {
  if (code === null) return '연말 예상을 산출할 수 없습니다.'
  return PROJECTION_REASONS[code] ?? code
}

/**
 * 정박 중인가.
 *
 * **`underway_state`만 본다.** 「진행 중 항차가 없다」로 판정하면 항차를 아직
 * 등록하지 않은 선박이 전부 정박 중으로 보인다 — 기록이 없는 것과 정박한 것은
 * 다르다(`#356`의 `stateText`와 같은 판단).
 */
export function isNotUnderWay(data: RealtimeCii): boolean {
  return data.underwayState === 'NOT_UNDER_WAY'
}

/**
 * 정박이 등급을 실제로 밀고 있는가 — **명세 3-③이 보이라고 한 것**.
 *
 * 정박 상태인 것만으로는 부족하다. 정박 **연료가 기록되어 있어야** 분자 `M`이
 * 늘고, 그때 비로소 등급이 악화된다. 기록이 없으면 정박해도 값은 그대로다 —
 * 그 상태를 「악화 중」으로 그리면 화면이 사실과 다른 말을 한다.
 *
 * `#370`이 만든 입력 경로가 바로 이 조건을 채우는 곳이다.
 */
export function isDegradingAtBerth(data: RealtimeCii): boolean {
  return isNotUnderWay(data) && data.ytd.notUnderwayPeriodCount > 0
}

/**
 * 진행 중 항차의 남은 거리.
 *
 * 계획 거리에서 누적 거리를 뺀다. **음수는 0으로 자른다** — 계획보다 더 간 항차는
 * 실제로 생기고(우회·기상), 「남은 거리 −120 nm」는 아무 뜻도 없다.
 *
 * 계획 거리가 없으면 `null`이다. 0으로 두면 「다 왔다」로 읽힌다.
 */
export function remainingDistanceNm(data: RealtimeCii): number | null {
  const voyage = data.currentVoyage
  if (!voyage || voyage.plannedDistanceNm === null || voyage.distanceNm === null) {
    return null
  }
  const planned = Number(voyage.plannedDistanceNm)
  const done = Number(voyage.distanceNm)
  if (Number.isNaN(planned) || Number.isNaN(done)) return null
  return Math.max(0, Number((planned - done).toFixed(2)))
}

/** 진행률(0~1). 계획 거리가 없거나 0이면 `null` — 분모 0을 화면이 만들지 않는다. */
export function voyageProgressRatio(data: RealtimeCii): number | null {
  const voyage = data.currentVoyage
  if (!voyage || voyage.plannedDistanceNm === null || voyage.distanceNm === null) {
    return null
  }
  const planned = Number(voyage.plannedDistanceNm)
  const done = Number(voyage.distanceNm)
  if (!Number.isFinite(planned) || planned <= 0 || !Number.isFinite(done)) return null
  return Math.min(1, Math.max(0, done / planned))
}

/**
 * ⑴ 대비 ⑶의 방향 — 「좋아지는 중 / 나빠지는 중 / 같음」.
 *
 * 둘 중 하나라도 없으면 `null`이다. 없는 값을 「같음」으로 뭉치면 화면이 근거 없이
 * 안심시킨다.
 */
export function projectionDirection(
  data: RealtimeCii,
): 'IMPROVING' | 'WORSENING' | 'FLAT' | null {
  const now = data.ytd.attainedCii
  const end = data.projection.attainedCii
  if (now === null || end === null) return null

  const a = Number(now)
  const b = Number(end)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  // CII는 **낮을수록 좋다.** 부호를 뒤집어 읽으면 화면이 정반대를 말한다.
  if (b < a) return 'IMPROVING'
  if (b > a) return 'WORSENING'
  return 'FLAT'
}

/**
 * 등급 순서. **A가 가장 좋고 E가 가장 나쁘다.**
 *
 * 문자 비교(`'D' > 'C'`)로도 우연히 같은 답이 나오지만 쓰지 않는다 — 등급 문자가
 * 순서를 뜻한다는 보장이 어디에도 없고, 등급 체계가 바뀌면 조용히 틀린다.
 */
const RATING_ORDER: Readonly<Record<Rating, number>> = { A: 0, B: 1, C: 2, D: 3, E: 4 }

export type TransitionDirection = 'IMPROVING' | 'WORSENING' | 'FLAT'

export interface RatingTransition {
  /** ⑴ 연간 누적(YTD) 등급 */
  from: Rating
  /** ⑶ 연말 예상 등급 */
  to: Rating
  direction: TransitionDirection
}

/**
 * ⑴ → ⑶ **등급** 전이 — 「현재 누적 기준 예상 등급이 연말에 어디로 가는가」.
 *
 * ## `projectionDirection`과 다른 것을 본다
 *
 * 그쪽은 **CII 값**의 방향이고 이쪽은 **등급**의 이동이다. 둘은 어긋날 수 있다 —
 * CII가 나빠져도 경계를 넘지 않으면 등급은 그대로다. 그래서 값이 `WORSENING`인데
 * 등급 전이는 `FLAT`인 상태가 정상이며, 두 표시가 서로를 부정하지 않는다.
 * 값의 미세한 움직임은 ⑶ 카드가, 등급이 실제로 바뀌는지는 여기가 답한다.
 *
 * ## 한쪽이라도 없으면 `null`
 *
 * 연말 예상을 못 내는 경우(`NO_BASIS` 등)가 실제로 있다. 그때 없는 쪽을 현재
 * 등급으로 채우면 화면이 **「등급 유지 예상」이라는 근거 없는 안심**을 말한다.
 * `dataAvailable`을 함께 보는 것도 같은 이유다 — 등급만 남아 있고 산출이 무효인
 * 응답을 전이로 그리지 않는다.
 */
export function ratingTransition(data: RealtimeCii): RatingTransition | null {
  const from = data.ytd.dataAvailable ? data.ytd.rating : null
  const to = data.projection.dataAvailable ? data.projection.rating : null
  if (from === null || to === null) return null

  const delta = RATING_ORDER[to] - RATING_ORDER[from]
  return {
    from,
    to,
    direction: delta > 0 ? 'WORSENING' : delta < 0 ? 'IMPROVING' : 'FLAT',
  }
}

/**
 * 전이 라벨.
 *
 * `DESIGN_SYSTEM §14` — 색만으로 의미를 전달하지 않는다. 이 문구가 색과 짝을 이루는
 * 보조 채널이라 **색을 못 보아도 방향이 읽힌다.**
 *
 * `§4.3`의 ▼▲는 여기 쓰지 않는다. 그 기호는 **CII 수치의 증감** 표기이고, 등급
 * 이동에 갖다 붙이면 「등급 하락」과 「CII 증가(▲)」가 한 줄에서 서로 반대로 읽힌다.
 */
export const RATING_TRANSITION_TEXT: Readonly<Record<TransitionDirection, string>> = {
  IMPROVING: '등급 상승 예상',
  WORSENING: '등급 하락 예상',
  FLAT: '등급 유지 예상',
}

/**
 * 값이 있을 때만 포매터를 부른다.
 *
 * `src/display/format.ts`의 포매터는 **십진 문자열만** 받는다 — 아닌 것이 오면
 * `TypeError`를 던진다(정밀도 규약을 조용히 어기느니 멈추는 쪽을 택한 설계다).
 * `API_SPEC §2.14`의 수치는 대부분 `string | null`이라 그대로 넘기면 화면이 죽는다.
 *
 * 「없음」은 **포맷 대상이 아니라 별도의 표시**다. 그 판단을 화면 곳곳에 흩어 두면
 * 한 자리만 빠뜨려도 그 필드가 null인 응답에서만 터진다 — 늦게 발견되는 종류다.
 * 여기 한 곳에 두고 DOM 없이 검증한다.
 *
 * 포맷 자체는 하지 않는다. **어떤 포매터를 쓸지는 호출부가 정한다** — 필드마다
 * 자릿수가 다르고(`DESIGN_SYSTEM §4`), 그 선택은 화면의 몫이다.
 */
export function formatOrNull(
  value: string | null,
  format: (raw: string) => string,
): string | null {
  return value === null ? null : format(value)
}

/** 기준 시각 표시. 실시간 화면에서는 값 자체만큼 중요한 정보다. */
export function formatAsOf(asOf: string): string {
  return new Date(asOf).toLocaleString('ko-KR', { hour12: false })
}


/**
 * 신뢰도 배지를 붙이는가 — `DESIGN_SYSTEM §8.1` 🔒 (`#485` ⑤).
 *
 * ## 판정을 화면이 지어내지 않는다
 *
 * `§8.1`이 「언제 붙는가」를 정본으로 확정했다. *「정해 두지 않으면 구현이 임계를
 * 지어내고, **화면이 깨지지 않으므로** 정본과 갈린 사실이 늦게 발견된다」*가
 * 그 절이 신설된 이유다.
 *
 * ## 왜 `substitutions`만 보는가
 *
 * `§8.1`의 컷은 `IN_PROGRESS latest estimate` **이하 전부**인데, YTD 집계는
 * 애초에 `INCLUDE_AS_PLAN`(PLANNED·IN_PROGRESS)을 넣지 않는다
 * (`services/ytd_cii.py`). 따라서 YTD 등급이 실측이 아닌 값으로 계산되는 경로는
 * **`§8.1`이 예외로 명시한 그 경우 하나뿐**이다 — `COMPLETED`인데 실적이 없어
 * 계획값이 대입된 항차(`PRD §8.3 [ORACLE-C-4B]`).
 *
 * 그 결과가 `ytd.substitutions`이고, 같은 상황에 `COMPLETED_NO_FUEL` 경고가
 * 이미 나가고 있어 **배지와 문구가 같은 사실을 가리킨다**(`§8.1`).
 */
export function hasSubstitutedInputs(ytd: YtdValues): boolean {
  return ytd.substitutions.length > 0
}

/**
 * 배지에 붙일 설명.
 *
 * **무엇이 대체됐는지까지 말한다.** `API_SPEC §2.14`가 항차별 목록을 실어 주는
 * 이유가 *「항차가 40건이면 경고 하나로는 40건을 전부 열어 봐야 한다」*이므로,
 * 화면이 「추정값 포함」으로만 끝내면 그 목록을 받은 뜻이 없다.
 */
export function substitutionSummary(ytd: YtdValues): string {
  const fuel = ytd.substitutions.filter((s) => s.axis === 'FUEL').length
  const distance = ytd.substitutions.filter((s) => s.axis === 'DISTANCE').length

  const parts: string[] = []
  if (fuel > 0) parts.push(`연료 ${fuel}건`)
  if (distance > 0) parts.push(`거리 ${distance}건`)

  return `완료 항차의 ${parts.join(' · ')}이 실적 대신 계획값으로 계산됐습니다. 실적을 입력하면 등급이 달라질 수 있습니다.`
}
