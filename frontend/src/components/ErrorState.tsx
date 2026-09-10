import type { ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import './ErrorState.css'
import { Icon } from './Icon'

/**
 * 실패 표시 — **화면 전체가 이 하나를 쓴다** (`#694` · 2026-09-10 디자인 확정).
 *
 * ## 왜 한 곳으로 모으는가
 *
 * 로딩과 빈 상태는 `#613`(`PR #614`)이 규격을 정했는데 **에러만 빠졌다.** 그 사이
 * 새 화면과 새 실패 경로가 계속 붙어 에러 표현 클래스가 **24종**이 됐다. 층위가
 * 정해지지 않으면 매번 「이건 어느 형태인가」를 판단해야 하고, 그 판단이 쌓인 결과다.
 *
 * ## 층위는 둘이다
 *
 * - `page` — 화면 전체가 뜨지 않았다. **재시도 필수**
 * - `region` — 이 영역이 실패했다. 목록 로드 실패와 **계산 실패가 같은 층위**다
 *
 * 종전에는 그 둘을 나눠 두었는데, 사용자 입장에서 둘 다 「이 영역이 실패했다」이고
 * **차이는 크기뿐**이다. 크기는 층위가 아니라 `size` 속성으로 다룬다.
 *
 * 필드 검증은 이 컴포넌트가 다루지 않는다 — **폼 규격 소관**이다.
 * CSV 행 오류 표도 대상이 아니다. 그것은 상태 표시가 아니라 **결과 데이터**다.
 *
 * ## 색면을 중립으로 뺀다
 *
 * BlueLog는 화면 어디서나 **색이 곧 등급을 뜻하는** 제품이다. 실패 표시가 커다란
 * 빨간 면적을 차지하면 토큰을 분리해도 사용자 눈에는 계속 등급 신호로 읽힌다 —
 * 실제로 종전 `.empty--error`가 **등급 E 토큰**(`--cii-e-*`)을 쓰고 있었고, 그 코드가
 * 살아 있는 화면이 하필 **등급을 보여 주는 선박 상세**였다.
 *
 * 배경·테두리는 중립, **아이콘과 문구만 위험색**이다. 색각 이상 사용자에게 아이콘이
 * 두 번째 단서가 되는 이점도 함께 온다(`§0.2` 제약 3).
 */
export function ErrorState({
  level,
  size = 'block',
  title,
  message,
  onRetry,
  action,
}: {
  level: 'page' | 'region'
  /** `region`에서만 뜻이 있다. 한 줄로 낼 때 `compact`. */
  size?: 'compact' | 'block'
  /** 없으면 층위 기본 제목을 쓴다. */
  title?: string
  message: string
  /**
   * 재시도 수단. **`page`에서는 필수다** — 없으면 사용자가 할 수 있는 것이
   * 브라우저 새로고침뿐이다. `region`은 다시 시도할 수 있는 실패일 때만 준다.
   */
  onRetry?: () => void
  /**
   * 재시도로는 풀리지 않는 실패의 다른 길 — 예: 없는 선박에서 「대시보드로」.
   *
   * 재시도와 **함께 두지 않는다.** 다시 시도해도 소용없는 실패에 재시도 버튼을
   * 두면 사용자가 같은 실패를 반복한다.
   */
  action?: ReactNode
}) {
  const compact = level === 'region' && size === 'compact'
  const heading = title ?? (level === 'page' ? '화면을 불러오지 못했습니다' : '불러오지 못했습니다')

  return (
    <div
      className={`error-state error-state--${level}${compact ? ' error-state--compact' : ''}`}
      role="alert"
    >
      <Icon glyph={AlertTriangle} className="error-state__icon" size={compact ? 16 : 20} />
      <div className="error-state__body">
        {/* compact는 제목을 두지 않는다 — 한 줄이 곧 제목이자 본문이다. */}
        {compact ? null : <p className="error-state__title">{heading}</p>}
        <p className="error-state__message">{message}</p>
      </div>
      {onRetry ? (
        // 문구는 하나다. 「다시 불러오기 / 다시 계산 / 재시도」로 갈리면 24종이 다시 생긴다.
        <button type="button" className="error-state__retry" onClick={onRetry}>
          다시 시도
        </button>
      ) : (
        action ?? null
      )}
    </div>
  )
}
