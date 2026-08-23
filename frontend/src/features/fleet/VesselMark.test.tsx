// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { VesselMark } from './VesselMark'
import { UnderwayChip } from './UnderwayChip'
import type { FleetVessel } from './types'

/**
 * 선박 마크와 상태 칩 (`#701` ④⑤).
 *
 * 여기서 고정하는 것은 셋이다.
 *
 * * **등급이 색 단독으로 전달되지 않는다** (`§14`) — 마크가 `GradeBadge`를 대신하므로
 *   배지가 쓰던 세 채널을 그대로 갖고 있어야 한다
 * * **등급 없음을 등급으로 그리지 않는다** — 중립색 배는 「옅은 등급」으로 읽힌다
 * * **상태 칩이 등급색을 쓰지 않는다** — 운항 상태는 등급과 다른 축이다
 */

/*
 * `as FleetVessel` 캐스트를 쓰지 않는다. 캐스트를 두면 타입이 바뀌었을 때
 * **픽스처만 조용히 낡는다** — 실제로 이 파일이 그렇게 세 필드를 빠뜨렸다.
 */
function vessel(over: Partial<FleetVessel> = {}): FleetVessel {
  return {
    id: 'v1',
    name: '샘플 벌크선',
    shipType: 'BULK_CARRIER',
    imoNumber: '9100001',
    underwayState: 'UNDER_WAY',
    detailStatus: 'SAILING',
    lat: null,
    lon: null,
    positionUpdatedAt: null,
    isCiiApplicableHint: true,
    grossTonnage: 50000,
    dataAvailable: true,
    unavailableReason: null,
    ytdAttainedCii: '8.9801',
    ytdRequiredCii: '5.0450',
    ytdRating: 'E',
    riskLevel: 'HIGH',
    riskReasons: [],
    daysToD: 12,
    daysToDReason: null,
    ...over,
  }
}

describe('선박 마크', () => {
  it('등급이 접근성 트리에 닿는다 — 색·패턴만으로 두지 않는다', () => {
    render(<VesselMark vessel={vessel({ ytdRating: 'E' })} />)
    expect(screen.getByLabelText(/올해 누적 등급 E/)).toBeTruthy()
  })

  it('등급 문자를 눈으로도 낸다 — 마크의 세 번째 채널이다', () => {
    const { container } = render(<VesselMark vessel={vessel({ ytdRating: 'D' })} />)
    expect(container.querySelector('.vessel__mark-grade')?.textContent).toBe('D')
  })

  it('등급마다 다른 무늬를 쓴다 — 3색 체계는 색만으로 갈리지 않는다', () => {
    const d = render(<VesselMark vessel={vessel({ ytdRating: 'D' })} />).container.innerHTML
    const e = render(<VesselMark vessel={vessel({ ytdRating: 'E' })} />).container.innerHTML
    expect(d).toContain('url(#grade-d)')
    expect(e).toContain('url(#grade-e)')
  })

  it('등급이 없으면 배를 그리지 않는다 — 중립색 배는 「옅은 등급」으로 읽힌다', () => {
    const { container } = render(
      <VesselMark
        vessel={vessel({ ytdRating: null, dataAvailable: false, unavailableReason: 'NO_DATA' })}
      />,
    )
    expect(container.querySelector('svg')).toBeNull()
    // 자리를 비우지도 않는다 — 열이 어긋난다.
    expect(container.textContent).toContain('—')
  })

  it('등급이 없는 이유를 읽어 준다 (#419)', () => {
    render(
      <VesselMark
        vessel={vessel({ ytdRating: null, dataAvailable: false, unavailableReason: 'NO_DATA' })}
      />,
    )
    // 사유가 없으면 항차를 넣어야 하는지 제원을 넣어야 하는지 알 수 없다.
    expect(screen.getByLabelText(/샘플 벌크선 —/)).toBeTruthy()
  })
})

describe('운항 상태 칩', () => {
  it('운항과 정박이 다른 아이콘을 쓴다 — 색이 아니라 형태로 갈린다', () => {
    const sailing = render(<UnderwayChip vessel={vessel({ underwayState: 'UNDER_WAY' })} />)
    const moored = render(
      <UnderwayChip vessel={vessel({ underwayState: 'NOT_UNDER_WAY', detailStatus: 'AT_ANCHOR' })} />,
    )
    const a = sailing.container.querySelector('.vessel__state-icon')?.innerHTML
    const b = moored.container.querySelector('.vessel__state-icon')?.innerHTML
    expect(a).toBeTruthy()
    expect(b).toBeTruthy()
    expect(a).not.toBe(b)
  })

  it('등급색을 쓰지 않는다 — 운항 상태는 등급과 다른 축이다', () => {
    const { container } = render(<UnderwayChip vessel={vessel({ ytdRating: 'E' })} />)
    expect(container.innerHTML).not.toMatch(/cii-[a-e]-/)
  })

  it('세부 상태를 표시 문구로 낸다 — 코드를 그대로 내지 않는다', () => {
    render(<UnderwayChip vessel={vessel({ underwayState: 'NOT_UNDER_WAY', detailStatus: 'AT_ANCHOR' })} />)
    expect(screen.getByText(/정박 중 · 묘박/)).toBeTruthy()
  })

  it('상태 미기록을 「정박」으로 적지 않는다 — 없는 사실이 된다', () => {
    render(<UnderwayChip vessel={vessel({ underwayState: null, detailStatus: null })} />)
    expect(screen.getByText('상태 미기록')).toBeTruthy()
  })
})
