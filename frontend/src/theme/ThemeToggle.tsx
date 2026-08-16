import { useSyncExternalStore } from 'react'
import {
  getEffectiveTheme,
  setTheme,
  subscribeTheme,
  type ThemeChoice,
} from './theme'
import './ThemeToggle.css'

/**
 * 라이트·다크 선택 — 해 / 달 두 칸짜리 세그먼트 컨트롤.
 *
 * ## 왜 토글 버튼 하나가 아니라 두 칸인가
 *
 * 버튼 하나로 번갈아 바꾸면 **지금 어느 쪽인지**와 **누르면 어디로 가는지**가
 * 아이콘 하나에 겹쳐 담긴다(해가 보이면 지금이 라이트인가, 누르면 라이트가 되는가).
 * 두 칸으로 나누면 선택 상태가 그대로 보인다.
 *
 * ## 접근성
 *
 * `radiogroup`으로 노출한다 — 상호배타 선택이라 툴바 버튼보다 의미가 맞는다.
 * 아이콘만 있으므로 각 칸에 `aria-label`을 붙이고, SVG는 `aria-hidden`으로 감춘다.
 */
export function ThemeToggle() {
  // 서버 스냅샷(3번째 인자)은 `light` — SSR을 쓰지 않지만 vitest 환경에서
  // matchMedia가 없을 때의 초기값과 일치시켜 깜빡임 경고를 피한다.
  const theme = useSyncExternalStore<ThemeChoice>(
    subscribeTheme,
    getEffectiveTheme,
    () => 'light',
  )

  return (
    <div className="theme-toggle" role="radiogroup" aria-label="화면 테마">
      <Option current={theme} value="light" label="밝은 화면" />
      <Option current={theme} value="dark" label="어두운 화면" />
    </div>
  )
}

function Option({
  current,
  value,
  label,
}: {
  current: ThemeChoice
  value: ThemeChoice
  label: string
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
        selected ? 'theme-toggle__option theme-toggle__option--on' : 'theme-toggle__option'
      }
      onClick={() => setTheme(value)}
      data-testid={`theme-${value}`}
    >
      {value === 'light' ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}

/*
 * 아이콘은 인라인 SVG다. 아이콘 폰트·외부 스프라이트를 쓰지 않는 이유는
 * 오프라인 시연에서 네트워크에 의존하지 않기 위해서다.
 * 획 두께는 `--icon-stroke`(디자이너 토큰 1.5px)를 따른다.
 */

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.6v2.2M12 19.2v2.2M21.4 12h-2.2M4.8 12H2.6M18.6 5.4l-1.6 1.6M7 17l-1.6 1.6M18.6 18.6L17 17M7 7L5.4 5.4" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {/* 초승달 — 획만 두면 얇은 실선으로 보여 채운다(CSS `.moon-fill`). */}
      <path
        className="moon-fill"
        d="M20.2 14.4A8.6 8.6 0 0 1 9.6 3.8a8.6 8.6 0 1 0 10.6 10.6z"
      />
    </svg>
  )
}
