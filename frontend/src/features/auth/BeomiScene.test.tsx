// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { AuthShell } from './AuthShell'
import { BeomiScene } from './BeomiScene'
import geometry from './beomiHello.geometry.json'

const css = readFileSync(join(process.cwd(), 'src/features/auth/BeomiScene.css'), 'utf-8')
/** 규칙 검사가 설명 문장에 걸리지 않게 한다 — `#831`·`#829`·`#694`에서 세 번 밟았다. */
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '')
const source = readFileSync(join(process.cwd(), 'src/features/auth/BeomiScene.tsx'), 'utf-8')

function scene() {
  const { container } = render(<BeomiScene />)
  return container
}

describe('로그인 화면의 바다 — #2076', () => {
  it('로그인 화면에만 나온다 — 나머지 셋에는 없다', () => {
    /*
     * 소개 블록과 **같은 깃발**로 가른다. 1100px 이하에서 판이 상단 띠로 접힐 때
     * (확정 3-3) 소개와 함께 사라져야 하기 때문이다 — 띠에 바다만 남으면 로고
     * 옆에서 거품이 올라간다.
     */
    const { container: login } = render(
      <AuthShell title="로그인" intro>
        폼
      </AuthShell>,
    )
    expect(login.querySelector('.beomi-sea')).not.toBeNull()

    const { container: signup } = render(<AuthShell title="회원가입">폼</AuthShell>)
    expect(signup.querySelector('.beomi-sea')).toBeNull()
  })

  it('장식이다 — 장면 전체가 접근성 트리에서 빠지고 그림은 이름을 갖지 않는다 (§14)', () => {
    /*
     * 이 장면이 말하는 것은 옆의 소개 문장과 계층 목록이 이미 글자로 적는다.
     * 대체 텍스트를 주면 같은 말이 두 번 읽힌다.
     */
    const container = scene()
    expect(container.querySelector('.beomi-sea')?.getAttribute('aria-hidden')).toBe('true')
    for (const img of container.querySelectorAll('img')) {
      expect(img.getAttribute('alt')).toBe('')
    }
  })

  it('범이는 **3D 렌더 두 장**이고, 네 경로가 모두 실재한다', () => {
    /*
     * 「규칙이 화면에 닿지 않는다」의 자산판이다 — 경로를 틀려도 화면 검사는 전부
     * 통과한다. 깨진 그림도 렌더 트리에서는 `<img>`다.
     */
    const container = scene()
    const sources = [...container.querySelectorAll('img')].flatMap((img) => [
      img.getAttribute('src') ?? '',
      ...(img.getAttribute('srcset') ?? '').split(',').map((part) => part.trim().split(/\s+/)[0]),
    ])
    const unique = [...new Set(sources.filter(Boolean))]

    expect(unique).toHaveLength(4)
    for (const path of unique) {
      expect(existsSync(join(process.cwd(), 'public', path))).toBe(true)
    }
  })

  it('지느러미의 자리와 회전축은 **자산에서 읽는다** — 손으로 적지 않는다', () => {
    /*
     * 자산을 다시 뽑는 날 숫자가 갈리면 지느러미가 몸에서 어긋난 채 돈다. 그 어긋남은
     * 화면 검사로는 보이지 않으므로, **같은 값에서 나왔는지**를 잠근다.
     */
    const flipper = scene().querySelector('.beomi-flipper') as HTMLElement
    expect(flipper.style.left).toBe(`${geometry.flipper.left}%`)
    expect(flipper.style.top).toBe(`${geometry.flipper.top}%`)
    expect(flipper.style.transformOrigin).toBe(
      `${geometry.pivotInFlipper[0]}% ${geometry.pivotInFlipper[1]}%`,
    )

    // CSS가 같은 숫자를 또 적고 있지 않다 — 적으면 두 곳이 갈린다.
    const rule = rules.slice(rules.indexOf('.beomi-flipper {'))
    expect(rule.slice(0, rule.indexOf('}'))).not.toMatch(/left|top|transform-origin/)
  })

  it('상자의 비율이 몸 자산의 비율과 같다 — 다르면 범이가 눌린다', () => {
    const [w, h] = geometry.bodySize
    const rule = rules.slice(rules.indexOf('.beomi-figure {'))
    expect(rule.slice(0, rule.indexOf('}'))).toContain(`aspect-ratio: ${w} / ${h}`)
  })

  it('두 장을 **조상 선택자로 묶지 않는다** — #2046·#2047이 밟은 자리', () => {
    /*
     * `.beomi-figure img`(0-1-1)로 적으면 지느러미 규칙(0-1-0)이 특이도로 져서
     * 지느러미가 상자 전체로 늘어난다. 실제로 한 번 그렇게 그려졌다.
     */
    expect(rules).not.toMatch(/\.beomi-figure\s+img/)
  })

  it('범이가 내는 거품은 **몸통 밖에만** 있다', () => {
    /*
     * ⚠️ 범이는 흰색이라 그 위에 올린 흰 거품은 한 알도 보이지 않는다 — 처음에
     * 가운데로 모았다가 열 알이 통째로 사라졌다.
     */
    const foam = [...scene().querySelectorAll('.beomi-foam')] as HTMLElement[]
    expect(foam.length).toBeGreaterThan(6)
    for (const bubble of foam) {
      const left = Number.parseFloat(bubble.style.left)
      expect(left < 30 || left > 66, `몸통 위의 거품은 보이지 않는다: left ${left}%`).toBe(true)
    }
  })

  it('거품이 앞뒤로 갈려 있다 — 한쪽만 있으면 평평해진다', () => {
    /*
     * 전부 앞에 두면 범이가 거품 **뒤에** 갇혀 보이고, 전부 뒤에 두면 물속이 아니라
     * 그림 한 장이 된다.
     */
    const container = scene()
    const body = container.querySelector('.beomi-body')
    const foam = [...container.querySelectorAll('.beomi-foam')]
    const before = foam.filter((node) => body?.compareDocumentPosition(node) === Node.DOCUMENT_POSITION_PRECEDING)

    expect(before.length).toBeGreaterThan(0)
    expect(before.length).toBeLessThan(foam.length)
  })

  it('거품은 **속이 빈 고리**다 — 꽉 찬 원은 그냥 점이다', () => {
    const rule = rules.slice(rules.indexOf('.beomi-foam {'))
    const body = rule.slice(0, rule.indexOf('@keyframes'))
    expect(body).toContain('radial-gradient')
    expect(body).toContain('box-shadow: inset')
  })

  it('움직임을 줄여 달라고 하면 **멈추되 손은 든 채**다 (§14)', () => {
    /*
     * 지느러미를 0도로 두면 손을 내린 모습이 되어, 인사하러 온 장면이 그냥 떠 있는
     * 장면이 된다.
     */
    const media = rules.slice(rules.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(media).toContain('animation: none')
    expect(media).toMatch(/\.beomi-flipper\s*\{\s*transform: rotate\((?!0deg)/)

    /*
     * 멈추는 목록이 **실제로 도는 것들**을 덮는다. 장면이 자라면 목록을 빠뜨리기
     * 쉬운데, 빠뜨려도 화면은 멀쩡해 보인다 — 줄여 달라고 한 사람에게만 계속 움직인다.
     *
     * 돌기 **시작하는** 규칙(`animation:` · `animation-name:`)만 센다 — 변종들의
     * `animation-duration`은 바탕 규칙이 멈추면 같이 멈춘다.
     */
    const moving = [
      ...rules.matchAll(/^\.(beomi-[a-z-]+)[^{]*\{[^}]*animation(?:-name)?\s*:[^;}]*[;}]/gms),
    ]
      .filter((match) => !/animation:\s*none/.test(match[0]))
      .map((match) => match[1])
    const stopped = [...media.matchAll(/\.(beomi-[a-z-]+)/g)].map((match) => match[1])
    for (const name of new Set(moving)) {
      // 변종(`beomi-ray--b`)은 바탕(`beomi-ray`)이 목록에 있으면 같이 멈춘다 —
      // 특이도가 같고 멈추는 규칙이 파일에서 **뒤**라 그쪽이 이긴다.
      expect(
        stopped.some((listed) => name.startsWith(listed)),
        `${name}이 멈추는 목록에 없다`,
      ).toBe(true)
    }
  })

  it('색을 **판의 토큰에서 뽑는다** — 고정색이면 다크에서 뜬다', () => {
    /*
     * 판은 테마에 따라 밝기가 달라진다(`--brand-gradient-*`). `§15`는 토큰만 쓰라고
     * 하고, 여기서는 그것이 곧 테마 적응이다.
     */
    expect(rules).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(rules).not.toMatch(/\brgba?\(/)
    expect(rules).toContain('color-mix(in srgb, var(--brand-gradient-to)')
  })

  it('자리 값이 **표로** 모여 있다 — 마크업에 흩어져 있지 않다', () => {
    /*
     * 배·부유물·거품은 수가 많다. 좌표를 JSX 안에 흩으면 한 알을 옮길 때마다
     * 마크업을 뒤져야 하고, 그러다 겹치거나 몸통 위로 올라간다.
     */
    for (const table of ['const SHIPS', 'const DRIFT', 'const FOAM']) {
      expect(source).toContain(table)
    }
  })
})
