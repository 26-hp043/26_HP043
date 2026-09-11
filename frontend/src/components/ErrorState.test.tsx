// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ErrorState } from './ErrorState'
import {
  PAGE_FAILURE_MESSAGE,
  PAGE_FAILURE_TITLE,
  actionFailureTitle,
  loadFailureTitle,
} from './errorCopy'

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
    render(<ErrorState level="region" subject="항차 목록" message="실패." />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('재시도와 다른 길을 함께 두지 않는다', () => {
    /*
     * 다시 시도해도 소용없는 실패(404 등)에 재시도 버튼을 두면 사용자가 같은
     * 실패를 반복한다. 재시도가 있으면 `alternative`는 그리지 않는다.
     */
    render(
      <ErrorState level="page" message="실패" onRetry={() => {}} alternative={<a href="/x">다른 길</a>} />,
    )
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
    expect(screen.queryByText('다른 길')).toBeNull()
  })
})

describe('제목은 대상 명사에서 짓는다 — 2026-09-11 확정 B', () => {
  it('영역 실패 — 조회는 「{대상}을/를 불러오지 못했습니다」', () => {
    render(<ErrorState level="region" subject="선박 목록" message="잠시 후 다시 시도해 주세요." />)
    expect(screen.getByText('선박 목록을 불러오지 못했습니다')).toBeTruthy()
  })

  it('영역 실패 — 처리는 「{동작}에 실패했습니다」', () => {
    render(<ErrorState level="region" action="계산" message="입력값을 확인해 주세요." />)
    expect(screen.getByText('계산에 실패했습니다')).toBeTruthy()
  })

  it('영역 실패에는 기본 제목이 없다 — 주어 없는 「불러오지 못했습니다」가 나오지 않는다', () => {
    /*
     * 기본값이 있으면 그 기본값이 쓰이고, 주어를 붙여 두던 자리도 옮기며 주어를 잃는다.
     * 타입이 `subject`·`action` 중 하나를 요구하므로 여기서는 두 경로의 결과를 본다.
     */
    for (const props of [{ subject: '연료 목록' }, { action: '비교' }]) {
      const { unmount } = render(<ErrorState level="region" message="실패." {...props} />)
      expect(screen.queryByText('불러오지 못했습니다')).toBeNull()
      unmount()
    }
  })

  it('영역 실패는 대상 명사 없이 쓸 수 없다 — 타입이 막는다', () => {
    // 기본 제목이 없으므로 `subject`·`action` 중 하나가 필요하다. 빠지면 빌드(`tsc -b`)가 실패한다.
    // @ts-expect-error — 대상 명사 누락
    const element = <ErrorState level="region" message="실패." />
    expect(element).toBeTruthy()
  })

  it('페이지 실패는 본문을 주지 않으면 기본 본문을 쓴다', () => {
    render(<ErrorState level="page" onRetry={() => {}} />)
    expect(screen.getByText(PAGE_FAILURE_TITLE)).toBeTruthy()
    expect(screen.getByText(PAGE_FAILURE_MESSAGE)).toBeTruthy()
  })

  it('기본 본문의 어미가 한 가지다 — 「주세요」와 「주십시오」를 섞지 않는다', () => {
    // 확정 B ⚠️ — 종전 `LoginFailurePage` 문장이 한 문장 안에서 둘을 섞었다.
    expect(PAGE_FAILURE_MESSAGE).not.toContain('주십시오')
  })

  it('제목에는 마침표가 없고 본문에는 있다 (`PRD §6.4`)', () => {
    for (const title of [PAGE_FAILURE_TITLE, loadFailureTitle('선박 목록'), actionFailureTitle('계산')]) {
      expect(title.endsWith('.')).toBe(false)
    }
    expect(PAGE_FAILURE_MESSAGE.endsWith('.')).toBe(true)
  })
})
