// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { AuthShell } from './AuthShell'
import geometry from './beomiHello.geometry.json'

const css = readFileSync(join(process.cwd(), 'src/features/auth/BeomiScene.css'), 'utf-8')
/** 규칙 검사가 설명 문장에 걸리지 않게 한다 — `#831`·`#829`·`#694`에서 세 번 밟았다. */
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '')
const source = readFileSync(join(process.cwd(), 'src/features/auth/BeomiScene.tsx'), 'utf-8')
const shellCss = readFileSync(join(process.cwd(), 'src/features/auth/AuthShell.css'), 'utf-8')

/**
 * **판을 통째로 그린다** — 조각만 그리지 않는다 (`#2157`).
 *
 * 장면은 두 조각(`BeomiSea` · `BeomiFigure`)이고, **그 둘이 판에서 어디에 놓이는지**가
 * 이 장면의 요점이다. 조각만 그려 보면 자리가 바뀌어도 검사가 통과한다 — 실제로
 * 범이가 소개 위로 올라와 계층 목록과 겹친 것이 그 자리였다.
 */
function scene() {
  const { container } = render(
    <AuthShell title="로그인" intro>
      폼
    </AuthShell>,
  )
  return container
}

describe('로그인 화면의 바다 — #2076', () => {
  it('로그인 화면에만 나온다 — 나머지 셋에는 없다', () => {
    /*
     * 소개 블록과 **같은 깃발**로 가른다.
     *
     * ⚠️ 깃발만으로는 모자랐다 (`#2157`). 1100px 이하에서 판이 상단 띠로 접힐 때
     * (확정 3-3) 소개와 함께 사라져야 하는데, **그렇게 만드는 규칙이 없었다** —
     * `@media`가 `.auth-intro`만 접었고 장면은 판의 다른 자식이라 83px 띠 안에
     * 범이 몸통과 산호가 잘린 채 남았다. 적어 둔 것과 도는 것이 갈려 있었고,
     * 아래 「접힌 띠」 검사가 이제 그 자리를 본다.
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
    expect(container.querySelector('.beomi-figure')?.getAttribute('aria-hidden')).toBe('true')
    // 판 전체를 그리므로 로고까지 잡힌다 — **장면의 그림만** 본다.
    for (const img of container.querySelectorAll('.beomi-figure img')) {
      expect(img.getAttribute('alt')).toBe('')
    }
  })

  it('범이는 **3D 렌더 두 장**이고, 네 경로가 모두 실재한다', () => {
    /*
     * 「규칙이 화면에 닿지 않는다」의 자산판이다 — 경로를 틀려도 화면 검사는 전부
     * 통과한다. 깨진 그림도 렌더 트리에서는 `<img>`다.
     */
    const container = scene()
    const sources = [...container.querySelectorAll('.beomi-figure img')].flatMap((img) => [
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

  /**
   * **접힌 띠에서 장면이 사라진다** (`#2157`).
   *
   * 소개를 접는 그 블록이 장면도 접어야 한다. 두 규칙이 **다른 블록**에 있으면
   * 중단점이 바뀌는 날 한쪽만 따라가고, 그 어긋남은 1100px 이하에서만 보인다.
   */
  it('소개를 접는 그 블록이 바다와 범이도 접는다 (#2157)', () => {
    const shellRules = shellCss.replace(/\/\*[\s\S]*?\*\//g, '')
    const at = shellRules.indexOf('@media (width <= 1100px)')
    expect(at, '1100px 블록을 찾지 못했다').toBeGreaterThan(-1)

    // 블록 하나를 중괄호를 세며 끊는다 — 안에 규칙이 여럿 들어 있다.
    let depth = 0
    let end = at
    for (let i = shellRules.indexOf('{', at); i < shellRules.length; i += 1) {
      if (shellRules[i] === '{') depth += 1
      else if (shellRules[i] === '}') {
        depth -= 1
        if (depth === 0) {
          end = i
          break
        }
      }
    }
    const block = shellRules.slice(at, end)

    expect(block).toMatch(/\.auth-intro\s*\{[^}]*display:\s*none/)
    expect(block, '바다가 접힌 띠에 남는다').toContain('.beomi-sea')
    expect(block, '범이가 접힌 띠에 남는다').toContain('.beomi-figure')
    expect(block.slice(block.indexOf('.beomi-sea'))).toMatch(/display:\s*none/)
  })

  /**
   * **범이는 소개 아래, 판의 자식이다** (`#2157`).
   *
   * 겹치지 않는 이유가 **숫자가 아니라 구조**다. 그림이 글 흐름 안에 있고 남은
   * 높이를 받아 가므로, 소개가 길어지면 그림이 작아진다. 다시 띄워 두면(절대 위치)
   * 그림은 소개가 어디서 끝나는지 모르게 되고 겹침이 돌아온다 — 1280×720에서 65px
   * 겹쳤던 자리다.
   *
   * 멈춘 화면으로는 안 보인다. jsdom은 배치를 하지 않으므로 **구조**를 잠근다.
   */
  it('범이가 소개 뒤에 오고 바다 안에 들어 있지 않다 (#2157)', () => {
    const container = scene()
    const panel = container.querySelector('.auth-brand-panel') as HTMLElement
    const figure = container.querySelector('.beomi-figure') as HTMLElement
    const intro = container.querySelector('.auth-intro') as HTMLElement
    const sea = container.querySelector('.beomi-sea') as HTMLElement

    expect(figure.parentElement, '범이가 판의 직계 자식이 아니다').toBe(panel)
    expect(sea.contains(figure), '범이가 다시 바다 안에 들어갔다').toBe(false)
    expect(
      intro.compareDocumentPosition(figure) & Node.DOCUMENT_POSITION_FOLLOWING,
      '범이가 소개보다 앞에 온다',
    ).toBeTruthy()

    // 띄워 두지 않는다 — 띄우면 남은 높이를 받지 못한다.
    const rule = rules.slice(rules.indexOf('.beomi-figure {'))
    const body = rule.slice(0, rule.indexOf('}'))
    expect(body).not.toMatch(/position:\s*absolute/)
    expect(body).not.toMatch(/inset-block-end/)
    expect(body).toMatch(/flex:\s*1/)
    expect(body).toContain('min-block-size: 0')
  })

  it('자리 값이 **표로** 모여 있다 — 마크업에 흩어져 있지 않다', () => {
    /*
     * 배·부유물·거품은 수가 많다. 좌표를 JSX 안에 흩으면 한 알을 옮길 때마다
     * 마크업을 뒤져야 하고, 그러다 겹치거나 몸통 위로 올라간다.
     */
    for (const table of ['const SHIPS', 'const DRIFT', 'const FOAM', 'const WAVES', 'const CLUMPS', 'const ROCKS', 'const FISH']) {
      expect(source).toContain(table)
    }
  })

  it('수면 물결은 **이음매 없이** 돈다 — 미는 거리가 마루 간격이다', () => {
    /*
     * 물결은 `period`마다 같은 모양이 되풀이되는 선이다. 가로로 **정확히 그만큼**
     * 밀어야 되돌아온 자리가 처음과 겹친다. 조금이라도 다르면 한 바퀴마다 물결이
     * 한 번씩 튀는데, 그 튐은 **멈춘 그림에서는 보이지 않는다**.
     */
    const waves = [...scene().querySelectorAll('.beomi-wave')] as SVGPathElement[]
    expect(waves.length).toBeGreaterThan(1)

    for (const wave of waves) {
      const step = Number.parseFloat(wave.style.getPropertyValue('--beomi-wave-step'))
      const d = wave.getAttribute('d') ?? ''

      // `q`가 마루 한쪽(= 간격의 절반)을 그리고 `t`가 그것을 되비추며 이어 간다.
      const half = Number.parseFloat(d.slice(d.indexOf('t') + 1))
      expect(half * 2, `미는 거리 ${step}가 마루 간격 ${half * 2}와 다르다`).toBe(step)
    }
  })

  it('수면에 **경계가 없다** — 띠로 보였던 자리다', () => {
    /*
     * 처음에 수면을 채운 도형으로 그렸더니 판 위쪽에 회색 띠가 한 줄 생겨, 올려다본
     * 물이 아니라 **덧댄 사각형**으로 보였다. 아래로 사라지는 가리개가 그 자리를 막는다.
     */
    const rule = rules.slice(rules.indexOf('.beomi-surface {'))
    const body = rule.slice(0, rule.indexOf('}'))
    expect(body).toContain('fill: none')
    expect(body).toMatch(/mask-image:\s*linear-gradient\(to bottom[^;]*transparent/)
  })

  it('산호는 **바닥에 붙어 자란다** — 떠 있으면 바위가 된다', () => {
    /*
     * 덩이의 밑동(`y`)은 해저 띠 안이어야 한다. 위로 올리면 물 가운데 산호가 떠 있고,
     * 그래도 화면 검사는 전부 통과한다.
     */
    const bases = [...source.matchAll(/\{ x: \d+, y: (\d+), h: \d+, seed/g)].map((m) => Number(m[1]))
    expect(bases.length).toBeGreaterThan(6)
    for (const y of bases) {
      expect(y >= 130 && y <= 175, `산호 밑동 ${y}가 해저 밖이다`).toBe(true)
    }
  })

  it('물고기는 **가는 쪽으로** 헤엄친다 — 꼬리가 뒤다', () => {
    /*
     * 한 번 거꾸로 그렸다. 머리와 꼬리를 바꿔 달아도 모양은 그럴듯해서, 보고 있지
     * 않으면 **뒤로 헤엄치는 떼**가 그대로 나간다.
     */
    const fish = scene().querySelector('.beomi-school path') as SVGPathElement
    const tail = /l(-?[\d.]+)/.exec(fish.getAttribute('d') ?? '')
    expect(tail, '꼬리 획을 찾지 못했다').not.toBeNull()
    expect(Number(tail?.[1]) < 0, '꼬리가 머리와 같은 쪽에 있다').toBe(true)

    const swim = rules.slice(rules.indexOf('@keyframes beomi-swim'))
    expect(swim.slice(0, swim.indexOf('}') + 2)).toMatch(/from \{ inset-inline-start: -/)
  })

  it('떠 있는 움직임은 **제자리에서 시작하고 끝난다** — 아니면 한 번 튄다', () => {
    /*
     * 떠오르는 동작이 `transform: none`으로 끝나고 여기서 이어받는다. 시작 칸이
     * 제자리가 아니면 그 순간 범이가 한 번 튀는데, 3.2초 뒤 한 프레임이라 눈에
     * 걸리지 않고 지나간다.
     */
    const float = rules.slice(rules.indexOf('@keyframes beomi-float'))
    const first = float.slice(float.indexOf('0%'), float.indexOf(';', float.indexOf('0%')))
    expect(first).toContain('0%, 100%')
    expect(first).toMatch(/translate\(0, 0\) rotate\(0deg\)/)
  })
})
