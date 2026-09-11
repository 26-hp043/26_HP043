/**
 * 항차 CSV 가져오기 규칙 — `API_SPEC §8.2` (`#60` 엔드포인트).
 *
 * ## 두 걸음으로 나눈다 — `dry_run`이 있는 이유다
 *
 * `§8.2`가 `dry_run`을 두고 *「검증만 하고 저장하지 않는다 — `imported_count`는
 * **들어갈 수 있는 행 수**」*라고 적었다. 화면이 그 걸음을 쓰지 않고 바로 저장하면,
 * **부분 성공 계약과 겹쳐 되돌릴 수 없는 상태가 만들어진다.**
 *
 * `§8.2`는 틀린 행이 있어도 유효한 행은 **넣는다.** 1,000행 중 300행이 틀린 파일을
 * 확인 없이 올리면 700행이 들어간 채로 오류 목록을 처음 본다. 그 700행을 되돌리는
 * 경로는 없다(삭제는 항차 하나씩이다).
 *
 * → **검증 → 결과 확인 → 확정.** 확정 전에 무엇이 들어가고 무엇이 빠지는지 보인다.
 *
 * ## 파일 단위 제한만 화면이 먼저 본다
 *
 * 크기(5MB)는 올려 보기 전에 알 수 있고, 5MB를 보내고 나서 거부당하는 것은 낭비다.
 *
 * **컬럼·행 내용은 화면이 검사하지 않는다.** 필수 컬럼 7종·연료 마스터·`VAL-002`·
 * `VAL-009`를 여기에 옮겨 적으면 사본이 하나 더 생기고, 그 사본은 연료 마스터가
 * 바뀌는 날 갈라진다. **그것이 `dry_run`의 일이다.**
 */

/** `§8.2` 보안 제한 — 최대 파일 크기. 서버 `MAX_FILE_BYTES`의 사본이다. */
export const MAX_FILE_BYTES = 5 * 1024 * 1024

/** `§8.2` 보안 제한 — 최대 행 수. 넘으면 서버가 **자르고** 그 사실을 `errors[]`에 남긴다. */
export const MAX_ROWS = 1_000

/**
 * `§8.2` 필수 컬럼 7종.
 *
 * **검증에 쓰지 않는다** — 화면에 「이런 컬럼이 필요합니다」를 적어 주기 위한 것이다.
 * 판정은 서버가 한다. 여기서 미리 막으면 서버가 컬럼을 늘렸을 때 화면이 먼저 거부한다.
 */
export const REQUIRED_COLUMNS: readonly string[] = [
  'voyage_no',
  'departure_port_name',
  'arrival_port_name',
  'planned_distance_nm',
  'planned_speed_kn',
  'fuel_type',
  'planned_fuel_ton',
]

/**
 * `§8.2` 선택 컬럼 (#906) — 출항·도착 예정 시각. **시간대가 붙은 ISO 8601**만 받는다.
 *
 * 비워도 들어가지만, 출항 예정 시각이 빈 항차는 진행 중으로 옮겨도 누적에 **0으로**
 * 기여한다(`#873`). 그래서 결과 화면이 빈 수를 알린다(`missingDepartureNotice`).
 */
export const OPTIONAL_COLUMNS: readonly string[] = ['planned_departure_at', 'planned_arrival_at']

/** 시각 칸의 예. 서버 `INSTANT_EXAMPLE`과 같은 값이다. */
export const INSTANT_EXAMPLE = '2026-09-12T09:00:00+09:00'

export interface ImportRowError {
  /** **파일에서 보이는 행 번호다** — 헤더가 1행이므로 첫 데이터 행이 `2`다 (`§8.2`). */
  row: number
  /** CSV 컬럼명. 파일 단위 문제는 `file`이다. */
  field: string
  message: string
}

export interface ImportResult {
  importedCount: number
  skippedCount: number
  errors: ImportRowError[]
  /** `true`면 아직 아무것도 저장되지 않았다 — `importedCount`는 「들어갈 수 있는 행 수」다. */
  dryRun: boolean
  /**
   * 들어가는(`dryRun`이면 들어갈) 행 가운데 **출항 예정 시각이 빈 수** (#906).
   * 그 항차들은 진행 중으로 옮겨도 누적에 0으로 기여한다.
   */
  missingDepartureCount: number
}

/** 올려 보기 전에 알 수 있는 것만 본다. 통과해도 서버가 최종 판정한다. */
export function validateFile(file: File | null): string | null {
  if (file === null) return '가져올 CSV 파일을 선택해 주세요.'
  if (file.size === 0) return '빈 파일입니다.'
  if (file.size > MAX_FILE_BYTES) {
    return `파일이 너무 큽니다. 최대 ${MAX_FILE_BYTES / (1024 * 1024)}MB까지 가져올 수 있습니다.`
  }
  return null
}

/**
 * 검증 결과 한 줄.
 *
 * **「성공 n건」이라고 쓰지 않는다** — `dry_run`에서는 아직 아무것도 들어가지 않았다.
 * 같은 문구를 두 단계에 쓰면 사용자는 검증만 했는데 저장된 것으로 읽는다.
 */
export function resultSummary(result: ImportResult): string {
  const { importedCount, skippedCount, dryRun } = result
  if (dryRun) {
    if (importedCount === 0) {
      return skippedCount === 0
        ? '가져올 행이 없습니다.'
        : `들어갈 수 있는 행이 없습니다. ${skippedCount}건에 문제가 있습니다.`
    }
    return skippedCount === 0
      ? `${importedCount}건을 가져올 수 있습니다.`
      : `${importedCount}건을 가져올 수 있고, ${skippedCount}건은 건너뜁니다.`
  }
  return skippedCount === 0
    ? `${importedCount}건을 가져왔습니다.`
    : `${importedCount}건을 가져왔고, ${skippedCount}건은 건너뛰었습니다.`
}

/**
 * 출항 예정 시각이 빈 행을 알린다 (#906) — 없으면 `null`.
 *
 * 들어가는 것은 맞으므로 오류가 아니다. 그러나 **말하지 않으면** 사용자는 진행 중으로
 * 옮긴 항차의 누적이 늘지 않는 것을 고장으로 읽는다. 검증 단계에서 먼저 알려야 저장
 * 전에 파일을 고칠 수 있다.
 */
export function missingDepartureNotice(result: ImportResult): string | null {
  const count = result.missingDepartureCount
  if (count <= 0) return null
  const head = result.dryRun
    ? `출항 예정 시각이 없는 행 ${count}건이 들어갑니다.`
    : `출항 예정 시각이 없는 행 ${count}건이 들어갔습니다.`
  return (
    `${head} 이 항차들은 진행 중으로 옮겨도 누적 CII에 반영되지 않습니다. ` +
    '파일에 planned_departure_at을 넣거나, 가져온 뒤 항차에서 출항 예정 시각을 입력해 주세요.'
  )
}

/**
 * 확정 버튼을 열어도 되는가.
 *
 * 들어갈 행이 하나도 없으면 확정할 이유가 없다 — 눌러도 `imported_count: 0`이고,
 * 그 시점에 사용자는 「올렸는데 아무 일도 없다」를 보게 된다.
 */
export function canCommit(result: ImportResult | null): boolean {
  return result !== null && result.dryRun && result.importedCount > 0
}

/**
 * 가져온 항차가 연간 집계에 **바로 들어가지 않는다**는 사실을 화면이 말한다 (`§8.2`).
 *
 * `status=DRAFT` · `annual_inclusion_policy=EXCLUDE`로 들어온다. 적지 않으면
 * 사용자는 CSV를 올린 뒤 등급이 안 바뀌는 것을 **고장으로 읽는다.**
 */
export const IMPORT_NOTICE =
  '가져온 항차는 초안 상태로 들어오며 연간 집계에 바로 반영되지 않습니다. 목록에서 상태를 전환해 주세요.'
