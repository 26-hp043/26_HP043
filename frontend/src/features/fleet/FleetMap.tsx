import { useCallback, useId, useMemo, type ReactNode } from 'react'
import './FleetMap.css'
import type { MapVessel } from './types'
import {
  seaRouteKey,
  useSeaRoutes,
  type RouteLine,
} from './seaRoute'
import { getKnownRouteSource } from '../map/routeGeometry'
import { routeDisclosure } from '../map/routeDisclosure'
import { adaptFleetMap } from '../map/adapters'
import { MapRendererHost, type MapRendererEvent } from '../map/renderer'
import { mapQualityPolicy } from '../map/quality'
import { mapLibreRenderer, type MapLibreMapModel } from '../map/mapLibreRenderer'
import { useSamplePorts } from '../ports/samplePorts'
import { routeFeatureCollection } from '../map/routeModel'
import { VESSEL_GRID, VESSEL_PATHS } from '../../components/vesselShape'
import { HarborTransitionShell } from '../map/HarborTransitionShell'
import { MapAlternative } from '../map/MapAlternative'
import {
  isAtRisk,
  missingPositionAria,
  missingPositionText,
  NO_POSITION_RECORDED_TEXT,
} from './fleetRules'

/**
 * 선대 지도 (`#763`).
 *
 * ## 타일은 우리 오리진의 파일 하나다
 *
 * 키가 없고 런타임 외부 요청이 없다 — 자세한 근거는 `basemap.ts`. 자산이 없으면 이
 * 컴포넌트는 **그려지지 않고**, 호출부가 개략도(`PositionChart`)를 대신 그린다.
 *
 * ## 마커는 개략도와 같은 언어를 쓴다
 *
 * 배 모양(`vesselShape`)과 등급 색을 그대로 옮긴다. 지도로 바뀌었다고 기호가 달라지면
 * 같은 화면의 등급 분포·선박 카드와 읽는 법이 갈린다.
 *
 * ⚠️ **등급을 색으로만 말하지 않는다**(`DESIGN_SYSTEM §14`). 마커에 등급 문자를 함께
 * 적는다 — 개략도는 SVG `<pattern>`으로 무늬를 덮지만, 지도 마커는 DOM 요소라 같은
 * 패턴 정의를 쓸 수 없다. **문자가 그 자리를 대신한다**(`§15.1`이 「패턴 없는 A」를
 * 허용하는 근거와 같다 — 등급 문자가 항상 함께 놓인다).
 *
 * ## 항로선은 진행 중 항차에만
 *
 * `route`가 있는 선박만 그린다. 없는 배는 점만 남는다 — **없는 항로를 지어내지 않는다.**
 *
 * ## 선은 공개 해상 경로망 위의 바닷길이다 (`#1300` · `PRD §5.2`)
 *
 * 종전에는 두 항을 잇는 **대권선**이었다 — 최단 경로라 육지를 가로질렀다(`#1275`). 지금은
 * 서버(`API_SPEC §3.11`)가 Eurostat 경로망에서 찾은 선을 받아 그린다(`seaRoute.ts`).
 * **표의 거리는 그대로다** — 계산 거리는 사용자 입력 또는 대권거리이고(`PRD §15.2`) 이
 * 선은 표시일 뿐이다. 서버가 선을 주지 못하면 **그리지 않고 그 사실을 적는다** —
 * 대권선으로 되돌리면 캡션(「경로망 위의 경로」)이 거짓이 된다.
 */

/**
 * 선박과 무관하게 그리는 항로 하나 (`#1265` · `#1300`).
 *
 * 항로 비교(`UIFLOW 2-2`)가 쓴다. 직항은 현재 위치 → 목적항이고, 고급 설정에 우회
 * 경유지를 넣으면 **우회 선이 하나 더** 온다(`kind: 'DETOUR'` · `via`) — 세 시나리오 중
 * 감속은 직항과 같은 길이라 선이 둘을 넘지 않는다(`PRD §11.3`).
 */
/** 못 그린 선이 있을 때 지도 옆에 적는 문장 — 선을 지어내지 않고 그 사실을 말한다. */
export const ROUTE_UNAVAILABLE_TEXT = '항로선을 불러오지 못했습니다 — 위치만 표시합니다.'

/**
 * 선 **일부만** 못 받았을 때의 문장 (`#1856`). 받은 선은 그려져 있으므로 「위치만 표시합니다」는
 * 거짓이 된다 — 전부 못 받았을 때와 문장을 가른다. 표시 문구(`AGENTS §4.6`) · 개발 임시안이며
 * 디자인 담당이 바꿀 수 있다.
 */
export const ROUTE_PARTIAL_TEXT = '항로선 일부를 불러오지 못했습니다 — 그리지 못한 항로는 위치만 표시합니다.'

/**
 * 경로망 출처 표기 (`#1300` 결정 5항 — `README` · `NOTICE` · 화면 세 곳).
 *
 * 지도 오른쪽 아래 접힌 출처 컨트롤에 「© OpenStreetMap」과 나란히 실린다(MapLibre가
 * 소스별 attribution을 모은다). 경로망 데이터는 Eurostat SeaRoute(EUPL-1.2), 그것을
 * 번들한 파이썬 패키지 `searoute`는 Apache-2.0이다. ⚠️ 문구·자리는 **개발 임시안**이며
 * 디자인 담당 검토 대상이다(`DESIGN_SYSTEM §9.5` 출처 표기는 「© OpenStreetMap」으로 확정돼 있다).
 */
const ROUTE_SOURCE = getKnownRouteSource('searoute/marnet')!
export const ROUTE_ATTRIBUTION = ROUTE_SOURCE.attribution

/**
 * 빈 기본값을 **모듈 상수로** 둔다.
 *
 * `routes = []`로 쓰면 렌더마다 새 배열이 만들어져 아래 마커 effect의 의존 배열이
 * 매번 달라진다 — **무한 재실행**이 된다. 호출부가 프롭을 생략해도 같은 참조다.
 */
const NO_ROUTES: readonly RouteLine[] = []

interface FleetMapProps {
  vessels: readonly MapVessel[]
  /** 선박에서 파생하지 않는 항로. 생략하면 종전과 같다. */
  routes?: readonly RouteLine[]
  /**
   * 낭독 라벨·읽는 법 문구 (`#1265`).
   *
   * 기본 문안은 **선대 화면 기준**이라(「선박 N척」·「테두리가 굵은 표는 주의 대상」)
   * 선박을 그리지 않는 화면에서는 그대로 두면 **틀린 말이 된다.** 생략하면 종전과 같다.
   */
  ariaLabel?: string
  caption?: ReactNode
  /**
   * 서버가 항로선을 주지 못했을 때 지도 옆에 적는 문장 (`#1300`). 기본 문안은 선대 화면
   * 기준(「위치만 표시합니다」)이라 선박을 그리지 않는 화면에서는 틀린 말이 된다 —
   * `ariaLabel`·`caption`과 같은 이유로 호출부가 넘긴다. 생략하면 선대 문안이다.
   */
  routeUnavailableText?: string
  /** 선 **일부만** 못 받았을 때의 문장 (`#1856`). `routeUnavailableText`와 같은 이유로 호출부가 넘긴다. */
  routePartialText?: string
  /**
   * 재시도 신호 (`#1856`). 값이 바뀌면 **못 받은 선만** 다시 묻는다 — 받은 선은 다시 묻지
   * 않는다(`useSeaRoutes`). 생략하면 실패한 선은 이 지도가 떠 있는 동안 다시 묻지 않는다.
   */
  retryToken?: number
  /** 공용 renderer의 제품 화면 구분. */
  mapMode?: 'fleet' | 'comparison'
  /**
   * 대체 정보(접힌 텍스트)의 제목 (`#1913`). 기본 문안 「선대 현재 위치 지도」는
   * **선대 화면 기준**이라 한 척을 그리는 화면에서는 틀린 말이 된다 —
   * `ariaLabel`·`caption`과 같은 이유로 호출부가 넘긴다.
   */
  alternativeTitle?: string
  /** renderer/WebGL 실패 시 호출부가 개략도로 전환한다. */
  onRendererError?: (error: Error) => void
}

/**
 * 마커 DOM. 배 모양 + 등급색 + 등급 문자.
 *
 * `hullIs3d`면 **배 모양을 그리지 않는다** (`#1917`) — three가 3D 선체를 그리는데
 * 평면 SVG 배까지 그리면 같은 자리에 배가 둘이 된다. 등급 문자 배지는 남는다.
 */
function markerElement(vessel: MapVessel, hullIs3d = false): HTMLElement {
  const root = document.createElement('div')
  root.className = 'fleetmap__marker'
  const rating = vessel.ytdRating
  root.classList.add(rating ? `fleetmap__marker--${rating.toLowerCase()}` : 'fleetmap__marker--none')
  // 판정을 넘기지 않은 호출자(선박 상세 등)는 「위험 없음」이 아니라 **판정 없음**이다.
  const atRisk = isAtRisk({ riskReasons: vessel.riskReasons ?? [] })
  if (atRisk) root.classList.add('fleetmap__marker--risk')

  if (hullIs3d) root.classList.add('fleetmap__marker--hull3d')
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', `0 0 ${VESSEL_GRID} ${VESSEL_GRID}`)
  svg.setAttribute('aria-hidden', 'true')
  /*
   * 선수 방향 (#1824 · `DESIGN_SYSTEM §9.5` v2.28) — 서버가 준 `course_deg`만큼
   * 돌린다(북 = 0 · 시계 방향).
   *
   * ⚠️ **화면이 계산하지 않는다.** 같은 방위를 내는 `initial_bearing_deg`가 서버에
   * 있고 항로 비교의 기상 보정이 그 함수를 쓴다(`#1804` · `#1672` 회신 ⑴) — 여기서
   * 다시 계산하면 지도와 항로 비교가 다른 값을 말할 수 있다.
   *
   * **값이 없으면 돌리지 않는다** — 없는 방향을 0°(북)로 그리면 「북쪽으로 간다」는
   * 거짓을 그리는 것이다. 정박·묘박처럼 목적항이 없는 배가 여기 든다.
   *
   * 배지는 함께 돌지 않는다 — 글자가 뒤집히면 등급을 읽을 수 없다(`§14` 문자 채널).
   */
  const course = vessel.courseDeg === null ? null : Number(vessel.courseDeg)
  if (course !== null && Number.isFinite(course)) {
    svg.style.transform = `rotate(${course}deg)`
  }
  for (const d of VESSEL_PATHS) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', d)
    svg.appendChild(path)
  }
  root.appendChild(svg)

  /*
   * 정박 · 묘박의 닻 배지 (#1824 · 정본 v2.28). `detail_status`의 NOT_UNDER_WAY
   * 다섯이 여기 든다 — 접안 · 묘박 · 표류 · 선박 간 이적 · 운하 통과.
   * **배 모양은 그대로**다. 갈리는 것은 이 배지 하나이고, 낭독은 아래 이름표가 받는다.
   */
  const moored = vessel.underwayState === 'NOT_UNDER_WAY'
  if (moored) {
    const anchor = document.createElement('span')
    anchor.className = 'fleetmap__anchor'
    anchor.setAttribute('aria-hidden', 'true')
    anchor.textContent = '⚓'
    root.appendChild(anchor)
  }

  const label = document.createElement('span')
  label.className = 'fleetmap__badge'
  // 색 단독 금지 (`§14`). 등급이 없으면 「—」로 둔다 — 빈 칸은 「A」로 읽힌다.
  label.textContent = rating ?? '—'
  root.appendChild(label)

  root.setAttribute('role', 'img')
  root.setAttribute(
    'aria-label',
    `${vessel.name} · 등급 ${rating ?? '없음'}${moored ? ' · 정박 중' : ''}${atRisk ? ' · 주의' : ''}`,
  )
  return root
}

export function FleetMap({
  vessels,
  routes = NO_ROUTES,
  ariaLabel,
  caption,
  routeUnavailableText = ROUTE_UNAVAILABLE_TEXT,
  routePartialText = ROUTE_PARTIAL_TEXT,
  retryToken,
  mapMode = 'fleet',
  alternativeTitle = '선대 현재 위치 지도',
  onRendererError,
}: FleetMapProps) {
  const samplePorts = useSamplePorts()
  /*
   * 좌표가 없는 선박은 `placed()`에서 **조용히 빠진다** (#1103).
   *
   * 개략도(`PositionChart`)는 몇 척이 빠졌는지 적는데 이 지도만 아무 말도 하지
   * 않았다 — 4척 중 1척이 미입력이면 지도에 3척만 그려지고 **그 3척이 선대 전부로**
   * 읽힌다. 문구는 개략도와 **같은 원천**(`fleetRules`)을 쓴다.
   */
  const adapted = useMemo(() => adaptFleetMap(vessels, routes, samplePorts), [vessels, routes, samplePorts])
  const shown = adapted.positions.length
  const missingText = missingPositionText(vessels.length, shown)
  // 렌더마다 새 배열이면 아래 effect가 매번 다시 돈다 — `NO_ROUTES`와 같은 이유로 고정한다.
  const asks = adapted.routes
  const lines = useSeaRoutes(
    asks.map((ask) => ask.request),
    undefined,
    retryToken,
  )
  /*
   * 못 받은 선이 **전부인가 일부인가** (`#1856`). 서버는 세 점 요청을 한 덩어리로 실패시키므로
   * 우회만 실패하고 직항은 그려질 수 있다 — 그때 「그려지지 않습니다」라고 적으면 거짓이다.
   */
  const failedAsks = asks.filter((ask) => lines[seaRouteKey(ask.request)] === 'failed').length
  const routeFailure =
    failedAsks === 0 ? null : failedAsks === asks.length ? routeUnavailableText : routePartialText
  const hintId = useId()
  const disclosure = routeDisclosure({
    mode: mapMode,
    source: ROUTE_SOURCE,
    kinds: asks.map(({ kind }) => kind),
  })
  const handleRendererEvent = useCallback((event: MapRendererEvent) => {
    if (event.type === 'error') onRendererError?.(event.error)
  }, [onRendererError])

  /*
   * 3D 선체를 쓸 수 있는 환경인가 (`#1917`).
   *
   * 켜지면 마커는 **등급 배지만** 남긴다 — 3D 선체가 배를 그리는데 평면 SVG 배까지
   * 그리면 같은 자리에 배가 둘이 된다. ⚠️ **등급 문자를 지우지 않는다**
   * (`DESIGN_SYSTEM §14` — 색으로만 말하지 않는다). 선체가 색을, 배지가 문자를 맡는다.
   */
  const vesselsAre3d = mapQualityPolicy().globe
  const rendererMarkers = useMemo(() => adapted.positions.map(({ vessel, lon, lat }) => ({
    coordinate: [lon, lat] as const, element: markerElement(vessel, vesselsAre3d),
  })), [adapted.positions, vesselsAre3d])
  const rendererModel = useMemo<MapLibreMapModel>(() => {
    const points = adapted.positions
    const bounds: [number, number][] = points.map(({ lon, lat }) => [lon, lat])
    for (const { request } of asks) {
      bounds.push([request.fromLon, request.fromLat], [request.toLon, request.toLat])
      if (request.via) bounds.push([request.via.lon, request.via.lat])
    }
    return {
      mode: mapMode,
      ports: adapted.ports,
      markers: rendererMarkers,
      vessels: adapted.positions.map(({ vessel, lon, lat }) => ({
        id: vessel.id,
        coordinate: [lon, lat] as const,
        heading: vessel.courseDeg === null || vessel.courseDeg === undefined || !Number.isFinite(Number(vessel.courseDeg))
          ? null
          : Number(vessel.courseDeg),
        // 선체 색이 등급을 잇는다 (`#1917`). 문자 채널은 아래 마커 배지가 계속 맡는다.
        rating: vessel.ytdRating,
      })),
      routes: { data: routeFeatureCollection(asks, lines), attribution: ROUTE_ATTRIBUTION, bounds },
    }
  }, [adapted.positions, adapted.ports, asks, lines, rendererMarkers, mapMode])

  if (vessels.length > 0 && shown === 0) {
    // 전부 빠진 경우는 빈 지도를 띄우지 않는다 — 빈 바다는 「선박이 없다」로 읽힌다.
    return (
      <div className="fleetmap">
        <p className="fleetmap__missing">{NO_POSITION_RECORDED_TEXT}</p>
      </div>
    )
  }

  return (
    <div className="fleetmap">
      {/*
        그림 요약을 접근성 트리에 싣는다 — 지도는 캔버스라 화면 낭독이 읽을 것이
        없다. 결측도 여기 넣는다(`missingPositionAria`): 눈으로 보는 쪽에만 있으면
        낭독으로는 빠진 것이 없는 것처럼 들린다.
      */}
      <HarborTransitionShell onGlobeEvent={handleRendererEvent} renderGlobe={(onEvent) => (
        <MapRendererHost
          className="fleetmap__canvas"
          model={rendererModel}
          renderer={mapLibreRenderer}
          ariaLabel={
            ariaLabel ??
            `선박 ${shown}척의 현재 위치 지도.${missingPositionAria(vessels.length, shown)}`
          }
          ariaDescribedBy={hintId}
          onEvent={onEvent}
        />
      )} />
      {missingText === null ? null : (
        <p className="fleetmap__missing">{missingText}</p>
      )}
      {/* 서버가 선을 주지 못했다 — 대권선으로 되돌리지 않고 그 사실을 적는다 (`#1300`). */}
      {routeFailure === null ? null : <p className="fleetmap__missing">{routeFailure}</p>}
      {/*
        읽는 법 (`#1052` ⓥ · 2026-09-18 확정).

        **범례를 따로 두지 않는다.** 마커마다 등급 문자가 붙어 있고, 같은 화면 위쪽
        「등급 분포」가 색↔문자 대응을 이미 보여 준다 — 범례를 더하면 같은 대응이
        화면에 세 번 적힌다.

        스스로 설명되지 않는 표식은 **굵은 테두리 하나**뿐이라 이 문장이 받는다.

        ## 세 문장에서 두 문장으로 (#1421)

        첫 문장 「확대·축소로 위치를 확인할 수 있습니다」는 **지도라면 누구나 하는 조작**을
        적은 것이라 뺐다. 남긴 둘은 뺄 수 없다 — 점선이 육지를 가로지르는 이유(`#1275`)와
        굵은 테두리의 뜻(`§9.5` 🔒)은 그림이 스스로 말하지 못한다.

        ⚠️ 「테두리가 굵은 **표**」는 오타였다(`PositionChart`는 「배」로 적는다).

        ## 「최단 경로일 뿐」에서 「경로망 위의 경로」로 (#1300)

        선이 대권선이 아니라 공개 해상 경로망(Eurostat SeaRoute)의 바닷길이 됐으므로
        「육지를 가로지를 수 있다」는 더 이상 사실이 아니다. 대신 **실제 항해 계획이
        아니라는 것**을 말한다 — 경로망은 운항 계획·수심·기상을 모른다.
      */}
      <p className="fleetmap__hint" id={hintId}>
        {caption ?? (
          <>
            {disclosure.visibleText} <b>테두리가 굵은 배</b>는 주의 대상입니다.
          </>
        )}
      </p>
      <MapAlternative id={`${hintId}-alternative`} title={alternativeTitle}
        items={adapted.positions.map(({ vessel, lat, lon }) => `${vessel.name}: 위도 ${lat}, 경도 ${lon}${vessel.route ? ` · 출발 ${vessel.route.departureLat}, ${vessel.route.departureLon} · 도착 ${vessel.route.arrivalLat}, ${vessel.route.arrivalLon}` : ''}`)} />
    </div>
  )
}
