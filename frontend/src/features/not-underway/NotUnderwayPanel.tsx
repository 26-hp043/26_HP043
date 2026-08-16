import { useCallback, useEffect, useState } from 'react'
import { createApiNotUnderwayProvider, NotUnderwayError } from './apiProvider'
import {
  CONSUMER_TYPE_LABELS,
  PERIOD_TYPE_LABELS,
  formatRange,
  hasErrors,
  labelOf,
  toIso,
  toLocalInput,
  totalFuelTon,
  validateDraft,
  type DraftErrors,
} from './periodRules'
import type { FuelUseDraft, NotUnderwayProvider, Period, PeriodDraft } from './types'
import './NotUnderwayPanel.css'

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
}: {
  vesselId: string
  /** 테스트가 갈아 끼운다 — 이 저장소의 vitest에는 DOM도 네트워크도 없다. */
  provider?: NotUnderwayProvider
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
          className="nu__toggle"
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
        <p className="nu__error" role="alert">
          {failure}
        </p>
      ) : null}

      {formOpen ? (
        <PeriodForm
          choices={choices}
          onSubmit={async (draft) => {
            await api.create(vesselId, draft)
            setFormOpen(false)
            await reload()
          }}
        />
      ) : null}

      {periods === null && !failure ? (
        <p className="nu__loading" aria-busy="true">
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
              onClose={async (endedAt) => {
                await api.close(period.id, endedAt)
                await reload()
              }}
              onRemove={async () => {
                await api.remove(period.id)
                await reload()
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
  onClose,
  onRemove,
}: {
  period: Period
  onClose: (endedAt: string) => Promise<void>
  onRemove: () => Promise<void>
}) {
  const [closing, setClosing] = useState(false)
  const [endValue, setEndValue] = useState(() => toLocalInput(new Date().toISOString()))
  const [rowError, setRowError] = useState<string | null>(null)

  const guard = async (action: () => Promise<void>) => {
    try {
      setRowError(null)
      await action()
    } catch (error) {
      // 서버 문구를 그대로 쓴다 — 겹침이면 상대 구간의 시각까지 담겨 온다.
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

      <dl className="nu__figures">
        <div>
          <dt>항구</dt>
          <dd>{period.portName ?? '—'}</dd>
        </div>
        <div>
          <dt>연료</dt>
          {/* 0건과 0톤은 다르다 — 안 넣은 것과 안 쓴 것을 같게 적지 않는다. */}
          <dd className="num">
            {period.fuelUses.length === 0 ? '미입력' : `${totalFuelTon(period)} t`}
          </dd>
        </div>
        <div>
          <dt>이동 거리</dt>
          <dd className="num">{period.distanceNm} nm</dd>
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
              <span className="num">{fu.fuelTon} t</span>
              {/* CF는 서버가 뜬 snapshot이다. 표시만 하고 편집하지 않는다. */}
              <span className="num nu__cf">CF {fu.cfUsed}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {rowError ? (
        <p className="nu__error" role="alert">
          {rowError}
        </p>
      ) : null}

      <div className="nu__row-actions">
        {ongoing && !closing ? (
          <button type="button" onClick={() => setClosing(true)} data-testid="nu-close">
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
              onClick={() =>
                guard(async () => {
                  await onClose(toIso(endValue))
                })
              }
            >
              확정
            </button>
            <button type="button" onClick={() => setClosing(false)}>
              취소
            </button>
          </span>
        ) : null}

        <button
          type="button"
          className="nu__danger"
          onClick={() => guard(onRemove)}
          data-testid="nu-remove"
        >
          삭제
        </button>
      </div>
    </li>
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
      <p className="nu__error" role="alert">
        입력 선택지를 불러오지 못해 구간을 추가할 수 없습니다.
      </p>
    )
  }

  const submit = async () => {
    const draft: PeriodDraft = {
      periodType: periodType || choices.periodTypes[0],
      startedAt,
      endedAt: endedAt || null,
      portName: portName.trim() || null,
      distanceNm,
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
        <p className="nu__error" role="alert">
          {failure}
        </p>
      ) : null}

      <div className="nu__grid">
        <label>
          <span>구간 유형</span>
          <select
            value={periodType || choices.periodTypes[0]}
            onChange={(event) => setPeriodType(event.target.value)}
            data-testid="nu-period-type"
          >
            {choices.periodTypes.map((code) => (
              <option key={code} value={code}>
                {labelOf(code, PERIOD_TYPE_LABELS)}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>시작 시각</span>
          <input
            type="datetime-local"
            value={startedAt}
            onChange={(event) => setStartedAt(event.target.value)}
            data-testid="nu-started-at"
          />
          {errors.startedAt ? <em className="nu__field-error">{errors.startedAt}</em> : null}
        </label>

        <label>
          <span>종료 시각</span>
          <input
            type="datetime-local"
            value={endedAt}
            onChange={(event) => setEndedAt(event.target.value)}
            data-testid="nu-ended-at"
          />
          {/* 비워 두는 것이 정상 경로다 — 정박이 시작될 때는 끝을 모른다. */}
          <em className="nu__hint">비워 두면 「진행 중」으로 기록됩니다.</em>
          {errors.endedAt ? <em className="nu__field-error">{errors.endedAt}</em> : null}
        </label>

        <label>
          <span>항구 (선택)</span>
          <input
            type="text"
            value={portName}
            onChange={(event) => setPortName(event.target.value)}
            maxLength={200}
          />
        </label>

        <label>
          <span>이동 거리 (nm)</span>
          <input
            type="number"
            min={0}
            step="0.01"
            value={distanceNm}
            onChange={(event) => setDistanceNm(event.target.value)}
            data-testid="nu-distance"
          />
          {/* 왜 0이 기본인지 말해 준다 — 안 그러면 사용자가 빈칸으로 두거나 지어 낸다. */}
          <em className="nu__hint">
            접안·묘박은 0입니다. 운하 통과·표류·STS만 값이 있습니다.
          </em>
          {errors.distanceNm ? (
            <em className="nu__field-error">{errors.distanceNm}</em>
          ) : null}
        </label>
      </div>

      <div className="nu__fuel-head">
        <h3>연료 소모</h3>
        <button
          type="button"
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
                {code}
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
            className="nu__danger"
            onClick={() => setFuelUses((rows) => rows.filter((_, i) => i !== index))}
          >
            삭제
          </button>
        </div>
      ))}

      {errors.fuelUses ? <em className="nu__field-error">{errors.fuelUses}</em> : null}

      <button
        className="nu__submit"
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
