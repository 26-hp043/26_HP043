import { NavLink, Outlet, useLocation } from 'react-router'
import './AppShell.css'
import { NAV_SCREENS, findScreenByPath } from '../screens'
import { GradePatternDefs } from '../components/GradePatternDefs'
import { logout, useAuthUser } from '../auth/session'

/**
 * 공통 셸 — `DESIGN_SYSTEM.md` §7.2.
 *
 * 2026-08-04 디자인 회신으로 §16-6(사이드바 vs 상단바)이 닫히고 §7.2가 개정됐다.
 * 그 개정 문구를 그대로 구현한다.
 *
 * - **브랜드와 주 네비게이션은 좌측 사이드바**에 둔다.
 * - **상단바는 우측 정렬 유틸리티 영역** — 전역 컨텍스트(선박·항차) · 알림 · 계정만
 *   배치하고 **네비게이션 항목을 두지 않는다.** 배치 순서는 좌→우로 선박·항차·알림·계정.
 * - 사이드바는 대시보드 + 기능 6개 = 7개를 UIFLOW §2 순서로 유지하고,
 *   **미구현 항목은 숨기지 않고 비활성 상태로 노출**한다(`screens.ts`의 `demoScope`).
 * - 사이드바 **폭은 토큰으로 분리**하고 클래스 토글로 접히도록 구조만 잡는다.
 *   접힘 동작 자체는 MVP 범위 밖이라 토글 UI는 두지 않는다 — 나중에 셸을
 *   다시 만들지 않기 위한 준비다.
 *
 * 서비스명은 **BlueLog**다(2026-08-04 디자인 담당 확인 — 정식 명칭).
 * 로고 이미지는 아직 전달받지 못해 텍스트로 둔다. SVG를 받으면 이 자리를 교체한다.
 *
 * 상단바 항차 영역은 8/8까지 **읽기 전용 표시**다. 선택기로 바꿀지는 기능② 착수 시
 * 재확인하며, 최종 레이블 문구는 디자인 담당이 추후 전달한다(현재 문구는 임시).
 *
 * 메인 영역의 최대 폭·좌우 패딩은 §7.1 폭 정책을 화면별로 적용한다.
 */
export function AppShell() {
  const { pathname } = useLocation()
  const screen = findScreenByPath(pathname)
  const width = screen?.width ?? 'form'
  const user = useAuthUser()

  return (
    <div className="app-shell">
      <GradePatternDefs />

      <nav className="app-shell__sidebar" aria-label="주요 화면">
        <p className="app-shell__brand">
          <span className="app-shell__brand-name">BlueLog</span>
          <span className="app-shell__brand-sub">CII 예측 · 운항 의사결정 보조</span>
        </p>

        <ul className="app-shell__nav">
          {NAV_SCREENS.map((item) =>
            item.demoScope ? (
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
            ) : (
              /*
               * 비활성 항목. `NavLink`로 두고 CSS로만 막지 않는 이유 — 링크로 남기면
               * 키보드·스크린리더에는 이동 가능한 것으로 계속 노출된다.
               * 이동 대상이 아니므로 링크가 아닌 요소로 렌더한다.
               */
              <li key={item.id}>
                <span
                  className="app-shell__nav-link app-shell__nav-link--disabled"
                  aria-disabled="true"
                >
                  <span className="app-shell__nav-label">{item.label}</span>
                  <span className="app-shell__nav-label-en">{item.labelEn}</span>
                  <span className="app-shell__nav-tag">준비 중</span>
                </span>
              </li>
            ),
          )}
        </ul>
      </nav>

      <div className="app-shell__stack">
        {/* 우측 정렬 유틸리티. 순서 = §7.2의 좌→우 배치: 선박 · 항차 · 알림 · 계정 */}
        <header className="app-shell__topbar">
          <span className="app-shell__util-item">
            <span className="app-shell__util-key">선박</span>
            <span className="app-shell__util-value">—</span>
          </span>
          <span className="app-shell__util-item">
            <span className="app-shell__util-key">항차</span>
            <span className="app-shell__util-value">—</span>
          </span>
          <span className="app-shell__util-item app-shell__util-item--plain">알림</span>
          {/* 계정 — #278: 현재 사용자 표시 + 로그아웃. demo 모드(사용자 없음)는
              종전의 정적 표시를 유지한다. */}
          {user ? (
            <span className="app-shell__util-item">
              <span className="app-shell__util-key">계정</span>
              <span className="app-shell__util-value">
                {user.displayName ?? user.email}
              </span>
              <button
                type="button"
                className="app-shell__logout"
                onClick={() => void logout()}
                data-testid="logout-button"
              >
                로그아웃
              </button>
            </span>
          ) : (
            <span className="app-shell__util-item app-shell__util-item--plain">계정</span>
          )}
          <span className="app-shell__env">데모 환경</span>
        </header>

        <main className={`app-shell__main app-shell__main--${width}`}>
          <div className="app-shell__content">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
