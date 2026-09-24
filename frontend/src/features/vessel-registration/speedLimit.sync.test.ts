/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { initialFormState, MAX_SPEED_KN, STORABLE, validateForm } from './formRules'

/**
 * 속력 물리 상한 — 화면 · 서버 · DB가 같은 60을 쓰는가 (`#1269` · `PRD §9.1` VAL-009).
 *
 * 서버가 상한을 내려주는 API가 없어 값을 옮겨 적을 수밖에 없다. **옮겨 적은 것이 어긋나면
 * CI가 실패하게** 한다 — `specBounds.sync.test.ts`와 같은 취지다. 원본은 서버
 * `api/schemas/bounds.py`의 `MAX_SPEED_KN`이며, 모델 CHECK·마이그레이션 `062`와의 대조는
 * `tests/test_request_bounds.py`가 한다.
 */

const boundsPy = readFileSync(
  new URL('../../../../src/cii_platform/api/schemas/bounds.py', import.meta.url),
  'utf-8',
)

describe('속력 물리 상한 — #1269', () => {
  it('화면 상수가 서버 MAX_SPEED_KN과 같다', () => {
    const match = /^MAX_SPEED_KN = Decimal\("(\d+)"\)$/m.exec(boundsPy)
    expect(match, 'bounds.py에서 MAX_SPEED_KN 선언을 찾지 못했습니다').not.toBeNull()
    expect(MAX_SPEED_KN).toBe(Number(match![1]))
  })

  it('선박 기준속도는 하한이 저장 형식(0.01), 상한이 60이다', () => {
    expect(STORABLE.speed).toEqual({ min: 0.01, max: MAX_SPEED_KN })
    expect(validateForm({ ...initialFormState(), referenceSpeedKn: '60' }, [])).not.toHaveProperty(
      'reference_speed_kn',
    )
    expect(validateForm({ ...initialFormState(), referenceSpeedKn: '60.01' }, [])).toHaveProperty(
      'reference_speed_kn',
    )
  })
})
