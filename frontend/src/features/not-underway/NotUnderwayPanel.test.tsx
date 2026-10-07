// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
    // 확인 줄을 거친다 (#2130) — 아래 「지우기 전에 한 번 더 묻는다」가 그 규칙을 본다.
    await user.click(screen.getByTestId('nu-caution-confirm'))

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


describe('바뀌면 부모에게 알린다 (#1648)', () => {
  it('연료를 더하면 onChanged를 부른다 — 누적 CII가 바뀌기 때문이다', async () => {
    const onChanged = vi.fn()
    const user = userEvent.setup()
    render(<NotUnderwayPanel vesselId="v-1" provider={stub()} onChanged={onChanged} />)
    await screen.findByTestId('nu-fuel-add')

    await user.click(screen.getByTestId('nu-fuel-add'))
    await user.type(screen.getByLabelText('연료량'), '4.5')
    await user.click(screen.getByTestId('nu-fuel-save'))

    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('실패하면 부르지 않는다 — 바뀌지 않은 데이터를 다시 부르지 않는다', async () => {
    const onChanged = vi.fn()
    const addFuelUse = vi.fn().mockRejectedValue(new Error('거부됨'))
    const user = userEvent.setup()
    render(
      <NotUnderwayPanel vesselId="v-1" provider={stub({ addFuelUse })} onChanged={onChanged} />,
    )
    await screen.findByTestId('nu-fuel-add')

    await user.click(screen.getByTestId('nu-fuel-add'))
    await user.type(screen.getByLabelText('연료량'), '4.5')
    await user.click(screen.getByTestId('nu-fuel-save'))

    await waitFor(() => expect(addFuelUse).toHaveBeenCalled())
    expect(onChanged).not.toHaveBeenCalled()
  })
})

describe('지우기 전에 한 번 더 묻는다 (#2130 · 전수검수 D-11)', () => {
  /*
   * 구간 삭제와 연료 한 줄 삭제는 누적 CII의 분자·분모를 바꾸고 화면에서 되돌릴 길이 없다.
   * 항차 카드의 확인 줄(`VoyagePanel` · `#1598`)과 같은 규칙을 본다 — 첫 누름은 지우지 않고,
   * 줄에는 그 값이 적히며, 초점은 「그만두기」에 먼저 간다.
   * 문구는 리터럴로 묻지 않는다(`AGENTS §4.6` 표시 문구) — 값이 실리는지만 본다.
   */
  it('연료 한 줄 — 첫 누름은 지우지 않고, 그 줄의 양을 적은 확인 줄을 연다', async () => {
    const removeFuelUse = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<NotUnderwayPanel vesselId="v-1" provider={stub({ removeFuelUse })} />)

    const trigger = await screen.findByLabelText(/연료 기록 삭제$/)
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    await user.click(trigger)

    expect(removeFuelUse).not.toHaveBeenCalled()
    const group = screen.getByRole('group')
    expect(group.textContent).toContain('5.6')
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    // 안전한 쪽에 초점 — Enter를 한 번 더 눌러 실행되지 않게.
    expect(document.activeElement).toBe(within(group).getByTestId('nu-caution-keep'))

    await user.click(within(group).getByTestId('nu-caution-confirm'))
    await waitFor(() => expect(removeFuelUse).toHaveBeenCalledWith('p-1', 'f-1'))
    expect(screen.queryByRole('group')).toBeNull()
  })

  it('구간 — 첫 누름은 지우지 않고, 「그만두기」는 아무것도 지우지 않고 초점을 돌려준다', async () => {
    const remove = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<NotUnderwayPanel vesselId="v-1" provider={stub({ remove })} />)

    const trigger = await screen.findByTestId('nu-remove')
    await user.click(trigger)
    expect(remove).not.toHaveBeenCalled()
    expect(screen.getByRole('group').textContent).toContain('5.6')

    await user.click(screen.getByTestId('nu-caution-keep'))
    expect(screen.queryByRole('group')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(remove).not.toHaveBeenCalled()

    // Escape도 「그만두기」다.
    await user.click(trigger)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('group')).toBeNull()
    expect(remove).not.toHaveBeenCalled()

    await user.click(trigger)
    await user.click(screen.getByTestId('nu-caution-confirm'))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('p-1'))
  })

  it('한 행에 확인 줄은 하나다 — 두 「삭제하기」가 함께 서 있으면 무엇을 지우는지 읽히지 않는다', async () => {
    const user = userEvent.setup()
    render(<NotUnderwayPanel vesselId="v-1" provider={stub()} />)

    await user.click(await screen.findByLabelText(/연료 기록 삭제$/))
    await user.click(screen.getByTestId('nu-remove'))

    expect(screen.getAllByRole('group')).toHaveLength(1)
    expect(screen.getByTestId('nu-remove').getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByLabelText(/연료 기록 삭제$/).getAttribute('aria-expanded')).toBe('false')
  })
})

describe('접안·묘박은 거리 칸을 잠근다 (#2130 · 전수검수 D-11)', () => {
  const CHOICES: PeriodList = {
    ...LIST,
    periods: [],
    periodTypes: ['IN_PORT', 'CANAL_TRANSIT', 'AT_ANCHOR'],
  }

  it('잠긴 유형은 칸이 비활성이고 0을 보낸다 — 적어 둔 값은 거리가 있는 유형에서 다시 보인다', async () => {
    const create = vi.fn().mockResolvedValue(PERIOD)
    const api = stub({ list: vi.fn().mockResolvedValue(CHOICES), create })
    const user = userEvent.setup()
    render(<NotUnderwayPanel vesselId="v-1" provider={api} />)

    await user.click(await screen.findByTestId('nu-toggle'))
    const distance = () => screen.getByTestId('nu-distance') as HTMLInputElement
    const periodType = screen.getByTestId('nu-period-type') as HTMLSelectElement

    // 첫 유형(접안)이 기본값이다 — 처음부터 잠겨 있다.
    expect(distance().disabled).toBe(true)
    expect(distance().value).toBe('0')

    await user.selectOptions(periodType, 'CANAL_TRANSIT')
    expect(distance().disabled).toBe(false)
    await user.clear(distance())
    await user.type(distance(), '12')

    await user.selectOptions(periodType, 'AT_ANCHOR')
    expect(distance().disabled).toBe(true)
    expect(distance().value).toBe('0')

    // 거리가 있는 유형으로 돌아가면 적어 둔 값이 남아 있다 — 잠금이 입력을 지우지 않는다.
    await user.selectOptions(periodType, 'CANAL_TRANSIT')
    expect(distance().value).toBe('12')
    await user.selectOptions(periodType, 'AT_ANCHOR')

    fireEvent.change(screen.getByTestId('nu-started-at'), {
      target: { value: '2026-08-10T09:00' },
    })
    await user.click(screen.getByTestId('nu-submit'))

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    // 화면에 12가 적혀 있었어도 잠긴 유형이면 0을 보낸다 — 서버는 0이 아니면 422다.
    expect(create.mock.calls[0][1]).toMatchObject({ periodType: 'AT_ANCHOR', distanceNm: '0' })
  })

  it('거리가 있는 유형은 적은 값을 그대로 보낸다', async () => {
    const create = vi.fn().mockResolvedValue(PERIOD)
    const api = stub({ list: vi.fn().mockResolvedValue(CHOICES), create })
    const user = userEvent.setup()
    render(<NotUnderwayPanel vesselId="v-1" provider={api} />)

    await user.click(await screen.findByTestId('nu-toggle'))
    await user.selectOptions(screen.getByTestId('nu-period-type'), 'CANAL_TRANSIT')
    const distance = screen.getByTestId('nu-distance') as HTMLInputElement
    await user.clear(distance)
    await user.type(distance, '12')
    fireEvent.change(screen.getByTestId('nu-started-at'), {
      target: { value: '2026-08-10T09:00' },
    })
    await user.click(screen.getByTestId('nu-submit'))

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(create.mock.calls[0][1]).toMatchObject({ periodType: 'CANAL_TRANSIT', distanceNm: '12' })
  })
})
