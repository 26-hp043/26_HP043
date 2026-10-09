// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { PrivacyPage, TermsPage } from './LegalPage'
import { SCREEN_BY_ID } from '../screens'
import { WITHDRAWAL_NOTICE } from '../features/auth/authRules'

/**
 * 이용약관 · 개인정보처리방침 (`UIFLOW 0-5` · `0-6`).
 *
 * 두 문서는 **확인된 사실만** 적고, 운영 주체가 정할 칸은 「입력 필요」로 보인다 —
 * 그 칸이 조용히 비거나 지어낸 값으로 채워지지 않는지를 본다.
 */
function renderAt(page: 'terms' | 'privacy') {
  return render(<MemoryRouter>{page === 'terms' ? <TermsPage /> : <PrivacyPage />}</MemoryRouter>)
}

describe('이용약관 · 개인정보처리방침', () => {
  it.each(['terms', 'privacy'] as const)('%s — 제목이 화면 표의 이름이고 탭 제목에도 붙는다', (page) => {
    renderAt(page)
    const label = page === 'terms' ? SCREEN_BY_ID.TERMS.label : SCREEN_BY_ID.PRIVACY.label
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(label)
    expect(document.title).toContain(label)
  })

  it.each(['terms', 'privacy'] as const)('%s — 정해지지 않은 칸은 「입력 필요」로 보인다', (page) => {
    const { container } = renderAt(page)
    const todos = container.querySelectorAll('.legal__todo')
    expect(todos.length).toBeGreaterThan(0)
    for (const todo of todos) expect(todo.textContent).toContain('입력 필요')
    // 시행일 · 운영 주체는 두 문서 모두 확정 전이다.
    expect(screen.getByText('시행일').closest('div')?.textContent).toContain('입력 필요')
  })

  it('두 문서가 서로를 잇고, 로그인으로 돌아가는 길이 있다', () => {
    renderAt('terms')
    const nav = screen.getByRole('navigation', { name: '약관 문서' })
    const hrefs = [...nav.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    expect(hrefs).toContain(SCREEN_BY_ID.PRIVACY.path)
    expect(hrefs).toContain(SCREEN_BY_ID.LOGIN.path)
  })

  it('약관의 탈퇴 조항은 정본 문구를 그대로 쓴다 — 다시 적지 않는다', () => {
    renderAt('terms')
    expect(document.body.textContent).toContain(WITHDRAWAL_NOTICE)
  })

  it('처리방침은 외부 언어모델에 보내지 않는 것을 적는다 (PRD §16.3.1)', () => {
    renderAt('privacy')
    const text = document.body.textContent ?? ''
    for (const kept of ['선박명', 'IMO 번호', '항구', '연료량']) expect(text).toContain(kept)
  })
})
