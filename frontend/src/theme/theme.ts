/**
 * 테마(라이트·다크) 상태.
 *
 * ## 상태가 셋이다
 *
 * 사용자가 고른 값은 `light` · `dark` 둘뿐이지만, **아직 고르지 않은 상태**가 따로
 * 있다. 그때는 OS 설정(`prefers-color-scheme`)을 따른다.
 *
 * | 저장값 | `<html data-theme>` | 실제 표시 |
 * |---|---|---|
 * | 없음 (미선택) | 속성 없음 | OS 설정을 따름 |
 * | `light` | `light` | 항상 라이트 |
 * | `dark` | `dark` | 항상 다크 |
 *
 * **미선택일 때 `data-theme`을 붙이지 않는 것이 중요하다.** 붙여 버리면 OS 설정을
 * 나중에 바꿔도 화면이 따라가지 않는다. `tokens.css`의 3-상태 규칙이 이 전제 위에
 * 서 있다.
 *
 * ## 첫 페인트 전에 적용해야 한다
 *
 * React가 마운트된 뒤에 속성을 붙이면 **흰 화면이 한 번 번쩍인 뒤 다크로 바뀐다.**
 * 그래서 실제 적용은 `index.html`의 인라인 스크립트가 먼저 하고, 이 모듈은 그 뒤의
 * 변경만 맡는다. 두 곳이 같은 키·같은 규칙을 쓴다 — 키를 바꾸면 양쪽을 함께 고친다.
 *
 * ## 왜 전역을 직접 쓰지 않고 주입받는가
 *
 * 이 저장소에는 DOM 테스트 환경(jsdom 등)이 없다 — 테스트가 전부 순수 로직이다.
 * `session.ts`가 `fetchImpl`·`env`를 주입받는 것과 같은 방식으로, 여기서도
 * 저장소·미디어쿼리·루트 요소를 **선택적 인자**로 받는다. 실행 시에는 전역을 쓰고,
 * 테스트에서는 가짜를 넘긴다. 의존성을 새로 추가하지 않기 위한 선택이다.
 */

/** `index.html` 인라인 스크립트와 **공유하는 키**. 바꾸면 양쪽을 함께 고친다. */
export const THEME_STORAGE_KEY = 'bluelog-theme'

export type ThemeChoice = 'light' | 'dark'

const DARK_QUERY = '(prefers-color-scheme: dark)'

/** 테스트에서 갈아 끼우는 최소 인터페이스들. */
export interface ThemeStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export interface ThemeRoot {
  setAttribute(name: string, value: string): void
  removeAttribute(name: string): void
}

export type ThemeMatchMedia = (query: string) => { matches: boolean }

/** 전역이 없거나 접근이 막힌 환경(사파리 프라이빗 등)에서는 `null`을 준다. */
function defaultStorage(): ThemeStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function defaultMatchMedia(): ThemeMatchMedia | null {
  if (typeof window === 'undefined' || !window.matchMedia) return null
  return (query) => window.matchMedia(query)
}

function defaultRoot(): ThemeRoot | null {
  return typeof document === 'undefined' ? null : document.documentElement
}

/** 저장된 명시적 선택. 없으면 `null`(= OS 설정을 따름). */
export function getStoredChoice(
  storage: ThemeStorage | null = defaultStorage(),
): ThemeChoice | null {
  if (!storage) return null
  try {
    const raw = storage.getItem(THEME_STORAGE_KEY)
    return raw === 'light' || raw === 'dark' ? raw : null
  } catch {
    // 접근이 던지는 환경이 있다. 미선택으로 본다.
    return null
  }
}

/** OS 설정. `matchMedia`가 없는 환경에서는 라이트로 본다. */
export function getSystemTheme(
  matchMediaImpl: ThemeMatchMedia | null = defaultMatchMedia(),
): ThemeChoice {
  if (!matchMediaImpl) return 'light'
  return matchMediaImpl(DARK_QUERY).matches ? 'dark' : 'light'
}

/** 지금 화면에 실제로 적용된 테마. */
export function getEffectiveTheme(
  storage: ThemeStorage | null = defaultStorage(),
  matchMediaImpl: ThemeMatchMedia | null = defaultMatchMedia(),
): ThemeChoice {
  return getStoredChoice(storage) ?? getSystemTheme(matchMediaImpl)
}

/**
 * 문서에 반영한다.
 *
 * `null`이면 속성을 **지운다** — 위 표의 「미선택」으로 되돌리는 경로다.
 */
export function applyTheme(
  choice: ThemeChoice | null,
  root: ThemeRoot | null = defaultRoot(),
): void {
  if (!root) return
  if (choice === null) root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
}

/** 선택을 저장하고 즉시 반영한다. 저장에 실패해도 이번 세션에는 적용한다. */
export function setTheme(
  choice: ThemeChoice,
  storage: ThemeStorage | null = defaultStorage(),
  root: ThemeRoot | null = defaultRoot(),
): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, choice)
  } catch {
    // 저장 실패는 무시한다 — 화면 적용이 더 중요하다.
  }
  applyTheme(choice, root)
  notify()
}

// ── 구독자 관리 (React 훅이 쓴다) ──────────────────────────────────────────

const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

/**
 * `useSyncExternalStore`용 구독. OS 변경과 명시적 선택 둘 다 알린다.
 *
 * **명시적 선택이 있으면 OS 변경을 무시한다** — 사용자가 다크를 골라 뒀는데 OS가
 * 라이트로 바뀌었다고 화면이 따라가면 선택이 무의미해진다.
 */
export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener)

  let detach = () => {}
  if (typeof window !== 'undefined' && window.matchMedia) {
    const media = window.matchMedia(DARK_QUERY)
    const handler = () => {
      if (getStoredChoice() === null) notify()
    }
    media.addEventListener('change', handler)
    detach = () => media.removeEventListener('change', handler)
  }

  return () => {
    listeners.delete(listener)
    detach()
  }
}
