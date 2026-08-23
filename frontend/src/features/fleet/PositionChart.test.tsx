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

/**
 * 겹치는 마커를 벌린다.
 *
 * 이 그림은 선대의 좌표 범위에 맞춰 확대된다. 시연 데이터가 수에즈~한국 97°를
 * 걸치는데 네 척 중 셋이 한국 앞바다라, 그 셋이 몇 px 안에 들어와 **한 덩어리로
 * 뭉쳤다.** 「보유 선박 4척」이라 적어 놓고 그림에는 배가 둘로 보였다.
 *
 * `#701` ⑥이 「윤곽을 모든 마커에 줘서 몇 척인지 셀 수 있게」 한 것이 여기서
 * 무력해진다 — 좌표가 거의 같으면 윤곽도 겹친다.
 */
describe('위치 개략도 — 겹침 분산', () => {
  /** 마커를 옮기는 `<g transform>`만 고른다. 안쪽 채움·무늬 `<g>`에는 없다. */
  function markerTransforms(container: HTMLElement): string[] {
    return [...container.querySelectorAll('g[transform]')].map(
      (node) => node.getAttribute('transform') ?? '',
    )
  }

  it('같은 좌표의 세 척이 서로 다른 자리에 그려진다', () => {
    const { container } = render(
      <PositionChart
        vessels={[
          vessel({ id: 'a', lat: '35.0', lon: '129.0' }),
          vessel({ id: 'b', lat: '35.0', lon: '129.0' }),
          vessel({ id: 'c', lat: '35.0', lon: '129.0' }),
          vessel({ id: 'far', lat: '30.0', lon: '32.0' }),
        ]}
      />,
    )
    const transforms = markerTransforms(container)
    expect(transforms).toHaveLength(4)
    expect(new Set(transforms).size).toBe(4)
  })

  it('벌린 사실을 화면에 적는다 — 없는 정밀도를 주장하지 않는다', () => {
    render(
      <PositionChart
        vessels={[
          vessel({ id: 'a', lat: '35.0', lon: '129.0' }),
          vessel({ id: 'b', lat: '35.0', lon: '129.0' }),
        ]}
      />,
    )
    expect(screen.getByText(/조금 벌려 그렸습니다/)).toBeTruthy()
  })

  it('겹치지 않으면 벌렸다고 적지 않는다', () => {
    render(
      <PositionChart
        vessels={[
          vessel({ id: 'a', lat: '35.0', lon: '129.0' }),
          vessel({ id: 'b', lat: '30.0', lon: '32.0' }),
        ]}
      />,
    )
    expect(screen.queryByText(/조금 벌려 그렸습니다/)).toBeNull()
  })

  /*
   * 자리를 무작위로 정하면 다시 그릴 때마다 배가 자리를 바꾼다. 시연 중 화면이
   * 갱신되면 **같은 배가 움직인 것처럼 보인다.**
   */
  it('다시 그려도 같은 자리다 — 배치가 입력에만 달려 있다', () => {
    const fleet = [
      vessel({ id: 'a', lat: '35.0', lon: '129.0' }),
      vessel({ id: 'b', lat: '35.0', lon: '129.0' }),
      vessel({ id: 'c', lat: '35.0', lon: '129.0' }),
    ]
    const first = markerTransforms(render(<PositionChart vessels={fleet} />).container)
    const second = markerTransforms(render(<PositionChart vessels={fleet} />).container)
    expect(second).toEqual(first)
  })

  it('그림 설명을 차트가 낸다 — 대시보드가 따로 적지 않는다', () => {
    render(<PositionChart vessels={[vessel({ id: 'a' })]} />)
    expect(screen.getByText(/배 색과 무늬는 올해 누적\(YTD\) 등급입니다/)).toBeTruthy()
  })
})
