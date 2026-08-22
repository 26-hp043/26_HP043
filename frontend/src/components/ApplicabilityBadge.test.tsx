// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ApplicabilityBadge } from './ApplicabilityBadge'
import { APPLICABILITY_FULL_TEXT, applicabilityState } from './applicability'

/**
 * CII 적용 대상 배지 (`DESIGN_SYSTEM §8.2` · `#653`).
 *
 * 여기서 고정하는 것은 넷이다.
 *
 * * **적용 대상이면 아무것도 그리지 않는 것** — 정상 상태를 배지로 덮으면 예외가 묻힌다.
 * * **「미해당」과 「판정 불가」가 갈리는 것** — 이 이슈의 본체다.
 * * **화면이 GT로 다시 판정하지 않는 것** — 임계값(5,000)이 화면에 나오면 안 된다.
 * * **전체 문구가 접근성 트리에 닿는 것** — 짧은 라벨만으로는 무엇을 하라는지 모른다.
 */

describe('applicabilityState', () => {
  it('서버가 적용 대상이라고 하면 그대로 따른다', () => {
    expect(applicabilityState({ isCiiApplicableHint: true, grossTonnage: 30000 })).toBe(
      'APPLICABLE',
    )
  })

  it('미해당인데 GT가 있으면 「대상 아님」이다', () => {
    expect(applicabilityState({ isCiiApplicableHint: false, grossTonnage: 4999 })).toBe(
      'NOT_APPLICABLE',
    )
  })

  it('미해당인데 GT가 없으면 「판정 불가」다 — 단정하지 않는다', () => {
    expect(applicabilityState({ isCiiApplicableHint: false, grossTonnage: null })).toBe(
      'UNKNOWN',
    )
  })

  it('GT가 문자열로 와도 같은 판정을 낸다', () => {
    expect(applicabilityState({ isCiiApplicableHint: false, grossTonnage: '4999.00' })).toBe(
      'NOT_APPLICABLE',
    )
  })
})

describe('ApplicabilityBadge', () => {
  it('적용 대상이면 아무것도 그리지 않는다', () => {
    const { container } = render(
      <ApplicabilityBadge isCiiApplicableHint grossTonnage={30000} />,
    )
    expect(container.textContent).toBe('')
  })

  it('GT가 작으면 「규제 대상 아님」', () => {
    render(<ApplicabilityBadge isCiiApplicableHint={false} grossTonnage={4999} />)
    expect(screen.getByText('규제 대상 아님')).toBeDefined()
  })

  it('GT가 없으면 「GT 미입력」 — 두 상태가 같은 말을 하지 않는다', () => {
    render(<ApplicabilityBadge isCiiApplicableHint={false} grossTonnage={null} />)
    expect(screen.getByText('GT 미입력')).toBeDefined()
    expect(screen.queryByText('규제 대상 아님')).toBeNull()
  })

  it('전체 문구가 aria-label로 나간다 — 짧은 라벨만으로는 할 일을 모른다', () => {
    render(
      <ApplicabilityBadge
        isCiiApplicableHint={false}
        grossTonnage={null}
        vesselName="STAR SKIPPER"
      />,
    )
    const badge = screen.getByRole('img')
    expect(badge.getAttribute('aria-label')).toContain('STAR SKIPPER')
    expect(badge.getAttribute('aria-label')).toContain('총톤수')
    expect(badge.getAttribute('title')).toBe(APPLICABILITY_FULL_TEXT.UNKNOWN)
  })

  it('임계값(5,000)을 화면에 적지 않는다 — 판정은 서버 소관이다', () => {
    for (const gt of [null, 4999]) {
      const { container, unmount } = render(
        <ApplicabilityBadge isCiiApplicableHint={false} grossTonnage={gt} />,
      )
      expect(container.innerHTML).not.toMatch(/5,?000/)
      unmount()
    }
  })
})
