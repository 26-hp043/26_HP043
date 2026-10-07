import { Link } from 'react-router'
import { GradeBadge } from '../../components/GradeBadge'
import { SCREEN_BY_ID } from '../../screens'
import { VESSEL_QUERY_KEY } from '../../layout/globalContext'
import { regulationParametersPath } from '../parameters/referenceRules'
import { shipTypeLabel } from '../vessel-registration/shipTypes'
import { UnderwayChip } from './UnderwayChip'
import {
  daysToDText,
  showsDaysToD,
  unavailableHint,
  unavailableText,
  ytdCiiText,
} from './fleetRules'
import type { FleetAction, FleetVessel } from './types'
import './CheckTable.css'

/*
 * 「확인할 선박」 표 (10/7 시안 01).
 *
 * 종전에는 지도 위 좌측 패널에 **「조치 필요」 카드와 선박 카드 목록이 따로** 있었다. 같은 배가
 * 두 번 나오고(조치 카드 · 선박 카드), 그 배에 **무엇을 해야 하는지**는 조치 문구를 읽고 스스로
 * 찾아가야 했다. 한 행에 「누적 등급 · 왜 · 다음 작업」을 함께 둔다.
 *
 * 값은 전부 이미 받은 선대 요약에서 온다 — 서버를 더 부르지 않는다. 순서는 받은 목록의 정렬
 * (상단 셀렉트) 그대로이고, 조치가 걸린 배를 맨 위로만 올린다.
 */
export function CheckTable({
  vessels,
  actions,
  onLocate,
  compact = false,
}: {
  vessels: readonly FleetVessel[]
  actions: readonly FleetAction[]
  /** 지도에서 이 배를 보여 준다. 지도가 없거나 좌표가 없으면 `undefined`를 돌려준다. */
  onLocate: (vessel: FleetVessel) => (() => void) | undefined
  /** 좁은 자리 — 「왜」를 선박 칸 아래 줄로 접고 열을 셋으로 둔다. */
  compact?: boolean
}) {
  const actionBy = new Map<string, FleetAction>()
  for (const action of actions) if (!actionBy.has(action.vesselId)) actionBy.set(action.vesselId, action)
  const rows = [...vessels].sort(
    (a, b) => Number(actionBy.has(b.id)) - Number(actionBy.has(a.id)),
  )

  return (
    <div className="check__scroll">
      <table className="check">
        <thead>
          <tr>
            <th scope="col">선박</th>
            <th scope="col">누적 등급</th>
            {compact ? null : <th scope="col">왜</th>}
            <th scope="col" className="check__next-h">
              다음 작업
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((vessel) => {
            const action = actionBy.get(vessel.id)
            const locate = onLocate(vessel)
            return (
              <tr key={vessel.id} className={action ? 'check__row check__row--action' : 'check__row'}>
                <td>
                  <span className="check__name-line">
                    <Link className="check__name" to={`/vessels/${vessel.id}`}>
                      {vessel.name}
                    </Link>
                    {locate === undefined ? null : (
                      <button
                        type="button"
                        className="check__locate"
                        onClick={locate}
                        aria-label={`지도에서 ${vessel.name} 보기`}
                        title="지도에서 보기"
                      >
                        <PinIcon />
                      </button>
                    )}
                  </span>
                  <span className="check__meta">
                    {shipTypeLabel(vessel.shipType)} · <UnderwayChip vessel={vessel} />
                  </span>
                  {compact ? (
                    <span className="check__why check__why--inline">
                      <WhyText vessel={vessel} action={action} />
                    </span>
                  ) : null}
                </td>
                <td>
                  <span className="check__grade">
                    <GradeBadge rating={vessel.ytdRating} size="sm" />
                    <span className="check__value">{ytdCiiText(vessel.ytdAttainedCii)}</span>
                  </span>
                </td>
                {compact ? null : (
                  <td className="check__why">
                    <WhyText vessel={vessel} action={action} />
                  </td>
                )}
                <td className="check__next">
                  <NextStep vessel={vessel} action={action} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function WhyText({ vessel, action }: { vessel: FleetVessel; action: FleetAction | undefined }) {
  if (action !== undefined) {
    return (
      <>
        <span className="check__why-main">{action.message}</span>
        {vessel.isCiiApplicableHint ? null : (
          <span className="check__why-sub">규제 대상 여부 확인 필요</span>
        )}
      </>
    )
  }
  if (!vessel.dataAvailable) {
    return (
      <>
        <span className="check__why-muted" title={unavailableHint(vessel.unavailableReason)}>
          {unavailableText(vessel.unavailableReason)}
        </span>
        {/*
          「기준값 없음」은 사용자가 할 수 있는 것이 없는 사유라 그 절로 가는 길을 둔다
          (`#1516` · `#1239` 결정 A) — 종전 선박 카드(`VesselRow`)가 갖던 링크다.
        */}
        {vessel.unavailableReason === 'NO_PARAMETERS' ? (
          <Link className="check__why-sub" to={regulationParametersPath()}>
            규제 기준값 보기
          </Link>
        ) : null}
      </>
    )
  }
  if (showsDaysToD(vessel.daysToD, vessel.daysToDReason)) {
    return <span className="check__why-main">{daysToDText(vessel.daysToD, vessel.daysToDReason)}</span>
  }
  return <span className="check__why-muted">이상 없음</span>
}

function NextStep({ vessel, action }: { vessel: FleetVessel; action: FleetAction | undefined }) {
  if (action !== undefined && !vessel.isCiiApplicableHint) {
    return <Link to={`/vessels/${vessel.id}`}>제원 확인</Link>
  }
  if (action !== undefined) {
    return <Link to={SCREEN_BY_ID.FLEET_REDUCTION.path}>감축 계획 세우기</Link>
  }
  if (vessel.dataAvailable && showsDaysToD(vessel.daysToD, vessel.daysToDReason)) {
    return (
      <Link
        to={`${SCREEN_BY_ID.ANNUAL_GRADE.path}?${new URLSearchParams({ [VESSEL_QUERY_KEY]: vessel.id })}`}
      >
        연말 등급 보기
      </Link>
    )
  }
  return (
    /* role 없는 `<span>`의 `aria-label`은 무시된다(`a11yWiring`) — 대시는 감추고 낭독 글자를 따로 둔다. */
    <span className="check__none">
      <span aria-hidden="true">—</span>
      <span className="sr-only">없음</span>
    </span>
  )
}

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
      <path
        d="M12 21s-6-5.6-6-11a6 6 0 1 1 12 0c0 5.4-6 11-6 11z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <circle cx="12" cy="10" r="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}
