import type { FleetVessel } from './types'
import { isAtRisk } from './fleetRules'

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
 * ## 색만으로 구분하지 않는다
 *
 * 등급 색에 더해 **위험 선박에는 이름표와 굵은 테두리**를 준다(`DESIGN_SYSTEM §14`).
 */

/** 좌표가 한 점뿐이거나 모두 같을 때 0으로 나누지 않도록 두는 최소 폭(도). */
const MIN_SPAN = 0.5

/** 여백 — 점이 테두리에 붙지 않게 한다. */
const PADDING = 8

const VIEW_W = 160
const VIEW_H = 100

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
      aria-label={`선박 ${points.length}척의 현재 위치 개략도. 점의 색은 올해 누적 등급입니다.`}
    >
      {points.map((point) => {
        const { x, y } = project(point)
        const rating = point.vessel.ytdRating
        // 등급이 없는 선박(실적 없음)은 중립색 — 나쁜 등급으로 보이면 안 된다.
        const color = rating
          ? `var(--cii-${rating.toLowerCase()}-fill)`
          : 'var(--cii-none-fill)'
        const risky = isAtRisk(point.vessel)

        return (
          <g key={point.vessel.id}>
            <circle
              className={risky ? 'position-chart__dot position-chart__dot--risk' : 'position-chart__dot'}
              cx={x}
              cy={y}
              r="2.6"
              fill={color}
              vectorEffect="non-scaling-stroke"
            />
            {risky ? (
              <text className="position-chart__label" x={x} y={y - 6} textAnchor="middle" fill={color}>
                {point.vessel.name}
              </text>
            ) : null}
          </g>
        )
      })}
    </svg>
  )
}
