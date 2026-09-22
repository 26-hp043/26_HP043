// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import { ReportsView } from './ReportsView'
import type { ReportsProvider, VesselOption, VoyageOption } from './types'

/**
 * 보고서 화면의 **조회 상태 3상태** (#824 ⑵).
 *
 * ## 무엇이 문제였나
 *
 * 항차 재조회에 **이 저장소에서 유일하게 취소 플래그가 없었다**(다른 열 곳은 전부
 * 갖고 있다). 게다가 단발이 아니라 **커서 전량 순회**라 응답 시간이 항차 수에
 * 비례한다. 세 결함이 겹쳐 있었다.
 *
 * - **경합** — 항차가 많은 A → 적은 B로 전환하면 **B가 먼저 오고 A가 덮어쓴다.**
 *   선박 셀렉트는 B인데 항차 셀렉트는 A의 항차이고, 그대로 만들면 **선박 B 화면에서
 *   선박 A의 문서**가 나오거나 404/422가 난다.
 * - **잔류** — `setVoyages(null)`이 없어 두 번째 선박부터 「불러오는 중」이 영영 안
 *   뜬다. 사용자는 A의 항차를 B의 것으로 읽는다.
 * - **실패 은폐** — `.catch(() => setVoyages([]))` → 항차가 1,000건이어도 「이 선박에
 *   등록된 항차가 없습니다」.
 *
 * ⚠️ **같은 파일이 스스로 세운 규칙을 어기고 있었다** — 선박·연도 셀렉트는 「불러오는
 * 중」과 「없음」을 구분한다(`#613`). 항차 셀렉트만 예외였다.
 */

const VESSELS: VesselOption[] = [
  { id: 'v-a', name: 'STAR SKIPPER', imoNumber: '9876543' },
  { id: 'v-b', name: 'PAN HORIZON', imoNumber: '9876544' },
]

function voyage(id: string, no: string): VoyageOption {
  return {
    id,
    voyageNo: no,
    status: 'CONFIRMED',
    regulationYear: 2026,
    departurePortName: 'BUSAN',
    arrivalPortName: 'SINGAPORE',
    reportable: true,
  }
}

const A_VOYAGES = [voyage('a-1', 'A-2026-01')]
const B_VOYAGES = [voyage('b-1', 'B-2026-01')]

function stub(over: Partial<ReportsProvider> = {}): ReportsProvider {
  return {
    listVessels: vi.fn(async () => VESSELS),
    listVoyages: vi.fn(async () => A_VOYAGES),
    previewHtml: vi.fn(async () => '<p>preview</p>'),
    download: vi.fn(async () => 'report.pdf'),
    ...over,
  }
}

/** 「항차 완료」로 바꾼다 — 항차 셀렉트는 그때만 그려진다. */
async function chooseVoyageKind() {
  fireEvent.click(await screen.findByTestId('kind-voyage'))
}

/** 선박 셀렉트. 라벨이 `<span>`이라 `data-testid`로 잡는다(화면의 기존 관례). */
function vesselSelect(): HTMLSelectElement {
  return screen.getByTestId('vessel-select') as HTMLSelectElement
}

describe('선박을 바꾸면 항차 목록이 어긋나지 않는다 (#824 ⑵)', () => {
  it('늦게 도착한 옛 선박의 항차가 새 선박 화면을 덮지 않는다', async () => {
    let releaseA: ((rows: VoyageOption[]) => void) | null = null
    const provider = stub({
      listVoyages: vi.fn(async (vesselId: string) => {
        if (vesselId === 'v-a') {
          return new Promise<VoyageOption[]>((resolve) => {
            releaseA = resolve
          })
        }
        return B_VOYAGES
      }),
    })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })
    // A가 아직 응답하지 않은 채 B로 넘어간다.
    fireEvent.change(vesselSelect(), { target: { value: 'v-b' } })
    expect(await screen.findByText(/B-2026-01/)).toBeTruthy()

    // 이제서야 A가 돌아온다. 종전에는 이 한 줄이 B의 목록을 덮었다.
    await import('@testing-library/react').then(({ act }) =>
      act(async () => {
        releaseA?.(A_VOYAGES)
      }),
    )

    expect(screen.getByText(/B-2026-01/)).toBeTruthy()
    expect(screen.queryByText(/A-2026-01/)).toBeNull()
  })

  it('전환 직후 「불러오는 중」이 다시 뜬다 — 옛 항차가 남지 않는다', async () => {
    let releaseB: ((rows: VoyageOption[]) => void) | null = null
    const provider = stub({
      listVoyages: vi.fn(async (vesselId: string) => {
        if (vesselId === 'v-a') return A_VOYAGES
        return new Promise<VoyageOption[]>((resolve) => {
          releaseB = resolve
        })
      }),
    })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })
    expect(await screen.findByText(/A-2026-01/)).toBeTruthy()

    fireEvent.change(vesselSelect(), { target: { value: 'v-b' } })

    /*
     * 종전에는 `setVoyages(null)`이 없어 **두 번째 선박부터 이 문구가 영영 안 떴고**,
     * 사용자는 A의 항차를 B의 것으로 읽었다.
     */
    expect(await screen.findByText(/항차 목록을 불러오는 중입니다/)).toBeTruthy()
    expect(screen.queryByText(/A-2026-01/)).toBeNull()

    await import('@testing-library/react').then(({ act }) =>
      act(async () => {
        releaseB?.(B_VOYAGES)
      }),
    )
    expect(await screen.findByText(/B-2026-01/)).toBeTruthy()
  })

  it('조회 실패를 「항차 없음」으로 말하지 않는다', async () => {
    const provider = stub({
      listVoyages: vi.fn(async () => {
        throw new Error('서버 오류')
      }),
    })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    await waitFor(() => expect(vesselSelect().querySelectorAll('option').length).toBeGreaterThan(1))
    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })

    /*
     * ⚠️ 종전에는 실패도 `[]`라 **항차가 1,000건이어도** 「등록된 항차가 없습니다」로
     * 나갔다 — 원인이 뒤바뀐다.
     */
    expect(await screen.findByText(/항차 목록을 불러오지 못했습니다/)).toBeTruthy()
    expect(screen.queryByText(/등록된 항차가 없습니다/)).toBeNull()
  })

  it('진짜로 항차가 없으면 종전대로 「없음」이다', async () => {
    const provider = stub({ listVoyages: vi.fn(async () => []) })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    await waitFor(() => expect(vesselSelect().querySelectorAll('option').length).toBeGreaterThan(1))
    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })

    expect(await screen.findByText(/등록된 항차가 없습니다/)).toBeTruthy()
    expect(screen.queryByText(/불러오지 못했습니다/)).toBeNull()
  })

  it('선박을 고르기 전에는 「불러오는 중」을 말하지 않는다', async () => {
    render(<ReportsView provider={stub()} />)
    await chooseVoyageKind()

    await waitFor(() => expect(vesselSelect()).toBeTruthy())
    expect(screen.queryByText(/항차 목록을 불러오는 중/)).toBeNull()
  })
})

/**
 * 선박 목록의 **실패와 없음** (`#1076` ⑴).
 *
 * 항차 칸이 `#824` ⑵에서 고쳐진 뒤에도 **선박 칸만 `[]`로 떨어지고 있었다.** 게다가
 * 실패 문구를 리포트 생성 오류 칸(`failure`)에 담아, `run()`의 `setFailure(null)`이
 * 그것을 지웠다 — 「미리보기」를 한 번 누르면 **오류는 사라지고 「등록된 선박이
 * 없습니다」만 남아** 원인이 정반대로 읽혔다.
 */
describe('선박 목록 조회 실패를 「선박 없음」으로 말하지 않는다 (#1076 ⑴)', () => {
  const failing = () =>
    stub({
      listVessels: vi.fn(async () => {
        throw new Error('서버 오류')
      }),
    })

  it('실패했을 때 「등록된 선박이 없습니다」가 나오지 않는다', async () => {
    render(<ReportsView provider={failing()} />)

    expect(await screen.findByText(/선박 목록을 불러오지 못했습니다/)).toBeTruthy()
    expect(screen.queryByText(/등록된 선박이 없습니다/)).toBeNull()
  })

  it('미리보기를 눌러도 실패 표시가 지워지지 않는다', async () => {
    render(<ReportsView provider={failing()} />)
    await screen.findByText(/선박 목록을 불러오지 못했습니다/)

    // 이 버튼이 `setFailure(null)`을 부른다 — 종전에는 여기서 원인이 뒤바뀌었다.
    fireEvent.click(screen.getByTestId('preview-button'))

    await waitFor(() =>
      expect(screen.queryByText(/등록된 선박이 없습니다/)).toBeNull(),
    )
    expect(screen.getByText(/선박 목록을 불러오지 못했습니다/)).toBeTruthy()
  })

  it('진짜로 선박이 없으면 종전대로 「없음」이다', async () => {
    render(<ReportsView provider={stub({ listVessels: vi.fn(async () => []) })} />)

    expect(await screen.findByText(/등록된 선박이 없습니다/)).toBeTruthy()
    expect(screen.queryByText(/선박 목록을 불러오지 못했습니다/)).toBeNull()
  })
})

/**
 * 상단바의 선박·항차 선택을 따른다 (#1414 · `DESIGN_SYSTEM §7.2` 🔒).
 *
 * 종전에는 셸에서 배를 고르고 들어와도 「선택하세요」로 시작했다. 셸 밖 렌더(위 검사들)는
 * 선택이 없는 셸과 같아야 하므로 그 동작은 바꾸지 않는다 — 위 검사들이 그대로 지킨다.
 */
function renderInShell(
  provider: ReportsProvider,
  context: Partial<ShellContext> = {},
) {
  const value: ShellContext = { ...EMPTY_SHELL_CONTEXT, vesselsState: 'ready', ...context }
  return render(
    <MemoryRouter initialEntries={['/reports']}>
      <Routes>
        <Route element={<Outlet context={value} />}>
          <Route path="/reports" element={<ReportsView provider={provider} />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

/**
 * 셸 선택을 테스트 안에서 바꿀 수 있는 하네스. 상단바에서 선택을 지우는 동작을 버튼으로 흉내 낸다
 * — 바꾸는 함수를 밖으로 꺼내면 렌더 중 외부 값을 고치게 된다(`react(immutability)`).
 */
function renderSwitchableShell(provider: ReportsProvider, initialVesselId: string | null) {
  function Harness() {
    const [vesselId, setVesselId] = useState<string | null>(initialVesselId)
    const value: ShellContext = {
      ...EMPTY_SHELL_CONTEXT,
      vesselId,
      vesselsState: 'ready',
      selectVesselId: setVesselId,
    }
    return (
      <MemoryRouter initialEntries={['/reports']}>
        <button type="button" onClick={() => setVesselId(null)}>
          상단바 선택 지우기
        </button>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/reports" element={<ReportsView provider={provider} />} />
          </Route>
        </Routes>
      </MemoryRouter>
    )
  }
  render(<Harness />)
}

function voyageSelect(): HTMLSelectElement {
  return screen.getByTestId('voyage-select') as HTMLSelectElement
}

describe('상단바 선택을 따른다 (#1414)', () => {
  it('셸에 고른 선박이 있으면 그 선박으로 시작한다', async () => {
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-b' })

    await waitFor(() => expect(vesselSelect().value).toBe('v-b'))
    // 보이는 선택과 조회 대상이 같아야 한다 — 셀렉트만 바뀌고 항차는 다른 배 것이면 안 된다.
    await waitFor(() => expect(provider.listVoyages).toHaveBeenCalledWith('v-b'))
  })

  it('여기서 선박을 바꾸면 상단바도 바뀐다', async () => {
    const selectVesselId = vi.fn()
    renderInShell(stub(), { vesselId: 'v-a', selectVesselId })
    await waitFor(() => expect(vesselSelect().value).toBe('v-a'))

    fireEvent.change(vesselSelect(), { target: { value: 'v-b' } })

    expect(selectVesselId).toHaveBeenCalledWith('v-b')
  })

  it('셸이 기억한 선박이 목록에 없으면 비우고 말한다 — 그 id로 조회하지 않는다', async () => {
    const provider = stub()
    const selectVesselId = vi.fn()
    renderInShell(provider, { vesselId: 'v-deleted', selectVesselId })

    expect(await screen.findByText(/상단바에서 고른 선박이 목록에 없습니다/)).toBeTruthy()
    expect(selectVesselId).toHaveBeenCalledWith(null)
    expect(vesselSelect().value).toBe('')
    expect(provider.listVoyages).not.toHaveBeenCalledWith('v-deleted')
  })

  it('상단바에서 선택을 지우면 이 화면도 비운다', async () => {
    renderSwitchableShell(stub(), 'v-a')
    await waitFor(() => expect(vesselSelect().value).toBe('v-a'))

    fireEvent.click(screen.getByRole('button', { name: '상단바 선택 지우기' }))

    await waitFor(() => expect(vesselSelect().value).toBe(''))
  })

  it('셸 항차가 리포트를 만들 수 있으면 그 항차로 시작한다', async () => {
    const provider = stub({
      listVoyages: vi.fn(async () => [voyage('a-1', 'A-2026-01'), voyage('a-2', 'A-2026-02')]),
    })
    renderInShell(provider, { vesselId: 'v-a', voyageId: 'a-2' })
    await chooseVoyageKind()

    await waitFor(() => expect(voyageSelect().value).toBe('a-2'))
  })

  it('셸 항차가 완료 전이면 고르지 않고 이유를 말한다', async () => {
    const running: VoyageOption = { ...voyage('a-2', 'A-2026-02'), status: 'IN_PROGRESS', reportable: false }
    const provider = stub({ listVoyages: vi.fn(async () => [voyage('a-1', 'A-2026-01'), running]) })
    renderInShell(provider, { vesselId: 'v-a', voyageId: 'a-2' })
    await chooseVoyageKind()

    expect(await screen.findByText(/상단바에서 고른 항차는 완료 전이라/)).toBeTruthy()
    // 비활성 선택지를 고른 상태로 두지 않는다.
    expect(voyageSelect().value).toBe('')
  })

  it('여기서 항차를 바꾸면 상단바도 바뀐다', async () => {
    const selectVoyageId = vi.fn()
    renderInShell(stub(), { vesselId: 'v-a', selectVoyageId })
    await chooseVoyageKind()
    await screen.findByRole('option', { name: /A-2026-01/ })

    fireEvent.change(voyageSelect(), { target: { value: 'a-1' } })

    expect(selectVoyageId).toHaveBeenCalledWith('a-1')
  })
})

describe('하단 안내가 면책 배너를 되풀이하지 않는다 (#1578)', () => {
  it('리포트의 성격(내부 보고용)만 말하고 「공식 문서가 아니다」는 배너 한 곳이다', async () => {
    render(<ReportsView provider={stub()} />)
    await waitFor(() => expect(vesselSelect().querySelectorAll('option').length).toBeGreaterThan(1))

    expect(screen.getByText(/내부 보고용/).closest('p')?.textContent).toBe('리포트는 내부 보고용입니다.')
    expect(screen.queryByText(/대관 제출용/)).toBeNull()
    expect(screen.getAllByText(/공식/)).toHaveLength(1)
  })
})


describe('선대가 100척을 넘어도 (#1644)', () => {
  it('셸이 고른 150번째 선박을 지우지 않고 그 선박으로 조회한다', async () => {
    const many: VesselOption[] = Array.from({ length: 200 }, (_, i) => ({
      id: `v-${i + 1}`,
      name: `VESSEL ${i + 1}`,
      imoNumber: String(9000000 + i),
    }))
    const provider = stub({ listVessels: vi.fn(async () => many) })
    const selectVesselId = vi.fn()
    renderInShell(provider, { vesselId: 'v-150', selectVesselId })

    await waitFor(() => expect(vesselSelect().value).toBe('v-150'))
    await waitFor(() => expect(provider.listVoyages).toHaveBeenCalledWith('v-150'))
    expect(selectVesselId).not.toHaveBeenCalledWith(null)
    expect(vesselSelect().options.length).toBeGreaterThanOrEqual(200)
  })
})


/**
 * 입력-결과 2단과 「한 번 만든 뒤에는 따라 갱신」 (#1768).
 *
 * 종전에는 문서가 조건 **아래**에 붙었고, 조건을 바꾸면 낡은 문서를 남겨 둔 채
 * 「조건이 바뀌었습니다 — 다시 만들어 주세요」라고 시켰다 — 화면이 할 수 있는 일을
 * 사용자에게 시킨 셈이다. 누르기 전에는 그 자리가 아예 없어 **첫 화면의 40%가 빈
 * 면**이었다.
 */
describe('한 번 만든 뒤에는 조건을 따라간다 (#1768)', () => {
  const twoVoyages = () =>
    stub({
      listVoyages: vi.fn(async () => [voyage('a-1', 'A-2026-01'), voyage('a-2', 'A-2026-02')]),
    })

  it('마운트만으로는 만들지 않는다 — 조건을 정하기 전의 문서는 누구의 질문도 아니다', async () => {
    const provider = twoVoyages()
    renderInShell(provider, { vesselId: 'v-a', voyageId: 'a-1' })
    await chooseVoyageKind()

    await waitFor(() => expect(voyageSelect().value).toBe('a-1'))
    // `#511`이 항로 비교에서 정한 것과 같다 — 실패하면 화면이 오류로 시작한다.
    expect(provider.previewHtml).not.toHaveBeenCalled()
  })

  it('누르기 전에도 빈 면이 아니다 — 무엇을 고르면 무엇이 나오는지가 있다', async () => {
    render(<ReportsView provider={stub()} />)

    expect(await screen.findByText(/선박을 먼저 선택해 주세요/)).toBeTruthy()
    expect(screen.getByText(/같은 문서/)).toBeTruthy()
  })

  it('조건을 바꾸면 문서를 다시 만든다 — 「다시 만들어 주세요」가 없다', async () => {
    const provider = twoVoyages()
    renderInShell(provider, { vesselId: 'v-a' })
    await chooseVoyageKind()
    await screen.findByRole('option', { name: /A-2026-01/ })

    fireEvent.change(voyageSelect(), { target: { value: 'a-1' } })
    fireEvent.click(screen.getByTestId('preview-button'))
    await waitFor(() => expect(provider.previewHtml).toHaveBeenCalledTimes(1))

    fireEvent.change(voyageSelect(), { target: { value: 'a-2' } })

    await waitFor(() => expect(provider.previewHtml).toHaveBeenCalledTimes(2))
    expect(provider.previewHtml).toHaveBeenLastCalledWith({ kind: 'VOYAGE', voyageId: 'a-2' })
    expect(screen.queryByText(/다시 만들어 주세요/)).toBeNull()
  })

  it('같은 조건으로 다시 그려도 두 번 부르지 않는다', async () => {
    const provider = twoVoyages()
    renderInShell(provider, { vesselId: 'v-a' })
    await chooseVoyageKind()
    await screen.findByRole('option', { name: /A-2026-01/ })

    fireEvent.change(voyageSelect(), { target: { value: 'a-1' } })
    fireEvent.click(screen.getByTestId('preview-button'))
    await waitFor(() => expect(screen.getByTitle('리포트 미리보기')).toBeTruthy())

    /*
     * 문서가 도착하면 `preview`가 바뀌어 효과가 한 번 더 돈다. 키가 같아 거기서
     * 멈추지 않으면 **자기 자신을 다시 부르는 고리**가 된다.
     */
    await waitFor(() => expect(provider.previewHtml).toHaveBeenCalledTimes(1))
  })

  it('다시 만들다 실패해도 앞 문서를 지우지 않는다', async () => {
    let calls = 0
    const provider = twoVoyages()
    provider.previewHtml = vi.fn(async () => {
      calls += 1
      if (calls === 1) return '<p>first</p>'
      throw new Error('서버 오류')
    })
    renderInShell(provider, { vesselId: 'v-a' })
    await chooseVoyageKind()
    await screen.findByRole('option', { name: /A-2026-01/ })

    fireEvent.change(voyageSelect(), { target: { value: 'a-1' } })
    fireEvent.click(screen.getByTestId('preview-button'))
    await waitFor(() => expect(screen.getByTitle('리포트 미리보기')).toBeTruthy())

    fireEvent.change(voyageSelect(), { target: { value: 'a-2' } })

    expect(await screen.findByText(/리포트를 만들지 못했습니다/)).toBeTruthy()
    // 되돌리려고 조건을 기억해 다시 고르게 하지 않는다 — 보던 문서는 남는다.
    expect(screen.getByTitle('리포트 미리보기')).toBeTruthy()
  })
})
