import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { ErrorState } from '../../components/ErrorState'
import { GradeBadge } from '../../components/GradeBadge'
import { NO_TIMESTAMP_TEXT, currentKstYear, formatDecimalString, formatPercent, formatTimestamp } from '../../display/format'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { useYearOptions, yearStateText } from '../parameters/yearCatalog'
import { voyageActualsPath } from '../voyage-management/voyageRules'
import { createApiDataQualityProvider } from './apiProvider'
import {
  DATA_QUALITY_COPY as COPY,
  IMPACT_REASON,
  PUBLIC_RECORD_FIELD_LABEL,
  SEVERITY_MEANING,
  SEVERITY_TITLE,
  UNRECONCILED_REASON_LABEL,
  publicRecordSourceText,
  reasonText,
} from './copy'
import { IMPACT_DIGITS, orderedIssues } from './issueOrder'
import {
  SEVERITIES,
  UNRECONCILED_REASONS,
  type DataQualityIssue,
  type DataQualityProvider,
  type DataQualitySnapshot,
  type PublicRecord,
  type PublicRecordCoverage,
  type PublicRecordMismatch,
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

/**
 * 「이 값으로 채우기」 한 번 (#1923). **실패하면 문구를, 성공하면 `null`을** 돌려준다 —
 * 오류는 누른 줄 곁에 적어야 어느 칸이 거절됐는지 보인다.
 */
type FillHandler = (
  issue: DataQualityIssue,
  record: PublicRecord,
  mismatch: PublicRecordMismatch,
  revertConfirmed: boolean,
) => Promise<string | null>

export function DataQuality({ provider }: { provider?: DataQualityProvider }) {
  const api = useMemo(() => provider ?? createApiDataQualityProvider(), [provider])
  const yearOptions = useYearOptions(FLEET_KEY, { throughCurrentYear: true })
  const { years, loading: yearsLoading } = yearOptions
  /** 목록이 없으면 연도 칸 자리에 보일 상태 문구 — 로딩·실패·빈 목록이 서로 다르다 (#2120). */
  const yearText = yearStateText(yearOptions)
  /** 사용자가 고른 해. 화면에 쓰는 값은 아래 `year`다 — 목록과 대조해 렌더 중에 정한다. */
  const [chosenYear, setChosenYear] = useState('')
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  /** 채운 뒤 다시 불러오는 열쇠 — 채운 칸의 어긋남이 목록에서 사라지는 것까지 보여야 한다. */
  const [reloadKey, setReloadKey] = useState(0)
  /** 채운 결과 한 줄(`role="status"`) — 다시 불러오면 그 행이 사라지므로 무엇을 했는지 남긴다. */
  const [notice, setNotice] = useState<string | null>(null)

  /*
   * 기본 연도는 **렌더 중에 파생**한다 (`#1616`). 종전에는 목록이 오면 effect가 상태를
   * 채워, 목록 도착과 기본값 사이에 연도가 빈 렌더가 한 번 있었다. 고른 해가 목록에
   * 있으면 그것, 없으면 올해, 올해도 없으면 가장 최근 해다(`pickDefaultYear`). 목록이
   * 비어 있으면 `''`다 — 그때만 서버 기본(올해)으로 부른다.
   */
  const year = pickDefaultYear(years, currentKstYear(), chosenYear)

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
  }, [api, year, yearsLoading, reloadKey])

  const fill: FillHandler | undefined = api.fill
    ? async (issue, record, mismatch, revertConfirmed) => {
        if (issue.voyageId === null || mismatch.callYear === null || mismatch.callSeq === null) {
          return COPY.fillFailed
        }
        try {
          const result = await api.fill!(issue.voyageId, {
            field: mismatch.field,
            periodId: mismatch.periodId,
            record: {
              source: record.source,
              portAuthorityCode: mismatch.portAuthorityCode,
              callYear: mismatch.callYear,
              callSeq: mismatch.callSeq,
            },
            recordedAt: mismatch.recordedAt,
            revertConfirmed,
          })
          const label = PUBLIC_RECORD_FIELD_LABEL[mismatch.field]
          const voyageNo = issue.voyageNo ?? ''
          setNotice(
            result.revertedFromStatus === null
              ? COPY.fillDone(label, voyageNo)
              : COPY.fillDoneReverted(label, voyageNo),
          )
          setReloadKey((key) => key + 1)
          return null
        } catch (error) {
          return error instanceof Error ? error.message : COPY.fillFailed
        }
      }
    : undefined

  return (
    <section className="dq">
      <div className="dq__controls">
        <label className="dq__field" htmlFor={yearText === null ? 'dq-year' : undefined}>
          <span className="dq__label">{COPY.yearLabel}</span>
          {yearText !== null ? (
            <span className="dq__note">{yearText}</span>
          ) : (
            <select id="dq-year" value={year} onChange={(event) => setChosenYear(event.target.value)}>
              {years.map((y) => (
                <option key={y} value={String(y)}>
                  {y}
                </option>
              ))}
            </select>
          )}
        </label>
        <p className="dq__note">{COPY.readOnlyNote}</p>
      </div>
      {notice !== null ? (
        <p className="dq__notice" role="status">
          {notice}
        </p>
      ) : null}

      {state.status === 'loading' ? (
        <p className="dq__placeholder" aria-live="polite">
          {COPY.loading}
        </p>
      ) : null}
      {state.status === 'error' ? (
        <ErrorState level="region" subject={COPY.loadSubject} message={state.message} />
      ) : null}
      {state.status === 'ready' ? <Result snapshot={state.snapshot} fill={fill} /> : null}
    </section>
  )
}

/**
 * 할 일 카드의 말 (10/7 디자인 결정) — 사유 코드 문장(「완료 상태 — 실적 확정 전」)만으로는
 * 「무엇이 문제고, 눌러서 무엇을 하는지」가 읽히지 않았다. 심각도마다 쉬운 제목 · 왜 중요한지 ·
 * 버튼에서 할 일을 정한다. 서버 사유 문장은 「상세」 줄에 그대로 남긴다(`reasonText`).
 */
const TASK_COPY: Record<
  (typeof SEVERITIES)[number],
  { title: string; why: string; action: string; vesselAction: string }
> = {
  UNCONFIRMED: {
    title: '항해는 끝났는데 실적이 확정되지 않았습니다',
    why: '확정 전이라 이 항차는 올해 누적 등급에 실측으로 들어가지 않습니다. 실적을 확인하고 「실적 확정」을 누르면 해결됩니다.',
    action: '실적 확정하러 가기',
    vesselAction: '선박에서 확인하기',
  },
  ANOMALY: {
    title: '입력한 연료가 속력에 비해 너무 많거나 적습니다',
    why: '속력으로 예상한 연료와 차이가 큽니다. 입력 실수일 수 있으니 연료 값을 확인하고, 맞다면 그대로 두어도 됩니다.',
    action: '연료 값 확인하기',
    vesselAction: '선박에서 확인하기',
  },
  SUBSTITUTED: {
    title: '실측 연료가 없어 추정값으로 계산했습니다',
    why: '실제 연료 기록 대신 속력 모델 값이 들어갔습니다. 실측 연료를 입력하면 등급이 실제 값으로 다시 계산됩니다.',
    action: '실측 연료 입력하기',
    vesselAction: '선박 제원 확인하기',
  },
  UNAVAILABLE: {
    title: '값이 빠져 CII를 계산하지 못했습니다',
    why: '거리나 연료, 선박 제원 중 빠진 값이 있어 이 부분은 누적 등급에서 빠져 있습니다.',
    action: '빠진 값 채우기',
    vesselAction: '선박 제원 채우기',
  },
  PUBLIC_RECORD: {
    title: '입력한 기록이 해양수산부 공적 기록과 다릅니다',
    why: '출항 · 입항 시각이나 항구가 공적 기록과 어긋납니다. 아래에서 두 값을 비교하고 맞는 쪽으로 고칠 수 있습니다.',
    action: '항차 기록 보기',
    vesselAction: '선박에서 확인하기',
  },
}

/**
 * 공적 기록 대조의 분모 한 줄 (#2114) — 「공적 기록과 다름 0건」 옆에 **견준 항차와 견주지 못한
 * 항차**를 함께 적는다. 0건 사유는 괄호에서 뺀다. 요약 띠의 다른 보조 줄(`unjudgedHint`)과 같은
 * 자리·모양이다 — 새 표현이 아니다.
 */
function PublicRecordCoverageNote({ coverage }: { coverage: PublicRecordCoverage }) {
  const reasons = UNRECONCILED_REASONS.filter((reason) => coverage.reasons[reason] > 0)
    .map((reason) => `${UNRECONCILED_REASON_LABEL[reason]} ${coverage.reasons[reason]}`)
    .join(' · ')
  const fetched = coverage.lastFetchedAt === null ? null : formatTimestamp(coverage.lastFetchedAt)
  return (
    <p className="dq-hero__note">
      {COPY.publicRecordCoverage(coverage.reconciled, coverage.unreconciled, reasons)}
      {' · '}
      {COPY.publicRecordLastFetched(fetched)}
    </p>
  )
}

function Result({ snapshot, fill }: { snapshot: DataQualitySnapshot; fill?: FillHandler }) {
  const [filter, setFilter] = useState<(typeof SEVERITIES)[number] | null>(null)
  if (snapshot.vessels.length === 0) {
    return <p className="dq__placeholder">{COPY.noVessels}</p>
  }
  /*
   * 서버가 준 배열을 **CII 영향 순**으로 다시 늘어놓는다 (#1766 · `issueOrder.ts`).
   * 원본은 그대로 둔다 — 정렬은 표시 순서이지 데이터가 아니다.
   */
  const allRows = orderedIssues(snapshot.issues)
  const rows = allRows
  const shown = filter === null ? allRows : allRows.filter((issue) => issue.severity === filter)

  return (
    <>
      {/*
        요약 띠 (#1766). 종전에는 카드 안의 4칸이었다 — 건수 넷과 완결성은 「한 덩어리의
        데이터」가 아니라 아래 목록을 읽는 눈금이라 면을 띄우지 않는다(`§5` 카드 예산).

        **결론 띠(`§8.6`)가 아니다.** 이 화면의 답은 하나가 아니라 성격이 다른 다섯 축의
        건수다 — 하나로 합치면 그 다섯을 한 수로 뭉갠다(`#1197`이 다섯째를 더했다).
      */}
      {/*
        요약 (10/7 디자인 결정) — 같은 크기 타일 여섯이 「무엇부터」를 말하지 않았다. 처리할 일
        건수와 완결성 두 숫자를 크게, 심각도별 건수는 거르기 칩으로 둔다. 0건 심각도는 지우지
        않고 한 칩에 모아 흐리게 둔다(`#513` — 지우면 「확인 안 함」과 구분되지 않는다).
      */}
      <section className="dq-hero" aria-label={COPY.summaryTitle}>
        <div className="dq-hero__stat">
          <span className="dq-hero__label">처리할 일</span>
          <span className="dq-hero__value">
            {rows.length}
            <span className="dq-hero__unit">{COPY.countSuffix}</span>
          </span>
        </div>
        <div className="dq-hero__stat dq-hero__stat--sep">
          <span className="dq-hero__label">{COPY.completenessLabel}</span>
          <span className="dq-hero__value">
            {snapshot.completenessRatio === null
              ? COPY.completenessNone
              : `${formatPercent(snapshot.completenessRatio)}%`}
          </span>
          <span className="dq-hero__hint">{COPY.completenessHint}</span>
        </div>
        <div className="dq-hero__chips" role="group" aria-label="심각도로 거르기">
          <button
            type="button"
            className="dq-chip"
            aria-pressed={filter === null}
            onClick={() => setFilter(null)}
          >
            전체 {rows.length}
          </button>
          {SEVERITIES.filter((sev) => snapshot.counts[sev] > 0).map((sev) => (
            <button
              key={sev}
              type="button"
              className={`dq-chip dq-chip--${sev.toLowerCase()}`}
              aria-pressed={filter === sev}
              onClick={() => setFilter((was) => (was === sev ? null : sev))}
            >
              {SEVERITY_TITLE[sev]} {snapshot.counts[sev]}
            </button>
          ))}
          {SEVERITIES.some((sev) => snapshot.counts[sev] === 0) ? (
            <span className="dq-chip dq-chip--zero">
              {SEVERITIES.filter((sev) => snapshot.counts[sev] === 0)
                .map((sev) => `${SEVERITY_TITLE[sev]} 0`)
                .join(' · ')}
            </span>
          ) : null}
        </div>
        {snapshot.anomalyUnjudged > 0 ? (
          <p className="dq-hero__note">{COPY.unjudgedHint(snapshot.anomalyUnjudged)}</p>
        ) : null}
        {snapshot.publicRecordCoverage ? (
          <PublicRecordCoverageNote coverage={snapshot.publicRecordCoverage} />
        ) : null}
      </section>

      <section className="card dq__list" aria-labelledby="dq-list-title">
        <h2 id="dq-list-title" className="card__title">
          {COPY.listTitle}
        </h2>
        {rows.some((issue) => issue.cii !== null) ? (
          <p className="dq__caption">{COPY.impactCaption}</p>
        ) : null}
        {rows.length === 0 ? (
          <p className="dq__empty">{COPY.noIssues}</p>
        ) : (
          <>
            {/*
              **한 표다** (#1766). 종전에는 심각도 그룹마다 같은 다섯 열짜리 표가 하나씩
              서서, 행 6건에 표 머리가 세 번 나왔다. 심각도는 열이 된다.

              0건 심각도를 지우는 것이 아니다 — 위 요약 띠가 「실적 확정 전 0건」으로 계속
              말한다(`#513`: 지우면 「확인 안 함」과 구분되지 않는다).
            */}
            {/*
              표 → 할 일 카드 (10/7) — 문제 문장을 제목으로 세우고, 각 카드 오른쪽에 갈 곳 하나.
            */}
            <ul className="dq-tasks">
              {shown.map((issue) => (
                <li
                  key={`${issue.vesselId}-${issue.voyageId ?? 'vessel'}-${issue.codes.join()}`}
                  className={`dq-task dq-task--${issue.severity.toLowerCase()}`}
                >
                  <div className="dq-task__body">
                    <span className="dq-task__meta">
                      <span className={`dq__severity dq__severity--${issue.severity.toLowerCase()}`}>
                        {SEVERITY_TITLE[issue.severity]}
                      </span>
                      <span>{issue.vesselName}</span>
                      <span>· {issue.voyageId === null ? COPY.vesselLevel : (issue.voyageNo ?? '—')}</span>
                    </span>
                    <h3 className="dq-task__title">{TASK_COPY[issue.severity].title}</h3>
                    <p className="dq-task__why">{TASK_COPY[issue.severity].why}</p>
                    <p className="dq-task__detail">
                      <span>
                        상세 · {issue.codes.map((code) => reasonText(code)).join(' · ')}
                      </span>
                      {issue.cii !== null ? (
                        <span>
                          · 누적 CII 영향 <Impact issue={issue} />
                        </span>
                      ) : null}
                    </p>
                    {issue.publicRecord ? (
                      <PublicRecordDetail issue={issue} record={issue.publicRecord} fill={fill} />
                    ) : null}
                  </div>
                  {/*
                    항차 행은 **그 항차 카드로** 간다 (#1549) — 실적을 넣을 수 있는 항차면 입력이 열린 채
                    도착한다(`#1540`). 선박 단위 행은 선박 상세.
                  */}
                  {issue.voyageId === null ? (
                    <Link className="dq-task__go" to={`/vessels/${issue.vesselId}`}>
                      {TASK_COPY[issue.severity].vesselAction}
                    </Link>
                  ) : (
                    <Link
                      className={`dq-task__go${issue.severity === 'UNCONFIRMED' ? ' dq-task__go--primary' : ''}`}
                      to={voyageActualsPath(issue.vesselId, issue.voyageId)}
                      aria-label={`${TASK_COPY[issue.severity].action} — ${issue.vesselName} ${issue.voyageNo ?? ''}`.trim()}
                    >
                      {TASK_COPY[issue.severity].action} →
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
        {/*
          심각도 다섯의 뜻은 `DESIGN_SYSTEM §2.3.1` 「의미」 열이라 화면에서 없애지 않는다.
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
                    <span className="dq-bar">
                      <span className="dq-bar__track" aria-hidden="true">
                        <span
                          className={`dq-bar__fill${vessel.completenessRatio !== null && formatPercent(vessel.completenessRatio) !== '100.0' ? ' dq-bar__fill--gap' : ''}`}
                          style={{
                            inlineSize:
                              vessel.completenessRatio === null
                                ? '0%'
                                : `${formatPercent(vessel.completenessRatio)}%`,
                          }}
                        />
                      </span>
                      {vessel.completenessRatio === null
                        ? '—'
                        : `${formatPercent(vessel.completenessRatio)}%`}
                    </span>
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
 * 공적 기록과의 어긋남 — 항목마다 「입력 / 공적 기록(항만청)」 두 칸 비교와 차이(#1197 · #2359).
 *
 * **출처는 행 아래에 함께 적는다.** 그룹으로 묶지 않고 한 표에 늘어놓는 화면이라
 * (`#1766`), 어느 행이 어느 출처·수집 시각을 근거로 하는지는 그 행에 붙어야 흔들리지
 * 않는다.
 */
function PublicRecordDetail({
  issue,
  record,
  fill,
}: {
  issue: DataQualityIssue
  record: PublicRecord
  fill?: FillHandler
}) {
  return (
    <>
      <ul className="dq__mismatches">
        {record.mismatches.map((mismatch, index) => {
          const hours = Math.floor(mismatch.differenceMinutes / 60)
          const minutes = mismatch.differenceMinutes % 60
          const authority = mismatch.portAuthorityName ?? mismatch.portAuthorityCode
          return (
            // 한 항차에 정박 구간이 둘이면 같은 칸(`BERTH_START`)이 두 줄이다 — 순번을 붙인다.
            <li key={`${mismatch.field}-${index}`} className="dq__mismatch">
              {/* 「입력 / 공적 기록」 두 칸 비교 + 차이만 강조 (#2359). */}
              <span className="dq__mismatch-field">{PUBLIC_RECORD_FIELD_LABEL[mismatch.field]}</span>
              <dl className="dq__compare">
                <div className="dq__compare-cell">
                  <dt>{COPY.publicRecordEntered}</dt>
                  {/* 읽을 수 없는 시각은 값 없음으로 적는다 (#2124). */}
                  <dd>{formatTimestamp(mismatch.enteredAt) ?? NO_TIMESTAMP_TEXT}</dd>
                </div>
                <div className="dq__compare-cell">
                  <dt>{COPY.publicRecordRecorded(authority)}</dt>
                  <dd>{formatTimestamp(mismatch.recordedAt) ?? NO_TIMESTAMP_TEXT}</dd>
                </div>
              </dl>
              <strong className="dq__mismatch-diff">{COPY.publicRecordDifference(hours, minutes)}</strong>
              {fill && canFill(issue, mismatch) ? (
                <FillControl issue={issue} record={record} mismatch={mismatch} fill={fill} />
              ) : null}
            </li>
          )
        })}
      </ul>
      <p className="dq__source">
        {COPY.publicRecordSourceNote(publicRecordSourceText(record.source), formatTimestamp(record.fetchedAt))}
      </p>
    </>
  )
}

/**
 * 이 줄에 「이 값으로 채우기」를 둘 수 있는가 (#1923).
 *
 * 보낼 열쇠가 없으면(옛 서버 · 항차 없는 행 · 구간 id 없는 정박 칸) 두지 않는다 — 눌러도 서버가
 * 거절할 버튼을 보이지 않는다.
 */
function canFill(issue: DataQualityIssue, mismatch: PublicRecordMismatch): boolean {
  if (issue.voyageId === null || mismatch.callYear === null || mismatch.callSeq === null) return false
  const berth = mismatch.field === 'BERTH_START' || mismatch.field === 'BERTH_END'
  return !berth || mismatch.periodId !== null
}

/**
 * 「이 값으로 채우기」 버튼과 확정 항차의 재확인 줄 (#1923 · `PRD §17.4.4`).
 *
 * **누르지 않으면 아무것도 바뀌지 않는다.** 완료 항차·정박 구간은 누르면 바로 그 칸만 채운다.
 * **확정 항차는 바로 채우지 않고 재확인 줄을 연다** — 확정을 되돌린다는 사실을 적고, 실행 버튼
 * (「확정을 되돌리고 채우기」)을 눌러야 `revert_confirmed: true`로 보낸다(`API_SPEC §3.12` · 결정 B).
 *
 * 모달을 두지 않는다 — `VoyagePanel`의 확인 줄(#1598)과 같은 이유다: 저장소에 아직 모달이 없고,
 * 확인할 대상(어긋남 한 줄)이 바로 위에 보여야 판단할 수 있다. 버튼 모양·줄 표현은
 * `DESIGN_SYSTEM §2.3.1` 〔**확정** 2026-10-07 · `#2154`〕다.
 */
function FillControl({
  issue,
  record,
  mismatch,
  fill,
}: {
  issue: DataQualityIssue
  record: PublicRecord
  mismatch: PublicRecordMismatch
  fill: FillHandler
}) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const keepRef = useRef<HTMLButtonElement>(null)
  const cautionId = useId()
  const confirmed = record.voyageStatus === 'CONFIRMED'

  useEffect(() => {
    // 줄이 열리면 **안전한 쪽**(「그만두기」)에 초점 — Enter를 한 번 더 눌러 실행되지 않게.
    if (confirming) keepRef.current?.focus()
  }, [confirming])

  const close = () => {
    setConfirming(false)
    triggerRef.current?.focus()
  }

  const submit = async (revertConfirmed: boolean) => {
    setBusy(true)
    setError(null)
    const failure = await fill(issue, record, mismatch, revertConfirmed)
    // 성공하면 목록을 다시 불러오며 이 줄이 사라진다 — 실패했을 때만 상태를 되돌린다.
    if (failure !== null) {
      setBusy(false)
      setConfirming(false)
      setError(failure)
    }
  }

  return (
    <div className="dq__fill">
      <button
        type="button"
        ref={triggerRef}
        className="dq__fill-action"
        disabled={busy}
        aria-expanded={confirmed ? confirming : undefined}
        aria-label={[COPY.fillAction, '—', PUBLIC_RECORD_FIELD_LABEL[mismatch.field], formatTimestamp(mismatch.recordedAt)]
          .filter((part) => part !== null)
          .join(' ')}
        onClick={() => {
          if (confirmed) setConfirming(true)
          else void submit(false)
        }}
      >
        {busy ? COPY.fillBusy : COPY.fillAction}
      </button>
      {confirming ? (
        <div
          className="dq__fill-caution"
          role="group"
          aria-labelledby={cautionId}
          onKeyDown={(event) => {
            if (event.key === 'Escape') close()
          }}
        >
          <p id={cautionId} className="dq__fill-caution-text">
            {COPY.fillConfirmedCaution}
          </p>
          <div className="dq__fill-caution-actions">
            <button
              type="button"
              className="dq__fill-action"
              disabled={busy}
              onClick={() => void submit(true)}
            >
              {COPY.fillConfirmedAction}
            </button>
            <button type="button" ref={keepRef} className="dq__fill-keep" disabled={busy} onClick={close}>
              {COPY.fillKeep}
            </button>
          </div>
        </div>
      ) : null}
      {error !== null ? (
        <p className="dq__fill-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
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
