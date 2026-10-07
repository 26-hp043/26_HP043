import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import './AnnualSimulation.css'
import { PercentileRange } from './PercentileRange'
import { DISPLAY_DIGITS, formatDecimalString, formatTimestamp } from '../../display/format'
import { riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { useShellContext } from '../../layout/shellContext'
import { VESSEL_QUERY_KEY } from '../../layout/globalContext'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeText } from '../parameters/fuelTypes'
import { SELECT_VESSEL_FIRST, YEAR_STATE_COPY, useYearOptions } from '../parameters/yearCatalog'
import { gradePatternUrl } from '../../components/gradePattern'
import { ANNUAL_COPY } from './copy'
import { SCREEN_BY_ID } from '../../screens'

/**
 * 잔여 계획 항차가 0건임을 알리는 경고 코드 (`calc/annual_simulation.py`).
 *
 * 문구는 `resultRules.WARNING_MESSAGE`가 갖는다 — 여기서는 **있는지만** 본다.
 */
const NO_REMAINING_VOYAGES = 'NO_REMAINING_VOYAGES'
const SENSITIVITY_ONE_AT_A_TIME = 'SENSITIVITY_ONE_AT_A_TIME'
import {
  RUNS_MAX,
  RUNS_MIN,
  probabilityOfDorE,
  reproducibilityLine,
  riskFlag,
  sensitivityRows,
  topLever,
  stackSegments,
  toPercent,
  validateRuns,
  RUNS_DEFAULT,
  TARGET_DEFAULT,
  countAdvancedChanges,
  reductionCutText,
  resultConditionsText,
  futureYearsLineShown,
  futureYearsUnavailableText,
  targetVesselText,
} from './annualRules'
import { createAnnualSimulationProvider } from './providerSelection'
import type { AnnualSimulationProvider, AnnualSimulationResult } from './types'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'
import { ChoiceCards } from '../../components/ChoiceCards'
import { targetDescription, useGradeBoundaries } from './gradeBoundaries'
import { SnapshotVoyages } from './SnapshotVoyages'
import { isOffice, useAuthUser } from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'
import { Icon } from '../../components/Icon'
import { VerdictStrip } from '../../components/VerdictStrip'
import { publishScreenResult } from '../assistant/screenResult'
import { AnnualPlayback } from './visualization/AnnualPlayback'
import type { AnnualMapGeometryProvider } from './visualization/model'
import { YearlyActuals, type ActualsState } from './YearlyActuals'
import { createApiVesselDetailProvider, VesselDetailError } from '../vessel-detail/apiProvider'
import type { VesselDetailProvider } from '../vessel-detail/types'

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
  | {
      status: 'success'
      result: AnnualSimulationResult
      conditions: RunConditions
      /** 들어올 때 다시 연 마지막 실행이면 그 시각과 재계산 필요 여부 (#1701). 방금 돌렸으면 없다. */
      restored?: { createdAt: string; needsRecalc: boolean }
    }
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
  mapGeometryProvider,
  historyProvider: injectedHistory,
}: {
  /** 면책 배너는 페이지가 항상 렌더한다(`DESIGN_SYSTEM §13` 🔒). */
  onDisclaimer?: (text: string | undefined) => void
  /** API 응답에는 없는 실제 snapshot 좌표를 future provider가 주입하는 경계다. */
  mapGeometryProvider?: AnnualMapGeometryProvider
  /**
   * 연도별 실적의 출처 (#2017) — **선박 상세와 같은 조회**(`GET /vessels/{id}/cii-history`)다.
   * 이 화면이 경로를 따로 정의하지 않는다: 같은 경로를 두 곳이 정의하면 한쪽만 고쳐진 날
   * 두 화면이 다른 값을 말한다(`#750` · `#866`). 검사가 시간을 쥐려고 주입한다.
   *
   * ⚠️ **안정된 참조**를 넘겨야 한다 — 이 값은 조회 effect의 의존성이라, 렌더마다 새 객체를
   * 만들어 넘기면 렌더마다 다시 받는다. 호출자가 `useMemo`로 쥐거나 모듈 상수로 둔다.
   */
  historyProvider?: Pick<VesselDetailProvider, 'load'>
}) {
  // 선박은 **상단바 전역 선택을 따른다** (#484 · #535). 종전에는 UUID가 상수로
  // 박혀 있어, 상단에서 어떤 배를 골라도 늘 같은 배로 계산했다.
  const shell = useShellContext()
  const provider = useMemo(() => createAnnualSimulationProvider(), [])
  const historyProvider = useMemo(
    () => injectedHistory ?? createApiVesselDetailProvider(),
    [injectedHistory],
  )
  /*
   * 연도별 실적 (#2017). `vesselId`를 함께 쥔다 — 렌더는 **지금 고른 배의 것**일 때만 그린다.
   * 선박이 바뀐 직후 effect가 돌기 전 한 렌더에서 앞 배의 표가 새 배 이름 아래 보이지 않게.
   */
  const [actuals, setActuals] = useState<(ActualsState & { vesselId: string }) | null>(null)
  /** 「다시 시도」 — 올리면 같은 선박으로 다시 받는다. */
  const [actualsAttempt, setActualsAttempt] = useState(0)
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
  /** 들어올 때 다시 연 결과의 `선박|연도` (#1701) — 리셋 effect가 그 결과를 지우지 않게. */
  const restoredKeyRef = useRef<string | null>(null)
  /**
   * 들어올 때 받던 「마지막 결과」를 **버리는** 번호 (#1701 후속). 세대 번호(`generationRef`)와
   * 따로 둔다 — 세대 번호는 `year`가 바뀔 때마다 오르는데, 연도 **목록이 늦게 도착해**
   * `year`가 빈 값에서 올해로 채워지는 것도 거기에 든다. 그것은 사용자가 대상을 바꾼 것이
   * 아니다. 한데 두면 목록보다 늦게 온 복원 응답이 「늦은 응답」으로 버려져, 실제 화면에서
   * **복원이 한 번도 보이지 않았다**(09-26 로컬 스택 실측 · 서버는 결과를 돌려줬다).
   * 올리는 곳은 셋 — 실행을 누름 · 사용자가 연도를 고름 · (선박 변경은 effect 정리가 맡는다).
   */
  const restoreCancelRef = useRef(0)
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
  const fuelOptions = useFuelOptions()
  /*
   * 셀렉트에 보이는 값과 요청에 실리는 값은 **같은 값**이다 (#2125). 복원한 결과의 대체 연료가
   * 지금 연료 목록에 없는 코드이면(비활성화 · 아직 받는 중 · 받지 못함) 셀렉트는 「고르지 않음」을
   * 보이는데 요청에는 그 코드가 실려 갈리게 된다 — 목록에 있는 코드일 때만 쓴다. 목록이 늦게
   * 도착하면 그때 보이지만, 그 사이에 실행을 눌렀다면 실행 시작에서 상태를 **실제로 보낸 값**으로
   * 고정한다 — 그러지 않으면 목록이 오는 순간 방금 돌린 결과와 다른 연료가 입력칸에 나타난다.
   */
  const alternativeFuelValue = fuelOptions.fuels.some((fuel) => fuel.code === alternativeFuel)
    ? alternativeFuel
    : ''
  const advancedChanged = countAdvancedChanges({
    runs,
    seed,
    applyFeedback,
    alternativeFuel: alternativeFuelValue,
  })

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
  /** 사용자가 고른 해. 화면에 쓰는 값은 아래 `year`다 — 목록과 대조해 렌더 중에 정한다. */
  const [chosenYear, setChosenYear] = useState('')

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
   * 기본 선택은 **렌더 중에 파생**한다 (`#1616` · `ScenarioComparison`과 같은 형태).
   * 종전에는 목록이 오면 effect가 상태를 채워, 목록 도착과 기본값 사이에 연도가 빈
   * 렌더가 한 번 있었다.
   *
   * `VoyageCiiForm`과 **같은 함수**를 쓴다. 종전에는 이 화면만 「가장 최근 해」를
   * 골랐는데, 규제연도가 2023~2030이라 기본값이 **2030**이었다 — 아직 실적이 없는
   * 해다. 「올해 남은 항차로 목표 등급을 맞출 수 있는가」를 보는 화면이므로
   * (`PRD §12`) 올해가 맞다.
   *
   * 올해를 **여기서 읽어** 순수 함수에 넘긴다 — 함수 안에서 `new Date()`를 부르면
   * 검사가 해를 고정할 수 없다.
   */
  // 아직 고른 해가 없으면 주소의 후보를 넘긴다 — 목록에 있을 때만 채택된다. 목록이 없으면 `''`다.
  const year = pickDefaultYear(years, new Date().getFullYear(), chosenYear || requestedYear)
  // 목표 등급 카드의 한 줄 풀이 — 이 배 · 이 연도의 등급 경계 (#2201).
  const gradeBoundaries = useGradeBoundaries(shell.vesselId, year)

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
    // 들어올 때 다시 연 마지막 결과가 **바로 이 (선박, 연도)의 것**이면 지우지 않는다
    // (#1701). 그 결과의 연도로 입력칸을 맞추느라 `year`가 바뀐 것이지 사용자가 대상을
    // 바꾼 것이 아니다. 사용자가 다른 해를 고르면 키가 달라져 종전대로 지운다.
    if (restoredKeyRef.current === `${shell.vesselId}|${year}`) return
    restoredKeyRef.current = null
    generationRef.current += 1
    // oxlint-disable-next-line react/set-state-in-effect -- 대상(선박·연도)이 바뀌면 앞 결과를 지우는 리셋 — 조건은 남기고 결과만 지우므로 파생값으로 둘 수 없다
    setState({ status: 'idle' })
  }, [shell.vesselId, year])

  /*
   * 들어오면 **그 배의 마지막 결과부터** 보여 준다 (#1701 · `API_SPEC §6.5` → `§6.2`).
   *
   * - **자동 실행하지 않는다** — 실행은 사무직만 가능하고 부를 때마다 `CalculationRun`이
   *   쌓인다(`§1.8` 비멱등). 여기서는 이미 있는 결과를 읽기만 한다(조회는 두 역할 모두).
   * - 입력칸도 **그 결과의 조건**(연도 · 목표 등급 · 반복 횟수)으로 맞춘다 — 결과와 입력이
   *   다른 조건을 가리키지 않게.
   * - 없거나 못 받으면 지금의 빈 화면 그대로다. 못 받은 것을 오류로 띄우지 않는다 — 이
   *   조회는 편의이고, 사용자는 실행으로 언제든 결과를 얻는다.
   * - 받는 동안 사용자가 실행을 누르거나 연도를 고르거나 선박을 바꾸면 늦은 응답을 버린다
   *   (`restoreCancelRef` · 선박은 effect 정리). **연도 목록이 늦게 와서 `year`가 채워지는 것은
   *   버릴 이유가 아니다** — 세대 번호를 쓰면 그것까지 버려 실제 화면에서 복원이 안 보였다.
   */
  useEffect(() => {
    const vesselId = shell.vesselId
    if (vesselId === null) return
    const ticket = restoreCancelRef.current
    let alive = true
    provider
      .latest(vesselId)
      .then((found) => {
        if (!alive || found === null || ticket !== restoreCancelRef.current) return
        const { item, result } = found
        const itemYear = String(item.regulation_year)
        restoredKeyRef.current = `${vesselId}|${itemYear}`
        setChosenYear(itemYear)
        if ((TARGET_RATINGS as readonly string[]).includes(item.target_rating)) {
          setTarget(item.target_rating as (typeof TARGET_RATINGS)[number])
        }
        setRuns(String(item.simulation_runs))
        /*
         * 실적 보정·대체 연료도 **결과 본문이 말하는 값**으로 맞춘다 (#2125). 옛 결과에는 두 블록이
         * 없을 수 있다 — 값을 지어내지 않고 기본(끔·고르지 않음)으로 둔다. `seed`는 되돌리지
         * 않는다: 결과의 `rng` 메타는 서버가 정한 값이어서, 사용자가 직접 고르지 않은 실행에서
         * 입력칸을 채우면 「직접 고정했다」로 읽힌다(고급 설정 변경 수 표시도 달라진다).
         */
        setApplyFeedback(result.feedback?.requested === true)
        setAlternativeFuel(result.sensitivity_analysis?.fuel_cf_alternative?.alternative_fuel ?? '')
        setState({
          status: 'success',
          result,
          // 선박명은 렌더할 때 채운다 — 복원 결과는 선박이 바뀌면 지워지므로 지금 이름이 그 배다.
          conditions: { vesselName: '', year: itemYear, target: item.target_rating },
          restored: { createdAt: item.created_at, needsRecalc: item.needs_recalc },
        })
      })
      .catch(() => {
        // 편의 조회다 — 실패해도 빈 화면 그대로 둔다(위 주석).
      })
    return () => {
      alive = false
    }
  }, [provider, shell.vesselId])

  /*
   * 연도별 실적을 받는다 (#2017 · `API_SPEC §2.7`, 기본 창 최근 3년).
   *
   * - **조회다** — 화면에 들어올 때 시뮬레이션을 자동 실행하지 않는다는 `#1701` 결정과 무관하다.
   *   `CalculationRun`이 쌓이지 않고 두 역할 모두 읽을 수 있다.
   * - 실패해도 **이 블록 안에서만** 알린다(`PRD §16.2` 오류 격리). 시뮬레이션은 그대로 실행된다.
   * - 선박이 바뀌면 다시 받고, 앞 배의 늦은 응답은 `alive`로 버린다(`#1094`와 같은 이유 —
   *   결과 표에 선박명이 없어 사용자가 섞인 것을 알아챌 수 없다).
   */
  useEffect(() => {
    const vesselId = shell.vesselId
    if (vesselId === null) return
    let alive = true
    // oxlint-disable-next-line react/set-state-in-effect -- 선박이 바뀌면 앞 배의 실적을 지우고 「받는 중」으로 — 요청과 함께 시작하는 상태라 파생값으로 둘 수 없다
    setActuals({ vesselId, status: 'loading' })
    historyProvider.load(vesselId).then(
      (detail) => {
        if (alive) setActuals({ vesselId, status: 'success', detail })
      },
      (error: unknown) => {
        if (!alive) return
        setActuals({
          vesselId,
          status: 'error',
          message: error instanceof Error ? error.message : ANNUAL_COPY.actualsErrorFallback,
          // 없는 선박(404)에는 재시도를 주지 않는다 — 다시 눌러도 같은 실패다(선박 상세 · `#694`).
          retryable: !(error instanceof VesselDetailError && error.notFound),
        })
      },
    )
    return () => {
      alive = false
    }
  }, [historyProvider, shell.vesselId, actualsAttempt])

  const targetVessel = targetVesselText(shell.vesselId, shell.vessels, shell.vesselsState, {
    none: ANNUAL_COPY.targetVesselNone,
    loading: ANNUAL_COPY.targetVesselLoading,
    unknown: ANNUAL_COPY.targetVesselUnknown,
  })

  /*
   * 어시스턴트가 읽는 실행은 **화면에 보이는 결과의 실행**이다 (#1533 · #2125).
   * 새 실행이 성공했을 때뿐 아니라 들어올 때 다시 연 「마지막 실행」(#1701)도 올리고, 결과가
   * 지워지는 모든 경로(선박·연도 전환 · 새 실행 시작 · 실패 · 막힘 · 화면을 떠남)에서 비운다 —
   * `state`가 성공이 아니게 되는 순간이 곧 그 경로들이라 한 곳에서 맞춘다.
   * (확률까지 저장된 실행에서 읽게 하는 이유: 다시 돌리면 화면과 달라진다.)
   */
  const shownRunId = state.status === 'success' ? state.result.calculation_run_id : null
  useEffect(() => {
    publishScreenResult(shownRunId)
    return () => publishScreenResult(null)
  }, [shownRunId])

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
        // 목록이 비어 있는 것(실패도 로딩도 아님)을 「불러오는 중」으로 말하지 않는다 (#2120).
        message: yearsFailed
          ? ANNUAL_COPY.yearsUnavailable
          : yearsLoading
            ? ANNUAL_COPY.yearsPending
            : YEAR_STATE_COPY.empty,
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
    // 보낸 값으로 상태를 고정한다 — 복원한 연료가 목록 도착 전이라 빠졌다면 상태에서도 뺀다 (#2125).
    setAlternativeFuel(alternativeFuelValue)
    setState({ status: 'running' })
    // 새 실행이 시작되면 들어올 때 받던 마지막 결과가 뒤늦게 와도 버린다(#1701).
    generationRef.current += 1
    restoreCancelRef.current += 1
    restoredKeyRef.current = null
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
        ...(alternativeFuelValue ? { alternative_fuel: alternativeFuelValue } : {}),
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
  }, [provider, shell.vesselId, targetVessel, year, yearsFailed, yearsLoading, target, runs, seed, applyFeedback, alternativeFuelValue, onDisclaimer])

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
              <span className="annual-sim__hint">{YEAR_STATE_COPY.loading}</span>
            ) : yearsFailed ? (
              <span className="annual-sim__hint">{YEAR_STATE_COPY.failed}</span>
            ) : shell.vesselId && years.length === 0 ? (
              <span className="annual-sim__hint">{YEAR_STATE_COPY.empty}</span>
            ) : (
              <select
                {...control}
                className="annual-sim__control"
                value={year}
                onChange={(event) => {
                  // 사용자가 고른 해를 늦게 온 복원 결과가 덮지 않게 한다 (#1701 후속).
                  restoreCancelRef.current += 1
                  setChosenYear(event.target.value)
                }}
              >
                {/*
                  선박을 고르기 전에는 자리표시 한 줄이 선다 (#2048 · `PRD §6.4`).
                  없으면 빈 상자가 떠서 「고장」과 「내 차례가 아님」이 구분되지 않는다.
                */}
                {shell.vesselId ? null : <option value="">{SELECT_VESSEL_FIRST}</option>}
                {years.map((y) => (
                  <option key={y} value={String(y)}>
                    {y}
                  </option>
                ))}
              </select>
            )
          }
        </Field>

        {/*
          목표 등급 — 선택 카드 (#2201 · `DESIGN_SYSTEM §8.4`). 넷 중 하나이고, 카드마다 **이 배 ·
          이 연도의 등급 경계**를 한 줄로 적는다(「연말 CII 5.348 이하」) — 셀렉트로는 A~D가 각각
          무엇을 뜻하는지 고르기 전에 보이지 않았다. 경계는 서버 값이다(`gradeBoundaries.ts`).
          E는 두지 않는다(`PRD §12.8`).
        */}
        <ChoiceCards
          name="annual-sim-target"
          legend={ANNUAL_COPY.targetRatingLabel}
          legendClassName="field__label"
          value={target}
          onChange={(rating) => setTarget(rating)}
          options={TARGET_RATINGS.map((rating) => ({
            value: rating,
            label: rating,
            description: targetDescription(rating, gradeBoundaries),
          }))}
        />

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
                value={alternativeFuelValue}
                aria-describedby="annual-sim-alt-fuel-hint"
                onChange={(event) => setAlternativeFuel(event.target.value)}
              >
                <option value="">{ANNUAL_COPY.alternativeFuelNone}</option>
                {fuelOptions.fuels.map((fuel) => (
                  <option key={fuel.code} value={fuel.code}>
                    {fuelTypeText(fuel.code)}
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
      {/*
        오른쪽 기둥 — **연도별 실적이 위, 시뮬레이션 결과가 아래** (#2017). 실적은
        결과 컨테이너 **밖**에 둔다: 결과의 첫 자리는 결론 띠여야 하고(`DESIGN_SYSTEM §8.6` 🔒),
        지나간 해의 기록은 그 결과의 일부가 아니다. 선박이 없으면 실적을 그리지 않는다 —
        아래 자리표시자가 「선박을 먼저 선택하라」를 이미 말하고 있어 같은 말을 두 번 두지 않는다.

        선박을 바꾸는 동안 **절은 남기고 본문만 「받는 중」**으로 둔다 — 절을 없앴다 다시 그리면
        제목이 깜빡이고 낭독이 다시 시작된다. 앞 배의 표가 새 배 이름 아래 보이지 않게 하는
        가드(`actuals.vesselId`)는 그대로다.
      */}
      <div className="annual-sim__column">

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
              vesselId={shell.vesselId}
              conditions={
                state.restored ? { ...state.conditions, vesselName: targetVessel } : state.conditions
              }
              restored={state.restored}
              provider={provider}
              mapGeometryProvider={mapGeometryProvider}
            />
          ) : null}
        </div>
        {/* 근거는 결과 아래 (10/7 시안 03) — 첫 자리는 결론이다. */}
        {shell.vesselId !== null && actuals !== null ? (
          <YearlyActuals
            footer={
              state.status === 'success' ? (
                <ResultBasis key={state.result.simulation_id} result={state.result} provider={provider} />
              ) : null
            }
            state={actuals.vesselId === shell.vesselId ? actuals : { status: 'loading' }}
            onRetry={() => setActualsAttempt((attempt) => attempt + 1)}
            // 결과의 해가 표의 확정 행과 같으면 두 값의 계산 경로가 다르다는 한 줄을 표 아래에 둔다.
            simulatedYear={state.status === 'success' ? Number(state.conditions.year) : undefined}
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

/**
 * 남은 해 기준 한 줄 (#2043 · 디자인 담당 제안 「남은 해 전부」) — 올해 결과 **하나**를 올해
 * 뒤의 규정연도마다의 기준에 대 본 등급. 「이대로면 2027년 C · 2028년 C · 2029년 D · 2030년 D」.
 *
 * 시뮬레이션을 다시 돌리지 않는다 — 위 「연도별 실적」(지나간 해 · 확정)과 달리 이 줄은
 * **예측** 쪽이라 결론 띠 아래 조건 줄들 사이에 둔다. 등급은 서버가 그 해의 경계로 판정한
 * 값 그대로다(`#2002`). 지나간 해는 위 블록이 맡으므로 이 줄은 이력 링크를 두지 않는다.
 *
 * **두 상태를 가른다**(`FutureYearOutlook` 타입 주석). 키가 없는 옛 실행은 그리지 않는다 —
 * 「계산하지 않았다」를 「이후 해는 괜찮다」로 읽히게 두지 않으려고 빈 목록은 사유를 말한다.
 * 등급 문자 뒤에 시각 숨김 「등급」을 붙여 낭독이 「2027년 D 등급」으로 읽히게 한다(`§14`).
 *
 * 모양은 `rlatnals4114`의 2026-09-29 확정이다(`#2056` C · `UIFLOW 2-3`) — 머리말 「이대로면」 ·
 * 구분자 「·」 · 배지 없는 글자 등급 · 결론 띠 아래. 그때 붙은 조건 둘:
 * - **지나간 해의 실행에는 이 줄을 싣지 않는다** — 실행한 규제연도가 기준 시각(`as_of`)의
 *   해이자 **지금**의 해일 때만 그린다(`futureYearsLineShown`). 지금을 함께 보는 것은 지난해
 *   결과를 올해 복원했을 때(`#1701`)를 위해서다. 빈 목록 문구도 같은 조건이다.
 * - **같은 등급의 연속 해를 묶지 않는다** — 해마다 한 항목이다. 「2027–2029 D」로 접으면
 *   기준선이 해마다 내려간다는 사실이 사라진다.
 * 가정 문구는 이 줄 **바로 아래**에 둔다 — 하단 면책 배너에 합치지 않는다(`#2056` C④).
 * `DESIGN_SYSTEM §13`의 「배너 한 칸」은 화면 바닥 고지의 규칙이고, 이 문장은 바로 위
 * 한 줄을 한정하는 문맥이라 그 대상에서 떨어지면 무엇에 대한 가정인지 사라진다.
 */
function FutureYearsLine({
  outlook,
  year,
  asOf,
}: {
  outlook: AnnualSimulationResult['future_years_outlook']
  /** 실행한 규제연도 (`RunConditions.year`) */
  year: string
  /** 그 실행의 기준 시각 (`meta.as_of`) — 「올해」의 근거 */
  asOf: string | undefined
}) {
  if (!outlook) return null
  // 지금을 **여기서 읽어** 넘긴다 — 검사는 `vi.useFakeTimers({ toFake: ['Date'] })`로 해를 고정한다.
  if (!futureYearsLineShown(year, asOf, new Date())) return null
  return (
    <div className="annual-sim__future-years" data-testid="annual-sim-future-years">
      {outlook.length === 0 ? (
        <p className="annual-sim__notice">{futureYearsUnavailableText(year)}</p>
      ) : (
        /*
          10/7 — 한 줄로. 해마다 같은 등급이면 「2027–2030년 모두 E」로 줄이고, 가정 문장(확정
          문구 · `#2056`)은 뒤에 짧게 붙인 뒤 전문은 풀이(title)로 둔다.
        */
        <p className="annual-sim__meta-line" title={ANNUAL_COPY.futureYearsAssumption}>
          <span className="annual-sim__conditions-label">{ANNUAL_COPY.futureYearsLabel}</span>{' '}
          {outlook.every((row) => row.projected_rating === outlook[0].projected_rating) &&
          outlook.length > 1 ? (
            <span data-testid="annual-sim-future-year">
              {`${outlook[0].regulation_year}–${outlook[outlook.length - 1].regulation_year}${ANNUAL_COPY.futureYearSuffix} 모두`}{' '}
              <strong>{outlook[0].projected_rating}</strong>
            </span>
          ) : (
            outlook.map((row, index) => (
              <span key={row.regulation_year} data-testid="annual-sim-future-year">
                {index > 0 ? ' · ' : null}
                {`${row.regulation_year}${ANNUAL_COPY.futureYearSuffix}`}{' '}
                <strong>{row.projected_rating}</strong>
                <span className="sr-only">{` ${ANNUAL_COPY.futureYearRatingUnit}`}</span>
              </span>
            ))
          )}
          <span className="annual-sim__meta-sub"> · 올해 연말 값이 그대로일 때의 참고 등급</span>
          <span className="sr-only"> {ANNUAL_COPY.futureYearsAssumption}</span>
        </p>
      )}
    </div>
  )
}

/** 「목표까지」를 띠에 올리는 조건 (10/7 시안 03) — 달성 가능 · 계획 있음 · 줄일 양이 0이 아님. */
function cutShown(cut: AnnualSimulationResult['reduction_plan']): boolean {
  return (
    cut != null &&
    cut.achievable &&
    cut.required_cut_fuel_ton !== null &&
    !(cut.required_cut_gco2 === '0' || Number(cut.required_cut_gco2) === 0)
  )
}

/** 「C 경계 5.348보다 67.7% 높음」 — 연말 예측과 목표 경계의 차이 (10/7 시안 03). */
function boundaryGapText(
  projected: string,
  cut: AnnualSimulationResult['reduction_plan'],
): string | undefined {
  if (cut == null) return undefined
  const p = Number(projected)
  const b = Number(cut.target_cii)
  if (!Number.isFinite(p) || !Number.isFinite(b) || b <= 0) return undefined
  const diff = ((p - b) / b) * 100
  const boundary = formatDecimalString(cut.target_cii, DISPLAY_DIGITS.cii)
  if (Math.abs(diff) < 0.05) return `${cut.target_rating} 경계 ${boundary}와 같음`
  return `${cut.target_rating} 경계 ${boundary}보다 ${Math.abs(diff).toFixed(1)}% ${diff > 0 ? '높음' : '낮음'}`
}

/**
 * 재현 · 계산 근거 (10/7) — 결과 카드들 사이가 아니라 「근거 — 연도별 실적」 카드의 맨 아래에 둔다.
 * 둘 다 「이 결과가 무엇으로 계산됐나」라 한 자리에 모았다. seed 줄과 재현 버튼은 늘 보인다
 * (`PRD §12.4.3` · #1418).
 */
function ResultBasis({
  result,
  provider,
}: {
  result: AnnualSimulationResult
  provider: AnnualSimulationProvider
}) {
  const { deterministic: det, monte_carlo: mc, feedback } = result
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

  return (
        <section className="annual-sim__basis" aria-label={ANNUAL_COPY.reproTitle}>
          <div className="annual-sim__reproduce">
            <dl className="annual-sim__repro">
              <dt>seed</dt>
              <dd>{reproducibilityLine(mc)}</dd>
            </dl>
            {/*
              seed를 입력칸에 옮겨 적는 우회로 대신 두는 버튼이다 — 그 우회는 **폼의 다른 칸이
              바뀌었으면 다른 조건으로** 돌고, 결과가 달라도 그것이 재현 실패인지 알 수 없다.
            */}
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
                  모양은 `ErrorState`의 영역 실패를 따른다(중립 면 + 테두리 + 아이콘).

                  ⚠️ **색을 쓰지 않는다.** 라이트 `--color-success`(`#38a169`)가 이 면
                  (`--color-surface-2`) 위에서 **2.89**라 비텍스트 `3:1`조차 넘지 못한다.
                  문자 전용 별칭 `--color-success-text`(`#1653`)는 이미 있다 — 이 면 위에서도
                  4.61이라 넘는다. 색을 입히는 것은 별건이고, 지금은 입히지 않는다.
                */}
                <div className="annual-sim__reproduce-ok" role="status">
                  <Icon glyph={CheckCircle2} className="annual-sim__reproduce-ok-icon" size="inline" />
                  <p className="annual-sim__reproduce-ok-text">{ANNUAL_COPY.reproduceSuccess}</p>
                </div>
                {/*
                  재현 응답의 경고 (`#1095` ⑶). 아래 결과 경고 목록과 **다른 범위**라 따로
                  둔다: 저쪽은 원본 실행의 경고이고 이쪽은 **재현 실행**의 경고다.
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

          <details className="annual-sim__repro-details">
            <summary>{ANNUAL_COPY.reproDetailsToggle}</summary>

            {/* ── 결정론 (PRD §12.3) — 값과 등급은 결론 띠에 있다. 여기는 무엇을 더했는지 ── */}
            <div className="annual-sim__group">
              <h3 className="annual-sim__sub-title">{ANNUAL_COPY.deterministicTitle}</h3>
              <p className="annual-sim__caption">{ANNUAL_COPY.deterministicCaption}</p>
              <dl className="annual-sim__list">
                <Row
                  label={ANNUAL_COPY.projectedCiiLabel}
                  value={formatDecimalString(det.projected_attained_cii, DISPLAY_DIGITS.cii)}
                />
                <Row label={ANNUAL_COPY.projectedRatingLabel} value={det.projected_rating} />
                <Row label={ANNUAL_COPY.completedLabel} value={String(det.completed_voyage_count)} />
                <Row label={ANNUAL_COPY.remainingLabel} value={String(det.remaining_voyage_count)} />
              </dl>
            </div>

            {/*
              ── 실적 보정계수 (PRD §12.2.1 · #363) ──

              세 상태를 가른다 — ⑴ 곱했다 ⑵ 값은 있으나 곱하지 않았다 ⑶ 표본이 모자라 값이
              없다. ⚠️ ⑶을 1.0이나 빈칸으로 그리면 「계획대로 쓰고 있다」로 읽힌다.

              `#363` 이전 실행에는 블록이 없다 — 그때는 그리지 않는다.
            */}
            {feedback && (
              <div className="annual-sim__group">
                <h3 className="annual-sim__sub-title">{ANNUAL_COPY.feedbackTitle}</h3>
                <p className="annual-sim__caption">{ANNUAL_COPY.feedbackCaption}</p>
                <dl className="annual-sim__list">
                  <Row
                    label={ANNUAL_COPY.feedbackFactorLabel}
                    value={
                      feedback.factor === null
                        ? ANNUAL_COPY.feedbackUnavailableValue
                        : `× ${formatDecimalString(feedback.factor, 4)}`
                    }
                  />
                  <Row
                    label={ANNUAL_COPY.feedbackSampleLabel}
                    value={`${feedback.sample_size}건`}
                    hint={`${ANNUAL_COPY.feedbackMinSampleHint} ${feedback.min_sample}건`}
                  />
                </dl>
                {feedback.factor === null ? (
                  <p className="annual-sim__caption">{ANNUAL_COPY.feedbackUnavailable}</p>
                ) : feedback.applied ? (
                  <p className="annual-sim__notice">{ANNUAL_COPY.feedbackApplied}</p>
                ) : (
                  <p className="annual-sim__caption">{ANNUAL_COPY.feedbackNotApplied}</p>
                )}
              </div>
            )}

            <div className="annual-sim__group">
              <h3 className="annual-sim__sub-title">{ANNUAL_COPY.reproTitle}</h3>
              <p className="annual-sim__caption">{ANNUAL_COPY.reproCaption}</p>
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
            </div>
          </details>
        </section>
  )
}

function Result({
  result,
  vesselId,
  conditions,
  restored,
  provider,
  mapGeometryProvider,
}: {
  result: AnnualSimulationResult
  /** 다음 행동 링크(항로 비교)가 같은 배를 담아 간다 (#2222). 상단바 전역 선택이 소유한다. */
  vesselId: string | null
  conditions: RunConditions
  restored?: { createdAt: string; needsRecalc: boolean }
  provider: AnnualSimulationProvider
  mapGeometryProvider?: AnnualMapGeometryProvider
}) {
  const { deterministic: det, monte_carlo: mc, reduction_plan: cut, feedback } = result
  const risk = riskLabel(result.risk_level)
  const pDorE = probabilityOfDorE(mc.rating_probabilities)
  const flag = riskFlag(pDorE)
  const segments = stackSegments(mc.rating_probabilities)
  const rows = sensitivityRows(result.sensitivity_analysis)
  const noRemaining = result.warnings.includes(NO_REMAINING_VOYAGES)
  // 잔여 계획 0건이면 표를 그리지 않으므로(#1580) 한 줄도 내지 않는다.
  const lever = noRemaining ? null : topLever(rows)
  /*
   * 민감도 절이 있으면 「복합 효과 미포함」은 그 절이 `interaction_note`로 이미 말한다 (#1700).
   * 서버가 같은 문장을 경고 코드로도 내려 종전에는 **카드 안과 맨 아래에 두 번** 나왔다.
   * 절이 없을 때(`#433` 이전 실행 등)는 경고 목록이 유일한 자리라 남긴다.
   */
  const resultWarnings =
    rows.length > 0
      ? result.warnings.filter((code) => code !== SENSITIVITY_ONE_AT_A_TIME)
      : result.warnings

  return (
    <>
      {mapGeometryProvider ? <AnnualPlayback result={result} geometryProvider={mapGeometryProvider}
        projectedYear={conditions.year} vesselName={conditions.vesselName} /> : null}
      {/*
        ── 결론 띠 (`DESIGN_SYSTEM §8.6` 🔒 · #1700) ─────────────────────

        이 화면의 답은 **목표 달성 확률**이다 — 위험도(`PRD §9.4.2`)가 이 값에서 나온다.
        종전에는 네 번째 카드의 두 번째 타일에 본문 크기로 들어 있어, 계산 순서를 따라
        결정론 → 보정 → 목표까지를 지나야 닿았다.

        보조는 결정론 연말 예측 하나다. 등급 배지와 값은 한 사실이다(`§14`).
        집계 · 남은 항차 수는 아래 「계산 근거」로 내린다.
      */}
      <VerdictStrip
        label={ANNUAL_COPY.verdictLabel}
        main={{
          label: `${ANNUAL_COPY.targetSuccessLabel} (${mc.target_rating} 이상)`,
          value: toPercent(mc.target_success_probability),
        }}
        sub={{
          label: ANNUAL_COPY.verdictProjectedLabel,
          value: formatDecimalString(det.projected_attained_cii, DISPLAY_DIGITS.cii),
          rating: det.projected_rating,
          ratingLabel: `${ANNUAL_COPY.projectedRatingLabel} ${det.projected_rating}`,
          note: boundaryGapText(det.projected_attained_cii, cut),
        }}
        /*
          10/7 시안 03 — 「목표까지」를 띠의 셋째 칸으로. 종전에는 분포 아래 목록에 있어 첫 화면에서
          「얼마나 줄여야 하나」가 읽히지 않았다. 달성 가능하고 줄일 양이 있을 때만 — 나머지 경우
          (달성 불가 · 잔여 계획 없음 · 이미 충족)는 아래 안내 문장이 그대로 말한다.
        */
        third={
          cutShown(cut)
            ? {
                label: ANNUAL_COPY.verdictTargetLabel,
                value: `연료 −${reductionCutText(cut!.required_cut_gco2, cut!.required_cut_fuel_ton).fuel}`,
                note: `CO₂ −${reductionCutText(cut!.required_cut_gco2, cut!.required_cut_fuel_ton).co2} · 남은 계획 거리는 그대로`,
              }
            : undefined
        }
        risk={{ level: result.risk_level, heading: ANNUAL_COPY.riskLabel, ...risk }}
      />

      {/*
        이 결과의 조건 (#1553) · 추정 고지 (#1578) — 띠 바로 아래 한 줄씩(`§8.6`).
        결과만 캡처해도 어느 배 · 어느 해 · 어느 목표인지 읽힌다.
      */}
      <div className="annual-sim__under-verdict">
        {/*
          결과를 바꾸는 변수 한 줄 (#2199) — 표는 화면 맨 아래라 첫 화면에서 답의 다음
          질문(「그럼 무엇이 바꾸나」)이 읽히지 않았다. 수치와 등급만 강조한다.
          권고가 아니라 민감도 결과의 서술이다(`topLever` 머리주석).
        */}
        {lever ? (
          <p className="annual-sim__conditions" data-testid="annual-sim-top-lever">
            <span className="annual-sim__conditions-label">{ANNUAL_COPY.topLeverLabel}</span>{' '}
            {lever.label} → {ANNUAL_COPY.topLeverYearEnd}{' '}
            <b className="annual-sim__em">{lever.toRating}</b> · {ANNUAL_COPY.topLeverProbability}{' '}
            <b className="annual-sim__em">{lever.probabilityChange}</b>
          </p>
        ) : null}
        {restored?.needsRecalc ? (
          <p className="annual-sim__notice" role="status">
            {ANNUAL_COPY.lastRunNeedsRecalc}
          </p>
        ) : null}
        <FutureYearsLine
          outlook={result.future_years_outlook}
          year={conditions.year}
          asOf={result.as_of}
        />
        {/*
          조건 · 실행 시각 · 추정 고지를 한 줄로 (10/7) — 종전 세 줄(「이 결과의 조건」 · 「마지막 실행」 ·
          「이 결과의 수치는 모두 …추정값입니다. 기준 시각은 …」)이 같은 시각을 두 번 적었다.
          화면 단위 추정 고지(`§11` · #1578)는 줄 끝에 짧게 남는다.
        */}
        <p className="annual-sim__meta-line annual-sim__meta-line--muted" data-testid="annual-sim-last-run">
          {resultConditionsText(conditions)}
          {formatTimestamp(restored?.createdAt ?? result.as_of ?? '') !== null
            ? ` · ${formatTimestamp(restored?.createdAt ?? result.as_of ?? '')} 실행`
            : ''}
          {result.is_sample_data
            ? ` · ${ANNUAL_COPY.sampleNotice}`
            : ' · 잔여 계획을 전제로 한 추정값'}
        </p>
      </div>

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
            if (seg.empty) return null
            /*
              10/7 — 등급 배지와 같은 표기(연한 면 · 진한 글자). 글자가 구간 **안에** 들어가는 구간은
              무늬를 빼고(`§2.4.4` 「패턴 미적용」), 8% 미만이라 글자가 못 들어가는 구간만 무늬를 남긴다.
            */
            const inline = seg.inline
            const pattern = inline ? null : gradePatternUrl(seg.rating)
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
        {/*
          `§2.5 (a)` — 확률 파생 표기 `P(D/E)`. 위험도 pill과 **다른 채널**이라 띠에 올리지
          않고 분포 곁에 둔다. 한 자리에 두 경고 표기가 겹치지 않게 한다(`§2.3`).
        */}
        <p className={`annual-sim__flag annual-sim__flag--${flag.tone}`}>
          {/* §2.5 (b) — 라벨이 바로 옆에 있으므로 장식이다. `Icon`이 aria-hidden을 붙인다. */}
          {flag.withIcon ? <Icon glyph={AlertTriangle} size="inline" /> : null} {flag.text}
        </p>

        {/*
          목표까지 · 분포 요약 — 타일 대신 「라벨 · 값」 목록 두 벌을 나란히 둔다(`§5` 카드 예산).
          섹션 제목이 `h2`라 다음 단계는 `h3`다 — 단계를 건너뛰지 않는다 (#1096 ⑶).
        */}
        <div className="annual-sim__pair">
          {/*
            ── 필요 감축량 (PRD §12.3.1 · #433) ──

            **Monte Carlo를 부르지 않는다**(UIFLOW 2-10). 결정론 예측과 같은 실행에서
            파생되므로 확률 결과와 전제가 갈릴 수 없다.

            ⚠️ `#433` 이전에 만들어진 실행에는 블록이 없다 — 그때는 그리지 않는다.
            없는 것을 0으로 그리면 「줄일 것이 없다」로 읽힌다.
          */}
          {cut && !cutShown(cut) && (
            <div className="annual-sim__group">
              <h3 className="annual-sim__sub-title">{ANNUAL_COPY.reductionTitle}</h3>
              <p className="annual-sim__caption">{ANNUAL_COPY.reductionCaption}</p>
              <dl className="annual-sim__list">
                <Row
                  label={`${ANNUAL_COPY.reductionBoundaryLabel} (${cut.target_rating})`}
                  value={formatDecimalString(cut.target_cii, DISPLAY_DIGITS.cii)}
                />
                {cut.achievable &&
                cut.required_cut_fuel_ton !== null &&
                !(cut.required_cut_gco2 === '0' || Number(cut.required_cut_gco2) === 0) ? (
                  <>
                    {/* 단위·자릿수는 `§4.2`가 소유한다 — g을 그대로 적던 자리다 (#1539). */}
                    <Row
                      label={ANNUAL_COPY.reductionCutLabel}
                      value={reductionCutText(cut.required_cut_gco2, cut.required_cut_fuel_ton).co2}
                    />
                    <Row
                      label={ANNUAL_COPY.reductionCutFuelLabel}
                      value={reductionCutText(cut.required_cut_gco2, cut.required_cut_fuel_ton).fuel}
                    />
                  </>
                ) : null}
              </dl>
              {!cut.achievable ? (
                <p className="annual-sim__unreachable">{ANNUAL_COPY.reductionUnreachable}</p>
              ) : cut.required_cut_fuel_ton === null ? (
                <p className="annual-sim__caption">{ANNUAL_COPY.reductionNoPlan}</p>
              ) : cut.required_cut_gco2 === '0' || Number(cut.required_cut_gco2) === 0 ? (
                <p className="annual-sim__caption">{ANNUAL_COPY.reductionNoneNeeded}</p>
              ) : null}
            </div>
          )}
          <div className="annual-sim__group">
            <h3 className="annual-sim__sub-title">{ANNUAL_COPY.spreadTitle}</h3>
            {/* 네 값을 한눈에 — 막대 아래 숫자 행은 그대로 둔다 (#1456) */}
            <PercentileRange p10={mc.p10} p50={mc.p50} p90={mc.p90} mean={mc.mean_cii} />
            {/*
              숫자는 한 줄 셋으로 (10/7 · A7) — 하위 10% · 중앙값 · 상위 10%. 평균은 중앙값과 거의 같아
              같은 말을 두 번 했다. 평균 위치는 위 막대의 ◆가 그대로 보인다.
            */}
            <dl className="annual-sim__spread-row">
              <div>
                <dt>{ANNUAL_COPY.p10Label}</dt>
                <dd>{formatDecimalString(mc.p10, DISPLAY_DIGITS.cii)}</dd>
              </div>
              <div>
                <dt>{ANNUAL_COPY.p50Label}</dt>
                <dd className="annual-sim__spread-mid">{formatDecimalString(mc.p50, DISPLAY_DIGITS.cii)}</dd>
              </div>
              <div>
                <dt>{ANNUAL_COPY.p90Label}</dt>
                <dd>{formatDecimalString(mc.p90, DISPLAY_DIGITS.cii)}</dd>
              </div>
            </dl>
          </div>
        </div>
      </section>

      {/* ── 민감도 (PRD §12.6) ─────────────────────────────────────── */}
      {rows.length > 0 ? (
        <section className="annual-sim__block">
          <h2 className="card__title annual-sim__section-title">{ANNUAL_COPY.sensitivityTitle}</h2>
          {/*
            ⚠️ **잔여 계획이 0건이면 표를 그리지 않는다** (#1580). 지렛대는 잔여 계획 항차를
            움직여 결과를 다시 내므로 0건이면 **모든 행이 기준과 같은 값**이다(#756 · 실측
            8행 전부 「E→E · +0.0%」). 표를 두고 안내를 붙이면 같은 값 여덟 줄과 설명 두 개가
            한 자리에 쌓인다 — 안내 한 줄이 이 절의 전부다. 응답의 `NO_REMAINING_VOYAGES`로
            가른다(화면이 다시 판정하지 않는다).
          */}
          {noRemaining ? (
            <p className="annual-sim__caption">{ANNUAL_COPY.sensitivityNoRemainingNote}</p>
          ) : (
            <>
              {/*
                「복합 효과 미포함」 (`PRD §12.8`). 이 문장이 있으면 맨 아래 경고 목록에서는
                같은 코드를 뺀다 — 위 `resultWarnings` 참조.
              */}
              <p className="annual-sim__caption">
                {result.sensitivity_analysis.interaction_note}
              </p>
              {/*
                거리 행은 잔여 계획과 확정 실적의 배출 강도가 같으면 기준과 **정확히 같은**
                값이 나온다 — 모델의 성질이지 결함이 아니다(`PRD §12.6` 각주 · #756). 그 행이
                표에 있을 때만 이유를 말한다.
              */}
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
                          {/* 코드 원문(`LNG`)이 아니라 다른 자리와 같은 표기로 (`DESIGN_SYSTEM §3` · #2122). */}
                          {entry.alternative_fuel ? ` — ${fuelTypeText(entry.alternative_fuel)}` : ''}
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
              {/*
                거리 행 각주 (10/7) — 표 위에 긴 문단으로 있어 표보다 먼저 읽혔다. 표 아래 접힘으로
                내린다. 그 행이 표에 있을 때만 둔다(`PRD §12.6` 각주 · #756).
              */}
              {rows.some((row) => row.key.startsWith('distance_')) ? (
                <details className="annual-sim__footnote">
                  <summary>거리 행이 기준과 같은 이유</summary>
                  <p>{ANNUAL_COPY.distanceNote}</p>
                </details>
              ) : null}
            </>
          )}
          {/* 결과 경고 — 카드 사이에 큰 글씨로 떠 있던 것을 민감도 카드 안 작은 글씨로 (10/7) */}
          {resultWarnings.length > 0 ? (
            <ul className="annual-sim__warnings">
              {resultWarnings.map((code) => (
                <li key={code}>{warningMessage(code)}</li>
              ))}
            </ul>
          ) : null}
          {/* 다음 행동 — 민감도 카드의 맨 아래 한 줄 (10/7) */}
          {vesselId !== null ? (
            <p className="result-card__next annual-sim__next">
              <Link
                to={`${SCREEN_BY_ID.ROUTE_COMPARISON.path}?${new URLSearchParams({ [VESSEL_QUERY_KEY]: vesselId })}`}
              >
                이 선박으로 {SCREEN_BY_ID.ROUTE_COMPARISON.label} →
              </Link>
            </p>
          ) : null}
        </section>
      ) : null}

      {/*
        다음 행동 — 결과 맨 아래 한 줄, 하나만 (#2222 · `DESIGN_SYSTEM §8` 결과 카드). 띠 아래
        「가장 크게 움직이는 변수」(#2208)를 **이번 항로로 확인하는 곳**이 항로 비교다 — 같은 배가
        선택된 채로 간다(쿼리로 선박을 담는 화면이다). 「함대 단위로 보기」는 실행 조건 쪽 진입로라
        그 자리에 둔다(rlatnals4114 결정).
      */}
      {vesselId !== null && rows.length === 0 ? (
        <p className="result-card__next">
          <Link
            to={`${SCREEN_BY_ID.ROUTE_COMPARISON.path}?${new URLSearchParams({ [VESSEL_QUERY_KEY]: vesselId })}`}
          >
            {SCREEN_BY_ID.ROUTE_COMPARISON.label}
          </Link>
        </p>
      ) : null}

      {/* 재현 · 계산 근거는 「근거 — 연도별 실적」 카드 안으로 옮겼다 (10/7) — `ResultBasis` */}

      {rows.length === 0 && resultWarnings.length > 0 ? (
        <ul className="annual-sim__warnings">
          {resultWarnings.map((code) => (
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

/**
 * 「라벨 · 값」 한 줄 (`DESIGN_SYSTEM §5` 카드 예산 · #1700).
 *
 * 종전 `Metric`은 회색 타일(면 + 테두리)이라 카드 안에 면을 또 띄웠다 — 결과 한 번에
 * 타일 17개였다. 목록 한 줄로 두고 구분선으로만 나눈다. `dl` 안의 `div` 묶음은 HTML이
 * 허용하는 형태다.
 */
function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="annual-sim__row">
      <dt>{label}</dt>
      <dd>
        <span className="annual-sim__value">{value}</span>
        {hint ? <span className="annual-sim__hint">{hint}</span> : null}
      </dd>
    </div>
  )
}
