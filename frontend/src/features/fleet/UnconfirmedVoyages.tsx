import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { SCREEN_BY_ID } from '../../screens'
import { createApiDataQualityProvider } from '../data-quality/apiProvider'
import type { DataQualityIssue, DataQualityProvider } from '../data-quality/types'
import { voyageActualsPath } from '../voyage-management/voyageRules'
import { UNCONFIRMED_VISIBLE, unconfirmedVoyages } from './fleetRules'

/**
 * 실적 확정 전 항차 — 대시보드의 「할 일」 카드 (#1573 · `UIFLOW 2-4`).
 *
 * 항차 실적 입력 · 확정은 세 역할 모두의 일이다(`UIFLOW §2.2` 각주). 그런데 확정을 기다리는
 * 항차 목록은 데이터 점검(`2-11`)의 표 안에만 있어, 로그인 직후 보는 대시보드에는 개수도
 * 입구도 없었다. 행마다 `#1540` · `#1549`와 같은 진입으로 **그 항차 카드에 실적 입력을 연 채**
 * 데려간다.
 *
 * ## 데이터는 데이터 점검 응답을 그대로 쓴다
 *
 * `GET /fleet/data-quality`(`API_SPEC §2.16`)의 `UNCONFIRMED` — COMPLETED → CONFIRMED 미전이.
 * 서버를 새로 두지 않는다. 대시보드 요약 조회와 **따로** 부른다 — 한쪽 실패가 다른 쪽을 막지
 * 않는다.
 *
 * ## 0건이면 그리지 않는다
 *
 * 경고 배너와 같은 규칙이다 — 없는 일을 상시 띄우면 배경이 된다. 조회 실패는 0건과 섞지
 * 않고 한 줄로 말한다.
 */
/**
 * `as`로 두 모양을 낸다 (#1824).
 *
 * - `card` — 종전 카드. 다른 화면이 쓰면 그대로다
 * - `cell` — **요약 띠의 한 칸.** 대시보드가 지도를 본문 전체로 펴면서 이 카드가 설
 *   자리가 없어졌다. `#1573`이 이미 「5건까지 보이고 나머지는 `2-11`로」를 정해
 *   두었으므로 **넘기는 자리를 하나로 합친 것**이고, 그 화면은 `#1766`이 할 일 한
 *   목록으로 다시 만든 자리라 행별 「이 항차로」가 거기서 더 잘 산다
 */
export function UnconfirmedVoyages({
  provider,
  as = 'card',
}: {
  provider?: DataQualityProvider
  as?: 'card' | 'cell'
}) {
  const api = useMemo(() => provider ?? createApiDataQualityProvider(), [provider])
  const [issues, setIssues] = useState<DataQualityIssue[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .load()
      .then((snapshot) => {
        if (alive) setIssues(snapshot.issues)
      })
      .catch(() => {
        if (alive) setFailed(true)
      })
    return () => {
      alive = false
    }
  }, [api])

  if (failed) {
    return (
      <p className="todo__failed">
        실적 확정 전 항차를 불러오지 못했습니다 ·{' '}
        <Link className="kpi__link" to={SCREEN_BY_ID.DATA_QUALITY.path}>
          {SCREEN_BY_ID.DATA_QUALITY.label}에서 보기
        </Link>
      </p>
    )
  }
  if (issues === null) return null

  const all = unconfirmedVoyages(issues)
  if (all.length === 0) return null

  /*
   * 띠의 한 칸 (#1824). 0건이면 위에서 이미 `null`이라 **칸이 아예 서지 않는다** —
   * 경고 배너와 같은 규칙(`#1573`)이고, 「0」을 띄워 두면 할 일이 없는 날에도 할 일
   * 칸이 자리를 차지한다.
   */
  if (as === 'cell') {
    return (
      <div className="kpi">
        <p className="kpi__label">실적 확정 전 항차</p>
        <p className="kpi__value">{all.length}</p>
        <p className="kpi__foot">
          <Link className="kpi__link" to={SCREEN_BY_ID.DATA_QUALITY.path}>
            데이터 점검에서 처리
          </Link>
        </p>
      </div>
    )
  }
  const shown = all.slice(0, UNCONFIRMED_VISIBLE)
  const rest = all.length - shown.length

  return (
    <section className="card" aria-label="실적 확정 전 항차">
      <div className="card__head">
        <h2 className="card__title">
          실적 확정 전 항차 <span className="todo__count">{all.length}건</span>
        </h2>
        <span className="card__meta">완료했지만 실적이 확정되지 않았습니다</span>
      </div>
      <ul className="todo__list">
        {shown.map((voyage) => (
          <li className="todo__row" key={voyage.voyageId}>
            <span className="todo__vessel">{voyage.vesselName}</span>
            <span className="todo__voyage">{voyage.voyageNo ?? '—'}</span>
            <Link
              className="todo__go"
              to={voyageActualsPath(voyage.vesselId, voyage.voyageId)}
              aria-label={`이 항차로 — ${voyage.vesselName} ${voyage.voyageNo ?? ''}`.trim()}
            >
              이 항차로
            </Link>
          </li>
        ))}
      </ul>
      {rest > 0 ? (
        <p className="todo__more">
          {rest}건 더 ·{' '}
          <Link className="kpi__link" to={SCREEN_BY_ID.DATA_QUALITY.path}>
            {SCREEN_BY_ID.DATA_QUALITY.label}에서 모두 보기
          </Link>
        </p>
      ) : null}
    </section>
  )
}
