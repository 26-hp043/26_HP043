import { ANNUAL_COPY } from './copy'

/** 범위 막대의 낭독 문장 — `ANNUAL_COPY.rangeSummary`의 자리를 표시 문자열로 채운다 (#1456). */
export function rangeSummaryText(p10: string, p50: string, p90: string, mean: string): string {
  return ANNUAL_COPY.rangeSummary
    .replaceAll('{p10}', p10)
    .replaceAll('{p50}', p50)
    .replaceAll('{p90}', p90)
    .replaceAll('{mean}', mean)
}

/**
 * 네 값을 막대 위 자리(0~100%)로. 양 끝에 폭의 10%씩 여백을 둔다 — 평균이 P90 밖에 있을 수
 * 있어(우측 꼬리) 네 값의 최소~최대를 기준으로 삼는다. 네 값이 모두 같으면 가운데에 모은다.
 */
export function rangePlacement(
  p10: string,
  p50: string,
  p90: string,
  mean: string,
): { p10: number; p50: number; p90: number; mean: number } {
  const values = [p10, p50, p90, mean].map(Number)
  const low = Math.min(...values)
  const high = Math.max(...values)
  const span = high - low
  const at = (value: number) => (span === 0 ? 50 : 10 + ((value - low) / span) * 80)
  const [a, b, c, d] = values.map(at)
  return { p10: a, p50: b, p90: c, mean: d }
}
