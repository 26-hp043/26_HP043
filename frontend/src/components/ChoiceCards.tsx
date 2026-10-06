import { useId, type ReactNode } from 'react'
import './ChoiceCards.css'

/**
 * 선택 카드 (#2201) — 선택지가 적은 배타 선택을 「이름 + 한 줄 풀이」 카드로 보인다.
 *
 * ## 언제 쓰나 (`DESIGN_SYSTEM §8.4`)
 *
 * 선택지가 **5개 이하**이고 선택지마다 **풀이 한 줄**이 있을 때만. 셀렉트는 열어 보기 전에는
 * 무엇을 고를 수 있는지 보이지 않고, 맨 라디오는 이름만 있어 각 선택지가 무슨 뜻인지
 * 말하지 않는다. 그 밖(선택지가 많거나 풀이가 없음)에는 셀렉트를 그대로 쓴다.
 *
 * ## 라디오를 지우지 않는다
 *
 * 카드는 **진짜 `<input type="radio">`를 품은 `<label>`**이다. 그래서 키보드(Tab으로 그룹에
 * 들어가 화살표로 옮기고 Space로 고르기)와 낭독(「라디오 단추, 3개 중 2번째」)이 브라우저
 * 기본 동작 그대로다 — 자바스크립트로 다시 짜지 않는다.
 *
 * - **이름은 선택지 이름만이다** — 라디오의 접근 이름을 `aria-labelledby`로 이름 줄에만
 *   묶는다. 풀이까지 이름에 들어가면 「총량 항차 전체에 쓴 연료를…」이 이름이 되어
 *   낭독이 길어지고, 기존 검사(`getByLabelText('총량')`)도 맞지 않는다.
 * - **풀이는 설명이다** — `aria-describedby`로 잇는다. 고를 수 없는 사유가 있으면 그 id를
 *   뒤에 붙인다(`DESIGN_SYSTEM §14` 「비활성의 사유」).
 * - **고른 표시는 채널 둘이다** — 라디오의 점(모양) + 카드 테두리 · 배경(색). 색만으로
 *   고른 것을 말하지 않는다(`§14` 색 단독 금지).
 */
export interface ChoiceOption<T extends string> {
  readonly value: T
  readonly label: string
  /** 한 줄 풀이. 이 부품을 쓰는 조건이므로 비울 수 없다. */
  readonly description: string
  readonly disabled?: boolean
  /** 고를 수 없는 사유 요소의 id — 풀이 뒤에 `aria-describedby`로 붙는다. */
  readonly reasonId?: string
}

interface ChoiceCardsProps<T extends string> {
  /** 라디오 그룹의 `name`. */
  readonly name: string
  readonly legend: string
  /** 그 화면의 라벨 규칙(`voyage-cii-form__label` 등) — 크기는 쓰는 쪽이 정한다. */
  readonly legendClassName?: string
  readonly options: ReadonlyArray<ChoiceOption<T>>
  readonly value: T
  readonly onChange: (value: T) => void
  /** 카드 아래에 붙는 것 — 비활성 사유 등. */
  readonly children?: ReactNode
}

export function ChoiceCards<T extends string>({
  name,
  legend,
  legendClassName,
  options,
  value,
  onChange,
  children,
}: ChoiceCardsProps<T>) {
  const baseId = useId()

  return (
    <fieldset className="choice-cards">
      <legend className={legendClassName}>{legend}</legend>
      <div className="choice-cards__grid">
        {options.map((option) => {
          const nameId = `${baseId}-${option.value}-name`
          const descId = `${baseId}-${option.value}-desc`
          const describedBy = option.reasonId ? `${descId} ${option.reasonId}` : descId
          return (
            <label
              key={option.value}
              className={option.disabled ? 'choice-card choice-card--disabled' : 'choice-card'}
            >
              <input
                type="radio"
                className="choice-card__input"
                name={name}
                value={option.value}
                checked={value === option.value}
                disabled={option.disabled}
                aria-labelledby={nameId}
                aria-describedby={describedBy}
                onChange={() => {
                  // 실제 브라우저는 `disabled` 컨트롤에서 change를 내지 않는다. jsdom은
                  // 그렇지 않아(`fireEvent.click`이 그대로 넘어온다) 여기서도 막는다.
                  if (option.disabled) return
                  onChange(option.value)
                }}
              />
              <span className="choice-card__body">
                <span id={nameId} className="choice-card__name">
                  {option.label}
                </span>
                <span id={descId} className="choice-card__desc">
                  {option.description}
                </span>
              </span>
            </label>
          )
        })}
      </div>
      {children}
    </fieldset>
  )
}
