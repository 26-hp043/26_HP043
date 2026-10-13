// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CalculationHistory } from './CalculationHistory'
import {
  WEATHER_AS_OF_LABEL,
  WEATHER_NOT_APPLIED_TEXT,
  weatherAsOfText,
} from '../../display/weatherAsOf'

/**
 * 재계산 필요 표시가 **화면에 보이는가** (#992 · `PRD §8.4`).
 *
 * `needs_recalc`는 켜지는데 보는 자리가 없었다(`#776` 정정). 규칙만 검사하면 화면이 그 값을
 * 그리지 않아도 초록이다.
 */
function run(id: string, needsRecalc: boolean) {
  return {
    calculation_run_id: id,
    calculation_type: 'VOYAGE_ESTIMATE',
    voyage_id: needsRecalc ? 'voy-1' : null,
    result_summary: { attained_cii: '5.000000', estimated_rating: 'C' },
    needs_recalc: needsRecalc,
    created_at: '2026-09-11T00:00:00Z',
  }
}

function respond(data: unknown[], meta: Record<string, unknown>) {
  return { ok: true, status: 200, json: async () => ({ data, meta }) } as Response
}

/** 조회 실패 — `fetchCalculationPage`가 `!response.ok`에서 던진다. */
function fail() {
  return { ok: false, status: 500, json: async () => ({}) } as Response
}

/*
 * 실패 표시의 본문. ⚠️ **문구로 찾지 않는다** — `ErrorState`는 제목과 본문 두 곳에 같은
 * 문장을 그려 두 노드가 잡힌다. 종전에는 본문에만 있던 `(HTTP 500)`으로 갈랐는데, 그
 * 숫자가 화면에 나가지 않는 것이 이제 지킬 성질이다(`#2221`).
 */
async function failureMessage(): Promise<string> {
  const alert = await screen.findByRole('alert')
  return alert.querySelector('.error-state__message')?.textContent ?? ''
}

describe('계산 이력 — 기상 기준 시각 (#2135)', () => {
  function scenarioRun(id: string, fetchedAt: string | null, modelUsed: string | null = fetchedAt === null ? 'NONE' : 'SIMPLE_RULE') {
    return {
      ...run(id, false),
      calculation_type: 'SCENARIO',
      result_summary: {},
      weather: {
        model_requested: 'SIMPLE_RULE',
        model_used: modelUsed,
        fetched_at: fetchedAt,
        warnings: modelUsed === 'NONE' ? ['WEATHER_NONE_FALLBACK'] : [],
      },
    }
  }

  it('보정한 항로 비교에만 기준 시각 줄이 나오고, 보정하지 않았으면 「보정 없이」가 나온다', async () => {
    const fetchImpl = vi.fn(async () =>
      respond(
        [scenarioRun('s1', '2026-10-06T00:00:00Z'), scenarioRun('s2', null), run('r1', false)],
        { next_cursor: null, has_more: false, needs_recalc_total: 0 },
      ),
    )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    expect(await screen.findByText(weatherAsOfText('2026-10-06T00:00:00Z') as string)).toBeTruthy()
    // 기상을 적용하지 않는 종류(CII 예측)는 줄이 없다 — 세 행 가운데 둘만 기상 줄을 가진다.
    expect(screen.getAllByText(WEATHER_NOT_APPLIED_TEXT)).toHaveLength(1)
    expect(screen.getAllByText(new RegExp(`^(${WEATHER_AS_OF_LABEL}|${WEATHER_NOT_APPLIED_TEXT})`))).toHaveLength(2)
  })

  it('보정했지만 받은 시각을 모르는 행에는 「보정 없이」를 적지 않는다 — 줄을 뺀다 (#2461)', async () => {
    // 스냅샷 행을 찾지 못했거나 `#904` 이전 계산 — 실제 모델은 보정 모델인데 시각이 없다.
    const fetchImpl = vi.fn(async () =>
      respond([scenarioRun('s1', null, 'SIMPLE_RULE'), scenarioRun('s2', null, null)], {
        next_cursor: null,
        has_more: false,
        needs_recalc_total: 0,
      }),
    )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    expect(await screen.findAllByText('현행')).toHaveLength(2)
    expect(screen.queryByText(WEATHER_NOT_APPLIED_TEXT)).toBeNull()
    expect(screen.queryByText(new RegExp(`^${WEATHER_AS_OF_LABEL}`))).toBeNull()
  })
})

describe('계산 이력 (#992)', () => {
  it('재계산 필요 계산을 배지로 표시하고 건수를 머리에 적는다', async () => {
    const fetchImpl = vi.fn(async () =>
      respond([run('r1', true), run('r2', false)], {
        next_cursor: null,
        has_more: false,
        needs_recalc_total: 1,
      }),
    )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    expect(await screen.findByText('재계산 필요 1건')).toBeTruthy()
    expect(screen.getAllByText('재계산 필요')).toHaveLength(1)
    expect(screen.getByText('현행')).toBeTruthy()
    // 항차에 붙은 계산(#817)은 표시가 따로 있다
    expect(screen.getByText('항차')).toBeTruthy()
  })

  it('다음 페이지를 커서로 받아 뒤에 붙인다', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        respond([run('r1', false)], {
          next_cursor: 'c2',
          has_more: true,
          needs_recalc_total: 1,
        }),
      )
      .mockResolvedValueOnce(
        respond([run('r2', true)], {
          next_cursor: null,
          has_more: false,
          needs_recalc_total: 1,
        }),
      )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    /*
     * ⚠️ 첫 페이지에는 낡은 계산이 **한 건도 없다.** 그래도 머리는 「1건」이다 —
     * 건수를 세는 주체가 화면이 아니라 서버이기 때문이다 (`#1076` ⑵).
     */
    expect(await screen.findByText('재계산 필요 1건')).toBeTruthy()

    fireEvent.click(await screen.findByRole('button', { name: '이전 계산 더 보기' }))
    expect(await screen.findByText('재계산 필요 1건')).toBeTruthy()
    expect(String(fetchImpl.mock.calls[1][0])).toContain('cursor=c2')
    expect(screen.getAllByText('CII 예측')).toHaveLength(2)
  })

  it('계산이 없으면 그렇다고 말한다 — 빈 표를 두지 않는다', async () => {
    const fetchImpl = vi.fn(async () =>
      respond([], { next_cursor: null, has_more: false, needs_recalc_total: 0 }),
    )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)
    expect(await screen.findByText('이 선박으로 실행한 계산이 없습니다.')).toBeTruthy()
  })
})

/**
 * **받은 것과 못 받은 것을 같이 다룬다** (`#1076` ⑵).
 *
 * 종전에는 상태가 `loading | error | ready` 한 덩어리라 「더 보기」가 실패하는 순간
 * `ready`가 통째로 `error`로 바뀌었다 — 이미 받은 20건이 화면에서 사라지고, 버튼도
 * `ready` 조건에 걸려 함께 사라져 **재시도할 자리조차 없었다.**
 */
describe('「더 보기」가 실패해도 받은 행을 버리지 않는다 (#1076 ⑵)', () => {
  const firstThenFail = () =>
    vi
      .fn()
      .mockResolvedValueOnce(
        respond([run('r1', false)], {
          next_cursor: 'c2',
          has_more: true,
          needs_recalc_total: 0,
        }),
      )
      .mockResolvedValueOnce(fail())

  it('2페이지 조회가 실패해도 1페이지 행이 남아 있다', async () => {
    const fetchImpl = firstThenFail()
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    fireEvent.click(await screen.findByRole('button', { name: '이전 계산 더 보기' }))

    const message = await failureMessage()
    expect(message).not.toBe('')
    // 조회가 500으로 실패했다 — 그 숫자는 화면에 나가지 않는다 (`#2221`).
    expect(message).not.toMatch(/HTTP|\d{3}/)
    // 숫자를 뺀 본문이 제목을 되풀이하지 않는다 — 같은 문장이 두 줄로 보이지 않게.
    const title = screen.getByRole('alert').querySelector('.error-state__title')?.textContent ?? ''
    expect(title).not.toBe('')
    expect(message.replace(/[.\s]/g, '')).not.toBe(title.replace(/[.\s]/g, ''))
    // 표가 그대로다 — 종전에는 여기서 `ErrorState` 하나만 남았다.
    expect(screen.getByText('CII 예측')).toBeTruthy()
    // 실패를 「계산이 없다」로 바꿔 말하지도 않는다.
    expect(screen.queryByText('이 선박으로 실행한 계산이 없습니다.')).toBeNull()
  })

  it('실패 뒤에도 다시 시도할 버튼이 남는다', async () => {
    const fetchImpl = firstThenFail().mockResolvedValueOnce(
      respond([run('r2', true)], {
        next_cursor: null,
        has_more: false,
        needs_recalc_total: 1,
      }),
    )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    fireEvent.click(await screen.findByRole('button', { name: '이전 계산 더 보기' }))
    await screen.findByRole('alert')

    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }))

    expect(await screen.findByText('재계산 필요 1건')).toBeTruthy()
    expect(screen.getAllByText('CII 예측')).toHaveLength(2)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('첫 페이지가 실패하면 「계산이 없습니다」로 말하지 않는다', async () => {
    const fetchImpl = vi.fn(async () => fail())
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    expect(await failureMessage()).not.toMatch(/HTTP|\d{3}/)
    expect(screen.queryByText('이 선박으로 실행한 계산이 없습니다.')).toBeNull()
  })

  it('서버가 건수를 싣지 않으면 건수를 적지 않는다 — 받은 행으로 대신 세지 않는다', async () => {
    /*
     * ⚠️ 이 응답에는 낡은 계산이 **한 건 보인다.** 그래도 머리에 「1건」을 적지
     * 않는다 — 화면이 아는 것은 「이 페이지에 한 건」뿐이고, 그것을 전체 건수로
     * 적는 것이 `#1076`이 고친 결함이기 때문이다.
     */
    const fetchImpl = vi.fn(async () =>
      respond([run('r1', true)], { next_cursor: null, has_more: false }),
    )
    render(<CalculationHistory vesselId="v1" fetchImpl={fetchImpl as unknown as typeof fetch} />)

    // 행 배지는 그대로 뜬다 — 그 행에 대한 사실이라 화면이 안다.
    expect(await screen.findByText('재계산 필요')).toBeTruthy()
    expect(screen.queryByText(/재계산 필요 \d+건/)).toBeNull()
  })
})
