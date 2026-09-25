// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useReducedMotion } from './useReducedMotion'

afterEach(() => vi.unstubAllGlobals())

it('초기 설정과 실행 중 변경을 반영하고 listener를 해제한다', () => {
  let listener: (() => void) | undefined
  const media = { matches: false, addEventListener: vi.fn((_type, next) => { listener = next }), removeEventListener: vi.fn() }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
  const view = renderHook(() => useReducedMotion())
  expect(view.result.current).toBe(false)
  media.matches = true
  act(() => listener?.())
  expect(view.result.current).toBe(true)
  view.unmount()
  expect(media.removeEventListener).toHaveBeenCalledWith('change', listener)
})
