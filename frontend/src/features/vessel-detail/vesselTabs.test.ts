import { describe, expect, it } from 'vitest'
import { currentTab, TAB_PARAM, VESSEL_TABS } from './vesselTabs'

/**
 * 어느 탭이 열리는가 — 주소를 읽는 규칙 (`UIFLOW 2-8` · #1774).
 */

const at = (query: string) => currentTab(new URLSearchParams(query))

describe('탭의 자리는 주소가 갖는다 (#1774)', () => {
  it('아무것도 없으면 첫 탭이다', () => {
    expect(at('')).toBe('overview')
    expect(VESSEL_TABS[0].id).toBe('overview')
  })

  it.each(VESSEL_TABS)('`$label` 탭을 주소로 지정할 수 있다', (tab) => {
    expect(at(`${TAB_PARAM}=${tab.id}`)).toBe(tab.id)
  })

  /*
   * 실시간 CII의 「이 항차 실적 입력」과 데이터 점검의 「이 항차로」가 이 주소로 온다
   * (`#1540` · `#1549`). 그 링크에는 `tab`이 없으므로 여기서 잡히지 않으면 개요에 떨어지고,
   * 패널이 마운트되지 않아 **폼이 열리지 않는다.**
   */
  it('`actuals`만 있으면 항차 탭이다', () => {
    expect(at('actuals=vy-9')).toBe('voyages')
  })

  it('`tab`이 `actuals`를 이긴다 — 그러지 않으면 누를 때마다 항차로 되돌아온다', () => {
    expect(at(`actuals=vy-9&${TAB_PARAM}=overview`)).toBe('overview')
  })

  it('모르는 값이면 첫 탭이다 — 주소를 고쳐 쓰는 일은 화면이 하지 않는다', () => {
    expect(at(`${TAB_PARAM}=없는탭`)).toBe('overview')
    // `actuals`가 함께 있으면 그쪽으로 떨어진다 — 모르는 값은 없는 것과 같다.
    expect(at(`${TAB_PARAM}=없는탭&actuals=vy-9`)).toBe('voyages')
  })

  it('빈 `actuals`는 없는 것으로 본다', () => {
    expect(at('actuals=')).toBe('overview')
  })
})
