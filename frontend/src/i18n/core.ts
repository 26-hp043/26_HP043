import { createContext, useContext } from 'react'
import { ko, type MessageKey } from './ko'
import { en } from './en'

/**
 * 화면 문구 i18n — 사전·훅 (새 의존성 없는 자체 구현, #1215).
 *
 * ## 왜 라이브러리가 아니라 여기 있는가
 *
 * 필요한 것은 **사전 조회·치환·지속화** 셋뿐이다. `react-i18next`는 복수형·
 * 네임스페이스·지연 로딩까지 가져오는데, 이 제품은 한국어·영문 두 사전이 전부고
 * 번들은 로컬 파일 하나로 항상 함께 간다. 의존성 하나를 더 지키는 비용이 얻는
 * 것보다 크다 — 필요해지는 날(제3언어·복수형) 그때 옮긴다.
 *
 * ## 기본은 한국어다
 *
 * 전환은 **선택**이다. 저장값이 없으면 `ko` — 기존 화면·테스트가 전부 이 경로다.
 * 키가 사전에 없으면 `ko` 원문으로 돌아간다(fallback). 영문 사전이 키를
 * 빠뜨려도 화면이 빈 칸으로 깨지지 않게 하는 마지막 안전선이다.
 *
 * ## 정본 문구는 다루지 않는다
 *
 * 면책(`PRD §6.3`) · 상태 문구(`PRD §6.4`) · 경고 코드(`API_SPEC §1.6`) 체인은
 * 이 모듈 밖에 있다 — 어느 언어에서도 한국어 원문으로 렌더된다(`ko.ts` 주석 참조).
 *
 * ## 컴포넌트는 별도 파일이다
 *
 * 이 파일엔 컴포넌트가 없다 — `Provider.tsx`의 fast-refresh 규칙(파일이 컴포넌트만
 * export해야 개발 서버가 상태를 지키고 다시 그린다)과 사전·훅을 한 파일에 두면
 * 어긋난다. 그래서 나눴다.
 */

export type Language = 'ko' | 'en'

export const LANGUAGES: readonly Language[] = ['ko', 'en']

const DEFAULT_LANGUAGE: Language = 'ko'

const STORAGE_KEY = 'bluelog.lang'

const DICTIONARIES: Record<Language, Record<MessageKey, string>> = { ko, en }

/** 저장된 언어 — 없거나 모르는 값이면 기본(`ko`). */
function readStoredLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return stored === 'en' ? 'en' : 'ko'
  } catch {
    // localStorage 접근이 막히는 환경(일부 테스트·프라이버시 모드)에서는 기본값으로
    // 돌아간다. 언어 선택은 복구 가능한 편의 기능이다.
    return 'ko'
  }
}

function persistLanguage(language: Language): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // 저장 실패는 세션 안에서만 유효한 선택이 되게 둔다.
  }
}

/** `{name}` 모양의 치환자를 채운다. 파라미터가 없는 키는 원문 그대로. */
export function interpolate(template: string, params?: Record<string, string>): string {
  if (params === undefined) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.hasOwn(params, name) ? params[name] : match,
  )
}

export type I18nContextValue = {
  language: Language
  setLanguage: (language: Language) => void
  t: (key: MessageKey, params?: Record<string, string>) => string
}

export const LanguageContext = createContext<I18nContextValue | null>(null)

/** 셸 어디서나 — provider 없이 쓰면 기본(ko) 사전으로 동작한다(테스트 편의). */
export function useI18n(): I18nContextValue {
  const context = useContext(LanguageContext)
  if (context !== null) return context
  return {
    language: DEFAULT_LANGUAGE,
    setLanguage: () => undefined,
    t: (key, params) => interpolate(ko[key], params),
  }
}

/** provider 내부용 — 상태 초기화·부수효과의 단일 출처. */
export const i18nInternals = { readStoredLanguage, persistLanguage, DICTIONARIES, DEFAULT_LANGUAGE }
