import { useEffect, useRef, useState } from 'react'

/** 지도 엔진과 제품 화면 사이의 공통 생명주기 계약이다. */
export type MapModeInput =
  | { readonly mode: 'fleet' }
  | { readonly mode: 'comparison' }
  | { readonly mode: 'playback' }

export type MapRendererEvent =
  | { readonly type: 'ready' }
  | { readonly type: 'error'; readonly error: Error }
  | { readonly type: 'selection'; readonly id: string | null }

export interface MapRenderer<Model extends MapModeInput> {
  mount(
    target: HTMLElement,
    model: Model,
    emit: (event: MapRendererEvent) => void,
  ): MapRendererSession<Model>
}

export interface MapRendererSession<Model extends MapModeInput> {
  update(model: Model): void
  destroy(): void
}

interface MapRendererHostProps<Model extends MapModeInput> {
  readonly className?: string
  readonly ariaLabel: string
  readonly ariaDescribedBy?: string
  readonly model: Model
  readonly renderer?: MapRenderer<Model>
  readonly loadRenderer?: () => Promise<MapRenderer<Model>>
  readonly onEvent?: (event: MapRendererEvent) => void
}

/** React의 수명 주기를 지도 엔진의 mount/update/destroy로 연결한다. */
export function MapRendererHost<Model extends MapModeInput>({
  className,
  ariaLabel,
  ariaDescribedBy,
  model,
  renderer,
  loadRenderer,
  onEvent,
}: MapRendererHostProps<Model>) {
  const [target, setTarget] = useState<HTMLDivElement | null>(null)
  const latestModel = useRef(model)
  const latestOnEvent = useRef(onEvent)
  const session = useRef<MapRendererSession<Model> | null>(null)

  useEffect(() => {
    latestModel.current = model
  }, [model])

  useEffect(() => {
    latestOnEvent.current = onEvent
  }, [onEvent])

  useEffect(() => {
    if (target === null) return
    let disposed = false
    const emit = (event: MapRendererEvent) => {
      if (!disposed) latestOnEvent.current?.(event)
    }
    const mount = (loaded: MapRenderer<Model>) => {
      if (disposed) return
      try {
        session.current = loaded.mount(target, latestModel.current, emit)
      } catch (error) {
        emit({ type: 'error', error: error instanceof Error ? error : new Error(String(error)) })
      }
    }
    if (renderer) mount(renderer)
    else if (loadRenderer) void loadRenderer().then(mount, (error: unknown) => {
      emit({ type: 'error', error: error instanceof Error ? error : new Error(String(error)) })
    })
    else throw new Error('지도 renderer 또는 loader가 필요합니다.')
    return () => {
      disposed = true
      session.current?.destroy()
      session.current = null
    }
  }, [loadRenderer, renderer, target])

  useEffect(() => {
    session.current?.update(model)
  }, [model])

  return <div className={className} ref={setTarget} role="img" aria-label={ariaLabel} aria-describedby={ariaDescribedBy} />
}
