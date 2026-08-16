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
  const [busy, setBusy] = useState(false)

  if (!user || isEmailVerified(user.emailVerifiedAt)) return null

  const resend = async () => {
    setBusy(true)
    try {
      setSent(await requestEmailVerification(user.email))
    } catch {
      // 실패해도 배너는 남는다 — 사용자가 다시 누를 수 있다.
      setSent('메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.')
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
    </div>
  )
}
