import type { FleetVessel } from './types'
import { isAtRisk } from './fleetRules'
import { gradePatternUrl } from '../../components/gradePattern'

/**
 * 선박 위치 개략도.
 *
 * ## 지도가 아니다
 *
 * `PRD §5.2`가 **지도 기반 렌더링을 범위에서 제외**했다 — 타일 서비스·API 키·비용·
 * 오프라인 시연 가능 여부가 미결이기 때문이다. 같은 절이 *"실시간 화면은 지도 없이
 * 성립한다"* 고 적고 있다.
 *
 * 그래서 여기서는 **좌표를 상대 배치로만** 보여 준다. 외부 요청이 없어 오프라인에서
 * 그대로 그려지고, 「어느 배가 서로 얼마나 떨어져 있나」와 「등급이 어떤가」가 읽히면
 * 목적을 다한다.
 *
 * ## 항적(track)을 그리지 않는다
 *
 * `GET /fleet/summary`(`#350`)는 **현재 좌표만** 준다. 지나온 항적은 항차 계층
 * 데이터라 이 응답에 없다. 없는 것을 그리면 안 되므로 점만 찍는다 — 항적은 지도 API
 * 연동 또는 실시간 CII 화면(`#357`) 소관이다.
 *
 * ## 색만으로 구분하지 않는다 — 마커는 패턴이 필수다
 *
 * 마커에는 **등급 문자가 없다.** `DESIGN_SYSTEM §2.4.4`는 문자가 없는 자리에서
 * 패턴을 필수로 요구한다 — 구현된 fill 토큰이 사실상 3색 체계라(A·B 초록 · C 주황 ·
 * D·E 빨강) 적록색맹에서 세 색상군이 모두 황갈색으로 수렴하고, 패턴 없이는 구분이
 * 불가능하다. 그래서 채움색 원 위에 `GradePatternDefs`의 패턴 원을 겹친다.
 *
 * 패턴 타일은 투명 배경 위에 무늬만 그린다. **한 원에 색과 패턴을 함께 줄 수 없어**
 * 아래에 색 원, 위에 패턴 원 두 장을 포갠다.
 *
 * 위험 선박에는 여기에 더해 **이름표와 굵은 테두리**를 준다(`§14`).
 *
 * ## 뷰박스를 마커가 아니라 패턴 해상도에 맞춘다
 *
 * 패턴은 `userSpaceOnUse` 4px 타일이라 **이 SVG의 사용자 좌표계에서** 4단위다.
 * 좌표계가 성기면 마커 하나에 무늬가 한두 개밖에 안 들어가 도트·사선·크로스해치가
 * 서로 구분되지 않는다. 그래서 뷰박스를 16:10 비율 그대로 3배(480×300)로 키우고
 * 마커·여백도 함께 3배로 적었다 — **화면에 그려지는 크기는 그대로**이고, 마커
 * 지름 안에 들어가는 무늬 수만 늘어난다.
 *
 * 테두리는 `vector-effect="non-scaling-stroke"`라 이 배율에 영향받지 않는다.
 */

/** 좌표가 한 점뿐이거나 모두 같을 때 0으로 나누지 않도록 두는 최소 폭(도). */
const MIN_SPAN = 0.5

/** 여백 — 점이 테두리에 붙지 않게 한다. */
const PADDING = 24

const VIEW_W = 480
const VIEW_H = 300

/** 마커 반지름. 4px 패턴 타일이 지름 안에 네 번쯤 들어가는 크기다. */
const DOT_R = 7.8

/** 이름표를 마커 위(또는 아래)로 띄우는 거리. */
const LABEL_OFFSET = 18

/**
 * 이름표 글자 크기 — **뷰박스 유저 단위**다. CSS 픽셀이 아니다.
 *
 * `viewBox`가 `0 0 480 300`이고 박스는 폭에 맞춰 늘어나므로, 실제 렌더 크기는
 * `LABEL_FONT × (박스 폭 / 480)`이다. 박스 폭은 레이아웃에 따라 778~1049px이라
 * **배율이 1.6~2.2배** 사이에서 움직인다.
 *
 * | 종전 21 | 지금 8 |
 * |---|---|
 * | 34~46px | 13~18px |
 *
 * 21은 `§3` 타입 스케일에 없는 값이었고, 렌더 크기 46px는 스케일 최대값인
 * `display`(32px)보다 컸다 — **선박명이 페이지에서 제일 큰 글자였다.** 8은
 * `caption`(12) ~ `heading`(16) 대역에 들어온다.
 *
 * 이 값을 CSS(`.position-chart__label`)가 아니라 여기 두는 것은, 아래
 * `labelPlacement`가 넘침을 막으려면 **글자 크기를 알아야 하기 때문**이다.
 * 두 곳에 나뉘어 있으면 한쪽만 바뀌었을 때 조용히 어긋난다.
 */
const LABEL_FONT = 8

/** 뷰박스 가장자리에서 이름표를 띄우는 최소 거리. */
const LABEL_EDGE = 4

/** 좌표축 선이 뷰박스 가장자리에서 떨어지는 거리 — 점 영역(`PADDING`) 바깥이다. */
const AXIS_INSET = PADDING / 2

/**
 * 위도·경도를 사람이 읽는 표기로 바꾼다 — `37.4°N` · `126.5°E`.
 *
 * 부호 대신 방위 문자를 쓰는 것이 해도의 관행이고, **음수 부호는 「남위」보다
 * 읽는 데 한 단계가 더 든다.** 소수 1자리는 이 개략도의 축척(최소 0.5°)에서
 * 의미가 남는 마지막 자리다.
 */
function formatLat(v: number): string {
  return `${Math.abs(v).toFixed(1)}°${v >= 0 ? 'N' : 'S'}`
}

function formatLon(v: number): string {
  return `${Math.abs(v).toFixed(1)}°${v >= 0 ? 'E' : 'W'}`
}

/**
 * 이름표가 뷰박스를 넘지 않게 자리를 잡는다.
 *
 * SVG는 뷰박스 밖을 잘라 내므로, 가장자리 마커의 이름표가 **글자 중간에서
 * 뚝 끊긴다.** 실제로 위쪽 마커의 이름이 위로 잘리고 오른쪽 마커의 이름이
 * 오른쪽으로 잘리고 있었다.
 *
 * - **세로** — 위로 띄운 이름표가 천장을 넘으면 마커 **아래**로 뒤집는다.
 * - **가로** — 가운데 정렬이라 이름이 좌우로 뻗는다. 한쪽 끝에 닿으면 그쪽
 *   기준 정렬로 바꾸고 x를 가장자리에 붙인다.
 *
 * 글자 폭은 잴 수 없으므로 어림한다. 한글은 대략 한 글자가 글자 크기만큼,
 * 숫자·라틴 문자는 그 절반쯤이다. **어림이 빗나가도 손해는 「필요 없는데
 * 끝 정렬로 바뀌는 것」뿐**이고, 잘리는 것보다 낫다.
 */
function labelPlacement(name: string, x: number, y: number) {
  /*
   * 비ASCII(여기서는 사실상 한글)의 개수를 센다.
   *
   * 정규식을 쓰지 않는다. `[^\x00-\x7F]`도 `[^\u0000-\u007F]`도 제어문자를
   * 범위에 담고 있어 `no-control-regex`에 걸린다. 세려는 것은 「ASCII가 아닌 것」이지
   * 제어문자가 아니므로, 코드포인트를 직접 보는 편이 뜻에도 가깝다.
   *
   * `[...name]`은 코드포인트 단위로 쪼갠다 — `name.length`(UTF-16 단위)와 달리
   * 서로게이트 쌍을 두 글자로 세지 않는다.
   */
  const chars = [...name]
  const wide = chars.filter((ch) => ch.codePointAt(0)! > 0x7f).length
  const narrow = chars.length - wide
  const halfWidth = (wide * LABEL_FONT + narrow * LABEL_FONT * 0.55) / 2

  const above = y - LABEL_OFFSET
  const flipped = above - LABEL_FONT < LABEL_EDGE

  let anchor: 'start' | 'middle' | 'end' = 'middle'
  let labelX = x
  if (x + halfWidth > VIEW_W - LABEL_EDGE) {
    anchor = 'end'
    labelX = VIEW_W - LABEL_EDGE
  } else if (x - halfWidth < LABEL_EDGE) {
    anchor = 'start'
    labelX = LABEL_EDGE
  }

  return {
    x: labelX,
    // 아래로 뒤집을 때는 글자의 윗변이 마커에 닿지 않게 한 줄 높이를 더한다.
    y: flipped ? y + LABEL_OFFSET + LABEL_FONT : above,
    anchor,
  }
}

interface Positioned {
  vessel: FleetVessel
  lat: number
  lon: number
}

interface PositionChartProps {
  vessels: FleetVessel[]
}

export function PositionChart({ vessels }: PositionChartProps) {
  const points: Positioned[] = vessels.flatMap((vessel) => {
    if (vessel.lat === null || vessel.lon === null) return []
    const lat = Number(vessel.lat)
    const lon = Number(vessel.lon)
    return Number.isFinite(lat) && Number.isFinite(lon) ? [{ vessel, lat, lon }] : []
  })

  if (points.length === 0) {
    return (
      <p className="position-chart__empty">
        위치가 기록된 선박이 없습니다. 선박 상세에서 현재 위치를 입력하면 여기에
        표시됩니다.
      </p>
    )
  }

  const lats = points.map((p) => p.lat)
  const lons = points.map((p) => p.lon)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const latSpan = Math.max(maxLat - minLat, MIN_SPAN)
  const lonSpan = Math.max(maxLon - minLon, MIN_SPAN)

  /** 경도 → x, 위도 → y. **위도는 위쪽이 크므로 뒤집는다.** */
  const project = (p: Positioned) => ({
    x: PADDING + ((p.lon - minLon) / lonSpan) * (VIEW_W - PADDING * 2),
    y: PADDING + (1 - (p.lat - minLat) / latSpan) * (VIEW_H - PADDING * 2),
  })

  return (
    <>
    <svg
      className="position-chart"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      role="img"
      aria-label={`선박 ${points.length}척의 현재 위치 개략도. 위도 ${formatLat(minLat)}~${formatLat(maxLat)}, 경도 ${formatLon(minLon)}~${formatLon(maxLon)} 범위입니다. 점의 색과 무늬는 올해 누적 등급입니다.`}
    >
      {/*
        좌표축 — `DESIGN_SYSTEM §9.1` 축선(`--color-border-strong`, 1px).
        눈금과 격자는 두지 않는다. 이 그림은 **좌표 평면 위의 개략도**이지
        값을 읽는 차트가 아니라서, 격자를 깔면 읽을 수 있는 눈금이 있는 것처럼
        보인다. 축선 두 줄은 「가로가 경도, 세로가 위도」만 말한다.

        `vector-effect`로 굵기를 고정한다 — 뷰박스 배율(1.6~2.2배)을 타면
        같은 1px이 화면에서 2px 넘게 그려진다.
      */}
      <line
        className="position-chart__axis"
        x1={AXIS_INSET}
        y1={AXIS_INSET}
        x2={AXIS_INSET}
        y2={VIEW_H - AXIS_INSET}
        vectorEffect="non-scaling-stroke"
      />
      <line
        className="position-chart__axis"
        x1={AXIS_INSET}
        y1={VIEW_H - AXIS_INSET}
        x2={VIEW_W - AXIS_INSET}
        y2={VIEW_H - AXIS_INSET}
        vectorEffect="non-scaling-stroke"
      />
      {/*
        방위 — 위쪽이 북쪽임을 밝힌다(`project`가 위도를 뒤집는 이유이기도 하다).
        지도가 아니므로 나침반을 그리지 않고 글자 하나만 둔다.

        **점 영역보다 위에 둔다.** 마커는 아무리 북쪽이어도 `PADDING`(24)까지만
        올라오므로 윗변이 `24 - DOT_R` = 16.2다. 글자 밑변을 12에 두면 글자가
        4~12를 쓰고 그 아래로 4.2가 남는다 — 종전 밑변 20은 16.2와 겹쳐서
        **좌상단에 선박이 있으면 나침방이 마커에 가려 보이지 않았다.**
      */}
      <text
        className="position-chart__compass"
        x={AXIS_INSET + 5}
        y={LABEL_EDGE + LABEL_FONT}
        fontSize={LABEL_FONT}
      >
        ↑N
      </text>
      {points.map((point) => {
        const { x, y } = project(point)
        const rating = point.vessel.ytdRating
        // 등급이 없는 선박(실적 없음)은 중립색 — 나쁜 등급으로 보이면 안 된다.
        const color = rating
          ? `var(--cii-${rating.toLowerCase()}-fill)`
          : 'var(--cii-none-fill)'
        // A는 solid라 패턴이 없다(§15.1). 등급 미상도 무늬를 주지 않는다 —
        // 없는 등급에 등급 무늬를 붙이면 있는 것처럼 읽힌다.
        const pattern = rating ? gradePatternUrl(rating) : undefined
        const risky = isAtRisk(point.vessel)
        const dotClass = risky
          ? 'position-chart__dot position-chart__dot--risk'
          : 'position-chart__dot'

        return (
          <g key={point.vessel.id}>
            {/* 마우스오버·보조기술용. 무늬를 못 읽어도 등급이 글로 나온다. */}
            <title>{`${point.vessel.name} — ${rating ? `등급 ${rating}` : '등급 미상'}`}</title>
            <circle cx={x} cy={y} r={DOT_R} fill={color} />
            {pattern ? <circle cx={x} cy={y} r={DOT_R} fill={pattern} /> : null}
            {/*
              테두리를 맨 위 빈 원으로 따로 그린다. 채움 원에 얹으면 패턴 원이
              선의 안쪽 절반을 덮어 위험 표시가 반 두께로 보인다.
            */}
            <circle
              className={dotClass}
              cx={x}
              cy={y}
              r={DOT_R}
              fill="none"
              vectorEffect="non-scaling-stroke"
            />
            {risky ? (
              (() => {
                const place = labelPlacement(point.vessel.name, x, y)
                return (
                  <text
                    className="position-chart__label"
                    x={place.x}
                    y={place.y}
                    textAnchor={place.anchor}
                    fontSize={LABEL_FONT}
                    fill={color}
                  >
                    {point.vessel.name}
                  </text>
                )
              })()
            ) : null}
          </g>
        )
      })}
    </svg>
    {/*
      좌표 범위를 그림 밖 글로 적는다.
      뷰박스 안에 눈금 숫자를 넣지 않는 이유는 두 가지다 — ⑴ 유저 단위라
      배율을 타서 크기가 흔들리고(이름표가 46px로 그려지던 것이 그 사례다),
      ⑵ 개략도에 눈금이 붙으면 좌표를 읽을 수 있는 그림처럼 보인다.

      좌표는 `§3`에 따라 mono로 적는다 — 「식별자용 mono는 IMO 번호·좌표 전용」.
    */}
    <p className="position-chart__range">
      위도 <span className="position-chart__coord">{formatLat(minLat)}</span>~
      <span className="position-chart__coord">{formatLat(maxLat)}</span>
      {' · '}
      경도 <span className="position-chart__coord">{formatLon(minLon)}</span>~
      <span className="position-chart__coord">{formatLon(maxLon)}</span>
    </p>
    </>
  )
}
