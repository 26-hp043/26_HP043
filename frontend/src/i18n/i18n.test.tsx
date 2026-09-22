// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { interpolate, useI18n } from './core'
import { LanguageProvider } from './Provider'
import { LanguageToggle } from './LanguageToggle'
import { ThemeToggle } from '../theme/ThemeToggle'
import { ko } from './ko'
import { en } from './en'

/**
 * i18n 기반 동작 검증 (#1215).
 *
 * ## 이 파일이 보는 것
 *
 * ⑴ **사전 완전성** — `en`이 `ko`의 키를 하나도 빠뜨리지 않는가. 타입
 * (`Record<MessageKey, string>`)이 컴파일 시점을 보지만, 사전을 `satisfies` 없이
 * 확장하는 경로까지 잡으려면 런타임 대조가 필요하다.
 * ⑵ **기본은 한국어** — 저장값이 없으면 `ko`. 기존 화면·테스트 전체가 이 경로다.
 * ⑶ **전환·지속화·`<html lang>`** — 언어는 WCAG 3.1.1(페이지 언어)의 축이다.
 * 바꾸면 문서 언어도 따라가야 스크린 리더가 발음 엔진을 갈아 낸다.
 */

function Probe() {
  const { language, setLanguage, t } = useI18n()
  return (
    <div>
      <output data-testid="probe-lang">{language}</output>
      <output data-testid="probe-text">{t('shell.vessel')}</output>
      <button type="button" onClick={() => setLanguage('en')}>
        to-en
      </button>
    </div>
  )
}

function setup() {
  return render(
    <LanguageProvider>
      <Probe />
    </LanguageProvider>,
  )
}

afterEach(() => {
  window.localStorage.clear()
  document.documentElement.lang = 'ko'
})

describe('사전 완전성', () => {
  it('en이 ko의 키를 전부 갖는다 — 하나라도 어긋나면 사전이 잘렸다', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ko).sort())
  })

  it('치환자 {name}을 채우고, 파라미터가 없는 치환자는 그대로 둔다', () => {
    expect(interpolate('{a}와 {b}', { a: '1', b: '2' })).toBe('1와 2')
    expect(interpolate('{a}', {})).toBe('{a}')
    expect(interpolate('파라미터 없음')).toBe('파라미터 없음')
  })
})

describe('기본 언어', () => {
  it('저장값이 없으면 한국어다 — 기존 경로가 그대로다', () => {
    const { getByTestId } = setup()
    expect(getByTestId('probe-lang').textContent).toBe('ko')
    expect(getByTestId('probe-text').textContent).toBe('선박')
  })

  it('모르는 저장값은 한국어로 돌아간다', () => {
    window.localStorage.setItem('bluelog.lang', 'jp')
    const { getByTestId } = setup()
    expect(getByTestId('probe-lang').textContent).toBe('ko')
  })

  it('저장된 en을 복원한다', () => {
    window.localStorage.setItem('bluelog.lang', 'en')
    const { getByTestId } = setup()
    expect(getByTestId('probe-lang').textContent).toBe('en')
    expect(getByTestId('probe-text').textContent).toBe('Vessel')
  })
})

describe('전환', () => {
  it('바꾸면 문구가 바뀌고 <html lang>과 저장값이 따라간다', () => {
    const { getByTestId } = setup()
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'to-en' }))
    })
    expect(getByTestId('probe-lang').textContent).toBe('en')
    expect(getByTestId('probe-text').textContent).toBe('Vessel')
    expect(document.documentElement.lang).toBe('en')
    expect(window.localStorage.getItem('bluelog.lang')).toBe('en')
  })
})

describe('LanguageToggle', () => {
  it('두 칸이고 현재 언어가 선택으로 보인다 — 눌러 전환한다', () => {
    render(
      <LanguageProvider>
        <LanguageToggle />
      </LanguageProvider>,
    )
    const group = screen.getByRole('radiogroup', { name: '언어' })
    expect(group).toBeTruthy()
    const korean = screen.getByRole('radio', { name: '한국어' })
    const english = screen.getByRole('radio', { name: '영어' })
    expect(korean.getAttribute('aria-checked')).toBe('true')
    expect(english.getAttribute('aria-checked')).toBe('false')

    act(() => {
      fireEvent.click(english)
    })
    expect(english.getAttribute('aria-checked')).toBe('true')
    expect(window.localStorage.getItem('bluelog.lang')).toBe('en')
  })
})

describe('ThemeToggle — 낭독 이름이 현재 언어를 따른다 (#1525)', () => {
  it('영어 모드에서 테마 칸이 영어로 읽힌다 — 종전에는 한국어 리터럴이었다', () => {
    window.localStorage.setItem('bluelog.lang', 'en')
    render(
      <LanguageProvider>
        <ThemeToggle />
      </LanguageProvider>,
    )
    expect(screen.getByRole('radiogroup', { name: en['theme.groupLabel'] })).toBeTruthy()
    expect(screen.getByRole('radio', { name: en['theme.light'] })).toBeTruthy()
    expect(screen.getByRole('radio', { name: en['theme.dark'] })).toBeTruthy()
    // 한국어 이름이 남아 있지 않다.
    expect(screen.queryByRole('radiogroup', { name: ko['theme.groupLabel'] })).toBeNull()
  })
})
