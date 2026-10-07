// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  closeIntroHint,
  dismissIntroHint,
  INTRO_HINT_CLOSED_KEY,
  INTRO_HINT_DISMISSED_KEY,
  shouldShowIntroHint,
} from './introHint'

describe('범이 첫 방문 안내 — 띄울지 (#2205)', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('처음에는 띄운다', () => {
    expect(shouldShowIntroHint()).toBe(true)
  })

  it('「닫기」는 이 탭(sessionStorage)에만 기억한다', () => {
    closeIntroHint()
    expect(shouldShowIntroHint()).toBe(false)
    expect(window.sessionStorage.getItem(INTRO_HINT_CLOSED_KEY)).toBe('true')
    expect(window.localStorage.getItem(INTRO_HINT_DISMISSED_KEY)).toBeNull()

    // 새 탭 — 탭 저장소가 비면 다시 뜬다
    window.sessionStorage.clear()
    expect(shouldShowIntroHint()).toBe(true)
  })

  it('「다시 보지 않기」는 이 브라우저(localStorage)에 기억한다', () => {
    dismissIntroHint()
    window.sessionStorage.clear()
    expect(shouldShowIntroHint()).toBe(false)
  })

  it('저장소를 읽지 못하면 띄운다 — 못 본 안내는 되돌릴 수 없다', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(shouldShowIntroHint()).toBe(true)
  })

  it('저장소에 쓰지 못해도 던지지 않는다', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => dismissIntroHint()).not.toThrow()
    expect(() => closeIntroHint()).not.toThrow()
  })
})
