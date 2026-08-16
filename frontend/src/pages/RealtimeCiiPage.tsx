import { RealtimeCiiView } from '../features/realtime-cii/RealtimeCiiView'

/**
 * 실시간 CII 화면 (`UIFLOW 2-9` · `#357`).
 *
 * 라우트는 `/vessels/:vesselId/voyages/:voyageId`지만 **`voyageId`를 쓰지 않는다.**
 * 3종 값 엔드포인트(`#354`)가 선박 리소스에 걸려 있고, 「지금 어느 항차인가」는
 * 서버가 판정한다 — 화면이 항차를 고르면 서버 판정과 갈라질 수 있다.
 *
 * 선박 상세는 이 경로에 `voyageId`로 `current`를 넣어 링크한다.
 */
export function RealtimeCiiPage() {
  return <RealtimeCiiView />
}
