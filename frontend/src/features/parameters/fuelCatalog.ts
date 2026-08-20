import { useEffect, useMemo, useState } from 'react'
import { API_BASE_URL_ENV_KEY } from '../voyage-cii/providerSelection'
import { createApiParametersProvider, ParametersError } from './apiProvider'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'

/**
 * 연료 종류 선택지의 데이터 경계 (#542 · #558).
 *
 * ## 왜 만드는가
 *
 * `#236`이 「실API 모드에서도 선박·연도·연료 선택지가 프론트엔드 고정표에서 온다」를
 * 열었고, 선박 축(`vesselCatalog.ts` · `#236`)과 연도 축(`yearCatalog.ts` · `#534`)이
 * 차례로 옮겨졌다. **연료 축만 남아 있었다.**
 *
 * 남은 규모는 `#558` 본문이 적은 한 곳이 아니라 **네 곳**이다(그 이슈에 정정 코멘트를
 * 남겼다).
 *
 * | 기능 | 종전 |
 * |---|---|
 * | CII 예측 | `voyage-cii/formRules.ts` → `FUEL_CF` |
 * | 항로 비교 | `scenario-comparison/requestRules.ts` → `FUEL_CF` |
 * | 선박 등록 | `vessel-registration/formRules.ts` → `FUEL_CF` |
 * | 선박 관리 | `vessel-management/{editRules,VesselManagement}` → `FUEL_CF` |
 *
 * 정박 구간(`#370`)과 파라미터 화면은 이미 `/parameters/fuel-types`를 부르고 있었다.
 * **같은 목록을 화면마다 다른 곳에서 가져오는 상태**였고, 연료가 추가·비활성화되면
 * 한쪽만 따라간다.
 *
 * ## 왜 `features/parameters` 아래인가
 *
 * 선박·연도 카탈로그는 `features/voyage-cii/` 안에 있다. 연료는 네 기능이 쓰므로
 * 그 자리에 두면 **선박 등록·관리가 기능① 모듈을 import하게 된다** — `FUEL_CF`를
 * `voyage-cii/referenceTable`에서 끌어 쓰던 지금 상태가 경로만 바꿔 남는 것이다.
 * `/parameters/*` 접근은 이 기능이 이미 소유하고 있고(`apiProvider.ts`), 정박 구간이
 * 같은 방향으로 import하는 선례가 있다.
 *
 * ## 서버가 활성만 준다
 *
 * `GET /parameters/fuel-types`는 `active` 기본값이 `true`다(`routes/parameters.py`).
 * **화면에서 다시 거르지 않는다** — 거르는 규칙이 두 곳에 있으면 갈린다.
 *
 * ## `cf`를 들고 오지 않는다
 *
 * 서버 응답에는 `cf`·`unit`·`isActive`도 실리지만 이 카탈로그는 `code`·`displayName`만
 * 노출한다. 실 API 경로에서 `cf` 수치를 쓰는 곳은 없었고(demo provider 2곳뿐),
 * 들고 오면 **화면이 계산에 쓸 수 있는 상태**가 된다 — `yearCatalog.ts`가 Z계수를
 * 빼 둔 것과 같은 이유다.
 */

/** 연료 선택지 1건. 화면이 셀렉트에 그리는 데 필요한 최소값이다. */
export interface FuelOption {
  code: string
  displayName: string
}

/** 연료 선택지 조회의 데이터 경계. 화면은 출처를 알지 않는다 (`#134`). */
export interface FuelCatalogProvider {
  listFuels(): Promise<FuelOption[]>
}

/**
 * 선택지 조회 실패.
 *
 * 계산·저장 요청의 실패와 섞지 않는다 — `vesselCatalog.ts`·`yearCatalog.ts`가 적은
 * 이유와 같다. 「고를 수 없는 연료를 골랐다」와 「목록 자체가 없다」는 다른 상태다.
 */
export class FuelCatalogError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'FuelCatalogError'
  }
}

/**
 * 실 API 구현 — `GET /api/v1/parameters/fuel-types` (`API_SPEC §7.2`).
 *
 * 조회는 `features/parameters`의 공용 provider에 위임한다. 여기서 `fetch`를 다시
 * 쓰면 같은 엔드포인트를 부르는 코드가 두 벌이 되고, 그것이 `#444`가 없앤 상태다.
 *
 * ## 한 번만 받는다
 *
 * 연료 목록은 선박·연도와 달리 **어떤 인자에도 갈리지 않는다.** 네 화면이 각자
 * 마운트될 때마다 같은 GET을 보내지 않도록 성공한 조회 하나를 붙들어 재사용한다.
 * **실패는 붙들지 않는다** — 일시적 네트워크 오류가 새로고침 전까지 영구 실패로
 * 굳는다(`yearCatalog.ts`와 같은 판단).
 */
export function createApiFuelCatalog(baseUrl?: string): FuelCatalogProvider {
  const parameters = createApiParametersProvider(globalThis.fetch, baseUrl || DEFAULT_API_BASE_URL)
  let inFlight: Promise<FuelOption[]> | null = null

  return {
    async listFuels() {
      if (inFlight === null) {
        inFlight = parameters
          .listFuelTypes()
          .then((rows) => rows.map(({ code, displayName }) => ({ code, displayName })))
          .catch((cause) => {
            inFlight = null
            if (cause instanceof ParametersError) {
              throw new FuelCatalogError(cause.message, { cause })
            }
            throw new FuelCatalogError('연료 목록을 불러오지 못했습니다.', { cause })
          })
      }
      return inFlight
    },
  }
}

/** 환경에 맞는 카탈로그를 만든다. 데모 갈래는 `#542`가 없앴다. */
export function createFuelCatalog(env: ImportMetaEnv = import.meta.env): FuelCatalogProvider {
  return createApiFuelCatalog((env[API_BASE_URL_ENV_KEY] as string | undefined) || undefined)
}

/** 연료 선택지의 화면 상태. 네 화면이 같은 모양으로 다룬다. */
export interface FuelOptionsState {
  fuels: FuelOption[]
  loading: boolean
  failed: boolean
}

/**
 * 연료 선택지를 받아 오는 훅.
 *
 * **네 화면이 같은 로딩 절차를 각자 적지 않게 하려고 둔다.** 종전에는 `selectableFuels()`가
 * 동기 함수라 `useMemo` 한 줄이면 됐는데, 서버 조회로 바뀌면서 로딩·실패 상태가
 * 생겼다. 그 절차를 네 번 복사하면 한 곳만 고치는 실수가 나온다.
 *
 * 이 훅은 **저장소에 DOM 테스트 환경이 없어 단언할 수 없다**(`#557`). 그래서 판정
 * 규칙은 전부 순수 함수(`validateForm`·`validateEdit`)에 두고, 여기에는 상태를
 * 옮기는 배선만 남긴다.
 */
export function useFuelOptions(): FuelOptionsState {
  const catalog = useMemo(() => createFuelCatalog(), [])
  const [fuels, setFuels] = useState<FuelOption[]>([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    catalog
      .listFuels()
      .then((rows) => {
        if (!cancelled) setFuels(rows)
      })
      .catch(() => {
        if (cancelled) return
        setFailed(true)
        setFuels([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [catalog])

  return { fuels, loading, failed }
}

/**
 * 선택지 목록에 그 코드가 있는가.
 *
 * 종전 `!FUEL_CF[code]` 동기 조회를 대신한다. **검증 함수가 목록을 인자로 받도록
 * 바꾼 이유**는 그것이 비동기가 됐기 때문이다 — 검증을 비동기로 만들면 폼 제출
 * 경로 전체가 따라 바뀌므로, 목록을 화면이 들고 있다가 넘기는 쪽을 택했다.
 */
export function isKnownFuel(code: string, fuels: readonly FuelOption[]): boolean {
  return fuels.some((f) => f.code === code)
}
