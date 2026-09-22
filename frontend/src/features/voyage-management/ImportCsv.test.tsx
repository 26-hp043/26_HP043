// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ImportCsv } from './ImportCsv'
import type { ImportResult } from './importRules'
import type { VoyageManagementProvider } from './apiProvider'

/**
 * 항차 CSV 가져오기의 **늦게 온 검증 결과** (`#1642`).
 *
 * 검증이 도는 동안 파일을 바꿨는데 앞 파일의 성공이 적용되면, 사용자는 **B를 보면서 A의 결과로**
 * 확정하게 된다. 그 경로만 본다 — 나머지 동작은 `VoyagePanel.test.tsx`가 덮는다.
 */

function ok(dryRun: boolean): ImportResult {
  return { importedCount: 2, skippedCount: 0, errors: [], dryRun, missingDepartureCount: 0 }
}

function deferred() {
  let release: ((value: ImportResult) => void) | null = null
  const importCsv = vi.fn(
    () =>
      new Promise<ImportResult>((resolve) => {
        release = resolve
      }),
  )
  const provider = { importCsv } as unknown as VoyageManagementProvider
  return { provider, importCsv, finish: (value: ImportResult) => release?.(value) }
}

function pick(name: string) {
  const input = screen.getByLabelText('가져올 CSV 파일') as HTMLInputElement
  fireEvent.change(input, { target: { files: [new File(['a\n1\n'], name, { type: 'text/csv' })] } })
}

function commitButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /가져오기/ }) as HTMLButtonElement
}

describe('늦게 온 검증 결과 (#1642)', () => {
  it('기다리는 동안 파일을 바꾸면 앞 파일의 성공으로 확정이 열리지 않는다', async () => {
    const { provider, finish } = deferred()
    render(<ImportCsv vesselId="v-1" provider={provider} onImported={vi.fn()} />)

    pick('a.csv')
    fireEvent.click(screen.getByRole('button', { name: '검증' }))
    pick('b.csv')
    finish(ok(true))

    await waitFor(() =>
      expect((screen.getByRole('button', { name: /검증/ }) as HTMLButtonElement).disabled).toBe(false),
    )
    expect(commitButton().disabled).toBe(true)
  })

  it('파일을 바꾸지 않으면 검증 성공이 그대로 확정을 연다', async () => {
    const { provider, finish } = deferred()
    render(<ImportCsv vesselId="v-1" provider={provider} onImported={vi.fn()} />)

    pick('a.csv')
    fireEvent.click(screen.getByRole('button', { name: '검증' }))
    finish(ok(true))

    await waitFor(() => expect(commitButton().disabled).toBe(false))
  })
})
