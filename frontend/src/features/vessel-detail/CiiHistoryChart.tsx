import type { CapacityBasis } from '../voyage-cii/types'
import { ciiUnit } from '../voyage-cii/resultRules'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
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
const VIEW_H = 120
const PAD_L = 8
const PAD_R = 8
const PAD_T = 16
// 연도 라벨이 SVG 밖으로 나가 아래 여백이 거의 필요 없다 (#723).
const PAD_B = 6

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
  const barW = Math.min(slot * 0.36, 44)

  const marks = withData.map((year, i) => {
    const cx = PAD_L + slot * i + slot / 2
    const y = PAD_T + plotH - (Number(year.attainedCii) / max) * plotH
    const required = year.requiredCii === null ? null : Number(year.requiredCii)
    const reqY =
      required !== null && Number.isFinite(required)
        ? PAD_T + plotH - (required / max) * plotH
        : null
    // 라벨은 막대와 기준선 중 **위쪽** 것보다 더 위에 놓는다.
    return { year, cx, y, reqY, capY: reqY === null ? y : Math.min(y, reqY) }
  })

  /** 뷰박스 좌표를 백분율로. HTML 라벨이 SVG와 같은 자리에 서게 한다. */
  const pctX = (x: number) => `${(x / VIEW_W) * 100}%`
  const pctY = (y: number) => `${(y / VIEW_H) * 100}%`

  return (
    <div className="history">
      {/*
        ## 글자를 SVG 밖으로 뺐다 (#723)

        SVG 안의 `<text>`는 **유저 단위**라 그림이 커지면 글자도 같이 커진다. 뷰박스가
        320인데 카드가 896이면 배율이 2.8이라, `font-size: 10`으로 적은 연도가
        **28px로 그려진다** — 표 제목보다 큰 글자가 차트 안에 앉아 있었다.

        `PositionChart`가 같은 이유로 좌표 범위를 그림 밖 글로 적는다 —
        *「유저 단위라 배율을 타서 크기가 흔들린다」*.

        그래서 SVG는 **그리드·막대·기준선만** 그리고, 글자는 같은 자리에 겹쳐 놓은
        HTML이 맡는다. 자리는 뷰박스 좌표를 백분율로 바꿔 맞춘다 — 배율이 바뀌어도
        선과 글자가 함께 움직인다.
      */}
      <div className="history__plot">
        <svg
          className="history__chart"
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          role="img"
          aria-label={`연도별 CII 이력 차트. 값은 아래 표에 있습니다. 단위 ${unit}.`}
        >
          {/*
            `§9.1` — 그리드선은 **가로만**. 세로 그리드선은 시간축이라 쓰지 않는다.
            종전에는 바닥선 하나뿐이라 막대가 허공에 떠 있었다.
          */}
          {[0, 0.5, 1].map((step) => {
            const gy = PAD_T + plotH - step * plotH
            return (
              <line
                key={step}
                className={step === 0 ? 'history__axis' : 'history__grid'}
                x1={PAD_L}
                x2={VIEW_W - PAD_R}
                y1={gy}
                y2={gy}
                vectorEffect="non-scaling-stroke"
              />
            )
          })}

          {marks.map(({ year, cx, y, reqY }) => (
            <g key={year.regulationYear}>
              <rect
                className="history__bar"
                x={cx - barW / 2}
                y={y}
                width={barW}
                height={Math.max(PAD_T + plotH - y, 1)}
                rx="3"
                fill={
                  year.rating
                    ? `var(--cii-${year.rating.toLowerCase()}-fill)`
                    : 'var(--cii-none-fill)'
                }
              />
              {/*
                기준선 — 파선이라 색을 못 봐도 구분된다 (`§14`). 막대보다 **넓게**
                긋는다. 막대 폭에 맞추면 막대의 뚜껑처럼 보여, 견주는 선이 아니라
                막대의 일부로 읽힌다.
              */}
              {reqY !== null ? (
                <line
                  className="history__req"
                  x1={cx - slot * 0.34}
                  x2={cx + slot * 0.34}
                  y1={reqY}
                  y2={reqY}
                  vectorEffect="non-scaling-stroke"
                />
              ) : null}
            </g>
          ))}
        </svg>

        {marks.map(({ year, cx, capY }) => (
          <p
            className="history__cap"
            key={year.regulationYear}
            style={{ left: pctX(cx), top: pctY(capY) }}
          >
            {year.rating ? <b className="history__cap-rating">{year.rating}</b> : null}
            {/*
              값을 여기 적는다. 종전에는 등급 문자만 있어 **실적이 얼마인지 보려면
              아래 표를 봐야 했다** — 차트가 「크다·작다」만 말하고 값은 말하지 않았다.
              `§9.1`의 세로축 눈금을 대신하는 자리이기도 하다(막대가 둘셋뿐이라
              눈금보다 값을 직접 적는 편이 짧다).
            */}
            {year.attainedCii === null
              ? null
              : formatDecimalString(year.attainedCii, DISPLAY_DIGITS.cii)}
          </p>
        ))}
      </div>

      <ul className="history__xaxis">
        {marks.map(({ year, cx }) => (
          <li key={year.regulationYear} style={{ left: pctX(cx) }}>
            {year.regulationYear}
          </li>
        ))}
      </ul>

      <ul className="history__legend">
        <li>
          <span className="history__swatch" /> 실적 (attained)
        </li>
        <li>
          <span className="history__swatch history__swatch--line" /> 기준 (required)
        </li>
      </ul>

      {/*
        범례가 이름만 적고 **뜻을 적지 않았다** (#723). 「기준 (required)」는 그 선이
        무엇인지는 말하지만 **어느 쪽이 좋은지**를 말하지 않는다 — CII는 낮을수록 좋다는
        것이 이 도메인 밖에서는 직관에 어긋난다(막대가 길면 좋아 보인다).

        `realtimeRules.ts`가 같은 사실을 코드 주석으로만 갖고 있었다 —
        *「CII는 **낮을수록 좋다.** 부호를 뒤집어 읽으면 화면이 정반대를 말한다」*.
        그 문장이 화면에도 있어야 한다.
      */}
      <p className="history__hint">
        <b>막대가 기준선보다 낮으면 좋습니다.</b> CII는 운송한 일에 견준 배출량이라 값이
        작을수록 효율이 높습니다.
      </p>

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
              {/* §4.1 🔒 — CII·required 모두 소수 3자리 고정. 원본은 6자리다. */}
              <td className="num">
                {year.attainedCii === null
                  ? '—'
                  : formatDecimalString(year.attainedCii, DISPLAY_DIGITS.cii)}
              </td>
              <td className="num">
                {year.requiredCii === null
                  ? '—'
                  : formatDecimalString(year.requiredCii, DISPLAY_DIGITS.cii)}
              </td>
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
