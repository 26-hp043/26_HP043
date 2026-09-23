// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { SettingsPage } from './SettingsPage'
import * as session from '../auth/session'

/**
 * 설정 절 목차 (#1791).
 *
 * 이 화면은 절이 여섯이고 2.24 화면이다 — 규제 기준값이 `1,021px`(1.13 화면) 아래에서
 * 시작해, 내려가는 길이 스크롤뿐이었다. **하위 메뉴는 만들지 않는다**(`#1239`).
 *
 * 여기서 보는 것은 하나다 — **목차가 가리키는 자리가 실제로 있는가.** 목록이 갈리면
 * 링크는 누르고 나서야 아무 데도 가지 않고, 그 상태는 화면을 봐서는 드러나지 않는다.
 */

function stubRole(role: session.UserRole) {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'tester@bluelog.local',
    displayName: null,
    role,
    emailVerifiedAt: null,
  })
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  )
}

/** 목차의 링크가 가리키는 id들. */
function tocTargets(): string[] {
  const nav = screen.getByRole('navigation', { name: '설정 절 바로가기' })
  return [...nav.querySelectorAll('a')].map((a) => (a.getAttribute('href') ?? '').replace('#', ''))
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('설정 절 목차 (#1791)', () => {
  it.each(['OFFICE', 'ADMIN'] as const)(
    '%s — 목차가 가리키는 절이 화면에 실제로 있다',
    (role) => {
      stubRole(role)
      const { container } = renderPage()

      const targets = tocTargets()
      expect(targets.length).toBeGreaterThan(0)
      for (const id of targets) {
        expect(container.querySelector(`#${id}`), `${id} 절이 화면에 없다`).not.toBeNull()
      }
    },
  )

  it('관리자 전용 절은 사무직 목차에 없다 — 눌러도 갈 데가 없다', () => {
    stubRole('OFFICE')
    renderPage()
    expect(tocTargets()).not.toContain('account-role')
  })

  it('관리자에게는 그 절이 목차에도 화면에도 있다', () => {
    stubRole('ADMIN')
    const { container } = renderPage()
    expect(tocTargets()).toContain('account-role')
    expect(container.querySelector('#account-role')).not.toBeNull()
  })

  it('규제 기준값 링크가 밖에서 오는 링크와 같은 앵커를 쓴다', () => {
    stubRole('OFFICE')
    renderPage()
    // `#1239`의 세 자리가 `/settings#regulation-parameters`로 온다.
    expect(tocTargets()).toContain('regulation-parameters')
  })
})
