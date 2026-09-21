/**
 * 규제 기준값 개정 적재 규칙 — `API_SPEC §7.5` · `#1517`(`#1239` 결정 F·H).
 *
 * ## 항차 CSV와 판정이 반대다 — 확정 조건이 여기서 갈린다
 *
 * 항차 CSV(`§8.2`)는 **부분 성공**이라 틀린 행이 있어도 맞는 행은 들어간다. 규제 기준값은
 * **전부 아니면 전무**다(`§7.5` 「한 행이라도 걸리면 아무것도 들어가지 않는다」) — 일부만
 * 들어가면 계산 근거가 반쪽이 되기 때문이다.
 *
 * 그래서 `voyage-management/importRules.ts`의 `canCommit`(들어갈 행이 하나라도 있으면
 * 연다)을 **그대로 쓰면 틀린다.** 오류가 한 건이라도 있는 검증 결과로 확정 버튼을 열면,
 * 눌러도 아무것도 안 들어가고 사용자는 「올렸다」고 믿는다.
 *
 * ## 확인 단계에 싣는 것은 「무엇이 바뀌는가」다
 *
 * 되돌리는 경로가 없다(과거 계산은 보존되지만 적재 자체를 취소할 수 없다). 확인 단계에서
 * 「정말 하시겠습니까」를 묻는 대신 **몇 행이 적용되고 기존 활성 행 몇 개가 이전 판본으로
 * 물러나는지**를 보인다 — `#1239` 결정 F.
 */

export { MAX_FILE_BYTES, MAX_ROWS, validateFile } from '../voyage-management/importRules'

/** `§7.5` `type` 네 가지. 화면에 보이는 이름과 순서는 조회 절(`#1516`)과 같게 둔다. */
export type ParameterKind =
  | 'regulation_years'
  | 'reference_lines'
  | 'rating_boundaries'
  | 'fuel_types'

interface ParameterKindSpec {
  kind: ParameterKind
  label: string
  /**
   * `§7.5` 표의 필수 컬럼 — **안내용이다. 화면이 검사하지 않는다.** 판정은 `dry_run`이
   * 한다. 여기서 먼저 막으면 서버가 컬럼을 바꾸는 날 화면이 먼저 거부한다.
   */
  requiredColumns: readonly string[]
  note?: string
}

export const PARAMETER_KINDS: readonly ParameterKindSpec[] = [
  {
    kind: 'regulation_years',
    label: '연도별 감축률',
    requiredColumns: ['year', 'z_factor_percent', 'effective_from', 'source_ref'],
  },
  {
    kind: 'reference_lines',
    label: '선종별 기준선',
    requiredColumns: ['ship_type', 'condition_expr', 'capacity_rule', 'a_raw', 'c', 'source_ref'],
    note: 'a_decimal은 서버가 a_raw에서 계산합니다 — 올리지 않습니다.',
  },
  {
    kind: 'rating_boundaries',
    label: '등급 경계',
    requiredColumns: ['ship_type', 'condition_expr', 'capacity_basis', 'd1', 'd2', 'd3', 'd4', 'source_ref'],
    note: 'd1 < d2 < d3 < d4 여야 합니다.',
  },
  {
    kind: 'fuel_types',
    label: '연료 탄소계수',
    requiredColumns: ['code', 'display_name', 'cf', 'source_ref'],
    note: '연료는 제자리에서 갱신되어 이전 값이 남지 않습니다.',
  },
]

export function kindLabel(kind: string): string {
  return PARAMETER_KINDS.find((spec) => spec.kind === kind)?.label ?? kind
}

export interface ParameterImportRowError {
  /** 원본 파일의 행 번호 — 헤더가 1행이라 첫 데이터 행이 2다. 파일 단위 문제는 `field: "file"`. */
  row: number
  field: string
  message: string
}

export interface ParameterImportResult {
  kind: string
  /** 적용된(검증이면 적용될) 행 수 — 연료 갱신도 포함한다(`§7.5`). */
  importedCount: number
  /** 그중 기존 활성 행을 이전 판본으로 물린 수(연료는 제자리 갱신한 수). */
  replacedCount: number
  errors: ParameterImportRowError[]
  /** `true`면 아직 아무것도 저장되지 않았다. */
  dryRun: boolean
}

/**
 * 확정 버튼을 열어도 되는가 — **검증을 통과했고 오류가 0건이며 적용할 행이 있을 때만.**
 *
 * 오류가 한 건이라도 있으면 전부 아니면 전무 계약상 아무것도 들어가지 않는다.
 */
export function canCommit(result: ParameterImportResult | null): boolean {
  return (
    result !== null && result.dryRun && result.errors.length === 0 && result.importedCount > 0
  )
}

/**
 * 결과 한 줄. 검증과 확정을 **다른 문장**으로 쓴다 — 같은 문장이면 검증만 했는데
 * 저장된 것으로 읽힌다(`importRules.resultSummary`와 같은 판단).
 */
export function revisionSummary(result: ParameterImportResult): string {
  const { importedCount, replacedCount, errors, dryRun } = result
  if (dryRun) {
    if (errors.length > 0) {
      return `문제가 있는 행 ${errors.length}건 — 이 파일은 한 행도 들어가지 않습니다. 고친 뒤 다시 검증해 주세요.`
    }
    if (importedCount === 0) return '적용할 행이 없습니다.'
    return replacedCount > 0
      ? `${importedCount}행을 적용할 수 있습니다. 그중 ${replacedCount}행은 지금 쓰는 값을 대체합니다.`
      : `${importedCount}행을 적용할 수 있습니다.`
  }
  return replacedCount > 0
    ? `${importedCount}행을 적용했습니다. 그중 ${replacedCount}행이 지금 쓰던 값을 대체했습니다.`
    : `${importedCount}행을 적용했습니다.`
}

/**
 * 확정 직전에 보이는 고지 — 되돌릴 수 없다는 것과, 이미 끝난 계산에 무슨 일이 생기는지.
 *
 * 표시 문구다(`AGENTS §4.6`) — 사실은 `API_SPEC §7.5`(과거 계산 보존 · 재현은
 * `parameter_hash`가 갈리면 409)와 `PRD §8.4`에서 온다.
 */
export const COMMIT_NOTICE =
  '확정하면 되돌릴 수 없습니다. 이미 끝난 계산은 그때의 기준값으로 보존되고, 새로 하는 계산부터 바뀐 값을 씁니다. 보존된 연간 시뮬레이션을 다시 실행(재현)하면 기준값이 바뀌었다는 이유로 거절됩니다.'

/** 개정 이력 한 건 — `GET /audit-logs?action=PARAMETER_IMPORT` 한 행(`API_SPEC §16.1`). */
export interface ParameterRevisionEvent {
  id: string
  timestamp: string
  kind: string
  /** 서버가 푼 행위자. 찾지 못하면 `null` — 그때는 `userId`만 남는다. */
  actor: { displayName: string | null; email: string } | null
  userId: string | null
  importedCount: number | null
  replacedCount: number | null
  /** 적재가 붙인 판본 라벨(`import.YYYYMMDDTHHMMSSZ`) — 조회 절의 이전 판본 행과 같은 값이다. */
  version: string | null
  sourceRefs: string[]
}

/**
 * 「누가」 칸. 사람 이름으로 답하는 것이 개정 이력의 목적이다(`#1239` 결정 E).
 * 행위자를 풀지 못했을 때만 식별자를 보인다 — 빈칸으로 두면 「아무도 안 했다」로 읽힌다.
 */
export function actorLabel(event: ParameterRevisionEvent): string {
  if (event.actor) {
    return event.actor.displayName
      ? `${event.actor.displayName} (${event.actor.email})`
      : event.actor.email
  }
  return event.userId ? `확인되지 않은 사용자 (${event.userId})` : '기록 없음'
}
