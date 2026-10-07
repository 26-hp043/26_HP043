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
  it('바꾸면 문구와 저장값이 따라간다', () => {
    const { getByTestId } = setup()
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'to-en' }))
    })
    expect(getByTestId('probe-lang').textContent).toBe('en')
    expect(getByTestId('probe-text').textContent).toBe('Vessel')
    expect(window.localStorage.getItem('bluelog.lang')).toBe('en')
  })
})

/**
 * 문서 언어 경계 (`#1652`).
 *
 * 종전 단언은 「루트가 `en`이 된다」였다. 그런데 영문 모드에서 영어로 바뀌는 것은
 * 셸 문자열뿐이고 화면 본문·면책·선박명은 한국어로 남으므로, 루트를 `en`으로
 * 돌리면 **그 한국어 전부가 영어라고 표시된다.** 루트는 `ko`로 두고 바뀌는 쪽에
 * `lang="en"`을 붙이는 것으로 뒤집었다 — 이 describe가 그 두 축을 함께 본다.
 *
 * 정본 인용이 붙지 않은 표시 성질 검사이므로 `AGENTS §4.6`상 정본 개정 없이
 * 바꿀 수 있는 단언이다. `PRD.md:571`도 「셸 문자열의 영문 전환」이라 적을 뿐
 * 루트 `lang`을 말하지 않는다.
 */
describe('문서 언어 경계 (#1652)', () => {
  function toggles() {
    return render(
      <LanguageProvider>
        <LanguageToggle />
        <ThemeToggle />
        <Probe />
      </LanguageProvider>,
    )
  }

  const toEn = () =>
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'to-en' }))
    })

  it('영문으로 바꿔도 문서 루트는 ko다 — 한국어 본문이 영어로 표시되지 않게', () => {
    const { getByTestId } = setup()
    expect(document.documentElement.lang).toBe('ko')

    toEn()

    expect(getByTestId('probe-lang').textContent).toBe('en')
    expect(document.documentElement.lang).toBe('ko')
  })

  it('영문으로 바뀌는 셸 문자열에 lang="en"이 붙는다', () => {
    toggles()
    toEn()

    expect(screen.getByRole('radiogroup', { name: 'Language' }).getAttribute('lang')).toBe(
      'en',
    )
    expect(screen.getByRole('radio', { name: 'English' }).getAttribute('lang')).toBe('en')
    expect(screen.getByRole('radiogroup', { name: 'Theme' }).getAttribute('lang')).toBe('en')
    expect(screen.getByTestId('theme-dark').getAttribute('lang')).toBe('en')
  })

  it('한국어 모드에서는 lang을 붙이지 않는다 — 루트에서 상속받는다', () => {
    toggles()

    expect(screen.getByRole('radiogroup', { name: '언어' }).getAttribute('lang')).toBeNull()
    expect(screen.getByRole('radio', { name: '한국어' }).getAttribute('lang')).toBeNull()
    expect(screen.getByTestId('theme-dark').getAttribute('lang')).toBeNull()
  })

  it('언어 칸의 「한」은 영문 모드에서도 ko로 남는다', () => {
    toggles()
    toEn()

    const korean = screen.getByRole('radio', { name: 'Korean' })
    expect(korean.getAttribute('lang')).toBe('en')
    // 버튼의 이름(`aria-label`)은 영어지만 칸에 적힌 글자는 한국어 그대로다.
    expect(korean.querySelector('.language-toggle__glyph')?.getAttribute('lang')).toBe('ko')
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

/*
 * `radiogroup`이면 **화살표로 옮겨진다** (#2128 ⑶).
 *
 * 역할을 선언하면 낭독기는 「라디오 그룹, 2개 중 1번째」라고 읽고 사용자는 화살표를
 * 누른다. 종전에는 `onKeyDown`이 없어 아무 일도 일어나지 않았고, 두 칸이 **모두 Tab
 * 순서에** 있었다. 선택된 칸만 Tab을 받고 화살표가 선택과 초점을 함께 옮긴다.
 */
describe('두 칸 토글의 키보드 조작 (#2128)', () => {
  const radios = (group: HTMLElement) => [...group.querySelectorAll<HTMLElement>('[role="radio"]')]
  const checked = (group: HTMLElement) =>
    radios(group).find((radio) => radio.getAttribute('aria-checked') === 'true')!

  function exercise(group: HTMLElement) {
    // Tab이 닿는 칸은 선택된 칸 하나다.
    expect(radios(group).filter((radio) => radio.tabIndex === 0)).toEqual([checked(group)])

    const start = checked(group)
    start.focus()
    for (const key of ['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp']) {
      const before = checked(group)
      act(() => {
        fireEvent.keyDown(document.activeElement!, { key })
      })
      const after = checked(group)
      expect(after, `${key}가 선택을 옮기지 않았다`).not.toBe(before)
      expect(document.activeElement, `${key} 뒤 초점이 선택을 따라가지 않았다`).toBe(after)
      expect(radios(group).filter((radio) => radio.tabIndex === 0)).toEqual([after])
    }
    // 네 번 옮겼으니 제자리다 — 두 칸에서 양쪽 끝이 서로 이어진다.
    expect(checked(group)).toBe(start)
  }

  it('언어 토글 — 화살표가 선택과 초점을 함께 옮긴다', () => {
    render(
      <LanguageProvider>
        <LanguageToggle />
      </LanguageProvider>,
    )
    exercise(screen.getByRole('radiogroup'))
  })

  it('테마 토글 — 화살표가 선택과 초점을 함께 옮긴다', () => {
    render(
      <LanguageProvider>
        <ThemeToggle />
      </LanguageProvider>,
    )
    exercise(screen.getByRole('radiogroup'))
  })

  it('화살표가 아닌 키는 선택을 건드리지 않는다', () => {
    render(
      <LanguageProvider>
        <LanguageToggle />
      </LanguageProvider>,
    )
    const group = screen.getByRole('radiogroup')
    const before = checked(group)
    before.focus()
    act(() => {
      fireEvent.keyDown(before, { key: 'a' })
    })
    expect(checked(group)).toBe(before)
    expect(document.activeElement).toBe(before)
  })
})
