// @vitest-environment jsdom
import '../test/renderSetup'

import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { LanguageProvider } from './Provider'
import { useI18n } from './core'
import { Field } from '../components/Field'
import { PageHeader } from '../components/PageHeader'
import { SCREEN_BY_ID } from '../screens'

/**
 * 영문 보조 라벨은 한국어 모드에서 그리지 않는다 (`#1426`).
 *
 * ## 무엇이 문제였나
 *
 * `DESIGN_SYSTEM §3` 🔒과 `PRD §4`는 「한국어 기본 + **영문 약어** 병기」다. 그런데
 * 화면에 붙어 있던 영문은 `Dashboard` · `Distance` · `Vessel Name`처럼 **약어가 아닌
 * 일반 단어** 47곳이었다 — 정본이 허용한 적 없는 표기다. `#1215`가 한/EN 토글을
 * 만든 뒤로는 같은 말을 두 언어로 동시에 적을 이유도 사라졌다.
 *
 * ## 두 갈래로 나뉜다
 *
 * ⑴ **화면 이름** — 데이터에 영어 이름(`labelEn`)이 따로 있으므로 **언어에 맞는
 *    이름 하나**를 고른다. 종전에는 언어와 무관하게 한국어가 주 제목이라 영어
 *    모드에서도 제목만 한국어로 남아 있었다 — 토글이 닿지 않는 자리였다.
 * ⑵ **폼·섹션 라벨** — 한국어가 하드코딩이라 번역 대상이 아니다. 한국어 모드에서는
 *    지우되 **영어 모드에서는 남긴다** — 그 영문이 영어 사용자에게 가는 유일한
 *    영어다.
 *
 * 지우는 것이 아니라 **조건부로 그리는 것**이므로, 영어 모드가 여전히 영어로
 * 나오는지를 함께 본다. 그러지 않으면 이 변경이 토글을 조용히 망가뜨린다.
 */

function ToEn() {
  const { setLanguage } = useI18n()
  return (
    <button type="button" onClick={() => setLanguage('en')}>
      to-en
    </button>
  )
}

function renderWith(children: React.ReactNode) {
  return render(
    <LanguageProvider>
      <MemoryRouter>
        {children}
        <ToEn />
      </MemoryRouter>
    </LanguageProvider>,
  )
}

const toEn = () => fireEvent.click(screen.getByRole('button', { name: 'to-en' }))

afterEach(() => {
  window.localStorage.clear()
  document.documentElement.lang = 'ko'
})

describe('폼 라벨의 영문 보조 (#1426)', () => {
  function field() {
    return (
      <Field id="distance" label="항해거리" labelEn="Distance">
        {(control) => <input {...control} />}
      </Field>
    )
  }

  it('한국어 모드에서는 영문이 붙지 않는다', () => {
    renderWith(field())

    expect(screen.getByText('항해거리')).toBeTruthy()
    expect(screen.queryByText('Distance')).toBeNull()
  })

  it('영어 모드에서는 영문이 남는다 — 토글이 망가지지 않았다', () => {
    renderWith(field())

    toEn()

    expect(screen.getByText('Distance')).toBeTruthy()
    // 한국어 라벨은 하드코딩이라 그대로다 — 그래서 영문 보조가 필요하다.
    expect(screen.getByText('항해거리')).toBeTruthy()
  })

  it('영문 보조에는 lang 속성이 붙는다 — 낭독 엔진이 한국어로 읽지 않게', () => {
    renderWith(field())
    toEn()

    expect(screen.getByText('Distance').getAttribute('lang')).toBe('en')
  })
})

describe('화면 이름은 언어에 맞는 것 하나만 (#1426)', () => {
  const meta = SCREEN_BY_ID.MAINBOARD

  it('한국어 모드에서는 한국어 이름만 나온다', () => {
    renderWith(<PageHeader screen="MAINBOARD" />)

    const title = screen.getByRole('heading', { level: 1 })
    expect(title.textContent).toBe(meta.label)
    expect(title.textContent).not.toContain(meta.labelEn)
  })

  it('영어 모드에서는 영어 이름 하나로 바뀐다 — 종전에는 제목만 한국어로 남았다', () => {
    renderWith(<PageHeader screen="MAINBOARD" />)

    toEn()

    const title = screen.getByRole('heading', { level: 1 })
    expect(title.textContent).toBe(meta.labelEn)
    expect(title.textContent).not.toContain(meta.label)
  })

  it('영어 이름에는 lang="en"이 붙고 한국어 이름에는 붙지 않는다 (#1652)', () => {
    renderWith(<PageHeader screen="MAINBOARD" />)

    expect(screen.getByRole('heading', { level: 1 }).getAttribute('lang')).toBeNull()

    toEn()

    expect(screen.getByRole('heading', { level: 1 }).getAttribute('lang')).toBe('en')
  })
})
