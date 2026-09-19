import { LANGUAGES, useI18n, type Language } from './core'
import './LanguageToggle.css'

/**
 * 언어 선택 — 한/EN 두 칸짜리 세그먼트 (#1215).
 *
 * `ThemeToggle`과 같은 모양·같은 접근성 규약(`radiogroup`)을 쓴다. 이유도 같다 —
 * 버튼 하나로 번갈아 바꾸면 **지금 어느 쪽인지**와 **누르면 어디로 가는지**가
 * 한 칸에 겹쳐 담긴다. 두 칸으로 나누면 선택 상태가 그대로 보인다.
 *
 * 칸에 적는 글자는 **그 언어의 이름 그 자체**(한국어는 「한」, 영문은 「EN」)다.
 * 번역하지 않는다 — 자기 이름을 모국어로 적는 것이 언어 선택 칸의 관례이고,
 * 현재 언어를 몰라도 원하는 쪽을 찾을 수 있어야 한다.
 *
 * `aria-label`은 현재 언어로 붙인다 — 안내 문구는 쓰는 사람의 언어로 읽혀야
 * 한다(`DESIGN_SYSTEM §14` 정신). 언어 이름 자체는 위 규칙을 따른다.
 */
export function LanguageToggle() {
  const { language, setLanguage, t } = useI18n()

  return (
    <div className="language-toggle" role="radiogroup" aria-label={t('i18n.groupLabel')}>
      {LANGUAGES.map((candidate) => (
        <Option
          key={candidate}
          current={language}
          value={candidate}
          label={candidate === 'ko' ? t('i18n.korean') : t('i18n.english')}
          text={candidate === 'ko' ? '한' : 'EN'}
          onSelect={setLanguage}
        />
      ))}
    </div>
  )
}

function Option({
  current,
  value,
  label,
  text,
  onSelect,
}: {
  current: Language
  value: Language
  label: string
  text: string
  onSelect: (language: Language) => void
}) {
  const selected = current === value
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={label}
      title={label}
      className={
        selected
          ? 'language-toggle__option language-toggle__option--on'
          : 'language-toggle__option'
      }
      onClick={() => onSelect(value)}
    >
      <span className="language-toggle__glyph" aria-hidden="true">
        {text}
      </span>
    </button>
  )
}
