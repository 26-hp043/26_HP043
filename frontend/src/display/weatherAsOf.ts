import { formatTimestamp } from './format'

/**
 * 보정에 쓴 기상의 **기준 시각** 한 줄 — `PRD §6.3` (#2135).
 *
 * 기능②(시나리오 비교) 결과와 선박 상세의 계산 이력이 같은 문구를 쓴다. 시각 형식은
 * `DESIGN_SYSTEM §4.4`(분까지 · KST 고정)이고 `formatTimestamp` 하나가 구현한다 —
 * 여기서 따로 포맷하지 않는다.
 */

// 정본 문구 (PRD §6.3) — 바꾸려면 PRD 개정이 먼저다.
export const WEATHER_AS_OF_LABEL = '기상 기준 시각'

// 정본 문구 (PRD §6.3 · API_SPEC §1.6 `WEATHER_NONE_FALLBACK`) — 바꾸려면 PRD 개정이 먼저다.
export const WEATHER_NOT_APPLIED_TEXT = '기상 보정 없이 계산했습니다.'

/**
 * 기상 보정 한 줄의 문장. 보정에 쓴 기상의 받은 시각이 있으면 「기상 기준 시각: …」,
 * 없으면(`null` · 값 없음) 「기상 보정 없이 계산했습니다.」다.
 *
 * 시각이 **있는데 읽을 수 없으면** `null`이다 — 보정했는데 「보정 없이」라고 적으면 거짓이고,
 * 「기준 시각: —」은 값이 없다는 말로 읽힌다. 그 줄을 통째로 뺀다(#2124와 같은 방식).
 */
export function weatherAsOfText(fetchedAt: string | null | undefined): string | null {
  if (fetchedAt === null || fetchedAt === undefined) return WEATHER_NOT_APPLIED_TEXT
  const time = formatTimestamp(fetchedAt)
  return time === null ? null : `${WEATHER_AS_OF_LABEL}: ${time}`
}

/**
 * 계산 이력 한 행의 기상 줄 (#2461). 보정하지 않은 계산에만 「기상 보정 없이 계산했습니다.」를
 * 적는다 — 받은 시각이 없다는 것만으로는 적지 않는다. 보정했지만 시각을 모르는 행
 * (스냅샷 행을 찾지 못했거나 `#904` 이전 계산 · `API_SPEC §1.9`)은 줄을 통째로 뺀다(`null`).
 */
export function historyWeatherText(weather: { fetchedAt: string | null; notApplied: boolean }): string | null {
  if (weather.notApplied) return WEATHER_NOT_APPLIED_TEXT
  return weather.fetchedAt === null ? null : weatherAsOfText(weather.fetchedAt)
}
