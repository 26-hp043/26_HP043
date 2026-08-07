import './VoyageCiiResult.css'
import { DISPLAY_DIGITS, formatDecimalString, formatGrouped, formatPercent } from './format'
import {
  ciiUnit,
  marginDisplay,
  riskLabel,
  warningMessage,
  type ResultState,
} from './resultRules'
import { GradeBadge } from '../../components/GradeBadge'
import type { VoyageCiiResponse } from './types'

/**
 * 기능① 결과 화면 (#136).
 *
 * ## 표시 규칙은 이 파일에 없다
 *
 * 자릿수·구분자는 `format.ts`, 단위·여유율·위험도·경고 문구는 `resultRules.ts`가
 * 소유한다. 이 컴포넌트는 그 결과를 배치할 뿐이다.
 *
 * ## Layer 1 값을 숫자로 되돌리지 않는다
 *
 * `parseFloat`·`Number`를 쓰지 않는다(`API_SPEC §1.7` `[ORACLE-C-1]`).
 * 문자열로 직렬화해 정밀도 손실을 막는 이유가 화면에서 되돌리면 사라진다.
 *
 * ## 근거 없는 표현을 쓰지 않는다
 *
 * 기능③(연간 시뮬레이터)과 누적 데이터가 없으므로 **「연말 예상 등급」·
 * 「현재 누적 기준」** 같은 표현을 쓰지 않는다. 등급은 **「참고 등급」**,
 * CII는 **「항차 조건 기준 예상 CII」**다. `estimated_rating`이라는 API 필드명은
 * 그대로 두고 화면 라벨만 바꾼다.
 *
 * ## 면책 배너는 여기서 렌더하지 않는다
 *
 * `DESIGN_SYSTEM §13` 🔒이 요구하는 것은 **상시 노출**이다. 이 컴포넌트 안에 두면
 * 계산 전·로딩·실패 상태에서 배너가 사라져 **안전장치가 결과 유무에 종속된다.**
 * 페이지가 항상 렌더하고 응답이 있을 때만 `disclaimer`를 넘긴다.
 */

interface VoyageCiiResultProps {
  state: ResultState
}

export function VoyageCiiResult({ state }: VoyageCiiResultProps) {
  if (state.status === 'idle') {
    return (
      <section className="voyage-cii-result voyage-cii-result--placeholder" aria-live="polite">
        <p className="voyage-cii-result__placeholder-text">
          항차 조건을 입력하고 <strong>계산하기</strong>를 누르면 결과가 표시됩니다.
        </p>
      </section>
    )
  }

  if (state.status === 'loading') {
    return (
      <section className="voyage-cii-result voyage-cii-result--placeholder" aria-live="polite">
        <p className="voyage-cii-result__placeholder-text">계산 중입니다…</p>
      </section>
    )
  }

  if (state.status === 'error') {
    return (
      <section className="voyage-cii-result voyage-cii-result--error" aria-live="assertive">
        <p className="voyage-cii-result__error-title">계산에 실패했습니다</p>
        <p className="voyage-cii-result__error-message">{state.message}</p>
      </section>
    )
  }

  return <SuccessResult response={state.response} />
}

/* ------------------------------------------------------------------ */

function SuccessResult({ response }: { response: VoyageCiiResponse }) {
  const data = response.data
  const unit = ciiUnit(data.transport_capacity_basis)
  const margin = marginDisplay(data.estimated_rating, data.next_worse_boundary_margin_ratio)
  const risk = riskLabel(data.risk_level)

  return (
    <section className="voyage-cii-result" aria-live="polite">
      <h2 className="voyage-cii-result__title">
        계산 결과
        <span className="voyage-cii-result__title-en"> Result</span>
      </h2>

      {/*
        DESIGN_SYSTEM §11 — 전면 추정 화면이므로 개별 점선 밑줄 대신 화면 단위 고지로
        갈음한다. 표시 수치가 전부 사용자 입력 기반 추정이라 개별 표기가 구분 정보를
        전달하지 못한다. 외부 데이터 출처가 없으므로 출처명 필드는 강제하지 않는다.
      */}
      <p className="voyage-cii-result__estimate-notice">
        이 화면의 수치는 모두 <strong>입력한 항차 조건에 기반한 추정값</strong>입니다.
        기준 시각은 계산을 실행한 시점입니다.
      </p>

      <div className="voyage-cii-result__grade-row">
        <GradeBadge rating={data.estimated_rating} label={`참고 등급 ${data.estimated_rating}`} />
        <div className="voyage-cii-result__grade-meta">
          <p className="voyage-cii-result__grade-label">참고 등급</p>
          <p className="voyage-cii-result__margin">{margin.text}</p>
          <p className="voyage-cii-result__risk">
            <span className="voyage-cii-result__risk-label">위험도</span>
            {risk.withIcon ? (
              // §2.5 (b) — 라벨이 항상 옆에 있으므로 aria-hidden. 아이콘에도
              // aria-label을 붙이면 「높음 HIGH 주의 필요」로 중복해 읽힌다.
              <span className="voyage-cii-result__risk-icon" aria-hidden="true">
                ⚠
              </span>
            ) : null}
            <span className={`voyage-cii-result__risk-value voyage-cii-result__risk-value--${data.risk_level.toLowerCase()}`}>
              {risk.text}
            </span>
          </p>
        </div>
      </div>

      <dl className="voyage-cii-result__metrics">
        <Metric
          label="항차 조건 기준 예상 CII"
          value={formatDecimalString(data.attained_cii, DISPLAY_DIGITS.cii)}
          unit={unit}
          emphasis
        />
        <Metric
          label="기준 CII"
          labelEn="required CII"
          value={formatDecimalString(data.required_cii, DISPLAY_DIGITS.cii)}
          unit={unit}
        />
        <Metric
          label="기준 대비 비율"
          value={`${formatPercent(data.ratio_to_required)}%`}
        />
        <Metric
          label="CO₂ 배출량"
          value={formatGrouped(data.co2_emission_ton, DISPLAY_DIGITS.co2Ton)}
          unit="t"
        />
        <Metric
          label="연료 사용량"
          value={formatGrouped(data.fuel_consumption_ton, DISPLAY_DIGITS.fuelTon)}
          unit="t"
        />
        <Metric
          label="항해거리"
          value={formatGrouped(String(data.distance_nm), DISPLAY_DIGITS.distanceNm)}
          unit="nm"
        />
      </dl>

      {response.warnings.length > 0 ? (
        <ul className="voyage-cii-result__warnings">
          {response.warnings.map((code) => (
            <li key={code} className="voyage-cii-result__warning">
              <span className="voyage-cii-result__warning-icon" aria-hidden="true">
                ⚠
              </span>
              {warningMessage(code)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

/* ------------------------------------------------------------------ */

interface MetricProps {
  label: string
  labelEn?: string
  value: string
  unit?: string
  emphasis?: boolean
}

function Metric({ label, labelEn, value, unit, emphasis }: MetricProps) {
  return (
    <div
      className={
        emphasis
          ? 'voyage-cii-result__metric voyage-cii-result__metric--emphasis'
          : 'voyage-cii-result__metric'
      }
    >
      <dt className="voyage-cii-result__metric-label">
        {label}
        {labelEn ? (
          <span className="voyage-cii-result__metric-label-en"> {labelEn}</span>
        ) : null}
      </dt>
      <dd className="voyage-cii-result__metric-value">
        {value}
        {unit ? <span className="voyage-cii-result__metric-unit"> {unit}</span> : null}
      </dd>
    </div>
  )
}
