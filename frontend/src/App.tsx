import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AppShell } from './layout/AppShell'
import { DEFAULT_PATH, SCREEN_BY_ID } from './screens'
import { MainboardPage } from './pages/MainboardPage'
import { VesselRegistrationPage } from './pages/VesselRegistrationPage'
import { CiiForecastPage } from './pages/CiiForecastPage'
import { RouteComparisonPage } from './pages/RouteComparisonPage'
import { AnnualGradePage } from './pages/AnnualGradePage'
import { FleetMonitoringPage } from './pages/FleetMonitoringPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'

/**
 * `UIFLOW.md` §1·§2의 화면을 라우트로 연결한다.
 *
 * 경로 문자열은 `screens.ts`가 정본이며 여기서 다시 적지 않는다.
 * 화면 ID로 조회하므로 사이드바 순서(`NAV_ORDER`)가 바뀌어도 연결이 어긋나지 않는다.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to={DEFAULT_PATH} replace />} />

          <Route path={SCREEN_BY_ID.MAINBOARD.path} element={<MainboardPage />} />
          <Route
            path={SCREEN_BY_ID.VESSEL_REGISTRATION.path}
            element={<VesselRegistrationPage />}
          />
          <Route path={SCREEN_BY_ID.CII_FORECAST.path} element={<CiiForecastPage />} />
          <Route
            path={SCREEN_BY_ID.ROUTE_COMPARISON.path}
            element={<RouteComparisonPage />}
          />
          <Route path={SCREEN_BY_ID.ANNUAL_GRADE.path} element={<AnnualGradePage />} />
          <Route
            path={SCREEN_BY_ID.FLEET_MONITORING.path}
            element={<FleetMonitoringPage />}
          />
          <Route path={SCREEN_BY_ID.REPORTS.path} element={<ReportsPage />} />
          <Route path={SCREEN_BY_ID.SETTINGS.path} element={<SettingsPage />} />

          <Route path="*" element={<Navigate to={DEFAULT_PATH} replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
