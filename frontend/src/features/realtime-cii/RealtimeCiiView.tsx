import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { GradeBadge } from '../../components/GradeBadge'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { ciiUnit } from '../voyage-cii/resultRules'
import { createApiRealtimeCiiProvider, RealtimeCiiError } from './apiProvider'
import {
  POLL_INTERVAL_MS,
  RATING_TRANSITION_TEXT,
  formatAsOf,
  isDegradingAtBerth,
  isNotUnderWay,
  projectionDirection,
  projectionReason,
  ratingTransition,
  remainingDistanceNm,
  voyageProgressRatio,
  warningText,
} from './realtimeRules'
import type { Rating, RealtimeCii, RealtimeCiiProvider } from './types'
import './RealtimeCiiView.css'

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
export function RealtimeCiiView({ provider }: { provider?: RealtimeCiiProvider }) {
  const { vesselId } = useParams()
  const [data, setData] = useState<RealtimeCii | null>(null)
  const [failure, setFailure] = useState<{ message: string; notFound: boolean } | null>(
    null,
  )
  const [refreshing, setRefreshing] = useState(false)

  /*
   * provider를 ref에 담는다. 매 렌더마다 새로 만들면 아래 effect의 의존성이 계속
   * 바뀌어 폴링 타이머가 재설정되고, 결국 간격이 지켜지지 않는다.
   */
  const providerRef = useRef<RealtimeCiiProvider | null>(null)
  if (providerRef.current === null) {
    providerRef.current = provider ?? createApiRealtimeCiiProvider()
  }

  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!vesselId) return
      if (options.silent) setRefreshing(true)
      try {
        const next = await providerRef.current!.load(vesselId)
        setData(next)
        setFailure(null)
      } catch (error) {
        /*
         * 폴링 중 실패는 **화면을 비우지 않는다.** 마지막으로 받은 값이 여전히
         * 「방금 전 기준」으로 유효하고, 통신 오류로 값을 지우면 사용자는 정박도
         * 항해도 아닌 빈 화면을 본다. 최초 로드 실패만 화면을 대체한다.
         */
        if (data === null) {
          setFailure({
            message:
              error instanceof Error ? error.message : '값을 불러오지 못했습니다.',
            notFound: error instanceof RealtimeCiiError && error.notFound,
          })
        }
      } finally {
        setRefreshing(false)
      }
    },
    [vesselId, data],
  )

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vesselId])

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vesselId])

  if (failure) {
    return (
      <div className="rt">
        <BackLink vesselId={vesselId} />
        <section className="empty empty--error" role="alert">
          <p className="empty__msg">{failure.message}</p>
          {failure.notFound ? (
            <Link className="empty__cta" to="/dashboard">
              대시보드로 돌아가기
            </Link>
          ) : null}
        </section>
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

  return (
    <div className="rt">
      <BackLink vesselId={data.vesselId} />

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
          <p className="rt__asof">
            기준 {formatAsOf(data.asOf)}
            {refreshing ? ' · 갱신 중…' : ''}
          </p>
          <p className="rt__poll">{POLL_INTERVAL_MS / 1000}초마다 자동 갱신</p>
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

      {/* ── ⑴ 연간 누적 — 주 표시 ────────────────────────────────── */}
      <section className="card rt__ytd" aria-label="연간 누적 CII">
        <div className="card__head">
          <h2 className="card__title">연간 누적 (YTD)</h2>
          <span className="card__meta">현재 누적 기준 예상 등급</span>
        </div>

        {data.ytd.dataAvailable && data.ytd.rating ? (
          <div className="ytd">
            <RatingTransitionView data={data} current={data.ytd.rating} />
            <dl className="ytd__figures">
              <Figure label="실적 (attained)" value={data.ytd.attainedCii} />
              <Figure label="기준 (required)" value={data.ytd.requiredCii} />
              <Figure label="누적 거리" value={data.ytd.totalDistanceNm} suffix=" nm" />
              <Figure label="누적 연료" value={data.ytd.totalFuelTon} suffix=" t" />
            </dl>
          </div>
        ) : (
          <p className="rt__nodata">
            올해 등록된 실적이 없습니다. 항차 실적을 입력하면 누적값이 계산됩니다.
          </p>
        )}

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
            <VoyagePanel data={data} unit={unit} />
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

      {/* ── 경고 ─────────────────────────────────────────────────── */}
      {data.warnings.length > 0 ? (
        <ul className="rt__warnings">
          {data.warnings.map((code) => (
            <li key={code}>{warningText(code)}</li>
          ))}
        </ul>
      ) : null}

      <DisclaimerBanner />
    </div>
  )
}

// ─── 부품 ────────────────────────────────────────────────────────────────────

function BackLink({ vesselId }: { vesselId?: string }) {
  return (
    <Link className="rt__back" to={vesselId ? `/vessels/${vesselId}` : '/dashboard'}>
      ← 선박 상세
    </Link>
  )
}

function Figure({
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
      {/* 빈칸이면 항목 자체가 없는 것으로 읽힌다. */}
      <dd className={value ? 'num' : 'num muted'}>{value ? `${value}${suffix}` : '—'}</dd>
    </div>
  )
}

function VoyagePanel({ data, unit }: { data: RealtimeCii; unit: string }) {
  const voyage = data.currentVoyage!
  const ratio = voyageProgressRatio(data)
  const remaining = remainingDistanceNm(data)

  return (
    <>
      <p className="rt__voyage-title">
        {voyage.voyageNo ?? '항차'} · {voyage.departurePortName ?? '—'} →{' '}
        {voyage.arrivalPortName ?? '—'}
      </p>

      {ratio !== null ? (
        <div className="rt__progress" aria-label="항해 진행률">
          <div className="rt__progress-bar" style={{ inlineSize: `${ratio * 100}%` }} />
          <span className="rt__progress-text num">{Math.round(ratio * 100)}%</span>
        </div>
      ) : null}

      <dl className="ytd__figures rt__voyage-figures">
        <Figure label="누적 거리" value={voyage.distanceNm} suffix=" nm" />
        {/* 계획이 없으면 「남은 거리」를 만들지 않는다 — 0은 「다 왔다」로 읽힌다. */}
        <Figure
          label="남은 거리"
          value={remaining === null ? null : String(remaining)}
          suffix=" nm"
        />
        <Figure label="누적 연료" value={voyage.fuelTon} suffix=" t" />
        <Figure label="항해 시간" value={voyage.underwayHours} suffix=" h" />
      </dl>

      <div className="rt__segment">
        <span className="rt__segment-label">구간 CII</span>
        <span className="num rt__segment-value">{voyage.attainedCii ?? '—'}</span>
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
    </>
  )
}

/**
 * ⑴ → ⑶ 등급 전이 — 「현재 누적 기준 예상 등급」이 연말에 어디로 가는가.
 *
 * ## 왜 ⑴ 카드 안에 두는가
 *
 * `API_SPEC §2.14`가 ⑴을 **주 표시**, ⑶을 **보조 표시**로 못박는다. 전이를 별도
 * 카드로 떼면 ⑶이 ⑴과 같은 무게를 얻어 그 위계가 무너진다. ⑴의 자리에서
 * 「지금 여기, 이대로 가면 저기」를 말하는 것이 위계를 지키면서 전이를 보이는 길이다.
 *
 * 같은 이유로 **연말 배지를 한 단계 작게** 쓴다. 크기 차이 자체가 「확정에 가까운
 * 누적 : 가정 위의 추정」을 말한다.
 *
 * ## 색은 §2.3 시맨틱만 쓴다
 *
 * 배지 두 개는 등급 램프다(`§2.4.4`가 등급 표시에 램프+패턴을 요구한다). 반면
 * **화살표와 라벨은 등급이 아니라 「변화 방향」**이므로 `§2.3` 시맨틱을 쓴다 —
 * 같은 절이 시맨틱 색을 등급 표시에 쓰는 것을 금지하는데, 방향은 등급이 아니다.
 *
 * `--color-warning`은 쓰지 않는다. 그 별칭은 현재 `--cii-c-fill`(등급 램프)을
 * 가리켜서, 쓰는 순간 램프가 시맨틱 자리로 새어 들어온다.
 */
function RatingTransitionView({ data, current }: { data: RealtimeCii; current: Rating }) {
  const transition = ratingTransition(data)

  /*
   * 연말 예상을 못 내면 현재 등급만 그린다. 없는 쪽을 빈 배지나 「—」로 채우면
   * 전이가 있는 것처럼 읽히고, 사유는 ⑶ 카드가 이미 글로 말한다.
   */
  if (!transition) {
    return <GradeBadge rating={current} label={`현재 누적 기준 예상 등급 ${current}`} />
  }

  const modifier = transition.direction.toLowerCase()

  return (
    <div className="rt__transition">
      <div className="rt__transition-pair">
        <div className="rt__transition-step">
          <span className="rt__transition-caption">현재 누적</span>
          <GradeBadge
            rating={transition.from}
            label={`현재 누적 기준 예상 등급 ${transition.from}`}
          />
        </div>

        {/* 잇는 기호일 뿐이라 방향을 뜻하지 않는다 — 방향은 아래 라벨이 말한다. */}
        <span className={`rt__transition-arrow rt__transition-arrow--${modifier}`} aria-hidden="true">
          →
        </span>

        <div className="rt__transition-step">
          <span className="rt__transition-caption">연말 예상</span>
          <GradeBadge
            rating={transition.to}
            size="sm"
            label={`연말 예상 등급 ${transition.to}`}
          />
        </div>
      </div>

      <p className={`rt__transition-label rt__transition-label--${modifier}`}>
        {RATING_TRANSITION_TEXT[transition.direction]}
      </p>
    </div>
  )
}

function ProjectionPanel({ data }: { data: RealtimeCii }) {
  const { projection } = data

  if (!projection.dataAvailable) {
    // 사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.
    return <p className="rt__nodata">{projectionReason(projection.reason)}</p>
  }

  const direction = projectionDirection(data)

  return (
    <>
      <div className="rt__projection">
        {projection.rating ? (
          <GradeBadge
            rating={projection.rating}
            size="sm"
            label={`연말 예상 등급 ${projection.rating}`}
          />
        ) : null}
        <div>
          <p className="rt__projection-value num">{projection.attainedCii ?? '—'}</p>
          {direction ? (
            <p className={`rt__direction rt__direction--${direction.toLowerCase()}`}>
              {direction === 'IMPROVING'
                ? '현재 누적보다 나아지는 추세'
                : direction === 'WORSENING'
                  ? '현재 누적보다 나빠지는 추세'
                  : '현재 누적과 같은 수준'}
            </p>
          ) : null}
        </div>
      </div>

      {/*
       * 가정을 함께 보여 준다 — `PRD §3.3` ⑶ 요구. 이 값이 무엇을 전제로 나온
       * 것인지 없으면 확정값처럼 읽힌다.
       */}
      {projection.assumptions ? (
        <details className="rt__assumptions">
          <summary>산출 가정</summary>
          <dl>
            <div>
              <dt>방식</dt>
              <dd>지금까지의 일평균이 연말까지 이어진다고 가정</dd>
            </div>
            <div>
              <dt>경과 / 잔여</dt>
              <dd className="num">
                {projection.assumptions.elapsedDays ?? '—'} 일 /{' '}
                {projection.assumptions.remainingDays ?? '—'} 일
              </dd>
            </div>
            <div>
              <dt>일평균 거리</dt>
              <dd className="num">{projection.assumptions.dailyDistanceNm ?? '—'} nm</dd>
            </div>
            <div>
              <dt>일평균 연료</dt>
              <dd className="num">{projection.assumptions.dailyFuelTon ?? '—'} t</dd>
            </div>
          </dl>
        </details>
      ) : null}
    </>
  )
}
