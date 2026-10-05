// @vitest-environment jsdom
import '../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { Avatar } from './Avatar'
import { initialOf } from './avatarInitial'

const css = readFileSync(join(process.cwd(), 'src/components/Avatar.css'), 'utf-8')
/** 규칙 검사가 설명 문장에 걸리지 않게 한다. */
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '')

describe('프로필 이미지 — #2080', () => {
  it('올리기 전에는 **머리글자**다 — 이쪽이 기본 상태다', () => {
    /*
     * 올린 사람보다 안 올린 사람이 많다. 「없을 때 무엇을 그리나」가 곁다리가
     * 아니라 이 컴포넌트의 주된 모양이다.
     */
    const { container } = render(<Avatar hasAvatar={false} name="김수민" />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toBe('김')
  })

  it('올린 뒤에는 그림이고, 그림일 때는 글자가 남지 않는다', () => {
    const { container } = render(<Avatar hasAvatar name="김수민" />)
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(container.textContent).toBe('')
  })

  it('장식이다 — 두 모양 모두 이름을 갖지 않는다 (§14)', () => {
    /*
     * 이 자리가 누구인지는 **옆의 이름이** 말한다. 대체 텍스트를 주면 계정 메뉴
     * 버튼에서 같은 말이 두 번 읽힌다.
     */
    for (const has of [true, false]) {
      const { container } = render(<Avatar hasAvatar={has} name="김수민" />)
      const node = container.firstElementChild
      expect(node?.getAttribute('aria-hidden')).toBe('true')
      if (has) expect(node?.getAttribute('alt')).toBe('')
    }
  })

  it('그림일 때 **채움면을 지운다** — 투명한 구석으로 브랜드색이 비치지 않게', () => {
    /*
     * 비치면 올린 사진이 아니라 **덜 그려진 것**처럼 보인다. 값이 아니라 관계를
     * 잠근다 — 기본 모양은 면을 갖고, 그림 변종은 그것을 끈다.
     */
    const base = rules.slice(rules.indexOf('.avatar {'))
    expect(base.slice(0, base.indexOf('}'))).toContain('background: var(--color-primary-solid)')

    const image = rules.slice(rules.indexOf('.avatar--image {'))
    const body = image.slice(0, image.indexOf('}'))
    expect(body).toContain('background: none')
    expect(body).toContain('object-fit: cover')
  })

  it('판에 hex를 직접 적지 않는다 — DESIGN_SYSTEM §15', () => {
    expect(rules).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})

describe('머리글자', () => {
  it('이메일이면 로컬파트의 첫 글자다', () => {
    expect(initialOf('demo@bluelog.local')).toBe('D')
  })

  it('두 칸을 쓰는 글자를 **반 토막 내지 않는다**', () => {
    /*
     * 종전 `name[0]`은 UTF-16 한 칸이라 이모지를 쪼갠다 — 표시 이름에 이모지를
     * 쓰는 사람이 드물지 않고, 쪼개진 반쪽은 깨진 네모로 보인다.
     */
    expect(initialOf('🐧 펭귄')).toBe('🐧')
  })

  it('빈 이름에도 그릴 것을 준다', () => {
    expect(initialOf('   ')).toBe('?')
  })
})
