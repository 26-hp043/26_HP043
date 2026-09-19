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
 * 이 화면은 자기 문구 맵(`WARNING_TEXT`)을 갖고 `?? code`로 폴백했다. 서버가
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
 *
 * ## 사본은 소스로 본다 (#1292)
 *
 * 종전에 로컬 맵이 7종이었는데 **5종이 폴백과 글자까지 같았다.** 그런 항목은
 * `warningText()`로는 **보이지 않는다** — 로컬에서 나온 값과 폴백에서 나온 값이
 * 같은 문자열이라 동작이 구분되지 않는다. 그래서 여기서만 **소스를 읽는다.**
 * `deadCss.test.ts`·`a11yWiring.test.ts`가 같은 이유로 소스를 보는 것과 같다.
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

/**
 * 「화면 맞춤」이라는 이름값을 지킨다 (#1292).
 *
 * 폴백과 같은 문구를 로컬 맵에 두면 지워도 화면이 안 바뀌는 **사본**이 된다.
 * `API_SPEC §1.6`이 개정되면 `WARNING_MESSAGE`만 따라가고 이쪽은 조용히 낡는다.
 *
 * 사본이 생긴 경위는 순서다 — `#649`·`#653`이 항목을 넣을 때는 폴백이 없어
 * 여기 없으면 원문 코드가 화면에 나왔다. `#822`가 폴백을 만들며 그 이유가
 * 사라졌는데 항목은 남았다.
 */
describe('로컬 문구 맵에 폴백과 같은 문구를 두지 않는다 (#1292)', () => {
  /** 소스에서 `WARNING_TEXT` 리터럴을 떼어 낸다 — `export`하지 않는 맵이다(`#594`). */
  function localEntries(): Record<string, string> {
    const file = join(HERE, 'realtimeRules.ts')
    const src = readFileSync(file, 'utf-8')
    const at = src.indexOf('const WARNING_TEXT')
    expect(at, '`WARNING_TEXT` 선언을 찾지 못했다').toBeGreaterThan(-1)

    const open = src.indexOf('{', at)
    let depth = 0
    let end = open
    for (; end < src.length; end++) {
      if (src[end] === '{') depth++
      else if (src[end] === '}') {
        depth--
        if (depth === 0) break
      }
    }
    const body = src.slice(open, end)
    const found: Record<string, string> = {}
    for (const m of body.matchAll(/(?:^|\n)\s*([A-Z_0-9]+):\s*\n?\s*'((?:[^'\\]|\\.)*)'/g)) {
      found[m[1]] = m[2]
    }
    return found
  }

  it('파싱 자체가 실패하지 않았다', () => {
    // 이 단언이 없으면 정규식이 깨진 순간부터 아래 대조가 무의미해진다.
    expect(Object.keys(localEntries()).length).toBeGreaterThan(0)
  })

  it('⚠️ 로컬 맵의 모든 항목이 폴백과 다르다 — 같으면 사본이다', () => {
    const copies = Object.entries(localEntries())
      .filter(([code, text]) => WARNING_MESSAGE[code] === text)
      .map(([code]) => code)
      .sort()
    expect(
      copies,
      `폴백과 글자까지 같아 지워도 화면이 바뀌지 않습니다 — 지우세요: ${copies.join(', ')}`,
    ).toEqual([])
  })
})
