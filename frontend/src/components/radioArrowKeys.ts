import type { KeyboardEvent } from 'react'

/**
 * `radiogroup`의 화살표 이동 (#2128) — 그 역할을 선언한 값이다.
 *
 * 역할을 듣고 화살표를 누르는 사람에게 종전에는 아무 일도 일어나지 않았다. 좌우·상하
 * 화살표가 **선택과 초점을 함께** 옮기고 양 끝은 서로 이어진다. 선택은 그 칸의 `click`에
 * 맡긴다 — 누르는 경로와 화살표 경로가 같은 한 곳을 지난다.
 *
 * 묶음(`role="radiogroup"`)의 `onKeyDown`에 건다. 칸은 `role="radio"`이고 **선택된 칸만**
 * `tabIndex={0}`이어야 한다 — 나머지는 이 화살표로 닿는다. 쓰는 곳은 `ThemeToggle` ·
 * `LanguageToggle` 둘이다.
 */
export function moveRadioByArrow(event: KeyboardEvent<HTMLElement>) {
  const step =
    event.key === 'ArrowRight' || event.key === 'ArrowDown'
      ? 1
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
        ? -1
        : 0
  if (step === 0) return
  const radios = [...event.currentTarget.querySelectorAll<HTMLElement>('[role="radio"]')]
  const from = radios.findIndex((radio) => radio === event.target)
  if (from < 0) return
  // 화살표가 페이지를 굴리지 않게 한다.
  event.preventDefault()
  const next = radios[(from + step + radios.length) % radios.length]
  next.focus()
  next.click()
}
