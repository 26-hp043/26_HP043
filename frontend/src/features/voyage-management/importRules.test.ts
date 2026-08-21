import { describe, expect, it } from 'vitest'
import {
  IMPORT_NOTICE,
  MAX_FILE_BYTES,
  MAX_ROWS,
  REQUIRED_COLUMNS,
  canCommit,
  resultSummary,
  validateFile,
  type ImportResult,
} from './importRules'

/**
 * CSV 가져오기 규칙 (`API_SPEC §8.2` · `#60`).
 *
 * 여기서 고정하는 것은 **되돌릴 수 없는 상태를 만들지 않는다**는 것이다.
 * `§8.2`는 부분 성공이라 틀린 행이 있어도 유효한 행은 들어가고, 삭제는 항차
 * 하나씩이다. 확인 없이 확정할 수 있으면 700행이 들어간 뒤에 오류를 처음 본다.
 */

function result(over: Partial<ImportResult> = {}): ImportResult {
  return { importedCount: 0, skippedCount: 0, errors: [], dryRun: true, ...over }
}

function fileOf(bytes: number): File {
  return new File([new Uint8Array(bytes)], 'voyages.csv', { type: 'text/csv' })
}

describe('파일 단위 검사 — 올려 보기 전에 알 수 있는 것만', () => {
  it('파일을 안 고르면 막는다', () => {
    expect(validateFile(null)).not.toBeNull()
  })

  it('빈 파일을 막는다', () => {
    expect(validateFile(fileOf(0))).not.toBeNull()
  })

  it('5MB를 넘으면 올리기 전에 막는다', () => {
    expect(validateFile(fileOf(MAX_FILE_BYTES + 1))).not.toBeNull()
    expect(validateFile(fileOf(MAX_FILE_BYTES))).toBeNull()
  })

  it('컬럼·행 내용은 검사하지 않는다 — 그것이 dry_run의 일이다', () => {
    /*
     * 필수 컬럼 7종·연료 마스터·VAL-002·VAL-009를 화면에 옮겨 적으면 사본이
     * 하나 더 생기고, 연료 마스터가 바뀌는 날 갈라진다. `REQUIRED_COLUMNS`는
     * **안내 문구용**이지 판정용이 아니다.
     */
    const empty = new File([''], 'x.csv', { type: 'text/csv' })
    const noColumns = new File(['아무 내용'], 'x.csv', { type: 'text/csv' })
    expect(validateFile(empty)).not.toBeNull() // 빈 파일이라 막힌 것이다
    expect(validateFile(noColumns)).toBeNull() // 내용은 보지 않는다
  })

  it('§8.2 필수 컬럼 7종을 그대로 안내한다', () => {
    expect(REQUIRED_COLUMNS).toEqual([
      'voyage_no',
      'departure_port_name',
      'arrival_port_name',
      'planned_distance_nm',
      'planned_speed_kn',
      'fuel_type',
      'planned_fuel_ton',
    ])
    expect(MAX_ROWS).toBe(1000)
  })
})

describe('확정 버튼', () => {
  it('검증 전에는 열리지 않는다 — 부분 성공은 되돌릴 수 없다', () => {
    expect(canCommit(null)).toBe(false)
  })

  it('들어갈 행이 없으면 열리지 않는다', () => {
    expect(canCommit(result({ importedCount: 0, skippedCount: 3 }))).toBe(false)
  })

  it('검증에서 들어갈 행이 있으면 열린다 — 틀린 행이 섞여 있어도', () => {
    expect(canCommit(result({ importedCount: 7, skippedCount: 3 }))).toBe(true)
  })

  it('이미 저장된 결과로는 다시 열리지 않는다 — 같은 파일이 두 번 들어간다', () => {
    expect(canCommit(result({ importedCount: 7, dryRun: false }))).toBe(false)
  })
})

describe('결과 문구 — 검증과 저장을 같은 말로 쓰지 않는다', () => {
  it('검증 결과는 「가져올 수 있습니다」다', () => {
    const text = resultSummary(result({ importedCount: 12, skippedCount: 1 }))
    expect(text).toContain('가져올 수 있고')
    expect(text).not.toContain('가져왔')
  })

  it('저장 결과는 「가져왔습니다」다', () => {
    const text = resultSummary(result({ importedCount: 12, skippedCount: 1, dryRun: false }))
    expect(text).toContain('가져왔')
    expect(text).not.toContain('있습니다')
  })

  it('건너뛴 행이 없으면 그 말을 하지 않는다', () => {
    expect(resultSummary(result({ importedCount: 12 }))).not.toContain('건너')
  })

  it('들어갈 행이 하나도 없는 것을 「0건 가져올 수 있습니다」로 쓰지 않는다', () => {
    const text = resultSummary(result({ importedCount: 0, skippedCount: 5 }))
    expect(text).toContain('없습니다')
  })
})

describe('초안으로 들어온다는 사실을 말한다', () => {
  it('연간 집계에 바로 반영되지 않는다고 적는다', () => {
    // 적지 않으면 사용자는 CSV를 올린 뒤 등급이 안 바뀌는 것을 고장으로 읽는다.
    expect(IMPORT_NOTICE).toContain('초안')
    expect(IMPORT_NOTICE).toContain('연간')
  })

  it('내부 문서 참조가 새어 나오지 않는다 (#529)', () => {
    expect(IMPORT_NOTICE).not.toMatch(/§|API_SPEC|PRD|DESIGN_SYSTEM/)
  })
})
