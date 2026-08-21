import { readFileSync } from 'node:fs'
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

  it('미선택이면 OS 라이트를 따른다', () => {
    // 다크 쪽만 잠가 두면 「무조건 다크」로 잘못 고쳐도 통과한다. 양방향을 함께 본다.
    expect(getSystemTheme(media(false))).toBe('light')
    expect(getEffectiveTheme(fakeStorage(), media(false))).toBe('light')
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

/**
 * `index.html` 인라인 스크립트와의 어긋남 방지.
 *
 * 테마는 **두 곳**이 적용한다 — 첫 페인트 전에는 `index.html`의 인라인 스크립트가,
 * 그 뒤 변경은 이 모듈이 맡는다. FOUC를 막으려면 React보다 먼저 돌아야 해서
 * 나뉜 구조이고, `theme.ts` 주석이 「두 곳이 같은 키·같은 규칙을 쓴다」고 적어 두었다.
 *
 * 그런데 **그 약속을 강제하는 것이 없었다.** 키를 한쪽만 바꾸면 저장은 되는데 첫
 * 페인트가 그 값을 못 읽어, 다크 사용자에게 흰 화면이 한 번 번쩍인 뒤 어두워진다 —
 * 화면이 깨지지 않고 깜빡임만 남으므로 발견이 늦다. 여기서 잠근다.
 */
describe('index.html 인라인 스크립트 — 첫 페인트 전 적용', () => {
  const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf-8')

  it('모듈과 같은 저장소 키를 쓴다', () => {
    expect(html).toContain(`'${THEME_STORAGE_KEY}'`)
  })

  it('`<head>` 안에서, 앱 번들보다 먼저 돈다', () => {
    // 번들 뒤로 밀리면 React 마운트 뒤에 적용돼 FOUC를 막지 못한다.
    const script = html.indexOf(THEME_STORAGE_KEY)
    expect(script).toBeGreaterThan(-1)
    expect(script).toBeLessThan(html.indexOf('</head>'))
    expect(script).toBeLessThan(html.indexOf('src/main.tsx'))
  })

  it('저장값이 없으면 속성을 붙이지 않는다', () => {
    /*
     * 미선택일 때 라이트를 박으면 OS가 다크인 사용자에게 흰 화면이 나가고,
     * 나중에 OS를 바꿔도 화면이 따라가지 않는다(`tokens.css`의 3-상태 규칙 전제).
     * 스크립트가 두 값에 대해서만 `setAttribute`를 부르는지 본다.
     */
    expect(html).toMatch(/if\s*\(\s*stored === 'light' \|\| stored === 'dark'\s*\)/)
    expect(html).not.toMatch(/setAttribute\([^)]*'light'\s*\)/)
  })
})
