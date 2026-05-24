// frontend/src/hooks/useIsMobile.ts
import { useEffect, useState } from 'react'

/**
 * Tracks whether the viewport is below a mobile breakpoint.
 *
 * Defaults to 768px (Tailwind's `md`) so the JS state stays in lockstep
 * with our responsive utility classes. Reads the initial value
 * synchronously from `matchMedia` so the first render already has the
 * correct value (no flash of desktop layout on mobile, no extra repaint).
 */
export default function useIsMobile(breakpoint = 768): boolean {
  const query = `(max-width: ${breakpoint - 1}px)`

  const [isMobile, setIsMobile] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false
    }
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return
    }
    const mq = window.matchMedia(query)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    // Modern browsers: addEventListener; legacy Safari: addListener
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', handler)
      return () => mq.removeEventListener('change', handler)
    } else {
      // Legacy Safari (<14) API. Cast to any to avoid TS complaining
      // about the deprecated overload not being on MediaQueryList.
      const legacy = mq as unknown as {
        addListener: (cb: (e: MediaQueryListEvent) => void) => void
        removeListener: (cb: (e: MediaQueryListEvent) => void) => void
      }
      legacy.addListener(handler)
      return () => legacy.removeListener(handler)
    }
  }, [query])

  return isMobile
}
