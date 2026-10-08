import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { fuelTypeText } from '../parameters/fuelTypes'
import { createApiNotUnderwayProvider, NotUnderwayError } from './apiProvider'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatTimestamp } from '../../display/format'
import { publicRecordFilledNote } from '../data-quality/timeSource'
import {
  CONSUMER_TYPE_LABELS,
  PERIOD_TYPE_LABELS,
  distanceLocked,
  formatRange,
  fuelUseDeleteCaution,
  hasErrors,
  labelOf,
  periodDeleteCaution,
  toIso,
  toLocalInput,
  quantityText,
  totalFuelTon,
  validateDraft,
  validateFuelDraft,
  type DeleteCaution,
  type DraftErrors,
} from './periodRules'
import type { FuelUse, FuelUseDraft, NotUnderwayProvider, Period, PeriodDraft } from './types'
import './NotUnderwayPanel.css'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'

/**
 * not under way 구간 입력 — 선박 상세(`#356`) 하위 (`UIFLOW 2-8` · `#370`).
 *
 * ## 왜 이 화면이 필요한가
 *
 * 정박 연료는 CII 분자 `M`에 그대로 들어간다(`#353`). 지금까지 그 기록은 **시드로만**
 * 들어갔다 — 시연은 되지만 실제로 쓸 수 없었고, 기록이 없으면 `M`이 늘지 않아
 * **정박해도 등급이 떨어지지 않는다.** 이 패널이 그 입구다.
 *
 * ## 선택지를 서버에서 받는다
 *
 * `period_type`·`consumer_type`·`fuel_type`을 화면 코드에 박지 않는다. DB CHECK
 * 제약·연료 seed와 갈라지면 사용자는 **저장 단계에서야** 거부를 만난다. 목록 응답의
 * `meta`가 세 선택지를 함께 준다(`API_SPEC §2.9`).
 *
 * ## 진행 중 구간을 따로 다룬다
 *
 * 정박이 시작될 때는 언제 끝날지 모르므로 종료 시각 없이 넣고, 출항할 때 닫는다.
 * `ended_at`이 `null`인 것은 **「진행 중」이지 「모름」이 아니다** — 목록에서 이 둘을
 * 같게 그리면 사용자가 종료 시각을 잊었다고 오해한다.
 */
export function NotUnderwayPanel({
  vesselId,
  provider,
  onChanged,
}: {
  vesselId: string
  /** 테스트가 갈아 끼운다 — 이 저장소의 vitest에는 DOM도 네트워크도 없다. */
  provider?: NotUnderwayProvider
  /**
   * 구간·연료를 바꾼 **뒤** 부른다 (`#1648`). 정박 연료와 기간은 누적 CII의 분자·분모에
   * 들어가므로(`PRD §3.3`), 이 패널만 갱신하면 부모(선박 상세)의 누적값이 옛 기록으로 남는다.
   * **성공에서만** 부른다.
   */
  onChanged?: () => void
}) {
  const [periods, setPeriods] = useState<Period[] | null>(null)
  const [choices, setChoices] = useState<{
    periodTypes: string[]
    consumerTypes: string[]
    fuelTypes: string[]
  }>({ periodTypes: [], consumerTypes: [], fuelTypes: [] })
  const [failure, setFailure] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)

  const api = provider ?? createApiNotUnderwayProvider()

  const reload = useCallback(async () => {
    try {
      const result = await api.list(vesselId)
      setPeriods(result.periods)
      setChoices({
        periodTypes: result.periodTypes,
        consumerTypes: result.consumerTypes,
        fuelTypes: result.fuelTypes,
      })
      setFailure(null)
    } catch (error) {
      setFailure(
        error instanceof Error ? error.message : '구간을 불러오지 못했습니다.',
      )
    }
    // provider는 매 렌더마다 새로 만들어지므로 의존성에 넣지 않는다 — 넣으면 무한 루프다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vesselId])

  useEffect(() => {
    void reload()
  }, [reload])

  return (
    <section className="card nu" aria-label="not under way 구간">
      <div className="card__head">
        <h2 className="card__title">정박·묘박 기록</h2>
        <button
          className="nu__button"
          type="button"
          onClick={() => setFormOpen((open) => !open)}
          data-testid="nu-toggle"
        >
          {formOpen ? '닫기' : '+ 구간 추가'}
        </button>
      </div>

      <p className="nu__why">
        이 기록의 연료는 CII 계산의 <b>분자에 그대로 더해집니다</b>. 넣지 않으면 정박
        구간이 등급에 반영되지 않습니다.
      </p>

      {failure ? (
        <ErrorState level="region" size="compact" message={failure} />
      ) : null}

      {formOpen ? (
        <PeriodForm
          choices={choices}
          onSubmit={async (draft) => {
            await api.create(vesselId, draft)
            setFormOpen(false)
            await reload()
            onChanged?.()
          }}
        />
      ) : null}

      {periods === null && !failure ? (
        <p className="nu__loading" aria-busy="true" role="status">
          구간을 불러오는 중입니다…
        </p>
      ) : null}

      {periods !== null && periods.length === 0 ? (
        /* 기록이 없는 것은 오류가 아니다 — 아직 안 넣었을 뿐이다. */
        <p className="nu__empty">
          기록된 구간이 없습니다. 정박·묘박이 있었다면 추가해 주세요.
        </p>
      ) : null}

      {periods !== null && periods.length > 0 ? (
        <ul className="nu__list">
          {periods.map((period) => (
            <PeriodRow
              key={period.id}
              period={period}
              choices={choices}
              onClose={async (endedAt) => {
                await api.close(period.id, endedAt)
                await reload()
                onChanged?.()
              }}
              onRemove={async () => {
                await api.remove(period.id)
                await reload()
                onChanged?.()
              }}
              onAddFuel={async (draft) => {
                await api.addFuelUse(period.id, draft)
                await reload()
                onChanged?.()
              }}
              onRemoveFuel={async (fuelUseId) => {
                await api.removeFuelUse(period.id, fuelUseId)
                await reload()
                onChanged?.()
              }}
            />
          ))}
        </ul>
      ) : null}
    </section>
  )
}

// ─── 목록 한 행 ──────────────────────────────────────────────────────────────

function PeriodRow({
  period,
  choices,
  onClose,
  onRemove,
  onAddFuel,
  onRemoveFuel,
}: {
  period: Period
  choices: { consumerTypes: string[]; fuelTypes: string[] }
  onClose: (endedAt: string) => Promise<void>
  onRemove: () => Promise<void>
  onAddFuel: (draft: FuelUseDraft) => Promise<void>
  onRemoveFuel: (fuelUseId: string) => Promise<void>
}) {
  const [closing, setClosing] = useState(false)
  const [endValue, setEndValue] = useState(() => toLocalInput(new Date().toISOString()))
  const [rowError, setRowError] = useState<string | null>(null)
  /**
   * 나중에 더하는 연료 한 줄 (`#638`).
   *
   * `null`이면 폼을 열지 않은 상태다 — 빈 draft와 구분한다. 항상 열어 두면 구간
   * 스무 개가 폼으로 덮여 목록이 읽히지 않는다.
   */
  const [fuelDraft, setFuelDraft] = useState<FuelUseDraft | null>(null)
  const [fuelError, setFuelError] = useState<string | null>(null)
  /*
   * 지우기 전에 한 번 더 묻는다 (`#2130` · 전수검수 D-11). 구간 삭제와 연료 한 줄 삭제는
   * 누적 CII의 분자·분모를 바꾸고 화면에서 되돌릴 길이 없다. 같은 선박 상세의 항차 카드가
   * 같은 성격의 동작(취소·보관)에 **카드 안 확인 줄**을 두므로 그 모양을 그대로 쓴다
   * (`VoyagePanel`의 `#1598`). 브라우저 `confirm()`은 쓰지 않는다 — 창 안에 달라지는 값을
   * 보여 줄 수 없고, 계정 패널이 같은 이유로 거부했다.
   *
   * 한 행에 확인 줄은 하나다 — 구간 삭제와 연료 한 줄 삭제가 동시에 열려 있으면 어느
   * 「삭제하기」가 무엇을 지우는지 읽히지 않는다.
   */
  const [pending, setPending] = useState<
    { kind: 'period' } | { kind: 'fuel'; fuelUse: FuelUse } | null
  >(null)
  const pendingTrigger = useRef<HTMLButtonElement | null>(null)
  const keepRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    // 줄이 열리면 **안전한 쪽**(「그만두기」)에 초점 — Enter를 한 번 더 눌러 실행되지 않게.
    if (pending !== null) keepRef.current?.focus()
  }, [pending])
  const closePending = () => {
    setPending(null)
    // 초점을 누른 버튼으로 돌려준다 — 줄이 사라지면 초점이 문서 머리로 떨어진다.
    pendingTrigger.current?.focus()
  }
  const openPending = (
    next: { kind: 'period' } | { kind: 'fuel'; fuelUse: FuelUse },
    trigger: HTMLButtonElement,
  ) => {
    pendingTrigger.current = trigger
    setPending(next)
  }
  const cautionId = `nu-caution-${period.id}`

  const guard = async (action: () => Promise<void>) => {
    try {
      setRowError(null)
      await action()
    } catch (error) {
      // 제공자가 만든 문구를 그대로 쓴다 — 겹침이면 상대 구간의 시각이 목록과 같은 형식으로 담긴다.
      setRowError(
        error instanceof NotUnderwayError
          ? error.message
          : '처리하지 못했습니다. 잠시 후 다시 시도해 주세요.',
      )
    }
  }

  const ongoing = period.endedAt === null

  return (
    <li className={`nu__row${ongoing ? ' nu__row--ongoing' : ''}`}>
      <div className="nu__row-main">
        <span className="nu__type">{labelOf(period.periodType, PERIOD_TYPE_LABELS)}</span>
        <span className="nu__range num">{formatRange(period)}</span>
        {ongoing ? <span className="nu__badge">진행 중</span> : null}
      </div>

      {/*
        「이 값으로 채우기」로 넣은 시각이면 그 사실을 붙인다 (#2114 · `PRD §17.4.4`). 항차
        카드의 같은 표식과 같은 문구 틀이다(`publicRecordFilledNote`) — 출처가 `PUBLIC_RECORD`일
        때만이고 `null`(「모른다」)에는 붙이지 않는다. ⚠️ 디자인 담당 확인 전 개발 임시안이다.
      */}
      {period.startedAtSource === 'PUBLIC_RECORD' ? (
        <p className="nu__hint">
          {publicRecordFilledNote('시작 시각', formatTimestamp(period.startedAt))}
        </p>
      ) : null}
      {period.endedAtSource === 'PUBLIC_RECORD' && period.endedAt !== null ? (
        <p className="nu__hint">{publicRecordFilledNote('끝 시각', formatTimestamp(period.endedAt))}</p>
      ) : null}

      <dl className="nu__figures">
        <div>
          <dt>항구</dt>
          <dd>{period.portName ?? '—'}</dd>
        </div>
        <div>
          <dt>연료</dt>
          {/* 0건과 0톤은 다르다 — 안 넣은 것과 안 쓴 것을 같게 적지 않는다. */}
          <dd className="num">
            {period.fuelUses.length === 0
              ? '미입력'
              : `${quantityText(totalFuelTon(period), DISPLAY_DIGITS.fuelTon)} ${DISPLAY_UNITS.fuel}`}
          </dd>
        </div>
        <div>
          <dt>이동 거리</dt>
          <dd className="num">
            {quantityText(period.distanceNm, DISPLAY_DIGITS.distanceNm)} {DISPLAY_UNITS.distance}
          </dd>
        </div>
        <div>
          <dt>규제연도</dt>
          <dd className="num">{period.regulationYear}</dd>
        </div>
      </dl>

      {period.fuelUses.length > 0 ? (
        <ul className="nu__fuels">
          {period.fuelUses.map((fu) => (
            <li key={fu.id}>
              <span>{labelOf(fu.consumerType, CONSUMER_TYPE_LABELS)}</span>
              <span>{fu.fuelType}</span>
              <span className="num">
                {quantityText(fu.fuelTon, DISPLAY_DIGITS.fuelTon)} {DISPLAY_UNITS.fuel}
              </span>
              {/* CF는 서버가 뜬 snapshot이다. 표시만 하고 편집하지 않는다. */}
              <span className="num nu__cf">CF {fu.cfUsed}</span>
              {/*
                잘못 넣은 한 줄을 지운다 (`API_SPEC §2.13` · `#638`). **물리 삭제다** —
                `not_underway_fuel_use`에는 `is_deleted` 열이 없다(`#345`).
                종전에는 이 경로에 소비처가 없어 구간을 통째로 지우고 다시 만들어야 했고,
                그때 `started_at`을 다시 입력하면서 값이 틀어질 여지가 생겼다.
              */}
              <button
                type="button"
                className="nu__fuel-remove"
                aria-label={`${labelOf(fu.consumerType, CONSUMER_TYPE_LABELS)} ${fu.fuelType} 연료 기록 삭제`}
                aria-expanded={pending?.kind === 'fuel' && pending.fuelUse.id === fu.id}
                onClick={(event) => openPending({ kind: 'fuel', fuelUse: fu }, event.currentTarget)}
              >
                삭제
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {/* 연료 한 줄의 확인 줄은 그 목록 바로 아래 — 지울 줄이 바로 위에 보여야 판단할 수 있다. */}
      {pending?.kind === 'fuel' ? (
        <DeleteCautionRow
          id={cautionId}
          caution={fuelUseDeleteCaution(pending.fuelUse)}
          keepRef={keepRef}
          onKeep={closePending}
          onConfirm={() => {
            const fuelUseId = pending.fuelUse.id
            setPending(null)
            void guard(() => onRemoveFuel(fuelUseId))
          }}
        />
      ) : null}

      {/*
        구간을 만든 뒤 연료를 더한다 (`API_SPEC §2.13` · `#638`).

        `§2.13`이 이 경로의 존재 이유를 적고 있다 — *「정박이 끝나야 총 소모량을 아는
        것이 보통이다」*. 구간 생성 폼도 *「지금 몰라도 됩니다 — 구간을 먼저 만들고
        실적이 확인되면 추가할 수 있습니다」*로 안내하고 있었는데, **그 경로가 화면에
        없어 사실이 아닌 안내였다.**
      */}
      {fuelDraft === null ? (
        <button
          type="button"
          className="nu__fuel-add"
          onClick={() => {
            setFuelError(null)
            setFuelDraft({
              consumerType: choices.consumerTypes[0] ?? '',
              fuelType: choices.fuelTypes[0] ?? '',
              fuelTon: '',
            })
          }}
          data-testid="nu-fuel-add"
        >
          + 연료 기록 추가
        </button>
      ) : (
        <div className="nu__fuel-row" data-testid="nu-fuel-form">
          <select
            value={fuelDraft.consumerType}
            aria-label="소비원"
            onChange={(event) =>
              setFuelDraft((d) => (d ? { ...d, consumerType: event.target.value } : d))
            }
          >
            {choices.consumerTypes.map((code) => (
              <option key={code} value={code}>
                {labelOf(code, CONSUMER_TYPE_LABELS)}
              </option>
            ))}
          </select>

          <select
            value={fuelDraft.fuelType}
            aria-label="유종"
            onChange={(event) =>
              setFuelDraft((d) => (d ? { ...d, fuelType: event.target.value } : d))
            }
          >
            {choices.fuelTypes.map((code) => (
              <option key={code} value={code}>
                {fuelTypeText(code)}
              </option>
            ))}
          </select>

          <input
            type="number"
            min={0}
            step="0.01"
            placeholder="톤"
            aria-label="연료량"
            value={fuelDraft.fuelTon}
            onChange={(event) =>
              setFuelDraft((d) => (d ? { ...d, fuelTon: event.target.value } : d))
            }
          />

          <button
            type="button"
            className="nu__button"
            data-testid="nu-fuel-save"
            onClick={() => {
              // 화면이 볼 수 있는 것만 본다 — 중복 판정은 서버가 409로 한다.
              const message = validateFuelDraft(fuelDraft)
              if (message !== null) {
                setFuelError(message)
                return
              }
              setFuelError(null)
              void guard(async () => {
                await onAddFuel(fuelDraft)
                setFuelDraft(null)
              })
            }}
          >
            저장
          </button>

          <button type="button" className="nu__button" onClick={() => setFuelDraft(null)}>
            취소
          </button>
        </div>
      )}

      {fuelError ? <em className="nu__field-error" role="alert">{fuelError}</em> : null}

      {rowError ? (
        <ErrorState level="region" size="compact" message={rowError} />
      ) : null}

      <div className="nu__row-actions">
        {ongoing && !closing ? (
          <button type="button" className="nu__button" onClick={() => setClosing(true)} data-testid="nu-close">
            종료 시각 확정
          </button>
        ) : null}

        {ongoing && closing ? (
          <span className="nu__close-form">
            <input
              type="datetime-local"
              value={endValue}
              onChange={(event) => setEndValue(event.target.value)}
              aria-label="종료 시각"
            />
            <button
              type="button"
              className="nu__button"
              onClick={() =>
                guard(async () => {
                  await onClose(toIso(endValue))
                })
              }
            >
              확정
            </button>
            <button type="button" className="nu__button" onClick={() => setClosing(false)}>
              취소
            </button>
          </span>
        ) : null}

        <button
          type="button"
          className="nu__button nu__danger"
          aria-expanded={pending?.kind === 'period'}
          onClick={(event) => openPending({ kind: 'period' }, event.currentTarget)}
          data-testid="nu-remove"
        >
          삭제
        </button>
      </div>

      {pending?.kind === 'period' ? (
        <DeleteCautionRow
          id={cautionId}
          caution={periodDeleteCaution(period)}
          keepRef={keepRef}
          onKeep={closePending}
          onConfirm={() => {
            setPending(null)
            void guard(onRemove)
          }}
        />
      ) : null}
    </li>
  )
}

/**
 * 카드 안 확인 줄 (`#2130`). 항차 카드의 확인 줄(`VoyagePanel` · `#1598`)과 같은 규칙이다 —
 * 무엇이 달라지는지 적고, 실행 버튼은 동사로 끝나며, 초점은 「그만두기」에 먼저 간다.
 * Escape도 「그만두기」다. 모달을 두지 않는 이유도 같다 — 저장소에 모달이 없고
 * (`DESIGN_SYSTEM §16` 항목 17 미결), 확인할 대상이 줄 바로 위에 보여야 판단할 수 있다.
 */
function DeleteCautionRow({
  id,
  caution,
  keepRef,
  onKeep,
  onConfirm,
}: {
  id: string
  caution: DeleteCaution
  keepRef: RefObject<HTMLButtonElement | null>
  onKeep: () => void
  onConfirm: () => void
}) {
  return (
    <div
      className="nu__caution"
      role="group"
      aria-labelledby={id}
      data-testid="nu-caution"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onKeep()
      }}
    >
      <p id={id} className="nu__caution-text">
        {caution.message}
      </p>
      <div className="nu__caution-actions">
        <button
          type="button"
          className="nu__button nu__danger"
          onClick={onConfirm}
          data-testid="nu-caution-confirm"
        >
          {caution.confirm}
        </button>
        <button
          type="button"
          ref={keepRef}
          className="nu__text-action"
          onClick={onKeep}
          data-testid="nu-caution-keep"
        >
          그만두기
        </button>
      </div>
    </div>
  )
}

// ─── 입력 폼 ─────────────────────────────────────────────────────────────────

const EMPTY_FUEL = (consumerType: string, fuelType: string): FuelUseDraft => ({
  consumerType,
  fuelType,
  fuelTon: '',
})

function PeriodForm({
  choices,
  onSubmit,
}: {
  choices: { periodTypes: string[]; consumerTypes: string[]; fuelTypes: string[] }
  onSubmit: (draft: PeriodDraft) => Promise<void>
}) {
  const [periodType, setPeriodType] = useState('')
  const [startedAt, setStartedAt] = useState('')
  const [endedAt, setEndedAt] = useState('')
  const [portName, setPortName] = useState('')
  const [distanceNm, setDistanceNm] = useState('0')
  const [fuelUses, setFuelUses] = useState<FuelUseDraft[]>([])
  const [errors, setErrors] = useState<DraftErrors>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const ready = choices.periodTypes.length > 0 && choices.fuelTypes.length > 0

  /*
   * 선택지가 오지 않았으면 폼을 그리지 않는다. 기본값을 지어 내면 DB 제약과
   * 갈라지고, 사용자는 다 채운 뒤 저장 단계에서야 거부를 만난다.
   */
  if (!ready) {
    return (
      <ErrorState
        level="region"
        size="compact"
        message="입력 선택지를 불러오지 못해 구간을 추가할 수 없습니다."
      />
    )
  }

  const effectiveType = periodType || choices.periodTypes[0]
  /*
   * 접안·묘박은 이동 거리가 0이다 (`#2130` · D-11). 칸을 잠그고 `0`을 보낸다 — 서버도 같은
   * 규칙으로 422를 낸다(`API_SPEC §2.10`). 잠그기 전에 적어 둔 값은 지우지 않고 두었다가
   * 거리가 있는 유형으로 돌아가면 다시 보인다.
   */
  const locked = distanceLocked(effectiveType)

  const submit = async () => {
    const draft: PeriodDraft = {
      periodType: effectiveType,
      startedAt,
      endedAt: endedAt || null,
      portName: portName.trim() || null,
      distanceNm: locked ? '0' : distanceNm,
      fuelUses,
    }
    const found = validateDraft(draft)
    setErrors(found)
    if (hasErrors(found)) return

    setBusy(true)
    setFailure(null)
    try {
      await onSubmit({
        ...draft,
        startedAt: toIso(draft.startedAt),
        endedAt: draft.endedAt ? toIso(draft.endedAt) : null,
      })
    } catch (error) {
      setFailure(
        error instanceof NotUnderwayError
          ? error.message
          : '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="nu__form">
      {failure ? (
        <ErrorState level="region" size="compact" message={failure} />
      ) : null}

      <div className="nu__grid">
        <Field id="nu-period-type" label="구간 유형">
          {(control) => (
            <select
              {...control}
              value={effectiveType}
              onChange={(event) => setPeriodType(event.target.value)}
              data-testid="nu-period-type"
            >
              {choices.periodTypes.map((code) => (
                <option key={code} value={code}>
                  {labelOf(code, PERIOD_TYPE_LABELS)}
                </option>
              ))}
            </select>
          )}
        </Field>

        <Field id="nu-started-at" label="시작 시각" error={errors.startedAt}>
          {(control) => (
            <input
              {...control}
              type="datetime-local"
              value={startedAt}
              onChange={(event) => setStartedAt(event.target.value)}
              data-testid="nu-started-at"
            />
          )}
        </Field>

        {/* 비워 두는 것이 정상 경로다 — 정박이 시작될 때는 끝을 모른다. */}
        <Field
          id="nu-ended-at"
          label="종료 시각"
          hint="비워 두면 「진행 중」으로 기록됩니다."
          error={errors.endedAt}
        >
          {(control) => (
            <input
              {...control}
              type="datetime-local"
              value={endedAt}
              onChange={(event) => setEndedAt(event.target.value)}
              data-testid="nu-ended-at"
            />
          )}
        </Field>

        <Field id="nu-port-name" label="항구 (선택)">
          {(control) => (
            <input
              {...control}
              type="text"
              value={portName}
              onChange={(event) => setPortName(event.target.value)}
              maxLength={200}
            />
          )}
        </Field>

        {/* 왜 0이 기본인지 말해 준다 — 안 그러면 사용자가 빈칸으로 두거나 지어 낸다. */}
        <Field
          id="nu-distance"
          label={`이동 거리 (${DISPLAY_UNITS.distance})`}
          hint="접안·묘박은 0입니다. 운하 통과·표류·STS만 값이 있습니다."
          error={errors.distanceNm}
        >
          {(control) => (
            <input
              {...control}
              type="number"
              min={0}
              step="0.01"
              value={locked ? '0' : distanceNm}
              disabled={locked}
              onChange={(event) => setDistanceNm(event.target.value)}
              data-testid="nu-distance"
            />
          )}
        </Field>
      </div>

      <div className="nu__fuel-head">
        <h3>연료 소모</h3>
        <button
          type="button"
          className="nu__button"
          onClick={() =>
            setFuelUses((rows) => [
              ...rows,
              EMPTY_FUEL(choices.consumerTypes[0], choices.fuelTypes[0]),
            ])
          }
          data-testid="nu-add-fuel"
        >
          + 연료 추가
        </button>
      </div>

      {fuelUses.length === 0 ? (
        <p className="nu__hint">
          {/*
            `#638` 이전에는 이 안내가 **사실이 아니었다** — 구간을 만든 뒤 연료를
            더할 경로가 화면에 없어, 고치려면 구간을 지우고 다시 만들어야 했다.
            이제 구간 카드의 「+ 연료 기록 추가」가 그 경로다.
          */}
          지금 몰라도 됩니다 — 구간을 먼저 만들고 실적이 확인되면 추가할 수 있습니다.
        </p>
      ) : null}

      {fuelUses.map((row, index) => (
        <div className="nu__fuel-row" key={index}>
          <select
            value={row.consumerType}
            aria-label="소비원"
            onChange={(event) =>
              setFuelUses((rows) =>
                rows.map((r, i) =>
                  i === index ? { ...r, consumerType: event.target.value } : r,
                ),
              )
            }
          >
            {choices.consumerTypes.map((code) => (
              <option key={code} value={code}>
                {labelOf(code, CONSUMER_TYPE_LABELS)}
              </option>
            ))}
          </select>

          <select
            value={row.fuelType}
            aria-label="유종"
            onChange={(event) =>
              setFuelUses((rows) =>
                rows.map((r, i) => (i === index ? { ...r, fuelType: event.target.value } : r)),
              )
            }
          >
            {choices.fuelTypes.map((code) => (
              <option key={code} value={code}>
                {fuelTypeText(code)}
              </option>
            ))}
          </select>

          <input
            type="number"
            min={0}
            step="0.01"
            placeholder="톤"
            aria-label="연료량"
            value={row.fuelTon}
            onChange={(event) =>
              setFuelUses((rows) =>
                rows.map((r, i) => (i === index ? { ...r, fuelTon: event.target.value } : r)),
              )
            }
          />

          <button
            type="button"
            className="nu__button nu__danger"
            onClick={() => setFuelUses((rows) => rows.filter((_, i) => i !== index))}
          >
            삭제
          </button>
        </div>
      ))}

      {errors.fuelUses ? <em className="nu__field-error" role="alert">{errors.fuelUses}</em> : null}

      <button
        className="nu__button nu__submit"
        type="button"
        onClick={() => void submit()}
        disabled={busy}
        data-testid="nu-submit"
      >
        {busy ? '저장 중…' : '구간 저장'}
      </button>
    </div>
  )
}
