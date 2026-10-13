import { describe, expect, it } from 'vitest'
import { SESSION_KEY, forgetSession, recallSession, rememberSession } from './sessionMemory'

/** 대화 번호의 탭 기억 (`#1981`). 저장소를 인자로 주어 환경에 기대지 않는다. */

function memoryStorage(): Storage {
  const map = new Map<string, string>()
  return {
    get length() {
      return map.size
    },
    clear: () => map.clear(),
    getItem: (key) => map.get(key) ?? null,
    key: (index) => [...map.keys()][index] ?? null,
    removeItem: (key) => {
      map.delete(key)
    },
    setItem: (key, value) => {
      map.set(key, value)
    },
  }
}

describe('기억 · 되찾기 · 지우기', () => {
  it('기억한 번호를 되찾고, 지우면 없다', () => {
    const storage = memoryStorage()
    expect(recallSession(storage)).toBeUndefined()
    rememberSession('s-1', storage)
    expect(recallSession(storage)).toBe('s-1')
    expect(storage.getItem(SESSION_KEY)).toBe('s-1')
    forgetSession(storage)
    expect(recallSession(storage)).toBeUndefined()
  })

  it('저장소가 없거나 막혀 있어도 던지지 않는다 — 조용히 새 대화다', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
      removeItem: () => {
        throw new Error('blocked')
      },
    } as unknown as Storage
    expect(() => rememberSession('s-1', broken)).not.toThrow()
    expect(recallSession(broken)).toBeUndefined()
    expect(() => forgetSession(broken)).not.toThrow()
    expect(recallSession(undefined)).toBeUndefined()
  })

  it('빈 문자열은 기억이 아니다', () => {
    const storage = memoryStorage()
    storage.setItem(SESSION_KEY, '')
    expect(recallSession(storage)).toBeUndefined()
  })
})
