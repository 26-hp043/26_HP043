import { STATUS_LABELS } from '../voyage-management/voyageRules'
import type { VoyageStatus } from '../voyage-management/types'
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
// 이 파일 안에서만 쓴다 — `export`를 붙이면 모듈 경계가 실제보다 넓어 보인다 (#594).
const REPORTABLE_STATUSES = ['COMPLETED', 'CONFIRMED'] as const

export function isReportable(status: string): boolean {
  return (REPORTABLE_STATUSES as readonly string[]).includes(status)
}

/**
 * 항차 상태의 한국어 라벨. 모르는 값은 코드를 그대로 — 빈칸보다 낫다.
 *
 * ## 표를 여기서 다시 적지 않는다 (#594)
 *
 * 종전에는 이 파일이 **자기 표**를 갖고 있었고, 같은 상태를 항차 기록 화면과 **다른
 * 이름으로** 불렀다.
 *
 * ```
 * PLANNED       계획 확정  ↔  계획
 * IN_PROGRESS   항해 중    ↔  진행 중
 * COMPLETED     항해 완료  ↔  완료
 * CONFIRMED     실적 확정  ↔  확정
 * ARCHIVED      보관됨     ↔  (없음 — 코드가 그대로 나왔다)
 * ```
 *
 * 그리고 서버(`reports/labels.py`)의 동기화 대상은 **`voyageRules.ts` 쪽**이라
 * (`test_reports.py`), 이 표만 아무도 대조하지 않는 상태였다. 표를 하나로 합치면
 * 그 가드가 화면 전체를 덮는다.
 */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status as VoyageStatus] ?? status
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
 * 읽는다.
 *
 * ## 과거 하한도 같은 논거다 (#635)
 *
 * 종전에는 하한이 `2019`로 박혀 있었다. **CII 규제는 2023년에 시작**하므로 그
 * 이전 해에는 규제 파라미터가 없고, 고르면 전부 `—`인 빈 문서가 `200 OK`로 나온다
 * — 미래 연도를 뺀 것과 **정확히 같은 이유**인데 한쪽만 막고 있었다.
 *
 * ## 서버 목록을 따른다
 *
 * 고정 연도(2023)를 박지 않는다. 파라미터가 늘거나 줄면 화면만 낡는다 —
 * `#558`이 연간 등급 기준연도에서 없앤 상태와 같다. 목록은
 * `GET /parameters/regulation-years`(`API_SPEC §7.1`)가 주며, 기능①·연간
 * 시뮬레이션·항로 비교가 이미 같은 목록을 쓴다(`parameters/yearCatalog.ts`).
 *
 * ## `span`을 없앴다
 *
 * 종전의 `span = 5`는 **`earliest = 2019`와 짝을 이루던 임시 상한**이다 — 쓸모없는
 * 해가 목록에 섞이니 개수로 잘라 낸 것인데, 서버 목록에는 **쓸모없는 해가 애초에
 * 없다.** 남겨 두면 규제연도가 늘었을 때 화면이 조용히 과거 5년만 보인다.
 */
export function yearOptions(regulationYears: readonly number[], currentYear: number): number[] {
  return regulationYears.filter((year) => year <= currentYear).sort((a, b) => b - a)
}

/**
 * 선택된 연도를 목록 안으로 맞춘다 (#635).
 *
 * 화면은 올해를 기본값으로 들고 시작하는데, **서버 목록이 올해를 포함하지 않을 수
 * 있다** — 파라미터가 작년까지만 등재된 상태가 실제로 가능하다(현재 seed는
 * 2023~2030이라 2031년이 되면 그 상태다). 그대로 두면 select가 목록에 없는 값을
 * 들고 있어 브라우저가 첫 항목을 보이는데, **화면의 상태는 여전히 올해**라
 * 사용자가 보는 연도와 요청하는 연도가 갈린다.
 *
 * 목록이 비어 있으면 `null`이다 — 로딩·실패 상태이며, 그때는 고를 것이 없다.
 */
export function coerceYear(options: readonly number[], selected: number): number | null {
  if (options.length === 0) return null
  return options.includes(selected) ? selected : options[0]
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
