import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import './AppShell.css'
import { NAV_SCREENS, findScreenByPath } from '../screens'
import { createVesselCatalog, type VesselOption } from '../features/voyage-cii/vesselCatalog'
import { createVoyageCatalog, type VoyageOption } from './voyageCatalog'
import {
  EMPTY_CONTEXT,
  isVesselQueryPath,
  isVesselScopedPath,
  loadStored,
  navigationFor,
  readContext,
  saveStored,
  selectVessel,
  selectVoyage,
  type GlobalContextValue,
} from './globalContext'
import { GradePatternDefs } from '../components/GradePatternDefs'
import { logout, useAuthUser } from '../auth/session'
import { ThemeToggle } from '../theme/ThemeToggle'
import { VerifyBanner } from '../features/auth/VerifyBanner'
import { BellGlyph, NavIcon, ShipGlyph, VoyageGlyph } from './NavIcons'
import type { ShellContext } from './shellContext'

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
 *   (`screens.ts`의 `implemented`).
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
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const screen = findScreenByPath(pathname)
  const width = screen?.width ?? 'form'
  const user = useAuthUser()

  const vesselCatalog = useMemo(() => createVesselCatalog(), [])
  const voyageCatalog = useMemo(() => createVoyageCatalog(), [])

  const [vessels, setVessels] = useState<VesselOption[]>([])
  // 「아직 안 왔다」와 「못 읽었다」와 「등록된 배가 없다」는 서로 다른 상태다.
  // 화면이 그 셋을 다르게 안내할 수 있도록 함께 내린다 (#484).
  const [vesselsState, setVesselsState] = useState<ShellContext['vesselsState']>('loading')
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
        if (!alive) return
        setVessels(options)
        setVesselsState('ready')
      },
      () => {
        // 목록을 못 읽어도 셸은 계속 돈다. 선택기만 비활성으로 남는다 —
        // 화면 전체를 오류로 만들 이유가 없다.
        if (!alive) return
        setVessels([])
        setVesselsState('failed')
      },
    )
    return () => {
      alive = false
    }
  }, [vesselCatalog])

  /*
   * 지금 유효한 선택. 계층 화면이면 경로가, 쿼리 화면이면 쿼리가 정본이고,
   * 그 밖에서는 기억해 둔 값이다. 두 곳을 합치지 않고 **어느 쪽이 이기는지
   * 한 줄로 정한다** — 합치면 갈렸을 때 어느 쪽이 맞는지 알 수 없다.
   * 판정 규칙은 `globalContext.readContext`가 소유한다(#484).
   */
  const context: GlobalContextValue = readContext(pathname, search, remembered)

  // URL을 통해 들어온 선택도 기억한다 — 대시보드로 나가도 유지되어야 한다.
  useEffect(() => {
    if (!isVesselScopedPath(pathname) && !isVesselQueryPath(pathname)) return
    const fromUrl = readContext(pathname, search, EMPTY_CONTEXT)
    // 쿼리 화면에 쿼리 없이 들어온 경우다. 기억을 지우지 않는다 — 사이드바로
    // 들어왔을 뿐 사용자가 선택을 취소한 것이 아니다.
    if (fromUrl.vesselId === null) return
    setRemembered(fromUrl)
    saveStored(fromUrl)
  }, [pathname, search])

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

  /*
   * `outletContext`가 매 렌더 새로 만들어지지 않게 하면서도 최신 `pathname`·
   * `search`·`context`를 쓰도록 ref로 우회한다. 하위 화면은 이 객체를 효과의
   * 의존성에 두므로, 정체성이 흔들리면 그 효과가 매 렌더 돈다.
   */
  const contextRef = useRef(context)
  contextRef.current = context

  /** 선택을 반영한다 — 기억하고, 화면에 맞는 방식으로 주소를 갱신한다. */
  const applyContext = (next: GlobalContextValue) => {
    setRemembered(next)
    saveStored(next)
    const target = navigationFor(pathname, next, search)
    if (target === null || target === `${pathname}${search}`) return
    // 쿼리 화면에서는 **히스토리를 쌓지 않는다** (#484). 선박을 세 번 바꾸면
    // 뒤로가기를 세 번 눌러야 이전 화면으로 나가게 되고, 그건 선택을 바꾼
    // 사용자가 기대하는 동작이 아니다. 계층 화면은 화면 자체가 바뀌므로
    // 히스토리에 남는 것이 맞다.
    navigate(target, { replace: isVesselQueryPath(pathname) })
  }
  const applyContextRef = useRef(applyContext)
  applyContextRef.current = applyContext

  /**
   * 하위 화면에 넘기는 값 (#484 · #535).
   *
   * **화면이 자기 선박 상태를 따로 갖지 않게 하려는 것**이다. 종전에는 CII 예측·
   * 항로 비교가 각자 선박 셀렉트를 들고 있어, 상단에서 배를 바꿔도 폼은 그대로였다
   * (`#535`). 셋이 같은 값을 보게 하려면 값과 **바꾸는 수단**을 함께 내려야 한다.
   *
   * `createContext`를 쓰지 않고 `Outlet context`를 쓴다 — 라우터가 이미 부모·자식
   * 관계를 알고 있고, 이 값이 필요한 화면은 전부 이 셸의 라우트 자식이다.
   */
  const outletContext: ShellContext = useMemo(
    () => ({
      vesselId: context.vesselId,
      voyageId: context.voyageId,
      vessels,
      vesselsState,
      selectVesselId: (vesselId: string | null) =>
        applyContextRef.current(selectVessel(contextRef.current, vesselId)),
    }),
    // `selectVesselId`는 ref를 거쳐 최신 값을 읽으므로 여기 넣지 않는다. 넣으면
    // 매 렌더 새 객체가 되고, 이 값을 의존성에 둔 화면의 효과가 무한히 돈다.
    [context.vesselId, context.voyageId, vessels, vesselsState],
  )

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
            item.implemented ? (
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
            <Outlet context={outletContext} />
          </div>
        </main>
      </div>
    </div>
  )
}
