// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { currentScreenResult, publishScreenResult, resetScreenResult } from './screenResult'

/** 화면이 낸 결과를 챗봇에 넘기는 자리 (`#1533`). */
describe('screenResult', () => {
  afterEach(() => {
    resetScreenResult()
    window.history.pushState({}, '', '/')
  })

  it('낸 화면에서는 그 실행 id를 준다', () => {
    window.history.pushState({}, '', '/voyage-cii')
    publishScreenResult('run-1')
    expect(currentScreenResult()).toBe('run-1')
  })

  it('다른 화면으로 옮기면 넘기지 않는다 — 떠난 화면의 결과로 답하지 않는다', () => {
    window.history.pushState({}, '', '/voyage-cii')
    publishScreenResult('run-1')
    window.history.pushState({}, '', '/dashboard')
    expect(currentScreenResult()).toBeUndefined()
  })

  it('새 결과가 앞 결과를 대신하고, 빈 id는 지운다', () => {
    window.history.pushState({}, '', '/scenarios')
    publishScreenResult('run-1')
    publishScreenResult('run-2')
    expect(currentScreenResult()).toBe('run-2')
    publishScreenResult(undefined)
    expect(currentScreenResult()).toBeUndefined()
  })
})
