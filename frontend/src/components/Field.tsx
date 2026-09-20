import type { ReactNode } from 'react'

import './Field.css'
import { useShowsLabelEn } from '../i18n/core'

/**
 * 폼 필드 한 벌 — **`DESIGN_SYSTEM §8.4` 규격을 여기서 강제한다** (`#936`).
 *
 * ## 왜 공용으로 모으는가
 *
 * 확정 1-1이 에러 층위를 셋으로 나누며 필드를 폼 규격으로 이관했는데, 그 규격이
 * 신설된 적이 없어 **화면마다 제각각 처리하고 있었다** — `Field` 컴포넌트 넷(둘은
 * 접두어만 다른 복제) · 오류 클래스 16종 · 컨트롤 87곳 중 `aria-invalid`가 붙은 것이
 * **18곳**. `§16` 항목 8의 「클래스 이름 24종」이 필드 층위에서 재현된 것이다.
 *
 * ## 배선을 돌려주는 이유 — children이 함수다
 *
 * `§8.4`는 *「컴포넌트가 라벨·힌트·오류·`aria` 배선을 **함께** 들고 있어야 한다」*고
 * 요구한다. 그런데 컨트롤은 `<input>`만이 아니다 — 87곳 중 **40곳이 `<select>`**라
 * 컴포넌트가 컨트롤을 직접 그릴 수 없다(`<option>`을 받아야 한다).
 *
 * 그래서 컨트롤을 받지 않고 **배선을 넘겨준다.** 호출부는 그것을 펼치기만 하면 된다.
 *
 * ```tsx
 * <Field id="distance" label="운항 거리" labelEn="distance_nm" unit="nm" error={err}>
 *   {(control) => <input {...control} value={v} onChange={onChange} />}
 * </Field>
 * ```
 *
 * `id`가 배선 안에 있으므로 **펼치지 않으면 라벨이 컨트롤에 닿지 않는다** — 잊으면
 * 조용히 통과하는 대신 눈에 띈다. 남은 누락은 `a11yWiring.test.ts`가 소스에서 잡는다.
 *
 * ## 문구는 소유하지 않는다
 *
 * 오류·힌트 문자열은 `PRD §6.3`·`§6.4`가 갖는다(`§13` 규율). 이 컴포넌트는 **자리와
 * 배선만** 정한다.
 */

/**
 * 컨트롤에 펼칠 배선. `<input>`·`<select>`·`<textarea>` 어디에나 맞는다.
 *
 * **export 하지 않는다** — 호출부는 `children`의 인자로 받으므로 이름이 필요 없다.
 * 내보내 두면 `moduleBoundary.test.ts`가 미참조 export로 잡는다.
 */
interface FieldControlProps {
  id: string
  'aria-invalid'?: true
  'aria-describedby'?: string
}

export function Field({
  id,
  label,
  labelHidden,
  labelEn,
  unit,
  hint,
  hintHidden,
  error,
  children,
}: {
  id: string
  label: string
  /**
   * 라벨을 **화면에서만** 감춘다 — 낭독에는 남는다 (전역 `.sr-only`, `#831 ⑸`).
   *
   * `§8.4`는 라벨의 **자리**를 정할 뿐 「반드시 보여야 한다」고 적지 않았다. 칸이
   * 하나뿐이고 placeholder가 같은 말을 하는 자리(어시스턴트 질문칸)에서는 라벨
   * 한 줄이 정보를 더하지 않는다. 그렇다고 라벨을 **지우면** 낭독에서 이름이
   * 사라지므로, 지우는 대신 감춘다.
   *
   * 감추면 `labelEn`·`unit`도 함께 감춰진다 — 보여야 할 것이 있으면 쓰지 않는다.
   */
  labelHidden?: boolean
  /** 요청 본문의 필드명. `§14` 「한국어 라벨 + 영문 병기」. */
  labelEn?: string
  unit?: string
  hint?: string
  /**
   * 힌트를 **화면에서만** 감춘다 — 낭독에는 남는다 (`labelHidden`과 같은 규율).
   *
   * placeholder가 같은 말을 하는 자리에서 쓴다. 같은 문장을 칸 안과 칸 아래에 두 번
   * 두면 줄만 늘고, 그렇다고 힌트를 **지우면** 입력을 시작한 뒤 그 말이 사라진다 —
   * placeholder는 값이 들어오면 없어지고 낭독이 건너뛰기도 한다. 지우는 대신 감춘다.
   */
  hintHidden?: boolean
  error?: string
  children: (control: FieldControlProps) => ReactNode
}) {
  const showsLabelEn = useShowsLabelEn()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`

  /*
   * `§8.4` — 둘 다 있으면 **오류를 먼저** 적는다. 낭독 순서가 곧 고칠 순서다.
   */
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ')

  const control: FieldControlProps = {
    id,
    ...(error ? { 'aria-invalid': true as const } : {}),
    ...(describedBy ? { 'aria-describedby': describedBy } : {}),
  }

  /* `§8.4` — 라벨 → 입력칸 → 힌트 → 오류 순이다. */
  return (
    <div className="field">
      <label className={labelHidden ? 'sr-only' : 'field__label'} htmlFor={id}>
        {label}
        {labelEn && showsLabelEn ? (
          <span className="field__label-en" lang="en">
            {' '}
            {labelEn}
          </span>
        ) : null}
        {unit ? <span className="field__unit">{unit}</span> : null}
      </label>

      {children(control)}

      {hint ? (
        <p className={hintHidden ? 'sr-only' : 'field__hint'} id={hintId}>
          {hint}
        </p>
      ) : null}

      {/*
        `§8.4` — `role="alert"`가 없으면 검증 실패가 **낭독되지 않는다.**
        재시도 버튼은 두지 않는다(확정 1-2) — 고칠 대상이 화면에 있다.
      */}
      {error ? (
        <p className="field__error" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
