// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GradeBadge, NO_GRADE_TEXT } from './GradeBadge'
import type { Rating } from '../features/voyage-cii/types'

/**
 * 등급 배지 — `DESIGN_SYSTEM §8` variant 규격 (#485).
 *
 * `§8`이 **`grade`(a·b·c·d·e·none) × `size`(xs·sm·lg) = 18개**로 확정한다. 종전 구현은
 * `sm`·`md` 둘뿐이었고 `none`이 없었다.
 *
 * **이 파일은 `#557`이 들인 렌더 테스트 기반의 첫 활용이다.** 종전에는 배지가 SVG
 * 뷰박스에 문자를 그려 「`—`가 잘리는지」를 확인할 방법이 없었다.
 */

const GRADES: Rating[] = ['A', 'B', 'C', 'D', 'E']

describe('등급 6종 × 크기 3종 = 18 variant (§8)', () => {
  it.each(GRADES)('%s 등급이 문자로 표시된다', (rating) => {
    render(<GradeBadge rating={rating} />)

    expect(screen.getByRole('img').textContent).toBe(rating)
  })

  it('등급이 없으면 em dash를 쓴다 — N/A나 하이픈이 아니다 (§2.4.3 🔒)', () => {
    render(<GradeBadge rating={null} />)

    expect(screen.getByRole('img').textContent).toBe(NO_GRADE_TEXT)
    expect(NO_GRADE_TEXT).toBe('—')
  })

  it.each(['xs', 'sm', 'lg'] as const)('%s 크기가 클래스로 구분된다', (size) => {
    render(<GradeBadge rating="C" size={size} />)

    expect(screen.getByRole('img').className).toContain(`grade-badge--${size}`)
  })

  it('기본 크기는 lg다', () => {
    render(<GradeBadge rating="C" />)

    expect(screen.getByRole('img').className).toContain('grade-badge--lg')
  })
})

describe('색은 등급 토큰에서 온다 (§2.4.2)', () => {
  it('bg·border·text 세 토큰을 쓴다 — fill은 쓰지 않는다', () => {
    // `fill`은 마커·차트 선 등 면 채움 전용이다.
    render(<GradeBadge rating="D" />)

    const style = screen.getByRole('img').getAttribute('style') ?? ''
    expect(style).toContain('--cii-d-bg')
    expect(style).toContain('--cii-d-border')
    expect(style).toContain('--cii-d-text')
    expect(style).not.toContain('--cii-d-fill')
  })

  it('등급 없음은 none 토큰을 쓴다', () => {
    render(<GradeBadge rating={null} />)

    const style = screen.getByRole('img').getAttribute('style') ?? ''
    expect(style).toContain('--cii-none-bg')
  })
})

describe('접근성 (§14)', () => {
  it('문자를 뺀 variant를 만들지 않는다 — 문자가 없으면 §14 위반이다', () => {
    for (const rating of GRADES) {
      const { unmount } = render(<GradeBadge rating={rating} />)
      expect(screen.getByRole('img').textContent?.trim()).not.toBe('')
      unmount()
    }
  })

  it('기본 aria-label이 등급을 읽는다', () => {
    render(<GradeBadge rating="B" />)

    expect(screen.getByRole('img').getAttribute('aria-label')).toBe('등급 B')
  })

  it('등급 없음의 기본 aria-label은 「등급 없음」이다', () => {
    render(<GradeBadge rating={null} />)

    expect(screen.getByRole('img').getAttribute('aria-label')).toBe('등급 없음')
  })

  it('화면이 준 label이 기본값을 이긴다', () => {
    render(<GradeBadge rating="A" label="올해 누적 등급 A" />)

    expect(screen.getByRole('img').getAttribute('aria-label')).toBe('올해 누적 등급 A')
  })
})

describe('오토 레이아웃 — 고정 폭을 쓰지 않는다 (§8)', () => {
  it('폭을 인라인 스타일로 고정하지 않는다', () => {
    // 종전 SVG 구현은 64×64 고정이라 `—`가 잘렸다. `§8`이 그 방식을 막는다.
    render(<GradeBadge rating={null} />)

    const style = screen.getByRole('img').getAttribute('style') ?? ''
    expect(style).not.toContain('width')
  })
})
