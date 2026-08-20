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
  /** 사이드바 화면 → 페이지 컴포넌트 파일. 라우팅은 `App.tsx`가 갖고 있어 여기 적는다. */
  const NAV_PAGE_FILE: Readonly<Record<string, string>> = {
    MAINBOARD: 'MainboardPage',
    ANNUAL_GRADE: 'AnnualGradePage',
    CII_FORECAST: 'CiiForecastPage',
    ROUTE_COMPARISON: 'RouteComparisonPage',
    REPORTS: 'ReportsPage',
    VESSEL_MANAGEMENT: 'VesselManagementPage',
    SETTINGS: 'SettingsPage',
  }

  function isComingSoonStub(screenId: string): boolean {
    const name = NAV_PAGE_FILE[screenId]
    const source = readFileSync(new URL(`./pages/${name}.tsx`, import.meta.url), 'utf-8')
    return source.includes('ComingSoon')
  }

  it('표에 사이드바 화면이 빠짐없이 있다', () => {
    // 사이드바에 화면을 추가하고 이 표를 잊으면 아래 검사가 통째로 건너뛰어진다.
    expect(Object.keys(NAV_PAGE_FILE).sort()).toEqual([...NAV_ORDER].sort())
  })

  it('구현이 있는 화면은 implemented가 true다 — 막히면 사용자가 들어갈 수 없다', () => {
    const blocked = NAV_ORDER.filter(
      (id) => !SCREEN_BY_ID[id].implemented && !isComingSoonStub(id),
    )
    expect(
      blocked,
      `화면은 만들어져 있는데 사이드바에서 막혀 있다: ${blocked.join(', ')}. ` +
        'implemented는 「실 API로 도는가」다 (#442·#527).',
    ).toEqual([])
  })

  it('ComingSoon 스텁은 implemented가 false다 — 준비 중을 열어 두면 빈 화면이 열린다', () => {
    const wrong = NAV_ORDER.filter(
      (id) => SCREEN_BY_ID[id].implemented && isComingSoonStub(id),
    )
    expect(wrong, `스텁인데 사이드바가 열려 있다: ${wrong.join(', ')}`).toEqual([])
  })

  it('선박 관리는 실 API로 도는 화면이다 (#510 · #527 회귀 고정)', () => {
    expect(SCREEN_BY_ID.VESSEL_MANAGEMENT.implemented).toBe(true)
    expect(isComingSoonStub('VESSEL_MANAGEMENT')).toBe(false)
  })

  it('설정은 아직 스텁이다 — #359 확정 전까지 (#506 · COR-9)', () => {
    expect(SCREEN_BY_ID.SETTINGS.implemented).toBe(false)
    expect(isComingSoonStub('SETTINGS')).toBe(true)
  })
})
