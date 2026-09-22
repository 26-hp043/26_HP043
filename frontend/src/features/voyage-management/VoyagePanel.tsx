import { useCallback, useEffect, useRef, useState } from 'react'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatGrouped } from '../../display/format'
import { withRo } from '../../display/josa'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { VoyageError, createApiVoyageManagementProvider } from './apiProvider'
import { ExportCsv } from './ExportCsv'
import { ImportCsv } from './ImportCsv'
import type { VoyageManagementProvider } from './apiProvider'
import {
  POLICY_LABELS,
  STATUS_LABELS,
  canEnterActuals,
  primaryAction,
  hasErrors,
  isRevert,
  nextStatuses,
  toLocalInput,
  transitionBlocker,
  transitionCaution,
  validateActuals,
  validateDraft,
} from './voyageRules'
import type { FieldErrors } from './voyageRules'
import {
  ESTIMATED_DISTANCE_HINT,
  ESTIMATED_DISTANCE_LIST_NOTE,
  distanceInput,
  matchSamplePort,
  portOptionLabel,
  type SamplePort,
} from '../ports/samplePorts'
import type { ActualsDraft, ManagedVoyage, VoyageDraft, VoyageFuelDraft, VoyageStatus } from './types'
import './VoyagePanel.css'
import { Field } from '../../components/Field'
import { ErrorState } from '../../components/ErrorState'

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
  /**
   * 들어오자마자 데려갈 항차 (#1540 · #1549 · `voyageActualsPath`).
   * 실시간 CII의 「이 항차 실적 입력」과 데이터 점검의 「이 항차로」가 여기로 온다.
   * 그 카드로 스크롤해 초점을 두고, 실적을 넣을 수 있는 항차면 입력을 열어 둔다.
   */
  openActualsFor?: string | null
}

export function VoyagePanel({ vesselId, provider, openActualsFor = null }: VoyagePanelProps) {
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

  /**
   * 데려갈 항차가 받은 목록에 없다 (#1549). 조용히 맨 위에 머무르면 사용자는 링크가 고장 난
   * 줄 안다. 다음 페이지가 있으면 거기 있을 수 있고 — 「더 보기」로 불러와 행이 그려지면
   * 그 행이 스스로 스크롤한다 — 없으면 이 선박의 기록에 없는 항차다(삭제 등).
   * 첫 페이지를 못 받은 경우는 오류가 이미 말하므로 겹쳐 말하지 않는다.
   */
  const targetMissing =
    openActualsFor !== null &&
    voyages !== null &&
    failure === null &&
    !voyages.some((voyage) => voyage.id === openActualsFor)

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
        <ErrorState level="region" size="compact" message={failure} />
      ) : null}

      {formOpen ? (
        <VoyageForm
          api={api}
          fuelTypes={fuelTypes}
          onCancel={() => setFormOpen(false)}
          onSubmit={async (draft) => {
            const created = await api.create(vesselId, draft)
            setVoyages((rows) => [created, ...(rows ?? [])])
            setFormOpen(false)
          }}
        />
      ) : null}

      {targetMissing ? (
        <p className="vy__target-missing" role="status">
          {hasMore
            ? '찾는 항차가 아직 불러오지 않은 목록에 있을 수 있습니다. 아래 「더 보기」로 이어서 불러오면 그 항차로 이동합니다.'
            : '찾는 항차가 이 선박의 항차 기록에 없습니다. 삭제됐거나 다른 선박의 항차일 수 있습니다.'}
        </p>
      ) : null}

      {voyages === null ? (
        <p className="vy__loading" aria-busy="true" role="status">
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
            <VoyageRow
              key={voyage.id}
              voyage={voyage}
              api={api}
              onChange={replace}
              openOnMount={voyage.id === openActualsFor}
            />
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
      {/*
        가져오기 **바로 아래**다 (`#890`). `PRD:636`이 `SCR-007`을 「Data Import/Export」
        한 항목으로 규정하므로 두 방향이 한 자리에 있어야 한다.
      */}
      <ExportCsv vesselId={vesselId} provider={api} />
    </section>
  )
}

function VoyageRow({
  voyage,
  api,
  onChange,
  openOnMount = false,
}: {
  voyage: ManagedVoyage
  api: VoyageManagementProvider
  onChange: (updated: ManagedVoyage) => void
  openOnMount?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)
  /*
   * 실시간 CII에서 「이 항차 실적 입력」으로 왔으면 **열린 채로 시작한다** (#1540).
   * 진행 중 · 완료 항차가 아니면(`canEnterActuals`) 열지 않는다 — 실적을 넣을 수 없는 항차다.
   */
  const [actualsOpen, setActualsOpen] = useState(openOnMount && canEnterActuals(voyage.status))
  const rowRef = useRef<HTMLLIElement>(null)
  /*
   * 되돌릴 수 없거나 정본이 재확인을 요구하는 전환은 **카드 안 확인 줄**을 거친다 (#1598 ·
   * `transitionCaution`). 모달을 두지 않는다 — 저장소에 아직 모달이 없고(`DESIGN_SYSTEM §5`
   * `--radius-modal` 사용처 0 · `§16` 항목 17 겹침 순서 미결), 확인할 대상(이 카드의 값)이
   * 줄 바로 위에 보여야 판단할 수 있다.
   */
  const [pending, setPending] = useState<VoyageStatus | null>(null)
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
  /** 확인이 필요한 전환이면 줄을 열고, 아니면 바로 돌린다. */
  const request = (to: VoyageStatus, trigger: HTMLButtonElement) => {
    if (transitionCaution(voyage.status, to) === null) {
      void run(() => api.transition(voyage, to))
      return
    }
    pendingTrigger.current = trigger
    setPending(to)
  }
  useEffect(() => {
    if (!openOnMount) return
    const row = rowRef.current
    // jsdom에는 scrollIntoView가 없다 — 있을 때만 부른다.
    row?.scrollIntoView?.({ block: 'start' })
    // 초점을 옮긴다 — 키보드·낭독 사용자도 같은 자리에 도착한다. 입력이 열렸으면 첫 칸,
    // 아니면 카드 자체(#1549 — 확정 항차도 데이터 점검에서 데려온다).
    const firstInput = row?.querySelector<HTMLInputElement>('.vy__form--actuals input')
    ;(firstInput ?? row)?.focus({ preventScroll: true })
    // 한 번만 — 목록이 다시 와도 사용자가 닫은 폼을 다시 열지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * 한 항차의 요청을 돌리고 **성공 여부를 돌려준다** (`#824` ⑸).
   *
   * 종전에는 오류를 잡아 표시하고 끝이라 호출부가 성공·실패를 가릴 수 없었다. 실적
   * 입력이 그것을 그대로 밟았다 — `await run(...)` 뒤에 무조건 폼을 닫아, **저장이
   * 실패해도 폼이 사라지고 사용자가 넣은 실제 거리·평균 속력·연료별 실적이 전부
   * 소실**됐다(`ActualsForm`이 `useState`로 들고 있다).
   *
   * 던지지 않고 `boolean`을 돌려주는 것은 **오류 표시가 이미 이 함수의 일**이기
   * 때문이다. 다시 던지면 호출부마다 같은 `try/catch`가 생긴다.
   */
  const run = async (task: () => Promise<ManagedVoyage>): Promise<boolean> => {
    setBusy(true)
    setRowError(null)
    try {
      onChange(await task())
      return true
    } catch (error) {
      setRowError(
        error instanceof VoyageError || error instanceof Error
          ? error.message
          : '처리하지 못했습니다.',
      )
      return false
    } finally {
      setBusy(false)
    }
  }

  const primary = primaryAction(voyage)
  const primaryTo = primary?.kind === 'transition' ? primary.to : null
  const otherTransitions = nextStatuses(voyage.status).filter(
    (to) => to !== primaryTo && to !== 'CANCELLED' && !isRevert(voyage.status, to),
  )
  const revertTo = nextStatuses(voyage.status).find((to) => isRevert(voyage.status, to)) ?? null
  const caution = pending === null ? null : transitionCaution(voyage.status, pending)
  const cautionId = `vy-caution-${voyage.id}`
  const canCancel = nextStatuses(voyage.status).includes('CANCELLED')

  /*
    「실적 입력」이 주 버튼이어도 **열린 뒤에는 채움을 내린다** — 그때 글자는 「실적 닫기」이고,
    할 일은 폼 안의 「실적 저장」이다. 닫기를 가장 진하게 칠하지 않는다.
  */
  const actualsToggle = (asPrimary: boolean) => (
    <button
      type="button"
      className={asPrimary ? 'vy__toggle vy__primary' : 'vy__toggle'}
      onClick={() => setActualsOpen((open) => !open)}
      aria-expanded={actualsOpen}
    >
      {actualsOpen ? '실적 닫기' : '실적 입력'}
    </button>
  )

  return (
    <li
      className={openOnMount ? 'vy__row vy__row--target' : 'vy__row'}
      id={`voyage-${voyage.id}`}
      ref={rowRef}
      // 데려온 카드만 초점을 받을 수 있다 — 탭 순서에는 넣지 않는다(#1549).
      tabIndex={openOnMount ? -1 : undefined}
    >
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

      {/*
        저장된 계획 거리가 좌표 추정이면 그 사실을 붙인다 (#1256 · `PRD §15.2`).

        문구는 목록용 `ESTIMATED_DISTANCE_LIST_NOTE`를 쓴다 (#1354). 입력 칸의
        `ESTIMATED_DISTANCE_HINT`는 끝이 「고쳐 주세요」인데 목록에는 계획 거리를 고치는 경로가
        없다 — 따를 수 없는 말 대신 그 값이 CII를 어느 쪽으로 기울이는지를 적는다. 앞머리
        「좌표 기반 추정 거리」는 두 문구가 같다(`PRD §15.2`). `COORDINATE_DISTANCE_NOTICE`(항로
        비교)는 「현재 위치에서 목적항까지」라 항차의 출발항 → 도착항에는 맞지 않는다.

        **`null`(「모른다」)에는 아무것도 붙이지 않는다.** 059 이전 항차와 출처 없이 만든
        항차가 여기 들고, 직접 입력한 값에 「추정」이 붙는 것이 `PRD §0.3`이 금하는 거짓말이다.
      */}
      {voyage.plannedDistanceSource === 'COORDINATE_ESTIMATE' ? (
        <p className="vy__hint">{ESTIMATED_DISTANCE_LIST_NOTE}</p>
      ) : null}

      {rowError ? (
        <ErrorState level="region" size="compact" message={rowError} />
      ) : null}

      {/*
        카드마다 **다음에 누를 것 하나**만 채움 버튼이다 (#1551 · `primaryAction`).

        종전에는 전환 · 실적 입력 · 취소가 모두 같은 외곽선이라, 막힌 전환의 사유(「실적 연료를
        먼저…」)가 바로 옆 「실적 입력」과 이어지지 않았고 완료 카드는 「실적 확정으로」와
        「실적 입력」 중 무엇이 먼저인지 말하지 않았다. 순서는 **주 버튼 → 나머지 전환 → 실적
        입력 → 취소**다. 취소는 주 동작이 아닌 자리라 텍스트 버튼이다(`DESIGN_SYSTEM §8`).
      */}
      <div className="vy__row-actions">
        {primary?.kind === 'actuals' ? actualsToggle(!actualsOpen) : null}
        {[...(primaryTo !== null ? [primaryTo] : []), ...otherTransitions].map((to) => {
          const blocker = transitionBlocker(voyage, to)
          const blockerId = `vy-blocker-${voyage.id}-${to}`
          return (
            <span className="vy__action" key={to}>
              <button
                type="button"
                className={to === primaryTo ? 'vy__transition vy__primary' : 'vy__transition'}
                disabled={busy || blocker !== null}
                /* 사유가 눈에만 있었다 — 낭독에도 닿게 한다 (`§14` · `#1170` ⑵). */
                aria-describedby={blocker ? blockerId : undefined}
                aria-expanded={transitionCaution(voyage.status, to) ? pending === to : undefined}
                onClick={(event) => request(to, event.currentTarget)}
              >
                {withRo(STATUS_LABELS[to])}
              </button>
              {/* 왜 못 누르는지 버튼 옆에 적는다 — 눌러 보고 422를 받는 것보다 낫다. */}
              {blocker ? (
                <span id={blockerId} className="vy__blocker">
                  {blocker}
                </span>
              ) : null}
            </span>
          )
        })}

        {canEnterActuals(voyage.status) && primary?.kind !== 'actuals' ? actualsToggle(false) : null}

        {/*
          확정 되돌리기는 **뒤로 가는** 전환이라 「항해 완료로」 틀에 두지 않는다 (#1598 · `isRevert`).
          오류 정정에만 쓰는 동작이라 취소와 같은 텍스트 버튼이다(`DESIGN_SYSTEM §8`).
        */}
        {revertTo !== null ? (
          <button
            type="button"
            className="vy__text-action"
            disabled={busy}
            aria-expanded={pending === revertTo}
            onClick={(event) => request(revertTo, event.currentTarget)}
          >
            확정 되돌리기
          </button>
        ) : null}

        {canCancel ? (
          <button
            type="button"
            className="vy__text-action"
            disabled={busy}
            aria-expanded={pending === 'CANCELLED'}
            onClick={(event) => request('CANCELLED', event.currentTarget)}
          >
            이 항차 취소
          </button>
        ) : null}
      </div>

      {/*
        확인 줄 (#1598). 무엇이 달라지는지 적고, 실행 버튼은 동사로 끝난다. 초점은 「그만두기」에
        먼저 간다. Escape도 「그만두기」다.
      */}
      {pending !== null && caution !== null ? (
        <div
          className="vy__caution"
          role="group"
          aria-labelledby={cautionId}
          onKeyDown={(event) => {
            if (event.key === 'Escape') closePending()
          }}
        >
          <p id={cautionId} className="vy__caution-text">
            {caution.message}
          </p>
          <div className="vy__caution-actions">
            <button
              type="button"
              className="vy__transition"
              disabled={busy}
              onClick={() => {
                const to = pending
                setPending(null)
                void run(() => api.transition(voyage, to))
              }}
            >
              {caution.confirm}
            </button>
            <button type="button" ref={keepRef} className="vy__text-action" onClick={closePending}>
              그만두기
            </button>
          </div>
        </div>
      ) : null}

      {actualsOpen ? (
        <ActualsForm
          voyage={voyage}
          onCancel={() => setActualsOpen(false)}
          onSubmit={async (draft) => {
            // 성공했을 때만 닫는다 (`#824` ⑸) — 실패에 닫으면 입력이 사라진다.
            if (await run(() => api.saveActuals(voyage.id, draft))) setActualsOpen(false)
          }}
        />
      ) : null}
    </li>
  )
}

function VoyageForm({
  api,
  fuelTypes,
  onCancel,
  onSubmit,
}: {
  api: VoyageManagementProvider
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
    plannedDepartureAt: '',
    plannedArrivalAt: '',
    regulationYear: '',
    fuelUses: [{ fuelType: fuelTypes[0] ?? '', plannedFuelTon: '' }],
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  /*
   * 샘플 항만 (#760 · `PRD §15.1`). 못 받아도 폼은 그대로 쓴다 — 목록은 편의이고 항만명은
   * 자유 입력이다. 그래서 실패를 폼 오류로 올리지 않고 선택지만 비운다.
   */
  const [ports, setPorts] = useState<SamplePort[]>([])
  /** 계획 거리 칸이 **좌표 기반 추정 거리**로 채워졌는가 — 사용자가 고치면 내린다. */
  const [estimated, setEstimated] = useState(false)

  /**
   * 거리 입력의 세대 (`#1657`). 항만이 바뀌거나 사용자가 거리를 직접 고치면 올린다.
   *
   * 추정 요청이 도는 동안 입력이 바뀌면 **늦게 온 응답을 버린다** — 버리지 않으면 A/B 항로의
   * 거리(와 「좌표 기반 추정」 출처)가 C 항로나 직접 입력한 값을 덮어쓴다. 그 값은 저장까지
   * 따라가므로(`plannedDistanceSource` · `#1256`) 화면과 저장이 함께 어긋난다.
   */
  const distanceGeneration = useRef(0)
  const [estimating, setEstimating] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .samplePorts()
      .then((rows) => {
        if (alive) setPorts(rows)
      })
      .catch(() => {
        if (alive) setPorts([])
      })
    return () => {
      alive = false
    }
    // api는 렌더마다 새로 만들어질 수 있다 — 폼이 열릴 때 한 번만 받는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const set = (key: keyof VoyageDraft) => (value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  /** 항만명 칸 — 목록의 항과 **정확히** 같으면 좌표를 붙이고, 아니면 좌표를 뗀다. */
  const setPort = (side: 'departure' | 'arrival') => (value: string) => {
    const match = matchSamplePort(ports, value)
    const coord = match ? { lat: match.lat, lon: match.lon } : null
    setDraft((prev) => {
      const next =
        side === 'departure'
          ? { ...prev, departurePortName: match ? match.name : value, departureCoord: coord }
          : { ...prev, arrivalPortName: match ? match.name : value, arrivalCoord: coord }
      // #1256 — 추정 거리는 **그때의 두 항**에서 나온 값이다. 항을 바꾸면 그 숫자는 새 항로의
      // 추정도, 사용자가 넣은 값도 아니므로 비운다 — 남겨 두면 옛 항로의 거리가 「좌표 기반
      // 추정」으로 저장된다(출처가 저장까지 가면서 생긴 결함).
      return estimated ? { ...next, plannedDistanceNm: '' } : next
    })
    // 항이 바뀌면 진행 중이던 추정의 결과는 이 항로의 것이 아니다 (`#1657`).
    distanceGeneration.current += 1
    if (estimated) setEstimated(false)
  }

  const canEstimate = Boolean(draft.departureCoord && draft.arrivalCoord)

  const estimateDistance = async () => {
    if (!draft.departureCoord || !draft.arrivalCoord || estimating) return
    setEstimating(true)
    const ticket = distanceGeneration.current
    try {
      const distance = await api.greatCircle(draft.departureCoord, draft.arrivalCoord)
      // 기다리는 동안 항만이나 거리 칸이 바뀌었으면 이 값은 **지금 입력의 것이 아니다** (`#1657`).
      if (ticket !== distanceGeneration.current) return
      setDraft((prev) => ({ ...prev, plannedDistanceNm: distanceInput(distance) }))
      setEstimated(true)
    } catch (error) {
      if (ticket !== distanceGeneration.current) return
      setFailure(error instanceof Error ? error.message : '추정 거리를 받지 못했습니다.')
    } finally {
      setEstimating(false)
    }
  }

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
      <ErrorState
        level="region"
        size="compact"
        message="연료 선택지를 불러오지 못해 항차를 추가할 수 없습니다."
      />
    )
  }

  return (
    <form
      className="vy__form"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        /*
          화면이 그리는 값과 **같은 값으로** 검증·전송한다 (`#824` ⑹).

          셀렉트가 첫 연료를 그리고 있는데 상태가 비어 있으면, 눈에 보이는 것과
          보내는 것이 갈린다. 빈 칸을 여기서 메워 그 어긋남을 없앤다 — 목록조차
          비어 있으면 그대로 두고 `validateDraft`가 잡는다.
        */
        const filled: VoyageDraft = {
          ...draft,
          fuelUses: draft.fuelUses.map((fu) => ({
            ...fu,
            fuelType: fu.fuelType || (fuelTypes[0] ?? ''),
          })),
          /*
           * 거리의 출처를 저장에 싣는다 (#1256). `estimated`는 이 폼의 임시 상태라 저장하면
           * 사라졌다 — 그래서 저장된 항차에는 「좌표 기반 추정 거리」 표시가 붙을 수
           * 없었다(`PRD §15.2` · #1052 ⓷). 사용자가 고친 값은 위 `onChange`가 이미 내렸다.
           */
          plannedDistanceSource: estimated ? 'COORDINATE_ESTIMATE' : 'USER_INPUT',
        }
        const found = validateDraft(filled)
        setErrors(found)
        if (hasErrors(found)) return

        setBusy(true)
        setFailure(null)
        try {
          await onSubmit(filled)
        } catch (error) {
          setFailure(error instanceof Error ? error.message : '항차를 만들지 못했습니다.')
        } finally {
          setBusy(false)
        }
      }}
    >
      {failure ? (
        <ErrorState level="region" size="compact" message={failure} />
      ) : null}

      <VoyageField id="vy-no" label="항차 번호" value={draft.voyageNo} onChange={set('voyageNo')} error={errors.voyageNo} />
      {/* 샘플 항만 선택지 (#760) — 자유 입력과 함께 쓴다(`PRD §20 O-11`). */}
      <datalist id="vy-ports">
        {ports.map((port) => (
          <option key={port.locode} value={port.name} label={portOptionLabel(port)} />
        ))}
      </datalist>
      <VoyageField id="vy-from" label="출발항" value={draft.departurePortName} onChange={setPort('departure')} error={errors.departurePortName} list="vy-ports" hint={draft.departureCoord ? '샘플 항만 — 좌표가 함께 저장됩니다.' : undefined} />
      <VoyageField id="vy-to" label="도착항" value={draft.arrivalPortName} onChange={setPort('arrival')} error={errors.arrivalPortName} list="vy-ports" hint={draft.arrivalCoord ? '샘플 항만 — 좌표가 함께 저장됩니다.' : undefined} />
      <VoyageField
        id="vy-dist"
        label={`계획 거리 (${DISPLAY_UNITS.distance})`}
        value={draft.plannedDistanceNm}
        onChange={(value) => {
          // 사용자가 고친 값은 추정값이 아니다. 진행 중이던 추정의 결과도 버린다 (`#1657`) —
          // 직접 입력이 자동 추정보다 앞선다.
          distanceGeneration.current += 1
          setEstimated(false)
          set('plannedDistanceNm')(value)
        }}
        error={errors.plannedDistanceNm}
        inputMode="decimal"
        hint={estimated ? ESTIMATED_DISTANCE_HINT : undefined}
      />
      {canEstimate ? (
        <button type="button" className="vy__estimate" onClick={estimateDistance} disabled={estimating}>
          {estimating ? '추정 거리를 계산하는 중…' : '좌표 기반 추정 거리로 채우기'}
        </button>
      ) : null}
      <VoyageField id="vy-speed" label={`계획 속력 (${DISPLAY_UNITS.speed})`} value={draft.plannedSpeedKn} onChange={set('plannedSpeedKn')} error={errors.plannedSpeedKn} inputMode="decimal" />
      {/*
        계획 출항·도착 시각 (`#873`).

        **종전에는 이 두 칸이 없었다.** 서버는 `§3.3`에서 처음부터 받고 있었는데
        화면이 보내지 않아, 화면으로 만든 항차는 출항 시각이 영원히 `null`이었다.
        그 항차를 진행 중으로 옮기면 시뮬레이션 시계가 곧바로 거리·연료 **0**을
        돌려주고(`services/simulation_clock.py:177`), 경고 체계는 `distance_nm > 0`을
        전제하므로 그 0도 잡지 못한다 — **조용히 0으로 기여한다.**

        `§3.3`이 optional이라 여기서도 필수로 만들지 않는다. 대신 결과를 말한다.
      */}
      <VoyageField
        id="vy-dep-at"
        label="계획 출항 시각"
        type="datetime-local"
        value={draft.plannedDepartureAt}
        onChange={set('plannedDepartureAt')}
        error={errors.plannedDepartureAt}
        hint="비워 두면 진행 중 누적에 0으로 기여합니다. 나중에 실적 입력에서 채울 수 있습니다."
      />
      <VoyageField
        id="vy-arr-at"
        label="계획 도착 시각"
        type="datetime-local"
        value={draft.plannedArrivalAt}
        onChange={set('plannedArrivalAt')}
        error={errors.plannedArrivalAt}
        hint="도착 실적이 없을 때 진행 중 누적의 상한이 됩니다."
      />
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
            {/*
              값이 비어 있으면 **렌더 시점에** 첫 연료로 본다 (`#824` ⑹).

              `draft.fuelUses`는 `useState` 초기화 때 `fuelTypes[0] ?? ''`로 굳는데,
              `fuelTypes`는 비동기로 채워진다. 목록이 오기 전에 「항차 추가」를 누르면
              `fuelType: ''`로 **굳고 이후에도 재동기되지 않는다.**

              그 상태에서 `<option value="">`가 없으므로 브라우저는 `selectedIndex=0`,
              즉 **첫 연료가 선택된 것처럼 그린다.** 사용자는 고른 것으로 보고 저장을
              누르는데 「연료 종류를 선택해 주세요.」가 뜬다 — **화면과 상태가 다른
              말을 한다.**

              `NotUnderwayPanel`이 같은 문제를 렌더 시점 계산으로 피한다
              (`periodType || choices.periodTypes[0]`). 여기서는 **화면이 보이는 값을
              상태에도 반영**해야 저장이 그 값을 쓴다.
            */}
            <select
              className="vy__input"
              aria-label={`연료 종류 ${index + 1}`}
              value={fu.fuelType || (fuelTypes[0] ?? '')}
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
              <em className="vy__field-error" role="alert">{errors[`fuelType.${index}`]}</em>
            ) : null}
            {errors[`plannedFuelTon.${index}`] ? (
              <em className="vy__field-error" role="alert">{errors[`plannedFuelTon.${index}`]}</em>
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

        {errors.fuelUses ? <em className="vy__field-error" role="alert">{errors.fuelUses}</em> : null}
      </fieldset>

      <VoyageField
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
    // 이미 넣어 둔 시각을 되읽는다 (`#873`) — 빈 폼으로 시작하면 저장할 때 지워진다.
    actualDepartureAt: toLocalInput(voyage.actualDepartureAt),
    actualArrivalAt: toLocalInput(voyage.actualArrivalAt),
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

      <VoyageField
        id={`ac-dist-${voyage.id}`}
        label={`실제 거리 (${DISPLAY_UNITS.distance})`}
        value={draft.actualDistanceNm}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualDistanceNm: value }))}
        error={errors.actualDistanceNm}
        inputMode="decimal"
        hint={`계획 ${quantity(voyage.plannedDistanceNm, DISPLAY_DIGITS.distanceNm)} ${DISPLAY_UNITS.distance}`}
      />

      <VoyageField
        id={`ac-speed-${voyage.id}`}
        label={`실제 평균 속력 (${DISPLAY_UNITS.speed})`}
        value={draft.actualAvgSpeedKn}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualAvgSpeedKn: value }))}
        error={errors.actualAvgSpeedKn}
        inputMode="decimal"
      />

      {/*
        실제 출항·도착 시각 (`#873`).

        출항 실적은 계획보다 **먼저 읽힌다**(`cii_current.py:429`
        `actual_departure_at or planned_departure_at`). 도착 실적은 시계의 상한이라
        입력하는 순간 누적이 그 시각에서 멈춘다 — 결과 화면의 「도착 실적을 입력하면
        확정됩니다」가 가리키던 칸이 **제품에 없던** 상태를 이번에 메운다.
      */}
      <VoyageField
        id={`ac-dep-at-${voyage.id}`}
        label="실제 출항 시각"
        type="datetime-local"
        value={draft.actualDepartureAt}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualDepartureAt: value }))}
        error={errors.actualDepartureAt}
        hint={
          voyage.plannedDepartureAt === null
            ? '계획 출항 시각이 없습니다. 이 칸을 채우면 진행 중 누적이 계산됩니다.'
            : `계획 ${toLocalInput(voyage.plannedDepartureAt)}`
        }
      />
      <VoyageField
        id={`ac-arr-at-${voyage.id}`}
        label="실제 도착 시각"
        type="datetime-local"
        value={draft.actualArrivalAt}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualArrivalAt: value }))}
        error={errors.actualArrivalAt}
        hint={
          voyage.plannedArrivalAt === null
            ? undefined
            : `계획 ${toLocalInput(voyage.plannedArrivalAt)}`
        }
      />

      {voyage.fuelUses.map((use) => (
        <VoyageField
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
 * 항차 폼의 입력 한 칸 — 공용 `Field` 위의 얇은 층이다 (`#936`).
 *
 * 배선은 `Field`가 준다. 여기 남는 것은 이 폼의 입력칸 모양과
 * `type`·`inputMode`·`list` 기본값뿐이다. `AuthField`와 같은 형태다.
 */
function VoyageField({
  id,
  label,
  value,
  onChange,
  error,
  hint,
  inputMode,
  type = 'text',
  list,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  hint?: string
  inputMode?: 'decimal' | 'numeric'
  /** 선택지(`<datalist>`)의 id — 자유 입력을 막지 않고 제안만 한다 (#760). */
  list?: string
  /**
   * `datetime-local`을 쓰는 칸이 생겼다 (`#873`).
   *
   * 텍스트로 두고 형식을 안내하는 대신 **브라우저 달력 UI**를 쓴다 — 시각 입력은
   * 사용자가 형식을 틀리기 가장 쉬운 칸이고, 이 폼은 그 틀림을 저장 뒤에야
   * 알려 줄 수 있다(서버가 받는 값이 `null`이 되어도 오류가 아니다).
   */
  type?: 'text' | 'datetime-local'
}) {
  /*
   * 배선은 공용 `Field`가 준다 (`#936` · `§8.4`). 여기 남는 것은 이 폼의 입력칸
   * 모양과 `list`·`inputMode`·`type` 기본값뿐이다 — 호출부 열세 곳은 그대로 둔다.
   *
   * 이름을 `VoyageField`로 바꾼 것은 공용 `Field`와 **한 파일에서 이름이 겹치기**
   * 때문이다. 겹친 채로 두면 어느 쪽을 쓰는지 읽어서 알 수 없다.
   */
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {(control) => (
        <input
          {...control}
          className="vy__input"
          type={type}
          value={value}
          inputMode={inputMode}
          list={list}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
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
