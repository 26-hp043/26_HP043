import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import './AnnualSimulation.css'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { useShellContext } from '../../layout/shellContext'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { useYearOptions } from '../parameters/yearCatalog'
import { GradeBadge } from '../../components/GradeBadge'
import { gradePatternUrl } from '../../components/gradePattern'
import { ANNUAL_COPY } from './copy'
import { SCREEN_BY_ID } from '../../screens'

/**
 * 잔여 계획 항차가 0건임을 알리는 경고 코드 (`calc/annual_simulation.py`).
 *
 * 문구는 `resultRules.WARNING_MESSAGE`가 갖는다 — 여기서는 **있는지만** 본다.
 */
const NO_REMAINING_VOYAGES = 'NO_REMAINING_VOYAGES'
import {
  RUNS_MAX,
  RUNS_MIN,
  probabilityOfDorE,
  reproducibilityLine,
  riskFlag,
  sensitivityRows,
  stackSegments,
  toPercent,
  validateRuns,
  RUNS_DEFAULT,
  TARGET_DEFAULT,
  countAdvancedChanges,
  reductionCutText,
  resultConditionsText,
  estimateNoticeText,
  targetVesselText,
} from './annualRules'
import { createAnnualSimulationProvider } from './providerSelection'
import type { AnnualSimulationProvider, AnnualSimulationResult } from './types'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'
import { SnapshotVoyages } from './SnapshotVoyages'
import { isOffice, useAuthUser } from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'
import { Icon } from '../../components/Icon'

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
  /*
   * 실행 **전**에 막힌 상태 (#1096 ⑸). 선박 미선택·연도 목록 미도착·목록 실패는
   * 실행한 적이 없으니 `error`가 아니다 — 종전에는 `error`로 넣어 「시뮬레이션에
   * 실패했습니다」 제목 아래 「선박을 먼저 선택해 주세요」가 나왔다.
   */
  | { status: 'blocked'; message: string }
  | { status: 'running' }
  /*
   * `conditions`는 **실행 시점의 값**이다 (#1553). 목표 등급은 실행 뒤에 바꿔도 결과를
   * 지우지 않으므로, 결과 머리에 지금 고른 값을 적으면 결과와 어긋난다.
   */
  | { status: 'success'; result: AnnualSimulationResult; conditions: RunConditions }
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

/** 결과가 어떤 조건으로 나왔는가 — 결과 머리 한 줄에 적는다 (#1553). */
interface RunConditions {
  vesselName: string
  year: string
  target: string
}

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
  // 실행은 사무직 전용이다 (`API_SPEC §1.2` · #672). 현장직은 폼을 읽되 실행 버튼이 잠긴다.
  const office = isOffice(useAuthUser())
  const [state, setState] = useState<RunState>({ status: 'idle' })
  /*
   * 실행 **세대 번호** — 늦은 응답을 버린다 (`#1094` · `#874` 선례).
   *
   * 실행 중에 상단바에서 선박을 바꾸면, 앞 선박의 요청은 그대로 날아가고 있다.
   * 그 응답이 돌아오면 `setState({ status: 'success', … })`가 **새 선박 화면에**
   * 성공 결과를 붙였다 — 결과 카드에 선박명이 없어 사용자가 알아챌 수 없다.
   * Monte Carlo 10,000회는 초 단위라 전환할 시간이 충분하다.
   */
  const generationRef = useRef(0)
  const [target, setTarget] = useState<(typeof TARGET_RATINGS)[number]>(TARGET_DEFAULT)
  const [runs, setRuns] = useState(RUNS_DEFAULT)
  /** 반복 횟수 위반 문구. 실행을 누를 때 판정하고, 값을 고치면 지운다 (#1096 ⑴). */
  const [runsError, setRunsError] = useState<string | null>(null)
  const [seed, setSeed] = useState('')
  // `PRD §12.2.1` 실적 보정계수 — 기본은 끔(`#363`). 켜지 않은 실행은 종전과 같다.
  const [applyFeedback, setApplyFeedback] = useState(false)
  /*
   * 대체 연료 지렛대 (#756 ⑴) — 빈 문자열은 「고르지 않음」이다. 서버에 빈 값을
   * 보내지 않는다(미지정 요청 모양이 종전과 같게 남는다 — `apply_feedback_factor`와
   * 같은 규약).
   */
  const [alternativeFuel, setAlternativeFuel] = useState('')
  /*
   * 고급 설정 펼침 (#1418). 반복 횟수 오류가 나면 **펼친다** — 접힌 칸의 오류는 보이지
   * 않는다. 그래서 `<details>`의 열림을 상태로 쥔다.
   */
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const advancedChanged = countAdvancedChanges({ runs, seed, applyFeedback, alternativeFuel })
  const fuelOptions = useFuelOptions()

  // 연도 선택지도 CII 예측과 **같은 경계** 뒤에 둔다 (`#534` · `#558`). 기준이 갈리면
  // 두 화면이 서로 다른 해를 보여 주고, 그 차이는 값이 아니라 목록에서 나타나 늦게 발견된다.
  /*
   * 첫 연도는 주소의 `?year=`에서 받는다 (#891 · `PRD §10.5` 「해당 선박·**연도**로 이동」).
   * 기능①의 「연간 시뮬레이터에서 보기」가 싣는다.
   *
   * ⚠️ **주소 값은 목록과 대조되기 전에는 `year`가 되지 않는다** (#1096 ⑷). 종전에는
   * 주소 값을 곧바로 상태에 넣어, 목록을 못 받으면 `?year=2099`가 검증 없이 전송되고
   * `?year=abc`는 `Number('abc')` = `NaN` → JSON `null` → 422가 됐다 — 「값을 지어내
   * 계산하지 않는다」는 아래 `run`의 주석과 반대였다. 주소 값은 **후보**로만 두고,
   * 목록이 오면 `pickDefaultYear`가 목록 안의 값일 때만 고른다. 목록이 없으면 `year`는
   * 빈 채로 남고 `run`이 실행을 막는다.
   */
  const [searchParams] = useSearchParams()
  const requestedYear = searchParams.get('year') ?? ''
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
    // 아직 고른 해가 없으면 주소의 후보를 넘긴다 — 목록에 있을 때만 채택된다.
    setYear((prev) => pickDefaultYear(years, thisYear, prev || requestedYear))
  }, [years, requestedYear])

  /*
   * ⚠️ **대상이 바뀌면 앞의 결과를 지운다** (`#1094`).
   *
   * 종전에는 상단바에서 선박을 바꿔도 `state`가 그대로여서 **앞 선박의 P50·달성
   * 확률·필요 감축량이 새 선박을 고른 상태로 계속 보였다.** 결과 카드에 선박명이
   * 없으므로 화면만 보고는 어느 배의 숫자인지 알 수 없다 — **「아직 안 돌렸다」와
   * 「앞 배 결과」가 같은 모양**이었고, 사용자는 둘을 구분할 방법이 없었다.
   *
   * 연도도 같다 — 2026년 결과를 2027년을 고른 상태로 두면 같은 문제다.
   *
   * **세대를 함께 올려** 이미 날아간 요청의 응답을 버린다. `Result`의 재현 상태는
   * 그 컴포넌트 안에 있으므로 `idle`로 돌아가면 언마운트되며 함께 사라진다.
   *
   * `target`·`runs`·`seed`·`applyFeedback`은 **지우지 않는다.** 사용자가 정한 조건이고,
   * 배를 바꿨다고 조건까지 되돌리면 같은 조건으로 두 배를 비교할 수 없다. 그래서
   * 페이지에 `key`를 주어 통째로 다시 만드는 방법을 쓰지 않았다.
   *
   * ⚠️ **`onDisclaimer`를 여기서 부르지 않는다.** 그것을 의존성에 넣으면 호출자가
   * 함수를 `useCallback`으로 감싸지 않는 순간 **매 렌더마다 결과가 지워진다** —
   * 화면이 「실행했는데 아무 일도 안 일어난다」가 된다. 지금 호출자(`AnnualGradePage`)는
   * 안정적이지만 그 성질에 기대는 설계를 두지 않는다. 배너는 `undefined`일 때
   * 기본 문구를 쓰므로(`DisclaimerBanner`) 여기서 비울 것도 없다.
   */
  useEffect(() => {
    generationRef.current += 1
    setState({ status: 'idle' })
  }, [shell.vesselId, year])

  const targetVessel = targetVesselText(shell.vesselId, shell.vessels, shell.vesselsState, {
    none: ANNUAL_COPY.targetVesselNone,
    loading: ANNUAL_COPY.targetVesselLoading,
    unknown: ANNUAL_COPY.targetVesselUnknown,
  })

  const run = useCallback(async () => {
    // 실행 전 차단은 `blocked`다 — 실패가 아니라 안내 (#1096 ⑸).
    if (shell.vesselId === null) {
      setState({ status: 'blocked', message: ANNUAL_COPY.needVessel })
      return
    }
    if (year === '') {
      // 목록을 못 받았거나 아직 오는 중이다. 값을 지어내 계산하지 않는다 — 종전
      // 고정값(2026)이 정확히 그런 형태였고, 사용자는 다른 해를 볼 수 없었다.
      // 주소의 `?year=`도 여기서 막힌다 — 목록과 대조되지 않은 값은 `year`가 아니다.
      setState({
        status: 'blocked',
        message: yearsFailed ? ANNUAL_COPY.yearsUnavailable : ANNUAL_COPY.yearsPending,
      })
      return
    }
    // 반복 횟수는 서버와 같은 규칙으로 화면에서 먼저 막는다 (#1096 ⑴).
    const runsProblem = validateRuns(runs)
    if (runsProblem !== null) {
      setRunsError(runsProblem)
      setAdvancedOpen(true)
      return
    }
    setState({ status: 'running' })
    const ticket = generationRef.current
    // 누른 순간의 조건을 잡아 둔다 — 응답을 기다리는 동안 목표를 바꿔도 결과 줄은 이것이다.
    const conditions: RunConditions = { vesselName: targetVessel, year, target }
    try {
      const result = await provider.run({
        vessel_id: shell.vesselId,
        regulation_year: Number(year),
        target_rating: target,
        simulation_runs: Number(runs),
        // 빈 문자열을 보내지 않는다 — 서버가 「지정했는데 비었다」로 볼 수 있다.
        ...(seed.trim() ? { random_seed: seed.trim() } : {}),
        // 끈 상태는 보내지 않는다 — 서버 기본이 끔이고, 요청 모양이 종전과 같게 남는다.
        ...(applyFeedback ? { apply_feedback_factor: true } : {}),
        // 대체 연료 지렛대 (#756 ⑴) — 골랐을 때만 보낸다.
        ...(alternativeFuel ? { alternative_fuel: alternativeFuel } : {}),
      })
      // 기다리는 동안 대상이 바뀌었으면 **버린다** — 새 선박 화면에 앞 배의 성공
      // 결과를 붙이지 않는다 (`#1094`).
      if (ticket !== generationRef.current) return
      setState({ status: 'success', result, conditions })
      onDisclaimer?.(undefined)
    } catch (error: unknown) {
      // 실패도 같다. 앞 배의 오류 문구를 새 배 화면에 띄우면 사용자는 새 배에
      // 문제가 있다고 읽는다.
      if (ticket !== generationRef.current) return
      setState({
        status: 'error',
        message: error instanceof Error ? error.message : ANNUAL_COPY.errorFallback,
      })
    }
  }, [provider, shell.vesselId, targetVessel, year, yearsFailed, target, runs, seed, applyFeedback, alternativeFuel, onDisclaimer])

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

      {/*
        `noValidate` — 브라우저 기본 검증(툴팁)을 끄고 화면이 직접 검증한다 (#1096 ⑴).
        종전에는 `step={1000}`이 2,500을 툴팁으로만 막아 **화면 오류 자리는 비어 있고
        서버는 받는 값**이었다. 지금은 `validateRuns`가 판정하고 그 결과가 입력 아래 선다.
      */}
      <form
        className="annual-sim__form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void run()
        }}
      >
        <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.runTitle}</h2>
        {/* `UIFLOW 2-10` 진입 조건 — 한 척에서 선대 단위 조치로 넘어간다 (#513). */}
        <Link className="annual-sim__fleet-link" to={SCREEN_BY_ID.FLEET_REDUCTION.path}>
          {ANNUAL_COPY.fleetLink}
        </Link>

        {/*
          대상 선박 (#1553) — 입력이 아니라 **읽기 전용**이다. 선박은 상단바 전역 선택이
          소유하고(`shellContext`), 여기서 따로 고르게 하면 두 곳이 갈린다(`#535`).
        */}
        <div className="annual-sim__target">
          <span className="annual-sim__target-label">{ANNUAL_COPY.targetVesselLabel}</span>
          <strong className="annual-sim__target-name">{targetVessel}</strong>
          <span className="annual-sim__target-hint">{ANNUAL_COPY.targetVesselHint}</span>
        </div>

        {/* 컨트롤이 없는 가지가 있다(로딩·실패) — `control`은 `<select>`를 실제로
            그리는 가지에서만 펼친다 (`#936`). */}
        <Field
          id="annual-sim-year"
          label="기준연도"
          hint="규제연도에 따라 required CII와 등급 경계가 달라집니다."
        >
          {(control) =>
            yearsLoading ? (
              <span className="annual-sim__hint">규제연도 목록을 불러오는 중…</span>
            ) : yearsFailed ? (
              <span className="annual-sim__hint">규제연도 목록을 불러오지 못했습니다</span>
            ) : (
              <select
                {...control}
                className="annual-sim__control"
                value={year}
                onChange={(event) => setYear(event.target.value)}
              >
                {years.map((y) => (
                  <option key={y} value={String(y)}>
                    {y}
                  </option>
                ))}
              </select>
            )
          }
        </Field>

        <Field
          id="annual-sim-target"
          label={ANNUAL_COPY.targetRatingLabel}
          hint={ANNUAL_COPY.targetRatingHint}
        >
          {(control) => (
            <select
              {...control}
              className="annual-sim__control"
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
          )}
        </Field>

        {/*
          기본값이 있는 네 칸을 접는다 (#1418). 첫 화면이 입력 폼이 아니라 **기준연도 · 목표 등급 ·
          실행**이 되게. 입력칸을 숨기지 말라는 조항은 `PRD §12`·`UIFLOW 2-3`에 없다.
        */}
        <details
          className="annual-sim__advanced"
          open={advancedOpen}
          onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
        >
          <summary>
            {ANNUAL_COPY.advancedTitle}
            <span className="annual-sim__hint">
              {' · '}
              {advancedChanged === 0
                ? ANNUAL_COPY.advancedDefault
                : `${advancedChanged}${ANNUAL_COPY.advancedChangedSuffix}`}
            </span>
          </summary>
          <Field
            id="annual-sim-runs"
            label={ANNUAL_COPY.runsLabel}
            hint={ANNUAL_COPY.runsHint}
            error={runsError ?? undefined}
          >
            {/* `step`을 두지 않는다 — 서버 규칙(정수 · 1,000 이상)에 없는 제약이다. */}
            {(control) => (
              <input
                {...control}
                className="annual-sim__control"
                type="number"
                min={RUNS_MIN}
                max={RUNS_MAX}
                value={runs}
                onChange={(event) => {
                  setRuns(event.target.value)
                  setRunsError(null)
                }}
              />
            )}
          </Field>

          {/*
            seed 안내는 칸 안에 둔다 (#1418 화면 확인). 빈 칸일 때만 보이면 되는 말이고,
            고급 설정을 열었을 때 줄 수를 늘리지 않는다. `aria-describedby`로도 같은 문장을
            이어 둔다 — 플레이스홀더는 입력을 시작하면 사라지고 낭독이 건너뛰기도 한다.
          */}
          <Field id="annual-sim-seed" label={ANNUAL_COPY.seedLabel} hint={ANNUAL_COPY.seedHint} hintHidden>
            {(control) => (
              <input
                {...control}
                className="annual-sim__control"
                type="text"
                inputMode="numeric"
                placeholder={ANNUAL_COPY.seedHint}
                value={seed}
                onChange={(event) => setSeed(event.target.value)}
              />
            )}
          </Field>

          <div className="annual-sim__field annual-sim__field--check">
            <label className="annual-sim__check" htmlFor="annual-sim-feedback">
              <input
                id="annual-sim-feedback"
                type="checkbox"
                checked={applyFeedback}
                aria-describedby="annual-sim-feedback-hint"
                onChange={(event) => setApplyFeedback(event.target.checked)}
              />
              {ANNUAL_COPY.feedbackToggle}
            </label>
            <span id="annual-sim-feedback-hint" className="annual-sim__hint">
              {ANNUAL_COPY.feedbackToggleHint}
            </span>
          </div>

          {/*
            대체 연료 지렛대 (#756 ⑴ · 결정 「나」 — 질량 유지). 목록은 파라미터
            카탈로그(`useFuelOptions`)에서 온다 — 고정표를 두면 연료가 추가·비활성화될 때
            화면만 따라간다(#558과 같은 이유). 불러오기에 실패하면 선택지를 아예
            둘지 않는다: 지금 고를 수 없는 연료를 보여 주면 고르고 나서 실패하게 된다.
          */}
          {!fuelOptions.failed && fuelOptions.fuels.length > 0 ? (
            <div className="annual-sim__field">
              <label className="annual-sim__label" htmlFor="annual-sim-alt-fuel">
                {ANNUAL_COPY.alternativeFuelLabel}
              </label>
              {/* 다른 칸과 같은 컨트롤 규격을 준다 (#1418) — 이 셀렉트만 브라우저 기본 모양이었다. */}
              <select
                id="annual-sim-alt-fuel"
                className="annual-sim__control"
                value={alternativeFuel}
                aria-describedby="annual-sim-alt-fuel-hint"
                onChange={(event) => setAlternativeFuel(event.target.value)}
              >
                <option value="">{ANNUAL_COPY.alternativeFuelNone}</option>
                {fuelOptions.fuels.map((fuel) => (
                  <option key={fuel.code} value={fuel.code}>
                    {fuelTypeOptionText(fuel.code)}
                  </option>
                ))}
              </select>
              <span id="annual-sim-alt-fuel-hint" className="annual-sim__hint">
                {ANNUAL_COPY.alternativeFuelHint}
              </span>
            </div>
          ) : null}
        </details>

        <button
          type="submit"
          disabled={state.status === 'running' || !office}
          aria-describedby={office ? undefined : 'annual-sim-office-only'}
        >
          {state.status === 'running' ? ANNUAL_COPY.submitting : ANNUAL_COPY.submit}
        </button>
        {office ? null : (
          <span id="annual-sim-office-only" className="annual-sim__hint">
            {OFFICE_ONLY_ACTION_HINT}
          </span>
        )}
      </form>

      {/*
        결과 전체를 한 겹으로 묶는다. `Result`가 Fragment를 반환하므로 묶지 않으면
        그 안의 블록들이 `.annual-sim`의 직계 자식이 되고, 12컬럼 자동 배치가
        첫 블록만 폼 옆에 올린 뒤 나머지를 아래 줄로 흘려보낸다.
      */}
      <div className="annual-sim__results">
        {state.status === 'idle' ? (
          <p className="annual-sim__placeholder">
            {/* 선박이 없으면 「조건을 고르라」보다 먼저 할 일을 말한다 (#1096 ⑸). */}
            {shell.vesselId === null ? ANNUAL_COPY.needVessel : ANNUAL_COPY.empty}
          </p>
        ) : null}
        {/*
          실행 전 차단은 안내다 — `role="status"`로 읽히고 「실패했습니다」 제목이 없다.
          `alert`로 내면 실행한 적 없는 일이 실패한 것으로 읽힌다 (#1096 ⑸).
        */}
        {state.status === 'blocked' ? (
          <p className="annual-sim__placeholder" role="status">
            {state.message}
          </p>
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
          <ErrorState level="region" action={ANNUAL_COPY.errorAction} message={state.message} />
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
            conditions={state.conditions}
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
  /**
   * 재현 성공 — **응답의 경고를 함께 든다** (`#1095` ⑶).
   *
   * 종전에는 응답을 통째로 버리고 `{ status: 'success' }`만 세웠다. 서버는 원본과
   * 다른 `model_version`에서 돌아 결과가 같았을 때 `MODEL_VERSION_DIFFERS`를 붙이는데
   * (`services/annual_simulation.py` · `#833`), 화면이 그것을 읽지 않아 **「같은
   * 환경에서 같은 결과」와 「다른 환경에서 같은 결과」가 한 문장으로 뭉개졌다.**
   * `#833`이 만든 구분이 화면에서 사라진 것이다.
   */
  | { status: 'success'; warnings: readonly string[] }
  | { status: 'error'; message: string }

function Result({
  result,
  conditions,
  provider,
}: {
  result: AnnualSimulationResult
  conditions: RunConditions
  provider: AnnualSimulationProvider
}) {
  const { deterministic: det, monte_carlo: mc, reduction_plan: cut, feedback } = result
  const [reproduce, setReproduce] = useState<ReproduceState>({ status: 'idle' })

  const runReproduce = useCallback(async () => {
    setReproduce({ status: 'running' })
    try {
      const reproduced = await provider.reproduce(result.simulation_id)
      setReproduce({ status: 'success', warnings: reproduced.warnings })
    } catch (error: unknown) {
      // 서버 문구를 그대로 낸다 — 409(파라미터 변경 → 새로 실행)와 500(무결성 실패
      // → 관리자 문의)은 **사용자가 할 일이 다르고** 그 안내가 문구에 들어 있다(#837).
      setReproduce({
        status: 'error',
        message: error instanceof Error ? error.message : ANNUAL_COPY.reproduceErrorFallback,
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
      {/*
        이 결과의 조건 (#1553) — 결과만 캡처해도 어느 배 · 어느 해 · 어느 목표인지 읽히게.
        결과 블록들의 맨 위, 추정 고지보다 먼저다.
      */}
      <p className="annual-sim__conditions">
        <span className="annual-sim__conditions-label">{ANNUAL_COPY.resultConditionsLabel}</span>{' '}
        <strong>{resultConditionsText(conditions)}</strong>
      </p>
      {result.is_sample_data ? (
        <p className="annual-sim__notice">{ANNUAL_COPY.sampleNotice}</p>
      ) : (
        <p className="annual-sim__notice">{estimateNoticeText(result.as_of)}</p>
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

      {/*
        ── 실적 보정계수 (PRD §12.2.1 · #363) ─────────────────────────

        세 상태를 가른다 — ⑴ 곱했다 ⑵ 값은 있으나 곱하지 않았다 ⑶ 표본이 모자라 값이
        없다. ⚠️ ⑶을 1.0이나 빈칸으로 그리면 「계획대로 쓰고 있다」로 읽힌다.

        `#363` 이전 실행에는 블록이 없다 — 그때는 카드를 그리지 않는다.
      */}
      {feedback && (
        <section className="annual-sim__block">
          <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.feedbackTitle}</h2>
          <p className="annual-sim__caption">{ANNUAL_COPY.feedbackCaption}</p>
          <div className="annual-sim__metrics">
            <Metric
              label={ANNUAL_COPY.feedbackFactorLabel}
              value={
                feedback.factor === null
                  ? ANNUAL_COPY.feedbackUnavailableValue
                  : `× ${formatDecimalString(feedback.factor, 4)}`
              }
            />
            <Metric
              label={ANNUAL_COPY.feedbackSampleLabel}
              value={`${feedback.sample_size}건`}
              hint={`${ANNUAL_COPY.feedbackMinSampleHint} ${feedback.min_sample}건`}
            />
          </div>
          {feedback.factor === null ? (
            <p className="annual-sim__caption">{ANNUAL_COPY.feedbackUnavailable}</p>
          ) : feedback.applied ? (
            <p className="annual-sim__notice">{ANNUAL_COPY.feedbackApplied}</p>
          ) : (
            <p className="annual-sim__caption">{ANNUAL_COPY.feedbackNotApplied}</p>
          )}
        </section>
      )}

      {/*
        ── 필요 감축량 (PRD §12.3.1 · #433) ──────────────────────────

        **Monte Carlo를 부르지 않는다**(UIFLOW 2-10). 위 결정론 블록과 같은 실행에서
        파생되므로 확률 결과와 전제가 갈릴 수 없다.

        ⚠️ `#433` 이전에 만들어진 실행에는 블록이 없다 — 그때는 카드를 그리지 않는다.
        없는 것을 0으로 그리면 「줄일 것이 없다」로 읽힌다.
      */}
      {cut && (
        <section className="annual-sim__block">
          <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.reductionTitle}</h2>
          <p className="annual-sim__caption">{ANNUAL_COPY.reductionCaption}</p>

          <div className="annual-sim__metrics">
            <div className="annual-sim__metric">
              <span className="annual-sim__label">{ANNUAL_COPY.reductionTargetLabel}</span>
              <GradeBadge
                rating={cut.target_rating}
                size="lg"
                label={`${ANNUAL_COPY.reductionTargetLabel} ${cut.target_rating}`}
              />
            </div>
            <Metric
              label={ANNUAL_COPY.reductionBoundaryLabel}
              value={formatDecimalString(cut.target_cii, DISPLAY_DIGITS.cii)}
            />
          </div>

          {!cut.achievable ? (
            <p className="annual-sim__notice">{ANNUAL_COPY.reductionUnreachable}</p>
          ) : cut.required_cut_fuel_ton === null ? (
            <p className="annual-sim__caption">{ANNUAL_COPY.reductionNoPlan}</p>
          ) : cut.required_cut_gco2 === '0' || Number(cut.required_cut_gco2) === 0 ? (
            <p className="annual-sim__caption">{ANNUAL_COPY.reductionNoneNeeded}</p>
          ) : (
            <div className="annual-sim__metrics">
              {/* 단위·자릿수는 `§4.2`가 소유한다 — g을 그대로 적던 자리다 (#1539). */}
              <Metric
                label={ANNUAL_COPY.reductionCutLabel}
                value={reductionCutText(cut.required_cut_gco2, cut.required_cut_fuel_ton).co2}
              />
              <Metric
                label={ANNUAL_COPY.reductionCutFuelLabel}
                value={reductionCutText(cut.required_cut_gco2, cut.required_cut_fuel_ton).fuel}
              />
            </div>
          )}
        </section>
      )}

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
            // 「0.0%」 구간은 그리지 않는다 — 폭이 없어 보이지 않는 요소에 초점이 가던
            // 자리다 (#1096 ⑵). 값은 아래 범례와 그룹의 대체 텍스트에 그대로 있다.
            if (seg.empty) return null
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
              {/* §2.5 (b) — 라벨이 바로 옆에 있으므로 장식이다. `Icon`이 aria-hidden을 붙인다. */}
              {flag.withIcon ? <Icon glyph={AlertTriangle} size="inline" /> : null} {flag.text}
            </span>
          </div>
        </div>

        {/* 섹션 제목이 `h2`라 다음 단계는 `h3`다 — 단계를 건너뛰지 않는다 (#1096 ⑶). */}
        <h3 className="annual-sim__sub-title">{ANNUAL_COPY.spreadTitle}</h3>
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
            ⚠️ **잔여 계획이 0건이면 여섯 행이 전부 같은 값**이다 — 지렛대가 움직일
            대상이 없다(#756 · 2026-09-13 화면 실측). 그때 거리 행 설명만 띄우면
            **나머지 행은 의미가 있는 것처럼 읽힌다.** 응답이 이미 `NO_REMAINING_VOYAGES`를
            싣고 있으므로, 화면이 아는 사실을 이 자리에서 말한다(`#630`과 같은 처리).

            잔여가 있을 때만 거리 행 설명을 띄운다. 거리 행은 잔여 계획과 확정 실적의
            배출 강도가 같으면 기준과 **정확히 같은** 값이 나온다 — 모델의 성질이지
            결함이 아니다(`PRD §12.6` 각주). 그 행이 표에 있을 때만 이유를 말한다.
          */}
          {result.warnings.includes(NO_REMAINING_VOYAGES) ? (
            <p className="annual-sim__caption">{ANNUAL_COPY.sensitivityNoRemainingNote}</p>
          ) : rows.some((row) => row.key.startsWith('distance_')) ? (
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
        {/*
          seed 줄은 밖에 둔다 (#1418) — `PRD §12.4.3` 「자동 seed … 결과에 표시한다」.
          스냅샷·계산 이력 식별자(UUID)와 항차 사본은 「계산 근거 보기」 안으로.
        */}
        <dl className="annual-sim__repro">
          <dt>seed</dt>
          <dd>{reproducibilityLine(mc)}</dd>
        </dl>
        <details className="annual-sim__repro-details">
          <summary>{ANNUAL_COPY.reproDetailsToggle}</summary>
          <dl className="annual-sim__repro">
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
          {/* 이 실행에 쓴 항차 — 펼칠 때 불러온다 (`API_SPEC §6.3` · #992). */}
          <SnapshotVoyages
            simulationId={result.simulation_id}
            voyageCount={result.snapshot.voyage_count}
            provider={provider}
          />
        </details>
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
            <>
              {/*
                재현 성공은 **실패와 같은 무게**로 보인다 (2026-09-17 확정 ⓑ · `#1053` 40번).

                종전에는 성공이 `--text-muted` 작은 한 줄이고 실패만 아이콘 달린 블록이라
                **무게가 반대**였다 — 재현 확인은 「같은 결과가 나왔다」가 곧 결론인
                검증 행위인데, 그 결론이 더 약하게 보였다.

                모양은 `ErrorState`의 영역 실패를 따른다(중립 면 + 테두리 + 아이콘).

                ⚠️ **색을 쓰지 않는다.** 같은 구조라면 아이콘·문구에 Success를 입히는
                것이 `§0.2` 제약 2·3의 짝이지만, 라이트 `--color-success`(`#38a169`)가
                이 면(`--color-surface-2`) 위에서 **2.89**라 비텍스트 `3:1`조차 넘지
                못한다. Success 값이 정해지면(별건 이슈) 아이콘과 문구에 색만 입히면 된다.
              */}
              <div className="annual-sim__reproduce-ok" role="status">
                <Icon glyph={CheckCircle2} className="annual-sim__reproduce-ok-icon" size="inline" />
                <p className="annual-sim__reproduce-ok-text">{ANNUAL_COPY.reproduceSuccess}</p>
              </div>
              {/*
                재현 응답의 경고 (`#1095` ⑶). 문구는 `WARNING_MESSAGE`가 갖는다 —
                `API_SPEC §1.6`과 `warningMessage.sync.test.ts`가 잠그는 사슬이다.
                위 결과 경고 목록과 **다른 범위**라 여기 따로 둔다: 저쪽은 원본
                실행의 경고이고 이쪽은 **재현 실행**의 경고다.
              */}
              {reproduce.warnings.length > 0 ? (
                <ul className="annual-sim__warnings">
                  {reproduce.warnings.map((code) => (
                    <li key={code}>{warningMessage(code)}</li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}
        </div>
        {reproduce.status === 'error' ? (
          <ErrorState
            level="region"
            action={ANNUAL_COPY.reproduceErrorAction}
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
