import { describe, expect, it } from 'vitest'
import {
  DISPLAY_DIGITS,
  formatDecimalString,
  formatGrouped,
} from '../../display/format'
import {
  POLL_INTERVAL_MS,
  RATING_TRANSITION_TEXT,
  formatOrNull,
  isDegradingAtBerth,
  isNotUnderWay,
  projectionDirection,
  projectionReason,
  ratingTransition,
  remainingDistanceNm,
  voyageProgressRatio,
  warningText,
} from './realtimeRules'
import type { RealtimeCii } from './types'

/**
 * 실시간 CII 화면 규칙 (`#357`).
 *
 * 이 화면의 결함은 **방향과 사유**에서 난다.
 *
 * * CII는 **낮을수록 좋다.** 부호를 뒤집어 읽으면 화면이 정반대를 말한다.
 * * 「정박 중」과 「정박이 등급을 밀고 있다」는 다르다. 정박 연료 기록이 없으면
 *   값은 그대로이고, 그때 「악화 중」이라 적으면 사실과 다른 말이 된다.
 * * 「없는 것」은 사유와 함께 말해야 한다. 빈칸은 「로딩 중」으로 읽힌다.
 */

const BASE: RealtimeCii = {
  vesselId: 'v-1',
  vesselName: 'STAR SKIPPER',
  regulationYear: 2026,
  capacityBasis: 'DWT',
  underwayState: 'UNDER_WAY',
  ytd: {
    dataAvailable: true,
    attainedCii: '18.637188',
    requiredCii: '17.374582',
    ratioToRequired: '1.07267',
    rating: 'B',
    riskLevel: 'WATCH',
    marginRatio: '0.09321',
    totalCo2Ton: '620.00',
    totalFuelTon: '199.10',
    underwayDistanceNm: '10620.00',
    notUnderwayDistanceNm: '0.00',
    totalDistanceNm: '10620.00',
    voyageCount: 3,
    notUnderwayPeriodCount: 0,
  },
  currentVoyage: {
    voyageId: 'vy-1',
    voyageNo: '2026-02',
    status: 'IN_PROGRESS',
    departurePortName: 'Busan',
    arrivalPortName: 'Singapore',
    plannedDistanceNm: '3000.00',
    underwayHours: '112.0000',
    distanceNm: '1848.00',
    fuelTon: '140.00',
    fuelType: 'HFO',
    isSimulated: true,
    attainedCii: '4.720000',
    co2Ton: '435.96',
    rating: null,
  },
  projection: {
    dataAvailable: true,
    reason: null,
    attainedCii: '19.500000',
    requiredCii: '17.374582',
    ratioToRequired: '1.12234',
    rating: 'C',
    riskLevel: 'WATCH',
    assumptions: {
      method: 'YTD_DAILY_AVERAGE',
      elapsedDays: '227.73',
      remainingDays: '137.27',
      dailyDistanceNm: '46.63',
      dailyFuelTon: '0.87',
      projectedExtraDistanceNm: '6400.00',
      projectedExtraFuelTon: '120.00',
      fuelType: 'HFO',
    },
  },
  warnings: ['REFERENCE_ONLY'],
  asOf: '2026-08-17T02:00:00+00:00',
  simulated: true,
}

describe('등급 전이 — ⑴ → ⑶', () => {
  const withRatings = (
    from: RealtimeCii['ytd']['rating'],
    to: RealtimeCii['projection']['rating'],
  ): RealtimeCii => ({
    ...BASE,
    ytd: { ...BASE.ytd, rating: from },
    projection: { ...BASE.projection, rating: to },
  })

  it('나빠지는 쪽으로 가면 WORSENING', () => {
    // BASE가 B → C다. E가 최악이라는 방향을 뒤집어 읽으면 여기서 걸린다.
    expect(ratingTransition(BASE)).toEqual({ from: 'B', to: 'C', direction: 'WORSENING' })
  })

  it('좋아지는 쪽으로 가면 IMPROVING', () => {
    expect(ratingTransition(withRatings('D', 'B'))?.direction).toBe('IMPROVING')
  })

  it('같으면 FLAT', () => {
    expect(ratingTransition(withRatings('C', 'C'))?.direction).toBe('FLAT')
  })

  it('A와 E의 방향을 혼동하지 않는다', () => {
    // 문자 비교에 기대면 통과하지만, 순서표를 잘못 적으면 여기서 뒤집힌다.
    expect(ratingTransition(withRatings('A', 'E'))?.direction).toBe('WORSENING')
    expect(ratingTransition(withRatings('E', 'A'))?.direction).toBe('IMPROVING')
  })

  it('연말 예상 등급이 없으면 전이를 만들지 않는다', () => {
    expect(ratingTransition(withRatings('B', null))).toBeNull()
  })

  it('YTD 등급이 없으면 전이를 만들지 않는다', () => {
    expect(ratingTransition(withRatings(null, 'C'))).toBeNull()
  })

  it('연말 예상을 못 낸 응답은 등급이 남아 있어도 전이가 아니다', () => {
    // `dataAvailable: false`인데 rating이 실려 오는 응답을 「등급 유지」로 읽으면
    // 화면이 근거 없이 안심시킨다.
    const noBasis: RealtimeCii = {
      ...BASE,
      projection: { ...BASE.projection, dataAvailable: false, reason: 'NO_BASIS' },
    }
    expect(ratingTransition(noBasis)).toBeNull()
  })

  it('YTD 실적이 없으면 전이가 아니다', () => {
    const noYtd: RealtimeCii = {
      ...BASE,
      ytd: { ...BASE.ytd, dataAvailable: false },
    }
    expect(ratingTransition(noYtd)).toBeNull()
  })

  it('세 방향 모두 라벨 문구를 갖는다', () => {
    // 색 외 보조 채널(§14). 빠진 방향이 있으면 그 상태에서 색만 남는다.
    expect(RATING_TRANSITION_TEXT.WORSENING).toBe('등급 하락 예상')
    expect(RATING_TRANSITION_TEXT.IMPROVING).toBe('등급 상승 예상')
    expect(RATING_TRANSITION_TEXT.FLAT).toBe('등급 유지 예상')
  })

  it('CII 값 방향과 등급 전이는 별개다', () => {
    /*
     * 값은 나빠지는데(18.63 → 19.50) 경계를 넘지 않아 등급은 그대로인 상태.
     * 둘이 한 함수로 합쳐지면 이 구분이 사라진다.
     */
    const sameGrade = withRatings('B', 'B')
    expect(projectionDirection(sameGrade)).toBe('WORSENING')
    expect(ratingTransition(sameGrade)?.direction).toBe('FLAT')
  })
})

describe('폴링', () => {
  it('간격이 문서에 적힌 값과 같다', () => {
    // 값이 바뀌면 이 테스트가 먼저 깨진다 — 근거를 다시 적으라는 뜻이다.
    expect(POLL_INTERVAL_MS).toBe(60_000)
  })
})

describe('정박 판정 — 명세 3-③', () => {
  it('운항 상태만으로 판정한다', () => {
    expect(isNotUnderWay(BASE)).toBe(false)
    expect(isNotUnderWay({ ...BASE, underwayState: 'NOT_UNDER_WAY' })).toBe(true)
  })

  it('진행 중 항차가 없다고 정박으로 보지 않는다', () => {
    // 항차를 아직 등록하지 않은 선박이 전부 정박 중으로 보이면 안 된다.
    expect(isNotUnderWay({ ...BASE, currentVoyage: null })).toBe(false)
  })

  it('상태를 모르면 정박이 아니다 — 모르는 것을 단정하지 않는다', () => {
    expect(isNotUnderWay({ ...BASE, underwayState: null })).toBe(false)
  })

  it('정박 연료 기록이 있어야 「악화 중」이다', () => {
    const berthed = { ...BASE, underwayState: 'NOT_UNDER_WAY' as const }
    // 기록이 없으면 M이 늘지 않아 값이 그대로다 — 「악화 중」은 사실과 다르다.
    expect(isDegradingAtBerth(berthed)).toBe(false)

    const withFuel = {
      ...berthed,
      ytd: { ...berthed.ytd, notUnderwayPeriodCount: 1 },
    }
    expect(isDegradingAtBerth(withFuel)).toBe(true)
  })

  it('항해 중이면 정박 기록이 있어도 「악화 중」이 아니다', () => {
    const sailing = { ...BASE, ytd: { ...BASE.ytd, notUnderwayPeriodCount: 2 } }
    expect(isDegradingAtBerth(sailing)).toBe(false)
  })
})

describe('연말 예상의 방향', () => {
  it('CII가 낮아지면 나아지는 것이다', () => {
    const better = {
      ...BASE,
      projection: { ...BASE.projection, attainedCii: '17.000000' },
    }
    expect(projectionDirection(better)).toBe('IMPROVING')
  })

  it('CII가 높아지면 나빠지는 것이다', () => {
    expect(projectionDirection(BASE)).toBe('WORSENING')
  })

  it('같으면 FLAT이다', () => {
    const flat = {
      ...BASE,
      projection: { ...BASE.projection, attainedCii: BASE.ytd.attainedCii },
    }
    expect(projectionDirection(flat)).toBe('FLAT')
  })

  it('한쪽이 없으면 판정하지 않는다 — 「같음」으로 뭉치면 근거 없이 안심시킨다', () => {
    expect(
      projectionDirection({
        ...BASE,
        projection: { ...BASE.projection, attainedCii: null },
      }),
    ).toBeNull()
    expect(
      projectionDirection({ ...BASE, ytd: { ...BASE.ytd, attainedCii: null } }),
    ).toBeNull()
  })
})

describe('남은 거리·진행률', () => {
  it('계획에서 누적을 뺀다', () => {
    expect(remainingDistanceNm(BASE)).toBe(1152)
  })

  it('계획보다 더 갔으면 0으로 자른다 — 음수는 아무 뜻도 없다', () => {
    const over = {
      ...BASE,
      currentVoyage: { ...BASE.currentVoyage!, distanceNm: '3500.00' },
    }
    expect(remainingDistanceNm(over)).toBe(0)
  })

  it('계획 거리가 없으면 null이다 — 0은 「다 왔다」로 읽힌다', () => {
    const noPlan = {
      ...BASE,
      currentVoyage: { ...BASE.currentVoyage!, plannedDistanceNm: null },
    }
    expect(remainingDistanceNm(noPlan)).toBeNull()
  })

  it('항차가 없으면 null이다', () => {
    expect(remainingDistanceNm({ ...BASE, currentVoyage: null })).toBeNull()
  })

  it('진행률은 0~1로 자른다', () => {
    expect(voyageProgressRatio(BASE)).toBeCloseTo(0.616, 3)
    const over = {
      ...BASE,
      currentVoyage: { ...BASE.currentVoyage!, distanceNm: '9000.00' },
    }
    expect(voyageProgressRatio(over)).toBe(1)
  })

  it('계획 거리가 0이면 진행률을 만들지 않는다 — 분모 0을 화면이 만들지 않는다', () => {
    const zero = {
      ...BASE,
      currentVoyage: { ...BASE.currentVoyage!, plannedDistanceNm: '0' },
    }
    expect(voyageProgressRatio(zero)).toBeNull()
  })
})

describe('사유·경고 문구', () => {
  it('연말 예상을 못 낸 이유를 사람 말로 옮긴다', () => {
    expect(projectionReason('NO_BASIS')).toContain('실적')
    expect(projectionReason('YEAR_COMPLETE')).toContain('끝나')
  })

  it('모르는 사유 코드는 코드를 그대로 보여 준다 — 빈칸보다 낫다', () => {
    expect(projectionReason('SOMETHING_NEW')).toBe('SOMETHING_NEW')
  })

  it('사유가 null이어도 빈 문자열을 내지 않는다', () => {
    expect(projectionReason(null).length).toBeGreaterThan(0)
  })

  it('시뮬레이션 경고는 행동을 안내한다 — 「값이 안 변한다」로만 적으면 기다린다', () => {
    expect(warningText('SIMULATION_NO_FUEL_RATE')).toContain('제원')
    expect(warningText('SIMULATION_NO_FUEL_TYPE')).toContain('연료')
  })

  it('모르는 경고 코드도 코드를 그대로 보여 준다', () => {
    expect(warningText('NEW_WARNING')).toBe('NEW_WARNING')
  })
})

/**
 * 표시 자릿수 — `DESIGN_SYSTEM §4`(🔒).
 *
 * 이 화면은 서버 원본 문자열을 그대로 내보내고 있었다(`8.979907` · `4300.00 nm`).
 * 자릿수가 화면마다 갈리면 `§4.1`이 「자릿수 가변 금지, 정렬 붕괴」로 막으려던
 * 상태가 그대로 생긴다.
 *
 * `AGENTS §4.6`에 따라 **문구는 리터럴로 단언하지 않는다.** 다만 자릿수와
 * 구분자는 `§4`가 확정한 값이므로 그 성질 자체를 단언한다.
 *
 * 여기서 검증하는 것은 **필드와 포매터의 짝**이다. 화면이 어떤 포매터를 고르는지가
 * 이 화면의 결함이 나는 자리이고, vitest에 DOM 환경이 없어 렌더 결과로는 잡을 수
 * 없다. `BASE`는 `API_SPEC §2.14` 응답 예시에서 온 값이라 실제 자릿수를 그대로 쓴다.
 */
describe('표시 자릿수 — DESIGN_SYSTEM §4', () => {
  const cii = (v: string) => formatDecimalString(v, DISPLAY_DIGITS.cii)
  const distance = (v: string) => formatGrouped(v, DISPLAY_DIGITS.distanceNm)
  const fuel = (v: string) => formatGrouped(v, DISPLAY_DIGITS.fuelTon)

  const decimals = (s: string) => {
    const dot = s.indexOf('.')
    return dot === -1 ? 0 : s.length - dot - 1
  }

  it('CII 넷이 모두 소수 3자리다 (§4.1)', () => {
    // 원본은 6자리다 — 그대로 내보내면 여기서 걸린다.
    const values = [
      BASE.ytd.attainedCii,
      BASE.ytd.requiredCii,
      BASE.projection.attainedCii,
      BASE.currentVoyage!.attainedCii,
    ]
    for (const raw of values) {
      expect(decimals(cii(raw!))).toBe(DISPLAY_DIGITS.cii)
    }
  })

  it('CII에는 천단위 구분자를 넣지 않는다 (§4.2 GROUPED_FIELDS 제외)', () => {
    // 구분자는 §4.1이 자릿수 고정으로 확보한 소수부 정렬을 방해한다.
    expect(cii('1234.567800')).not.toContain(',')
  })

  it('거리는 소수점이 없다 (§4.2)', () => {
    expect(distance(BASE.ytd.totalDistanceNm!)).not.toContain('.')
    expect(distance(BASE.currentVoyage!.distanceNm!)).not.toContain('.')
  })

  it('거리가 1000 이상이면 천단위 구분자가 붙는다 (§4.2)', () => {
    // BASE의 누적 거리는 10620이다.
    expect(distance(BASE.ytd.totalDistanceNm!)).toContain(',')
    expect(distance('999')).not.toContain(',')
  })

  it('연료는 소수 1자리다 (§4.2)', () => {
    expect(decimals(fuel(BASE.ytd.totalFuelTon!))).toBe(DISPLAY_DIGITS.fuelTon)
    expect(decimals(fuel(BASE.currentVoyage!.fuelTon!))).toBe(DISPLAY_DIGITS.fuelTon)
  })
})

describe('formatOrNull — 값이 없으면 포매터를 부르지 않는다', () => {
  it('null이면 null을 돌려주고 포매터를 호출하지 않는다', () => {
    /*
     * 포매터는 십진 문자열이 아니면 TypeError를 던진다. null을 그대로 넘기면
     * 화면이 죽으므로, 호출 자체가 일어나지 않아야 한다.
     */
    let called = 0
    const format = (v: string) => {
      called += 1
      return v
    }

    expect(formatOrNull(null, format)).toBeNull()
    expect(called).toBe(0)
  })

  it('값이 있으면 포매터를 태워 돌려준다', () => {
    expect(formatOrNull('4300.00', (v) => formatGrouped(v, DISPLAY_DIGITS.distanceNm)))
      .toBe('4,300')
  })

  it('포매터에 null이 넘어가면 던진다 — 가드가 필요한 이유', () => {
    // 이 단언이 깨지면 포매터가 조용히 통과시키기 시작한 것이고,
    // 그때는 잘못된 값이 화면에 나간다.
    expect(() =>
      formatDecimalString(null as unknown as string, DISPLAY_DIGITS.cii),
    ).toThrow()
  })
})
