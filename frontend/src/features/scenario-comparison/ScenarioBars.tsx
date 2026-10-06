import { useId, useState } from 'react'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString, formatGrouped } from '../../display/format'
import { shareOfMax } from '../../display/decimal'
import type { ScenarioResult } from './types'

/**
 * 항목별 미니 막대 (#2202) — 비교 표의 숫자를 세 안끼리 눈으로 맞춰 보는 수고를 던다.
 *
 * 링카고(2024 대상작)의 견적 비교 화면에서 가져온 패턴이다 — 항목 드롭다운을 바꾸면
 * 업체 셋이 가로 막대로 비교된다.
 *
 * ## 표를 대신하지 않는다
 *
 * 숫자 · 증감 · 등급은 위 비교 표가 말한다. 이 부품은 **한 항목을 길이로 한 번 더**
 * 보일 뿐이고, 값은 같은 응답 · 같은 표시 자릿수에서 나온다(`shareOfMax`). 화면에서
 * 다시 계산하지 않는다.
 *
 * ## 중립 (`PRD §11.2` · `DESIGN_SYSTEM §11` · `§8.6` 항로 비교 행)
 *
 * - **순서는 표와 같다** — 값으로 정렬하지 않는다. 정렬하는 순간 1등이 생긴다
 * - **「최소」 · 「추천」 표시를 붙이지 않는다** — 지표별 최소값은 표 아래 줄이 이미 적는다
 * - **막대 색은 하나다** — 시나리오마다 색을 달리하면 한 안이 눈에 띈다. 시나리오는
 *   각 줄 앞의 이름 글자가 가른다(§14 — 색이 뜻을 나르지 않는다). 계열색(§9.3)은 선 ·
 *   영역 차트의 것이고, 생성 토큰에도 아직 없다(`tokens.css` #831 ⑷)
 *
 * ## 낭독
 *
 * 각 줄에 이름과 값이 글자로 있다. 막대 자체는 장식이라 `aria-hidden`이다.
 */
type BarMetric = 'attained_cii' | 'duration_hours' | 'fuel_ton' | 'co2_emission_ton'

interface MetricDef {
  readonly key: BarMetric
  readonly label: string
  readonly digits: number
  readonly unit: string
  readonly format: (value: string) => string
}

function metricDefs(ciiUnit: string): readonly MetricDef[] {
  return [
    {
      key: 'attained_cii',
      label: 'CII',
      digits: DISPLAY_DIGITS.cii,
      unit: ciiUnit,
      format: (v) => formatDecimalString(v, DISPLAY_DIGITS.cii),
    },
    {
      key: 'duration_hours',
      label: '예상 소요시간',
      digits: DISPLAY_DIGITS.durationHours,
      unit: DISPLAY_UNITS.duration,
      format: (v) => formatDecimalString(v, DISPLAY_DIGITS.durationHours),
    },
    {
      key: 'fuel_ton',
      label: '예상 연료',
      digits: DISPLAY_DIGITS.fuelTon,
      unit: DISPLAY_UNITS.fuel,
      format: (v) => formatGrouped(v, DISPLAY_DIGITS.fuelTon),
    },
    {
      key: 'co2_emission_ton',
      label: 'CO₂ 배출량',
      digits: DISPLAY_DIGITS.co2Ton,
      unit: DISPLAY_UNITS.co2,
      format: (v) => formatGrouped(v, DISPLAY_DIGITS.co2Ton),
    },
  ]
}

export function ScenarioBars({
  scenarios,
  ciiUnit,
}: {
  scenarios: readonly ScenarioResult[]
  ciiUnit: string
}) {
  const selectId = useId()
  const defs = metricDefs(ciiUnit)
  const [metric, setMetric] = useState<BarMetric>('attained_cii')
  const def = defs.find((d) => d.key === metric) ?? defs[0]
  const widths = shareOfMax(
    scenarios.map((s) => s[def.key]),
    def.digits,
  )

  if (scenarios.length === 0) return null

  return (
    <section className="scenario-bars" aria-labelledby={`${selectId}-title`}>
      <div className="scenario-bars__head">
        <h3 id={`${selectId}-title`} className="scenario-bars__title">
          항목별로 나란히 보기
        </h3>
        <label htmlFor={selectId}>
          <span className="sr-only">막대로 볼 항목</span>
          <select
            id={selectId}
            value={metric}
            onChange={(event) => setMetric(event.target.value as BarMetric)}
          >
            {defs.map((d) => (
              <option key={d.key} value={d.key}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ul className="scenario-bars__list">
        {scenarios.map((scenario, index) => (
          <li key={scenario.scenario_type} className="scenario-bars__row">
            <span className="scenario-bars__name">{scenario.scenario_name}</span>
            <span className="scenario-bars__track" aria-hidden="true">
              <span className="scenario-bars__fill" style={{ inlineSize: `${widths[index]}%` }} />
            </span>
            <span className="scenario-bars__value">
              {def.format(scenario[def.key])}
              <span className="scenario-bars__unit"> {def.unit}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="scenario-bars__note">막대는 0에서 시작하며, 값의 순서가 아니라 표의 순서대로 놓입니다.</p>
    </section>
  )
}
