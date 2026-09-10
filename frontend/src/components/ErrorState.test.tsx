// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ErrorState } from './ErrorState'

/**
 * 실패 표시 규격 (`#694` · 2026-09-10 디자인 확정).
 *
 * 여기서 잠그는 것은 **규격 자체**다 — 층위·재시도 문구·색 채널. 화면마다 다시
 * 판단하지 않게 하려고 만든 규격이므로, 규격이 흔들리면 24종이 다시 생긴다.
 */
describe('층위와 재시도 (#694)', () => {
  it('페이지 실패에는 제목이 있다', () => {
    render(<ErrorState level="page" message="불러오지 못했습니다." />)
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('화면을 불러오지 못했습니다')).toBeTruthy()
  })

  it('compact는 제목을 두지 않는다 — 한 줄이 곧 제목이자 본문이다', () => {
    render(<ErrorState level="region" size="compact" message="목록을 불러오지 못했습니다." />)
    expect(screen.getByText('목록을 불러오지 못했습니다.')).toBeTruthy()
    expect(screen.queryByText('불러오지 못했습니다')).toBeNull()
  })

  it('재시도 문구는 「다시 시도」 하나다', () => {
    /*
     * 「다시 불러오기 / 다시 계산 / 재시도」로 갈리는 것이 **24종이 생긴 경로**다.
     * 문구를 인자로 받지 않으므로 호출부가 만들 수 없다.
     */
    const onRetry = vi.fn()
    render(<ErrorState level="page" message="실패" onRetry={onRetry} />)
    const button = screen.getByRole('button', { name: '다시 시도' })
    fireEvent.click(button)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('재시도를 주지 않으면 버튼이 없다', () => {
    render(<ErrorState level="region" message="실패" />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('재시도와 다른 길을 함께 두지 않는다', () => {
    /*
     * 다시 시도해도 소용없는 실패(404 등)에 재시도 버튼을 두면 사용자가 같은
     * 실패를 반복한다. 재시도가 있으면 `action`은 그리지 않는다.
     */
    render(
      <ErrorState level="page" message="실패" onRetry={() => {}} action={<a href="/x">다른 길</a>} />,
    )
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
    expect(screen.queryByText('다른 길')).toBeNull()
  })
})
