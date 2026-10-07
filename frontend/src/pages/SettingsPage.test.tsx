// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { SettingsPage } from './SettingsPage'
import * as session from '../auth/session'
import { visibleSections } from './settingsSections'
import { REGULATION_PARAMETERS_ANCHOR } from '../features/parameters/referenceRules'

/**
 * 설정 탭 (#1791 → 10/7 디자인 결정 · #2321).
 *
 * 종전에는 절 여섯을 한 장에 쌓고 위에 절 목차(앵커 링크)를 두었다. 10/7 결정으로 목차가
 * **탭 셋**(내 프로필 / 팀 · 역할 (관리자 전용) / 규제 기준값)으로 바뀌었다.
 *
 * 지키려던 것은 그대로 하나다 — **고를 수 있는 자리가 실제로 있는가.** 목록(`settingsSections`)의
 * 절이 어느 탭에도 없거나, 탭이 가리키는 패널이 비어 있으면 누르고 나서야 아무 데도 가지 않는다.
 */

function stubRole(role: session.UserRole) {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'tester@bluelog.local',
    displayName: null,
    role,
    emailVerifiedAt: null,
    hasAvatar: false,
  })
  // 팀 탭이 계정 목록을 묻는다 — 서버로 나가지 않게 세운다.
  vi.spyOn(session, 'listUsers').mockResolvedValue([])
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  )
}

function tabs(): HTMLElement[] {
  return within(screen.getByRole('tablist')).getAllByRole('tab')
}

/** 탭을 하나씩 열며 그 패널 안에 그려진 절의 `id`를 모은다. */
function sectionIdsReachableByTabs(): Set<string> {
  const found = new Set<string>()
  for (const tab of tabs()) {
    fireEvent.click(tab)
    expect(tab.getAttribute('aria-selected')).toBe('true')
    const panel = document.getElementById(tab.getAttribute('aria-controls') ?? '')
    expect(panel, `${tab.textContent} 탭의 패널이 없다`).not.toBeNull()
    expect(panel!.hidden).toBe(false)
    for (const node of panel!.querySelectorAll('[id]')) found.add(node.id)
  }
  return found
}

afterEach(() => {
  vi.restoreAllMocks()
  window.history.replaceState(null, '', '/')
})

describe('설정 탭 (#1791 · #2321)', () => {
  it.each(['OFFICE', 'ADMIN', 'FIELD'] as const)(
    '%s — 목록의 절이 전부 어느 탭에선가 열린다',
    (role) => {
      stubRole(role)
      renderPage()

      const reachable = sectionIdsReachableByTabs()
      const missing = visibleSections(role === 'ADMIN')
        .map((section) => section.id)
        .filter((id) => !reachable.has(id))
      expect(missing, '어느 탭에서도 열리지 않는 절이다').toEqual([])
    },
  )

  it('관리자 전용 탭은 사무직에게 없다 — 눌러도 갈 데가 없다', () => {
    stubRole('OFFICE')
    const { container } = renderPage()
    expect(tabs()).toHaveLength(2)
    sectionIdsReachableByTabs()
    expect(container.querySelector('#account-role')).toBeNull()
  })

  it('관리자에게는 그 탭이 있고, 열면 역할 지정 절이 있다', () => {
    stubRole('ADMIN')
    renderPage()
    expect(tabs()).toHaveLength(3)
    expect(sectionIdsReachableByTabs().has('account-role')).toBe(true)
  })

  it('처음에는 첫 탭(내 프로필)이 열린다', () => {
    stubRole('OFFICE')
    renderPage()
    expect(tabs()[0].getAttribute('aria-selected')).toBe('true')
    expect(document.getElementById('account-info')).not.toBeNull()
    expect(document.getElementById(REGULATION_PARAMETERS_ANCHOR)).toBeNull()
  })

  it('밖에서 오는 `#regulation-parameters` 링크는 규제 기준값 탭을 연다', () => {
    // `#1239`의 세 자리가 `/settings#regulation-parameters`로 온다 — 앵커가 가리키던 절이 그 탭 안에 있다.
    window.history.replaceState(null, '', `/settings#${REGULATION_PARAMETERS_ANCHOR}`)
    stubRole('OFFICE')
    renderPage()
    const panel = document.getElementById(REGULATION_PARAMETERS_ANCHOR)?.closest('[role="tabpanel"]')
    expect(panel, '규제 기준값 절이 열리지 않았다').toBeTruthy()
    expect((panel as HTMLElement).hidden).toBe(false)
  })

  it('`?tab=regulation`으로도 규제 기준값 탭을 연다', () => {
    window.history.replaceState(null, '', '/settings?tab=regulation')
    stubRole('FIELD')
    renderPage()
    expect(document.getElementById(REGULATION_PARAMETERS_ANCHOR)).not.toBeNull()
  })

  it('이미 열린 화면에서 해시가 바뀌어도 규제 기준값 탭으로 간다', () => {
    stubRole('OFFICE')
    renderPage()
    expect(document.getElementById(REGULATION_PARAMETERS_ANCHOR)).toBeNull()

    act(() => {
      window.history.replaceState(null, '', `/settings#${REGULATION_PARAMETERS_ANCHOR}`)
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(document.getElementById(REGULATION_PARAMETERS_ANCHOR)).not.toBeNull()
  })
})
