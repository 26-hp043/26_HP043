import { describe, expect, it } from 'vitest'
import {
  THEME_STORAGE_KEY,
  applyTheme,
  getEffectiveTheme,
  getStoredChoice,
  getSystemTheme,
  setTheme,
  type ThemeRoot,
  type ThemeStorage,
} from './theme'

/*
 * 이 저장소에는 DOM 테스트 환경이 없다(테스트가 전부 순수 로직). 그래서 전역 대신
 * 가짜 저장소·가짜 루트를 주입해 검증한다 — `theme.ts`의 주입 인자가 그 용도다.
 */

function fakeStorage(initial: Record<string, string> = {}): ThemeStorage & {
  data: Record<string, string>
} {
  const data = { ...initial }
  return {
    data,
    getItem: (key) => data[key] ?? null,
    setItem: (key, value) => {
      data[key] = value
    },
  }
}

function fakeRoot(): ThemeRoot & { attr: string | null } {
  return {
    attr: null,
    setAttribute(_name, value) {
      this.attr = value
    },
    removeAttribute() {
      this.attr = null
    },
  }
}

const media = (prefersDark: boolean) => () => ({ matches: prefersDark })

describe('저장된 선택', () => {
  it('저장값이 없으면 null이다 — 미선택은 OS를 따른다는 뜻', () => {
    expect(getStoredChoice(fakeStorage())).toBeNull()
  })

  it('알 수 없는 값은 미선택으로 본다', () => {
    expect(getStoredChoice(fakeStorage({ [THEME_STORAGE_KEY]: 'solarized' }))).toBeNull()
  })

  it('저장된 값을 그대로 읽는다', () => {
    expect(getStoredChoice(fakeStorage({ [THEME_STORAGE_KEY]: 'dark' }))).toBe('dark')
  })

  it('setTheme이 저장하고 문서에 반영한다', () => {
    const storage = fakeStorage()
    const root = fakeRoot()
    setTheme('dark', storage, root)
    expect(storage.data[THEME_STORAGE_KEY]).toBe('dark')
    expect(root.attr).toBe('dark')
  })
})

describe('OS 설정 연동', () => {
  it('미선택이면 OS 다크를 따른다', () => {
    expect(getSystemTheme(media(true))).toBe('dark')
    expect(getEffectiveTheme(fakeStorage(), media(true))).toBe('dark')
  })

  it('명시적 라이트 선택이 OS 다크를 이긴다', () => {
    const storage = fakeStorage({ [THEME_STORAGE_KEY]: 'light' })
    expect(getEffectiveTheme(storage, media(true))).toBe('light')
  })

  it('명시적 다크 선택이 OS 라이트를 이긴다', () => {
    const storage = fakeStorage({ [THEME_STORAGE_KEY]: 'dark' })
    expect(getEffectiveTheme(storage, media(false))).toBe('dark')
  })

  it('matchMedia가 없는 환경에서는 라이트로 본다', () => {
    expect(getSystemTheme(null)).toBe('light')
  })
})

describe('applyTheme', () => {
  it('null이면 속성을 지운다 — OS를 다시 따르게 하는 경로', () => {
    const root = fakeRoot()
    applyTheme('dark', root)
    expect(root.attr).toBe('dark')

    applyTheme(null, root)
    expect(root.attr).toBeNull()
  })

  it('루트가 없어도 던지지 않는다', () => {
    expect(() => applyTheme('dark', null)).not.toThrow()
  })
})

describe('저장소를 못 쓰는 환경', () => {
  it('읽기가 던져도 미선택으로 처리한다', () => {
    const throwing: ThemeStorage = {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {},
    }
    expect(getStoredChoice(throwing)).toBeNull()
  })

  it('쓰기가 던져도 화면에는 적용한다', () => {
    const throwing: ThemeStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error('denied')
      },
    }
    const root = fakeRoot()
    setTheme('dark', throwing, root)
    expect(root.attr).toBe('dark')
  })

  it('저장소가 아예 없어도(null) 화면에는 적용한다', () => {
    const root = fakeRoot()
    setTheme('light', null, root)
    expect(root.attr).toBe('light')
  })
})
