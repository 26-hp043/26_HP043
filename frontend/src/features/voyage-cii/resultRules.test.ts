import { describe, expect, it } from 'vitest'
import {
  ciiUnit,
  isPositiveDecimalString,
  marginDisplay,
  nextWorseRating,
  riskLabel,
  warningMessage,
  WARNING_MESSAGE,
} from './resultRules'
import type { Rating, RiskLevel } from './types'

describe('ciiUnit — DESIGN_SYSTEM §4.1 단위 파생', () => {
  it('DWT 축은 gCO₂/(DWT·nm)', () => {
    expect(ciiUnit('DWT')).toBe('gCO₂/(DWT·nm)')
  })

  it('GT 축은 gCO₂/(GT·nm) — 고정 문자열이 아니다', () => {
    // 이 테스트가 「dwt를 상수로 박지 않았는가」를 잠근다.
    // MVP는 BULK_CARRIER 단독이라 화면에는 DWT만 나오지만,
    // 상수로 박으면 선종이 늘 때 크루즈선에 DWT가 표시된다.
    expect(ciiUnit('GT')).toBe('gCO₂/(GT·nm)')
  })

  it('분모가 괄호로 묶인다', () => {
    // 괄호가 없으면 gCO₂/DWT 에 nm 을 곱한 것으로 읽힌다.
    expect(ciiUnit('DWT')).toContain('(DWT·nm)')
  })

  it('t 를 쓰지 않는다 — 재화중량톤수와 실제 적재 무게는 다른 값이다', () => {
    expect(ciiUnit('DWT')).not.toMatch(/\bt\b/)
  })

  it('지표명을 병기하지 않는다', () => {
    // DESIGN_SYSTEM §4.1 🔒 · 디자인 28번 ⑵
    for (const basis of ['DWT', 'GT'] as const) {
      expect(ciiUnit(basis)).not.toContain('AER')
      expect(ciiUnit(basis)).not.toContain('cgDIST')
    }
  })
})

describe('nextWorseRating', () => {
  it.each([
    ['A', 'B'],
    ['B', 'C'],
    ['C', 'D'],
    ['D', 'E'],
  ])('%s의 다음 악화 등급은 %s', (from, to) => {
    expect(nextWorseRating(from as Rating)).toBe(to)
  })

  it('E는 더 나쁜 등급이 없다', () => {
    expect(nextWorseRating('E')).toBeNull()
  })
})

describe('isPositiveDecimalString — Number를 거치지 않는다', () => {
  it.each([
    ['0.0724', true],
    ['0.0000001', true],
    ['1', true],
    ['0', false],
    ['0.0', false],
    ['0.000', false],
    ['-0.05', false],
    ['', false],
    ['abc', false],
  ])('%s → %s', (value, expected) => {
    expect(isPositiveDecimalString(value)).toBe(expected)
  })

  it('자릿수가 아주 많아도 판단이 흔들리지 않는다', () => {
    // 부동소수점으로 바꾸면 언더플로로 0이 되는 값이다.
    expect(isPositiveDecimalString('0.' + '0'.repeat(400) + '1')).toBe(true)
  })
})

describe('marginDisplay — DESIGN_SYSTEM §2.5 (b)', () => {
  it('대상 등급을 함께 적는다', () => {
    // 「다음 등급까지」만 쓰면 개선·악화 방향이 갈리지 않는다.
    const result = marginDisplay('C', '0.0724')
    expect(result.kind).toBe('ratio')
    expect(result.text).toBe('D 등급까지 7.2%')
  })

  it('백분율 1자리로 반올림한다', () => {
    expect(marginDisplay('B', '0.14149').text).toBe('C 등급까지 14.1%')
    expect(marginDisplay('B', '0.14151').text).toBe('C 등급까지 14.2%')
  })

  it('0보다 크고 0.1% 미만이면 0.0%가 아니라 「0.1% 미만」', () => {
    // 경계 근처에서 0.0%는 이미 등급이 넘어간 것처럼 읽힌다.
    const result = marginDisplay('C', '0.0002')
    expect(result.kind).toBe('below-threshold')
    expect(result.text).toBe('D 등급까지 0.1% 미만')
  })

  it('정확히 0.1%는 예외가 아니다', () => {
    expect(marginDisplay('C', '0.001').text).toBe('D 등급까지 0.1%')
  })

  it('0에는 예외를 적용하지 않는다', () => {
    // 0 이하는 경계에 도달했거나 이미 넘은 상태다.
    const result = marginDisplay('C', '0')
    expect(result.kind).toBe('ratio')
    expect(result.text).toBe('D 등급까지 0.0%')
  })

  it('음수에도 예외를 적용하지 않는다', () => {
    const result = marginDisplay('C', '-0.0002')
    expect(result.kind).toBe('ratio')
    expect(result.text).not.toContain('미만')
  })

  it('등급 E는 여유율을 숫자로 내지 않는다', () => {
    // E는 다음 악화 등급이 없어 여유율이 정의되지 않는다(#171). 숫자를 만들면 없는
    // 값을 있는 것처럼 보이게 한다. 문구 자체는 디자인 소관이다.
    const result = marginDisplay('E', null)
    expect(result.kind).toBe('lowest')
    expect(result.text).not.toContain('%')
  })

  it('등급 E는 값이 와도 「해당 없음」이다', () => {
    // #171 결론은 null이지만 정본 반영은 #55다. 값이 와도 깨지지 않아야 한다.
    expect(marginDisplay('E', '0.05').kind).toBe('lowest')
  })

  it('E가 아닌데 값이 없으면 문구를 지어내지 않는다', () => {
    expect(marginDisplay('C', null).kind).toBe('unavailable')
    expect(marginDisplay('C', '').kind).toBe('unavailable')
  })
})

describe('riskLabel — DESIGN_SYSTEM §2.5 (b) · §14', () => {
  it.each([
    ['LOW', '낮음 LOW'],
    ['MEDIUM', '보통 MEDIUM'],
    ['HIGH', '높음 HIGH'],
    ['CRITICAL', '심각 CRITICAL'],
  ])('%s → %s', (level, text) => {
    expect(riskLabel(level as RiskLevel).text).toBe(text)
  })

  it('한국어가 앞에 온다 — 좁은 폭에서 잘려도 의미가 남는다', () => {
    for (const level of ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as RiskLevel[]) {
      expect(riskLabel(level).text).toMatch(/^[가-힣]/)
    }
  })

  it('아이콘은 HIGH·CRITICAL 두 단계에만 붙는다', () => {
    // 단계별로 다른 아이콘을 만들면 4단계 시각 체계가 되어 램프 금지 취지가 무너진다.
    expect(riskLabel('LOW').withIcon).toBe(false)
    expect(riskLabel('MEDIUM').withIcon).toBe(false)
    expect(riskLabel('HIGH').withIcon).toBe(true)
    expect(riskLabel('CRITICAL').withIcon).toBe(true)
  })
})

describe('warningMessage — API_SPEC §1.6 전사', () => {
  it('REFERENCE_ONLY 문구가 정본과 같다', () => {
    expect(warningMessage('REFERENCE_ONLY')).toBe(
      '참고용 예측값입니다. 규제 제출용이 아닙니다.',
    )
  })

  it('§1.6의 7개 코드를 전부 담는다', () => {
    expect(Object.keys(WARNING_MESSAGE).sort()).toEqual(
      [
        'CB_ESTIMATED',
        'COMPLETED_NO_FUEL',
        'EXPERIMENTAL_MODEL',
        'NON_CII_VESSEL',
        'REFERENCE_ONLY',
        'WEATHER_NONE_FALLBACK',
        'WEATHER_STALE',
      ].sort(),
    )
  })

  it('표에 없는 코드는 감추지 않고 코드 자체를 보여 준다', () => {
    // 조용히 감추면 경고가 사라진다.
    expect(warningMessage('SOME_NEW_CODE')).toBe('SOME_NEW_CODE')
  })
})

describe('통합 — demo fixture의 실제 응답으로 표시 규칙을 돌린다', () => {
  it('등급 C 응답이 계약대로 표시된다', async () => {
    const { createDemoProvider } = await import('./demoProvider')
    const { initialFormState, toRequest } = await import('./formRules')

    const response = await createDemoProvider().estimate(
      toRequest({
        ...initialFormState(),
        distanceNm: '1000',
        speedKn: '14.2',
        fuelType: 'HFO',
        fuelTon: '80',
      }),
    )
    const data = response.data

    // 정본 문구 (DESIGN_SYSTEM §4.1 단위 표기) — 바꾸려면 DESIGN_SYSTEM 개정이 먼저다.
    expect(ciiUnit(data.transport_capacity_basis)).toBe('gCO₂/(DWT·nm)')
    expect(marginDisplay(data.estimated_rating, data.next_worse_boundary_margin_ratio).text).toBe(
      'D 등급까지 7.2%',
    )
    // 한국어 레이블은 디자인 소관. 판정 코드(PRD §9.4.1)가 실려 나가는지만 본다.
    expect(riskLabel(data.risk_level).text).toContain('MEDIUM')
    // 정본 문구 (API_SPEC §1.6 warning 표를 그대로 전사) — 바꾸려면 API_SPEC 개정이
    // 먼저다.
    expect(response.warnings.map(warningMessage)).toEqual([
      '참고용 예측값입니다. 규제 제출용이 아닙니다.',
    ])
  })
})
