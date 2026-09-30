import type { RefObject } from 'react'
import './FilePicker.css'

/**
 * CSV를 고르는 자리 (#2049).
 *
 * ## 왜 기본 단추를 그대로 두지 않나
 *
 * 맨 `<input type="file">`은 브라우저가 단추를 그린다 — 그 안의 글자
 * (`Choose File` · `No file chosen`)는 **브라우저 UI 언어**를 따르므로 우리가 한국어로
 * 바꿀 수 없다. 사용자의 Chrome이 영문이면 제품의 나머지가 전부 한국어인데 이 두
 * 자리만 영문이다. 모양·높이도 옆 「검증」 버튼과 맞지 않는다.
 *
 * ## `<input>`을 지우지 않는다
 *
 * 접근성 트리와 키보드 조작이 그 요소에 걸려 있고 `aria-label`도 거기 있다.
 * **화면에서만 가리고** `<label htmlFor>`가 그 자리를 진다 — 라벨을 누르면 입력이
 * 열리는 것은 브라우저 기본 동작이라 자바스크립트가 필요 없다.
 *
 * ⚠️ `display: none`을 쓰지 않는다 — 일부 브라우저에서 **초점을 받지 못한다.**
 * 저장소가 이미 쓰는 `.sr-only`(화면 밖으로 잘라 두되 접근성 트리에는 남긴다)를
 * 그대로 쓰고, 초점이 사라져 보이지 않게 **라벨이 그 초점을 대신 보인다**
 * (`FilePicker.css`의 `:focus-visible + ...`).
 *
 * ## 고른 파일 이름을 옆에 적는다
 *
 * 종전에는 브라우저 단추 **안에만** 있었다. 단추를 가리면 「무엇을 골랐는지」가
 * 함께 사라지므로 이 컴포넌트가 문자로 적는다.
 *
 * ## 모양은 쓰는 쪽이 정한다
 *
 * `buttonClassName`으로 **그 화면의 버튼 규칙**을 받는다. 두 화면의 버튼 모양이
 * 각자 자기 CSS에 있고(`.param-revision__row button` · `.vy-import__row button`),
 * 여기서 높이를 새로 정하면 옆 버튼과 어긋난다 — `BrandLogo`가 크기를 쓰는 쪽에
 * 맡긴 것과 같은 이유다.
 */
interface FilePickerProps {
  /** `<label htmlFor>`가 가리킬 id. */
  readonly id: string
  /** 낭독이 읽는 이름 — 기존 `aria-label`을 그대로 넘긴다. */
  readonly ariaLabel: string
  readonly accept?: string
  readonly file: File | null
  readonly onPick: (file: File | null) => void
  readonly inputRef?: RefObject<HTMLInputElement | null>
  /** 이 화면의 버튼 규칙. 높이·테두리를 옆 버튼과 맞추기 위한 것이다. */
  readonly buttonClassName?: string
}

/** 고르기 전에 이 자리가 하는 말. 값 자리 한 줄이라 마침표를 찍지 않는다(`PRD §6.4` 관례 ②). */
export const NO_FILE_CHOSEN = '선택된 파일 없음'
export const CHOOSE_FILE = '파일 선택'

export function FilePicker({
  id,
  ariaLabel,
  accept,
  file,
  onPick,
  inputRef,
  buttonClassName,
}: FilePickerProps) {
  return (
    <span className="file-picker">
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={accept}
        aria-label={ariaLabel}
        className="sr-only file-picker__input"
        onChange={(event) => onPick(event.target.files?.[0] ?? null)}
      />
      <label htmlFor={id} className={['file-picker__button', buttonClassName].filter(Boolean).join(' ')}>
        {CHOOSE_FILE}
      </label>
      {/*
        낭독에는 싣지 않는다 — 파일을 고르면 입력 자신의 값이 바뀌어 보조기술이
        이미 안다. 여기 또 실으면 같은 사실을 두 번 읽는다.
      */}
      <span className="file-picker__name" aria-hidden="true">
        {file === null ? NO_FILE_CHOSEN : file.name}
      </span>
    </span>
  )
}
