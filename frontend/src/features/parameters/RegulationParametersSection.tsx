import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useAuthUser, type CurrentUser } from '../../auth/session'
import { ParameterRevision } from './ParameterRevision'
import { createApiParameterRevisionProvider, type ParameterRevisionProvider } from './revisionProvider'
import { useLocation } from 'react-router'
import { ErrorState } from '../../components/ErrorState'
import { shipTypeLabel } from '../vessel-registration/shipTypes'
import {
  createApiReferenceParametersProvider,
  type FuelTypeRow,
  type RatingBoundaryRow,
  type ReferenceLineRow,
  type ReferenceParametersProvider,
  type RegulationYearRow,
} from './referenceApiProvider'
import { FUEL_NO_HISTORY_NOTICE, REGULATION_PARAMETERS_ANCHOR } from './referenceRules'
import './RegulationParametersSection.css'

/**
 * 「규제 기준값」 절 — 설정(`UIFLOW 2-6`) 안의 절 (`#1516` · `#1239` 결정 A~D·G).
 *
 * ## 왜 설정 안의 절인가 (결정 B)
 *
 * 네 표 합쳐 50행이고 1년에 한두 번 IMO 개정 때만 바뀐다 — 사이드바 탭 하나를 정당화하지
 * 않는다. 대신 「왜 이 등급인가」가 시작되는 세 자리(실시간 CII의 기준값 · 기능①의 계산
 * 근거 · 대시보드의 기준값 없음 안내)가 **이 절로 링크**한다. 그래서 절은 `id`를 갖고,
 * 해시로 들어오면 스스로 초점을 받는다 — SPA는 문서를 다시 읽지 않아 라우터가 해시로
 * 스크롤해 주지 않는다.
 *
 * ## 역할 가드를 두지 않는다 (결정 D)
 *
 * 값은 IMO가 공개한 규제 상수이고 `API_SPEC §1.2`가 「조회(`GET §7.1~§7.4`)는 세 역할 모두」다. 현장직의
 * 「왜 이 등급인가」 사슬(실시간 CII required → `a`·`c` × Z → d)을 여기서 끊으면 링크가
 * 막다른 길이 된다. 둘러보기 세션도 같다. 적재·기록(`#1517`)만 사무직이다.
 *
 * ## 숫자는 서버 문자열 그대로 (결정 G)
 *
 * 기준선 계수 `a`·`c`, 경계 `d1`~`d4`, 연료 `CF`, 감축률 Z는 `DESIGN_SYSTEM §4.2` 자릿수
 * 표에 없는 값이다 — 규제 파라미터를 원문과 대조하는 자리라 **반올림도 자릿수 맞춤도 하지
 * 않는다.** 기능① 「계산 근거」(`VoyageCiiResult.tsx`)가 같은 판단을 먼저 했다.
 * `a_raw`(IMO 원문 표기 · `14479E10`)를 앞세우고 `a_decimal`은 보조로 둔다 — 원문과
 * 대조하는 사람이 보는 것은 앞쪽이다.
 *
 * ## 이력 (결정 C)
 *
 * 기본은 활성분이다. 「이전 판본 포함」을 켜면 세 표를 `?active=false`로 다시 받아 이행
 * 행(개정으로 대체된 옛 판본)을 섞어 보이되 **판본·출처·상태**로 구분한다 — 흐린 색만으로
 * 가르지 않는다(`DESIGN_SYSTEM §14`). 연료는 제자리 갱신이라 이력이 없고, 그 사실을 표 안에
 * 적는다(`FUEL_NO_HISTORY_NOTICE`).
 */
export function RegulationParametersSection({
  provider,
  revisionProvider,
  user,
}: {
  /** 테스트 주입점. 없으면 실 API. */
  provider?: ReferenceParametersProvider
  /** 개정 적재·이력(`#1517`) 테스트 주입점. 없으면 실 API. */
  revisionProvider?: ParameterRevisionProvider
  /** 테스트 주입점. 없으면 로그인 세션의 사용자. */
  user?: CurrentUser | null
}) {
  const api = useMemo(() => provider ?? createApiReferenceParametersProvider(), [provider])
  const revisionApi = useMemo(
    () => revisionProvider ?? createApiParameterRevisionProvider(),
    [revisionProvider],
  )
  const authUser = useAuthUser()
  const currentUser = user !== undefined ? user : authUser
  /*
   * 개정을 확정하면 네 표를 다시 받는다(`#1517`). 올린 사람이 같은 화면에서 새 값이
   * 현행으로 올라오고 옛 값이 이행 행으로 물러난 것을 곧바로 확인하게 — 적재와 확인을
   * 가르지 않는다(`#1239` 결정 H).
   */
  const [reloadKey, setReloadKey] = useState(0)
  const [includeInactive, setIncludeInactive] = useState(false)
  const [years, setYears] = useState<RegulationYearRow[] | null>(null)
  const [lines, setLines] = useState<ReferenceLineRow[] | null>(null)
  const [boundaries, setBoundaries] = useState<RatingBoundaryRow[] | null>(null)
  const [fuels, setFuels] = useState<FuelTypeRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [failure, setFailure] = useState<string | null>(null)
  const [fuelFailure, setFuelFailure] = useState<string | null>(null)
  const rootRef = useRef<HTMLElement>(null)
  const location = useLocation()

  // 이력이 있는 세 표 — 전환이 바뀌면 그 값으로 다시 받는다.
  useEffect(() => {
    let alive = true
    // oxlint-disable-next-line react/set-state-in-effect -- 조회 시작 전 리셋 — 전환(`includeInactive`)이 바뀌면 로딩으로 돌리고 다시 받는다
    setLoading(true)
    setFailure(null)
    Promise.all([
      api.listRegulationYears({ includeInactive }),
      api.listReferenceLines({ includeInactive }),
      api.listRatingBoundaries({ includeInactive }),
    ])
      .then(([nextYears, nextLines, nextBoundaries]) => {
        if (!alive) return
        setYears(nextYears)
        setLines(nextLines)
        setBoundaries(nextBoundaries)
      })
      .catch((caught: unknown) => {
        if (alive) setFailure(caught instanceof Error ? caught.message : '규제 기준값을 불러오지 못했습니다.')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [api, includeInactive, reloadKey])

  // 연료는 이력이 없어 전환과 무관하다 — 한 번만 받는다.
  useEffect(() => {
    let alive = true
    api.listFuelTypes().then(
      (rows) => {
        if (alive) setFuels(rows)
      },
      (caught: unknown) => {
        if (alive) setFuelFailure(caught instanceof Error ? caught.message : '연료 탄소계수를 불러오지 못했습니다.')
      },
    )
    return () => {
      alive = false
    }
  }, [api, reloadKey])

  /*
   * 해시로 들어오면 절로 초점을 옮긴다. 세 자리의 링크가 `…/settings#regulation-parameters`로
   * 오는데 라우터는 해시 스크롤을 하지 않는다. `tabindex="-1"`라 링은 그리지 않는다
   * (`DESIGN_SYSTEM §14` 프로그램적 초점 대상 · `global.css`).
   */
  useEffect(() => {
    if (location.hash !== `#${REGULATION_PARAMETERS_ANCHOR}`) return
    const element = rootRef.current
    if (!element) return
    if (typeof element.scrollIntoView === 'function') element.scrollIntoView({ block: 'start' })
    element.focus({ preventScroll: true })
  }, [location.hash])

  return (
    <section
      ref={rootRef}
      id={REGULATION_PARAMETERS_ANCHOR}
      className="card regp"
      aria-labelledby="regp-title"
      tabIndex={-1}
    >
      <div className="card__head">
        <h2 className="card__title" id="regp-title">
          규제 기준값
        </h2>
        <span className="card__meta">CII 계산이 쓰는 값 · IMO 공개 규제 상수</span>
      </div>

      <p className="regp__notice">
        등급 계산이 참조하는 기준값 네 표입니다. 숫자는 등록된 값을 자릿수 가공 없이 그대로 보이므로
        IMO 원문과 바로 대조할 수 있습니다.
      </p>

      <label className="regp__toggle">
        <input
          type="checkbox"
          checked={includeInactive}
          onChange={(event) => setIncludeInactive(event.target.checked)}
          data-testid="regp-include-inactive"
        />
        <span>이전 판본 포함</span>
      </label>
      <p className="regp__hint">
        개정으로 대체된 옛 판본(이행 행)을 판본·출처와 함께 보입니다. 계산에는 현행 행만 쓰입니다.
      </p>

      {failure !== null ? <ErrorState level="region" size="compact" message={failure} /> : null}
      {loading ? (
        // `role="status"` — `aria-busy` 단독은 낭독되지 않는다 (`a11yWiring.test.ts`).
        <p className="regp__hint" role="status" aria-busy="true">
          규제 기준값을 불러오는 중…
        </p>
      ) : null}

      <Group title="연도별 감축률" testId="years" rows={years} defaultOpen>
        <table className="regp__table" data-testid="regp-table-years">
          <thead>
            <tr>
              <th scope="col">연도</th>
              <th scope="col" className="regp__num">
                감축률 Z (%)
              </th>
              <th scope="col">적용 시작</th>
              <th scope="col">출처</th>
              <th scope="col">판본</th>
              <th scope="col">상태</th>
            </tr>
          </thead>
          <tbody>
            {(years ?? []).map((row, index) => (
              <Row key={`${row.year}-${row.version}-${index}`} active={row.isActive}>
                <th scope="row" className="regp__num">
                  {row.year}
                </th>
                <td className="regp__num">{row.zFactorPercent}</td>
                <td>{row.effectiveFrom}</td>
                <td>{row.sourceRef}</td>
                <td>{row.version}</td>
                <td>{stateText(row.isActive)}</td>
              </Row>
            ))}
          </tbody>
        </table>
      </Group>

      <Group title="선종별 기준선" testId="lines" rows={lines}>
        <table className="regp__table" data-testid="regp-table-lines">
          <thead>
            <tr>
              <th scope="col">선종</th>
              <th scope="col">조건</th>
              <th scope="col">용량 규칙</th>
              <th scope="col" className="regp__num">
                a (IMO 표기)
              </th>
              <th scope="col" className="regp__num">
                a (십진)
              </th>
              <th scope="col" className="regp__num">
                c
              </th>
              <th scope="col">출처</th>
              <th scope="col">판본</th>
              <th scope="col">상태</th>
            </tr>
          </thead>
          <tbody>
            {(lines ?? []).map((row, index) => (
              <Row key={`${row.shipType}-${row.conditionExpr}-${row.version ?? ''}-${index}`} active={row.isActive}>
                <th scope="row">
                  <ShipType code={row.shipType} />
                </th>
                <td>{row.conditionExpr}</td>
                <td>{row.capacityRule}</td>
                <td className="regp__num regp__raw">{row.aRaw}</td>
                <td className="regp__num regp__aux">{row.aDecimal}</td>
                <td className="regp__num">{row.c}</td>
                <td>{row.sourceRef}</td>
                <td>{row.version ?? '—'}</td>
                <td>{stateText(row.isActive)}</td>
              </Row>
            ))}
          </tbody>
        </table>
      </Group>

      <Group title="등급 경계" testId="boundaries" rows={boundaries}>
        <table className="regp__table" data-testid="regp-table-boundaries">
          <thead>
            <tr>
              <th scope="col">선종</th>
              <th scope="col">조건</th>
              <th scope="col">용량 축</th>
              <th scope="col" className="regp__num">
                d1
              </th>
              <th scope="col" className="regp__num">
                d2
              </th>
              <th scope="col" className="regp__num">
                d3
              </th>
              <th scope="col" className="regp__num">
                d4
              </th>
              <th scope="col">출처</th>
              <th scope="col">판본</th>
              <th scope="col">상태</th>
            </tr>
          </thead>
          <tbody>
            {(boundaries ?? []).map((row, index) => (
              <Row key={`${row.shipType}-${row.conditionExpr}-${row.version ?? ''}-${index}`} active={row.isActive}>
                <th scope="row">
                  <ShipType code={row.shipType} />
                </th>
                <td>{row.conditionExpr}</td>
                <td>{row.capacityBasis}</td>
                <td className="regp__num">{row.d1}</td>
                <td className="regp__num">{row.d2}</td>
                <td className="regp__num">{row.d3}</td>
                <td className="regp__num">{row.d4}</td>
                <td>{row.sourceRef}</td>
                <td>{row.version ?? '—'}</td>
                <td>{stateText(row.isActive)}</td>
              </Row>
            ))}
          </tbody>
        </table>
      </Group>

      <Group
        title="연료 탄소계수"
        testId="fuels"
        rows={fuels}
        failure={fuelFailure}
        // 「없음」의 종류 — 이력이 없는 것이지 개정이 없었던 것이 아니다.
        footer={
          <p className="regp__hint" data-testid="regp-fuel-no-history">
            {FUEL_NO_HISTORY_NOTICE}
          </p>
        }
      >
        <table className="regp__table" data-testid="regp-table-fuels">
          <thead>
            <tr>
              <th scope="col">코드</th>
              <th scope="col">이름</th>
              <th scope="col" className="regp__num">
                CF
              </th>
              <th scope="col">단위</th>
              <th scope="col">출처</th>
            </tr>
          </thead>
          <tbody>
            {(fuels ?? []).map((row) => (
              <Row key={row.code} active={row.isActive}>
                <th scope="row">{row.code}</th>
                <td>{row.displayName}</td>
                <td className="regp__num">{row.cf}</td>
                <td>{row.unit}</td>
                <td>{row.sourceRef}</td>
              </Row>
            ))}
          </tbody>
        </table>
      </Group>

      <ParameterRevision
        user={currentUser}
        provider={revisionApi}
        onImported={() => setReloadKey((key) => key + 1)}
      />
    </section>
  )
}

/** 상태 열 — 색이 아니라 글자로 가른다 (`DESIGN_SYSTEM §14`). */
function stateText(active: boolean): string {
  return active ? '현행' : '이행'
}

/**
 * 표 하나를 접는 묶음. **표마다 접는다** — 네 표를 한 번에 펼치면 50행이 설정 화면을
 * 밀어내고, 사용자는 대개 한 표만 보러 온다. 첫 표(연도별 감축률)만 기본으로 펼친다 —
 * 대시보드의 「적용 기준」 한 줄이 가리키는 값이 거기 있다.
 */
function Group({
  title,
  testId,
  rows,
  defaultOpen = false,
  failure = null,
  footer = null,
  children,
}: {
  title: string
  testId: string
  rows: ReadonlyArray<unknown> | null
  defaultOpen?: boolean
  failure?: string | null
  footer?: ReactNode
  children: ReactNode
}) {
  return (
    <details className="regp__group" open={defaultOpen} data-testid={`regp-group-${testId}`}>
      <summary className="regp__summary">
        <span>{title}</span>
        {rows !== null ? <span className="regp__count">{rows.length}행</span> : null}
      </summary>
      <div className="regp__body">
        {failure !== null ? <ErrorState level="region" size="compact" message={failure} /> : null}
        {rows !== null && rows.length === 0 ? (
          <p className="regp__empty">등록된 행이 없습니다.</p>
        ) : (
          // 5~10열이라 좁은 폭에서 넘친다 — 표 상자만 가로로 흐른다.
          <div className="regp__scroll">{children}</div>
        )}
        {footer}
      </div>
    </details>
  )
}

/**
 * 이행 행은 흐리게 + 속성으로 표시한다. 흐린 색은 보조 채널이고, 구분은 「상태」 열의
 * 글자(현행/이행)와 판본이 진다 — 검사는 `data-superseded`를 본다.
 */
function Row({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <tr
      className={active ? undefined : 'regp__row--superseded'}
      data-superseded={active ? undefined : 'true'}
    >
      {children}
    </tr>
  )
}

/** 선종은 한국어 이름을 앞세우고 코드를 곁들인다 — IMO 표는 코드가 아니라 선종명으로 읽는다. */
function ShipType({ code }: { code: string }) {
  const label = shipTypeLabel(code)
  return (
    <>
      {label}
      {label !== code ? <span className="regp__sub">{code}</span> : null}
    </>
  )
}
