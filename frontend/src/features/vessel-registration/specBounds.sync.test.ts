/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { STORABLE, storableRange, validateForm, initialFormState } from './formRules'
import { validateEdit, type VesselEditState } from '../vessel-management/editRules'

/**
 * 선박 제원 경계 — 화면 · 서버 · DB가 같은 범위를 쓰는가 (`#860`).
 *
 * 종전에는 화면도 서버도 `> 0`만 봤다. DB는 `NUMERIC(12,2)` 등 고정 정밀도라, `1e-7`이
 * 두 층을 통과한 뒤 `0.00`으로 반올림돼 CHECK 제약에 걸려 **500**이 났다.
 *
 * 이슈 완료 기준이 「화면과 서버가 **같은 경계**를 쓴다」다. 경계를 화면에 옮겨 적는
 * 것 말고 방법이 없으므로 — 서버가 제원 경계를 내려주는 API가 없다 — **옮겨 적은 것이
 * 어긋나면 CI가 실패하게** 한다. `shipTypes.sync.test.ts`와 같은 취지다.
 *
 * 원본은 ORM 모델의 `sa.Numeric(precision=…, scale=…)`이다. 서버 스키마도 같은 값에서
 * 경계를 계산하며 `tests/test_vessel_spec_bounds.py`가 그쪽을 대조한다.
 */

const modelPy = readFileSync(
  new URL('../../../../src/cii_platform/db/models/vessel.py', import.meta.url),
  'utf-8',
)

function numericOf(column: string): { precision: number; scale: number } {
  const match = new RegExp(
    `${column}\\s*=\\s*sa\\.Column\\(sa\\.Numeric\\(precision=(\\d+),\\s*scale=(\\d+)\\)`,
  ).exec(modelPy)
  expect(match, `${column}의 Numeric 선언을 찾지 못했습니다`).not.toBeNull()
  return { precision: Number(match![1]), scale: Number(match![2]) }
}

describe('선박 제원 경계 — #860', () => {
  it.each([
    ['deadweight', STORABLE.tonnage],
    ['gross_tonnage', STORABLE.tonnage],
    ['reference_speed_kn', STORABLE.speed],
    ['reference_daily_foc_ton', STORABLE.dailyFoc],
  ] as const)('%s — 화면 경계가 DB 컬럼 정밀도에서 나온 값과 같다', (column, range) => {
    const { precision, scale } = numericOf(column)
    expect(range).toEqual(storableRange(precision, scale))
  })

  it('1e-7은 등록 화면에서 막힌다 — 종전에는 통과해 서버가 500을 냈다', () => {
    const errors = validateForm({ ...initialFormState(), deadweight: '0.0000001' }, [])
    expect(errors.deadweight).toBeDefined()
  })

  it('1e10은 등록 화면에서 막힌다 — NUMERIC(12,2) 초과', () => {
    const errors = validateForm({ ...initialFormState(), grossTonnage: '10000000000' }, [])
    expect(errors.gross_tonnage).toBeDefined()
  })

  it('수정 화면도 같은 경계를 쓴다 — 복제본이 따로 있었다', () => {
    /*
     * 종전에는 `vessel-management/editRules.ts`에 같은 검사가 **한 벌 더** 있었다.
     * 등록 화면만 고치면 수정 화면이 다시 뚫린다. 두 폼이 한 함수를 쓰는지를 결과로 본다.
     */
    const state: VesselEditState = {
      name: '수정 대상',
      shipType: 'BULK_CARRIER',
      grossTonnage: '',
      deadweight: '0.0000001',
      defaultFuelType: '',
      referenceSpeedKn: '100000',
      referenceDailyFocTon: '',
    }
    const errors = validateEdit(state, [])
    expect(errors.deadweight).toBeDefined()
    expect(errors.reference_speed_kn).toBeDefined()
  })

  it('저장 가능한 범위의 끝값과 소수 셋째 자리는 통과한다', () => {
    /*
     * 소수 셋째 자리를 막지 않는다 — 서버도 막지 않고 DB가 반올림한다. 한쪽만 막으면
     * 멀쩡한 입력이 화면에서만 거부된다.
     */
    for (const deadweight of ['0.01', '9999999999.99', '50000.125']) {
      const errors = validateForm({ ...initialFormState(), deadweight }, [])
      expect(errors.deadweight, deadweight).toBeUndefined()
    }
  })
})
