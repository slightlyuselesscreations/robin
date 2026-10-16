import { useState } from 'react'

/** The style that places an element `i` steps into a `.rise` wave, `step` milliseconds each. */
export const riseAt = (i: number, step?: number): React.CSSProperties =>
  ({ '--i': i, ...(step ? { '--step': `${step}ms` } : {}) }) as React.CSSProperties

const NONE = Symbol('none')

/**
 * The `pop` class once `value` changed after the user acted, `busy` the action's pending flag,
 * and a key that replays it. A value that changes as data loads, unasked, never pops.
 */
export function usePop(value: unknown, busy: boolean): { key: string; className?: string } {
  const [seen, setSeen] = useState<{ busy: boolean; from: unknown }>({ busy, from: NONE })
  if (seen.busy !== busy) setSeen({ busy, from: busy ? value : seen.from })
  const popping = seen.from !== NONE && seen.from !== value
  return { key: String(value), className: popping ? 'pop' : undefined }
}
