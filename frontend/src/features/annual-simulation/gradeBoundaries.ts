import { useEffect, useState } from 'react'
import { csrfHeaders } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../../api/base'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'

/**
 * 목표 등급 선택 카드의 한 줄 풀이 — **이 배 · 이 연도의 등급 경계** (#2201 · `DESIGN_SYSTEM §8.4`).
 *
 * ## 출처
 *
 * `GET /vessels/{id}/cii/ytd-series?year=` (`API_SPEC §2.18`)의 `boundaries`다. 경계는
 * `required × d`라 **실적과 무관하게 연중 고정**이고, 서버가 계산해 싣는다 — 화면이 `d`를 곱해
 * 다시 만들지 않는다(`#1371` 「화면이 경계를 다시 만들지 않는다」). `§8.4` 「풀이 문구의 출처 —
 * 규제값은 정본에서 옮긴다」에 맞는 자리다.
 *
 * ## 못 받으면
 *
 * 경계를 못 받으면(제원 미비 · 통신 실패 · 선박 미선택) **경계 이름**으로 적는다 — 「기준 × d2
 * 이하」. 숫자 없이도 각 등급이 어느 경계인지는 말한다(`PRD §3` 등급 판정식). 카드를 비우지
 * 않는다 — `§8.4` 「선택지마다 풀이 한 줄」.
 */

type TargetRating = 'A' | 'B' | 'C' | 'D'

interface Boundaries {
  superior: string
  lower: string
  upper: string
  inferior: string
}

/** 등급 → 그 등급의 위쪽(나쁜 쪽) 경계. A는 superior 이하, …, D는 inferior 이하다(`PRD §3`). */
const BOUNDARY_OF: Record<TargetRating, keyof Boundaries> = {
  A: 'superior',
  B: 'lower',
  C: 'upper',
  D: 'inferior',
}

/** 경계를 못 받았을 때 — 판정식의 경계 이름(`PRD §3` `required_CII × d1~d4`). */
const FALLBACK: Record<TargetRating, string> = {
  A: '연말 CII가 기준 × d1 이하',
  B: '연말 CII가 기준 × d2 이하',
  C: '연말 CII가 기준 × d3 이하',
  D: '연말 CII가 기준 × d4 이하',
}

/** 카드 한 줄 풀이. 경계가 있으면 이 배의 숫자로, 없으면 경계 이름으로. */
export function targetDescription(rating: TargetRating, boundaries: Boundaries | null): string {
  if (boundaries === null) return FALLBACK[rating]
  return `연말 CII ${formatDecimalString(boundaries[BOUNDARY_OF[rating]], DISPLAY_DIGITS.cii)} 이하`
}

async function loadBoundaries(
  vesselId: string,
  year: string,
  fetchImpl: typeof globalThis.fetch,
  baseUrl: string,
): Promise<Boundaries | null> {
  const response = await fetchImpl(
    `${baseUrl}/vessels/${encodeURIComponent(vesselId)}/cii/ytd-series?${new URLSearchParams({ year })}`,
    { method: 'GET', credentials: 'include', headers: { Accept: 'application/json', ...csrfHeaders() } },
  )
  if (!response.ok) return null
  const body = (await response.json()) as {
    data?: { boundaries?: Record<string, unknown> | null }
  } | null
  const raw = body?.data?.boundaries
  if (!raw) return null
  const superior = raw.superior_boundary
  const lower = raw.lower_boundary
  const upper = raw.upper_boundary
  const inferior = raw.inferior_boundary
  if (
    typeof superior !== 'string' ||
    typeof lower !== 'string' ||
    typeof upper !== 'string' ||
    typeof inferior !== 'string'
  ) {
    return null
  }
  return { superior, lower, upper, inferior }
}

/**
 * 선박 · 연도가 바뀔 때마다 경계를 다시 받는다. 받는 동안과 못 받았을 때는 `null` — 카드는
 * 경계 이름으로 선다. **다른 선박의 응답이 늦게 와서 덮어쓰지 않게** 바뀐 뒤 온 응답은 버린다.
 */
export function useGradeBoundaries(
  vesselId: string | null,
  year: string,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
): Boundaries | null {
  const [state, setState] = useState<{ key: string; value: Boundaries | null } | null>(null)
  const key = vesselId && year ? `${vesselId}|${year}` : ''

  useEffect(() => {
    if (!vesselId || !year) return
    let alive = true
    loadBoundaries(vesselId, year, fetchImpl, baseUrl)
      .catch(() => null)
      .then((value) => {
        if (alive) setState({ key: `${vesselId}|${year}`, value })
      })
    return () => {
      alive = false
    }
  }, [vesselId, year, fetchImpl, baseUrl])

  // 지금 고른 배 · 연도의 것일 때만 쓴다 — 바꾼 직후 옛 배의 숫자가 남지 않게.
  return state !== null && state.key === key ? state.value : null
}
