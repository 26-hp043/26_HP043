import { AlertTriangle } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import './VoyageCiiResult.css'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  formatDecimalString,
  formatGrouped,
  formatPercent,
  toDecimalInput,
} from '../../display/format'
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
import { VerdictStrip } from '../../components/VerdictStrip'
import { gradeTargets } from './targetRules'
import { shipTypeLabel } from '../vessel-registration/shipTypes'
import type { AnnualImpact, VoyageCiiResponse } from './types'
import { ErrorState } from '../../components/ErrorState'
import { Icon } from '../../components/Icon'
import { useShowsLabelEn } from '../../i18n/core'
import { regulationParametersPath } from '../parameters/referenceRules'

/**
 * 「연간 반영 시 변화」의 표시 값 — `PRD §10.4` 행 (`#1338`).
 *
 * 등급 **둘을 나란히** 보여 준다. 차이(Δ)를 숫자로 적지 않는 것은 그 값이
 * `attained_cii`의 차이이고, 사용자가 판단에 쓰는 것은 **등급**이기 때문이다.
 */
function annualImpactValue(impact: AnnualImpact): string {
  return `${impact.before.rating} → ${impact.after.rating}`
}

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
 * 이 화면은 **항차 한 건**의 추정이라 「연말 예상 등급」·「현재 누적 기준」이
 * 아니다. 등급은 **「참고 등급」**, CII는 **「항차 조건 기준 예상 CII」**다
 * (`PRD §10.4` 출력 표 — `estimated_rating` → `참고 등급`). API 필드명은 그대로 두고
 * 화면 라벨만 바꾼다.
 *
 * 종전 근거는 「기능③과 누적 데이터가 **없으므로**」(`#136`)였는데 둘 다 생겼다
 * (`#63` · `#353`). 표기는 그대로이고 근거만 `§10.4`로 옮겼다 (`#749`).
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
  /**
   * 「이 결과로」 — 결과 카드 끝에 둔다 (#1711). 종전에는 페이지가 결과 아래에 따로
   * 떠 있는 카드로 그렸다. 부품을 이 모듈이 알 필요는 없어 페이지가 넘긴다.
   */
  actions?: ReactNode
}

export function VoyageCiiResult({ state, stale = false, actions }: VoyageCiiResultProps) {
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
      <ErrorState level="region" action="계산" message={state.message} />
    )
  }

  return <SuccessResult response={state.response} stale={stale} actions={actions} />
}

/* ------------------------------------------------------------------ */

function SuccessResult({
  response,
  stale,
  actions,
}: {
  response: VoyageCiiResponse
  stale: boolean
  actions?: ReactNode
}) {
  const showsLabelEn = useShowsLabelEn()

  const data = response.data
  const unit = ciiUnit(data.transport_capacity_basis)
  const margin = marginDisplay(data.estimated_rating, data.next_worse_boundary_margin_ratio)
  const risk = riskLabel(data.risk_level)
  const warnings = displayWarnings(response.warnings)

  return (
    <div
      className={`voyage-cii-result-stack${stale ? ' voyage-cii-result-stack--stale' : ''}`}
      aria-live="polite"
    >
      {/*
        ── 결론 띠 (`DESIGN_SYSTEM §8.6` 🔒 · #1711) ─────────────────────

        이 화면의 답은 「이 항차는 C · 4.982, D까지 7.2% 여유」 한 줄이다. 종전에는 등급
        배지 옆에 참고 등급 · 다음 경계 · 위험도가 본문 크기로 붙고, 예상 CII는 아래 타일
        일곱 칸 중 첫 칸에 다른 수치와 같은 크기로 들어 있었다.

        주 결론의 이름은 「항차 조건 기준 예상 CII」 그대로다(#1338) — 아래 「연간 반영 시
        변화」와 다른 질문에 답한다는 구분을 띠에서도 지킨다.
      */}
      <VerdictStrip
        label="결론"
        main={{
          label: '항차 조건 기준 예상 CII',
          value: formatDecimalString(data.attained_cii, DISPLAY_DIGITS.cii),
          unit,
          rating: data.estimated_rating,
          ratingLabel: `참고 등급 ${data.estimated_rating}`,
        }}
        /*
          라벨이 없으면 굵은 「해당 없음 — 최하위 등급」이 **등급 E 자체를 설명하는 말**로
          읽힌다 (#727). 실시간 CII 화면(`#725`)이 같은 값에 같은 라벨을 쓴다.
        */
        sub={{ label: '다음 경계까지', value: margin.text }}
        risk={{ level: data.risk_level, heading: '위험도', ...risk }}
      />

      {/*
        입력이 바뀌었는데 결과가 그대로 남아 있는 상태 (#727). 종전에는 표시가
        없어 **옛 입력으로 낸 숫자를 현재 조건의 답으로** 읽게 됐다. 띠 바로 아래다.

        `role`을 붙이지 않는다 — 이 묶음이 이미 `aria-live`라 안내가 두 번 읽힌다.
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
        자리는 띠 바로 아래다(`§8.6` · #1578).
      */}
      <p className="voyage-cii-result__estimate-notice">
        이 화면의 수치는 모두 <strong>입력한 항차 조건에 기반한 추정값</strong>입니다.
        기준 시각은 계산을 실행한 시점입니다.
      </p>

      <section className="voyage-cii-result" aria-labelledby="voyage-cii-result-title">
        <h2 id="voyage-cii-result-title" className="card__title voyage-cii-result__title">
          계산 결과
          {showsLabelEn ? (
            <span className="voyage-cii-result__title-en" lang="en">
              {' '}
              Result
            </span>
          ) : null}
        </h2>

        {/*
          「라벨 · 값」 2열 목록 (`§5` 카드 예산 · #1711). 종전에는 타일 일곱 칸을 3열에
          놓아 마지막 줄에 「연간 반영 시 변화」 한 칸만 남았다. 예상 CII는 띠로 올라갔다.
        */}
        <dl className="voyage-cii-result__list">
          <Row
            label="기준 CII"
            labelEn="required CII"
            value={formatDecimalString(data.required_cii, DISPLAY_DIGITS.cii)}
            unit={unit}
          />
          <Row label="기준 대비 비율" value={`${formatPercent(data.ratio_to_required)}%`} />
          <Row
            label="CO₂ 배출량"
            value={formatGrouped(data.co2_emission_ton, DISPLAY_DIGITS.co2Ton)}
            unit={DISPLAY_UNITS.co2}
          />
          <Row
            label="연료 사용량"
            value={formatGrouped(data.fuel_consumption_ton, DISPLAY_DIGITS.fuelTon)}
            unit={DISPLAY_UNITS.fuel}
          />
          <Row
            label="항해거리"
            value={formatGrouped(toDecimalInput(data.distance_nm), DISPLAY_DIGITS.distanceNm)}
            unit={DISPLAY_UNITS.distance}
          />
          {/*
            「연간 반영 시 변화」 — `PRD §10.4` 출력 표의 행 (`#1338`).

            ⚠️ **위 값들과 다른 질문에 답한다.** 띠는 「이 항차 하나의 강도」이고
            이 줄은 「선박의 연말 값이 이 항차 때문에 어디로 가나」다 — **두 값이
            반대 방향을 가리키는 것이 정상**이므로 값 옆에 그 사실을 적는다.

            기초 자료가 없으면 서버가 `null`을 주고 **줄 자체를 그리지 않는다** —
            빈칸을 두면 「아직 안 온 값」으로 읽힌다(`#1097`과 같은 판단).
          */}
          {data.annual_impact !== null ? (
            <Row
              label="연간 반영 시 변화"
              value={annualImpactValue(data.annual_impact)}
              unit={data.annual_impact.rating_changed ? '등급 변동' : '등급 유지'}
            />
          ) : null}
        </dl>

        {/*
          목록 바로 아래 — 이 바는 한 값의 부속이 아니라 **예상 CII · 기준 CII가 놓인
          축**이다. 폭도 카드 전체를 써야 눈금이 읽힌다.
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
          표로 둔다 — 카드로 쪼개면 떠 있는 면이 늘어난다(`§5` · #1711).
        */}
        <GradeTargets
          data={data}
          boundary={response.parameters_used.rating_boundary}
          unit={unit}
        />

        {/*
          면책은 화면 하단 배너 한 곳에서만 말한다 — `REFERENCE_ONLY`는 그 문구와
          같은 말이라 여기서 걸러 낸다. 나머지 경고는 그대로 싣는다.
        */}
        {warnings.length > 0 ? (
          <ul className="voyage-cii-result__warnings">
            {warnings.map((code) => (
              <li key={code} className="voyage-cii-result__warning">
                <span className="voyage-cii-result__warning-icon">
                  <Icon glyph={AlertTriangle} size="inline" />
                </span>
                {warningMessage(code)}
              </li>
            ))}
          </ul>
        ) : null}

        {/*
          결과 카드의 마지막 줄 (#1711 ④ · #1786) — 「이 결과로」(#891 · `PRD §10.5`) 버튼
          줄과, **그 줄 오른쪽**의 「계산 근거」 접기(#727). 종전에는 접기가 버튼 줄 아래
          별도 블록이었고 카드 안에 회색 면을 가졌다(`§5` 카드 안 회색 타일 금지).
          열면 근거는 이 줄 아래 카드 전체 폭에 펼쳐진다 — 배치는 CSS `__footer` 격자가 한다.
        */}
        <div className="voyage-cii-result__footer">
          {actions}
          <CalculationBasisPanel response={response} />
        </div>
      </section>
    </div>
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
 * 접어 둔다 — 평소에는 결과를 가리지 않고, 물어보는 순간 펼친다.
 *
 * `<details>`가 아니라 `aria-expanded` 버튼 + 아래 영역이다 (#1786). 여는 줄은 「이 결과로」
 * 버튼 줄의 **오른쪽 끝**에 놓이고(#1711 ④) 펼친 내용은 그 줄 **아래 전체 폭**에 서야
 * 하는데, `<details>`는 요약과 내용이 한 상자라 둘을 다른 칸에 둘 수 없다. 같은 줄의
 * 「계획 저장」이 이미 이 형태다(`VoyageCiiActions.tsx`).
 *
 * ## 자릿수를 함부로 정하지 않는다
 *
 * 기준선 계수 `a`·`c`와 연료 `CF`는 `DESIGN_SYSTEM §4.2` 자릿수 표에 없는 값이다.
 * 규제 파라미터를 그대로 보여 주는 자리이므로 **서버 문자열을 손대지 않는다** —
 * 여기서 반올림하면 근거를 대조하려는 사람에게 근거가 아닌 것을 보여 주게 된다.
 */
const BASIS_PANEL_ID = 'voyage-cii-basis'

function CalculationBasisPanel({ response }: { response: VoyageCiiResponse }) {
  const [open, setOpen] = useState(false)
  const data = response.data
  const basis = data.calculation_basis
  const parameters = response.parameters_used

  return (
    <>
      <button
        type="button"
        className="voyage-cii-result__basis-toggle"
        aria-expanded={open}
        aria-controls={BASIS_PANEL_ID}
        onClick={() => setOpen((value) => !value)}
      >
        계산 근거
      </button>
      {/*
        컨테이너는 항상 렌더하고 `hidden`으로만 감춘다 (`#1786` 리뷰) — 닫힌 상태에서 이 id가
        DOM에 없으면 버튼의 `aria-controls`가 끊긴 참조가 된다. `AccountMenu.tsx`(#717) ·
        `VesselDetail.tsx`의 `NoVoyageDrill`(#759-776)과 같은 규약이다.
      */}
      <div
        id={BASIS_PANEL_ID}
        className="voyage-cii-result__basis"
        role="region"
        aria-label="계산 근거"
        hidden={!open}
      >
        {open ? (
          <>
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

            {/*
              이 패널은 **이 계산이 쓴** 값만 보인다. 다른 선종·연도의 값, 대체된 옛 판본, 원문
              표기(`a_raw`)는 설정의 「규제 기준값」 절에 있다 (#1516 · `#1239` 결정 B) — 대조하러
              온 사람이 여기서 막히지 않게 잇는다.
            */}
            <p className="voyage-cii-result__basis-link">
              <Link to={regulationParametersPath()}>규제 기준값 전체 보기</Link>
            </p>
          </>
        ) : null}
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ */
/**
 * 「라벨 · 값」 한 줄 (`DESIGN_SYSTEM §5` 카드 예산 · #1711).
 *
 * 종전 `Metric`은 회색 타일(면 + 테두리)이라 카드 안에 면을 또 띄웠다. 목록 한 줄로
 * 두고 구분선으로만 나눈다. `dl` 안의 `div` 묶음은 HTML이 허용하는 형태다.
 */
interface RowProps {
  label: string
  labelEn?: string
  value: string
  unit?: string
}

function Row({ label, labelEn, value, unit }: RowProps) {
  const showsLabelEn = useShowsLabelEn()

  return (
    <div className="voyage-cii-result__row">
      <dt>
        {label}
        {labelEn && showsLabelEn ? (
          <span className="voyage-cii-result__row-label-en" lang="en">
            {' '}
            {labelEn}
          </span>
        ) : null}
      </dt>
      <dd>
        <span className="voyage-cii-result__row-value">{value}</span>
        {unit ? <span className="voyage-cii-result__row-unit"> {unit}</span> : null}
      </dd>
    </div>
  )
}
