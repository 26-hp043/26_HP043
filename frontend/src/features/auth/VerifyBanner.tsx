import { useState } from 'react'
import { isEmailVerified } from './authRules'
import { requestEmailVerification, useAuthUser } from '../../auth/session'

/**
 * 이메일 미인증 배너 (#415).
 *
 * ## 왜 막지 않고 배너로 두는가
 *
 * `PRD §7.10`이 **미인증 상태에서도 로그인과 이용을 허용**하도록 규정한다. 강제하면
 * 메일이 도착하지 않을 때 **사용자가 아무것도 하지 못하는 상태**가 되고, 시연 중
 * 메일 지연으로 진행이 막히는 것도 실질적 위험이다.
 *
 * 대신 셸 상단에 상시 노출해 잊히지 않게 한다.
 */
export function VerifyBanner() {
  const user = useAuthUser()
  const [sent, setSent] = useState<string | null>(null)
  /*
   * 실패는 **성공과 다른 상태에 담는다** (`#825` ⑸).
   *
   * 종전에는 둘 다 `sent`에 들어갔고, 아래 삼항이 `sent`가 있으면 **버튼을 문구로
   * 교체**했다. 그래서 「잠시 후 다시 시도해 주세요」라고 말하면서 **다시 시도할
   * 수단을 없앴다** — 새로고침해야 복구된다.
   *
   * 바로 위 주석은 *「실패해도 배너는 남는다 — 사용자가 다시 누를 수 있다」*를 적어
   * 두었다. **주석과 코드가 정면으로 어긋난 상태**였다. 백엔드는 SMTP 실패에서 실제로
   * 502를 낸다(`routes/auth_tokens.py`).
   */
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!user || isEmailVerified(user.emailVerifiedAt)) return null

  const resend = async () => {
    setBusy(true)
    setFailure(null)
    try {
      setSent(await requestEmailVerification(user.email))
    } catch (error) {
      // 서버 문구를 그대로 쓴다 — 무엇이 막혔는지는 서버가 가장 정확히 안다.
      setFailure(
        error instanceof Error
          ? error.message
          : '메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="verify-banner" role="status">
      {/* `PRD §6.3` 확정 문구. */}
      <span>이메일 인증이 완료되지 않았습니다. 받은 메일의 링크를 눌러 주세요.</span>
      {sent ? (
        <span className="verify-banner__action">{sent}</span>
      ) : (
        <button
          type="button"
          className="verify-banner__action"
          onClick={() => void resend()}
          disabled={busy}
          data-testid="resend-verification"
        >
          {busy ? '보내는 중…' : '인증 메일 다시 받기'}
        </button>
      )}
      {/*
        실패는 **버튼을 지우지 않고 옆에** 붙는다 (`#825` ⑸).

        `role="alert"`인 이유: 이 배너 전체가 `role="status"`(polite)라 실패 문구를
        그 안에 그냥 두면 **오류로 안내되지 않는다.** 「메일이 안 갔다」는 사용자가
        지금 알아야 하는 사실이다.
      */}
      {failure !== null ? (
        <span className="verify-banner__failure" role="alert">
          {failure}
        </span>
      ) : null}
    </div>
  )
}
