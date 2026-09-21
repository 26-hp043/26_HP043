// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { RegulationParametersSection } from './RegulationParametersSection'
import type {
  FuelTypeRow,
  RatingBoundaryRow,
  ReferenceLineRow,
  ReferenceListOptions,
  ReferenceParametersProvider,
  RegulationYearRow,
} from './referenceApiProvider'
import { REGULATION_PARAMETERS_ANCHOR } from './referenceRules'
import { SettingsPage } from '../../pages/SettingsPage'
import * as session from '../../auth/session'

/**
 * 설정의 「규제 기준값」 절 (`#1516` · `#1239` 결정 A~D·G).
 *
 * 문구가 아니라 **성질**을 단언한다(`AGENTS §4.6`) — 네 표가 서버 행 수만큼 그려지는가,
 * 숫자가 서버 문자열과 같은가(가공 안 됨), 전환이 `active=false`로 다시 묻는가, 이행 행이
 * 구분되는가, 연료 표에 이력 없음 안내가 있는가, 현장직 세션에서도 절이 있는가.
 */

const YEARS: RegulationYearRow[] = [
  { year: 2026, zFactorPercent: '11.0', effectiveFrom: '2026-01-01', sourceRef: 'MEPC.400(83)', version: '2025-q2', isActive: true },
  { year: 2027, zFactorPercent: '13.625', effectiveFrom: '2027-01-01', sourceRef: 'MEPC.400(83)', version: '2025-q2', isActive: true },
  { year: 2028, zFactorPercent: '16.25', effectiveFrom: '2028-01-01', sourceRef: 'MEPC.400(83)', version: '2025-q2', isActive: true },
]

const LINES: ReferenceLineRow[] = [
  { shipType: 'BULK_CARRIER', conditionExpr: 'DWT >= 279000', capacityRule: 'fixed 279000', aRaw: '4745', aDecimal: '4745', c: '0.622000', sourceRef: 'MEPC.353(78)', version: null, isActive: true },
  { shipType: 'LNG_CARRIER', conditionExpr: 'DWT < 65000', capacityRule: 'fixed 65000', aRaw: '14779E10', aDecimal: '147790000000000', c: '2.673000', sourceRef: 'MEPC.353(78)', version: null, isActive: true },
]

const BOUNDARIES: RatingBoundaryRow[] = [
  { shipType: 'BULK_CARRIER', conditionExpr: 'all', capacityBasis: 'DWT', d1: '0.86', d2: '0.94', d3: '1.06', d4: '1.18', sourceRef: 'MEPC.354(78)', version: null, isActive: true },
]

const FUELS: FuelTypeRow[] = [
  { code: 'HFO', displayName: 'Heavy Fuel Oil', cf: '3.114000', unit: 'tCO₂/tFuel', sourceRef: 'MEPC.364(79)', isActive: true },
  { code: 'LNG', displayName: 'Liquefied Natural Gas', cf: '2.750000', unit: 'tCO₂/tFuel', sourceRef: 'MEPC.364(79)', isActive: true },
  { code: 'MDO', displayName: 'Marine Diesel Oil', cf: '3.206000', unit: 'tCO₂/tFuel', sourceRef: 'MEPC.364(79)', isActive: true },
  { code: 'LPG', displayName: 'LPG (Propane)', cf: '3.000000', unit: 'tCO₂/tFuel', sourceRef: 'MEPC.364(79)', isActive: true },
]

/** 「이전 판본 포함」일 때 서버가 섞어 주는 이행 행. */
const SUPERSEDED_YEAR: RegulationYearRow = {
  year: 2026,
  zFactorPercent: '9.00',
  effectiveFrom: '2026-01-01',
  sourceRef: 'MEPC.338(76)',
  version: '2024-q1',
  isActive: false,
}

function fakeProvider() {
  const calls: Array<{ table: string; options: ReferenceListOptions | undefined }> = []
  const provider: ReferenceParametersProvider = {
    listRegulationYears: vi.fn(async (options) => {
      calls.push({ table: 'years', options })
      return options?.includeInactive ? [...YEARS, SUPERSEDED_YEAR] : YEARS
    }),
    listReferenceLines: vi.fn(async (options) => {
      calls.push({ table: 'lines', options })
      return LINES
    }),
    listRatingBoundaries: vi.fn(async (options) => {
      calls.push({ table: 'boundaries', options })
      return BOUNDARIES
    }),
    listFuelTypes: vi.fn(async () => {
      calls.push({ table: 'fuels', options: undefined })
      return FUELS
    }),
  }
  return { provider, calls }
}

function renderSection(provider: ReferenceParametersProvider, initialEntry = '/settings') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <RegulationParametersSection provider={provider} />
    </MemoryRouter>,
  )
}

/** 표의 본문 행 수 — 머리행은 뺀다. */
function bodyRows(testId: string): HTMLElement[] {
  const table = screen.getByTestId(testId)
  return within(table.querySelector('tbody') as HTMLElement).getAllByRole('row')
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('네 표가 서버 행 수만큼 그려진다', () => {
  it('연도·기준선·경계·연료 표의 행 수가 응답과 같다', async () => {
    const { provider } = fakeProvider()
    renderSection(provider)

    await waitFor(() => expect(bodyRows('regp-table-years')).toHaveLength(YEARS.length))
    expect(bodyRows('regp-table-lines')).toHaveLength(LINES.length)
    expect(bodyRows('regp-table-boundaries')).toHaveLength(BOUNDARIES.length)
    await waitFor(() => expect(bodyRows('regp-table-fuels')).toHaveLength(FUELS.length))
  })

  it('절은 앵커 id를 가진 영역이다 — 세 자리의 링크가 여기로 온다', async () => {
    const { provider } = fakeProvider()
    renderSection(provider)

    const section = document.getElementById(REGULATION_PARAMETERS_ANCHOR)
    expect(section).not.toBeNull()
    expect(section?.tagName).toBe('SECTION')
    await waitFor(() => expect(bodyRows('regp-table-years').length).toBeGreaterThan(0))
  })
})

describe('숫자는 서버 문자열 그대로다 (`#1239` 결정 G)', () => {
  it('자릿수·표기를 가공하지 않는다 — `0.622000`이 `0.622`가 되지 않는다', async () => {
    const { provider } = fakeProvider()
    renderSection(provider)
    await waitFor(() => expect(bodyRows('regp-table-lines')).toHaveLength(LINES.length))

    const lines = screen.getByTestId('regp-table-lines')
    for (const row of LINES) {
      expect(within(lines).getByText(row.c)).toBeTruthy()
      // `a_raw`와 `a_decimal`이 같은 값(`4745`)일 수 있어 둘 이상 잡히는 것이 정상이다.
      expect(within(lines).getAllByText(row.aRaw).length).toBeGreaterThanOrEqual(1)
    }
    // 정규화된 형태는 어디에도 없다.
    expect(within(lines).queryByText('0.622')).toBeNull()
    expect(within(lines).queryByText('2.673')).toBeNull()

    const fuels = await screen.findByTestId('regp-table-fuels')
    for (const row of FUELS) expect(within(fuels).getByText(row.cf)).toBeTruthy()
    expect(within(fuels).queryByText('3.114')).toBeNull()
  })

  it('`a_raw`(IMO 원문 표기)와 `a_decimal`이 함께 보인다', async () => {
    const { provider } = fakeProvider()
    renderSection(provider)
    await waitFor(() => expect(bodyRows('regp-table-lines')).toHaveLength(LINES.length))

    const lines = screen.getByTestId('regp-table-lines')
    expect(within(lines).getByText('14779E10')).toBeTruthy()
    expect(within(lines).getByText('147790000000000')).toBeTruthy()
  })
})

describe('「이전 판본 포함」 (`#1239` 결정 C)', () => {
  it('처음에는 활성만 묻고, 켜면 세 표를 `includeInactive`로 다시 묻는다', async () => {
    const { provider, calls } = fakeProvider()
    renderSection(provider)
    await waitFor(() => expect(bodyRows('regp-table-years')).toHaveLength(YEARS.length))

    const first = calls.filter((call) => call.table !== 'fuels')
    expect(first).toHaveLength(3)
    expect(first.every((call) => !call.options?.includeInactive)).toBe(true)

    fireEvent.click(screen.getByTestId('regp-include-inactive'))

    await waitFor(() => {
      const again = calls.filter((call) => call.options?.includeInactive === true)
      expect(again.map((call) => call.table).sort()).toEqual(['boundaries', 'lines', 'years'])
    })
    // 연료는 이력이 없어 다시 묻지 않는다.
    expect(calls.filter((call) => call.table === 'fuels')).toHaveLength(1)
  })

  it('이행 행이 섞여 보이되 활성 행과 구분된다 — 판본이 붙는다', async () => {
    const { provider } = fakeProvider()
    renderSection(provider)
    await waitFor(() => expect(bodyRows('regp-table-years')).toHaveLength(YEARS.length))

    fireEvent.click(screen.getByTestId('regp-include-inactive'))
    await waitFor(() => expect(bodyRows('regp-table-years')).toHaveLength(YEARS.length + 1))

    const rows = bodyRows('regp-table-years')
    const superseded = rows.filter((row) => row.getAttribute('data-superseded') === 'true')
    const current = rows.filter((row) => row.getAttribute('data-superseded') !== 'true')
    expect(superseded).toHaveLength(1)
    expect(current).toHaveLength(YEARS.length)
    // 이행 행은 자기 판본·출처·옛 값을 그대로 싣는다 — 「왜 등급이 바뀌었나」의 답이 여기 있다.
    const text = superseded[0].textContent ?? ''
    expect(text).toContain(SUPERSEDED_YEAR.version)
    expect(text).toContain(SUPERSEDED_YEAR.sourceRef)
    expect(text).toContain(SUPERSEDED_YEAR.zFactorPercent)
    // 상태 열의 글자가 다르다 — 색만으로 가르지 않는다.
    const stateOf = (row: HTMLElement) => within(row).getAllByRole('cell').at(-1)?.textContent
    expect(stateOf(superseded[0])).not.toBe(stateOf(current[0]))
  })

  it('연료 표에는 이력 없음 안내가 있다 — 「없음」의 종류를 말한다', async () => {
    const { provider } = fakeProvider()
    renderSection(provider)
    await screen.findByTestId('regp-table-fuels')

    const notice = screen.getByTestId('regp-fuel-no-history')
    expect((notice.textContent ?? '').length).toBeGreaterThan(0)
    // 연료 묶음 안에 있다 — 다른 표에는 붙지 않는다.
    expect(screen.getByTestId('regp-group-fuels').contains(notice)).toBe(true)
    expect(screen.getByTestId('regp-group-years').contains(notice)).toBe(false)
  })
})

describe('조회는 세 역할 모두 (`#1239` 결정 D)', () => {
  it('현장직 세션에서도 설정 화면에 절이 있다', async () => {
    vi.spyOn(session, 'useAuthUser').mockReturnValue({
      id: 'u-field',
      email: 'field@bluelog.local',
      displayName: '현장',
      role: 'FIELD',
      emailVerifiedAt: null,
    })
    // 실 provider가 전역 fetch로 네 표를 묻는다 — 연도 표 하나만 채워도 절의 존재는 드러난다.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = new URL(String(input), 'https://x')
        const data = url.pathname.endsWith('/regulation-years') ? YEARS.map((row) => ({
          year: row.year,
          z_factor_percent: row.zFactorPercent,
          effective_from: row.effectiveFrom,
          source_ref: row.sourceRef,
          version: row.version,
          is_active: row.isActive,
        })) : []
        return { ok: true, status: 200, json: async () => ({ data }) } as Response
      }),
    )

    render(
      <MemoryRouter initialEntries={['/settings']}>
        <SettingsPage />
      </MemoryRouter>,
    )

    expect(document.getElementById(REGULATION_PARAMETERS_ANCHOR)).not.toBeNull()
    await waitFor(() => expect(bodyRows('regp-table-years')).toHaveLength(YEARS.length))
    // 역할 가드 문구로 대체되지 않았다.
    expect(screen.getByTestId('regp-include-inactive')).toBeTruthy()
  })
})

describe('해시로 들어오면 절이 초점을 받는다', () => {
  it('`#regulation-parameters`로 열면 절이 활성 요소다', async () => {
    const { provider } = fakeProvider()
    renderSection(provider, `/settings#${REGULATION_PARAMETERS_ANCHOR}`)

    await waitFor(() => expect(document.activeElement?.id).toBe(REGULATION_PARAMETERS_ANCHOR))
  })
})

describe('실패는 절 안에 남는다', () => {
  it('세 표 조회가 실패하면 그 사유가 절 안에 보이고 연료 표는 그대로 뜬다', async () => {
    const { provider } = fakeProvider()
    ;(provider.listReferenceLines as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('기준선 실패'))
    renderSection(provider)

    expect(await screen.findByText('기준선 실패')).toBeTruthy()
    await waitFor(() => expect(bodyRows('regp-table-fuels')).toHaveLength(FUELS.length))
  })
})
