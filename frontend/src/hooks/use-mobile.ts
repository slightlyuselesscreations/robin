import * as React from 'react'

const MOBILE_BREAKPOINT = 768
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

function subscribe(onChange: () => void) {
  const mql = window.matchMedia(QUERY)
  mql.addEventListener('change', onChange)
  return () => mql.removeEventListener('change', onChange)
}

/** Whether the window is phone width, kept current as it is resized. */
export function useIsMobile() {
  return React.useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches)
}
