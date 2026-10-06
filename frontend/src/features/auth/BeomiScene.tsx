import './BeomiScene.css'
import geometry from './beomiHello.geometry.json'

/**
 * 로그인 화면 브랜드 판의 바다 (`#2076`).
 *
 * ## 판이 곧 바다다
 *
 * 그림을 네모로 얹지 않는다. 판은 이미 어두운 네이비 그라데이션이라, 그 위에
 * 빛·부유물·거품만 띄우면 **판 자체가 물**이 된다. 처음에 수면을 도형으로 그렸더니
 * 판 위쪽에 회색 띠가 한 줄 생겨 「올려다본 물」이 아니라 **덧댄 사각형**으로 보였다.
 *
 * ## 수면 위의 선대는 장식이 아니다
 *
 * BlueLog가 보는 것이 선대이고, 물속에서 올려다본 선체가 그 사실을 한 번에 말한다.
 * 아주 흐리게 둔다 — 알아보이되 글자와 겨루지 않는다(`§0.2` 제약 1은 글자 대비를
 * 요구하고, 이 판 위에는 로고·소개·계층이 모두 올라간다).
 *
 * ## 범이는 **3D 렌더 그대로**다
 *
 * 손으로 다시 그리지 않았다. 시안 폴더의 `01_환영인사` 렌더를 **두 겹으로 쪼개**
 * (몸 전체 · 들어 올린 앞지느러미) 지느러미만 어깨를 축으로 돌린다. 프레임을 새로
 * 그리지 않으므로 픽셀은 전부 원본이고, 메워 넣은 가짜 픽셀도 없다 — 돌린 지느러미가
 * 제자리의 원본을 덮기 때문이다.
 *
 * ⚠️ 몸판에서 지느러미를 **지우고 가려져 있던 몸을 메웠다**(`#2084`). 처음에는 몸판을
 * 원본 그대로 두고 「돌린 지느러미가 제자리를 덮는다」고 보았는데, 회전은 늘 제자리를
 * **비운다** — 화면에서 손 뒤에 손이 하나 더 보였다. 메운 윤곽은 지어낸 선이 아니라
 * **가려지지 않은 오른쪽 윤곽을 재어** 옮긴 것이다 — 머리에서 목까지 몸이 얼마나
 * 잘록해지는지를 오른쪽에서 뽑고(가장 넓은 곳 대비 69px), 그만큼을 왼쪽에 옮겼다.
 * 아래쪽은 배의 실측값에 이어 붙였다 — 배는 오른쪽으로 더 불러 있어 거울로 옮기면 틀린다.
 *
 * 지느러미의 자리와 회전축은 `beomiHello.geometry.json`이 갖는다. 그 파일은 자산을
 * 자를 때 **함께 나온 값**이고, 화면은 그것을 읽어서 쓴다 — 손으로 옮겨 적으면 자산을
 * 다시 뽑는 날 둘이 갈리고, 지느러미가 몸에서 어긋난 채 돈다.
 *
 * `public/`에서 import하지 않는다 — Vite의 `public/`은 그대로 복사되는 자리라,
 * 거기서 읽으면 같은 파일이 번들에도 한 벌 더 들어간다.
 *
 * ## 바다라고 **말하지 않고 보이게** 한다 (`#2084`)
 *
 * 수면 물결 · 암초 · 물고기 떼가 그 일을 한다. 셋 다 **표 하나에서 생성**한다 —
 * 좌표를 마크업에 흩으면 한 알을 옮길 때마다 마크업을 뒤져야 한다.
 *
 * ## 장식이다
 *
 * 판 전체가 `aria-hidden`이다(`§14`). 이 장면이 말하는 것은 옆의 소개 문장과 계층
 * 목록이 이미 글자로 적는다.
 */

/**
 * 수면 물결 — 물속에서 올려다본 수면.
 *
 * ⚠️ **채운 도형으로 그리지 않는다.** 처음에 수면을 도형으로 그렸더니 판 위쪽에 회색
 * 띠가 한 줄 생겨, 올려다본 물이 아니라 **덧댄 사각형**으로 보였다. 선 몇 줄과
 * 아래로 사라지는 가리개(`mask-image`)뿐이라 경계가 없다.
 */
const WAVES = [
  { key: 'a', y: 34, amp: 13, period: 150, duration: 19 },
  { key: 'b', y: 41, amp: 8, period: 110, duration: 27 },
  { key: 'c', y: 26, amp: 17, period: 210, duration: 34 },
] as const

/**
 * 물결 한 줄. `q` 한 번에 `t`를 이어 붙이면 마루와 골이 **정확히 `period`마다**
 * 되풀이된다 — 가로로 `period`만큼 밀면 이음매가 보이지 않는다. 미는 거리는 CSS가
 * 아니라 이 표에서 나간다(`--beomi-wave-step`).
 */
function waveD(y: number, amp: number, period: number) {
  const half = period / 2
  const parts = [`M-420 ${y}`, `q${half / 2} ${-amp} ${half} 0`]
  for (let x = -420 + half; x + half <= 1620; x += half) parts.push(`t${half} 0`)
  return parts.join(' ')
}

/**
 * 암초 — 산호 덩이와 바위.
 *
 * ⚠️ 줄기 하나를 길게 세우고 끝에서만 갈라지면 산호가 아니라 **마른 나무**가 된다 —
 * 한 번 그렇게 그려졌다. 밑동부터 여러 갈래로 서고(`stems`), 가지는 짧고 굵게 두고,
 * 끝을 뭉툭하게(`stroke-linecap: round`) 둬야 산호로 읽힌다.
 *
 * 범이가 서는 가운데(대략 `190`~`400`)는 비워 둔다 — 거기 둔 것은 범이 뒤에 가린다.
 */
const CLUMPS = [
  { x: 30, y: 152, h: 38, seed: 3, stems: 2, far: true },
  { x: 84, y: 160, h: 62, seed: 7, stems: 3, far: false },
  { x: 152, y: 154, h: 30, seed: 23, stems: 2, far: false },
  { x: 196, y: 138, h: 24, seed: 29, stems: 2, far: true },
  { x: 236, y: 162, h: 46, seed: 53, stems: 3, far: false },
  { x: 398, y: 140, h: 26, seed: 37, stems: 2, far: true },
  { x: 444, y: 158, h: 56, seed: 41, stems: 3, far: false },
  { x: 512, y: 152, h: 28, seed: 11, stems: 2, far: false },
  { x: 556, y: 162, h: 44, seed: 17, stems: 3, far: false },
  { x: 590, y: 146, h: 30, seed: 61, stems: 2, far: true },
] as const

/** 바위 — 산호 사이의 둥근 덩이. 반타원 하나면 된다. */
const ROCKS = [
  { cx: 136, cy: 160, rx: 26, ry: 18, far: false },
  { cx: 300, cy: 146, rx: 30, ry: 20, far: true },
  { cx: 348, cy: 144, rx: 18, ry: 13, far: true },
  { cx: 492, cy: 162, rx: 22, ry: 15, far: false },
] as const

/** 물고기 떼의 자리. 머리가 **가는 쪽**(+x)이고 꼬리가 뒤(-x)다. */
const FISH = [
  [6, 12], [26, 6], [24, 22], [46, 15], [62, 8], [66, 24], [84, 18],
] as const

/**
 * 씨 하나에서 **늘 같은 모양**이 나오는 난수. `Math.random`을 쓰면 새로고침마다
 * 암초가 바뀌고, 그러면 검사도 스냅샷도 잡을 것이 없다.
 *
 * `Math.imul`로 곱한다 — 그냥 곱하면 2⁵³을 넘겨 아래 비트가 날아간다.
 */
function random(seed: number) {
  let state = seed
  return () => {
    state = (Math.imul(state, 1103515245) + 12345) >>> 0
    return state / 4294967296
  }
}

/** 산호 덩이 하나를 **굵기별 세 줄**로 만든다 — 가지마다 요소를 두면 수가 는다. */
function coral({ x, y, h, seed, stems }: (typeof CLUMPS)[number]) {
  const next = random(seed)
  const levels: string[][] = [[], [], []]
  const round = (value: number) => Math.round(value * 10) / 10

  const grow = (px: number, py: number, angle: number, len: number, depth: number) => {
    const nx = px + Math.sin(angle) * len * 1.35
    const ny = py - Math.cos(angle) * len
    levels[depth].push(`M${round(px)} ${round(py)}L${round(nx)} ${round(ny)}`)
    if (depth === 0) return
    const forks = 2 + (next() < 0.45 ? 1 : 0)
    for (let i = 0; i < forks; i += 1) {
      grow(
        nx,
        ny,
        angle + (i - (forks - 1) / 2) * 0.8 + (next() - 0.5) * 0.3,
        len * (0.74 + next() * 0.16),
        depth - 1,
      )
    }
  }

  for (let k = 0; k < stems; k += 1) {
    grow(
      x + (k - (stems - 1) / 2) * h * 0.1,
      y,
      (k - (stems - 1) / 2) * 0.42 + (next() - 0.5) * 0.2,
      h * 0.26,
      2,
    )
  }

  // 굵은 줄기가 **위**로 간다 — 가는 가지를 나중에 그리면 밑동이 갈라져 보인다.
  return [2, 1, 0].map((depth) => ({
    width: Math.round(h * 0.15 * 0.82 ** (2 - depth) * 10) / 10,
    d: levels[depth].join(''),
  }))
}

const REEF = CLUMPS.map((clump) => ({ ...clump, paths: coral(clump) }))

/** 떠 있는 알갱이·배·거품의 자리. 값을 코드가 아니라 **표**로 둔다. */
const SHIPS = [
  { key: 'a', y: 14, hull: 'M4 30 H140 L128 52 Q120 58 108 58 H30 Q20 58 14 50 Z', house: { x: 96, y: 14, w: 22, h: 16 } },
  { key: 'b', y: 56, hull: 'M4 34 H104 L95 50 Q89 55 80 55 H26 Q18 55 13 48 Z', house: { x: 70, y: 21, w: 16, h: 13 } },
  { key: 'c', y: 0, hull: 'M4 26 H182 L166 54 Q157 61 143 61 H34 Q22 61 15 51 Z', house: { x: 128, y: 8, w: 26, h: 18 } },
] as const

/** 판 전체에 흩뿌리는 거품 — 물의 배경이다. */
const DRIFT = [
  { left: 14, size: 9, duration: 11, delay: 0 },
  { left: 31, size: 5, duration: 9, delay: 2.2 },
  { left: 66, size: 12, duration: 13, delay: 1 },
  { left: 82, size: 7, duration: 10, delay: 4.4 },
  { left: 48, size: 6, duration: 12, delay: 6.1 },
] as const

/**
 * 범이가 내는 물거품.
 *
 * ⚠️ **몸통 밖에만 둔다.** 범이는 흰색이라 그 위에 올린 흰 거품은 한 알도 보이지
 * 않는다 — 처음에 가운데로 모았다가 열 알이 통째로 사라졌다. `front`는 몸 앞을
 * 지나가는 알이다(전부 뒤에 두면 평평해진다).
 */
const FOAM = [
  { left: 2, bottom: 16, size: 26, drift: 26, duration: 8.4, delay: 0.3, front: false },
  { left: 86, bottom: 20, size: 30, drift: -24, duration: 9.2, delay: 2.6, front: false },
  { left: 10, bottom: 38, size: 20, drift: 18, duration: 7.4, delay: 5.1, front: false },
  { left: 92, bottom: 44, size: 22, drift: -16, duration: 8, delay: 3.8, front: false },
  { left: 0, bottom: 56, size: 17, drift: 20, duration: 8.8, delay: 6.6, front: false },
  { left: 16, bottom: 50, size: 16, drift: 22, duration: 5.8, delay: 1.1, front: true },
  { left: 78, bottom: 54, size: 18, drift: -20, duration: 6.4, delay: 3.4, front: true },
  { left: 8, bottom: 60, size: 12, drift: 16, duration: 5.2, delay: 2.2, front: true },
  { left: 88, bottom: 64, size: 13, drift: -14, duration: 6, delay: 5, front: true },
  { left: 22, bottom: 68, size: 10, drift: 12, duration: 4.9, delay: 6.3, front: true },
  { left: 72, bottom: 74, size: 11, drift: -10, duration: 5.5, delay: 0.8, front: true },
  { left: 4, bottom: 78, size: 9, drift: 14, duration: 5, delay: 4.1, front: true },
] as const

const BODY_1X = '/brand/beomi/beomi-3d-hello-body@1x.webp'
const BODY_2X = '/brand/beomi/beomi-3d-hello-body@2x.webp'
const FLIPPER_1X = '/brand/beomi/beomi-3d-hello-flipper@1x.webp'
const FLIPPER_2X = '/brand/beomi/beomi-3d-hello-flipper@2x.webp'

/** 암초 한 겹 — 멀고 흐린 겹과 가깝고 진한 겹을 따로 그린다. */
function Reef({ far }: { readonly far: boolean }) {
  return (
    <g className={far ? 'beomi-reef-far' : 'beomi-reef-near'}>
      <g className="beomi-coral">
        {REEF.filter((clump) => clump.far === far).flatMap((clump) =>
          clump.paths.map((path) => (
            <path key={`${clump.seed}-${path.width}`} strokeWidth={path.width} d={path.d} />
          )),
        )}
      </g>
      <g className="beomi-rock">
        {ROCKS.filter((rock) => rock.far === far).map((rock) => (
          <path
            key={rock.cx}
            d={`M${rock.cx - rock.rx} ${rock.cy} a${rock.rx} ${rock.ry} 0 0 1 ${rock.rx * 2} 0 Z`}
          />
        ))}
      </g>
    </g>
  )
}

/** 물고기 떼 한 무리. */
function School({ variant }: { readonly variant: string }) {
  return (
    <svg className={`beomi-school beomi-school--${variant}`} viewBox="0 0 104 32">
      {FISH.map(([x, y]) => (
        <path
          key={`${x}-${y}`}
          transform={`translate(${x} ${y})`}
          d="M0 0q5-3.4 10.5 0q-5.5 3.4-10.5 0ZM0 0l-4.4-2.8v5.6Z"
        />
      ))}
    </svg>
  )
}

function Foam({ front }: { readonly front: boolean }) {
  return (
    <>
      {FOAM.filter((bubble) => bubble.front === front).map((bubble) => (
        <span
          key={`${bubble.left}-${bubble.bottom}`}
          className={`beomi-foam${front ? '' : ' beomi-foam--back'}`}
          style={{
            left: `${bubble.left}%`,
            bottom: `${bubble.bottom}%`,
            inlineSize: bubble.size,
            blockSize: bubble.size,
            animationDuration: `${bubble.duration}s`,
            animationDelay: `${bubble.delay}s`,
            ['--beomi-foam-drift' as string]: `${bubble.drift}px`,
          }}
        />
      ))}
    </>
  )
}

/**
 * 물 — 판 뒤에 깔리는 배경 한 겹. 글자도 범이도 이 위에 온다.
 *
 * 범이는 **여기 들어 있지 않다**(`#2157`). 아래 `BeomiFigure` 주석을 보라.
 */
export function BeomiSea() {
  return (
    <div className="beomi-sea" aria-hidden="true">
      <span className="beomi-deep" />
      <span className="beomi-glow" />

      <svg className="beomi-surface" viewBox="0 0 1200 60" preserveAspectRatio="none">
        {WAVES.map((wave) => (
          <path
            key={wave.key}
            className={`beomi-wave beomi-wave--${wave.key}`}
            d={waveD(wave.y, wave.amp, wave.period)}
            style={{
              // 미는 거리는 **마루 간격과 같은 값**이어야 이음매가 보이지 않는다.
              ['--beomi-wave-step' as string]: `${wave.period}px`,
              animationDuration: `${wave.duration}s`,
            }}
          />
        ))}
      </svg>

      <svg className="beomi-fleet" viewBox="0 0 600 110" preserveAspectRatio="none">
        {SHIPS.map((ship) => (
          <g className={`beomi-ship beomi-ship--${ship.key}`} key={ship.key} transform={`translate(0 ${ship.y})`}>
            <path d={ship.hull} />
            <rect x={ship.house.x} y={ship.house.y} width={ship.house.w} height={ship.house.h} rx="2" />
          </g>
        ))}
      </svg>

      <span className="beomi-ray beomi-ray--a" />
      <span className="beomi-ray beomi-ray--b" />
      <span className="beomi-ray beomi-ray--c" />
      <span className="beomi-ray beomi-ray--d" />

      <School variant="a" />
      <School variant="b" />

      <svg className="beomi-bed" viewBox="0 0 600 180" preserveAspectRatio="none">
        <path className="beomi-bed-far" d="M0 108 q90 -34 180 -6 q96 30 180 -12 q110 -34 240 10 V180 H0 Z" />
        <path className="beomi-bed-near" d="M0 142 q120 -26 230 4 q104 28 190 -8 q96 -24 180 6 V180 H0 Z" />
      </svg>

      {/*
        암초는 **비율을 지켜** 그린다 — 해저(`.beomi-bed`)처럼 `preserveAspectRatio="none"`로
        늘이면 산호가 세로로 늘어나 버섯처럼 보인다.
      */}
      <svg className="beomi-reef" viewBox="0 0 600 180">
        <Reef far />
        <Reef far={false} />
      </svg>

      <span className="beomi-dust" />

      {DRIFT.map((bubble) => (
        <span
          key={bubble.left}
          className="beomi-drift"
          style={{
            left: `${bubble.left}%`,
            inlineSize: bubble.size,
            blockSize: bubble.size,
            animationDuration: `${bubble.duration}s`,
            animationDelay: `${bubble.delay}s`,
          }}
        />
      ))}

    </div>
  )
}

/**
 * 범이 — **글 흐름 안에 둔다** (`#2157`).
 *
 * ⚠️ 처음에는 물과 함께 띄워 두고(`position: absolute`) 높이를 `min(52vh, 470px)`로
 * 줬다. 그러면 그림이 **소개 문장이 어디서 끝나는지 모른다** — 화면이 낮거나 판이
 * 좁아 문장이 한 줄 더 늘면 계층 목록 셋째 줄이 범이 모자 위에 그려졌다(1280×720에서
 * 65px 겹쳤다). 겹침을 상수로 피하려 하면 **문구가 한 줄 늘 때마다 그 상수가 틀린다.**
 *
 * 그래서 판의 **flex 항목**으로 둔다. 남은 높이를 받아 가므로 소개가 길어지면 범이가
 * 그만큼 작아지고, 겹칠 수가 없다 — 계산은 브라우저가 한다.
 *
 * 물(`BeomiSea`)과 떨어져 있지만 같은 파일에 둔다. 둘은 **한 장면**이고, 자리만
 * 다르다 — 물은 판 뒤에 깔리고 범이는 글 아래에 선다.
 */
export function BeomiFigure() {
  const { flipper, pivotInFlipper } = geometry

  return (
    <span className="beomi-figure" aria-hidden="true">

      <Foam front={false} />
      <img
        className="beomi-body"
        src={BODY_1X}
        srcSet={`${BODY_1X} 1x, ${BODY_2X} 2x`}
        alt=""
      />
      {/*
        지느러미의 자리와 회전축은 **자산에서 나온 값**이다(`beomiHello.geometry.json`).
        손으로 옮겨 적으면 자산을 다시 뽑는 날 둘이 갈리고, 그러면 지느러미가 몸에서
        어긋난 채 돈다 — 화면 검사는 그래도 통과한다.
      */}
      <img
        className="beomi-flipper"
        src={FLIPPER_1X}
        srcSet={`${FLIPPER_1X} 1x, ${FLIPPER_2X} 2x`}
        alt=""
        style={{
          left: `${flipper.left}%`,
          top: `${flipper.top}%`,
          inlineSize: `${flipper.width}%`,
          blockSize: `${flipper.height}%`,
          transformOrigin: `${pivotInFlipper[0]}% ${pivotInFlipper[1]}%`,
        }}
      />
      <Foam front />
    </span>
  )
}
