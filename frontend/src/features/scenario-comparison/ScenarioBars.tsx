import { useId } from 'react'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString, formatGrouped } from '../../display/format'
import { percentChangeFixed, shareOfMax } from '../../display/decimal'
import { lowestScenarios } from './comparisonRules'
import type { ScenarioResult } from './types'

/**
 * 항목별 비교 타일 (#2202 · 10/7 디자인 결정).
 *
 * 종전에는 드롭다운으로 고른 항목 **하나**만 막대로 보였고, 지표별 최소값은 그 아래
 * 3줄 목록에 따로 있었다 — 눈이 위아래로 오가야 했다. 이제 CII · 소요시간 · 연료를
 * 타일 셋으로 **한 줄에** 놓고, 각 타일 안에서 최소값을 표시한다.
 *
 * ## 중립 (`PRD §11.2` · `DESIGN_SYSTEM §11`)
 *
 * - **순서는 표와 같다** — 값으로 정렬하지 않는다
 * - 「추천」은 없다. **지표마다 따로** 최소값만 적고, 동률이면 전부 표시한다(`#799`)
 * - 막대 색은 위 지도 칩과 같은 시나리오 3색이다 — 지도와 표를 잇는 범례 역할이고,
 *   세 안 모두 같은 강도로 칠한다. 최소값은 색이 아니라 굵은 글자와 태그가 말한다(§14)
 *
 * ## 값
 *
 * 숫자는 같은 응답 · 같은 표시 자릿수에서 나온다. 증감률은 표시값끼리 `BigInt`로
 * 나눈다(`percentChangeFixed`).
 */
type TileMetric = 'attained_cii' | 'duration_hours' | 'fuel_ton'

interface MetricDef {
  readonly key: TileMetric
  readonly label: string
  readonly lowestTag: string
  readonly digits: number
  readonly unit: string
  readonly format: (value: string) => string
}

function metricDefs(ciiUnit: string): readonly MetricDef[] {
  return [
    {
      key: 'attained_cii',
      label: 'CII',
      lowestTag: '가장 낮음',
      digits: DISPLAY_DIGITS.cii,
      unit: ciiUnit,
      format: (v) => formatDecimalString(v, DISPLAY_DIGITS.cii),
    },
    {
      key: 'duration_hours',
      label: '소요시간',
      lowestTag: '가장 짧음',
      digits: DISPLAY_DIGITS.durationHours,
      unit: DISPLAY_UNITS.duration,
      format: (v) => formatDecimalString(v, DISPLAY_DIGITS.durationHours),
    },
    {
      key: 'fuel_ton',
      label: '연료',
      lowestTag: '가장 적음',
      digits: DISPLAY_DIGITS.fuelTon,
      unit: DISPLAY_UNITS.fuel,
      format: (v) => formatGrouped(v, DISPLAY_DIGITS.fuelTon),
    },
  ]
}

function MetricTile({ def, scenarios }: { def: MetricDef; scenarios: readonly ScenarioResult[] }) {
  const titleId = useId()
  const widths = shareOfMax(
    scenarios.map((s) => s[def.key]),
    def.digits,
  )
  const lowest = lowestScenarios(scenarios, def.key)
  const tie = lowest.length > 1
  const direct = scenarios.find((s) => s.scenario_type === 'DIRECT')
  const best = scenarios.find((s) => s.scenario_type === lowest[0])
  const change =
    !tie && direct !== undefined && best !== undefined && best.scenario_type !== 'DIRECT'
      ? percentChangeFixed(best[def.key], direct[def.key], def.digits)
      : null
  const names = lowest
    .map((type) => scenarios.find((s) => s.scenario_type === type)?.scenario_name ?? '—')
    .join(' · ')

  return (
    <section className="scenario-tile" aria-labelledby={titleId}>
      <h4 id={titleId} className="scenario-tile__title">
        {def.label}
        <span className="scenario-tile__unit"> {def.unit}</span>
      </h4>
      <ul className="scenario-tile__list">
        {scenarios.map((scenario, index) => {
          const isLowest = lowest.includes(scenario.scenario_type)
          return (
            <li
              key={scenario.scenario_type}
              className={`scenario-tile__row scenario-tile__row--${scenario.scenario_type.toLowerCase()}${isLowest ? ' scenario-tile__row--lowest' : ''}`}
            >
              <span className="scenario-tile__name">{scenario.scenario_name}</span>
              <span className="scenario-tile__track" aria-hidden="true">
                <span className="scenario-tile__fill" style={{ inlineSize: `${widths[index]}%` }} />
              </span>
              <span className="scenario-tile__value">
                {def.format(scenario[def.key])}
                {isLowest ? <span className="sr-only"> ({def.lowestTag})</span> : null}
              </span>
            </li>
          )
        })}
      </ul>
      <p className="scenario-tile__foot">
        <span className="scenario-tile__tag">{def.lowestTag}</span>
        <strong className="scenario-tile__best">
          {lowest.length === 0 ? '—' : names}
          {tie ? ' (동률)' : null}
        </strong>
        {change !== null ? (
          <span className="scenario-tile__change">
            <small>직항 대비</small> {change.startsWith('-') ? '−' + change.slice(1) : '+' + change}%
          </span>
        ) : null}
      </p>
    </section>
  )
}

export function ScenarioBars({
  scenarios,
  ciiUnit,
}: {
  scenarios: readonly ScenarioResult[]
  ciiUnit: string
}) {
  const titleId = useId()
  if (scenarios.length === 0) return null
  const defs = metricDefs(ciiUnit)

  return (
    <section className="scenario-bars" aria-labelledby={titleId}>
      <h3 id={titleId} className="scenario-bars__title">
        항목별로 나란히 보기
      </h3>
      <div className="scenario-bars__tiles">
        {defs.map((def) => (
          <MetricTile key={def.key} def={def} scenarios={scenarios} />
        ))}
      </div>
      <p className="scenario-bars__note">막대는 0에서 시작하며, 표와 같은 순서로 놓입니다. 추천이 아니라 항목별 최솟값입니다.</p>
    </section>
  )
}
