import { useEffect, useMemo, useState } from 'react'
import { createApiParametersProvider, ParametersError } from '../../api/parameters'
import { DEFAULT_API_BASE_URL } from '../../api/base'
import { API_BASE_URL_ENV_KEY } from '../voyage-cii/providerSelection'

/**
 * 규제연도 선택지의 데이터 경계 (#534 · #558).
 *
 * ## 왜 `features/parameters` 아래인가
 *
 * 종전에는 `features/voyage-cii/` 안에 있었다. `#558`이 **연간 등급 관리 화면도 같은
 * 목록을 쓰게** 하면서, 그 자리에 두면 기능③이 기능① 모듈을 import하게 된다 —
 * `FUEL_CF`를 `voyage-cii/referenceTable`에서 끌어 쓰던 상태가 경로만 바꿔 남는 것이다.
 * `/parameters/*` 접근은 이 기능이 소유하며 `fuelCatalog.ts`(#542 · #568)가 같은
 * 판단으로 여기 있다.
 *
 * ## 왜 이제 만드는가
 *
 * `#236`이 「실API 모드에서도 선박·연도·연료 선택지가 프론트엔드 고정표에서 온다」를
 * 고치면서 **선박 축만 옮기고 연도 축은 유예했다.** 그 이슈 체크리스트의 문구가
 * 조건까지 남겨 두었다.
 *
 * > `regulation_year` 선택지의 출처를 정한다. 현재 서버에 규정연도 목록 엔드포인트가
 * > 없다 — 없다면 이 이슈에서 만들지 말고 후속 이슈로 분리하고, 그때까지 연도는
 * > 고정표를 유지한다
 *
 * 그 엔드포인트가 `#444`로 들어왔다(`GET /parameters/regulation-years`,
 * `API_SPEC §7.1`). 유예 조건이 풀렸으므로 남은 절반을 여기서 옮긴다.
 *
 * ## 무엇이 깨져 있었나
 *
 * `selectableYears()`는 `FIXED_PARAMETERS`를 읽는데 그 표에는 행이 하나뿐이고
 * `vesselId`가 `…0001`(샘플 벌크선)이다. `demo_seed`는 선박 4척을 넣으므로,
 * 실 API 모드에서 나머지 3척을 고르면 연도 목록이 빈 배열이 되어 **계산 자체가
 * 불가능**했다. 선종 문제가 아니라 **선박 UUID 일치 문제**이므로, 사용자가 새로
 * 등록하는 선박도 예외 없이 같은 상태가 된다.
 *
 * ## 선박 축과 같은 스위치를 쓴다
 *
 * `vesselCatalog.ts`가 적어 둔 이유를 그대로 따른다 — 기준이 갈리면 계산은 서버로
 * 가는데 선택지는 고정표에서 오는, 지금 고치려는 상태가 다시 만들어진다.
 */

/** 규제연도 선택지 조회의 데이터 경계. 화면은 출처를 알지 않는다 (`#134`). */
/*
 * `export`를 뗐다 (`#824` ⑴). 마지막 소비처였던 `AnnualSimulation`·`VoyageCiiForm`이
 * `useYearOptions` 훅으로 옮겨가며 **이 파일 밖에서 이 타입을 쓰는 곳이 없어졌다.**
 * 남겨 두면 `moduleBoundary.test.ts`(`#594`)가 잡는 「아무도 쓰지 않는 export」가
 * 되고, 모듈 경계가 실제보다 넓어 보인다.
 */
interface YearCatalogProvider {
  /**
   * 해당 선박이 고를 수 있는 규제연도. 오름차순.
   *
   * **실 API 구현은 `vesselId`를 쓰지 않는다.** Z계수는 전 선종 공통이라 선박마다
   * 목록이 갈리지 않기 때문이다(`parameters/apiProvider.ts` 주석 참조). 인자를
   * 남겨 둔 것은 demo 구현이 고정표를 `(vesselId, year)` 키로 들고 있어서이며,
   * 두 구현이 같은 서명을 갖도록 맞춘 것이다.
   */
  listYears(vesselId: string): Promise<number[]>
}

/**
 * 실 API 구현 — `GET /api/v1/parameters/regulation-years` (`API_SPEC §7.1`).
 *
 * 조회는 `features/parameters`의 공용 provider에 위임한다. 여기서 `fetch`를 다시
 * 쓰면 같은 엔드포인트를 부르는 코드가 두 벌이 되고, 그것이 `#444`가 없앤 상태다.
 *
 * ## 한 번만 받는다
 *
 * 화면은 **선박을 바꿀 때마다** 이 함수를 부른다 — demo 구현이 선박별로 다른 답을
 * 내기 때문이다. 실 API 쪽 답은 선박과 무관하게 같으므로, 그대로 두면 선박을 고를
 * 때마다 같은 GET이 반복된다. 성공한 조회 하나를 붙들어 재사용한다.
 *
 * **실패는 붙들지 않는다.** 실패까지 캐시하면 일시적인 네트워크 오류가 새로고침
 * 전까지 영구 실패로 굳는다.
 */
export function createApiYearCatalog(baseUrl?: string): YearCatalogProvider {
  const parameters = createApiParametersProvider(globalThis.fetch, baseUrl || DEFAULT_API_BASE_URL)
  let inFlight: Promise<number[]> | null = null

  return {
    async listYears() {
      if (inFlight === null) {
        inFlight = parameters.listRegulationYears().catch((cause) => {
          inFlight = null
          if (cause instanceof ParametersError) {
            throw new YearCatalogError(cause.message, { cause })
          }
          throw new YearCatalogError('규제연도 목록을 불러오지 못했습니다.', { cause })
        })
      }
      return inFlight
    },
  }
}

/**
 * 선택지 조회 실패.
 *
 * `VoyageCiiError`를 재사용하지 않는다 — `vesselCatalog.ts`가 적은 이유와 같다.
 * 계산 요청의 실패와 목록을 못 불러온 것은 성격이 다르고, 섞으면 화면이
 * 「고를 수 없는 연도를 골랐다」와 「목록 자체가 없다」를 구분하지 못한다.
 */
export class YearCatalogError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'YearCatalogError'
  }
}

/** demo ↔ 실 API 전환. 판단 기준은 계산·선박 provider와 **같은 환경변수**다 (`#138`). */
export function createYearCatalog(env: ImportMetaEnv = import.meta.env): YearCatalogProvider {
  return createApiYearCatalog((env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined)
}

/**
 * 화면에 내놓는 연도 선택지 — **최신 연도부터**, 조회 화면은 **올해까지만** (#1584).
 *
 * ## 순서를 한 곳에서 정한다
 *
 * 종전에는 일곱 화면이 서버 목록(오름차순 2023~2030)을 그대로 그렸고 보고서만 이 규칙을
 * 따로 들고 있어(`reportRules.yearOptions` · `#635`) **보고서만 내림차순**이었다. 기본값은
 * 어느 화면이든 올해라, 최신 연도가 위에 있어야 기본값이 목록 머리 근처에 온다.
 *
 * ## 조회 화면은 미래 연도를 넣지 않는다 (`throughYear`)
 *
 * 실적이 있을 수 없는 해를 고르면 조회 화면은 언제나 빈 결과이고, 사용자는 그것을
 * 고장으로 읽는다(`#635`가 보고서에서 먼저 막은 이유). 계획을 짜는 화면(CII 예측 · 연간
 * 등급 · 항로 비교)은 다음 해를 고를 수 있어야 하므로 `null`을 준다.
 *
 * ⚠️ 「데이터가 있는 연도」 그 자체를 알려 주는 서버 경로는 없다 — 하한은 서버 목록
 * (규제 시작 2023)이, 상한은 올해가 정한다. 규제 이전 해가 목록에 없는 것도 같은 논거다.
 *
 * 개수를 자르지 않는다 — 규제연도가 늘면 선택지도 는다(종전 `span = 5` 제거 · `#635`).
 */
export function displayYears(rows: readonly number[], throughYear: number | null): number[] {
  return rows.filter((year) => throughYear === null || year <= throughYear).sort((a, b) => b - a)
}

/** `useYearOptions()`가 돌려주는 것. 로딩·실패를 **빈 목록과 구분한다.** */
export interface YearOptionsState {
  years: number[]
  loading: boolean
  failed: boolean
}

/**
 * 규제연도 선택지를 받아 오는 훅 (`#632`).
 *
 * ## 왜 훅으로 뽑는가
 *
 * 같은 로직이 이미 **두 화면에 글자 그대로 복사**돼 있었다 —
 * `VoyageCiiForm.tsx`(`#534`)와 `AnnualSimulation.tsx`(`#558`). 세 번째 화면
 * (항로 비교)이 같은 목록을 쓰게 되면서 사본이 셋이 된다.
 *
 * `fuelCatalog.ts`의 `useFuelOptions()`가 같은 판단으로 먼저 있고(`#568`), 항로 비교
 * 화면은 **이미 그 훅을 쓰고 있다.**
 *
 * > ⚠️ `#627`은 `ServerVoyage` 세 벌을 **공용화하지 않는다**고 판단했다. 반대로
 * > 보이지만 다르다 — 거기서는 셋이 **출처가 다른 타입**이었고(한쪽은 아예 다른
 * > 엔드포인트), 여기는 **같은 엔드포인트를 같은 방식으로 부르는 코드**다.
 *
 * ## 선박을 인자로 받는다
 *
 * 실 API 구현은 `vesselId`를 쓰지 않지만(Z계수는 전 선종 공통) demo 구현이 고정표를
 * `(vesselId, year)` 키로 들고 있어 서명을 맞춰 두었다. 화면은 선박이 바뀔 때마다
 * 다시 부른다 — 위 `createApiYearCatalog`가 성공한 조회 하나를 붙들어 재사용하므로
 * 실제 GET이 반복되지는 않는다.
 *
 * ## 빈 `vesselId`에서는 부르지 않는다
 *
 * 셸이 선박을 아직 정하지 않은 순간이 있다. 그때 부르면 demo 구현이 빈 목록을 주고,
 * 화면은 「등록된 규제연도가 없습니다」를 잠깐 보인다.
 */
export function useYearOptions(
  vesselId: string,
  /**
   * 조회 화면(데이터 점검 · 보고서 · CSV 내보내기 · 감축 계획)은 `true` — 올해 이후를 뺀다
   * (#1584 · `displayYears`). 계획을 짜는 화면은 기본값(`false`)이다.
   */
  { throughCurrentYear = false }: { throughCurrentYear?: boolean } = {},
): YearOptionsState {
  const catalog = useMemo(() => createYearCatalog(), [])
  const [years, setYears] = useState<number[]>([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!vesselId) {
      setYears([])
      setLoading(false)
      setFailed(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setFailed(false)
    catalog
      .listYears(vesselId)
      .then((rows) => {
        if (!cancelled) {
          setYears(displayYears(rows, throughCurrentYear ? new Date().getFullYear() : null))
        }
      })
      .catch(() => {
        if (cancelled) return
        setFailed(true)
        setYears([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [catalog, vesselId, throughCurrentYear])

  return { years, loading, failed }
}
