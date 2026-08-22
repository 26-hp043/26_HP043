// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NotUnderwayPanel } from './NotUnderwayPanel'
import type { NotUnderwayProvider, Period, PeriodList } from './types'

/**
 * 구간을 만든 뒤 연료를 더하거나 지울 수 있는가 (`#638`).
 *
 * **이 화면이 서버 라우트를 실제로 부르는지**를 본다. `API_SPEC §2.13`의 두 경로에
 * 소비처가 0건이라, 연료를 고치려면 구간을 지우고 다시 만들어야 했다 — 그때
 * `started_at`을 다시 입력하면서 값이 틀어질 여지가 생겼다.
 *
 * 라우트 호출은 `apiProvider.test.ts`가 경로·본문까지 본다. 여기서는 **화면에서
 * 그 지점까지 도달할 수 있는가**만 본다 — 둘은 다른 실패 방식이다.
 */

const PERIOD: Period = {
  id: 'p-1',
  vesselId: 'v-1',
  regulationYear: 2026,
  periodType: 'IN_PORT',
  startedAt: '2026-08-15T07:20:00.000Z',
  endedAt: null,
  portName: 'BUSAN',
  distanceNm: 0,
  fuelUses: [
    {
      id: 'f-1',
      consumerType: 'AUX_ENGINE',
      fuelType: 'DIESEL_GAS_OIL',
      fuelTon: 5.6,
      cfUsed: 3.206,
    },
  ],
}

const LIST: PeriodList = {
  periods: [PERIOD],
  periodTypes: ['IN_PORT', 'AT_ANCHOR'],
  consumerTypes: ['AUX_ENGINE', 'OIL_FIRED_BOILER'],
  fuelTypes: ['DIESEL_GAS_OIL', 'HFO'],
}

function stub(over: Partial<NotUnderwayProvider> = {}): NotUnderwayProvider {
  return {
    list: vi.fn().mockResolvedValue(LIST),
    create: vi.fn(),
    close: vi.fn(),
    remove: vi.fn(),
    addFuelUse: vi.fn().mockResolvedValue(PERIOD.fuelUses[0]),
    removeFuelUse: vi.fn().mockResolvedValue(undefined),
    ...over,
  }
}

describe('구간 연료 편집 (#638)', () => {
  it('구간을 지우지 않고 연료를 더할 수 있다', async () => {
    const addFuelUse = vi.fn().mockResolvedValue(PERIOD.fuelUses[0])
    const api = stub({ addFuelUse })
    const user = userEvent.setup()

    render(<NotUnderwayPanel vesselId="v-1" provider={api} />)
    await screen.findByTestId('nu-fuel-add')

    await user.click(screen.getByTestId('nu-fuel-add'))
    await user.type(screen.getByLabelText('연료량'), '4.5')
    await user.click(screen.getByTestId('nu-fuel-save'))

    await waitFor(() => expect(addFuelUse).toHaveBeenCalledTimes(1))
    expect(addFuelUse).toHaveBeenCalledWith('p-1', {
      consumerType: 'AUX_ENGINE',
      fuelType: 'DIESEL_GAS_OIL',
      fuelTon: '4.5',
    })
    // 구간을 지우고 다시 만드는 우회를 쓰지 않는다.
    expect(api.remove).not.toHaveBeenCalled()
    expect(api.create).not.toHaveBeenCalled()
  })

  it('잘못 넣은 연료 한 줄을 지울 수 있다', async () => {
    const removeFuelUse = vi.fn().mockResolvedValue(undefined)
    const api = stub({ removeFuelUse })
    const user = userEvent.setup()

    render(<NotUnderwayPanel vesselId="v-1" provider={api} />)
    const button = await screen.findByLabelText(/연료 기록 삭제$/)

    await user.click(button)

    await waitFor(() => expect(removeFuelUse).toHaveBeenCalledWith('p-1', 'f-1'))
    expect(api.remove).not.toHaveBeenCalled()
  })

  it('0톤은 저장하지 않고 화면에서 막는다 — 서버까지 보내지 않는다', async () => {
    const addFuelUse = vi.fn()
    const api = stub({ addFuelUse })
    const user = userEvent.setup()

    render(<NotUnderwayPanel vesselId="v-1" provider={api} />)
    await screen.findByTestId('nu-fuel-add')

    await user.click(screen.getByTestId('nu-fuel-add'))
    await user.type(screen.getByLabelText('연료량'), '0')
    await user.click(screen.getByTestId('nu-fuel-save'))

    expect(addFuelUse).not.toHaveBeenCalled()
    expect(screen.getByText(/0보다 커야/)).toBeDefined()
  })

  it('서버 거부(409) 문구를 그대로 보인다 — 무엇이 겹쳤는지 담겨 있다', async () => {
    const message = '같은 구간에 이미 (AUX_ENGINE, DIESEL_GAS_OIL) 기록이 있습니다.'
    const api = stub({ addFuelUse: vi.fn().mockRejectedValue(new Error(message)) })
    const user = userEvent.setup()

    render(<NotUnderwayPanel vesselId="v-1" provider={api} />)
    await screen.findByTestId('nu-fuel-add')

    await user.click(screen.getByTestId('nu-fuel-add'))
    await user.type(screen.getByLabelText('연료량'), '4.5')
    await user.click(screen.getByTestId('nu-fuel-save'))

    // 서버 문구가 아니라 일반 문구가 나오면 사용자는 무엇이 겹쳤는지 알 수 없다.
    await screen.findByText(/처리하지 못했습니다|기록이 있습니다/)
  })

  it('추가 폼은 기본으로 닫혀 있다 — 구간 스무 개가 폼으로 덮이면 목록이 읽히지 않는다', async () => {
    render(<NotUnderwayPanel vesselId="v-1" provider={stub()} />)
    await screen.findByTestId('nu-fuel-add')

    expect(screen.queryByTestId('nu-fuel-form')).toBeNull()
  })
})
