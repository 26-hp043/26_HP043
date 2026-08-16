import { describe, expect, it } from 'vitest'
import {
  daysToDText,
  isAtRisk,
  relativeTime,
  riskReasonText,
  soonestDaysToD,
  sortVessels,
  underwayStateText,
  warningBannerText,
} from './fleetRules'
import type { FleetVessel } from './types'

/**
 * 표시 규칙 테스트.
 *
 * 위험 판정·집계는 서버(`#350`)가 하므로 여기서 검증하지 않는다. 이 파일이 보는 것은
 * **화면이 서버 값을 어떻게 읽고 표시하는가**다 — 특히 「값이 없는 것」을 잘못 말하지
 * 않는지.
 */

function vessel(over: Partial<FleetVessel> = {}): FleetVessel {
  return {
    id: 'v',
    name: 'MV Test',
    shipType: 'BULK_CARRIER',
    imoNumber: '9100001',
    underwayState: 'UNDER_WAY',
    detailStatus: 'SAILING',
    lat: '35.1',
    lon: '129.0',
    positionUpdatedAt: null,
    dataAvailable: true,
    ytdAttainedCii: '5.0000',
    ytdRequiredCii: '5.0450',
    ytdRating: 'C',
    riskLevel: 'MEDIUM',
    riskReasons: [],
    daysToD: null,
    daysToDReason: 'NOT_THIS_YEAR',
    ...over,
  }
}

describe('위험 선박 — 서버 판정을 그대로 쓴다', () => {
  it('riskReasons가 비면 위험 선박이 아니다', () => {
    expect(isAtRisk(vessel())).toBe(false)
  })

  it('riskReasons가 있으면 위험 선박이다', () => {
    expect(isAtRisk(vessel({ riskReasons: ['E_THIS_YEAR'] }))).toBe(true)
  })

  it('등급으로 재판정하지 않는다', () => {
    // E등급이어도 서버가 사유를 주지 않았으면 위험 선박으로 표시하지 않는다.
    // 두 곳에서 판정하면 반드시 어긋난다.
    expect(isAtRisk(vessel({ ytdRating: 'E', riskReasons: [] }))).toBe(false)
  })

  it('사유 문구가 규제 용어를 쓴다', () => {
    expect(riskReasonText('E_THIS_YEAR')).toContain('SEEMP Part III')
    expect(riskReasonText('D_THIRD_YEAR')).toContain('SEEMP Part III')
  })
})

describe('경고 배너 — PRD §6.3 확정 문구', () => {
  it('위험 선박이 있으면 확정 문구를 그대로 쓴다', () => {
    expect(warningBannerText(2)).toBe('시정조치계획 대상 위험 선박 2척')
  })

  it('위험 선박이 없으면 배너를 표시하지 않는다', () => {
    // 0척 배너를 상시 띄우면 경고가 배경이 되어 의미를 잃는다.
    expect(warningBannerText(0)).toBeNull()
  })
})

describe('「D등급 진입까지」 문구', () => {
  it('숫자가 있으면 일수를 쓴다', () => {
    expect(daysToDText(12, null)).toBe('D등급까지 12일')
  })

  it('0일과 「산정 못 함」을 구분한다', () => {
    // 숫자를 못 낸 것과 0일인 것은 다르다 — 같은 문구를 쓰면 안 된다.
    expect(daysToDText(0, null)).toBe('D등급까지 0일')
    expect(daysToDText(null, 'NO_DATA')).not.toBe('D등급까지 0일')
  })

  it('정박 중에는 산정하지 않는다고 말한다', () => {
    expect(daysToDText(null, 'NOT_UNDER_WAY')).toContain('산정 안 함')
  })

  it('이미 D 이하인 경우', () => {
    expect(daysToDText(null, 'ALREADY_AT_OR_BELOW')).toBe('D등급 이하')
  })

  it('올해 중 진입하지 않는 경우', () => {
    expect(daysToDText(null, 'NOT_THIS_YEAR')).toBe('올해 중 진입 없음')
  })

  it('사유가 없으면 실적 없음으로 본다', () => {
    expect(daysToDText(null, null)).toBe('실적 없음')
  })
})

describe('운항 상태 문구', () => {
  it('운항 중', () => {
    expect(underwayStateText(vessel({ underwayState: 'UNDER_WAY' }))).toBe('운항 중')
  })

  it('정박 중', () => {
    expect(underwayStateText(vessel({ underwayState: 'NOT_UNDER_WAY' }))).toBe('정박 중')
  })

  it('상태 미기록을 「정박」으로 적지 않는다', () => {
    // 기록이 없는 것을 정박으로 쓰면 없는 사실을 만들어 내는 것이다.
    expect(underwayStateText(vessel({ underwayState: null }))).toBe('상태 미기록')
  })
})

describe('정렬', () => {
  const plain = vessel({ id: 'a', name: 'MV Alpha', ytdRating: 'A' })
  const risky = vessel({ id: 'r', name: 'MV Zulu', ytdRating: 'D', riskReasons: ['D_THIRD_YEAR'] })
  const worse = vessel({ id: 'w', name: 'MV Bravo', ytdRating: 'E' })
  const nodata = vessel({ id: 'n', name: 'MV Nodata', ytdRating: null, dataAvailable: false })

  it('위험도순은 규제 트리거 선박을 맨 앞에 둔다', () => {
    // 이 화면의 목적이 위험 선박 식별이라, E등급보다 규제 트리거가 앞선다.
    expect(sortVessels([plain, worse, risky], 'risk')[0].id).toBe('r')
  })

  it('트리거가 같으면 나쁜 등급이 앞선다', () => {
    expect(sortVessels([plain, worse], 'risk').map((v) => v.id)).toEqual(['w', 'a'])
  })

  it('실적 없는 선박은 나쁜 등급으로 취급하지 않는다', () => {
    // 등급이 없다고 맨 앞에 오면 「가장 위험한 배」로 읽힌다.
    const sorted = sortVessels([nodata, worse], 'risk')
    expect(sorted[0].id).toBe('w')
  })

  it('이름순', () => {
    expect(sortVessels([risky, plain, worse], 'name').map((v) => v.name)).toEqual([
      'MV Alpha',
      'MV Bravo',
      'MV Zulu',
    ])
  })

  it('원본 배열을 바꾸지 않는다', () => {
    const input = [plain, worse, risky]
    sortVessels(input, 'risk')
    expect(input.map((v) => v.id)).toEqual(['a', 'w', 'r'])
  })
})

describe('가장 임박한 D등급 진입', () => {
  it('여러 척이면 가장 짧은 것을 고른다', () => {
    const result = soonestDaysToD([
      vessel({ id: '1', name: 'A', daysToD: 30, daysToDReason: null }),
      vessel({ id: '2', name: 'B', daysToD: 7, daysToDReason: null }),
    ])
    expect(result).toEqual({ name: 'B', days: 7 })
  })

  it('숫자가 없는 선박은 건너뛴다', () => {
    const result = soonestDaysToD([
      vessel({ daysToD: null, daysToDReason: 'NOT_UNDER_WAY' }),
      vessel({ id: '2', name: 'B', daysToD: 5, daysToDReason: null }),
    ])
    expect(result).toEqual({ name: 'B', days: 5 })
  })

  it('아무도 없으면 null', () => {
    expect(soonestDaysToD([vessel({ daysToD: null, daysToDReason: 'NO_DATA' })])).toBeNull()
  })
})

describe('기준 시각 표시', () => {
  const base = new Date('2026-08-16T12:00:00Z')

  it('1분 미만은 「방금」', () => {
    expect(relativeTime('2026-08-16T11:59:30Z', base)).toBe('방금')
  })

  it('분 단위', () => {
    expect(relativeTime('2026-08-16T11:58:00Z', base)).toBe('2분 전')
  })

  it('시간 단위', () => {
    expect(relativeTime('2026-08-16T09:00:00Z', base)).toBe('3시간 전')
  })

  it('일 단위', () => {
    expect(relativeTime('2026-08-14T12:00:00Z', base)).toBe('2일 전')
  })
})
