import type { Rating } from '../features/voyage-cii/types'

/**
 * 등급 스케일 바의 기하 — `DESIGN_SYSTEM §8` · `§9.4`.
 *
 * 컴포넌트에서 분리한 이유는 저장소의 다른 규칙 모듈과 같다 — **비율 계산은 DOM 없이
 * 검증할 수 있어야 한다.** 경계 하나를 잘못 나누면 화면은 멀쩡하고 위치만 틀린다.
 */

/** `parameters_used.rating_boundary` — `required_cii`에 곱하는 배수다. */
export interface DVector {
  d1: string
  d2: string
  d3: string
  d4: string
}

export interface ScaleBand {
  rating: Rating
  /** 트랙 전체 폭에 대한 비율 (0~1). 다섯 구간의 합은 1이다. */
  fraction: number
}

export interface GradeScale {
  bands: ScaleBand[]
  /** 마커 위치 (0~1). 항상 트랙 안이다 — 아래 「끝 구간」 참조. */
  markerFraction: number
}

const RATINGS: readonly Rating[] = ['A', 'B', 'C', 'D', 'E']

/**
 * 열린 끝 구간(A·E)에 줄 여유. 안쪽 폭(`d4 - d1`)에 대한 비율이다.
 *
 * A는 아래로, E는 위로 경계가 없다. 어떤 값을 주든 표시상의 선택이므로, **안쪽 폭에
 * 비례**시켜 경계 간격이 좁은 선종에서는 끝도 좁아지게 했다. 고정 px로 두면 선종에
 * 따라 끝 구간만 과장된다.
 */
const END_PAD_RATIO = 0.35

/**
 * 비율 공간(`cii / required_cii`)에서 다섯 구간의 폭과 마커 위치를 낸다.
 *
 * ## 왜 비율 공간인가
 *
 * `d1`~`d4`가 이미 `required_cii`의 배수다(`API_SPEC §4.1`). 비율로 두면 경계가 곧
 * `0.86 · 0.94 · 1.06 · 1.18`이라 선박·연도가 달라도 같은 축에서 읽힌다.
 *
 * ## 구간 폭은 균등이 아니다 (`§9.4`)
 *
 * B·C·D의 폭은 `d2-d1` · `d3-d2` · `d4-d3`에 **정확히 비례**한다. 실제 경계는 균등하지
 * 않고(예: B는 0.08, C·D는 0.12), 균등 분할로 그리면 「C에서 D까지가 B에서 C까지와
 * 같은 거리」라는 **틀린 감각**을 준다.
 *
 * ## 끝 구간과 마커
 *
 * A·E는 경계가 한쪽뿐이라 정의역을 정해야 한다. 여기서는 **차트 축과 같은 방식**으로
 * 데이터가 정의역을 정하게 했다 — 경계 넷과 현재 값이 모두 들어가도록 잡고 여유를
 * 덧붙인다. 그 결과 **마커는 항상 트랙 안에 있고 잘라 내지 않는다.**
 *
 * 대가는 값에 따라 A·E의 폭이 달라진다는 것이다. 두 선박의 바를 나란히 놓고 끝 구간
 * 길이를 비교할 수는 없다. 안쪽 세 구간의 비례는 어느 경우에도 유지되므로 **「지금
 * 어느 구간에 있고 경계까지 얼마나 남았나」** 라는 이 컴포넌트의 목적에는 영향이 없다.
 *
 * ## 못 그리는 경우
 *
 * 값이 숫자가 아니거나 경계가 오름차순이 아니면 `null`이다. **추정해서 그리지
 * 않는다** — 위치가 틀린 스케일 바는 없는 것보다 나쁘다.
 */
/**
 * 빈 문자열을 숫자로 읽지 않는다.
 *
 * `Number('')`과 `Number('  ')`은 **`NaN`이 아니라 `0`이다.** 그대로 두면 값이 비어
 * 있을 때 마커가 「비율 0」 자리, 즉 A 구간 맨 왼쪽에 조용히 선다 — 화면은 멀쩡하고
 * 「최고 등급」이라는 틀린 말만 남는다.
 */
function toNumber(raw: string): number {
  return raw.trim() === '' ? Number.NaN : Number(raw)
}

export function buildGradeScale(
  ratioToRequired: string,
  d: DVector,
): GradeScale | null {
  /*
   * Layer 1 문자열을 숫자로 읽는다. `API_SPEC §1.7`이 금지하는 것은 **표시값을
   * 되돌리는 것**이고, 여기서 내는 것은 픽셀 위치다 — 소수 20자리가 화면에서
   * 의미를 갖지 않는다. 표시용 수치는 호출부가 문자열 그대로 넘긴다.
   */
  const edges = [toNumber(d.d1), toNumber(d.d2), toNumber(d.d3), toNumber(d.d4)]
  const value = toNumber(ratioToRequired)
  if (!edges.every(Number.isFinite) || !Number.isFinite(value)) return null

  // 오름차순이 아니면 구간 폭이 음수가 되어 레이아웃이 조용히 뒤집힌다.
  for (let i = 1; i < edges.length; i += 1) {
    if (edges[i] <= edges[i - 1]) return null
  }

  const interior = edges[3] - edges[0]
  const pad = interior * END_PAD_RATIO
  const min = Math.min(edges[0] - pad, value - pad / 2)
  const max = Math.max(edges[3] + pad, value + pad / 2)
  const span = max - min

  const cuts = [min, ...edges, max]
  const bands = RATINGS.map((rating, i) => ({
    rating,
    fraction: (cuts[i + 1] - cuts[i]) / span,
  }))

  return { bands, markerFraction: (value - min) / span }
}
