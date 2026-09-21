// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DisclaimerBanner } from './DisclaimerBanner'

/**
 * 면책 배너 한 칸이 `PRD §6.3` 두 행을 함께 말할 수 있다 (#1578).
 *
 * 대시보드 · 선박 상세는 「추정값 사용」 문장을 배너 **아래 별도 문단**으로 붙여 하단에
 * 고지 두 덩어리가 겹쳐 보였다. 문구는 그대로 두고 **같은 배너 안 둘째 문장**으로 옮긴다.
 */
const DISCLAIMER = '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.'
const ESTIMATE = '일부 값은 사용자 입력 또는 모델 추정값입니다.'

describe('면책 배너 — 추정값 문장 (#1578)', () => {
  it('기본은 §6.3 「모든 결과 화면」 한 문장뿐이다', () => {
    render(<DisclaimerBanner />)
    expect(screen.getByRole('note').textContent).toBe(DISCLAIMER)
  })

  it('estimate면 같은 배너 안에 §6.3 「추정값 사용」 원문이 둘째 문장으로 붙는다', () => {
    render(<DisclaimerBanner estimate />)
    const notes = screen.getAllByRole('note')
    expect(notes).toHaveLength(1)
    expect(notes[0].textContent).toBe(`${DISCLAIMER} ${ESTIMATE}`)
  })

  it('서버 문구를 받아도 추정값 문장은 그 뒤에 붙는다', () => {
    render(<DisclaimerBanner text="서버 면책." estimate />)
    expect(screen.getByRole('note').textContent).toBe(`서버 면책. ${ESTIMATE}`)
  })
})
