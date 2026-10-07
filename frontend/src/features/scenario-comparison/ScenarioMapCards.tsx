import { useState, type ComponentProps } from 'react'
import { GradeBadge } from '../../components/GradeBadge'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { RouteSourceNotice } from '../map/RouteSourceNotice'
import { getKnownRouteSource } from '../map/routeGeometry'
import { routeDisclosure } from '../map/routeDisclosure'
import { VoyageRouteMap } from './VoyageRouteMap'
import type { ScenarioResult, ScenarioType } from './types'
import '../fleet/FleetMap.css'
import './ScenarioMapCards.css'

type MapProps = Omit<ComponentProps<typeof VoyageRouteMap>, 'only' | 'compact' | 'highlight'>

const ORDER: readonly ScenarioType[] = ['DIRECT', 'DETOUR', 'SLOW_STEAMING']

const CAPTION: Readonly<Record<ScenarioType, string>> = {
  DIRECT: '출발항에서 목적항으로 바로',
  DETOUR: '경유지를 지나 돌아가는 길',
  SLOW_STEAMING: '직항과 같은 길을 더 느리게',
}

/*
 * 시나리오 카드 + 지도 하나 (10/7 디자인 결정).
 *
 * 카드마다 지도를 두는 안을 거쳐 **지도는 하나**로 돌아왔다. 직항과 감속은 같은 길이라 지도가
 * 같은 그림을 두 번 그렸고, 「우회하면 얼마나 돌아가나」는 두 선을 한 지도에 겹쳐야 보인다.
 * 카드는 **범례 겸 선택 칩**이다 — 이름 · 선 모양 · 등급 · CII만 둔다. 거리 · 소요 · 연료는 아래
 * 비교 표가 직항 대비 차이까지 함께 말하므로 카드에 되풀이하지 않는다(10/7 — 위아래 중복). 카드는 — 카드에 올리거나 누르면 지도에서 그 선만
 * 앞으로 나온다(감속은 직항선). 우회 경유지를 고르지 않으면 우회는 거리 +5%로만 계산되어 그릴
 * 길이 없다는 것을 우회 카드가 말한다.
 */
export function ScenarioMapCards({
  scenarios,
  map,
  unit,
}: {
  scenarios: readonly ScenarioResult[]
  map: MapProps
  unit: string
}) {
  const [picked, setPicked] = useState<ScenarioType | null>(null)
  const [hovered, setHovered] = useState<ScenarioType | null>(null)
  const active = hovered ?? picked
  const hasWaypoint = (map.detourWaypointLat ?? '') !== '' && (map.detourWaypointLon ?? '') !== ''
  const source = getKnownRouteSource('searoute/marnet')!
  const disclosure = routeDisclosure({
    mode: 'comparison',
    source,
    kinds: hasWaypoint ? ['DIRECT', 'DETOUR'] : ['DIRECT'],
  })
  const ordered = ORDER.map((type) => scenarios.find((s) => s.scenario_type === type)).filter(
    (s): s is ScenarioResult => s !== undefined,
  )
  const highlight =
    active === null
      ? null
      : active === 'DETOUR'
        ? hasWaypoint
          ? 'DETOUR'
          : null
        : active === 'SLOW_STEAMING'
          ? 'SLOW'
          : 'DIRECT'

  return (
    <section className="scenario-maps" aria-label="시나리오별 항로">
      <div className="scenario-maps__grid" role="group" aria-label="지도에서 앞으로 낼 시나리오">
        {ordered.map((scenario) => {
          const type = scenario.scenario_type
          const noLine = type === 'DETOUR' && !hasWaypoint
          return (
            <button
              type="button"
              key={scenario.scenario_id}
              className={`scenario-maps__card scenario-maps__card--${type.toLowerCase()}${active === type ? ' scenario-maps__card--active' : ''}${active !== null && active !== type ? ' scenario-maps__card--dim' : ''}`}
              aria-pressed={picked === type}
              onClick={() => setPicked((p) => (p === type ? null : type))}
              onMouseEnter={() => setHovered(type)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(type)}
              onBlur={() => setHovered(null)}
            >
              <span className="scenario-maps__head">
                <span className="scenario-maps__swatch" aria-hidden="true" />
                <span className="scenario-maps__title">{scenario.scenario_name}</span>
                {/* 칩에서는 설명을 접는다 — 경유지가 없어 선을 못 그릴 때만 그 사실을 적는다 */}
                {noLine ? (
                  <span className="scenario-maps__caption">경유지 없음 · 지도에 선 없음</span>
                ) : type === 'SLOW_STEAMING' ? (
                  <span className="scenario-maps__caption">직항과 같은 길</span>
                ) : (
                  <span className="sr-only">{CAPTION[type]}</span>
                )}
              </span>
              <span className="scenario-maps__facts">
                <span className="scenario-maps__fact scenario-maps__fact--grade">
                  <GradeBadge
                    rating={scenario.estimated_rating}
                    size="sm"
                    label={`${scenario.scenario_name} 참고 등급 ${scenario.estimated_rating}`}
                  />
                  <span className="scenario-maps__cii">
                    {formatDecimalString(scenario.attained_cii, DISPLAY_DIGITS.cii)}
                  </span>
                  <span className="scenario-maps__unit">{unit}</span>
                </span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="scenario-maps__map">
        <VoyageRouteMap {...map} compact highlight={highlight} alternativeTitle="항로 비교 지도" />
      </div>

      <div className="fleetmap__foot">
        <p className="fleetmap__hint">
          <span className="fleetmap__hint-item">카드를 누르면 그 노선만 진하게 · 표시용 항로(실제 항적 아님)</span>
        </p>
        <div className="fleetmap__more-row">
          <details className="fleetmap__more">
            <summary>항로선 안내</summary>
            <p>{disclosure.visibleText}</p>
          </details>
        </div>
        <RouteSourceNotice source={source} />
      </div>
    </section>
  )
}
