import { FleetDashboard } from '../features/fleet/FleetDashboard'

/**
 * `UIFLOW v2.0` 2-4 대시보드 — 로그인 직후 기본 진입 경로.
 *
 * 관리 중심 전환(`#343`·`#344`)으로 종전 `1-3 메인보드`와 `2-4 선대 모니터링`이
 * 같은 화면이 됐다(`PRD §6.2 SCR-001`). 화면 ID는 참조 보존을 위해 그대로 둔다.
 *
 * 페이지는 자리만 잡고 내용은 `features/fleet`이 소유한다 — 선대 요약 API가 붙을 때
 * provider만 갈아 끼우면 되도록(`#138`이 기능①에서 한 전환과 같은 구조).
 */
export function MainboardPage() {
  return <FleetDashboard />
}
