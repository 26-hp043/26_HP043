/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { warningText } from './realtimeRules'
import { WARNING_MESSAGE } from '../voyage-cii/resultRules'

/**
 * `warningText()` ↔ `API_SPEC §1.6` 드리프트 가드 (#822).
 *
 * ## 무엇이 문제였나
 *
 * 이 화면은 자기 문구 맵(`WARNING_TEXT`, 7종)을 갖고 `?? code`로 폴백했다. 서버가
 * 내는 코드는 그보다 많아서, 사용자가 실시간 CII 화면에서 **`COMPLETED_NO_DISTANCE`
 * 라는 영문 대문자를 그대로** 봤다 — 실거리가 비어 계획거리로 대체된 완료 항차가
 * 하나라도 있으면 발동한다(`services/ytd_cii.py`).
 *
 * ## 왜 `#630`의 가드가 못 잡았나
 *
 * `voyage-cii/warningMessage.sync.test.ts`는 **그 파일 하나만** 본다. 문구를
 * 내보내는 파일이 둘인데 가드가 하나만 보는 구조였다 — `#749`(금지 문구 가드가
 * 나가는 파일을 안 본다)와 같은 모양이다.
 *
 * ## 여기서 보는 것
 *
 * `#822`는 `warningText`가 `warningMessage`로 폴백하게 했다. 그러면 정본에 있는
 * 코드는 원문으로 노출될 수 없다 — **그 성질을 여기서 고정한다.**
 *
 * 로컬 맵을 지우지 않은 이유는 두 맵의 문구가 2종에서 다르고(`REFERENCE_ONLY`·
 * `COMPLETED_NO_FUEL`), 화면 문구가 `AGENTS §3.2.2`상 디자인 소관이기 때문이다.
 * 대신 로컬 맵이 **정본에 없는 코드를 발명하지 않았는지**를 함께 본다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const API_SPEC = join(HERE, '..', '..', '..', '..', 'API_SPEC.md')

/** `§1.6` 표에서 첫 열의 코드만 뽑는다 — `warningMessage.sync.test.ts`와 같은 방식. */
function codesInSpec(): Set<string> {
  const text = readFileSync(API_SPEC, 'utf-8')
  const start = text.indexOf('### 1.6')
  const end = text.indexOf('### 1.7', start)
  expect(start, '`API_SPEC §1.6` 절을 찾지 못했다').toBeGreaterThan(-1)
  expect(end, '`API_SPEC §1.7` 절을 찾지 못했다').toBeGreaterThan(start)

  const codes = new Set<string>()
  for (const line of text.slice(start, end).split('\n')) {
    const m = /^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|/.exec(line)
    if (m) codes.add(m[1])
  }
  return codes
}

describe('실시간 CII 화면이 경고 코드를 원문으로 노출하지 않는다 (#822)', () => {
  it('절 파싱 자체가 실패하지 않았다', () => {
    // 이 단언이 없으면 정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다.
    expect(codesInSpec().size).toBeGreaterThanOrEqual(10)
  })

  it('§1.6의 어느 코드도 원문으로 나가지 않는다', () => {
    const raw = [...codesInSpec()].filter((code) => warningText(code) === code).sort()
    expect(
      raw,
      `화면에 문구가 없어 원문 코드가 그대로 노출된다: ${raw.join(', ')}`,
    ).toEqual([])
  })

  it('COMPLETED_NO_DISTANCE가 사람 말로 나간다 — 이 이슈가 발견한 코드다', () => {
    /*
     * 실거리가 비어 계획거리로 대체된 완료 항차가 하나라도 있으면 서버가 낸다
     * (`services/ytd_cii.py`). 거리는 CII의 **분모**라 영향이 연료 못지않다(`#449`).
     */
    expect(warningText('COMPLETED_NO_DISTANCE')).not.toBe('COMPLETED_NO_DISTANCE')
    expect(warningText('COMPLETED_NO_DISTANCE')).toBe(
      WARNING_MESSAGE.COMPLETED_NO_DISTANCE,
    )
  })

  it('화면 맞춤 문구가 있는 코드는 그것을 쓴다 — 공유 맵이 덮어쓰지 않는다', () => {
    /*
     * `SIMULATION_NO_FUEL_RATE`는 **행동을 안내해야 한다**(모듈 머리주석). 폴백이
     * 로컬 맵보다 먼저 걸리면 그 의도가 사라진다.
     */
    expect(warningText('REFERENCE_ONLY')).toBe(
      '본 화면의 값은 참고용 예측값이며 규제 제출용 공식 결과가 아닙니다.',
    )
    expect(warningText('REFERENCE_ONLY')).not.toBe(WARNING_MESSAGE.REFERENCE_ONLY)
  })

  it('정본에 없는 코드가 오면 코드 자체를 보인다 — 조용히 감추지 않는다', () => {
    // `#630`의 판단과 같다. 감추면 경고가 사라진 것과 구분되지 않는다.
    expect(warningText('BRAND_NEW_CODE')).toBe('BRAND_NEW_CODE')
  })
})
