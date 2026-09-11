/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { EMAIL_IMMUTABLE_NOTICE, INVITE_CODE_HINT, WITHDRAWAL_NOTICE } from './authRules'

/**
 * 정본 문구 ↔ `PRD §6.3` 표 드리프트 가드 (`#754`).
 *
 * ## 왜 필요한가
 *
 * `AGENTS §4.6`이 **「정본 문구」와 「표시 문구」**를 구분한다(`#468`). 정본이 원문을
 * 확정한 문구는 화면이 **임의로 바꿀 수 없다** — 그런데 그 규칙을 지키는지 확인하는
 * 자리가 없었다.
 *
 * `#754`가 그 공백의 결과를 보여 준다: `PRD §6.3`의 탈퇴 확인 문구가 원문까지
 * 확정돼 있는데 **소비처가 0**이었다. 화면 자체가 없었고, 그 사실이 어디에서도
 * 드러나지 않았다. 다음에 누가 화면을 만들 때 이 문구를 못 찾고 **새로 적을** 여지가
 * 그대로 남아 있었다.
 *
 * ## 무엇을 보는가
 *
 * `PRD §6.3` 표의 「문구」 열을 읽어 코드 상수와 **문자 단위로** 대조한다.
 * `digits.sync.test.ts`가 `DESIGN_SYSTEM §4.2` 표를 읽어 자릿수를 대조하는 것과
 * 같은 방식이다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const PRD = join(HERE, '..', '..', '..', '..', 'PRD.md')

/**
 * `PRD §6.3` 표에서 한 행의 문구를 뽑는다.
 *
 * 표 모양: `| 탈퇴 확인 | `문구` |` — 문구는 백틱 안에 있다.
 */
function noticeInPrd(label: string): string {
  const text = readFileSync(PRD, 'utf-8')
  const row = new RegExp(`^\\|\\s*${label}\\s*\\|\\s*\`([^\`]+)\`\\s*\\|`, 'm')
  const match = row.exec(text)
  expect(match, `\`PRD §6.3\` 표에서 「${label}」 행을 찾지 못했다 — 표 형식이 바뀌었는지 확인할 것`).not.toBeNull()
  return match![1]
}

describe('정본이 확정한 문구를 화면이 그대로 쓴다 (#754)', () => {
  it('표 파싱 자체가 실패하지 않았다', () => {
    // 이 단언이 없으면 정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다.
    expect(noticeInPrd('탈퇴 확인').length).toBeGreaterThan(20)
  })

  it('탈퇴 확인 문구가 `PRD §6.3`과 문자 단위로 같다', () => {
    expect(WITHDRAWAL_NOTICE).toBe(noticeInPrd('탈퇴 확인'))
  })

  it('이메일 변경 불가 고지도 같다 — 같은 표의 다른 행', () => {
    /*
     * `#754` 이전부터 있던 상수다. 이 가드가 그때는 없어서 **대조된 적이 없었다** —
     * 함께 잠근다.
     */
    expect(EMAIL_IMMUTABLE_NOTICE).toBe(noticeInPrd('회원가입 — 이메일 변경 불가 고지'))
  })

  it('초대 코드 안내도 같다 — 가입 게이트 (#808)', () => {
    expect(INVITE_CODE_HINT).toBe(noticeInPrd('회원가입 — 초대 코드 안내'))
  })
})
