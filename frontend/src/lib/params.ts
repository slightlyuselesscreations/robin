import { useEffect, useRef, useSyncExternalStore } from 'react'
import { useLocation, useNavigate, useNavigationType, useSearchParams } from 'react-router-dom'

/**
 * The address of the page with one more search parameter, which opens an item's dialog over
 * it. Every other parameter is kept, so the page behind the dialog does not change.
 */
export function withParam(params: URLSearchParams, key: string, value: string | number): string {
  const next = new URLSearchParams(params)
  next.set(key, String(value))
  return `?${next}`
}

/**
 * A dialog's search parameter and closing it. Closing drops the parameter rather than going
 * back, so landing straight on a link and closing it does not leave the app.
 */
export function useDialogParam(key: string): [string | null, () => void] {
  const [params, setParams] = useSearchParams()
  const close = () => {
    const next = new URLSearchParams(params)
    next.delete(key)
    setParams(next, { replace: true })
  }
  return [params.get(key), close]
}

/** The search parameters that open a dialog over the page. */
const DIALOGS = ['game', 'title', 'book', 'comic', 'favourite', 'series']

/** Which dialog an address has open, or null with none. */
function opened(search: string): string | null {
  const params = new URLSearchParams(search)
  const key = DIALOGS.find((k) => params.has(k))
  return key ? `${key}=${params.get(key)}` : null
}

// The history entries a dialog was opened on from another dialog, by location key, so Back
// returns to the one before. Kept for the session, as history itself is.
const backable = new Set<string>()
const listeners = new Set<() => void>()
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Marks each dialog opened from another one. Mounted once, beside the dialogs. */
export function useDialogTrail() {
  const location = useLocation()
  const type = useNavigationType()
  const previous = useRef(location)
  useEffect(() => {
    const before = opened(previous.current.search)
    const now = opened(location.search)
    if (type === 'PUSH' && before && now && before !== now) {
      backable.add(location.key)
      for (const listener of listeners) listener()
    }
    previous.current = location
  }, [location, type])
}

/** Going back to the dialog this one was opened from, or null when it was opened from a page. */
export function useDialogBack(): (() => void) | null {
  const { key } = useLocation()
  const navigate = useNavigate()
  const can = useSyncExternalStore(subscribe, () => backable.has(key))
  return can ? () => void navigate(-1) : null
}
