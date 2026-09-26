import { AlertTriangle, ArrowLeft } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { DataConfidenceBadge } from '../../components/DataConfidenceBadge'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { GradeScaleBar } from '../../components/GradeScaleBar'
import { VerdictStrip } from '../../components/VerdictStrip'
import { YtdSeriesChart } from './YtdSeriesChart'
/*
 * 항로 비교가 쓰는 **공용 지도**를 그대로 쓴다 (#1949). 같은 그림을 두 번 만들지
 * 않는다 — `moduleBoundary`의 `COMPOSITION`은 요청 계층(provider) 결합을 세는 것이고,
 * 화면 부품을 빌려 쓰는 것은 그 규칙의 대상이 아니다.
 */
import { VoyageRouteMap } from '../scenario-comparison/VoyageRouteMap'
import {
  ciiUnit,
  displayWarnings,
  marginDisplay,
  riskLabel,
  warningMessage,
} from '../voyage-cii/resultRules'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  formatDecimalString,
  formatTimestamp,
  formatGrouped,
  formatPercent,
  toDecimalInput,
} from '../../display/format'
import { createApiRealtimeCiiProvider, RealtimeCiiError } from './apiProvider'
import { regulationParametersPath } from '../parameters/referenceRules'
import { voyageActualsPath } from '../voyage-management/voyageRules'
import { portDisplayName, useSamplePorts } from '../ports/samplePorts'
import {
  POLL_INTERVAL_MS,
  formatAsOf,
  formatOrNull,
  isDegradingAtBerth,
  isNotUnderWay,
  projectionSentence,
  projectionReason,
  hasSubstitutedInputs,
  substitutionSummary,
  remainingDistanceNm,
  voyageProgressRatio,
  warningText,
  ytdGradeScaleVector,
  ytdRisk,
} from './realtimeRules'
import type {
  Rating,
  RealtimeCii,
  RealtimeCiiProvider,
  VoyageRoute,
  YearEndProjection,
  YtdSeries,
  YtdValues,
} from './types'
import './RealtimeCiiView.css'
import { ErrorState } from '../../components/ErrorState'
import { SCREEN_BY_ID } from '../../screens'
import { Icon } from '../../components/Icon'

/**
 * 실시간 CII — `UIFLOW 2-9` · `#357`.
 *
 * ## 「실시간」이 무엇으로 구현되는가
 *
 * `PRD §1 COR-5`가 「MVP는 AIS·IoT를 연동하지 않는다」로 못박는다. 값이 변하는
 * 근거는 **위치가 아니라 누적량**이다 — `#368` 시뮬레이션 시계가 출항 시각·속도·
 * 소모율로 누적 거리와 연료를 만들고, 그것이 CII 분자·분모로 들어간다.
 *
 * 그래서 이 화면은 지도를 그리지 않는다(이슈가 명시한 범위 밖). 그릴 것은 **수치가
 * 시간에 따라 움직이는 것**이다.
 *
 * ## 3종 값의 위계 (`PRD §3.3`)
 *
 * ⑴ 연간 누적을 **크게 하나** 두고, ⑵ 항차 구간값과 ⑶ 연말 예상은 그 아래 나란히
 * 둔다. ⑶을 단독으로 크게 표시하지 않는 것은 명세 요구다 — 확정값처럼 읽힌다.
 * ⑵에는 등급을 붙이지 않는다(`COR-1`).
 *
 * ## 배지를 감추지 않는다
 *
 * `PRD R-5`가 시뮬레이션 데이터 표기를 요구한다. 판정은 서버(`meta.simulated`)가
 * 하고, 화면은 조건을 덧붙이지 않는다.
 */
/**
 * 누적 CII를 **계산하지 못한 사유**로 읽을 수 있는 경고 (`#1095` ⑵ · `API_SPEC §1.6`).
 *
 * 앞의 둘은 「진행 중 항차의 연료를 알 수 없어 그 항차분이 누적에 들어가지 않았다」는
 * 뜻이고, 셋째(`COMPLETED_FUEL_UNFILLED`)는 **확정 항차에 연료 기록이 한 행도 없다**는
 * 뜻이다. 셋 다 문구가 **사용자가 할 일**(선박 제원의 기준 일일 연료소모량 입력 · 항차
 * 연료 입력)을 담고 있다.
 *
 * ⚠️ **`COMPLETED_NO_FUEL`·`COMPLETED_NO_DISTANCE`는 넣지 않았다.** 두 문구는
 * 「계획값을 임시 사용 중」으로 끝나는데, 그것은 **값이 들어갔다**는 뜻이라
 * 「계산하지 못했다」와 모순된다. 이 목록에 코드를 더할 때는 그 문구가 「무엇을
 * 채우면 값이 생기는가」에 답하는지 먼저 본다 — 답하지 않는 경고를 넣으면 카드가
 * 다시 「고칠 수 없는 안내」나 서로 어긋나는 안내를 하게 된다.
 */
const YTD_BLOCKER_WARNINGS: ReadonlySet<string> = new Set([
  'SIMULATION_NO_FUEL_RATE',
  'SIMULATION_NO_FUEL_TYPE',
  // 확정 항차에 연료 기록이 **한 행도 없다** (#1095 ⑵) — 거리만 더해지고 연료는 0이
  // 된다. 문구가 「해당 항차에 연료를 입력해 주세요」로 끝나 위 기준을 충족한다.
  'COMPLETED_FUEL_UNFILLED',
])

export function RealtimeCiiView({ provider }: { provider?: RealtimeCiiProvider }) {
  const { vesselId } = useParams()
  const [data, setData] = useState<RealtimeCii | null>(null)
  const [failure, setFailure] = useState<{ message: string; notFound: boolean } | null>(
    null,
  )
  const [refreshing, setRefreshing] = useState(false)
  /*
   * 마지막 폴링이 실패해 화면의 값이 낡았다 (`#755`).
   *
   * 값을 지우지 않는 것과 **값이 최신인 척하는 것**은 다르다. 종전에는 실패가 화면에
   * 드러나는 자리가 없어, 고친 뒤에는 값이 조용히 낡을 수 있었다 — 이 화면은
   * 「항해 중 CII가 변하는 것을 보여 주는」 자리(`UIFLOW 2-9`)라 그 침묵이 특히 나쁘다.
   */
  const [stale, setStale] = useState(false)

  /*
   * provider를 ref에 담는다. 매 렌더마다 새로 만들면 아래 effect의 의존성이 계속
   * 바뀌어 폴링 타이머가 재설정되고, 결국 간격이 지켜지지 않는다.
   */
  const providerRef = useRef<RealtimeCiiProvider | null>(null)
  if (providerRef.current === null) {
    providerRef.current = provider ?? createApiRealtimeCiiProvider()
  }

  /*
   * 선박 전환 세대 (`#874`).
   *
   * ## 왜 `alive` 지역 변수로는 안 되는가
   *
   * `/vessels/:vesselId/voyages/:voyageId`는 **라우트 파라미터만 바뀌므로 언마운트
   * 없이 선박이 전환된다.** `VesselDetail.tsx`가 쓰는 「effect 안의 `let alive`,
   * 정리 함수에서 `false`」 선례는 요청을 **그 effect가 시작한 경우에만** 덮는다.
   *
   * 이 화면은 다르다 — 60초 폴링이 **effect 밖에서** `load`를 부른다. 정리 함수가
   * `clearInterval`을 해도 **이미 날아간 요청은 취소되지 않고**, 그 응답이 돌아와
   * `setData(A)`로 B의 화면을 덮는다. 다음 폴링까지 60초간 복구가 없다.
   *
   * 그래서 소유권을 effect가 아니라 **ref 하나**가 갖는다. 리셋 effect가 세대를
   * 올리고, `load`는 시작할 때 받은 표를 응답 시점에 대조해 **자기 세대가 아니면
   * 아무 상태도 건드리지 않는다.**
   *
   * `vesselId` 자체를 비교하지 않는 것은 A → B → A 왕복 때문이다. 그때 첫 A의
   * 인플라이트 응답은 `vesselId`가 같아 통과하지만 **더 오래된 값**이다.
   */
  const generationRef = useRef(0)

  /*
   * `load`는 **상태를 읽지 않는다** (`#755`).
   *
   * ## 종전에 무엇이 틀렸나
   *
   * 실패 처리가 `if (data === null)`로 「최초 로드인가」를 갈랐고, 그래서 `load`가
   * `data`에 의존했다(`[vesselId, data]`). 그런데 폴링 타이머는 **effect가 돈 시점의
   * `load`를 캡처**한다 — 그 클로저에 담긴 `data`는 첫 렌더의 `null`이고, 이후 값이
   * 들어와도 **그 클로저 안에서는 영원히 `null`이다.**
   *
   * 결과: 판정이 항상 「최초 로드」로 떨어져 **폴링이 한 번 실패하면 화면이 통째로
   * 비워졌다.** 바로 위 주석은 정반대를 적고 있었다.
   *
   * `oxlint`가 못 잡은 것은 폴링 effect에 `exhaustive-deps` 억제 주석이 붙어 있었기
   * 때문이다. 그 억제는 이제 필요 없다 — 아래 두 effect의 의존성이 전부 안정적이다.
   *
   * ## 어떻게 고쳤나
   *
   * 「최초인가」를 상태에서 읽지 않고 **`setData`의 함수형 갱신 안에서** 판정한다.
   * React가 넘겨주는 `prev`는 **항상 최신값**이라 클로저 나이와 무관하다.
   *
   * ref에 최신 `load`나 `data`를 담는 대안도 있으나, 그러면 **같은 사실이 상태와 ref
   * 두 곳에** 있게 된다. 여기서는 상태 하나로 끝난다.
   */
  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!vesselId) return
      // 이 요청이 어느 선박의 것인지 (`#874`). 응답 시점에 대조한다.
      const ticket = generationRef.current
      if (options.silent) setRefreshing(true)
      try {
        const next = await providerRef.current!.load(vesselId)
        if (ticket !== generationRef.current) return
        setData(next)
        setFailure(null)
        setStale(false)
      } catch (error) {
        if (ticket !== generationRef.current) return
        const message =
          error instanceof Error ? error.message : '값을 불러오지 못했습니다.'
        const notFound = error instanceof RealtimeCiiError && error.notFound

        /*
         * 폴링 중 실패는 **화면을 비우지 않는다.** 마지막으로 받은 값이 여전히
         * 「방금 전 기준」으로 유효하고, 통신 오류로 값을 지우면 사용자는 정박도
         * 항해도 아닌 빈 화면을 본다. 최초 로드 실패만 화면을 대체한다.
         *
         * 판정을 `setData` 안에서 한다 — `prev`가 최신값이라 타이머가 붙든 클로저의
         * 나이에 영향받지 않는다. 값은 그대로 두고(`prev` 반환) 판정만 한다.
         */
        setData((prev) => {
          if (prev === null) setFailure({ message, notFound })
          // 값이 있으면 남긴다. 대신 낡았다는 사실을 화면이 말한다.
          else setStale(true)
          return prev
        })
      } finally {
        if (ticket === generationRef.current) setRefreshing(false)
      }
    },
    [vesselId],
  )

  /*
   * 선박이 바뀌면 **화면을 먼저 비운다** (`#874`).
   *
   * 종전에는 전환을 아무도 몰랐다 — `load`는 새 `vesselId`로 다시 돌지만 `data`·
   * `failure`·`stale`이 그대로라 ⑴ A의 이름·등급이 B의 URL 아래 남고(「불러오는
   * 중」은 두 번째 선박부터 영영 뜨지 않는다) ⑵ A의 404 오류 패널이 B에서 유지되며
   * 그 안의 「← 선박 상세」가 URL과 다른 배를 가리켰다.
   *
   * **이 effect가 아래 로드 effect보다 먼저 선언돼 있어야 한다.** React는 선언
   * 순서대로 실행하므로, 세대를 올리는 일이 `load()` 호출보다 앞서야 새 요청이
   * 새 표를 받는다.
   */
  useEffect(() => {
    generationRef.current += 1
    // oxlint-disable-next-line react/set-state-in-effect -- 선박이 바뀌면 화면을 먼저 비우는 리셋(`#874`) — 아래 로드 effect보다 앞서야 한다
    setData(null)
    setFailure(null)
    setStale(false)
    setRefreshing(false)
  }, [vesselId])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- 선박이 정해지면 조회 — `load`가 시작 시점의 진행 상태를 세운다
    void load()
  }, [load])

  useEffect(() => {
    if (!vesselId) return
    const timer = setInterval(() => {
      /*
       * 탭이 보이지 않으면 쉰다. 배경 탭을 켜 둔 사용자가 하루에 1440번을 요청하는데,
       * 그중 사람이 보는 것은 돌아온 순간의 한 번뿐이다.
       */
      if (typeof document !== 'undefined' && document.hidden) return
      void load({ silent: true })
    }, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [vesselId, load])

  if (failure) {
    return (
      <div className="rt">
        <BackLink vesselId={vesselId} />
        {/*
          없는 대상(404)에는 재시도를 주지 않는다 — 다시 눌러도 같은 실패다 (`#694`).
          그 경우에는 나갈 길(대시보드)을 준다.
        */}
        <ErrorState
          level="page"
          message={failure.message}
          onRetry={failure.notFound ? undefined : () => window.location.reload()}
          alternative={
            failure.notFound ? (
              <Link className="error-state__retry" to="/dashboard">
                대시보드로 돌아가기
              </Link>
            ) : null
          }
        />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="rt" aria-busy="true">
        <BackLink vesselId={vesselId} />
        <p className="fleet__loading">실시간 값을 불러오는 중입니다…</p>
      </div>
    )
  }

  const unit = ciiUnit(data.capacityBasis)
  const degrading = isDegradingAtBerth(data)
  /*
   * 누적을 계산하지 못한 **사유**로 서버가 내려보낸 경고 (`#1095` ⑵).
   *
   * 화면이 사유를 새로 짓지 않는다 — 이 네 코드는 「값이 없다」가 아니라 「**무엇을
   * 채우면 값이 생긴다**」를 말하고, 그 문구는 `API_SPEC §1.6`이 소유한다. 여기서
   * 하는 일은 **그 가운데 지금 화면에 해당하는 것만 골라** 카드 안으로 옮기는 것뿐이다
   * (전체 경고 목록은 화면 아래에 그대로 남는다).
   */
  const ytdBlockers = data.warnings.filter((code) => YTD_BLOCKER_WARNINGS.has(code))
  const shownWarnings = displayWarnings(data.warnings)

  return (
    <div className="rt">
      {/*
        URL의 선박을 가리킨다 (`#874`). 종전에는 `data.vesselId`였는데, 전환 후
        옛 선박의 값이 남는 동안 이 링크가 **주소창과 다른 배**를 가리켰다. 리셋이
        그 잔류를 없앴지만, 기준을 URL로 두면 애초에 어긋날 수 없다 — 위 실패 갈래도
        같은 값을 쓴다.
      */}
      <BackLink vesselId={vesselId} />

      <header className="rt__head">
        <div>
          <h1 className="rt__title">{data.vesselName}</h1>
          <p className="rt__sub">
            {data.regulationYear}년 누적 · 단위 {unit}
          </p>
        </div>
        <div className="rt__status">
          {/* PRD R-5 — 판정은 서버가 한다. 화면이 조건을 덧붙이지 않는다. */}
          {data.simulated ? (
            <span className="rt__sim" title="AIS·IoT 미연동. 입력값과 서버 시각에서 파생된 값입니다.">
              시뮬레이션 데이터
            </span>
          ) : null}
          {/*
            한 문장으로 합쳤다 (#725). 둘 다 「언제 값인가」를 말하는데 두 줄로
            나뉘어 있어, 왼쪽 두 줄(제목·부제)과 높이가 어긋났다.
          */}
          <p className="rt__asof">
            기준 {formatAsOf(data.asOf)}
            {refreshing ? ' · 갱신 중…' : ''} · {POLL_INTERVAL_MS / 1000}초마다 자동 갱신
          </p>
          {/*
            `#755` — 갱신에 실패하면 **그 사실을 말한다.** 값을 남기는 것과 값이
            최신인 척하는 것은 다르다. `role="status"`로 내는 것은 이것이 오류
            상황이 아니라 **상태 안내**이기 때문이다 — 화면은 여전히 유효한 값을
            보여 주고 있고, 다음 주기에 스스로 회복한다.
          */}
          {stale ? (
            <p className="rt__stale" role="status">
              마지막 갱신에 실패했습니다. 위 기준 시각의 값을 보여 주는 중이며,
              {POLL_INTERVAL_MS / 1000}초 뒤 다시 시도합니다.
            </p>
          ) : null}
        </div>
      </header>

      {/* ── 정박 중 악화 — 명세 3-③ ─────────────────────────────── */}
      {isNotUnderWay(data) ? (
        <p className={`rt__berth${degrading ? ' rt__berth--degrading' : ''}`} role="status">
          {degrading ? (
            <>
              <b>정박 중입니다.</b> 거리는 늘지 않고 정박 연료만 누적되므로{' '}
              <b>누적 CII가 계속 나빠집니다.</b>
            </>
          ) : (
            <>
              <b>정박 중입니다.</b> 정박 연료 기록이 없어 누적값이 움직이지 않습니다 —
              기록을 넣으면 반영됩니다.
            </>
          )}
        </p>
      ) : null}

      {/*
        ── 결론 띠 (#1949 · `DESIGN_SYSTEM §8.6` 🔒) ─────────────────────

        **이 화면만 결론 띠를 쓰지 않고 있었다.** 선박 상세 · CII 예측 · 연간 등급 관리 ·
        함대 감축 계획이 이미 `VerdictStrip`을 쓴다. 그 결과 1440에서 **34px 숫자 아홉 개**가
        한 무게로 늘어섰고(실측 09-26), 정작 연말 예상은 20px로 **결론보다 작았다.**

        주 결론은 **올해 누적**이다 — 이 화면의 질문이 「지금 내 배의 올해 등급이 어떤가」이고,
        연말 예상은 가정이 든 추정값이라 보조다(`§8.6`이 정한 주 1 · 보조 1).

        띠가 값을 말하므로 아래 카드의 `실적`·`기준` 칸은 걷었다 — 같은 숫자를 한 화면에
        두 번 두지 않는다.
      */}
      <ConclusionStrip data={data} />

      {/* ── ⑴ 연간 누적의 재료 ───────────────────────────────────── */}
      <section className="card rt__ytd" aria-label="연간 누적 CII">
        <div className="card__head">
          <h2 className="card__title">연간 누적 (YTD)</h2>
          <span className="card__meta">현재 누적 기준 예상 등급</span>
        </div>

        {data.ytd.dataAvailable && data.ytd.rating ? (
          <div className="ytd">
            {/*
              ⚠️ **등급 배지를 여기서 걷었다** (#1949) — 결론 띠가 같은 배지를 이미
              들고 있다. 남는 것은 **신뢰도**다: 이 누적이 실측이 아닌 값으로 계산됐는지,
              그리고 무엇이 그런지 보러 가는 길(`#1082` · `UIFLOW 2-11` 진입 조건).
              그것은 결론이 아니라 재료의 성질이라 재료 옆이 제자리다.
            */}
            <YtdConfidence data={data} />
            {/*
              자릿수는 `DESIGN_SYSTEM §4`(🔒)가 정한다 — CII 3자리(`§4.1`),
              거리 0자리·연료 1자리(`§4.2`). 종전에는 서버 원본 문자열을 그대로
              내보내 `8.979907` · `4300.00 nm`처럼 화면마다 자릿수가 갈렸다.

              단위는 `DISPLAY_UNITS`를 참조한다. 리터럴로 박으면 표기가 바뀔 때
              일부가 남고, 그 누락은 화면이 깨지지 않아 발견이 늦다(#164).
            */}
            <dl className="ytd__figures">
              {/*
                ⚠️ **실적·기준 두 칸을 여기서 걷었다** (#1949). 실적은 결론 띠의 주
                결론이고, 기준은 그 띠가 등급 배지·위험도로 말한다 — 같은 숫자를 한
                화면에 두 번 두면 어느 쪽이 결론인지 흐려진다(`§8.6`).

                다만 **「기준값 근거」로 가는 길은 지워지지 않는다** — `#1516`·`#1239`
                결정 B·D가 「왜 이 등급인가」의 출발점으로 세운 링크다. 아래 등급 스케일
                옆으로 옮겼다.
              */}
              {/*
                누적 거리를 운항·정박으로 쪼갠다 (#725). 위의 정박 경고가 「거리는
                늘지 않고 연료만 누적된다」고 말하는데, 그 말을 **뒷받침하는 숫자가
                화면에 없었다** — 서버는 두 축을 나눠 싣고 있었고 화면이 합계만 읽었다.
              */}
              <Figure
                label="누적 거리"
                value={formatOrNull(data.ytd.totalDistanceNm, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.distanceNm),
                )}
                suffix={` ${DISPLAY_UNITS.distance}`}
                hint={distanceSplitHint(data.ytd)}
              />
              <Figure
                label="누적 연료"
                value={formatOrNull(data.ytd.totalFuelTon, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.fuelTon),
                )}
                suffix={` ${DISPLAY_UNITS.fuel}`}
              />
              {/*
                CII의 **분자**다 (#725). 화면에는 분모 쪽(거리)과 그 재료(연료)만
                있고 정작 규제가 세는 양이 없었다 — `total_co2_ton`은 `#357`부터
                응답에 있었고 화면이 읽지 않았다. 연료 옆에 두어 연료 → CO₂ 순서로
                읽히게 한다.
              */}
              <Figure
                label="누적 CO₂"
                value={formatOrNull(data.ytd.totalCo2Ton, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.co2Ton),
                )}
                suffix={` ${DISPLAY_UNITS.co2}`}
              />
            </dl>
          </div>
        ) : (
          /*
           * ⚠️ **「실적이 없다」와 「있는데 계산하지 못했다」는 다르다** (`#1095` ⑵).
           *
           * 서버는 `total_distance_nm <= 0` **또는** `total_fuel_ton <= 0`이면
           * `data_available=false`를 준다(`services/ytd_cii.py:390`). 뒤쪽은 항차도
           * 거리도 있는데 **연료를 모르는** 상태다 — 기여도 카드에는 거리 수백 nm이
           * 찍히는데 여기서만 「실적을 입력하라」고 말하고 있었고, 실제로 해야 할 일은
           * 선박 제원(기준 일일 연료소모량) 입력이다.
           *
           * 사유는 **서버가 이미 경고로 말하고 있다** — `SIMULATION_NO_FUEL_RATE` ·
           * `SIMULATION_NO_FUEL_TYPE` 등이 같은 응답의 `warnings`에 실린다
           * (`API_SPEC §1.6`). 화면이 새로 문구를 짓지 않고 그 문구를 그대로 쓴다.
           */
          <div className="rt__nodata">
            {ytdBlockers.length > 0 ? (
              <ul className="rt__nodata-reasons">
                {ytdBlockers.map((code) => (
                  <li key={code}>{warningText(code)}</li>
                ))}
              </ul>
            ) : (
              <p>올해 등록된 실적이 없습니다. 항차 실적을 입력하면 누적값이 계산됩니다.</p>
            )}
          </div>
        )}

        {data.ytd.dataAvailable && data.ytd.rating ? (
          <YtdAxis ytd={data.ytd} rating={data.ytd.rating} />
        ) : null}

        <p className="rt__note">
          연중 누적 예측값이며 <b>공식 등급이 아닙니다</b>. 공식 등급은 연말 DCS
          보고·검증 후 확정됩니다.
        </p>
      </section>

      <div className="rt__split">
        {/* ── ⑵ 항차 구간값 — 등급 없음 ──────────────────────────── */}
        <section className="card" aria-label="항차 CII 기여도">
          <div className="card__head">
            <h2 className="card__title">항차 CII 기여도</h2>
            <span className="card__meta">등급 판정 대상 아님</span>
          </div>
          {data.currentVoyage ? (
            <div className="rt__voyage-body">
              {/*
                이번 항차 지도 (#1949 · R-D2 `#1672` 확정).

                **보간하지 않는다** — 진행률로 위치를 만들지 않고, 서버가 마지막으로
                받은 위치를 그대로 찍고 그 시각을 함께 적는다. 진행률은 옆 단의 막대에만
                둔다. 좌표를 못 받으면 지도를 그리지 않고 수치가 카드 전체를 쓴다.
              */}
              <VoyageMapBlock
                provider={provider}
                vesselId={data.vesselId}
                voyageId={data.currentVoyage.voyageId}
                arrivalPortName={data.currentVoyage.arrivalPortName}
              />
              <div className="rt__voyage-figures-col">
                <VoyagePanel data={data} unit={unit} vesselId={vesselId} />
              </div>
            </div>
          ) : (
            /* 항차가 없는 것은 오류가 아니다 — 정박 중이거나 아직 등록 전이다. */
            <p className="rt__nodata">진행 중인 항차가 없습니다.</p>
          )}
        </section>

        {/* ── ⑶ 연말 예상 — 보조 표시 ───────────────────────────── */}
        <section className="card" aria-label="연말 예상">
          <div className="card__head">
            <h2 className="card__title">연말 예상</h2>
            <span className="card__meta">가정에 따라 달라지는 추정값</span>
          </div>
          <ProjectionPanel data={data} />
        </section>
      </div>

      {/*
        ── 올해 누적 추이 (#1949) ──────────────────────────────────────

        **두 단 밖**이다 — 시간축이 한 해를 담으므로 반 폭에서는 항차 경계가 서로 붙어
        「언제부터 나빠졌나」가 읽히지 않는다. 그것이 이 블록의 유일한 목적이다.

        조회는 **따로** 나간다(`loadSeries`). 실패가 이 카드 안에서 끝나야 하기
        때문이다 — 결론·재료·이번 항차는 `/cii/current` 하나로 이미 서 있다.
      */}
      {/*
        선박이 바뀌면 **다시 만든다**(`key`). 이 화면은 라우트 파라미터만 바뀌어
        언마운트 없이 선박이 전환되므로(위 세대 주석), 키가 없으면 앞 선박의 추이가
        남은 채로 새 조회가 돌아오기를 기다린다.
      */}
      <TrendSection key={data.vesselId} provider={provider} vesselId={data.vesselId} />

      {/* ── 경고 ─────────────────────────────────────────────────── */}
      {/*
        면책은 화면 하단 배너 한 곳에서만 말한다 (#1416). `REFERENCE_ONLY`는 그 배너
        (`DESIGN_SYSTEM §13` 🔒)와 같은 말이라 거른다 — 기능①·항로 비교와 같은 함수다.
      */}
      {shownWarnings.length > 0 ? (
        <ul className="rt__warnings">
          {shownWarnings.map((code) => (
            <li key={code}>{warningText(code)}</li>
          ))}
        </ul>
      ) : null}

      <DisclaimerBanner />
    </div>
  )
}

// ─── 부품 ────────────────────────────────────────────────────────────────────

const TREND_FAILED_TEXT = '추이를 불러오지 못했습니다.'

/**
 * 이번 항차 지도 (#1949 · R-D2 `#1672` 확정).
 *
 * ⚠️ **없으면 그리지 않는다.** 좌표가 비었거나 조회가 실패하면 **아무것도 그리지
 * 않고** 아래 진행률 막대만 남는다 — 「지도를 못 불러왔습니다」를 내면 없는 고장을
 * 만드는 것이다(좌표는 선택 입력이라 비어 있는 것이 정상 경로다).
 *
 * ⚠️ **위치 기준 시각을 함께 적는다.** 이 값은 마지막으로 **받은** 위치이지 지금
 * 위치가 아니다. 시각이 없으면 얼마나 낡았는지 말할 수 없으므로 지도를 그리지 않는다.
 */
function VoyageMapBlock({
  provider,
  vesselId,
  voyageId,
  arrivalPortName,
}: {
  provider?: RealtimeCiiProvider
  vesselId: string
  voyageId: string
  arrivalPortName: string | null
}) {
  const client = useMemo(() => provider ?? createApiRealtimeCiiProvider(), [provider])
  const [route, setRoute] = useState<VoyageRoute | null>(null)

  useEffect(() => {
    const loadRoute = client.loadRoute
    if (loadRoute === undefined) return
    let cancelled = false
    loadRoute.call(client, vesselId, voyageId).then(
      (value) => {
        if (!cancelled) setRoute(value)
      },
      () => {
        // 조용히 그리지 않는다 — 지도는 이 화면의 보조다.
        if (!cancelled) setRoute(null)
      },
    )
    return () => {
      cancelled = true
    }
  }, [client, vesselId, voyageId])

  if (
    route === null ||
    route.currentLat === null ||
    route.currentLon === null ||
    route.arrivalLat === null ||
    route.arrivalLon === null ||
    route.positionUpdatedAt === null
  ) {
    return null
  }

  return (
    <div className="rt__map">
      <VoyageRouteMap
        currentLat={route.currentLat}
        currentLon={route.currentLon}
        destinationLat={route.arrivalLat}
        destinationLon={route.arrivalLon}
        destinationName={route.arrivalPortName ?? arrivalPortName ?? ''}
        /*
          ⚠️ **빌려 쓴 부품의 기본 문안은 그 화면 기준이다.** 그대로 두면 이 화면에
          「항로 비교 지도 텍스트 정보」가 나온다 — 실측에서 그렇게 나왔다.
        */
        alternativeTitle="이번 항차 지도"
      />
      {/*
        **마지막으로 받은 위치**임을 말한다. 「지금 여기 있다」가 아니다 — 진행률과
        위치가 서로 다른 시점을 가리킬 수 있다는 것이 R-D2가 연 문제였다.
      */}
      <p className="rt__map-asof">위치 기준 {formatTimestamp(route.positionUpdatedAt)}</p>
    </div>
  )
}

/**
 * 기여 요인의 이름 — `API_SPEC`의 뜻 열을 그대로 옮겼다 (`#1673` → `#1829`).
 *
 * 문구를 새로 쓰지 않는다(`AGENTS §3`). 표에 없는 키가 오면 **키 자체를 보여 준다** —
 * 조용히 감추면 합이 맞지 않는 것처럼 보인다.
 */
const DRIVER_LABEL: Readonly<Record<string, string>> = {
  BASIS_DIFFERENCE: '집계 기준 차이',
  CURRENT_VOYAGE: '이 항해를 마치면',
  REMAINING_PLAN: '남은 계획까지 하면',
}

/**
 * 연말 예상을 **무엇이 올리는가** (#1949 · `API_SPEC` `drivers[]`).
 *
 * ⚠️ **화면이 합을 다시 계산하지 않는다.** 정본이 「부분값을 더해 총량을 만들지
 * 않는다」로 못박았고, 동치가 성립하는 자릿수는 **응답 자릿수(6자리)**다. 화면이
 * 3자리로 반올림해 더하면 끝자리에서 어긋난다. 총량은 결론 띠와 위의 방향 문장이
 * 서버 값 그대로 말하고, 여기는 **단계별 변화만** 적는다.
 *
 * 값은 음수일 수 있다 — 부호를 그대로 보인다.
 */
function ProjectionDrivers({ projection }: { projection: YearEndProjection }) {
  const drivers = projection.drivers
  if (drivers.length === 0) return null

  return (
    <dl className="rt__drivers">
      {drivers.map((driver) => (
        <div key={driver.key}>
          <dt>{DRIVER_LABEL[driver.key] ?? driver.key}</dt>
          <dd className="num">
            {formatOrNull(driver.deltaCii, (v) => signedCii(v)) ?? '—'}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/**
 * 부호를 **앞에 붙여** 적는다 — `+0.760` · `−0.008`.
 *
 * 서버 문자열의 음수 기호는 ASCII 하이픈이라 화면에서는 빼기 기호(U+2212)로 바꾼다.
 * 자릿수는 `§4.1`(🔒)의 CII 자릿수를 그대로 쓴다.
 */
function signedCii(raw: string): string {
  const negative = raw.trimStart().startsWith('-')
  const magnitude = formatDecimalString(negative ? raw.trimStart().slice(1) : raw, DISPLAY_DIGITS.cii)
  return `${negative ? '−' : '+'}${magnitude}`
}

/**
 * 올해 누적 추이 블록 (#1949).
 *
 * ⚠️ **실패가 이 블록 안에서 끝난다.** 바깥으로 던지면 대시보드가 통째로 오류 화면이
 * 되고, 이미 받아 둔 결론·재료·이번 항차까지 사라진다 — 그것이 곧 격리 실패다
 * (`#1831` 팝오버에서 세운 것과 같은 규칙).
 *
 * 조회를 못 하는 대역(`loadSeries`가 없는 provider)에서는 **아무것도 그리지 않는다** —
 * 「불러오지 못했습니다」를 내면 없는 고장을 만드는 것이다.
 */
function TrendSection({
  provider,
  vesselId,
}: {
  provider?: RealtimeCiiProvider
  vesselId: string
}) {
  const client = useMemo(() => provider ?? createApiRealtimeCiiProvider(), [provider])
  const [series, setSeries] = useState<YtdSeries | null>(null)
  /*
   * 첫 상태를 **여기서 정한다.** effect 안에서 `setState('loading')`을 부르면 한 번 더
   * 렌더되고, 조회를 못 하는 대역에서는 그 렌더가 헛돈다. 선박이 바뀔 때는 호출부가
   * `key`로 이 부품을 다시 만들므로 상태도 초기값부터다.
   */
  const [state, setState] = useState<'idle' | 'loading' | 'ok' | 'failed'>(() =>
    client.loadSeries === undefined ? 'idle' : 'loading',
  )

  useEffect(() => {
    const loadSeries = client.loadSeries
    if (loadSeries === undefined) return
    let cancelled = false
    loadSeries.call(client, vesselId).then(
      (value) => {
        if (cancelled) return
        setSeries(value)
        setState('ok')
      },
      () => {
        if (!cancelled) setState('failed')
      },
    )
    return () => {
      cancelled = true
    }
  }, [client, vesselId])

  if (state === 'idle') return null

  return (
    <section className="card rt__trend" aria-label="올해 누적 추이">
      <div className="card__head">
        <h2 className="card__title">올해 누적 추이</h2>
        <span className="card__meta">항차 경계마다 한 점</span>
      </div>
      {state === 'loading' ? (
        <p className="rt__nodata">추이를 불러오는 중…</p>
      ) : state === 'failed' || series === null ? (
        <p className="rt__nodata">{TREND_FAILED_TEXT}</p>
      ) : (
        <YtdSeriesChart series={series} />
      )}
    </section>
  )
}

/**
 * 결론 띠 (#1949 · `DESIGN_SYSTEM §8.6` 🔒).
 *
 * 주 = 올해 누적 · 보조 = 연말 예상 · 위험도는 **올해 누적의 것**이다. 연말 예상의
 * 위험도를 쓰지 않는 것은 띠의 주 결론이 올해 누적이기 때문이다 — 한 띠에 두 축의
 * 위험도가 서면 어느 값의 판정인지 읽을 수 없다(연말 예상 쪽 위험도는 그 카드가 낸다).
 *
 * ⚠️ **값이 없으면 띠를 세우지 않는다.** 빈 띠는 「값이 0」으로 읽힌다 — 그때는 아래
 * 카드들이 각자 사유를 말한다(`ytd.reason` · `projection.reason`).
 */
function ConclusionStrip({ data }: { data: RealtimeCii }) {
  // CII 단위는 상수가 아니다 — 선종의 capacity 축에서 갈린다 (`§4.1` 🔒 · `ciiUnit`).
  const unit = ciiUnit(data.capacityBasis)
  const ytdValue = formatOrNull(data.ytd.attainedCii, (v) =>
    formatDecimalString(v, DISPLAY_DIGITS.cii),
  )
  if (!data.ytd.dataAvailable || ytdValue === null) return null

  const risk = ytdRisk(data.ytd)
  const projectionValue = formatOrNull(data.projection.attainedCii, (v) =>
    formatDecimalString(v, DISPLAY_DIGITS.cii),
  )

  return (
    <VerdictStrip
      label="올해 누적과 연말 예상"
      main={{
        label: '올해 누적 (YTD)',
        value: ytdValue,
        unit,
        rating: data.ytd.rating,
        ratingLabel: `현재 누적 기준 예상 등급 ${data.ytd.rating ?? '없음'}`,
      }}
      /*
       * 연말 예상을 못 내는 선박도 있다(`projection.dataAvailable`). 그때는 값 자리에
       * 「—」를 두고 **등급 배지를 아예 두지 않는다** — `rating`을 넘기지 않으면 배지가
       * 서지 않는다(`#1729`). 「등급 없음」 배지를 세우면 *계산했는데 등급이 없다*로
       * 읽히는데, 실제로는 계산 자체를 못 한 것이다.
       */
      sub={
        projectionValue === null
          ? { label: '연말 예상', value: '—' }
          : {
              label: '연말 예상',
              value: projectionValue,
              unit,
              rating: data.projection.rating,
              ratingLabel: `연말 예상 등급 ${data.projection.rating ?? '없음'}`,
            }
      }
      {...(risk === null
        ? {}
        : { risk: { level: risk, heading: '위험도', ...riskLabel(risk) } })}
    />
  )
}

function BackLink({ vesselId }: { vesselId?: string }) {
  return (
    <Link className="rt__back" to={vesselId ? `/vessels/${vesselId}` : '/dashboard'}>
      <Icon glyph={ArrowLeft} size="inline" />
      선박 상세
    </Link>
  )
}

function Figure({
  label,
  value,
  suffix = '',
  hint = null,
  link = null,
}: {
  label: string
  value: string | null
  suffix?: string
  /** 값 아래 링크 — 그 값의 근거가 있는 자리로 (#1516). `hint`처럼 `<dd>` 안이다. */
  link?: ReactNode
  /**
   * 값 아래 한 줄 — **그 값이 무엇으로 이루어졌는가** (`#725`).
   *
   * `<dd>` 안에 둔다. `<dl>` 안에서 `<dt>`·`<dd>` 사이에 다른 요소를 끼울 수 없고,
   * 이 문장은 값의 부속이지 별도 항목이 아니다.
   */
  hint?: string | null
}) {
  return (
    <div>
      <dt>{label}</dt>
      {/* 빈칸이면 항목 자체가 없는 것으로 읽힌다. */}
      <dd className={value ? 'num' : 'num muted'}>
        {value ? `${value}${suffix}` : '—'}
        {hint ? <span className="rt__figure-hint">{hint}</span> : null}
        {link}
      </dd>
    </div>
  )
}

/**
 * 누적 거리의 내역 — 운항 / 정박 (`#725`).
 *
 * **한쪽만 있어도 적는다.** 「정박 0」은 값이 없는 것과 다른 사실이고, 그 0이야말로
 * 정박 경고를 읽는 사람이 확인하려는 숫자다. 둘 다 없으면 `null` — 없는 내역을
 * 「— · —」로 적으면 줄만 늘고 뜻이 없다.
 */
function distanceSplitHint(ytd: YtdValues): string | null {
  const underway = formatOrNull(ytd.underwayDistanceNm, (v) =>
    formatGrouped(v, DISPLAY_DIGITS.distanceNm),
  )
  const berth = formatOrNull(ytd.notUnderwayDistanceNm, (v) =>
    formatGrouped(v, DISPLAY_DIGITS.distanceNm),
  )
  if (underway === null && berth === null) return null
  return `운항 ${underway ?? '—'} · 정박 ${berth ?? '—'}`
}

/**
 * ⑴의 축 — 기준 대비 · 위험도 · 다음 경계까지 · 등급 스케일 (`#725`).
 *
 * ## 왜 한 덩어리인가
 *
 * 넷이 **같은 질문 하나**에 답한다 — 「이대로 가면 위험한가」. 종전에는 그 질문에
 * 등급 전이(E→E) 하나로만 답하고 있었는데, 전이는 **경계를 넘을 때만** 움직이므로
 * 경계 바로 앞과 구간 한가운데가 화면에서 같아 보였다.
 *
 * 위 수치 격자에 섞지 않는다. 그쪽은 「무엇이 얼마인가」(실적·기준·거리·연료)이고
 * 여기는 「그래서 어디쯤인가」다. 다섯 칸을 여섯으로 늘리면 1280에서 34px 수치가
 * 한 칸(약 136px)에 들어가지 않기도 한다.
 *
 * ## 값은 서버 것을 그대로 쓴다
 *
 * `risk_level`·`margin_ratio`는 `PRD §9.4.1`의 결정표를 서버가 적용한 결과다.
 * 문구는 기능①이 이미 쓰는 `riskLabel`·`marginDisplay`를 그대로 부른다 — 같은
 * 사실을 두 화면이 다른 말로 적으면 그 차이가 곧 버그 신고가 된다.
 */
function YtdAxis({ ytd, rating }: { ytd: YtdValues; rating: Rating }) {
  const risk = ytdRisk(ytd)
  const riskText = risk === null ? null : riskLabel(risk)
  const margin = marginDisplay(rating, ytd.marginRatio)
  const ratio = formatOrNull(ytd.ratioToRequired, (v) => `${formatPercent(v)}%`)
  const scale = ytdGradeScaleVector(ytd)
  /*
   * 스케일 바를 그리면 **그 마커가 비율을 적는다** — 목록에도 두면 한 카드에 같은 값이 두 번이다
   * (#1555). 바를 못 그리면(경계 없음 · 기준 0) 목록이 유일한 자리라 남긴다.
   */
  const drawsBar = Boolean(scale && ytd.ratioToRequired && ratio)

  return (
    <div className="rt__axis">
      <dl className="rt__axis-facts">
        {drawsBar ? null : (
          <div>
            <dt>기준 대비</dt>
            {/*
              「7.871 / 5.045」를 눈으로 나누고 있었다. 서버가 `ratio_to_required`를
              이미 싣는다 — 기능①의 「기준 대비 비율」과 같은 값·같은 자릿수다.
            */}
            <dd className={ratio ? 'num' : 'num muted'}>{ratio ?? '—'}</dd>
          </div>
        )}
        <div>
          <dt>위험도</dt>
          <dd className={riskText ? `rt__risk rt__risk--${risk!.toLowerCase()}` : 'muted'}>
            {riskText ? (
              <>
                {riskText.withIcon ? (
                  // §2.5 (b) — 라벨이 바로 옆에 있으므로 aria-hidden.
                  <span className="rt__risk-icon">
                    <Icon glyph={AlertTriangle} size="inline" />
                  </span>
                ) : null}
                {riskText.text}
              </>
            ) : (
              '—'
            )}
          </dd>
        </div>
        <div>
          <dt>다음 경계까지</dt>
          <dd>{margin.text}</dd>
        </div>
      </dl>

      {/*
        스케일 바는 격자 밖에 둔다 — 한 항목의 부속이 아니라 **위 세 값이 놓인 축**
        이고, 폭도 카드 전체를 써야 눈금이 읽힌다(`VoyageCiiResult`와 같은 배치).

        `boundaries`가 없거나 `required_cii`가 0이면 `scale`이 `null`이다. 그때는
        바를 아예 만들지 않는다 — 컴포넌트에 넘겨 「못 읽는다」를 적게 하면, 값이
        원래 없는 상태(실적 없음)까지 오류처럼 보인다.
      */}
      {drawsBar && scale && ytd.ratioToRequired && ratio ? (
        <GradeScaleBar
          ratioToRequired={ytd.ratioToRequired}
          boundaries={scale}
          rating={rating}
          valueLabel={ratio}
          label="연간 누적 CII의 등급 스케일"
        />
      ) : null}
      {/*
        「왜 이 등급인가」의 출발점 (#1516 · `#1239` 결정 B·D). 기준값은 `a`·`c` ×
        (1 − Z/100)에서 오는데 그 상수가 어디에도 보이지 않았다 — 설정의 「규제 기준값」
        절로 잇는다. 종전에는 「기준 (required)」 칸 아래 있었고, `#1949`가 그 칸을
        결론 띠로 올리면서 **등급 스케일 옆으로 옮겼다** — 경계값을 그리는 자리가
        그 상수를 가장 가까이 쓰는 자리다.
      */}
      <p className="rt__scale-source">
        <Link className="rt__figure-link" to={regulationParametersPath()}>
          기준값 근거
        </Link>
      </p>
    </div>
  )
}

function VoyagePanel({
  data,
  unit,
  vesselId,
}: {
  data: RealtimeCii
  unit: string
  vesselId?: string
}) {
  const voyage = data.currentVoyage!
  const ratio = voyageProgressRatio(data)
  const remaining = remainingDistanceNm(data)
  // 항구는 저장값(`BUSAN`)이 아니라 **보이는 이름**으로 적는다 (#1776). 선박 상세의 항차 표가
  // `#1742`에서 이미 그렇게 하므로, 같은 항차가 두 화면에서 다른 이름으로 보이지 않게 한다.
  // 목록에 없는 항구와 목록을 아직 받지 못한 때는 입력한 그대로다(`portDisplayName`).
  const ports = useSamplePorts()
  const portName = (stored: string | null | undefined) =>
    stored === null || stored === undefined ? '—' : portDisplayName(ports, stored)

  return (
    <>
      <p className="rt__voyage-title">
        {voyage.voyageNo ?? '항차'} · {portName(voyage.departurePortName)} →{' '}
        {portName(voyage.arrivalPortName)}
      </p>

      {ratio !== null ? (
        /*
         * 진행률에는 **값도 함께** 알린다 (#829 ⑸b). `aria-label`만으로는 「항해
         * 진행률」이라는 이름만 읽히고 **몇 퍼센트인지는 읽히지 않았다.**
         * `role="progressbar"`와 `aria-valuenow`가 짝이다.
         */
        <div
          className="rt__progress"
          role="progressbar"
          aria-label="항해 진행률"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Number(formatPercent(toDecimalInput(ratio)))}
          aria-valuetext={`${formatPercent(toDecimalInput(ratio))}%`}
        >
          <div className="rt__progress-bar" style={{ inlineSize: `${ratio * 100}%` }} />
          {/*
            `§4.2` 「비율」 — 백분율 1자리. `Math.round(ratio * 100)`은 화면이
            직접 셈하는 것이라 규정 자릿수와 무관하게 정수로 떨어졌다.
          */}
          <span className="rt__progress-text num">{formatPercent(toDecimalInput(ratio))}%</span>
        </div>
      ) : null}

      <dl className="ytd__figures rt__voyage-figures">
        <Figure
          label="누적 거리"
          value={formatOrNull(voyage.distanceNm, (v) =>
            formatGrouped(v, DISPLAY_DIGITS.distanceNm),
          )}
          suffix={` ${DISPLAY_UNITS.distance}`}
        />
        {/*
          계획이 없으면 「남은 거리」를 만들지 않는다 — 0은 「다 왔다」로 읽힌다.
          `remainingDistanceNm`은 뺄셈을 하느라 숫자를 내주므로 여기서 문자열로
          되돌려 같은 포매터를 태운다. 그 함수의 반올림은 계산 보조라 건드리지 않는다.
        */}
        <Figure
          label="남은 거리"
          value={formatOrNull(remaining === null ? null : String(remaining), (v) =>
            formatGrouped(v, DISPLAY_DIGITS.distanceNm),
          )}
          suffix={` ${DISPLAY_UNITS.distance}`}
        />
        <Figure
          label="누적 연료"
          value={formatOrNull(voyage.fuelTon, (v) =>
            formatGrouped(v, DISPLAY_DIGITS.fuelTon),
          )}
          suffix={` ${DISPLAY_UNITS.fuel}`}
        />
        <Figure
          label="항해 시간"
          value={formatOrNull(voyage.underwayHours, (v) =>
            formatDecimalString(v, DISPLAY_DIGITS.durationHours),
          )}
          suffix={` ${DISPLAY_UNITS.duration}`}
        />
      </dl>

      <div className="rt__segment">
        <span className="rt__segment-label">구간 CII</span>
        <span className="num rt__segment-value">
          {formatOrNull(voyage.attainedCii, (v) =>
            formatDecimalString(v, DISPLAY_DIGITS.cii),
          ) ?? '—'}
        </span>
        <span className="rt__segment-unit">{unit}</span>
      </div>

      {/*
       * 등급이 없다는 것을 **말로 적는다**(`COR-1`). 배지 자리가 비어 있으면
       * 사용자는 값이 아직 안 왔다고 읽고, 다른 화면의 등급을 여기 갖다 붙인다.
       */}
      <p className="rt__no-rating">
        항차 구간값에는 등급을 붙이지 않습니다. 등급은 <b>연간 누적</b>에만
        해당합니다.
      </p>

      {/*
        이 항차의 실적 입력으로 한 번에 간다 (#1540).

        이 화면은 현장직의 주 화면이고(`UIFLOW §2.2`), 연말 예상의 산출 가정이
        「도착 실적을 입력하면 확정됩니다」라고 말한다. 그런데 입력은 선박 상세의 항차 카드
        사이에만 있어 되돌아가 찾아야 했다. 선박 상세가 이 항차의 입력을 **열어 둔 채**
        그 카드로 데려간다 — 입력을 여기 복제하지 않는다(`voyageActualsPath` 주석).

        **계획 거리를 다 채웠으면(남은 거리 0) 채움 버튼이다** — 그때 이 화면에서 할 다음
        일이 그것뿐이다. 아직 가는 중이면 보조 링크다.
      */}
      {vesselId ? (
        <Link
          className={remaining === 0 ? 'rt__actuals rt__actuals--primary' : 'rt__actuals'}
          to={voyageActualsPath(vesselId, voyage.voyageId)}
        >
          이 항차 실적 입력
        </Link>
      ) : null}
    </>
  )
}

/**
 * ⑴ 현재 누적 등급 — **연말 예상은 여기서 말하지 않는다** (#1555).
 *
 * 종전(`#725`)에는 이 자리에 「현재 누적 → 연말 예상」 전이를 같은 크기 배지 둘로 그렸다.
 * 그런데 ⑶ 카드도 연말 예상 등급을 그려 **같은 값이 두 곳**에 있었고, 여기의 「등급 유지
 * 예상」과 ⑶의 「현재 누적보다 나빠지는 추세」가 나란히 어긋나 읽혔다(하나는 등급, 하나는
 * 값의 방향이었다). `PRD §3.3.8`이 ⑶을 **보조 표시**로 정하므로 연말 예상은 ⑶ 한 곳에서,
 * 등급과 값을 한 문장으로 말한다(`projectionSentence`).
 *
 * 신뢰도 배지는 **현재 누적 등급 옆**에 붙는다 (`DESIGN_SYSTEM §8` · `#485` ⑤). 대체가
 * 일어난 것은 YTD 집계의 입력이다. 판정은 `§8.1`을 구현한 `hasSubstitutedInputs`가 소유한다.
 */
/**
 * 누적이 **실측이 아닌 값으로** 계산됐는가 (#1082 · #1949).
 *
 * 종전 `YtdGrade`는 등급 배지와 이 신뢰도를 함께 들었다. 등급은 결론 띠로 올라갔고,
 * 남은 신뢰도만 여기 둔다 — 추정이 섞였다는 사실은 **재료의 성질**이다.
 * 섞이지 않았으면 아무것도 그리지 않는다.
 */
function YtdConfidence({ data }: { data: RealtimeCii }) {
  if (!hasSubstitutedInputs(data.ytd)) return null
  return (
    <span className="rt__grade-row">
      <DataConfidenceBadge detail={substitutionSummary(data.ytd)} />
      {/* 무엇이 추정인지 선대 단위로 보는 곳 — `UIFLOW 2-11` 진입 조건 「신뢰도 표시」 (#1082). */}
      <Link className="rt__confidence-link" to={SCREEN_BY_ID.DATA_QUALITY.path}>
        {SCREEN_BY_ID.DATA_QUALITY.label}
      </Link>
    </span>
  )
}

/**
 * 연말 예상의 기준 대비 비율·위험도 — `#725`.
 *
 * 표기·클래스는 `YtdAxis`와 같은 것을 쓴다. 같은 뜻의 값을 화면 안에서 두 가지
 * 모양으로 보여 주면, 나란히 놓인 두 카드가 서로 다른 지표처럼 읽힌다.
 */
function ProjectionAxis({ projection }: { projection: YearEndProjection }) {
  const risk = ytdRisk(projection)
  const riskText = risk === null ? null : riskLabel(risk)
  const ratio = formatOrNull(projection.ratioToRequired, (v) => `${formatPercent(v)}%`)

  // 둘 다 없으면 빈 격자만 남는다 — 그 자리는 「값이 0」으로 읽힌다.
  if (ratio === null && riskText === null) return null

  return (
    <dl className="rt__axis-facts rt__axis-facts--projection">
      <div>
        <dt>기준 대비</dt>
        <dd className={ratio ? 'num' : 'num muted'}>{ratio ?? '—'}</dd>
      </div>
      <div>
        <dt>위험도</dt>
        <dd className={riskText ? `rt__risk rt__risk--${risk!.toLowerCase()}` : 'muted'}>
          {riskText ? (
            <>
              {riskText.withIcon ? (
                // §2.5 (b) — 라벨이 바로 옆에 있으므로 aria-hidden.
                <span className="rt__risk-icon">
                  <Icon glyph={AlertTriangle} size="inline" />
                </span>
              ) : null}
              {riskText.text}
            </>
          ) : (
            '—'
          )}
        </dd>
      </div>
    </dl>
  )
}

function ProjectionPanel({ data }: { data: RealtimeCii }) {
  const { projection } = data

  if (!projection.dataAvailable) {
    // 사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.
    return <p className="rt__nodata">{projectionReason(projection.reason)}</p>
  }

  const sentence = projectionSentence(data)

  return (
    <>
      {/*
        ⚠️ **등급 배지와 큰 값을 여기서 걷었다** (#1949).

        종전에는 이 카드가 등급 배지(`lg`)와 값을 크게 들고 있었다 — 「이 카드의 주인공은
        등급이다」가 그때의 판단이었다. `#1949`가 결론 띠를 세우면서 **연말 예상이 띠의
        보조 결론**이 됐고, 같은 등급·같은 값을 한 화면에 두 번 두면 어느 쪽이 결론인지
        흐려진다(검사 「연말 예상 등급은 화면 전체에 한 번이다」가 그 규칙을 이미 잠그고
        있었다 — 이제 그 한 번은 띠다).

        **이 카드에 남는 일은 「무엇이 그 값을 만드는가」다** — 방향 문장 · 기여 요인 ·
        산출 가정. 결론이 아니라 근거를 맡는다.
      */}
      <div className="rt__projection">
        <div>
          {/*
            등급과 값의 방향을 **한 문장**으로 (#1555 · `projectionSentence`). 종전에는 값의
            방향만 여기 있고 등급의 방향은 ⑴ 카드에 있어, 「나빠지는 추세」와 「등급 유지」가
            떨어진 두 자리에서 어긋나 읽혔다.
          */}
          {sentence ? (
            <p className={`rt__direction rt__direction--${sentence.tone.toLowerCase()}`}>
              {sentence.text}
            </p>
          ) : null}
        </div>
      </div>

      {/*
       * ⑴ 누적과 **같은 축**을 붙인다 (`#725`). 서버는 연말 예상에도
       * `ratio_to_required`·`risk_level`을 싣는데 화면이 읽지 않아, 위 카드는
       * 「기준 대비 155.5% · 심각」이고 이 카드는 CII 숫자와 추세 문구뿐이었다.
       * 축이 다르면 두 등급을 나란히 놓아도 **얼마나 벌어졌는지**를 셀 수 없다.
       *
       * 스케일 바는 여기 두지 않는다 — `boundaries`는 YTD에만 실리고, 연말 예상의
       * 경계를 YTD 것으로 대신 그리면 다른 값의 눈금을 빌려 쓰는 것이 된다.
       */}
      <ProjectionAxis projection={projection} />

      {/*
       * 가정을 함께 보여 준다 — `PRD §3.3` ⑶ 요구. 이 값이 무엇을 전제로 나온
       * 것인지 없으면 확정값처럼 읽힌다.
       */}
      {/*
       * ⑶에만 붙는 경고 (`#798`). 최상위 경고 목록과 **범위가 다르다** — 이쪽은
       * 「이 값이 어떤 성격인가」를 말한다. 특히 잔여 계획이 0건이면 ⑶이 ⑴과 같은
       * 값이 되는데, 그 사실을 말하지 않으면 종전 결함(항상 ⑴과 같음)과 화면에서
       * 구분되지 않는다.
       */}
      {projection.warnings.length > 0 ? (
        <ul className="rt__projection-warnings">
          {projection.warnings.map((code) => (
            <li key={code}>
              <span><Icon glyph={AlertTriangle} size="inline" /></span> {warningMessage(code)}
            </li>
          ))}
        </ul>
      ) : null}

      <ProjectionDrivers projection={projection} />

      {projection.assumptions ? (
        <details className="rt__assumptions">
          <summary>산출 가정</summary>
          <dl>
            <div>
              <dt>방식</dt>
              {/* `#798` — 종전에는 「지금까지의 일평균이 연말까지 이어진다고 가정」이었다.
                  그 방식은 거리·연료를 같은 비율로 더해 ⑶이 구조적으로 ⑴과 같아졌다. */}
              <dd>확정 실적에 잔여 계획 항차를 더한다 (남은 거리 기반)</dd>
            </div>
            <div>
              <dt>잔여 계획</dt>
              <dd className="num">
                {projection.assumptions.remainingVoyageCount ?? '—'} 건 /{' '}
                {/* `§4.2` 일수 0자리 (#592). 서버 값을 가공 없이 내보내면
                    `231.64 일`이 나가 같은 표 안에서 규율이 갈린다. */}
                {formatOrNull(projection.assumptions.remainingDays, (v) =>
                  formatDecimalString(v, DISPLAY_DIGITS.days),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.day}
              </dd>
            </div>
            <div>
              <dt>잔여 계획 거리 / CO₂</dt>
              <dd className="num">
                {formatOrNull(projection.assumptions.plannedDistanceNm, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.distanceNm),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.distance} /{' '}
                {/*
                  ⚠️ **CO₂에는 CO₂ 단위·자릿수를 쓴다** (`#1095` ⑴ · `DESIGN_SYSTEM §4.2`).
                  종전에는 연료 쪽(`fuel`·`fuelTon`)을 쓰고 있어 **CO₂ 값에 `t`가
                  붙었다.** 같은 화면의 「누적 CO₂」는 `tCO₂`라 한 화면 안에서 규율이
                  갈렸고, `format.ts`의 주석이 그 구분의 이유를 이미 적고 있다 —
                  「둘 다 `t`면 무엇의 질량인지 구분되지 않는다」.
                */}
                {formatOrNull(projection.assumptions.plannedCo2Ton, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.co2Ton),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.co2}
              </dd>
            </div>
            <div>
              <dt>확정 실적 거리 / CO₂</dt>
              <dd className="num">
                {formatOrNull(projection.assumptions.completedDistanceNm, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.distanceNm),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.distance} /{' '}
                {/* 위 「잔여 계획 거리 / CO₂」와 같은 자리 (`#1095` ⑴). */}
                {formatOrNull(projection.assumptions.completedCo2Ton, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.co2Ton),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.co2}
              </dd>
            </div>
          </dl>
        </details>
      ) : null}
    </>
  )
}
