/**
 * 이메일 인증 토큰의 **일회성**을 화면 밖에서 지킨다 (`#1646`).
 *
 * 개발 Strict Mode는 효과를 mount → unmount → mount로 두 번 돌린다. 첫 요청이 토큰을 정상으로
 * 소비하고 두 번째 요청이 「이미 사용됨」 오류를 받아 **성공한 인증이 실패 화면으로 덮였다.**
 * 토큰별로 진행 중·끝난 요청을 기억해 두 번째 효과가 **같은 요청의 결과를 받게** 한다.
 *
 * ## 왜 별도 파일인가
 *
 * 화면 파일이 컴포넌트가 아닌 것을 함께 내보내면 Fast Refresh가 깨진다(`react-refresh` 규칙 ·
 * CI lint 오류). 기억은 컴포넌트 밖 상태이므로 모듈로 뺀다 — `useRef`로는 unmount에서 사라져
 * 두 번째 mount를 막지 못한다.
 */

import { confirmEmailVerification } from '../auth/session'

/** 토큰 → 그 토큰으로 이미 보낸 요청. 성공 결과는 남기고, 실패는 지운다. */
const requests = new Map<string, Promise<string>>()

/** 검사용 — 모듈 기억을 비운다. */
export function resetVerificationRequests(): void {
  requests.clear()
}

export function verifyOnce(token: string): Promise<string> {
  const existing = requests.get(token)
  if (existing) return existing
  const request = confirmEmailVerification(token).catch((error: unknown) => {
    requests.delete(token)
    throw error
  })
  requests.set(token, request)
  return request
}
