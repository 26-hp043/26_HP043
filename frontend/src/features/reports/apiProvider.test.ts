import { describe, expect, it, vi } from 'vitest'
import { createApiReportsProvider, pathOf, ReportsError } from './apiProvider'
import type { ReportTarget } from './types'

/**
 * 리포트 provider 계약 (`API_SPEC §8.3~§8.5` · `#362`).
 *
 * 고정하는 것 셋.
 *
 * * **fetch로 받는 것** — `<a href>`로 걸면 실패가 화면 밖에서 일어난다. 401이면
 *   로그인 HTML이 `.pdf`로 저장되고, 사용자는 파일을 열고 나서야 잘못을 안다.
 * * **서버 오류 문구를 그대로 쓰는 것** — 「완료되지 않은 항차는…」은 화면이 다시
 *   쓸 수 없다.
 * * **서버가 준 파일명을 쓰는 것.**
 */

const ANNUAL: ReportTarget = { kind: 'ANNUAL', vesselId: 'v-1', year: 2026 }
const VOYAGE: ReportTarget = { kind: 'VOYAGE', voyageId: 'vy-1' }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function fileResponse(body: string, disposition?: string): Response {
  return new Response(body, {
    status: 200,
    headers: disposition ? { 'Content-Disposition': disposition } : {},
  })
}

describe('경로', () => {
  it('두 리포트가 서로 다른 리소스에 걸린다', () => {
    expect(pathOf(VOYAGE, 'pdf')).toBe('/voyages/vy-1/report?format=pdf')
    expect(pathOf(ANNUAL, 'csv')).toBe('/vessels/v-1/annual-report?year=2026&format=csv')
  })
})

describe('목록', () => {
  it('선박을 옮긴다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        data: [{ id: 'v-1', name: 'DONGJIN ENDURANCE', imo_number: '9633862' }],
      }),
    )
    const result = await createApiReportsProvider(fetchImpl).listVessels()
    expect(result[0]).toEqual({
      id: 'v-1',
      name: 'DONGJIN ENDURANCE',
      imoNumber: '9633862',
    })
  })

  it('진행 중 항차를 목록에서 지우지 않고 표시만 내린다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        data: [
          { id: 'a', voyage_no: '1', status: 'COMPLETED', regulation_year: 2026 },
          { id: 'b', voyage_no: '2', status: 'IN_PROGRESS', regulation_year: 2026 },
        ],
      }),
    )
    const result = await createApiReportsProvider(fetchImpl).listVoyages('v-1')

    // 감추면 「내 항차가 왜 없지」에 답이 없다.
    expect(result).toHaveLength(2)
    expect(result.map((v) => v.reportable)).toEqual([true, false])
  })
})

describe('미리보기', () => {
  it('PDF와 같은 소스를 받는다 — format=html', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(fileResponse('<html>문서</html>'))
    const html = await createApiReportsProvider(fetchImpl).previewHtml(ANNUAL)

    expect(fetchImpl.mock.calls[0][0]).toContain('format=html')
    expect(html).toContain('문서')
  })
})

describe('다운로드', () => {
  it('서버가 준 UTF-8 파일명으로 저장한다', async () => {
    const saved: Array<{ blob: Blob; filename: string }> = []
    const fetchImpl = vi.fn().mockResolvedValue(
      fileResponse(
        'csv',
        "attachment; filename=\"annual-report-x.csv\"; filename*=UTF-8''%EC%97%B0%EA%B0%84.csv",
      ),
    )

    const provider = createApiReportsProvider(fetchImpl, '/api/v1', (blob, filename) =>
      saved.push({ blob, filename }),
    )
    const name = await provider.download(ANNUAL, 'csv')

    expect(name).toBe('연간.csv')
    expect(saved[0].filename).toBe('연간.csv')
  })

  it('헤더가 없으면 대체 이름을 만든다 — 확장자는 요청한 포맷이다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(fileResponse('pdf'))
    const provider = createApiReportsProvider(fetchImpl, '/api/v1', () => {})

    expect(await provider.download(ANNUAL, 'pdf')).toMatch(/\.pdf$/)
  })

  it('요청한 포맷을 그대로 보낸다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(fileResponse('x'))
    const provider = createApiReportsProvider(fetchImpl, '/api/v1', () => {})
    await provider.download(VOYAGE, 'pdf')

    expect(fetchImpl.mock.calls[0][0]).toContain('format=pdf')
  })

  it('실패하면 저장하지 않는다 — 오류 JSON이 .pdf로 저장되면 안 된다', async () => {
    const saved: string[] = []
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'STATE_TRANSITION_ERROR',
            message: '완료되지 않은 항차는 리포트 대상이 아닙니다 (현재 상태: IN_PROGRESS).',
          },
        },
        422,
      ),
    )
    const provider = createApiReportsProvider(fetchImpl, '/api/v1', (_blob, filename) =>
      saved.push(filename),
    )

    await expect(provider.download(VOYAGE, 'pdf')).rejects.toThrow(/완료되지 않은 항차/)
    expect(saved).toEqual([])
  })
})

describe('실패 경로', () => {
  it('서버 문구를 그대로 쓴다 — 화면이 다시 쓸 수 없는 문장이다', async () => {
    const message = '완료되지 않은 항차는 리포트 대상이 아닙니다 (현재 상태: PLANNED).'
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ error: { message } }, 422))

    await expect(
      createApiReportsProvider(fetchImpl).previewHtml(VOYAGE),
    ).rejects.toThrow(message)
  })

  it('서버가 문구를 안 주면 상태 코드라도 말한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('', { status: 500 }))
    await expect(
      createApiReportsProvider(fetchImpl).previewHtml(ANNUAL),
    ).rejects.toThrow(/HTTP 500/)
  })

  it('네트워크 실패를 삼키지 않고 원인을 보존한다', async () => {
    const cause = new TypeError('Failed to fetch')
    const fetchImpl = vi.fn().mockRejectedValue(cause)

    const promise = createApiReportsProvider(fetchImpl).listVessels()
    await expect(promise).rejects.toBeInstanceOf(ReportsError)
    await expect(promise).rejects.toMatchObject({ cause })
  })
})
