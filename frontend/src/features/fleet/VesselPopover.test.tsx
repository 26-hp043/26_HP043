// @vitest-environment jsdom
import '../../test/renderSetup'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { VesselPopover, type YearEnd } from './VesselPopover'
import type { FleetVessel } from './types'

/**
 * 마커 팝오버 (#1831 · `DESIGN_SYSTEM §9.5` v2.28).
 *
 * 여기서 보는 것은 **카드 하나**다 — 마커가 버튼인지는 `FleetMap.test.tsx`, 무대에
 * 붙는 자리와 초점 복귀는 `FleetDashboard.test.tsx`가 본다.
 */
const vessel = {
  id: 'v1',
  name: '부산호',
  imoNumber: '9000001',
  ytdRating: 'C',
  ytdAttainedCii: '12.3456',
  underwayState: 'UNDER_WAY',
  riskReasons: [],
} as unknown as FleetVessel

const ANCHOR = { left: 100, top: 100, size: 22 }
const STAGE = { width: 1000, height: 600 }

function open(
  overrides: Partial<Parameters<typeof VesselPopover>[0]> = {},
  yearEnd: (() => Promise<YearEnd>) | null = async () => ({ rating: 'D', attainedCii: '13.9999' }),
) {
  const onClose = overrides.onClose ?? vi.fn()
  render(
    <MemoryRouter>
      <VesselPopover
        vessel={vessel}
        anchor={ANCHOR}
        stage={STAGE}
        panelRight={0}
        onClose={onClose}
        provider={yearEnd === null ? undefined : { yearEnd }}
        {...overrides}
      />
    </MemoryRouter>,
  )
  return { onClose }
}

describe('마커 팝오버 — 무엇을 말하는가 (#1831)', () => {
  it('누적은 받은 값을 적고 연말 예상은 열 때 한 번 묻는다', async () => {
    const yearEnd = vi.fn(async () => ({ rating: 'D', attainedCii: '13.9999' }))
    open({}, yearEnd)

    expect(screen.getByRole('dialog', { name: '부산호 요약' })).toBeTruthy()
    expect(screen.getByText('운항 중')).toBeTruthy()
    // 자릿수는 `§4.1`(🔒) — 선박 목록과 **같은 포매터**를 쓴다. 원본 4자리가 3자리로 줄어든다.
    expect(screen.getByText('C · 12.346')).toBeTruthy()
    expect(screen.getByText(/불러오는 중/)).toBeTruthy()

    await waitFor(() => expect(screen.getByText('D · 14.000')).toBeTruthy())
    expect(yearEnd).toHaveBeenCalledTimes(1)
    expect(yearEnd).toHaveBeenCalledWith('v1')
  })

  /**
   * **실패가 카드 안에서 끝난다.**
   *
   * 던지면 대시보드가 통째로 오류 화면이 된다 — 이미 받아 둔 지도와 선박 목록까지
   * 사라지는 것이 곧 격리 실패다. 카드가 계속 서 있고 이름·누적은 그대로 읽혀야 한다.
   */
  it('연말 예상 조회가 실패해도 카드가 서 있고 나머지는 그대로 읽힌다', async () => {
    open({}, async () => {
      throw new Error('502')
    })

    await waitFor(() => expect(screen.getByText(/연말 예상을 불러오지 못했습니다/)).toBeTruthy())
    expect(screen.getByRole('dialog', { name: '부산호 요약' })).toBeTruthy()
    expect(screen.getByText('C · 12.346')).toBeTruthy()
  })

  it('서버가 값을 못 주면 「—」다 — 빈 칸으로 두지 않는다', async () => {
    open({}, async () => ({ rating: null, attainedCii: null }))
    await waitFor(() => expect(screen.getByText('— · —')).toBeTruthy())
  })
})

describe('마커 팝오버 — 닫히는 길 (#1831)', () => {
  it('열리면 초점이 카드로 온다 — 낭독이 열린 것을 알고 Tab이 카드 안으로 간다', async () => {
    open()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('dialog')))
  })

  it('Esc로 닫는다', () => {
    const { onClose } = open()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('닫기 버튼으로 닫는다', () => {
    const { onClose } = open()
    fireEvent.click(screen.getByRole('button', { name: '닫기' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('바깥을 누르면 닫는다', () => {
    const { onClose } = open()
    fireEvent.pointerDown(document.body)
    expect(onClose).toHaveBeenCalled()
  })

  it('카드 안을 누르는 것은 닫지 않는다', () => {
    const { onClose } = open()
    fireEvent.pointerDown(screen.getByRole('dialog'))
    expect(onClose).not.toHaveBeenCalled()
  })

  /**
   * **마커는 「바깥」이 아니다.** 다른 배를 누를 때 닫혔다 열리면 한 번 깜빡인다 —
   * 마커를 누르면 그 배의 선택이 카드를 바꿔 달고, 「한 번에 하나」는 그렇게 지켜진다.
   */
  it('다른 마커를 누르는 것은 닫지 않는다 — 카드가 깜빡이지 않고 갈린다', () => {
    const { onClose } = open()
    const marker = document.createElement('button')
    marker.className = 'fleetmap__marker'
    document.body.appendChild(marker)

    fireEvent.pointerDown(marker)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('지도 위에서 굴리면 닫는다 — 확대는 마커 자리를 옮긴다', () => {
    const { onClose } = open()
    const canvas = document.createElement('div')
    canvas.className = 'fleetmap__canvas'
    document.body.appendChild(canvas)

    fireEvent.wheel(canvas)
    expect(onClose).toHaveBeenCalled()
  })

  it('패널 목록을 굴리는 것은 닫지 않는다 — 지도와 무관하다', () => {
    const { onClose } = open()
    const list = document.createElement('div')
    list.className = 'fleet__list'
    document.body.appendChild(list)

    fireEvent.wheel(list)
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('마커 팝오버 — 자리 (#1831 · §9.5)', () => {
  const styleOf = () => screen.getByRole('dialog').getAttribute('style') ?? ''

  it('기본은 배 오른쪽 옆이다', () => {
    open()
    // 마커 왼쪽 100 + 폭 22 + 틈 10 = 132
    expect(styleOf()).toContain('left: 132px')
  })

  it('오른쪽 가장자리에 닿으면 왼쪽으로 뒤집는다 — 카드가 잘리지 않는다', () => {
    open({ anchor: { left: 960, top: 100, size: 22 } })
    // 960 + 22 + 10 + 240 > 1000 이므로 왼쪽: 960 - 10 - 240 = 710
    expect(styleOf()).toContain('left: 710px')
  })

  it('좌측 패널과 겹치면 패널 바깥으로 민다 — 카드가 패널 밑으로 숨지 않는다', () => {
    open({ anchor: { left: 40, top: 100, size: 22 }, panelRight: 300 })
    expect(styleOf()).toContain('left: 310px')
  })

  it('아래 가장자리에 닿으면 위로 올린다', () => {
    open({ anchor: { left: 100, top: 560, size: 22 } })
    // 600 - 190 - 10 = 400
    expect(styleOf()).toContain('top: 400px')
  })
})
