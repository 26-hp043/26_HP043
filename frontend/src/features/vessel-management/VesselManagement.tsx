import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { ApplicabilityBadge } from '../../components/ApplicabilityBadge'
import { PageHeader } from '../../components/PageHeader'
import { VESSEL_GRID, VESSEL_PATHS } from '../../components/vesselShape'
import { SCREEN_BY_ID } from '../../screens'
import { SHIP_TYPES } from '../vessel-registration/shipTypes'
import { useFuelOptions, type FuelOption } from '../parameters/fuelCatalog'
// 상태 칩은 대시보드와 **같은 컴포넌트**를 쓴다 — 베끼면 두 화면의 표기가 갈린다.
import { UnderwayChip } from '../fleet/UnderwayChip'
import { toUnderwayState } from '../fleet/fleetRules'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import type { Vessel } from '../vessel-registration/types'
import {
  EDIT_FIELD,
  clearAttemptNotice,
  isEmptyPatch,
  recalcNotice,
  toEditState,
  toUpdateRequest,
  validateEdit,
  type EditErrors,
  type VesselEditState,
} from './editRules'
import { DISPLAY_UNIT_DAILY_FUEL } from '../../display/format'
import {
  LOADED_PARTIAL_HINT,
  MISSING,
  SORT_KEYS,
  SORT_LABEL,
  type BlockedReason,
  blockedReasons,
  capacityCell,
  dailyFuelCell,
  deleteConfirmMessage,
  emptyMessage,
  listTitle,
  referenceSpeedCell,
  saveFailureNotice,
  shipTypeLabel,
  sortVessels,
  type VesselSortKey,
} from './listRules'
import { VesselManagementError } from './provider'
import { createVesselManagementProvider } from './providerSelection'
import { isOffice, useAuthUser } from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'
import './VesselManagement.css'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'

/**
 * 선박 관리 화면 — 목록 · 수정 · 삭제 (#510).
 *
 * `PRD §6.2 SCR-002`(Vessel Management) · `PRD §6.1`(계층 밖 네비게이션) ·
 * `PRD §5`(선박 관리 MUST).
 *
 * ## 등록은 여기서 하지 않는다
 *
 * 등록은 온보딩 흐름(`UIFLOW 1-1 → 1-2 → 1-3`)이고 `#441`이 전용 화면을 이미 갖고
 * 있다. 이 화면은 **등록 화면으로 보내는 링크**만 둔다 — 같은 폼을 두 벌 두면
 * 검증 규칙이 갈리고, 갈린 쪽이 어디인지 화면을 봐서는 알 수 없다.
 *
 * ## 목록을 다시 읽는 시점
 *
 * 수정·삭제 뒤에 **서버 응답으로 로컬 상태를 갱신**하고, 목록 전체를 다시 부르지
 * 않는다. 다시 부르면 사용자가 보던 스크롤·검색어가 초기화되고, 무엇보다 **커서
 * 페이지네이션에서 지금 보고 있는 페이지로 돌아온다는 보장이 없다.**
 *
 * ## 커서를 화면이 갖는다
 *
 * `GET /vessels`는 커서 페이지네이션이다(`routes/vessels.py:54`). 「더 보기」를
 * 두지 않으면 **21척째부터 조용히 사라진다** — 사용자는 없는 배를 그리워할 수 없다.
 *
 * ## 진행 중인 조작은 선박 id에 묶는다 (#1102)
 *
 * 저장·삭제는 응답이 오기 전에 다른 선박의 조작이 시작될 수 있다. 종전에는 수정 폼
 * 하나·`saving` 하나·`deletingId` 하나가 화면 전체의 상태였다 —
 *
 * - A 저장 중 B 「수정」 → A 성공이 **B 폼을 닫아 입력이 사라지고**, A의 422가
 *   B 폼 같은 칸에 붙었다.
 * - A 삭제 중 B 삭제 → A가 끝나면 B의 「삭제 중…」도 풀려 다시 누르면 404였다.
 *
 * 그래서 폼은 `{ id, state, errors }` 한 덩어리로 두고 응답이 오면 **요청 당시의
 * id와 대조**해 그 선박의 폼일 때만 반영한다. 삭제 진행은 id 집합이다.
 */
export function VesselManagement() {
  const provider = useMemo(() => createVesselManagementProvider(), [])
  /*
   * 제원 수정·삭제는 사무직 전용이다 (`API_SPEC §1.2` · #672). 현장직에게는 버튼을 두지
   * 않고 짧은 안내만 남긴다 — 눌러서 403을 받게 하는 것은 「되는 것처럼 보이는」 것이다.
   */
  const office = isOffice(useAuthUser())
  // 기본 연료 선택지는 서버가 준다 (#542). 종전에는 고정표를 직접 순회했다.
  const { fuels, loading: fuelsLoading, failed: fuelsFailed } = useFuelOptions()

  const [vessels, setVessels] = useState<Vessel[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  /** 열려 있는 수정 폼. 어느 선박의 폼인지·입력·오류를 한 덩어리로 갖는다 (#1102 ⑴). */
  const [edit, setEdit] = useState<EditSession | null>(null)
  /** 저장 응답을 기다리는 선박. 폼이 다른 선박으로 바뀌어도 이 값은 요청을 따라간다. */
  const [savingId, setSavingId] = useState<string | null>(null)
  /*
   * 마지막 저장 실패. **어느 선박의 실패인지**를 갖고, 표시할 자리는 렌더에서 정한다 —
   * 그 선박의 폼이 아직 열려 있으면 폼 안에, 폼이 다른 선박으로 바뀌었거나 닫혔으면
   * 폼 밖에 이름을 달아 알린다. 응답이 온 시점의 폼을 비동기 콜백에서 읽지 않는다.
   */
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null)

  /*
   * 기본이 이름순이 아니다 — 근거는 `listRules.SORT_KEYS` 주석에 있다.
   * 정렬은 파생이라 목록 상태(`vessels`)를 건드리지 않는다. 건드리면 수정 중이던
   * 행이 정렬 때문에 사라지거나 다른 배의 폼으로 바뀐다.
   */
  const [sortKey, setSortKey] = useState<VesselSortKey>('gaps')
  const sorted = useMemo(() => sortVessels(vessels, sortKey), [vessels, sortKey])

  /** 삭제 응답을 기다리는 선박들. 한 칸이면 먼저 끝난 삭제가 다른 배의 표시를 푼다 (#1102 ⑵). */
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(() => new Set())
  const [actionNotice, setActionNotice] = useState<string | null>(null)
  /*
   * 조작(저장·삭제)의 실패. `loadError`와 가른다 — 종전에는 삭제 실패가 `loadError`에
   * 남아 **다음 성공 안내와 나란히** 보였다. 새 조작이 시작되면 비운다.
   */
  const [actionError, setActionError] = useState<string | null>(null)

  const loadPage = useCallback(
    async (cursor?: string) => {
      setLoading(true)
      setLoadError(null)
      try {
        const page = await provider.list(cursor ? { cursor } : {})
        // 이어 붙인다 — 커서 페이지네이션은 앞 페이지를 다시 주지 않는다.
        setVessels((prev) => (cursor ? [...prev, ...page.vessels] : page.vessels))
        setNextCursor(page.nextCursor)
        setHasMore(page.hasMore)
      } catch (error) {
        setLoadError(
          error instanceof VesselManagementError
            ? error.message
            : '선박 목록을 불러오지 못했습니다.',
        )
      } finally {
        setLoading(false)
      }
    },
    [provider],
  )

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  const startEdit = (vessel: Vessel) => {
    setEdit({ id: vessel.id, state: toEditState(vessel), errors: {} })
    setSaveFailure(null)
    setActionNotice(null)
    setActionError(null)
  }

  const cancelEdit = () => {
    setEdit(null)
    setSaveFailure(null)
  }

  /** 폼 오류를 **그 선박의 폼이 아직 열려 있을 때만** 바꾼다. */
  const setEditErrorsFor = (vesselId: string, errors: EditErrors) =>
    setEdit((current) => (current !== null && current.id === vesselId ? { ...current, errors } : current))

  const editing = edit === null ? null : (vessels.find((v) => v.id === edit.id) ?? null)

  const handleSave = async () => {
    if (editing === null || edit === null) return
    setSaveFailure(null)
    const errors = validateEdit(edit.state, fuels, editing)
    if (Object.keys(errors).length > 0) {
      setEditErrorsFor(editing.id, errors)
      return
    }
    const patch = toUpdateRequest(editing, edit.state)
    if (isEmptyPatch(patch)) {
      // 보낼 것이 없으면 요청을 만들지 않는다. 「저장됨」을 표시하면 사용자가 비운
      // 칸이 지워진 것으로 읽는다(`clearAttemptNotice`가 그 사실을 이미 알린다).
      setEditErrorsFor(editing.id, { [EDIT_FIELD.form]: '바뀐 값이 없습니다.' })
      return
    }

    // 요청 당시의 선박을 붙잡는다 — 응답이 올 때 폼은 다른 선박의 것일 수 있다.
    const target = editing
    setSavingId(target.id)
    setEditErrorsFor(target.id, {})
    setActionError(null)
    try {
      const updated = await provider.update(target.id, patch)
      setVessels((prev) => prev.map((v) => (v.id === updated.id ? updated : v)))
      setActionNotice(`${updated.name}의 정보를 저장했습니다.`)
      // 이 선박의 폼일 때만 닫는다. 그 사이 열린 다른 선박의 폼은 그대로 둔다.
      setEdit((current) => (current !== null && current.id === target.id ? null : current))
    } catch (error) {
      // 어느 선박의 실패인지만 기록한다. 폼 안에 붙일지 밖에 알릴지는 렌더가 정한다.
      setSaveFailure({
        id: target.id,
        name: target.name,
        message: error instanceof VesselManagementError ? error.message : '수정에 실패했습니다.',
        field: error instanceof VesselManagementError ? error.field : undefined,
      })
    } finally {
      setSavingId((current) => (current === target.id ? null : current))
    }
  }

  const handleDelete = async (vessel: Vessel) => {
    setDeletingIds((prev) => new Set(prev).add(vessel.id))
    setSaveFailure(null)
    setActionNotice(null)
    setActionError(null)
    try {
      await provider.remove(vessel.id)
      setVessels((prev) => prev.filter((v) => v.id !== vessel.id))
      setEdit((current) => (current !== null && current.id === vessel.id ? null : current))
      setActionNotice(`${vessel.name}을(를) 목록에서 제거했습니다.`)
    } catch (error) {
      setActionError(
        error instanceof VesselManagementError ? error.message : '삭제에 실패했습니다.',
      )
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev)
        next.delete(vessel.id)
        return next
      })
    }
  }

  /*
   * 저장 실패를 놓을 자리. 그 선박의 폼이 열려 있으면 폼 오류에 합치고(서버가 필드를
   * 지목했으면 그 입력창, 아니면 폼 상단), 아니면 폼 밖 안내가 된다 (#1102 ⑴).
   */
  const failureInForm = saveFailure !== null && edit !== null && saveFailure.id === edit.id
  const formErrors: EditErrors =
    edit === null
      ? {}
      : failureInForm
        ? { ...edit.errors, [saveFailure.field ?? EDIT_FIELD.form]: saveFailure.message }
        : edit.errors
  const shownActionError =
    actionError ??
    (saveFailure !== null && !failureInForm
      ? saveFailureNotice(saveFailure.name, saveFailure.message)
      : null)

  return (
    <section className="vessel-management">
      {/*
        이름을 손으로 적고 있었다 — 사이드바는 `screens.ts`를 쓰는데 여기만
        문자열이라, 한쪽을 고치면 다른 쪽이 남는다.
      */}
      <PageHeader screen="VESSEL_MANAGEMENT">
        <p className="page-head__sub">
          보유 선박의 제원을 확인하고 수정합니다. 제원이 비어 있으면 CII 계산과 항로
          비교가 실행되지 않으므로, 빠진 값을 함께 표시합니다.
        </p>
      </PageHeader>

      <div className="vessel-management__actions">
        <Link
          className="vessel-management__primary-link"
          to={SCREEN_BY_ID.VESSEL_REGISTRATION.path}
        >
          선박 등록
        </Link>
        <Link className="vessel-management__link" to={SCREEN_BY_ID.MAINBOARD.path}>
          대시보드로 이동
        </Link>
      </div>

      {actionNotice !== null && (
        <p className="vessel-management__notice" role="status">
          {actionNotice}
        </p>
      )}

      {loadError !== null && (
        <ErrorState level="region" size="compact" message={loadError} />
      )}

      {shownActionError !== null && (
        <ErrorState level="region" size="compact" message={shownActionError} />
      )}

      {/*
        최초 조회 중에는 **본문이 통째로 비어 있었다** (`#824` ⑷).

        `loading`을 읽는 렌더 분기가 「더 보기」 버튼뿐이었고 그 버튼은 `hasMore`일
        때만 존재한다. 그래서 첫 로드 동안 오류도·빈 상태도(`!loading`으로 배제)·
        목록도 없어 **머리말과 링크 두 개만 남았다** — 사용자는 선박이 없는 화면으로
        읽는다.

        다른 목록 화면은 전부 이 자리를 채운다(`FleetDashboard`·`VoyagePanel`·
        `NotUnderwayPanel`).
      */}
      {loading && vessels.length === 0 && loadError === null && (
        <p className="vessel-management__empty" aria-busy="true" role="status">
          선박 목록을 불러오는 중입니다…
        </p>
      )}

      {/*
        빈 목록 판정에 `hasMore`를 넣는다 (#1102 ⑶). 불러온 20척을 모두 지웠는데
        뒤 페이지가 남아 있으면 「등록된 선박이 없습니다」는 거짓이다.
      */}
      {!loading && vessels.length === 0 && loadError === null && (
        <p className="vessel-management__empty">{emptyMessage(hasMore)}</p>
      )}

      {vessels.length > 0 && (
        <section className="card vm" aria-label="선박 목록">
          <div className="card__head">
            {/*
              「불러온 만큼」임을 밝힌다 (#1102 ⑶). `GET /vessels`가 커서 페이지네이션이라
              화면은 전체 수를 모르고, 정렬은 **받은 페이지 안에서만** 성립한다 —
              전체를 정렬한 것처럼 보이면 21척째부터 조용히 어긋난다.
            */}
            <h2 className="card__title">{listTitle(vessels.length, hasMore)}</h2>
            <label className="sort">
              <span className="sr-only">정렬 기준</span>
              <select
                value={sortKey}
                onChange={(event) => setSortKey(event.target.value as VesselSortKey)}
                data-testid="vessel-sort"
              >
                {SORT_KEYS.map((key) => (
                  <option key={key} value={key}>
                    {SORT_LABEL[key]}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {hasMore && <p className="vm__partial">{LOADED_PARTIAL_HINT}</p>}

          <ul className="vm__list">
            {/*
              열 이름을 **한 번만** 적는다. 종전에는 행마다 `dt`가 따라다녀
              같은 라벨이 네 번 반복되고, 정작 값은 세로로 맞지 않았다.

              `aria-hidden`인 이유 — 아래 각 셀이 `sr-only` 라벨을 그대로 갖고
              있어, 이 줄까지 읽히면 스크린 리더에서 이름이 두 번 나온다.
            */}
            <li className="vm__head" aria-hidden="true">
              <span />
              <span>선박</span>
              <span>선종</span>
              <span>용량</span>
              <span>기준속도</span>
              <span>일일 연료</span>
              <span>운항 상태</span>
              <span />
            </li>

            {sorted.map((vessel) => {
              const capacity = capacityCell(vessel)
              const blocked = blockedReasons(vessel)
              const isEditing = edit !== null && edit.id === vessel.id
              const isDeleting = deletingIds.has(vessel.id)
              return (
                <li className="vm__item" key={vessel.id}>
                  <div className="vm__row">
                    <VesselSilhouette />

                    <div className="vm__ident">
                      <Link className="vm__name" to={`/vessels/${vessel.id}`}>
                        {vessel.name}
                      </Link>
                      <span className="vm__meta">
                        <span className="vm__imo">IMO {vessel.imo_number}</span>
                        {/*
                          CII 적용 대상 여부는 등록 결과 화면에만 있었다 (`#653`).
                          선박을 식별하는 자리마다 같은 배지를 둔다.
                        */}
                        <ApplicabilityBadge
                          isCiiApplicableHint={vessel.is_cii_applicable_hint}
                          grossTonnage={vessel.gross_tonnage}
                          vesselName={vessel.name}
                        />
                      </span>
                    </div>

                    <div className="vm__cell">
                      <span className="sr-only">선종 </span>
                      {shipTypeLabel(vessel.ship_type)}
                    </div>

                    {/*
                      단위를 값 옆에 둔다. 선종마다 축이 달라(`capacityCell`) 열 이름
                      하나로는 못 적는데, 그렇다고 라벨을 행마다 왼쪽에 세우면 값이
                      세로로 안 맞는다. 값 뒤에 붙이면 열은 훑어지고 축은 남는다.
                    */}
                    <div className="vm__cell vm__cell--num">
                      <span className="sr-only">용량 </span>
                      {capacity.value}
                      <span className="vm__unit"> {capacity.label}</span>
                    </div>

                    {/*
                      완성도 막대를 값 두 칸으로 바꿨다. 막대는 「2/3」까지만 말하고
                      **무엇이** 빠졌는지는 아래 문장을 읽어야 했다. 값을 열에 두면
                      `—`가 그 자리에 서고, 사용자가 채울 칸과 화면의 칸이 맞는다.
                    */}
                    <ValueCell label="기준속도" value={referenceSpeedCell(vessel)} />
                    <ValueCell label="일일 연료" value={dailyFuelCell(vessel)} />

                    <div className="vm__cell">
                      <span className="sr-only">운항 상태 </span>
                      <UnderwayChip
                        vessel={{
                          underwayState: toUnderwayState(vessel.underway_state),
                          detailStatus: vessel.detail_status,
                        }}
                      />
                    </div>

                    <div className="vm__actions">
                      {office ? (
                        <>
                          <button
                            type="button"
                            className="vessel-management__button"
                            onClick={() => (isEditing ? cancelEdit() : startEdit(vessel))}
                          >
                            {isEditing ? '취소' : '수정'}
                          </button>
                          <button
                            type="button"
                            className="vessel-management__button vessel-management__button--danger"
                            onClick={() => {
                              // 되돌리기 어려운 조작이라 확인을 받는다. soft delete임을
                              // 문구가 밝힌다(`listRules.deleteConfirmMessage`).
                              if (globalThis.confirm(deleteConfirmMessage(vessel))) {
                                void handleDelete(vessel)
                              }
                            }}
                            disabled={isDeleting}
                          >
                            {isDeleting ? '삭제 중…' : '삭제'}
                          </button>
                        </>
                      ) : (
                        <span className="vm__office-only">{OFFICE_ONLY_ACTION_HINT}</span>
                      )}
                    </div>
                  </div>

                  {blocked.length > 0 && <BlockedSpecLine reasons={blocked} />}

                  {isEditing && (
                    <EditForm
                      vessel={vessel}
                      state={edit.state}
                      errors={formErrors}
                      fuels={fuels}
                      fuelsLoading={fuelsLoading}
                      fuelsFailed={fuelsFailed}
                      saving={savingId === vessel.id}
                      onChange={(next) =>
                        setEdit((current) =>
                          current !== null && current.id === vessel.id
                            ? { ...current, state: next }
                            : current,
                        )
                      }
                      onSave={() => void handleSave()}
                      onCancel={cancelEdit}
                    />
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {hasMore && nextCursor !== null && (
        <button
          type="button"
          className="vessel-management__button"
          onClick={() => void loadPage(nextCursor)}
          disabled={loading}
        >
          {loading ? '불러오는 중…' : '더 보기'}
        </button>
      )}
    </section>
  )
}

/** 열려 있는 수정 폼 — 어느 선박의 것인지를 입력·오류와 떼어 놓지 않는다 (#1102 ⑴). */
interface EditSession {
  id: string
  state: VesselEditState
  errors: EditErrors
}

/** 저장 실패 한 건. `id`가 폼과 맞을 때만 폼 안에 붙는다. */
interface SaveFailure {
  id: string
  name: string
  message: string
  field?: string
}

interface EditFormProps {
  vessel: Vessel
  state: VesselEditState
  errors: EditErrors
  /** 연료 선택지. 화면이 고정표를 순회하지 않는다 (#542). */
  fuels: readonly FuelOption[]
  fuelsLoading: boolean
  fuelsFailed: boolean
  saving: boolean
  onChange: (next: VesselEditState) => void
  onSave: () => void
  onCancel: () => void
}

/**
 * 수정 폼.
 *
 * **IMO는 입력창이 아니다.** 서버가 `imo_number`를 아예 받지 않으므로
 * (`api/schemas/vessel.py:47`) 바꿀 수 있는 것처럼 보이면 안 된다.
 */
function EditForm({
  vessel,
  state,
  errors,
  fuels,
  fuelsLoading,
  fuelsFailed,
  saving,
  onChange,
  onSave,
  onCancel,
}: EditFormProps) {
  const set = (patch: Partial<VesselEditState>) => onChange({ ...state, ...patch })
  const clearNotice = clearAttemptNotice(vessel, state)
  const recalc = recalcNotice(vessel, state)

  return (
    <form
      className="vessel-management__form"
      onSubmit={(event) => {
        event.preventDefault()
        onSave()
      }}
    >
      {errors[EDIT_FIELD.form] !== undefined && (
        <ErrorState level="region" size="compact" message={errors[EDIT_FIELD.form]} />
      )}

      {/* 근거는 `API_SPEC §2.4` — 화면에는 적지 않는다 (#529). */}
      <p className="vessel-management__readonly">
        IMO 번호 <strong>{vessel.imo_number}</strong> — 등록 후에는 변경할 수 없습니다.
      </p>

      <Field id="vm-name" label="선명" error={errors[EDIT_FIELD.name]}>
        {(control) => (
          <input
            {...control}
            className="vessel-management__control"
            value={state.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        )}
      </Field>

      <Field id="vm-shipType" label="선종" error={errors[EDIT_FIELD.shipType]}>
        {(control) => (
          <select
            {...control}
            className="vessel-management__control"
            value={state.shipType}
            onChange={(e) => set({ shipType: e.target.value })}
          >
            <option value="">선택</option>
            {SHIP_TYPES.map((option) => (
              <option key={option.code} value={option.code}>
                {option.label} ({option.code})
              </option>
            ))}
          </select>
        )}
      </Field>

      <Field id="vm-grossTonnage" label="총톤수(GT)" error={errors[EDIT_FIELD.grossTonnage]}>
        {(control) => (
          <input
            {...control}
            className="vessel-management__control"
            inputMode="decimal"
            value={state.grossTonnage}
            onChange={(e) => set({ grossTonnage: e.target.value })}
          />
        )}
      </Field>

      <Field id="vm-deadweight" label="재화중량톤수(DWT)" error={errors[EDIT_FIELD.deadweight]}>
        {(control) => (
          <input
            {...control}
            className="vessel-management__control"
            inputMode="decimal"
            value={state.deadweight}
            onChange={(e) => set({ deadweight: e.target.value })}
          />
        )}
      </Field>

      <Field id="vm-referenceSpeedKn" label="기준속도 (kn)" error={errors[EDIT_FIELD.referenceSpeedKn]}>
        {(control) => (
          <input
            {...control}
            className="vessel-management__control"
            inputMode="decimal"
            value={state.referenceSpeedKn}
            onChange={(e) => set({ referenceSpeedKn: e.target.value })}
          />
        )}
      </Field>

      <Field id="vm-referenceDailyFocTon" label={`기준 일일 연료소모량 (${DISPLAY_UNIT_DAILY_FUEL})`} error={errors[EDIT_FIELD.referenceDailyFocTon]}>
        {(control) => (
          <input
            {...control}
            className="vessel-management__control"
            inputMode="decimal"
            value={state.referenceDailyFocTon}
            onChange={(e) => set({ referenceDailyFocTon: e.target.value })}
          />
        )}
      </Field>

      <Field id="vm-blockCoefficient" label="방형계수 (CB)" error={errors[EDIT_FIELD.blockCoefficient]}>
        {(control) => (
          <input
            {...control}
            className="vessel-management__control"
            inputMode="decimal"
            value={state.blockCoefficient}
            onChange={(e) => set({ blockCoefficient: e.target.value })}
          />
        )}
      </Field>

      <Field id="vm-defaultFuelType" label="기본 연료" error={errors[EDIT_FIELD.defaultFuelType]}>
        {(control) => (
          <select
            {...control}
            className="vessel-management__control"
            value={state.defaultFuelType}
            onChange={(e) => set({ defaultFuelType: e.target.value })}
          >
            <option value="">
              {fuelsLoading
                ? '연료 목록을 불러오는 중…'
                : fuelsFailed
                  ? '연료 목록을 불러오지 못했습니다'
                  : '선택 안 함'}
            </option>
            {fuels.map((fuel) => (
              <option key={fuel.code} value={fuel.code}>
                {fuelTypeOptionText(fuel.code)}
              </option>
            ))}
          </select>
        )}
      </Field>

      {clearNotice !== null && (
        <p className="vessel-management__warn" role="status">
          {clearNotice}
        </p>
      )}
      {recalc !== null && (
        <p className="vessel-management__warn" role="status">
          {recalc}
        </p>
      )}

      <div className="vessel-management__buttons">
        <button type="submit" className="vessel-management__submit" disabled={saving}>
          {saving ? '저장 중…' : '저장'}
        </button>
        <button type="button" className="vessel-management__button" onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  )
}

/**
 * 목록의 배 실루엣.
 *
 * ## 등급 색을 쓰지 않는다 — 그리고 그게 대시보드와 다른 이유다
 *
 * 대시보드의 배 마크(`VesselMark`)는 **등급 칸**에 놓인다. 그래서 등급이 없으면
 * 배를 그리지 않는다 — 중립색 배가 「등급이 있는데 옅은 것」으로 읽히기 때문이다.
 *
 * **이 화면에는 등급 축이 아예 없다.** 선종·용량·제원만 다루므로 배가 등급을
 * 가리킬 여지가 없고, 중립 회색이 곧 「여기서 이 그림은 값이 아니다」가 된다.
 *
 * 실루엣은 `components/vesselShape.ts` 한 벌에서 온다. 여기서 경로를 다시 그리면
 * 대시보드의 배와 이 배가 서로 다른 모양이 되는 날이 온다.
 */
function VesselSilhouette() {
  return (
    <svg
      className="vessel-management__glyph"
      viewBox={`0 0 ${VESSEL_GRID} ${VESSEL_GRID}`}
      aria-hidden="true"
      focusable="false"
    >
      {VESSEL_PATHS.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}

/**
 * 제원 값 한 칸 (#719).
 *
 * **없을 때 빈칸으로 두지 않는다.** 빈칸이면 「항목 자체가 없는 배」로 읽히고,
 * 이 화면에서 그 구분이 곧 용건이다(`#449` — 계산할 수 없을 때 그 사실을 값으로
 * 만든다). `—`를 세우고 색을 낮춰 **값이 있는 칸과 없는 칸이 훑을 때 갈리게** 한다.
 *
 * 색만으로 구분하지 않는다 — `—`라는 문자 자체가 보조 채널이다 (`§14`).
 */
/**
 * 제원이 비어 막힌 것들 — **한 줄** (#1277).
 *
 * 종전에는 이유마다 `li`로 쌓였다. 제원이 빈 행만 두 배 높이가 되고, 이 화면의
 * 용건이 「제원을 채우는 것」이라(`PRD §6.1 SCR-002`) 그런 행이 흔하다. 표를
 * 세로로 훑을 수 없었다.
 *
 * ## 빠진 항목 이름을 눈으로 보이지 않는다
 *
 * 같은 행의 `용량` · `기준속도` · `일일 연료` 열이 `—`로 이미 말한다 — `#719`가
 * 완성도 막대를 값 두 칸으로 바꾸면서 그렇게 됐다. 문장으로 다시 적으면 같은 말이
 * 두 번이다.
 *
 * **그래도 지우지는 않는다.** `—`가 스크린 리더에서 「비었다」로 읽힌다는 보장이
 * 없어, 그 사용자에게는 `#511` 이후의 문장이 그대로 필요하다. `sr-only`로 남긴다.
 */
function BlockedSpecLine({ reasons }: { reasons: BlockedReason[] }) {
  return (
    <p className="vm__blocked">
      {reasons.map((reason, index) => (
        <span key={reason.consequence}>
          {index > 0 && ' · '}
          <span className="sr-only">{reason.fields} — </span>
          {reason.consequence}
        </span>
      ))}
    </p>
  )
}

function ValueCell({ label, value }: { label: string; value: string | null }) {
  return (
    <div className={`vm__cell vm__cell--num${value === null ? ' vm__cell--empty' : ''}`}>
      <span className="sr-only">{label} </span>
      {value ?? MISSING}
    </div>
  )
}
