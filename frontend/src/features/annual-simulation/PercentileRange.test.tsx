// @vitest-environment jsdom
import '../../test/renderSetup'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PercentileRange } from './PercentileRange'
import { rangePlacement, rangeSummaryText } from './percentileRules'
import { ANNUAL_COPY } from './copy'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'

describe('분포 범위 막대 (#1456)', () => {
  it('낭독 문장이 화면의 네 값과 같다 — 서버 문자열을 표시 자릿수로 자른 값', () => {
    render(<PercentileRange p10="4.12349" p50="4.56781" p90="5.01239" mean="4.61001" />)

    const rail = screen.getByRole('img')
    const text = (value: string) => formatDecimalString(value, DISPLAY_DIGITS.cii)
    expect(rail.getAttribute('aria-label')).toBe(
      rangeSummaryText(text('4.12349'), text('4.56781'), text('5.01239'), text('4.61001')),
    )
  })

  it('밴드는 P10~P90, 점선은 P50 자리에 선다 — 양 끝 10% 여백', () => {
    const place = rangePlacement('4', '5', '6', '5.5')
    expect(place.p10).toBe(10)
    expect(place.p90).toBe(90)
    expect(place.p50).toBe(50)
    expect(place.mean).toBe(70)

    render(<PercentileRange p10="4" p50="5" p90="6" mean="5.5" />)
    const band = document.querySelector('.annual-sim__range-band') as HTMLElement
    const median = document.querySelector('.annual-sim__range-median') as HTMLElement
    expect(band.style.left).toBe('10%')
    expect(band.style.width).toBe('80%')
    expect(median.style.left).toBe('50%')
  })

  it('평균이 P90 밖(우측 꼬리)이어도 막대 안에 선다', () => {
    const place = rangePlacement('4', '5', '6', '7')
    expect(place.mean).toBe(90)
    expect(place.p90).toBeLessThan(place.mean)
    expect(place.p10).toBe(10)
  })

  it('네 값이 모두 같으면 가운데에 모은다 — 0으로 나누지 않는다', () => {
    expect(rangePlacement('5', '5', '5', '5')).toEqual({ p10: 50, p50: 50, p90: 50, mean: 50 })
  })

  it('중앙선 범례는 「중앙값(P50)」이다 — 평균과 헷갈리지 않게 (`DESIGN_SYSTEM §10.1`)', () => {
    expect(ANNUAL_COPY.rangeMedianLabel).toContain('P50')
    expect(ANNUAL_COPY.rangeMedianLabel).not.toBe(ANNUAL_COPY.rangeMeanLabel)
  })
})
