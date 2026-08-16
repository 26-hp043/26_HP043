import type { CapacityBasis } from '../voyage-cii/types'
import { ciiUnit } from '../voyage-cii/resultRules'
import type { CiiYear } from './types'

/**
 * 연도별 CII 이력 차트.
 *
 * ## 표 요약을 함께 낸다 — 선택이 아니라 의무
 *
 * `PRD §16.4`가 *"차트·확률분포는 표 요약 제공"* 을 요구한다. 차트만 두면 스크린
 * 리더 사용자와 인쇄본에서 값을 읽을 수 없다. 그래서 이 컴포넌트는 **차트와 표를
 * 한 쌍으로** 렌더하며, 표를 옵션으로 두지 않는다.
 *
 * ## 값을 숫자로 되돌리는 곳은 여기뿐이다
 *
 * 막대 높이를 그리려면 비율이 필요해 `Number()`를 쓴다. **표시에는 원본 문자열을
 * 그대로 쓴다**(`API_SPEC §1.7`) — 화면에 보이는 숫자는 서버가 확정한 자릿수다.
 *
 * ## 색만으로 구분하지 않는다
 *
 * attained는 채운 막대, required는 **파선 기준선**이다(`DESIGN_SYSTEM §14`).
 * 등급은 막대 색 + 문자 라벨로 함께 표시한다.
 */

const VIEW_W = 320
const VIEW_H = 140
const PAD_L = 8
const PAD_R = 8
const PAD_T = 12
const PAD_B = 22

interface CiiHistoryChartProps {
  years: CiiYear[]
  basis: CapacityBasis
}

export function CiiHistoryChart({ years, basis }: CiiHistoryChartProps) {
  const unit = ciiUnit(basis)
  const withData = years.filter((y) => y.dataAvailable && y.attainedCii !== null)

  if (withData.length === 0) {
    return (
      <div className="history">
        <p className="history__empty">
          표시할 연도별 실적이 없습니다. 항차를 등록하면 이력이 쌓입니다.
        </p>
        <HistoryTable years={years} unit={unit} />
      </div>
    )
  }

  // 축 상한 — attained와 required 중 큰 값 기준. 0에서 시작해야 막대 길이가
  // 값의 비율을 그대로 나타낸다(잘린 축은 차이를 과장한다).
  const values = withData.flatMap((y) => [Number(y.attainedCii), Number(y.requiredCii ?? 0)])
  const max = Math.max(...values.filter(Number.isFinite), 1)
  const plotW = VIEW_W - PAD_L - PAD_R
  const plotH = VIEW_H - PAD_T - PAD_B
  const slot = plotW / withData.length
  const barW = Math.min(slot * 0.5, 36)

  return (
    <div className="history">
      <svg
        className="history__chart"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label={`연도별 CII 이력 차트. 값은 아래 표에 있습니다. 단위 ${unit}.`}
      >
        {withData.map((year, i) => {
          const attained = Number(year.attainedCii)
          const required = year.requiredCii === null ? null : Number(year.requiredCii)
          const cx = PAD_L + slot * i + slot / 2
          const h = (attained / max) * plotH
          const y = PAD_T + plotH - h
          const color = year.rating
            ? `var(--cii-${year.rating.toLowerCase()}-fill)`
            : 'var(--cii-none-fill)'

          return (
            <g key={year.regulationYear}>
              <rect
                className="history__bar"
                x={cx - barW / 2}
                y={y}
                width={barW}
                height={Math.max(h, 1)}
                rx="2"
                fill={color}
              />
              {/* required 기준선 — 파선이라 색을 못 봐도 구분된다 (§14). */}
              {required !== null && Number.isFinite(required) ? (
                <line
                  className="history__req"
                  x1={cx - barW / 2 - 4}
                  x2={cx + barW / 2 + 4}
                  y1={PAD_T + plotH - (required / max) * plotH}
                  y2={PAD_T + plotH - (required / max) * plotH}
                  vectorEffect="non-scaling-stroke"
                />
              ) : null}
              <text className="history__xlabel" x={cx} y={VIEW_H - 8} textAnchor="middle">
                {year.regulationYear}
              </text>
              {year.rating ? (
                <text className="history__rating" x={cx} y={y - 4} textAnchor="middle">
                  {year.rating}
                </text>
              ) : null}
            </g>
          )
        })}
        {/* 바닥선 */}
        <line
          className="history__axis"
          x1={PAD_L}
          x2={VIEW_W - PAD_R}
          y1={PAD_T + plotH}
          y2={PAD_T + plotH}
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      <ul className="history__legend">
        <li>
          <span className="history__swatch" /> 실적 (attained)
        </li>
        <li>
          <span className="history__swatch history__swatch--line" /> 기준 (required)
        </li>
      </ul>

      <HistoryTable years={years} unit={unit} />
    </div>
  )
}

/**
 * 표 요약 — `PRD §16.4` 「표 대체 설명」.
 *
 * 차트가 없어도 이 표만으로 값을 전부 읽을 수 있어야 한다.
 */
function HistoryTable({ years, unit }: { years: CiiYear[]; unit: string }) {
  return (
    <div className="history__tablebox">
      <table className="history__table">
        <caption className="history__caption">연도별 CII 실적 · 단위 {unit}</caption>
        <thead>
          <tr>
            <th scope="col">연도</th>
            <th scope="col">상태</th>
            <th scope="col">실적</th>
            <th scope="col">기준</th>
            <th scope="col">등급</th>
            <th scope="col">항차</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => (
            <tr key={year.regulationYear}>
              <th scope="row">{year.regulationYear}</th>
              <td>{year.status === 'CONFIRMED' ? '확정' : '진행 중'}</td>
              <td className="num">{year.attainedCii ?? '—'}</td>
              <td className="num">{year.requiredCii ?? '—'}</td>
              {/* 등급을 색으로만 구분하지 않는다 — 문자를 그대로 싣는다 (§14). */}
              <td>{year.rating ?? '—'}</td>
              <td className="num">{year.voyageCount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
