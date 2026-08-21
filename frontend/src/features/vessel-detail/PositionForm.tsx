import { useState } from 'react'
import { detailStatusText } from '../fleet/fleetRules'
import { VesselDetailError } from './apiProvider'
import {
  DETAIL_STATUS_BY_STATE,
  detailStatusFor,
  hasPositionErrors,
  initialPositionDraft,
  isEmptyPayload,
  positionPayload,
  validatePosition,
  type PositionDraft,
  type PositionErrors,
} from './positionRules'
import type { VesselDetailProvider, VesselSpec } from './types'

/**
 * 위치·운항 상태 입력 — `2-8 선박 상세`의 「현재 상태」 카드 안 (`API_SPEC §2.6`).
 *
 * ## 왜 이 카드 안인가
 *
 * 새 화면을 만들지 않는다 — 화면 신설은 `AGENTS §3.2.1`상 UIFLOW 소관이다.
 * 그리고 **값을 본 자리에서 고칠 수 있어야 한다.** 이 카드는 이미 운항 상태·세부
 * 상태·위치·갱신 시각을 보여 주고 있었고, **읽기만 가능했다.** 쓰는 경로가 없어
 * 위치가 시드 이후 고정됐고, 대시보드 `PositionChart`가 빈 채로 떴다.
 *
 * ## 평소에는 접어 둔다
 *
 * 이 카드의 주 용도는 조회다. 폼을 늘 펴 두면 「현재 상태」를 읽으러 온 사람이
 * 입력창부터 만난다. 「수정」을 누르면 열리고, 저장하거나 취소하면 닫힌다.
 *
 * ## 저장 후 갱신 시각을 화면이 만들지 않는다
 *
 * `position_updated_at`은 서버가 확정한다(`§2.6`). 응답으로 온 선박 객체를 그대로
 * 위로 올려 카드가 다시 그리게 한다 — 화면이 `new Date()`를 찍으면 단말 시계에
 * 따라 「언제 기준 위치인가」가 갈린다.
 */
export function PositionForm({
  vessel,
  provider,
  onSaved,
}: {
  vessel: VesselSpec
  provider: VesselDetailProvider
  /** 갱신된 선박 객체. 카드가 이 값으로 다시 그린다. */
  onSaved: (vessel: VesselSpec) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<PositionDraft>(() => initialPositionDraft(vessel))
  const [errors, setErrors] = useState<PositionErrors>({})
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const base = initialPositionDraft(vessel)
  const payload = positionPayload(draft, base)
  const nothingToSave = isEmptyPayload(payload)

  function start() {
    setDraft(initialPositionDraft(vessel))
    setErrors({})
    setFailure(null)
    setOpen(true)
  }

  function close() {
    setOpen(false)
    setErrors({})
    setFailure(null)
  }

  function setState(next: string) {
    // 운항 상태가 바뀌면 세부 상태를 다시 고른다 — 규칙은 `positionRules`가 소유한다.
    setDraft((prev) => ({
      ...prev,
      underwayState: next,
      detailStatus: detailStatusFor(next, prev.detailStatus),
    }))
  }

  async function save() {
    const found = validatePosition(draft)
    setErrors(found)
    setFailure(null)
    if (hasPositionErrors(found)) return
    if (nothingToSave) return

    setBusy(true)
    try {
      const updated = await provider.updatePosition(vessel.id, payload)
      onSaved(updated)
      setOpen(false)
    } catch (error) {
      /*
       * 서버 문구를 그대로 쓴다. 화면 사본이 서버와 갈라졌을 때 사용자에게
       * 사실을 전하는 유일한 경로다 — `field`가 오면 그 칸 아래에 붙인다.
       */
      if (error instanceof VesselDetailError && error.field) {
        setErrors({ [fieldKey(error.field)]: error.message })
      } else {
        setFailure(error instanceof Error ? error.message : '저장하지 못했습니다.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className="vd__pos-open" onClick={start}>
        위치 · 상태 수정
      </button>
    )
  }

  const detailOptions =
    draft.underwayState === 'UNDER_WAY' || draft.underwayState === 'NOT_UNDER_WAY'
      ? DETAIL_STATUS_BY_STATE[draft.underwayState]
      : []

  return (
    <div className="vd__pos">
      <div className="vd__pos-row">
        <label className="vd__pos-field">
          <span>운항 상태</span>
          <select
            value={draft.underwayState}
            onChange={(e) => setState(e.target.value)}
            aria-invalid={errors.underwayState !== undefined}
          >
            <option value="">선택 안 함</option>
            <option value="UNDER_WAY">운항 중</option>
            <option value="NOT_UNDER_WAY">정박 중</option>
          </select>
          {errors.underwayState ? (
            <span className="vd__pos-error">{errors.underwayState}</span>
          ) : null}
        </label>

        <label className="vd__pos-field">
          <span>세부 상태</span>
          <select
            value={draft.detailStatus}
            disabled={detailOptions.length === 0}
            onChange={(e) => setDraft({ ...draft, detailStatus: e.target.value })}
            aria-invalid={errors.detailStatus !== undefined}
          >
            {/*
             * `UNDER_WAY`는 허용값이 하나뿐이라 빈 항목을 두지 않는다 — 고를 것이
             * 없는 자리에 「선택 안 함」을 내밀면 그것이 유효한 선택으로 읽힌다.
             */}
            {draft.underwayState === 'UNDER_WAY' ? null : <option value="">선택</option>}
            {detailOptions.map((code) => (
              <option key={code} value={code}>
                {detailStatusText(code)}
              </option>
            ))}
          </select>
          {errors.detailStatus ? (
            <span className="vd__pos-error">{errors.detailStatus}</span>
          ) : null}
        </label>
      </div>

      <div className="vd__pos-row">
        <Coordinate
          id="vd-lat"
          label="위도"
          hint="−90 ~ 90"
          value={draft.lat}
          error={errors.lat}
          onChange={(v) => setDraft({ ...draft, lat: v })}
        />
        <Coordinate
          id="vd-lon"
          label="경도"
          hint="−180 ~ 180"
          value={draft.lon}
          error={errors.lon}
          onChange={(v) => setDraft({ ...draft, lon: v })}
        />
      </div>

      {failure ? (
        <p className="vd__pos-error" role="alert">
          {failure}
        </p>
      ) : null}

      <div className="vd__pos-actions">
        <button type="button" onClick={save} disabled={busy || nothingToSave}>
          {busy ? '저장 중…' : '저장'}
        </button>
        <button type="button" className="vd__pos-cancel" onClick={close} disabled={busy}>
          취소
        </button>
        {/*
         * 왜 못 누르는지 적는다. 빈 본문은 200이지만 서버가 갱신 시각을 건드리지
         * 않아, 누르면 「저장했는데 아무 일도 없다」가 된다 (`§2.6`).
         */}
        {nothingToSave ? <span className="vd__pos-note">바뀐 값이 없습니다.</span> : null}
      </div>
    </div>
  )
}

function Coordinate({
  id,
  label,
  hint,
  value,
  error,
  onChange,
}: {
  id: string
  label: string
  hint: string
  value: string
  error?: string
  onChange: (value: string) => void
}) {
  return (
    <label className="vd__pos-field" htmlFor={id}>
      <span>
        {label} <em>{hint}</em>
      </span>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error !== undefined}
      />
      {error ? <span className="vd__pos-error">{error}</span> : null}
    </label>
  )
}

/** 서버 `field`(스네이크)를 폼 키로 옮긴다. 모르는 이름은 위치 칸에 붙이지 않는다. */
function fieldKey(field: string): keyof PositionDraft {
  switch (field) {
    case 'underway_state':
      return 'underwayState'
    case 'current_lat':
      return 'lat'
    case 'current_lon':
      return 'lon'
    default:
      return 'detailStatus'
  }
}
