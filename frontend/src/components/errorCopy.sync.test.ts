import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  PAGE_FAILURE_MESSAGE,
  PAGE_FAILURE_TITLE,
  actionFailureTitle,
  loadFailureTitle,
} from './errorCopy'

describe('문구는 `PRD §6.4`와 같다 — 컴포넌트가 정본을 전사한다', () => {
  /*
   * `DESIGN_SYSTEM §13`이 「문구 원문은 PRD §6에 있다」로 정한다. 종전에는 이 컴포넌트의
   * 기본 제목이 **어느 정본에도 없었다**(`#931`). 등재한 뒤 한쪽만 바뀌면 여기서 실패한다.
   */
  const HERE = fileURLToPath(new URL('.', import.meta.url))
  const prd = readFileSync(join(HERE, '..', '..', '..', 'PRD.md'), 'utf-8')
  const start = prd.indexOf('### 6.4 ')
  const section = prd.slice(start, prd.indexOf('\n---', start))

  it('§6.4를 찾았다', () => {
    expect(start).toBeGreaterThan(-1)
  })

  it.each([
    ['페이지 실패 제목', PAGE_FAILURE_TITLE],
    ['페이지 실패 본문', PAGE_FAILURE_MESSAGE],
    ['조회 실패 패턴', loadFailureTitle('{대상}').replace('{대상}를', '{대상}을/를')],
    ['처리 실패 패턴', actionFailureTitle('{동작}')],
    ['재시도 버튼', '다시 시도'],
  ])('%s', (_, text) => {
    expect(section).toContain(`\`${text}\``)
  })
})
