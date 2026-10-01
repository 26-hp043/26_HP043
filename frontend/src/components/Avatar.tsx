import './Avatar.css'
import { avatarSrc } from '../auth/session'
import { initialOf } from './avatarInitial'

/**
 * 프로필 이미지 — 올리기 전에는 **이름의 머리글자**다 (`#2080`).
 *
 * ## 기본 상태가 더 자주 보인다
 *
 * 올린 사람보다 **안 올린 사람이 많다.** 그래서 「없을 때 무엇을 그리나」가
 * 곁다리가 아니라 이 컴포넌트의 주된 모양이다. 머리글자는 사람마다 달라서
 * **자기 것임을 알아볼 수 있다** — 모두 같은 기본 그림이면 목록에서 서로
 * 구분되지 않는다.
 *
 * 범이 얼굴은 쓰지 않는다. 범이는 어시스턴트의 얼굴이라, 사용자 자리에 두면
 * 「나」와 「어시스턴트」가 섞인다.
 *
 * ## 장식이다
 *
 * `alt=""` + `aria-hidden`이다(`§14`). 이 자리가 누구인지는 **옆의 이름이**
 * 말한다 — 계정 메뉴의 버튼도, 설정의 절 제목도 이름을 이미 글자로 적는다.
 * 대체 텍스트를 주면 같은 말이 두 번 읽힌다.
 */
export function Avatar({
  hasAvatar,
  name,
  className,
  size,
}: {
  readonly hasAvatar: boolean
  /** 머리글자를 뽑을 이름. 표시 이름이 없으면 이메일을 넘긴다. */
  readonly name: string
  readonly className?: string
  /** 한 변의 길이(px). 안 주면 쓰는 쪽 CSS가 정한다. */
  readonly size?: number
}) {
  const classes = ['avatar', className].filter(Boolean).join(' ')
  const style = size === undefined ? undefined : { inlineSize: size, blockSize: size }

  if (!hasAvatar) {
    return (
      <span className={classes} style={style} aria-hidden="true">
        {initialOf(name)}
      </span>
    )
  }

  return (
    <img
      className={`${classes} avatar--image`}
      style={style}
      src={avatarSrc()}
      alt=""
      aria-hidden="true"
    />
  )
}
