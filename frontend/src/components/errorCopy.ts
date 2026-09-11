import { withEulReul } from '../display/josa'

/*
 * 실패 표시의 문구 (`PRD §6.4` · 2026-09-11 디자인 확정 B).
 *
 * `ErrorState.tsx`와 파일을 나눈 것은 fast refresh 규칙(컴포넌트 파일은 컴포넌트만
 * 내보낸다) 때문이다. 정본과의 대조는 `errorCopy.sync.test.ts`가 한다.
 */

export const PAGE_FAILURE_TITLE = '화면을 불러오지 못했습니다'
export const PAGE_FAILURE_MESSAGE =
  '잠시 후 다시 시도해 주세요. 문제가 계속되면 관리자에게 문의해 주세요.'

/** 조회 실패 제목 — `{대상}을/를 불러오지 못했습니다`. */
export function loadFailureTitle(subject: string): string {
  return `${withEulReul(subject)} 불러오지 못했습니다`
}

/** 처리 실패 제목 — `{동작}에 실패했습니다`. */
export function actionFailureTitle(action: string): string {
  return `${action}에 실패했습니다`
}
