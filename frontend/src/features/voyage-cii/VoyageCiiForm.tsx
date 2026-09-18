import { useEffect, useMemo, useState, type FormEvent } from 'react'
import './VoyageCiiForm.css'
import {
  FIELD,
  initialFormState,
  toFormErrors,
  toRequest,
  validateForm,
  type FormErrors,
  sameInputs,
  type VoyageCiiFormState,
  pickDefaultYear,
} from './formRules'
import { DISPLAY_UNITS } from '../../display/format'
import { createVoyageCiiProvider } from './providerSelection'
import { useShellContext } from '../../layout/shellContext'
import { useYearOptions } from '../parameters/yearCatalog'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import type { ResultState } from './resultRules'
import { Field } from '../../components/Field'

/**
 * 기능① 항차 조건 입력 폼 (#135).
 *
 * **검증·변환 규칙은 이 파일에 없다** — `formRules.ts`의 순수 함수를 호출한다.
 * 이 컴포넌트가 하는 일은 상태 보관, 규칙 호출, 그 결과를 화면에 붙이는 것뿐이다.
 *
 * ## 선택지는 전부 provider 경계 뒤에 있다
 *
 * 선박은 **셸의 전역 컨텍스트**(#484 · #535), 연도는 `yearCatalog`(#534)가 맡는다.
 * 이 컴포넌트는 어느 쪽이 고정표이고 어느 쪽이 서버인지 알지 않는다. **연료만 아직 `formRules`의
 * 고정표를 읽는다** — `/parameters/fuel-types`가 이미 있으므로(`#444`) 옮길 수 있으나
 * 이번 이슈 범위 밖이다.
 *
 * ## 선박·연도를 왜 셀렉트로 두지 않는가
 *
 * 선택지가 **1개면 고정 표시, 2개 이상이면 셀렉트**로 렌더한다.
 * 항목이 하나뿐인 드롭다운은 사용자가 다른 선택이 가능한 것으로 오해하게 만든다
 * (#135 코멘트 2026-08-02). 그렇다고 값을 화면에 하드코딩하면 `#34` 회신으로 선박이
 * 늘 때 이 파일을 고쳐야 한다. **선택지는 `formRules`가 고정표에서 만들고, 개수에
 * 따라 렌더 방식만 갈린다** — 고정표에 행이 추가되면 화면이 저절로 셀렉트가 된다.
 *
 * ## 상태를 문자열로 들고 있는 이유
 *
 * `formRules.VoyageCiiFormState` 주석 참조 — 입력 도중의 중간 상태 때문이다.
 *
 * ## 결과는 부모가 보관한다
 *
 * `onStateChange`로 상태를 넘긴다. 결과 표시는 `VoyageCiiResult`(#136)가 맡는다.
 * 이 컴포넌트가 응답을 렌더하면 입력과 결과가 같은 자리를 두고 겹친다.
 *
 * ## 오류를 어디에 붙이는가
 *
 * | 종류 | 위치 |
 * |---|---|
 * | 입력 검증 실패 (필드별) | 해당 입력창 아래 |
 * | 입력 검증 실패 (폼 전체) | 폼 상단 배너 |
 * | provider 오류 중 필드가 있는 것 | 해당 입력창 아래 — 사용자가 고칠 수 있다 |
 * | provider 오류 중 필드가 없는 것 | **결과 영역의 실패 상태** |
 *
 * 마지막 줄이 중요하다. 폼 상단과 결과 영역 양쪽에 같은 메시지를 띄우면 사용자가
 * 두 개의 다른 문제로 읽는다. **고칠 수 있는 것은 입력 쪽, 계산 자체의 실패는
 * 결과 쪽**으로 나눈다.
 */

interface VoyageCiiFormProps {
  /** 계산 상태 변화. 결과 렌더는 `VoyageCiiResult`(#136)가 맡는다. */
  onStateChange?: (state: ResultState) => void
  /**
   * 마지막 계산 이후 입력이 바뀌었는지 (`#727`). 결과 카드가 옛 숫자를 현재
   * 조건의 답처럼 보여 주는 것을 막는다.
   */
  onStaleChange?: (stale: boolean) => void
}

const SHELL_VESSEL_MISSING = '상단바에서 고른 선박이 목록에 없어 첫 번째 선박으로 바꿨습니다. 확인해 주세요.'

export function VoyageCiiForm({ onStateChange, onStaleChange }: VoyageCiiFormProps) {
  // 연료 선택지도 선박·연도와 같은 경계 뒤에 둔다 (#542). 종전에는 `selectableFuels()`가
  // 고정표(`referenceTable.ts`)를 직행으로 읽어, 실 API 모드에서도 서버가 아는 연료와
  // 화면이 보여 주는 연료가 갈릴 수 있었다.
  const { fuels, loading: fuelsLoading, failed: fuelsFailed } = useFuelOptions()

  // 선박 선택은 **셸이 소유한다** (#484 · #535). 종전에는 이 폼이 자기 목록과
  // 선택을 따로 들고 있어, 상단바에서 배를 바꿔도 폼은 그대로였다.
  const shell = useShellContext()
  const { vessels, vesselsState, selectVesselId } = shell

  const [state, setState] = useState<VoyageCiiFormState>(initialFormState)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitting, setSubmitting] = useState(false)
  /*
   * 성공한 계산이 어떤 입력으로 나온 것인지 (`#727`). 결과 자체는 페이지가 들고
   * 있으므로 여기서는 **입력 쪽 사실**만 갖는다 — 폼이 결과를 알면 「입력과 결과가
   * 서로를 알지 않는다」는 이 화면의 구조가 무너진다.
   */
  const [submittedState, setSubmittedState] = useState<VoyageCiiFormState | null>(null)

  // 연도 선택지도 같은 경계 뒤에 둔다 (#534). 종전에는 `selectableYears()`가
  // 고정표를 직행으로 읽어, 실 API 모드에서 고정표에 없는 선박(= 벌크선 외 전부)이
  // 연도를 못 받아 계산 자체가 불가능했다.
  /*
   * 연도 선택지는 **공용 훅**이 받는다 (`#632`가 만든 것 · `#824` ⑴로 이관).
   *
   * 종전 자체 구현은 `if (!state.vesselId) return`으로 조기 반환하면서
   * `yearsLoading`을 `true`로 남겨 뒀다. 이 화면은 목록의 첫 배를 자동 선택하므로
   * 평시에는 드러나지 않지만, **선박이 0척이거나 `GET /vessels`가 실패하면** 같은
   * 영구 로딩이 된다 — 그때 「선박」 칸은 「등록된 선박이 없습니다」로 정확히
   * 안내하는데 바로 아래 「규제연도」만 영원히 로딩이라, **한 화면에서 두 칸이 다른
   * 사실을 말한다.** 공용 훅은 빈 `vesselId`에서 목록을 비우고 `loading`을 내린다.
   */
  const { years, loading: yearsLoading, failed: yearsFailed } = useYearOptions(state.vesselId)

  // demo ↔ 실 API 전환은 providerSelection이 판단한다(#138). 화면은 어느 쪽이
  // 선택됐는지 알지 않는다 — 그것이 #134가 provider 경계를 그은 이유다.
  const provider = useMemo(() => createVoyageCiiProvider(), [])

  /**
   * 셸의 선택을 폼 상태에 반영한다 (#535).
   *
   * **폼은 선박을 「소유」하지 않고 셸의 값을 따라간다.** 상단바에서 배를 바꾸면
   * 주소가 바뀌고, 그 주소가 셸을 거쳐 여기로 돌아온다.
   *
   * 셸에 선택이 없으면 **목록의 첫 배를 골라 셸에 알린다.** 폼만 몰래 정하면
   * 상단바는 「선택 안 함」인데 폼은 특정 배로 계산하는, `#535`가 지적한 어긋남이
   * 그대로 남는다. `#543`(초기값이 고정표 UUID라 서버에 없는 배를 가리킨다)도
   * 이 경로로 함께 해소된다 — 첫 배는 항상 서버 목록에서 고른다.
   */
  const shellVesselId = shell.vesselId
  /** 상단바가 기억한 선박이 목록에 없을 때의 안내 (`#1097` ⑵). 사용자가 배를 고르면 지운다. */
  const [vesselNotice, setVesselNotice] = useState<string | null>(null)
  useEffect(() => {
    if (shellVesselId !== null) {
      // 목록에 없는 선박(삭제됨)이면 첫 배로 바꾸고 안내한다 — 그 id로 계산하지 않는다 (#1097 ⑵).
      if (vessels.length > 0 && !vessels.some((vessel) => vessel.id === shellVesselId)) {
        setVesselNotice(SHELL_VESSEL_MISSING)
        selectVesselId(vessels[0].id)
        return
      }
      setState((prev) => (prev.vesselId === shellVesselId ? prev : { ...prev, vesselId: shellVesselId }))
      return
    }
    if (vessels.length > 0) selectVesselId(vessels[0].id)
  }, [shellVesselId, vessels, selectVesselId])

  /*
   * 목록이 오면 기본 선택을 맞춘다 (`ScenarioComparison`과 같은 형태).
   *
   * `pickDefaultYear`가 정한다 — 이미 고른 해는 유지하고, 없으면 올해를, 올해가
   * 목록에 없으면 가장 최근 해를 고른다.
   *
   * 올해를 **여기서 읽어** 순수 함수에 넘긴다. 함수 안에서 `new Date()`를 부르면
   * 검사가 해를 고정할 수 없다. 이 값은 셀렉트의 초기 선택을 정할 뿐이고 **서버로
   * 가는 것은 사용자가 고른 값**이다(함수 주석 참조).
   */
  useEffect(() => {
    if (years.length === 0) return
    const thisYear = new Date().getFullYear()
    setState((prev) => {
      const next = pickDefaultYear(years, thisYear, prev.regulationYear)
      return next === prev.regulationYear ? prev : { ...prev, regulationYear: next }
    })
  }, [years])

  const selectedVessel = vessels.find((v) => v.id === state.vesselId)

  /** 한 필드를 갱신하고 그 필드의 오류만 지운다. 다른 필드의 오류는 그대로 둔다. */
  /*
   * 마지막 계산 이후 입력이 바뀌었는가 (#727).
   *
   * 렌더 중에 계산하고 효과로 알린다 — `update`마다 부모를 부르면 「어긋났다」를
   * 알리는 책임이 입력 처리기 여섯 군데로 흩어지고, 셸이 선박을 바꿔 폼이
   * 갱신되는 경로(위 효과)는 `update`를 거치지 않아 그 방식으로는 누락된다.
   */
  const stale = submittedState !== null && !sameInputs(submittedState, state)

  useEffect(() => {
    onStaleChange?.(stale)
  }, [stale, onStaleChange])

  function update<K extends keyof VoyageCiiFormState>(
    key: K,
    value: VoyageCiiFormState[K],
    field?: string,
  ) {
    setState((prev) => ({ ...prev, [key]: value }))
    if (field) {
      setErrors((prev) => {
        if (!(field in prev)) return prev
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  /**
   * 선박을 바꾼다. **폼 상태를 직접 고치지 않고 셸에 알린다** (#535).
   *
   * 셸이 주소를 갱신하면 위 효과가 그 값을 받아 폼에 반영한다. 여기서 `setState`를
   * 직접 하면 폼만 바뀌고 상단바는 그대로여서, 고치려는 어긋남을 반대 방향으로
   * 다시 만든다.
   *
   * 연도도 여기서 정하지 않는다 — `vesselId`가 바뀌면 연도 효과가 다시 돈다(`#534`).
   */
  function changeVessel(vesselId: string) {
    shell.selectVesselId(vesselId)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    const found = validateForm(state, fuels)
    setErrors(found)
    if (Object.keys(found).length > 0) {
      onStateChange?.({ status: 'idle' })
      // 결과가 사라지므로 「어긋났다」고 말할 대상도 없다 (#727).
      setSubmittedState(null)
      return
    }

    setSubmitting(true)
    onStateChange?.({ status: 'loading' })
    try {
      const request = toRequest(state)
      const response = await provider.estimate(request)
      onStateChange?.({ status: 'success', response, request })
      /*
       * `state`가 아니라 이 시점의 값을 그대로 담는다. 요청을 보내는 동안
       * 사용자가 입력을 고쳤을 수 있고, 그러면 결과는 **보낸 값**의 답이다.
       */
      setSubmittedState(state)
    } catch (error) {
      // provider 검증은 화면 검증의 방어선이다. 여기 도달하면 두 규칙이 어긋난 것이다.
      const mapped = toFormErrors(error)
      if (FIELD.form in mapped) {
        // 입력창에 붙일 수 없는 오류는 결과 영역의 실패 상태로 보낸다.
        onStateChange?.({ status: 'error', message: mapped[FIELD.form] })
      } else {
        setErrors(mapped)
        onStateChange?.({ status: 'idle' })
      }
      setSubmittedState(null)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="voyage-cii-form" onSubmit={handleSubmit} noValidate>
      <h2 className="card__title voyage-cii-form__title">
        항차 조건 입력
        <span className="voyage-cii-form__title-en"> Voyage Input</span>
      </h2>

      {/*
        입력창에 붙지 않는 오류는 폼 상단에 둔다 (`DESIGN_SYSTEM §8.4` 예외 조항).
        선박·규제연도가 여기 오는 이유는 **그 칸이 셀렉트가 아닐 수 있기** 때문이다 —
        1척이거나 목록을 못 읽으면 고정 표시가 되어 오류를 붙일 입력창이 없다.
        세 줄을 각자 내는 것은 `#1093` ⑶ — 한 칸을 돌려 쓰다 선박 오류가 사라졌다.
      */}
      {[FIELD.form, FIELD.vesselId, FIELD.regulationYear].map((key) =>
        errors[key] ? (
          <p key={key} className="voyage-cii-form__form-error" role="alert">
            {errors[key]}
          </p>
        ) : null,
      )}

      <div className="voyage-cii-form__grid">
        {/* 선박 — 1척이면 고정 표시, 2척 이상이면 셀렉트 */}
        {vesselsState === 'loading' ? (
          <StaticField label="선박" labelEn="Vessel" value="선박 목록을 불러오는 중…" />
        ) : vesselsState === 'failed' ? (
          <StaticField label="선박" labelEn="Vessel" value="선박 목록을 불러오지 못했습니다" />
        ) : vessels.length > 1 ? (
          <Field id="vessel" label="선박" labelEn="Vessel">
            {/*
              안내(`SHELL_VESSEL_MISSING`)를 컨트롤과 함께 돌려준다. 검증 오류도
              정적 힌트도 아닌 **상태 변경 알림**이라 `Field`의 `error`·`hint` 어느
              자리도 아니다 — 원래 위치(셀렉트 바로 아래)와 `role="alert"`를 지킨다.
            */}
            {(control) => (
              <>
              <select
                {...control}
                className="voyage-cii-form__control"
                value={state.vesselId}
                onChange={(e) => {
                  setVesselNotice(null)
                  changeVessel(e.target.value)
                }}
              >
                {vessels.map((vessel) => (
                  <option key={vessel.id} value={vessel.id}>
                    {vessel.displayName}
                  </option>
                ))}
              </select>
              {vesselNotice !== null ? (
                <p className="voyage-cii-form__hint" role="alert">
                  {vesselNotice}
                </p>
              ) : null}
              </>
            )}
          </Field>
        ) : (
          <StaticField
            label="선박"
            labelEn="Vessel"
            value={selectedVessel?.displayName ?? '등록된 선박이 없습니다'}
          />
        )}

        {/* 규제연도 — 선박과 같은 규칙. 로딩·실패를 빈 선택지와 구분해 보인다 */}
        {state.vesselId === '' ? (
          /*
           * ⚠️ **「선박을 아직 안 골랐다」와 「그 선박에 연도가 없다」는 다르다**
           * (`#1093` ⑶ · `#829` 계열).
           *
           * `useYearOptions`는 선박이 없으면 **조회하지 않고** 빈 목록을 돌려준다
           * (`yearCatalog.ts`의 「빈 `vesselId`에서는 부르지 않는다」). 그래서 이
           * 칸은 마지막 갈래로 떨어져 「등록된 규제연도가 없습니다」를 말했는데
           * **사실이 아니다** — 연도는 등재돼 있고 선박을 고르지 않았을 뿐이다.
           *
           * 항로 비교 화면(`ScenarioComparison.tsx`)과 보고서 화면(`ReportsView`)이
           * 이미 같은 구분을 하고 있다. 문구도 그쪽 것을 그대로 쓴다.
           */
          <StaticField label="규제연도" labelEn="Year" value="선박을 먼저 선택해 주세요" />
        ) : yearsLoading ? (
          <StaticField label="규제연도" labelEn="Year" value="규제연도 목록을 불러오는 중…" />
        ) : yearsFailed ? (
          <StaticField label="규제연도" labelEn="Year" value="규제연도 목록을 불러오지 못했습니다" />
        ) : years.length > 1 ? (
          <Field id="year" label="규제연도" labelEn="Year">
            {(control) => (
              <select
                {...control}
                className="voyage-cii-form__control"
                value={state.regulationYear}
                onChange={(e) => update('regulationYear', e.target.value)}
              >
                {years.map((year) => (
                  <option key={year} value={String(year)}>
                    {year}
                  </option>
                ))}
              </select>
            )}
          </Field>
        ) : (
          /*
           * 목록이 비었을 때의 문구 (#534).
           *
           * 종전 문구는 「지원 연도가 없습니다」였다. 연도 파라미터가 없다는 뜻으로
           * 읽히는데 실제 원인은 그게 아니었고, 그 오독이 #534 본문의 원인 추정을
           * 그대로 만들어 냈다 — 없는 백엔드 작업이 P0로 등재됐다.
           *
           * 이제 이 자리가 비는 경우는 `regulation_year` 테이블이 실제로 비어 있을
           * 때뿐이므로 그렇게 적는다. **선종별 기준선 부재는 여기서 드러나지 않는다**
           * — Z계수는 전 선종 공통이라 연도 목록은 채워지고, 기준선이 없는 선박은
           * 계산 실행 시 서버가 「선종의 기준선이 없습니다: <선종>」을 돌려준다
           * (`services/voyage_cii.py`). 그 메시지는 `toVoyageCiiError` →
           * `toFormErrors`를 거쳐 결과 영역의 실패 상태로 그대로 표시된다.
           */
          <StaticField
            label="규제연도"
            labelEn="Year"
            value={state.regulationYear || '등록된 규제연도가 없습니다'}
          />
        )}

        <Field
          id="distance"
          label="항해거리"
          labelEn="Distance"
          unit={DISPLAY_UNITS.distance}
          error={errors[FIELD.distanceNm]}
        >
          {(control) => (
            <input
              {...control}
              className="voyage-cii-form__control"
              type="number"
              inputMode="decimal"
              min="0"
              step="any"
              value={state.distanceNm}
              onChange={(e) => update('distanceNm', e.target.value, FIELD.distanceNm)}
            />
          )}
        </Field>

        {/*
          속력은 이 화면의 CII를 바꾸지 않는다 — `attained = CO₂ / (capacity × distance)`이고
          CO₂는 연료량에서 온다. **그러나 「결과를 바꾸지 않는다」로만 적으면 틀린 안내다**
          (`#1263`). `actionRules.ts`의 「계획 저장」이 이 값을 `plannedSpeedKn`으로 옮기고
          **도착 예정 시각까지 이 값으로 정한다.** 그 계획 속력은 연간 시뮬레이션의 속도
          민감도와 감속 시나리오가 다시 쓴다 — 임의값을 넣어도 된다고 읽히면 그 값이
          거기까지 흘러간다.

          ⚠️ **상한 검증은 여기 없다.** `PRD §9.1` VAL-009가 하한(`≥ 1.0`)만 규정하고
          프론트·서버 모두 그대로 구현했다. 상한은 정본에 값이 생긴 뒤에야 내려온다
          (`AGENTS §6` — 수치를 임의로 재작성하지 않는다). 후속 이슈에서 다룬다.
        */}
        <Field
          id="speed"
          label="평균 속력"
          labelEn="Speed"
          unit={DISPLAY_UNITS.speed}
          error={errors[FIELD.speedKn]}
          hint="이 화면의 CII 값은 연료량과 거리가 정하므로 속력만 바꿔도 같습니다. 다만 「계획 저장」을 하면 이 값이 계획 속력이 되고 도착 예정 시각을 정합니다 — 실제 운항 속력을 넣어 주세요."
        >
          {(control) => (
            <input
              {...control}
              className="voyage-cii-form__control"
              type="number"
              inputMode="decimal"
              min="1"
              step="any"
              value={state.speedKn}
              onChange={(e) => update('speedKn', e.target.value, FIELD.speedKn)}
            />
          )}
        </Field>

        {/* 연료 종류 — 규제연도와 같은 규칙. 로딩·실패를 빈 선택지와 구분해 보인다 (#542) */}
        {fuelsLoading ? (
          <StaticField label="연료 종류" labelEn="Fuel Type" value="연료 목록을 불러오는 중…" />
        ) : fuelsFailed ? (
          <StaticField label="연료 종류" labelEn="Fuel Type" value="연료 목록을 불러오지 못했습니다" />
        ) : (
          <Field
            id="fuel-type"
            label="연료 종류"
            labelEn="Fuel Type"
            error={errors[FIELD.fuelType]}
          >
            {(control) => (
              <select
                {...control}
                className="voyage-cii-form__control"
                value={state.fuelType}
                onChange={(e) => update('fuelType', e.target.value, FIELD.fuelType)}
              >
                <option value="">선택해 주세요</option>
                {fuels.map((fuel) => (
                  <option key={fuel.code} value={fuel.code}>
                    {fuelTypeOptionText(fuel.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}

        <Field
          id="fuel-ton"
          label="연료 사용량"
          labelEn="Fuel Consumption"
          unit={DISPLAY_UNITS.fuel}
          error={errors[FIELD.fuelTon]}
        >
          {(control) => (
            <input
              {...control}
              className="voyage-cii-form__control"
              type="number"
              inputMode="decimal"
              min="0"
              step="any"
              value={state.fuelTon}
              onChange={(e) => update('fuelTon', e.target.value, FIELD.fuelTon)}
            />
          )}
        </Field>
      </div>

      <button className="voyage-cii-form__submit" type="submit" disabled={submitting}>
        {submitting ? '계산 중…' : '계산하기'}
      </button>
    </form>
  )
}

/* ------------------------------------------------------------------ */

interface StaticFieldProps {
  label: string
  labelEn: string
  value: string
}

/**
 * 선택지가 하나뿐인 항목의 고정 표시.
 *
 * 컨트롤을 두지 않는다 — 항목이 하나뿐인 드롭다운은 다른 선택이 가능한 것으로
 * 오해하게 만든다(#135 코멘트). 값은 요청에 그대로 실린다.
 */
function StaticField({ label, labelEn, value }: StaticFieldProps) {
  return (
    <div className="voyage-cii-form__field">
      <p className="voyage-cii-form__label">
        {label}
        <span className="voyage-cii-form__label-en"> {labelEn}</span>
      </p>
      <p className="voyage-cii-form__static">{value}</p>
    </div>
  )
}
