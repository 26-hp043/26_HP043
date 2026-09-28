import type { FleetProvider, FleetVessel, UnavailableReason } from '../fleet/types'
import type { Rating } from '../voyage-cii/types'

/*
 * ── 올해 누적 등급 조회표 (#2018) ─────────────────────────────────────────
 *
 * ## 값을 어디서 받는가
 *
 * 선박 관리 목록은 `GET /vessels`(`API_SPEC §2.1`)를 쓰고, 그 응답에는 등급이 없다.
 * 등급·CII는 대시보드가 쓰는 `GET /fleet/summary`(`§2.8`)에 이미 있다. **같은 값을
 * 내는 경로를 하나 더 만들지 않고** 그 응답을 그대로 받는다 — 같은 선박·같은 해의
 * 누적 CII가 경로마다 갈린 전례가 두 번 있다(`#750` · `#866`).
 *
 * ## 목록으로 합치지 않는다
 *
 * 요약은 **선박 번호로 찾아 보는 표**로만 쓴다. 목록의 행·검색·선종 필터·정렬·페이지는
 * 지금처럼 `/vessels`가 정한다. 요약의 순서(`sort`)를 화면 표시에 쓰지 않으므로 두
 * 경로의 정렬·커서·필터 규칙이 부딪치지 않는다(`#2018` 결정 코멘트).
 *
 * ## 네 상태를 가른다
 *
 * | 상태 | 뜻 | 사용자가 할 일 |
 * |---|---|---|
 * | `loading` | 아직 받는 중 | 기다린다 |
 * | `failed` | 요약을 **받지 못했다** | 다시 연다 · 운영자 문의 |
 * | `unavailable` | 받았는데 서버가 **값을 내지 못했다**(사유 4종) | 사유마다 다르다(`unavailableHint`) |
 * | `rated` | 값이 있다 | — |
 *
 * `failed`와 `unavailable`을 같게 그리면 사용자는 더 나쁜 쪽으로 읽는다 — 「실적
 * 없음」이 요약 호출 실패 때문에 뜬 것인지 알 수 없게 된다. 요약에 **없는 선박**
 * (`absent` — 요약을 받은 뒤 등록된 배 등)도 따로 둔다. 받지 못한 것도, 서버가
 * 값을 내지 못한 것도 아니다.
 */

/** 행에 붙일 값 — 대시보드가 파싱한 `FleetVessel`에서 필요한 것만 옮긴다. */
export type GradeEntry = Pick<
  FleetVessel,
  'ytdRating' | 'ytdAttainedCii' | 'ytdRequiredCii' | 'dataAvailable' | 'unavailableReason'
>

export type GradeTable =
  | { status: 'loading' }
  | { status: 'failed' }
  | {
      status: 'ready'
      asOf: string
      byId: ReadonlyMap<string, GradeEntry>
      /**
       * 다시 받기(제원 저장 뒤)가 실패했다. 표는 **직전에 받은 것 그대로**다 — 값이 있던
       * 칸을 「받지 못함」으로 바꾸면 방금까지 보이던 등급이 사라진다. 이 플래그를 화면에
       * 어떻게 알릴지는 디자인 확인 ⑶(받지 못함 표시)에 따라 바뀔 수 있다.
       */
      refreshFailed?: boolean
    }

export type GradeCell =
  | { kind: 'loading' }
  | { kind: 'failed' }
  | { kind: 'absent' }
  | { kind: 'unavailable'; reason: UnavailableReason | null }
  | { kind: 'rated'; rating: Rating; attainedCii: string | null; requiredCii: string | null }

/** 요약 페이지 수 상한 — 100척씩 50쪽(5,000척)은 이 제품의 선대 규모를 한참 넘는다. */
export const MAX_GRADE_PAGES = 50

/**
 * 요약을 끝 페이지까지 받아 조회표로 만든다.
 *
 * - **정렬을 고정한다.** 커서는 정렬마다 갈려 다른 `sort`의 커서는 422다(`§2.8`).
 *   표로만 쓰므로 어느 정렬이든 상관없고, 이름순이 가장 흔들리지 않는다.
 * - **첫 페이지의 `as_of`를 뒤 페이지에 넣는다.** 안 넣으면 페이지마다 다른 시점의
 *   값이 섞인다(`TECH_SPEC §5.4.1`).
 * - 페이지 크기는 대시보드 provider가 이미 상한(100)으로 받는다.
 *
 * 실패는 그대로 던진다 — 화면이 `failed`로 받는다. 일부 페이지만 받은 표를 내면
 * 뒤 페이지의 배가 `absent`로 보여 「요약에 없다」는 거짓이 된다.
 *
 * **되풀이를 막는다.** 같은 커서가 다시 오거나 페이지 수가 상한(`MAX_GRADE_PAGES`)을
 * 넘으면 던진다 — 서버 결함 하나로 요청이 끝없이 이어지면 목록 화면까지 붙잡힌다.
 */
export async function loadGradeTable(
  provider: FleetProvider,
): Promise<{ asOf: string; byId: Map<string, GradeEntry> }> {
  const byId = new Map<string, GradeEntry>()
  const first = await provider.load({ sort: 'name' })
  const asOf = first.asOf
  let page = first
  let pages = 1
  const seenCursors = new Set<string>()
  for (;;) {
    for (const vessel of page.vessels) {
      byId.set(vessel.id, {
        ytdRating: vessel.ytdRating,
        ytdAttainedCii: vessel.ytdAttainedCii,
        ytdRequiredCii: vessel.ytdRequiredCii,
        dataAvailable: vessel.dataAvailable,
        unavailableReason: vessel.unavailableReason,
      })
    }
    if (!page.hasMore || page.nextCursor === null) break
    if (seenCursors.has(page.nextCursor)) {
      throw new Error('선대 요약 커서가 되풀이됐습니다.')
    }
    if (pages >= MAX_GRADE_PAGES) {
      throw new Error(`선대 요약이 ${MAX_GRADE_PAGES}쪽을 넘었습니다.`)
    }
    seenCursors.add(page.nextCursor)
    pages += 1
    page = await provider.load({ sort: 'name', cursor: page.nextCursor, asOf })
  }
  return { asOf, byId }
}

/** 한 선박의 칸 상태. */
export function gradeCellOf(table: GradeTable, vesselId: string): GradeCell {
  if (table.status === 'loading') return { kind: 'loading' }
  if (table.status === 'failed') return { kind: 'failed' }
  const entry = table.byId.get(vesselId)
  if (entry === undefined) return { kind: 'absent' }
  /*
   * 등급이 없으면 값이 있다고 치지 않는다. `dataAvailable`이 `true`인데 등급이 `null`인
   * 응답은 계약 밖이지만, 그때 빈 배지를 그리면 「등급이 있는데 옅다」로 읽힌다.
   */
  if (!entry.dataAvailable || entry.ytdRating === null) {
    return { kind: 'unavailable', reason: entry.unavailableReason }
  }
  return {
    kind: 'rated',
    rating: entry.ytdRating,
    attainedCii: entry.ytdAttainedCii,
    requiredCii: entry.ytdRequiredCii,
  }
}

/**
 * 등급순 정렬의 값 — 나쁜 등급이 앞(작은 수)이다. 등급이 없으면 `null`이고 끝으로 간다.
 *
 * `/fleet/summary`의 `sort=grade`와 같은 규칙이다(`§2.8` — 등급이 나쁜 순, 등급이 없는
 * 선박은 나쁜 등급으로 오해되지 않게 **가장 뒤**).
 */
const GRADE_ORDER: Readonly<Record<Rating, number>> = { E: 0, D: 1, C: 2, B: 3, A: 4 }

export function gradeRank(cell: GradeCell): number | null {
  return cell.kind === 'rated' ? GRADE_ORDER[cell.rating] : null
}

/** 요약을 받지 못했을 때의 짧은 표시. 「실적 없음」 등 서버 사유와 다른 말이어야 한다. */
export const GRADE_FAILED_TEXT = '불러오지 못함'
export const GRADE_FAILED_HINT =
  '선대 요약을 불러오지 못해 등급을 표시할 수 없습니다. 목록은 그대로 쓸 수 있습니다.'
export const GRADE_LOADING_TEXT = '불러오는 중'
export const GRADE_ABSENT_HINT = '아직 선대 요약에 없는 선박입니다. 다시 열면 표시됩니다.'
/**
 * 다시 받기가 실패했을 때 목록 위 한 줄 — 표시 문구다(`AGENTS §4.6` · 디자인 담당이 바꿀
 * 수 있다). 노출 여부·위치는 디자인 확인 ⑶(받지 못함 표시)에 따라 바뀔 수 있다.
 */
export const GRADE_REFRESH_FAILED_TEXT =
  '등급을 새로 고치지 못했습니다. 표시된 등급은 저장 전에 받은 값입니다.'
