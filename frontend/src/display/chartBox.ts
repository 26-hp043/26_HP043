import { useEffect, useRef, useState } from 'react'

/**
 * 차트가 **배율을 타지 않게** 하는 상자 (`DESIGN_SYSTEM §9.1` · `#2038`).
 *
 * ## 왜 필요한가
 *
 * `§9`는 치수를 px로 적는다 — 선 `1.5px` · 축 라벨 `12px` · 경계선 `1px`. 그런데
 * SVG의 `stroke-width: 1.5`에서 `1.5`는 **뷰박스 좌표 단위**이지 CSS 픽셀이 아니다.
 * 뷰박스를 고정해 두고 `inline-size: 100%`로 늘리면 **안의 모든 것이 같은 배율로**
 * 커진다 — `#2038` 실측에서 1920 창의 배율이 `2.19×`였고, 선 `2px`가 `4.37px`,
 * 축 라벨 `12px`가 `26.2px`로 그려졌다. **`§9`가 적은 숫자가 어느 폭에서도 나오지
 * 않았다.**
 *
 * 뷰박스 폭을 **실제 픽셀**로 두면 `1칸 = 1 CSS px`이 되어 배율이 `1.0×`로 고정된다.
 * 그러면 선언한 값이 그대로 나오고, **높이를 폭과 따로 정할 수 있다.**
 *
 * ## `non-scaling-stroke`만으로는 부족하다
 *
 * 저장소가 이미 네 곳에서 쓰고 있는 그 속성은 **선의 두께만** 되돌린다. 축 라벨
 * (`§9.1` 12px)과 차트 높이는 그대로 배율을 탄다.
 *
 * ## 쓰는 법
 *
 * 높이는 **부르는 쪽이 상수로 갖는다** — 치수는 `§0.2`상 Figma 소유이고, 차트마다
 * 담는 것이 달라 공용 값이 없다.
 *
 * ```tsx
 * const VIEW_H = 200
 * const { ref, width } = useChartWidth()
 * return (
 *   <div ref={ref}>
 *     <svg width={width} height={VIEW_H} viewBox={`0 0 ${width} ${VIEW_H}`}>…</svg>
 *   </div>
 * )
 * ```
 */

/**
 * 재기 전에 쓰는 폭.
 *
 * 첫 렌더는 **아직 잰 값이 없다** — `ResizeObserver`는 붙은 뒤에 부른다. 0을 쓰면 그
 * 한 프레임 동안 뷰박스가 무너져 선이 한 점으로 모였다가 펴진다. 잰 값이 올 때까지
 * 쓸 수 있는 폭을 둔다.
 */
export const CHART_FALLBACK_WIDTH = 720

/**
 * 감싼 요소의 **실제 폭**을 CSS 픽셀로 돌려준다.
 *
 * ⚠️ `ResizeObserver`가 없는 환경(구형 브라우저 · 일부 테스트 환경)에서는 **마운트
 * 시점의 한 번**만 잰다 — 그때도 차트는 그려진다. 같은 판단이 `mapLibreRenderer`에
 * 이미 있다.
 */
export function useChartWidth(): {
  ref: React.RefObject<HTMLDivElement | null>
  width: number
} {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(CHART_FALLBACK_WIDTH)

  useEffect(() => {
    const element = ref.current
    if (element === null) return

    /*
     * 0은 받지 않는다 — 감춰진 탭 안에서 마운트되면 폭이 0으로 오고, 그 값을 넣으면
     * 탭을 열었을 때까지 차트가 한 점으로 남는다. 다음 관측이 실제 폭을 가져온다.
     */
    const measure = () => {
      const measured = Math.round(element.getBoundingClientRect().width)
      if (measured > 0) setWidth(measured)
    }

    measure()
    if (typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return { ref, width }
}
