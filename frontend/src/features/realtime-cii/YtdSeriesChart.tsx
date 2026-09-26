import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { formatTimestamp } from '../../display/format'
import { ciiUnit } from '../voyage-cii/resultRules'
import type { YtdSeries, YtdSeriesPoint } from './types'
import './YtdSeriesChart.css'

/**
 * 올해 누적 CII 추이 (`#1949` · `DESIGN_SYSTEM §9.1`·`§9.2`·`§9.4` 🔒).
 *
 * ## 무엇을 그리는가
 *
 * 세로축은 **누적 CII**, 가로축은 **시간**이다. 점 하나가 항차 경계 하나이고
 * (`API_SPEC` `ytd-series`), 값은 그 시각까지의 **누적**이다 — 구간값이 아니다.
 *
 * - 실적(`ACTUAL`·`IN_PROGRESS`) — 실선 2px (`§9.2`)
 * - 계획(`PLAN`) — 점선 `6 4` 2px (`§9.2`)
 * - 둘 사이에 **세로 구분선 + 「오늘」** (`§9.2`)
 * - 등급 구간 배경과 경계선 (`§9.4`) — 이 차트는 **결정론 추이 차트**(실적선 + 단일
 *   예측선)라 구간 배경이 허용된다. 불확실성 밴드가 없기 때문이다
 *
 * ## 표를 함께 낸다 — 선택이 아니라 의무
 *
 * `PRD §16.4`가 「차트·확률분포는 표 요약 제공」을 요구한다. 차트만 두면 화면 낭독과
 * 인쇄본에서 값을 읽을 수 없다. `CiiHistoryChart`가 세운 규칙을 그대로 따른다.
 *
 * ## 값을 숫자로 되돌리는 곳은 좌표 계산뿐이다
 *
 * 선을 그리려면 비율이 필요해 `Number()`를 쓴다. **표시에는 서버 문자열을 그대로**
 * 쓴다(`API_SPEC §1.7`) — 화면에 보이는 숫자는 서버가 확정한 자릿수다.
 */

/* 뷰박스 — 실제 크기는 CSS가 정한다(`§0.2` 치수는 Figma 소유). */
const VIEW_W = 720
const VIEW_H = 220
const PAD_L = 34
const PAD_R = 44
const PAD_T = 12
const PAD_B = 26

/** 실적 쪽으로 세는 종류. `IN_PROGRESS`는 「지금까지의 누적」이라 실적 쪽이다. */
const ACTUAL_KINDS: ReadonlySet<YtdSeriesPoint['kind']> = new Set(['ACTUAL', 'IN_PROGRESS'])

/**
 * 선을 그리려면 점이 **둘** 있어야 한다 (`#1949` 확정 2026-09-26).
 *
 * 시드 실측에서 실적 점이 1건인 선박이 있었다. 점 하나를 선으로 잇는 척하면 **없는
 * 추세를 그리는 것**이다 — `§9.5`가 항로선에서 세운 「지어내지 않고 그 사실을 적는다」와
 * 같은 갈래다. 점만 찍고 한 줄로 말한다.
 */
const MIN_LINE_POINTS = 2

const NO_TREND_TEXT = '확정된 항차가 1건이라 아직 추세를 그리지 않습니다.'
const EMPTY_TEXT = '올해 누적 추이를 그릴 항차가 아직 없습니다.'

export function YtdSeriesChart({ series }: { series: YtdSeries }) {
  const unit = ciiUnit(series.capacityBasis)
  const points = series.points
  if (points.length === 0) {
    return <p className="ytds__empty">{EMPTY_TEXT}</p>
  }

  const actual = points.filter((p) => ACTUAL_KINDS.has(p.kind))
  const plan = points.filter((p) => p.kind === 'PLAN')

  /*
   * 가로축은 **규제연도 한 해**로 고정한다 — 점의 최소·최대에 맞추면 항차가 몰린
   * 선박과 흩어진 선박의 기울기가 서로 다른 뜻을 갖게 된다. 한 해가 늘 같은 폭이면
   * 「연말까지 얼마나 남았나」가 그림에서 바로 읽힌다.
   */
  const yearStart = Date.UTC(series.regulationYear, 0, 1)
  const yearEnd = Date.UTC(series.regulationYear + 1, 0, 1)
  const xOf = (iso: string) => {
    const t = Date.parse(iso)
    if (!Number.isFinite(t)) return PAD_L
    const ratio = Math.min(1, Math.max(0, (t - yearStart) / (yearEnd - yearStart)))
    return PAD_L + ratio * (VIEW_W - PAD_L - PAD_R)
  }

  /*
   * 세로축은 **점과 경계를 모두 담는다.** 0에서 시작하지 않는 것은 이 차트가 값의
   * 크기가 아니라 **경계 대비 위치**를 말하기 때문이다(`§9.4` 구간 배경의 근거와 같다).
   */
  const edges = edgesOf(series)
  const values = [
    ...points.map((p) => Number(p.attainedCii)),
    ...edges.map((e) => e.value),
    ...(series.requiredCii === null ? [] : [Number(series.requiredCii)]),
  ].filter(Number.isFinite)
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = hi - lo || 1
  const pad = span * 0.08
  const top = lo - pad
  const bottom = hi + pad
  const yOf = (value: number) => {
    const ratio = (value - top) / (bottom - top)
    return VIEW_H - PAD_B - ratio * (VIEW_H - PAD_T - PAD_B)
  }

  /*
   * 바깥 두 구간(A 위 · E 아래)은 **끝이 없다.** 그림의 위아래 끝까지 늘린다 —
   * 임의의 폭을 주면 배가 실제로 서 있는 자리가 어느 구간에도 속하지 않는 것처럼
   * 보인다(실측에서 E 구간이 배보다 한참 아래에서 끝났다).
   */
  const bands = bandsOf(edges, top, bottom)

  const path = (list: readonly YtdSeriesPoint[]) =>
    list.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.at)} ${yOf(Number(p.attainedCii))}`).join(' ')

  // 실적과 계획을 잇는다 — 끊어 두면 「오늘 값이 사라졌다」로 읽힌다.
  const planPath = actual.length > 0 && plan.length > 0 ? path([actual[actual.length - 1], ...plan]) : path(plan)
  const todayX = actual.length > 0 ? xOf(actual[actual.length - 1].at) : null

  return (
    <div className="ytds">
      <svg
        className="ytds__canvas"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label={`올해 누적 CII 추이. 실적 ${actual.length}점 · 계획 ${plan.length}점. 값은 아래 표에 있습니다.`}
      >
        {/*
          등급 구간 배경 (`§9.4` 조건부 허용) — **불투명도 0.16 이하**이고 높이는
          균등 분할이 아니라 **실제 경계값에 비례**한다. 좌측 축에 등급 문자를 함께
          적는 것이 그 허용의 조건이다(`§0.2` 제약 2·3).
        */}
        {bands.map((band) => {
          /*
           * ⚠️ **두 끝의 화면 좌표를 비교해서 쓴다.** 값의 크고 작음과 화면의 위아래가
           * 반대다 — CII는 클수록 나쁘고, 나쁜 쪽을 위에 그린다. `y`에 「작은 값의
           * 좌표」를 그대로 넣었더니 높이가 음수가 되어 `max(0, …)`에 걸려 **모든
           * 밴드가 높이 0으로 사라졌다**(1440 실측 · 화면에 색이 한 칸도 없었다).
           */
          const yLow = yOf(band.top)
          const yHigh = yOf(band.bottom)
          const y = Math.min(yLow, yHigh)
          const height = Math.abs(yLow - yHigh)
          return (
            <g key={band.rating}>
              <rect
                className={`ytds__band ytds__band--${band.rating.toLowerCase()}`}
                x={PAD_L}
                y={y}
                width={VIEW_W - PAD_L - PAD_R}
                height={height}
              />
              <text
                className="ytds__band-label"
                x={PAD_L - 8}
                y={y + height / 2}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {band.rating}
              </text>
            </g>
          )
        })}

        {/* 등급 경계선 — 1px dashed `3 3` · **등급색 금지** (`§9.4`). */}
        {edges.map((edge) => (
          <line
            key={`edge-${edge.rating}`}
            className="ytds__boundary"
            x1={PAD_L}
            x2={VIEW_W - PAD_R}
            y1={yOf(edge.value)}
            y2={yOf(edge.value)}
          />
        ))}

        {/*
          기준값 — 경계 넷과 **다른 것**이라 다른 결로 긋는다(실선). 경계는 등급을
          가르는 선이고, 이것은 그 경계들이 파생된 규제 기준이다(`기준 대비 %`의 기준).
        */}
        {series.requiredCii === null ? null : (
          <>
            <line
              className="ytds__required"
              x1={PAD_L}
              x2={VIEW_W - PAD_R}
              y1={yOf(Number(series.requiredCii))}
              y2={yOf(Number(series.requiredCii))}
            />
            <text className="ytds__edge-label" x={VIEW_W - PAD_R + 6} y={yOf(Number(series.requiredCii))} dominantBaseline="middle">
              기준
            </text>
          </>
        )}

        {/* 실적 — 실선 2px (`§9.2`). 점이 둘 미만이면 선을 긋지 않는다. */}
        {actual.length >= MIN_LINE_POINTS ? (
          <path className="ytds__actual" d={path(actual)} fill="none" />
        ) : null}
        {actual.map((p) => (
          <circle key={`a-${p.at}`} className="ytds__dot" cx={xOf(p.at)} cy={yOf(Number(p.attainedCii))} r={3.5} />
        ))}

        {/* 계획 — 점선 `6 4` 2px (`§9.2`). */}
        {plan.length > 0 ? <path className="ytds__plan" d={planPath} fill="none" /> : null}

        {/* 실적/계획 경계의 세로 구분선 + 「오늘」 (`§9.2`). */}
        {todayX === null ? null : (
          <>
            <line className="ytds__today" x1={todayX} x2={todayX} y1={PAD_T} y2={VIEW_H - PAD_B} />
            <text className="ytds__today-label" x={todayX} y={VIEW_H - PAD_B + 16} textAnchor="middle">
              오늘
            </text>
          </>
        )}

        {/* 축선 — 가로만 (`§9.1`: 세로 그리드선은 쓰지 않는다). */}
        <line className="ytds__axis" x1={PAD_L} x2={VIEW_W - PAD_R} y1={VIEW_H - PAD_B} y2={VIEW_H - PAD_B} />
      </svg>

      {actual.length > 0 && actual.length < MIN_LINE_POINTS ? (
        <p className="ytds__note">{NO_TREND_TEXT}</p>
      ) : null}

      <SeriesTable series={series} unit={unit} />
    </div>
  )
}

/** 등급 구간 하나. `value`는 그 구간의 **아래 경계**(가장 바깥은 `null`). */
interface Band {
  rating: string
  /** 구간의 위 끝(작은 CII 값). */
  top: number
  /** 구간의 아래 끝(큰 CII 값). */
  bottom: number
}

/** 경계선 하나 — 등급 사이를 가르는 값. */
interface Edge {
  rating: string
  value: number
}

/**
 * 경계 넷을 읽는다. 하나라도 값이 아니면 **구간을 만들지 않는다** — 반쯤 그린
 * 경계는 지어낸 경계다.
 */
function edgesOf(series: YtdSeries): Edge[] {
  const b = series.boundaries
  if (b === null) return []
  const values = [
    { rating: 'A', value: Number(b.superior) },
    { rating: 'B', value: Number(b.lower) },
    { rating: 'C', value: Number(b.upper) },
    { rating: 'D', value: Number(b.inferior) },
  ]
  return values.every((e) => Number.isFinite(e.value)) ? values : []
}

/**
 * 경계 넷에서 구간 다섯을 만든다.
 *
 * CII는 **작을수록 좋다** — A가 가장 작은 값 쪽이다. 바깥 두 구간은 끝이 없으므로
 * 그림의 위아래 끝(`top`·`bottom`)까지 늘린다.
 */
function bandsOf(edges: Edge[], top: number, bottom: number): Band[] {
  if (edges.length !== 4) return []
  const [a, b, c, d] = edges
  return [
    { rating: 'A', top, bottom: a.value },
    { rating: 'B', top: a.value, bottom: b.value },
    { rating: 'C', top: b.value, bottom: c.value },
    { rating: 'D', top: c.value, bottom: d.value },
    { rating: 'E', top: d.value, bottom },
  ]
}

/**
 * 표 요약 (`PRD §16.4`).
 *
 * 값은 **서버 문자열을 자릿수만 맞춰** 적는다. 시각은 `formatTimestamp`가 정한
 * 형식이다(`DESIGN_SYSTEM §4.4` 🔒) — 화면마다 다른 형식을 쓰지 않는다.
 */
function SeriesTable({ series, unit }: { series: YtdSeries; unit: string }) {
  return (
    <div className="ytds__tablebox">
      <table className="ytds__table">
        <caption className="sr-only">올해 누적 CII 추이 값</caption>
        <thead>
          <tr>
            <th scope="col">시각</th>
            <th scope="col">구분</th>
            <th scope="col">누적 CII ({unit})</th>
            <th scope="col">등급</th>
          </tr>
        </thead>
        <tbody>
          {series.points.map((p) => (
            <tr key={`${p.at}-${p.voyageId ?? ''}`}>
              <td>{formatTimestamp(p.at)}</td>
              <td>{kindText(p.kind)}</td>
              <td className="num">
                {formatDecimalString(p.attainedCii, DISPLAY_DIGITS.cii)}
                {/* 실측이 아닌 값이 섞였는가 — 색이 아니라 글자로 말한다 (`§14`). */}
                {p.substituted ? <span className="ytds__sub"> 추정 포함</span> : null}
              </td>
              <td>{p.rating ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function kindText(kind: YtdSeriesPoint['kind']): string {
  if (kind === 'ACTUAL') return '확정 실적'
  if (kind === 'IN_PROGRESS') return '진행 중'
  return '계획'
}
