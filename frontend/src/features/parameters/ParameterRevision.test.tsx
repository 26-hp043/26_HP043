// @vitest-environment jsdom
import '../../test/renderSetup'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { CurrentUser } from '../../auth/session'
import { ParameterRevision } from './ParameterRevision'
import { RevisionError, type ParameterRevisionProvider } from './revisionProvider'
import type { ParameterImportResult } from './revisionRules'

/**
 * 규제 기준값 개정 적재 화면 (`#1517` · `#1239` 결정 D·E·F·H).
 *
 * 문구가 아니라 성질을 단언한다(`AGENTS §4.6`) — 역할별로 무엇이 열리고 닫히는가,
 * 확정이 언제 열리는가, 확정 뒤 이력이 다시 불리는가.
 */

function user(role: CurrentUser['role']): CurrentUser {
  return {
    id: 'u1',
    email: 'someone@example.com',
    displayName: '사용자',
    role,
    emailVerifiedAt: '2026-09-01T00:00:00Z',
  } as CurrentUser
}

function provider(
  results: ParameterImportResult[] = [],
  history: Parameters<ParameterRevisionProvider['listRevisions']> extends unknown[]
    ? Awaited<ReturnType<ParameterRevisionProvider['listRevisions']>>
    : never = { events: [], nextCursor: null },
): ParameterRevisionProvider & {
  importParameters: ReturnType<typeof vi.fn>
  listRevisions: ReturnType<typeof vi.fn>
} {
  const queue = [...results]
  return {
    importParameters: vi.fn(async () => {
      const next = queue.shift()
      if (!next) throw new Error('예상하지 않은 호출')
      return next
    }),
    listRevisions: vi.fn(async () => history),
  }
}

function ok(dryRun: boolean): ParameterImportResult {
  return { kind: 'regulation_years', importedCount: 2, replacedCount: 1, errors: [], dryRun }
}

function pickFile() {
  const input = screen.getByLabelText('적재할 CSV 파일') as HTMLInputElement
  const file = new File(['year\n2027\n'], 'z.csv', { type: 'text/csv' })
  fireEvent.change(input, { target: { files: [file] } })
}

describe('ParameterRevision', () => {
  it('현장직에게는 적재 영역을 열지 않되 숨기지 않고 잠긴 이유를 보인다', () => {
    const p = provider()
    render(<ParameterRevision user={user('FIELD')} provider={p} />)
    expect(screen.queryByLabelText('적재할 CSV 파일')).toBeNull()
    expect(screen.getByRole('heading', { name: '개정 적재' })).toBeTruthy()
    expect(p.listRevisions).not.toHaveBeenCalled()
  })

  it('오류가 있는 검증 결과로는 확정을 열지 않는다 — 전부 아니면 전무', async () => {
    const p = provider([
      { ...ok(true), errors: [{ row: 3, field: 'c', message: '숫자가 아닙니다.' }] },
    ])
    render(<ParameterRevision user={user('OFFICE')} provider={p} />)
    pickFile()
    fireEvent.click(screen.getByRole('button', { name: '검증' }))
    await screen.findByRole('table', { name: '문제가 있는 행' })
    expect((screen.getByRole('button', { name: '확정' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('검증을 통과하면 확정이 열리고, 확정하면 이력을 다시 불러온다', async () => {
    const onImported = vi.fn()
    const p = provider([ok(true), ok(false)])
    render(<ParameterRevision user={user('OFFICE')} provider={p} onImported={onImported} />)
    await waitFor(() => expect(p.listRevisions).toHaveBeenCalledTimes(1))

    pickFile()
    fireEvent.click(screen.getByRole('button', { name: '검증' }))
    const commit = screen.getByRole('button', { name: '확정' })
    await waitFor(() => expect((commit as HTMLButtonElement).disabled).toBe(false))

    fireEvent.click(commit)
    await waitFor(() => expect(onImported).toHaveBeenCalledTimes(1))
    expect(p.importParameters).toHaveBeenLastCalledWith('regulation_years', expect.any(File), {
      dryRun: false,
    })
    await waitFor(() => expect(p.listRevisions).toHaveBeenCalledTimes(2))
  })

  it('종류를 바꾸면 앞의 검증 결과를 버린다 — 다른 종류의 결과로 확정하지 않게', async () => {
    const p = provider([ok(true)])
    render(<ParameterRevision user={user('OFFICE')} provider={p} />)
    pickFile()
    fireEvent.click(screen.getByRole('button', { name: '검증' }))
    await waitFor(() => expect((screen.getByRole('button', { name: '확정' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.change(screen.getByLabelText('종류'), { target: { value: 'fuel_types' } })
    expect((screen.getByRole('button', { name: '확정' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('이력에는 식별자가 아니라 사람을 보인다', async () => {
    const p = provider([], {
      events: [
        {
          id: 'e1',
          timestamp: '2026-09-21T03:15:00+00:00',
          kind: 'regulation_years',
          actor: { displayName: '홍길동', email: 'office@example.com' },
          userId: 'uuid-should-not-show',
          importedCount: 3,
          replacedCount: 1,
          version: 'import.20260921T031500Z',
          sourceRefs: ['MEPC.400(83)'],
        },
      ],
      nextCursor: null,
    })
    render(<ParameterRevision user={user('OFFICE')} provider={p} />)
    expect(await screen.findByText(/홍길동/)).toBeTruthy()
    expect(screen.queryByText(/uuid-should-not-show/)).toBeNull()
    expect(screen.getByText('import.20260921T031500Z')).toBeTruthy()
  })

  it('서버가 이력을 막으면(둘러보기 403) 그 문구를 그대로 보인다', async () => {
    const p = provider()
    p.listRevisions.mockRejectedValueOnce(
      new RevisionError('둘러보기에서는 열람할 수 없는 화면입니다.', { forbidden: true }),
    )
    render(<ParameterRevision user={user('ADMIN')} provider={p} />)
    expect(await screen.findByText('둘러보기에서는 열람할 수 없는 화면입니다.')).toBeTruthy()
  })
})


describe('늦게 온 검증 결과 (#1642)', () => {
  /** 검증 응답을 테스트가 원할 때 끝내는 provider. */
  function deferredProvider() {
    let release: ((value: ParameterImportResult) => void) | null = null
    const importParameters = vi.fn(
      () =>
        new Promise<ParameterImportResult>((resolve) => {
          release = resolve
        }),
    )
    return {
      provider: { importParameters, listRevisions: vi.fn(async () => ({ events: [], nextCursor: null })) },
      finish: (value: ParameterImportResult) => release?.(value),
      importParameters,
    }
  }

  it('기다리는 동안 종류를 바꾸면 앞 요청의 성공으로 확정이 열리지 않는다', async () => {
    const { provider: p, finish } = deferredProvider()
    render(<ParameterRevision user={user('OFFICE')} provider={p as never} />)
    pickFile()
    fireEvent.click(screen.getByRole('button', { name: '검증' }))

    fireEvent.change(screen.getByLabelText('종류'), { target: { value: 'fuel_types' } })
    finish(ok(true))

    await waitFor(() =>
      expect((screen.getByRole('button', { name: '검증' }) as HTMLButtonElement).disabled).toBe(false),
    )
    expect((screen.getByRole('button', { name: '확정' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('기다리는 동안 파일을 바꿔도 앞 요청의 성공을 쓰지 않는다', async () => {
    const { provider: p, finish } = deferredProvider()
    render(<ParameterRevision user={user('OFFICE')} provider={p as never} />)
    pickFile()
    fireEvent.click(screen.getByRole('button', { name: '검증' }))

    pickFile()
    finish(ok(true))

    await waitFor(() =>
      expect((screen.getByRole('button', { name: '검증' }) as HTMLButtonElement).disabled).toBe(false),
    )
    expect((screen.getByRole('button', { name: '확정' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
