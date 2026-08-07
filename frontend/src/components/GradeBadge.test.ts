import { describe, expect, it } from 'vitest'
import { gradePatternUrl } from './gradePattern'
import type { Rating } from '../features/voyage-cii/types'

/**
 * `DESIGN_SYSTEM §14` — 패턴 없는 등급 표시는 구현 금지.
 * 색만으로 A~E를 구분하면 적록색맹에서 A(녹)와 E(적)가 무너진다.
 */
describe('gradePatternUrl', () => {
  it('A는 solid라 패턴이 없다', () => {
    // 「패턴 없음」 자체가 A의 식별 표시이고 등급 문자가 항상 함께 놓인다(§15.1).
    expect(gradePatternUrl('A')).toBeUndefined()
  })

  it.each([
    ['B', 'url(#grade-b)'],
    ['C', 'url(#grade-c)'],
    ['D', 'url(#grade-d)'],
    ['E', 'url(#grade-e)'],
  ])('%s는 %s', (rating, url) => {
    expect(gradePatternUrl(rating as Rating)).toBe(url)
  })

  it('A를 뺀 네 등급이 서로 다른 패턴을 쓴다', () => {
    const urls = (['B', 'C', 'D', 'E'] as Rating[]).map(gradePatternUrl)
    expect(new Set(urls).size).toBe(4)
  })
})
