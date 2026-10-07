// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { DISPLAY_UNITS, formatTimestamp } from '../../display/format'
import { FleetReduction } from './FleetReduction'
import { FLEET_REDUCTION_COPY, TARGET_TEXT } from './copy'
import type {
  EvaluateRequest,
  EvaluateResult,
  FleetReductionProvider,
  SavedPlanSummary,
} from './types'

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
        isCiiApplicableHint: true,
        grossTonnage: 30000,
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
        isCiiApplicableHint: true,
        grossTonnage: 30000,
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

/**
 * 연도·연료 목록은 실 fetch를 탄다. 연도 목록은 정상으로 주고(올해 · 전해), 나머지는 500이다 —
 * 연도 조회 500은 정상 전제가 아니라 연도 칸 상태를 검사하는 별도 자리(#2120)에서만 쓴다.
 */
function stubCatalogs(yearsResponse: () => Response = okYears) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
    String(input).includes('/parameters/regulation-years') ? yearsResponse() : new Response('{}', { status: 500 }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function okYears() {
  const thisYear = new Date().getFullYear()
  return new Response(JSON.stringify({ data: [{ year: thisYear - 1 }, { year: thisYear }] }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderWith(evaluated: EvaluateResult = result()) {
  stubCatalogs()
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

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('함대 감축 계획 화면 (#513)', () => {
  /*
   * 10/7 디자인 결정(#2314) — 안내는 결과 맨 아래 한 줄로 옮겼다. 설명할 연말 등급이 있을 때
   * 서는 문장이라 결과와 함께 나온다. 문구는 정본(`PRD §6.3`) 원문 그대로 단언한다.
   */
  it('결과가 있으면 결정론 안내가 결과 맨 아래에 선다 — 연간 등급 관리와 달라 보이는 이유(`PRD §6.3`)', async () => {
    renderWith()

    expect(await screen.findByText('MV One')).toBeTruthy()
    const notice = screen.getByText(FLEET_REDUCTION_COPY.deterministicNotice)
    // 결과(표 카드)보다 뒤에 있다
    const table = document.querySelector('.fr__table-card') as HTMLElement
    expect(table.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
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

  /*
   * 10/7(#2314) — 「단가 입력 필요」 한 문장에서 **무엇이 빠졌는지**를 말하는 문장으로 바뀌었다.
   * 지키려던 것은 그대로다: 빈 비용은 0으로 보이지 않고, 입력이 필요하다고 말한다.
   */
  it('⚠️ 단가가 없는 비용 칸은 0이 아니라 무엇이 빠졌는지 말한다', async () => {
    renderWith()
    await screen.findByText('MV One')

    const hero = document.querySelector('.fr-hero') as HTMLElement
    // 고정표: 일일 용선료만 비었다(`missingCharterRates: ['v1']`) — 순손익과 용선료 손실이 빈다
    const net = hero.querySelector('.fr-hero__value') as HTMLElement
    expect(net.classList.contains('fr-hero__value--empty')).toBe(true)
    expect(net.textContent).toMatch(/용선료.*입력 필요/)
    expect(net.textContent).not.toMatch(/연료 단가/)
    expect(net.textContent).not.toMatch(/\d/)
    const charter = within(hero.querySelector('.fr-hero__breakdown') as HTMLElement)
      .getByText(FLEET_REDUCTION_COPY.charterLoss).closest('div') as HTMLElement
    expect(charter.querySelector('dd')?.textContent).toMatch(/용선료.*입력 필요/)
    expect(charter.querySelector('dd')?.textContent).not.toMatch(/\d/)
    // 단가가 있는 칸은 값이다
    expect(screen.getByText('75,468 USD')).toBeTruthy()
    // 빈 선박의 이름과 해당 칸으로 가는 버튼
    expect(hero.textContent).toContain('MV One')
    expect(within(hero).getByRole('button', { name: '용선료 입력' })).toBeTruthy()
  })

  it('연료 단가가 비면 「연료 단가 입력」이 연료 단가 접기를 연다', async () => {
    renderWith(result({ costs: { ...result().costs, missingCharterRates: [], missingFuelPrices: ['HFO'] } }))
    await screen.findByText('MV One')

    const hero = document.querySelector('.fr-hero') as HTMLElement
    expect(hero.querySelector('.fr-hero__value--empty')?.textContent).toMatch(/연료 단가.*입력 필요/)
    const prices = screen.getByText(new RegExp(escapeRegExp(FLEET_REDUCTION_COPY.fuelPricesTitle)))
      .closest('details') as HTMLDetailsElement
    expect(prices.open).toBe(false)
    fireEvent.click(within(hero).getByRole('button', { name: '연료 단가 입력' }))
    await waitFor(() => expect(prices.open).toBe(true))
  })

  it('순손익은 부호를 붙여 크게 적고, 환율을 넣으면 원화를 곁에 적어 이 브라우저에 기억한다', async () => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    })
    renderWith(result({ costs: { ...result().costs, charterLoss: '100000.00', net: '-24532.00', missingCharterRates: [] } }))
    await screen.findByText('MV One')

    const hero = document.querySelector('.fr-hero') as HTMLElement
    expect(hero.querySelector('.fr-hero__value')?.textContent).toMatch(/^−24,532/)
    // 환율을 넣기 전에는 원화를 지어내지 않는다
    expect(hero.querySelector('.fr-hero__krw')).toBeNull()

    fireEvent.change(screen.getByLabelText('환율 (원/USD)'), { target: { value: '1400' } })
    await waitFor(() => expect(hero.querySelector('.fr-hero__krw')?.textContent).toMatch(/^≈ −/))
    expect(store.get('bluelog.fleetReduction.krwPerUsd')).toBe('1400')
  })

  it('등급이 바뀌면 전이를 그리고(`DESIGN_SYSTEM §8.3`), 계산 못 한 선박은 사유와 비활성 슬라이더', async () => {
    renderWith()

    expect(await screen.findByLabelText('조정 전 E, 조정 후 D')).toBeTruthy()
    expect(screen.getByText('올해 계산할 항차 없음')).toBeTruthy()
    expect((screen.getByLabelText('MV Empty 감속률') as HTMLInputElement).disabled).toBe(true)
  })

  it('미달 힌트의 연료량은 같은 표의 「연료 절감」 칸과 같은 자릿수·단위다 (#2122)', async () => {
    const base = result().vessels[0]
    renderWith(
      result({
        vessels: [
          { ...base, meetsTarget: false, achievable: true, fuelSavedTon: '1305.52', requiredCutFuelTon: '1305.52' },
        ],
      }),
    )
    await screen.findByText('MV One')

    // 같은 값을 넣었으므로 두 자리의 표기가 **글자까지 같아야** 한다 — 종전에는 힌트만
    // 단위를 붙여 쓰고(`305.5t`) 자릿수도 따로 박았다.
    const cell = [...document.querySelectorAll('td.fr__num')]
      .map((td) => td.textContent ?? '')
      .find((text) => text.endsWith(` ${DISPLAY_UNITS.fuel}`))
    expect(cell).toBeTruthy()
    const hint = [...document.querySelectorAll('.fr__hint')]
      .map((el) => el.textContent ?? '')
      .find((text) => text.includes(FLEET_REDUCTION_COPY.misses))
    expect(hint).toContain(cell!.trim())
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
    // 첫 결과가 오기 전에는 이름이 있어도 잠겨 있다(#2120) — 결과가 선 뒤에 이름으로 켠다.
    await screen.findByText('MV One')

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
/**
 * 선박명 옆 CII 적용 대상 배지 (`#2132` 결정 3 · `DESIGN_SYSTEM §8.2` 「선박을 식별하는 자리마다」).
 *
 * 「위험 선박 0척」 목표에서 적용 대상이 아닌 선박은 E여도 「목표 달성」이다(`PRD §12.3.2` ⑸).
 * 그 이유가 같은 행에 보이지 않으면 「E · 목표 달성」이 모순으로 읽힌다. 배지 문구는 표시
 * 문구라 리터럴로 단언하지 않고(`AGENTS §4.6`) 공용 배지의 성질(`role="img"` · 접근성 이름에
 * 선박명)과 **세 상태가 서로 다르게 그려지는가**로 본다.
 */
describe('선박명 옆에 CII 적용 대상 배지를 붙인다 (#2132)', () => {
  const vessel = (over: Partial<EvaluateResult['vessels'][number]>) => ({
    ...result().vessels[0],
    ...over,
  })

  it('적용 대상이 아닌 선박(GT 4,999)과 판정 불가(GT 미입력) 선박의 행에 배지가 그려진다', async () => {
    renderWith(
      result({
        vessels: [
          vessel({ vesselId: 's', vesselName: 'MV Small', isCiiApplicableHint: false, grossTonnage: 4999 }),
          vessel({ vesselId: 'n', vesselName: 'MV NoGT', isCiiApplicableHint: false, grossTonnage: null }),
          vessel({ vesselId: 'b', vesselName: 'MV Big', isCiiApplicableHint: true, grossTonnage: 30000 }),
        ],
      }),
    )

    const rowOf = async (name: string) => (await screen.findByRole('link', { name })).closest('tr')!
    const small = within(await rowOf('MV Small')).getByRole('img', { name: /MV Small/ })
    const noGt = within(await rowOf('MV NoGT')).getByRole('img', { name: /MV NoGT/ })
    // 두 상태(「미해당」 · 「판정 불가」)를 같은 말로 합치지 않는다 — `DESIGN_SYSTEM §8.2`.
    expect(small.textContent).not.toBe('')
    expect(noGt.textContent).not.toBe('')
    expect(small.textContent).not.toBe(noGt.textContent)
    // 배지는 선박명 칸(`th`)에 붙는다 — 선박을 식별하는 자리다.
    expect(small.closest('th')?.className).toContain('fr__vessel')
    // 적용 대상이면 아무것도 그리지 않는다.
    expect(within(await rowOf('MV Big')).queryByRole('img', { name: /MV Big/ })).toBeNull()
  })
})

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
    stubCatalogs()
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
    stubCatalogs()
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
/*
 * 10/7 디자인 결정(#2314) — 결론의 주인공이 척수에서 **순손익**으로 바뀌었다(`.fr-hero`).
 * 척수는 오른쪽 「미달 N척 · 충족 N척」으로 남는다. 세는 규칙(계산 못 한 선박을 세지 않는다)은
 * 그대로 지킨다.
 */
describe('결론 띠 — DESIGN_SYSTEM §8.6 (#1757 · #2314)', () => {
  const strip = () => document.querySelector('.fr-hero') as HTMLElement
  const target = () => document.querySelector('.fr-hero__target') as HTMLElement

  it('목표 척수는 계산할 수 있는 선박만 센다 — 계산 못 한 선박은 미달로도 충족으로도 세지 않는다', async () => {
    renderWith()
    await screen.findByText('MV One')

    /* 고정표: 계산 가능 1척(v1 · 달성) + 계산 불가 1척(v2). 충족 1척이고 미달은 없다. */
    expect(target().textContent).toContain('충족 1척')
    expect(target().textContent).not.toContain('2척')
    expect(target().querySelector('.fr-hero__missed')).toBeNull()
  })

  it('미달 선박이 있으면 「미달 N척」을 먼저, 그 선박 이름과 함께 적는다', async () => {
    const base = result().vessels[0]
    renderWith(
      result({
        vessels: [
          { ...base, vesselId: 'v3', vesselName: 'MV Short', meetsTarget: false, requiredCutFuelTon: '12.30' },
          base,
        ],
      }),
    )
    await screen.findByText('MV Short')

    const missed = target().querySelector('.fr-hero__missed') as HTMLElement
    expect(missed.textContent).toContain('1척')
    expect(target().textContent).toContain('충족 1척')
    expect(target().textContent).toContain('MV Short')
    // 표에서도 미달 행이 먼저다
    const rows = [...document.querySelectorAll('.fr__table tbody tr')]
    expect(rows[0].textContent).toContain('MV Short')
    expect(rows[0].classList.contains('fr__row--missed')).toBe(true)
  })

  it('계산할 수 있는 선박이 0척이면 척수를 지어내지 않는다', async () => {
    renderWith(
      result({
        targetMet: null,
        vessels: [
          {
            vesselId: 'v2',
            vesselName: 'MV Empty',
            isCiiApplicableHint: true,
            grossTonnage: 30000,
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

    expect(target().querySelector('.fr-hero__status')?.textContent).toBe('—')
    // 목표 이름(「위험 선박 0척」)은 척수가 아니다 — 판정 줄에 「충족 0척」 같은 수를 지어내지 않는다
    expect(target().textContent).not.toMatch(/(충족|미달) 0척/)
    /* 상태 문장은 `<strong>목표</strong> — 문구` 꼴이라 텍스트가 두 노드로 갈린다. */
    expect(document.querySelector('.fr__status')?.textContent).toContain(
      FLEET_REDUCTION_COPY.statusNoVessel,
    )
  })

  it('⚠️ 주 결론은 순손익이고, 단가가 비면 0이 아니라 입력이 필요하다고 말한다 (PRD §12.3.2)', async () => {
    renderWith()
    await screen.findByText('MV One')

    const cost = strip().querySelector('.fr-hero__cost') as HTMLElement
    expect(cost.querySelector('.fr-hero__label')?.textContent).toContain(FLEET_REDUCTION_COPY.net)
    const value = cost.querySelector('.fr-hero__value') as HTMLElement
    expect(value.textContent).toMatch(/입력 필요/)
    expect(value.textContent).not.toMatch(/\d/)
  })

  it('위험도 pill을 두지 않는다 — 이 화면의 데이터에 위험도 값이 없다 (§8.6 v2.23)', async () => {
    renderWith()
    await screen.findByText('MV One')

    expect(document.querySelector('.verdict-strip__risk')).toBeNull()
  })

  it('비용 내역 셋은 순손익 바로 아래 목록이다 — 카드로 감싸지 않는다 (§8.6)', async () => {
    renderWith()
    await screen.findByText('MV One')

    const costs = document.querySelector('.fr-hero__breakdown') as HTMLElement
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
    (screen.getByText(name, { selector: 'summary' }).closest('details') as HTMLDetailsElement)

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
 * 이어받은 단가의 출처 (#2020).
 *
 * 가장 최근 계획의 단가를 새 계획에 채우는 것은 09-13 결정이다(`PRD §12.3.2` · `API_SPEC §2.17.3`).
 * 종전에는 **아무 말 없이** 채워, 사용자는 지금 시세로 넣은 값으로 읽고 그대로 저장할 수 있었다.
 *
 * 문장은 표시 문구라(`AGENTS §4.6`) 리터럴로 단언하지 않는다 — **어느 계획에서 왔는지가 보이는가**,
 * **이어받은 그대로가 아닐 때 사라지는가**를 본다.
 */
describe('이어받은 단가는 출처를 말한다 (#2020)', () => {
  const SAVED: SavedPlanSummary = {
    planId: 'p1',
    planName: '8월 감속안',
    regulationYear: 2026,
    target: 'NO_AT_RISK',
    adjustments: [{ vesselId: 'v1', percent: 5 }],
    prices: { charterUsdPerDay: { v1: '15000' }, fuelUsdPerTon: { HFO: '600' } },
    createdAt: '2026-08-20T03:00:00Z',
  }

  function renderWithPlans(plans: SavedPlanSummary[]) {
    stubCatalogs()
    const provider = {
      evaluate: vi.fn(async (_req: EvaluateRequest) =>
        result({ costs: { ...result().costs, missingFuelPrices: ['HFO'] } }),
      ),
      save: vi.fn(async (req: EvaluateRequest & { planName: string }) => ({
        ...SAVED,
        planId: 'p2',
        planName: req.planName,
        prices: req.prices,
      })),
      list: vi.fn(async () => plans),
    } satisfies FleetReductionProvider
    render(
      <MemoryRouter>
        <FleetReduction provider={provider} />
      </MemoryRouter>,
    )
    return provider
  }

  /** 출처 문장 — 계획 이름을 담은 상태 문장. 문구가 아니라 「이름이 보이는가」로 찾는다. */
  const sourceLine = () =>
    screen.queryAllByRole('status').find((el) => el.textContent?.includes(SAVED.planName)) ?? null

  it('⚠️ 이어받으면 어느 계획에서 언제 왔는지 보인다 — 접힌 연료 단가 밖에서', async () => {
    renderWithPlans([SAVED])
    await screen.findByText('MV One')

    const line = await waitFor(() => {
      const found = sourceLine()
      expect(found).not.toBeNull()
      return found as HTMLElement
    })
    expect(line.textContent).toContain(formatTimestamp(SAVED.createdAt as string))
    // 이어받은 용선료는 표에 있다 — 접힌 안쪽에만 적으면 표를 보는 사용자에게 안 보인다.
    expect(line.closest('details')).toBeNull()
    expect((screen.getByLabelText('MV One 일일 용선료 (USD)') as HTMLInputElement).value).toBe('15000')
  })

  it('단가 칸을 하나라도 고치면 사라진다 — 그때부터는 이어받은 값이 아니다', async () => {
    renderWithPlans([SAVED])
    await waitFor(() => expect(sourceLine()).not.toBeNull())

    fireEvent.change(await screen.findByLabelText('MV One 일일 용선료 (USD)'), {
      target: { value: '16000' },
    })
    expect(sourceLine()).toBeNull()
  })

  it('연료 단가를 고쳐도 사라진다', async () => {
    renderWithPlans([SAVED])
    await waitFor(() => expect(sourceLine()).not.toBeNull())

    fireEvent.change(await screen.findByLabelText('중유 (HFO)'), { target: { value: '650' } })
    expect(sourceLine()).toBeNull()
  })

  it('저장한 계획이 없으면 말할 출처가 없다', async () => {
    renderWithPlans([])
    await screen.findByText('MV One')
    await screen.findByText(FLEET_REDUCTION_COPY.noPlans)

    // 이름으로 찾는 것만으로는 빈 단언이다(이름이 있을 수 없다). 문구 함수에서 **이름 뒤의 고정
    // 부분**을 뽑아, 어느 상태 문장에도 그것이 없음을 본다 — 문장의 위치·클래스가 바뀌어도
    // 거짓 통과하지 않고, 문구를 바꿔도 함께 따라간다(`AGENTS §4.6`).
    const tail = FLEET_REDUCTION_COPY.inheritedPrices('\u0000', null).split('\u0000')[1]
    expect(tail.trim()).not.toBe('')
    for (const el of screen.queryAllByRole('status')) expect(el.textContent ?? '').not.toContain(tail)
  })

  it('⚠️ 단가 없이 저장한 계획이면 이어받은 값이 없다 — 「이어받았다」고 적지 않는다', async () => {
    renderWithPlans([{ ...SAVED, prices: { charterUsdPerDay: {}, fuelUsdPerTon: { HFO: ' ' } } }])
    await screen.findByText('MV One')
    await screen.findByText(FLEET_REDUCTION_COPY.loadPlaceholder)

    expect(sourceLine()).toBeNull()
  })

  it('⚠️ 불러오기는 그 계획을 연 것이다 — 이어받음 문장을 쓰지 않는다', async () => {
    const other: SavedPlanSummary = { ...SAVED, planId: 'p0', planName: '7월 기준안' }
    renderWithPlans([SAVED, other])
    await waitFor(() => expect(sourceLine()).not.toBeNull())

    fireEvent.change(screen.getByLabelText(FLEET_REDUCTION_COPY.loadLabel), {
      target: { value: 'p0' },
    })
    expect(sourceLine()).toBeNull()
    expect(
      screen.queryAllByRole('status').some((el) => el.textContent?.includes(other.planName)),
    ).toBe(false)
  })

  it('이어받은 단가로 저장하면 그 단가는 새 계획의 가정이다 — 문장을 내린다', async () => {
    const provider = renderWithPlans([SAVED])
    await waitFor(() => expect(sourceLine()).not.toBeNull())

    fireEvent.change(screen.getByLabelText(FLEET_REDUCTION_COPY.planNameLabel), {
      target: { value: '9월안' },
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: FLEET_REDUCTION_COPY.saveButton }))
    })

    await waitFor(() => expect(provider.save).toHaveBeenCalledTimes(1))
    // 결정 — 저장된 계획에 출처를 남기지 않는다. 요청 모양은 그대로다.
    expect(Object.keys(provider.save.mock.calls[0][0]).sort()).toEqual(
      ['adjustments', 'planName', 'prices', 'regulationYear', 'target'].sort(),
    )
    expect(sourceLine()).toBeNull()
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

    const costs = document.querySelector('.fr-hero__breakdown dd.fr__num') as HTMLElement
    const [rowDays] = vesselCells()
    for (const text of [costs.textContent?.trim() ?? '', rowDays]) {
      /* 숫자와 단위 사이는 한 칸 띄운다 — `§4.2` 예시 「232 일」. */
      expect(text.endsWith(` ${DISPLAY_UNITS.day}`)).toBe(true)
      expect(text.slice(0, -DISPLAY_UNITS.day.length - 1)).toMatch(/^\d+$/)
    }
    /* 절사가 아니라 반올림이다 — `1.52`는 `1`이 아니다. */
    expect(rowDays.slice(0, -DISPLAY_UNITS.day.length - 1)).not.toBe('1')
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
    expect(fuel.endsWith(` ${DISPLAY_UNITS.fuel}`)).toBe(true)
    expect(fuel.slice(0, -DISPLAY_UNITS.fuel.length - 1)).toMatch(/^\d{1,3}(,\d{3})+\.\d$/)
  })

  it('값이 없으면 단위도 붙이지 않는다', async () => {
    renderWith()
    await screen.findByText('MV Empty')

    const row = screen.getByText('MV Empty').closest('tr') as HTMLTableRowElement
    const cells = [...row.querySelectorAll('td.fr__num')].map((cell) => cell.textContent?.trim())
    expect(cells).toEqual(['—', '—'])
  })
})

/**
 * 「위험 선박」의 기준을 화면이 말한다 (#1593 · `#1531`).
 *
 * 대시보드 배너의 「위험 선박 n척」과 이 화면의 「위험 선박 0척」은 **기준이 다르다** —
 * `PRD §12.3.2` ⑸가 이 화면을 「조정 후 **연말 결정론 예상 등급**」으로 정하고, 배너는
 * `§3.3.7`의 **올해 누적(YTD)**이다. 정본은 그 차이를 적어 두었으나(`#1531`) **화면에는
 * 어디에도 없었다** — 두 화면을 오가는 사람에게는 같은 이름의 수가 다르게 보일 뿐이었다.
 *
 * 자리는 `DESIGN_SYSTEM §8.6`이 정한 **결론 띠 바로 아래 한 줄**이고, 그 줄이 이미
 * 목표 이름을 들고 있어 이름과 기준이 떨어지지 않는다.
 */
describe('위험 선박의 기준 표기 (#1593)', () => {
  it('결론 띠 아래 상태 줄이 「연말 예상 기준」을 함께 말한다', async () => {
    renderWith()
    await screen.findByText('MV One')

    const status = document.querySelector('.fr__status')
    expect(status?.textContent).toContain(FLEET_REDUCTION_COPY.statusBasis)
    /* 목표 이름과 같은 줄이어야 한다 — 떨어지면 무엇의 기준인지 읽히지 않는다. */
    expect(status?.textContent).toContain(TARGET_TEXT.NO_AT_RISK)
  })

  it('기준 문구는 「연말」을 말하고 「YTD·누적」을 말하지 않는다', () => {
    /*
     * 대시보드 배너 쪽 문구와 **바뀌어 적히는 것**을 막는다. 이 화면은 연말 예상이고
     * 배너는 올해 누적이다 — 둘이 뒤집히면 이 이슈가 고치려던 혼동이 되돌아온다.
     */
    expect(FLEET_REDUCTION_COPY.statusBasis).toContain('연말')
    expect(FLEET_REDUCTION_COPY.statusBasis).not.toMatch(/YTD|누적/)
  })
})

describe('함대 감축 계획 화면 — 연도 칸 상태와 재계산 중 (#2120)', () => {
  function mount(evaluate: FleetReductionProvider['evaluate'], save = vi.fn()) {
    render(
      <MemoryRouter>
        <FleetReduction provider={{ evaluate, save, list: vi.fn(async () => []) }} />
      </MemoryRouter>,
    )
  }
  const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

  it('⚠️ 연도 조회가 500이면 평가 요청을 보내지 않고 연도 칸 자리에 상태 문구를 보인다', async () => {
    stubCatalogs(() => new Response('{}', { status: 500 }))
    const evaluate = vi.fn(async (_req: EvaluateRequest) => result())
    mount(evaluate)

    await screen.findByText(/규제연도/, { selector: '.fr__hint' })
    await wait(600)
    // 기기 시계의 해로 대신 묻지 않는다 — 한 번도 나가지 않는다.
    expect(evaluate).not.toHaveBeenCalled()
    expect(screen.queryByRole('combobox', { name: FLEET_REDUCTION_COPY.yearLabel })).toBeNull()
    // 계산을 시작하지 않았으므로 「계산하는 중」을 적지 않는다.
    expect(screen.queryByText(FLEET_REDUCTION_COPY.loading)).toBeNull()
  })

  it('연도 목록이 비어 있을 때(실패가 아님)도 요청이 없고, 문구는 실패와 서로 다르다', async () => {
    stubCatalogs(() => new Response(JSON.stringify({ data: [] }), { status: 200 }))
    const evaluate = vi.fn(async (_req: EvaluateRequest) => result())
    mount(evaluate)
    const empty = await screen.findByText(/규제연도/, { selector: '.fr__hint' })
    await wait(600)
    expect(evaluate).not.toHaveBeenCalled()
    const emptyText = empty.textContent
    cleanup()

    stubCatalogs(() => new Response('{}', { status: 500 }))
    mount(evaluate)
    const failed = await screen.findByText(/규제연도/, { selector: '.fr__hint' })
    expect(failed.textContent).not.toBe(emptyText)
  })

  it('⚠️ 감속률을 바꾼 뒤 응답이 오기 전에는 진행 표시가 서고 저장이 잠긴다 — 응답이 오면 풀린다', async () => {
    stubCatalogs()
    let release: (value: EvaluateResult) => void = () => {}
    const evaluate = vi
      .fn<FleetReductionProvider['evaluate']>()
      .mockResolvedValueOnce(result())
      .mockImplementationOnce(() => new Promise<EvaluateResult>((resolve) => (release = resolve)))
    mount(evaluate)

    const slider = await screen.findByLabelText('MV One 감속률')
    const root = document.querySelector('.fr') as HTMLElement
    await waitFor(() => expect(root.getAttribute('aria-busy')).toBe('false'))
    fireEvent.click(screen.getByText(FLEET_REDUCTION_COPY.saveTitle))
    fireEvent.change(screen.getByLabelText(FLEET_REDUCTION_COPY.planNameLabel), {
      target: { value: '계획' },
    })
    const save = screen.getByRole('button', { name: FLEET_REDUCTION_COPY.saveButton }) as HTMLButtonElement
    await waitFor(() => expect(save.disabled).toBe(false))

    fireEvent.change(slider, { target: { value: '50' } })

    await waitFor(() => expect(root.getAttribute('aria-busy')).toBe('true'))
    await waitFor(() => expect(evaluate).toHaveBeenCalledTimes(2))
    expect(save.disabled).toBe(true)
    // 이전 결과가 그대로 남은 채 진행 중임을 말한다.
    expect(screen.getByText(FLEET_REDUCTION_COPY.loading)).toBeTruthy()

    await act(async () => {
      release(result())
    })
    await waitFor(() => expect(root.getAttribute('aria-busy')).toBe('false'))
    expect(save.disabled).toBe(false)
  })

  it('⚠️ 「다시 시도」도 응답이 오기 전에는 진행 중이다 — 요청이 같아도 기다리는 중이고, 지난 실패는 그동안 보이지 않는다', async () => {
    stubCatalogs()
    let release: (value: EvaluateResult) => void = () => {}
    const evaluate = vi
      .fn<FleetReductionProvider['evaluate']>()
      .mockRejectedValueOnce(new Error('평가 실패'))
      .mockImplementationOnce(() => new Promise<EvaluateResult>((resolve) => (release = resolve)))
    mount(evaluate)

    // 화면에는 다른 「다시 시도」(목록 조회 실패)도 있을 수 있다 — 평가 실패의 것을 집는다.
    const failure = (await screen.findByText(/평가 실패/)).closest('[role="alert"]') as HTMLElement
    const root = document.querySelector('.fr') as HTMLElement
    expect(root.getAttribute('aria-busy')).toBe('false')

    fireEvent.click(within(failure).getByRole('button'))

    await waitFor(() => expect(root.getAttribute('aria-busy')).toBe('true'))
    expect(screen.getByText(FLEET_REDUCTION_COPY.loading)).toBeTruthy()
    expect(screen.queryByText(/평가 실패/)).toBeNull()
    // 요청은 디바운스 뒤에 나간다 — 나간 것을 보고 답을 준다.
    await waitFor(() => expect(evaluate).toHaveBeenCalledTimes(2))

    await act(async () => {
      release(result())
    })
    await waitFor(() => expect(root.getAttribute('aria-busy')).toBe('false'))
  })

  it('연도 칸이 문구일 때도 라벨이 가리키는 id가 화면에 있다', async () => {
    stubCatalogs(() => new Response('{}', { status: 500 }))
    mount(vi.fn<FleetReductionProvider['evaluate']>())
    const hint = await screen.findByText(/규제연도/, { selector: '.fr__hint' })
    const label = document.querySelector('label[for="fr-year"]')
    expect(label).not.toBeNull()
    expect(hint.id).toBe('fr-year')
  })
})
