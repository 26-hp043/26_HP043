import type { CurrentUser } from '../auth/session'

/**
 * 사이드바 계정 카드의 역할 자리 글자 키 (#2203 · `DESIGN_SYSTEM §7.2`).
 *
 * **둘러보기 계정이면 역할 대신 「둘러보기」다.** 둘러보기 계정은 서비스를 다 보이려고
 * `ADMIN`이라(`POST /auth/tour-login`) `role`만 보면 「관리자」가 적힌다 — 심사위원이 그것을
 * 자기 권한으로 읽는다. 판정은 서버의 `is_tour`(고정 PK) 하나다.
 */
export function roleKey(user: Pick<CurrentUser, 'role' | 'isTour'>) {
  if (user.isTour === true) return 'account.role.tour' as const
  return `account.role.${user.role}` as const
}
