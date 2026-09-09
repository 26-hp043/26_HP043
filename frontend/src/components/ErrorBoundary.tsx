import { Component, type ErrorInfo, type ReactNode } from 'react'
import './ErrorBoundary.css'

/**
 * 렌더 예외를 받아 **화면을 백지로 만들지 않는** 경계 (`#823`).
 *
 * ## 무엇이 문제였나
 *
 * 앱 전체에 경계가 하나도 없었다.
 *
 * ```
 * $ grep -rn "componentDidCatch|getDerivedStateFromError|ErrorBoundary" frontend/src
 * (0건)
 * ```
 *
 * **React 19는 렌더 중 예외가 올라오면 루트를 언마운트한다** — `#root`가 비어 완전
 * 백지가 되고, 콘솔 에러만 남는다. **새로고침해도 복구되지 않는다**(같은 데이터로
 * 같은 지점에서 다시 던진다). 사용자는 URL을 직접 쳐야 빠져나올 수 있다.
 *
 * 그런데 표시 포매터는 **던지도록 설계돼 있다.**
 *
 * ```
 * formatCapacity(1e-7)  -> THROW TypeError: 십진 문자열이 아닙니다: "1e-7"
 * formatCapacity(1e+21) -> THROW TypeError: 십진 문자열이 아닙니다: "1e+21"
 * ```
 *
 * JS는 `1e-6` 미만과 `1e21` 이상에서 지수 표기로 전환하므로 그 지점이 경계다.
 * 재화중량톤수에 `0.0000001`을 넣은 선박이 등록되면(서버는 `Field(gt=0)`뿐이다)
 * 그 선박의 목록·상세가 앱을 통째로 죽인다.
 *
 * ## 왜 포매터를 고치지 않고 경계를 두는가 (`#823` 판정, 2026-09-08)
 *
 * **조용한 폴백은 틀린 값을 숨긴다.** `1e-7`을 `0`이나 `—`로 표시하면 사용자는
 * 그것이 실제 값이라고 믿는다. 실제로 `formatCapacity(0.000001)`은 던지지 않고
 * **`0`을 낸다** — 던지는 쪽이 오히려 정직하다.
 *
 * 그리고 이 결함은 `formatCapacity` 하나가 아니라 **「경계 부재」라는 구조** 때문이다.
 * 경계 1개를 넣으면 아직 발견되지 않은 다른 throw 경로까지 함께 막힌다.
 *
 * ## 클래스 컴포넌트인 이유
 *
 * React가 에러 경계에 **훅 API를 주지 않는다.** `getDerivedStateFromError`·
 * `componentDidCatch`는 클래스에만 있다. 이 저장소의 유일한 클래스 컴포넌트다.
 *
 * ## 스스로 리셋되지 않는다
 *
 * 한 번 잡으면 그 상태가 유지된다. 화면 단위로 쓸 때 `key`에 경로를 주면
 * **경로가 바뀔 때 React가 인스턴스를 새로 만들어** 자동으로 회복된다. 그렇게 하지
 * 않으면 사이드바를 눌러도 오류 화면이 남아, 사용자 입장에서는 백지와 다르지 않다.
 */

interface ErrorBoundaryProps {
  children: ReactNode
  /**
   * 오류 화면. `reset`을 부르면 경계가 다시 자식을 그린다.
   *
   * **경계가 화면 모양을 정하지 않는다** — 루트(셸 밖)와 화면 단위(셸 안)는 쓸 수
   * 있는 것이 다르다. 루트에서는 라우터가 죽었을 수 있어 `window.location`을 써야
   * 하고, 화면 단위에서는 라우터 `Link`가 살아 있다.
   */
  fallback: (state: { error: Error; reset: () => void }) => ReactNode
  /** 진단용 이름. 콘솔에 어느 경계가 잡았는지 남긴다. */
  name: string
}

interface ErrorBoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    /*
     * **삼키지 않는다.** 화면은 사람이 읽을 문구를 보여 주지만, 개발자가 원인을
     * 찾으려면 스택과 컴포넌트 경로가 필요하다. 종전에는 경계가 없어 React가
     * 알아서 콘솔에 남겼는데, 경계를 두면 그것이 사라진다.
     */
    console.error(`[ErrorBoundary:${this.props.name}]`, error, info.componentStack)
  }

  private reset = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (error !== null) {
      return this.props.fallback({ error, reset: this.reset })
    }
    return this.props.children
  }
}

/**
 * 오류 화면의 공통 뼈대.
 *
 * ## 문구를 여기 한 곳에 모은다
 *
 * `#694`(에러 상태 패턴)가 아직 미결이고 `DESIGN_SYSTEM §16` 항목 8도 *「로딩·에러는
 * 여전히 미정이며 개발 임시안 유지」*다. 확정되면 **이 파일 하나만** 고치면 되도록
 * 문구와 배치를 여기 둔다 — 경계마다 따로 적으면 그때 일부가 남는다(`#164`가 단위
 * 리터럴에 대해 한 판단과 같다).
 *
 * ## 오류 원문을 화면에 싣는다
 *
 * 사용자가 그대로 읽을 문장은 아니지만, **시연·지원 상황에서 이 한 줄이 있으면
 * 원인이 즉시 잡힌다.** 숨기면 「그냥 오류가 났다」만 남는다. `<details>`로 접어
 * 두어 평소에는 보이지 않게 한다.
 */
export function ErrorScreen({
  error,
  actions,
}: {
  error: Error
  /** 이 오류 화면에서 사용자가 할 수 있는 행동. 경계가 정한다. */
  actions: ReactNode
}) {
  return (
    <section className="error-screen" role="alert" aria-labelledby="error-screen-title">
      <h2 id="error-screen-title" className="error-screen__title">
        화면을 표시하지 못했습니다
      </h2>
      <p className="error-screen__body">
        예상하지 못한 오류가 발생했습니다. 아래에서 다시 시도하거나 다른 화면으로
        이동해 주세요.
      </p>
      <div className="error-screen__actions">{actions}</div>
      <details className="error-screen__detail">
        <summary>오류 내용</summary>
        <pre className="error-screen__message">{error.message}</pre>
      </details>
    </section>
  )
}
