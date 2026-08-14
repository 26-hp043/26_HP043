import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AppShell } from './layout/AppShell'
import { RequireAuth } from './auth/RequireAuth'
import { DEFAULT_PATH, SCREEN_BY_ID } from './screens'
import { LoginFailurePage, LoginPage } from './pages/LoginPage'
import { MainboardPage } from './pages/MainboardPage'
import { VesselRegistrationPage } from './pages/VesselRegistrationPage'
import { CiiForecastPage } from './pages/CiiForecastPage'
import { RouteComparisonPage } from './pages/RouteComparisonPage'
import { AnnualGradePage } from './pages/AnnualGradePage'
import { FleetMonitoringPage } from './pages/FleetMonitoringPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'

/**
 * `UIFLOW.md` §0·§1·§2의 화면을 라우트로 연결한다.
 *
 * 경로 문자열은 `screens.ts`가 정본이며 여기서 다시 적지 않는다.
 * 화면 ID로 조회하므로 사이드바 순서(`NAV_ORDER`)가 바뀌어도 연결이 어긋나지 않는다.
 *
 * **로그인 계열(§0)은 셸 밖**에 둔다 — 사이드바·상단바가 없는 전체 화면이며,
 * 가드로 보호하면 로그인으로 돌아가는 무한 루프가 된다. 그 외 모든 화면은
 * `RequireAuth`로 감싼다(#278). demo 모드에서는 가드가 스스로 우회한다.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* UIFLOW §0 — 인증 화면(셸 밖·가드 밖) */}
        <Route path={SCREEN_BY_ID.LOGIN.path} element={<LoginPage />} />
        <Route path={SCREEN_BY_ID.LOGIN_FAILURE.path} element={<LoginFailurePage />} />

        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
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
