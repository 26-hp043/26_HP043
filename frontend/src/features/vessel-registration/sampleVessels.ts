import { useEffect, useState } from 'react'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import { API_BASE_URL_ENV_KEY } from '../voyage-cii/providerSelection'
import type { VesselFormState } from './formRules'

/**
 * 샘플 선박 — 선박 등록 화면이 제원을 채우는 출발점 (#982 · `API_SPEC §2.15`).
 *
 * `PRD §5.1` 「선박 관리」 행의 **샘플 선박 선택**이다. 목록은 서버가 준다 — 값의 출처가
 * 데모 시드 한 곳이어야 「샘플로 등록한 배」와 「데모의 같은 이름 배」가 같은 계산을 낸다.
 *
 * ## 신원은 채우지 않는다
 *
 * 샘플은 「이런 배라면」의 제원이지 등록할 배의 신원이 아니다. **IMO·선명은 사용자가
 * 넣은 값을 그대로 둔다** — 샘플을 바꿔 골라도 지워지지 않는다.
 */

/** `GET /vessels/samples` 한 행. 수치는 CRUD 층이라 JSON 숫자다(`API_SPEC §1.7`). */
export interface SampleVessel {
  sample_id: string
  label: string
  ship_type: string
  gross_tonnage: number | null
  deadweight: number | null
  default_fuel_type: string | null
  reference_speed_kn: number | null
  reference_daily_foc_ton: number | null
}

export const SAMPLE_LOAD_FAILED_MESSAGE =
  '샘플 선박 목록을 불러오지 못했습니다. 제원을 직접 입력해 등록할 수 있습니다.'

function text(value: number | string | null): string {
  return value === null ? '' : String(value)
}

/**
 * 샘플의 제원을 폼 상태에 옮긴다. **IMO·선명은 건드리지 않는다.**
 *
 * 샘플에 값이 없는 필드는 **비운다** — 앞서 고른 샘플의 값이 남으면 두 샘플이 섞인
 * 제원이 등록된다(예: 로로 여객선을 고른 뒤에도 벌크선의 DWT가 남는다).
 */
export function applySample(state: VesselFormState, sample: SampleVessel): VesselFormState {
  return {
    ...state,
    shipType: sample.ship_type,
    grossTonnage: text(sample.gross_tonnage),
    deadweight: text(sample.deadweight),
    defaultFuelType: text(sample.default_fuel_type),
    referenceSpeedKn: text(sample.reference_speed_kn),
    referenceDailyFocTon: text(sample.reference_daily_foc_ton),
  }
}

/** 샘플이 채우는 폼 필드 — 채운 뒤 그 필드들의 오류를 지우는 데 쓴다. */
export const SAMPLE_FILLED_FIELDS = [
  'ship_type',
  'gross_tonnage',
  'deadweight',
  'default_fuel_type',
  'reference_speed_kn',
  'reference_daily_foc_ton',
] as const

/** `applySample`이 채우는 여섯 폼 필드 — `hasDivergedFields`가 이 목록으로 돈다. */
const SAMPLE_FORM_FIELDS = [
  'shipType',
  'grossTonnage',
  'deadweight',
  'defaultFuelType',
  'referenceSpeedKn',
  'referenceDailyFocTon',
] as const satisfies readonly (keyof VesselFormState)[]

/**
 * 두 텍스트 값이 「같은 값」인지 본다. 문자 그대로 같으면 참이고, 아니면 **둘 다
 * 유한수로 읽힐 때만** 수치로 비교한다 — `'12345.0'`과 `'12345'`는 표현만 다를 뿐
 * 같은 값이다. `Number('')`가 `0`이라 빈 문자열을 수치로 취급하면 안 된다.
 */
function sameValue(a: string, b: string): boolean {
  if (a === b) return true
  if (a.trim() === '' || b.trim() === '') return false
  const na = Number(a)
  const nb = Number(b)
  return Number.isFinite(na) && Number.isFinite(nb) && na === nb
}

/**
 * 샘플을 고르면 **사용자가 직접 적은 값이 사라지는가**를 본다 (`#1526`).
 *
 * 샘플을 고를 때 조건 없이 덮으면(`applySample`) 직접 입력한 값이 조용히 사라진다.
 * 이 함수는 「덮기 전에 물어야 하는가」를 판정하는 순수 함수다 — 화면은 이 결과로만
 * `confirm()`을 부른다. 한 칸이 걸리려면 셋이 모두 성립해야 한다.
 *
 * 1. **값이 있다** — 빈 칸은 덮어도 잃을 것이 없다.
 * 2. **마지막으로 채운 샘플의 값이 아니다** — 샘플이 넣은 값은 사용자가 적은 값이
 *    아니다. 그래서 샘플끼리 바꿀 때는 묻지 않는다(`lastApplied`가 없으면 이 조건은
 *    늘 성립한다).
 * 3. **고르려는 샘플이 넣을 값과 다르다** — 같으면 바뀌는 것이 없다.
 *
 * 값 비교는 `applySample`과 **같은 변환**을 거친 뒤 한다(`sameValue`).
 */
export function hasDivergedFields(
  state: VesselFormState,
  lastApplied: SampleVessel | null,
  next: SampleVessel,
): boolean {
  const fromLast = lastApplied === null ? null : applySample(state, lastApplied)
  const fromNext = applySample(state, next)
  return SAMPLE_FORM_FIELDS.some((field) => {
    const current = state[field]
    if (current.trim() === '') return false
    if (fromLast !== null && sameValue(current, fromLast[field])) return false
    return !sameValue(current, fromNext[field])
  })
}

/** 샘플 덮어쓰기 확인 문구. 문구 자체는 표시 문구다(`AGENTS §4.6`) — 디자인 확정 전 자리표시자. */
export function sampleOverwriteConfirmMessage(): string {
  return '입력한 선종·제원을 샘플 값으로 바꿀까요?'
}

function isSample(row: unknown): row is SampleVessel {
  if (typeof row !== 'object' || row === null) return false
  const r = row as Record<string, unknown>
  return (
    typeof r.sample_id === 'string' && typeof r.label === 'string' && typeof r.ship_type === 'string'
  )
}

/**
 * 목록을 받아 온다. 응답 모양이 계약과 다르면 **던진다** — 빈 목록으로 삼키면
 * 「샘플이 없다」와 「못 불러왔다」가 구분되지 않는다.
 */
export async function fetchSampleVessels(
  fetchImpl: typeof fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): Promise<SampleVessel[]> {
  const response = await fetchImpl(`${baseUrl}/vessels/samples`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const body = (await response.json()) as { data?: unknown }
  if (!Array.isArray(body.data) || !body.data.every(isSample)) {
    throw new Error('샘플 선박 응답이 계약과 다릅니다.')
  }
  return body.data
}

interface SampleVesselsState {
  samples: SampleVessel[]
  loading: boolean
  failed: boolean
}

/**
 * 샘플 목록 훅. 실패해도 등록 화면은 그대로 쓸 수 있다 — 샘플은 편의이지 필수가 아니다.
 *
 * 상태는 **비동기 콜백 안에서만** 바꾼다(첫 상태가 곧 「불러오는 중」이다).
 */
export function useSampleVessels(env: ImportMetaEnv = import.meta.env): SampleVesselsState {
  const [state, setState] = useState<SampleVesselsState>({
    samples: [],
    loading: true,
    failed: false,
  })
  const baseUrl = (env[API_BASE_URL_ENV_KEY] as string | undefined) || DEFAULT_API_BASE_URL

  useEffect(() => {
    let cancelled = false
    fetchSampleVessels(globalThis.fetch, baseUrl)
      .then((samples) => {
        if (!cancelled) setState({ samples, loading: false, failed: false })
      })
      .catch(() => {
        if (!cancelled) setState({ samples: [], loading: false, failed: true })
      })
    return () => {
      cancelled = true
    }
  }, [baseUrl])

  return state
}
