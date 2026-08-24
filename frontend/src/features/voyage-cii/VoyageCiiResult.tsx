import './VoyageCiiResult.css'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString, formatGrouped, formatPercent } from '../../display/format'
import {
  ciiUnit,
  displayWarnings,
  marginDisplay,
  riskLabel,
  warningMessage,
  type ResultState,
} from './resultRules'
import { GradeBadge } from '../../components/GradeBadge'
import { GradeScaleBar } from '../../components/GradeScaleBar'
import { gradeTargets } from './targetRules'
import { shipTypeLabel } from '../vessel-registration/shipTypes'
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
  /**
   * 마지막 계산 이후 입력이 바뀌었는가 (`#727`). 성공 상태에서만 뜻이 있다 —
   * 결과가 없으면 어긋날 대상도 없다.
   */
  stale?: boolean
}

export function VoyageCiiResult({ state, stale = false }: VoyageCiiResultProps) {
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

  return <SuccessResult response={state.response} stale={stale} />
}

/* ------------------------------------------------------------------ */

function SuccessResult({ response, stale }: { response: VoyageCiiResponse; stale: boolean }) {
  const data = response.data
  const unit = ciiUnit(data.transport_capacity_basis)
  const margin = marginDisplay(data.estimated_rating, data.next_worse_boundary_margin_ratio)
  const risk = riskLabel(data.risk_level)
  const warnings = displayWarnings(response.warnings)

  return (
    <section
      className={`voyage-cii-result${stale ? ' voyage-cii-result--stale' : ''}`}
      aria-live="polite"
    >
      <h2 className="card__title voyage-cii-result__title">
        계산 결과
        <span className="voyage-cii-result__title-en"> Result</span>
      </h2>

      {/*
        입력이 바뀌었는데 결과가 그대로 남아 있는 상태 (#727). 종전에는 표시가
        없어 **옛 입력으로 낸 숫자를 현재 조건의 답으로** 읽게 됐다.

        `role`을 붙이지 않는다 — 이 섹션이 이미 `aria-live`라 안내가 두 번 읽힌다.
      */}
      {stale ? (
        <p className="voyage-cii-result__stale">
          <strong>입력이 바뀌었습니다.</strong> 아래는 이전 입력으로 계산한 값입니다 —
          <strong> 계산하기</strong>를 다시 눌러 주세요.
        </p>
      ) : null}

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
          {/*
            라벨이 없으면 굵은 「해당 없음 — 최하위 등급」이 **등급 E 자체를
            설명하는 말**로 읽힌다 (#727). 실시간 CII 화면(`#725`)이 같은 값에
            같은 라벨을 쓴다 — 두 화면이 같은 지표를 다른 이름으로 부르지 않는다.
          */}
          <p className="voyage-cii-result__margin">
            <span className="voyage-cii-result__margin-label">다음 경계까지</span>
            {margin.text}
          </p>
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
          unit={DISPLAY_UNITS.co2}
        />
        <Metric
          label="연료 사용량"
          value={formatGrouped(data.fuel_consumption_ton, DISPLAY_DIGITS.fuelTon)}
          unit={DISPLAY_UNITS.fuel}
        />
        <Metric
          label="항해거리"
          value={formatGrouped(String(data.distance_nm), DISPLAY_DIGITS.distanceNm)}
          unit={DISPLAY_UNITS.distance}
        />
      </dl>

      {/*
        지표 격자 바로 아래 — 첫 칸이 「항차 조건 기준 예상 CII」다. 격자 안에
        끼우지 않은 것은 이 바가 한 지표의 부속이 아니라 **위 세 CII 값이 놓인
        축**이기 때문이다. 폭도 한 칸이 아니라 카드 전체를 써야 눈금이 읽힌다.
      */}
      <GradeScaleBar
        ratioToRequired={data.ratio_to_required}
        boundaries={response.parameters_used.rating_boundary}
        rating={data.estimated_rating}
        valueLabel={`${formatPercent(data.ratio_to_required)}%`}
        label="항차 조건 기준 예상 CII의 등급 스케일"
      />

      {/*
        「그래서 얼마나 줄여야 하나」 (#727). 이 화면은 **항해 전** 화면이라
        수치를 바꿀 여지가 아직 있고, 그 질문이 곧 이 화면을 여는 이유다.
        종전에는 「E입니다」에서 끝나 다음 행동이 화면 밖에 있었다.
      */}
      <GradeTargets
        data={data}
        boundary={response.parameters_used.rating_boundary}
        unit={unit}
      />

      {/* 「그 숫자가 어떻게 나왔나」 (#727) */}
      <CalculationBasisPanel response={response} />

      {/*
        면책은 화면 하단 배너 한 곳에서만 말한다 — `REFERENCE_ONLY`는 그 문구와
        같은 말이라 여기서 걸러 낸다. 나머지 경고는 그대로 싣는다.
      */}
      {warnings.length > 0 ? (
        <ul className="voyage-cii-result__warnings">
          {warnings.map((code) => (
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

/**
 * 목표 등급별 연료 상한 — `#727`.
 *
 * 값은 `targetRules.gradeTargets`가 만든다. 그 모듈의 헤더가 **왜 여기서만
 * 숫자 연산을 하는지**와 **왜 내림인지**를 설명한다.
 *
 * 가정을 표 아래가 아니라 **표 위**에 둔다. 「연료 445.6 t」를 먼저 읽고 나면
 * 그 뒤의 단서는 이미 받아들인 숫자에 붙는 각주로 읽힌다.
 */
function GradeTargets({
  data,
  boundary,
  unit,
}: {
  data: VoyageCiiResponse['data']
  boundary: VoyageCiiResponse['parameters_used']['rating_boundary']
  unit: string
}) {
  const targets = gradeTargets(data, boundary)
  if (targets.length === 0) return null

  return (
    <div className="voyage-cii-result__targets">
      <h3 className="voyage-cii-result__section-title">등급을 올리려면</h3>
      <p className="voyage-cii-result__targets-note">
        선박·거리·연도가 그대로일 때, <strong>모든 유종을 같은 비율로 줄인다고 가정</strong>한
        값입니다. 화면에서 계산한 참고값이며 규제 판정이 아닙니다.
      </p>
      <table className="voyage-cii-result__targets-table">
        <thead>
          <tr>
            <th scope="col">목표 등급</th>
            <th scope="col">CII 상한</th>
            <th scope="col">연료 상한</th>
            <th scope="col">감축량</th>
          </tr>
        </thead>
        <tbody>
          {targets.map((target) => (
            <tr key={target.rating}>
              <th scope="row">
                {/* §8 세 단 중 `sm` — 표 한 줄 안이라 `lg`는 행 높이를 밀어낸다. */}
                <GradeBadge
                  rating={target.rating}
                  size="sm"
                  label={`목표 등급 ${target.rating}`}
                />
              </th>
              <td>
                {target.boundaryCii}
                <span className="voyage-cii-result__cell-unit"> {unit}</span>
              </td>
              <td>
                {formatGrouped(target.allowedFuelTon, DISPLAY_DIGITS.fuelTon)}
                <span className="voyage-cii-result__cell-unit"> {DISPLAY_UNITS.fuel}</span>
              </td>
              <td>
                −{formatGrouped(target.reduceFuelTon, DISPLAY_DIGITS.fuelTon)}
                <span className="voyage-cii-result__cell-unit"> {DISPLAY_UNITS.fuel}</span>
                <span className="voyage-cii-result__cell-sub"> ({target.reducePercent}%)</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ */

/**
 * 계산 근거 — `#727`.
 *
 * 응답은 `calculation_basis`와 `parameters_used`로 **선종·기준선 계수·감축계수·
 * 유종별 CF·수송능력·파라미터 버전**을 이미 싣고 있었고 화면이 하나도 읽지 않았다.
 * 그래서 「CO₂ 2,400.0 tCO₂」가 어디서 나온 값인지 화면 안에 근거가 없었다.
 *
 * `<details>`로 접어 둔다 — 평소에는 결과를 가리지 않고, 물어보는 순간 펼친다.
 * 실시간 CII의 「산출 가정」(`#725`)과 같은 형태다.
 *
 * ## 자릿수를 함부로 정하지 않는다
 *
 * 기준선 계수 `a`·`c`와 연료 `CF`는 `DESIGN_SYSTEM §4.2` 자릿수 표에 없는 값이다.
 * 규제 파라미터를 그대로 보여 주는 자리이므로 **서버 문자열을 손대지 않는다** —
 * 여기서 반올림하면 근거를 대조하려는 사람에게 근거가 아닌 것을 보여 주게 된다.
 */
function CalculationBasisPanel({ response }: { response: VoyageCiiResponse }) {
  const data = response.data
  const basis = data.calculation_basis
  const parameters = response.parameters_used

  return (
    <details className="voyage-cii-result__basis">
      <summary className="voyage-cii-result__basis-summary">계산 근거</summary>

      <dl className="voyage-cii-result__basis-list">
        <div>
          <dt>선종</dt>
          <dd>{shipTypeLabel(basis.ship_type)}</dd>
        </div>
        <div>
          <dt>수송능력</dt>
          <dd>
            {formatGrouped(data.transport_capacity, DISPLAY_DIGITS.capacity)}{' '}
            {data.transport_capacity_basis}
          </dd>
        </div>
        <div>
          <dt>기준 용량</dt>
          <dd>
            {formatGrouped(data.reference_capacity, DISPLAY_DIGITS.capacity)}{' '}
            <span className="voyage-cii-result__cell-sub">
              ({data.reference_capacity_rule})
            </span>
          </dd>
        </div>
        <div>
          <dt>기준선 계수</dt>
          {/* required_cii = a × 기준용량^(−c) × (1 − Z/100) */}
          <dd>
            a {basis.a_decimal} · c {basis.c}
          </dd>
        </div>
        <div>
          <dt>감축계수 Z</dt>
          <dd>
            {formatDecimalString(basis.z_factor_percent, DISPLAY_DIGITS.percent)}%{' '}
            <span className="voyage-cii-result__cell-sub">
              ({parameters.regulation_year.year}년)
            </span>
          </dd>
        </div>
        <div>
          <dt>파라미터 버전</dt>
          <dd>{parameters.parameter_source_version}</dd>
        </div>
      </dl>

      {/*
        CO₂는 유종마다 CF가 달라 한 줄로 적을 수 없다. 표로 두면 「연료 × CF = CO₂」가
        행마다 눈으로 검산된다 — 이 블록이 답해야 하는 질문이 그것이다.
      */}
      <table className="voyage-cii-result__basis-table">
        <thead>
          <tr>
            <th scope="col">유종</th>
            <th scope="col">연료</th>
            <th scope="col">CF</th>
          </tr>
        </thead>
        <tbody>
          {basis.fuel_cf_details.map((detail) => (
            <tr key={detail.fuel_type}>
              <th scope="row">{detail.fuel_type}</th>
              <td>
                {formatGrouped(detail.fuel_ton, DISPLAY_DIGITS.fuelTon)}
                <span className="voyage-cii-result__cell-unit"> {DISPLAY_UNITS.fuel}</span>
              </td>
              <td>{detail.cf}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
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
