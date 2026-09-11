import { useEffect, useState } from 'react'
import { ErrorState } from '../../components/ErrorState'
import { fetchCalculationPage, type CalculationRow } from './calculationRuns'

/**
 * 선박 상세 — **계산 이력과 재계산 필요 표시** (#992 · `PRD §8.4` · `API_SPEC §1.9`).
 *
 * 계산 결과는 고칠 수 없다(immutable). 선박 제원이나 그 항차의 계획이 바뀌면 결과를 지우지 않고
 * **「재계산 필요」로 표시**만 한다(`PRD §8.4`). 이 카드가 그 표시를 보여 주는 유일한 자리다 —
 * 표시만 켜지고 아무도 보지 않던 상태(`#776` 정정)를 끝낸다.
 *
 * 다시 계산하는 버튼은 두지 않는다 — 계산은 각 화면(CII 예측 · 항로 비교 · 연간 시뮬레이션)에서
 * 한다. 이 카드는 **무엇이 낡았는지**를 알린다. **개발 임시안.**
 */
type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; rows: CalculationRow[]; nextCursor: string | null; hasMore: boolean }

export function CalculationHistory({
  vesselId,
  fetchImpl,
}: {
  vesselId: string
  /** 검사 주입점. */
  fetchImpl?: typeof globalThis.fetch
}) {
  const [state, setState] = useState<State>({ status: 'loading' })
  const [loadingMore, setLoadingMore] = useState(false)

  useEffect(() => {
    let alive = true
    fetchCalculationPage(vesselId, null, fetchImpl)
      .then((page) => {
        if (alive) setState({ status: 'ready', ...page })
      })
      .catch((error: unknown) => {
        if (alive) {
          setState({
            status: 'error',
            message: error instanceof Error ? error.message : '계산 이력을 불러오지 못했습니다.',
          })
        }
      })
    return () => {
      alive = false
    }
  }, [vesselId, fetchImpl])

  async function loadMore() {
    if (state.status !== 'ready' || !state.nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const page = await fetchCalculationPage(vesselId, state.nextCursor, fetchImpl)
      setState((prev) =>
        prev.status === 'ready'
          ? { status: 'ready', rows: [...prev.rows, ...page.rows], nextCursor: page.nextCursor, hasMore: page.hasMore }
          : prev,
      )
    } catch (error: unknown) {
      setState({
        status: 'error',
        message: error instanceof Error ? error.message : '계산 이력을 불러오지 못했습니다.',
      })
    } finally {
      setLoadingMore(false)
    }
  }

  const stale = state.status === 'ready' ? state.rows.filter((r) => r.needsRecalc).length : 0

  return (
    <section className="card vd-calcs" aria-label="계산 이력">
      <div className="card__head">
        <h2 className="card__title">계산 이력</h2>
        {stale > 0 ? (
          <span className="card__meta" role="status">
            재계산 필요 {stale}건
          </span>
        ) : null}
      </div>
      <p className="vd-calcs__lead">
        선박 제원이나 항차 계획이 바뀌면 그 뒤로 결과는 그대로 두고 「재계산 필요」로 표시합니다.
        다시 계산하려면 각 화면에서 새로 실행하세요.
      </p>
      {state.status === 'loading' ? (
        <p className="vd-calcs__note" role="status">
          계산 이력을 불러오는 중입니다…
        </p>
      ) : null}
      {state.status === 'error' ? (
        <ErrorState level="region" subject="계산 이력" message={state.message} />
      ) : null}
      {state.status === 'ready' && state.rows.length === 0 ? (
        <p className="vd-calcs__note">이 선박으로 실행한 계산이 없습니다.</p>
      ) : null}
      {state.status === 'ready' && state.rows.length > 0 ? (
        <div className="history__tablebox">
          <table className="history__table">
            <thead>
              <tr>
                <th scope="col">일시</th>
                <th scope="col">종류</th>
                <th scope="col" className="num">
                  CII
                </th>
                <th scope="col">등급</th>
                <th scope="col">상태</th>
              </tr>
            </thead>
            <tbody>
              {state.rows.map((row) => (
                <tr key={row.id}>
                  <td>{new Date(row.createdAt).toLocaleString('ko-KR', { hour12: false })}</td>
                  <td>
                    {row.typeLabel}
                    {row.attachedToVoyage ? <span className="vd-calcs__tag">항차</span> : null}
                  </td>
                  <td className="num">{row.ciiText}</td>
                  <td>{row.rating ?? '—'}</td>
                  <td>
                    {row.needsRecalc ? (
                      <span className="vd-calcs__badge">재계산 필요</span>
                    ) : (
                      '현행'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {state.status === 'ready' && state.hasMore ? (
        <button type="button" className="vd-calcs__more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? '이력을 더 불러오는 중…' : '이전 계산 더 보기'}
        </button>
      ) : null}
    </section>
  )
}
