import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { ErrorState } from '../../components/ErrorState'
import { GradeBadge } from '../../components/GradeBadge'
import { formatDecimalString, formatPercent } from '../../display/format'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { useYearOptions } from '../parameters/yearCatalog'
import { voyageActualsPath } from '../voyage-management/voyageRules'
import { createApiDataQualityProvider } from './apiProvider'
import {
  DATA_QUALITY_COPY as COPY,
  IMPACT_REASON,
  IMPACT_REASON_ORDER,
  SEVERITY_MEANING,
  SEVERITY_TITLE,
  reasonText,
} from './copy'
import { IMPACT_DIGITS, orderedIssues } from './issueOrder'
import {
  SEVERITIES,
  type DataQualityIssue,
  type DataQualityProvider,
  type DataQualitySnapshot,
} from './types'
import './DataQuality.css'


/**
 * `UIFLOW 2-11` 데이터 점검 — 선대 계층 (#513).
 *
 * ## 네 그룹을 **항상** 그린다
 *
 * 0건인 그룹을 지우면 「확인했더니 없다」와 「확인하지 않았다」가 같은 화면이 된다.
 * `PRD §5.2` 각주가 이 화면을 반쪽으로 열지 않은 이유가 그것이었다.
 *
 * ## 그룹은 접히지 않는다 (`UIFLOW 2-11`)
 *
 * 아코디언은 반드시 봐야 할 항목을 닫힌 채 지나치게 한다.
 */

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; snapshot: DataQualitySnapshot }

/** 연도 목록 훅은 선박 키를 받는다 — 이 화면은 선대 단위라 고정 키를 준다. */
const FLEET_KEY = 'fleet'

export function DataQuality({ provider }: { provider?: DataQualityProvider }) {
  const api = useMemo(() => provider ?? createApiDataQualityProvider(), [provider])
  const { years, loading: yearsLoading } = useYearOptions(FLEET_KEY, { throughCurrentYear: true })
  /** 사용자가 고른 해. 화면에 쓰는 값은 아래 `year`다 — 목록과 대조해 렌더 중에 정한다. */
  const [chosenYear, setChosenYear] = useState('')
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  /*
   * 기본 연도는 **렌더 중에 파생**한다 (`#1616`). 종전에는 목록이 오면 effect가 상태를
   * 채워, 목록 도착과 기본값 사이에 연도가 빈 렌더가 한 번 있었다. 고른 해가 목록에
   * 있으면 그것, 없으면 올해, 올해도 없으면 가장 최근 해다(`pickDefaultYear`). 목록이
   * 비어 있으면 `''`다 — 그때만 서버 기본(올해)으로 부른다.
   */
  const year = pickDefaultYear(years, new Date().getFullYear(), chosenYear)

  useEffect(() => {
    // 연도 목록을 못 받으면 서버 기본(올해)으로 부른다 — 화면 전체를 막지 않는다.
    if (yearsLoading) return
    let cancelled = false
    // oxlint-disable-next-line react/set-state-in-effect -- 조회 시작 전 리셋 — 이 effect가 곧 보내는 요청의 로딩 상태를 세운다
    setState({ status: 'loading' })
    api
      .load(year === '' ? undefined : Number(year))
      .then((snapshot) => {
        if (!cancelled) setState({ status: 'ready', snapshot })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : COPY.loading,
        })
      })
    return () => {
      cancelled = true
    }
  }, [api, year, yearsLoading])

  return (
    <section className="dq">
      <div className="dq__controls">
        <label className="dq__field" htmlFor="dq-year">
          <span className="dq__label">{COPY.yearLabel}</span>
          <select
            id="dq-year"
            value={year}
            disabled={years.length === 0}
            onChange={(event) => setChosenYear(event.target.value)}
          >
            {years.map((y) => (
              <option key={y} value={String(y)}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <p className="dq__note">{COPY.readOnlyNote}</p>
      </div>

      {state.status === 'loading' ? (
        <p className="dq__placeholder" aria-live="polite">
          {COPY.loading}
        </p>
      ) : null}
      {state.status === 'error' ? (
        <ErrorState level="region" subject={COPY.loadSubject} message={state.message} />
      ) : null}
      {state.status === 'ready' ? <Result snapshot={state.snapshot} /> : null}
    </section>
  )
}

function Result({ snapshot }: { snapshot: DataQualitySnapshot }) {
  if (snapshot.vessels.length === 0) {
    return <p className="dq__placeholder">{COPY.noVessels}</p>
  }
  /*
   * 서버가 준 배열을 **CII 영향 순**으로 다시 늘어놓는다 (#1766 · `issueOrder.ts`).
   * 원본은 그대로 둔다 — 정렬은 표시 순서이지 데이터가 아니다.
   */
  const rows = orderedIssues(snapshot.issues)

  return (
    <>
      {/*
        요약 띠 (#1766). 종전에는 카드 안의 4칸이었다 — 건수 넷과 완결성은 「한 덩어리의
        데이터」가 아니라 아래 목록을 읽는 눈금이라 면을 띄우지 않는다(`§5` 카드 예산).

        **결론 띠(`§8.6`)가 아니다.** 이 화면의 답은 하나가 아니라 성격이 다른 네 축의
        건수다 — 하나로 합치면 그 넷을 한 수로 뭉갠다.
      */}
      <dl className="dq__tiles" aria-label={COPY.summaryTitle}>
        {(['SUBSTITUTED', 'UNAVAILABLE', 'ANOMALY', 'UNCONFIRMED'] as const).map((severity) => (
          <div
            key={severity}
            className={`dq__tile${
              showsSeverity(snapshot.counts[severity]) ? ` dq__tile--${severity.toLowerCase()}` : ''
            }`}
          >
            <dt>{SEVERITY_TITLE[severity]}</dt>
            <dd>
              {snapshot.counts[severity]}
              <span className="dq__unit">{COPY.countSuffix}</span>
            </dd>
            {severity === 'ANOMALY' && snapshot.anomalyUnjudged > 0 ? (
              <dd className="dq__hint">{COPY.unjudgedHint(snapshot.anomalyUnjudged)}</dd>
            ) : null}
          </div>
        ))}
        <div className="dq__tile">
          <dt>{COPY.completenessLabel}</dt>
          <dd>
            {snapshot.completenessRatio === null
              ? COPY.completenessNone
              : `${formatPercent(snapshot.completenessRatio)}%`}
          </dd>
          <dd className="dq__hint">{COPY.completenessHint}</dd>
        </div>
      </dl>

      <section className="card dq__list" aria-labelledby="dq-list-title">
        <h2 id="dq-list-title" className="card__title">
          {COPY.listTitle}
        </h2>
        <p className="dq__caption">{COPY.impactCaption}</p>
        {rows.length === 0 ? (
          <p className="dq__empty">{COPY.noIssues}</p>
        ) : (
          <>
            {/*
              **한 표다** (#1766). 종전에는 심각도 그룹마다 같은 다섯 열짜리 표가 하나씩
              서서, 행 6건에 표 머리가 세 번 나왔다. 심각도는 열이 된다.

              0건 심각도를 지우는 것이 아니다 — 위 요약 띠가 「실적 미입력 0건」으로 계속
              말한다(`#513`: 지우면 「확인 안 함」과 구분되지 않는다).
            */}
            <div className="dq__table-wrap">
              <table className="dq__table dq__issues">
                <thead>
                  <tr>
                    <th scope="col">{COPY.colSeverity}</th>
                    <th scope="col">{COPY.colVessel}</th>
                    <th scope="col">{COPY.colVoyage}</th>
                    <th scope="col">{COPY.colProblem}</th>
                    <th scope="col">{COPY.colImpact}</th>
                    <th scope="col">{COPY.colGo}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((issue) => (
                    <tr key={`${issue.vesselId}-${issue.voyageId ?? 'vessel'}-${issue.codes.join()}`}>
                      <td>
                        {/*
                          행이 있다는 것 자체가 「볼 것이 있다」이므로 `#1288`의 조건(건수 0)은
                          여기서 성립할 수 없다 — 칩은 늘 제 심각도 색을 단다. 0건일 때 색을
                          빼는 판단은 위 요약 띠가 맡는다.
                        */}
                        <span className={`dq__severity dq__severity--${issue.severity.toLowerCase()}`}>
                          {SEVERITY_TITLE[issue.severity]}
                        </span>
                      </td>
                      <th scope="row">{issue.vesselName}</th>
                      <td>{issue.voyageId === null ? COPY.vesselLevel : (issue.voyageNo ?? '—')}</td>
                      <td>
                        <ul className="dq__codes">
                          {issue.codes.map((code) => (
                            <li key={code}>{reasonText(code)}</li>
                          ))}
                        </ul>
                      </td>
                      <td>
                        <Impact issue={issue} />
                      </td>
                      <td>
                        {/*
                          항차 행은 **그 항차 카드로** 간다 (#1549). 종전에는 모든 행이 선박 상세
                          맨 위로 가서 페이지 중간의 항차를 다시 찾아야 했다. 실적을 넣을 수 있는
                          항차면 입력이 열린 채 도착한다(`#1540`과 같은 진입). 선박 단위 행은
                          가리킬 항차가 없어 종전대로 선박 상세다.
                        */}
                        {issue.voyageId === null ? (
                          <Link to={`/vessels/${issue.vesselId}`}>{COPY.goToVessel}</Link>
                        ) : (
                          <Link
                            to={voyageActualsPath(issue.vesselId, issue.voyageId)}
                            aria-label={`${COPY.goToVoyage} — ${issue.vesselName} ${issue.voyageNo ?? ''}`.trim()}
                          >
                            {COPY.goToVoyage}
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ImpactNotes issues={rows} />
          </>
        )}
        {/*
          심각도 넷의 뜻은 `DESIGN_SYSTEM §2.3.1` 「의미」 열이라 화면에서 없애지 않는다.
          그룹마다 한 줄이던 것을 접기 하나로 모은다 — 늘 펴 두면 표보다 설명이 길어진다.
        */}
        <details className="dq__legend">
          <summary>{COPY.legendTitle}</summary>
          <dl className="dq__legend-list">
            {SEVERITIES.map((severity) => (
              <div key={severity}>
                <dt>{SEVERITY_TITLE[severity]}</dt>
                <dd>{SEVERITY_MEANING[severity]}</dd>
              </div>
            ))}
          </dl>
        </details>
      </section>

      <section className="card dq__vessels" aria-labelledby="dq-vessels-title">
        <h2 id="dq-vessels-title" className="card__title">
          {COPY.vesselsTitle}
        </h2>
        <div className="dq__table-wrap">
          <table className="dq__table">
            <thead>
              <tr>
                <th scope="col">{COPY.colVessel}</th>
                <th scope="col">{COPY.colRating}</th>
                <th scope="col">{COPY.colVoyages}</th>
                <th scope="col">{COPY.colCompleteness}</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.vessels.map((vessel) => (
                <tr key={vessel.vesselId}>
                  <th scope="row">
                    <Link to={`/vessels/${vessel.vesselId}`}>{vessel.vesselName}</Link>
                  </th>
                  <td>
                    {vessel.ytdRating ? (
                      <GradeBadge rating={vessel.ytdRating} size="sm" />
                    ) : vessel.unavailableReason ? (
                      reasonText(vessel.unavailableReason)
                    ) : (
                      // 항차가 없는 선박은 「계산 불가」가 아니다 — 아직 셀 것이 없다.
                      COPY.noActualVoyages
                    )}
                  </td>
                  <td className="dq__num">{vessel.voyageCount}</td>
                  <td className="dq__num">
                    {vessel.completenessRatio === null
                      ? '—'
                      : `${formatPercent(vessel.completenessRatio)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

/**
 * 심각도 색을 붙일 조건 (#1288).
 *
 * ## 0건이면 붙이지 않는다
 *
 * 종전에는 건수를 보지 않고 심각도 변형을 늘 달아, **0건인 칸도 좌측에 위험색 띠**를
 * 갖고 있었다. 요약 4칸 중 3칸이 경고색이라 실제로 볼 것이 있는 칸이 묻혔다.
 *
 * 색은 **심각도 신호**다 — 「색이 있다 = 볼 것이 있다」. 분류 키가 아니다. 근거:
 * 클래스 이름이 그룹명이 아니라 심각도이고, `UNCONFIRMED`는 원래부터 중립색이며,
 * `DESIGN_SYSTEM §16` 항목 8이 「색은 **면이 중립, 아이콘·문구만 위험색**」으로
 * 정했다(`#694`).
 *
 * **대가는 같은 그룹의 색이 날마다 달라지는 것**이고, 의도한 것이다. 그룹이
 * 무엇인지는 제목과 `SEVERITY_MEANING` 한 줄이 계속 말한다.
 *
 * ## 중립 클래스를 새로 만들지 않는다
 *
 * `.dq__tile`·`.dq__group` 기본 규칙이 이미 `--color-border`로 4px 띠를 그린다.
 * 변형을 **빼기만** 하면 그 중립이 드러난다.
 *
 * ## ⚠️ 클래스 이름 조립을 이 함수로 가져오지 않는다
 *
 * 처음에 `severityClass(block, severity, count)`로 이름까지 만들었더니
 * **`deadCss.test.ts`가 `.dq__tile--substituted` 넷을 죽은 클래스로 잡았다.**
 * 그 가드는 ``` `x--${` ``` 처럼 **리터럴 접두가 템플릿에 보일 때만** 동적 조립으로
 * 인정한다(`deadCss.test.ts`의 `dynamicPrefixes`). 접두가 변수(`${block}--`)가 되면
 * 그 근거가 사라진다.
 *
 * 그래서 **판단만 여기에 두고 이름은 부르는 쪽에 리터럴로 남긴다.** 규칙이 한
 * 곳이라는 목적은 그대로 지켜진다.
 */
function showsSeverity(count: number): boolean {
  return count > 0
}

/**
 * CII 영향 칸의 표시(`*`)가 가리키는 사유 — **이 표에 나온 것만**, 한 번씩 (#1580).
 *
 * 칸마다 긴 문장을 되풀이하던 것을 여기로 모은다. 나오지 않은 사유까지 적으면 표에 없는
 * 사실을 말하게 된다.
 */
function ImpactNotes({ issues }: { issues: DataQualityIssue[] }) {
  const present = new Set(
    issues.filter((issue) => issue.voyageId !== null && issue.cii === null).map((issue) => issue.ciiReason),
  )
  const notes = IMPACT_REASON_ORDER.filter((code) => present.has(code))
  if (notes.length === 0) return null
  return (
    <ul className="dq__footnotes">
      {notes.map((code) => (
        <li key={code}>
          {IMPACT_REASON[code].mark} {IMPACT_REASON[code].note}
        </li>
      ))}
    </ul>
  )
}

/**
 * CII 영향 칸 — 차이 + 등급이 바뀌면 전이(`DESIGN_SYSTEM §8.3`).
 *
 * **바뀌지 않으면 전이를 그리지 않는다**(`§8.3`). 부호에 색을 입히지 않는다 — 등급 배지 옆에
 * 시맨틱 색이 들어오면 `§0.2` 제약 2 위반이다.
 */
function Impact({ issue }: { issue: DataQualityIssue }) {
  if (issue.voyageId === null) return <span className="dq__muted">—</span>
  if (issue.cii === null) {
    const reason = IMPACT_REASON[issue.ciiReason ?? '']
    // 모르는 사유는 코드 그대로 — 빈칸이면 문제가 없는 것처럼 보인다(`reasonText`와 같은 규칙)
    if (reason === undefined) return <span className="dq__muted">{issue.ciiReason ?? '—'}</span>
    return (
      <span className="dq__muted">
        {reason.cell}
        {reason.mark}
      </span>
    )
  }
  // 정렬도 같은 자릿수에서 비교한다 — 화면에 찍힌 숫자와 순서가 어긋나지 않게 (`issueOrder.ts`).
  const delta = formatDecimalString(issue.cii.delta, IMPACT_DIGITS)
  const signed = delta.startsWith('-') || delta === '0.000' ? delta : `+${delta}`
  const { rating, ratingWithout } = issue.cii
  return (
    <span className="dq__impact">
      <span className="dq__num">{signed}</span>
      {rating && ratingWithout && rating !== ratingWithout ? (
        <span
          className="dq__transition"
          role="img"
          aria-label={`이 항차가 없으면 ${ratingWithout}, 있으면 ${rating}`}
        >
          <GradeBadge rating={ratingWithout} size="xs" />
          <span className="dq__connector" aria-hidden="true">
            →
          </span>
          <GradeBadge rating={rating} size="xs" />
        </span>
      ) : null}
    </span>
  )
}
