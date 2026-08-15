import { useEffect, useMemo, useState } from 'react'
import './ScenarioComparison.css'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString, formatGrouped, formatPercent } from '../../display/format'
import { ciiUnit, marginDisplay, riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { GradeBadge } from '../../components/GradeBadge'
import {
  createDemoScenarioProvider,
  ESTIMATE_NOTICE,
  NO_AUTO_DECISION_NOTICE,
} from './demoProvider'
import { lowestSummary } from './comparisonRules'
import type {
  ScenarioComparisonRequest,
  ScenarioComparisonResponse,
  ScenarioResult,
} from './types'

/**
 * 기능② 시나리오 비교 (#156).
 *
 * ## 추천하지 않는다 — `PRD §11.2`
 *
 * > 시스템은 `추천 시나리오`를 표시하지 않는다. 대신 각 지표별 최소값을
 * > **중립적으로** 표시한다.
 *
 * 종합 점수를 매기거나 하나를 강조하지 않는다. 지표마다 따로 최소값을 적고,
 * 어느 지표가 중요한지는 사용자가 정한다(`PRD §6.3` 「자동 결정 금지」).
 *
 * ## 8/8 범위에는 입력 폼이 없다
 *
 * `PRD §11.3`의 입력(현재 좌표·목적항 등)은 `#139` 소관이다. 이 화면은 기준 조건을
 * 상수로 넘기고 비교 결과만 보여 준다. **요청 타입은 `#57` 구조에 맞춰 두어**
 * 실 API 연결 시 provider 구현체만 바뀌게 한다.
 *
 * ## 표시 규칙은 기능①과 같다
 *
 * 자릿수·구분자는 `format.ts`, 단위·위험도·경고 문구는 `voyage-cii/resultRules.ts`를
 * 그대로 쓴다. 두 화면이 각자 규칙을 두면 한쪽만 정본을 따라가게 된다.
 */

/**
 * 8/8 시연 기준 조건. `PRD §13.1` Fixture 1의 선박·조건과 같다 —
 * 기능①에서 본 값이 기능②의 `직항`으로 다시 나와 두 화면이 이어진다.
 */
const DEMO_REQUEST: ScenarioComparisonRequest = {
  vessel_id: '00000000-0000-4000-8000-000000000001',
  regulation_year: 2026,
  base_distance_nm: 1000,
  base_speed_kn: 14,
  base_fuel_ton: 80,
  fuel_type: 'HFO',
}

type LoadState =
  | { status: 'loading' }
  | { status: 'success'; response: ScenarioComparisonResponse }
  | { status: 'error'; message: string }

export function ScenarioComparison({
  onDisclaimer,
}: {
  /** 면책 배너는 페이지가 항상 렌더한다(`DESIGN_SYSTEM §13` 🔒). */
  onDisclaimer?: (text: string | undefined) => void
}) {
  const provider = useMemo(() => createDemoScenarioProvider(), [])
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
    let alive = true
    provider.compare(DEMO_REQUEST).then(
      (response) => {
        if (!alive) return
        setState({ status: 'success', response })
        onDisclaimer?.(response.disclaimer)
      },
      (error: unknown) => {
        if (!alive) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : '비교에 실패했습니다.',
        })
      },
    )
    return () => {
      alive = false
    }
  }, [provider, onDisclaimer])

  if (state.status === 'loading') {
    return (
      <section className="scenario-comparison scenario-comparison--placeholder" aria-live="polite">
        <p>시나리오를 계산하는 중입니다…</p>
      </section>
    )
  }

  if (state.status === 'error') {
    return (
      <section className="scenario-comparison scenario-comparison--error" aria-live="assertive">
        <p className="scenario-comparison__error-title">비교에 실패했습니다</p>
        <p className="scenario-comparison__error-message">{state.message}</p>
      </section>
    )
  }

  const { response } = state
  const unit = ciiUnit(response.transport_capacity_basis)
  const summary = lowestSummary(response.scenarios)
  const nameOf = (type: string | null) =>
    response.scenarios.find((s) => s.scenario_type === type)?.scenario_name ?? '—'

  return (
    <section className="scenario-comparison">
      <header className="scenario-comparison__header">
        <h2 className="scenario-comparison__title">
          시나리오 비교
          <span className="scenario-comparison__title-en"> Scenario Comparison</span>
        </h2>
        <p className="scenario-comparison__context">
          {response.vessel_display_name} · {DEMO_REQUEST.regulation_year}년 기준 ·
          기준 CII {formatDecimalString(response.required_cii, DISPLAY_DIGITS.cii)} {unit}
        </p>
      </header>

      {/* PRD §6.3 — 「추정값 사용」·「자동 결정 금지」 문구를 그대로 쓴다 */}
      <p className="scenario-comparison__notice">
        {ESTIMATE_NOTICE} {NO_AUTO_DECISION_NOTICE}
      </p>

      <div className="scenario-comparison__cards">
        {response.scenarios.map((scenario) => (
          <ScenarioCard key={scenario.scenario_type} scenario={scenario} unit={unit} />
        ))}
      </div>

      {/*
        PRD §11.2 — 추천 시나리오를 표시하지 않고 지표별 최소값만 중립적으로 적는다.
        하나를 고르지 않으므로 세 줄의 답이 서로 다를 수 있다.
      */}
      <dl className="scenario-comparison__lowest">
        {summary.map((item) => (
          <div key={item.metric} className="scenario-comparison__lowest-row">
            <dt>{item.label}</dt>
            <dd>{nameOf(item.scenarioType)}</dd>
          </div>
        ))}
      </dl>

      {response.warnings.length > 0 ? (
        <ul className="scenario-comparison__warnings">
          {response.warnings.map((code) => (
            <li key={code} className="scenario-comparison__warning">
              <span aria-hidden="true">⚠</span> {warningMessage(code)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

/* ------------------------------------------------------------------ */

function ScenarioCard({ scenario, unit }: { scenario: ScenarioResult; unit: string }) {
  const margin = marginDisplay(
    scenario.estimated_rating,
    scenario.next_worse_boundary_margin_ratio,
  )
  const risk = riskLabel(scenario.risk_level)

  return (
    <article className="scenario-card">
      <header className="scenario-card__head">
        <div>
          <p className="scenario-card__name">{scenario.scenario_name}</p>
          <p className="scenario-card__type">{scenario.scenario_type}</p>
        </div>
        <GradeBadge
          rating={scenario.estimated_rating}
          label={`${scenario.scenario_name} 참고 등급 ${scenario.estimated_rating}`}
          size="sm"
        />
      </header>

      <p className="scenario-card__cii">
        {formatDecimalString(scenario.attained_cii, DISPLAY_DIGITS.cii)}
        <span className="scenario-card__cii-unit"> {unit}</span>
      </p>

      <p className="scenario-card__margin">{margin.text}</p>

      <p className="scenario-card__risk">
        <span className="scenario-card__risk-label">위험도</span>
        {risk.withIcon ? (
          // §2.5 (b) — 라벨이 항상 옆에 있으므로 aria-hidden
          <span className="scenario-card__risk-icon" aria-hidden="true">
            ⚠
          </span>
        ) : null}
        <span
          className={`scenario-card__risk-value scenario-card__risk-value--${scenario.risk_level.toLowerCase()}`}
        >
          {risk.text}
        </span>
      </p>

      <dl className="scenario-card__rows">
        <Row label="항해거리" value={formatGrouped(String(scenario.distance_nm), DISPLAY_DIGITS.distanceNm)} unit={DISPLAY_UNITS.distance} />
        <Row label="평균 속력" value={String(scenario.speed_kn)} unit={DISPLAY_UNITS.speed} />
        <Row label="예상 소요시간" value={formatDecimalString(scenario.duration_hours, DISPLAY_DIGITS.durationHours)} unit={DISPLAY_UNITS.duration} />
        <Row label="예상 연료" value={formatGrouped(scenario.fuel_ton, DISPLAY_DIGITS.fuelTon)} unit={DISPLAY_UNITS.fuel} />
        <Row label="CO₂ 배출량" value={formatGrouped(scenario.co2_emission_ton, DISPLAY_DIGITS.co2Ton)} unit={DISPLAY_UNITS.co2} />
        <Row label="기준 대비" value={`${formatPercent(scenario.ratio_to_required)}%`} />
      </dl>
    </article>
  )
}

function Row({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="scenario-card__row">
      <dt>{label}</dt>
      <dd>
        {value}
        {unit ? <span className="scenario-card__row-unit"> {unit}</span> : null}
      </dd>
    </div>
  )
}
