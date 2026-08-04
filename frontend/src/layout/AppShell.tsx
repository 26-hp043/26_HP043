import { NavLink, Outlet, useLocation } from 'react-router'
import './AppShell.css'
import { NAV_SCREENS, findScreenByPath } from '../screens'
import { GradePatternDefs } from '../components/GradePatternDefs'

/**
 * 공통 셸 — `DESIGN_SYSTEM.md` §7.2 "좌측 사이드바 네비 + 상단바".
 *
 * 사이드바 구성은 `UIFLOW.md` §2의 *"메인보드 진입 후 좌측 사이드바로 6가지 핵심
 * 기능 화면으로 이동"* 구조를 따른다(메인보드 + 기능 6개).
 *
 * 메인 영역의 최대 폭·좌우 패딩은 `DESIGN_SYSTEM` §7.1 폭 정책을 화면별로 적용한다.
 */
export function AppShell() {
  const { pathname } = useLocation()
  const screen = findScreenByPath(pathname)
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
            {NAV_SCREENS.map((item) => (
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
