import { useEffect } from 'react'

import type { Item } from '@/lib/items'

/** How long after Reload an item drawn new or changed is marked. The fresh data is already on
 * the server by then, so the lists come back well inside it. */
const WINDOW = 4000

/** How long an item glows, the `updated` animation in index.css. */
const GLOW = 6000

/** What each item on screen was last drawn with, by key. */
const drawn = new Map<string, string>()
/** Until when each item found new or changed glows, so a redraw does not cut it short. */
const glowing = new Map<string, number>()
let before: Map<string, string> | null = null
let until = 0

const signature = (item: Item) =>
  [item.title, item.meta, item.tag, item.platform?.name, item.image].join('\u0000')

/** Remember what is on screen, so what Reload brings in can be told apart from it. */
export function markReload() {
  before = new Map(drawn)
  glowing.clear()
  until = Date.now() + WINDOW
}

function changed(key: string, drawnAs: string): boolean {
  const now = Date.now()
  if (before !== null && now < until && before.get(key) !== drawnAs && !glowing.has(key)) {
    glowing.set(key, now + GLOW)
  }
  const end = glowing.get(key)
  if (end !== undefined && now >= end) glowing.delete(key)
  return end !== undefined && now < end
}

/** The class that rings an item new or changed since Reload, once. */
export function useUpdated(item: Item): string | undefined {
  const drawnAs = signature(item)
  const ring = changed(item.key, drawnAs)
  useEffect(() => {
    drawn.set(item.key, drawnAs)
    return () => {
      drawn.delete(item.key)
    }
  }, [item.key, drawnAs])
  return ring ? 'updated' : undefined
}
