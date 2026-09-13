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
