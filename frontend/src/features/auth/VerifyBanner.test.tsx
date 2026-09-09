// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VerifyBanner } from './VerifyBanner'
import { probeCurrentUser } from '../../auth/session'

/**
 * 재발송이 실패해도 **다시 누를 수 있다** (#825 ⑸).
 *
 * 종전에는 성공 문구와 실패 문구가 **같은 상태**(`sent`)에 들어갔고, 렌더의 삼항이
 * `sent`가 있으면 **버튼을 문구로 교체**했다. 그래서 「잠시 후 다시 시도해 주세요」라고
 * 말하면서 **다시 시도할 수단을 없앴다** — 새로고침해야 복구된다.
 *
 * ⚠️ **주석과 코드가 정면으로 어긋난 상태였다** — *「실패해도 배너는 남는다 — 사용자가
 * 다시 누를 수 있다」*. 백엔드는 SMTP 실패에서 실제로 502를 낸다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

/** 미인증 사용자를 캐시에 넣는다 — 배너는 그때만 그려진다. */
async function signInUnverified() {
  await probeCurrentUser(
    async () =>
      jsonResponse({
        data: {
          id: 'u-1',
          email: 'captain@example.com',
          display_name: '김선장',
          email_verified_at: null,
        },
      }) as unknown as Response,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('인증 메일 재발송 실패 (#825 ⑸)', () => {
  it('실패해도 버튼이 남는다 — 다시 누를 수 있다', async () => {
    await signInUnverified()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ error: { message: '메일 발송에 실패했습니다.' } }, 502),
      ),
    )

    render(<VerifyBanner />)
    fireEvent.click(await screen.findByTestId('resend-verification'))

    expect(await screen.findByText('메일 발송에 실패했습니다.')).toBeTruthy()
    // ⚠️ 여기가 핵심 — 종전에는 이 버튼이 문구로 교체돼 사라졌다.
    expect(screen.getByTestId('resend-verification')).toBeTruthy()
  })

  it('실패 문구를 `alert`로 알린다 — 배너가 polite라 그냥 두면 읽히지 않는다', async () => {
    await signInUnverified()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ error: { message: '메일 발송에 실패했습니다.' } }, 502)),
    )

    render(<VerifyBanner />)
    fireEvent.click(await screen.findByTestId('resend-verification'))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('메일 발송에 실패했습니다.')
  })

  it('성공하면 종전대로 문구가 버튼을 대신한다', async () => {
    await signInUnverified()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ data: { message: '인증 메일을 보냈습니다.' } })),
    )

    render(<VerifyBanner />)
    fireEvent.click(await screen.findByTestId('resend-verification'))

    expect(await screen.findByText('인증 메일을 보냈습니다.')).toBeTruthy()
    await waitFor(() => expect(screen.queryByTestId('resend-verification')).toBeNull())
  })
})
