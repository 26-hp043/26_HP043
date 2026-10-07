import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { SESSION_EXPIRED_MESSAGE } from './session'
import { dirOf, srcKey } from '../test/srcPaths'

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
const SRC = dirOf(import.meta.url, '..')

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    if (!/\.tsx?$/.test(name) || name.includes('.test.')) return []
    return [path]
  })
}

/*
 * 파일은 **한 번만** 읽는다 (`#2250`). 세 검사가 같은 파일 수백 개를 각자 다시 읽고
 * 있었다 — 읽는 대상이 같으므로 한 번이면 된다. 검사 파일은 실행마다 새로 불려 오므로
 * 이 기억이 다음 실행으로 넘어가지 않는다.
 */
const texts = new Map<string, string>()

function text(path: string): string {
  let found = texts.get(path)
  if (found === undefined) {
    found = readFileSync(path, 'utf8')
    texts.set(path, found)
  }
  return found
}

/*
 * 기본 5초를 쓰지 않는다 (`#2250`). `src/` 전체를 읽는 값은 디스크가 정한다 — CI에서는
 * 0.1초 안쪽이지만, 저장소가 느린 파일 시스템 위에 있고 다른 작업이 함께 돌면 한 번
 * 읽는 데 2~4초가 걸려 5초에 닿았다. 20초는 `deadCss.test.ts`가 같은 훑기에 준 값이다.
 * 셋 중 어느 검사가 먼저 돌아도 그 검사가 읽기 값을 치르므로 셋 모두에 준다.
 */
const SCAN_TIMEOUT_MS = 20_000

describe('세션 만료 문구의 출처는 하나다 (#901)', () => {
  const files = sourceFiles(SRC)

  it('정본 선언은 auth/session.ts 한 곳뿐이다', { timeout: SCAN_TIMEOUT_MS }, () => {
    const declaring = files.filter((path) =>
      /export const SESSION_EXPIRED_MESSAGE/.test(text(path)),
    )
    expect(declaring.map((p) => srcKey(SRC, p))).toEqual(['auth/session.ts'])
  })

  it('문구를 리터럴로 다시 적은 파일이 없다', { timeout: SCAN_TIMEOUT_MS }, () => {
    // 정본 선언이 있는 파일만 그 문자열을 담을 수 있다.
    const offenders = files.filter(
      (path) =>
        !path.endsWith('auth/session.ts') &&
        text(path).includes(SESSION_EXPIRED_MESSAGE),
    )
    expect(offenders.map((p) => srcKey(SRC, p))).toEqual([])
  })

  it('갈라져 있던 짧은 판이 남아 있지 않다', { timeout: SCAN_TIMEOUT_MS }, () => {
    // 이 문장은 정본과 **다른 말**이었다. 되살아나면 다시 두 갈래가 된다.
    const offenders = files.filter((path) =>
      text(path).includes('세션이 만료되었습니다.'),
    )
    expect(offenders.map((p) => srcKey(SRC, p))).toEqual([])
  })
})
