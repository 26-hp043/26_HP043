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
 * 부수효과는 둘이다: `<html lang>` 갱신(WCAG 3.1.1 — 스크린 리더가 언어를 알아야
 * 발음 엔진을 고른다)과 `localStorage` 저장(새로고침·재방문에도 선택이 남는다).
 * 둘 다 언어가 바뀔 때만 돈다.
 */
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(i18nInternals.readStoredLanguage)

  useEffect(() => {
    document.documentElement.lang = language
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
