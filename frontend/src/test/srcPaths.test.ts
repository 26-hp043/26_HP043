import { win32 } from 'node:path'
import { pathToFileURL } from 'node:url'
import { describe, expect, it } from 'vitest'
import { dirOf, srcKey } from './srcPaths'

/** 소스 스캔 가드의 경로 규칙 (`#1615`) — Windows 규칙을 Linux에서 재현해 잠근다. */
describe('srcPaths', () => {
  it('Windows 경로의 비교 키도 POSIX 한 모양이다', () => {
    expect(srcKey('C:\\repo\\frontend\\src\\', 'C:\\repo\\frontend\\src\\auth\\session.ts', win32)).toBe(
      'auth/session.ts',
    )
  })

  it('이 OS에서도 같은 키를 낸다', () => {
    const root = dirOf(import.meta.url, '..')
    expect(srcKey(root, dirOf(import.meta.url) + 'srcPaths.ts')).toBe('test/srcPaths.ts')
  })

  it('디렉터리 경로는 URL이 아니라 OS 경로다 — `/C:/…`가 나오지 않는다', () => {
    const dir = dirOf(pathToFileURL('/tmp/x/y.ts'))
    expect(dir.startsWith('/tmp/x')).toBe(true)
    expect(dir).not.toMatch(/^\/[A-Za-z]:/)
  })
})
