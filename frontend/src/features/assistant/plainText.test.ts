// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { stripMarkdown } from './plainText'

/** 2026-09-30 01:31 KST 운영판 `41278bd9`의 실측 답 — `#2064` 본문. */
const MEASURED =
  'D등급: 실적 CII가 기준 CII의 **1.0600배(106.0%) 초과 ~ 1.1800배(118.0%) 이하**'

const DIGITS = /[\d.,]+/g

describe('마크다운 걷어 내기 — #2064', () => {
  it('운영에서 글자로 찍힌 그 별표를 걷는다', () => {
    const out = stripMarkdown(MEASURED)
    expect(out).toBe('D등급: 실적 CII가 기준 CII의 1.0600배(106.0%) 초과 ~ 1.1800배(118.0%) 이하')
    expect(out).not.toContain('*')
  })

  it('숫자는 한 글자도 바뀌지 않는다', () => {
    /*
     * 걷는 일이 **숫자를 건드리면** 사용자가 보는 값과 가드가 본 값이 갈린다.
     * 기호를 어떤 방법으로 걷든 이 관계는 유지되어야 한다.
     */
    for (const text of [
      MEASURED,
      '기준선 a는 **1.5900** · c는 `0.5300`입니다',
      '- **감축률**: 1.1000',
    ]) {
      expect(stripMarkdown(text).match(DIGITS)).toEqual(text.match(DIGITS))
    }
  })

  it('밑줄은 걷지 않는다 — 프롬프트가 적으라고 시킨 칸 이름이다', () => {
    /*
     * `#1703`·`#1973`이 모델에게 `source_ref` · `condition_expr` ·
     * `reduction_factor.by_year`를 **답에 적으라고** 시킨다. 밑줄 쌍을 강조로 보고
     * 걷으면 그 이름들이 망가진다 — 화면 검사는 그래도 모두 통과한다.
     */
    const names = 'source_ref와 condition_expr, reduction_factor.by_year를 함께 적습니다'
    expect(stripMarkdown(names)).toBe(names)
  })

  it('목록은 **지워지지 않고** 가운뎃점으로 남는다', () => {
    /*
     * 통째로 지우면 줄들이 한 덩어리로 읽혀 목록이었다는 것이 사라진다.
     * `·`는 이 제품이 이미 쓰는 구분자다.
     */
    expect(stripMarkdown('- 첫째\n* 둘째\n+ 셋째')).toBe('· 첫째\n· 둘째\n· 셋째')
    expect(stripMarkdown('1. 첫째')).toBe('1. 첫째')
  })

  it('제목 · 인용 · 백틱 · 링크를 걷는다', () => {
    expect(stripMarkdown('## 등급 경계')).toBe('등급 경계')
    expect(stripMarkdown('> 참고')).toBe('참고')
    expect(stripMarkdown('`lookup_regulation` 도구')).toBe('lookup_regulation 도구')
    expect(stripMarkdown('[IMO 원문](https://example.org)을 보십시오')).toBe(
      'IMO 원문을 보십시오',
    )
  })

  it('코드 울타리는 줄만 걷고 안의 글은 남긴다', () => {
    expect(stripMarkdown('```json\n{"d3": "1.0600"}\n```')).toBe('{"d3": "1.0600"}')
  })

  it('기호가 없는 답은 **한 글자도** 바뀌지 않는다', () => {
    const plain = '현재 등급은 C입니다. 기준 CII의 비율은 도구가 준 값입니다.'
    expect(stripMarkdown(plain)).toBe(plain)
  })

  it('걷는 일은 표시 층에만 있다 — 저장 경로는 이 모듈을 알지 못한다', () => {
    /*
     * 저장된 대화는 감사 기록이라 **모델이 낸 그대로** 둔다(`#2064` 체크리스트 ⑶).
     * 받아서 상태에 넣는 쪽(`apiProvider`)이 이 함수를 부르기 시작하면 원문이
     * 조용히 바뀌고, 화면 검사는 그래도 모두 통과한다.
     */
    const provider = readFileSync(join(process.cwd(), 'src/features/assistant/apiProvider.ts'), 'utf-8')
    expect(provider).not.toContain('stripMarkdown')
    expect(provider).not.toContain('plainText')
  })
})
