import { useEffect, useState } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

/** OS 설정의 초기값과 실행 중 변경을 모두 반영한다. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => globalThis.matchMedia?.(QUERY).matches ?? false)
  useEffect(() => {
    const query = globalThis.matchMedia?.(QUERY)
    if (!query) return
    const change = () => setReduced(query.matches)
    change()
    query.addEventListener?.('change', change)
    return () => query.removeEventListener?.('change', change)
  }, [])
  return reduced
}
