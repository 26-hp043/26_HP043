// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RegulatoryFlag, RegulatoryFlags } from './RegulatoryFlag'

/**
 * 규제 플래그 (`DESIGN_SYSTEM §8` · `#485` ④).
 *
 * 여기서 고정하는 것은 셋이다.
 *
 * * **등급과 별개 축이라는 것** — 같은 등급이라도 사유가 다르면 다르게 보여야 한다.
 * * **등급 색을 쓰지 않는 것** — 옆이 등급 배지라, 같은 색 계열이면 한 축으로 읽힌다.
 * * **규제 근거가 접근성 트리에 닿는 것** — 짧은 라벨만 남으면 「E 1년차」가 무엇을
 *   뜻하는지 화면 밖에서는 알 수 없다.
 */

describe('RegulatoryFlag', () => {
  it('사유마다 다른 라벨을 낸다 — 배지는 같고 플래그만 달라야 한다', () => {
    const { unmount } = render(<RegulatoryFlag reason="E_THIS_YEAR" />)
    expect(screen.getByText('E 1년차')).toBeDefined()
    unmount()

    render(<RegulatoryFlag reason="D_THIRD_YEAR" />)
    expect(screen.getByText('D 3년 연속')).toBeDefined()
  })

  it('규제 근거 전문을 대체 텍스트로 낸다', () => {
    render(<RegulatoryFlag reason="E_THIS_YEAR" vesselName="샘플 벌크선" />)
    const flag = screen.getByRole('img')
    expect(flag.getAttribute('aria-label')).toContain('시정조치계획 대상')
    expect(flag.getAttribute('aria-label')).toContain('샘플 벌크선')
  })

  it('폐기된 「운항 제한 위험」 표현을 쓰지 않는다', () => {
    render(<RegulatoryFlag reason="D_THIRD_YEAR" />)
    expect(screen.getByRole('img').getAttribute('aria-label')).not.toContain('운항 제한')
  })

  it('등급 색 토큰을 쓰지 않는다 (§8 — 옆이 등급 배지다)', () => {
    render(<RegulatoryFlag reason="E_THIS_YEAR" />)
    const cls = screen.getByRole('img').className
    expect(cls).not.toMatch(/cii-/)
    expect(cls).toContain('regulatory-flag')
  })
})

describe('RegulatoryFlags', () => {
  it('비어 있으면 아무것도 그리지 않는다', () => {
    const { container } = render(<RegulatoryFlags reasons={[]} />)
    expect(container.textContent).toBe('')
  })

  /*
   * 지금은 두 사유가 동시에 성립하지 않지만, `PRD §3.3.7`이 트리거를 늘릴 수 있다.
   * 화면이 「하나만 그린다」로 굳으면 그때 조용히 하나가 사라진다.
   */
  it('여러 사유를 모두 그린다', () => {
    render(<RegulatoryFlags reasons={['E_THIS_YEAR', 'D_THIRD_YEAR']} />)
    expect(screen.getAllByRole('img')).toHaveLength(2)
  })
})
