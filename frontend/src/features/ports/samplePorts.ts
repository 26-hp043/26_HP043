import { useEffect, useState } from 'react'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import { API_BASE_URL_ENV_KEY } from '../voyage-cii/providerSelection'

/**
 * 샘플 항만 — 항만을 입력하는 세 자리의 공용 규칙 (#760 · #1005 · `PRD §15.1` · `§15.2`).
 *
 * 쓰는 곳은 셋이다 — 항차 추가(#760) · 기능① 「계획 저장」 · 기능② 목적항·현재 위치(#1005).
 * 규칙을 화면마다 두면 한 화면만 「비슷한 이름 추측」으로 바뀌는 날이 온다.
 *
 * `PRD §15.1`이 MUST로 둔 「샘플 항만 테이블」이다. 목록은 서버가 준다(`API_SPEC §3.8`) —
 * 값의 출처(NGA World Port Index)를 한 곳에 두어야 원본과 대조할 수 있다.
 *
 * ## 고르면 좌표가 따라온다 · 자유 입력은 좌표가 없다
 *
 * 항만명 칸은 **자유 입력**이다(`PRD §20 O-11`). 입력이 목록의 항과 **정확히** 같을 때만
 * 그 좌표를 쓴다 — 비슷한 이름을 추측해 좌표를 붙이면, 사용자가 다른 항을 뜻했을 때
 * 틀린 좌표가 조용히 저장된다.
 */

/** `GET /ports/samples` 한 행. */
export interface SamplePort {
  locode: string
  /** 항차에 저장되는 이름(대문자 영문). */
  name: string
  /** 목록에 보이는 이름. */
  name_ko: string
  country_code: string
  lat: number
  lon: number
}

export interface PortCoord {
  lat: number
  lon: number
}

/**
 * 입력이 목록의 항과 같으면 그 항을 돌려준다. 영문 이름(대소문자 무시)이나 한국어 이름이
 * **정확히** 같아야 한다 — 위 모듈 설명 참조.
 */
export function matchSamplePort(ports: readonly SamplePort[], text: string): SamplePort | null {
  const wanted = text.trim()
  if (wanted === '') return null
  const upper = wanted.toUpperCase()
  return ports.find((p) => p.name === upper || p.name_ko === wanted) ?? null
}

/** 목록에 보이는 한 줄 — 「부산 · KR」. */
export function portOptionLabel(port: SamplePort): string {
  return `${port.name_ko} · ${port.country_code}`
}

/**
 * 추정 거리 칸의 표시 — **원문은 `PRD §15.2`다**(「화면에 `좌표 기반 추정 거리`라고 표시한다」).
 *
 * 대권거리는 운하·해협을 돌아가는 실제 항로보다 짧다. 사용자가 그 값을 실제 거리로 믿고
 * 두지 않도록 **왜 짧은지와 무엇을 하면 되는지**를 함께 적는다.
 */
export const ESTIMATED_DISTANCE_HINT =
  '좌표 기반 추정 거리 — 운하·해협을 돌아가는 실제 항로보다 짧을 수 있습니다. 실제 항로거리를 알면 고쳐 주세요.'

/** 추정 거리를 계획 거리 칸에 넣을 문자열로 — 소수 2자리(`planned_distance_nm` NUMERIC(12,2)). */
export function distanceInput(distanceNm: number): string {
  return distanceNm.toFixed(2)
}

/** 응답 한 행이 계약 모양인가 — 목록을 받는 모든 경로가 같은 검사를 쓴다. */
export function isSamplePort(row: unknown): row is SamplePort {
  if (typeof row !== 'object' || row === null) return false
  const r = row as Record<string, unknown>
  return (
    typeof r.name === 'string' &&
    typeof r.name_ko === 'string' &&
    typeof r.lat === 'number' &&
    typeof r.lon === 'number'
  )
}

/** `GET /ports/samples` (`API_SPEC §3.8`). 모양이 다르면 던진다 — 「없다」와 「못 받았다」를 가른다. */
export async function fetchSamplePorts(
  fetchImpl: typeof fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): Promise<SamplePort[]> {
  const response = await fetchImpl(`${baseUrl}/ports/samples`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const body = (await response.json()) as { data?: unknown }
  if (!Array.isArray(body.data) || !body.data.every(isSamplePort)) {
    throw new Error('샘플 항만 응답이 계약과 다릅니다.')
  }
  return body.data
}

/**
 * 샘플 항만 목록 훅 — 못 받으면 빈 목록이다. 항만은 늘 자유 입력이 되므로 실패를 오류로
 * 올리지 않는다(목록은 편의다). 상태는 비동기 콜백 안에서만 바꾼다.
 */
export function useSamplePorts(env: ImportMetaEnv = import.meta.env): SamplePort[] {
  const [ports, setPorts] = useState<SamplePort[]>([])
  const baseUrl = (env[API_BASE_URL_ENV_KEY] as string | undefined) || DEFAULT_API_BASE_URL
  useEffect(() => {
    let alive = true
    fetchSamplePorts(globalThis.fetch, baseUrl)
      .then((rows) => {
        if (alive) setPorts(rows)
      })
      .catch(() => {
        if (alive) setPorts([])
      })
    return () => {
      alive = false
    }
  }, [baseUrl])
  return ports
}

/**
 * `GET /ports/lookup` 응답의 좌표 (`API_SPEC §3.10` · `#768`).
 *
 * 내보내지 않는다 — `lookupPort`의 반환 타입으로만 쓰이고, 호출부는 값으로 받는다.
 * 쓰는 곳 없이 내보내면 `moduleBoundary` 가드가 막는다(`#594`).
 */
interface LookedUpPort {
  name: string
  lat: number
  lon: number
  /** SAMPLE · CACHE · LOOKUP — 어디서 온 값인지 화면이 말한다. */
  source: string
}

/** 조회 결과의 출처 문구. 「어디서 온 좌표인가」를 사용자가 알아야 한다. */
export const LOOKUP_SOURCE_NOTICE: Record<string, string> = {
  SAMPLE: '샘플 항만 목록에서 찾았습니다.',
  CACHE: '전에 조회해 둔 좌표입니다.',
  LOOKUP: '지도 서비스(OpenStreetMap)에서 찾은 좌표입니다. 확인 후 쓰세요.',
}

/** 조회에 실패했을 때 화면이 쓰는 문구 — 서버가 준 문장을 그대로 보인다. */
export const LOOKUP_FAILED_FALLBACK =
  '항만 좌표를 찾지 못했습니다. 좌표를 직접 입력하거나 그대로 진행하세요.'

/**
 * 항만명으로 좌표를 찾는다 (`API_SPEC §3.10`).
 *
 * **입력 중에 부르지 않는다** — 공개 Nominatim 사용 정책이 자동완성을 금지한다. 호출부는
 * 사용자가 「좌표 찾기」를 눌렀을 때만 부른다.
 *
 * 실패는 **오류로 올리지 않는다.** 좌표가 없어도 항차는 만들 수 있어야 하므로(`PRD §16.2`)
 * `{ ok: false, message }`로 돌려주고 화면이 그 문장을 보인다.
 */
export async function lookupPort(
  name: string,
  fetchImpl: typeof fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): Promise<{ ok: true; port: LookedUpPort } | { ok: false; message: string }> {
  try {
    const response = await fetchImpl(`${baseUrl}/ports/lookup?name=${encodeURIComponent(name)}`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
    const body = (await response.json().catch(() => null)) as
      | { data?: unknown; error?: { message?: string } }
      | null
    if (!response.ok) {
      return { ok: false, message: body?.error?.message || LOOKUP_FAILED_FALLBACK }
    }
    const data = body?.data as LookedUpPort | undefined
    if (!data || typeof data.lat !== 'number' || typeof data.lon !== 'number') {
      return { ok: false, message: LOOKUP_FAILED_FALLBACK }
    }
    return { ok: true, port: data }
  } catch {
    return { ok: false, message: LOOKUP_FAILED_FALLBACK }
  }
}
