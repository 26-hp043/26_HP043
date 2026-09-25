import { AlertTriangle } from 'lucide-react'
import { useRef, useEffect, useMemo, useState } from 'react'
import './ScenarioComparison.css'
import { useShellContext } from '../../layout/shellContext'
import { ScenarioAdoptPanel } from './ScenarioAdoptPanel'
import { VoyageRouteMap } from './VoyageRouteMap'
import {
  FIELD,
  MIN_SPEED_KN,
  NO_VESSEL_MESSAGE,
  WEATHER_MODELS,
  applyVesselSpec,
  initialFormState,
  countAdvancedFilled,
  hasAdvancedError,
  toRequest,
  usesCoordinateDistance,
  usesWaypointDistance,
  validateForm,
  weatherNeedsCoordinates,
  type ComparisonFormState,
  type FormErrors,
} from './requestRules'
import {
  ESTIMATED_DISTANCE_HINT,
  GREAT_CIRCLE_FAILED,
  LOOKUP_SOURCE_NOTICE,
  distanceInput,
  fetchGreatCircleNm,
  lookupPort,
  matchSamplePort,
  portDisplayName,
  portOptionLabel,
  useSamplePorts,
  type PortCoord,
} from '../ports/samplePorts'
import { ScenarioComparisonError } from './provider'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  DISPLAY_UNIT_DAILY_FUEL,
  formatDecimalString,
  formatGrouped,
  formatPercent,
  toDecimalInput,
} from '../../display/format'
import {
  ciiUnit,
  displayWarnings,
  marginDisplay,
  riskLabel,
  warningMessage,
} from '../voyage-cii/resultRules'
import { GradeBadge } from '../../components/GradeBadge'
import {
  COORDINATE_DISTANCE_NOTICE,
  ESTIMATE_NOTICE,
  NO_AUTO_DECISION_NOTICE,
  WAYPOINT_DISTANCE_NOTICE,
} from './notices'
import { selectScenarioProvider } from './providerSelection'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { useYearOptions } from '../parameters/yearCatalog'
import { pickDefaultYear, sameInputs } from '../voyage-cii/formRules'
import {
  deltaFromDirect,
  isZeroDelta,
  lowestSummary,
  type ScenarioDelta,
} from './comparisonRules'
import { ScenarioRouteGlyph } from './ScenarioRouteGlyph'
import type { ScenarioComparisonResponse, ScenarioResult } from './types'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'
import { Icon } from '../../components/Icon'
import { useShowsLabelEn } from '../../i18n/core'
import { publishScreenResult } from '../assistant/screenResult'

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
 * ## 조건 입력 폼 (#511)
 *
 * 종전에는 입력 폼 없이 `DEMO_REQUEST` 상수를 마운트 즉시 보냈다. 그 상수의
 * `vessel_id`(`…0003`)가 demo 고정표에 없어 **데모 모드에서 항로 비교가 아무 입력
 * 없이 언제나 실패**했다. 상수를 `…0001`로 바꾸면 이번에는 실 API가 422를 낸다
 * (그 배는 `reference_speed_kn`이 비어 있다) — 어느 쪽을 골라도 한쪽이 깨진다.
 *
 * 그래서 선박을 **provider의 목록**에서 읽고 조건을 사용자가 넣는다. 규칙은
 * `requestRules.ts`에 있다.
 *
 * `PRD §11.3`의 나머지 입력(우회 거리·감속 속력·기상 모델·현재 좌표·목적항)은
 * `#892` 소관으로 남는다 — 이 화면이 받는 것은 계산에 실제로 필요한 여섯 값이다.
 * 종전 주석이 가리키던 `#139`는 2026-08-16에 닫혔고, 그 뒤로 **열린 추적처가
 * 없었다**(`AGENTS §6.1`). `#826`이 그 사실을 잡아 `#892`로 갈랐다.
 *
 * ## 표시 규칙은 기능①과 같다
 *
 * 자릿수·구분자는 `format.ts`, 단위·위험도·경고 문구는 `voyage-cii/resultRules.ts`를
 * 그대로 쓴다. 두 화면이 각자 규칙을 두면 한쪽만 정본을 따라가게 된다.
 */

/**
 * 비교 결과의 적재 상태.
 *
 * `idle`이 기본이다 — **마운트 시 계산을 걸지 않는다.** 사용자가 조건을 정하기
 * 전의 계산은 누구의 질문도 아니고, 실패하면 화면이 오류로 시작한다(#511).
 */
/** 좌표 찾기 한 칸의 안내 상태 (#768). 실패해도 폼을 막지 않으므로 오류가 아니라 안내다. */
interface LookupState {
  status: 'idle' | 'loading' | 'done'
  message: string
}

const IDLE_LOOKUP: LookupState = { status: 'idle', message: '' }

/**
 * 두 입력 문자열을 좌표 한 쌍으로 — 한쪽이라도 비었거나 수가 아니면 `null`이다 (#1750).
 *
 * `Number('')`은 0이다. 빈 칸을 적도 0도로 읽으면 **고르지 않은 위치로 거리를 낸다.**
 */
function toCoord(lat: string, lon: string): PortCoord | null {
  if (lat.trim() === '' || lon.trim() === '') return null
  const parsed = { lat: Number(lat), lon: Number(lon) }
  return Number.isFinite(parsed.lat) && Number.isFinite(parsed.lon) ? parsed : null
}

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; response: ScenarioComparisonResponse; snapshot: ResultSnapshot }
  | { status: 'error'; message: string }

/**
 * 계산 시점에 고정해 두는 것들 (#875).
 *
 * **숫자는 스냅샷인데 제목만 살아 있었다.** 제목의 선박명·연도가 `form`을 직접
 * 읽어, 결과를 본 뒤 상단바에서 배를 바꾸면 **A선의 계산 결과 위에 B선의 이름**이
 * 붙었다(연도도 같다 — 「2027년 기준」 제목 아래 2026년 계산이 남았다).
 *
 * 스냅샷을 응답 옆에 함께 둔다. 「제목만 따로 조심한다」로는 같은 결함이 다음에
 * 추가되는 표시값에서 되풀이된다 — **계산 시점 값은 계산 결과와 같은 자리에**
 * 있어야 한다.
 *
 * `inputs`는 제목의 출처이자 「결과가 낡음」의 비교 기준이다. 연도를 따로 복사해
 * 두지 않는 것은 두 곳이 갈라지지 않게 하기 위해서다.
 */
interface ResultSnapshot {
  /** 계산 시점 셸 목록에서 읽은 이름. 목록이 아직 없거나 지워진 배면 `null`. */
  vesselName: string | null
  /** 계산에 실제로 쓴 조건 전부. */
  inputs: ComparisonFormState
}

export function ScenarioComparison({
  onDisclaimer,
}: {
  /** 면책 배너는 페이지가 항상 렌더한다(`DESIGN_SYSTEM §13` 🔒). */
  onDisclaimer?: (text: string | undefined) => void
}) {
  const showsLabelEn = useShowsLabelEn()
  // 화면은 provider가 어떻게 만들어지는지 알지 않는다 (#134). demo 갈래는 #542가
  // 없앴다.
  const provider = useMemo(() => selectScenarioProvider(), [])
  // 선택지도 같은 원칙이다 (#236). 계산은 서버로 가는데 선택지는 고정표에서 오는
  // 상태가 이번 결함의 뿌리였다 — 연료 축이 마지막 조각이었다 (#542 · #558).
  const { fuels, loading: fuelsLoading, failed: fuelsFailed } = useFuelOptions()

  // 선박 목록·선택은 **셸이 소유한다** (#484 · #535). 종전에는 이 화면이 목록을
  // 따로 조회하고 선택도 따로 들어, 상단바에서 배를 바꿔도 여기는 그대로였다.
  const shell = useShellContext()
  const { vesselsState, selectVesselId } = shell
  const vessels = vesselsState === 'loading' ? null : shell.vessels
  const catalogError = vesselsState === 'failed' ? '선박 목록을 불러오지 못했습니다.' : null

  /*
   * ⚠️ **입력 핸들러는 전부 함수형 갱신(`setForm((prev) => …)`)이다** (`#1093` ⑷).
   *
   * 종전에는 `setForm({ ...form, X })`로 **렌더 시점의 스냅샷**을 펼쳤다. 규제연도
   * 기본값은 당시 목록이 도착한 뒤 effect가 채웠는데(지금은 렌더 중 파생 · `#1616`), 그 사이에 다른 칸을 건드리면
   * 스냅샷이 방금 채워진 연도를 **빈 값으로 되덮었다.** 종전에는 초기값에 `'2026'`이
   * 박혀 있어 이 손실이 드러나지 않았다 — 되덮어도 여전히 2026이었기 때문이다.
   */
  /**
   * 입력한 그대로의 폼. 화면·검증·요청에 쓰는 것은 아래 `form`이다 — 규제연도만 목록과
   * 대조해 렌더 중에 정한다(`#1616`). 갱신은 전부 `setForm((prev) => …)`라 원본을 다룬다.
   */
  const [rawForm, setForm] = useState<ComparisonFormState>(initialFormState)

  /*
   * 규제연도 선택지 (`#632`).
   *
   * 종전에는 **이 화면만 자유 입력**이라 파라미터가 없는 해를 넣을 수 있었고, 그때
   * 서버가 `PARAMETER_ERROR`로 거부했다 — `#236`이 「선박·연도·연료」 세 축을 고치며
   * 연도만 유예했고, `#534`가 두 화면을 옮기며 이 화면을 빠뜨렸다.
   */
  const { years, loading: yearsLoading, failed: yearsFailed } = useYearOptions(rawForm.vesselId)

  /*
   * 기본 연도는 **렌더 중에 파생**한다 (`#1616`). 종전에는 목록이 오면 effect가 상태를
   * 채워, 목록 도착과 기본값 사이에 연도가 빈 렌더가 한 번 있었다. **이미 고른 해가
   * 목록에 있으면 그대로 둔다** — 사용자가 고른 값을 덮으면 폼이 스스로 되돌아간다.
   * 목록이 비어 있으면 입력값을 그대로 둔다.
   *
   * 올해를 **여기서 읽어** 순수 함수에 넘긴다. 함수 안에서 `new Date()`를 부르면
   * 테스트가 해를 고정할 수 없다 (`formRules.ts` 주석과 같은 이유).
   */
  const regulationYear =
    years.length === 0
      ? rawForm.regulationYear
      : pickDefaultYear(years, new Date().getFullYear(), rawForm.regulationYear)
  const form = useMemo(
    () => (regulationYear === rawForm.regulationYear ? rawForm : { ...rawForm, regulationYear }),
    [rawForm, regulationYear],
  )
  /**
   * 지금 입력칸의 목적지 이름 — 늦게 온 좌표 조회 응답이 대조한다 (#1097 ⑴).
   *
   * 렌더 중에 대입하지 않는다 (`#1616`). 읽는 곳은 클릭 핸들러의 `await` 뒤 하나뿐이라
   * **커밋 이후**이고, 렌더 중 `ref.current`에 쓰면 React가 렌더를 버리거나 두 번 돌릴 때
   * 화면에 없는 값이 남는다. 입력 이벤트가 일으킨 렌더의 effect는 그 이벤트 안에서
   * 함께 비워지므로 대조 시점은 그대로다.
   */
  const destinationNameRef = useRef('')
  useEffect(() => {
    destinationNameRef.current = form.destinationPortName.trim()
  }, [form.destinationPortName])
  /*
   * 샘플 항만 (#1005 · `PRD §15.1`). 못 받아도 폼은 그대로 쓴다 — 좌표는 손으로도 넣는다.
   * 「현재 위치」 칸은 **입력 보조**다 — 고르면 위도·경도 칸을 채울 뿐 요청에 따로 싣지 않는다.
   */
  const ports = useSamplePorts()
  const [currentPortText, setCurrentPortText] = useState('')
  /**
   * 지금 입력칸의 현재 위치 이름 — 목적항과 같은 이유로 늦게 온 응답이 대조한다 (#1097 ⑴).
   * 목적항 쪽과 같은 이유로 렌더 중이 아니라 effect에서 대입한다 (`#1616`).
   */
  const currentNameRef = useRef('')
  useEffect(() => {
    currentNameRef.current = currentPortText.trim()
  }, [currentPortText])
  const [errors, setErrors] = useState<FormErrors>({})
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const advancedFilled = countAdvancedFilled(form)
  // 목적항 좌표 찾기 상태 (#768). 실패해도 폼을 막지 않으므로 오류가 아니라 안내다.
  /*
   * 상단바가 기억한 선박이 목록에 없을 때의 안내 (`#1097` ⑵). 삭제된 배를 상단바가 기억하고
   * 있으면 셀렉트는 빈 채로 폼은 그 id로 계산했다 — 보이는 대상과 계산 대상이 달랐다.
   */
  const SHELL_VESSEL_MISSING = '상단바에서 고른 선박이 목록에 없습니다. 다시 선택해 주세요.'
  /*
   * 상단바의 선박이 목록에 없어 **한 척뿐인 목록의 배를 대신 골랐을 때**의 안내 (`#1858`).
   * 오류(`SHELL_VESSEL_MISSING`)로 세우면 곧이어 선택이 유효해지며 지워진다(`#1815`) —
   * 그래서 오류가 아니라 칸의 안내로 두고, **대신 고른 배가 선택돼 있는 동안** 보인다.
   *
   * 표시 문구 — 디자인 담당이 바꿀 수 있다 (`AGENTS §4.6`). 개발 임시안이다.
   */
  const SHELL_VESSEL_REPLACED = '상단바에서 고른 선박이 목록에 없어 목록의 유일한 선박을 골랐습니다.'
  /** 대신 고른 배의 id — 이 배가 선택돼 있는 동안 `SHELL_VESSEL_REPLACED`를 보인다. */
  const [replacedShellVesselFor, setReplacedShellVesselFor] = useState<string | null>(null)
  /*
   * 좌표 찾기 안내 — **두 칸이 따로 갖는다** (#1750). 하나로 두면 현재 위치를 찾고 난
   * 안내가 목적항 칸 아래에 붙는다.
   */
  const [lookup, setLookup] = useState<{ current: LookupState; destination: LookupState }>({
    current: IDLE_LOOKUP,
    destination: IDLE_LOOKUP,
  })
  /*
   * 추정 거리 (#1750).
   *
   * `estimatedRef`는 **직항 거리 칸의 값이 추정으로 채워진 것인지**를 기억한다. 항을 바꾸면
   * 그 숫자는 새 항로의 추정도, 사용자가 넣은 값도 아니므로 비운다 — 사용자가 직접 넣은
   * 값은 건드리지 않는다(`#1256`이 항차 추가 폼에서 같은 결함을 고쳤다).
   *
   * `distanceGeneration`은 늦게 온 응답을 버리는 표다(`#1657`).
   */
  const estimatedRef = useRef(false)
  const distanceGeneration = useRef(0)
  const [estimating, setEstimating] = useState(false)
  const [distanceNotice, setDistanceNotice] = useState('')
  const [state, setState] = useState<LoadState>({ status: 'idle' })

  /**
   * 셸의 선택을 폼에 반영한다 (#535).
   *
   * **선택이 없을 때 임의로 고르지 않는다.** `#511`의 완료 기준이 「선박 미선택
   * 상태에서 에러 대신 입력 UI가 보인다」이므로, 고르지 않은 상태 자체가 이 화면의
   * 정상 상태다. 목록이 한 척뿐일 때만 미리 채운다 — 고를 것이 없기 때문이다.
   */
  const shellVesselId = shell.vesselId
  /** 선박 칸 오류를 마지막으로 지운 선택 — 같은 선택에서 다시 지우지 않는다 (#1815). */
  const clearedForVesselRef = useRef<string | null>(null)
  useEffect(() => {
    if (shellVesselId !== null) {
      // 목록에 없는 선박(삭제됨)이면 선택을 풀고 안내한다 — 그 id로 계산하지 않는다 (#1097 ⑵).
      if (vessels !== null && !vessels.some((option) => option.id === shellVesselId)) {
        /*
         * 한 척뿐이면 선택을 풀지 않고 **그 배를 바로 고른다** (`#1858`). 종전에는 풀었다가
         * 아래 「선택이 풀렸다」 갈래가 같은 배를 미리 채우며 방금 세운 오류를 지워,
         * 기억한 배가 없어졌다는 사실이 전해지지 않고 다른 배가 조용히 골라졌다. 오류 대신
         * 안내를 남긴다 — 선택은 유효하므로 오류로 둘 이유가 없다.
         */
        if (vessels.length === 1) {
          const only = vessels[0].id
          clearedForVesselRef.current = null
          // oxlint-disable-next-line react/set-state-in-effect -- 셸(상단바)의 선택과 폼을 맞추는 동기화 — 대신 고른 배와 안내를 같은 패스에 세운다
          setReplacedShellVesselFor(only)
          // 폼도 같은 패스에서 맞춘다 — 두 척 갈래가 폼을 비우는 것과 대칭이다. 다음 패스까지
          // 폼이 없어진 배의 id를 한 렌더 동안 쥐지 않게 한다(`#1097 ⑵`).
          setForm((prev) => (prev.vesselId === only ? prev : { ...prev, vesselId: only }))
          selectVesselId(only)
          return
        }
        selectVesselId(null)
        clearedForVesselRef.current = null
        setForm((prev) => ({ ...prev, vesselId: '' }))
        setErrors((prev) => ({ ...prev, [FIELD.vesselId]: SHELL_VESSEL_MISSING }))
        return
      }
      setForm((prev) => (prev.vesselId === shellVesselId ? prev : { ...prev, vesselId: shellVesselId }))
      /*
       * 유효한 선박으로 다시 골랐으니 앞서 남은 선박 칸 오류는 이 선택과 무관하다 —
       * 지운다 (#1815). 종전에는 이 셀렉트의 `onChange`도, 상단바의 선택도 오류를
       * 지우지 않아 「목록에 없습니다」가 실제로 고른 선박 위에 그대로 남았다. 지우는
       * 곳을 이 효과로 둔 것은 선박 선택이 **이 화면의 셀렉트(:onChange)와 상단바**
       * 두 경로 모두에서 여기 `shellVesselId`로 모이기 때문이다 — 한쪽만 지우면
       * 다른 경로에서는 여전히 남는다.
       */
      /*
       * 선택이 **실제로 바뀐 때만** 지운다. 이 효과는 `vessels` 참조가 바뀔 때도 다시 도는데,
       * 그때 지우면 사용자가 다시 고르지 않았는데도 서버가 방금 준 선박 칸 오류가 사라진다
       * (PR #1837 리뷰 · 지금은 그 경로가 없다 — `refreshVessels`를 부르는 화면이 이 화면과
       * 함께 열리지 않는다).
       */
      if (clearedForVesselRef.current !== shellVesselId) {
        clearedForVesselRef.current = shellVesselId
        // 대신 고른 배가 아닌 배로 바뀌었으면 그 안내는 이 선택과 무관하다 (`#1858`).
        setReplacedShellVesselFor((prev) => (prev === shellVesselId ? prev : null))
        setErrors((prev) => {
          if (!(FIELD.vesselId in prev)) return prev
          const next = { ...prev }
          delete next[FIELD.vesselId]
          return next
        })
      }
      return
    }
    // 선택이 풀렸다 — 같은 배를 다시 고르는 것도 「바뀐 선택」이다.
    clearedForVesselRef.current = null
    setReplacedShellVesselFor(null)
    if (vessels !== null && vessels.length === 1) selectVesselId(vessels[0].id)
  }, [shellVesselId, vessels, selectVesselId, SHELL_VESSEL_MISSING])

  /*
   * 고른 배의 제원으로 속력·일일 연료·연료 종류를 채운다 (#1538).
   *
   * **배마다 한 번만** 채운다 — 목록이 다시 와서 같은 배의 제원 객체가 새로 만들어져도
   * 다시 덮지 않는다. 그래서 같은 배에서 사용자가 고친 칸은 남고, **배를 바꾸면** 새 배의
   * 제원으로 바뀐다(앞 배의 숫자가 새 배 이름으로 계산되던 것이 이번 결함이다).
   *
   * 제원을 모르는 선택지(`spec === undefined`)는 건드리지 않는다 — `vesselCatalog.ts` 참조.
   */
  const selectedSpec = vessels?.find((option) => option.id === form.vesselId)?.spec
  const specAppliedFor = useRef<string | null>(null)
  useEffect(() => {
    if (form.vesselId === '' || selectedSpec === undefined) return
    if (specAppliedFor.current === form.vesselId) return
    specAppliedFor.current = form.vesselId
    setForm((prev) => applyVesselSpec(prev, selectedSpec))
  }, [form.vesselId, selectedSpec])
  const dailyFocHint =
    selectedSpec === undefined
      ? '선박 정보에 이 값이 없어도 여기 입력한 값으로 계산합니다.'
      : selectedSpec.referenceDailyFocTon === null
        ? '선박 제원에 이 값이 없습니다 — 직접 입력하면 이 비교에 씁니다.'
        : '선박 제원 값입니다. 고치면 이 비교에만 씁니다.'

  // 항만 이름이 바뀌면 앞 조회의 안내는 다른 항만 것이다 — 지운다 (#1097 ⑴).
  const destinationName = form.destinationPortName.trim()
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- 항만 이름이 바뀌면 앞 조회의 안내를 지우는 리셋 — 이름은 입력과 항만 선택 두 경로로 바뀌어 여기서 모은다
    setLookup((prev) => ({ ...prev, destination: IDLE_LOOKUP }))
  }, [destinationName])
  const currentName = currentPortText.trim()
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- 위와 같은 리셋 — 현재 위치 칸
    setLookup((prev) => ({ ...prev, current: IDLE_LOOKUP }))
  }, [currentName])

  /**
   * 추정으로 채운 거리를 버린다 (#1256 · #1657).
   *
   * 항이나 좌표가 바뀌면 그 숫자는 **그때의 두 항에서 나온 값**이라 더 이상 이 항로의
   * 추정이 아니다. 사용자가 직접 넣은 값(`estimatedRef.current === false`)은 남긴다.
   * 진행 중이던 조회의 결과도 함께 버린다.
   */
  const dropEstimatedDistance = () => {
    distanceGeneration.current += 1
    setDistanceNotice('')
    if (!estimatedRef.current) return
    estimatedRef.current = false
    setForm((prev) => ({ ...prev, baseDistanceNm: '' }))
  }

  const currentCoord = toCoord(form.currentLat, form.currentLon)
  const destinationCoord = toCoord(form.destinationLat, form.destinationLon)
  const canEstimate = currentCoord !== null && destinationCoord !== null

  /** 「추정 거리 넣기」 — 누를 때만 부른다. 실패해도 폼은 그대로 쓴다(`PRD §16.2`). */
  const estimateDistance = async () => {
    if (currentCoord === null || destinationCoord === null || estimating) return
    distanceGeneration.current += 1
    const ticket = distanceGeneration.current
    setEstimating(true)
    setDistanceNotice('')
    try {
      const nm = await fetchGreatCircleNm(currentCoord, destinationCoord)
      // 기다리는 동안 항이나 좌표가 바뀌었으면 이 거리는 다른 항로의 것이다 (#1657).
      if (ticket !== distanceGeneration.current) return
      estimatedRef.current = true
      setForm((prev) => ({ ...prev, baseDistanceNm: distanceInput(nm) }))
      setDistanceNotice(ESTIMATED_DISTANCE_HINT)
    } catch (error) {
      if (ticket !== distanceGeneration.current) return
      setDistanceNotice(error instanceof Error ? error.message : GREAT_CIRCLE_FAILED)
    } finally {
      setEstimating(false)
    }
  }

  /**
   * 목록 밖 항만의 좌표를 찾는다 (#768). 두 칸이 같은 절차를 쓴다 (#1750).
   *
   * **입력 중에 부르지 않는다** — 공개 Nominatim 사용 정책이 자동완성을 금지한다.
   */
  const findCoordinates = async (side: 'current' | 'destination') => {
    const nameRef = side === 'current' ? currentNameRef : destinationNameRef
    const requested = nameRef.current
    setLookup((prev) => ({ ...prev, [side]: { status: 'loading', message: '' } }))
    const result = await lookupPort(requested)
    // 조회하는 동안 이름이 바뀌었으면 이 좌표는 다른 항만 것이다 — 버린다 (#1097 ⑴).
    if (nameRef.current !== requested) return
    if (result.ok) {
      setForm((current) =>
        side === 'current'
          ? { ...current, currentLat: String(result.port.lat), currentLon: String(result.port.lon) }
          : {
              ...current,
              destinationLat: String(result.port.lat),
              destinationLon: String(result.port.lon),
            },
      )
      // 좌표가 바뀌었으니 앞서 채운 추정 거리는 이 항로의 것이 아니다.
      dropEstimatedDistance()
      setLookup((prev) => ({
        ...prev,
        [side]: { status: 'done', message: LOOKUP_SOURCE_NOTICE[result.port.source] ?? '' },
      }))
      return
    }
    setLookup((prev) => ({ ...prev, [side]: { status: 'done', message: result.message } }))
  }

  /*
   * 연도를 고를 수 없으면 비교하지 않는다 (`#1093` ⑷).
   *
   * 목록이 실패·빈 목록이면 아래 규제연도 칸은 셀렉트가 아니라 주석 한 줄이 된다 —
   * 사용자가 연도를 **고를 수 없다.** 그런데 `initialFormState()`가 `'2026'`을
   * 들고 있어 검증을 통과했고, **고른 적 없는 2026년 기준 결과**가 나왔다. 같은
   * 파일이 선박 축에는 「기본값을 넣지 않는다」를 이미 적어 두었다(`requestRules.ts`).
   *
   * **불러오는 중에도 막는다** — 그때도 고를 연도가 없다. 막지 않으면 목록이 오기
   * 전에 누른 비교가 빈 연도로 검증에 걸려, 사용자는 화면에 보이지도 않는 칸에 대한
   * 오류를 본다.
   *
   * 선박을 고르지 않은 경우는 **막지 않는다** — 그때 버튼을 잠그면 「선박을 선택해
   * 주세요」를 띄울 길이 없어져 화면이 아무 반응도 하지 않는다.
   *
   * ⚠️ **`form.regulationYear === ''`도 막는다.** 종전에는 목록이 도착한 커밋과 기본값을
   * 채우는 effect 사이에 한 칸이 열려 있었다. 그 칸에서 `<select>`는 **상태가 비어
   * 있어도 첫 옵션(2026)을 보여 준다** — 브라우저가 목록에 없는 값을 첫 항목으로
   * 떨어뜨리기 때문이다(`AnnualSimulation.test.tsx`의 `runOnce` 주석이 같은 함정을
   * 적고 있다). 화면은 「2026이 골라졌다」로 보이는데 요청에 실릴 값은 없는, 이
   * 이슈가 고치려는 바로 그 어긋남이다. 기본값이 렌더 중 파생으로 바뀌어(`#1616`) 그
   * 칸은 닫혔지만, 「빈 연도로는 비교하지 않는다」는 조건 자체는 그대로 둔다.
   */
  const yearUnavailable =
    form.vesselId !== '' &&
    (yearsLoading || yearsFailed || years.length === 0 || form.regulationYear === '')

  const runComparison = () => {
    /*
     * 연도를 고를 수 없으면 여기서 멈춘다 (`#1093` ⑷). 버튼도 비활성이지만
     * 폼은 Enter로도 제출되므로 두 겹으로 막는다. **검증 오류를 세우지 않는다** —
     * 규제연도 칸이 이미 원인(목록 실패 · 등재 없음)을 말하고 있고, 그 위에
     * 「4자리 숫자로 입력해 주세요」를 얹으면 고칠 수 없는 것을 고치라고 말한다.
     */
    if (yearUnavailable) return
    const found = validateForm(form, fuels)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      if (hasAdvancedError(found)) setAdvancedOpen(true)
      return
    }
    setErrors({})
    /*
     * 스냅샷은 **응답이 온 뒤가 아니라 지금** 뜬다 (#875). 계산이 도는 동안에도
     * 상단바에서 배를 바꿀 수 있으므로, 응답 시점에 읽으면 사용자가 「비교하기」를
     * 누를 때 화면에 있던 이름이 아니라 그 사이에 바뀐 이름이 박힌다.
     */
    const snapshot: ResultSnapshot = {
      vesselName: vessels?.find((option) => option.id === form.vesselId)?.displayName ?? null,
      inputs: form,
    }
    setState({ status: 'loading' })
    provider.compare(toRequest(form, fuels)).then(
      (response) => {
        // #1533 — 챗봇이 「이 결과」를 저장된 실행에서 읽게 한다.
        publishScreenResult(response.calculation_run_id)
        setState({ status: 'success', response, snapshot })
        onDisclaimer?.(response.disclaimer)
      },
      (error: unknown) => {
        // 서버가 칸을 짚어 주면(`details[0].field`) 그 입력칸에 붙인다 (#1097 ⑶ · `#936`).
        // 종전에는 `ScenarioComparisonError.field`를 담아 던지고 아무도 읽지 않았다.
        if (
          error instanceof ScenarioComparisonError &&
          typeof error.field === 'string' &&
          (Object.values(FIELD) as string[]).includes(error.field)
        ) {
          const field = error.field
          setErrors((prev) => ({ ...prev, [field]: error.message }))
          if (hasAdvancedError({ [field]: error.message })) setAdvancedOpen(true)
        }
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : '비교에 실패했습니다.',
        })
      },
    )
  }

  /*
   * 「등록된 배가 없다」는 **조회에 성공했을 때만** 할 수 있는 말이다 (`#1093` ⑵).
   *
   * 종전 조건(`vessels !== null && length === 0`)은 `vesselsState === 'failed'`에서도
   * 참이었다 — 실패하면 셸이 `vessels`를 `[]`로 두기 때문이다. 그 결과 위의
   * `catalogError`(「선박 목록을 불러오지 못했습니다」)와 `NO_VESSEL_MESSAGE`(「등록된
   * 선박이 없어 비교할 대상이 없습니다. 선박을 먼저 등록해 주세요」)가 **동시에**
   * 떴고, 뒤쪽이 행동을 지시하므로 사용자는 **등록할 필요가 없는데 등록 화면으로
   * 갔다.**
   */
  const noVessel = vesselsState === 'ready' && vessels !== null && vessels.length === 0

  const conditionForm = (
    <form
      className="scenario-comparison__form"
      onSubmit={(event) => {
        event.preventDefault()
        runComparison()
      }}
    >
      <h2 className="card__title scenario-comparison__form-title">
        비교 조건
        {showsLabelEn ? (
          <span className="scenario-comparison__form-title-en" lang="en">
            {' '}
            Comparison Input
          </span>
        ) : null}
      </h2>
      {catalogError !== null && (
        <p className="scenario-comparison__error-message" role="alert">
          {catalogError}
        </p>
      )}
      {noVessel && (
        <p id="sc-no-vessel" className="scenario-comparison__error-message" role="status">
          {NO_VESSEL_MESSAGE}
        </p>
      )}

      {/*
        입력을 성격으로 셋으로 가른다 (`#1417`).

        종전에는 13칸이 `<fieldset>` 없이 한 평면에 놓여, **비워도 되는 칸과 비우면 계산이
        안 되는 칸이 같은 무게**였다. 소제목 「선택 입력」 한 줄이 경계를 긋고 있었지만
        그 아래 위치 칸까지 선택으로 묶여, 무엇이 기본이고 무엇이 조정인지 읽히지 않았다.

        ⑴ 필수 — 없으면 계산이 안 된다
        ⑵ 위치 — 표기와 좌표 채우기. 목적항은 `#1454`로 선택 필드가 됐다
        ⑶ 고급 — **비워 두면 서버 기본**이다. 접어 둔다

        고급 칸에 값을 **미리 채우지 않는다** — 빈 칸이 서버 기본이다(`requestRules.ts`).
      */}
      <fieldset className="scenario-comparison__group">
        <legend className="scenario-comparison__form-subtitle">필수 입력</legend>
        <Field
          id="sc-vesselId"
          label="선박"
          error={errors[FIELD.vesselId]}
          hint={
            replacedShellVesselFor !== null && form.vesselId === replacedShellVesselFor
              ? SHELL_VESSEL_REPLACED
              : undefined
          }
        >
          {(control) => (
            <select
              {...control}
              className="scenario-comparison__control"
              value={form.vesselId}
              onChange={(e) => selectVesselId(e.target.value || null)}
              disabled={vesselsState !== 'ready' || noVessel}
            >
              {/* 실패를 「선택」으로 말하지 않는다 — 고를 것이 없다 (`#1093` ⑵). */}
              <option value="">
                {vesselsState === 'loading'
                  ? '선박 목록을 불러오는 중…'
                  : vesselsState === 'failed'
                    ? '선박 목록을 불러오지 못했습니다'
                    : '선택'}
              </option>
              {(vessels ?? []).map((option) => (
                <option key={option.id} value={option.id}>
                  {option.displayName}
                </option>
              ))}
            </select>
          )}
        </Field>

        {/*
          * 규제연도 — 다른 두 화면과 같은 규칙 (`#632`).
          * 로딩·실패를 **빈 선택지와 구분해** 보인다. 셋을 한 문구로 뭉치면
          * 「목록이 아직 안 왔다」와 「등록된 해가 없다」를 사용자가 가를 수 없다.
          *
          * ⚠️ 이 칸은 **컨트롤이 없을 수도 있다.** 그래서 `Field`의 자식 함수가
          * 조건 전체를 돌려준다 — `control`(=`id`·`aria-*`)은 `<select>`가 실제로
          * 그려지는 가지에서만 쓴다 (`#936`).
          */}
        <Field id="sc-regulationYear" label="규제연도" error={errors[FIELD.regulationYear]}>
          {(control) =>
            yearsLoading ? (
              <span className="scenario-comparison__field-note">규제연도 목록을 불러오는 중…</span>
            ) : yearsFailed ? (
              <span className="scenario-comparison__field-note">규제연도 목록을 불러오지 못했습니다</span>
            ) : years.length > 0 ? (
              <select
                {...control}
                className="scenario-comparison__control"
                value={form.regulationYear}
                onChange={(e) => setForm((prev) => ({ ...prev, regulationYear: e.target.value }))}
              >
                {years.map((year) => (
                  <option key={year} value={String(year)}>
                    {year}
                  </option>
                ))}
              </select>
            ) : !form.vesselId ? (
              /*
               * ⚠️ **「선박을 아직 안 골랐다」와 「그 선박에 연도가 없다」는 다르다** (#829 계열).
               *
               * `useYearOptions`는 선박이 없으면 조회하지 않고 **빈 목록**을 돌려준다. 종전에는
               * 그때도 「등록된 규제연도가 없습니다」가 떴는데, **사실이 아니다** — 연도는
               * 등재되어 있고 선박을 고르지 않았을 뿐이다. 화면에 처음 들어온 사용자는 그것을
               * **데이터가 없다**로 읽고 선박을 고를 생각을 못 한다(2026-09-13 실측 5/5 재현).
               *
               * 보고서 화면(`ReportsView`)이 이미 `vesselId &&`로 같은 구분을 하고 있다 —
               * 그 형태에 맞춘다.
               */
              <span className="scenario-comparison__field-note">선박을 먼저 선택해 주세요</span>
            ) : (
              <span className="scenario-comparison__field-note">등록된 규제연도가 없습니다</span>
            )
          }
        </Field>

        <Field
          id="sc-baseDistanceNm"
          label={`직항 거리 (${DISPLAY_UNITS.distance})`}
          error={errors[FIELD.baseDistanceNm]}
        >
          {(control) => (
            <>
              <input
                {...control}
                className="scenario-comparison__control"
                inputMode="decimal"
                value={form.baseDistanceNm}
                onChange={(e) => {
                  /*
                   * 손으로 고친 값은 더 이상 추정이 아니다 (#1750). 표시를 떼지 않으면
                   * 사용자가 넣은 숫자에 「좌표 기반 추정 거리」가 붙은 채로 남는다.
                   */
                  estimatedRef.current = false
                  setDistanceNotice('')
                  setForm((prev) => ({ ...prev, baseDistanceNm: e.target.value }))
                }}
              />
              {/*
                항구를 고르면 거리를 **손으로 넣지 않아도 된다** (#1750). 누를 때만 부른다 —
                입력 중 자동 조회는 공개 Nominatim 사용 정책 위반이다(#768).

                좌표가 없으면 비활성하고 **그 사유를 적는다**(`§14` 비활성 사유).
              */}
              <button
                type="button"
                className="scenario-comparison__lookup"
                onClick={estimateDistance}
                disabled={!canEstimate || estimating}
                // §14 — 잠긴 사유를 낭독에도 잇는다 (#1170 ⑵).
                aria-describedby={canEstimate ? undefined : 'sc-estimate-blocked'}
              >
                {estimating ? '추정하는 중…' : '추정 거리 넣기'}
              </button>
              {!canEstimate && (
                <span id="sc-estimate-blocked" className="scenario-comparison__field-hint">
                  현재 위치와 목적항의 좌표가 모두 있어야 추정할 수 있습니다.
                </span>
              )}
              {distanceNotice !== '' && (
                <span className="scenario-comparison__field-hint" role="status">
                  {distanceNotice}
                </span>
              )}
              {/* 비우면 좌표로 계산한다는 것을 **누르기 전에** 알린다 (#1005 · `PRD §15.2`).
                  조건부라 `Field`의 `hint`가 아니라 여기 둔다 — `role="status"`로 떠야 한다. */}
              {usesCoordinateDistance(form) && (
                <span className="scenario-comparison__field-hint" role="status">
                  비워 두면 현재 위치와 목적항 좌표로 계산합니다(좌표 기반 추정 거리).
                </span>
              )}
            </>
          )}
        </Field>

        <Field
          id="sc-baseSpeedKn"
          label={`현재 속력 (${DISPLAY_UNITS.speed})`}
          error={errors[FIELD.baseSpeedKn]}
        >
          {(control) => (
            <input
              {...control}
              className="scenario-comparison__control"
              inputMode="decimal"
              value={form.baseSpeedKn}
              onChange={(e) => setForm((prev) => ({ ...prev, baseSpeedKn: e.target.value }))}
            />
          )}
        </Field>

        {/* 단위는 `§4.2` 「일일 연료소모량」 행이 소유한다 — 질량이 아니라
            질량유량이다(`DB_SCHEMA`의 `ton/day`). 종전에 화면마다 `(t)`와
            `t/일`로 갈려 있던 것은 그 행이 없어서였다 (#592 → `#858`).

            `PRD §11.4` 우선순위 ⑴이 이 칸이다. 선박에 `reference_daily_foc_ton`이
            없어도 여기 값을 넣으면 계산된다 — 데모 선박 4척이 모두 그 상태다. */}
        <Field
          id="sc-baseDailyFocTon"
          label={`기준 일일 연료소모량 (${DISPLAY_UNIT_DAILY_FUEL})`}
          hint={dailyFocHint}
          error={errors[FIELD.baseDailyFocTon]}
        >
          {(control) => (
            <input
              {...control}
              className="scenario-comparison__control"
              inputMode="decimal"
              value={form.baseDailyFocTon}
              onChange={(e) => setForm((prev) => ({ ...prev, baseDailyFocTon: e.target.value }))}
            />
          )}
        </Field>

        <Field id="sc-fuelType" label="연료 종류" error={errors[FIELD.fuelType]}>
          {(control) => (
            <select
              {...control}
              className="scenario-comparison__control"
              value={form.fuelType}
              onChange={(e) => setForm((prev) => ({ ...prev, fuelType: e.target.value }))}
              disabled={fuelsLoading || fuelsFailed}
            >
              {/* 로딩·실패를 「선택」과 구분해 보인다 — 빈 목록과 못 불러온 것은 다른 상태다 (#542) */}
              <option value="">
                {fuelsLoading
                  ? '연료 목록을 불러오는 중…'
                  : fuelsFailed
                    ? '연료 목록을 불러오지 못했습니다'
                    : '선택'}
              </option>
              {fuels.map((fuel) => (
                <option key={fuel.code} value={fuel.code}>
                  {fuelTypeOptionText(fuel.code)}
                </option>
              ))}
            </select>
          )}
        </Field>
      </fieldset>

      <fieldset className="scenario-comparison__group">
        <legend className="scenario-comparison__form-subtitle">위치</legend>
        {/* 샘플 항만 선택지 (#1005) — 현재 위치·목적항 두 칸이 같이 쓴다. */}
        <datalist id="sc-ports">
          {ports.map((port) => (
            <option key={port.locode} value={port.name} label={portOptionLabel(port)} />
          ))}
        </datalist>

        <Field id="sc-currentPort" label="현재 위치 (항만에서 고르기)">
          {(control) => (
            <>
              <input
                {...control}
                className="scenario-comparison__control"
                list="sc-ports"
                value={currentPortText}
                onChange={(e) => {
                  setCurrentPortText(e.target.value)
                  const match = matchSamplePort(ports, e.target.value)
                  if (match) {
                    setForm((prev) => ({
                      ...prev,
                      currentLat: String(match.lat),
                      currentLon: String(match.lon),
                    }))
                  }
                  // 출발점이 바뀌면 앞서 채운 추정 거리는 이 항로의 것이 아니다 (#1256).
                  dropEstimatedDistance()
                }}
                placeholder="예: BUSAN — 비워 두고 「고급 설정」에서 좌표를 넣어도 됩니다"
              />
              {/*
                목록 밖 항만도 **누르면** 좌표를 찾는다 (#768 · #1750). 종전에는 목적항에만
                있어, 출발항이 목록 밖이면 두 끝이 생기지 않아 거리 추정이 막혔다.
              */}
              {currentName.length >= 2 && form.currentLat === '' && (
                <button
                  type="button"
                  className="scenario-comparison__lookup"
                  onClick={() => findCoordinates('current')}
                  disabled={lookup.current.status === 'loading'}
                >
                  {lookup.current.status === 'loading' ? '찾는 중…' : '좌표 찾기'}
                </button>
              )}
              {lookup.current.message !== '' && (
                <span className="scenario-comparison__field-hint">{lookup.current.message}</span>
              )}
            </>
          )}
        </Field>
        <Field id="sc-destinationPortName" label="목적항">
          {(control) => (
            <>
              <input
                {...control}
                className="scenario-comparison__control"
                list="sc-ports"
                value={form.destinationPortName}
                onChange={(e) => {
                  // 샘플 항만과 **정확히** 같을 때만 좌표를 붙인다 — 추측하지 않는다(#1005).
                  const match = matchSamplePort(ports, e.target.value)
                  setForm((prev) => ({
                    ...prev,
                    destinationPortName: match ? match.name : e.target.value,
                    destinationLat: match ? String(match.lat) : '',
                    destinationLon: match ? String(match.lon) : '',
                  }))
                  // 도착점이 바뀌면 앞서 채운 추정 거리는 이 항로의 것이 아니다 (#1256).
                  dropEstimatedDistance()
                }}
              />
              {form.destinationLat !== '' && (
                <span className="scenario-comparison__field-hint">샘플 항만 — 좌표가 함께 쓰입니다.</span>
              )}
              {/*
                목록 밖 항만은 **누르면** 좌표를 찾는다 (#768). 입력 중에 부르지 않는 이유는
                공개 Nominatim 사용 정책이 자동완성을 금지하기 때문이다 — 타이핑에 붙이면
                곧바로 위반이다. 실패해도 폼은 그대로 쓸 수 있다(`PRD §16.2`).
              */}
              {destinationName.length >= 2 && form.destinationLat === '' && (
                <button
                  type="button"
                  className="scenario-comparison__lookup"
                  onClick={() => findCoordinates('destination')}
                  disabled={lookup.destination.status === 'loading'}
                >
                  {lookup.destination.status === 'loading' ? '찾는 중…' : '좌표 찾기'}
                </button>
              )}
              {lookup.destination.message !== '' && (
                <span className="scenario-comparison__field-hint">
                  {lookup.destination.message}
                </span>
              )}
            </>
          )}
        </Field>
      </fieldset>

      {/*
        고급 설정 (`#1417`). 요약에 **기본에서 벗어난 칸의 수**를 적는다 — 안에 값이
        들어 있는데 겉에서 안 보이면 사용자는 기본 규칙으로 계산했다고 믿는다(`#1418`과
        같은 판단). 고급 칸에 오류가 나면 **스스로 펼친다** — 접힌 채로 두면 오류가
        보이지 않는다.
      */}
      <details
        className="scenario-comparison__advanced"
        open={advancedOpen}
        onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
      >
        <summary>
          고급 설정
          <span className="scenario-comparison__field-hint">
            {advancedFilled === 0 ? ' · 기본 규칙으로 계산' : ` · ${advancedFilled}개 입력함`}
          </span>
        </summary>
        {/*
          칸은 **이 div가** 그리드로 편다 (`#1417` 화면 확인). `<details>` 자체에
          `display: grid`를 걸면 Chromium이 안쪽 배치에 쓰지 않아 칸이 한 줄로 쌓였다 —
          위 두 묶음은 옆으로 펼쳐지는데 고급만 세로로 길어졌다.
        */}
        <div className="scenario-comparison__advanced-body">
          <p className="scenario-comparison__field-hint">
            비워 두면 기본 규칙(우회 +5% · 감속 −1kn)으로 계산합니다.
          </p>
          <Field
            id="sc-detourDistanceNm"
            label={`우회 거리 (${DISPLAY_UNITS.distance})`}
            error={errors[FIELD.detourDistanceNm]}
          >
            {(control) => (
              <input
                {...control}
                className="scenario-comparison__control"
                inputMode="decimal"
                value={form.detourDistanceNm}
                onChange={(e) => setForm((prev) => ({ ...prev, detourDistanceNm: e.target.value }))}
                placeholder="직항 × 1.05"
              />
            )}
          </Field>

          {/*
            우회 경유지 (`#1300` E-6 ⓓ · `PRD §11.3` · `UIFLOW 2-2`). 샘플 항만에서 고르면 좌표가
            붙고, 그때 서버가 우회 거리를 「현재 위치 → 경유지 → 목적항」 대권거리의 합으로 내며
            지도가 우회 선을 따로 그린다. 목적항과 같은 규칙 — **정확히 같은 이름일 때만** 좌표를
            붙인다. 우회 거리 칸을 채우면 그쪽이 우선이다(`API_SPEC §5.1`).
          */}
          <Field
            id="sc-detourWaypoint"
            label="우회 경유지 (항만에서 고르기)"
            hint="고르면 우회 거리는 경유지를 지나는 대권거리의 합이 되고, 지도에 우회 선이 따로 그려집니다."
            error={
              // 서버가 짚는 칸은 `detour_waypoint_lat`/`_lon`이다 — 한 입력창이 셋을 받는다
              // (#1097 ⑶ 「서버가 짚은 칸에 붙인다」).
              errors[FIELD.detourWaypointName] ??
              errors[FIELD.detourWaypointLat] ??
              errors[FIELD.detourWaypointLon]
            }
          >
            {(control) => (
              <>
                <input
                  {...control}
                  className="scenario-comparison__control"
                  list="sc-ports"
                  value={form.detourWaypointName}
                  onChange={(e) => {
                    const match = matchSamplePort(ports, e.target.value)
                    setForm((prev) => ({
                      ...prev,
                      detourWaypointName: match ? match.name : e.target.value,
                      detourWaypointLat: match ? String(match.lat) : '',
                      detourWaypointLon: match ? String(match.lon) : '',
                    }))
                  }}
                  placeholder="예: SINGAPORE — 비워 두면 직항 × 1.05"
                />
                {form.detourWaypointLat !== '' && (
                  <span className="scenario-comparison__field-hint">
                    샘플 항만 — 좌표가 함께 쓰입니다.
                  </span>
                )}
                {form.detourWaypointName.trim() !== '' && form.detourWaypointLat === '' && (
                  <span className="scenario-comparison__field-hint" role="status">
                    샘플 항만 목록에 없는 이름입니다 — 좌표가 없어 우회 거리는 기본 규칙으로 계산합니다.
                  </span>
                )}
              </>
            )}
          </Field>

          {/* `PRD §9.1` VAL-009 — floor가 1.0kn이라는 사실을 넣기 전에 알린다.
              도달했을 때의 경고(`SLOW_SPEED_FLOOR`)는 서버가 결과에 붙인다. */}
          <Field
            id="sc-slowSpeedKn"
            label={`감속 속력 (${DISPLAY_UNITS.speed})`}
            hint={`최소 ${MIN_SPEED_KN}kn까지 내릴 수 있습니다.`}
            error={errors[FIELD.slowSpeedKn]}
          >
            {(control) => (
              <input
                {...control}
                className="scenario-comparison__control"
                inputMode="decimal"
                value={form.slowSpeedKn}
                onChange={(e) => setForm((prev) => ({ ...prev, slowSpeedKn: e.target.value }))}
                placeholder={`현재 속력 − 1 (최소 ${MIN_SPEED_KN})`}
              />
            )}
          </Field>

          <Field id="sc-weatherModel" label="기상 보정 모델" error={errors[FIELD.weatherModel]}>
            {(control) => (
              <>
                <select
                  {...control}
                  className="scenario-comparison__control"
                  value={form.weatherModel}
                  onChange={(e) => setForm((prev) => ({ ...prev, weatherModel: e.target.value }))}
                >
                  {WEATHER_MODELS.map((model) => (
                    <option key={model.code} value={model.code}>
                      {model.label}
                    </option>
                  ))}
                </select>
                {/*
                  좌표 없이 모델만 고르면 **보정이 통째로 건너뛴다.** 결과에 붙는
                  `WEATHER_NONE_FALLBACK` 배너로는 계산이 끝난 뒤에야 알 수 있어,
                  누르기 전에 같은 사실을 알린다 (`requestRules.ts`의 측정치 참조).
                */}
                {weatherNeedsCoordinates(form) && (
                  <span className="scenario-comparison__field-hint" role="status">
                    현재 좌표를 입력해야 기상 보정이 적용됩니다. 비워 두면 보정 없이 계산합니다.
                  </span>
                )}
              </>
            )}
          </Field>
          <Field id="sc-currentLat" label="현재 위도 (°)" error={errors[FIELD.currentLat]}>
            {(control) => (
              <input
                {...control}
                className="scenario-comparison__control"
                inputMode="decimal"
                value={form.currentLat}
                onChange={(e) => {
                  // 좌표를 손으로 고쳐도 추정 거리는 앞 좌표의 것이다 — 항을 바꿀 때와 같이
                  // 버린다 (#1777). 손으로 넣은 거리는 `dropEstimatedDistance`가 남긴다.
                  dropEstimatedDistance()
                  setForm((prev) => ({ ...prev, currentLat: e.target.value }))
                }}
                placeholder="-90 ~ 90"
              />
            )}
          </Field>

          {/*
            문구에 **다른 칸의 이름을 넣지 않는다.** 종전에는 힌트가 `<label>` 안에 있어
            접근성 이름에 섞였고, 같은 낱말이 두 칸에 들어가면 라벨로 칸을 특정할 수
            없게 됐다 — 실제로 기존 검사의 `getByLabelText(/직항 거리/)`가 중복 일치로
            깨졌다. `Field`로 옮긴 뒤 힌트는 `aria-describedby`로 빠져 이름에 섞이지
            않지만, **읽어 주는 순서에는 그대로 들어간다.** 규칙은 유지한다 (`#936`).
          */}
          <Field
            id="sc-currentLon"
            label="현재 경도 (°)"
            hint="기상 보정에 쓰고, 항해거리를 비웠을 때는 대권거리의 출발점이 됩니다."
            error={errors[FIELD.currentLon]}
          >
            {(control) => (
              <input
                {...control}
                className="scenario-comparison__control"
                inputMode="decimal"
                value={form.currentLon}
                onChange={(e) => {
                  // 좌표를 손으로 고쳐도 추정 거리는 앞 좌표의 것이다 — 항을 바꿀 때와 같이
                  // 버린다 (#1777). 손으로 넣은 거리는 `dropEstimatedDistance`가 남긴다.
                  dropEstimatedDistance()
                  setForm((prev) => ({ ...prev, currentLon: e.target.value }))
                }}
                placeholder="-180 ~ 180"
              />
            )}
          </Field>
        </div>
      </details>

      <div className="scenario-comparison__form-actions">
        <button
          type="submit"
          className="scenario-comparison__submit"
          disabled={state.status === 'loading' || noVessel || yearUnavailable}
          /*
           * 비활성의 사유를 낭독에도 닿게 한다 (`§14` · `#1170` ⑵). `yearUnavailable`은
           * **규제연도 칸 자신이 원인을 말하고** `Field`가 그 문구를 그 칸에 배선해
           * 두었으므로 여기서 다시 잇지 않는다 — 두 번 읽히게 된다.
           */
          aria-describedby={noVessel ? 'sc-no-vessel' : undefined}
        >
          {state.status === 'loading' ? '계산 중…' : '비교하기'}
        </button>
      </div>
    </form>
  )

  if (state.status !== 'success') {
    return (
      <section className="scenario-comparison">
        {conditionForm}
        {/*
          결과가 없을 때도 오른쪽 단을 비워 두지 않는다. 빈 칸으로 두면 화면이
          고장 난 것처럼 보이고, 계산 후에 폼이 옆으로 밀리는 것처럼도 읽힌다.
          `2-1 CII 예측`의 `VoyageCiiResult`가 idle에 자리표시자를 두는 것과 같다.
        */}
        <div className="scenario-comparison__results">
          {state.status === 'idle' && (
            <p className="scenario-comparison__placeholder">
              비교 조건을 입력하고 <strong>비교하기</strong>를 누르면 결과가 표시됩니다.
            </p>
          )}
          {state.status === 'loading' && (
            <p className="scenario-comparison__placeholder" aria-live="polite">
              시나리오를 계산하는 중입니다…
            </p>
          )}
          {state.status === 'error' && (
            // 여기는 조건이 폼에 그대로 남아 있어 **다시 시도할 수 있는** 실패다.
            <ErrorState
              level="region"
              action="비교"
              message={state.message}
              onRetry={runComparison}
            />
          )}
        </div>
      </section>
    )
  }

  const { response, snapshot } = state
  const unit = ciiUnit(response.transport_capacity_basis)
  const summary = lowestSummary(response.scenarios)
  const shownWarnings = displayWarnings(response.warnings)

  /*
   * 제목의 선박명 (#821 · #875).
   *
   * **서버 응답에는 이 값이 없다.** 종전에는 provider가 `vessel_display_name: ''`을
   * 응답 타입에 채워 넣었고, 제목이 `` · 2026년 기준 · …``처럼 **구분점만 남은**
   * 상태로 배포됐다. 그 필드가 응답 타입에 있던 것이 「서버가 준다」는 오해를
   * 만들었으므로 타입에서 없앴다.
   *
   * 여기서 `GET /vessels/{id}`를 부르지 않는다 — **셸이 이미 목록을 들고 있고**,
   * 위 선박 드롭다운이 같은 `displayName`을 렌더한다. 사용자가 고른 그 이름을
   * 그대로 쓰는 것이 서버에서 다시 조회해 오는 것보다 화면과 일치한다.
   *
   * 목록이 아직 안 왔거나 그 사이 선박이 지워졌으면 `null`이라 이름 칸을 통째로
   * 뺀다 — 빈 문자열을 두면 구분점만 남아 **레이아웃이 깨진 것처럼 보인다.**
   *
   * `#875`가 여기서 **`form`이 아니라 스냅샷을 읽게** 바꿨다. 종전에는 결과를 본 뒤
   * 상단바에서 배를 바꾸면 옛 숫자 위에 새 이름이 붙었다.
   */
  const { vesselName } = snapshot

  /*
   * 결과가 낡았는가 (#875 · 선례 `#727`).
   *
   * 제목을 고정하면 이번에는 **제목·숫자와 폼이 어긋난 상태**가 화면에 남는다.
   * 어긋남 자체는 정상이다(결과를 보며 조건을 고치는 것이 이 화면의 사용법이다) —
   * 다만 **그 사실을 화면이 말해야** 사용자가 옛 숫자를 현재 조건의 답으로 읽지
   * 않는다. 기능①이 같은 이유로 같은 표시를 갖고 있다.
   *
   * 비교는 폼 전체를 본다 — 선박·연도만 보면 거리나 연료만 고쳤을 때 안내가
   * 빠진다. 판정은 `sameInputs`가 하고, 그 함수는 키를 열거하지 않아 폼에 칸이
   * 늘어도 자동으로 포함된다.
   */
  const stale = !sameInputs(snapshot.inputs, form)

  const nameOf = (type: string | null) =>
    response.scenarios.find((s) => s.scenario_type === type)?.scenario_name ?? '—'

  /*
   * 동률이면 **전부 적고 동률임을 밝힌다** (`PRD §11.2`, `#799`).
   *
   * 같은 값 중 하나만 지목하는 것은 그 자체가 추천이다 — 사용자는 두 시나리오의
   * CII가 표에 같게 찍혀 있는데 한쪽만 「가장 낮은」으로 불리는 것을 보고 그쪽이
   * 낫다고 읽는다. 「(동률)」을 붙이는 이유는 이름 두 개만으로는 **둘 다 최소인지**
   * **둘을 함께 추천하는지** 읽는 사람이 가릴 수 없기 때문이다.
   */
  const namesOf = (types: readonly string[]) =>
    types.length === 0
      ? '—'
      : types.length === 1
        ? nameOf(types[0])
        : `${types.map(nameOf).join(' · ')} (동률)`

  return (
    <section className="scenario-comparison">
      {/* 결과를 본 뒤 조건을 바꿔 다시 비교할 수 있어야 한다 — 폼을 남긴다. */}
      {conditionForm}
      {/*
        결과 전체를 한 겹으로 묶는다. 묶지 않으면 12컬럼 자동 배치가 `__header`만
        폼 옆에 올리고 `__notice`부터는 아래 줄로 흘려보낸다 — 결과가 두 단에
        걸쳐 쪼개진다.
      */}
      <div
        className={`scenario-comparison__results${stale ? ' scenario-comparison__results--stale' : ''}`}
      >
        <header className="scenario-comparison__header">
          {/*
            결과 제목은 다른 화면의 결과 제목(`VoyageCiiResult`)·이 화면의 폼 제목과 같은
            `card__title`이다 (#1303). 종전에는 규칙 없는 이름표만 있어 전역 `h2`(20px · 700)로
            그려졌고, 곁의 영문 병기(16px)와 폼 제목(`card__title` 16px · 600)보다 한 단 컸다.
          */}
          <h2 className="card__title scenario-comparison__title">
            시나리오 비교
            {showsLabelEn ? (
              <span className="scenario-comparison__title-en" lang="en">
                {' '}
                Scenario Comparison
              </span>
            ) : null}
          </h2>
          <p className="scenario-comparison__context">
            {vesselName !== null && `${vesselName} · `}
            {snapshot.inputs.regulationYear}년 기준 · 기준 CII{' '}
            {formatDecimalString(response.required_cii, DISPLAY_DIGITS.cii)} {unit}
          </p>
        </header>

        {/*
          입력이 바뀌었는데 결과가 그대로 남아 있는 상태 (#875, 선례 `#727`).
          문구를 기능①과 같은 형태로 두되 버튼 이름만 이 화면의 것(`비교하기`)을
          쓴다 — 다시 눌러야 할 버튼이 화면에 실제로 있는 이름이어야 한다.
        */}
        {stale ? (
          <p className="scenario-comparison__stale" role="status">
            <strong>입력이 바뀌었습니다.</strong> 아래는 이전 입력으로 계산한 값입니다 —
            <strong> 비교하기</strong>를 다시 눌러 주세요.
          </p>
        ) : null}

        {/* PRD §6.3 — 「추정값 사용」·「자동 결정 금지」 문구를 그대로 쓴다 */}
        <p className="scenario-comparison__notice">
          {ESTIMATE_NOTICE} {NO_AUTO_DECISION_NOTICE}
        </p>
        {/* `PRD §15.2` — 좌표로 계산한 거리는 「좌표 기반 추정 거리」라고 표시한다 (#1005). */}
        {usesCoordinateDistance(snapshot.inputs) ? (
          <p className="scenario-comparison__notice">{COORDINATE_DISTANCE_NOTICE}</p>
        ) : null}
        {/* `TECH_SPEC §6.3` — 경유지로 낸 우회 거리도 대권거리의 합이라 같은 성질의 추정값이다 (#1300). */}
        {usesWaypointDistance(snapshot.inputs) ? (
          <p className="scenario-comparison__notice">{WAYPOINT_DISTANCE_NOTICE}</p>
        ) : null}

        {/*
          항로 지도 (`#1265` · `#1300`). **좌표가 들어왔을 때만** 그려지며 그 판단은
          컴포넌트가 스스로 한다 — 좌표는 선택 입력이라 비어 있는 것이 기본 경로이고,
          그때 빈 지도를 두면 정상 상태가 고장으로 읽힌다.

          선은 공개 해상 경로망 위의 바닷길이다. 우회 경유지를 골랐을 때만 우회 선이 하나
          더 그려진다 — 감속은 직항과 같은 길이라 선이 늘지 않는다(`PRD §11.3`).

          선 이름은 **보이는 이름**이다 (#1836 ⑹). 입력칸은 샘플 항만을 고르면 저장 코드
          (`BUSAN`)를 담는다 — 항차 입력 폼(`VoyagePanel`·`VoyageCiiActions`)과 같은
          패턴이라 그대로 둔다. 지도는 표시 자리이므로 `portDisplayName`을 거친다(`#1742`).
        */}
        <VoyageRouteMap
          currentLat={snapshot.inputs.currentLat}
          currentLon={snapshot.inputs.currentLon}
          destinationLat={snapshot.inputs.destinationLat}
          destinationLon={snapshot.inputs.destinationLon}
          destinationName={portDisplayName(ports, snapshot.inputs.destinationPortName)}
          detourWaypointLat={snapshot.inputs.detourWaypointLat}
          detourWaypointLon={snapshot.inputs.detourWaypointLon}
          detourWaypointName={portDisplayName(ports, snapshot.inputs.detourWaypointName)}
          samplePorts={ports}
        />

        {/*
          결과는 면 하나다 (`§5` 카드 예산 · #1745). 표와 「지표별 최소값」은 같은 것을
          두 번 말하는 자리다 — 최소값 줄은 표에서 읽을 수 있는 사실의 요약이므로,
          따로 떠 있는 카드로 두면 면만 하나 늘고 둘의 관계가 흐려진다.
          이 화면의 면은 입력 · 결과 · 채택 셋이다.
        */}
        <div className="scenario-result">
          {/*
            기준은 `DIRECT`다 (#739). 배열 첫 번째가 아니라 **타입으로** 찾는다 —
            `PRD §11.2` 표 순서가 배열 순서와 같지만, 순서가 바뀌어도 기준이
            따라 움직이면 안 된다. 없으면 `deltaFromDirect`가 `null`을 내고
            차이 표시가 통째로 빠진다(잘못된 기준으로 빼는 것보다 낫다).
          */}
          <ScenarioTable
            scenarios={response.scenarios}
            direct={response.scenarios.find((s) => s.scenario_type === 'DIRECT')}
            unit={unit}
          />

          {/*
            PRD §11.2 — 추천 시나리오를 표시하지 않고 지표별 최소값만 중립적으로 적는다.
            하나를 고르지 않으므로 세 줄의 답이 서로 다를 수 있다.
          */}
          <dl className="scenario-comparison__lowest">
            {summary.map((item) => (
              <div key={item.metric} className="scenario-comparison__lowest-row">
                <dt>{item.label}</dt>
                <dd>{namesOf(item.scenarioTypes)}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/*
          면책은 화면 하단 배너 한 곳에서만 말한다 (#1416). `REFERENCE_ONLY`는 그 배너
          (`DESIGN_SYSTEM §13` 🔒)와 같은 말이라 여기서 거른다 — 기능①(`VoyageCiiResult`)과
          같은 함수다. `apiProvider`는 여전히 서버 경고를 그대로 넘긴다(#821): 거르는 것은
          **이 화면의 배치 문제**이고 응답은 건드리지 않는다.
        */}
        {shownWarnings.length > 0 ? (
          <ul className="scenario-comparison__warnings">
            {shownWarnings.map((code) => (
              <li key={code} className="scenario-comparison__warning">
                <span><Icon glyph={AlertTriangle} size="inline" /></span> {warningMessage(code)}
              </li>
            ))}
          </ul>
        ) : null}

        {/*
          비교 뒤 그 판단을 항차 계획으로 옮기는 경로 (#580). 선박은 **비교를 실행한**
          선박이다 — 폼에서 배를 바꿨으면 결과가 낡은(`stale`) 상태라 반영을 막는다.
        */}
        <ScenarioAdoptPanel
          provider={provider}
          vesselId={snapshot.inputs.vesselId}
          scenarios={response.scenarios}
          stale={stale}
          preferredVoyageId={shell.voyageId}
          samplePorts={ports}
        />
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */

/**
 * 시나리오 비교 표 (#1745).
 *
 * ## 카드 세 장을 표 하나로
 *
 * 종전에는 시나리오마다 카드 한 장이었고, 카드마다 같은 여덟 줄(참고 등급 · CII ·
 * 다음 경계까지 · 위험도 · 항해거리 · 평균 속력 · 예상 소요시간 · 예상 연료 ·
 * CO₂ · 기준 대비)이 같은 순서로 반복됐다. **세 값을 견주려면 카드 사이로 눈을
 * 옮겨야 했다** — 비교하는 화면에서 비교가 가장 어려웠다.
 *
 * 행이 지표, 열이 시나리오다. 라벨은 왼쪽에 한 번만 서고 같은 지표의 세 값이 한 줄에
 * 나란히 놓인다.
 *
 * ## 단위는 지표 이름 옆에 한 번
 *
 * 칸마다 단위를 붙이면 `4,200 nm` `4,410 nm` `4,200 nm`으로 세 번 반복되어 정작
 * 비교할 숫자를 가린다. 문자열은 여전히 `DISPLAY_UNITS`에서 읽는다 —
 * `§4.2` 「화면에 리터럴로 박지 않는다 🔒」는 **자리**가 아니라 **출처**를 정한 것이다.
 *
 * ## 결론 띠를 두지 않는다
 *
 * `§8.6` 표의 「항로 비교」 행이 **두지 않는다**로 못박혀 있다. 이 화면의 결론은 비교
 * 표 자체이고, 셋 중 하나를 골라 맨 위에 크게 적는 순간 그것이 추천이 된다
 * (`PRD §11.2` · `§6.3` 자동 결정 금지). 같은 이유로 증감 칩에 색을 주지 않는다.
 */
function ScenarioTable({
  scenarios,
  direct,
  unit,
}: {
  scenarios: readonly ScenarioResult[]
  direct: ScenarioResult | undefined
  unit: string
}) {
  const deltas = scenarios.map((scenario) => deltaFromDirect(scenario, direct))

  return (
    <>
      {/* 좁은 폭에서는 표가 가로로 스크롤한다 — 열을 접어 숨기면 비교가 끊긴다. */}
      <div className="scenario-table-wrap">
        <table className="scenario-table">
          {/*
            제목(`h2 시나리오 비교`)과 같은 말을 쓰지 않는다 — 스크린리더가 같은 문구를
            연달아 읽고, 테스트에서도 제목과 구분되지 않는다.
          */}
          <caption className="sr-only">
            지표별 비교 — 행은 지표, 열은 각 시나리오이며 직항 열을 기준으로 증감을 적는다
          </caption>
          <thead>
            <tr>
              <th scope="col" className="scenario-table__corner">
                지표
              </th>
              {scenarios.map((scenario) => (
                <th scope="col" key={scenario.scenario_type} className="scenario-table__scenario">
                  <span className="scenario-table__name">
                    {scenario.scenario_name}
                    {/*
                      증감의 기준이 어느 열인지 열 머리가 말한다 (#739). 카드에서는
                      「기준 시나리오」 한 줄이 그 일을 했다.
                    */}
                    {scenario.scenario_type === 'DIRECT' ? (
                      <span className="scenario-table__baseline">기준</span>
                    ) : null}
                  </span>
                  <ScenarioRouteGlyph type={scenario.scenario_type} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">참고 등급</th>
              {scenarios.map((scenario) => (
                <td key={scenario.scenario_type}>
                  <GradeBadge
                    rating={scenario.estimated_rating}
                    label={`${scenario.scenario_name} 참고 등급 ${scenario.estimated_rating}`}
                    size="sm"
                  />
                </td>
              ))}
            </tr>

            <MetricRow
              label="CII"
              unit={unit}
              scenarios={scenarios}
              deltas={deltas}
              value={(scenario) => formatDecimalString(scenario.attained_cii, DISPLAY_DIGITS.cii)}
              delta={(delta) => delta.cii}
              digits={DISPLAY_DIGITS.cii}
            />

            <tr>
              <th scope="row">다음 경계까지</th>
              {scenarios.map((scenario) => (
                <td key={scenario.scenario_type}>
                  {marginDisplay(scenario.estimated_rating, scenario.next_worse_boundary_margin_ratio).text}
                </td>
              ))}
            </tr>

            <tr>
              <th scope="row">위험도</th>
              {scenarios.map((scenario) => {
                const risk = riskLabel(scenario.risk_level)
                return (
                  <td key={scenario.scenario_type}>
                    {risk.withIcon ? (
                      // §2.5 (b) — 라벨이 항상 옆에 있으므로 aria-hidden
                      <span className="scenario-table__risk-icon">
                        <Icon glyph={AlertTriangle} size="inline" />
                      </span>
                    ) : null}
                    <span
                      className={`scenario-table__risk-value scenario-table__risk-value--${scenario.risk_level.toLowerCase()}`}
                    >
                      {risk.text}
                    </span>
                  </td>
                )
              })}
            </tr>

            <MetricRow
              label="항해거리"
              unit={DISPLAY_UNITS.distance}
              scenarios={scenarios}
              deltas={deltas}
              value={(scenario) =>
                formatGrouped(toDecimalInput(scenario.distance_nm), DISPLAY_DIGITS.distanceNm)
              }
              delta={(delta) => delta.distanceNm}
              digits={DISPLAY_DIGITS.distanceNm}
            />

            {/*
              `#822` — 종전에는 `String(...)` 그대로였다. 나머지 행은 전부 포매터를
              거치는데 이 한 행만 빠져 있었다. `12.8`은 우연히 1자리라 눈에 띄지 않지만
              `12`나 `12.75`가 오면 같은 표 안에서 자릿수가 갈린다.

              차이 칸은 두지 않는다 — 감속 시나리오의 속력차는 사용자가 직접 넣은 값이다.
            */}
            <MetricRow
              label="평균 속력"
              unit={DISPLAY_UNITS.speed}
              scenarios={scenarios}
              deltas={deltas}
              value={(scenario) =>
                formatDecimalString(toDecimalInput(scenario.speed_kn), DISPLAY_DIGITS.speedKn)
              }
            />

            <MetricRow
              label="예상 소요시간"
              unit={DISPLAY_UNITS.duration}
              scenarios={scenarios}
              deltas={deltas}
              value={(scenario) =>
                formatDecimalString(scenario.duration_hours, DISPLAY_DIGITS.durationHours)
              }
              delta={(delta) => delta.durationHours}
              digits={DISPLAY_DIGITS.durationHours}
            />

            <MetricRow
              label="예상 연료"
              unit={DISPLAY_UNITS.fuel}
              scenarios={scenarios}
              deltas={deltas}
              value={(scenario) => formatGrouped(scenario.fuel_ton, DISPLAY_DIGITS.fuelTon)}
              delta={(delta) => delta.fuelTon}
              digits={DISPLAY_DIGITS.fuelTon}
            />

            <MetricRow
              label="CO₂ 배출량"
              unit={DISPLAY_UNITS.co2}
              scenarios={scenarios}
              deltas={deltas}
              value={(scenario) => formatGrouped(scenario.co2_emission_ton, DISPLAY_DIGITS.co2Ton)}
              delta={(delta) => delta.co2Ton}
              digits={DISPLAY_DIGITS.co2Ton}
            />

            <MetricRow
              label="기준 대비"
              scenarios={scenarios}
              deltas={deltas}
              value={(scenario) => `${formatPercent(scenario.ratio_to_required)}%`}
            />
          </tbody>
        </table>
      </div>

      <CiiSameNotes scenarios={scenarios} direct={direct} deltas={deltas} />
    </>
  )
}

/* ------------------------------------------------------------------ */

/**
 * 지표 한 행 — 첫 칸이 지표 이름, 나머지가 시나리오별 값이다.
 *
 * 차이를 값 **바로 옆**에 둔다 (#739). 표 아래에 「직항 대비」 묶음을 따로 만들면 같은
 * 지표가 화면에 두 번 나오고, 어느 숫자가 어느 차이인지를 다시 눈으로 짝지어야 한다.
 */
function MetricRow({
  label,
  unit,
  scenarios,
  deltas,
  value,
  delta,
  digits,
}: {
  label: string
  unit?: string
  scenarios: readonly ScenarioResult[]
  deltas: readonly (ScenarioDelta | null)[]
  value: (scenario: ScenarioResult) => string
  delta?: (delta: ScenarioDelta) => string
  digits?: number
}) {
  return (
    <tr>
      <th scope="row">
        {label}
        {unit ? <span className="scenario-table__unit"> ({unit})</span> : null}
      </th>
      {scenarios.map((scenario, index) => {
        const scenarioDelta = deltas[index]
        return (
          <td key={scenario.scenario_type} className="scenario-table__num">
            <span className="scenario-table__value">{value(scenario)}</span>
            {delta !== undefined && digits !== undefined && scenarioDelta !== null ? (
              <DeltaValue value={delta(scenarioDelta)} digits={digits} />
            ) : null}
          </td>
        )
      })}
    </tr>
  )
}

/* ------------------------------------------------------------------ */

/**
 * CII가 직항과 같을 때 그 이유를 적는다 — `#739`.
 *
 * ## 같은 숫자 두 개를 그냥 두지 않는다
 *
 * 같은 속력으로 우회하면 **CII가 정확히 같다.** 연료가 시간에, 시간이 거리에
 * 비례하므로 `attained = M / (용량 × 거리)`의 분자와 분모가 같은 비율로 늘기
 * 때문이다. 화면은 그 사실을 말하지 않고 `6.614`와 `6.614`를 나란히 놓았고,
 * **보는 사람은 계산이 틀렸다고 읽는다.**
 *
 * 이것은 추천이 아니라 사실 설명이므로 `PRD §11.2`의 「추천 시나리오를 표시하지
 * 않는다」에 걸리지 않는다. 어느 쪽이 낫다고 말하지 않고, CO₂ 차이는 표가 따로
 * 보여 준다 — 등급은 같아도 총량은 다르다는 것을 사용자가 직접 읽는다.
 *
 * 표에서는 칸에 `동일`만 적고 이유를 **표 아래 한 줄**로 내린다 (#1745). 칸 안에
 * 두 줄짜리 설명을 넣으면 그 행만 키가 커져 옆 열의 숫자와 줄이 어긋난다.
 */
function CiiSameNotes({
  scenarios,
  direct,
  deltas,
}: {
  scenarios: readonly ScenarioResult[]
  direct: ScenarioResult | undefined
  deltas: readonly (ScenarioDelta | null)[]
}) {
  const same = scenarios.filter((_, index) => {
    const delta = deltas[index]
    return delta !== null && isZeroDelta(delta.cii)
  })

  if (same.length === 0) return null

  return (
    <>
      {same.map((scenario) => (
        <p className="scenario-table__same" key={scenario.scenario_type}>
          <strong>{scenario.scenario_name}의 CII는 직항과 같습니다.</strong>{' '}
          {/* 거리가 같은데 CII도 같은 것은 설명할 일이 아니다 — 같은 조건이니 같은 값이다. */}
          {direct !== undefined && scenario.distance_nm > direct.distance_nm
            ? 'CII는 거리당 값이라, 같은 속력이면 거리가 늘어도 연료가 같은 비율로 늘어 값이 변하지 않습니다.'
            : '같은 속력·같은 거리이므로 값이 같습니다.'}
        </p>
      ))}
    </>
  )
}

/**
 * 직항 대비 한 값 — `#739`.
 *
 * **색을 주지 않는다.** 늘어난 쪽을 빨강, 줄어든 쪽을 초록으로 칠하면 그것이 곧
 * 「이쪽이 낫다」가 되어 `PRD §11.2`의 추천 금지에 걸린다. 게다가 항해거리가
 * 늘어난 것이 나쁘다고 단정할 수도 없다 — 우회에는 이유가 있다. 방향은 `+`·`−`
 * 문자가 말하고, 좋고 나쁨의 판단은 사용자에게 남긴다(`PRD §6.3`).
 */
function DeltaValue({ value, digits }: { value: string; digits: number }) {
  if (isZeroDelta(value)) {
    return <span className="scenario-table__delta">동일</span>
  }

  const negative = value.startsWith('-')
  const magnitude = formatGrouped(negative ? value.slice(1) : value, digits)

  return (
    <span className="scenario-table__delta">
      {/* U+2212 MINUS SIGN — 하이픈은 좁아서 `+`와 폭이 어긋난다 */}
      {negative ? '−' : '+'}
      {magnitude}
    </span>
  )
}
