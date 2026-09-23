// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { DISPLAY_UNITS } from '../../display/format'
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
/**
 * 선박명이 한 줄로 고정된다 (`#1427`).
 *
 * 종전에는 「샘플 로로 여객선 (25,000 GT)」 같은 이름이 넉 줄로 꺾여 행 높이가
 * 들쭉날쭉했다 — 감속률 슬라이더가 행마다 다른 높이에 놓여 세로로 훑기가 어려웠다.
 *
 * **CSS는 jsdom에서 계산되지 않으므로 「보이는 줄 수」를 잴 수 없다.** 대신 그 규격을
 * 지는 자리(전용 클래스)가 이름 칸에 붙어 있는지와, **잘려도 이름을 잃지 않는지**를
 * 본다 — 접근성 이름은 전체 텍스트이고, `title`이 마우스 보조로 같은 값을 든다.
 */
describe('선박명은 한 줄로 고정된다 (#1427)', () => {
  const LONG = '샘플 로로 여객선 (25,000 GT)'

  it('이름 칸이 한 줄 규격을 지는 클래스를 갖는다', async () => {
    renderWith(result({ vessels: [{ ...result().vessels[0], vesselName: LONG }] }))

    const link = await screen.findByRole('link', { name: LONG })
    const cell = link.closest('th')
    expect(cell).not.toBeNull()
    expect(cell!.className).toContain('fr__vessel')
  })

  it('잘려도 이름을 잃지 않는다 — 접근성 이름과 title이 전체 이름이다', async () => {
    renderWith(result({ vessels: [{ ...result().vessels[0], vesselName: LONG }] }))

    const link = await screen.findByRole('link', { name: LONG })
    /*
     * 말줄임은 **그리기**일 뿐 DOM을 자르지 않는다 — 낭독은 계속 전체 이름을 읽는다.
     * `title`은 그 위에 얹는 마우스 보조다(`#1424`와 달리 여기 담긴 것이 다른 데
     * 없는 정보가 아니다).
     */
    expect(link.textContent).toBe(LONG)
    expect(link.getAttribute('title')).toBe(LONG)
  })
})

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


/**
 * 연료 단가 칸의 범위 (#1273).
 *
 * 종전에는 **서버 연료 목록 8종 전체**에 `missingFuelPrices`를 더해 물었다 — 보유 선박이
 * 쓰지도 않는 연료까지 칸이 떴다. 서버가 이미 「이 계획에 필요한데 없는 연료」를 지목하므로
 * 그것으로 좁힌다.
 */
describe('연료 단가는 이 계획에 필요한 연료만 묻는다 (#1273)', () => {
  function withMissingFuels(codes: string[]): EvaluateResult {
    const base = result()
    return { ...base, costs: { ...base.costs, missingFuelPrices: codes } }
  }

  it('⚠️ 서버가 지목한 연료만 뜬다 — 8종 전체가 아니다', async () => {
    renderWith(withMissingFuels(['HFO']))

    // 표시 문구는 `fuelTypes.ts`가 갖는다 — 서버 `displayName`(원문 표기)이 아니다(`#598`).
    expect(await screen.findByLabelText('중유 (HFO)')).toBeTruthy()
    expect(screen.queryByLabelText('메탄올 (METHANOL)')).toBeNull()
    expect(screen.queryByLabelText('액화천연가스 (LNG)')).toBeNull()
  })

  it('필요한 단가가 없으면 칸 대신 그 사실을 적는다 — 빈 카드로 두지 않는다', async () => {
    renderWith(withMissingFuels([]))

    expect(await screen.findByText(FLEET_REDUCTION_COPY.fuelPricesNone)).toBeTruthy()
  })

  it('⚠️ 값을 넣어도 칸이 사라지지 않는다 — 채우는 순간 missingFuelPrices에서 빠진다', async () => {
    let missing = ['HFO']
    const evaluate = vi.fn(async (_req: EvaluateRequest) => withMissingFuels(missing))
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    render(
      <MemoryRouter>
        <FleetReduction provider={{ evaluate, save: vi.fn(), list: vi.fn(async () => []) }} />
      </MemoryRouter>,
    )

    const field = await screen.findByLabelText('중유 (HFO)')
    missing = []
    await act(async () => {
      fireEvent.change(field, { target: { value: '620' } })
    })

    await waitFor(() => {
      const last = evaluate.mock.calls.at(-1)?.[0]
      expect(last?.prices.fuelUsdPerTon).toEqual({ HFO: '620' })
    })
    expect(screen.getByLabelText('중유 (HFO)')).toBeTruthy()
    expect(screen.queryByText(FLEET_REDUCTION_COPY.fuelPricesNone)).toBeNull()
  })
})

/*
 * 결론 띠 · 전폭 표 (#1757).
 *
 * 이 화면의 답은 「목표를 몇 척이 달성하는가」 하나인데 종전에는 오른쪽 기둥 맨 위의
 * 한 줄짜리 상태 문장이었다. 여기서 보는 것은: 척수가 맞게 세어지는가(계산 못 한 선박을
 * 실패로 세지 않는가), 위험도 pill을 두지 않는가, 오른쪽 기둥이 없어졌는가.
 */
describe('결론 띠 — DESIGN_SYSTEM §8.6 (#1757)', () => {
  const strip = () => document.querySelector('.verdict-strip') as HTMLElement

  it('주 결론은 목표 달성 척수다 — 계산 못 한 선박은 분모에도 넣지 않는다', async () => {
    renderWith()
    await screen.findByText('MV One')

    /* 고정표: 계산 가능 1척(v1 · 달성) + 계산 불가 1척(v2). 「1 / 2」가 아니라 「1 / 1」이다. */
    expect(strip().textContent).toContain('1 / 1')
    expect(strip().textContent).toContain('척')
  })

  it('계산할 수 있는 선박이 0척이면 척수를 지어내지 않는다', async () => {
    renderWith(
      result({
        targetMet: null,
        vessels: [
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
      }),
    )
    await screen.findByText('MV Empty')

    expect(strip().textContent).toContain('—')
    expect(strip().textContent).not.toContain('0 / 0')
    /* 상태 문장은 `<strong>목표</strong> — 문구` 꼴이라 텍스트가 두 노드로 갈린다. */
    expect(document.querySelector('.fr__status')?.textContent).toContain(
      FLEET_REDUCTION_COPY.statusNoVessel,
    )
  })

  it('⚠️ 보조는 순손익이고, 단가가 비면 0이 아니라 「단가 입력 필요」다 (PRD §12.3.2)', async () => {
    renderWith()
    await screen.findByText('MV One')

    expect(strip().textContent).toContain(FLEET_REDUCTION_COPY.net)
    expect(strip().textContent).toContain(FLEET_REDUCTION_COPY.needsPrice)
  })

  it('위험도 pill을 두지 않는다 — 이 화면의 데이터에 위험도 값이 없다 (§8.6 v2.23)', async () => {
    renderWith()
    await screen.findByText('MV One')

    expect(document.querySelector('.verdict-strip__risk')).toBeNull()
  })

  it('나머지 비용 셋은 띠 아래 2열 목록이다 — 카드로 감싸지 않는다 (§8.6)', async () => {
    renderWith()
    await screen.findByText('MV One')

    const costs = document.querySelector('.fr__costs') as HTMLElement
    expect(costs.tagName).toBe('DL')
    expect(costs.closest('.card')).toBeNull()
    expect(costs.textContent).toContain(FLEET_REDUCTION_COPY.extraDays)
    expect(costs.textContent).toContain(FLEET_REDUCTION_COPY.charterLoss)
    expect(costs.textContent).toContain(FLEET_REDUCTION_COPY.fuelSaving)
    /* 순손익은 띠로 올라갔다 — 같은 값을 두 번 적지 않는다. */
    expect(costs.textContent).not.toContain(FLEET_REDUCTION_COPY.net)
  })

  it('표는 전폭이다 — 오른쪽 기둥이 없다', async () => {
    renderWith()
    await screen.findByText('MV One')

    expect(document.querySelector('.fr__grid')).toBeNull()
    expect(document.querySelector('.fr__side')).toBeNull()
    const card = document.querySelector('.fr__table-card') as HTMLElement
    expect(card.querySelector('table')).not.toBeNull()
    expect(card.querySelector('.card__title')?.textContent).toBe(FLEET_REDUCTION_COPY.vesselsTitle)
  })
})

/*
 * 도구 줄 (#1757) — 연료 단가 · 계획 저장을 표 위 한 줄로 접었다. 접어 두는 대가로
 * 「안에 값이 있는지」를 겉에서 알 수 있어야 한다(`#1417`과 같은 판단).
 */
describe('도구 줄 — 연료 단가 · 계획 저장 (#1757)', () => {
  const toolByName = (name: RegExp) =>
    (screen.getByText(name).closest('details') as HTMLDetailsElement)

  it('연료 단가는 접혀 있고, 채운 칸 수를 겉에서 말한다', async () => {
    renderWith(
      result({
        costs: { ...result().costs, missingFuelPrices: ['HFO', 'MGO'] },
      }),
    )
    await screen.findByText('MV One')

    const prices = toolByName(/연료 단가/)
    expect(prices.open).toBe(false)
    expect(prices.querySelector('summary')?.textContent).toContain('0 / 2 입력함')

    fireEvent.change(await screen.findByLabelText('중유 (HFO)'), { target: { value: '600' } })
    expect(prices.querySelector('summary')?.textContent).toContain('1 / 2 입력함')
  })

  it('단가가 잘못되면 스스로 펼친다 — 접힌 채로는 오류가 보이지 않는다', async () => {
    renderWith(
      result({
        costs: { ...result().costs, missingFuelPrices: ['HFO'] },
      }),
    )
    await screen.findByText('MV One')

    const prices = toolByName(/연료 단가/)
    expect(prices.open).toBe(false)
    fireEvent.change(await screen.findByLabelText('중유 (HFO)'), { target: { value: '-1' } })

    await waitFor(() => expect(prices.open).toBe(true))
    expect(screen.getByText(FLEET_REDUCTION_COPY.priceInvalid)).toBeTruthy()
  })

  it('계획 저장도 접기 안이지만 잠긴 사유는 그대로 이어진다 (§14 · #1170 ⑵)', async () => {
    renderWith(
      result({
        costs: { ...result().costs, missingFuelPrices: ['HFO'] },
      }),
    )
    await screen.findByText('MV One')

    fireEvent.change(await screen.findByLabelText('중유 (HFO)'), { target: { value: '-1' } })
    fireEvent.change(screen.getByLabelText(FLEET_REDUCTION_COPY.planNameLabel), {
      target: { value: '9월 계획' },
    })

    const save = screen.getByRole('button', { name: FLEET_REDUCTION_COPY.saveButton })
    expect(save.getAttribute('aria-describedby')).toBe('fr-save-blocked')
    expect(document.getElementById('fr-save-blocked')?.textContent).toBe(
      FLEET_REDUCTION_COPY.saveBlockedByPrice,
    )
  })
})

/**
 * 수치·단위 표시 (`DESIGN_SYSTEM §4.2` · #1813).
 *
 * `extraDays`는 API가 `"1.52"`처럼 소수 문자열로 준다(`API_SPEC §2.17`). 종전에는 그대로 `…일`로
 * 이어 붙여 소수가 나갔고, 단위 `일`·`t`가 리터럴이었다. 규정은 일수 0자리 · 연료 1자리+천단위 ·
 * 단위는 `DISPLAY_UNITS`다. 표시 반올림이므로 값 자체(`'1.52'`)는 그대로 둔다(`§4.2` 「반올림 🔒」).
 */
describe('수치·단위 표시 (§4.2 · #1813)', () => {
  function vesselCells(): string[] {
    const row = screen.getByText('MV One').closest('tr') as HTMLTableRowElement
    return [...row.querySelectorAll('td.fr__num')].map((cell) => cell.textContent?.trim() ?? '')
  }

  it('추가 항해일은 소수 없이 「n일」이고 단위는 DISPLAY_UNITS.day다', async () => {
    renderWith()
    await screen.findByText('MV One')

    const costs = document.querySelector('.fr__costs dd.fr__num') as HTMLElement
    const [rowDays] = vesselCells()
    for (const text of [costs.textContent?.trim() ?? '', rowDays]) {
      expect(text.endsWith(DISPLAY_UNITS.day)).toBe(true)
      expect(text.slice(0, -DISPLAY_UNITS.day.length)).toMatch(/^\d+$/)
    }
    /* 절사가 아니라 반올림이다 — `1.52`는 `1`이 아니다. */
    expect(rowDays.slice(0, -DISPLAY_UNITS.day.length)).not.toBe('1')
  })

  it('연료 절감은 1자리 + 천단위 구분이고 단위는 DISPLAY_UNITS.fuel이다', async () => {
    const base = result()
    renderWith(
      result({
        vessels: base.vessels.map((vessel) =>
          vessel.vesselId === 'v1' ? { ...vessel, fuelSavedTon: '12345.67' } : vessel,
        ),
      }),
    )
    await screen.findByText('MV One')

    const [, fuel] = vesselCells()
    expect(fuel.endsWith(DISPLAY_UNITS.fuel)).toBe(true)
    expect(fuel.slice(0, -DISPLAY_UNITS.fuel.length)).toMatch(/^\d{1,3}(,\d{3})+\.\d$/)
  })

  it('값이 없으면 단위도 붙이지 않는다', async () => {
    renderWith()
    await screen.findByText('MV Empty')

    const row = screen.getByText('MV Empty').closest('tr') as HTMLTableRowElement
    const cells = [...row.querySelectorAll('td.fr__num')].map((cell) => cell.textContent?.trim())
    expect(cells).toEqual(['—', '—'])
  })
})
