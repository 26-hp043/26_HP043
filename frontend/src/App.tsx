import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AppShell } from './layout/AppShell'
import { DEFAULT_PATH, SCREENS } from './screens'
import { DashboardPage } from './pages/DashboardPage'
import { VesselsPage } from './pages/VesselsPage'
import { VoyageCiiPage } from './pages/VoyageCiiPage'
import { ScenarioComparisonPage } from './pages/ScenarioComparisonPage'
import { AnnualSimulatorPage } from './pages/AnnualSimulatorPage'
import { ParametersPage } from './pages/ParametersPage'
import { DataIoPage } from './pages/DataIoPage'

/**
 * PRD §6.2의 화면 7개를 라우트로 연결한다.
 * 경로 문자열은 `screens.ts`가 정본이며 여기서 다시 적지 않는다.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to={DEFAULT_PATH} replace />} />
          <Route path={SCREENS[0].path} element={<DashboardPage />} />
          <Route path={SCREENS[1].path} element={<VesselsPage />} />
          <Route path={SCREENS[2].path} element={<VoyageCiiPage />} />
          <Route path={SCREENS[3].path} element={<ScenarioComparisonPage />} />
          <Route path={SCREENS[4].path} element={<AnnualSimulatorPage />} />
          <Route path={SCREENS[5].path} element={<ParametersPage />} />
          <Route path={SCREENS[6].path} element={<DataIoPage />} />
          <Route path="*" element={<Navigate to={DEFAULT_PATH} replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
