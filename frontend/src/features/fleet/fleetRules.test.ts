import { describe, expect, it } from 'vitest'
import {
  daysToDText,
  distributionAria,
  distributionSlots,
  gradeDistributionSegments,
  showsInlineLabel,
  usesPictogram,
  PICTOGRAM_MAX_VESSELS,
  zeroRatings,
  isAtRisk,
  missingGrossTonnageCount,
  relativeTime,
  riskReasonText,
  soonestDaysToD,
  sortVessels,
  unavailableHint,
  unavailableText,
  underwayStateText,
  warningBannerText,
  ytdCiiText,
} from './fleetRules'
import { DISPLAY_DIGITS } from '../../display/format'
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
    isCiiApplicableHint: true,
    grossTonnage: 30000,
    dataAvailable: true,
    ytdAttainedCii: '5.0000',
    ytdRequiredCii: '5.0450',
    ytdRating: 'C',
    riskLevel: 'MEDIUM',
    riskReasons: [],
    unavailableReason: null,
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
    // 정본 문구 (PRD §6.3) — 원문이 확정돼 있다. 바꾸려면 PRD 개정이 먼저다 (AGENTS §4.6).
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

  it('소수를 받아도 §4.2 자릿수로 접는다', () => {
    // 서버 계약이 정수를 보장하지 않는다. 규정이 없던 동안에는 값을 그대로
    // 끼워 넣어 `12.4일`이 카드에 나갈 자리였다 (#592).
    expect(daysToDText(12.4, null)).toBe('D등급까지 12일')
    expect(daysToDText(12.5, null)).toBe('D등급까지 13일')
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

  it('올해 중 진입하지 않는 경우 — 숫자를 내지 않는다', () => {
    // 지키려는 것은 문구가 아니라 「숫자를 만들지 않는 것」이다. 숫자를 내면
    // 「곧 진입한다」로 읽힌다.
    expect(daysToDText(null, 'NOT_THIS_YEAR')).not.toMatch(/\d/)
  })

  it('사유가 저마다 다른 말을 한다 — 같은 문구로 뭉치지 않는다', () => {
    const texts = (['ALREADY_AT_OR_BELOW', 'NOT_THIS_YEAR', 'NOT_UNDER_WAY', null] as const).map(
      (reason) => daysToDText(null, reason),
    )
    expect(new Set(texts).size).toBe(texts.length)
  })
})

describe('값이 없는 사유 문구 (#419)', () => {
  it('제원 미입력과 실적 없음을 다르게 말한다', () => {
    // 같은 문구로 쓰면 화면이 무엇을 하라고 말할 수 없다 — 항차 등록과 제원 입력은
    // 서로 다른 일이다.
    expect(unavailableText('MISSING_SPEC')).not.toBe(unavailableText('NO_DATA'))
  })

  it('제원 미입력에는 제원을 채우라고 안내한다', () => {
    expect(unavailableHint('MISSING_SPEC')).toContain('제원')
  })

  it('실적 없음에는 항차를 등록하라고 안내한다', () => {
    expect(unavailableHint('NO_DATA')).toContain('항차')
  })

  it('기준값 없음에는 항차 등록을 시키지 않는다', () => {
    // 사용자가 해도 풀리지 않는 일을 안내하면 안 된다 — 운영자 몫이다.
    expect(unavailableHint('NO_PARAMETERS')).not.toContain('항차를 등록')
    expect(unavailableHint('NO_PARAMETERS')).toContain('운영자')
  })

  it('계산 실패도 사용자에게 항차 등록을 시키지 않는다', () => {
    expect(unavailableHint('CALCULATION_ERROR')).not.toContain('항차를 등록')
    expect(unavailableHint('CALCULATION_ERROR')).toContain('운영자')
  })

  it('사유를 모르면 「실적 없음」 쪽으로 본다 — 가장 흔하고 가장 덜 단정적이다', () => {
    // 모르는 사유를 「제원 미입력」·「기준값 없음」으로 단정하면 하지 않아도 될 일을
    // 시키게 된다.
    expect(unavailableText(null)).toBe(unavailableText('NO_DATA'))
    expect(unavailableText(null)).not.toBe(unavailableText('MISSING_SPEC'))
  })
})

describe('운항 상태 문구', () => {
  it('세 상태가 서로 다른 말을 한다', () => {
    const texts = [
      underwayStateText(vessel({ underwayState: 'UNDER_WAY' })),
      underwayStateText(vessel({ underwayState: 'NOT_UNDER_WAY' })),
      underwayStateText(vessel({ underwayState: null })),
    ]
    expect(new Set(texts).size).toBe(3)
    expect(texts.every((text) => text.length > 0)).toBe(true)
  })

  it('상태 미기록을 「정박」으로 적지 않는다', () => {
    // **이 파일에서 가장 중요한 단언**이다. 기록이 없는 것을 정박으로 쓰면 없는 사실을
    // 만들어 내는 것이다. 문구가 바뀌어도 이 성질은 유지돼야 한다.
    expect(underwayStateText(vessel({ underwayState: null }))).not.toBe(
      underwayStateText(vessel({ underwayState: 'NOT_UNDER_WAY' })),
    )
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

  it('1분 미만에는 숫자를 붙이지 않는다', () => {
    // 「0분 전」은 지난 시간을 아는 것처럼 보이지만 실제로는 반올림 결과다.
    expect(relativeTime('2026-08-16T11:59:30Z', base)).not.toMatch(/\d/)
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

/**
 * YTD CII 표시 자릿수 — `DESIGN_SYSTEM §4.1` 🔒.
 *
 * 대시보드는 서버 원본을 그대로 내보내 **소수 4자리**로 그리고 있었다(`8.9799`).
 * 선박 상세·실시간 CII에서 같은 병이 이미 두 번 나왔다 — 값이 문자열이라 그냥
 * 꽂으면 화면이 멀쩡해 보이는 것이 원인이다.
 *
 * `AGENTS §4.6`에 따라 문구는 리터럴로 단언하지 않는다. 다만 자릿수는 `§4.1`이
 * 확정한 값이므로 자릿수 자체는 단언한다.
 */
describe('YTD CII 표시 — DESIGN_SYSTEM §4.1', () => {
  const decimals = (s: string) => {
    const dot = s.indexOf('.')
    return dot === -1 ? 0 : s.length - dot - 1
  }

  it('원본 자릿수와 무관하게 항상 소수 3자리다', () => {
    // 서버는 4자리(대시보드)·6자리(상세)로 준다. 자리수가 화면마다 달라지면
    // §4.1이 「정렬 붕괴」로 막으려던 상태가 그대로 생긴다.
    for (const raw of ['8.9799', '21.7250', '19.1631', '18.6343', '5.045066', '7']) {
      expect(decimals(ytdCiiText(raw))).toBe(DISPLAY_DIGITS.cii)
    }
  })

  it('반올림한다 — 잘라 내지 않는다', () => {
    // 절사하면 실제보다 낮게 보이고, 등급 경계 부근에서 잘못 읽힌다(§4.1).
    expect(ytdCiiText('8.9799')).toBe('8.980')
    expect(ytdCiiText('21.7250')).toBe('21.725')
  })

  it('천단위 구분자를 넣지 않는다', () => {
    // CII는 GROUPED_FIELDS가 아니다 — 구분자는 소수부 정렬을 방해한다(§4.2).
    expect(ytdCiiText('1234.5678')).not.toContain(',')
  })

  it('값이 없으면 포매터를 부르지 않고 빈 자리 표시를 낸다', () => {
    // 포매터는 십진 문자열이 아니면 던진다. null을 그대로 넘기면 화면이 죽는다.
    expect(() => ytdCiiText(null)).not.toThrow()
    expect(decimals(ytdCiiText(null))).toBe(0)
  })

  it('실적 없는 선박(dataAvailable=false)의 값도 안전하다', () => {
    const v = vessel({ dataAvailable: false, ytdAttainedCii: null })
    expect(() => ytdCiiText(v.ytdAttainedCii)).not.toThrow()
  })
})

describe('등급 분포 스택 바', () => {
  const dist = (over: Partial<Record<'A' | 'B' | 'C' | 'D' | 'E', number>> = {}) => ({
    A: 0, B: 0, C: 0, D: 0, E: 0, ...over,
  })

  it('0척인 등급은 구간을 만들지 않는다 — 폭 0인 조각은 그릴 수 없다', () => {
    const segments = gradeDistributionSegments(dist({ B: 1, D: 1, E: 2 }))
    expect(segments.map((s) => s.rating)).toEqual(['B', 'D', 'E'])
  })

  it('감추는 것이 아니라 형태를 바꾼다 — 0척인 등급을 따로 낸다', () => {
    // 「A등급이 한 척도 없다」는 것 자체가 정보다.
    expect(zeroRatings(dist({ B: 1, D: 1, E: 2 }))).toEqual(['A', 'C'])
  })

  it('분모는 집계된 선박 수다', () => {
    const segments = gradeDistributionSegments(dist({ B: 1, D: 1, E: 2 }))
    expect(segments.find((s) => s.rating === 'E')?.percent).toBe(50)
    expect(segments.reduce((sum, s) => sum + s.percent, 0)).toBeCloseTo(100)
  })

  it('등급이 하나도 없으면 빈 배열이다 — 회색 막대를 그리지 않는다', () => {
    expect(gradeDistributionSegments(dist())).toEqual([])
  })

  it('A→E 순서를 지킨다 — 등급 램프와 같은 방향이어야 한다', () => {
    const segments = gradeDistributionSegments(dist({ E: 1, A: 1, C: 1 }))
    expect(segments.map((s) => s.rating)).toEqual(['A', 'C', 'E'])
  })

  it('§10.2의 8% 임계를 그대로 쓴다 — 경계를 포함한다', () => {
    // 형태가 같은 바가 화면마다 다른 폭에서 글자를 감추면 안 된다.
    expect(showsInlineLabel(8)).toBe(true)
    expect(showsInlineLabel(7.99)).toBe(false)
  })

  it('좁은 구간의 값이 접근성 트리에서 사라지지 않는다', () => {
    const segments = gradeDistributionSegments(dist({ A: 1, E: 99 }))
    expect(distributionAria(segments)).toContain('A등급 1척')
    expect(showsInlineLabel(segments[0].percent)).toBe(false)
  })

  it('집계된 등급이 없으면 그 사실을 말한다', () => {
    expect(distributionAria([])).toContain('없습니다')
  })
})

describe('픽토그램 ↔ 막대 전환', () => {
  const segs = (count: number) => [{ rating: 'C' as const, count, percent: 100 }]

  it('스무 척 남짓까지는 배 그림으로 센다', () => {
    expect(usesPictogram(segs(4))).toBe(true)
    expect(usesPictogram(segs(PICTOGRAM_MAX_VESSELS))).toBe(true)
  })

  it('그 위로는 막대로 돌아간다 — 세는 것이 일이 되면 픽토그램은 진다', () => {
    expect(usesPictogram(segs(PICTOGRAM_MAX_VESSELS + 1))).toBe(false)
  })

  it('등급이 갈려도 합계로 판단한다 — 화면에 놓이는 마크 수가 기준이다', () => {
    const spread = [
      { rating: 'B' as const, count: 10, percent: 40 },
      { rating: 'D' as const, count: 10, percent: 40 },
      { rating: 'E' as const, count: 5, percent: 20 },
    ]
    expect(spread.reduce((s, x) => s + x.count, 0)).toBe(25)
    expect(usesPictogram(spread)).toBe(false)
  })
})

describe('GT 미입력 척수', () => {
  const ship = (grossTonnage: FleetVessel['grossTonnage']) =>
    ({ grossTonnage }) as FleetVessel

  it('`null`과 빈 문자열을 세지 않은 것으로 본다', () => {
    expect(missingGrossTonnageCount([ship(null), ship(''), ship(25000)])).toBe(2)
  })

  /*
   * 숫자로 바꿔 판정하면 `Number('')`이 `0`이라 **GT 0인 배와 구분이 사라진다.**
   * 0은 「없다」가 아니라 「0으로 적혀 있다」이고, 둘은 다른 상태다.
   */
  it('GT 0은 미입력이 아니다', () => {
    expect(missingGrossTonnageCount([ship(0), ship('0')])).toBe(0)
  })

  it('문자열로 온 값도 입력된 것으로 본다 — 서버가 소수를 문자열로 내린다', () => {
    expect(missingGrossTonnageCount([ship('25000.5')])).toBe(0)
  })
})

describe('등급 자리 — 픽토그램용', () => {
  /* 위 describe의 `dist`는 그 블록 안에 갇혀 있다. 같은 형태로 다시 만든다. */
  const dist = (over: Partial<Record<'A' | 'B' | 'C' | 'D' | 'E', number>> = {}) => ({
    A: 0,
    B: 0,
    C: 0,
    D: 0,
    E: 0,
    ...over,
  })

  it('다섯 등급을 A→E 순서로, 0척까지 낸다', () => {
    expect(distributionSlots(dist({ B: 1, D: 1, E: 2 }))).toEqual([
      { rating: 'A', count: 0 },
      { rating: 'B', count: 1 },
      { rating: 'C', count: 0 },
      { rating: 'D', count: 1 },
      { rating: 'E', count: 2 },
    ])
  })

  /*
   * 막대는 폭 0인 조각을 그릴 수 없어 0척을 뺀다(`gradeDistributionSegments`).
   * 픽토그램은 자리를 차지하지 않고도 적을 수 있어 **판단이 갈린다** — 둘이
   * 같은 목록을 쓰면 한쪽이 반드시 틀린다.
   */
  it('막대용 구간과 다르다 — 0척을 뺀 쪽과 섞이지 않는다', () => {
    const distribution = dist({ B: 1, D: 1, E: 2 })
    expect(distributionSlots(distribution)).toHaveLength(5)
    expect(gradeDistributionSegments(distribution)).toHaveLength(3)
  })
})
