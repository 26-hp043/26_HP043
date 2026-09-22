import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ko } from './ko'
import {
  i18nInternals,
  interpolate,
  LanguageContext,
  type I18nContextValue,
  type Language,
} from './core'

/**
 * 언어 provider (#1215) — 이 파일은 **컴포넌트만 export**한다(fast-refresh).
 *
 * 부수효과는 둘이다: `<html lang>` 고정과 `localStorage` 저장(새로고침·재방문에도
 * 선택이 남는다).
 *
 * ## 루트 `lang`은 토글을 따라가지 않는다 (`#1652`)
 *
 * 종전에는 `document.documentElement.lang = language`였다. 그런데 영문 모드에서
 * 영어로 바뀌는 것은 이 사전이 덮는 **셸 문자열뿐**이고, 화면 본문·면책
 * (`PRD §6.3`)·경고(`API_SPEC §1.6`)·선박명은 그대로 한국어다. 루트가 `en`이면
 * **그 한국어 전부가 영어라고 표시되어** 스크린 리더가 영어 발음 엔진으로 읽는다
 * (WCAG 3.1.1 — 페이지 언어는 실제 언어여야 한다).
 *
 * 그래서 루트는 `index.html`과 같은 `ko`로 두고, **영어로 바뀌는 자리**에만
 * `lang="en"`을 붙인다(`useTextLang()` · WCAG 3.1.2 부분 언어).
 */
/** 문서 루트의 언어 — `index.html`의 `<html lang="ko">`와 같은 값이다. */
const DOCUMENT_LANGUAGE = 'ko'

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(i18nInternals.readStoredLanguage)

  useEffect(() => {
    // 루트는 언어 선택과 무관하게 `ko`다 — 위 주석 참조. jsdom은 기본값이 빈
    // 문자열이라 여기서 적어 두어야 `index.html`과 같은 상태에서 검사된다.
    document.documentElement.lang = DOCUMENT_LANGUAGE
    i18nInternals.persistLanguage(language)
  }, [language])

  const value = useMemo<I18nContextValue>(
    () => ({
      language,
      setLanguage,
      t: (key, params) =>
        interpolate(i18nInternals.DICTIONARIES[language][key] ?? ko[key], params),
    }),
    [language],
  )

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}
