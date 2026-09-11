import { describe, expect, it } from 'vitest'
import { distanceInput, matchSamplePort, portOptionLabel, type SamplePort } from './samplePorts'

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
