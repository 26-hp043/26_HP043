import { describe, expect, it } from 'vitest'
import {
  DETAIL_STATUS_BY_STATE,
  detailStatusFor,
  hasPositionErrors,
  initialPositionDraft,
  isEmptyPayload,
  positionPayload,
  validatePosition,
  type PositionDraft,
} from './positionRules'

/**
 * 위치·상태 입력 규칙 (`API_SPEC §2.6` · `#369`).
 *
 * 여기서 고정하는 것은 **서버가 422로 거부하는 조건을 화면이 먼저 잡는다**는 것과,
 * **의미 없는 갱신을 만들지 않는다**는 것이다. 후자가 중요하다 —
 * `position_updated_at`이 「낡은 값인지」 판별의 근거인데, 안 바뀐 값을 실어 보내면
 * 그 근거가 무너진다.
 */

function draft(over: Partial<PositionDraft> = {}): PositionDraft {
  return { underwayState: '', detailStatus: '', lat: '', lon: '', ...over }
}

const AT_SEA = draft({
  underwayState: 'UNDER_WAY',
  detailStatus: 'SAILING',
  lat: '35.1',
  lon: '129.0',
})

describe('상태 2축', () => {
  it('한쪽만 고르면 막는다 — 서버 CHECK가 둘을 묶고 있다', () => {
    expect(validatePosition(draft({ underwayState: 'UNDER_WAY' })).detailStatus).toBeDefined()
    expect(validatePosition(draft({ detailStatus: 'SAILING' })).underwayState).toBeDefined()
  })

  it('허용되지 않는 조합을 막는다 — UNDER_WAY + AT_ANCHOR', () => {
    const errors = validatePosition(
      draft({ underwayState: 'UNDER_WAY', detailStatus: 'AT_ANCHOR' }),
    )
    expect(errors.detailStatus).toBeDefined()
  })

  it('NOT_UNDER_WAY 6값은 not_underway_period.period_type와 같은 집합이다', () => {
    // 정박 구간의 성격이 곧 선박의 표시 상태가 된다 (`§2.6`).
    expect([...DETAIL_STATUS_BY_STATE.NOT_UNDER_WAY]).toEqual([
      'IN_PORT',
      'AT_ANCHOR',
      'DRIFTING',
      'STS',
      'CANAL_TRANSIT',
      'DRYDOCK',
    ])
    expect([...DETAIL_STATUS_BY_STATE.UNDER_WAY]).toEqual(['SAILING'])
  })

  it('둘 다 비우는 것은 오류가 아니다 — 「바꾸지 않음」이다', () => {
    expect(hasPositionErrors(validatePosition(draft()))).toBe(false)
  })
})

describe('운항 상태를 바꾸면 세부 상태를 다시 고른다', () => {
  it('UNDER_WAY는 자동으로 SAILING이 된다 — 고를 것이 하나뿐이다', () => {
    expect(detailStatusFor('UNDER_WAY', 'AT_ANCHOR')).toBe('SAILING')
  })

  it('NOT_UNDER_WAY로 가면 SAILING을 버린다 — 남겨 두면 422가 된다', () => {
    expect(detailStatusFor('NOT_UNDER_WAY', 'SAILING')).toBe('')
  })

  it('NOT_UNDER_WAY 안에서 고른 값은 지키지 않는다면 매번 다시 골라야 한다', () => {
    expect(detailStatusFor('NOT_UNDER_WAY', 'AT_ANCHOR')).toBe('AT_ANCHOR')
  })
})

describe('위경도', () => {
  it('한쪽만 넣으면 막는다', () => {
    expect(validatePosition(draft({ lat: '35.1' })).lon).toBeDefined()
    expect(validatePosition(draft({ lon: '129.0' })).lat).toBeDefined()
  })

  it.each([
    ['91', '0', 'lat'],
    ['-91', '0', 'lat'],
    ['0', '181', 'lon'],
    ['0', '-181', 'lon'],
  ] as const)('범위를 벗어나면 막는다 — (%s, %s)', (lat, lon, field) => {
    expect(validatePosition(draft({ lat, lon }))[field]).toBeDefined()
  })

  it('경계값은 통과한다', () => {
    expect(hasPositionErrors(validatePosition(draft({ lat: '90', lon: '180' })))).toBe(false)
    expect(hasPositionErrors(validatePosition(draft({ lat: '-90', lon: '-180' })))).toBe(false)
  })

  it('숫자가 아니면 막는다 — 지수 표기도 받지 않는다', () => {
    expect(validatePosition(draft({ lat: '북위 35도', lon: '0' })).lat).toBeDefined()
    expect(validatePosition(draft({ lat: '3.5e1', lon: '0' })).lat).toBeDefined()
  })
})

describe('요청 본문 — 바뀐 것만 싣는다', () => {
  it('아무것도 안 바꾸면 빈 본문이다', () => {
    expect(isEmptyPayload(positionPayload(AT_SEA, AT_SEA))).toBe(true)
  })

  it('위치만 바꾸면 상태를 싣지 않는다', () => {
    /*
     * 상태까지 실으면 서버가 「바꿨다」로 보고 갱신 시각을 올린다. 실제로 상태는
     * 그대로이므로 「언제 기준 상태인가」가 사실과 달라진다.
     */
    const payload = positionPayload({ ...AT_SEA, lat: '36.0' }, AT_SEA)
    expect(payload).toEqual({ current_lat: 36, current_lon: 129 })
    expect('underway_state' in payload).toBe(false)
  })

  it('상태만 바꾸면 위치를 싣지 않는다', () => {
    const payload = positionPayload(
      { ...AT_SEA, underwayState: 'NOT_UNDER_WAY', detailStatus: 'IN_PORT' },
      AT_SEA,
    )
    expect(payload).toEqual({ underway_state: 'NOT_UNDER_WAY', detail_status: 'IN_PORT' })
    expect('current_lat' in payload).toBe(false)
  })

  it('상태는 2축을 함께 싣는다 — 한쪽만 보내면 서버가 기존 값과 섞어 검증한다', () => {
    // 세부 상태만 바꾼 경우에도 `underway_state`가 함께 나가야 한다.
    const payload = positionPayload(
      { ...AT_SEA, underwayState: 'NOT_UNDER_WAY', detailStatus: 'DRYDOCK' },
      { ...AT_SEA, underwayState: 'NOT_UNDER_WAY', detailStatus: 'IN_PORT' },
    )
    expect(payload.underway_state).toBe('NOT_UNDER_WAY')
    expect(payload.detail_status).toBe('DRYDOCK')
  })

  it('position_updated_at을 싣지 않는다 — extra=forbid가 422로 거부한다', () => {
    const payload = positionPayload({ ...AT_SEA, lat: '36.0' }, AT_SEA)
    expect(Object.keys(payload).every((key) => !key.includes('updated_at'))).toBe(true)
  })

  it('좌표를 문자열로 보내지 않는다 — §2.6이 number로 규정한다', () => {
    const payload = positionPayload({ ...AT_SEA, lat: '36.0' }, AT_SEA)
    expect(typeof payload.current_lat).toBe('number')
    expect(typeof payload.current_lon).toBe('number')
  })
})

describe('초기값', () => {
  it('서버 값이 없으면 빈 문자열이다 — null을 폼에 그대로 넣지 않는다', () => {
    expect(
      initialPositionDraft({
        underwayState: null,
        detailStatus: null,
        lat: null,
        lon: null,
      }),
    ).toEqual({ underwayState: '', detailStatus: '', lat: '', lon: '' })
  })
})
