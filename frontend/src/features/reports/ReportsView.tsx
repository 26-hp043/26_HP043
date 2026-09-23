import { useCallback, useEffect, useRef, useState } from 'react'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { PageHeader } from '../../components/PageHeader'
import { useYearOptions } from '../parameters/yearCatalog'
import { createApiReportsProvider, ReportsError } from './apiProvider'
import {
  coerceYear,
  targetKey,
  targetOf,
  voyageLabel,
} from './reportRules'
import type {
  DownloadFormat,
  ReportKind,
  ReportTarget,
  ReportsProvider,
  VesselOption,
  VoyageOption,
} from './types'
import './ReportsView.css'
import { ErrorState } from '../../components/ErrorState'
import { useShellContext } from '../../layout/shellContext'

/**
 * 보고서 — `UIFLOW 2-5` · `#362`.
 *
 * ## 미리보기와 다운로드가 같은 문서다
 *
 * 서버의 `format=html`이 PDF와 **같은 소스**를 낸다(`API_SPEC §8.3`). 화면이 따로
 * 그리면 미리보기와 받은 파일이 달라지고, 그 차이는 사용자가 파일을 연 뒤에야
 * 드러난다 — 이슈의 완료 기준이 「미리보기와 다운로드 결과가 일치함」인 이유다.
 *
 * ## 미리보기를 iframe에 격리한다
 *
 * 서버 HTML에는 문서 전용 스타일(`@page`·표 테두리)이 들어 있다. 그대로 붙이면
 * 이 화면의 스타일과 섞여 양쪽이 깨진다. `sandbox`를 걸어 스크립트도 막는다 —
 * 문서에 스크립트가 있을 이유가 없고, 없다는 것을 **화면이 강제**한다.
 *
 * ## 진행 중 항차를 감추지 않는다
 *
 * 리포트 대상이 아니지만(`PRD §25.2`) 목록에서 지우지 않고 비활성으로 둔다.
 * 감추면 사용자가 「내 항차가 왜 없지」를 묻게 되고, 답이 화면 어디에도 없다.
 *
 * ## 상단바의 선박·항차 선택을 따른다 (#1414)
 *
 * `DESIGN_SYSTEM §7.2` 🔒 「패널 간 유기적 데이터 연동」. CII 예측·항로 비교·연간 등급은
 * 이미 셸 선택을 따랐고(`#535`) 이 화면만 「선택하세요」로 시작했다. 대시보드에서 배를
 * 고르고 들어온 사용자가 **같은 배를 한 번 더 골라야** 했다.
 *
 * - **선박** — 셸 선택이 초깃값이고, 여기서 바꾸면 셸도 바뀐다. 상태를 가진 곳은
 *   셸 하나다(`shellContext.ts`). 다만 선택지는 **이 화면의 목록**을 쓴다 — IMO를
 *   함께 보여야 하는데 셸 목록(`VesselOption`)에는 IMO가 없다.
 * - **항차** — 셸 항차가 목록에 있고 **리포트를 만들 수 있을 때만** 채운다. 완료 전
 *   항차는 비활성 선택지라(`PRD §25.2`) 채우면 고를 수 없는 값을 고른 셈이 된다.
 * - **셸에 선택이 없을 때 임의로 고르지 않는다** — 항로 비교(`#511`)와 같은 규칙이다.
 */
export function ReportsView({ provider }: { provider?: ReportsProvider }) {
  const providerRef = useRef<ReportsProvider | null>(null)
  if (providerRef.current === null) {
    providerRef.current = provider ?? createApiReportsProvider()
  }
  const api = providerRef.current
  const shell = useShellContext()
  const { selectVesselId, selectVoyageId } = shell
  const shellVesselId = shell.vesselId
  const shellVoyageId = shell.voyageId

  const [kind, setKind] = useState<ReportKind>('ANNUAL')
  /*
   * 선박 목록 (`#1076` ⑴).
   *
   * 아래 항차 칸과 **같은 3상태**다 — `null`은 「아직 모른다」, `'failed'`는 「못
   * 읽었다」, 배열은 「이만큼이 전부다」. 종전에는 실패도 `[]`여서 **선박이 10척
   * 등록된 계정에서도 「등록된 선박이 없습니다」**가 나갔다.
   *
   * 실패를 `failure`(아래 리포트 생성 오류 칸)에 담지 않는 것이 핵심이다 —
   * `run()`이 실행할 때마다 `setFailure(null)`로 그 칸을 비우므로, 사용자가
   * 「미리보기」를 한 번 누르면 **오류 문구만 사라지고 「등록된 선박이 없습니다」가
   * 남아** 원인이 정반대로 읽혔다.
   */
  const [vessels, setVessels] = useState<VesselOption[] | 'failed' | null>(null)
  /*
   * 항차 목록 (`#824` ⑵).
   *
   * `null`은 **「아직 모른다」**, `'failed'`는 **「못 읽었다」**, 배열은 **「이만큼이
   * 전부다」**다. 종전에는 실패도 `[]`여서 항차가 1,000건이어도 「이 선박에 등록된
   * 항차가 없습니다」로 나갔다.
   *
   * **이 파일이 스스로 세운 규칙을 어기고 있었다** — 선박·연도 셀렉트는 「불러오는
   * 중」과 「없음」을 구분한다(`#613`). 항차 셀렉트만 예외였다.
   */
  const [voyages, setVoyages] = useState<VoyageOption[] | 'failed' | null>(null)
  const [vesselId, setVesselId] = useState('')
  const [voyageId, setVoyageId] = useState('')
  /*
   * 상단바가 기억한 선박이 목록에 없다 (#1414). 삭제된 배를 셸이 기억하고 있을 때다.
   * 항로 비교가 `#1097` ⑵에서 같은 경우를 고쳤다 — 조용히 비워 두면 사용자는 상단바의
   * 배가 선택된 줄 알고 리포트를 누른다.
   */
  const [shellVesselMissing, setShellVesselMissing] = useState(false)
  const [year, setYear] = useState(() => new Date().getFullYear())
  /*
   * 규제연도 선택지 (`#635`). 기능①·연간 시뮬레이션·항로 비교가 이미 쓰는 훅이며
   * (`#632`), 보고서 화면만 로컬 상수를 보고 있었다.
   */
  /*
   * 올해까지 · 최신 연도부터는 이제 훅이 모든 조회 화면에 같게 한다 (#1584) — 종전에는
   * 이 화면만 `reportRules.yearOptions`로 따로 하고 있었다.
   */
  const {
    years,
    loading: yearsLoading,
    failed: yearsFailed,
  } = useYearOptions(vesselId, { throughCurrentYear: true })

  const [preview, setPreview] = useState<{ target: ReportTarget; html: string } | null>(
    null,
  )
  const [busy, setBusy] = useState<null | 'preview' | DownloadFormat>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  /*
   * 선택된 연도를 목록 안으로 맞춘다 (`#635`).
   *
   * 화면은 올해를 기본값으로 들고 시작하는데 **서버 목록이 올해를 포함하지 않을 수
   * 있다.** 그대로 두면 select는 첫 항목을 보이는데 화면의 상태는 여전히 올해라,
   * 사용자가 보는 연도와 요청하는 연도가 갈린다.
   */
  useEffect(() => {
    const next = coerceYear(years, year)
    if (next !== null && next !== year) setYear(next)
    // `years`는 매 렌더 새 배열이라 의존성에 넣으면 무한 루프다 — 내용으로 비교한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [years.join(','), year])

  useEffect(() => {
    api
      .listVessels()
      .then(setVessels)
      .catch(() => {
        // 실패를 `[]`로 두면 「등록된 선박이 없습니다」가 되어 **원인이 뒤바뀐다**
        // (항차 칸이 `#824` ⑵에서 같은 이유로 고쳐진 자리다).
        setVessels('failed')
      })
  }, [api])

  /*
   * 상단바에서 선택을 **지웠을 때**도 따른다. 「지금 셸이 비어 있다」가 아니라
   * 「있다가 비었다」만 본다 — 처음부터 비어 있는 것은 이 화면에서 고르기 전의 상태이고,
   * 셸 밖(테스트·단독 렌더)에서는 늘 비어 있으므로 그때마다 비우면 사용자가 고른 값이
   * 사라진다.
   */
  const previousShellVesselId = useRef(shellVesselId)
  useEffect(() => {
    const previous = previousShellVesselId.current
    previousShellVesselId.current = shellVesselId
    if (previous !== null && shellVesselId === null) setVesselId('')
  }, [shellVesselId])

  /*
   * 셸의 선박을 이 화면에 반영한다 (#1414).
   *
   * **목록이 온 뒤에만 판단한다.** 목록 전에는 그 id가 있는지 모르므로, 먼저 채우면
   * 삭제된 배의 id로 항차를 조회하게 된다. 목록을 못 읽었으면(`'failed'`) 아무것도
   * 하지 않는다 — 없다고 단정할 근거가 없다.
   */
  useEffect(() => {
    if (shellVesselId === null || !Array.isArray(vessels)) return
    if (!vessels.some((vessel) => vessel.id === shellVesselId)) {
      setShellVesselMissing(true)
      setVesselId('')
      selectVesselId(null)
      return
    }
    setShellVesselMissing(false)
    setVesselId(shellVesselId)
  }, [shellVesselId, vessels, selectVesselId])

  /*
   * 선박이 바뀌면 항차를 다시 받는다 (`#824` ⑵).
   *
   * ## 취소 플래그가 없으면 경합이 난다
   *
   * 이 조회는 **단발이 아니라 커서 전량 순회**(`apiProvider.ts`)라 응답 시간이 항차
   * 수에 비례한다. 항차가 많은 A → 적은 B로 빠르게 전환하면 **B가 먼저 오고 A가
   * 덮어쓴다** — 선박 셀렉트는 B인데 항차 셀렉트는 A의 항차이고, 그대로 만들면
   * **선박 B 화면에서 선박 A의 문서**가 나오거나 404/422가 난다. 다음 전환 전까지
   * 복구되지 않는다.
   *
   * 이 저장소의 다른 재조회 열 곳은 전부 이 플래그를 갖고 있었다.
   *
   * ## 비우고 시작한다
   *
   * `setVoyages(null)`을 하지 않으면 **두 번째 선박부터 「불러오는 중」이 영영 뜨지
   * 않고**, 사용자는 A의 항차를 B의 것으로 읽는다 — `#874`가 실시간 CII에서 고친
   * 것과 같은 결함이다.
   */
  useEffect(() => {
    if (!vesselId) {
      setVoyages(null)
      return
    }
    let alive = true
    setVoyageId('')
    setVoyages(null)
    api.listVoyages(vesselId).then(
      (rows) => {
        if (alive) setVoyages(rows)
      },
      () => {
        // 실패를 `[]`로 두면 「등록된 항차가 없습니다」가 되어 **원인이 뒤바뀐다**.
        if (alive) setVoyages('failed')
      },
    )
    return () => {
      alive = false
    }
  }, [api, vesselId])

  const previousShellVoyageId = useRef(shellVoyageId)
  useEffect(() => {
    const previous = previousShellVoyageId.current
    previousShellVoyageId.current = shellVoyageId
    // 상단바에서 항차를 지웠을 때 — 선박 효과와 같은 이유로 「있다가 비었다」만 본다.
    if (previous !== null && shellVoyageId === null) {
      setVoyageId((current) => (current === previous ? '' : current))
    }
  }, [shellVoyageId])

  /*
   * 셸의 항차를 이 화면에 반영한다 (#1414).
   *
   * 항차 목록은 선박이 바뀔 때마다 비우고 다시 받으므로(위 효과), 목록이 도착한 시점이
   * 곧 **그 선박의 항차로 판단할 수 있는 첫 시점**이다. 리포트를 만들 수 없는 항차는
   * 채우지 않는다 — 비활성 선택지를 고른 상태가 된다.
   */
  useEffect(() => {
    if (shellVoyageId === null || !Array.isArray(voyages)) return
    const voyage = voyages.find((item) => item.id === shellVoyageId)
    if (voyage?.reportable) setVoyageId(shellVoyageId)
  }, [shellVoyageId, voyages])

  /* 셸이 고른 항차가 이 선박 목록에 있지만 아직 리포트를 만들 수 없다. */
  const shellVoyageNotReportable =
    shellVoyageId !== null &&
    Array.isArray(voyages) &&
    voyages.some((item) => item.id === shellVoyageId && !item.reportable)

  const resolve = useCallback((): ReportTarget | string => {
    return targetOf(kind, { vesselId, voyageId, year })
  }, [kind, vesselId, voyageId, year])

  /*
   * 늦게 온 문서를 버리는 표 (#1768 · `#1657`과 같은 배선).
   *
   * 조건을 빠르게 바꾸면 앞 요청이 **뒤 요청보다 늦게** 도착할 수 있다. 그대로 두면 지금
   * 고른 조건의 문서 위에 앞 조건의 문서가 덮인다 — 보고 있는 것과 고른 것이 갈린다.
   */
  const generation = useRef(0)

  const makePreview = useCallback(
    async (target: ReportTarget) => {
      generation.current += 1
      const ticket = generation.current
      setBusy('preview')
      setFailure(null)
      try {
        const html = await api.previewHtml(target)
        if (ticket !== generation.current) return
        setPreview({ target, html })
      } catch (error) {
        if (ticket !== generation.current) return
        /*
         * **앞 문서를 지우지 않는다** (#1768). 조건 하나를 잘못 골라 실패했을 때 보고 있던
         * 문서까지 사라지면, 되돌리려면 그 조건을 기억해 다시 골라야 한다. 오류는 조건
         * 기둥에 적고 문서는 그대로 둔다.
         */
        setFailure(
          error instanceof ReportsError
            ? error.message
            : '리포트를 만들지 못했습니다. 잠시 후 다시 시도해 주세요.',
        )
      } finally {
        if (ticket === generation.current) setBusy(null)
      }
    },
    [api],
  )

  const run = async (action: 'preview' | DownloadFormat) => {
    const target = resolve()
    if (typeof target === 'string') {
      setFailure(target)
      return
    }

    if (action === 'preview') {
      setSaved(null)
      await makePreview(target)
      return
    }

    setBusy(action)
    setFailure(null)
    setSaved(null)
    try {
      setSaved(await api.download(target, action))
    } catch (error) {
      // 서버 문구를 그대로 쓴다 — 「완료되지 않은 항차는…」은 화면이 다시 쓸 수 없다.
      setFailure(
        error instanceof ReportsError
          ? error.message
          : '리포트를 만들지 못했습니다. 잠시 후 다시 시도해 주세요.',
      )
    } finally {
      setBusy(null)
    }
  }

  const currentTarget = resolve()
  const ready = typeof currentTarget !== 'string'
  /*
   * 아직 고르지 않은 것을 자리표시자가 말한다.
   *
   * **오류가 아니라 안내다** — `PRD §6.4` 「선행 선택 필요」. 버튼을 눌렀을 때의 검증
   * 문구(`targetOf`의 반환값 · 마침표 있음)와는 다른 상태이며, 같은 절의 현행 관례 ②에
   * 따라 마침표를 찍지 않는다.
   *
   * 연간 실적은 선박만 고르면 완전해지므로, 이 자리에 남는 것은 항차뿐이다.
   */
  const blocking = vesselId ? '항차를 먼저 선택해 주세요' : '선박을 먼저 선택해 주세요'

  /*
   * 한 번 만든 뒤에는 조건을 따라간다 (#1768).
   *
   * **마운트 시에는 만들지 않는다** — `#511`이 항로 비교에서 정한 것과 같다: 사용자가
   * 조건을 정하기 전의 계산은 누구의 질문도 아니다. 게다가 기본 선택은 선박이 비어 있어
   * 만들 대상 자체가 없다. 그래서 `preview`가 있을 때만, 즉 **사용자가 한 번 누른
   * 뒤에만** 이 효과가 일한다.
   *
   * 「미리보기」를 한 번 누른 순간 사용자는 **「이 조건의 문서를 보고 있다」**고 선언한
   * 것이므로, 그 뒤 조건이 바뀌면 보고 있는 것도 따라 바뀌는 편이 맞다. 종전에는 낡은
   * 문서를 남겨 두고 「조건이 바뀌었습니다 — 다시 만들어 주세요」라고 시켰다 — 화면이
   * 할 수 있는 일을 사용자에게 시킨 셈이다.
   *
   * 대상이 **완전하고 직전에 만든 것과 다를 때만** 부른다 — 선박만 바꾼 중간 상태
   * (항차 미선택)에서는 부르지 않는다.
   *
   * ## 의존성은 원시값과 상태 객체뿐이다
   *
   * 대상을 여기서 다시 만든다(`targetOf`). 렌더에서 만든 객체를 의존성에 넣으면 매
   * 렌더 효과가 돌고, `setBusy`가 일으킨 렌더까지 새 요청이 된다. `preview`는 상태라
   * `setPreview` 때만 바뀌므로, 문서가 도착한 렌더에서 한 번 더 돌고 키가 같아 멈춘다.
   */
  useEffect(() => {
    if (preview === null) return
    const target = targetOf(kind, { vesselId, voyageId, year })
    if (typeof target === 'string') return
    if (targetKey(target) === targetKey(preview.target)) return
    void makePreview(target)
  }, [kind, vesselId, voyageId, year, preview, makePreview])

  return (
    <div className="rp">
      <PageHeader screen="REPORTS">
        <p className="page-head__sub">
          항차 완료 리포트와 연간 실적 리포트를 만들고 PDF·CSV로 내려받습니다.
        </p>
      </PageHeader>

      {/*
       * 입력-결과 2단 — `DESIGN_SYSTEM §8.7` 〔권장〕 (#1768). 조건은 고정 폭 기둥으로
       * 따라오고, 문서가 나머지를 채운다. 1100 이하에서는 조건이 위로 접힌다.
       */}
      <div className="rp__split">
        <section className="card rp__form" aria-label="리포트 조건">
          <fieldset className="rp__kinds">
            <legend>리포트 종류</legend>
            <label>
              <input
                type="radio"
                name="report-kind"
                checked={kind === 'ANNUAL'}
                onChange={() => setKind('ANNUAL')}
                data-testid="kind-annual"
              />
              <span>
                <b>연간 실적</b>
                <em>YTD·연도별 추이·정박 기여·연말 예상</em>
              </span>
            </label>
            <label>
              <input
                type="radio"
                name="report-kind"
                checked={kind === 'VOYAGE'}
                onChange={() => setKind('VOYAGE')}
                data-testid="kind-voyage"
              />
              <span>
                <b>항차 완료</b>
                <em>항차 요약·CII 기여도·연료 내역·시나리오 사후 비교</em>
              </span>
            </label>
          </fieldset>

          <div className="rp__selects">
            <label>
              <span>선박</span>
              <select
                value={vesselId}
                onChange={(event) => {
                  setShellVesselMissing(false)
                  setVesselId(event.target.value)
                  selectVesselId(event.target.value || null)
                }}
                data-testid="vessel-select"
              >
                <option value="">선택하세요</option>
                {(Array.isArray(vessels) ? vessels : []).map((vessel) => (
                  <option key={vessel.id} value={vessel.id}>
                    {vessel.name} (IMO {vessel.imoNumber})
                  </option>
                ))}
              </select>
              {/*
                「불러오는 중」과 「없음」을 구분한다. 구분하지 않으면 응답이 느릴 때
                빈 셀렉트만 보여 **선박이 등록되지 않은 앱**으로 읽힌다 (#613).
              */}
              {vessels === null ? (
                <em className="rp__hint" aria-busy="true" role="status">
                  선박 목록을 불러오는 중입니다…
                </em>
              ) : null}
              {/*
                실패는 「없음」과 다르다 (`#1076` ⑴ · `#824` ⑵). 이 안내는 `failure`
                칸이 아니라 셀렉트에 붙어 있으므로 **리포트를 만들어도 지워지지 않는다.**
              */}
              {vessels === 'failed' ? (
                <em className="rp__hint" role="alert">
                  선박 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
                </em>
              ) : null}
              {Array.isArray(vessels) && vessels.length === 0 ? (
                <em className="rp__hint">등록된 선박이 없습니다.</em>
              ) : null}
              {shellVesselMissing ? (
                <em className="rp__hint" role="alert">
                  상단바에서 고른 선박이 목록에 없습니다. 다시 선택해 주세요.
                </em>
              ) : null}
            </label>

            {kind === 'ANNUAL' ? (
              <label>
                <span>연도</span>
                {/*
                  선택지는 **서버가 등재한 규제연도**에서 온다 (`#635`). 종전에는 하한이
                  `2019`로 박혀 있어 CII 규제 시작(2023) 이전 해를 고를 수 있었고, 고르면
                  전부 `—`인 빈 문서가 `200 OK`로 나왔다.
                */}
                <select
                  value={year}
                  onChange={(event) => setYear(Number(event.target.value))}
                  disabled={!vesselId || years.length === 0}
                  data-testid="year-select"
                >
                  {years.map((option) => (
                    <option key={option} value={option}>
                      {option}년
                    </option>
                  ))}
                </select>
                {/*
                  로딩·실패를 **빈 목록과 구분한다** — 선박 선택 칸이 이미 같은 3상태
                  안내를 쓴다. 「없다」와 「아직 모른다」를 같게 그리면 사용자는 기다려야
                  할지 문의해야 할지 판단할 수 없다.
                */}
                {vesselId && yearsLoading ? (
                  <em className="rp__hint">규제연도를 불러오는 중입니다…</em>
                ) : null}
                {vesselId && yearsFailed ? (
                  <em className="rp__hint">규제연도 목록을 불러오지 못했습니다.</em>
                ) : null}
                {vesselId && !yearsLoading && !yearsFailed && years.length === 0 ? (
                  <em className="rp__hint">등재된 규제연도가 없습니다.</em>
                ) : null}
              </label>
            ) : (
              <label>
                <span>항차</span>
                <select
                  value={voyageId}
                  onChange={(event) => {
                    setVoyageId(event.target.value)
                    selectVoyageId(event.target.value || null)
                  }}
                  disabled={!vesselId}
                  data-testid="voyage-select"
                >
                  <option value="">선택하세요</option>
                  {(Array.isArray(voyages) ? voyages : []).map((voyage) => (
                    <option
                      key={voyage.id}
                      value={voyage.id}
                      /* 감추지 않고 비활성으로 — 감추면 「왜 없지」에 답이 없다. */
                      disabled={!voyage.reportable}
                    >
                      {voyageLabel(voyage)}
                      {voyage.reportable ? '' : ' — 완료 후 생성 가능'}
                    </option>
                  ))}
                </select>
                {/* 선박을 고른 뒤에만 항차를 부른다 — 고르기 전 「불러오는 중」은 거짓말이다. */}
                {vesselId && voyages === null ? (
                  <em className="rp__hint" aria-busy="true" role="status">
                    항차 목록을 불러오는 중입니다…
                  </em>
                ) : null}
                {/*
                  실패는 「없음」과 다르다 (`#824` ⑵). 종전에는 둘이 같은 문구로
                  나가서, 조회가 실패한 선박이 **항차가 없는 선박으로 보였다.**
                */}
                {vesselId && voyages === 'failed' ? (
                  <em className="rp__hint" role="alert">
                    항차 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
                  </em>
                ) : null}
                {vesselId && Array.isArray(voyages) && voyages.length === 0 ? (
                  <em className="rp__hint">이 선박에 등록된 항차가 없습니다.</em>
                ) : null}
                {/*
                  상단바 항차를 따르지 못한 이유를 말한다 (#1414). 말하지 않으면 「따른다」는
                  규칙이 이 화면에서만 깨진 것으로 읽힌다.
                */}
                {shellVoyageNotReportable && !voyageId ? (
                  <em className="rp__hint">
                    상단바에서 고른 항차는 완료 전이라 리포트를 만들 수 없습니다.
                  </em>
                ) : null}
                {Array.isArray(voyages) &&
                voyages.length > 0 &&
                !voyages.some((v) => v.reportable) ? (
                  <em className="rp__hint">
                    완료된 항차가 없습니다. 진행 중 항차는 실적이 확정된 뒤 생성할 수
                    있습니다.
                  </em>
                ) : null}
              </label>
            )}
          </div>

          <div className="rp__actions">
            <button
              type="button"
              onClick={() => void run('preview')}
              disabled={busy !== null}
              data-testid="preview-button"
            >
              {busy === 'preview' ? '만드는 중…' : '미리보기'}
            </button>
            <button
              type="button"
              className="rp__primary"
              onClick={() => void run('pdf')}
              disabled={busy !== null}
              data-testid="pdf-button"
            >
              {busy === 'pdf' ? '만드는 중…' : 'PDF 내려받기'}
            </button>
            <button
              type="button"
              onClick={() => void run('csv')}
              disabled={busy !== null}
              data-testid="csv-button"
            >
              {busy === 'csv' ? '만드는 중…' : 'CSV 내려받기'}
            </button>
          </div>

          {failure ? (
            <ErrorState level="region" size="compact" message={failure} />
          ) : null}
          {saved ? (
            <p className="rp__ok" role="status">
              내려받았습니다 — <b>{saved}</b>
            </p>
          ) : null}
        </section>

        <section className="card rp__doc" aria-label="리포트 미리보기">
          <div className="card__head">
            <h2 className="card__title">미리보기</h2>
            <span className="card__meta">
              {busy === 'preview'
                ? '만드는 중…'
                : preview === null
                  ? '아직 만들지 않았습니다'
                  : '실제 문서와 같은 내용'}
            </span>
          </div>
          {preview ? (
            <iframe
              className={`rp__frame${busy === 'preview' ? ' rp__frame--busy' : ''}`}
              title="리포트 미리보기"
              srcDoc={preview.html}
              /* 문서에 스크립트가 있을 이유가 없다 — 없다는 것을 화면이 강제한다. */
              sandbox=""
            />
          ) : (
            /*
             * 빈 카드를 두지 않는다 (#1768 · `§16` 항목 8 → `PRD §6.4`). 종전에는 누르기
             * 전까지 이 기둥이 아예 없어 **첫 화면의 40%가 빈 면**이었다. 무엇을 고르면
             * 무엇이 나오는지를 그 자리에 적는다.
             */
            <div className="rp__placeholder">
              <p className="rp__placeholder-lead">
                {ready ? '「미리보기」를 누르면 문서가 여기에 나옵니다' : blocking}
              </p>
              <p className="rp__placeholder-note">
                내려받는 PDF와 <b>같은 문서</b>입니다. 한 번 만든 뒤에는 조건을 바꾸면
                문서도 따라 바뀝니다.
              </p>
            </div>
          )}
        </section>
      </div>

      {/*
       * 화면 면책은 문서 면책과 **별개**다. 문서에는 서버가 넣고(PRD §25.1),
       * 화면에는 여기서 넣는다 — 문서를 만들지 않고 화면만 본 사용자도 있다.
       */}
      <DisclaimerBanner />
      {/*
        리포트의 **성격**만 말한다(`PRD §25.1`). 종전 뒷문장 「대관 제출용 공식 문서가
        아닙니다」는 바로 위 배너의 「규제 제출용 공식 결과가 아닙니다」와 같은 말이었다 (#1578).
      */}
      <p className="rp__note">
        리포트는 <b>내부 보고용</b>입니다.
      </p>
    </div>
  )
}