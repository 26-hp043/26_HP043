import { ACTUALS_PARAM } from '../voyage-management/voyageRules'

/**
 * 선박 상세의 탭 (`UIFLOW 2-8` · `DESIGN_SYSTEM §8` · #1772 · #1774).
 *
 * DOM 없이 검증할 수 있게 컴포넌트에서 분리한다 — 「어느 탭이 열리는가」는 **주소를 읽는
 * 규칙**이지 그리는 일이 아니다.
 */

/** 탭의 자리를 갖는 쿼리 파라미터 (`§8` 「자리는 주소가 갖는다」). */
export const TAB_PARAM = 'tab'

/**
 * 탭 넷 — `UIFLOW 2-8` 「화면 구성」이 정본이다. 순서도 그 절이 정한다.
 *
 * 넷째가 「데이터」가 아니라 **「계산」**인 이유는 그 절에 적혀 있다 — 자료 가져오기·
 * 내보내기는 `#890`이 항차 패널 안으로, 연료 내역 표는 `#1052` ⑵가 연도별 표 아래로
 * 자리를 이미 정해 두어, 남는 것이 계산 이력 하나다.
 */
export const VESSEL_TABS = [
  { id: 'overview', label: '개요' },
  { id: 'voyages', label: '항차' },
  { id: 'not-underway', label: '정박' },
  { id: 'calculations', label: '계산' },
] as const

export type VesselTabId = (typeof VESSEL_TABS)[number]['id']

const IDS: readonly string[] = VESSEL_TABS.map((tab) => tab.id)

/**
 * 주소가 가리키는 탭.
 *
 * ## 셋의 순서
 *
 * ⑴ **`?tab=`이 아는 값이면 그것** — 사용자가 마지막으로 고른 자리다.
 * ⑵ **아니면 `?actuals=`가 있을 때 항차** — 실시간 CII의 「이 항차 실적 입력」과 데이터
 *    점검의 「이 항차로」가 이 주소로 온다(`#1540` · `#1549`). 그 링크에는 `tab`이 없으므로
 *    ⑴을 지나 여기서 잡힌다. 반대로 사용자가 그 화면에서 개요를 누르면 `tab=overview`가
 *    적혀 ⑴이 이긴다 — 그러지 않으면 누를 때마다 항차로 되돌아온다.
 * ⑶ 그 밖에는 첫 탭.
 *
 * **모르는 값이면 첫 탭을 돌려주되 주소를 고쳐 쓰지 않는다**(`§8`) — 사용자가 친 것을
 * 화면이 지우지 않는다.
 */
export function currentTab(params: URLSearchParams): VesselTabId {
  const asked = params.get(TAB_PARAM)
  if (asked !== null && IDS.includes(asked)) return asked as VesselTabId
  if (params.get(ACTUALS_PARAM)) return 'voyages'
  return VESSEL_TABS[0].id
}
