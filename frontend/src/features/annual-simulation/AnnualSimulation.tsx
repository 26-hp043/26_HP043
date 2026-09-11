import { useCallback, useEffect, useMemo, useState } from 'react'
import './AnnualSimulation.css'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { useShellContext } from '../../layout/shellContext'
import { useYearOptions } from '../parameters/yearCatalog'
import { GradeBadge } from '../../components/GradeBadge'
import { gradePatternUrl } from '../../components/gradePattern'
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
import type { AnnualSimulationProvider, AnnualSimulationResult } from './types'
import { ErrorState } from '../../components/ErrorState'

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
 * 기준연도 — **서버가 준다** (`#558`).
 *
 * 종전에는 `const DEFAULT_YEAR = 2026`이 박혀 있어 **사용자가 2026년 외의 해를 볼 수
 * 없었다.** 규제연도는 2023~2030 여덟 개가 적재돼 있다.
 *
 * `#236`이 연 세 축 중 이것이 마지막이다 — 선박은 `#484`(상단바 전역 선택), 연도(CII
 * 예측)는 `#534`, 연료는 `#568`이 옮겼다. 같은 `yearCatalog`를 쓰므로 두 화면의 선택지가
 * 갈리지 않는다.
 */

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

  // 연도 선택지도 CII 예측과 **같은 경계** 뒤에 둔다 (`#534` · `#558`). 기준이 갈리면
  // 두 화면이 서로 다른 해를 보여 주고, 그 차이는 값이 아니라 목록에서 나타나 늦게 발견된다.
  const [year, setYear] = useState('')

  /*
   * 연도 선택지는 **공용 훅**이 받는다 (`#632`가 만든 것 · `#824` ⑴로 이관).
   *
   * ## 왜 자체 구현을 걷어냈나
   *
   * 종전에는 같은 로직이 이 파일에 복사돼 있었고, **선박이 아직 정해지지 않은 첫
   * 진입에서 영구 로딩**이 됐다.
   *
   * ```
   * const [yearsLoading, setYearsLoading] = useState(true)   // 초기값 true
   * useEffect(() => {
   *   if (shell.vesselId === null) return                    // ← false로 되돌리지 않고 나간다
   *   …
   *   .finally(() => setYearsLoading(false))                 // ← 유일한 false 경로
   * })
   * ```
   *
   * `EMPTY_CONTEXT`의 `vesselId`가 `null`이고 이 화면은 선박을 자동 선택하지
   * 않으므로(`AnnualGradePage`) **그것이 기본 진입 상태**다 — 「규제연도 목록을
   * 불러오는 중…」에서 끝내 바뀌지 않고 `<select>`가 렌더되지 않는다. 요청은 아예
   * 나가지도 않는다.
   *
   * **공용 훅은 이 자리를 이미 막고 있다** — 빈 `vesselId`면 목록을 비우고
   * `loading`을 내린다. `#632`가 훅을 만들며 항로 비교·보고서만 이관했고 이 화면과
   * `VoyageCiiForm`이 남아 있었다.
   */
  const { years, loading: yearsLoading, failed: yearsFailed } = useYearOptions(
    shell.vesselId ?? '',
  )

  /*
   * 목록이 오면 기본 선택을 맞춘다 (`ScenarioComparison`과 같은 형태).
   *
   * `VoyageCiiForm`과 **같은 함수**를 쓴다. 종전에는 이 화면만 「가장 최근 해」를
   * 골랐는데, 규제연도가 2023~2030이라 기본값이 **2030**이었다 — 아직 실적이 없는
   * 해다. 「올해 남은 항차로 목표 등급을 맞출 수 있는가」를 보는 화면이므로
   * (`PRD §12`) 올해가 맞다.
   *
   * 올해를 **여기서 읽어** 순수 함수에 넘긴다 — 함수 안에서 `new Date()`를 부르면
   * 검사가 해를 고정할 수 없다.
   */
  useEffect(() => {
    if (years.length === 0) return
    const thisYear = new Date().getFullYear()
    setYear((prev) => pickDefaultYear(years, thisYear, prev))
  }, [years])

  const run = useCallback(async () => {
    if (shell.vesselId === null) {
      setState({ status: 'error', message: '상단에서 선박을 먼저 선택해 주세요.' })
      return
    }
    if (year === '') {
      // 목록을 못 받았거나 아직 오는 중이다. 값을 지어내 계산하지 않는다 — 종전
      // 고정값(2026)이 정확히 그런 형태였고, 사용자는 다른 해를 볼 수 없었다.
      setState({
        status: 'error',
        message: yearsFailed
          ? '규제연도 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
          : '규제연도 목록을 불러오는 중입니다.',
      })
      return
    }
    setState({ status: 'running' })
    try {
      const result = await provider.run({
        vessel_id: shell.vesselId,
        regulation_year: Number(year),
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
  }, [provider, shell.vesselId, year, yearsFailed, target, runs, seed, onDisclaimer])

  return (
    <section className="annual-sim">
      {/*
        화면 제목은 페이지가 `PageHeader`로 그린다(`components/PageHeader.tsx`).
        여기서 다시 그리면 한 화면에 `h1`과 `h2` 두 개의 제목이 겹치고, 종전에는
        **`h2`만 있어 이 화면만 제목이 한 단 작았다.**

        머리 영역이 남는 이유는 샘플 데이터 배지 하나뿐이라 **배지가 있을 때만**
        렌더한다 — 빈 `header`가 남으면 위쪽에 설명 없는 여백이 생긴다.
      */}
      {state.status === 'success' && state.result.is_sample_data ? (
        <header className="annual-sim__head">
          <span className="annual-sim__badge">{ANNUAL_COPY.sampleBadge}</span>
        </header>
      ) : null}

      <form
        className="annual-sim__form"
        onSubmit={(event) => {
          event.preventDefault()
          void run()
        }}
      >
        <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.runTitle}</h2>

        <label className="annual-sim__field">
          <span className="annual-sim__label">기준연도</span>
          {yearsLoading ? (
            <span className="annual-sim__hint">규제연도 목록을 불러오는 중…</span>
          ) : yearsFailed ? (
            <span className="annual-sim__hint">규제연도 목록을 불러오지 못했습니다</span>
          ) : (
            <select value={year} onChange={(event) => setYear(event.target.value)}>
              {years.map((y) => (
                <option key={y} value={String(y)}>
                  {y}
                </option>
              ))}
            </select>
          )}
          <span className="annual-sim__hint">
            규제연도에 따라 required CII와 등급 경계가 달라집니다.
          </span>
        </label>

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
        {/*
          오류는 `role="alert"`로 낸다 — `aria-atomic`을 암시하므로 제목과 본문이
          통째로 읽힌다. `aria-live`만 두면 바뀐 노드만 읽혀 둘이 따로 논다.
          다른 화면 8곳이 모두 이 형태다 (#613).
        */}
        {state.status === 'error' ? (
          <ErrorState level="region" title={ANNUAL_COPY.errorTitle} message={state.message} />
        ) : null}

        {/*
          재현 상태(`ReproduceState`)가 **직전 실행의 「재현 확인」을 새 결과 옆에 남기지
          않아야** 한다 — 새 결과는 아직 아무도 재현하지 않았다.

          지금은 실행 중(`running`)에 결과가 내려가 어차피 새로 그려진다. `key`는 그
          경로에 기대지 않으려고 둔다 — 실행 중에도 직전 결과를 남기도록 바뀌는 날
          재현 확인이 새 결과에 붙는다. 동작은 `AnnualSimulation.test.tsx`가 잠근다.
        */}
        {state.status === 'success' ? (
          <Result
            key={state.result.simulation_id}
            result={state.result}
            provider={provider}
          />
        ) : null}
      </div>
    </section>
  )
}

/**
 * 「이 seed로 다시 실행」의 상태 (`PRD §12.4.3` · #776).
 *
 * 성공은 **값을 갈아 끼우지 않는다** — 서버가 원본과 대조해 같을 때만 200을 내므로
 * (`API_SPEC §6.4`, 다르면 500) 새로 그릴 값이 없다. 확인했다는 사실만 알린다.
 */
type ReproduceState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'success' }
  | { status: 'error'; message: string }

function Result({
  result,
  provider,
}: {
  result: AnnualSimulationResult
  provider: AnnualSimulationProvider
}) {
  const { deterministic: det, monte_carlo: mc } = result
  const [reproduce, setReproduce] = useState<ReproduceState>({ status: 'idle' })

  const runReproduce = useCallback(async () => {
    setReproduce({ status: 'running' })
    try {
      await provider.reproduce(result.simulation_id)
      setReproduce({ status: 'success' })
    } catch (error: unknown) {
      // 서버 문구를 그대로 낸다 — 409(파라미터 변경 → 새로 실행)와 500(무결성 실패
      // → 관리자 문의)은 **사용자가 할 일이 다르고** 그 안내가 문구에 들어 있다(#837).
      setReproduce({
        status: 'error',
        message: error instanceof Error ? error.message : ANNUAL_COPY.reproduceErrorTitle,
      })
    }
  }, [provider, result.simulation_id])
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
        <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.deterministicTitle}</h2>
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
              size="lg"
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
        <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.probabilityTitle}</h2>
        <p className="annual-sim__caption">{ANNUAL_COPY.probabilityCaption}</p>

        {/*
          `DESIGN_SYSTEM §2.4.4`가 「등급 확률 스택 바」를 패턴 적용 대상으로 명시하고,
          `§14`가 **등급 문자가 놓이지 않는 자리에서는 패턴을 필수**로 둔다. 이 바에는
          문자가 없고 범례에만 있으므로 패턴이 있어야 한다 — 3색 체계는 적록색맹에서
          초록·주황·빨강이 모두 황갈색으로 수렴해 5색보다 오히려 취약하다(§2.4.4).

          채움색 위에 SVG 패턴을 겹치는 방식은 `GradeScaleBar`와 같다. 무늬는 셸이
          한 번 그리는 `GradePatternDefs`를 참조하므로 여기서 다시 정의하지 않는다
          (§15.1 — 자산이 두 벌이 되면 서로 다른 무늬를 그리게 된다).
        */}
        {/*
          `role`을 `img`가 아니라 `group`으로 둔다. `img`는 하위 트리를 통째로
          presentational로 만들어 **구간마다 붙인 이름이 보조기술에 닿지 않는다** —
          8% 미만 구간의 값을 개별로 읽히게 하려면 그룹이어야 한다.
        */}
        <div
          className="annual-sim__stack"
          role="group"
          aria-label={`${ANNUAL_COPY.probabilityTitle} — ${stackAria(segments)}`}
        >
          {segments.map((seg) => {
            const pattern = gradePatternUrl(seg.rating)
            const inline = seg.inline
            const text = `${seg.rating} ${seg.label}`

            return (
              <span
                key={seg.rating}
                className={`annual-sim__seg annual-sim__seg--${seg.rating.toLowerCase()}`}
                style={{ width: `${seg.percent}%` }}
                role="img"
                aria-label={text}
                /*
                  8% 미만은 구간 안에 글자가 들어가지 않으므로 툴팁으로 낸다(§10.2).
                  `title`은 포인터 전용이라 **그것만으로는 키보드 사용자가 못 읽는다** —
                  `tabIndex`로 초점을 받게 해 위 `aria-label`이 읽히는 경로를 연다.
                  값 자체는 아래 범례에도 그대로 있어 눈으로도 확인된다.
                */
                {...(inline ? {} : { title: text, tabIndex: 0 })}
              >
                {/*
                  뷰박스를 두지 않는다 — 사용자 단위가 곧 CSS 픽셀이라 4px 타일이
                  4px로 그려진다. 뷰박스를 주고 폭에 맞춰 늘이면 무늬가 찌그러진다.
                */}
                {pattern ? (
                  <svg className="annual-sim__seg-pattern" aria-hidden="true">
                    <rect width="100%" height="100%" fill={pattern} />
                  </svg>
                ) : null}
                {inline ? (
                  <span className="annual-sim__seg-label" aria-hidden="true">
                    {text}
                  </span>
                ) : null}
              </span>
            )
          })}
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
          <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.sensitivityTitle}</h2>
          {/*
           * `interaction_note`는 `ORACLE-M-3`이 응답 포함을 지정한 항목이다. 빼면
           * 사용자가 두 변수를 함께 조정했을 때의 결과를 이 표에서 읽으려 한다.
           */}
          <p className="annual-sim__caption">
            {result.sensitivity_analysis.interaction_note}
          </p>
          {/*
            거리 행은 기준과 거의 같은 값이 나온다 — 모델의 성질이지 결함이 아니다(#756).
            그 행이 표에 있을 때만 이유를 말한다. 없는데 말하면 무엇을 설명하는지 모른다.
          */}
          {rows.some((row) => row.key.startsWith('distance_')) ? (
            <p className="annual-sim__caption">{ANNUAL_COPY.distanceNote}</p>
          ) : null}
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
                {rows.map(({ key, label, entry, probabilityChange }) => (
                  <tr key={key}>
                    <th scope="row">
                      {label}
                      {entry.alternative_fuel ? ` (${entry.alternative_fuel})` : ''}
                    </th>
                    <td>{formatDecimalString(entry.projected_cii, DISPLAY_DIGITS.cii)}</td>
                    <td>{entry.rating_change}</td>
                    {/*
                      `#822` — 종전에는 서버 값(`+0.12`)을 **그대로** 그렸다. 이 표
                      위쪽 지표가 `30.0%`라 사용자는 0.12%p로 읽지만 실제는 12%p다.
                      백분율 환산은 `sensitivityRows`가 한다 — 컴포넌트 안 삼항
                      연산자는 검사가 닿지 않는 자리였다.
                    */}
                    <td>{probabilityChange}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* ── 재현성 (TECH_SPEC §5.2 · §11) ──────────────────────────── */}
      <section className="annual-sim__block">
        <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.reproTitle}</h2>
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
        {/*
          `PRD §12.4.3` 「결과 재현 버튼」(#776). `#556`은 이 경로를 「검증 수단이지
          사용자 기능이 아니다」로 판정했으나 `PRD §12.4.3`이 버튼을 요구해 뒤집혔다.

          seed를 입력칸에 옮겨 적는 우회로 대신 두는 것이다 — 그 우회는 **폼의 다른 칸이
          바뀌었으면 다른 조건으로** 돌고, 결과가 달라도 그것이 재현 실패인지 알 수 없다.
        */}
        <div className="annual-sim__reproduce">
          <button
            type="button"
            onClick={() => void runReproduce()}
            disabled={reproduce.status === 'running'}
          >
            {reproduce.status === 'running'
              ? ANNUAL_COPY.reproducing
              : ANNUAL_COPY.reproduceButton}
          </button>
          {reproduce.status === 'success' ? (
            <p className="annual-sim__hint" role="status">
              {ANNUAL_COPY.reproduceSuccess}
            </p>
          ) : null}
        </div>
        {reproduce.status === 'error' ? (
          <ErrorState
            level="region"
            title={ANNUAL_COPY.reproduceErrorTitle}
            message={reproduce.message}
          />
        ) : null}
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
