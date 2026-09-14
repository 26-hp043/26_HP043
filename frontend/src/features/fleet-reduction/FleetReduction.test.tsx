// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { FleetReduction } from './FleetReduction'
import { FLEET_REDUCTION_COPY } from './copy'
import type { EvaluateRequest, EvaluateResult, FleetReductionProvider } from './types'

/**
 * 함대 감축 계획 화면 (`UIFLOW 2-10` · #513).
 *
 * 계산은 서버 검사가 잠근다. 여기서는 ⑴ **조작이 요청에 실리는가** ⑵ **빈 단가를 0으로 보이지
 * 않는가** ⑶ 상태 분기·결정론 안내·등급 전이가 보이는가를 본다.
 */

function result(overrides: Partial<EvaluateResult> = {}): EvaluateResult {
  return {
    regulationYear: 2026,
    target: 'NO_AT_RISK',
    targetMet: false,
    vessels: [
      {
        vesselId: 'v1',
        vesselName: 'MV One',
        unavailableReason: null,
        before: { attainedCii: '8.9711', rating: 'E' },
        after: { attainedCii: '7.1000', rating: 'D' },
        targetRating: 'D',
        meetsTarget: true,
        extraDays: '1.52',
        fuelSavedTon: '125.78',
        skippedVoyages: 0,
        requiredCutFuelTon: '0.00',
        achievable: true,
      },
      {
        vesselId: 'v2',
        vesselName: 'MV Empty',
        unavailableReason: 'NO_DATA',
        before: null,
        after: null,
        targetRating: null,
        meetsTarget: null,
        extraDays: null,
        fuelSavedTon: null,
        skippedVoyages: 0,
        requiredCutFuelTon: null,
        achievable: null,
      },
    ],
    distribution: {
      before: { A: 0, B: 0, C: 0, D: 0, E: 1 },
      after: { A: 0, B: 0, C: 0, D: 1, E: 0 },
    },
    costs: {
      extraDays: '1.52',
      charterLoss: null,
      fuelSaving: '75468.00',
      net: null,
      missingCharterRates: ['v1'],
      missingFuelPrices: [],
    },
    warnings: [],
    ...overrides,
  }
}

function renderWith(evaluated: EvaluateResult = result()) {
  // 연도·연료 목록은 실 fetch를 탄다 — 여기서는 실패시켜 서버 기본(올해)으로 부르게 둔다.
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
  const provider = {
    evaluate: vi.fn(async (_req: EvaluateRequest) => evaluated),
    save: vi.fn(),
    list: vi.fn(async () => []),
  } satisfies FleetReductionProvider
  render(
    <MemoryRouter>
      <FleetReduction provider={provider} />
    </MemoryRouter>,
  )
  return provider
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('함대 감축 계획 화면 (#513)', () => {
  it('결정론 안내를 항상 보인다 — 연간 등급 관리와 달라 보이는 이유(`PRD §6.3`)', async () => {
    renderWith()

    expect(screen.getByText(FLEET_REDUCTION_COPY.deterministicNotice)).toBeTruthy()
    expect(await screen.findByText('MV One')).toBeTruthy()
  })

  it('⚠️ 슬라이더를 움직이면 그 감속률로 다시 묻는다', async () => {
    const provider = renderWith()
    const slider = await screen.findByLabelText('MV One 감속률')

    fireEvent.change(slider, { target: { value: '12.5' } })

    await waitFor(() => {
      const last = provider.evaluate.mock.calls.at(-1)?.[0]
      expect(last?.adjustments).toContainEqual({ vesselId: 'v1', percent: 12.5 })
    })
  })

  it('⚠️ 단가가 없는 비용 칸은 0이 아니라 「단가 입력 필요」다', async () => {
    renderWith()

    expect(await screen.findAllByText(FLEET_REDUCTION_COPY.needsPrice)).toHaveLength(2)
    expect(screen.getByText('75,468 USD')).toBeTruthy()
  })

  it('등급이 바뀌면 전이를 그리고(`DESIGN_SYSTEM §8.3`), 계산 못 한 선박은 사유와 비활성 슬라이더', async () => {
    renderWith()

    expect(await screen.findByLabelText('조정 전 E, 조정 후 D')).toBeTruthy()
    expect(screen.getByText('올해 계산할 항차 없음')).toBeTruthy()
    expect((screen.getByLabelText('MV Empty 감속률') as HTMLInputElement).disabled).toBe(true)
  })

  it('상태 분기 — 감속 전 미달은 「움직이면 계산된다」, 달성은 「달성」', async () => {
    renderWith()
    expect(await screen.findByText(new RegExp(FLEET_REDUCTION_COPY.statusIdle))).toBeTruthy()

    vi.unstubAllGlobals()
    document.body.innerHTML = ''
    renderWith(result({ targetMet: true }))
    expect(await screen.findByText(new RegExp(FLEET_REDUCTION_COPY.statusMet))).toBeTruthy()
  })

  it('저장 버튼은 이름을 넣어야 켜진다', async () => {
    renderWith()
    const button = (await screen.findByRole('button', { name: FLEET_REDUCTION_COPY.saveButton })) as HTMLButtonElement
    expect(button.disabled).toBe(true)

    await act(async () => {
      fireEvent.change(screen.getByLabelText(FLEET_REDUCTION_COPY.planNameLabel), {
        target: { value: '9월안' },
      })
    })
    expect(button.disabled).toBe(false)
  })
})

/**
 * 오류 경로 (#1069) — 실패 한 번에 입력 칸까지 사라지면 **고칠 곳이 없어** 새로고침 말고는 빠져나올 수 없다.
 */
describe('함대 감축 계획 화면 — 실패해도 빠져나올 수 있다 (#1069)', () => {
  function renderProvider(provider: FleetReductionProvider) {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    render(
      <MemoryRouter>
        <FleetReduction provider={provider} />
      </MemoryRouter>,
    )
  }

  it('⚠️ 음수 단가는 서버에 묻지 않고 그 칸에 오류를 보인다 — 고치면 다시 계산한다', async () => {
    const evaluate = vi.fn(async (_req: EvaluateRequest) => result())
    renderProvider({ evaluate, save: vi.fn(), list: vi.fn(async () => []) })
    const charter = await screen.findByLabelText('MV One 일일 용선료 (USD)')
    await waitFor(() => expect(evaluate).toHaveBeenCalled())
    const before = evaluate.mock.calls.length

    await act(async () => {
      fireEvent.change(charter, { target: { value: '-5' } })
    })
    expect(await screen.findByText(FLEET_REDUCTION_COPY.priceInvalid)).toBeTruthy()
    expect(charter.getAttribute('aria-invalid')).toBe('true')
    // 칸이 사라지지 않았고, 음수로는 요청하지 않았다.
    await new Promise((r) => setTimeout(r, 400))
    expect(evaluate.mock.calls.length).toBe(before)
    expect(screen.getByText('MV One')).toBeTruthy()
    fireEvent.change(screen.getByLabelText(FLEET_REDUCTION_COPY.planNameLabel), {
      target: { value: '9월안' },
    })
    const saveButton = screen.getByRole('button', { name: FLEET_REDUCTION_COPY.saveButton })
    expect((saveButton as HTMLButtonElement).disabled).toBe(true)

    await act(async () => {
      fireEvent.change(charter, { target: { value: '12000' } })
    })
    await waitFor(() => {
      const last = evaluate.mock.calls.at(-1)?.[0]
      expect(last?.prices.charterUsdPerDay).toEqual({ v1: '12000' })
    })
    expect(screen.queryByText(FLEET_REDUCTION_COPY.priceInvalid)).toBeNull()
  })

  it('⚠️ 계산이 실패해도 마지막 결과와 입력 칸이 남고, 그 사실을 적고, 다시 시도할 수 있다', async () => {
    let fail = false
    const evaluate = vi.fn(async (_req: EvaluateRequest) => {
      if (fail) throw new Error('일시적인 오류입니다.')
      return result()
    })
    renderProvider({ evaluate, save: vi.fn(), list: vi.fn(async () => []) })
    const slider = await screen.findByLabelText('MV One 감속률')

    fail = true
    fireEvent.change(slider, { target: { value: '10' } })
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('일시적인 오류입니다.')
    expect(alert.textContent).toContain(FLEET_REDUCTION_COPY.staleResult)
    expect(screen.getByLabelText('MV One 감속률')).toBeTruthy()

    fail = false
    const calls = evaluate.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await waitFor(() => expect(evaluate.mock.calls.length).toBeGreaterThan(calls))
    await waitFor(() => expect(screen.queryByText(/일시적인 오류입니다/)).toBeNull())
  })

  it('처음부터 실패하면 오류와 재시도만 — 대체 문구는 진행 문구가 아니라 실패 문구다', async () => {
    let fail = true
    const evaluate = vi.fn(async (_req: EvaluateRequest) => {
      if (fail) throw 'not an Error'
      return result()
    })
    renderProvider({ evaluate, save: vi.fn(), list: vi.fn(async () => []) })

    expect(await screen.findByText(FLEET_REDUCTION_COPY.evaluateFailed)).toBeTruthy()
    expect(screen.queryByText(FLEET_REDUCTION_COPY.loading)).toBeNull()

    fail = false
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText('MV One')).toBeTruthy()
  })

  it('⚠️ 계획 목록을 못 받으면 「저장한 계획이 없습니다」가 아니라 실패를 보인다', async () => {
    let fail = true
    const list = vi.fn(async () => {
      if (fail) throw new Error('down')
      return []
    })
    renderProvider({ evaluate: vi.fn(async () => result()), save: vi.fn(), list })

    expect(await screen.findByText(FLEET_REDUCTION_COPY.plansFailed)).toBeTruthy()
    expect(screen.queryByText(FLEET_REDUCTION_COPY.noPlans)).toBeNull()

    fail = false
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText(FLEET_REDUCTION_COPY.noPlans)).toBeTruthy()
  })

  it('저장이 서버 문구 없이 실패하면 「저장하는 중」이 아니라 실패 문구다', async () => {
    const save = vi.fn(async () => {
      throw 'boom'
    })
    renderProvider({ evaluate: vi.fn(async () => result()), save, list: vi.fn(async () => []) })
    await screen.findByText('MV One')
    await act(async () => {
      fireEvent.change(screen.getByLabelText(FLEET_REDUCTION_COPY.planNameLabel), {
        target: { value: '9월안' },
      })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: FLEET_REDUCTION_COPY.saveButton }))
    })
    expect(await screen.findByText(FLEET_REDUCTION_COPY.saveFailed)).toBeTruthy()
  })
})

