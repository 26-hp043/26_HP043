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
    expect(findScreenByPath('/vessels')).toBeUndefined()
  })

  it('등록되지 않은 경로는 undefined를 반환한다', () => {
    expect(findScreenByPath('/no-such-screen')).toBeUndefined()
  })
})
