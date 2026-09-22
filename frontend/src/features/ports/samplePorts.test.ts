import { describe, expect, it, vi } from 'vitest'
import {
  portDisplayName,
  distanceInput,
  fetchSamplePorts,
  matchSamplePort,
  portOptionLabel,
  type SamplePort,
  LOOKUP_FAILED_FALLBACK,
  LOOKUP_SOURCE_NOTICE,
  lookupPort,
  fetchGreatCircleNm,
  greatCircleDistanceNm,
  greatCircleQuery,
} from './samplePorts'

/**
 * 샘플 항만 입력 규칙 (#760 · `PRD §15.1`).
 *
 * **정확히 같을 때만 좌표를 붙인다.** 비슷한 이름을 추측하면 사용자가 다른 항을 뜻했을 때
 * 틀린 좌표가 조용히 저장된다.
 */
const BUSAN: SamplePort = {
  locode: 'KRPUS',
  name: 'BUSAN',
  name_ko: '부산',
  country_code: 'KR',
  lat: 35.1,
  lon: 129.0333,
}
const PORTS = [BUSAN]

describe('matchSamplePort', () => {
  it('영문 이름은 대소문자를 가리지 않는다 — 데모 시드의 BUSAN과 입력 Busan은 같은 항이다', () => {
    expect(matchSamplePort(PORTS, 'Busan')).toBe(BUSAN)
    expect(matchSamplePort(PORTS, '  BUSAN ')).toBe(BUSAN)
  })

  it('한국어 이름으로도 고른다', () => {
    expect(matchSamplePort(PORTS, '부산')).toBe(BUSAN)
  })

  it('비슷한 이름은 추측하지 않는다 — 틀린 좌표가 조용히 저장되지 않게', () => {
    expect(matchSamplePort(PORTS, 'Busan New Port')).toBeNull()
    expect(matchSamplePort(PORTS, 'BUS')).toBeNull()
    expect(matchSamplePort(PORTS, '')).toBeNull()
  })
})

describe('표시', () => {
  it('선택지 한 줄은 「한국어 이름 · 국가」다', () => {
    expect(portOptionLabel(BUSAN)).toBe('부산 · KR')
  })

  it('추정 거리는 소수 2자리로 칸에 들어간다 — 저장 컬럼이 NUMERIC(12,2)다', () => {
    expect(distanceInput(2470.2)).toBe('2470.20')
  })
})

describe('fetchSamplePorts (#1005 — 세 화면이 같은 경로로 받는다)', () => {
  function respond(body: unknown, status = 200) {
    return vi.fn(async () => ({ ok: status < 400, status, json: async () => body }) as Response)
  }

  it('GET /ports/samples를 세션 쿠키와 함께 부른다', async () => {
    const fetchImpl = respond({ data: [BUSAN] })
    expect(await fetchSamplePorts(fetchImpl as unknown as typeof fetch, '/api/v1')).toEqual([BUSAN])
    const [url, init] = (fetchImpl.mock.calls as unknown as Array<[string, RequestInit]>)[0]
    expect(url).toBe('/api/v1/ports/samples')
    expect(init.credentials).toBe('include')
  })

  it('모양이 계약과 다르거나 HTTP가 실패하면 던진다 — 「없다」와 「못 받았다」를 가른다', async () => {
    await expect(
      fetchSamplePorts(respond({ data: [{ name: 'BUSAN' }] }) as unknown as typeof fetch, ''),
    ).rejects.toThrow('계약과 다릅니다')
    await expect(fetchSamplePorts(respond({}, 500) as unknown as typeof fetch, '')).rejects.toThrow(
      'HTTP 500',
    )
  })
})


describe('lookupPort (#768 — 목록 밖 항만의 좌표)', () => {
  function respond(body: unknown, status = 200) {
    return vi.fn(async () => ({ ok: status < 400, status, json: async () => body }) as Response)
  }

  it('이름을 URL 인코딩해 GET /ports/lookup을 부른다', async () => {
    const fetchImpl = respond({ data: { name: 'PORT KLANG', lat: 3, lon: 101.4, source: 'LOOKUP' } })

    const result = await lookupPort('PORT KLANG', fetchImpl as unknown as typeof fetch, '/api/v1')

    expect(result).toEqual({
      ok: true,
      port: { name: 'PORT KLANG', lat: 3, lon: 101.4, source: 'LOOKUP' },
    })
    const [url, init] = (fetchImpl.mock.calls as unknown as Array<[string, RequestInit]>)[0]
    expect(url).toBe('/api/v1/ports/lookup?name=PORT%20KLANG')
    expect(init.credentials).toBe('include')
  })

  it('찾지 못하면 **서버 문구를 그대로** 돌려준다 — 화면이 문장을 만들지 않는다', async () => {
    const fetchImpl = respond({ error: { message: '그 이름으로 항만을 찾지 못했습니다.' } }, 404)

    const result = await lookupPort('없는항만', fetchImpl as unknown as typeof fetch, '')

    expect(result).toEqual({ ok: false, message: '그 이름으로 항만을 찾지 못했습니다.' })
  })

  it('네트워크가 죽어도 던지지 않는다 — 좌표가 없어도 항차는 만들 수 있어야 한다', async () => {
    const dead = vi.fn(async () => {
      throw new Error('offline')
    })

    const result = await lookupPort('BUSAN', dead as unknown as typeof fetch, '')

    expect(result).toEqual({ ok: false, message: LOOKUP_FAILED_FALLBACK })
  })

  it('출처 문구는 사용자가 할 일로 둘로 갈린다 — 검증된 목록 / 확인이 필요한 지도 조회 (#1052 ⑷)', () => {
    // 캐시는 전에 지도 서비스에서 받아 둔 값이다 — 방금 조회한 것과 같은 말을 해야 한다.
    expect(LOOKUP_SOURCE_NOTICE.CACHE).toBe(LOOKUP_SOURCE_NOTICE.LOOKUP)
    expect(LOOKUP_SOURCE_NOTICE.SAMPLE).not.toBe(LOOKUP_SOURCE_NOTICE.LOOKUP)
    expect(LOOKUP_SOURCE_NOTICE.SAMPLE).not.toBe('')
  })
})

/** 보이는 이름 (#1742) — 저장값은 영문 대문자, 화면은 한글이다. */
describe('portDisplayName', () => {
  const PORTS = [
    { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    { locode: 'SGKEP', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
  ]

  it('목록에 있으면 보이는 이름으로 바꾼다', () => {
    expect(portDisplayName(PORTS, 'BUSAN')).toBe('부산')
    expect(portDisplayName(PORTS, 'SINGAPORE')).toBe('싱가포르')
  })

  it('⚠️ 목록에 없으면 입력한 그대로다 — 없는 이름을 지어내지 않는다', () => {
    expect(portDisplayName(PORTS, 'ULSAN')).toBe('ULSAN')
    expect(portDisplayName(PORTS, '군산')).toBe('군산')
  })

  it('목록을 못 받았으면 저장값 그대로다', () => {
    expect(portDisplayName([], 'BUSAN')).toBe('BUSAN')
  })

  it('이미 한글로 저장된 값도 그대로 선다 — 두 번 바꾸지 않는다', () => {
    expect(portDisplayName(PORTS, '부산')).toBe('부산')
  })
})

/*
 * 좌표 기반 추정 거리의 **계약**을 이 파일이 소유한다 (#1750).
 *
 * 같은 엔드포인트를 항차 추가 폼(#760)과 항로 비교가 부른다. 인자 이름이나 응답 필드가
 * 한쪽에서만 바뀌면 그 화면만 조용히 깨지므로, 질의와 응답 읽기를 여기 한 벌만 둔다.
 */
describe('좌표 기반 추정 거리 — GET /ports/great-circle (#1750)', () => {
  const FROM = { lat: 35.1, lon: 129.0333 }
  const TO = { lat: 1.2833, lon: 103.85 }

  it('질의는 `API_SPEC §3.9`의 네 인자다', () => {
    const query = greatCircleQuery(FROM, TO)
    expect(query).toBe('from_lat=35.1&from_lon=129.0333&to_lat=1.2833&to_lon=103.85')
  })

  it('응답에서 거리를 꺼낸다 — 계약과 다르면 null이다', () => {
    expect(greatCircleDistanceNm({ data: { distance_nm: 2504.62 } })).toBe(2504.62)
    // 문자열은 숫자가 아니다. 삼키면 `NaN`이 거리 칸에 들어간다.
    expect(greatCircleDistanceNm({ data: { distance_nm: '2504.62' } })).toBeNull()
    expect(greatCircleDistanceNm({ data: {} })).toBeNull()
    expect(greatCircleDistanceNm(null)).toBeNull()
  })

  it('받은 거리를 그대로 돌려준다 — 화면에서 다시 계산하지 않는다', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ data: { distance_nm: 2504.62 } }),
    })) as unknown as typeof fetch

    expect(await fetchGreatCircleNm(FROM, TO, fetchImpl, '/api/v1')).toBe(2504.62)
    expect(String((fetchImpl as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0])).toBe(
      `/api/v1/ports/great-circle?${greatCircleQuery(FROM, TO)}`,
    )
  })

  it('실패와 계약 위반을 가려 던진다 — 빈 값으로 삼키지 않는다', async () => {
    const failing = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({}),
    })) as unknown as typeof fetch
    await expect(fetchGreatCircleNm(FROM, TO, failing, '/api/v1')).rejects.toThrow(
      '추정 거리를 받지 못했습니다.',
    )

    const malformed = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ data: {} }),
    })) as unknown as typeof fetch
    await expect(fetchGreatCircleNm(FROM, TO, malformed, '/api/v1')).rejects.toThrow(
      '추정 거리 응답이 계약과 다릅니다.',
    )
  })
})
