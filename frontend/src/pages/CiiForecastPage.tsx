import { useState } from 'react'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { VoyageCiiForm } from '../features/voyage-cii/VoyageCiiForm'
import { VoyageCiiResult } from '../features/voyage-cii/VoyageCiiResult'
import type { ResultState } from '../features/voyage-cii/resultRules'
import './CiiForecastPage.css'

/**
 * UIFLOW §2-1 CII 예측 — 기능①이자 8/8 데모의 주 화면, 기본 진입 경로다.
 *
 * `#133`이 자리를 만들고 `#135`가 입력 폼을, `#136`이 결과 화면을 채웠다.
 *
 * ## 계산 상태를 페이지가 들고 있다
 *
 * 폼이 들고 있으면 결과 표시가 입력 컴포넌트에 종속된다. 페이지가 중개하면
 * 입력과 결과가 서로를 알지 않아도 된다 — `#138`이 provider를 실 API로 바꿔도
 * 이 구조는 그대로다.
 *
 * ## 면책 배너를 결과 안에 두지 않는다
 *
 * `DESIGN_SYSTEM §13` 🔒은 **상시 노출**을 요구한다. 결과 컴포넌트 안에 두면
 * 계산 전·로딩·실패에서 배너가 사라져 **안전장치가 결과 유무에 종속된다.**
 * 여기서 항상 렌더하고, 응답이 있을 때만 그 `disclaimer`를 넘긴다.
 * 값이 없으면 `DisclaimerBanner`가 `PRD §6.3` 기본 문구를 쓴다.
 */
export function CiiForecastPage() {
  const [result, setResult] = useState<ResultState>({ status: 'idle' })

  return (
    <div className="cii-forecast-page">
      <VoyageCiiForm onStateChange={setResult} />
      <VoyageCiiResult state={result} />
      <DisclaimerBanner
        text={result.status === 'success' ? result.response.disclaimer : undefined}
      />
    </div>
  )
}
