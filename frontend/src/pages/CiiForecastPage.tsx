import { useState } from 'react'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { VoyageCiiForm } from '../features/voyage-cii/VoyageCiiForm'
import type { VoyageCiiResponse } from '../features/voyage-cii/types'
import './CiiForecastPage.css'

/**
 * UIFLOW §2-1 CII 예측 — 기능①이자 8/8 데모의 주 화면, 기본 진입 경로다.
 *
 * `#133`이 자리를 만들고 `#135`가 입력 폼을 채웠다. **결과 표시는 `#136`이 붙인다.**
 *
 * 응답 상태를 폼이 아니라 이 페이지가 들고 있다. 폼이 결과까지 렌더하면 `#136`이
 * 같은 자리를 두고 겹치기 때문이다 — `#136`은 아래 자리 표시 블록을 결과 컴포넌트로
 * 바꾸기만 하면 된다.
 */
export function CiiForecastPage() {
  const [result, setResult] = useState<VoyageCiiResponse | null>(null)

  return (
    <div className="cii-forecast-page">
      <VoyageCiiForm onResult={setResult} />

      {/*
        결과 표시 자리 — #136 소관이라 여기서 값을 렌더하지 않는다.
        다만 아무것도 보여 주지 않으면 계산이 실행됐는지 화면에서 확인할 수 없어,
        경로가 동작했다는 사실만 남긴다. #136이 이 블록을 교체한다.
      */}
      {result ? (
        <p className="cii-forecast-page__pending" role="status">
          계산이 실행되었습니다. 결과 표시는 <strong>#136</strong>이 채웁니다.
          <span className="cii-forecast-page__run-id">{result.calculation_run_id}</span>
        </p>
      ) : null}

      <DisclaimerBanner />
    </div>
  )
}
