import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { MapRendererHost, type MapRendererEvent } from './renderer'
import type { HarborRendererModel } from './harborRenderer'
import { harborSceneFor } from './harborScenes'
import './HarborTransitionShell.css'

const loadHarbor = () => import('./harborRenderer').then(({ loadHarborRenderer }) => loadHarborRenderer())
let harborHistorySequence = 0

type HarborPort = HarborRendererModel['port']

function harborPort(selection: string | null): HarborPort | null {
  // 대응표는 `harborScenes.ts`가 갖는다 (`#1933`) — 핀을 만드는 쪽도 같은 판정을 써야
  // 「들어갈 수 있는 핀」을 가릴 수 있다. 여기 두면 그쪽에서 알 길이 없었다.
  return selection?.startsWith('port:') ? harborSceneFor(selection) : null
}

interface HarborTransitionShellProps {
  readonly renderGlobe: (onEvent: (event: MapRendererEvent) => void) => ReactNode
  readonly onGlobeEvent?: (event: MapRendererEvent) => void
  readonly onEnterHarbor?: () => void
  readonly onExitHarbor?: () => void
}

/** globe 세션을 보존한 채 lazy HarborScene만 겹쳐 여는 공용 전환 shell이다. */
export function HarborTransitionShell({ renderGlobe, onGlobeEvent, onEnterHarbor, onExitHarbor }: HarborTransitionShellProps) {
  const [port, setPort] = useState<HarborPort | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const returnFocus = useRef<HTMLElement | null>(null)
  const backButton = useRef<HTMLButtonElement | null>(null)
  const [pushed, setPushed] = useState(false)
  const historyEntry = useRef<{ token: string; previousState: unknown } | null>(null)

  const close = useCallback(() => {
    setPort(null)
    setStatus('loading')
    setErrorMessage(null)
    onExitHarbor?.()
  }, [onExitHarbor])

  useEffect(() => {
    const popstate = () => {
      if (port !== null) {
        setPushed(false)
        historyEntry.current = null
        close()
      }
    }
    window.addEventListener('popstate', popstate)
    return () => window.removeEventListener('popstate', popstate)
  }, [close, port])

  useEffect(() => () => {
    const entry = historyEntry.current
    if (entry !== null && history.state?.bluelogHarborToken === entry.token) {
      history.replaceState(entry.previousState, '', location.href)
    }
    historyEntry.current = null
  }, [])

  useEffect(() => {
    if (port !== null) backButton.current?.focus()
    else returnFocus.current?.focus()
  }, [port])

  const globeEvent = useCallback((event: MapRendererEvent) => {
    onGlobeEvent?.(event)
    if (event.type !== 'selection') return
    const selectedPort = harborPort(event.id)
    if (!selectedPort) return
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setStatus('loading')
    setPort(selectedPort)
    onEnterHarbor?.()
    const token = `harbor-${++harborHistorySequence}`
    historyEntry.current = { token, previousState: history.state }
    history.pushState({ bluelogHarbor: selectedPort, bluelogHarborToken: token }, '', location.href)
    setPushed(true)
  }, [onEnterHarbor, onGlobeEvent])
  const harborEvent = useCallback((event: MapRendererEvent) => {
    if (event.type === 'ready') setStatus('ready')
    if (event.type === 'error') { setStatus('error'); setErrorMessage(event.error.message) }
  }, [])

  const requestClose = () => {
    if (pushed) history.back()
    else close()
  }
  // renderer-neutral 이벤트를 주입하는 순수 JSX factory이며 ref 값을 읽지 않는다.
  // oxlint-disable-next-line react/refs
  const globe = renderGlobe(globeEvent)
  return <div className="harbor-transition">
    <div className="harbor-transition__globe" hidden={port !== null} aria-hidden={port !== null || undefined}>
      {globe}
    </div>
    {port === null ? null : <section className="harbor-transition__scene" aria-label={port === 'busan' ? '부산 북항 상세 장면' : '싱가포르 항만 상세 장면'}>
      <div className="harbor-transition__toolbar">
        <button ref={backButton} type="button" onClick={requestClose}>전체 항로로 돌아가기</button>
        <p role="status" aria-live="polite">{status === 'ready' ? '항만 장면이 준비되었습니다.' : status === 'error' ? `항만 장면을 표시하지 못했습니다. ${errorMessage ?? ''}` : '항만 장면을 불러오는 중입니다.'}</p>
      </div>
      {status === 'error' ? <button type="button" onClick={() => { setStatus('loading'); setErrorMessage(null); setAttempt((value) => value + 1) }}>다시 시도</button> : null}
      <MapRendererHost key={`${port}:${attempt}`} className="harbor-transition__canvas"
        ariaLabel={`${port === 'busan' ? '부산 북항' : '싱가포르 항만'} 3D 장면`}
        model={{ mode: 'playback', port }} loadRenderer={loadHarbor}
        onEvent={harborEvent} />
    </section>}
  </div>
}
