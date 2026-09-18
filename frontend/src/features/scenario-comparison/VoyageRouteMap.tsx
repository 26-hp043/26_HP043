import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { hasBasemap } from '../fleet/basemap'
import type { FleetVessel } from '../fleet/types'
import type { RouteLine } from '../fleet/FleetMap'

/**
 * 항로 비교의 위치 맥락 지도 (`#1265`).
 *
 * ## 경로는 하나다 — 세 시나리오를 겹쳐 그리지 않는다
 *
 * `ScenarioResult`에 기하가 없고 좌표는 **한 쌍뿐**이라 세 시나리오가 공유한다.
 * 우회는 `직항 × 1.05`의 **거리 배수**이지 경로가 아니다(`PRD §11.3`). 겹쳐 그리려면
 * 없는 기하를 지어내야 하고, `FleetMap`이 「없는 항로를 지어내지 않는다」를 원칙으로
 * 적고 있다. 시나리오 차이는 **비교 표가 맡는다.**
 *
 * 대권 경로를 그리는 근거는 서버가 쓰는 계산과 같다 — 직항 거리를 비우면 서버가
 * **이 두 점의 대권거리**로 낸다(`PRD §11.2` · `usesCoordinateDistance`).
 *
 * ⚠️ **캡션이 「표의 직항 거리가 이 선의 길이」라고 말하지 않는 이유**가 그것이다.
 * 사용자가 직항 거리를 직접 넣으면 서버는 그 값을 먼저 쓰므로 선의 길이와 표의 숫자가
 * 갈릴 수 있다. 지도는 **어디인가**만 말하고 길이는 표가 말한다.
 *
 * ## 그리지 못하면 아무것도 내지 않는다
 *
 * 좌표는 **선택 입력**이라 비어 있는 것이 기본 경로다(`types.ts` 「직항 거리가 있으면
 * 서버가 그것을 먼저 쓴다」). 없을 때 빈 지도나 오류를 내면 **정상 상태가 고장으로
 * 읽힌다.** 자산이 없을 때도 같다 — 개략도(`PositionChart`)는 선박 기반이라 이 자리에
 * 쓸 수 없다.
 */

/** 지도를 그릴 차례가 왔을 때 받는다 — `FleetDashboard`와 같은 판단이다. */
const FleetMap = lazy(() => import('../fleet/FleetMap').then((m) => ({ default: m.FleetMap })))

/**
 * 빈 배열을 **모듈 상수로** 둔다. 렌더마다 새 배열을 넘기면 `FleetMap`의 마커 effect
 * 의존 배열이 매번 달라져 무한 재실행이 된다(`FleetMap`의 `NO_ROUTES`와 같은 이유).
 */
const NO_VESSELS: FleetVessel[] = []

/** 범위를 벗어나거나 숫자가 아니면 `null`. 폼 검증(`requestRules`)과 같은 한계다. */
function coord(raw: string, limit: number): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  if (!Number.isFinite(value) || Math.abs(value) > limit) return null
  return value
}

interface VoyageRouteMapProps {
  currentLat: string
  currentLon: string
  destinationLat: string
  destinationLon: string
  /** 목적항 이름. 비어 있으면 선 이름을 「목적항」으로 둔다. */
  destinationName?: string
}

export function VoyageRouteMap({
  currentLat,
  currentLon,
  destinationLat,
  destinationLon,
  destinationName = '',
}: VoyageRouteMapProps) {
  const [basemap, setBasemap] = useState<boolean | null>(null)

  useEffect(() => {
    let alive = true
    void hasBasemap().then((found) => {
      if (alive) setBasemap(found)
    })
    return () => {
      alive = false
    }
  }, [])

  const lat1 = coord(currentLat, 90)
  const lon1 = coord(currentLon, 180)
  const lat2 = coord(destinationLat, 90)
  const lon2 = coord(destinationLon, 180)

  const routes = useMemo<RouteLine[]>(() => {
    if (lat1 === null || lon1 === null || lat2 === null || lon2 === null) return []
    return [
      {
        name: destinationName === '' ? '목적항' : destinationName,
        departureLat: lat1,
        departureLon: lon1,
        arrivalLat: lat2,
        arrivalLon: lon2,
      },
    ]
  }, [lat1, lon1, lat2, lon2, destinationName])

  if (routes.length === 0 || basemap !== true) return null

  return (
    <Suspense fallback={null}>
      <FleetMap
        vessels={NO_VESSELS}
        routes={routes}
        ariaLabel="현재 위치에서 목적항까지의 항로 지도."
        caption={
          <>
            <b>세 시나리오가 이 경로를 함께 씁니다.</b> 선은 현재 위치와 목적항을 잇는
            대권 경로입니다. 우회·감속은 거리와 속력만 달라지므로 지도에서는 구분되지
            않습니다 — 차이는 아래 표에 있습니다.
          </>
        }
      />
    </Suspense>
  )
}
