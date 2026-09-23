// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router'
import { RealtimeCiiView } from './RealtimeCiiView'
import { RealtimeCiiError } from './apiProvider'
import { POLL_INTERVAL_MS } from './realtimeRules'
import type { RealtimeCii, RealtimeCiiProvider } from './types'
import { regulationParametersPath } from '../parameters/referenceRules'
import { voyageActualsPath } from '../voyage-management/voyageRules'

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
    notUnderwayFuelTon: '0.00',
    notUnderwayCo2Ton: '0.00',
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
    drivers: [],
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

describe('데이터 점검 진입 (#1082 · `UIFLOW 2-11`)', () => {
  it('신뢰도 배지가 붙으면 옆에 「데이터 점검」 링크가 있고, 전부 실측이면 없다', async () => {
    const substituted: RealtimeCii = {
      ...BASE,
      ytd: { ...BASE.ytd, substitutions: [{ voyageId: 'vy-0', axis: 'FUEL', fuelType: 'HFO' }] },
    }
    const first = renderView({ load: vi.fn(async () => substituted) })
    const link = await screen.findByRole('link', { name: '데이터 점검' })
    expect(link.getAttribute('href')).toBe('/data-quality')
    first.unmount()

    renderView({ load: vi.fn(async () => BASE) })
    await screen.findByText(/Busan/)
    expect(screen.queryByRole('link', { name: '데이터 점검' })).toBeNull()
  })
})


/**
 * 「실적이 없다」와 「있는데 계산하지 못했다」를 가른다 (`#1095` ⑵).
 *
 * 서버는 `total_distance_nm <= 0` **또는** `total_fuel_ton <= 0`이면 `dataAvailable=false`를
 * 준다. 뒤쪽은 항차도 거리도 있는데 **연료를 모르는** 상태다 — 기여도 카드에는 거리
 * 수백 nm이 찍히는데 누적 카드만 「실적을 입력하라」고 말하고 있었고, 실제로 해야 할 일은
 * 선박 제원 입력이다. 사유는 서버가 이미 경고로 말한다(`API_SPEC §1.6`).
 */
describe('누적 카드가 「계산 불가」를 「실적 없음」으로 말하지 않는다 (#1095 ⑵)', () => {
  /** 누적은 못 냈지만 항차·거리는 있는 응답. 연료만 0이다. */
  function noFuel(warnings: string[]): RealtimeCii {
    return {
      ...BASE,
      ytd: {
        ...BASE.ytd,
        dataAvailable: false,
        attainedCii: null,
        requiredCii: null,
        rating: null,
        riskLevel: null,
        marginRatio: null,
        ratioToRequired: null,
        boundaries: null,
        totalCo2Ton: null,
        totalFuelTon: '0.00',
        voyageCount: 2,
      },
      warnings,
    }
  }

  function once(data: RealtimeCii): RealtimeCiiProvider {
    return { load: vi.fn(async () => data) }
  }

  it('서버가 사유를 주면 「실적을 입력하라」가 아니라 그 사유를 말한다', async () => {
    renderView(once(noFuel(['REFERENCE_ONLY', 'SIMULATION_NO_FUEL_RATE'])))

    /*
     * 문구는 `API_SPEC §1.6`이 소유하고 `WARNING_MESSAGE`가 전사한다 —
     * 화면이 새로 짓지 않는다. 사용자가 할 일(선박 제원 입력)이 그 문구에 있다.
     */
    expect(
      await screen.findAllByText(/기준 일일 연료소모량이 등록되지 않아/),
    ).not.toHaveLength(0)
    expect(screen.queryByText(/올해 등록된 실적이 없습니다/)).toBeNull()
  })

  it('진행 중 항차의 유종을 모르는 경우도 사유로 말한다', async () => {
    renderView(once(noFuel(['SIMULATION_NO_FUEL_TYPE'])))

    expect(await screen.findAllByText(/연료 종류를 알 수 없어/)).not.toHaveLength(0)
    expect(screen.queryByText(/올해 등록된 실적이 없습니다/)).toBeNull()
  })

  it('⚠️ 「계획값을 임시 사용 중」 경고는 사유로 쓰지 않는다 — 값이 들어갔다는 뜻이다', async () => {
    /*
     * `COMPLETED_NO_FUEL`은 「실적이 입력되지 않은 완료 항차입니다. 계획값을 임시
     * 사용 중.」이다. 그것을 「계산하지 못한 이유」로 쓰면 **값을 썼다는 문장과 못
     * 냈다는 상태가 서로 어긋난다.** 이 경고는 화면 아래 경고 목록에만 남는다.
     */
    renderView(once(noFuel(['COMPLETED_NO_FUEL'])))

    expect(await screen.findByText(/올해 등록된 실적이 없습니다/)).toBeTruthy()
  })

  it('진짜로 항차가 없으면 종전대로 「실적이 없습니다」다', async () => {
    const empty: RealtimeCii = {
      ...BASE,
      ytd: {
        ...BASE.ytd,
        dataAvailable: false,
        attainedCii: null,
        rating: null,
        totalDistanceNm: '0.00',
        totalFuelTon: '0.00',
        voyageCount: 0,
      },
      warnings: ['REFERENCE_ONLY'],
    }
    renderView(once(empty))

    expect(await screen.findByText(/올해 등록된 실적이 없습니다/)).toBeTruthy()
  })
})

/**
 * CO₂ 값에 연료 단위를 붙이지 않는다 (`#1095` ⑴ · `DESIGN_SYSTEM §4.2`).
 *
 * 같은 화면의 「누적 CO₂」는 `tCO₂`인데 연말 예상 가정 블록만 `t`였다 — 한 화면 안에서
 * 규율이 갈렸다. `format.ts`가 그 구분의 이유를 적고 있다: 「둘 다 `t`면 무엇의 질량인지
 * 구분되지 않는다」.
 */
describe('연말 예상 가정의 CO₂에 tCO₂를 쓴다 (#1095 ⑴)', () => {
  it('잔여 계획·확정 실적의 CO₂가 tCO₂로 표시된다', async () => {
    renderView({ load: vi.fn(async () => BASE) })

    const planned = await screen.findByText(/잔여 계획 거리 \/ CO₂/)
    const plannedValue = planned.closest('div')!.querySelector('dd')!.textContent!
    expect(plannedValue).toContain('tCO₂')

    const completed = screen.getByText(/확정 실적 거리 \/ CO₂/)
    const completedValue = completed.closest('div')!.querySelector('dd')!.textContent!
    expect(completedValue).toContain('tCO₂')
  })
})

/**
 * 면책은 화면 하단 배너 한 곳에서만 말한다 (#1416 · `DESIGN_SYSTEM §13` 🔒).
 *
 * 종전에는 서버의 `REFERENCE_ONLY`가 경고 목록에 「본 화면의 값은 참고용 예측값이며…」로
 * 한 번 더 나왔다. 배너 문구는 정본(`PRD §6.3`)이라 문장을 그대로 세되, **몇 번 나오는지**만 본다.
 */
describe('면책은 한 번만 (#1416)', () => {
  function once(data: RealtimeCii): RealtimeCiiProvider {
    return { load: vi.fn(async () => data) }
  }

  it('REFERENCE_ONLY가 와도 참고용 고지는 하단 배너 하나다', async () => {
    renderView(once({ ...BASE, warnings: ['REFERENCE_ONLY', 'COMPLETED_NO_DISTANCE'] }))

    const banners = await screen.findAllByText(/참고용 예측값/)
    expect(banners).toHaveLength(1)
    expect(banners[0].getAttribute('role')).toBe('note')
    // 면책과 무관한 경고는 남는다 — 목록을 통째로 지우지 않는다.
    expect(document.querySelector('.rt__warnings')).not.toBeNull()
  })

  it('면책 말고 경고가 없으면 경고 목록을 그리지 않는다', async () => {
    renderView(once({ ...BASE, warnings: ['REFERENCE_ONLY'] }))

    await screen.findAllByText(/참고용 예측값/)
    expect(document.querySelector('.rt__warnings')).toBeNull()
  })
})

/**
 * 「기준 (required)」 옆의 「기준값 근거」 링크 (`#1516` · `#1239` 결정 B·D).
 *
 * 현장직의 「왜 이 등급인가」 사슬은 여기서 시작한다 — required → `a`·`c` × Z → d. 링크의
 * **목적지**가 설정의 절 앵커인지를 본다.
 */
describe('기준값 근거 링크 (#1516)', () => {
  it('연간 누적 카드 안에 절 앵커로 가는 링크가 있다', async () => {
    const provider: RealtimeCiiProvider = { load: vi.fn(async () => BASE) }
    renderView(provider)

    const card = await screen.findByRole('region', { name: '연간 누적 CII' })
    const links = within(card).getAllByRole('link')
    expect(links.some((link) => link.getAttribute('href') === regulationParametersPath())).toBe(true)
  })
})

/**
 * 이 항차의 실적 입력으로 한 번에 간다 (#1540).
 *
 * 이 화면은 현장직의 주 화면이고(`UIFLOW §2.2`), 산출 가정이 「도착 실적을 입력하면
 * 확정됩니다」라고 말한다. 입력은 선박 상세에만 있어 되돌아가 찾아야 했다.
 */
describe('「이 항차 실적 입력」 (#1540)', () => {
  it('항차 카드 안에 그 항차의 실적 입력으로 가는 링크가 있다', async () => {
    const provider: RealtimeCiiProvider = { load: vi.fn(async () => BASE) }
    renderView(provider)

    const card = await screen.findByRole('region', { name: '항차 CII 기여도' })
    const link = within(card).getByRole('link', { name: '이 항차 실적 입력' })
    expect(link.getAttribute('href')).toBe(voyageActualsPath('v-1', 'vy-1'))
  })

  it('아직 가는 중이면 보조, 계획 거리를 다 채웠으면 채움 버튼이다', async () => {
    const going: RealtimeCiiProvider = { load: vi.fn(async () => BASE) }
    const { unmount } = renderView(going)
    const link = await screen.findByRole('link', { name: '이 항차 실적 입력' })
    expect(link.className).not.toContain('rt__actuals--primary')
    unmount()

    const arrived: RealtimeCiiProvider = {
      load: vi.fn(async () => ({
        ...BASE,
        currentVoyage: { ...BASE.currentVoyage!, distanceNm: '3000.00' },
      })),
    }
    renderView(arrived)
    const primary = await screen.findByRole('link', { name: '이 항차 실적 입력' })
    expect(primary.className).toContain('rt__actuals--primary')
  })

  it('진행 중 항차가 없으면 링크도 없다', async () => {
    const provider: RealtimeCiiProvider = {
      load: vi.fn(async () => ({ ...BASE, currentVoyage: null })),
    }
    renderView(provider)

    await screen.findByText('진행 중인 항차가 없습니다.')
    expect(screen.queryByRole('link', { name: '이 항차 실적 입력' })).toBeNull()
  })
})

/**
 * 연말 예상은 한 곳에서 한 문장으로 (#1555).
 *
 * 종전에는 YTD 카드의 「현재 누적 → 연말 예상」 전이와 연말 예상 카드가 같은 등급을 두 번
 * 그렸고, 「등급 유지 예상」과 「현재 누적보다 나빠지는 추세」가 떨어진 두 자리에서 어긋났다.
 * YTD 카드의 「기준 대비」도 스케일 바 마커와 두 번 나왔다.
 */
describe('연말 예상은 연말 예상 카드 한 곳 (#1555)', () => {
  const ytdCard = () => screen.getByRole('region', { name: '연간 누적 CII' })
  const projectionCard = () => screen.getByRole('region', { name: '연말 예상' })

  it('YTD 카드에는 연말 예상 등급이 없고 현재 누적 등급만 있다', async () => {
    renderView({ load: vi.fn(async () => BASE) })
    await screen.findByText(/Busan/)
    expect(within(ytdCard()).getByLabelText('현재 누적 기준 예상 등급 B')).toBeTruthy()
    expect(within(ytdCard()).queryByLabelText(/연말 예상 등급/)).toBeNull()
    expect(within(ytdCard()).queryByText(/연말 예상/)).toBeNull()
  })

  it('연말 예상 등급은 화면 전체에 한 번이다', async () => {
    renderView({ load: vi.fn(async () => BASE) })
    await screen.findByText(/Busan/)
    expect(screen.getAllByLabelText('연말 예상 등급 C')).toHaveLength(1)
    expect(within(projectionCard()).getByLabelText('연말 예상 등급 C')).toBeTruthy()
  })

  it('연말 예상 카드가 등급과 값의 방향을 한 문장으로 말한다', async () => {
    renderView({ load: vi.fn(async () => BASE) })
    await screen.findByText(/Busan/)
    const sentence = within(projectionCard()).getByText(/^등급은 /)
    expect(sentence.textContent).toBe('등급은 B → C 하락 · 값은 현재 누적보다 나빠짐 ▲ +0.863')
    expect(sentence.className).toContain('rt__direction--worsening')
  })

  it('스케일 바가 있으면 YTD 사실 목록에 「기준 대비」가 없다 — 비율은 바 마커가 한 번 적는다', async () => {
    renderView({ load: vi.fn(async () => BASE) })
    await screen.findByText(/Busan/)
    expect(within(ytdCard()).getByRole('img', { name: /연간 누적 CII의 등급 스케일/ })).toBeTruthy()
    expect(within(ytdCard()).queryByText('기준 대비')).toBeNull()
  })

  it('스케일 바를 못 그리면(경계 없음) 「기준 대비」가 목록에 남는다', async () => {
    const noBounds: RealtimeCii = { ...BASE, ytd: { ...BASE.ytd, boundaries: null } }
    renderView({ load: vi.fn(async () => noBounds) })
    await screen.findByText(/Busan/)
    expect(within(ytdCard()).queryByRole('img', { name: /등급 스케일/ })).toBeNull()
    expect(within(ytdCard()).getByText('기준 대비')).toBeTruthy()
    expect(within(ytdCard()).getByText('107.3%')).toBeTruthy()
  })
})

/*
 * 항차 제목의 항구는 저장값이 아니라 **보이는 이름**이다 (#1776).
 *
 * 선박 상세의 항차 표는 `#1742`에서 `portDisplayName`을 쓰게 됐는데, 같은 항차를 여는
 * 실시간 CII 제목은 저장값(`BUSAN`)을 그대로 적었다. 문구가 아니라 **두 성질**을 본다 —
 * 목록에 있는 항구는 목록이 주는 이름으로 바뀌고, 목록에 없는 항구는 입력한 그대로다.
 */
describe('항차 제목의 항구 이름 (#1776)', () => {
  const PORTS = [
    { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    { locode: 'SGSIN', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
  ]

  function stubPortList() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const body = String(input).includes('/ports/samples') ? { data: PORTS } : { data: {} }
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
  }

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const title = () => document.querySelector('.rt__voyage-title') as HTMLElement

  it('목록에 있는 항구는 저장값이 아니라 목록이 주는 이름으로 보인다', async () => {
    stubPortList()
    const stored: RealtimeCii = {
      ...BASE,
      currentVoyage: { ...BASE.currentVoyage!, departurePortName: 'BUSAN', arrivalPortName: 'SINGAPORE' },
    }
    renderView({ load: vi.fn(async () => stored) })

    await waitFor(() => expect(title().textContent).toContain(PORTS[0].name_ko))
    expect(title().textContent).toContain(PORTS[1].name_ko)
    expect(title().textContent).not.toContain('BUSAN')
    expect(title().textContent).not.toContain('SINGAPORE')
  })

  it('목록에 없는 항구는 입력한 그대로다 — 사전에 없는 이름을 지어내지 않는다', async () => {
    stubPortList()
    const freeText: RealtimeCii = {
      ...BASE,
      currentVoyage: { ...BASE.currentVoyage!, departurePortName: 'BUSAN', arrivalPortName: 'Rotterdam' },
    }
    renderView({ load: vi.fn(async () => freeText) })

    await waitFor(() => expect(title().textContent).toContain(PORTS[0].name_ko))
    expect(title().textContent).toContain('Rotterdam')
  })
})
