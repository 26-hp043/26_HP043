import { ArrowLeft } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApplicabilityBadge } from '../../components/ApplicabilityBadge'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { useShellContext } from '../../layout/shellContext'
import { NotUnderwayPanel } from '../not-underway/NotUnderwayPanel'
import { VoyagePanel } from '../voyage-management/VoyagePanel'
import { ACTUALS_PARAM } from '../voyage-management/voyageRules'
import { ciiUnit } from '../voyage-cii/resultRules'
import { shipTypeLabel } from '../vessel-registration/shipTypes'
import { detailStatusText } from '../fleet/fleetRules'
import { PositionChart } from '../fleet/PositionChart'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  DISPLAY_UNIT_DAILY_FUEL,
  formatCapacity,
  formatDecimalString,
  formatGrouped,
  formatPercent,
  formatTimestamp,
  toDecimalInput,
} from '../../display/format'
import { CiiHistoryChart } from './CiiHistoryChart'
import { createApiVesselDetailProvider, VesselDetailError } from './apiProvider'
import { PositionForm } from './PositionForm'
import { VerdictStrip } from '../../components/VerdictStrip'
import { Tabs, type TabDef } from '../../components/Tabs'
import { currentTab, TAB_PARAM, VESSEL_TABS, type VesselTabId } from './vesselTabs'
import { voyageProgress } from './types'
import type {
  CiiYear,
  InProgressVoyage,
  VesselDetail as Detail,
  VesselDetailProvider,
  VesselSpec,
} from './types'
import './VesselDetail.css'
import { ErrorState } from '../../components/ErrorState'
import { SCREEN_BY_ID } from '../../screens'
import { CURRENT_VOYAGE_SEGMENT, voyagePath } from '../../layout/globalContext'
import { voyageCountText } from './voyageCount'
import { CalculationHistory } from './CalculationHistory'
import { Icon } from '../../components/Icon'

/**
 * 상세 화면 지도의 최소 표시 범위(도) — 약 1,500km (#723).
 *
 * 배 한 척뿐이라 범위를 데이터가 정하지 못한다. 좁게 잡으면 해안선이 사라지고
 * (`landOutline.ts`가 0.6° 허용 오차로 단순화돼 있다), 넓게 잡으면 배가 점이 된다.
 *
 * 14°는 부산을 중심에 놓았을 때 **한반도 전체와 일본 서안이 함께 들어오는** 범위다 —
 * 「이 배가 어디 있나」에 답하는 데 필요한 최소한의 배경이다.
 */
const DETAIL_MAP_SPAN = 14

/**
 * 선박 상세 — `UIFLOW v2.0` 2-8 · `#356`.
 *
 * 3계층(선대 → 선박 → 항차)의 **허리**다. 대시보드에서 내려오고 실시간 CII로 내려간다.
 *
 * ## 올해 값을 이력에서 가져온다
 *
 * `GET /vessels/{id}/cii-history`가 올해 행을 `status: "IN_PROGRESS"`로 함께 준다.
 * `#354`의 3종 값 엔드포인트를 따로 부르지 않는 이유는, **같은 값을 두 곳에서 받으면
 * 어긋났을 때 어느 쪽이 맞는지 판단해야 하기 때문**이다.
 *
 * ## 단위를 화면이 만들지 않는다
 *
 * `gCO₂/(DWT·nm)`과 `gCO₂/(GT·nm)`은 선종에 따라 갈린다(`DESIGN_SYSTEM §4.1` 🔒).
 * 축은 **서버가 준 `transport_capacity_basis`**를 쓴다. 화면이 선종에서 유추하면
 * 선종이 늘 때 서버와 갈라지고, **크루즈선에 `DWT`가 표시돼도 화면은 깨지지 않는다.**
 */
export function VesselDetail({
  provider: injected,
}: {
  /** 테스트가 갈아 끼운다 — `NotUnderwayPanel`이 같은 형태를 쓴다 (`#588`). */
  provider?: VesselDetailProvider
} = {}) {
  const { vesselId } = useParams()
  // 실시간 CII의 「이 항차 실적 입력」 (#1540 · `voyageActualsPath`)
  const [searchParams, setSearchParams] = useSearchParams()
  const openActualsFor = searchParams.get(ACTUALS_PARAM)
  /*
   * 탭의 자리는 **주소가 갖는다** (`DESIGN_SYSTEM §8` · #1774). 화면 상태로 두면
   * `?actuals=`로 들어온 링크가 개요에 떨어지고, 뒤로 가기가 탭을 건너뛴다.
   */
  const tab = currentTab(searchParams)
  const selectTab = useCallback(
    (id: string) => {
      // 밀어 넣는다(`replace`가 아니다) — 뒤로 가기가 직전 탭으로 돌아가야 한다.
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set(TAB_PARAM, id)
        return next
      })
    },
    [setSearchParams],
  )
  const [detail, setDetail] = useState<Detail | null>(null)
  /*
   * provider를 매 렌더마다 새로 만들지 않는다. 로딩과 위치 저장이 같은
   * `fetch`·`baseUrl`을 써야 테스트가 하나만 갈아 끼워도 둘 다 대체된다 —
   * `voyage-management`가 연료 provider에 같은 것을 넘기는 이유와 같다.
   */
  const [created] = useState(() => createApiVesselDetailProvider())
  const provider = injected ?? created
  const [failure, setFailure] = useState<{ message: string; notFound: boolean } | null>(
    null,
  )
  /**
   * 진행 중 항차 (`#588`). `'loading'`을 값으로 둔다 — **「아직 모른다」와 「없다」를
   * 같게 그리면 확인 전에 없다고 단정**하게 되고, 그것이 이 이슈가 고치는 거짓
   * 신호의 반대 방향 판본이다.
   */
  const [inProgress, setInProgress] = useState<InProgressVoyage | null | 'loading'>(
    'loading',
  )

  /**
   * 아래 패널이 데이터를 바꾸면 올린다 (`#1647` · `#1648`).
   *
   * 항차(상태 전환·실적 입력·생성)와 정박 기록(구간·연료)은 **이 화면의 누적 CII·요약·실시간
   * CII 진입 조건**을 바꾸는데, 패널은 자기 목록만 갱신했다. 그래서 새로고침하기 전까지 위쪽
   * 숫자가 옛 항차 집합의 것이었다. 여기서 두 조회를 다시 부른다 — 패널이 부모를 직접 고치지
   * 않고 **바뀌었다는 사실만** 알린다.
   */
  const shell = useShellContext()
  const [changeCount, setChangeCount] = useState(0)
  const noteChanged = useCallback(() => setChangeCount((count) => count + 1), [])

  /*
   * 비우는 것은 **배가 바뀔 때만**이다 (#1811). 종전에는 아래 조회 effect가 `changeCount`에도
   * 반응하면서 시작마다 `setDetail(null)`을 했다 — 자식이 `noteChanged()`를 부를 때마다 화면
   * 전체가 로딩으로 교체돼, 더 보기로 받은 행과 쓰다 만 실적 입력이 사라지고 `?actuals=`로
   * 들어온 폼이 다시 열렸다. 다시 부르는 동안에는 그려진 상세를 그대로 두고 값만 갈아 끼운다.
   */
  useEffect(() => {
    setDetail(null)
    setFailure(null)
    setInProgress('loading')
  }, [vesselId, provider])

  useEffect(() => {
    if (!vesselId) return
    let alive = true

    provider
      .load(vesselId)
      .then((data) => {
        if (!alive) return
        setDetail(data)
        setFailure(null)
      })
      .catch((error: unknown) => {
        if (!alive) return
        setFailure({
          message:
            error instanceof Error ? error.message : '선박 정보를 불러오지 못했습니다.',
          notFound: error instanceof VesselDetailError && error.notFound,
        })
      })

    return () => {
      alive = false
    }
  }, [vesselId, provider, changeCount])

  /*
   * 진행 중 항차도 `changeCount`에 반응한다 (#1811). 항차 상태 전환은 이 조회의 답을 바꾸는데
   * deps에 없어 헤더가 새로고침 전까지 옛 항차를 보였다(`#1647`). 다시 부를 때 `'loading'`으로
   * 되돌리지 않는다 — 위와 같은 이유로, 답을 아는 동안 「확인 중」으로 물러서지 않는다.
   */
  useEffect(() => {
    if (!vesselId) return
    let alive = true

    provider
      .findInProgressVoyage(vesselId)
      .then((voyage) => {
        if (alive) setInProgress(voyage)
      })
      .catch(() => {
        // 조회가 실패하면 **링크를 그리지 않는다.** 실패를 「있다」로 읽으면
        // 이 이슈가 고치는 거짓 신호가 그대로 돌아온다.
        if (alive) setInProgress(null)
      })

    return () => {
      alive = false
    }
  }, [vesselId, provider, changeCount])

  // 다시 부르기가 실패해도 이미 그려진 상세를 오류 화면으로 바꾸지 않는다 (#1811).
  if (failure && !detail) {
    return (
      <div className="vd">
        <BackLink />
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

  if (!detail) {
    return (
      <div className="vd" aria-busy="true">
        <BackLink />
        <p className="fleet__loading">선박 정보를 불러오는 중입니다…</p>
      </div>
    )
  }

  const { vessel, years, capacityBasis } = detail
  const unit = ciiUnit(capacityBasis)
  // 올해 = 목록의 마지막 행(서버가 from~to 오름차순으로 준다).
  const current = years.length > 0 ? years[years.length - 1] : null

  /*
   * ── 탭 넷에 들어가는 것 (`UIFLOW 2-8` · `DESIGN_SYSTEM §8` · #1774) ──────
   *
   * `Tabs`가 **그 탭을 처음 열 때** 부른다 — 열지 않은 탭은 마운트되지 않으므로 그 탭의
   * 조회도 나가지 않는다. 종전에는 마운트 한 번에 요청 24건(경로 10종)이 나갔다.
   *
   * 한 번 연 뒤에는 `hidden`으로 감출 뿐이라 쓰다 만 실적 입력이 탭을 오가며 날아가지
   * 않는다(`§8`).
   */
  const panels: Record<VesselTabId, () => ReactNode> = {
    overview: () => (
      <div className="vd__split">
        {/* ── 연도별 이력 ────────────────────────────────────────── */}
        <section className="card vd__main" aria-label="연도별 CII 이력">
          <div className="card__head">
            <h2 className="card__title">연도별 CII 이력</h2>
            <span className="card__meta">단위 {unit}</span>
          </div>
          <CiiHistoryChart years={years} basis={capacityBasis} />
        </section>

        {/* ── 제원 · 현재 상태 ───────────────────────────────────── */}
        <div className="vd__side">
          {/*
            제원과 현재 상태를 한 면에 담는다 (#1729 · `DESIGN_SYSTEM §5` 카드 예산).
            둘 다 「이 배가 어떤 배이고 지금 무엇을 하고 있나」라 한 덩어리로 읽힌다 —
            면을 둘로 나눌 이유가 값의 출처뿐이었다.
          */}
          <section className="card" aria-label="선박 제원 · 현재 상태 · 위치">
            <div className="card__head">
              <h2 className="card__title">제원</h2>
            </div>
            <dl className="spec">
              <Spec label="선종" value={shipTypeLabel(vessel.shipType)} />
              <Spec label="IMO 번호" value={vessel.imoNumber} />
              {/* 축에 해당하는 제원을 앞에 둔다 — 그 값이 CII 분모다. */}
              {/*
                `Spec`은 값을 그대로 그린다 — 포맷 지점이 없어 서버 문자열
                `6405.77`이 그대로 나갔고, 같은 값이 선박 관리 목록에서는
                `6,405.77`이었다. `§4.2` 규정을 거치게 한다 (`#633`).
              */}
              {capacityBasis === 'DWT' ? (
                <Spec label="재화중량톤수 (DWT)" value={formatCapacity(vessel.deadweight)} />
              ) : (
                <Spec label="총톤수 (GT)" value={formatCapacity(vessel.grossTonnage)} />
              )}
              {/*
                `#822` — 종전에는 서버 문자열을 **그대로** 그리고 단위를 리터럴로
                박았다. `18.00`이 이 화면에서는 `18`, 선박 관리 목록에서는 `18.0 kn`이
                되어 같은 값이 화면마다 달랐다. 단위 리터럴은 `DESIGN_SYSTEM §4.2` 🔒가
                금지한다 — *「화면에 리터럴로 박지 않는다」*.
              */}
              <Spec
                label="기준 속력"
                value={
                  vessel.referenceSpeedKn === null
                    ? null
                    : formatDecimalString(vessel.referenceSpeedKn, DISPLAY_DIGITS.speedKn)
                }
                suffix={` ${DISPLAY_UNITS.speed}`}
              />
              {/*
                연료는 `GROUPED_FIELDS`라 천단위 구분자가 필수다 (`§4.2` 🔒) —
                `1234.5 t`가 아니라 `1,234.5 t`다.
              */}
              <Spec
                label="기준 일일 연료"
                value={
                  vessel.referenceDailyFocTon === null
                    ? null
                    : formatGrouped(vessel.referenceDailyFocTon, DISPLAY_DIGITS.fuelTon)
                }
                suffix={` ${DISPLAY_UNIT_DAILY_FUEL}`}
              />
              <Spec label="기본 연료" value={vessel.defaultFuelType} />
            </dl>

            <div className="card__head vd__subhead">
              <h3 className="card__title">현재 상태</h3>
            </div>
            <dl className="spec">
              <Spec label="운항 상태" value={stateText(vessel.underwayState)} />
              {/* `UIFLOW 2-4`가 정한 7값 표기. 코드를 그대로 내지 않는다. */}
              <Spec label="세부 상태" value={detailStatusText(vessel.detailStatus)} />
              {/*
                「현재 위치」·「위치 갱신」 두 줄은 아래 **현재 위치 절**로 옮겼다
                (#723 — 그때는 따로 떠 있는 카드였고, #1774가 같은 카드 안으로 합쳤다). 좌표 숫자와 그 좌표의 그림이 따로 있으면 같은 사실이 두 군데에
                놓인다 — 그리고 개략도가 이미 그 값을 자기 밑에 적는다.

                이 카드에는 **무엇을 하고 있나**만 남는다.
              */}
            </dl>

            {/*
              ── 현재 위치 ─────────────────────────────────────────────

              종전에는 **따로 떠 있는 카드**였다(#723 · #1729). 탭으로 나누며 개요 탭의
              면이 다섯이 되어 `§5` 카드 예산(4개 이하)을 하나 넘었고, 합칠 자리는
              `#1729`가 이미 적어 두었다 — **「같은 배를 설명하는 값들이다」**. 제원 ·
              현재 상태 · 위치는 한 덩어리로 읽힌다 (#1774).

              수정 입구(아래 「위치 · 상태 수정」)는 **지도 뒤**에 둔다 — 무엇이 어디
              있는지 본 다음에 고치는 순서다.
            */}
            <div className="card__head vd__subhead">
              <h3 className="card__title">현재 위치</h3>
              {vessel.positionUpdatedAt ? (
                <span className="card__meta">
                  {formatTimestamp(vessel.positionUpdatedAt)} 기준
                </span>
              ) : null}
            </div>

            {/*
              대시보드와 **같은 컴포넌트**를 쓴다. 베끼면 두 화면의 투영·등급색·결측
              표기가 갈리고, 갈린 쪽이 어디인지 화면을 봐서는 알 수 없다.

              **자산이 있어도 개략도다** (`#1264`). 대시보드는 `basemap`을 보고
              타일 지도(`FleetMap`)로 올라가지만 이 카드는 그 분기에 참여하지 않는다 —
              폭이 480이고 그리는 대상이 **한 척**이라, 그 크기의 타일 지도는 배 하나와
              둘레 바다만 비춘다. 배경이 주는 맥락이 거의 없는데 지도 인스턴스 비용만 든다.

              ⚠️ 같은 기기에서 대시보드는 지도, 여기는 개략도로 보인다. **고장이 아니다** —
              갈리는 축은 자산이 아니라 **대상 수(선대 ↔ 한 척)**다. 규격은
              `DESIGN_SYSTEM §9.5`에 있다.

              좌표를 따로 적지 않는다 — 개략도가 자기 밑에 「위치 30.6°N, 32.3°E」로
              이미 적는다. 여기서 또 적으면 같은 값이 두 군데가 된다.

              `minSpan`을 넓히는 이유는 그 프롭 주석에 있다.
            */}
            {vessel.lat && vessel.lon ? (
              <div className="vd__map">
                <PositionChart
                  vessels={[
                    {
                      id: vessel.id,
                      name: vessel.name,
                      lat: vessel.lat,
                      lon: vessel.lon,
                      // 배 색·무늬는 올해 누적 등급이다 — 없으면 중립색으로 떨어진다.
                      ytdRating: current?.rating ?? null,
                    },
                  ]}
                  minSpan={DETAIL_MAP_SPAN}
                />
              </div>
            ) : (
              /*
                **「못 불러왔다」가 아니라 「입력된 적이 없다」**를 적는다. 빈 상자를
                두면 앞의 뜻으로 읽히고, 사용자는 기다린다(`#705`가 대시보드에서 같은
                구분을 세웠다). 무엇을 하면 뜨는지도 함께 적는다.
              */
              <p className="vd__nodata">
                위치가 기록되지 않았습니다. 아래 「위치 · 상태 수정」에서 입력하면
                여기에 표시됩니다.
              </p>
            )}

            {/*
             * 위치·상태 입력 (`API_SPEC §2.6` · `#369`). 이 카드는 네 값을 보여
             * 주면서 **읽기만 가능했다** — 쓰는 경로가 없어 위치가 시드 이후
             * 고정됐고, 대시보드 `PositionChart`가 빈 채로 떴다.
             *
             * 정박 **구간 기록**은 아래 `NotUnderwayPanel`이 소유한다. 여기서 바꾸는
             * 것은 「지금 무엇을 하고 있나」라는 **표시 상태**뿐이다 — 세부 상태 6값이
             * `period_type`과 같은 집합인 것은 그 둘이 같은 사실을 가리키기 때문이지
             * 한쪽이 다른 쪽을 쓰기 때문이 아니다.
             */}
            <PositionForm
              vessel={vessel}
              provider={provider}
              onSaved={(updated: VesselSpec) => {
                setDetail((prev) => (prev ? { ...prev, vessel: updated } : prev))
                // 상단 선택기의 목록·기본 제원도 이 값으로 바뀌어야 한다 (`#1643`).
                shell.refreshVessels()
              }}
            />

          </section>

        </div>
      </div>
    ),
    voyages: () => (
      <>
      {/*
        ── 항차 기록은 전폭 (#1729) ─────────────────────────────────────

        `#723`이 「연도별 이력 · 제원」 / 「항차 기록 · 현재 위치」 두 줄을 같은 7:5로
        나눠 두었다. 항차 기록이 표가 되면서(#1729) 7열이 7/12 칸(1440에서 약 614px)에
        들어가지 않아 오른쪽 두 열이 가로 스크롤 뒤로 숨었다 — 표를 전폭으로 두고,
        위치 카드는 위 기둥(제원 · 현재 상태)으로 올렸다. 같은 배를 설명하는 값들이다.
      */}
      <VoyagePanel vesselId={vessel.id} openActualsFor={openActualsFor} onChanged={noteChanged} />
      </>
    ),
    'not-underway': () => (
      <>
      {/*
       * 정박 기록 입력 (#370). 선박 상세 아래에 두는 이유는, 이 기록이 바로 위
       * 「올해 누적」의 분자를 늘리기 때문이다 — 값을 본 자리에서 고칠 수 있어야 한다.
       */}
      {/*
        항차가 먼저다 — 정박·묘박은 항차와 항차 사이의 구간이라,
        운항 기록을 위에서 아래로 읽으면 순서가 이렇게 된다.
      */}
      <NotUnderwayPanel vesselId={vessel.id} onChanged={noteChanged} />
      </>
    ),
    calculations: () => (
      <>
      {/*
        계산 이력 · 재계산 필요 표시 (#992 · `PRD §8.4`). 운항 기록(항차 · 정박) 아래에 두는
        이유 — 그 기록을 고치면 여기 계산이 「재계산 필요」로 바뀐다. 원인 아래에 결과를 둔다.
      */}
      <CalculationHistory vesselId={vessel.id} />
      </>
    ),
  }

  return (
    <div className="vd">
      <BackLink />

      <header className="vd__head">
        <div>
          <h1 className="vd__title">
            {vessel.name}
            {/*
              선박 상세는 이 배의 제원을 확인하러 오는 자리다 (`#653`).
              적용 대상 여부가 여기 없으면, 아래 YTD·등급을 규제 결과로 읽게 된다.
            */}
            <ApplicabilityBadge
              isCiiApplicableHint={vessel.isCiiApplicableHint}
              grossTonnage={vessel.grossTonnage}
              vesselName={vessel.name}
            />
          </h1>
          <p className="vd__sub">
            IMO {vessel.imoNumber} · {shipTypeLabel(vessel.shipType)}
          </p>
          {/*
            기준 시각은 선명 쪽에 둔다 (#1415). 오른쪽에 실시간 CII 입구가 올라온 뒤 그 아래에
            두었더니 입구 상태에 따라 위치가 오르내렸다. 「이 배의 값이 언제 기준인가」는 배를
            설명하는 줄이므로 식별 정보 바로 아래가 제자리다.
          */}
          {detail.asOf ? (
            <p className="vd__asof">
              기준 {formatTimestamp(detail.asOf)}
            </p>
          ) : null}
        </div>
        {/*
          진행 중 항차로 내려가는 경로 (#1415). `UIFLOW 2-9`(실시간 CII)는 사이드바에 없고
          **이 화면에서만** 들어간다(`UIFLOW 2-9` 진입 조건). 종전에는 그 유일한 입구가 페이지
          중간 「현재 상태」 카드 안에 있어, 현장직의 주 화면으로 가는 길이 첫 화면에 없었다.

          머리에 두되 `PageHeader`는 쓰지 않는다 — 드릴다운 화면은 자체 머리를 쓴다
          (`PageHeader.tsx` 「쓰지 않는 자리」). 항차 목록을 여기서 따로 부르지 않는 것은
          종전과 같다 — 실시간 화면(#357)이 자기 데이터를 스스로 가져오는 편이 경계가 맞다.
        */}
        <div className="vd__head-side">
          {/*
            링크를 `underwayState`로 그리지 않는다 (`#588`).

            그 값은 **표시 상태**이고 진행 중 항차의 존재와 별개다 — 운항 중으로
            표시된 선박에 항차가 없는 상태가 실제로 있었고(`#587`), 그때
            **사용자는 「있다」고 읽고 눌렀는데 없었다.**

            없을 때 입구를 **감추지 않는다.** `#419`가 *「등급이 없는 이유를 읽어 주지
            않으면 사용자는 무엇을 해야 하는지 알 수 없다」*로 같은 판단을 했다.

            ## 없을 때는 누르면 말풍선으로 사유를 낸다 (#1415)

            종전에는 비활성 상자 + 상자 안 사유였다. 머리로 올라온 뒤 그 모양이 셋 다 맞지
            않았다 — 사유를 넣으면 상자가 세 줄로 커졌고, 흐린 채움으로 줄이면 사유가 버튼과
            따로 놀았다. 버튼은 링크 상태와 같은 모양으로 두고, 누르면 **왜 못 여는지와 무엇을
            하면 열리는지**를 말풍선으로 낸다. `#588`이 막은 「있다고 읽고 눌렀는데 **아무 일도
            없었다**」는 누른 자리에서 답이 나오므로 되살아나지 않는다. `DESIGN_SYSTEM §14`
            「비활성 컨트롤은 「왜」를 함께 낸다」의 예외다 — 이 자리는 비활성 컨트롤이 아니라
            **누르면 사유를 내는 버튼**이다.
          */}
          {inProgress === 'loading' ? (
            <span className="vd__drill vd__drill--off" aria-busy="true" role="status">
              진행 중 항차 확인 중…
            </span>
          ) : inProgress === null ? (
            <NoVoyageDrill />
          ) : (
            <Link className="vd__drill" to={voyagePath(vessel.id, CURRENT_VOYAGE_SEGMENT)}>
              진행 중 항차의 실시간 CII 보기
            </Link>
          )}
        </div>
      </header>

      {/*
        ── 선박 바 = 결론 띠 (`DESIGN_SYSTEM §8.6` 🔒 · #1729) ─────────────

        이 화면의 답은 **올해 누적 등급과 값**이다. 종전에는 YTD 카드 안에서 등급 배지 ·
        실적 · 기준 · 완료 항차가 **네 칸에 같은 무게**로 놓여, 무엇이 답이고 무엇이 딸린
        수치인지 보이지 않았다.

        보조는 진행 중 항차의 진행률이다(`§8.6` 표). 위험도 pill은 두지 않는다 —
        `API_SPEC §2.7` 연도별 이력에 `risk_level`이 없고, 없는 값을 다른 경로에서
        더 불러오지 않는다(`§8.6` · #1728).
      */}
      {current?.dataAvailable ? (
        <VerdictStrip
          label="올해 누적 CII"
          main={{
            label: `올해 누적 (YTD) · ${current.regulationYear}년`,
            value: ytdValueText(current),
            unit,
            rating: current.rating,
            ratingLabel: current.rating
              ? `올해 누적 등급 ${current.rating}`
              : '올해 누적 등급 없음',
          }}
          sub={progressSlot(inProgress)}
        />
      ) : (
        <section className="card" aria-label="올해 누적 CII">
          <h2 className="card__title">올해 누적 (YTD)</h2>
          <p className="vd__nodata">{noDataText(current)}</p>
        </section>
      )}

      {/*
        띠 아래 한 줄 — 완료 항차 수 · 단위 · 고지 (`§8.6` · #1578). 종전에는 완료 항차가
        등급과 같은 크기의 네 번째 칸이었고, 단위와 고지는 카드 안 별도 줄이었다.
      */}
      <div className="vd__under">
        <p className="vd__under-facts">
          {current?.dataAvailable ? (
            <>
              <span>완료 항차 {voyageCountText(current)}</span>
              <span>단위 {unit}</span>
            </>
          ) : null}
            {/*
              데이터 점검 입구 — 종전에는 YTD 카드 머리에 있었다. 카드가 띠로 바뀌며
              같은 줄(완료 항차 · 단위)로 내려왔다. 비율은 `2-11`이 소유한다(#1082 · #1052 ⑺).
            */}
          <Link to={SCREEN_BY_ID.DATA_QUALITY.path}>{SCREEN_BY_ID.DATA_QUALITY.label}</Link>
        </p>
        <p className="vd__note">
          올해 값은 연중 누적 예측값이며 <b>공식 등급이 아닙니다</b>. 공식 등급은 연말
          DCS 보고·검증 후 확정됩니다.
        </p>
      </div>

      {/*
        ── 탭 넷 (`UIFLOW 2-8` 「화면 구성」 · `DESIGN_SYSTEM §8` · #1774) ─────

        종전에는 **아홉 절이 한 장에** 쌓여 있었다 — 1440 × 900 실측으로 문서 높이
        `2,480px`(2.76 화면) · 떠 있는 면 **8개**(`§5` 카드 예산은 4개 이하) · 마운트 한 번에
        요청 **24건**. 「이 배 지금 어떤가」를 보러 온 사용자가 항차 표 · 가져오기 ·
        내보내기 · 정박 기록 · 계산 이력까지 전부 받아 들었다.

        **제목과 결론 띠는 탭 밖에 남는다**(`§8`) — 이 화면의 답은 탭을 갈아도 같다.
        그래서 탭마다 떠 있는 면을 세면 **탭 밖의 둘(결론 띠 · 면책)이 모든 탭에 들어간다**.
      */}
      <Tabs
        label="선박 상세 구획"
        items={VESSEL_TABS.map((item): TabDef => ({ ...item, render: panels[item.id] }))}
        current={tab}
        onSelect={selectTab}
      />

      <DisclaimerBanner estimate />
    </div>
  )
}

/** 값이 없을 때의 표기 — 빈칸은 「아직 안 온 값」으로 읽힌다. */
const NO_VALUE = '—'

/**
 * 띠의 주 결론 값 — 「실적 / 기준」 한 쌍 (`DESIGN_SYSTEM §8.6` 표의 선박 상세 행).
 *
 * 두 값을 나란히 두는 것이 이 화면의 답이다 — 실적만으로는 등급이 왜 그 등급인지
 * 읽히지 않는다. 값이 없으면 `—`로 적는다(빈칸은 「아직 안 온 값」으로 읽힌다).
 *
 * 자릿수는 `DESIGN_SYSTEM §4.1` 🔒 — CII는 소수 3자리 고정이고 `required_cii`도 같다.
 */
function ytdValueText(year: CiiYear): string {
  const attained =
    year.attainedCii === null ? NO_VALUE : formatDecimalString(year.attainedCii, DISPLAY_DIGITS.cii)
  const required =
    year.requiredCii === null ? NO_VALUE : formatDecimalString(year.requiredCii, DISPLAY_DIGITS.cii)
  return `${attained} / ${required}`
}

/**
 * 띠의 보조 — 진행 중 항차와 진행률 (#1729).
 *
 * 진행률은 **이미 부르고 있는 조회**에서 온다(`findInProgressVoyage`). 계획 거리나 실적
 * 거리가 없으면 막대 없이 항차 번호만 적는다 — 0%로 지어내면 「아직 아무것도 안 갔다」가
 * 되어 없는 사실을 말하게 된다.
 */
function progressSlot(
  inProgress: InProgressVoyage | null | 'loading',
): { label: string; value: string; meter?: { ratio: number; label: string } } {
  const label = '진행 중 항차'
  if (inProgress === 'loading') return { label, value: '확인 중…' }
  if (inProgress === null) return { label, value: '없음' }

  const name = inProgress.voyageNo ?? NO_VALUE
  const ratio = voyageProgress(inProgress)
  if (ratio === null) return { label, value: name }
  return {
    label,
    value: `${name} · ${formatPercent(toDecimalInput(ratio))}%`,
    meter: { ratio, label: '항해 진행률' },
  }
}

function BackLink() {
  return (
    <Link className="vd__back" to="/dashboard">
      <Icon glyph={ArrowLeft} size="inline" />
      대시보드
    </Link>
  )
}

function Spec({
  label,
  value,
  suffix = '',
}: {
  label: string
  value: string | null
  suffix?: string
}) {
  return (
    <div>
      <dt>{label}</dt>
      {/* 값이 없으면 「—」로 둔다. 빈칸이면 항목 자체가 없는 것으로 읽힌다. */}
      <dd className={value ? 'num' : 'num muted'}>{value ? `${value}${suffix}` : '—'}</dd>
    </div>
  )
}

/** 상태 미기록을 「정박」으로 적지 않는다 — 없는 사실이 된다. */
function stateText(state: 'UNDER_WAY' | 'NOT_UNDER_WAY' | null): string | null {
  if (state === 'UNDER_WAY') return '운항 중'
  if (state === 'NOT_UNDER_WAY') return '정박 중'
  return null
}

/** 데이터가 없는 이유를 사유별로 구분해 말한다. */
function noDataText(year: CiiYear | null): string {
  if (year === null) return '표시할 연도가 없습니다.'
  if (year.reason === 'NO_REGULATION_PARAMS') {
    return `${year.regulationYear}년 규정 파라미터가 등록되지 않아 산출할 수 없습니다.`
  }
  return '올해 등록된 항차 실적이 없습니다. 항차를 등록하면 누적값이 계산됩니다.'
}

/**
 * 진행 중 항차가 없을 때의 입구 (#1415) — 누르면 말풍선으로 사유와 여는 방법을 낸다.
 *
 * 말풍선 안은 `role="status"`라 열릴 때 낭독된다. 버튼은 `aria-expanded`·`aria-controls`로
 * 말풍선과 이어진다.
 *
 * 닫는 방식은 계정 메뉴(`AccountMenu.tsx`)를 따른다 — 다시 누르기 · Escape(초점을 버튼으로) ·
 * 바깥 `mousedown`. 면은 오버레이 규격(`§5` 「그림자 + 테두리」)이고 겹침 순서는 드롭다운과 같은
 * `1`이다(`§16` 항목 17 미확정).
 */
function NoVoyageDrill() {
  const [open, setOpen] = useState(false)
  const bubbleId = useId()
  const wrapRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      setOpen(false)
      buttonRef.current?.focus()
    }
    function onDown(event: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  return (
    <div className="vd__drill-wrap" ref={wrapRef}>
      <button
        ref={buttonRef}
        type="button"
        className="vd__drill"
        aria-expanded={open}
        aria-controls={bubbleId}
        onClick={() => setOpen((prev) => !prev)}
      >
        진행 중 항차의 실시간 CII 보기
      </button>
      <div id={bubbleId} className="vd__bubble" role="status" hidden={!open}>
        {open ? (
          <>
            {/*
              줄을 직접 나눈다. 자동 줄바꿈에 맡기면 「「항해 중으로」」처럼 **낫표로 시작하는 줄**이
              생기는데, 낫표는 전각이라 앞이 비어 보여 왼쪽 끝이 들쭉날쭉했다. 이름은 낫표 대신
              글자색으로 짚는다.
            */}
            <b>진행 중 항차가 없습니다.</b>
            <span>
              아래 <em>항차 기록</em>에서 항차를
            </span>
            <span>
              <em>항해 중으로</em> 바꾸면 열립니다.
            </span>
          </>
        ) : null}
      </div>
    </div>
  )
}
