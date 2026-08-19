import { describe, expect, it, vi } from 'vitest'
import { ParametersError, createApiParametersProvider } from './apiProvider'

/**
 * 규제 파라미터 조회 provider (`API_SPEC §7.2` · `#444`).
 *
 * 여기서 고정하는 것은 둘이다.
 *
 * * **`cf`를 문자열로 유지하는 것** — `Number`로 되돌리면 정밀도가 깎이고, 그 차이는
 *   등급 경계 근처에서만 드러나 발견이 늦다 (`API_SPEC §1.7`).
 * * **응답이 깨져도 화면이 죽지 않는 것** — 연료 선택지는 폼의 일부일 뿐인데
 *   그것 때문에 전체 화면이 못 뜨면 사용자는 아무것도 못 한다.
 */

const BODY = {
  data: [
    {
      code: 'HFO',
      display_name: 'Heavy Fuel Oil',
      cf: '3.114000',
      unit: 'tCO₂/tFuel',
      source_ref: 'MEPC.364(79)',
      is_active: true,
    },
    {
      code: 'LNG',
      display_name: 'Liquefied Natural Gas',
      cf: '2.750000',
      unit: 'tCO₂/tFuel',
      source_ref: 'MEPC.364(79)',
      is_active: true,
    },
  ],
  meta: { total: 2 },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('연료 종류 조회', () => {
  it('GET /parameters/fuel-types 를 부른다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(BODY))
    await createApiParametersProvider(fetchImpl).listFuelTypes()

    expect(String(fetchImpl.mock.calls[0][0])).toBe('/api/v1/parameters/fuel-types')
  })

  it('cf를 문자열 그대로 둔다 — 숫자로 되돌리지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(BODY))
    const rows = await createApiParametersProvider(fetchImpl).listFuelTypes()

    expect(rows[0].cf).toBe('3.114000')
    expect(typeof rows[0].cf).toBe('string')
  })

  it('표시 이름과 코드를 함께 준다 — 화면이 코드만 보이지 않아도 된다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(BODY))
    const rows = await createApiParametersProvider(fetchImpl).listFuelTypes()

    expect(rows.map((row) => row.code)).toEqual(['HFO', 'LNG'])
    expect(rows[0].displayName).toBe('Heavy Fuel Oil')
  })

  it('표시 이름이 없으면 코드를 쓴다 — 빈 항목을 셀렉트에 넣지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: [{ code: 'HFO' }] }))
    const rows = await createApiParametersProvider(fetchImpl).listFuelTypes()

    expect(rows[0].displayName).toBe('HFO')
  })

  it('코드가 없는 행은 버린다 — 고를 수 없는 선택지가 생기지 않게', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ data: [{ display_name: '이름만 있는 행' }, { code: 'HFO' }] }),
    )
    const rows = await createApiParametersProvider(fetchImpl).listFuelTypes()

    expect(rows).toHaveLength(1)
  })

  it('본문이 배열이 아니면 빈 목록이다 — 던지지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: null }))
    const rows = await createApiParametersProvider(fetchImpl).listFuelTypes()

    expect(rows).toEqual([])
  })

  it('실패는 ParametersError로 알린다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 500))

    await expect(createApiParametersProvider(fetchImpl).listFuelTypes()).rejects.toBeInstanceOf(
      ParametersError,
    )
  })

  it('네트워크 실패를 그대로 노출하지 않는다', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(createApiParametersProvider(fetchImpl).listFuelTypes()).rejects.toThrow(
      '서버에 연결하지 못했습니다.',
    )
  })
})

/**
 * 규정 연도 조회 (`API_SPEC §7.1` · `#534`).
 *
 * 여기서 고정하는 것은 **연도 숫자만 나가는 것**이다. `z_factor_percent`를 함께
 * 실어 내보내면 화면이 그 값으로 `required_cii`를 계산할 수 있게 되고, 그것은
 * `referenceTable.ts`가 *"이 값으로 다른 선박·연도를 계산하지 말 것"* 으로 막아 둔
 * 상태를 되돌리는 일이다.
 */
const YEARS_BODY = {
  data: [
    { year: 2026, z_factor_percent: '11.0000', effective_from: '2026-01-01' },
    { year: 2023, z_factor_percent: '5.0000', effective_from: '2023-01-01' },
  ],
  meta: { total: 2 },
}

describe('규정 연도 조회', () => {
  it('GET /parameters/regulation-years 를 부른다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(YEARS_BODY))
    await createApiParametersProvider(fetchImpl).listRegulationYears()

    expect(String(fetchImpl.mock.calls[0][0])).toBe('/api/v1/parameters/regulation-years')
  })

  it('연도 숫자만 오름차순으로 준다 — Z계수는 화면으로 나가지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(YEARS_BODY))
    const rows = await createApiParametersProvider(fetchImpl).listRegulationYears()

    expect(rows).toEqual([2023, 2026])
  })

  it('응답이 깨져도 빈 목록을 준다 — 화면이 죽지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: 'nope' }))
    const rows = await createApiParametersProvider(fetchImpl).listRegulationYears()

    expect(rows).toEqual([])
  })

  it('HTTP 오류는 ParametersError다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 503))

    await expect(
      createApiParametersProvider(fetchImpl).listRegulationYears(),
    ).rejects.toBeInstanceOf(ParametersError)
  })
})
