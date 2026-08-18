import { VesselManagement } from '../features/vessel-management/VesselManagement'

/**
 * 선박 관리 화면 (`PRD §6.2 SCR-002` · `PRD §6.1` 계층 밖 네비게이션 · #510).
 *
 * 등록(`1-2`)과 달리 **사이드바에 노출한다**(`screens.ts`의 `NAV_ORDER`). 등록은
 * 온보딩 흐름의 한 걸음이고, 관리는 운영 중 아무 때나 들어오는 화면이다.
 */
export function VesselManagementPage() {
  return <VesselManagement />
}
