import { NavLink, Outlet, useLocation } from 'react-router'
import './AppShell.css'
import { SCREENS, findScreen } from '../screens'
import { GradePatternDefs } from '../components/GradePatternDefs'

/**
 * 공통 셸 — DESIGN_SYSTEM.md §7.2 "좌측 사이드바 네비 + 상단바".
 *
 * 메인 영역의 최대 폭·좌우 패딩은 §7.1 폭 정책을 화면별로 적용한다.
 * 현재 경로의 `width`가 `wide`면 max 1920 / 패딩 32, `form`이면 max 1440 / 패딩 24다.
 */
export function AppShell() {
  const { pathname } = useLocation()
  const screen = findScreen(pathname)
  const width = screen?.width ?? 'form'

  return (
    <div className="app-shell">
      <GradePatternDefs />

      <header className="app-shell__topbar">
        <p className="app-shell__brand">CII 예측 · 운항 의사결정 보조 플랫폼</p>
        <p className="app-shell__env">데모 환경</p>
      </header>

      <div className="app-shell__body">
        <nav className="app-shell__sidebar" aria-label="주요 화면">
          <ul className="app-shell__nav">
            {SCREENS.map((item) => (
              <li key={item.id}>
                <NavLink
                  to={item.path}
                  className={({ isActive }) =>
                    isActive
                      ? 'app-shell__nav-link app-shell__nav-link--active'
                      : 'app-shell__nav-link'
                  }
                >
                  <span className="app-shell__nav-label">{item.label}</span>
                  <span className="app-shell__nav-label-en">{item.labelEn}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <main className={`app-shell__main app-shell__main--${width}`}>
          <div className="app-shell__content">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
