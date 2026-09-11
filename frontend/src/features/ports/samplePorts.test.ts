import { describe, expect, it, vi } from 'vitest'
import {
  distanceInput,
  fetchSamplePorts,
  matchSamplePort,
  portOptionLabel,
  type SamplePort,
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

