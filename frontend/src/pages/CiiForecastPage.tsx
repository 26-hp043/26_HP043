import { useState } from 'react'
import { DisclaimerBanner } from '../components/DisclaimerBanner'
import { PageHeader } from '../components/PageHeader'
import { VoyageCiiForm } from '../features/voyage-cii/VoyageCiiForm'
import { VoyageCiiResult } from '../features/voyage-cii/VoyageCiiResult'
import type { ResultState } from '../features/voyage-cii/resultRules'
import './CiiForecastPage.css'

/**
 * UIFLOW 2-1 CII 예측 — 기능①이자 8/8 데모의 주 화면, 기본 진입 경로다.
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
 *
 * ## 2단은 입력·결과만 감싼다
 *
 * 입력(5)과 결과(7)를 `__split`으로 묶고 **면책 배너는 그 밖에 둔다**(`§7.1`).
 * 배너를 한쪽 단에 넣으면 폭이 절반으로 줄고 다른 단 아래가 비며, 무엇보다
 * 두 단 모두에 걸리는 고지가 한쪽에 속한 것처럼 읽힌다. 배치는 CSS가 하므로
 * 이 래퍼 하나가 컴포넌트 쪽 변경의 전부다.
 */
export function CiiForecastPage() {
  const [result, setResult] = useState<ResultState>({ status: 'idle' })
  /*
   * 마지막 계산 이후 입력이 바뀌었는가 (#727). 결과와 마찬가지로 페이지가
   * 중개한다 — 폼이 결과 컴포넌트를 직접 알게 하지 않기 위해서다.
   */
  const [stale, setStale] = useState(false)

  return (
    <div className="cii-forecast-page">
      {/*
        「예상 등급」이라 쓰지 않는다 — 이 화면은 등급을 **「참고 등급」**으로 부른다
        (`VoyageCiiResult.tsx`). 결과 화면과 부제가 다른 말을 쓰면 같은 값이
        두 이름을 갖는다.
      */}
      <PageHeader screen="CII_FORECAST">
        <p className="page-head__sub">
          항해 전 항차 조건으로 CII와 참고 등급을 추정합니다.
        </p>
      </PageHeader>
      <div className="cii-forecast-page__split">
        <VoyageCiiForm onStateChange={setResult} onStaleChange={setStale} />
        <VoyageCiiResult state={result} stale={stale} />
      </div>
      <DisclaimerBanner
        text={result.status === 'success' ? result.response.disclaimer : undefined}
      />
    </div>
  )
}
