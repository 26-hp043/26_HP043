// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { PositionForm } from './PositionForm'
import { VesselDetailError } from './apiProvider'
import type { VesselDetailProvider, VesselSpec } from './types'

/**
 * 위치 저장 실패의 자리 (#2126).
 *
 * 서버가 지목한 칸은 그 칸 아래에, **모르는 `field`는 어느 칸에도 붙이지 않고** 폼의 일반
 * 오류로 보인다. 종전에는 모르는 이름이 「세부 상태」 칸에 붙었다.
 */

const VESSEL = {
  id: 'v-1',
  underwayState: 'NOT_UNDER_WAY',
  detailStatus: 'AT_ANCHOR',
  lat: '35.1',
  lon: '129.0',
} as unknown as VesselSpec

async function failSave(error: Error) {
  const provider = {
    updatePosition: vi.fn().mockRejectedValue(error),
  } as unknown as VesselDetailProvider
  render(<PositionForm vessel={VESSEL} provider={provider} onSaved={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /위치 · 상태 수정/ }))
  fireEvent.change(screen.getByLabelText(/위도/), { target: { value: '36.2' } })
  fireEvent.click(screen.getByRole('button', { name: '저장' }))
  await waitFor(() => expect(provider.updatePosition).toHaveBeenCalled())
}

describe('위치 저장 실패의 자리 (#2126)', () => {
  it('모르는 field는 어느 칸에도 붙지 않고 폼의 일반 오류로 보인다', async () => {
    await failSave(new VesselDetailError('서버가 말한 사유', { field: 'something_else' }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('서버가 말한 사유')
    // 어느 입력창도 오류 상태가 아니다 — 세부 상태 칸에 붙던 것이 종전 결함이다.
    for (const control of screen.getAllByRole('combobox')) {
      expect(control.getAttribute('aria-invalid')).not.toBe('true')
    }
    expect(screen.getByLabelText(/위도/).getAttribute('aria-invalid')).not.toBe('true')
  })

  it('field가 없는 오류도 같은 일반 오류 자리다', async () => {
    await failSave(new VesselDetailError('서버가 말한 사유'))
    expect((await screen.findByRole('alert')).textContent).toContain('서버가 말한 사유')
  })

  it('아는 field는 그 칸에 붙는다', async () => {
    await failSave(new VesselDetailError('위도 사유', { field: 'current_lat' }))
    await waitFor(() =>
      expect(screen.getByLabelText(/위도/).getAttribute('aria-invalid')).toBe('true'),
    )
    expect(screen.getByLabelText(/경도/).getAttribute('aria-invalid')).not.toBe('true')
  })

  it('detail_status는 세부 상태 칸에 붙는다', async () => {
    await failSave(new VesselDetailError('세부 사유', { field: 'detail_status' }))
    await waitFor(() =>
      expect(screen.getByLabelText(/세부 상태/).getAttribute('aria-invalid')).toBe('true'),
    )
  })
})
