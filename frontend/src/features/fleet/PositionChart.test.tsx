// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PositionChart } from './PositionChart'
import type { FleetVessel } from './types'

/**
 * 위치 개략도의 **결측 표기** (`#705`).
 *
 * 좌표가 없는 선박은 그림에서 조용히 빠진다. 여기서 고정하는 것은 하나다 —
 * **화면이 남은 것을 전부인 것처럼 보여 주지 않는다.**
 *
 * 갈래가 셋이라 셋 다 잡는다. 종전에는 「전부 없음」만 다뤄져 있었고, 그 안내가
 * 있다는 사실이 오히려 **「일부만 없음」이 처리된 것처럼 보이게** 했다.
 */

/*
 * `as FleetVessel` 캐스트를 쓰지 않는다. 캐스트를 두면 타입이 바뀌었을 때
 * **픽스처만 조용히 낡는다** (`VesselMark.test.tsx`가 실제로 그렇게 세 필드를
 * 빠뜨렸다).
 */
function vessel(over: Partial<FleetVessel> = {}): FleetVessel {
  return {
    id: 'v1',
    name: '샘플 벌크선',
    shipType: 'BULK_CARRIER',
    imoNumber: '9100001',
    underwayState: 'UNDER_WAY',
    detailStatus: 'SAILING',
    lat: '35.1',
    lon: '129.0',
    positionUpdatedAt: '2026-08-23T12:00:00Z',
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

/** 좌표가 없는 선박. 목록에는 나오지만 그림에는 못 들어간다. */
function noPosition(over: Partial<FleetVessel> = {}): FleetVessel {
  return vessel({ lat: null, lon: null, positionUpdatedAt: null, ...over })
}

describe('위치 개략도 — 결측 표기', () => {
  it('일부만 빠지면 몇 척 중 몇 척인지 말한다', () => {
    render(
      <PositionChart
        vessels={[
          vessel({ id: 'a' }),
          vessel({ id: 'b', lat: '34.0', lon: '128.0' }),
          vessel({ id: 'c', lat: '33.0', lon: '127.0' }),
          noPosition({ id: 'd', name: '샘플 로로 여객선' }),
        ]}
      />,
    )
    const note = screen.getByText(/표시되지 않았습니다/)
    expect(note.textContent).toContain('1척')
    expect(note.textContent).toContain('4척 중 3척')
  })

  it('빠진 선박의 이름은 적지 않는다 — 그 답은 선박 목록이 한다', () => {
    render(
      <PositionChart
        vessels={[vessel({ id: 'a' }), noPosition({ id: 'd', name: '샘플 로로 여객선' })]}
      />,
    )
    expect(screen.getByText(/표시되지 않았습니다/).textContent).not.toContain(
      '샘플 로로 여객선',
    )
  })

  it('결측이 접근성 트리에도 닿는다 — 눈으로 보는 쪽에만 있으면 반쪽이다', () => {
    const { container } = render(
      <PositionChart vessels={[vessel({ id: 'a' }), noPosition({ id: 'd' })]} />,
    )
    const label = container.querySelector('svg')?.getAttribute('aria-label') ?? ''
    expect(label).toContain('선박 1척')
    expect(label).toContain('좌표가 없는 1척은 빠져 있습니다')
  })

  it('빠진 것이 없으면 문구를 내지 않는다 — 「4척 중 4척」은 소음이다', () => {
    render(
      <PositionChart
        vessels={[vessel({ id: 'a' }), vessel({ id: 'b', lat: '34.0', lon: '128.0' })]}
      />,
    )
    expect(screen.queryByText(/표시되지 않았습니다/)).toBeNull()
    const label = document.querySelector('svg')?.getAttribute('aria-label') ?? ''
    expect(label).not.toContain('빠져 있습니다')
  })

  it('전부 빠지면 종전의 빈 상태를 그대로 쓴다', () => {
    render(<PositionChart vessels={[noPosition({ id: 'a' }), noPosition({ id: 'd' })]} />)
    expect(screen.getByText(/위치가 기록된 선박이 없습니다/)).toBeTruthy()
    expect(screen.queryByText(/표시되지 않았습니다/)).toBeNull()
  })

  it('일부 결측과 전부 결측이 같은 안내 문장을 공유한다', () => {
    const partial = render(
      <PositionChart vessels={[vessel({ id: 'a' }), noPosition({ id: 'd' })]} />,
    ).container.textContent
    const empty = render(<PositionChart vessels={[noPosition({ id: 'd' })]} />).container
      .textContent
    const shared = '선박 상세에서 현재 위치를 입력하면 여기에 표시됩니다.'
    expect(partial).toContain(shared)
    expect(empty).toContain(shared)
  })
})
