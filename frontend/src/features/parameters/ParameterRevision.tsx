import { useCallback, useEffect, useRef, useState } from 'react'
import { isOffice, type CurrentUser } from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'
import { ErrorState } from '../../components/ErrorState'
import { formatTimestamp } from '../../display/format'
import { RevisionError, type ParameterRevisionProvider } from './revisionProvider'
import {
  COMMIT_NOTICE,
  MAX_ROWS,
  PARAMETER_KINDS,
  actorLabel,
  canCommit,
  kindLabel,
  revisionSummary,
  validateFile,
  type ParameterImportResult,
  type ParameterKind,
  type ParameterRevisionEvent,
} from './revisionRules'
import './ParameterRevision.css'

/**
 * 규제 기준값 개정 — 적재와 개정 이력 (`#1517` · `#1239` 결정 D·E·F·H).
 *
 * ## 적재와 이력을 한 컴포넌트에 두는 이유
 *
 * 사무직의 일은 「올린다」에서 끝나지 않고 **「무엇이 들어갔는지 확인한다」**까지다. 둘을
 * 가르면 적재만 먼저 보이고 확인할 자리가 없어진다 — `AGENTS §6.1`이 `#236`으로 적은
 * 「있는데 반쪽만 동작한다」 모양이다(`#1239` 결정 H). 그래서 확정이 끝나면 곧바로 아래
 * 이력을 다시 불러 방금 올린 판본이 맨 위에 보이게 한다.
 *
 * ## 역할 (`#1239` 결정 D)
 *
 * 적재와 이력은 **사무직 이상**이다(서버 `require_office`). 현장직에게는 이 영역을 숨기지
 * 않고 **왜 잠겼는지**를 보인다(`UIFLOW §2.2` 「숨기지 않는다」). 둘러보기 세션은 역할이
 * 관리자라 화면은 열리지만 서버가 쓰기와 감사 조회를 403으로 막는다 — 그 문구를 그대로 보인다.
 */
export function ParameterRevision({
  user,
  provider,
  onImported,
}: {
  user: CurrentUser | null
  provider: ParameterRevisionProvider
  /** 확정 뒤 조회 표를 다시 불러오게 한다(조회 절이 넘긴다). */
  onImported?: () => void
}) {
  const office = isOffice(user)
  return (
    <section className="param-revision" aria-labelledby="param-revision-title">
      <h3 id="param-revision-title" className="param-revision__title">
        개정 적재
      </h3>
      {office ? (
        <RevisionWorkspace provider={provider} onImported={onImported} />
      ) : (
        <p className="param-revision__locked">
          <span className="param-revision__badge">사무직 전용</span> {OFFICE_ONLY_ACTION_HINT} 기준값
          조회는 위 표에서 할 수 있습니다.
        </p>
      )}
    </section>
  )
}

function RevisionWorkspace({
  provider,
  onImported,
}: {
  provider: ParameterRevisionProvider
  onImported?: () => void
}) {
  const [historyKey, setHistoryKey] = useState(0)
  return (
    <>
      <ImportForm
        provider={provider}
        onImported={() => {
          onImported?.()
          // 확정 직후 이력을 다시 불러 방금 올린 판본을 보인다.
          setHistoryKey((key) => key + 1)
        }}
      />
      <RevisionHistory key={historyKey} provider={provider} />
    </>
  )
}

function ImportForm({
  provider,
  onImported,
}: {
  provider: ParameterRevisionProvider
  onImported: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [kind, setKind] = useState<ParameterKind>('regulation_years')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ParameterImportResult | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState<'check' | 'commit' | null>(null)
  const spec = PARAMETER_KINDS.find((item) => item.kind === kind) ?? PARAMETER_KINDS[0]

  function invalidate() {
    // 종류나 파일이 바뀌면 앞의 검증 결과는 무효다 — 남겨 두면 다른 파일의 결과를 보고 확정한다.
    setResult(null)
    setFailure(null)
  }

  async function run(dryRun: boolean) {
    const invalid = validateFile(file)
    if (invalid !== null) {
      setFailure(invalid)
      return
    }
    setBusy(dryRun ? 'check' : 'commit')
    setFailure(null)
    try {
      const next = await provider.importParameters(kind, file as File, { dryRun })
      setResult(next)
      if (!next.dryRun) {
        setFile(null)
        if (inputRef.current) inputRef.current.value = ''
        onImported()
      }
    } catch (error) {
      setFailure(error instanceof RevisionError ? error.message : '적재하지 못했습니다.')
      setResult(null)
    } finally {
      setBusy(null)
    }
  }

  const ready = canCommit(result)
  const commitBlocked = file !== null && !ready && failure === null

  return (
    <div className="param-revision__form">
      <div className="param-revision__row">
        <label htmlFor="param-revision-kind">종류</label>
        <select
          id="param-revision-kind"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value as ParameterKind)
            invalidate()
          }}
        >
          {PARAMETER_KINDS.map((item) => (
            <option key={item.kind} value={item.kind}>
              {item.label}
            </option>
          ))}
        </select>
      </div>

      <details className="param-revision__format">
        <summary>형식 보기</summary>
        <p className="param-revision__hint">
          필수 컬럼 — <code>{spec.requiredColumns.join(', ')}</code>
        </p>
        {spec.note ? <p className="param-revision__hint">{spec.note}</p> : null}
        <p className="param-revision__hint">
          UTF-8 · 최대 5MB · {MAX_ROWS.toLocaleString('ko-KR')}행까지. 한 행이라도 문제가 있으면
          아무것도 들어가지 않습니다.
        </p>
      </details>

      <div className="param-revision__row">
        <input
          ref={inputRef}
          id="param-revision-file"
          type="file"
          accept=".csv,text/csv"
          aria-label="적재할 CSV 파일"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            invalidate()
          }}
        />
        <button type="button" onClick={() => run(true)} disabled={file === null || busy !== null}>
          {busy === 'check' ? '검증 중…' : '검증'}
        </button>
        <button
          type="button"
          className="param-revision__commit"
          onClick={() => run(false)}
          disabled={!ready || busy !== null}
          aria-describedby={commitBlocked ? 'param-revision-commit-note' : undefined}
        >
          {busy === 'commit' ? '적용 중…' : '확정'}
        </button>
      </div>

      {commitBlocked ? (
        <p id="param-revision-commit-note" className="param-revision__note">
          {result === null
            ? '먼저 검증하면 몇 행이 적용되고 무엇을 대체하는지 보고 확정할 수 있습니다.'
            : '문제가 있는 행을 고쳐 다시 검증해야 확정할 수 있습니다.'}
        </p>
      ) : null}

      {failure ? <ErrorState level="region" size="compact" message={failure} /> : null}

      {result ? (
        <div className="param-revision__result" role="status">
          <p
            className={
              result.dryRun
                ? 'param-revision__summary'
                : 'param-revision__summary param-revision__summary--done'
            }
          >
            {kindLabel(result.kind)} — {revisionSummary(result)}
          </p>
          {ready ? <p className="param-revision__warning">{COMMIT_NOTICE}</p> : null}
          {result.errors.length > 0 ? (
            <div className="param-revision__table-wrap">
              <table className="param-revision__errors">
                <caption>문제가 있는 행</caption>
                <thead>
                  <tr>
                    <th scope="col">행</th>
                    <th scope="col">항목</th>
                    <th scope="col">사유</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((error, index) => (
                    <tr key={`${error.row}-${error.field}-${index}`}>
                      <td className="num">{error.row}</td>
                      <td>
                        <code>{error.field}</code>
                      </td>
                      <td>{error.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function RevisionHistory({ provider }: { provider: ParameterRevisionProvider }) {
  const [events, setEvents] = useState<ParameterRevisionEvent[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'more'>('loading')
  const [failure, setFailure] = useState<string | null>(null)

  const load = useCallback(
    async (cursor: string | null) => {
      setState(cursor ? 'more' : 'loading')
      setFailure(null)
      try {
        const page = await provider.listRevisions(cursor)
        setEvents((prev) => (cursor ? [...prev, ...page.events] : page.events))
        setNextCursor(page.nextCursor)
      } catch (error) {
        setFailure(error instanceof RevisionError ? error.message : '개정 이력을 불러오지 못했습니다.')
      } finally {
        setState('ready')
      }
    },
    [provider],
  )

  useEffect(() => {
    void load(null)
  }, [load])

  return (
    <div className="param-revision__history" aria-labelledby="param-revision-history-title">
      <h4 id="param-revision-history-title" className="param-revision__subtitle">
        개정 이력
      </h4>
      {state === 'loading' ? <p className="param-revision__note">불러오는 중…</p> : null}
      {failure ? <ErrorState level="region" size="compact" message={failure} /> : null}
      {state !== 'loading' && !failure && events.length === 0 ? (
        <p className="param-revision__note">
          아직 화면에서 적재한 개정이 없습니다. 지금 표의 값은 처음 설치할 때 넣은 기준값입니다.
        </p>
      ) : null}
      {events.length > 0 ? (
        <div className="param-revision__table-wrap">
          <table className="param-revision__events">
            <thead>
              <tr>
                <th scope="col">시각</th>
                <th scope="col">종류</th>
                <th scope="col">누가</th>
                <th scope="col">적용 · 대체</th>
                <th scope="col">판본</th>
                <th scope="col">출처</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{formatTimestamp(event.timestamp)}</td>
                  <td>{kindLabel(event.kind)}</td>
                  <td>{actorLabel(event)}</td>
                  <td className="num">
                    {event.importedCount ?? '—'} · {event.replacedCount ?? '—'}
                  </td>
                  <td>
                    <code>{event.version ?? '—'}</code>
                  </td>
                  <td>{event.sourceRefs.length > 0 ? event.sourceRefs.join(', ') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {nextCursor && !failure ? (
        <button
          type="button"
          className="param-revision__more"
          onClick={() => void load(nextCursor)}
          disabled={state === 'more'}
        >
          {state === 'more' ? '불러오는 중…' : '더 보기'}
        </button>
      ) : null}
    </div>
  )
}
