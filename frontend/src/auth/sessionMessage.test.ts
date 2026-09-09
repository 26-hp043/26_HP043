import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { SESSION_EXPIRED_MESSAGE } from './session'

/**
 * 세션 만료 문구는 **한 곳에서만 나온다** (#901).
 *
 * 종전에는 같은 상황에 두 가지 말이 나갔다 — `auth/session.ts`와 네 provider가
 * `로그인이 만료되었습니다. 다시 로그인해 주세요.`를 **각자 선언**했고, 나머지
 * 여덟 provider는 `세션이 만료되었습니다.`라는 **다른 문장**을 썼다. 사용자가
 * 어느 화면에서 튕겼는지에 따라 다른 안내를 받는다.
 *
 * 문구 자체를 여기 다시 적지 않는다 — 적으면 이 파일이 **세 번째 출처**가 된다.
 * `session.ts`에서 가져와 대조한다.
 */
const SRC = new URL('..', import.meta.url).pathname

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    if (!/\.tsx?$/.test(name) || name.includes('.test.')) return []
    return [path]
  })
}

describe('세션 만료 문구의 출처는 하나다 (#901)', () => {
  const files = sourceFiles(SRC)

  it('정본 선언은 auth/session.ts 한 곳뿐이다', () => {
    const declaring = files.filter((path) =>
      /export const SESSION_EXPIRED_MESSAGE/.test(readFileSync(path, 'utf8')),
    )
    expect(declaring.map((p) => p.slice(SRC.length))).toEqual(['auth/session.ts'])
  })

  it('문구를 리터럴로 다시 적은 파일이 없다', () => {
    // 정본 선언이 있는 파일만 그 문자열을 담을 수 있다.
    const offenders = files.filter(
      (path) =>
        !path.endsWith('auth/session.ts') &&
        readFileSync(path, 'utf8').includes(SESSION_EXPIRED_MESSAGE),
    )
    expect(offenders.map((p) => p.slice(SRC.length))).toEqual([])
  })

  it('갈라져 있던 짧은 판이 남아 있지 않다', () => {
    // 이 문장은 정본과 **다른 말**이었다. 되살아나면 다시 두 갈래가 된다.
    const offenders = files.filter((path) =>
      readFileSync(path, 'utf8').includes('세션이 만료되었습니다.'),
    )
    expect(offenders.map((p) => p.slice(SRC.length))).toEqual([])
  })
})
