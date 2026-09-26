// @vitest-environment jsdom
import '../../test/renderSetup'

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { YtdSeriesChart } from './YtdSeriesChart'
import type { YtdSeries, YtdSeriesPoint } from './types'

/**
 * 올해 누적 CII 추이 (#1949 · `DESIGN_SYSTEM §9.1`·`§9.2`·`§9.4` 🔒).
 *
 * 여기서 보는 것은 **무엇을 그리고 무엇을 그리지 않는가**다. 자리·색은 정본이
 * 소유하므로 값이 아니라 **규칙**을 잠근다.
 */
const BOUNDARIES = {
  superior: '4.338757',
  lower: '4.742362',
  upper: '5.347770',
  inferior: '5.953178',
}

function point(at: string, kind: YtdSeriesPoint['kind'], value: string): YtdSeriesPoint {
  return { at, kind, attainedCii: value, rating: 'E', voyageId: null, substituted: false }
}

function series(points: YtdSeriesPoint[], overrides: Partial<YtdSeries> = {}): YtdSeries {
  return {
    regulationYear: 2026,
    capacityBasis: 'DWT',
    requiredCii: '5.045066',
    boundaries: BOUNDARIES,
    ytdAvailable: true,
    points,
    asOf: '2026-09-26T00:00:00+00:00',
    ...overrides,
  }
}

const ACTUAL_TWO = [
  point('2026-02-26T23:00:00+00:00', 'ACTUAL', '8.979906'),
  point('2026-09-26T00:00:00+00:00', 'IN_PROGRESS', '8.213830'),
]
const PLAN_TWO = [
  point('2026-10-01T00:00:00+00:00', 'PLAN', '8.973981'),
  point('2026-11-17T00:00:00+00:00', 'PLAN', '8.965893'),
]

const actualPath = () => document.querySelector('.ytds__actual')
const planPath = () => document.querySelector('.ytds__plan')

describe('누적 추이 — 무엇을 그리는가 (#1949)', () => {
  it('실적은 실선, 계획은 점선으로 나뉘어 그려진다 (§9.2)', () => {
    render(<YtdSeriesChart series={series([...ACTUAL_TWO, ...PLAN_TWO])} />)
    expect(actualPath()).not.toBeNull()
    expect(planPath()).not.toBeNull()
  })

  /**
   * **점 하나를 선으로 잇지 않는다** 〔확정 2026-09-26 · `#1949`〕.
   *
   * 시드에 확정 항차가 1건인 선박이 있다. 점 하나를 선으로 그리면 **없는 추세를
   * 그리는 것**이다 — `§9.5`가 항로선에서 세운 「지어내지 않고 그 사실을 적는다」와
   * 같은 갈래다. 계획 쪽은 그대로 그린다.
   */
  it('실적 점이 하나뿐이면 실선을 긋지 않고 그 사실을 적는다', () => {
    render(<YtdSeriesChart series={series([ACTUAL_TWO[0], ...PLAN_TWO])} />)
    expect(actualPath()).toBeNull()
    expect(screen.getByText(/확정된 항차가 1건이라 아직 추세를 그리지 않습니다/)).toBeTruthy()
    // 계획은 그대로 그린다 — 실적이 짧다고 계획까지 감추지 않는다.
    expect(planPath()).not.toBeNull()
  })

  it('실적이 둘이면 그 문구가 없다 — 없는 문제를 만들지 않는다', () => {
    render(<YtdSeriesChart series={series([...ACTUAL_TWO, ...PLAN_TWO])} />)
    expect(screen.queryByText(/아직 추세를 그리지 않습니다/)).toBeNull()
  })

  it('그릴 점이 없으면 빈 그림 대신 그 사실을 적는다', () => {
    render(<YtdSeriesChart series={series([])} />)
    expect(screen.getByText(/그릴 항차가 아직 없습니다/)).toBeTruthy()
    expect(document.querySelector('.ytds__canvas')).toBeNull()
  })

  /**
   * 등급 구간 배경을 칠하는 **조건**이 좌측 축의 등급 문자다 (`§9.4` · `§0.2` 제약 2·3).
   * 문자가 없으면 색만으로 등급을 말하는 것이 된다.
   */
  it('등급 구간을 칠하면 좌측에 등급 문자를 함께 적는다', () => {
    render(<YtdSeriesChart series={series([...ACTUAL_TWO, ...PLAN_TWO])} />)
    expect(document.querySelectorAll('.ytds__band')).toHaveLength(5)
    const letters = [...document.querySelectorAll('.ytds__band-label')].map((e) => e.textContent)
    expect(letters).toEqual(['A', 'B', 'C', 'D', 'E'])
  })

  it('경계값이 없으면 구간을 칠하지 않는다 — 지어낸 경계를 그리지 않는다', () => {
    render(<YtdSeriesChart series={series([...ACTUAL_TWO], { boundaries: null })} />)
    expect(document.querySelectorAll('.ytds__band')).toHaveLength(0)
  })

  /**
   * **표를 함께 낸다 — 선택이 아니라 의무** (`PRD §16.4`).
   *
   * 차트만 두면 화면 낭독과 인쇄본에서 값을 읽을 수 없다. `CiiHistoryChart`가 세운
   * 규칙을 그대로 따른다.
   */
  it('표를 함께 낸다 — 점마다 한 행', () => {
    render(<YtdSeriesChart series={series([...ACTUAL_TWO, ...PLAN_TWO])} />)
    const rows = document.querySelectorAll('.ytds__table tbody tr')
    expect(rows).toHaveLength(4)
    // 자릿수는 `§4.1`(🔒) — 서버 6자리가 3자리로 줄어든다.
    expect(screen.getByText('8.214')).toBeTruthy()
    expect(screen.getAllByText('확정 실적')).toHaveLength(1)
    expect(screen.getAllByText('계획')).toHaveLength(2)
  })

  it('실측이 아닌 값이 섞인 점은 글자로 말한다 — 색 단독 금지 (§14)', () => {
    const tainted = { ...ACTUAL_TWO[0], substituted: true }
    render(<YtdSeriesChart series={series([tainted, ACTUAL_TWO[1]])} />)
    expect(screen.getByText(/추정 포함/)).toBeTruthy()
  })

  it('실적과 계획 사이에 「오늘」 구분선이 선다 (§9.2)', () => {
    render(<YtdSeriesChart series={series([...ACTUAL_TWO, ...PLAN_TWO])} />)
    expect(document.querySelector('.ytds__today')).not.toBeNull()
    expect(screen.getByText('오늘')).toBeTruthy()
  })
})
