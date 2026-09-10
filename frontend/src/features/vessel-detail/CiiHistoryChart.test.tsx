// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { CiiHistoryChart } from './CiiHistoryChart'
import type { CiiYear } from './types'

/**
 * 연도별 이력 막대가 **색 말고 무늬로도 등급을 말한다** (#829 ⑸g · `DESIGN_SYSTEM §2.4.4`).
 *
 * `gradePatternUrl()` 소비처 다섯 중 **등급색 차트로 이 그림만 빠져 있었다.**
 * 인접 등급의 채움색 대비가 라이트 B↔C **1.21** · C↔D **1.19** · 다크 D↔E **1.04**라,
 * 색만으로는 막대 두 개를 구분할 수 없다.
 */
function year(overrides: Partial<CiiYear> & { regulationYear: number }): CiiYear {
  return {
    status: 'CONFIRMED',
    dataAvailable: true,
    reason: null,
    attainedCii: '5.000000',
    requiredCii: '5.500000',
    rating: 'B',
    voyageCount: 3,
    totalDistanceNm: '1000.00',
    totalFuelTon: '80.00',
    ...overrides,
  }
}

function patternsOf(container: HTMLElement): string[] {
  return [...container.querySelectorAll('rect.history__bar')]
    .map((rect) => rect.getAttribute('fill') ?? '')
    .filter((fill) => fill.startsWith('url(#grade-'))
}

describe('연도별 이력 막대의 등급 무늬 (#829)', () => {
  it('B~E 막대에 등급 무늬가 덮인다', () => {
    const { container } = render(
      <CiiHistoryChart
        years={[
          year({ regulationYear: 2023, rating: 'B' }),
          year({ regulationYear: 2024, rating: 'C' }),
          year({ regulationYear: 2025, rating: 'D' }),
          year({ regulationYear: 2026, rating: 'E' }),
        ]}
        basis="DWT"
      />,
    )

    expect(patternsOf(container)).toEqual([
      'url(#grade-b)',
      'url(#grade-c)',
      'url(#grade-d)',
      'url(#grade-e)',
    ])
  })

  it('등급 A에는 무늬를 덮지 않는다 — 그 등급은 무늬가 없다', () => {
    // `gradePatternUrl('A')`이 `undefined`다. 빈 `url()`을 그리면 SVG가 깨진다.
    const { container } = render(
      <CiiHistoryChart years={[year({ regulationYear: 2026, rating: 'A' })]} basis="DWT" />,
    )

    expect(patternsOf(container)).toEqual([])
    // 막대 자체는 그려진다 — 무늬만 없는 것이지 사라지는 것이 아니다.
    expect(container.querySelectorAll('rect.history__bar')).toHaveLength(1)
  })

  it('등급이 없는 해에는 무늬가 없다', () => {
    const { container } = render(
      <CiiHistoryChart
        years={[year({ regulationYear: 2026, rating: null, attainedCii: '5.000000' })]}
        basis="DWT"
      />,
    )

    expect(patternsOf(container)).toEqual([])
  })

  it('무늬가 채움을 가리지 않는다 — 같은 자리에 덮는다', () => {
    /*
     * 무늬는 **채움 위에 같은 도형을 한 번 더** 그린 것이다(`VesselGlyph`와 같은 방식).
     * 좌표가 어긋나면 무늬가 막대 밖으로 나가거나 이웃 막대를 덮는다.
     */
    const { container } = render(
      <CiiHistoryChart years={[year({ regulationYear: 2026, rating: 'C' })]} basis="DWT" />,
    )

    const bars = [...container.querySelectorAll('rect.history__bar')]
    expect(bars).toHaveLength(2)
    for (const attr of ['x', 'y', 'width', 'height']) {
      expect(bars[0].getAttribute(attr)).toBe(bars[1].getAttribute(attr))
    }
  })
})
