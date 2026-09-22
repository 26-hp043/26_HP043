// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { VerdictStrip } from './VerdictStrip'

/** 결론 띠의 칸 구성 — `DESIGN_SYSTEM §8.6` 🔒 (#1711). */
describe('결론 띠', () => {
  function renderStrip(mainRating?: 'C') {
    return render(
      <VerdictStrip
        label="결론"
        main={{ label: '참고 등급 · 예상 CII', value: '4.982', rating: mainRating }}
        sub={{ label: '다음 경계까지', value: 'D 등급까지 7.2%' }}
        risk={{ level: 'CRITICAL', heading: '위험도', text: '심각 CRITICAL', withIcon: true }}
      />,
    )
  }

  it('주 · 보조 · 위험도 세 칸이고, 주 결론 크기 자리는 하나뿐이다', () => {
    renderStrip('C')
    const strip = screen.getByRole('region', { name: '결론' })
    expect(strip.querySelectorAll('.verdict-strip__value')).toHaveLength(1)
    expect(strip.querySelector('.verdict-strip__sub .verdict-strip__value')).toBeNull()
    expect(strip.querySelectorAll('.verdict-strip__risk')).toHaveLength(1)
    expect(within(strip).getByText('심각 CRITICAL').className).toContain(
      'verdict-strip__risk-value--critical',
    )
  })

  it('등급이 있으면 배지와 값이 한 쌍이다 (`§14`) — 주 결론은 `lg`', () => {
    renderStrip('C')
    const main = screen.getByRole('region', { name: '결론' }).querySelector('.verdict-strip__main')!
    const badge = within(main as HTMLElement).getByRole('img', { name: '참고 등급 · 예상 CII C' })
    expect(badge.className).toContain('grade-badge--lg')
    expect(badge.parentElement).toBe(main.querySelector('.verdict-strip__value')!.parentElement)
  })

  it('등급이 없으면 배지를 그리지 않는다 — 값만 선다', () => {
    renderStrip()
    const strip = screen.getByRole('region', { name: '결론' })
    expect(strip.querySelector('.verdict-strip__main .grade-badge')).toBeNull()
  })
})
