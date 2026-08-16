import { ReportsView } from '../features/reports/ReportsView'

/**
 * 보고서 화면 (`UIFLOW 2-5` · `#362`).
 *
 * `PRD §25`의 리포트 2종을 만들고 PDF·CSV로 내려받는다. 미리보기는 서버의
 * `format=html`을 그대로 쓴다 — PDF와 **같은 소스**라 둘이 갈릴 수 없다.
 */
export function ReportsPage() {
  return <ReportsView />
}
