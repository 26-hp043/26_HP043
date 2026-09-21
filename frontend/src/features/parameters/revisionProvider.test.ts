import { describe, expect, it, vi } from 'vitest'
import { RevisionError, createApiParameterRevisionProvider } from './revisionProvider'

/** 규제 기준값 개정 적재·이력 provider (`#1517` · `API_SPEC §7.5` · `§16.1`). */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const FILE = new File(['year,z_factor_percent\n2027,13.625\n'], 'z.csv', { type: 'text/csv' })

describe('importParameters', () => {
  it('multipart로 파일과 종류를 보내고 Content-Type을 손으로 붙이지 않는다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({
        data: { table: 'regulation_years', imported_count: 1, replaced_count: 1, errors: [], dry_run: true },
      }),
    )
    const provider = createApiParameterRevisionProvider(fetchImpl, '/api/v1')
    const got = await provider.importParameters('regulation_years', FILE, { dryRun: true })

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/parameters/import')
    expect(url).toContain('dry_run=true')
    const form = init.body as FormData
    expect(form.get('type')).toBe('regulation_years')
    expect(form.get('file')).toBeInstanceOf(File)
    expect(Object.keys((init.headers ?? {}) as Record<string, string>)).not.toContain('Content-Type')
    expect(got).toMatchObject({ importedCount: 1, replacedCount: 1, dryRun: true, errors: [] })
  })

  it('행 오류를 옮기고 모양이 깨진 항목은 버린다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({
        data: {
          table: 'reference_lines',
          imported_count: 0,
          replaced_count: 0,
          errors: [{ row: 3, field: 'c', message: '숫자가 아닙니다.' }, { row: 'x' }],
          dry_run: true,
        },
      }),
    )
    const got = await createApiParameterRevisionProvider(fetchImpl, '').importParameters(
      'reference_lines',
      FILE,
      { dryRun: true },
    )
    expect(got.errors).toEqual([{ row: 3, field: 'c', message: '숫자가 아닙니다.' }])
  })

  it('403이면 서버 문구를 그대로 담고 막힌 것임을 표시한다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: 'FORBIDDEN_ROLE', message: '둘러보기에서는 열람할 수 없는 화면입니다.' } }, 403),
    )
    const error = await createApiParameterRevisionProvider(fetchImpl, '')
      .importParameters('fuel_types', FILE, { dryRun: false })
      .catch((e: unknown) => e)
    expect(error).toBeInstanceOf(RevisionError)
    expect((error as RevisionError).forbidden).toBe(true)
    expect((error as RevisionError).message).toContain('둘러보기')
  })

  it('필수 필드가 빠진 응답은 계약 위반으로 본다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: { table: 'x' } }))
    await expect(
      createApiParameterRevisionProvider(fetchImpl, '').importParameters('fuel_types', FILE, {
        dryRun: true,
      }),
    ).rejects.toBeInstanceOf(RevisionError)
  })
})

describe('listRevisions', () => {
  it('PARAMETER_IMPORT만 묻고 행위자·판본·출처를 옮긴다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({
        data: [
          {
            id: 'e1',
            timestamp: '2026-09-21T03:15:00+00:00',
            action: 'PARAMETER_IMPORT',
            user_id: 'u1',
            actor: { display_name: '홍길동', email: 'office@example.com' },
            entity_type: 'regulation_years',
            details: {
              imported_count: 3,
              replaced_count: 1,
              version: 'import.20260921T031500Z',
              dry_run: false,
              source_refs: ['MEPC.400(83)'],
            },
          },
        ],
        meta: { next_cursor: 'c2', has_more: true },
      }),
    )
    const page = await createApiParameterRevisionProvider(fetchImpl, '/api/v1').listRevisions()
    const [url] = fetchImpl.mock.calls[0] as unknown as [string]
    expect(url).toContain('action=PARAMETER_IMPORT')
    expect(page.nextCursor).toBe('c2')
    expect(page.events[0]).toMatchObject({
      kind: 'regulation_years',
      actor: { displayName: '홍길동', email: 'office@example.com' },
      importedCount: 3,
      replacedCount: 1,
      version: 'import.20260921T031500Z',
      sourceRefs: ['MEPC.400(83)'],
    })
  })

  it('다음 쪽은 커서를 붙여 묻는다', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ data: [], meta: {} }))
    const page = await createApiParameterRevisionProvider(fetchImpl, '').listRevisions('c2')
    const [url] = fetchImpl.mock.calls[0] as unknown as [string]
    expect(url).toContain('cursor=c2')
    expect(page.nextCursor).toBeNull()
  })

  it('행위자를 못 풀면 null로 둔다 — 식별자는 남는다', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({
        data: [{ id: 'e1', timestamp: '2026-09-21T03:15:00+00:00', user_id: 'u9', actor: null, details: {} }],
        meta: {},
      }),
    )
    const page = await createApiParameterRevisionProvider(fetchImpl, '').listRevisions()
    expect(page.events[0].actor).toBeNull()
    expect(page.events[0].userId).toBe('u9')
  })
})
