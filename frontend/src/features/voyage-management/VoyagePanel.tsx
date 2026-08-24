import { useCallback, useEffect, useState } from 'react'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatGrouped } from '../../display/format'
import { withRo } from '../../display/josa'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { VoyageError, createApiVoyageManagementProvider } from './apiProvider'
import { ImportCsv } from './ImportCsv'
import type { VoyageManagementProvider } from './apiProvider'
import {
  POLICY_LABELS,
  STATUS_LABELS,
  canEnterActuals,
  hasErrors,
  nextStatuses,
  transitionBlocker,
  validateActuals,
  validateDraft,
} from './voyageRules'
import type { FieldErrors } from './voyageRules'
import type { ActualsDraft, ManagedVoyage, VoyageDraft, VoyageFuelDraft } from './types'
import './VoyagePanel.css'

/**
 * 항차 기록 패널 — `2-8 선박 상세` 안의 한 구획 (`#610`).
 *
 * ## 새 화면을 만들지 않는다
 *
 * `UIFLOW`에 「항차 생성」·「실적 입력」이 없다. 화면 신설은 `AGENTS §3.2.1`상
 * UIFLOW 소관(화면 목록)이라 정본 개정이 선행하고, 마감 스프린트가 그것을
 * 컷라인 밖에 두었다. `NotUnderwayPanel`과 같은 자리·같은 방식으로 붙인다.
 *
 * ## 속력 표시 — 조건부 유예가 풀렸다
 *
 * 종전에는 `DESIGN_SYSTEM §4.2`에 **속력(kn) 자릿수가 없어** 목록에서 열을 뺐다.
 * 화면이 임의로 정하면 다른 화면과 갈라지기 때문이었고, 열을 비우는 대신 아예
 * 빼는 것으로 그 사실을 드러냈다(`AGENTS §6.1`).
 *
 * **`§4.2` v2.3이 1자리로 확정했다**(`#592`). 열을 되돌린다.
 */

const NO_VALUE = '—'

/** `periodRules.quantityText`와 같은 규율 — 없는 값은 `—`, 있으면 자릿수 고정. */
function quantity(value: number | null, digits: number): string {
  if (value === null || !Number.isFinite(value)) return NO_VALUE
  return formatGrouped(value.toFixed(6), digits)
}

function totalFuel(voyage: ManagedVoyage, kind: 'planned' | 'actual'): number | null {
  const values = voyage.fuelUses
    .map((use) => (kind === 'planned' ? use.plannedFuelTon : use.actualFuelTon))
    .filter((value): value is number => value !== null)
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0)
}

function routeText(voyage: ManagedVoyage): string {
  return `${voyage.departurePortName ?? NO_VALUE} \u2192 ${voyage.arrivalPortName ?? NO_VALUE}`
}

interface VoyagePanelProps {
  vesselId: string
  provider?: VoyageManagementProvider
}

export function VoyagePanel({ vesselId, provider }: VoyagePanelProps) {
  const [voyages, setVoyages] = useState<ManagedVoyage[] | null>(null)
  const [fuelTypes, setFuelTypes] = useState<string[]>([])
  const [failure, setFailure] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  const api = provider ?? createApiVoyageManagementProvider()

  /**
   * 한 페이지를 부른다 (`#627`).
   *
   * `cursor`가 `null`이면 **처음부터 다시** 부르고, 있으면 **뒤에 잇는다.** 종전에는
   * `?limit=100`만 박고 `meta.next_cursor`를 버려 **101번째 항차부터 화면에서 도달할
   * 방법이 없었다** — `#625`가 한 번에 1,000행을 넣을 수 있게 만든 뒤 실제 문제가 됐다.
   *
   * 선박 관리(`VesselManagement.tsx`)가 같은 계약을 이미 이렇게 소비한다.
   */
  const loadPage = useCallback(
    async (cursor: string | null) => {
      setFailure(null)
      if (cursor !== null) setLoadingMore(true)
      try {
        const result = await api.list(vesselId, cursor)
        setVoyages((rows) => (cursor === null ? result.voyages : [...(rows ?? []), ...result.voyages]))
        setFuelTypes(result.fuelTypes)
        setNextCursor(result.nextCursor)
        setHasMore(result.hasMore)
      } catch (error) {
        // 이어붙이던 중 실패하면 **이미 받은 행을 지우지 않는다.** 첫 페이지 실패만
        // 빈 목록으로 떨어뜨린다 — 그때는 보여 줄 것이 없다.
        if (cursor === null) setVoyages([])
        setFailure(error instanceof Error ? error.message : '항차를 불러오지 못했습니다.')
      } finally {
        setLoadingMore(false)
      }
    },
    // provider는 렌더마다 새로 만들어지므로 의존에 넣지 않는다 — 넣으면 무한 루프다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [vesselId],
  )

  const load = useCallback(async () => {
    await loadPage(null)
  }, [loadPage])

  useEffect(() => {
    void load()
  }, [load])

  const replace = (updated: ManagedVoyage) => {
    setVoyages((rows) => (rows ?? []).map((row) => (row.id === updated.id ? updated : row)))
  }

  return (
    <section className="card vy" aria-label="항차 기록">
      <div className="vy__head">
        <h2 className="card__title">항차 기록</h2>
        <button
          type="button"
          className="vy__toggle"
          onClick={() => setFormOpen((open) => !open)}
          aria-expanded={formOpen}
        >
          {formOpen ? '취소' : '항차 추가'}
        </button>
      </div>

      <p className="vy__why">
        계획을 먼저 만들고, 항해가 끝나면 실적을 입력합니다. 계획값은 실적을 넣어도 그대로
        남습니다 — 계획 대비 실적 차이가 다음 항차의 예측을 다듬는 근거입니다. 아래 수치는{' '}
        <b>계획 → 실적</b> 순입니다.
      </p>

      {failure ? (
        <p className="vy__error" role="alert">
          {failure}
        </p>
      ) : null}

      {formOpen ? (
        <VoyageForm
          fuelTypes={fuelTypes}
          onCancel={() => setFormOpen(false)}
          onSubmit={async (draft) => {
            const created = await api.create(vesselId, draft)
            setVoyages((rows) => [created, ...(rows ?? [])])
            setFormOpen(false)
          }}
        />
      ) : null}

      {voyages === null ? (
        <p className="vy__loading" aria-busy="true">
          항차를 불러오는 중입니다…
        </p>
      ) : voyages.length === 0 && !failure ? (
        <p className="vy__empty">
          기록된 항차가 없습니다. 「항차 추가」로 하나씩 만들거나, 아래에서 CSV로
          한 번에 가져올 수 있습니다.
        </p>
      ) : (
        <ul className="vy__list">
          {voyages.map((voyage) => (
            <VoyageRow key={voyage.id} voyage={voyage} api={api} onChange={replace} />
          ))}
        </ul>
      )}

      {/*
       * 「더 보기」 — 서버가 `meta.has_more`로 알려 준다. 커서가 없는데 버튼을 그리면
       * 같은 페이지를 다시 부르므로 **둘 다 있을 때만** 그린다(`VesselManagement.tsx`와 같은 조건).
       */}
      {hasMore && nextCursor !== null && (
        <button
          type="button"
          className="vy__more"
          disabled={loadingMore}
          onClick={() => void loadPage(nextCursor)}
        >
          {loadingMore ? '불러오는 중…' : '더 보기'}
        </button>
      )}

      {/*
       * 가져오기를 **목록 아래**에 둔다. 이 구획의 주 용도는 기록을 읽고 상태를
       * 옮기는 것이고, 대량 입력은 처음 한 번에 몰린다. 위에 두면 매번 지나쳐야 한다.
       *
       * 확정에 성공하면 목록을 다시 부른다 — 들어간 행을 화면이 스스로 만들지
       * 않는다. 서버가 `DRAFT`·`EXCLUDE`로 확정한 항차를 그대로 받아야 상태 전환
       * 버튼이 옳게 그려진다(`API_SPEC §8.2`).
       */}
      <ImportCsv vesselId={vesselId} provider={api} onImported={() => void load()} />
    </section>
  )
}

function VoyageRow({
  voyage,
  api,
  onChange,
}: {
  voyage: ManagedVoyage
  api: VoyageManagementProvider
  onChange: (updated: ManagedVoyage) => void
}) {
  const [busy, setBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)
  const [actualsOpen, setActualsOpen] = useState(false)

  const run = async (task: () => Promise<ManagedVoyage>) => {
    setBusy(true)
    setRowError(null)
    try {
      onChange(await task())
    } catch (error) {
      setRowError(
        error instanceof VoyageError || error instanceof Error
          ? error.message
          : '처리하지 못했습니다.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="vy__row">
      <div className="vy__row-main">
        <span className="vy__no">{voyage.voyageNo ?? NO_VALUE}</span>
        <span className={`vy__badge vy__badge--${voyage.status.toLowerCase()}`}>
          {STATUS_LABELS[voyage.status]}
        </span>
        <span className="vy__route">{routeText(voyage)}</span>
        <span className="vy__policy">{POLICY_LABELS[voyage.inclusionPolicy]}</span>
      </div>

      {/*
        여섯 칸을 **세 쌍**으로 묶었다 (#721).

        종전에는 `계획 거리 · 실제 거리 · 계획 속력 · 실제 평균 속력 · 계획 연료 ·
        실제 연료`가 여섯 칸에 흩어져 있었다. **이 패널의 머리글 스스로**가
        「계획 대비 실적 차이가 다음 항차의 예측을 다듬는 근거」라고 적어 두고,
        정작 화면은 비교할 두 값을 갈라 놓고 있었다.

        라벨이 절반이 되고 비교가 한 눈에 들어온다. 화살표의 뜻은 위 머리글이 적는다.
      */}
      <dl className="vy__figures">
        <Pair
          label="거리"
          planned={quantity(voyage.plannedDistanceNm, DISPLAY_DIGITS.distanceNm)}
          actual={quantity(voyage.actualDistanceNm, DISPLAY_DIGITS.distanceNm)}
          unit={DISPLAY_UNITS.distance}
        />
        <Pair
          label="속력"
          planned={quantity(voyage.plannedSpeedKn, DISPLAY_DIGITS.speedKn)}
          actual={quantity(voyage.actualAvgSpeedKn, DISPLAY_DIGITS.speedKn)}
          unit={DISPLAY_UNITS.speed}
        />
        <Pair
          label="연료"
          planned={quantity(totalFuel(voyage, 'planned'), DISPLAY_DIGITS.fuelTon)}
          actual={quantity(totalFuel(voyage, 'actual'), DISPLAY_DIGITS.fuelTon)}
          unit={DISPLAY_UNITS.fuel}
        />
      </dl>

      {rowError ? (
        <p className="vy__error" role="alert">
          {rowError}
        </p>
      ) : null}

      <div className="vy__row-actions">
        {nextStatuses(voyage.status).map((to) => {
          const blocker = transitionBlocker(voyage, to)
          return (
            <span className="vy__action" key={to}>
              <button
                type="button"
                className="vy__transition"
                disabled={busy || blocker !== null}
                onClick={() => void run(() => api.transition(voyage, to))}
              >
                {withRo(STATUS_LABELS[to])}
              </button>
              {/* 왜 못 누르는지 버튼 옆에 적는다 — 눌러 보고 422를 받는 것보다 낫다. */}
              {blocker ? <span className="vy__blocker">{blocker}</span> : null}
            </span>
          )
        })}

        {canEnterActuals(voyage.status) ? (
          <button
            type="button"
            className="vy__toggle"
            onClick={() => setActualsOpen((open) => !open)}
            aria-expanded={actualsOpen}
          >
            {actualsOpen ? '실적 닫기' : '실적 입력'}
          </button>
        ) : null}
      </div>

      {actualsOpen ? (
        <ActualsForm
          voyage={voyage}
          onCancel={() => setActualsOpen(false)}
          onSubmit={async (draft) => {
            await run(() => api.saveActuals(voyage.id, draft))
            setActualsOpen(false)
          }}
        />
      ) : null}
    </li>
  )
}

function VoyageForm({
  fuelTypes,
  onCancel,
  onSubmit,
}: {
  fuelTypes: string[]
  onCancel: () => void
  onSubmit: (draft: VoyageDraft) => Promise<void>
}) {
  const [draft, setDraft] = useState<VoyageDraft>({
    voyageNo: '',
    departurePortName: '',
    arrivalPortName: '',
    plannedDistanceNm: '',
    plannedSpeedKn: '',
    regulationYear: '',
    fuelUses: [{ fuelType: fuelTypes[0] ?? '', plannedFuelTon: '' }],
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const set = (key: keyof VoyageDraft) => (value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  /** 연료 한 줄의 필드를 바꾼다 (`#636`). */
  const setFuel = (index: number, patch: Partial<VoyageFuelDraft>) =>
    setDraft((prev) => ({
      ...prev,
      fuelUses: prev.fuelUses.map((fu, i) => (i === index ? { ...fu, ...patch } : fu)),
    }))

  if (fuelTypes.length === 0) {
    /*
     * 선택지를 못 받으면 폼을 그리지 않는다. 화면이 기본값을 지어내면 서버의
     * 연료 목록과 갈라지고, 사용자는 저장 단계에서야 거부를 만난다.
     */
    return (
      <p className="vy__error" role="alert">
        연료 선택지를 불러오지 못해 항차를 추가할 수 없습니다.
      </p>
    )
  }

  return (
    <form
      className="vy__form"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        const found = validateDraft(draft)
        setErrors(found)
        if (hasErrors(found)) return

        setBusy(true)
        setFailure(null)
        try {
          await onSubmit(draft)
        } catch (error) {
          setFailure(error instanceof Error ? error.message : '항차를 만들지 못했습니다.')
        } finally {
          setBusy(false)
        }
      }}
    >
      {failure ? (
        <p className="vy__error" role="alert">
          {failure}
        </p>
      ) : null}

      <Field id="vy-no" label="항차 번호" value={draft.voyageNo} onChange={set('voyageNo')} error={errors.voyageNo} />
      <Field id="vy-from" label="출발항" value={draft.departurePortName} onChange={set('departurePortName')} error={errors.departurePortName} />
      <Field id="vy-to" label="도착항" value={draft.arrivalPortName} onChange={set('arrivalPortName')} error={errors.arrivalPortName} />
      <Field id="vy-dist" label={`계획 거리 (${DISPLAY_UNITS.distance})`} value={draft.plannedDistanceNm} onChange={set('plannedDistanceNm')} error={errors.plannedDistanceNm} inputMode="decimal" />
      <Field id="vy-speed" label={`계획 속력 (${DISPLAY_UNITS.speed})`} value={draft.plannedSpeedKn} onChange={set('plannedSpeedKn')} error={errors.plannedSpeedKn} inputMode="decimal" />
      {/*
        연료는 여러 줄이다 (`#636`).

        서버(`API_SPEC §3.3` `fuel_uses[]`)·스키마(`DB_SCHEMA §2.4` N행)·실적 입력
        폼은 처음부터 다행이었고 **생성 폼만 단일**이었다. 그래서 화면으로 만든
        항차는 연료가 반드시 한 종이었고, 아래 실적 입력의 다행 UI가 늘 한 줄만
        그렸다 — **도달할 수 없는 코드**였다.

        정박 구간 폼(`NotUnderwayPanel`)이 같은 형태로 이미 다행을 받는다.
      */}
      <fieldset className="vy__fuels">
        <legend className="vy__label">계획 연료</legend>

        {draft.fuelUses.map((fu, index) => (
          <div className="vy__fuel-row" key={index}>
            <select
              className="vy__input"
              aria-label={`연료 종류 ${index + 1}`}
              value={fu.fuelType}
              onChange={(event) => setFuel(index, { fuelType: event.target.value })}
            >
              {fuelTypes.map((code) => (
                <option key={code} value={code}>
                  {fuelTypeOptionText(code)}
                </option>
              ))}
            </select>

            <input
              className="vy__input"
              inputMode="decimal"
              placeholder={DISPLAY_UNITS.fuel}
              aria-label={`계획 연료 ${index + 1} (${DISPLAY_UNITS.fuel})`}
              value={fu.plannedFuelTon}
              onChange={(event) => setFuel(index, { plannedFuelTon: event.target.value })}
            />

            {/*
              마지막 한 줄은 지우지 않는다 — 서버가 `min_length=1`을 요구한다(`§3.3`).
              버튼을 남겨 두고 저장 단계에서 거부하면 사용자는 무엇을 지웠는지 잊는다.
            */}
            {draft.fuelUses.length > 1 ? (
              <button
                type="button"
                className="vy__fuel-remove"
                aria-label={`연료 ${index + 1} 삭제`}
                onClick={() =>
                  setDraft((prev) => ({
                    ...prev,
                    fuelUses: prev.fuelUses.filter((_, i) => i !== index),
                  }))
                }
              >
                삭제
              </button>
            ) : null}

            {errors[`fuelType.${index}`] ? (
              <em className="vy__field-error">{errors[`fuelType.${index}`]}</em>
            ) : null}
            {errors[`plannedFuelTon.${index}`] ? (
              <em className="vy__field-error">{errors[`plannedFuelTon.${index}`]}</em>
            ) : null}
          </div>
        ))}

        <button
          type="button"
          className="vy__fuel-add"
          data-testid="vy-fuel-add"
          onClick={() =>
            setDraft((prev) => ({
              ...prev,
              /*
               * 아직 쓰지 않은 유종을 기본값으로 고른다 — 같은 값을 두 번 넣어 두면
               * 사용자가 고치기 전까지 폼이 오류 상태로 열린다. 남는 유종이 없으면
               * 첫 값으로 두고 검증이 잡는다.
               */
              fuelUses: [
                ...prev.fuelUses,
                {
                  fuelType:
                    fuelTypes.find((code) => !prev.fuelUses.some((fu) => fu.fuelType === code)) ??
                    fuelTypes[0] ??
                    '',
                  plannedFuelTon: '',
                },
              ],
            }))
          }
        >
          + 연료 추가
        </button>

        {errors.fuelUses ? <em className="vy__field-error">{errors.fuelUses}</em> : null}
      </fieldset>

      <Field
        id="vy-year"
        label="기준연도 (선택)"
        value={draft.regulationYear}
        onChange={set('regulationYear')}
        error={errors.regulationYear}
        inputMode="numeric"
        hint="연간 등급에 반영하려면 필요합니다. 나중에 지정해도 됩니다."
      />

      <div className="vy__form-actions">
        <button type="submit" className="vy__submit" disabled={busy}>
          {busy ? '만드는 중' : '항차 만들기'}
        </button>
        <button type="button" className="vy__cancel" onClick={onCancel} disabled={busy}>
          취소
        </button>
      </div>
    </form>
  )
}

function ActualsForm({
  voyage,
  onCancel,
  onSubmit,
}: {
  voyage: ManagedVoyage
  onCancel: () => void
  onSubmit: (draft: ActualsDraft) => Promise<void>
}) {
  const [draft, setDraft] = useState<ActualsDraft>({
    actualDistanceNm: voyage.actualDistanceNm?.toString() ?? '',
    actualAvgSpeedKn: voyage.actualAvgSpeedKn?.toString() ?? '',
    actualFuelTon: Object.fromEntries(
      voyage.fuelUses.map((use) => [use.fuelType, use.actualFuelTon?.toString() ?? '']),
    ),
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [busy, setBusy] = useState(false)

  return (
    <form
      className="vy__form vy__form--actuals"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        const found = validateActuals(draft)
        setErrors(found)
        if (hasErrors(found)) return
        setBusy(true)
        try {
          await onSubmit(draft)
        } finally {
          setBusy(false)
        }
      }}
    >
      <p className="vy__hint">
        비워 두면 그 항목은 바뀌지 않습니다. 실거리만 먼저 알고 연료가 나중에 오는 경우를 위해
        모든 칸이 선택입니다.
      </p>

      <Field
        id={`ac-dist-${voyage.id}`}
        label={`실제 거리 (${DISPLAY_UNITS.distance})`}
        value={draft.actualDistanceNm}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualDistanceNm: value }))}
        error={errors.actualDistanceNm}
        inputMode="decimal"
        hint={`계획 ${quantity(voyage.plannedDistanceNm, DISPLAY_DIGITS.distanceNm)} ${DISPLAY_UNITS.distance}`}
      />

      <Field
        id={`ac-speed-${voyage.id}`}
        label={`실제 평균 속력 (${DISPLAY_UNITS.speed})`}
        value={draft.actualAvgSpeedKn}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualAvgSpeedKn: value }))}
        error={errors.actualAvgSpeedKn}
        inputMode="decimal"
      />

      {voyage.fuelUses.map((use) => (
        <Field
          key={use.fuelType}
          id={`ac-fuel-${voyage.id}-${use.fuelType}`}
          label={`실제 ${use.fuelType} (${DISPLAY_UNITS.fuel})`}
          value={draft.actualFuelTon[use.fuelType] ?? ''}
          onChange={(value) =>
            setDraft((prev) => ({
              ...prev,
              actualFuelTon: { ...prev.actualFuelTon, [use.fuelType]: value },
            }))
          }
          error={errors[`actualFuelTon.${use.fuelType}`]}
          inputMode="decimal"
          hint={`계획 ${quantity(use.plannedFuelTon, DISPLAY_DIGITS.fuelTon)} ${DISPLAY_UNITS.fuel}`}
        />
      ))}

      <div className="vy__form-actions">
        <button type="submit" className="vy__submit" disabled={busy}>
          {busy ? '저장 중' : '실적 저장'}
        </button>
        <button type="button" className="vy__cancel" onClick={onCancel} disabled={busy}>
          취소
        </button>
      </div>
    </form>
  )
}

/**
 * 입력 한 칸.
 *
 * 오류를 `aria-describedby`로 잇고 `aria-invalid`를 세운다 — 색만으로 표시하면
 * 스크린 리더 사용자가 무엇이 잘못됐는지 알 수 없다(`DESIGN_SYSTEM §14`).
 * `AuthField`와 같은 규율이다.
 */
function Field({
  id,
  label,
  value,
  onChange,
  error,
  hint,
  inputMode,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  hint?: string
  inputMode?: 'decimal' | 'numeric'
}) {
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ')

  return (
    <div className="vy__field">
      <label className="vy__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={error ? 'vy__input vy__input--error' : 'vy__input'}
        value={value}
        inputMode={inputMode}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
      />
      {hint ? (
        <p className="vy__hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="vy__field-error" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

/**
 * 계획·실적 한 쌍 (#721).
 *
 * ## 화살표에 뜻을 싣되 화살표에만 싣지 않는다
 *
 * 보이는 것은 `900 → 915 nm` 한 줄이지만, 스크린 리더에는 **「계획 900 실적 915」**로
 * 읽히도록 `sr-only` 라벨을 함께 둔다. 화살표 하나가 유일한 채널이면 `§14`가 막는
 * 「한 채널에만 의존」이 된다.
 *
 * 사람이 읽는 쪽의 근거는 패널 머리글이 한 번 적는다 — 행마다 적으면 여섯 칸을
 * 세 칸으로 줄인 뜻이 없어진다.
 */
function Pair({
  label,
  planned,
  actual,
  unit,
}: {
  label: string
  planned: string
  actual: string
  unit: string
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className="num">
        <span className="sr-only">계획 </span>
        {planned}
        <span className="vy__arrow" aria-hidden="true">
          {' → '}
        </span>
        <span className="sr-only">실적 </span>
        {actual} {unit}
      </dd>
    </div>
  )
}
