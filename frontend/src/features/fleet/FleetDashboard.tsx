import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { PageHeader } from '../../components/PageHeader'
import { SCREEN_BY_ID } from '../../screens'
import { Link } from 'react-router'
import { ApplicabilityBadge } from '../../components/ApplicabilityBadge'
import { RegulatoryFlags } from '../../components/RegulatoryFlag'
import { GradeDistribution } from './GradeDistribution'
import { VesselMark } from './VesselMark'
import { AnchorIcon, UnderwayChip, UnderwayIcon } from './UnderwayChip'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { PositionChart } from './PositionChart'
/*
 * 지도는 **자산이 있을 때만** 내려받는다 (`#763`).
 *
 * MapLibre가 gzip 기준 약 311 KB다 — 번들에 그냥 넣으면 141 KB였던 첫 로드가
 * 452 KB가 된다. 자산이 없는 환경(개략도로 떨어지는 환경)은 그 311 KB를 받을
 * 이유가 없고, 있는 환경도 **지도를 그릴 차례가 왔을 때** 받으면 된다.
 */
const FleetMap = lazy(() => import('./FleetMap').then((m) => ({ default: m.FleetMap })))
import { BASEMAP_MISSING_NOTICE, hasBasemap } from './basemap'
import { createApiFleetProvider } from './apiProvider'
import {
  daysToDText,
  isAtRisk,
  missingGrossTonnageCount,
  relativeTime,
  soonestDaysToD,
  unavailableHint,
  unavailableText,
  ytdCiiText,
  warningBannerText,
} from './fleetRules'
import { shipTypeLabel } from '../vessel-registration/shipTypes'
import type { FleetSnapshot, FleetSort, FleetVessel } from './types'
import './FleetDashboard.css'

/**
 * 선대 대시보드 — `UIFLOW v2.0` 2-4 · `PRD §6.2 SCR-001` (`#351`).
 *
 * 관리 중심 전환(제16차 회의)으로 **서비스의 중심 화면**이 됐다. 로그인 직후 진입
 * 경로이며, 목적은 하나다 — *"보유 선박 전체에서 위험 선박을 즉시 식별한다"*
 * (`PRD §2.3` 관제 가능성).
 *
 * ## 화면 순서에 이유가 있다
 *
 * ⑴ 경고 배너 → ⑵ KPI → ⑶ 위치·선박 목록 → ⑷ 조치 필요.
 * **위에서 아래로 갈수록 구체적**이다. 「지금 문제가 있나」를 먼저 답하고, 「몇
 * 척인가」를 다음에, 「어느 배인가」, 「무엇을 해야 하나」 순으로 좁힌다.
 *
 * ## 숫자를 화면이 다시 세지 않는다
 *
 * KPI와 위험 판정은 서버(`#350`)가 확정한 값을 그대로 쓴다. 화면이 다시 세면
 * 필터·정렬이 붙었을 때 서버와 달라지는데 **그 차이는 눈으로 발견되지 않는다.**
 *
 * ## 정렬도 서버가 한다 (#772)
 *
 * 선박 목록은 서버가 정렬해 **페이지로 자른다**. KPI·배너·조치는 선대 전체 기준이다. 화면이
 * 받은 페이지를 다시 정렬하면 1쪽의 위험 선박 뒤에 2쪽의 더 위험한 선박이 오는 순서가 된다.
 * 정렬을 바꾸면 첫 페이지부터 다시 받고, 다음 페이지는 첫 페이지의 기준 시각으로 받는다.
 */

const INITIAL_VISIBLE = 6

export function FleetDashboard() {
  const [snapshot, setSnapshot] = useState<FleetSnapshot | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<FleetSort>('risk')
  const [expanded, setExpanded] = useState(false)
  /**
   * 지도 자산이 있는가 (`#763`). `null`은 **아직 모른다**는 뜻이다 — 그동안은
   * 개략도를 그리되 「없다」는 문구를 붙이지 않는다. 잠깐 보였다 사라지는 경고는
   * 사용자에게 **고장으로 읽힌다.**
   */
  const [basemap, setBasemap] = useState<boolean | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const provider = useMemo(() => createApiFleetProvider(), [])

  // 정렬이 바뀌면 첫 페이지부터 다시 받는다 — 서버가 정렬한다(#772).
  useEffect(() => {
    let alive = true
    void hasBasemap().then((found) => {
      if (alive) setBasemap(found)
    })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    let alive = true
    provider
      .load({ sort: sortKey })
      .then((data) => {
        if (alive) setSnapshot(data)
      })
      .catch((error: unknown) => {
        if (alive) {
          setFailure(
            error instanceof Error ? error.message : '선대 현황을 불러오지 못했습니다.',
          )
        }
      })
    return () => {
      alive = false
    }
  }, [provider, sortKey])

  /** 다음 페이지 — 같은 정렬·**첫 페이지의 기준 시각**으로 묻고 뒤에 붙인다. */
  async function loadMore() {
    if (!snapshot?.nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const next = await provider.load({
        sort: sortKey,
        cursor: snapshot.nextCursor,
        asOf: snapshot.asOf,
      })
      setSnapshot((prev) =>
        prev
          ? {
              ...prev,
              vessels: [...prev.vessels, ...next.vessels],
              nextCursor: next.nextCursor,
              hasMore: next.hasMore,
            }
          : prev,
      )
      setExpanded(true)
    } catch (error: unknown) {
      setFailure(error instanceof Error ? error.message : '선대 현황을 불러오지 못했습니다.')
    } finally {
      setLoadingMore(false)
    }
  }

  const vessels = useMemo(() => snapshot?.vessels ?? [], [snapshot])
  // 서버 순서 그대로다(#772) — 다시 정렬하지 않는다.
  const sorted = vessels

  if (failure) return <FleetPlaceholder tone="error" message={failure} />

  if (!snapshot) {
    return (
      <div className="fleet" aria-busy="true">
        <FleetHead />
        <p className="fleet__loading" role="status">
          선대 현황을 불러오는 중입니다…
        </p>
      </div>
    )
  }

  /*
   * 선박 0척은 오류가 아니라 정상 상태다 — 아직 아무것도 등록하지 않은 선사가 처음
   * 보는 화면이다. 0으로 채운 KPI를 보여 주면 「고장」처럼 읽히므로 다음에 할 일을
   * 가리키는 화면으로 대체한다 (`UIFLOW 1-1` 온보딩 흐름).
   */
  if (snapshot.counts.total === 0) {
    return (
      <FleetPlaceholder
        tone="empty"
        message="등록된 선박이 없습니다. 선박을 등록하면 이 화면에서 선대 전체의 CII 등급과 위험 선박을 한눈에 확인할 수 있습니다."
      />
    )
  }

  const { counts } = snapshot
  const banner = warningBannerText(counts.atRisk)
  const soonest = soonestDaysToD(vessels)
  const hasActions = snapshot.actions.length > 0
  const missingGt = missingGrossTonnageCount(vessels)
  const visible = expanded ? sorted : sorted.slice(0, INITIAL_VISIBLE)
  const remaining = sorted.length - visible.length

  return (
    <div className="fleet">
      <FleetHead
        asOf={snapshot.asOf}
        regulationYear={snapshot.regulationYear}
        total={counts.total}
      />

      {/*
       * 경고 배너 — 문구는 `PRD §6.3`이 확정한 원문 그대로다(#352 원문 대조).
       * 위험 선박이 없으면 표시하지 않는다 — 0척 배너를 상시 띄우면 경고가 배경이 된다.
       */}
      {banner ? (
        <section className="warn" role="alert">
          <WarnIcon />
          {/*
            답이 화면 한참 아래 「조치 필요」에 있는데 연결이 없었다. 배너는
            **「지금 문제가 있다」**만 말하고(`#701`) 무엇을 해야 하는지는 그
            목록이 말하므로, 둘을 이어 준다.

            목록이 없으면(위험 선박이 있는데 서버가 조치를 안 내린 경우) 링크를
            걸지 않는다 — 눌러도 아무 데도 가지 않는 링크가 더 나쁘다.
          */}
          {hasActions ? (
            <a className="warn__main warn__link" href={`#${ACTIONS_ID}`}>
              {banner}
            </a>
          ) : (
            <p className="warn__main">{banner}</p>
          )}
          {soonest ? (
            <p className="warn__sub">
              {/* 문구를 다시 쓰지 않고 `daysToDText`를 부른다 (#592). 종전에는
                  같은 문장을 여기서 한 번 더 조립해, 선박 카드와 이 배너의
                  자릿수가 갈릴 수 있었다. */}
              가장 임박 — {soonest.name} · {daysToDText(soonest.days, null)}
            </p>
          ) : null}
        </section>
      ) : null}

      {/*
        KPI 행이 카드 밖 맨몸으로 페이지 위에 얹혀 있었다. 아래 두 블록은
        칸인데 여기만 아니라, **가장 먼저 읽혀야 할 줄이 가장 약하게** 보였다.
      */}
      <section className="card fleet__kpi" aria-label="선대 요약">
        <div className="kpi">
          <p className="kpi__label">운항 상태</p>
          {/*
            ## 슬래시를 뺀다

            「1 / 3」은 **「3척 중 1척」이라는 분수로 읽힌다.** 실제로는 운항 1 ·
            정박 3이고 합이 4다 — 분수로 읽으면 **분모가 틀린다.** 라벨의 「운항 /
            정박」이 순서를 알려 주긴 했지만, 큰 숫자 두 개를 슬래시로 붙여 놓으면
            라벨보다 그 모양이 먼저 읽힌다.

            숫자마다 **아래 선박 카드가 쓰는 상태 아이콘**(물살·닻)과 짧은 라벨을
            붙인다. 같은 화면에서 배운 기호라 따로 익힐 것이 없다.
          */}
          <p className="kpi__states">
            <span className="kpi__state">
              <UnderwayIcon />
              <span className="kpi__value">{counts.underWay}</span>
              <span className="kpi__state-label">운항 중</span>
            </span>
            <span className="kpi__state">
              <AnchorIcon />
              <span className="kpi__value">{counts.notUnderWay}</span>
              <span className="kpi__state-label">정박 중</span>
            </span>
          </p>
          {/* 상태 미기록을 운항·정박 어느 쪽에도 넣지 않는다 — 없는 사실이 된다. */}
          {counts.unknownState > 0 ? (
            <p className="kpi__foot">상태 미기록 {counts.unknownState}척</p>
          ) : null}
        </div>

        {/*
         * ## 「규제 조치 대상」 타일을 두지 않는다
         *
         * 같은 사실이 이 화면에 네 번 나오고 있었다 — 위 경고 배너(「위험 선박 n척」),
         * 이 타일, 아래 「조치 필요」 목록, 그리고 선박 카드의 규제 플래그.
         * **네 번 말하면 각각이 무슨 역할인지 흐려진다.**
         *
         * 역할을 이렇게 나눈다.
         *
         * - 경고 배너 — 지금 문제가 있다
         * - 조치 필요 — 무엇을 해야 하나
         * - 이 KPI 행 — 선대 전체 상태
         *
         * 그래서 타일이 빠진 자리를 등급 분포가 가져간다. 대시보드에서 가장 먼저
         * 읽혀야 할 값인데 종전에는 가장 좁은 자리에 있었다.
         */}
        <div className="kpi kpi--wide">
          <p className="kpi__label">등급 분포</p>
          <GradeDistribution distribution={counts.ratingDistribution} />
          {counts.noData > 0 ? (
            /*
             * 사유를 가리지 않은 수다 — 제원 미입력·기준값 없음도 포함되므로
             * 「실적 없음」으로 적으면 틀린다 (`#419`). 사유는 목록에서 구분한다.
             */
            <p className="kpi__foot">집계 불가 {counts.noData}척</p>
          ) : null}
        </div>

        {/*
          ## 세 번째 칸을 두는 이유
          「GT 미입력」은 **배마다 배지로만** 보였다. 선대 단위로는 어디에도 없어
          몇 척이 그 상태인지 알려면 목록을 세어야 했고, KPI 행은 오른쪽 절반이
          비어 있었다.

          **「계산이 안 된다」고 쓰지 않는다.** GT가 없어도 CII 값은 나온다 —
          없는 것은 **적용 대상 판정**이다(`types.ts` `grossTonnage` 주석 ·
          `#653`). 안 되는 일을 넓게 적으면 사용자가 다른 값까지 의심한다.
        */}
        <div className="kpi">
          <p className="kpi__label">GT 미입력</p>
          <p className="kpi__value">{missingGt}</p>
          {missingGt > 0 ? (
            <p className="kpi__foot">
              CII 적용 대상 판정이 되지 않습니다 ·{' '}
              <Link className="kpi__link" to={SCREEN_BY_ID.VESSEL_MANAGEMENT.path}>
                선박 관리
              </Link>
            </p>
          ) : null}
        </div>
      </section>

      <div className="fleet__split">
        <div className="fleet__col">
          <section className="card" aria-label="선박 위치">
            <div className="card__head">
              <h2 className="card__title">선박 위치</h2>
              {/*
               * ⚠️ 「AIS」로 쓰지 않는다. AIS 자동 수집은 `PRD §2.4`에서 제외됐고,
               * 위치는 사용자 입력 또는 시뮬레이션 시계로 확보한다(COR-5).
               * 하지 않는 것을 화면에 적으면 안 된다.
               */}
              <span className="card__meta">사용자 입력 기준</span>
            </div>
            <div className="fleet__chartbox">
              {/*
                지도 자산이 있으면 지도, 없으면 개략도다 (`#763` ⓑ).
                **개략도를 지우지 않았다** — 지우면 자산이 없는 환경에서 위치 화면이
                통째로 빈다. 그림 읽는 법은 각자가 스스로 적는다.
              */}
              {basemap === true ? (
                // 내려받는 동안에는 개략도를 그대로 둔다 — 빈 칸이 번쩍이지 않는다.
                <Suspense fallback={<PositionChart vessels={vessels} />}>
                  <FleetMap vessels={vessels} />
                </Suspense>
              ) : (
                <>
                  {basemap === false ? (
                    <p className="fleet__note">{BASEMAP_MISSING_NOTICE}</p>
                  ) : null}
                  <PositionChart vessels={vessels} />
                </>
              )}
            </div>
          </section>

          {snapshot.actions.length > 0 ? (
            <section className="card" id={ACTIONS_ID} aria-label="조치 필요">
              <div className="card__head">
                <h2 className="card__title">조치 필요</h2>
                <span className="card__meta">MARPOL Annex VI Reg 28.7</span>
              </div>
              <ul className="actions">
                {snapshot.actions.map((action) => (
                  <li
                    key={`${action.vesselId}-${action.reason}`}
                    className={`action action--${action.severity}`}
                  >
                    <WarnIcon />
                    <Link className="action__vessel" to={`/vessels/${action.vesselId}`}>
                      {action.vesselName}
                    </Link>
                    <span className="action__msg">{action.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>

        <section className="card fleet__list" aria-label="선박 목록">
          <div className="card__head">
            <h2 className="card__title">선박</h2>
            <label className="sort">
              <span className="sr-only">정렬 기준</span>
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as FleetSort)}
                data-testid="fleet-sort"
              >
                <option value="risk">위험도순</option>
                <option value="grade">등급순</option>
                <option value="name">이름순</option>
              </select>
            </label>
          </div>

          <ul className="vessels">
            {visible.map((vessel) => (
              <VesselRow key={vessel.id} vessel={vessel} />
            ))}
          </ul>

          {remaining > 0 ? (
            <button type="button" className="more" onClick={() => setExpanded(true)}>
              {remaining}척 더 보기
            </button>
          ) : null}
          {/*
            서버에 다음 페이지가 있으면(`API_SPEC §2.8` · #772) 이어서 받는다. 위 「더 보기」는
            받은 선박을 펼치는 것이고, 이것은 **아직 받지 않은 선박**을 받는 것이다.
          */}
          {remaining === 0 && snapshot.hasMore ? (
            <button type="button" className="more" onClick={loadMore} disabled={loadingMore}>
              {loadingMore
                ? '선박을 더 불러오는 중…'
                : `다음 선박 불러오기 (전체 ${counts.total}척 중 ${vessels.length}척 표시)`}
            </button>
          ) : null}
        </section>
      </div>

      {/*
       * 면책은 결과 유무와 무관하게 상시 노출한다(`DESIGN_SYSTEM §13` 🔒).
       * YTD 등급은 연중 누적 예측값이지 공식 등급이 아니다(`PRD §3.3.7` 각주).
       */}
      <DisclaimerBanner />
      <p className="fleet__source">일부 값은 사용자 입력 또는 모델 추정값입니다.</p>
    </div>
  )
}

/** 경고 배너가 가리키는 자리. 두 곳이 같은 문자열을 쓰므로 상수로 둔다. */
const ACTIONS_ID = 'fleet-actions'

function FleetHead({
  asOf,
  regulationYear,
  total,
}: {
  asOf?: string
  regulationYear?: number
  total?: number
}) {
  return (
    <PageHeader screen="MAINBOARD">
      <p className="page-head__sub">
        {total !== undefined && regulationYear !== undefined
          ? `보유 선박 ${total}척 · ${regulationYear}년 누적(YTD) 기준`
          : '보유 선박 전체의 CII 등급과 위험 선박'}
      </p>
      {/*
       * 기준 시각을 **제목 블록 안으로** 옮긴다. 종전에는 헤더 오른쪽 끝에
       * 따로 떠 있어 무엇에 붙는 값인지 보이지 않았다 — 제목·부제목과 같은
       * 「이 화면이 무엇을 언제 기준으로 보여 주는가」이므로 한 덩어리다.
       */}
      {asOf ? (
        <p className="fleet__asof">
          {/* 상대 시각만으로는 어느 시점 데이터인지 특정할 수 없어 원본도 함께 둔다. */}
          <span className="fleet__asof-abs">
            {/*
              초를 내지 않는다. 선대 스냅숏의 기준 시각에 30초는 의미가 없고,
              바로 옆에 상대 시각(「방금」)이 이미 있다. `toLocaleString`이
              기본으로 초를 붙이는 것이라 형식을 명시해 끈다.
            */}
            기준{' '}
            {new Date(asOf).toLocaleString('ko-KR', {
              hour12: false,
              dateStyle: 'medium',
              timeStyle: 'short',
            })}
          </span>
          <span className="fleet__asof-rel">{relativeTime(asOf, new Date())}</span>
        </p>
      ) : null}
    </PageHeader>
  )
}

/**
 * 데이터가 없을 때의 화면.
 *
 * 「불러오지 못했다」와 「아직 없다」를 **다른 화면으로** 보여 준다. 같은 문구를 쓰면
 * 사용자가 새로고침해야 할지 선박을 등록해야 할지 알 수 없다.
 */
function FleetPlaceholder({
  tone,
  message,
}: {
  tone: 'empty' | 'error'
  message: string
}) {
  return (
    <div className="fleet">
      <FleetHead />
      <section
        className={`empty empty--${tone}`}
        role={tone === 'error' ? 'alert' : undefined}
      >
        <p className="empty__msg">{message}</p>
        {tone === 'empty' ? (
          <Link className="empty__cta" to="/vessel-registration">
            선박 등록하기
          </Link>
        ) : null}
      </section>
      <DisclaimerBanner />
    </div>
  )
}

function VesselRow({ vessel }: { vessel: FleetVessel }) {
  return (
    <li className={isAtRisk(vessel) ? 'vessel vessel--risk' : 'vessel'}>
      <Link className="vessel__link" to={`/vessels/${vessel.id}`}>
        {/*
         * 등급은 **왼쪽 마크**가 맡는다 (`#701` ④). 종전에는 축이 다른 배지 셋이
         * 전부 이름 위에 가로로 깔려 이름이 네 번째 줄에 있었다.
         *
         * `GradeBadge`를 쓰지 않는다 — 색·패턴·문자 세 채널을 마크가 그대로 담고,
         * 같은 등급을 두 번 말하지 않는다. 대신 이 화면은 위쪽 등급 분포와 **같은
         * 배 모양**을 쓰게 되어, 두 블록이 하나의 언어로 읽힌다.
         */}
        <VesselMark vessel={vessel} />

        <span className="vessel__body">
          <span className="vessel__head">
            <span className="vessel__name">{vessel.name}</span>
            {/*
              규제 플래그는 등급과 **별개 축**이다 (`§8`). 같은 D등급이라도 1년차와
              3년차는 배지가 같고 플래그만 달라야 한다. 이름 옆에 두어 「이 배에
              의무가 걸렸다」가 이름과 함께 읽히게 한다.
            */}
            <RegulatoryFlags reasons={vessel.riskReasons} vesselName={vessel.name} />
          </span>

          {/*
            선종·상태·적용 여부를 한 줄에 둔다 — 셋 다 「이 배가 어떤 배이고 지금
            무엇을 하고 있나」다. 상태만 칩으로 빼 형태로 드러낸다 (`#701` ⑤).
          */}
          <span className="vessel__meta">
            <UnderwayChip vessel={vessel} />
            <span className="vessel__type">{shipTypeLabel(vessel.shipType)}</span>
            {/*
              적용 대상 배지는 규제 플래그와 **또 다른 축**이다 (`#653`).
              플래그는 「의무가 걸렸다」, 이 배지는 「애초에 규제 대상인가」다.
            */}
            <ApplicabilityBadge
              isCiiApplicableHint={vessel.isCiiApplicableHint}
              grossTonnage={vessel.grossTonnage}
              vesselName={vessel.name}
            />
          </span>

          <span className="vessel__stats">
            <span>
              <b className="vessel__k">YTD</b>
              {/* 자릿수는 `DESIGN_SYSTEM §4.1`(🔒)이 정한다 — 원본은 4자리로 온다. */}
              {ytdCiiText(vessel.ytdAttainedCii)}
            </span>
            {/*
             * 값이 없는 선박에는 「D등급까지」 대신 **왜 없는지**를 쓴다 (`#419`).
             * 종전에는 제원이 없어도 「실적 없음」으로 보여, 항차를 등록해도 해결되지
             * 않는 선박을 사용자가 계속 들여다보게 됐다.
             */}
            <span
              className="vessel__days"
              title={
                vessel.dataAvailable ? undefined : unavailableHint(vessel.unavailableReason)
              }
              /*
               * `role` 없는 `<span>`의 `aria-label`은 무시된다 (#829 ⑸b).
               * 라벨이 붙는 조건과 **같은 조건**으로 준다 — 값이 있을 때는 본문
               * 텍스트가 그대로 읽히면 되므로 역할을 만들지 않는다.
               */
              role={vessel.dataAvailable ? undefined : 'img'}
              aria-label={
                vessel.dataAvailable ? undefined : unavailableHint(vessel.unavailableReason)
              }
            >
              {vessel.dataAvailable
                ? daysToDText(vessel.daysToD, vessel.daysToDReason)
                : unavailableText(vessel.unavailableReason)}
            </span>
          </span>
        </span>
      </Link>
    </li>
  )
}

function WarnIcon() {
  return (
    <svg className="action__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 4.6 2.9 20h18.2L12 4.6z" />
      <path d="M12 10.4v4" />
      <circle cx="12" cy="17" r=".9" />
    </svg>
  )
}
