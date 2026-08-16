import type { ReportTarget, VoyageOption } from './types'

/**
 * 리포트 화면 규칙 (`#362`).
 *
 * DOM 없이 검증할 수 있게 컴포넌트에서 분리한다 — 이 저장소의 vitest에는 DOM 환경이
 * 없다.
 */

/**
 * 리포트를 만들 수 있는 항차 상태 (`PRD §25.2` · 서버 `REPORTABLE_STATUSES`).
 *
 * **서버와 같은 목록을 화면에도 둔다.** 여기 없으면 사용자가 진행 중 항차를 골라
 * 422를 받고 나서야 「안 되는 것」임을 알게 된다. 대신 목록은 서버가 정본이고,
 * 화면이 틀려도 서버가 최종 판단을 한다 — 두 판정이 갈리면 **막는 쪽이 서버**다.
 */
export const REPORTABLE_STATUSES = ['COMPLETED', 'CONFIRMED'] as const

export function isReportable(status: string): boolean {
  return (REPORTABLE_STATUSES as readonly string[]).includes(status)
}

/** 항차 상태의 한국어 라벨. 모르는 값은 코드를 그대로 — 빈칸보다 낫다. */
export const VOYAGE_STATUS_LABELS: Readonly<Record<string, string>> = {
  DRAFT: '작성 중',
  PLANNED: '계획',
  IN_PROGRESS: '진행 중',
  COMPLETED: '완료',
  CONFIRMED: '확정',
  CANCELLED: '취소',
}

export function statusLabel(status: string): string {
  return VOYAGE_STATUS_LABELS[status] ?? status
}

/** 선택지에 보여 줄 항차 이름. 항차 번호가 없는 항차가 실제로 있다. */
export function voyageLabel(voyage: VoyageOption): string {
  const name = voyage.voyageNo ?? '(번호 없음)'
  const route =
    voyage.departurePortName && voyage.arrivalPortName
      ? ` · ${voyage.departurePortName} → ${voyage.arrivalPortName}`
      : ''
  return `${name}${route} · ${statusLabel(voyage.status)}`
}

/**
 * 연간 리포트에 쓸 연도 선택지.
 *
 * `API_SPEC §8.4`가 2019~2100을 받지만 **미래 연도를 선택지에 넣지 않는다** —
 * 실적이 있을 수 없는 해의 리포트는 언제나 빈 문서이고, 사용자는 그것을 고장으로
 * 읽는다. 올해부터 과거로 `span`년이다.
 */
export function yearOptions(currentYear: number, span = 5): number[] {
  const earliest = 2019
  const years: number[] = []
  for (let year = currentYear; year > currentYear - span && year >= earliest; year -= 1) {
    years.push(year)
  }
  return years
}

/** 요청을 만들 수 있는 상태인가. 만들 수 없으면 왜인지 돌려준다. */
export function targetOf(
  kind: 'VOYAGE' | 'ANNUAL',
  selection: { vesselId: string; voyageId: string; year: number },
): ReportTarget | string {
  if (kind === 'ANNUAL') {
    if (!selection.vesselId) return '선박을 선택해 주세요.'
    return { kind: 'ANNUAL', vesselId: selection.vesselId, year: selection.year }
  }
  if (!selection.vesselId) return '선박을 먼저 선택해 주세요.'
  if (!selection.voyageId) return '항차를 선택해 주세요.'
  return { kind: 'VOYAGE', voyageId: selection.voyageId }
}

/** 두 대상이 같은가 — 미리보기를 다시 받아야 하는지 판단한다. */
export function sameTarget(a: ReportTarget | null, b: ReportTarget | null): boolean {
  if (a === null || b === null) return a === b
  if (a.kind !== b.kind) return false
  if (a.kind === 'VOYAGE' && b.kind === 'VOYAGE') return a.voyageId === b.voyageId
  if (a.kind === 'ANNUAL' && b.kind === 'ANNUAL') {
    return a.vesselId === b.vesselId && a.year === b.year
  }
  return false
}

/**
 * `Content-Disposition` 헤더에서 파일명을 꺼낸다.
 *
 * 서버는 ASCII `filename`과 UTF-8 `filename*`을 **둘 다** 보낸다(RFC 6266 §4.3).
 * `filename*`을 우선한다 — 그쪽이 사람이 읽는 한글 이름이다.
 *
 * 헤더가 없으면 `null`이다. 호출부가 대체 이름을 만든다 — 여기서 지어 내면
 * 「서버가 준 이름」과 「우리가 만든 이름」이 섞여 어느 쪽인지 알 수 없다.
 */
export function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null

  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      // 잘못 인코딩된 헤더로 다운로드 전체를 실패시키지 않는다 — ASCII로 내려간다.
    }
  }

  const ascii = /filename="([^"]+)"/i.exec(disposition)
  return ascii ? ascii[1] : null
}
