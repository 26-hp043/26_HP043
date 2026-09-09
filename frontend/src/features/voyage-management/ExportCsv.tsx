import { useState } from 'react'
import { VoyageError, type VoyageManagementProvider } from './apiProvider'
import {
  EXPORT_FORMATS,
  EXPORT_TYPES,
  EXPORT_TYPE_HINTS,
  EXPORT_TYPE_LABELS,
  exportQuery,
  fallbackFilename,
  initialExportForm,
  validateExport,
  type ExportErrors,
  type ExportFormState,
  type ExportFormat,
  type ExportType,
} from './exportRules'
import { useYearOptions } from '../parameters/yearCatalog'

/**
 * 운항 기록 내보내기 — 항차 기록 패널 안 (`API_SPEC §8.1` · `PRD §5.1` MUST · `#890`).
 *
 * ## 왜 가져오기 옆인가
 *
 * `PRD:636`이 `SCR-007`을 **「Data Import/Export」 한 항목**으로 규정한다. 가져오기는
 * 이미 `ImportCsv.tsx`가 이 패널 안에 두고 있으므로, 내보내기를 다른 화면에 두면
 * **정본이 한 화면으로 정한 것이 두 화면에 쪼개진다.**
 *
 * 이슈(`#890`)는 「보고서 화면에 붙인다」를 잠정 유력안으로 적었으나, 그 판단은
 * **`UIFLOW`의 `SCR-007` 기술을 확인하기 전**의 것이었다. 확인 결과 `UIFLOW`에
 * `SCR-007`이 없고(`screens.ts` 주석대로 `UIFLOW`는 `SCR-00x` ID를 부여하지 않는다),
 * `SCR-002`도 같은 상황을 상위 문서 `PRD` 근거로 해소한 선례가 있다.
 *
 * 그리고 리포트와 내보내기는 **만드는 것이 다르다** — 라우트 주석이 적어 둔 대로
 * 리포트는 「사람이 읽는 문서」이고 여기는 **「다시 가져올 수 있는 표」**다. 가져오기와
 * 같은 표를 내보내는 것이 이 기능의 뜻이다.
 *
 * ## 화면을 새로 만들지 않는다
 *
 * `AGENTS §3.2.1`상 화면 신설은 `UIFLOW` 소관이다. `ImportCsv`가 같은 이유로 패널
 * 안에 있다.
 */
export function ExportCsv({
  vesselId,
  provider,
}: {
  vesselId: string
  provider: VoyageManagementProvider
}) {
  const [form, setForm] = useState<ExportFormState>(initialExportForm)
  const [errors, setErrors] = useState<ExportErrors>({})
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  /*
   * 연도 선택지도 서버에서 온다 (`#632`가 세 화면에 세운 규칙). 여기만 자유 입력으로
   * 두면 파라미터가 없는 해를 넣을 수 있고, 그때 서버가 거부한다.
   */
  const { years, loading: yearsLoading, failed: yearsFailed } = useYearOptions(vesselId)

  const set = (key: keyof ExportFormState) => (value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    // 조건이 바뀌면 직전 결과 문구를 지운다 — 남겨 두면 방금 받은 것처럼 읽힌다.
    setSaved(null)
    setFailure(null)
  }

  const run = async () => {
    const found = validateExport(form)
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setBusy(true)
    setFailure(null)
    setSaved(null)
    try {
      setSaved(await provider.exportData(vesselId, exportQuery(form), fallbackFilename(form)))
    } catch (error) {
      setFailure(
        error instanceof VoyageError || error instanceof Error
          ? error.message
          : '내보내지 못했습니다.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="vy-export" aria-label="자료 내보내기">
      <h3 className="vy-export__title">자료 내보내기</h3>

      <p className="vy-export__hint">{EXPORT_TYPE_HINTS[form.type as ExportType]}</p>

      <div className="vy-export__row">
        <label className="vy-export__field">
          <span className="vy-export__label">종류</span>
          <select value={form.type} onChange={(e) => set('type')(e.target.value)}>
            {EXPORT_TYPES.map((type) => (
              <option key={type} value={type}>
                {EXPORT_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
        </label>

        {/*
          로딩·실패를 **빈 선택지와 구분해** 보인다 — 셋을 한 문구로 뭉치면 「목록이
          아직 안 왔다」와 「등록된 해가 없다」를 사용자가 가를 수 없다(`#542`·`#632`).
        */}
        <label className="vy-export__field">
          <span className="vy-export__label">연도</span>
          {yearsLoading ? (
            <span className="vy-export__note">연도 목록을 불러오는 중…</span>
          ) : yearsFailed ? (
            <span className="vy-export__note">연도 목록을 불러오지 못했습니다</span>
          ) : (
            <select value={form.year} onChange={(e) => set('year')(e.target.value)}>
              {/* 전체가 기본이다 — `§8.1`의 `year`는 optional이고 선박 전체를 받는 것이 정상 사용이다. */}
              <option value="">전체</option>
              {years.map((year) => (
                <option key={year} value={String(year)}>
                  {year}
                </option>
              ))}
            </select>
          )}
          {errors.year !== undefined && (
            <span className="vy-export__error">{errors.year}</span>
          )}
        </label>

        <label className="vy-export__field">
          <span className="vy-export__label">형식</span>
          <select value={form.format} onChange={(e) => set('format')(e.target.value)}>
            {EXPORT_FORMATS.map((format: ExportFormat) => (
              <option key={format} value={format}>
                {format.toUpperCase()}
              </option>
            ))}
          </select>
        </label>

        <button type="button" className="vy-export__submit" onClick={() => void run()} disabled={busy}>
          {busy ? '내보내는 중…' : '내보내기'}
        </button>
      </div>

      {saved !== null && (
        <p className="vy-export__saved" role="status">
          <strong>{saved}</strong> 파일을 저장했습니다.
        </p>
      )}
      {failure !== null && (
        <p className="vy-export__failure" role="alert">
          {failure}
        </p>
      )}
    </section>
  )
}
