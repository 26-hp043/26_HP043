// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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

  it('영향을 낼 수 없으면 0이 아니라 사유를 적는다', async () => {
    renderWith(SNAPSHOT)

    expect(await screen.findByText('이 항차뿐이라 빼고 비교할 값이 없습니다')).toBeTruthy()
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
