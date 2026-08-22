/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  ALL_SCREEN_IDS,
  DEFAULT_PATH,
  NAV_ORDER,
  OFF_NAV_ORDER,
  SCREEN_BY_ID,
  findScreenByPath,
} from './screens'

/**
 * #348 — UIFLOW v2.0 3계층 재편의 라우팅·네비게이션 계약.
 * 화면 구조의 정본은 UIFLOW.md §2다. 여기선 파생물(screens.ts)이 그 구조를
 * 정확히 반영하는지 잠근다.
 */

describe('NAV_ORDER — 3계층 순서 (UIFLOW v2.0 §2)', () => {
  it('선대 → 선박 → 항차 → 산출물 → 계층 밖 순서다', () => {
    expect([...NAV_ORDER]).toEqual([
      'MAINBOARD', // [선대] 2-4
      'ANNUAL_GRADE', // [선박] 2-3
      'CII_FORECAST', // [항차] 2-1
      'ROUTE_COMPARISON', // [항차] 2-2
      'REPORTS', // [산출물] 2-5
      'VESSEL_MANAGEMENT', // [계층 밖] SCR-002 (PRD §6.1 — UIFLOW §2.2에는 행이 없다)
      'SETTINGS', // [계층 밖] 2-6
    ])
  })

  it('종전 FLEET_MONITORING(선대 모니터링)은 대시보드 통합으로 폐지됐다', () => {
    expect(ALL_SCREEN_IDS).not.toContain('FLEET_MONITORING')
    expect(SCREEN_BY_ID.MAINBOARD.uiflowRef).toBe('1-3 · 2-4')
  })

  it('드릴다운 화면(선박 상세·실시간 CII)은 사이드바 밖이다', () => {
    expect(NAV_ORDER).not.toContain('VESSEL_DETAIL')
    expect(NAV_ORDER).not.toContain('REALTIME_CII')
    expect(OFF_NAV_ORDER).toContain('VESSEL_DETAIL')
    expect(OFF_NAV_ORDER).toContain('REALTIME_CII')
  })
})

describe('계층 드릴다운 라우트 (#348)', () => {
  it('선박 상세 경로는 /vessels/:vesselId (UIFLOW 2-8)', () => {
    expect(SCREEN_BY_ID.VESSEL_DETAIL.path).toBe('/vessels/:vesselId')
    expect(SCREEN_BY_ID.VESSEL_DETAIL.uiflowRef).toBe('2-8')
  })

  it('실시간 CII 경로는 /vessels/:vesselId/voyages/:voyageId (UIFLOW 2-9)', () => {
    expect(SCREEN_BY_ID.REALTIME_CII.path).toBe('/vessels/:vesselId/voyages/:voyageId')
    expect(SCREEN_BY_ID.REALTIME_CII.uiflowRef).toBe('2-9')
  })
})

describe('DEFAULT_PATH — 기본 진입 경로', () => {
  it('대시보드(선대 계층)가 기본 진입 경로다 (UIFLOW v2.0 §2)', () => {
    expect(DEFAULT_PATH).toBe('/dashboard')
    expect(DEFAULT_PATH).toBe(SCREEN_BY_ID.MAINBOARD.path)
  })
})

describe('findScreenByPath — 경로 파라미터 매칭', () => {
  it('고정 경로를 화면으로 찾는다', () => {
    expect(findScreenByPath('/dashboard')?.labelEn).toBe('Dashboard')
    expect(findScreenByPath('/voyage-cii')?.labelEn).toBe('CII Forecast')
  })

  it('구체적인 vesselId 경로가 선박 상세로 매칭된다', () => {
    expect(findScreenByPath('/vessels/abc-123')?.labelEn).toBe('Vessel Detail')
  })

  it('구체적인 vesselId/voyageId 경로가 실시간 CII로 매칭된다', () => {
    expect(findScreenByPath('/vessels/abc-123/voyages/def-456')?.labelEn).toBe(
      'Realtime CII',
    )
  })

  it('세그먼트 수가 다른 경로는 선박 상세로 오매칭되지 않는다', () => {
    expect(findScreenByPath('/vessels/abc-123/voyages')).toBeUndefined()
    // `/vessels`는 #510이 선박 관리 화면에 배정했다. 여기서 잠그는 성질은
    // 「경로가 존재하는가」가 아니라 **「선박 상세로 새지 않는가」**다.
    expect(findScreenByPath('/vessels')?.labelEn).toBe('Vessel Management')
    expect(findScreenByPath('/vessels')?.labelEn).not.toBe('Vessel Detail')
  })

  it('선박 관리 경로는 /vessels다 (PRD §6.2 SCR-002)', () => {
    expect(SCREEN_BY_ID.VESSEL_MANAGEMENT.path).toBe('/vessels')
    // 등록(1-2)과 관리는 같은 SCR-002 아래의 다른 화면이다 — 경로가 갈린다.
    expect(SCREEN_BY_ID.VESSEL_REGISTRATION.path).toBe('/vessel-registration')
  })

  it('등록되지 않은 경로는 undefined를 반환한다', () => {
    expect(findScreenByPath('/no-such-screen')).toBeUndefined()
  })
})

/**
 * `implemented`가 실제 구현 상태와 어긋나는 것을 막는다 (#527).
 *
 * ## 왜 필요한가
 *
 * `#510`이 만든 선박 관리 화면은 **실 API로 도는데 `implemented: false`로 들어갔다.**
 * 사이드바가 그 값을 보고 **비활성으로 렌더해 클릭조차 되지 않았고**, 기능은 전부
 * 동작하는데 들어가는 문만 막혀 있었다. 디자인 담당이 화면을 열어 보고서야 드러났다.
 *
 * 값이 `false`인 것은 문법 오류가 아니라 **CI가 통과한다.** 종전 테스트는
 * `NAV_ORDER` 순서만 봤고 `implemented`를 보지 않았다.
 *
 * ## 무엇으로 판정하나 — 값이 아니라 **실제 화면**을 본다
 *
 * `implemented` 값을 그대로 다시 적으면 복사본이 하나 늘 뿐 드리프트를 못 잡는다.
 * 그래서 **페이지 컴포넌트가 `ComingSoon` 스텁인지**를 본다 — 그것이 「구현이 아직
 * 없다」의 실제 증거다.
 *
 * ## 이 가드가 틀릴 수 있는 경우
 *
 * 화면 파일은 진짜인데 **demo provider만 있어 실 API로는 안 도는** 상태가 생기면
 * (`#442`가 기능③에서 겪은 형태) `implemented: false`인데 `ComingSoon`이 아니게 된다.
 * 그때는 이 가드를 고치되 **왜 예외인지 여기에 적는다.** 조용히 통과시키지 않는다.
 */
describe('implemented ↔ 실제 구현 상태 (#527)', () => {
  /**
   * 화면 → 페이지 컴포넌트 파일. 라우팅은 `App.tsx`가 갖고 있어 여기 적는다.
   *
   * **사이드바 밖 화면까지 전부 적는다 (#628).** 종전에는 `NAV_ORDER`만 담았고,
   * 그래서 `implemented: false`인 화면 6개가 **한 번도 검사되지 않았다** — 여섯 다
   * `OFF_NAV_ORDER`에 있었기 때문이다. 그중 `VESSEL_REGISTRATION`은 근거가
   * **폐기된 데모 모드**였는데(`#542`), 사이드바에 영향이 없어 아무도 걸려 넘어지지
   * 않았다. `#527`이 사이드바에서 겪은 것의 조용한 판본이다.
   */
  const PAGE_FILE: Readonly<Record<string, string>> = {
    // 사이드바
    MAINBOARD: 'MainboardPage',
    ANNUAL_GRADE: 'AnnualGradePage',
    CII_FORECAST: 'CiiForecastPage',
    ROUTE_COMPARISON: 'RouteComparisonPage',
    REPORTS: 'ReportsPage',
    VESSEL_MANAGEMENT: 'VesselManagementPage',
    SETTINGS: 'SettingsPage',
    // 사이드바 밖 — 인증·온보딩·드릴다운
    LOGIN: 'LoginPage',
    LOGIN_FAILURE: 'LoginPage', // 같은 파일이 `LoginFailurePage`를 함께 export한다
    SIGNUP: 'SignupPage',
    PASSWORD_RESET: 'PasswordResetPage',
    VERIFY_EMAIL: 'VerifyEmailPage',
    VESSEL_REGISTRATION: 'VesselRegistrationPage',
    VESSEL_DETAIL: 'VesselDetailPage',
    REALTIME_CII: 'RealtimeCiiPage',
  }

  function isComingSoonStub(screenId: string): boolean {
    const name = PAGE_FILE[screenId]
    const source = readFileSync(new URL(`./pages/${name}.tsx`, import.meta.url), 'utf-8')
    return source.includes('ComingSoon')
  }

  it('표에 화면이 빠짐없이 있다 — 사이드바 밖까지', () => {
    // 화면을 추가하고 이 표를 잊으면 그 화면만 검사가 통째로 건너뛰어진다.
    expect(Object.keys(PAGE_FILE).sort()).toEqual([...ALL_SCREEN_IDS].sort())
  })

  it('구현이 있는 화면은 implemented가 true다 — 막히면 사용자가 들어갈 수 없다', () => {
    const blocked = ALL_SCREEN_IDS.filter(
      (id) => !SCREEN_BY_ID[id].implemented && !isComingSoonStub(id),
    )
    expect(
      blocked,
      `화면은 만들어져 있는데 implemented가 false다: ${blocked.join(', ')}. ` +
        'implemented는 「실 API로 도는가」다 (#442·#527·#628).',
    ).toEqual([])
  })

  it('ComingSoon 스텁은 implemented가 false다 — 준비 중을 열어 두면 빈 화면이 열린다', () => {
    const wrong = ALL_SCREEN_IDS.filter(
      (id) => SCREEN_BY_ID[id].implemented && isComingSoonStub(id),
    )
    expect(wrong, `스텁인데 implemented가 true다: ${wrong.join(', ')}`).toEqual([])
  })

  it('선박 등록은 실 API로 도는 화면이다 (#628 회귀 고정)', () => {
    // 근거가 **폐기된 데모 모드**였다 — `#542`가 데모 provider를 없앤 뒤
    // `providerSelection.ts`에는 실 API 갈래 하나만 남았다.
    expect(SCREEN_BY_ID.VESSEL_REGISTRATION.implemented).toBe(true)
    expect(isComingSoonStub('VESSEL_REGISTRATION')).toBe(false)
  })

  it('선박 관리는 실 API로 도는 화면이다 (#510 · #527 회귀 고정)', () => {
    expect(SCREEN_BY_ID.VESSEL_MANAGEMENT.implemented).toBe(true)
    expect(isComingSoonStub('VESSEL_MANAGEMENT')).toBe(false)
  })

  /*
   * 종전 이 자리는 「설정은 아직 스텁이다 — #359 확정 전까지」였다. 그 전제가 바뀌었다.
   *
   * `PRD §6.2` 각주(COR-9)는 *「2-6 설정은 어드민 범위 확정(§20 O-13 재개정) 결과에
   * 따른다」*고 적었는데, **그 재개정은 `#413`으로 끝났다** — O-13은 O-14로 대체되어
   * **CLOSED**이고 결과는 「사용자별 데이터 격리·RBAC는 계속 제외」다.
   *
   * RBAC가 제외된 이상 이 화면에 들어갈 권한 요소가 없다. 남는 것은 `PRD §5`가
   * **MUST**로 둔 계정 관리(비밀번호·표시 이름 변경)뿐이고, 그것은 권한과 무관하다.
   * 조직 설정·규제 파라미터 조회는 여전히 `#359` 대기이므로 넣지 않았다.
   */
  it('설정은 계정 관리로 도는 화면이다 (#506 · PRD §5 MUST)', () => {
    expect(SCREEN_BY_ID.SETTINGS.implemented).toBe(true)
    expect(isComingSoonStub('SETTINGS')).toBe(false)
  })
})
