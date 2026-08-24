import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { GradeBadge } from '../../components/GradeBadge'
import { DataConfidenceBadge } from '../../components/DataConfidenceBadge'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { GradeScaleBar } from '../../components/GradeScaleBar'
import { ciiUnit, marginDisplay, riskLabel } from '../voyage-cii/resultRules'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  formatDecimalString,
  formatGrouped,
  formatPercent,
} from '../../display/format'
import { createApiRealtimeCiiProvider, RealtimeCiiError } from './apiProvider'
import {
  POLL_INTERVAL_MS,
  RATING_TRANSITION_TEXT,
  formatAsOf,
  formatOrNull,
  isDegradingAtBerth,
  isNotUnderWay,
  projectionDirection,
  projectionReason,
  hasSubstitutedInputs,
  ratingTransition,
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
  YearEndProjection,
  YtdValues,
} from './types'
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
          {/*
            한 문장으로 합쳤다 (#725). 둘 다 「언제 값인가」를 말하는데 두 줄로
            나뉘어 있어, 왼쪽 두 줄(제목·부제)과 높이가 어긋났다.
          */}
          <p className="rt__asof">
            기준 {formatAsOf(data.asOf)}
            {refreshing ? ' · 갱신 중…' : ''} · {POLL_INTERVAL_MS / 1000}초마다 자동 갱신
          </p>
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
            {/*
              자릿수는 `DESIGN_SYSTEM §4`(🔒)가 정한다 — CII 3자리(`§4.1`),
              거리 0자리·연료 1자리(`§4.2`). 종전에는 서버 원본 문자열을 그대로
              내보내 `8.979907` · `4300.00 nm`처럼 화면마다 자릿수가 갈렸다.

              단위는 `DISPLAY_UNITS`를 참조한다. 리터럴로 박으면 표기가 바뀔 때
              일부가 남고, 그 누락은 화면이 깨지지 않아 발견이 늦다(#164).
            */}
            <dl className="ytd__figures">
              <Figure
                label="실적 (attained)"
                value={formatOrNull(data.ytd.attainedCii, (v) =>
                  formatDecimalString(v, DISPLAY_DIGITS.cii),
                )}
              />
              <Figure
                label="기준 (required)"
                value={formatOrNull(data.ytd.requiredCii, (v) =>
                  formatDecimalString(v, DISPLAY_DIGITS.cii),
                )}
              />
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
          <p className="rt__nodata">
            올해 등록된 실적이 없습니다. 항차 실적을 입력하면 누적값이 계산됩니다.
          </p>
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
  hint = null,
}: {
  label: string
  value: string | null
  suffix?: string
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

  return (
    <div className="rt__axis">
      <dl className="rt__axis-facts">
        <div>
          <dt>기준 대비</dt>
          {/*
            「7.871 / 5.045」를 눈으로 나누고 있었다. 서버가 `ratio_to_required`를
            이미 싣는다 — 기능①의 「기준 대비 비율」과 같은 값·같은 자릿수다.
          */}
          <dd className={ratio ? 'num' : 'num muted'}>{ratio ?? '—'}</dd>
        </div>
        <div>
          <dt>위험도</dt>
          <dd className={riskText ? `rt__risk rt__risk--${risk!.toLowerCase()}` : 'muted'}>
            {riskText ? (
              <>
                {riskText.withIcon ? (
                  // §2.5 (b) — 라벨이 바로 옆에 있으므로 aria-hidden.
                  <span className="rt__risk-icon" aria-hidden="true">
                    ⚠{' '}
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
      {scale && ytd.ratioToRequired && ratio ? (
        <GradeScaleBar
          ratioToRequired={ytd.ratioToRequired}
          boundaries={scale}
          rating={rating}
          valueLabel={ratio}
          label="연간 누적 CII의 등급 스케일"
        />
      ) : null}
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
          {/*
            `§4.2` 「비율」 — 백분율 1자리. `Math.round(ratio * 100)`은 화면이
            직접 셈하는 것이라 규정 자릿수와 무관하게 정수로 떨어졌다.
          */}
          <span className="rt__progress-text num">{formatPercent(String(ratio))}%</span>
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
   * 신뢰도 배지는 **현재 누적 등급 옆**에 붙는다 (`DESIGN_SYSTEM §8` · `#485` ⑤).
   * 대체가 일어난 것은 YTD 집계의 입력이므로, 연말 예상 쪽에 붙이면 무엇이
   * 추정인지 어긋난다. 판정은 `§8.1`을 구현한 `hasSubstitutedInputs`가 소유한다.
   */
  const confidence = hasSubstitutedInputs(data.ytd) ? (
    <DataConfidenceBadge detail={substitutionSummary(data.ytd)} />
  ) : null

  /*
   * 연말 예상을 못 내면 현재 등급만 그린다. 없는 쪽을 빈 배지나 「—」로 채우면
   * 전이가 있는 것처럼 읽히고, 사유는 ⑶ 카드가 이미 글로 말한다.
   */
  if (!transition) {
    return (
      <span className="rt__grade-row">
        <GradeBadge rating={current} label={`현재 누적 기준 예상 등급 ${current}`} />
        {confidence}
      </span>
    )
  }

  const modifier = transition.direction.toLowerCase()

  return (
    <div className="rt__transition">
      <div className="rt__transition-pair">
        <div className="rt__transition-step">
          <span className="rt__transition-caption">현재 누적</span>
          <span className="rt__grade-row">
            <GradeBadge
              rating={transition.from}
              label={`현재 누적 기준 예상 등급 ${transition.from}`}
            />
            {confidence}
          </span>
        </div>

        {/* 잇는 기호일 뿐이라 방향을 뜻하지 않는다 — 방향은 아래 라벨이 말한다. */}
        <span className={`rt__transition-arrow rt__transition-arrow--${modifier}`} aria-hidden="true">
          →
        </span>

        <div className="rt__transition-step">
          <span className="rt__transition-caption">연말 예상</span>
          {/*
           * 현재 누적과 **같은 크기**다 (#725). 종전에는 `sm`이었는데, 크기 차이는
           * 「덜 중요하다」로 읽힌다 — 이 화면에서 사용자가 보러 오는 값이 바로
           * 연말 예상이므로 정반대다. 두 값의 차이는 시점이고, 그 시점 차이는
           * 캡션(현재 누적 / 연말 예상)과 화살표가 이미 말한다.
           */}
          <GradeBadge
            rating={transition.to}
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
                <span className="rt__risk-icon" aria-hidden="true">
                  ⚠{' '}
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

  const direction = projectionDirection(data)

  return (
    <>
      <div className="rt__projection">
        {projection.rating ? (
          /*
            `sm`(13px)이었다. 옆 값이 h2(20px)라 배지가 눌려 **등급이 곁가지로**
            읽혔다 — 이 카드의 주인공은 등급이다. `§8`의 `lg`(20px)로 올린다.
            세 단 안이므로 정본을 벗어나지 않는다.
          */
          <GradeBadge
            rating={projection.rating}
            size="lg"
            label={`연말 예상 등급 ${projection.rating}`}
          />
        ) : null}
        <div>
          <p className="rt__projection-value num">
            {formatOrNull(projection.attainedCii, (v) =>
              formatDecimalString(v, DISPLAY_DIGITS.cii),
            ) ?? '—'}
          </p>
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
                {/* `§4.2` 일수 0자리 (#592). 종전에는 서버 값을 가공 없이 내보내
                    `231.64 일`이 나갔다 — 같은 블록의 거리·연료는 이미 `§4.2`를
                    따르고 있어 한 표 안에서 규율이 갈려 있었다. */}
                {formatOrNull(projection.assumptions.elapsedDays, (v) =>
                  formatDecimalString(v, DISPLAY_DIGITS.days),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.day} /{' '}
                {formatOrNull(projection.assumptions.remainingDays, (v) =>
                  formatDecimalString(v, DISPLAY_DIGITS.days),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.day}
              </dd>
            </div>
            <div>
              <dt>일평균 거리</dt>
              <dd className="num">
                {formatOrNull(projection.assumptions.dailyDistanceNm, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.distanceNm),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.distance}
              </dd>
            </div>
            <div>
              <dt>일평균 연료</dt>
              <dd className="num">
                {formatOrNull(projection.assumptions.dailyFuelTon, (v) =>
                  formatGrouped(v, DISPLAY_DIGITS.fuelTon),
                ) ?? '—'}{' '}
                {DISPLAY_UNITS.fuel}
              </dd>
            </div>
          </dl>
        </details>
      ) : null}
    </>
  )
}
