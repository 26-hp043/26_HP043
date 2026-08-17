import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { GradeBadge } from '../../components/GradeBadge'
import { GradeChip } from '../../components/GradeChip'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { PositionChart } from './PositionChart'
import { createApiFleetProvider } from './apiProvider'
import {
  daysToDText,
  isAtRisk,
  relativeTime,
  soonestDaysToD,
  sortVessels,
  unavailableHint,
  unavailableText,
  underwayStateText,
  warningBannerText,
  type SortKey,
} from './fleetRules'
import type { FleetSnapshot, FleetVessel } from './types'
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
 */

const INITIAL_VISIBLE = 6

export function FleetDashboard() {
  const [snapshot, setSnapshot] = useState<FleetSnapshot | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('risk')
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let alive = true
    createApiFleetProvider()
      .load()
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
  }, [])

  const vessels = useMemo(() => snapshot?.vessels ?? [], [snapshot])
  const sorted = useMemo(() => sortVessels(vessels, sortKey), [vessels, sortKey])

  if (failure) return <FleetPlaceholder tone="error" message={failure} />

  if (!snapshot) {
    return (
      <div className="fleet" aria-busy="true">
        <FleetHead />
        <p className="fleet__loading">선대 현황을 불러오는 중입니다…</p>
      </div>
    )
  }

  /*
   * 선박 0척은 오류가 아니라 정상 상태다 — 아직 아무것도 등록하지 않은 선사가 처음
   * 보는 화면이다. 0으로 채운 KPI를 보여 주면 「고장」처럼 읽히므로 다음에 할 일을
   * 가리키는 화면으로 대체한다 (`UIFLOW §1-1` 온보딩 흐름).
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
          <p className="warn__main">{banner}</p>
          {soonest ? (
            <p className="warn__sub">
              가장 임박 — {soonest.name} · D등급까지 {soonest.days}일
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="fleet__kpi" aria-label="선대 요약">
        <div className="kpi">
          <p className="kpi__label">운항 / 정박</p>
          <p className="kpi__value">
            {counts.underWay} <span className="kpi__slash">/</span> {counts.notUnderWay}
          </p>
          {/* 상태 미기록을 운항·정박 어느 쪽에도 넣지 않는다 — 없는 사실이 된다. */}
          {counts.unknownState > 0 ? (
            <p className="kpi__foot">상태 미기록 {counts.unknownState}척</p>
          ) : null}
        </div>

        <div className="kpi kpi--wide">
          <p className="kpi__label">등급 분포</p>
          <div className="kpi__chips">
            {(['A', 'B', 'C', 'D', 'E'] as const).map((rating) => (
              <span key={rating} className="dist">
                <GradeChip rating={rating} size="sm" label={`${rating}등급`} />
                <b className="dist__n">{counts.ratingDistribution[rating]}</b>
              </span>
            ))}
          </div>
          {counts.noData > 0 ? (
            /*
             * 사유를 가리지 않은 수다 — 제원 미입력·기준값 없음도 포함되므로
             * 「실적 없음」으로 적으면 틀린다 (`#419`). 사유는 목록에서 구분한다.
             */
            <p className="kpi__foot">집계 불가 {counts.noData}척</p>
          ) : null}
        </div>

        {/* 즉시 행동이 필요한 하나만 강조한다. 넷 다 강조하면 강조가 사라진다. */}
        <div className={counts.atRisk > 0 ? 'kpi kpi--alert' : 'kpi'}>
          <p className="kpi__label">규제 조치 대상</p>
          <p className="kpi__value">{counts.atRisk}</p>
          <p className="kpi__foot">SEEMP Part III</p>
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
              <PositionChart vessels={vessels} />
            </div>
            <p className="card__note">
              지도 없이 상대 위치만 표시합니다. 점 색은 올해 누적(YTD) 등급입니다.
            </p>
          </section>

          {snapshot.actions.length > 0 ? (
            <section className="card" aria-label="조치 필요">
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
                onChange={(e) => setSortKey(e.target.value as SortKey)}
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
    <header className="fleet__head">
      <div>
        <h1 className="fleet__title">선대 현황</h1>
        <p className="fleet__sub">
          {total !== undefined && regulationYear !== undefined
            ? `보유 선박 ${total}척 · ${regulationYear}년 누적(YTD) 기준`
            : '보유 선박 전체의 CII 등급과 위험 선박'}
        </p>
      </div>
      {asOf ? (
        <p className="fleet__asof">
          <span className="fleet__asof-rel">{relativeTime(asOf, new Date())}</span>
          {/* 상대 시각만으로는 어느 시점 데이터인지 특정할 수 없어 원본도 함께 둔다. */}
          <span className="fleet__asof-abs">
            기준 {new Date(asOf).toLocaleString('ko-KR', { hour12: false })}
          </span>
        </p>
      ) : null}
    </header>
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
         * 등급 배지는 `GradeBadge`를 재사용한다(#351 체크리스트). 색·패턴·문자
         * 세 채널을 함께 쓰는 컴포넌트라, 목록에서도 색만으로 구분되지 않는다(§14).
         */}
        {vessel.ytdRating ? (
          <GradeBadge
            rating={vessel.ytdRating}
            size="sm"
            label={`${vessel.name} 올해 누적 등급 ${vessel.ytdRating}`}
          />
        ) : (
          // 등급이 없는 **이유**를 읽어 주지 않으면, 사용자는 항차를 넣어야 하는지
          // 제원을 넣어야 하는지 알 수 없다 (`#419`).
          <span
            className="vessel__nograde"
            aria-label={`${vessel.name} — ${unavailableHint(vessel.unavailableReason)}`}
          >
            —
          </span>
        )}

        <span className="vessel__body">
          <span className="vessel__name">{vessel.name}</span>
          <span className="vessel__route">
            {vessel.shipType} · {underwayStateText(vessel)}
            {vessel.detailStatus ? ` · ${vessel.detailStatus}` : ''}
          </span>
          <span className="vessel__stats">
            <span>
              <b className="vessel__k">YTD</b>
              {vessel.ytdAttainedCii ?? '—'}
            </span>
            {/*
             * 값이 없는 선박에는 「D등급까지」 대신 **왜 없는지**를 쓴다 (`#419`).
             * 종전에는 제원이 없어도 「실적 없음」으로 보여, 항차를 등록해도 해결되지
             * 않는 선박을 사용자가 계속 들여다보게 됐다.
             */}
            <span
              className="vessel__days"
              // 짧은 문구만으로는 무엇을 해야 하는지 알 수 없다. 포인터에는 `title`로,
              // 스크린리더에는 `aria-label`로 같은 안내를 전한다.
              title={
                vessel.dataAvailable ? undefined : unavailableHint(vessel.unavailableReason)
              }
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
