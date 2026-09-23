/**
 * 지도 위 패널의 접힘 상태 (#1824).
 *
 * 컴포넌트 파일에서 함수를 내보내면 fast refresh가 깨지므로(`only-export-components`)
 * 규칙만 여기 둔다 — `fleetRules.ts`·`queryRules.ts`와 같은 자리다.
 */
/**
 * 패널 접힘을 기억하는 자리 (#1824).
 *
 * ⚠️ **서버에 보내지 않는다.** 기기마다 화면 폭이 다르고, 이건 계정의 설정이 아니라
 * **이 브라우저의 습관**이다. 저장이 막힌 환경(사생활 보호 창 등)에서도 화면이
 * 그대로 서야 하므로 읽기·쓰기를 모두 `try`로 감싼다.
 */
export const PANEL_KEY = 'bluelog.fleet.panelOpen'

/** 이 폭 아래에서는 접힌 채로 시작한다 — 360 패널이 남길 지도가 거의 없다. */
const PANEL_NARROW = 1100

export function initialPanelOpen(
  width: number = typeof window === 'undefined' ? PANEL_NARROW + 1 : window.innerWidth,
): boolean {
  try {
    const saved = window.localStorage.getItem(PANEL_KEY)
    // 한 번이라도 접거나 편 사람의 선택이 폭보다 앞선다.
    if (saved === 'true') return true
    if (saved === 'false') return false
  } catch {
    // 저장을 못 읽어도 폭으로 정한다.
  }
  return width > PANEL_NARROW
}

