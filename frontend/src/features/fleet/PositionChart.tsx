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

/** 이름표를 마커 위로 띄우는 거리. */
const LABEL_OFFSET = 18

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
    <svg
      className="position-chart"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      role="img"
      aria-label={`선박 ${points.length}척의 현재 위치 개략도. 점의 색과 무늬는 올해 누적 등급입니다.`}
    >
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
              <text
                className="position-chart__label"
                x={x}
                y={y - LABEL_OFFSET}
                textAnchor="middle"
                fill={color}
              >
                {point.vessel.name}
              </text>
            ) : null}
          </g>
        )
      })}
    </svg>
  )
}
