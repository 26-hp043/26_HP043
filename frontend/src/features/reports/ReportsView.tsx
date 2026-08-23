import { useCallback, useEffect, useRef, useState } from 'react'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { PageHeader } from '../../components/PageHeader'
import { useYearOptions } from '../parameters/yearCatalog'
import { createApiReportsProvider, ReportsError } from './apiProvider'
import {
  coerceYear,
  sameTarget,
  targetOf,
  voyageLabel,
  yearOptions,
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
 */
export function ReportsView({ provider }: { provider?: ReportsProvider }) {
  const providerRef = useRef<ReportsProvider | null>(null)
  if (providerRef.current === null) {
    providerRef.current = provider ?? createApiReportsProvider()
  }
  const api = providerRef.current

  const [kind, setKind] = useState<ReportKind>('ANNUAL')
  const [vessels, setVessels] = useState<VesselOption[] | null>(null)
  const [voyages, setVoyages] = useState<VoyageOption[] | null>(null)
  const [vesselId, setVesselId] = useState('')
  const [voyageId, setVoyageId] = useState('')
  const [year, setYear] = useState(() => new Date().getFullYear())
  /*
   * 규제연도 선택지 (`#635`). 기능①·연간 시뮬레이션·항로 비교가 이미 쓰는 훅이며
   * (`#632`), 보고서 화면만 로컬 상수를 보고 있었다.
   */
  const {
    years: regulationYears,
    loading: yearsLoading,
    failed: yearsFailed,
  } = useYearOptions(vesselId)
  const years = yearOptions(regulationYears, new Date().getFullYear())

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
      .catch((error: unknown) => {
        setVessels([])
        setFailure(
          error instanceof Error ? error.message : '선박 목록을 불러오지 못했습니다.',
        )
      })
  }, [api])

  useEffect(() => {
    if (!vesselId) {
      setVoyages(null)
      return
    }
    setVoyageId('')
    api
      .listVoyages(vesselId)
      .then(setVoyages)
      .catch(() => setVoyages([]))
  }, [api, vesselId])

  const resolve = useCallback((): ReportTarget | string => {
    return targetOf(kind, { vesselId, voyageId, year })
  }, [kind, vesselId, voyageId, year])

  const run = async (action: 'preview' | DownloadFormat) => {
    const target = resolve()
    if (typeof target === 'string') {
      setFailure(target)
      return
    }

    setBusy(action)
    setFailure(null)
    setSaved(null)
    try {
      if (action === 'preview') {
        setPreview({ target, html: await api.previewHtml(target) })
      } else {
        setSaved(await api.download(target, action))
      }
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

  // 선택이 바뀌면 미리보기는 더 이상 그 선택의 것이 아니다. 남겨 두면 사용자가
  // 다른 대상의 문서를 보면서 다운로드를 누른다.
  const currentTarget = resolve()
  const previewIsStale =
    preview !== null &&
    (typeof currentTarget === 'string' || !sameTarget(preview.target, currentTarget))

  return (
    <div className="rp">
      <PageHeader screen="REPORTS">
        <p className="page-head__sub">
          항차 완료 리포트와 연간 실적 리포트를 만들고 PDF·CSV로 내려받습니다.
        </p>
      </PageHeader>

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
              onChange={(event) => setVesselId(event.target.value)}
              data-testid="vessel-select"
            >
              <option value="">선택하세요</option>
              {(vessels ?? []).map((vessel) => (
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
              <em className="rp__hint" aria-busy="true">
                선박 목록을 불러오는 중입니다…
              </em>
            ) : null}
            {vessels !== null && vessels.length === 0 ? (
              <em className="rp__hint">등록된 선박이 없습니다.</em>
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
                onChange={(event) => setVoyageId(event.target.value)}
                disabled={!vesselId}
                data-testid="voyage-select"
              >
                <option value="">선택하세요</option>
                {(voyages ?? []).map((voyage) => (
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
                <em className="rp__hint" aria-busy="true">
                  항차 목록을 불러오는 중입니다…
                </em>
              ) : null}
              {vesselId && voyages !== null && voyages.length === 0 ? (
                <em className="rp__hint">이 선박에 등록된 항차가 없습니다.</em>
              ) : null}
              {voyages !== null && voyages.length > 0 && !voyages.some((v) => v.reportable) ? (
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
          <p className="rp__error" role="alert">
            {failure}
          </p>
        ) : null}
        {saved ? (
          <p className="rp__ok" role="status">
            내려받았습니다 — <b>{saved}</b>
          </p>
        ) : null}
      </section>

      {preview ? (
        <section className="card rp__preview" aria-label="리포트 미리보기">
          <div className="card__head">
            <h2 className="card__title">미리보기</h2>
            <span className="card__meta">
              {previewIsStale ? '조건이 바뀌었습니다 — 다시 만들어 주세요' : '실제 문서와 같은 내용'}
            </span>
          </div>
          <iframe
            className={`rp__frame${previewIsStale ? ' rp__frame--stale' : ''}`}
            title="리포트 미리보기"
            srcDoc={preview.html}
            /* 문서에 스크립트가 있을 이유가 없다 — 없다는 것을 화면이 강제한다. */
            sandbox=""
          />
        </section>
      ) : null}

      {/*
       * 화면 면책은 문서 면책과 **별개**다. 문서에는 서버가 넣고(PRD §25.1),
       * 화면에는 여기서 넣는다 — 문서를 만들지 않고 화면만 본 사용자도 있다.
       */}
      <DisclaimerBanner />
      <p className="rp__note">
        리포트는 <b>내부 보고용</b>입니다. 대관 제출용 공식 문서가 아닙니다.
      </p>
    </div>
  )
}