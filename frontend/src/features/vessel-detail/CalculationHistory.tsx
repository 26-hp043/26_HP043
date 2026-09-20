import { useCallback, useEffect, useState } from 'react'
import { ErrorState } from '../../components/ErrorState'
import { formatTimestamp } from '../../display/format'
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
 *
 * ## 목록과 오류를 한 상태에 담지 않는다 (`#1076` ⑵)
 *
 * 종전에는 `loading | error | ready` 한 덩어리라 **「더 보기」가 실패하는 순간 `ready`가
 * 통째로 `error`로 바뀌어 이미 받은 20건이 화면에서 사라졌다.** 표가 `ErrorState`로
 * 대체되고 「더 보기」 버튼도 `ready` 조건에 걸려 함께 사라져 **재시도할 자리조차
 * 없었다** — 사용자가 할 수 있는 일은 화면을 떠났다 돌아오는 것뿐이었다.
 *
 * 그래서 `rows`(받은 것)와 `failure`(못 받은 것)를 **따로 둔다.** 같은 화면의
 * 항차 기록(`voyage-management/VoyagePanel.tsx`)이 이미 이 모양이며, 거기 주석이
 * 「이어붙이던 중 실패하면 이미 받은 행을 지우지 않는다」로 근거를 적어 두었다.
 * 첫 페이지 실패만 빈 목록으로 떨어진다 — 그때는 보여 줄 것이 없다.
 */
export function CalculationHistory({
  vesselId,
  fetchImpl,
}: {
  vesselId: string
  /** 검사 주입점. */
  fetchImpl?: typeof globalThis.fetch
}) {
  /** `null`은 **「아직 모른다」**, 배열은 **「이만큼 받았다」**다 (`#824`와 같은 구분). */
  const [rows, setRows] = useState<CalculationRow[] | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  /** 서버가 센 전체 건수. 모르면 `null`이고, 그때는 건수를 적지 않는다 (`#1076` ⑵). */
  const [needsRecalcTotal, setNeedsRecalcTotal] = useState<number | null>(null)

  /**
   * 다음 페이지를 **뒤에 잇는다.** 첫 페이지는 아래 `useEffect`가 따로 부른다 —
   * 그쪽만 선박 전환 경합을 막는 취소 플래그가 필요하고, 실패했을 때 할 일도
   * 다르기 때문이다(여기서는 받은 행을 지키고, 그쪽은 빈 목록으로 떨어뜨린다).
   */
  const loadMore = useCallback(
    async (cursor: string) => {
      setFailure(null)
      setLoadingMore(true)
      try {
        const page = await fetchCalculationPage(vesselId, cursor, fetchImpl)
        setRows((prev) => [...(prev ?? []), ...page.rows])
        setNextCursor(page.nextCursor)
        setHasMore(page.hasMore)
        setNeedsRecalcTotal(page.needsRecalcTotal)
      } catch (error: unknown) {
        // 이어붙이던 중 실패하면 **이미 받은 행을 지우지 않는다** — `rows`를 건드리지
        // 않는 것이 이 `catch`의 핵심이다(`VoyagePanel`과 같은 규칙).
        setFailure(
          error instanceof Error ? error.message : '계산 이력을 불러오지 못했습니다.',
        )
      } finally {
        setLoadingMore(false)
      }
    },
    [vesselId, fetchImpl],
  )

  /*
   * 선박이 바뀌면 **비우고 시작한다** — 렌더 중에 조정한다(React가 「prop이 바뀔 때
   * 상태를 되돌리는」 자리로 권하는 형태이고, effect 안에서 하면 화면이 앞 선박의
   * 이력을 한 번 더 그린 뒤에야 비워진다).
   *
   * 비우지 않으면 앞 선박의 행과 **건수**가 다음 선박의 조회가 끝날 때까지 남는다 —
   * 「재계산 필요 3건」이 다른 배의 수인 채로 보이는 자리다(`ReportsView`의 항차
   * 칸이 `#874`에서 같은 이유로 고쳐졌다).
   */
  const [loadedVesselId, setLoadedVesselId] = useState(vesselId)
  if (loadedVesselId !== vesselId) {
    setLoadedVesselId(vesselId)
    setRows(null)
    setFailure(null)
    setNextCursor(null)
    setHasMore(false)
    setNeedsRecalcTotal(null)
  }

  useEffect(() => {
    let alive = true
    fetchCalculationPage(vesselId, null, fetchImpl)
      .then((page) => {
        if (!alive) return
        setRows(page.rows)
        setNextCursor(page.nextCursor)
        setHasMore(page.hasMore)
        setNeedsRecalcTotal(page.needsRecalcTotal)
      })
      .catch((error: unknown) => {
        if (!alive) return
        // 첫 페이지 실패는 빈 목록으로 떨어뜨린다 — 보여 줄 것이 없다. 그래도
        // 「계산이 없습니다」로 말하지 않는다(아래 `!failure` 조건).
        setRows([])
        setFailure(
          error instanceof Error ? error.message : '계산 이력을 불러오지 못했습니다.',
        )
      })
    return () => {
      alive = false
    }
  }, [vesselId, fetchImpl])

  return (
    <section className="card vd-calcs" aria-label="계산 이력">
      <div className="card__head">
        <h2 className="card__title">계산 이력</h2>
        {/*
         * 건수는 **서버가 센 전체**다 (`API_SPEC §1.9` `meta.needs_recalc_total` · `#1076`).
         * 종전에는 화면이 받은 페이지만 세어, 21번째 행부터 낡아 있어도 머리에
         * 「0건」이 찍혔다 — 「낡은 계산이 없다」와 「아직 다 세어 보지 않았다」가
         * 같은 모양이었다. 서버가 말해 주지 않으면(`null`) **적지 않는다.**
         */}
        {needsRecalcTotal !== null && needsRecalcTotal > 0 ? (
          <span className="card__meta" role="status">
            재계산 필요 {needsRecalcTotal}건
          </span>
        ) : null}
      </div>
      <p className="vd-calcs__lead">
        선박 제원이나 항차 계획이 바뀌면 그 뒤로 결과는 그대로 두고 「재계산 필요」로 표시합니다.
        다시 계산하려면 각 화면에서 새로 실행하세요.
      </p>
      {rows === null ? (
        <p className="vd-calcs__note" role="status">
          계산 이력을 불러오는 중입니다…
        </p>
      ) : null}
      {failure ? <ErrorState level="region" subject="계산 이력" message={failure} /> : null}
      {/*
       * 「계산이 없습니다」는 **실패했을 때 말하지 않는다.** 둘을 같이 띄우면 조회가
       * 실패한 선박이 계산을 한 번도 돌리지 않은 선박으로 읽힌다(`#1076` ⑴과 같은 결함).
       */}
      {rows !== null && rows.length === 0 && !failure ? (
        <p className="vd-calcs__note">이 선박으로 실행한 계산이 없습니다.</p>
      ) : null}
      {rows !== null && rows.length > 0 ? (
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
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{formatTimestamp(row.createdAt)}</td>
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
      {/*
       * 실패해도 버튼이 남는다 — **이 버튼이 재시도 수단이다** (`#1076` ⑵). 종전에는
       * 실패가 `ready`를 지워 버튼까지 함께 사라졌고, 남은 길은 화면을 떠났다
       * 돌아오는 것뿐이었다. 커서가 없는데 그리면 같은 페이지를 다시 부르므로
       * **둘 다 있을 때만** 그린다(`VoyagePanel`과 같은 조건).
       */}
      {rows !== null && hasMore && nextCursor !== null ? (
        <button
          type="button"
          className="vd-calcs__more"
          onClick={() => void loadMore(nextCursor)}
          disabled={loadingMore}
        >
          {loadingMore
            ? '이력을 더 불러오는 중…'
            : failure
              ? '다시 시도'
              : '이전 계산 더 보기'}
        </button>
      ) : null}
    </section>
  )
}
