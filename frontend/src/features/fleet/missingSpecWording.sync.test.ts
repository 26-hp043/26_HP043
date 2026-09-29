/// <reference types="node" />
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { dirOf } from '../../test/srcPaths'
import { unavailableHint } from './fleetRules'

/**
 * **화면이 서버보다 넓게 말하지 않는가** (`#2056`).
 *
 * ## 무엇이 어긋나 있었나
 *
 * `MISSING_SPEC`의 할 일 문장이 「선박 제원(**선종·DWT·GT**)으로 계산할 수 없습니다」였다.
 * 셋을 나열했지만 서버가 보는 것은 **둘**이다 — 선종이 지원 목록에 있는가, 그리고 **그
 * 선종의 축 하나**(DWT 기준 선종은 DWT · GT 기준 선종은 GT)가 양수인가.
 *
 * 그래서 GT 기준 선박의 사용자가 **DWT를 채우라는 안내를 받고 있었다.** 채워도 아무것도
 * 바뀌지 않는다 — 「사용자가 해도 풀리지 않는 일을 안내하지 않는다」(`#419`)를 이 문장
 * 스스로가 어기고 있었다.
 *
 * ## 문자열을 고정하지 않는다
 *
 * 문구는 디자인 소관이라 바뀔 수 있다(`AGENTS §4.6`). 그래서 전문을 박지 않고 **두 축을
 * 배타적으로 말하는가**만 본다 — 「DWT 또는 GT」는 통과, 「선종·DWT·GT」처럼 함께 요구하는
 * 나열은 실패다.
 *
 * ## 전제도 함께 검사한다
 *
 * 「축이 하나」라는 것은 **서버의 판정**이지 화면의 사정이 아니다. 서버가 둘 다 요구하도록
 * 바뀌면 이 문구가 오히려 좁아진다. 그래서 `spec_gap()`이 축을 하나 고르는 함수를 부르는지
 * 파이썬 소스에서 확인한다 — 전제가 무너지면 가드가 먼저 붉어진다.
 */
const ROOT = join(dirOf(import.meta.url), '..', '..', '..', '..')
const CAPACITY = join(ROOT, 'src', 'cii_platform', 'calc', 'capacity.py')
const FLEET_SUMMARY = join(ROOT, 'src', 'cii_platform', 'services', 'fleet_summary.py')

/** 파이썬 쪽을 읽을 수 없는 환경(프런트만 체크아웃)에서는 전제 검사를 건너뛴다. */
const backendPresent = existsSync(CAPACITY) && existsSync(FLEET_SUMMARY)

describe('제원 미입력 안내가 서버 판정보다 넓게 말하지 않는다 (#2056)', () => {
  const hint = unavailableHint('MISSING_SPEC')

  it('두 축을 **배타적으로** 말한다 — 함께 요구하지 않는다', () => {
    expect(hint, '축을 「또는」으로 가르지 않습니다').toMatch(/DWT\s*(또는|·|\/)\s*GT|GT\s*(또는|·|\/)\s*DWT/)
    // 종전 문구가 정확히 이 모양이었다 — 셋을 나란히 요구했다.
    expect(hint).not.toMatch(/선종\s*[·,]\s*DWT\s*[·,]\s*GT/)
    expect(hint).not.toMatch(/DWT\s*(와|과|및)\s*GT/)
  })

  it('서버 어휘 「제원」을 그대로 쓴다', () => {
    /*
     * `#2037`이 가른 것은 **화면 전용 어휘**(「제원 미비」 → 「입력 미완료」)다. 이 문장은
     * 서버 사유(`MISSING_SPEC`)를 푸는 쪽이라 서버 어휘를 쓴다 — 여기까지 바꾸면 같은
     * 사실이 화면과 서버에서 다른 말이 된다(`#750` · `#866`).
     */
    expect(hint).toContain('제원')
  })

  it.runIf(backendPresent)('전제 — 서버는 축을 **하나만** 고른다', () => {
    const capacity = readFileSync(CAPACITY, 'utf8')
    // `capacity_axis()`가 선종을 보고 둘 중 하나를 돌려준다.
    expect(capacity).toMatch(/def capacity_axis\(/)
    expect(capacity).toMatch(/return "DWT"/)
    expect(capacity).toMatch(/return "GT"/)
    // 그리고 그 축 **하나**로만 값을 읽는다.
    expect(capacity).toMatch(/def _capacity_for_axis\(/)
    expect(capacity).toMatch(/vessel\.deadweight if axis == "DWT" else vessel\.gross_tonnage/)
  })

  it.runIf(backendPresent)('전제 — 제원 판정이 그 함수를 그대로 부른다', () => {
    /*
     * `spec_gap()`이 기준을 **다시 적지 않고** 계산 엔진의 함수를 부른다는 것이 이 문구의
     * 근거다. 여기에 별도 판정이 생기면 화면 문구가 무엇을 설명하는지 알 수 없게 된다.
     */
    const summary = readFileSync(FLEET_SUMMARY, 'utf8')
    const body = summary.slice(summary.indexOf('def spec_gap('))
    expect(body.slice(0, body.indexOf('\n\n\n'))).toMatch(/resolve_transport_capacity\(vessel\)/)
  })
})
