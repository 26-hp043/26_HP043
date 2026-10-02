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
 * 지느러미의 자리와 회전축은 `beomiHello.geometry.json`이 갖는다. 그 파일은 자산을
 * 자를 때 **함께 나온 값**이고, 화면은 그것을 읽어서 쓴다 — 손으로 옮겨 적으면 자산을
 * 다시 뽑는 날 둘이 갈리고, 지느러미가 몸에서 어긋난 채 돈다.
 *
 * `public/`에서 import하지 않는다 — Vite의 `public/`은 그대로 복사되는 자리라,
 * 거기서 읽으면 같은 파일이 번들에도 한 벌 더 들어간다.
 *
 * ## 장식이다
 *
 * 판 전체가 `aria-hidden`이다(`§14`). 이 장면이 말하는 것은 옆의 소개 문장과 계층
 * 목록이 이미 글자로 적는다.
 */

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

export function BeomiScene() {
  const { flipper, pivotInFlipper } = geometry

  return (
    <div className="beomi-sea" aria-hidden="true">
      <span className="beomi-deep" />
      <span className="beomi-glow" />

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

      <svg className="beomi-bed" viewBox="0 0 600 180" preserveAspectRatio="none">
        <path className="beomi-bed-far" d="M0 108 q90 -34 180 -6 q96 30 180 -12 q110 -34 240 10 V180 H0 Z" />
        <path className="beomi-bed-near" d="M0 142 q120 -26 230 4 q104 28 190 -8 q96 -24 180 6 V180 H0 Z" />
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

      <span className="beomi-figure">
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
    </div>
  )
}
