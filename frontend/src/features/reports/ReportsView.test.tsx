// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import { ReportsView } from './ReportsView'
import { SELECT_VESSEL_FIRST, YEAR_STATE_COPY } from '../parameters/yearCatalog'
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

    /*
     * `#2048`로 **연도 칸에도** 같은 안내가 생겼다(`PRD §6.4`가 그 상태에 등재한
     * 문장이다). 이 검사가 보는 것은 **결과 기둥이 빈 면이 아니다**이므로 그 자리를
     * 집어 찾는다 — 문장만으로 찾으면 두 자리 중 어느 것을 본 것인지 알 수 없다.
     */
    const lead = await waitFor(() => {
      const node = document.querySelector('.rp__placeholder-lead')
      if (node === null) throw new Error('아직 없음')
      return node
    })
    expect(lead.textContent).toMatch(/선박을 먼저 선택해 주세요/)
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

/**
 * #1812 — 항차 선택지의 구간이 저장 코드(`BUSAN`)가 아니라 보이는 이름(`부산`)으로 나온다.
 *
 * `apiProvider.ts`가 서버의 `departure_port_name`·`arrival_port_name`(저장 코드)을 그대로
 * `VoyageOption`에 옮기므로, 코드에서 이름으로 바꾸는 일은 이 화면이 `portDisplayName`으로
 * 해야 한다.
 */
describe('항차 선택지의 항구 이름 (#1812)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('샘플 항만 목록에 있는 저장 코드는 보이는 이름으로 바뀐다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/ports/samples')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              data: [
                { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
                {
                  locode: 'SGKEP',
                  name: 'SINGAPORE',
                  name_ko: '싱가포르',
                  country_code: 'SG',
                  lat: 1.2833,
                  lon: 103.85,
                },
              ],
            }),
          }
        }
        return { ok: true, status: 200, json: async () => ({ data: {} }) }
      }),
    )
    const provider = stub({ listVoyages: vi.fn(async () => A_VOYAGES) })
    renderInShell(provider, { vesselId: 'v-a' })
    await chooseVoyageKind()

    const option = await screen.findByRole('option', { name: /부산 → 싱가포르/ })
    expect(option.textContent).not.toContain('BUSAN')
  })
})

/**
 * 선박을 고르기 전 연도 칸 (#2048 · `PRD §6.4`).
 *
 * 훅은 빈 `vesselId`에서 **조회하지 않고 빈 목록**을 돌려준다(`#632` — 옳은 판단이다).
 * 종전에는 그때 화면이 그리는 것이 없어 **빈 상자**가 떴다. 바로 위 「선박」 칸은
 * 「선택하세요」라고 말하는데 이 칸만 아무 말이 없으니, 사용자에게는 「고장」과
 * 「내 차례가 아님」이 구분되지 않는다.
 */
describe('선박을 고르기 전 연도 칸 (#2048)', () => {
  const yearSelect = () => screen.getByTestId('year-select') as HTMLSelectElement

  it('⚠️ 선박이 없으면 연도 칸이 비어 있지 않다', () => {
    render(<ReportsView provider={stub()} />)
    const options = yearSelect().querySelectorAll('option')
    expect(options.length, '연도 칸이 빈 상자입니다').toBeGreaterThan(0)
    expect(options[0].textContent).toBe(SELECT_VESSEL_FIRST)
  })

  it('칸을 감추지 않는다 — 폼의 줄 수가 선택 여부로 달라지지 않는다', () => {
    render(<ReportsView provider={stub()} />)
    expect(screen.queryByTestId('year-select')).not.toBeNull()
  })

  it('선박을 고르면 연도 목록으로 바뀐다 — 자리표시는 사라진다', async () => {
    /*
     * 이 파일은 연도 조회를 대역으로 두지 않는다(다른 검사들이 연도를 보지 않는다).
     * 여기서만 `GET /parameters/regulation-years`를 세워 **자리표시 → 목록** 전환을 본다.
     */
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).includes('regulation-years')
          ? new Response(JSON.stringify({ data: [{ year: 2025 }, { year: 2026 }] }), {
              status: 200,
              headers: { 'content-type': 'application/json' },
            })
          : new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }),
      ),
    )
    renderInShell(stub(), { vesselId: 'v-a' })

    await waitFor(() => {
      const texts = [...yearSelect().querySelectorAll('option')].map((o) => o.textContent)
      expect(texts).toContain('2026년')
    })
    const texts = [...yearSelect().querySelectorAll('option')].map((o) => o.textContent)
    expect(texts, '선박을 골랐는데 자리표시가 남아 있습니다').not.toContain(SELECT_VESSEL_FIRST)
  })
})

/**
 * 내려받기 완료 안내는 **내려받은 조건**의 것이다 (#2125). 안내가 말하는 파일은 그 조건의
 * 문서이므로, 조건이 바뀌면 지금 보는 문서의 안내가 아니다. 문구가 아니라 안내의 유무를 본다.
 */
describe('내려받기 완료 안내는 조건을 따라간다 (#2125)', () => {
  /** 안내는 `role=status`로 읽힌다 — 클래스가 아니라 역할로 찾는다. */
  const notice = () => screen.queryByRole('status')
  /** 안내가 말하는 파일명이 화면 어디에든 보이는가. */
  const showsFile = (name: string) => screen.queryByText(name) !== null

  /** 조건(항차)마다 다른 파일명을 준다 — 어느 조건의 파일인지 안내가 말해야 한다. */
  const named = () =>
    stub({
      listVoyages: vi.fn(async () => [voyage('a-1', 'A-2026-01'), voyage('a-2', 'A-2026-02')]),
      download: vi.fn(async (target) => `report-${(target as { voyageId: string }).voyageId}.pdf`),
    })

  async function downloadFirstVoyage(provider: ReportsProvider) {
    renderInShell(provider, { vesselId: 'v-a' })
    await chooseVoyageKind()
    await screen.findByRole('option', { name: /A-2026-01/ })
    fireEvent.change(voyageSelect(), { target: { value: 'a-1' } })
    fireEvent.click(screen.getByTestId('pdf-button'))
    await waitFor(() => expect(notice()).not.toBeNull())
  }

  it('조건을 바꾸면 안내가 사라진다', async () => {
    await downloadFirstVoyage(named())
    expect(notice()?.textContent).toContain('report-a-1.pdf')

    fireEvent.change(voyageSelect(), { target: { value: 'a-2' } })

    expect(notice()).toBeNull()
    expect(showsFile('report-a-1.pdf')).toBe(false)
  })

  it('조건을 바꿨다가 되돌리면 다시 지금 조건의 안내다', async () => {
    await downloadFirstVoyage(named())

    fireEvent.change(voyageSelect(), { target: { value: 'a-2' } })
    expect(notice()).toBeNull()
    fireEvent.change(voyageSelect(), { target: { value: 'a-1' } })
    expect(notice()?.textContent).toContain('report-a-1.pdf')
  })

  it('조건이 그대로인 동안은 남는다', async () => {
    await downloadFirstVoyage(named())

    // 같은 값을 다시 고른다 — 조건은 그대로다.
    fireEvent.change(voyageSelect(), { target: { value: 'a-1' } })

    expect(notice()?.textContent).toContain('report-a-1.pdf')
  })
})

/**
 * 연도 목록이 없으면 연간 리포트를 요청하지 않는다 (#2183 · `#2120` 후속).
 *
 * 종전에는 연도 상태의 초깃값이 **기기 시계의 해**였고, `/parameters/regulation-years`가
 * 실패하거나 빈 목록이면 그 값으로 연간 리포트를 요청했다 — 목록에서 고를 수 없는 연도로
 * 문서를 묻는 것이다. 이제 연도는 목록에서 정하고(없으면 `null`), 그때 미리보기·PDF·CSV
 * 셋이 잠기며 요청이 한 건도 나가지 않는다. 항차 리포트는 연도와 무관하므로 영향이 없다.
 *
 * 연도 조회는 `fetch`로 세운다(`#2048`과 같은 자리) — `useYearOptions`가 만드는 API
 * 카탈로그는 마운트 때의 `globalThis.fetch`를 붙들므로 렌더 **전에** 세워야 한다.
 */
describe('연도 목록이 없으면 연간 리포트를 요청하지 않는다 (#2183)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    })

  /** 규제연도 조회만 `reply`로 답하고 나머지 요청은 빈 200이다. */
  function stubYears(reply: () => Promise<Response>) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).includes('regulation-years') ? reply() : json({}),
      ),
    )
  }

  const yearsReply = (years: number[]) => json({ data: years.map((year) => ({ year })) })

  /** 응답 시점을 검사가 쥔다 — 「도착 전」과 「도착 후」를 나눠 본다. */
  function deferred() {
    let resolve!: (response: Response) => void
    const promise = new Promise<Response>((done) => {
      resolve = done
    })
    return { promise, resolve }
  }

  const buttons = () =>
    (['preview-button', 'pdf-button', 'csv-button'] as const).map(
      (id) => screen.getByTestId(id) as HTMLButtonElement,
    )
  const yearSelect = () => screen.getByTestId('year-select') as HTMLSelectElement
  /**
   * 연도 칸의 상태 문구. 같은 문장이 결과 기둥의 자리표시에도 서므로(`#2048`과 같은 배선)
   * 문장으로 찾지 않고 버튼이 가리키는 자리(`rp-year-state`)를 읽는다.
   */
  const yearState = () => document.getElementById('rp-year-state')?.textContent ?? null
  /** 셸의 선박은 선박 목록이 온 뒤에야 이 화면에 반영된다 — 그 전의 「열림」은 선박 미선택이다. */
  const untilVessel = (id: string) => waitFor(() => expect(vesselSelect().value).toBe(id))

  /** 셋이 전부 잠겼고, 각 버튼이 사유(연도 칸의 상태 문구)를 가리킨다. */
  function expectLockedWithReason() {
    for (const button of buttons()) {
      expect(button.disabled, `${button.dataset.testid}가 열려 있습니다`).toBe(true)
      const reasonId = button.getAttribute('aria-describedby')
      expect(reasonId, `${button.dataset.testid}가 사유를 가리키지 않습니다`).not.toBeNull()
      expect(document.getElementById(reasonId as string)?.textContent?.trim()).not.toBe('')
    }
  }

  function expectUnlocked() {
    for (const button of buttons()) {
      expect(button.disabled, `${button.dataset.testid}가 잠겨 있습니다`).toBe(false)
      expect(button.getAttribute('aria-describedby')).toBeNull()
    }
  }

  it('⚠️ 목록 조회가 500이면 셋이 잠기고 요청이 한 건도 나가지 않는다', async () => {
    stubYears(async () => json({ detail: 'boom' }, 500))
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-a' })

    // 실패가 연도 칸에 적히는 때가 곧 판정이 끝난 때다 — 그 뒤에 버튼을 본다.
    await untilVessel('v-a')
    await waitFor(() => expect(yearState()).toBe(YEAR_STATE_COPY.failed))
    expectLockedWithReason()
    expect(yearSelect().disabled).toBe(true)

    for (const button of buttons()) fireEvent.click(button)
    expect(provider.previewHtml).not.toHaveBeenCalled()
    expect(provider.download).not.toHaveBeenCalled()
  })

  it('빈 목록이어도 같다 — 고를 연도가 없다', async () => {
    stubYears(async () => yearsReply([]))
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-a' })

    await untilVessel('v-a')
    await waitFor(() => expect(yearState()).toBe(YEAR_STATE_COPY.empty))
    expectLockedWithReason()

    for (const button of buttons()) fireEvent.click(button)
    expect(provider.previewHtml).not.toHaveBeenCalled()
    expect(provider.download).not.toHaveBeenCalled()
  })

  it('목록이 오면 풀리고 목록의 가장 최근 해로 요청한다 — 기기 시계의 해가 아니다', async () => {
    // 올해가 목록에 없는 상태 — 종전 초깃값(기기 시계의 해)이 그대로 요청에 실릴 수 있던 자리다.
    stubYears(async () => yearsReply([2023, 2024]))
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-a' })

    await untilVessel('v-a')
    await waitFor(() => expect(yearSelect().value).toBe('2024'))
    expectUnlocked()
    expect(yearState()).toBeNull()

    fireEvent.click(screen.getByTestId('preview-button'))
    await waitFor(() => expect(provider.previewHtml).toHaveBeenCalledTimes(1))
    expect(provider.previewHtml).toHaveBeenCalledWith({
      kind: 'ANNUAL',
      vesselId: 'v-a',
      year: 2024,
    })

    fireEvent.click(screen.getByTestId('pdf-button'))
    await waitFor(() => expect(provider.download).toHaveBeenCalledTimes(1))
    expect(provider.download).toHaveBeenCalledWith(
      { kind: 'ANNUAL', vesselId: 'v-a', year: 2024 },
      'pdf',
    )
  })

  it('불러오는 동안 잠기고, 도착하면 풀린다 — 도착 전에 누른 것은 요청이 되지 않는다', async () => {
    const pending = deferred()
    stubYears(() => pending.promise)
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-a' })

    await untilVessel('v-a')
    await waitFor(() => expect(yearState()).toBe(YEAR_STATE_COPY.loading))
    expectLockedWithReason()
    for (const button of buttons()) fireEvent.click(button)

    pending.resolve(yearsReply([2025]))
    await waitFor(() => expect(yearSelect().value).toBe('2025'))
    expectUnlocked()
    expect(yearState()).toBeNull()
    // 도착 전의 클릭은 요청이 아니었고, 도착 자체도 요청을 만들지 않는다 — 누르기 전의
    // 문서는 누구의 질문도 아니다(#1768).
    expect(provider.previewHtml).not.toHaveBeenCalled()
    expect(provider.download).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('csv-button'))
    await waitFor(() => expect(provider.download).toHaveBeenCalledTimes(1))
    expect(provider.download).toHaveBeenCalledWith(
      { kind: 'ANNUAL', vesselId: 'v-a', year: 2025 },
      'csv',
    )
  })

  it('불러오다 실패하면 잠긴 채 실패로 바뀐다 — 「불러오는 중」이 남지 않는다', async () => {
    const pending = deferred()
    stubYears(() => pending.promise)
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-a' })

    await untilVessel('v-a')
    await waitFor(() => expect(yearState()).toBe(YEAR_STATE_COPY.loading))
    pending.resolve(json({ detail: 'boom' }, 500))

    await waitFor(() => expect(yearState()).toBe(YEAR_STATE_COPY.failed))
    expect(screen.queryAllByText(YEAR_STATE_COPY.loading)).toEqual([])
    expectLockedWithReason()
    expect(provider.previewHtml).not.toHaveBeenCalled()
  })

  it('선박을 바꾸면 새 선박의 문서를 목록의 연도로 한 번만 다시 만든다', async () => {
    /*
     * 실 API 카탈로그는 성공한 목록을 붙들어 재사용하므로(`createApiYearCatalog`) 두 번째
     * 선박의 목록은 조회 없이 같은 목록이다 — 다시 받는 동안의 잠김은 위 「불러오는 동안」
     * 검사가 본다. 여기서 보는 것은 연도를 목록에서 **렌더 중에 정해도** 미리보기가 조건을
     * 따라가고(#1768), 같은 조건으로 두 번 묻지 않는다는 것이다.
     */
    stubYears(async () => yearsReply([2024, 2025]))
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-a' })

    await untilVessel('v-a')
    await waitFor(() => expect(yearSelect().value).toBe('2025'))
    fireEvent.click(screen.getByTestId('preview-button'))
    await waitFor(() => expect(provider.previewHtml).toHaveBeenCalledTimes(1))

    fireEvent.change(vesselSelect(), { target: { value: 'v-b' } })

    await waitFor(() => expect(provider.previewHtml).toHaveBeenCalledTimes(2))
    expect(provider.previewHtml).toHaveBeenLastCalledWith({
      kind: 'ANNUAL',
      vesselId: 'v-b',
      year: 2025,
    })
    await waitFor(() => expect(yearSelect().value).toBe('2025'))
    expectUnlocked()
    // 목록이 다시 온 뒤에도 같은 조건이면 다시 묻지 않는다.
    expect(provider.previewHtml).toHaveBeenCalledTimes(2)
  })

  it('선박을 고르기 전에는 잠그지 않는다 — 종전대로 누르면 사유를 말한다', async () => {
    stubYears(async () => json({ detail: 'boom' }, 500))
    const provider = stub()
    render(<ReportsView provider={provider} />)
    await screen.findByRole('option', { name: /STAR SKIPPER/ })

    expectUnlocked()
    fireEvent.click(screen.getByTestId('preview-button'))
    expect(provider.previewHtml).not.toHaveBeenCalled()
    // 선박을 고르라는 사유가 뜬다 — 연도 칸의 상태 문구가 아니다.
    expect(screen.getByText(/선박을 선택해 주세요/)).toBeTruthy()
    expect(yearState()).toBeNull()
  })

  it('항차 리포트는 연도와 무관하다 — 목록이 500이어도 종전대로 만든다', async () => {
    stubYears(async () => json({ detail: 'boom' }, 500))
    const provider = stub()
    renderInShell(provider, { vesselId: 'v-a', voyageId: 'a-1' })
    await chooseVoyageKind()
    await untilVessel('v-a')
    await waitFor(() => expect(voyageSelect().value).toBe('a-1'))

    expectUnlocked()
    fireEvent.click(screen.getByTestId('preview-button'))
    await waitFor(() => expect(provider.previewHtml).toHaveBeenCalledTimes(1))
    expect(provider.previewHtml).toHaveBeenCalledWith({ kind: 'VOYAGE', voyageId: 'a-1' })

    fireEvent.click(screen.getByTestId('pdf-button'))
    await waitFor(() => expect(provider.download).toHaveBeenCalledTimes(1))
    expect(provider.download).toHaveBeenCalledWith({ kind: 'VOYAGE', voyageId: 'a-1' }, 'pdf')
  })
})
