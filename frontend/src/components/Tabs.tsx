import { useCallback, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import './Tabs.css'

/**
 * 탭 — `DESIGN_SYSTEM §8` 「탭」 (#1772 · #1774).
 *
 * ## 낭독 배선을 부품이 강제한다
 *
 * `§8`이 「호출부마다 적게 두면 빠진 자리가 생기고, 그 자리는 화면이 깨지지 않아
 * 발견되지 않는다」로 정했다 — `§8.4`가 `Field`로 닫은 것과 같은 이유다. 그래서
 * `role`·`aria-selected`·`aria-controls`·화살표·`Home`/`End`·roving tabindex를 **여기서**
 * 배선하고, 호출부는 **무엇이 있는지와 지금 어느 것인지**만 넘긴다.
 *
 * ## 한 번 연 탭은 감추되 지우지 않는다
 *
 * `render`는 **그 탭을 처음 열 때** 불린다 — 열기 전에는 마운트하지 않으므로 그 탭의
 * 조회도 나가지 않는다. 한 번 연 뒤에는 `hidden`으로 감출 뿐이라, 쓰다 만 입력이 탭을
 * 오가며 날아가지 않는다(`§8`).
 *
 * ## 자리는 주소가 갖는다
 *
 * 이 부품은 **자리를 갖지 않는다** — `current`를 받고 `onSelect`로 알릴 뿐이다.
 * 주소에 적는 일은 화면이 한다(`§8` 「자리는 주소가 갖는다」).
 */
export type TabDef = {
  id: string
  label: string
  /** 그 탭을 처음 열 때 부른다. */
  render: () => ReactNode
}

export function Tabs({
  label,
  items,
  current,
  onSelect,
}: {
  /** 탭 줄의 낭독 이름 — 무엇을 가르는 탭인지. */
  label: string
  items: readonly TabDef[]
  current: string
  onSelect: (id: string) => void
}) {
  const base = useId()
  const tabId = (id: string) => `${base}-tab-${id}`
  const panelId = (id: string) => `${base}-panel-${id}`

  /*
   * 한 번 연 탭의 목록. 초깃값에 `current`가 들어 있어 **첫 화면의 탭은 바로 마운트**된다.
   *
   * 주소가 밖에서 바뀌어(뒤로 가기) 아직 기록되지 않은 탭이 `current`가 되면, 아래
   * `mounted`가 그 탭을 그 렌더에서 함께 그린다 — 기록은 누른 순간에만 남긴다.
   */
  const [opened, setOpened] = useState<readonly string[]>(() => [current])
  const mounted = opened.includes(current) ? opened : [...opened, current]

  const select = useCallback(
    (id: string) => {
      setOpened((prev) => (prev.includes(id) ? prev : [...prev, id]))
      onSelect(id)
    },
    [onSelect],
  )

  const buttons = useRef<Record<string, HTMLButtonElement | null>>({})

  /*
   * 좌우 화살표는 **초점과 선택을 함께** 옮긴다(자동 활성화). 패널이 마운트된 채로 남아
   * 있어 탭을 넘기는 비용이 없으므로, 「초점만 옮기고 스페이스로 고르는」 수동 활성화를
   * 쓸 이유가 없다 — 한 번 더 누르게 할 뿐이다.
   */
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = items.findIndex((item) => item.id === current)
    if (index < 0) return
    let next: number
    if (event.key === 'ArrowRight') next = (index + 1) % items.length
    else if (event.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = items.length - 1
    else return

    event.preventDefault()
    const target = items[next]
    select(target.id)
    buttons.current[target.id]?.focus()
  }

  return (
    <div className="tabs">
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role */}
      <div className="tabs__list" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
        {items.map((item) => {
          const on = item.id === current
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={tabId(item.id)}
              className={`tabs__tab${on ? ' tabs__tab--on' : ''}`}
              aria-selected={on}
              aria-controls={panelId(item.id)}
              /* roving tabindex — 탭 줄에는 Tab 키로 한 번만 들어온다. */
              tabIndex={on ? 0 : -1}
              ref={(element) => {
                buttons.current[item.id] = element
              }}
              onClick={() => select(item.id)}
            >
              {item.label}
            </button>
          )
        })}
      </div>

      {items
        .filter((item) => mounted.includes(item.id))
        .map((item) => (
          <div
            key={item.id}
            role="tabpanel"
            id={panelId(item.id)}
            aria-labelledby={tabId(item.id)}
            className="tabs__panel"
            hidden={item.id !== current}
          >
            {item.render()}
          </div>
        ))}
    </div>
  )
}
