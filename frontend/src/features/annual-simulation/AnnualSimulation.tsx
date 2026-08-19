import { useCallback, useMemo, useState } from 'react'
import './AnnualSimulation.css'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { useShellContext } from '../../layout/shellContext'
import { GradeBadge } from '../../components/GradeBadge'
import { ANNUAL_COPY } from './copy'
import {
  probabilityOfDorE,
  reproducibilityLine,
  riskFlag,
  sensitivityRows,
  stackSegments,
  toPercent,
} from './annualRules'
import { createAnnualSimulationProvider } from './providerSelection'
import type { AnnualSimulationResult } from './types'

/**
 * 기능③ 연간 CII 시뮬레이션 화면 (#157 · **#442에서 실 API 연결**).
 *
 * ## 화면이 계산하지 않는다
 *
 * 결정론 예측·확률 분포·민감도·위험도를 전부 서버가 낸다. 화면이 하는 계산은
 * `P(D∪E)` 파생 하나이며 그 정의도 `PRD §12.5`가 소유한다(`annualRules`).
 *
 * **특히 위험도를 다시 판정하지 않는다** — `PRD §9.4.2`가 기능③의 위험도를 목표 달성
 * 확률 기반으로 규정하고 서버가 확정한다. 화면이 확률을 보고 다시 판정하면 두 곳이
 * 갈리고, 그 차이는 눈으로 발견되지 않는다.
 *
 * ## 왜 버튼을 눌러야 실행되는가
 *
 * v1은 화면을 열면 목업을 자동으로 그렸다. 실 API는 **Monte Carlo 5,000회**가 기본이라
 * (`API_SPEC §6.1`) 화면 진입마다 자동 실행하면 서버 부담이 큰 것은 물론, 사용자가
 * 목표 등급·seed를 고르기 전에 실행돼 **의미 없는 결과를 먼저 보게 된다.**
 *
 * ## 화면 문구를 여기 적지 않는다
 *
 * 전부 `copy.ts`에 있다. `copy.test.ts`가 금지 표현(「연말」·「예상 등급」·「추천」)을
 * 전수 검사한다.
 */

type RunState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'success'; result: AnnualSimulationResult }
  | { status: 'error'; message: string }

/**
 * 기준연도.
 *
 * ⚠️ **아직 고정값이다.** 선박은 `#484`로 상단바 전역 선택을 따르게 됐으나, 연도는
 * 이 화면에 선택 UI가 없다. `GET /parameters/regulation-years`(`#444`)로 열 수 있고
 * `#534`가 CII 예측에 그 경로를 만들어 두었다 — 이 화면 적용은 별건이다.
 */
const DEFAULT_YEAR = 2026

/** `PRD §12.8` — **E는 목록에 없다.** 목표가 최하위 등급이면 「달성」이 의미를 잃는다. */
const TARGET_RATINGS = ['A', 'B', 'C', 'D'] as const

export function AnnualSimulation({
  onDisclaimer,
}: {
  /** 면책 배너는 페이지가 항상 렌더한다(`DESIGN_SYSTEM §13` 🔒). */
  onDisclaimer?: (text: string | undefined) => void
}) {
  // 선박은 **상단바 전역 선택을 따른다** (#484 · #535). 종전에는 UUID가 상수로
  // 박혀 있어, 상단에서 어떤 배를 골라도 늘 같은 배로 계산했다.
  const shell = useShellContext()
  const provider = useMemo(() => createAnnualSimulationProvider(), [])
  const [state, setState] = useState<RunState>({ status: 'idle' })
  const [target, setTarget] = useState<(typeof TARGET_RATINGS)[number]>('B')
  const [runs, setRuns] = useState('5000')
  const [seed, setSeed] = useState('')

  const run = useCallback(async () => {
    if (shell.vesselId === null) {
      setState({ status: 'error', message: '상단에서 선박을 먼저 선택해 주세요.' })
      return
    }
    setState({ status: 'running' })
    try {
      const result = await provider.run({
        vessel_id: shell.vesselId,
        regulation_year: DEFAULT_YEAR,
        target_rating: target,
        simulation_runs: Number(runs),
        // 빈 문자열을 보내지 않는다 — 서버가 「지정했는데 비었다」로 볼 수 있다.
        ...(seed.trim() ? { random_seed: seed.trim() } : {}),
      })
      setState({ status: 'success', result })
      onDisclaimer?.(undefined)
    } catch (error: unknown) {
      setState({
        status: 'error',
        message: error instanceof Error ? error.message : ANNUAL_COPY.errorTitle,
      })
    }
  }, [provider, shell.vesselId, target, runs, seed, onDisclaimer])

  return (
    <section className="annual-sim">
      <header className="annual-sim__head">
        <h2 className="annual-sim__title">
          {ANNUAL_COPY.title}
          <span className="annual-sim__title-en">{ANNUAL_COPY.titleEn}</span>
        </h2>
        {state.status === 'success' && state.result.is_sample_data ? (
          <span className="annual-sim__badge">{ANNUAL_COPY.sampleBadge}</span>
        ) : null}
      </header>

      <form
        className="annual-sim__form"
        onSubmit={(event) => {
          event.preventDefault()
          void run()
        }}
      >
        <h3 className="annual-sim__section-title">{ANNUAL_COPY.runTitle}</h3>

        <label className="annual-sim__field">
          <span className="annual-sim__label">{ANNUAL_COPY.targetRatingLabel}</span>
          <select
            value={target}
            onChange={(event) =>
              setTarget(event.target.value as (typeof TARGET_RATINGS)[number])
            }
          >
            {TARGET_RATINGS.map((rating) => (
              <option key={rating} value={rating}>
                {rating}
              </option>
            ))}
          </select>
          <span className="annual-sim__hint">{ANNUAL_COPY.targetRatingHint}</span>
        </label>

        <label className="annual-sim__field">
          <span className="annual-sim__label">{ANNUAL_COPY.runsLabel}</span>
          <input
            type="number"
            min={1000}
            max={10000}
            step={1000}
            value={runs}
            onChange={(event) => setRuns(event.target.value)}
          />
          <span className="annual-sim__hint">{ANNUAL_COPY.runsHint}</span>
        </label>

        <label className="annual-sim__field">
          <span className="annual-sim__label">{ANNUAL_COPY.seedLabel}</span>
          <input
            type="text"
            inputMode="numeric"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
          />
          <span className="annual-sim__hint">{ANNUAL_COPY.seedHint}</span>
        </label>

        <button type="submit" disabled={state.status === 'running'}>
          {state.status === 'running' ? ANNUAL_COPY.submitting : ANNUAL_COPY.submit}
        </button>
      </form>

      {/*
        결과 전체를 한 겹으로 묶는다. `Result`가 Fragment를 반환하므로 묶지 않으면
        그 안의 블록들이 `.annual-sim`의 직계 자식이 되고, 12컬럼 자동 배치가
        첫 블록만 폼 옆에 올린 뒤 나머지를 아래 줄로 흘려보낸다.
      */}
      <div className="annual-sim__results">
        {state.status === 'idle' ? (
          <p className="annual-sim__placeholder">{ANNUAL_COPY.empty}</p>
        ) : null}
        {state.status === 'running' ? (
          <p className="annual-sim__placeholder" aria-live="polite">
            {ANNUAL_COPY.loading}
          </p>
        ) : null}
        {state.status === 'error' ? (
          <div className="annual-sim__error" aria-live="assertive">
            <strong>{ANNUAL_COPY.errorTitle}</strong>
            <p>{state.message}</p>
          </div>
        ) : null}

        {state.status === 'success' ? <Result result={state.result} /> : null}
      </div>
    </section>
  )
}

function Result({ result }: { result: AnnualSimulationResult }) {
  const { deterministic: det, monte_carlo: mc } = result
  const risk = riskLabel(result.risk_level)
  const pDorE = probabilityOfDorE(mc.rating_probabilities)
  const flag = riskFlag(pDorE)
  const segments = stackSegments(mc.rating_probabilities)
  const rows = sensitivityRows(result.sensitivity_analysis)

  return (
    <>
      {result.is_sample_data ? (
        <p className="annual-sim__notice">{ANNUAL_COPY.sampleNotice}</p>
      ) : (
        <p className="annual-sim__notice">{ANNUAL_COPY.estimateNotice}</p>
      )}

      {/* ── 결정론 (PRD §12.3) ─────────────────────────────────────── */}
      <section className="annual-sim__block">
        <h3 className="annual-sim__section-title">{ANNUAL_COPY.deterministicTitle}</h3>
        <p className="annual-sim__caption">{ANNUAL_COPY.deterministicCaption}</p>
        <div className="annual-sim__metrics">
          <Metric
            label={ANNUAL_COPY.projectedCiiLabel}
            value={formatDecimalString(det.projected_attained_cii, DISPLAY_DIGITS.cii)}
          />
          <div className="annual-sim__metric">
            <span className="annual-sim__label">{ANNUAL_COPY.projectedRatingLabel}</span>
            <GradeBadge
              rating={det.projected_rating}
              size="md"
              label={`${ANNUAL_COPY.projectedRatingLabel} ${det.projected_rating}`}
            />
          </div>
          <Metric
            label={ANNUAL_COPY.completedLabel}
            value={String(det.completed_voyage_count)}
          />
          <Metric
            label={ANNUAL_COPY.remainingLabel}
            value={String(det.remaining_voyage_count)}
          />
        </div>
      </section>

      {/* ── 확률 (PRD §12.4 · §12.5 · DESIGN_SYSTEM §10.2) ─────────── */}
      <section className="annual-sim__block">
        <h3 className="annual-sim__section-title">{ANNUAL_COPY.probabilityTitle}</h3>
        <p className="annual-sim__caption">{ANNUAL_COPY.probabilityCaption}</p>

        <div className="annual-sim__stack" role="img" aria-label={stackAria(segments)}>
          {segments.map((seg) => (
            <span
              key={seg.rating}
              className={`annual-sim__seg annual-sim__seg--${seg.rating.toLowerCase()}`}
              style={{ width: `${seg.percent}%` }}
            />
          ))}
        </div>
        <ul className="annual-sim__legend">
          {segments.map((seg) => (
            <li key={seg.rating}>
              <span
                className={`annual-sim__swatch annual-sim__seg--${seg.rating.toLowerCase()}`}
                aria-hidden="true"
              />
              {seg.rating} {seg.label}
            </li>
          ))}
        </ul>

        <div className="annual-sim__metrics">
          <Metric
            label={ANNUAL_COPY.targetSuccessLabel}
            value={toPercent(mc.target_success_probability)}
            hint={`${ANNUAL_COPY.targetSuccessHint} (${mc.target_rating} 이상)`}
          />
          <div className="annual-sim__metric">
            <span className="annual-sim__label">{ANNUAL_COPY.riskLabel}</span>
            <span className="annual-sim__risk">{risk.text}</span>
            {/* DESIGN_SYSTEM §2.5 (a) — 확률 파생 표기. 위험도와 별개 채널이다. */}
            <span className={`annual-sim__flag annual-sim__flag--${flag.tone}`}>
              {flag.text}
            </span>
          </div>
        </div>

        <h4 className="annual-sim__sub-title">{ANNUAL_COPY.spreadTitle}</h4>
        <div className="annual-sim__metrics">
          <Metric
            label={ANNUAL_COPY.p10Label}
            value={formatDecimalString(mc.p10, DISPLAY_DIGITS.cii)}
          />
          <Metric
            label={ANNUAL_COPY.p50Label}
            value={formatDecimalString(mc.p50, DISPLAY_DIGITS.cii)}
          />
          <Metric
            label={ANNUAL_COPY.p90Label}
            value={formatDecimalString(mc.p90, DISPLAY_DIGITS.cii)}
          />
          <Metric
            label={ANNUAL_COPY.meanLabel}
            value={formatDecimalString(mc.mean_cii, DISPLAY_DIGITS.cii)}
          />
        </div>
      </section>

      {/* ── 민감도 (PRD §12.6) ─────────────────────────────────────── */}
      {rows.length > 0 ? (
        <section className="annual-sim__block">
          <h3 className="annual-sim__section-title">{ANNUAL_COPY.sensitivityTitle}</h3>
          {/*
           * `interaction_note`는 `ORACLE-M-3`이 응답 포함을 지정한 항목이다. 빼면
           * 사용자가 두 변수를 함께 조정했을 때의 결과를 이 표에서 읽으려 한다.
           */}
          <p className="annual-sim__caption">
            {result.sensitivity_analysis.interaction_note}
          </p>
          <div className="annual-sim__tablewrap">
            <table className="annual-sim__table">
              <thead>
                <tr>
                  <th scope="col">{ANNUAL_COPY.columnVariable}</th>
                  <th scope="col">{ANNUAL_COPY.columnProjectedCii}</th>
                  <th scope="col">{ANNUAL_COPY.columnRatingChange}</th>
                  <th scope="col">{ANNUAL_COPY.columnProbabilityChange}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ key, label, entry }) => (
                  <tr key={key}>
                    <th scope="row">
                      {label}
                      {entry.alternative_fuel ? ` (${entry.alternative_fuel})` : ''}
                    </th>
                    <td>{formatDecimalString(entry.projected_cii, DISPLAY_DIGITS.cii)}</td>
                    <td>{entry.rating_change}</td>
                    <td>{entry.target_probability_change ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* ── 재현성 (TECH_SPEC §5.2 · §11) ──────────────────────────── */}
      <section className="annual-sim__block">
        <h3 className="annual-sim__section-title">{ANNUAL_COPY.reproTitle}</h3>
        <p className="annual-sim__caption">{ANNUAL_COPY.reproCaption}</p>
        <dl className="annual-sim__repro">
          <dt>seed</dt>
          <dd>{reproducibilityLine(mc)}</dd>
          <dt>{ANNUAL_COPY.snapshotLabel}</dt>
          <dd>
            {result.snapshot.snapshot_id}
            <span className="annual-sim__hint">
              {ANNUAL_COPY.snapshotHint} ({result.snapshot.voyage_count}건)
            </span>
          </dd>
          <dt>{ANNUAL_COPY.runIdLabel}</dt>
          <dd>{result.calculation_run_id}</dd>
        </dl>
      </section>

      {result.warnings.length > 0 ? (
        <ul className="annual-sim__warnings">
          {result.warnings.map((code) => (
            <li key={code}>{warningMessage(code)}</li>
          ))}
        </ul>
      ) : null}
    </>
  )
}

/** 스택 바의 대체 텍스트 — 색만으로 정보를 주지 않는다(`DESIGN_SYSTEM §14`). */
function stackAria(segments: Array<{ rating: string; label: string }>): string {
  return segments.map((seg) => `${seg.rating} ${seg.label}`).join(', ')
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="annual-sim__metric">
      <span className="annual-sim__label">{label}</span>
      <span className="annual-sim__value">{value}</span>
      {hint ? <span className="annual-sim__hint">{hint}</span> : null}
    </div>
  )
}
