import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { ANNUAL_COPY } from './copy'
import { rangePlacement, rangeSummaryText } from './percentileRules'

/**
 * Monte Carlo 분포의 범위 막대 — P10~P90 밴드 · P50 점선 · 평균 표시 (#1456).
 *
 * 표현 규칙은 `DESIGN_SYSTEM §10.1` 팬 차트를 한 시점으로 자른 것이다 — 밴드 **1겹**
 * (P10–P90) · 밴드 색은 남색 12%(`--color-primary-subtle` — §10.1 `rgba(26,54,93,.12)`와
 * 같은 섞음이고 다크 테마에서도 성립한다) · 중앙선은 **P50 점선** · 라벨은 「중앙값(P50)」
 * (평균으로 오독 방지). 등급색은 쓰지 않는다. 결과 카드 안의 배치는 개발 임시안이다.
 *
 * **값은 서버 문자열을 그대로 보인다**(`API_SPEC §6.1` · `§1.7`). 숫자로 바꾸는 것은 막대
 * 위의 **자리**를 정할 때뿐이다 — 글자는 `formatDecimalString`이 문자열에서 자른다.
 *
 * 막대는 그림이라 `role="img"`에 **같은 뜻의 문장**을 싣는다(`DESIGN_SYSTEM §14`) — 화면과
 * 낭독이 같은 네 값 · 같은 뜻을 말한다.
 */
export function PercentileRange({
  p10,
  p50,
  p90,
  mean,
}: {
  p10: string
  p50: string
  p90: string
  mean: string
}) {
  const text = (value: string) => formatDecimalString(value, DISPLAY_DIGITS.cii)
  const place = rangePlacement(p10, p50, p90, mean)
  return (
    <figure className="annual-sim__range">
      <div
        className="annual-sim__range-rail"
        role="img"
        aria-label={rangeSummaryText(text(p10), text(p50), text(p90), text(mean))}
        data-testid="annual-sim-range"
      >
        <span
          className="annual-sim__range-band"
          style={{ left: `${place.p10}%`, width: `${place.p90 - place.p10}%` }}
        />
        <span className="annual-sim__range-median" style={{ left: `${place.p50}%` }} />
        <span className="annual-sim__range-mean" style={{ left: `${place.mean}%` }} />
      </div>
      <figcaption className="annual-sim__range-legend" aria-hidden="true">
        <span className="annual-sim__range-key annual-sim__range-key--band">
          {ANNUAL_COPY.rangeBandLabel}
        </span>
        <span className="annual-sim__range-key annual-sim__range-key--median">
          {ANNUAL_COPY.rangeMedianLabel}
        </span>
        <span className="annual-sim__range-key annual-sim__range-key--mean">
          {ANNUAL_COPY.rangeMeanLabel}
        </span>
      </figcaption>
    </figure>
  )
}
