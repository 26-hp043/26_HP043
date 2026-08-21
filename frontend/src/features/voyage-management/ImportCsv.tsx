import { useRef, useState } from 'react'
import { VoyageError, type VoyageManagementProvider } from './apiProvider'
import {
  IMPORT_NOTICE,
  MAX_ROWS,
  REQUIRED_COLUMNS,
  canCommit,
  resultSummary,
  validateFile,
  type ImportResult,
} from './importRules'

/**
 * 항차 CSV 가져오기 — 항차 기록 패널 안 (`API_SPEC §8.2` · `#60` 엔드포인트).
 *
 * ## 왜 항차 패널 안인가
 *
 * 가져오기는 **이 선박의 항차를 만드는 또 하나의 입구**다. 결과가 바로 위 목록에
 * 나타나므로 같은 구획에 두면 「올렸다 → 늘었다」가 한 화면에서 보인다. 새 화면을
 * 만들지 않는 이유는 `VoyagePanel`과 같다 — 화면 신설은 `AGENTS §3.2.1`상 UIFLOW
 * 소관이다.
 *
 * ## 검증 → 확인 → 확정
 *
 * `§8.2`는 **부분 성공**이다. 틀린 행이 있어도 유효한 행은 들어간다. 확인 없이 바로
 * 올리면 1,000행 중 700행이 들어간 뒤에 오류 목록을 처음 보게 되고, **그 700행을
 * 되돌리는 경로가 없다**(삭제는 항차 하나씩이다).
 *
 * `dry_run`이 그 자리를 위해 있는 값이다. 검증 결과를 보인 뒤에만 확정 버튼을 연다.
 */
export function ImportCsv({
  vesselId,
  provider,
  onImported,
}: {
  vesselId: string
  provider: VoyageManagementProvider
  /** 확정 성공 후 항차 목록을 다시 불러온다. */
  onImported: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState<'check' | 'commit' | null>(null)

  function pick(next: File | null) {
    setFile(next)
    // 파일이 바뀌면 앞 파일의 검증 결과는 무효다. 남겨 두면 **다른 파일의 결과를
    // 보고 확정**하게 된다.
    setResult(null)
    setFailure(null)
  }

  function reset() {
    pick(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  async function run(dryRun: boolean) {
    const invalid = validateFile(file)
    if (invalid !== null) {
      setFailure(invalid)
      return
    }
    setBusy(dryRun ? 'check' : 'commit')
    setFailure(null)
    try {
      const next = await provider.importCsv(vesselId, file as File, { dryRun })
      setResult(next)
      if (!next.dryRun) {
        onImported()
        reset()
        setResult(next)
      }
    } catch (error) {
      setFailure(error instanceof VoyageError ? error.message : '가져오지 못했습니다.')
      setResult(null)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="vy-import" aria-label="CSV 가져오기">
      <h3 className="vy-import__title">CSV 가져오기</h3>

      <p className="vy-import__hint">
        필수 컬럼 {REQUIRED_COLUMNS.length}개 — <code>{REQUIRED_COLUMNS.join(', ')}</code>
      </p>
      <p className="vy-import__hint">
        UTF-8 · 최대 5MB · {MAX_ROWS.toLocaleString('ko-KR')}행까지.
      </p>

      <div className="vy-import__row">
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          aria-label="가져올 CSV 파일"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
        <button type="button" onClick={() => run(true)} disabled={file === null || busy !== null}>
          {busy === 'check' ? '검증 중…' : '검증'}
        </button>
        <button
          type="button"
          className="vy-import__commit"
          onClick={() => run(false)}
          disabled={!canCommit(result) || busy !== null}
        >
          {busy === 'commit' ? '가져오는 중…' : '가져오기'}
        </button>
      </div>

      {/*
       * 확정 버튼이 왜 잠겨 있는지 적는다. 검증을 먼저 밟게 하는 것이 의도이므로
       * 그 의도를 말하지 않으면 고장으로 읽힌다.
       */}
      {file !== null && result === null && failure === null ? (
        <p className="vy-import__note">먼저 검증하면 무엇이 들어가는지 보고 확정할 수 있습니다.</p>
      ) : null}

      {failure ? (
        <p className="vy-import__error" role="alert">
          {failure}
        </p>
      ) : null}

      {result ? <ResultView result={result} /> : null}
    </section>
  )
}

function ResultView({ result }: { result: ImportResult }) {
  return (
    <div className="vy-import__result" role="status">
      <p className={result.dryRun ? 'vy-import__summary' : 'vy-import__summary vy-import__summary--done'}>
        {resultSummary(result)}
      </p>

      {/* 저장된 뒤에만 낸다 — 검증 단계에서는 아직 아무것도 들어가지 않았다. */}
      {!result.dryRun && result.importedCount > 0 ? (
        <p className="vy-import__note">{IMPORT_NOTICE}</p>
      ) : null}

      {result.errors.length > 0 ? (
        <table className="vy-import__errors">
          <caption>건너뛴 행</caption>
          <thead>
            <tr>
              {/* 파일에서 보이는 번호다 — 헤더가 1행이라 첫 데이터 행이 2다 (`§8.2`). */}
              <th scope="col">행</th>
              <th scope="col">항목</th>
              <th scope="col">사유</th>
            </tr>
          </thead>
          <tbody>
            {result.errors.map((error, index) => (
              <tr key={`${error.row}-${error.field}-${index}`}>
                <td className="num">{error.row}</td>
                <td>
                  <code>{error.field}</code>
                </td>
                <td>{error.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}
