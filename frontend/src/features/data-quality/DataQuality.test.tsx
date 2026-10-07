// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { DataQuality } from './DataQuality'
import { DATA_QUALITY_COPY, SEVERITY_TITLE } from './copy'
import { formatTimestamp } from '../../display/format'
import { fuelTypeText } from '../parameters/fuelTypes'
import type { DataQualityProvider, DataQualitySnapshot } from './types'

/**
 * 데이터 점검 화면 (`UIFLOW 2-11` · #513).
 *
 * 판정은 서버 검사가 잠근다. 여기서는 **화면이 무엇을 숨기지 않는가**를 본다 —
 * 이 화면이 반쪽으로 열리지 않았던 이유(`PRD §5.2` 각주)가 「0건으로 읽히는 빈칸」이었다.
 */

const SNAPSHOT: DataQualitySnapshot = {
  regulationYear: 2026,
  counts: { SUBSTITUTED: 1, UNAVAILABLE: 0, ANOMALY: 1, UNCONFIRMED: 0, PUBLIC_RECORD: 0 },
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
      publicRecord: null,
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
      publicRecord: null,
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

/** 점검 항목 목록 — `#1766`이 그룹 표 넷을 한 표로 합쳤다. */
async function listSection(): Promise<HTMLElement> {
  await screen.findByRole('heading', { name: DATA_QUALITY_COPY.listTitle })
  return document.querySelector('.dq__list') as HTMLElement
}

describe('데이터 점검 화면 (#513)', () => {
  it('⚠️ 다섯 심각도를 항상 보인다 — 0건도 지우지 않는다 (#513 · #1766)', async () => {
    renderWith(SNAPSHOT)

    /*
     * `#1766`이 그룹 표 넷을 한 표로 합치면서 그룹 제목이 없어졌다. **0건을 지운 것이
     * 아니다** — 요약 띠의 칸이 그 자리를 이어받는다. 「확인했고 0건이다」가 화면에
     * 남아 있는지는 그대로 본다(지우면 「확인 안 함」과 구분되지 않는다).
     */
    /*
     * 10/7(#2319) — 같은 크기 타일 여섯이 요약 영역(처리할 일 · 완결성 + 거르기 칩)으로 바뀌었다.
     * 0건 심각도는 지우지 않고 흐린 칩 하나에 「이름 0」으로 모은다.
     */
    const hero = await screen.findByLabelText(DATA_QUALITY_COPY.summaryTitle)
    for (const title of Object.values(SEVERITY_TITLE)) {
      expect(hero.textContent, title).toContain(title)
    }
    // 계산 불가·실적 확정 전·공적 기록과 다름은 0건 — 지우지 않고 0을 보인다.
    const zero = hero.querySelector('.dq-chip--zero')?.textContent ?? ''
    for (const severity of ['UNAVAILABLE', 'UNCONFIRMED', 'PUBLIC_RECORD'] as const) {
      expect(zero).toContain(`${SEVERITY_TITLE[severity]} 0`)
    }
    // 건수가 있는 것은 0 칩에 섞이지 않는다
    expect(zero).not.toContain(SEVERITY_TITLE.SUBSTITUTED)
    expect(zero).not.toContain(SEVERITY_TITLE.ANOMALY)
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

    const group = await listSection()
    expect(within(group).getByText('+0.223')).toBeTruthy()
    expect(within(group).getByLabelText('이 항차가 없으면 B, 있으면 C')).toBeTruthy()
    expect(screen.getByText(DATA_QUALITY_COPY.impactCaption)).toBeTruthy()
  })

  it('영향을 낼 수 없으면 0으로 적지 않는다 — 숫자가 있을 때만 영향 줄을 단다 (#1580 · 10/7)', async () => {
    renderWith(SNAPSHOT)

    const group = await listSection()
    // 10/7(#2319) — 할 일 카드에서 CII 영향은 숫자일 때만 보인다(표 아래 각주는 없앴다).
    const withImpact = group.querySelector('.dq-task--substituted') as HTMLElement // 영향 +0.2234
    const withoutImpact = group.querySelector('.dq-task--anomaly') as HTMLElement // ONLY_VOYAGE — 낼 수 없다
    expect(withImpact.querySelector('.dq-task__detail')?.textContent).toContain('+0.223')
    const detail = withoutImpact.querySelector('.dq-task__detail')?.textContent ?? ''
    expect(detail).not.toContain('영향')
    expect(detail).not.toMatch(/(^|\s)[+-]?0(\.0+)?(\s|$)/)
  })

  it('항차가 없는 선박은 「계산 불가」가 아니라 「실적 항차 없음」이다', async () => {
    renderWith(SNAPSHOT)

    expect(await screen.findByText(DATA_QUALITY_COPY.noActualVoyages)).toBeTruthy()
  })

  it('사유 코드는 사람이 읽는 문구로 — 유종은 다른 자리와 같은 표기로 붙인다 (#2122)', async () => {
    renderWith(SNAPSHOT)

    // 코드 원문 `(HFO)`가 아니라 연료 칸과 같은 표기다 — 같은 연료가 한 화면에서 두 이름이 되지 않는다.
    // 10/7(#2319) — 서버 사유 문장은 할 일 카드의 「상세」 줄에 남는다.
    const group = await listSection()
    const details = [...group.querySelectorAll('.dq-task__detail')].map((node) => node.textContent ?? '')
    const item = details.find((text) => text.includes(fuelTypeText('HFO')))
    expect(item).toBeTruthy()
    expect(item).not.toContain('FUEL:HFO')
    // 사유 문구가 앞에 있다 — 연료 이름만 남지 않는다.
    expect(item!.indexOf(fuelTypeText('HFO'))).toBeGreaterThan(item!.indexOf('상세') + 2)
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
  it('⚠️ 건수가 있는 것만 심각도 변형을 단다 — 요약 칩', async () => {
    const { container } = renderWith(SNAPSHOT)
    await screen.findByLabelText(DATA_QUALITY_COPY.summaryTitle)

    // 10/7(#2319) — 타일이 거르기 칩이 됐다. 색(심각도 변형)은 건수가 있는 칩에만 붙는다.
    expect(container.querySelector('.dq-chip--substituted')).toBeTruthy() // 1건
    expect(container.querySelector('.dq-chip--anomaly')).toBeTruthy() // 1건
    expect(container.querySelector('.dq-chip--unavailable')).toBeNull() // 0건
    expect(container.querySelector('.dq-chip--unconfirmed')).toBeNull() // 0건
    expect(container.querySelector('.dq-chip--public_record')).toBeNull() // 0건
  })

  it('⚠️ 표의 심각도 칩은 늘 색을 단다 — 행이 있다는 것이 곧 볼 것이 있다는 뜻이다 (#1766)', async () => {
    const { container } = renderWith(SNAPSHOT)
    await listSection()

    /*
     * `#1288`의 조건은 **건수 0**이다. 행이 있는 심각도는 정의상 0건이 아니므로 칩에서는
     * 그 조건이 성립할 수 없다 — 0건일 때 색을 빼는 판단은 요약 띠가 맡는다(위 검사).
     */
    expect(container.querySelector('.dq__severity--substituted')).toBeTruthy()
    expect(container.querySelector('.dq__severity--anomaly')).toBeTruthy()
    expect(container.querySelector('.dq__severity--unavailable')).toBeNull() // 행이 없다
  })

  it('색을 뺀 자리에도 기본 칩 모양은 남는다 — 0건 칩도 같은 칩이다', async () => {
    const { container } = renderWith(SNAPSHOT)
    const hero = await screen.findByLabelText(DATA_QUALITY_COPY.summaryTitle)

    // 모든 칩이 같은 기본 클래스를 갖는다 — 0건 칩은 심각도 변형만 빠진다.
    const chips = [...hero.querySelectorAll('.dq-chip')]
    expect(chips.length).toBeGreaterThan(0)
    const zero = container.querySelector('.dq-chip--zero')!
    expect(zero.classList.contains('dq-chip')).toBe(true)
    expect([...zero.classList].some((name) => /^dq-chip--(substituted|anomaly|unavailable|unconfirmed|public_record)$/.test(name))).toBe(false)
  })

  it('칩으로 거르면 그 심각도의 할 일만 남고, 누른 칩이 눌림 상태를 말한다', async () => {
    renderWith(SNAPSHOT)
    const hero = await screen.findByLabelText(DATA_QUALITY_COPY.summaryTitle)
    const group = await listSection()
    const chipFor = (title: string) =>
      within(hero).getByRole('button', { name: new RegExp(`^${title}`) })
    const all = within(hero).getAllByRole('button').find((chip) => chip.getAttribute('aria-pressed') === 'true')!
    expect(group.querySelectorAll('.dq-task')).toHaveLength(2)

    fireEvent.click(chipFor(SEVERITY_TITLE.ANOMALY))
    expect(chipFor(SEVERITY_TITLE.ANOMALY).getAttribute('aria-pressed')).toBe('true')
    expect(all.getAttribute('aria-pressed')).toBe('false')
    const left = [...group.querySelectorAll('.dq-task')]
    expect(left).toHaveLength(1)
    expect(left[0].classList.contains('dq-task--anomaly')).toBe(true)

    // 다시 누르면 풀린다
    fireEvent.click(chipFor(SEVERITY_TITLE.ANOMALY))
    expect(group.querySelectorAll('.dq-task')).toHaveLength(2)
    expect(all.getAttribute('aria-pressed')).toBe('true')
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
    const group = await listSection()
    const link = within(group).getByRole('link', { name: /MV One B$/ })
    expect(link.getAttribute('href')).toBe('/vessels/v1?actuals=voy-2')
    // 10/7(#2319) — 버튼 글은 「할 일」이다. 낭독 이름이 보이는 글로 시작해야 둘이 어긋나지 않는다.
    const visible = (link.textContent ?? '').replace(/\s*→\s*$/, '')
    expect(visible.length).toBeGreaterThan(0)
    expect(link.getAttribute('aria-label')?.startsWith(visible)).toBe(true)
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
          publicRecord: null,
        },
      ],
    })
    const group = await listSection()
    const links = within(group.querySelector('.dq-tasks') as HTMLElement).getAllByRole('link')
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('/vessels/v2')
    expect(links[0].textContent?.trim()).not.toBe('')
  })
})

/**
 * 다섯째 심각도 `PUBLIC_RECORD` — 공적 재항 기록과의 대조 (#1197).
 */
describe('공적 기록과 다름 (#1197)', () => {
  function publicRecordIssue() {
    return {
      severity: 'PUBLIC_RECORD' as const,
      vesselId: 'v1',
      vesselName: 'MV One',
      voyageId: 'voy-9',
      voyageNo: 'D',
      codes: ['PUBLIC_RECORD:ARRIVAL'],
      cii: null,
      ciiReason: null,
      publicRecord: {
        source: 'MOF_VESSEL_OPS',
        fetchedAt: '2026-09-26T01:00:00+00:00',
        voyageStatus: 'COMPLETED' as string | null,
        mismatches: [
          {
            field: 'ARRIVAL' as const,
            enteredAt: '2026-08-08T17:20:00+00:00',
            recordedAt: '2026-08-08T05:20:00+00:00',
            differenceMinutes: 720,
            portAuthorityCode: '020',
            portAuthorityName: '부산',
            callYear: 2026 as number | null,
            callSeq: '029' as string | null,
            periodId: null as string | null,
          },
        ],
      },
    }
  }

  function snapshotWithPublicRecord(): DataQualitySnapshot {
    return {
      ...SNAPSHOT,
      counts: { ...SNAPSHOT.counts, PUBLIC_RECORD: 1 },
      issues: [publicRecordIssue()],
    }
  }

  it('요약에 다섯째 심각도 칩으로 보인다', async () => {
    renderWith(snapshotWithPublicRecord())

    const hero = await screen.findByLabelText(DATA_QUALITY_COPY.summaryTitle)
    const chip = hero.querySelector('.dq-chip--public_record')
    expect(chip?.textContent).toContain(SEVERITY_TITLE.PUBLIC_RECORD)
    expect(chip?.textContent).toContain('1')
  })

  it('행마다 어긋남을 한 줄로 적는다 — 입력·공적 기록·항만청·차이', async () => {
    renderWith(snapshotWithPublicRecord())

    const group = await listSection()
    // 심각도 칩은 여기서 보지 않는다 — 접힌 「심각도가 뜻하는 것」 범례도 같은 표 문구를
    // 갖고 있어 `getByText`가 둘을 함께 찾는다(범례는 `.dq__list` 안에 함께 산다).
    expect(group.querySelector('.dq__severity--public_record')?.textContent).toBe(
      SEVERITY_TITLE.PUBLIC_RECORD,
    )
    const line = within(group).getByText(
      `도착 시각 입력 ${formatTimestamp('2026-08-08T17:20:00+00:00')} · 공적 기록 ${formatTimestamp('2026-08-08T05:20:00+00:00')} (부산) · 12시간 0분 차이`,
    )
    expect(line).toBeTruthy()
  })

  it('출처를 「해양수산부 선박운항정보(공공데이터포털) · 수집 시각 기준」으로 적는다', async () => {
    renderWith(snapshotWithPublicRecord())

    const group = await listSection()
    expect(
      within(group).getByText(`출처: 해양수산부 선박운항정보(공공데이터포털) · ${formatTimestamp('2026-09-26T01:00:00+00:00')} 기준`),
    ).toBeTruthy()
  })

  it('항만청 이름이 없으면 코드로 대신한다', async () => {
    const snapshot = snapshotWithPublicRecord()
    snapshot.issues[0] = {
      ...snapshot.issues[0],
      publicRecord: {
        ...snapshot.issues[0].publicRecord!,
        mismatches: [{ ...snapshot.issues[0].publicRecord!.mismatches[0], portAuthorityName: null }],
      },
    }
    renderWith(snapshot)

    const group = await listSection()
    expect(within(group).getByText(/\(020\)/)).toBeTruthy()
  })

  it('PUBLIC_RECORD가 아닌 행에는 어긋남 줄도 출처 줄도 없다', async () => {
    renderWith(SNAPSHOT)

    const group = await listSection()
    expect(group.querySelector('.dq__mismatches')).toBeNull()
    expect(group.querySelector('.dq__source')).toBeNull()
  })
})

/**
 * 「이 값으로 채우기」 (#1923 · `PRD §17.4.4`).
 *
 * 문구는 표시 문구라 리터럴로 단언하지 않는다(`AGENTS §4.6`) — `copy.ts`의 값을 가져와
 * **성질**(누르기 전에는 부르지 않는다 · 확정 항차는 한 번 더 묻는다 · 동의 표시가 실린다)을 본다.
 */
describe('이 값으로 채우기 (#1923)', () => {
  function fillSnapshot(voyageStatus: string): DataQualitySnapshot {
    return {
      ...SNAPSHOT,
      counts: { ...SNAPSHOT.counts, PUBLIC_RECORD: 1 },
      issues: [
        {
          severity: 'PUBLIC_RECORD',
          vesselId: 'v1',
          vesselName: 'MV One',
          voyageId: 'voy-9',
          voyageNo: 'D',
          codes: ['PUBLIC_RECORD:ARRIVAL'],
          cii: null,
          ciiReason: null,
          publicRecord: {
            source: 'MOF_VESSEL_OPS',
            fetchedAt: '2026-09-26T01:00:00+00:00',
            voyageStatus,
            mismatches: [
              {
                field: 'ARRIVAL',
                enteredAt: '2026-08-08T17:20:00+00:00',
                recordedAt: '2026-08-08T05:20:00+00:00',
                differenceMinutes: 720,
                portAuthorityCode: '020',
                portAuthorityName: '부산',
                callYear: 2026,
                callSeq: '029',
                periodId: null,
              },
            ],
          },
        },
      ],
    }
  }

  function renderFill(snapshot: DataQualitySnapshot, fill: DataQualityProvider['fill']) {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    const provider: DataQualityProvider = { load: vi.fn(async () => snapshot), fill }
    render(
      <MemoryRouter>
        <DataQuality provider={provider} />
      </MemoryRouter>,
    )
    return provider
  }

  function fillButton(group: HTMLElement): HTMLButtonElement {
    return within(group).getByRole('button', {
      name: new RegExp(`^${DATA_QUALITY_COPY.fillAction}`),
    }) as HTMLButtonElement
  }

  it('누르지 않으면 부르지 않는다 — 조회만으로는 아무것도 보내지 않는다', async () => {
    const fill = vi.fn(async () => ({ field: 'ARRIVAL' as const, revertedFromStatus: null }))
    renderFill(fillSnapshot('COMPLETED'), fill)

    const group = await listSection()
    expect(fillButton(group)).toBeTruthy()
    expect(fill).not.toHaveBeenCalled()
  })

  it('완료 항차는 누르면 그 칸 하나를 되돌림 동의 없이 보내고, 다시 불러온다', async () => {
    const fill = vi.fn(async () => ({ field: 'ARRIVAL' as const, revertedFromStatus: null }))
    const provider = renderFill(fillSnapshot('COMPLETED'), fill)

    const group = await listSection()
    fireEvent.click(fillButton(group))

    await waitFor(() => expect(fill).toHaveBeenCalledTimes(1))
    expect(fill).toHaveBeenCalledWith('voy-9', {
      field: 'ARRIVAL',
      periodId: null,
      record: { source: 'MOF_VESSEL_OPS', portAuthorityCode: '020', callYear: 2026, callSeq: '029' },
      recordedAt: '2026-08-08T05:20:00+00:00',
      revertConfirmed: false,
    })
    await waitFor(() => expect(provider.load).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('status')).toBeTruthy()
  })

  it('확정 항차는 바로 보내지 않고 재확인 줄을 연다 — 그만두면 아무것도 보내지 않는다', async () => {
    const fill = vi.fn(async () => ({ field: 'ARRIVAL' as const, revertedFromStatus: 'CONFIRMED' }))
    renderFill(fillSnapshot('CONFIRMED'), fill)

    const group = await listSection()
    const trigger = fillButton(group)
    fireEvent.click(trigger)

    expect(fill).not.toHaveBeenCalled()
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    const caution = within(group).getByRole('group', { name: DATA_QUALITY_COPY.fillConfirmedCaution })
    // 안전한 쪽에 초점이 먼저 간다
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(caution).getByRole('button', { name: DATA_QUALITY_COPY.fillKeep }),
      ),
    )
    fireEvent.click(within(caution).getByRole('button', { name: DATA_QUALITY_COPY.fillKeep }))
    expect(within(group).queryByRole('group', { name: DATA_QUALITY_COPY.fillConfirmedCaution })).toBeNull()
    expect(fill).not.toHaveBeenCalled()
  })

  it('확정 항차는 재확인 줄의 실행 버튼을 눌러야 되돌림 동의(revertConfirmed)를 싣는다', async () => {
    const fill = vi.fn(async () => ({ field: 'ARRIVAL' as const, revertedFromStatus: 'CONFIRMED' }))
    renderFill(fillSnapshot('CONFIRMED'), fill)

    const group = await listSection()
    fireEvent.click(fillButton(group))
    const caution = within(group).getByRole('group', { name: DATA_QUALITY_COPY.fillConfirmedCaution })
    fireEvent.click(within(caution).getByRole('button', { name: DATA_QUALITY_COPY.fillConfirmedAction }))

    await waitFor(() => expect(fill).toHaveBeenCalledTimes(1))
    expect(fill).toHaveBeenCalledWith('voy-9', expect.objectContaining({ revertConfirmed: true }))
    const done = await screen.findByRole('status')
    // 되돌렸다는 알림은 되돌리지 않은 알림과 다르다 — 재확정이 사용자 몫이라는 것이 전해져야 한다.
    expect(done.textContent).not.toBe(DATA_QUALITY_COPY.fillDone('도착 시각', 'D'))
    expect(done.textContent).toBe(DATA_QUALITY_COPY.fillDoneReverted('도착 시각', 'D'))
  })

  it('서버가 거절하면 그 문구를 누른 줄 곁에 보이고, 다시 불러오지 않는다', async () => {
    const message = 'SERVER-REFUSED'
    const fill = vi.fn(async () => {
      throw new Error(message)
    })
    const provider = renderFill(fillSnapshot('COMPLETED'), fill)

    const group = await listSection()
    fireEvent.click(fillButton(group))

    expect((await within(group).findByRole('alert')).textContent).toBe(message)
    expect(provider.load).toHaveBeenCalledTimes(1)
    expect(fillButton(group).disabled).toBe(false)
  })

  it('채우기 열쇠가 없으면(옛 서버) 버튼을 두지 않는다', async () => {
    const snapshot = fillSnapshot('COMPLETED')
    const record = snapshot.issues[0].publicRecord!
    snapshot.issues[0] = {
      ...snapshot.issues[0],
      publicRecord: { ...record, mismatches: [{ ...record.mismatches[0], callYear: null, callSeq: null }] },
    }
    renderFill(snapshot, vi.fn())

    const group = await listSection()
    expect(within(group).queryByRole('button', { name: new RegExp(`^${DATA_QUALITY_COPY.fillAction}`) })).toBeNull()
  })

  it('정박 칸에 구간 id가 없으면 버튼을 두지 않는다 — 서버가 거절할 버튼이다', async () => {
    const snapshot = fillSnapshot('COMPLETED')
    const record = snapshot.issues[0].publicRecord!
    snapshot.issues[0] = {
      ...snapshot.issues[0],
      codes: ['PUBLIC_RECORD:BERTH_START'],
      publicRecord: { ...record, mismatches: [{ ...record.mismatches[0], field: 'BERTH_START', periodId: null }] },
    }
    renderFill(snapshot, vi.fn())

    const group = await listSection()
    expect(within(group).queryByRole('button', { name: new RegExp(`^${DATA_QUALITY_COPY.fillAction}`) })).toBeNull()
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

describe('연도 칸 상태 — 문구 없는 빈 상자가 아니다 (#2120)', () => {
  async function yearTextFor(response: () => Response) {
    vi.stubGlobal('fetch', vi.fn(async () => response()))
    const provider: DataQualityProvider = { load: vi.fn(async () => SNAPSHOT) }
    const { unmount } = render(
      <MemoryRouter>
        <DataQuality provider={provider} />
      </MemoryRouter>,
    )
    const note = await screen.findByText(/규제연도/, { selector: '.dq__note' })
    const text = note.textContent
    // 목록이 없으면 연도 칸은 선택 상자가 아니라 상태 문구다.
    expect(screen.queryByRole('combobox', { name: DATA_QUALITY_COPY.yearLabel })).toBeNull()
    unmount()
    return text
  }

  it('실패와 빈 목록이 서로 다른 문구를 보인다', async () => {
    const failed = await yearTextFor(() => new Response('{}', { status: 500 }))
    const empty = await yearTextFor(() => new Response(JSON.stringify({ data: [] }), { status: 200 }))
    expect(failed).not.toBe(empty)
  })
})
