// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router'
import { RealtimeCiiView } from './RealtimeCiiView'
import { RealtimeCiiError } from './apiProvider'
import { POLL_INTERVAL_MS } from './realtimeRules'
import type { RealtimeCii, RealtimeCiiProvider } from './types'

/**
 * 폴링 실패가 화면을 비우지 않는다 (`#755`).
 *
 * ## 무엇이 문제였나
 *
 * 60초 폴링이 **한 번** 실패하면 YTD·등급·항차 기여도·연말 예상이 **전부 사라졌다.**
 * 코드 주석은 정반대를 적고 있었다 — *「폴링 중 실패는 화면을 비우지 않는다 … 최초
 * 로드 실패만 화면을 대체한다」*.
 *
 * 원인은 `setInterval`이 **마운트 시점의 `load`를 캡처**하는 것이었다. 그 클로저에
 * 담긴 `data`는 첫 렌더의 `null`이고 이후 값이 들어와도 **그 클로저 안에서는 영원히
 * `null`**이라, `if (data === null)` 판정이 항상 참이 되어 폴링 실패가 최초-로드
 * 실패로 처리됐다.
 *
 * ## 왜 이 파일이 필요한가
 *
 * 이 기능에는 **컴포넌트 렌더 검사가 없었다** — `apiProvider.test.ts`·
 * `realtimeRules.test.ts`는 전부 순수 함수다. 결함이 타이머와 클로저 사이에 있어서
 * **순수 함수 검사로는 원리적으로 드러나지 않는다**(`#823`에서 확인한 것과 같다).
 *
 * 가짜 타이머로 60초를 돌려 이슈의 재현 절차를 그대로 재현한다.
 */

const BASE: RealtimeCii = {
  vesselId: 'v-1',
  vesselName: 'STAR SKIPPER',
  regulationYear: 2026,
  capacityBasis: 'DWT',
  underwayState: 'UNDER_WAY',
  ytd: {
    dataAvailable: true,
    attainedCii: '18.637188',
    requiredCii: '17.374582',
    ratioToRequired: '1.07267',
    rating: 'B',
    riskLevel: 'WATCH',
    marginRatio: '0.09321',
    /*
     * 경계는 **절대 CII 값**이다 (#725). 위 값들과 앞뒤가 맞게 골랐다 —
     * `attained 18.637188`이 `superior`와 `lower` 사이(등급 B)에 놓이고,
     * `lower`는 `attained + margin_ratio × required`(≈ 20.257)와 같다.
     * 픽스처가 스스로 모순되면 스케일 바 테스트가 무엇을 재는지 흐려진다.
     */
    boundaries: {
      superior: '17.375',
      lower: '20.257',
      upper: '22.000',
      inferior: '24.000',
    },
    totalCo2Ton: '620.00',
    totalFuelTon: '199.10',
    underwayDistanceNm: '10620.00',
    notUnderwayDistanceNm: '0.00',
    totalDistanceNm: '10620.00',
    voyageCount: 3,
    notUnderwayPeriodCount: 0,
    // 기본 픽스처는 **전부 실측**이다 — 신뢰도 배지가 붙지 않는 상태 (#485 ⑤).
    substitutions: [],
  },
  currentVoyage: {
    voyageId: 'vy-1',
    voyageNo: '2026-02',
    status: 'IN_PROGRESS',
    departurePortName: 'Busan',
    arrivalPortName: 'Singapore',
    plannedDistanceNm: '3000.00',
    underwayHours: '112.0000',
    distanceNm: '1848.00',
    fuelTon: '140.00',
    fuelType: 'HFO',
    isSimulated: true,
    attainedCii: '4.720000',
    co2Ton: '435.96',
    rating: null,
  },
  projection: {
    dataAvailable: true,
    reason: null,
    attainedCii: '19.500000',
    requiredCii: '17.374582',
    ratioToRequired: '1.12234',
    rating: 'C',
    // `WATCH`는 서버에 없는 값이었다 — 허용값은 LOW·MEDIUM·HIGH·CRITICAL 넷이다 (#798).
    riskLevel: 'MEDIUM',
    warnings: [],
    assumptions: {
      method: 'REMAINING_PLAN',
      remainingDays: '137.27',
      remainingVoyageCount: 2,
      plannedDistanceNm: '4600.00',
      plannedCo2Ton: '2061.47',
      completedDistanceNm: '4300.00',
      completedCo2Ton: '1930.68',
    },
  },
  warnings: ['REFERENCE_ONLY'],
  asOf: '2026-08-17T02:00:00+00:00',
  simulated: true,
}

/** 첫 호출은 성공, 이후는 던지는 provider — 이슈의 재현 절차 그대로다. */
function failAfterFirst(error: Error = new Error('테스트 강제 실패')): RealtimeCiiProvider {
  let calls = 0
  return {
    load: vi.fn(async () => {
      calls += 1
      if (calls === 1) return BASE
      throw error
    }),
  }
}

function renderView(provider: RealtimeCiiProvider) {
  return render(
    <MemoryRouter initialEntries={['/vessels/v-1/voyages/current']}>
      <Routes>
        <Route
          path="/vessels/:vesselId/voyages/:voyageId"
          element={<RealtimeCiiView provider={provider} />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

/** 폴링 한 주기를 흘린다. `act`로 감싸지 않으면 상태 갱신이 경고를 낸다. */
async function tickOnePoll() {
  await act(async () => {
    vi.advanceTimersByTime(POLL_INTERVAL_MS)
  })
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('폴링 실패는 값을 남긴다 (#755)', () => {
  it('첫 로드 성공 뒤 폴링이 실패해도 값이 화면에 남는다', async () => {
    const provider = failAfterFirst()
    renderView(provider)

    // 첫 로드 — 값이 보인다.
    expect(await screen.findByText(BASE.vesselName)).toBeTruthy()

    await tickOnePoll()

    /*
     * ⚠️ 종전에는 여기서 화면이 통째로 비워지고 오류 문구만 남았다.
     * 선박명·YTD·연말 예상이 전부 사라졌다.
     */
    await waitFor(() => expect(provider.load).toHaveBeenCalledTimes(2))
    expect(screen.getByText(BASE.vesselName)).toBeTruthy()
    expect(screen.queryByText('테스트 강제 실패')).toBeNull()
  })

  it('폴링이 여러 번 실패해도 값이 남는다 — 첫 실패에서만 버티는 것이 아니다', async () => {
    const provider = failAfterFirst()
    renderView(provider)
    await screen.findByText(BASE.vesselName)

    await tickOnePoll()
    await tickOnePoll()
    await tickOnePoll()

    await waitFor(() => expect(provider.load).toHaveBeenCalledTimes(4))
    expect(screen.getByText(BASE.vesselName)).toBeTruthy()
  })

  it('갱신에 실패한 사실을 화면이 말한다 — 값이 조용히 낡지 않는다', async () => {
    const provider = failAfterFirst()
    renderView(provider)
    await screen.findByText(BASE.vesselName)

    expect(screen.queryByText(/마지막 갱신에 실패했습니다/)).toBeNull()

    await tickOnePoll()

    expect(await screen.findByText(/마지막 갱신에 실패했습니다/)).toBeTruthy()
  })

  it('다음 폴링이 성공하면 실패 표시가 사라진다 — 스스로 회복한다', async () => {
    let calls = 0
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async () => {
        calls += 1
        if (calls === 2) throw new Error('일시적 실패')
        return BASE
      }),
    }
    renderView(provider)
    await screen.findByText(BASE.vesselName)

    await tickOnePoll()
    expect(await screen.findByText(/마지막 갱신에 실패했습니다/)).toBeTruthy()

    await tickOnePoll()
    await waitFor(() =>
      expect(screen.queryByText(/마지막 갱신에 실패했습니다/)).toBeNull(),
    )
  })
})

describe('최초 로드 실패는 그대로 오류 패널이다 (#755)', () => {
  it('첫 호출이 실패하면 오류 문구를 낸다', async () => {
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async () => {
        throw new Error('처음부터 실패')
      }),
    }
    renderView(provider)

    expect(await screen.findByText('처음부터 실패')).toBeTruthy()
    // 보여 줄 값이 없으므로 화면을 대체하는 것이 맞다.
    expect(screen.queryByText(BASE.vesselName)).toBeNull()
  })

  it('없는 선박이면 대시보드로 가는 길을 준다', async () => {
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async () => {
        throw new RealtimeCiiError('선박을 찾을 수 없습니다.', { notFound: true })
      }),
    }
    renderView(provider)

    await screen.findByText('선박을 찾을 수 없습니다.')
    expect(screen.getByRole('link', { name: '대시보드로 돌아가기' })).toBeTruthy()
  })
})

describe('탭이 숨으면 요청하지 않는다 (UIFLOW 2-9 v2.2)', () => {
  it('`document.hidden`이면 폴링을 건너뛴다', async () => {
    const provider: RealtimeCiiProvider = { load: vi.fn(async () => BASE) }
    renderView(provider)
    await screen.findByText(BASE.vesselName)

    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    await tickOnePoll()
    expect(provider.load).toHaveBeenCalledTimes(1)

    hidden.mockReturnValue(false)
    await tickOnePoll()
    await waitFor(() => expect(provider.load).toHaveBeenCalledTimes(2))
  })
})

describe('출항 직후 극소 진행률이 화면을 죽이지 않는다 (#872)', () => {
  /**
   * 계획 거리가 큰 항차의 **출항 직후**면 진행률이 `1e-7` 근처가 된다.
   * `String(5e-7)`은 `"5e-7"`이고 포매터는 십진 문자열만 받으므로 던졌다 —
   * React 19는 렌더 예외에서 루트를 언마운트하므로 **화면이 통째로 백지**가 됐다.
   *
   * ⚠️ 순수 함수 검사(`format.test.ts`)만으로는 이 배선이 증명되지 않는다.
   * 그 함정을 `#823`·`#755`가 각각 겪었다 — 실제로 화면을 그려 확인한다.
   */
  function withTinyProgress(): RealtimeCii {
    return {
      ...BASE,
      currentVoyage: {
        ...BASE.currentVoyage!,
        // 12,000 nm 계획에 0.005 nm 진행 → 비율 약 4.2e-7
        plannedDistanceNm: '12000.00',
        distanceNm: '0.0050',
      },
    }
  }

  it('진행률 막대가 그려지고 화면이 살아 있다', async () => {
    const provider: RealtimeCiiProvider = { load: vi.fn(async () => withTinyProgress()) }
    renderView(provider)

    // 화면의 다른 내용이 정상적으로 나온다 — 크래시했다면 여기서 이미 못 찾는다.
    expect(await screen.findByText(BASE.vesselName)).toBeTruthy()
    // 극소 비율은 표시 자릿수에서 0.0%로 떨어진다. 「값이 없다」가 아니다.
    expect(screen.getByText('0.0%')).toBeTruthy()
  })

  it('보통 진행률은 종전과 같은 값을 낸다', async () => {
    const provider: RealtimeCiiProvider = { load: vi.fn(async () => BASE) }
    renderView(provider)

    await screen.findByText(BASE.vesselName)
    // 1848 / 3000 = 0.616 → 61.6%
    expect(screen.getByText('61.6%')).toBeTruthy()
  })
})

/**
 * 선박 전환을 화면이 안다 (#874).
 *
 * `/vessels/:vesselId/voyages/:voyageId`는 **라우트 파라미터만 바뀌므로 언마운트 없이
 * 선박이 전환된다.** 종전에는 이 화면이 그 전환을 전혀 몰라 ⑴ A선의 이름·등급이 B선의
 * URL 아래 그대로 남고(「불러오는 중」은 두 번째 선박부터 영영 안 뜬다) ⑵ 늦게 도착한
 * A의 폴링이 B의 화면을 덮으며(60초간 복구 없음) ⑶ A의 404 오류 패널이 B에서 유지됐다.
 *
 * ⚠️ **위 검사들이 이 결함을 하나도 잡지 못했다** — 전부 선박 하나로 시작해 끝까지
 * 그 선박이었다. 전환을 밟지 않는 검사는 이 종류의 결함을 원리적으로 놓친다.
 */

const OTHER: RealtimeCii = {
  ...BASE,
  vesselId: 'v-2',
  vesselName: 'PAN HORIZON',
}

/** 라우트를 갈아 끼울 수 있는 하네스. 같은 `path`라 컴포넌트는 **언마운트되지 않는다.** */
function renderSwitchable(provider: RealtimeCiiProvider) {
  function Switcher() {
    const navigate = useNavigate()
    return (
      <button type="button" onClick={() => navigate('/vessels/v-2/voyages/current')}>
        다른 배로
      </button>
    )
  }
  return render(
    <MemoryRouter initialEntries={['/vessels/v-1/voyages/current']}>
      <Switcher />
      <Routes>
        <Route
          path="/vessels/:vesselId/voyages/:voyageId"
          element={<RealtimeCiiView provider={provider} />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

function switchVessel() {
  fireEvent.click(screen.getByRole('button', { name: '다른 배로' }))
}

describe('선박을 바꾸면 옛 선박의 값이 남지 않는다 (#874)', () => {
  it('전환 직후 옛 이름이 사라지고 「불러오는 중」이 다시 뜬다', async () => {
    let releaseOther: ((value: RealtimeCii) => void) | null = null
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async (id: string) => {
        if (id === 'v-1') return BASE
        return new Promise<RealtimeCii>((resolve) => {
          releaseOther = resolve
        })
      }),
    }
    renderSwitchable(provider)
    await screen.findByText(BASE.vesselName)

    switchVessel()

    /*
     * 두 번째 선박부터 「불러오는 중」이 영영 안 뜨던 것이 종전 상태다 — `data`가
     * 남아 있어 로딩 갈래에 도달하지 못했다.
     */
    await waitFor(() => expect(screen.queryByText(BASE.vesselName)).toBeNull())
    expect(screen.getByText(/실시간 값을 불러오는 중입니다/)).toBeTruthy()
    // 그 창에서도 「← 선박 상세」는 **주소창의 배**를 가리켜야 한다.
    expect(screen.getByRole('link', { name: /선박 상세/ }).getAttribute('href')).toBe(
      '/vessels/v-2',
    )

    await act(async () => {
      releaseOther?.(OTHER)
    })
    expect(await screen.findByText(OTHER.vesselName)).toBeTruthy()
  })

  it('늦게 도착한 옛 선박의 응답이 새 화면을 덮지 않는다', async () => {
    let releaseFirst: ((value: RealtimeCii) => void) | null = null
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async (id: string) => {
        if (id === 'v-1') {
          return new Promise<RealtimeCii>((resolve) => {
            releaseFirst = resolve
          })
        }
        return OTHER
      }),
    }
    renderSwitchable(provider)
    // 첫 요청이 아직 떠 있는 상태에서 전환한다.
    switchVessel()
    expect(await screen.findByText(OTHER.vesselName)).toBeTruthy()

    // 이제서야 A가 돌아온다. 종전에는 이 한 줄이 B의 화면을 통째로 덮었다.
    await act(async () => {
      releaseFirst?.(BASE)
    })

    expect(screen.getByText(OTHER.vesselName)).toBeTruthy()
    expect(screen.queryByText(BASE.vesselName)).toBeNull()
  })

  it('옛 선박의 오류 패널이 새 선박을 기다리는 동안 유지되지 않는다', async () => {
    /*
     * **새 선박의 응답을 늦춘다.** 곧바로 돌려주면 성공 경로가 `setFailure(null)`을
     * 하므로 패널이 어차피 사라져, 리셋이 없어도 검사가 통과한다 — 결함이 실제로
     * 보이는 창은 **전환 직후 응답 전까지**다. 그 창을 만들지 않은 첫 판본은
     * 돌연변이 검사에서 통과해 버렸다.
     */
    let releaseOther: ((value: RealtimeCii) => void) | null = null
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async (id: string) => {
        if (id === 'v-1') {
          throw new RealtimeCiiError('선박을 찾을 수 없습니다.', { notFound: true })
        }
        return new Promise<RealtimeCii>((resolve) => {
          releaseOther = resolve
        })
      }),
    }
    renderSwitchable(provider)
    await screen.findByText('선박을 찾을 수 없습니다.')

    switchVessel()

    await waitFor(() =>
      expect(screen.queryByText('선박을 찾을 수 없습니다.')).toBeNull(),
    )
    expect(screen.getByText(/실시간 값을 불러오는 중입니다/)).toBeTruthy()

    await act(async () => {
      releaseOther?.(OTHER)
    })
    expect(await screen.findByText(OTHER.vesselName)).toBeTruthy()
  })

  /*
   * ⚠️ **이 검사는 돌연변이 검사로 고정되지 않는다.** `load`가 `vesselId`에 의존해
   * 재생성되므로 폴링 타이머는 리셋·가드가 없어도 새 선박을 조회한다. 그래도 남기는
   * 것은 `#755`가 이 자리에서 **클로저가 옛 값을 붙든** 결함을 겪었기 때문이다 —
   * 그 회귀가 다시 나면 이 검사가 잡는다.
   */
  it('전환 뒤 폴링은 새 선박만 조회한다 — 옛 선박으로 되돌아가지 않는다', async () => {
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async (id: string) => (id === 'v-1' ? BASE : OTHER)),
    }
    renderSwitchable(provider)
    await screen.findByText(BASE.vesselName)

    switchVessel()
    await screen.findByText(OTHER.vesselName)

    const before = (provider.load as ReturnType<typeof vi.fn>).mock.calls.length
    await tickOnePoll()

    const calls = (provider.load as ReturnType<typeof vi.fn>).mock.calls
    expect(calls.length).toBeGreaterThan(before)
    expect(calls.slice(before).every(([id]) => id === 'v-2')).toBe(true)
    expect(screen.getByText(OTHER.vesselName)).toBeTruthy()
  })
})
