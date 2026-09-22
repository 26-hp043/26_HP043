import { describe, expect, it, vi } from 'vitest'
import { ParametersError } from '../../api/parameters'
import { createApiReferenceParametersProvider } from './referenceApiProvider'

/**
 * 규제 기준값 표 조회 provider (`API_SPEC §7.1~§7.4` · `#1516`).
 *
 * 고정하는 것은 셋이다.
 *
 * * **숫자 필드를 문자열 그대로 둔다** — 이 절은 규제 상수를 원문과 대조하는 자리라
 *   `Number`로 되돌리거나 자릿수를 맞추면 근거가 아닌 것을 보여 주게 된다(`#1239` 결정 G).
 * * **`?active=`를 명시적으로 보낸다** — 「이전 판본 포함」이 `active=false`다.
 * * **`version`·`is_active`가 없어도 깨지지 않는다** — `#1515`가 더하는 필드라 그 PR이
 *   먼저 머지되지 않은 서버에서도 활성으로 그려진다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const YEARS = {
  data: [
    {
      year: 2026,
      z_factor_percent: '11.0',
      effective_from: '2026-01-01',
      source_ref: 'MEPC.400(83)',
      version: '2025-q2',
      is_active: true,
    },
    {
      year: 2026,
      z_factor_percent: '9.00',
      effective_from: '2026-01-01',
      source_ref: 'MEPC.338(76)',
      version: '2024-q1',
      is_active: false,
    },
  ],
  meta: { total: 2 },
}

const LINES = {
  data: [
    {
      ship_type: 'LNG_CARRIER',
      condition_expr: 'DWT < 65000',
      capacity_rule: 'fixed 65000',
      a_raw: '14779E10',
      a_decimal: '147790000000000',
      c: '2.673000',
      source_ref: 'MEPC.353(78)',
    },
  ],
  meta: { total: 1 },
}

describe('규제 기준값 표 조회 (#1516)', () => {
  it('기본 조회는 `active=true`, 「이전 판본 포함」은 `active=false`다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(YEARS))
    const provider = createApiReferenceParametersProvider(fetchImpl)

    await provider.listRegulationYears()
    await provider.listRegulationYears({ includeInactive: true })
    await provider.listReferenceLines({ includeInactive: true })
    await provider.listRatingBoundaries({ includeInactive: true })

    const urls = fetchImpl.mock.calls.map(([u]) => new URL(String(u), 'https://x'))
    expect(urls[0].pathname).toBe('/api/v1/parameters/regulation-years')
    expect(urls[0].searchParams.get('active')).toBe('true')
    expect(urls[1].searchParams.get('active')).toBe('false')
    expect(urls[2].pathname).toBe('/api/v1/parameters/reference-lines')
    expect(urls[2].searchParams.get('active')).toBe('false')
    expect(urls[3].pathname).toBe('/api/v1/parameters/rating-boundaries')
    expect(urls[3].searchParams.get('active')).toBe('false')
  })

  it('연료는 `active`를 보내지 않는다 — 지금 서버의 `active=false`는 「비활성만」이다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: [] }))
    await createApiReferenceParametersProvider(fetchImpl).listFuelTypes()

    const url = new URL(String(fetchImpl.mock.calls[0][0]), 'https://x')
    expect(url.pathname).toBe('/api/v1/parameters/fuel-types')
    expect(url.searchParams.has('active')).toBe(false)
  })

  it('숫자 필드를 서버 문자열 그대로 둔다 — 자릿수도 표기도 바꾸지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(LINES))
    const [row] = await createApiReferenceParametersProvider(fetchImpl).listReferenceLines()

    expect(row.aRaw).toBe('14779E10')
    expect(row.aDecimal).toBe('147790000000000')
    // `2.673000` → `2.673`으로 정규화되면 원문 대조에서 자릿수가 사라진다.
    expect(row.c).toBe('2.673000')
    expect(typeof row.c).toBe('string')
  })

  it('감축률도 문자열 그대로다 — `9.00`이 `9`가 되지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(YEARS))
    const rows = await createApiReferenceParametersProvider(fetchImpl).listRegulationYears({
      includeInactive: true,
    })

    expect(rows.map((row) => row.zFactorPercent)).toEqual(['11.0', '9.00'])
    expect(rows.map((row) => row.isActive)).toEqual([true, false])
  })

  it('`version`·`is_active`가 없으면 활성으로 본다 — 기본 조회는 활성만 돌려주는 계약이다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(LINES))
    const [row] = await createApiReferenceParametersProvider(fetchImpl).listReferenceLines()

    expect(row.isActive).toBe(true)
    expect(row.version).toBeNull()
  })

  it('본문이 배열이 아니면 빈 목록이다 — 던지지 않는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: { as_of: 'x' } }))
    const provider = createApiReferenceParametersProvider(fetchImpl)

    expect(await provider.listRatingBoundaries()).toEqual([])
    expect(await provider.listFuelTypes()).toEqual([])
  })

  it('HTTP 오류는 서버 문구를 실은 ParametersError다', async () => {
    // `Response` 본문은 한 번만 읽힌다 — 호출마다 새로 만든다.
    const fetchImpl = vi
      .fn()
      .mockImplementation(async () =>
        jsonResponse({ error: { code: 'INTERNAL_ERROR', message: '서버 문구' } }, 500),
      )

    await expect(createApiReferenceParametersProvider(fetchImpl).listRegulationYears()).rejects.toThrow(
      ParametersError,
    )
    await expect(createApiReferenceParametersProvider(fetchImpl).listRegulationYears()).rejects.toThrow(
      '서버 문구',
    )
  })

  it('네트워크 실패는 연결 문구로 옮긴다', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(createApiReferenceParametersProvider(fetchImpl).listFuelTypes()).rejects.toThrow(
      '서버에 연결하지 못했습니다.',
    )
  })
})
