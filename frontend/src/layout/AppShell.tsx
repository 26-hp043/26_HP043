import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import './AppShell.css'
import { NAV_SCREENS, findScreenByPath } from '../screens'
import { createVesselCatalog, type VesselOption } from '../features/voyage-cii/vesselCatalog'
import { createVoyageCatalog, type VoyageOption } from './voyageCatalog'
import {
  EMPTY_CONTEXT,
  isVesselScopedPath,
  loadStored,
  navigationFor,
  readFromPath,
  saveStored,
  selectVessel,
  selectVoyage,
  type GlobalContextValue,
} from './globalContext'
import { GradePatternDefs } from '../components/GradePatternDefs'
import { logout, useAuthUser } from '../auth/session'
import { ThemeToggle } from '../theme/ThemeToggle'
import { VerifyBanner } from '../features/auth/VerifyBanner'
import { shouldUseApi } from '../features/voyage-cii/providerSelection'
import { BellGlyph, NavIcon, ShipGlyph, VoyageGlyph } from './NavIcons'

/** 아바타 이니셜. 이메일이면 로컬파트 첫 글자를 쓴다. */
function initialOf(name: string): string {
  return (name.trim()[0] ?? '?').toUpperCase()
}

/**
 * 공통 셸 — `DESIGN_SYSTEM.md` §7.2.
 *
 * 2026-08-04 디자인 회신으로 §16-6(사이드바 vs 상단바)이 닫히고 §7.2가 개정됐다.
 * 그 개정 문구를 그대로 구현한다.
 *
 * - **브랜드와 주 네비게이션은 좌측 사이드바**에 둔다.
 * - **상단바는 우측 정렬 유틸리티 영역** — 전역 컨텍스트(선박·항차) · 알림 · 계정만
 *   배치하고 **네비게이션 항목을 두지 않는다.** 배치 순서는 좌→우로 선박·항차·알림·계정.
 * - 사이드바는 UIFLOW v2.0 §2의 3계층 순서(선대 → 선박 → 항차 → 산출물 →
 *   계층 밖)를 따르며, **미구현 항목은 숨기지 않고 비활성 상태로 노출**한다
 *   (`screens.ts`의 `demoScope`).
 * - 사이드바 **폭은 토큰으로 분리**하고 클래스 토글로 접히도록 구조만 잡는다.
 *   접힘 동작 자체는 MVP 범위 밖이라 토글 UI는 두지 않는다 — 나중에 셸을
 *   다시 만들지 않기 위한 준비다.
 *
 * 서비스명은 **BlueLog**다(2026-08-04 디자인 담당 확인 — 정식 명칭).
 * 로고 이미지는 아직 전달받지 못해 텍스트로 둔다. SVG를 받으면 이 자리를 교체한다.
 *
 * ## 전역 컨텍스트 선택기 (#512)
 *
 * 종전에는 「선박 선택 안 함」·「항차 선택 안 함」이 **글자로만** 있었다. 자리는
 * 있고 기능이 없어, 눌러도 아무 일이 없었다. 8/8 데모를 위해 읽기 전용으로 두고
 * 「기능② 착수 시 붙인다」고 적어 두었으나 그 약속을 추적하는 이슈가 없었다.
 *
 * **선택 상태의 정본은 URL이다.** `#348`의 계층 라우트(`/vessels/:vesselId` ·
 * `/vessels/:vesselId/voyages/:voyageId`)가 이미 선박 범위를 표현하므로, 상단바가
 * 별도 상태를 소유하면 두 곳이 갈린다. 규칙은 `globalContext.ts`에 있다.
 *
 * 메인 영역의 최대 폭·좌우 패딩은 §7.1 폭 정책을 화면별로 적용한다.
 */
export function AppShell() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const screen = findScreenByPath(pathname)
  const width = screen?.width ?? 'form'
  const user = useAuthUser()

  /*
   * 데모 모드인지 화면이 말해 준다 (#528).
   *
   * 데모 모드에서는 화면이 **실제 제품과 다르다** — demo provider가 있는 기능은
   * 셋뿐이라 대시보드·보고서·선박 상세·선박 관리는 아예 돌지 않는다. 게다가
   * 인증 가드까지 꺼져(`auth/session.ts`) 로그인 없이 열리므로 **모르고 쓰기
   * 쉽다.** 실제로 디자인 담당이 이 상태로 작업하다 「선박이 하나만 뜬다」고
   * 알려 왔다.
   *
   * 기본값을 실 API로 바꿨으므로(`frontend/.env`) 이 배너는 **일부러 껐을 때만**
   * 보인다. 조용히 데모로 떨어지는 경로를 없애는 것이 목적이다.
   */
  const demoMode = !shouldUseApi()

  const vesselCatalog = useMemo(() => createVesselCatalog(), [])
  const voyageCatalog = useMemo(() => createVoyageCatalog(), [])

  const [vessels, setVessels] = useState<VesselOption[]>([])
  const [voyages, setVoyages] = useState<VoyageOption[]>([])
  // 계층 밖 화면에서 보일 「기억해 둔 선택」. 계층 화면에서는 URL이 이긴다.
  const [remembered, setRemembered] = useState<GlobalContextValue>(EMPTY_CONTEXT)

  useEffect(() => {
    setRemembered(loadStored())
  }, [])

  useEffect(() => {
    let alive = true
    vesselCatalog.listVessels().then(
      (options) => {
        if (alive) setVessels(options)
      },
      () => {
        // 목록을 못 읽어도 셸은 계속 돈다. 선택기만 비활성으로 남는다 —
        // 화면 전체를 오류로 만들 이유가 없다.
        if (alive) setVessels([])
      },
    )
    return () => {
      alive = false
    }
  }, [vesselCatalog])

  /*
   * 지금 유효한 선택. 계층 화면이면 경로가 정본이고, 그 밖에서는 기억해 둔 값이다.
   * 두 곳을 합치지 않고 **어느 쪽이 이기는지 한 줄로 정한다** — 합치면 갈렸을 때
   * 어느 쪽이 맞는지 알 수 없다.
   */
  const context: GlobalContextValue = isVesselScopedPath(pathname)
    ? readFromPath(pathname)
    : remembered

  // 경로를 통해 들어온 선택도 기억한다 — 대시보드로 나가도 유지되어야 한다.
  useEffect(() => {
    if (!isVesselScopedPath(pathname)) return
    const fromPath = readFromPath(pathname)
    setRemembered(fromPath)
    saveStored(fromPath)
  }, [pathname])

  // 항차 목록은 선박이 정해진 뒤에만 의미가 있다.
  useEffect(() => {
    let alive = true
    if (context.vesselId === null) {
      setVoyages([])
      return
    }
    voyageCatalog.listVoyages(context.vesselId).then(
      (options) => {
        if (alive) setVoyages(options)
      },
      () => {
        if (alive) setVoyages([])
      },
    )
    return () => {
      alive = false
    }
  }, [voyageCatalog, context.vesselId])

  /** 선택을 반영한다 — 기억하고, 계층 화면이면 그 대상으로 이동한다. */
  const applyContext = (next: GlobalContextValue) => {
    setRemembered(next)
    saveStored(next)
    const target = navigationFor(pathname, next)
    if (target !== null && target !== pathname) navigate(target)
  }

  return (
    <div className="app-shell">
      <GradePatternDefs />

      <nav className="app-shell__sidebar" aria-label="주요 화면">
        <p className="app-shell__brand">
          <span className="app-shell__brand-name">BlueLog</span>
          <span className="app-shell__brand-sub">선대 CII 상시 관리</span>
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
                  <NavIcon id={item.id} />
                  <span className="app-shell__nav-text">
                    <span className="app-shell__nav-label">{item.label}</span>
                    <span className="app-shell__nav-label-en">{item.labelEn}</span>
                  </span>
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
                  <NavIcon id={item.id} />
                  <span className="app-shell__nav-text">
                    <span className="app-shell__nav-label">{item.label}</span>
                    <span className="app-shell__nav-label-en">{item.labelEn}</span>
                  </span>
                  <span className="app-shell__nav-tag">준비 중</span>
                </span>
              </li>
            ),
          )}
        </ul>
      </nav>

      <div className="app-shell__stack">
        {demoMode && (
          <p className="app-shell__demo-banner" role="status">
            <strong>데모 모드</strong> — 백엔드에 연결하지 않고 고정 데이터로 돌고
            있습니다. 대시보드·보고서·선박 상세·선박 관리는 동작하지 않으며 로그인도
            건너뜁니다. 실제 데이터로 보려면 <code>frontend/.env.local</code>의{' '}
            <code>VITE_USE_API</code>를 지우거나 <code>true</code>로 바꾸고 개발
            서버를 다시 띄우십시오.
          </p>
        )}
        {/* 이메일 미인증 안내 — 인증 전에도 이용은 허용한다(PRD §7.10). */}
        <VerifyBanner />
        {/* 우측 정렬 유틸리티. 순서 = §7.2의 좌→우 배치: 선박 · 항차 · 알림 · 계정 */}
        <header className="app-shell__topbar">
          {/*
           * 선박·항차 컨텍스트 (#512). 값이 없을 때 「—」만 두면 무엇을 고르라는
           * 것인지 읽히지 않아, 빈 선택지도 「선택 안 함」으로 명시한다.
           *
           * 선박이 0척이면 셀렉트를 **비활성으로 두되 숨기지 않는다** — 자리가
           * 사라지면 사용자가 「이 제품에는 그런 기능이 없다」로 읽는다
           * (`DESIGN_SYSTEM §7.2`가 사이드바에 대해 정한 것과 같은 원칙).
           */}
          <span className="app-shell__util-item">
            <ShipGlyph />
            <label className="app-shell__util-label" htmlFor="global-vessel">
              선박
            </label>
            <select
              id="global-vessel"
              className="app-shell__util-select"
              value={context.vesselId ?? ''}
              disabled={vessels.length === 0}
              onChange={(event) =>
                applyContext(selectVessel(context, event.target.value || null))
              }
            >
              <option value="">
                {vessels.length === 0 ? '선박 없음' : '선박 선택 안 함'}
              </option>
              {vessels.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.displayName}
                </option>
              ))}
            </select>
          </span>
          <span className="app-shell__util-item">
            <VoyageGlyph />
            <label className="app-shell__util-label" htmlFor="global-voyage">
              항차
            </label>
            {/*
              선박을 고르기 전에는 항차를 고를 수 없다 — 항차는 선박에 매달려 있다
              (`GET /vessels/{id}/voyages`). 이슈 체크리스트가 명시한 규칙이다.
            */}
            <select
              id="global-voyage"
              className="app-shell__util-select"
              value={context.voyageId ?? ''}
              disabled={context.vesselId === null || voyages.length === 0}
              onChange={(event) =>
                applyContext(selectVoyage(context, event.target.value || null))
              }
            >
              <option value="">
                {context.vesselId === null
                  ? '선박 먼저 선택'
                  : voyages.length === 0
                    ? '항차 없음'
                    : '항차 선택 안 함'}
              </option>
              {voyages.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.displayName}
                </option>
              ))}
            </select>
          </span>
          <button
            type="button"
            className="app-shell__iconbtn"
            aria-label="알림 (읽지 않음 없음)"
            title="알림"
          >
            <BellGlyph />
          </button>
          {/* 테마 선택(해·달). */}
          <ThemeToggle />

          {/* 계정 — #278: 현재 사용자 표시 + 로그아웃. */}
          {user ? (
            <span className="app-shell__account">
              <span className="app-shell__avatar" aria-hidden="true">
                {initialOf(user.displayName ?? user.email)}
              </span>
              <span className="app-shell__account-name">
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
          ) : null}
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
