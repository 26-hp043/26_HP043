import { describe, expect, it } from 'vitest'
import {
  WEATHER_MODELS,
  FIELD,
  MIN_SPEED_KN,
  countAdvancedFilled,
  hasAdvancedError,
  hasWaypoint,
  initialFormState,
  toRequest as toRequestWith,
  usesCoordinateDistance,
  usesWaypointDistance,
  validateForm as validateFormWith,
  weatherNeedsCoordinates,
  type ComparisonFormState,
} from './requestRules'

/**
 * #511 — 항로 비교 조건 입력 규칙.
 *
 * 이 파일이 잠그는 것은 **「화면이 선박을 고르지 않는다」**는 성질이다. 종전 화면은
 * `vessel_id`를 상수로 박았고 그 값이 demo 고정표에 없어, 데모 모드에서 항로 비교가
 * 아무 입력 없이 언제나 실패했다.
 */


/** `demo_seed`가 넣는 선박 UUID. 고정표가 사라져(#542) 값을 여기 둔다. */
const SEEDED_VESSEL_ID = '00000000-0000-4000-8000-000000000001'

/**
 * 연료 선택지 — 종전 고정표 `FUEL_CF`의 8종과 같은 코드 집합이다 (#542).
 *
 * `validateForm`이 목록을 **인자로 받도록** 바뀌었다. 서버(`GET /parameters/fuel-types`)가
 * 주는 값이므로 화면 규칙이 그 목록을 직접 알지 않는다 — 그 사실을 테스트에서도
 * 같은 모양으로 둔다.
 */
const FUELS: ReadonlyArray<{ code: string; displayName: string }> = [
  { code: 'HFO', displayName: '고유황유' },
  { code: 'LFO', displayName: '저유황유' },
  { code: 'MDO', displayName: '경유' },
  { code: 'MGO', displayName: '선박용 경유' },
  { code: 'LNG', displayName: '액화천연가스' },
  { code: 'LPG_PROPANE', displayName: '프로판' },
  { code: 'LPG_BUTANE', displayName: '부탄' },
  { code: 'METHANOL', displayName: '메탄올' },
]

/**
 * 목록을 채워 넘기는 얇은 래퍼. 기존 호출부를 그대로 두기 위한 것이며,
 * **주입 자체가 판정을 바꾼다는 사실은 아래 「주입된 목록이 판정을 정한다」가 잠근다.**
 */
const validateForm = (state: ComparisonFormState) => validateFormWith(state, FUELS)
const toRequest = (state: ComparisonFormState) => toRequestWith(state, FUELS)



/**
 * **다 채운 폼**을 만든다.
 *
 * 선박·연도·직항 거리는 `initialFormState()`가 비워 두므로(`#1093` ⑷ · `#1750` — 고르지
 * 않은 값으로 계산되는 것을 막는다) 여기서 명시한다. 검증 규칙을 보는 검사들은 「사용자가
 * 골랐다」를 전제로 하며, 비었을 때의 거동은 아래 전용 검사가 따로 본다.
 */
function state(overrides: Partial<ComparisonFormState> = {}): ComparisonFormState {
  return {
    ...initialFormState(),
    vesselId: SEEDED_VESSEL_ID,
    regulationYear: '2026',
    baseDistanceNm: '1000',
    ...overrides,
  }
}

describe('initialFormState — 선박·연도에 기본값을 넣지 않는다', () => {
  it('선박은 비어 있다', () => {
    // 목록을 읽기 전에 아무 배나 골라 두면 종전 버그(고정표에 없는 UUID)가 재발한다.
    expect(initialFormState().vesselId).toBe('')
  })

  it('규제연도도 비어 있다 (#1093 ⑷)', () => {
    /*
     * 종전에는 `'2026'`이 박혀 있었다. 연도 목록이 실패·빈 목록이면 화면은 셀렉트
     * 대신 주석 한 줄을 그려 **사용자가 연도를 고를 수 없는데**, 이 값이 검증을
     * 통과해 **고른 적 없는 2026년 기준 결과**가 나왔다. 선박 축에 이미 적용한
     * 원칙을 연도 축에도 적용한다 — 목록이 오면 `pickDefaultYear`가 채운다.
     */
    expect(initialFormState().regulationYear).toBe('')
    expect(validateForm(initialFormState())).toHaveProperty(FIELD.regulationYear)
  })

  it('직항 거리도 비어 있다 (#1750)', () => {
    /*
     * 종전에는 `'1000'`이 박혀 있었다. `#1005`가 「비워 두면 현재 위치·목적항 좌표로
     * 계산한다」를 열어 두었는데, **그 경로가 이 기본값에 덮여 있었다** — 항구를 골라도
     * 1000nm으로 계산됐다. 선박·연도와 같은 원칙이다.
     */
    expect(initialFormState().baseDistanceNm).toBe('')
    expect(validateForm(initialFormState())).toHaveProperty(FIELD.baseDistanceNm)
  })

  it('나머지 조건은 종전 DEMO_REQUEST 값을 그대로 물려받는다', () => {
    const initial = initialFormState()
    expect(initial.baseSpeedKn).toBe('12.8')
    expect(initial.baseDailyFocTon).toBe('26.88')
    expect(initial.fuelType).toBe('HFO')
  })
})

describe('validateForm', () => {
  it('선박을 고르지 않으면 오류다 — 상수로 채우지 않는다', () => {
    expect(validateForm(state({ vesselId: '' }))).toHaveProperty(FIELD.vesselId)
  })

  it('조건이 다 채워져 있으면 오류가 없다', () => {
    expect(validateForm(state())).toEqual({})
  })

  it('거리·속력·일일 연료는 필수이고 0보다 커야 한다 (VAL-002)', () => {
    expect(validateForm(state({ baseDistanceNm: '' }))).toHaveProperty(FIELD.baseDistanceNm)
    expect(validateForm(state({ baseSpeedKn: '0' }))).toHaveProperty(FIELD.baseSpeedKn)
    expect(validateForm(state({ baseDailyFocTon: '-1' }))).toHaveProperty(
      FIELD.baseDailyFocTon,
    )
  })

  it('숫자로 읽을 수 없는 값을 잡는다', () => {
    expect(validateForm(state({ baseDistanceNm: '천' }))).toHaveProperty(
      FIELD.baseDistanceNm,
    )
  })

  it('빈 칸이 0으로 통과하지 않는다 — Number("")는 0이다', () => {
    const errors = validateForm(state({ baseSpeedKn: '' }))
    expect(errors[FIELD.baseSpeedKn]).toContain('입력해')
  })

  it('규제연도는 정수여야 한다', () => {
    expect(validateForm(state({ regulationYear: '2026.5' }))).toHaveProperty(
      FIELD.regulationYear,
    )
  })

  it('알 수 없는 연료는 서버 422를 기다리지 않고 화면에서 잡는다 (VAL-006)', () => {
    expect(validateForm(state({ fuelType: 'ETHANE' }))).toHaveProperty(FIELD.fuelType)
  })

  it('위반을 전부 모아 돌려준다 — 한 번에 고칠 수 있어야 한다', () => {
    const errors = validateForm(
      state({ vesselId: '', baseDistanceNm: '', fuelType: 'ETHANE' }),
    )
    expect(Object.keys(errors).sort()).toEqual(
      [FIELD.vesselId, FIELD.baseDistanceNm, FIELD.fuelType].sort(),
    )
  })
})

describe('toRequest', () => {
  it('문자열 상태를 숫자 요청으로 옮긴다', () => {
    expect(toRequest(state())).toEqual({
      vessel_id: SEEDED_VESSEL_ID,
      regulation_year: 2026,
      base_distance_nm: 1000,
      base_speed_kn: 12.8,
      base_daily_foc_ton: 26.88,
      fuel_type: 'HFO',
    })
  })

  it('검증되지 않은 상태로 부르면 던진다', () => {
    expect(() => toRequest(state({ vesselId: '' }))).toThrow('검증되지 않은')
  })
})



describe('validateForm — 주입된 목록이 판정을 정한다 (#542)', () => {
  it('목록에 없으면 거부된다', () => {
    expect(validateFormWith(state({ fuelType: 'HFO' }), [])).toHaveProperty(FIELD.fuelType)
  })

  it('목록에 있으면 통과한다 — 고정표에 없던 코드라도 마찬가지다', () => {
    const errors = validateFormWith(state({ fuelType: 'AMMONIA' }), [
      { code: 'AMMONIA', displayName: '암모니아' },
    ])
    expect(errors).not.toHaveProperty(FIELD.fuelType)
  })
})


/**
 * #892 — 선택 입력 5종.
 *
 * ## 이 블록이 잠그는 것
 *
 * **「비운 칸은 키가 되지 않는다」**는 성질이다. `detour_distance_nm: 0`은 서버에서
 * 「기본을 쓰라」가 아니라 「0마일로 우회하라」이고 VAL-002에 걸려 422가 된다.
 * `null`도 마찬가지로 `extra="forbid"` 스키마의 명시적 값이다. 미지정을 표현하는
 * 방법은 **키를 넣지 않는 것 하나**뿐이다 (`API_SPEC §5.1` 기본값 표).
 */
describe('선택 입력 — 비운 칸 (#892)', () => {
  it('선택 넷은 비어 있고 기상만 NONE이다', () => {
    const initial = initialFormState()
    expect(initial.detourDistanceNm).toBe('')
    expect(initial.slowSpeedKn).toBe('')
    expect(initial.currentLat).toBe('')
    expect(initial.currentLon).toBe('')
    // 셀렉트에는 「미선택」 항목이 없다 — `NONE`이 그 자리다.
    expect(initial.weatherModel).toBe('NONE')
  })

  it('비워 두어도 오류가 아니다', () => {
    expect(validateForm(state())).toEqual({})
  })

  it('요청에 키 자체가 없다 — 0이나 null을 보내지 않는다', () => {
    const request = toRequest(state())
    expect(request).not.toHaveProperty('detour_distance_nm')
    expect(request).not.toHaveProperty('slow_speed_kn')
    expect(request).not.toHaveProperty('current_lat')
    expect(request).not.toHaveProperty('current_lon')
    // NONE도 보내지 않는다 — 서버 기본이 NONE이라 명시해도 결과가 같다.
    expect(request).not.toHaveProperty('weather_model')
  })
})

describe('선택 입력 — 채운 칸이 요청에 실린다 (#892)', () => {
  it('네 숫자가 서버 필드명 그대로 실린다', () => {
    const request = toRequest(
      state({
        detourDistanceNm: '1200',
        slowSpeedKn: '10.5',
        currentLat: '35.1',
        currentLon: '129.05',
      }),
    )
    expect(request).toMatchObject({
      detour_distance_nm: 1200,
      slow_speed_kn: 10.5,
      current_lat: 35.1,
      current_lon: 129.05,
    })
  })

  it('NONE이 아닌 기상 모델은 실린다', () => {
    expect(toRequest(state({ weatherModel: 'SIMPLE_RULE' }))).toMatchObject({
      weather_model: 'SIMPLE_RULE',
    })
  })
})

describe('선택 입력 — 검증 (#892)', () => {
  it('우회 거리는 0보다 커야 한다 (VAL-002)', () => {
    expect(validateForm(state({ detourDistanceNm: '0' }))).toHaveProperty(
      FIELD.detourDistanceNm,
    )
  })

  it('감속 속력의 하한은 0이 아니라 1.0이다 (VAL-009)', () => {
    /*
     * **0.5는 `> 0`을 통과한다.** 다른 칸과 같은 규칙(VAL-002)을 쓰면 여기를
     * 빠져나가 서버 422가 된다 — `PRD §9.1`이 이 칸에만 1.0 floor를 규정한다.
     */
    expect(validateForm(state({ slowSpeedKn: '0.5' }))).toHaveProperty(FIELD.slowSpeedKn)
    expect(validateForm(state({ slowSpeedKn: '0.999' }))).toHaveProperty(FIELD.slowSpeedKn)
  })

  it('경계값 1.0은 통과한다 — floor는 포함이다', () => {
    expect(validateForm(state({ slowSpeedKn: String(MIN_SPEED_KN) }))).toEqual({})
  })

  it('좌표를 한쪽만 넣으면 나머지 칸에 오류가 붙는다 (API_SPEC:572)', () => {
    // 서버가 422로 되돌리는 조합이다. 어느 칸이 빈지는 화면이 이미 안다.
    expect(validateForm(state({ currentLat: '35.1' }))).toHaveProperty(FIELD.currentLon)
    expect(validateForm(state({ currentLon: '129.0' }))).toHaveProperty(FIELD.currentLat)
  })

  it('둘 다 넣으면 통과한다', () => {
    expect(validateForm(state({ currentLat: '35.1', currentLon: '129.0' }))).toEqual({})
  })

  it('좌표 범위를 잡는다 (VAL-007)', () => {
    const errors = validateForm(state({ currentLat: '91', currentLon: '181' }))
    expect(errors).toHaveProperty(FIELD.currentLat)
    expect(errors).toHaveProperty(FIELD.currentLon)
  })

  it('0은 유효한 좌표다 — 적도·본초자오선이 빈 칸으로 읽히면 안 된다', () => {
    expect(validateForm(state({ currentLat: '0', currentLon: '0' }))).toEqual({})
    expect(toRequest(state({ currentLat: '0', currentLon: '0' }))).toMatchObject({
      current_lat: 0,
      current_lon: 0,
    })
  })

  it('알 수 없는 기상 모델을 잡는다', () => {
    expect(validateForm(state({ weatherModel: 'ECMWF' }))).toHaveProperty(FIELD.weatherModel)
  })
})

/**
 * `weatherNeedsCoordinates` — 고른 모델이 **실제로 적용되는지**.
 *
 * 좌표 없는 요청은 `services/weather.py:276-280`이 보정 없이 되돌린다. 실 API
 * 측정으로 확인했다 — `SIMPLE_RULE` + 좌표 없음의 `fuel_ton`이 모델 없음과
 * **완전히 같았다**(87.50 대 87.50). 좌표를 넣으면 94.22가 된다.
 */
describe('기상 모델이 적용되는 조건 (#892)', () => {
  it('NONE이면 좌표가 없어도 알릴 것이 없다', () => {
    expect(weatherNeedsCoordinates(state())).toBe(false)
  })

  it('모델을 골랐는데 좌표가 없으면 true다', () => {
    expect(weatherNeedsCoordinates(state({ weatherModel: 'SIMPLE_RULE' }))).toBe(true)
  })

  it('한쪽만 있어도 true다 — 서버는 둘 다 있어야 조회한다', () => {
    expect(
      weatherNeedsCoordinates(state({ weatherModel: 'SIMPLE_RULE', currentLat: '35.1' })),
    ).toBe(true)
  })

  it('둘 다 있으면 false다', () => {
    expect(
      weatherNeedsCoordinates(
        state({ weatherModel: 'SIMPLE_RULE', currentLat: '35.1', currentLon: '129.0' }),
      ),
    ).toBe(false)
  })
})

/**
 * 직항 거리를 좌표로 대신하는 조건 (#1005 · `PRD §11.2`).
 */
describe('좌표 기반 직항 거리 (#1005)', () => {
  const withCoords = {
    ...initialFormState(),
    vesselId: 'v-1',
    // 연도는 `initialFormState()`가 비워 둔다 (`#1093` ⑷) — 여기서는 고른 상태를 본다.
    regulationYear: '2026',
    baseDistanceNm: '',
    currentLat: '35.1',
    currentLon: '129.0333',
    destinationPortName: 'SINGAPORE',
    destinationLat: '1.2833',
    destinationLon: '103.85',
  }

  it('거리가 비었고 네 좌표가 다 있을 때만 좌표로 계산한다', () => {
    expect(usesCoordinateDistance(withCoords)).toBe(true)
    expect(usesCoordinateDistance({ ...withCoords, baseDistanceNm: '900' })).toBe(false)
    expect(usesCoordinateDistance({ ...withCoords, destinationLat: '' })).toBe(false)
  })

  it('좌표가 모자라면 직항 거리를 비울 수 없다 — 무엇을 하면 되는지 말한다', () => {
    const errors = validateForm({ ...withCoords, destinationLat: '', destinationLon: '' })
    expect(errors.direct_distance_nm).toBe(
      '직항 거리를 입력하거나, 현재 위치와 목적항을 샘플 항만에서 골라 주세요.',
    )
  })

  it('좌표로 계산할 때는 거리 키를 싣지 않고 목적항을 싣는다', () => {
    expect(validateForm(withCoords)).toEqual({})
    const request = toRequest(withCoords)
    expect(request).not.toHaveProperty('base_distance_nm')
    expect(request).toMatchObject({
      destination_port_name: 'SINGAPORE',
      destination_lat: 1.2833,
      destination_lon: 103.85,
    })
  })
})

describe('고급 설정의 상태 (#1417)', () => {
  it('처음에는 기본에서 벗어난 칸이 없다 — 기상 모델의 기본은 빈 칸이 아니라 NONE이다', () => {
    expect(countAdvancedFilled(initialFormState())).toBe(0)
  })

  it('칸을 채우면 센다 — 기상 모델은 NONE이 아닐 때만', () => {
    const form = { ...initialFormState(), slowSpeedKn: '10', weatherModel: 'SIMPLE_RULE' }
    expect(countAdvancedFilled(form)).toBe(2)
    expect(countAdvancedFilled({ ...initialFormState(), detourDistanceNm: '   ' })).toBe(0)
  })

  it('고급 칸의 오류만 고급 오류다 — 필수 칸 오류로 펼치지 않는다', () => {
    expect(hasAdvancedError({ [FIELD.slowSpeedKn]: 'x' })).toBe(true)
    expect(hasAdvancedError({ [FIELD.currentLat]: 'x' })).toBe(true)
    expect(hasAdvancedError({ [FIELD.baseSpeedKn]: 'x' })).toBe(false)
    expect(hasAdvancedError({})).toBe(false)
  })
})

describe('기상 모델 선택지 글자 (#1524)', () => {
  it('선택지 글자에 계약 코드 모양(대문자·밑줄)이 없다', () => {
    // 문구가 아니라 성질을 단언한다(`AGENTS §4.6`) — 글자는 디자인 담당이 바꿀 수 있다.
    for (const model of WEATHER_MODELS) {
      expect(model.label, model.code).not.toMatch(/\b[A-Z]+_[A-Z_]+\b/)
      expect(model.label, model.code).not.toContain(model.code)
    }
  })

  it('보내는 값은 계약 코드 그대로다', () => {
    expect(WEATHER_MODELS.map((model) => model.code)).toEqual([
      'NONE',
      'SIMPLE_RULE',
      'TOWNSIN_KWON_ALPHA',
    ])
  })
})

/**
 * 우회 경유지 (`#1300` · `PRD §11.3`).
 *
 * 목적항과 같은 규칙이다 — 샘플 항만을 골랐을 때만 좌표가 붙고, 좌표가 둘 다 있을 때만
 * 요청에 실린다. 좌표 넷이 없으면 서버가 422를 내므로 화면이 먼저 막는다.
 */
describe('우회 경유지 (#1300)', () => {
  const COORDS = {
    currentLat: '35.1',
    currentLon: '129.0333',
    destinationLat: '1.2833',
    destinationLon: '103.85',
  }
  const WAYPOINT = { detourWaypointName: 'HONOLULU', detourWaypointLat: '21.3', detourWaypointLon: '-157.87' }

  it('처음에는 비어 있고 요청에 키가 없다', () => {
    expect(hasWaypoint(initialFormState())).toBe(false)
    const request = toRequest(state())
    expect(request).not.toHaveProperty('detour_waypoint_lat')
    expect(request).not.toHaveProperty('detour_waypoint_name')
  })

  it('좌표가 둘 다 있을 때만 이름과 좌표를 싣는다', () => {
    expect(toRequest(state({ ...COORDS, ...WAYPOINT }))).toMatchObject({
      detour_waypoint_name: 'HONOLULU',
      detour_waypoint_lat: 21.3,
      detour_waypoint_lon: -157.87,
    })
    // 이름만 있고 좌표가 없으면(목록 밖 항만) 서버가 할 일이 없다 — 싣지 않는다.
    const request = toRequest(state({ ...COORDS, detourWaypointName: '어딘가' }))
    expect(request).not.toHaveProperty('detour_waypoint_name')
    expect(request).not.toHaveProperty('detour_waypoint_lat')
  })

  it('좌표 넷이 없으면 경유지를 쓸 수 없다 — 그 칸에 오류가 붙는다', () => {
    const errors = validateForm(state({ ...WAYPOINT }))
    expect(errors).toHaveProperty(FIELD.detourWaypointName)
    expect(validateForm(state({ ...COORDS, ...WAYPOINT }))).toEqual({})
    // 고급 칸이라 접힌 채로 두면 오류가 보이지 않는다.
    expect(hasAdvancedError(errors)).toBe(true)
  })

  it('고급 칸 수에 든다', () => {
    expect(countAdvancedFilled(state({ ...WAYPOINT }))).toBe(1)
  })

  it('경유지가 어느 끝과 같으면 막고, 어느 쪽인지 말한다 — 서버와 같은 갈래', () => {
    const onDestination = validateForm(
      state({ ...COORDS, detourWaypointName: 'X', detourWaypointLat: '1.2833', detourWaypointLon: '103.85' }),
    )
    expect(onDestination[FIELD.detourWaypointName]).toMatch(/목적항/)
    expect(onDestination[FIELD.detourWaypointName]).not.toMatch(/현재 위치/)

    const onCurrent = validateForm(
      state({ ...COORDS, detourWaypointName: 'X', detourWaypointLat: '35.1', detourWaypointLon: '129.0333' }),
    )
    expect(onCurrent[FIELD.detourWaypointName]).toMatch(/현재 위치/)
    expect(onCurrent[FIELD.detourWaypointName]).not.toMatch(/목적항/)

    const allThree = validateForm(
      state({
        ...COORDS,
        destinationLat: '35.1',
        destinationLon: '129.0333',
        detourWaypointName: 'X',
        detourWaypointLat: '35.1',
        detourWaypointLon: '129.0333',
      }),
    )
    expect(allThree[FIELD.detourWaypointName]).toMatch(/현재 위치/)
    expect(allThree[FIELD.detourWaypointName]).toMatch(/목적항/)
    // 표기가 달라도 같은 점이다 — `35.10` = `35.1`.
    const spelled = validateForm(
      state({ ...COORDS, detourWaypointName: 'X', detourWaypointLat: '35.10', detourWaypointLon: '129.03330' }),
    )
    expect(spelled).toHaveProperty(FIELD.detourWaypointName)
  })

  it('우회 거리를 비우고 경유지를 골랐을 때만 경유지 기준 추정이다', () => {
    expect(usesWaypointDistance(state({ ...COORDS, ...WAYPOINT }))).toBe(true)
    expect(usesWaypointDistance(state({ ...COORDS, ...WAYPOINT, detourDistanceNm: '1200' }))).toBe(false)
    expect(usesWaypointDistance(state({ ...COORDS }))).toBe(false)
  })
})
