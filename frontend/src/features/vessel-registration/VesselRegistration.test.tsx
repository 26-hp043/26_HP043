// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { VesselRegistration } from './VesselRegistration'

/**
 * 등록 결과 카드 (#1102 ⑷).
 *
 * - 선종이 `BULK_CARRIER` 코드로 찍혔다. 목록·상세는 `shipTypeLabel`로 「벌크선」을
 *   보이는데 등록 직후 화면만 코드였다 — 같은 배가 화면마다 다른 이름이었다.
 * - 두 번째 등록이 실패해도 첫 선박의 「등록 완료」 카드가 남아, 실패한 쪽이 등록된
 *   것처럼 읽혔다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const REGISTERED = {
  id: '00000000-0000-4000-8000-0000000000a1',
  imo_number: '9000001',
  name: '알파호',
  ship_type: 'BULK_CARRIER',
  gross_tonnage: 30000,
  deadweight: 50000,
  default_fuel_type: null,
  reference_speed_kn: null,
  reference_daily_foc_ton: null,
  is_cii_applicable_hint: true,
  underway_state: null,
  detail_status: null,
  current_lat: null,
  current_lon: null,
  position_updated_at: null,
  created_at: null,
  updated_at: null,
}

/** `POST /vessels` 응답을 순서대로 낸다. 나머지 조회는 빈 목록·연료 1종. */
function stubFetch(posts: Response[]) {
  const queue = [...posts]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      if (url.includes('/vessels/samples')) {
        return jsonResponse({
          data: [
            {
              sample_id: 's1',
              label: '벌크선 (5만 DWT급)',
              ship_type: 'BULK_CARRIER',
              gross_tonnage: 30000,
              deadweight: 50000,
              default_fuel_type: 'HFO',
              reference_speed_kn: 13,
              reference_daily_foc_ton: 22,
            },
          ],
        })
      }
      if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/vessels')) {
        const next = queue.shift()
        if (next === undefined) throw new Error('POST /vessels 응답이 더 없다')
        return next
      }
      throw new Error(`stub에 없는 요청: ${init?.method ?? 'GET'} ${url}`)
    }),
  )
}

function fillRequired(imo: string, name: string) {
  fireEvent.change(screen.getByLabelText(/^IMO 번호/), { target: { value: imo } })
  fireEvent.change(screen.getByLabelText(/^선명/), { target: { value: name } })
  fireEvent.change(screen.getByLabelText(/^선종/), { target: { value: 'BULK_CARRIER' } })
}

/**
 * IMO·선명만 채운다 — 선종은 손대지 않는다.
 *
 * `#1526`의 「빈 폼」은 `hasDivergedFields`가 보는 여섯 칸(선종 포함) 기준이다.
 * `fillRequired`는 선종까지 고르므로, 그 여섯 칸을 정말 비워 두고 싶은
 * 샘플-덮어쓰기-확인 테스트에서는 이 헬퍼를 쓴다.
 */
function fillIdentity(imo: string, name: string) {
  fireEvent.change(screen.getByLabelText(/^IMO 번호/), { target: { value: imo } })
  fireEvent.change(screen.getByLabelText(/^선명/), { target: { value: name } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/**
 * 입력 순서 (`#1423`).
 *
 * 종전에는 **샘플 선박 선택이 첫 섹션**이라, 자기 배를 등록하러 온 사람이 IMO·선명보다
 * 먼저 샘플 목록을 만났다. 식별 정보 → 샘플 → 제원으로 옮겼다.
 *
 * **자리를 세 개로 묶어 본다.** 「샘플이 첫 칸이 아니다」로만 적으면 맨 아래로 내려가도
 * 통과하는데, 거기는 안 된다 — `applySample`이 선종·제원을 **조건 없이 덮으므로**
 * 사용자가 제원을 다 채운 뒤에 만나면 그 입력이 사라진다. 셋의 **앞뒤 관계**를 잠근다.
 */
describe('등록 폼의 입력 순서 (#1423)', () => {
  function controlOrder(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('input, select')).map((el) => el.id)
  }

  it('첫 입력이 식별 정보이고, 샘플은 그 뒤·제원 앞이다', async () => {
    stubFetch([])
    const { container } = render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    await screen.findByLabelText(/^IMO 번호/)

    const order = controlOrder(container)
    const at = (id: string) => order.indexOf(id)

    expect(at('imo-number')).toBe(0)
    expect(at('imo-number')).toBeLessThan(at('sample-vessel'))
    expect(at('ship-type')).toBeLessThan(at('sample-vessel'))
    // 샘플은 자기가 채우는 제원 **앞**에 있다 — 뒤면 이미 채운 값을 덮는다.
    expect(at('sample-vessel')).toBeLessThan(at('deadweight'))
  })

  it('샘플을 고르면 제원이 채워지고 IMO·선명은 그대로다 — 옮겨도 동작은 같다', async () => {
    stubFetch([])
    // `fillRequired`가 선종을 직접 고른다(`#1526` 기준 여섯 칸 중 하나). 그 선종이
    // 고르는 샘플과 다르면 확인창이 뜨므로 승인으로 둔다 — 이 검사가 보는 것은
    // 「채워지고 IMO·선명은 그대로다」이지 확인 여부가 아니다.
    vi.stubGlobal('confirm', vi.fn(() => true))
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillRequired('9000001', '알파호')

    fireEvent.change(await screen.findByLabelText(/^샘플 선박에서 채우기/), {
      target: { value: 's1' },
    })

    await waitFor(() =>
      expect((screen.getByLabelText(/^재화중량톤수/) as HTMLInputElement).value).toBe('50000'),
    )
    expect((screen.getByLabelText(/^선종/) as HTMLSelectElement).value).toBe('BULK_CARRIER')
    // 이것이 이 자리로 옮긴 이유다 — 먼저 적은 식별 정보는 살아남는다.
    expect((screen.getByLabelText(/^IMO 번호/) as HTMLInputElement).value).toBe('9000001')
    expect((screen.getByLabelText(/^선명/) as HTMLInputElement).value).toBe('알파호')
  })
})

describe('등록 결과 카드 (#1102 ⑷)', () => {
  it('선종을 목록과 같은 한글명으로 보인다 — 코드를 그대로 찍지 않는다', async () => {
    stubFetch([jsonResponse({ data: REGISTERED }, 201)])
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillRequired('9000001', '알파호')
    fireEvent.click(screen.getByRole('button', { name: '등록하기' }))

    await screen.findByText('등록 완료')
    // `dd`의 값 전체가 「벌크선」이다. 선택지의 「벌크선 (BULK_CARRIER)」와는 다르다.
    expect(screen.getByText('벌크선')).toBeTruthy()
    expect(screen.queryByText('BULK_CARRIER')).toBeNull()
  })

  /**
   * 값 칸의 3상태 (`#1656`). 판정 자체는 `resultRules.test.ts`가 순수 함수로
   * 잠그고, 여기서는 **카드가 그 판정을 그린다**는 것만 본다.
   */
  async function registerAndRead(vessel: Record<string, unknown>) {
    stubFetch([jsonResponse({ data: { ...REGISTERED, ...vessel } }, 201)])
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillRequired('9000001', '알파호')
    fireEvent.click(screen.getByRole('button', { name: '등록하기' }))
    await screen.findByText('등록 완료')

    const label = screen.getByText('CII 적용 대상 추정')
    return label.nextElementSibling?.textContent ?? ''
  }

  it('GT 미입력을 「미해당」으로 적지 않는다 (#1656)', async () => {
    const value = await registerAndRead({ gross_tonnage: null, is_cii_applicable_hint: false })

    expect(value).not.toBe('미해당')
    expect(value).toContain('GT')
  })

  it('GT가 있는데 미해당이면 그대로 미해당이라고 적는다 (#1656)', async () => {
    const value = await registerAndRead({ gross_tonnage: 3000, is_cii_applicable_hint: false })

    expect(value).not.toContain('GT 미입력')
    expect(value.length).toBeGreaterThan(0)
  })

  it('대상인 선박은 해당이라고 적는다 (#1656)', async () => {
    const value = await registerAndRead({ gross_tonnage: 30000, is_cii_applicable_hint: true })

    expect(value).toBe('해당')
  })

  it('두 번째 등록이 실패하면 첫 선박의 「등록 완료」 카드가 남지 않는다', async () => {
    stubFetch([
      jsonResponse({ data: REGISTERED }, 201),
      jsonResponse({ error: { code: 'CONFLICT', message: '이미 등록된 IMO 번호입니다.' } }, 409),
    ])
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillRequired('9000001', '알파호')
    fireEvent.click(screen.getByRole('button', { name: '등록하기' }))
    await screen.findByText('등록 완료')

    // 성공 뒤 폼은 비워진다. 같은 IMO를 다시 넣어 두 번째 등록을 시도한다.
    fillRequired('9000001', '브라보호')
    fireEvent.click(screen.getByRole('button', { name: '등록하기' }))

    expect(await screen.findByText('이미 등록된 IMO 번호입니다.')).toBeTruthy()
    // 실패한 시도 옆에 이전 성공 카드가 있으면 실패한 쪽이 등록된 것처럼 읽힌다.
    await waitFor(() => expect(screen.queryByText('등록 완료')).toBeNull())
  })
})

/**
 * 샘플 덮어쓰기 확인 (`#1526`).
 *
 * 판정 자체(`hasDivergedFields`)는 `sampleVessels.test.ts`가 순수 함수로 잠근다.
 * 여기서는 화면이 그 판정으로 `confirm()`을 부르는지 · 취소하면 실제로 아무것도
 * 바꾸지 않는지를 본다.
 */
describe('샘플 덮어쓰기 확인 (#1526)', () => {
  it('빈 폼에서 고르면 확인을 구하지 않는다', async () => {
    stubFetch([])
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillIdentity('9000001', '알파호')

    fireEvent.change(await screen.findByLabelText(/^샘플 선박에서 채우기/), {
      target: { value: 's1' },
    })

    await waitFor(() =>
      expect((screen.getByLabelText(/^재화중량톤수/) as HTMLInputElement).value).toBe('50000'),
    )
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('직접 입력한 값이 있으면 확인을 구하고, 취소하면 값도 선택도 그대로다', async () => {
    stubFetch([])
    const confirmSpy = vi.fn(() => false)
    vi.stubGlobal('confirm', confirmSpy)
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillIdentity('9000001', '알파호')
    fireEvent.change(await screen.findByLabelText(/^재화중량톤수/), {
      target: { value: '12345' },
    })

    const select = (await screen.findByLabelText(
      /^샘플 선박에서 채우기/,
    )) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 's1' } })

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    // 취소했으니 직접 넣은 값이 남고, 선택 상자도 적용하지 않은 채 그대로다.
    expect((screen.getByLabelText(/^재화중량톤수/) as HTMLInputElement).value).toBe('12345')
    expect(select.value).toBe('')
  })

  it('직접 입력한 값이 있어도 확인하면 샘플 값으로 덮는다', async () => {
    stubFetch([])
    vi.stubGlobal('confirm', vi.fn(() => true))
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillIdentity('9000001', '알파호')
    fireEvent.change(await screen.findByLabelText(/^재화중량톤수/), {
      target: { value: '12345' },
    })

    fireEvent.change(await screen.findByLabelText(/^샘플 선박에서 채우기/), {
      target: { value: 's1' },
    })

    await waitFor(() =>
      expect((screen.getByLabelText(/^재화중량톤수/) as HTMLInputElement).value).toBe('50000'),
    )
  })
})


/**
 * 제원 묶음을 접는다 (#1783).
 *
 * 화면 머리가 「IMO 번호·선명·선종만 있으면 등록됩니다」라고 적는데 선택 입력 여덟 칸이
 * 늘 펼쳐져 있어 **그 말과 보이는 것이 어긋났다.**
 */
describe('제원은 접어 두고, 스스로 펼치는 자리가 둘이다 (#1783)', () => {
  const specs = () => screen.getByText(/^제원 · 선택 입력/).closest('details') as HTMLDetailsElement

  it('처음에는 접혀 있고, 접힌 겉이 비우면 무엇이 막히는지 말한다', () => {
    stubFetch([])
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )

    expect(specs().open).toBe(false)
    // 접어 두고 이 줄이 없으면 사용자는 나중에 선박 관리에서 같은 경고를 만난다.
    expect(screen.getByText(/CII 등급을 산출할 수 없고/)).toBeTruthy()
    expect(screen.getByText(/^제원 · 선택 입력 7칸$/)).toBeTruthy()
  })

  it('샘플이 값을 채우면 펼친다 — 무엇이 들어갔는지 모른 채 등록하지 않게', async () => {
    stubFetch([])
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    await screen.findByRole('option', { name: /벌크선 \(5만 DWT급\)/ })

    fireEvent.change(screen.getByLabelText(/^샘플 선박에서 채우기/), { target: { value: 's1' } })

    await waitFor(() => expect(specs().open).toBe(true))
    // 채운 칸 수를 접힌 겉이 말한다 (`#1417` 「고급 설정」과 같은 꼴).
    expect(screen.getByText(/7칸 중 \d칸 채움/)).toBeTruthy()
  })

  it('접힌 칸에서 검증 오류가 나면 사용자가 접어 두었어도 펼친다 (§14)', async () => {
    stubFetch([])
    render(
      <MemoryRouter>
        <VesselRegistration />
      </MemoryRouter>,
    )
    fillRequired('9000001', '알파호')

    // 제원에 잘못된 값을 넣고 — 채워졌으니 한 번 펼쳐진다 — 사용자가 도로 접는다.
    fireEvent.change(screen.getByLabelText(/^재화중량톤수/), { target: { value: '-1' } })
    await waitFor(() => expect(specs().open).toBe(true))
    fireEvent.click(screen.getByText(/^제원 · 선택 입력/))
    specs().open = false
    fireEvent(specs(), new Event('toggle'))
    await waitFor(() => expect(specs().open).toBe(false))

    fireEvent.submit(screen.getByRole('button', { name: '등록하기' }).closest('form') as HTMLFormElement)

    /*
     * `§14`는 오류를 컨트롤 아래에 두라고 하는데, 접혀 있으면 그 컨트롤이 화면에 없다.
     * 그래서 오류는 사용자의 선택보다 먼저다.
     */
    await waitFor(() => expect(specs().open).toBe(true))
  })
})
