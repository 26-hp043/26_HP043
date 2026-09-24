import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import './VoyageCiiForm.css'
import {
  FIELD,
  initialFormState,
  prefillFromVoyage,
  toFormErrors,
  toRequest,
  validateForm,
  type FormErrors,
  sameInputs,
  type VoyageCiiFormState,
  pickDefaultYear,
  effectiveFuelTon,
  voyageHours,
  type FuelInputMode,
} from './formRules'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  DISPLAY_UNIT_DAILY_FUEL,
  formatDecimalString,
  formatGrouped,
  toDecimalInput,
} from '../../display/format'
import { fetchVoyage } from '../voyage-management/apiProvider'
import { STATUS_LABELS } from '../voyage-management/voyageRules'
import type { ManagedVoyage } from '../voyage-management/types'
import { createVoyageCiiProvider } from './providerSelection'
import { useShellContext } from '../../layout/shellContext'
import { useYearOptions } from '../parameters/yearCatalog'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import type { ResultState } from './resultRules'
import { Field } from '../../components/Field'
import { useShowsLabelEn } from '../../i18n/core'
import { publishScreenResult } from '../assistant/screenResult'

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
  /** 상단에서 고른 항차 한 건을 읽는다 (#1576). 검사가 대역을 넣는 자리다. */
  loadVoyage?: (voyageId: string) => Promise<ManagedVoyage>
}

const SHELL_VESSEL_MISSING = '상단바에서 고른 선박이 목록에 없어 첫 번째 선박으로 바꿨습니다. 확인해 주세요.'

export function VoyageCiiForm({
  onStateChange,
  onStaleChange,
  loadVoyage = fetchVoyage,
}: VoyageCiiFormProps) {
  const showsLabelEn = useShowsLabelEn()

  // 연료 선택지도 선박·연도와 같은 경계 뒤에 둔다 (#542). 종전에는 `selectableFuels()`가
  // 고정표(`referenceTable.ts`)를 직행으로 읽어, 실 API 모드에서도 서버가 아는 연료와
  // 화면이 보여 주는 연료가 갈릴 수 있었다.
  const { fuels, loading: fuelsLoading, failed: fuelsFailed } = useFuelOptions()

  // 선박 선택은 **셸이 소유한다** (#484 · #535). 종전에는 이 폼이 자기 목록과
  // 선택을 따로 들고 있어, 상단바에서 배를 바꿔도 폼은 그대로였다.
  const shell = useShellContext()
  const { vessels, vesselsState, selectVesselId } = shell

  /**
   * 입력한 그대로의 폼. 화면·검증·요청에 쓰는 것은 아래 `state`다 — 규제연도만 목록과
   * 대조해 렌더 중에 정한다(`#1616`). 갱신은 전부 `setState((prev) => …)`라 원본을 다룬다.
   */
  const [rawState, setState] = useState<VoyageCiiFormState>(initialFormState)
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
  const { years, loading: yearsLoading, failed: yearsFailed } = useYearOptions(rawState.vesselId)

  /*
   * 기본 연도는 **렌더 중에 파생**한다 (`#1616` · `ScenarioComparison`과 같은 형태).
   * 종전에는 목록이 오면 effect가 상태를 채워, 목록 도착과 기본값 사이에 연도가 빈
   * 렌더가 한 번 있었다.
   *
   * `pickDefaultYear`가 정한다 — 이미 고른 해는 유지하고, 없으면 올해를, 올해가
   * 목록에 없으면 가장 최근 해를 고른다. 목록이 비어 있으면 입력값을 그대로 둔다.
   *
   * 올해를 **여기서 읽어** 순수 함수에 넘긴다. 함수 안에서 `new Date()`를 부르면
   * 검사가 해를 고정할 수 없다. 이 값은 셀렉트의 선택을 정할 뿐이고 **서버로
   * 가는 것은 사용자가 고른 값**이다(함수 주석 참조).
   */
  const regulationYear =
    years.length === 0
      ? rawState.regulationYear
      : pickDefaultYear(years, new Date().getFullYear(), rawState.regulationYear)
  const state = useMemo(
    () => (regulationYear === rawState.regulationYear ? rawState : { ...rawState, regulationYear }),
    [rawState, regulationYear],
  )

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
        // oxlint-disable-next-line react/set-state-in-effect -- 셸(상단바)의 선택과 폼을 맞추는 동기화 — 선박 교체와 안내를 같은 패스에 세운다
        setVesselNotice(SHELL_VESSEL_MISSING)
        selectVesselId(vessels[0].id)
        return
      }
      setState((prev) => (prev.vesselId === shellVesselId ? prev : { ...prev, vesselId: shellVesselId }))
      return
    }
    if (vessels.length > 0) selectVesselId(vessels[0].id)
  }, [shellVesselId, vessels, selectVesselId])

  const selectedVessel = vessels.find((v) => v.id === state.vesselId)

  /*
   * ## 상단 항차와 선박 기본 연료로 칸을 채운다 (#1576)
   *
   * 종전에는 선박만 상단을 따르고 항차는 받지 않아, 계획 항차를 골라도 거리 · 속력 · 연료가
   * 비어 있었다. 규칙은 `prefillFromVoyage`가 정한다 — 작성 중 · 계획 확정 항차만, 연료가
   * 여러 종이면 연료 칸을 비우고 말한다.
   *
   * **항차마다 한 번**이다(`#1538` 항로 비교와 같은 규칙) — 효과가 항차 id에만 걸려 있어 같은
   * 항차에서 고친 칸은 다시 덮지 않고, 항차를 바꾸면 새 값이 들어온다. 늦게 온 앞 항차의 응답은
   * 버린다(`alive`).
   *
   * 기본 연료는 **항차가 칸을 채우지 않았을 때만** 넣는다 — 항차의 연료(또는 여러 종이라 비운
   * 칸)가 우선이다. 선박마다 한 번이다.
   */
  const shellVoyageId = shell.voyageId
  const voyagePrefilledFor = useRef<string | null>(null)
  // 안내는 **어느 항차의 것인지와 함께** 둔다 — 항차를 바꾸거나 풀면 옛 안내가 저절로 사라진다.
  const [voyageNoticeFor, setVoyageNoticeFor] = useState<{ voyageId: string; text: string | null } | null>(null)
  const voyageNotice =
    voyageNoticeFor !== null && voyageNoticeFor.voyageId === shellVoyageId ? voyageNoticeFor.text : null
  useEffect(() => {
    if (shellVoyageId === null) {
      voyagePrefilledFor.current = null
      return
    }
    let alive = true
    loadVoyage(shellVoyageId).then(
      (voyage) => {
        if (!alive) return
        voyagePrefilledFor.current = shellVoyageId
        const prefill = prefillFromVoyage(voyage)
        if (prefill === null) {
          setVoyageNoticeFor({
            voyageId: shellVoyageId,
            text: `상단의 항차는 「${STATUS_LABELS[voyage.status]}」 상태라 계획값으로 채우지 않았습니다 — CII 예측은 항해 전 조건으로 추정합니다.`,
          })
          return
        }
        setState((prev) => ({ ...prev, ...prefill.fields }))
        setVoyageNoticeFor({
          voyageId: shellVoyageId,
          text:
            prefill.multiFuelCount === null
              ? null
              : `이 항차는 연료가 ${prefill.multiFuelCount}종이라 여기서는 한 종만 넣을 수 있습니다 — 연료 칸은 비워 두었습니다.`,
        })
      },
      () => {
        if (!alive) return
        voyagePrefilledFor.current = shellVoyageId
        setVoyageNoticeFor({ voyageId: shellVoyageId, text: '상단의 항차를 불러오지 못해 입력칸을 채우지 않았습니다.' })
      },
    )
    return () => {
      alive = false
    }
  }, [shellVoyageId, loadVoyage])

  const selectedSpec = selectedVessel?.spec
  const specAppliedFor = useRef<string | null>(null)
  useEffect(() => {
    if (state.vesselId === '' || selectedSpec === undefined) return
    if (specAppliedFor.current === state.vesselId) return
    specAppliedFor.current = state.vesselId
    const fuel = selectedSpec.defaultFuelType
    if (fuel === null || voyagePrefilledFor.current !== null) return
    setState((prev) => (prev.fuelType === '' ? { ...prev, fuelType: fuel } : prev))
  }, [state.vesselId, selectedSpec])

  /** 한 필드를 갱신하고 그 필드의 오류만 지운다. 다른 필드의 오류는 그대로 둔다. */
  /*
   * 마지막 계산 이후 입력이 바뀌었는가 (#727).
   *
   * 렌더 중에 계산하고 효과로 알린다 — `update`마다 부모를 부르면 「어긋났다」를
   * 알리는 책임이 입력 처리기 여섯 군데로 흩어지고, 셸이 선박을 바꿔 폼이
   * 갱신되는 경로(위 효과)는 `update`를 거치지 않아 그 방식으로는 누락된다.
   */
  const stale = submittedState !== null && !sameInputs(submittedState, state)

  /* 「제원에서 채우기」가 쓰는 값과, 화면이 보이는 환산 결과 (#1718). */
  const vesselDailyFocTon = selectedSpec?.referenceDailyFocTon ?? null
  const derivedHours = voyageHours(state.distanceNm, state.speedKn)
  const derivedFuelTon = effectiveFuelTon(state, vesselDailyFocTon)

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

    const found = validateForm(state, fuels, vesselDailyFocTon)
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
      const request = toRequest(state, vesselDailyFocTon)
      const response = await provider.estimate(request)
      // #1533 — 챗봇이 「이 결과」를 저장된 실행에서 읽게 한다.
      publishScreenResult(response.calculation_run_id)
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
        {showsLabelEn ? (
          <span className="voyage-cii-form__title-en" lang="en">
            {' '}
            Voyage Input
          </span>
        ) : null}
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

      {/* 상단 항차로 채운 결과 · 채우지 못한 까닭 (#1576). 오류가 아니라 안내다. */}
      {voyageNotice !== null ? (
        <p className="voyage-cii-form__hint" role="status">
          {voyageNotice}
        </p>
      ) : null}

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
          hint="CII는 연료·거리로 정해져 속력만 바꿔도 같습니다. 다만 「계획 저장」 시 이 값이 계획 속력·도착 예정 시각이 되니 실제 운항 속력을 넣어 주세요."
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

        {/*
          연료 입력 방식 (#1718) — 계약은 그대로다. 어느 방식이든 요청은 `fuel_ton`
          하나이고(`toRequest`), 환산한 총량을 칸 아래에 그대로 보여 **무엇이 서버로
          가는지** 화면에서 읽히게 한다.

          라디오 그룹으로 둔다 — 셋 중 하나이고 서로 배타적이다. 방식을 바꿔도 값은
          지우지 않는다: 총량으로 돌아오면 처음 넣은 총량이 그대로 있다.

          「선박 제원에서」는 제원에 기준 일일 연료소모량이 없으면 **고를 수 없다**
          (#1718 원문 · #1784 ⑴). `disabled`를 유지하고 사유를 곁에 그려 `aria-describedby`로
          잇는다(`DESIGN_SYSTEM §14` 「비활성의 사유」) — 고른 뒤에야 사유를 보이면 낭독기로는
          왜 안 되는지 고르기 전에 알 수 없다. 이미 고른 채 선박을 바꿔 제원이 사라진
          경우는 아래 값 자리와 `validateForm`이 그대로 막는다.
        */}
        <fieldset className="voyage-cii-form__modes">
          <legend className="voyage-cii-form__label">연료 입력 방식</legend>
          {FUEL_MODES.map((mode) => {
            const blocked = mode.value === 'VESSEL' && vesselDailyFocTon === null
            return (
              <label
                key={mode.value}
                className={
                  blocked ? 'voyage-cii-form__mode voyage-cii-form__mode--disabled' : 'voyage-cii-form__mode'
                }
              >
                <input
                  type="radio"
                  name="fuel-mode"
                  value={mode.value}
                  checked={state.fuelMode === mode.value}
                  disabled={blocked}
                  aria-describedby={blocked ? VESSEL_MODE_REASON_ID : undefined}
                  onChange={() => {
                    // 실제 브라우저는 `disabled` 컨트롤에서 change를 내지 않는다. jsdom은
                    // 그렇지 않아(`fireEvent.click`이 그대로 넘어온다) 여기서도 막는다.
                    if (blocked) return
                    update('fuelMode', mode.value, FIELD.fuelTon)
                  }}
                />
                {mode.label}
              </label>
            )
          })}
          {vesselDailyFocTon === null ? (
            <p id={VESSEL_MODE_REASON_ID} className="voyage-cii-form__mode-reason">
              {state.vesselId === ''
                ? '「선박 제원에서」는 선박을 고른 뒤에 쓸 수 있습니다.'
                : '「선박 제원에서」는 이 선박에 기준 일일 연료소모량이 없어 고를 수 없습니다.'}
            </p>
          ) : null}
        </fieldset>

        {state.fuelMode === 'TOTAL' ? (
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
        ) : state.fuelMode === 'DAILY' ? (
          <Field
            id="fuel-daily"
            label="하루 연료 사용량"
            labelEn="Daily Fuel"
            unit={DISPLAY_UNIT_DAILY_FUEL}
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
                value={state.dailyFuelTon}
                onChange={(e) => update('dailyFuelTon', e.target.value, FIELD.fuelTon)}
              />
            )}
          </Field>
        ) : (
          /*
            제원에서 채우기 — 입력칸이 없다. 값이 없는 선박이면 그 사실을 값 자리에
            적는다(`§14` 「비활성의 사유」). 오류는 `validateForm`이 같은 자리에 세운다.
          */
          <div className="voyage-cii-form__field">
            <StaticField
              label="하루 연료 사용량"
              labelEn="Daily Fuel"
              value={
                vesselDailyFocTon === null
                  ? '이 선박에는 기준 일일 연료소모량이 없습니다'
                  : `${formatDecimalString(vesselDailyFocTon, DISPLAY_DIGITS.fuelTon)} ${DISPLAY_UNIT_DAILY_FUEL} · 선박 제원`
              }
            />
            {/*
              입력칸이 없으므로 `Field`의 오류 자리도 없다 — 같은 모양으로 직접 둔다.
              `role="alert"`가 없으면 검증 실패가 낭독되지 않는다(`§8.4`).
            */}
            {errors[FIELD.fuelTon] ? (
              <p className="field__error" role="alert">
                {errors[FIELD.fuelTon]}
              </p>
            ) : null}
          </div>
        )}

        {/*
          환산 결과 — 「나」·「다」에서만. 항해시간을 쓰는 이유는 `formRules.voyageHours`에
          적었다(일수는 `§4.2`상 0자리라 화면의 셈이 어긋나 보인다).

          곱하는 값(하루치)을 이 줄에 함께 적는다 (#1784 ⑵). 제원의 하루치가 23.04인데
          화면은 `§4.2`대로 23.0으로 보이므로, 무엇을 곱했는지 적지 않으면 「23.0 × 시간」을
          손으로 셈한 사람에게 총량이 틀려 보인다. 등록 자릿수를 드러내는 대신 셈의 세
          항을 나란히 두고, 표시값이 반올림된 것임을 같은 줄에 말한다.
        */}
        {state.fuelMode !== 'TOTAL' ? (
          <p className="voyage-cii-form__derived" role="status">
            {derivedHours === null ? (
              '항해거리와 평균 속력을 넣으면 총량을 환산합니다.'
            ) : derivedFuelTon === null ? (
              '하루 연료 사용량을 넣으면 총량을 환산합니다.'
            ) : (
              <>
                하루{' '}
                {formatDecimalString(
                  state.fuelMode === 'DAILY'
                    ? toDecimalInput(Number(state.dailyFuelTon))
                    : String(vesselDailyFocTon),
                  DISPLAY_DIGITS.fuelTon,
                )}{' '}
                {DISPLAY_UNIT_DAILY_FUEL} × 항해시간{' '}
                {formatDecimalString(String(derivedHours), DISPLAY_DIGITS.durationHours)}{' '}
                {DISPLAY_UNITS.duration} ÷ 24 → 보내는 연료 총량{' '}
                <strong>
                  {formatGrouped(String(derivedFuelTon), DISPLAY_DIGITS.fuelTon)} {DISPLAY_UNITS.fuel}
                </strong>
                <span className="voyage-cii-form__derived-note">
                  {' '}
                  (표시값은 반올림한 것이라 끝자리가 손으로 셈한 값과 다를 수 있습니다)
                </span>
              </>
            )}
          </p>
        ) : null}
      </div>

      <button className="voyage-cii-form__submit" type="submit" disabled={submitting}>
        {submitting ? '계산 중…' : '계산하기'}
      </button>
    </form>
  )
}

/* ------------------------------------------------------------------ */

/** 「선박 제원에서」를 고를 수 없는 사유 요소의 `id` — 라디오의 `aria-describedby`가 잇는다 (#1784). */
const VESSEL_MODE_REASON_ID = 'voyage-cii-fuel-mode-vessel-reason'

/** 연료 입력 방식 셋 (#1718). 순서는 「아는 값이 무엇인가」의 흔한 순서다. */
const FUEL_MODES: ReadonlyArray<{ value: FuelInputMode; label: string }> = [
  { value: 'TOTAL', label: '총량' },
  { value: 'DAILY', label: '하루 × 항해일' },
  { value: 'VESSEL', label: '선박 제원에서' },
]

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
  const showsLabelEn = useShowsLabelEn()

  return (
    <div className="voyage-cii-form__field">
      <p className="voyage-cii-form__label">
        {label}
        {showsLabelEn ? (
          <span className="voyage-cii-form__label-en" lang="en">
            {' '}
            {labelEn}
          </span>
        ) : null}
      </p>
      <p className="voyage-cii-form__static">{value}</p>
    </div>
  )
}
