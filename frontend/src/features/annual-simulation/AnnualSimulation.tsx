import { useEffect, useMemo, useState } from 'react'
import './AnnualSimulation.css'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString, formatGrouped, formatPercent } from '../voyage-cii/format'
import { ciiUnit, marginDisplay, riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { GradeBadge } from '../../components/GradeBadge'
import { ANNUAL_COPY } from './copy'
import { createDemoAnnualProvider } from './demoProvider'
import type { AnnualSimulationResult } from './types'

/**
 * 기능③ 연간 CII 시뮬레이션 — **고정값 목업** (#157).
 *
 * ## 화면 문구를 여기 적지 않는다
 *
 * 전부 `copy.ts`에 있다. **이 이슈의 가장 큰 위험이 「근거 없는 표현」**이고,
 * 문구가 JSX에 흩어져 있으면 그 금지를 테스트로 확인할 수 없다.
 * `copy.test.ts`가 「연말」·「예상 등급」·「추천」·`P(D` 를 전수 검사한다.
 *
 * ## 「예시 데이터」 배지를 응답에서 판단한다
 *
 * `is_sample_data` 플래그를 본다. 화면에 상수로 박아 두면 `#63`·`#64` 연결 후에도
 * 남는다.
 *
 * ## 표시 규칙은 기능①과 같다
 *
 * 자릿수·구분자는 `format.ts`, 단위·위험도·경고 문구는 `voyage-cii/resultRules.ts`를
 * 그대로 쓴다.
 */

type LoadState =
  | { status: 'loading' }
  | { status: 'success'; result: AnnualSimulationResult }
  | { status: 'error'; message: string }

export function AnnualSimulation({
  onDisclaimer,
}: {
  /** 면책 배너는 페이지가 항상 렌더한다(`DESIGN_SYSTEM §13` 🔒). */
  onDisclaimer?: (text: string | undefined) => void
}) {
  const provider = useMemo(() => createDemoAnnualProvider(), [])
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
    let alive = true
    provider.load().then(
      (result) => {
        if (!alive) return
        setState({ status: 'success', result })
        onDisclaimer?.(result.disclaimer)
      },
      (error: unknown) => {
        if (!alive) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : ANNUAL_COPY.errorTitle,
        })
      },
    )
    return () => {
      alive = false
    }
  }, [provider, onDisclaimer])

  if (state.status === 'loading') {
    return (
      <section className="annual-sim annual-sim--placeholder" aria-live="polite">
        <p>{ANNUAL_COPY.loading}</p>
      </section>
    )
  }

  if (state.status === 'error') {
    return (
      <section className="annual-sim annual-sim--error" aria-live="assertive">
        <p className="annual-sim__error-title">{ANNUAL_COPY.errorTitle}</p>
        <p className="annual-sim__error-message">{state.message}</p>
      </section>
    )
  }

  const { result } = state
  const unit = ciiUnit(result.transport_capacity_basis)
  const margin = marginDisplay(
    result.estimated_rating,
    result.next_worse_boundary_margin_ratio,
  )
  const risk = riskLabel(result.risk_level)

  return (
    <section className="annual-sim">
      <header className="annual-sim__header">
        <h2 className="annual-sim__title">
          {ANNUAL_COPY.title}
          <span className="annual-sim__title-en"> {ANNUAL_COPY.titleEn}</span>
          {result.is_sample_data ? (
            <span className="annual-sim__badge">{ANNUAL_COPY.sampleBadge}</span>
          ) : null}
        </h2>
        <p className="annual-sim__context">
          {result.vessel_display_name} · {result.regulation_year}년 기준
        </p>
      </header>

      {result.is_sample_data ? (
        <p className="annual-sim__sample-notice">{ANNUAL_COPY.sampleNotice}</p>
      ) : null}

      {/* DESIGN_SYSTEM §11 — 전면 추정 화면의 화면 단위 고지. 외부 출처 없음 */}
      <p className="annual-sim__estimate-notice">{ANNUAL_COPY.estimateNotice}</p>

      {result.months.length === 0 ? (
        <p className="annual-sim__empty">{ANNUAL_COPY.empty}</p>
      ) : (
        <>
          <div className="annual-sim__summary">
            <div className="annual-sim__grade">
              <GradeBadge
                rating={result.estimated_rating}
                label={`${ANNUAL_COPY.ratingLabel} ${result.estimated_rating}`}
              />
              <div className="annual-sim__grade-meta">
                <p className="annual-sim__grade-label">{ANNUAL_COPY.ratingLabel}</p>
                <p className="annual-sim__margin">{margin.text}</p>
                <p className="annual-sim__risk">
                  <span className="annual-sim__risk-label">{ANNUAL_COPY.riskLabel}</span>
                  {risk.withIcon ? (
                    <span className="annual-sim__risk-icon" aria-hidden="true">
                      ⚠
                    </span>
                  ) : null}
                  <span
                    className={`annual-sim__risk-value annual-sim__risk-value--${result.risk_level.toLowerCase()}`}
                  >
                    {risk.text}
                  </span>
                </p>
              </div>
            </div>

            <dl className="annual-sim__metrics">
              <Metric
                label={ANNUAL_COPY.attainedLabel}
                value={formatDecimalString(result.attained_cii, DISPLAY_DIGITS.cii)}
                unit={unit}
                emphasis
              />
              <Metric
                label={ANNUAL_COPY.requiredLabel}
                value={formatDecimalString(result.required_cii, DISPLAY_DIGITS.cii)}
                unit={unit}
              />
              <Metric
                label={ANNUAL_COPY.ratioLabel}
                value={`${formatPercent(result.ratio_to_required)}%`}
              />
              <Metric
                label={ANNUAL_COPY.totalDistanceLabel}
                value={formatGrouped(String(result.total_distance_nm), DISPLAY_DIGITS.distanceNm)}
                unit={DISPLAY_UNITS.distance}
              />
              <Metric
                label={ANNUAL_COPY.totalFuelLabel}
                value={formatGrouped(result.total_fuel_ton, DISPLAY_DIGITS.fuelTon)}
                unit={DISPLAY_UNITS.fuel}
              />
              <Metric
                label={ANNUAL_COPY.totalCo2Label}
                value={formatGrouped(result.total_co2_emission_ton, DISPLAY_DIGITS.co2Ton)}
                unit={DISPLAY_UNITS.co2}
              />
            </dl>
          </div>

          <div className="annual-sim__months">
            <h3 className="annual-sim__months-title">{ANNUAL_COPY.monthsTitle}</h3>
            <div className="annual-sim__table-wrap">
              <table className="annual-sim__table">
                <caption className="annual-sim__caption">{ANNUAL_COPY.monthsCaption}</caption>
                <thead>
                  <tr>
                    <th scope="col">{ANNUAL_COPY.columnMonth}</th>
                    <th scope="col">{ANNUAL_COPY.columnVoyages}</th>
                    <th scope="col">{ANNUAL_COPY.columnDistance}</th>
                    <th scope="col">{ANNUAL_COPY.columnFuel}</th>
                    <th scope="col">{ANNUAL_COPY.columnCo2}</th>
                    <th scope="col">{ANNUAL_COPY.columnCii}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.months.map((month) => (
                    <tr key={month.month}>
                      <th scope="row">{month.month}</th>
                      <td>{month.voyage_count}</td>
                      <td>{formatGrouped(String(month.distance_nm), DISPLAY_DIGITS.distanceNm)}</td>
                      <td>{formatGrouped(month.fuel_ton, DISPLAY_DIGITS.fuelTon)}</td>
                      <td>{formatGrouped(month.co2_emission_ton, DISPLAY_DIGITS.co2Ton)}</td>
                      <td>{formatDecimalString(month.attained_cii, DISPLAY_DIGITS.cii)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {result.warnings.length > 0 ? (
        <ul className="annual-sim__warnings">
          {result.warnings.map((code) => (
            <li key={code} className="annual-sim__warning">
              <span aria-hidden="true">⚠</span> {warningMessage(code)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

function Metric({
  label,
  value,
  unit,
  emphasis,
}: {
  label: string
  value: string
  unit?: string
  emphasis?: boolean
}) {
  return (
    <div className={emphasis ? 'annual-sim__metric annual-sim__metric--emphasis' : 'annual-sim__metric'}>
      <dt className="annual-sim__metric-label">{label}</dt>
      <dd className="annual-sim__metric-value">
        {value}
        {unit ? <span className="annual-sim__metric-unit"> {unit}</span> : null}
      </dd>
    </div>
  )
}
