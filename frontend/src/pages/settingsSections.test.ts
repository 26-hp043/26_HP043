import { describe, expect, it } from 'vitest'
import { REGULATION_PARAMETERS_ANCHOR } from '../features/parameters/referenceRules'
import {
  SETTINGS_SECTIONS,
  settingsSection,
  visibleSections,
  type SettingsSection,
} from './settingsSections'

/**
 * 설정의 절 목록 (#1791). 목차와 절이 **이 한 목록에서** 나온다.
 */

describe('설정 절 목록', () => {
  it('규제 기준값의 앵커를 새로 짓지 않는다 — 밖에서 오는 링크가 이미 그것을 쓴다', () => {
    // `#1239`의 세 자리가 `/settings#regulation-parameters`로 온다.
    const ids = SETTINGS_SECTIONS.map((section) => section.id)
    expect(ids).toContain(REGULATION_PARAMETERS_ANCHOR)
  })

  it('id가 겹치지 않는다 — 겹치면 목차의 한 줄이 엉뚱한 절로 간다', () => {
    const ids = SETTINGS_SECTIONS.map((section) => section.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('관리자 전용 절은 다른 역할의 목차에 없다 — 없는 자리로 가는 링크를 두지 않는다', () => {
    const admin: SettingsSection[] = visibleSections(true)
    const office: SettingsSection[] = visibleSections(false)

    expect(admin.map((s) => s.id)).toContain('account-role')
    expect(office.map((s) => s.id)).not.toContain('account-role')
    expect(office).toHaveLength(admin.length - 1)
  })

  it('절을 id로 찾는다 — 절이 제목을 여기서 가져간다', () => {
    expect(settingsSection(REGULATION_PARAMETERS_ANCHOR).label).toBe('규제 기준값')
  })

  it('없는 절을 찾으면 조용히 넘어가지 않는다', () => {
    // 빈 제목으로 그려지면 화면이 깨지지 않아 발견되지 않는다.
    expect(() => settingsSection('no-such')).toThrow(/설정에 없는 절/)
  })
})
