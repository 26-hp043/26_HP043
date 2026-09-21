// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { DataQuality } from './DataQuality'
import { DATA_QUALITY_COPY, SEVERITY_TITLE } from './copy'
import type { DataQualityProvider, DataQualitySnapshot } from './types'

/**
 * 데이터 점검 화면 (`UIFLOW 2-11` · #513).
 *
 * 판정은 서버 검사가 잠근다. 여기서는 **화면이 무엇을 숨기지 않는가**를 본다 —
 * 이 화면이 반쪽으로 열리지 않았던 이유(`PRD §5.2` 각주)가 「0건으로 읽히는 빈칸」이었다.
 */

const SNAPSHOT: DataQualitySnapshot = {
  regulationYear: 2026,
  counts: { SUBSTITUTED: 1, UNAVAILABLE: 0, ANOMALY: 1, UNCONFIRMED: 0 },
  anomalyUnjudged: 3,
  completenessRatio: '0.9420',
  vessels: [
    {
      vesselId: 'v1',
      vesselName: 'MV One',
      dataAvailable: true,
      unavailableReason: null,
      ytdAttainedCii: '5.1234',
      ytdRating: 'C',
      voyageCount: 2,
      completenessRatio: '0.9420',
    },
    {
      vesselId: 'v2',
      vesselName: 'MV Empty',
      dataAvailable: false,
      unavailableReason: null,
      ytdAttainedCii: null,
      ytdRating: null,
      voyageCount: 0,
      completenessRatio: null,
    },
  ],
  issues: [
    {
      severity: 'SUBSTITUTED',
      vesselId: 'v1',
      vesselName: 'MV One',
      voyageId: 'voy-2',
      voyageNo: 'B',
      codes: ['FUEL:HFO'],
      cii: {
        attainedCii: '5.1234',
        attainedCiiWithout: '4.9000',
        delta: '0.2234',
        rating: 'C',
        ratingWithout: 'B',
      },
      ciiReason: null,
    },
    {
      severity: 'ANOMALY',
      vesselId: 'v1',
      vesselName: 'MV One',
      voyageId: 'voy-3',
      voyageNo: 'C',
      codes: ['FUEL_VS_MODEL'],
      cii: null,
      ciiReason: 'ONLY_VOYAGE',
    },
  ],
}

function renderWith(snapshot: DataQualitySnapshot) {
  // 연도 목록은 실 fetch를 탄다 — 여기서는 비워 서버 기본 연도로 부르게 둔다.
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
  const provider: DataQualityProvider = { load: vi.fn(async () => snapshot) }
  const result = render(
    <MemoryRouter>
      <DataQuality provider={provider} />
    </MemoryRouter>,
  )
  // `container`는 `#1288`이 클래스를 직접 본다 — 색은 보이는 것이지 문구가 아니다.
  return { provider, container: result.container }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('데이터 점검 화면 (#513)', () => {
  it('⚠️ 네 그룹을 항상 그린다 — 0건 그룹도 지우지 않는다', async () => {
    renderWith(SNAPSHOT)

    for (const title of Object.values(SEVERITY_TITLE)) {
      expect(await screen.findByRole('heading', { name: new RegExp(title) })).toBeTruthy()
    }
    // 계산 불가·실적 미입력은 0건 — 「해당 없음」 문장이 있어야 한다.
    expect(screen.getAllByText(DATA_QUALITY_COPY.emptyGroup)).toHaveLength(2)
  })

  it('완결성은 무엇의 비율인지 함께 말한다', async () => {
    renderWith(SNAPSHOT)

    expect(await screen.findAllByText('94.2%')).toHaveLength(2)
    expect(screen.getByText(DATA_QUALITY_COPY.completenessHint)).toBeTruthy()
  })

  it('⚠️ 판정하지 못한 항차 수를 이상치 0건과 섞지 않고 보인다', async () => {
    renderWith(SNAPSHOT)

    expect(await screen.findByText(DATA_QUALITY_COPY.unjudgedHint(3))).toBeTruthy()
  })

  it('CII 영향은 부호를 붙이고, 등급이 바뀌면 전이를 그린다', async () => {
    renderWith(SNAPSHOT)

    const group = (await screen.findByRole('heading', { name: /대체 계산/ })).closest('section')!
    expect(within(group).getByText('+0.223')).toBeTruthy()
    expect(within(group).getByLabelText('이 항차가 없으면 B, 있으면 C')).toBeTruthy()
    expect(screen.getByText(DATA_QUALITY_COPY.impactCaption)).toBeTruthy()
  })

  it('영향을 낼 수 없으면 0이 아니라 사유를 적는다 — 칸은 짧게, 이유는 표 아래 (#1580)', async () => {
    renderWith(SNAPSHOT)

    const group = (await screen.findByRole('heading', { name: /이상치/ })).closest('section')!
    expect(within(group).getByText('비교 불가*')).toBeTruthy()
    expect(within(group).getByText('* 선박의 유일한 항차라 빼고 비교할 누적 CII가 없습니다.')).toBeTruthy()
  })

  it('항차가 없는 선박은 「계산 불가」가 아니라 「실적 항차 없음」이다', async () => {
    renderWith(SNAPSHOT)

    expect(await screen.findByText(DATA_QUALITY_COPY.noActualVoyages)).toBeTruthy()
  })

  it('사유 코드는 사람이 읽는 문구로 — 유종은 괄호로 붙인다', async () => {
    renderWith(SNAPSHOT)

    expect(await screen.findByText('실적 연료 없음 — 계획 연료로 계산 (HFO)')).toBeTruthy()
  })
})

/**
 * 0건 항목은 위험색을 달지 않는다 (#1288).
 *
 * 종전에는 건수를 보지 않고 심각도 변형을 늘 붙여 **요약 4칸 중 3칸이 경고색**이었다.
 * 색은 심각도 신호다 — 「색이 있다 = 볼 것이 있다」(`DESIGN_SYSTEM §16` 항목 8 · `#694`).
 *
 * 0건 그룹을 **감추는 것이 아니다.** 「확인했더니 없다」와 「확인하지 않았다」는 다르다 —
 * 위 검사가 그것을 잠그고 있고, 이 검사는 **색만** 본다.
 *
 * `SNAPSHOT`이 그대로 두 경우를 갖는다 — 대체 계산 1건 · 이상치 1건 / 계산 불가 0건 ·
 * 실적 미확정 0건.
 */
describe('0건 항목은 위험색을 달지 않는다 (#1288)', () => {
  it('⚠️ 건수가 있는 것만 심각도 변형을 단다 — 타일', async () => {
    const { container } = renderWith(SNAPSHOT)
    await screen.findByText(DATA_QUALITY_COPY.summaryTitle)

    expect(container.querySelector('.dq__tile--substituted')).toBeTruthy() // 1건
    expect(container.querySelector('.dq__tile--anomaly')).toBeTruthy() // 1건
    expect(container.querySelector('.dq__tile--unavailable')).toBeNull() // 0건
  })

  it('⚠️ 건수가 있는 것만 심각도 변형을 단다 — 그룹', async () => {
    const { container } = renderWith(SNAPSHOT)
    await screen.findByText(DATA_QUALITY_COPY.summaryTitle)

    expect(container.querySelector('.dq__group--substituted')).toBeTruthy()
    expect(container.querySelector('.dq__group--anomaly')).toBeTruthy()
    expect(container.querySelector('.dq__group--unavailable')).toBeNull()
    expect(container.querySelector('.dq__group--unconfirmed')).toBeNull()
  })

  it('색을 뺀 자리에도 기본 띠는 남는다 — 중립 클래스를 새로 만들지 않았다', async () => {
    const { container } = renderWith(SNAPSHOT)
    await screen.findByText(DATA_QUALITY_COPY.summaryTitle)

    // 타일 넷(심각도 셋 + 완결성)과 그룹 넷이 모두 기본 클래스를 갖는다.
    expect(container.querySelectorAll('.dq__tile')).toHaveLength(4)
    expect(container.querySelectorAll('.dq__group')).toHaveLength(4)
  })
})

/**
 * 「이동」이 그 항차 카드로 간다 (#1549).
 *
 * 종전에는 모든 행이 `/vessels/:id` — 선박 상세 맨 위였다. 받는 쪽(`VoyagePanel`)이 카드로
 * 스크롤하는 것은 `VoyagePanel.test.tsx`가 보고, 여기서는 **어느 행이 어디로 가는가**를 본다.
 */
describe('점검 행에서 그 항차로 (#1549)', () => {
  it('항차 행은 그 항차로 간다 — 경로를 값으로 고정한다', async () => {
    renderWith(SNAPSHOT)
    const link = await screen.findByRole('link', { name: '이 항차로 — MV One B' })
    expect(link.getAttribute('href')).toBe('/vessels/v1?actuals=voy-2')
    expect(link.textContent).toBe('이 항차로')
  })

  it('선박 단위 행은 가리킬 항차가 없어 선박 상세로 간다', async () => {
    renderWith({
      ...SNAPSHOT,
      counts: { ...SNAPSHOT.counts, UNAVAILABLE: 1 },
      issues: [
        {
          severity: 'UNAVAILABLE',
          vesselId: 'v2',
          vesselName: 'MV Empty',
          voyageId: null,
          voyageNo: null,
          codes: ['NO_PARAMETERS'],
          cii: null,
          ciiReason: null,
        },
      ],
    })
    const link = await screen.findByRole('link', { name: '선박 상세' })
    expect(link.getAttribute('href')).toBe('/vessels/v2')
    expect(screen.queryByRole('link', { name: /이 항차로/ })).toBeNull()
  })
})

describe('CII 영향 사유는 표 아래 한 번 (#1580)', () => {
  function issue(voyageId: string, ciiReason: string | null) {
    return {
      severity: 'ANOMALY' as const,
      vesselId: `v-${voyageId}`,
      vesselName: `선박 ${voyageId}`,
      voyageId,
      voyageNo: voyageId,
      codes: ['FUEL_VS_MODEL'],
      cii: null,
      ciiReason,
    }
  }

  it('같은 사유가 다섯 행이어도 긴 문장은 표 아래 한 번이다', async () => {
    renderWith({ ...SNAPSHOT, issues: ['a', 'b', 'c', 'd', 'e'].map((id) => issue(id, 'ONLY_VOYAGE')) })

    const group = (await screen.findByRole('heading', { name: /이상치/ })).closest('section')!
    expect(within(group).getAllByText('비교 불가*')).toHaveLength(5)
    expect(within(group).getAllByText(/유일한 항차라/)).toHaveLength(1)
  })

  it('사유마다 표시가 다르고, 표에 나온 사유만 적는다', async () => {
    renderWith({ ...SNAPSHOT, issues: [issue('a', 'BASE_UNAVAILABLE'), issue('b', 'BASE_UNAVAILABLE')] })

    const group = (await screen.findByRole('heading', { name: /이상치/ })).closest('section')!
    expect(within(group).getAllByText('계산 불가**')).toHaveLength(2)
    expect(within(group).getByText('** 선박 누적 CII를 계산할 수 없어 차이를 낼 수 없습니다.')).toBeTruthy()
    expect(within(group).queryByText(/유일한 항차라/)).toBeNull()
  })

  it('두 사유가 섞이면 정해진 순서로 둘 다 적는다', async () => {
    renderWith({ ...SNAPSHOT, issues: [issue('a', 'BASE_UNAVAILABLE'), issue('b', 'ONLY_VOYAGE')] })

    const group = (await screen.findByRole('heading', { name: /이상치/ })).closest('section')!
    const notes = group.querySelectorAll('.dq__footnotes li')
    expect(Array.from(notes, (li) => li.textContent?.slice(0, 2))).toEqual(['* ', '**'])
  })

  it('모르는 사유는 코드 그대로 칸에 — 표 아래에는 적지 않는다', async () => {
    renderWith({ ...SNAPSHOT, issues: [issue('a', 'NEW_REASON')] })

    const group = (await screen.findByRole('heading', { name: /이상치/ })).closest('section')!
    expect(within(group).getByText('NEW_REASON')).toBeTruthy()
    expect(group.querySelector('.dq__footnotes')).toBeNull()
  })
})

describe('연도 선택지 — 조회 화면은 올해까지 · 최신 연도부터 (#1584)', () => {
  it('서버 목록 2023~2030 중 올해 이후를 빼고 최신 연도부터 보인다', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-06-01T00:00:00Z'))
    try {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () =>
          new Response(
            JSON.stringify({ data: [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030].map((year) => ({ year, z_factor_percent: '1.0000' })) }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
      )
      const provider: DataQualityProvider = { load: vi.fn(async () => SNAPSHOT) }
      render(
        <MemoryRouter>
          <DataQuality provider={provider} />
        </MemoryRouter>,
      )
      const select = (await screen.findByLabelText(DATA_QUALITY_COPY.yearLabel)) as HTMLSelectElement
      await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(4))
      expect([...select.options].map((o) => o.textContent)).toEqual(['2026', '2025', '2024', '2023'])
      expect(select.value).toBe('2026')
    } finally {
      vi.useRealTimers()
    }
  })
})
