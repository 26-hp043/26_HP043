// @vitest-environment jsdom
import '../test/renderSetup'


import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ErrorBoundary, ErrorScreen } from './ErrorBoundary'
import { formatCapacity } from '../display/format'

/**
 * 렌더 예외가 앱을 백지로 만들지 않는다 (`#823`).
 *
 * ## 무엇이 문제였나
 *
 * 앱 전체에 에러 경계가 하나도 없었다. **React 19는 렌더 예외에서 루트를
 * 언마운트**하므로 `#root`가 비어 완전 백지가 되고, 새로고침해도 같은 지점에서
 * 다시 던져 복구되지 않았다. 사용자가 빠져나올 길은 URL 직접 입력뿐이었다.
 *
 * 그런데 표시 포매터는 **던지도록 설계돼 있다** — 조용한 폴백이 틀린 값을 숨기기
 * 때문이다(`#823` 판정). 던지는 것이 문제가 아니라 **받는 곳이 없는 것**이 문제였다.
 */

/** 렌더 중 던지는 컴포넌트. `throw`는 렌더 단계여야 경계가 잡는다. */
function Boom({ message = '터졌다' }: { message?: string }): never {
  throw new Error(message)
}

/** 재현 케이스와 같은 경로 — 포매터가 실제로 던지는 값을 쓴다. */
function CapacityCell({ value }: { value: number }) {
  return <span>{formatCapacity(value)}</span>
}

function withBoundary(children: React.ReactNode, key?: string) {
  return (
    <ErrorBoundary
      key={key}
      name="test"
      fallback={({ error, reset }) => (
        <ErrorScreen
          error={error}
          actions={
            <button type="button" onClick={reset}>
              다시 시도
            </button>
          }
        />
      )}
    >
      {children}
    </ErrorBoundary>
  )
}

beforeEach(() => {
  // React가 경계로 잡힌 예외를 콘솔에 남긴다 — 검사 출력이 그것으로 덮이지 않게 한다.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('렌더 예외를 받아 화면을 남긴다 (#823)', () => {
  it('자식이 던지면 오류 화면을 그린다 — 백지가 되지 않는다', () => {
    render(withBoundary(<Boom />))

    expect(screen.getByText('화면을 표시하지 못했습니다')).toBeTruthy()
    // 사용자가 다음에 무엇을 할지 알 수 있어야 한다.
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
  })

  it('오류 원문을 화면에 남긴다 — 「그냥 오류가 났다」로 끝내지 않는다', () => {
    render(withBoundary(<Boom message="십진 문자열이 아닙니다: &quot;1e-7&quot;" />))

    // 시연·지원 상황에서 이 한 줄이 원인을 즉시 가른다. `<details>`로 접혀 있다.
    expect(screen.getByText(/십진 문자열이 아닙니다/)).toBeTruthy()
  })

  it('던지지 않으면 자식을 그대로 그린다', () => {
    render(withBoundary(<span>정상</span>))

    expect(screen.getByText('정상')).toBeTruthy()
    expect(screen.queryByText('화면을 표시하지 못했습니다')).toBeNull()
  })

  it('`role="alert"`로 낸다 — 스크린리더가 즉시 읽는다', () => {
    render(withBoundary(<Boom />))

    expect(screen.getByRole('alert')).toBeTruthy()
  })
})

describe('재현 케이스 — 1e-7 DWT (#823)', () => {
  /*
   * 이슈의 재현 절차: 재화중량톤수에 `0.0000001`을 넣은 선박을 등록하면
   * 목록·상세가 앱을 통째로 죽였다. 서버는 `Field(gt=0)`뿐이라 그 값을 받는다.
   */
  it('포매터가 실제로 던진다 — 이 검사의 전제', () => {
    expect(() => formatCapacity(1e-7)).toThrow(TypeError)
    expect(() => formatCapacity(1e21)).toThrow(TypeError)
  })

  it('그 값이 화면에 와도 오류 화면으로 끝난다', () => {
    render(withBoundary(<CapacityCell value={1e-7} />))

    expect(screen.getByText('화면을 표시하지 못했습니다')).toBeTruthy()
  })

  it('경계 바로 아래 값은 던지지 않는다 — 폴백을 두지 않은 근거', () => {
    /*
     * `formatCapacity(0.000001)`은 `0`을 낸다. 조용한 폴백을 두면 `1e-7`도 `0`이나
     * `—`가 되어 **사용자가 그것을 실제 값이라고 믿는다.** 던지는 설계를 유지한
     * 이유가 이것이다 (`#823` 판정).
     */
    expect(formatCapacity(0.000001)).toBe('0')
  })
})

describe('경계는 스스로 리셋되지 않는다 (#823)', () => {
  it('`reset`을 부르면 다시 자식을 그린다', () => {
    let shouldThrow = true
    function Flaky() {
      if (shouldThrow) throw new Error('일시적')
      return <span>회복됨</span>
    }

    render(withBoundary(<Flaky />))
    expect(screen.getByText('화면을 표시하지 못했습니다')).toBeTruthy()

    shouldThrow = false
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))

    expect(screen.getByText('회복됨')).toBeTruthy()
  })

  it('원인이 그대로면 다시 오류 화면이다 — 「고쳐진 척」하지 않는다', () => {
    render(withBoundary(<Boom />))
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))

    expect(screen.getByText('화면을 표시하지 못했습니다')).toBeTruthy()
  })

  it('`key`가 바뀌면 새 인스턴스가 만들어져 회복된다 — 셸의 경로 전환이 이 성질을 쓴다', () => {
    /*
     * `AppShell`이 `key={pathname}`을 준다. 이것이 없으면 한 화면이 깨진 뒤
     * **사이드바를 눌러도 오류 화면이 남아** 사용자 입장에서는 백지와 같다.
     */
    const { rerender } = render(withBoundary(<Boom />, '/vessels'))
    expect(screen.getByText('화면을 표시하지 못했습니다')).toBeTruthy()

    rerender(withBoundary(<span>다른 화면</span>, '/dashboard'))

    expect(screen.getByText('다른 화면')).toBeTruthy()
    expect(screen.queryByText('화면을 표시하지 못했습니다')).toBeNull()
  })
})

describe('진단 정보를 삼키지 않는다 (#823)', () => {
  it('콘솔에 경계 이름과 오류를 남긴다', () => {
    /*
     * 경계를 두면 React가 자동으로 남기던 콘솔 출력이 사라진다. 화면 문구는
     * 사람용이고, 개발자는 스택과 컴포넌트 경로가 필요하다.
     */
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(withBoundary(<Boom message="원인" />))

    const logged = spy.mock.calls.map((args) => String(args[0]))
    expect(logged.some((line) => line.includes('[ErrorBoundary:test]'))).toBe(true)
  })
})
