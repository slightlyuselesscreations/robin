import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** The first of this month at local midnight. Nothing dated before it is shown but in search. */
export function monthStart(): Date {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), 1)
}

/**
 * Whether something came out before the first of this month: a YYYY-MM-DD day, or a release
 * timestamp in seconds read as its UTC day. Search finds it, to favourite who made it, and
 * nothing offers to monitor it. Undated never is.
 */
export function outBeforeMonth(when: string | number | null): boolean {
  if (when === null) return false
  if (typeof when === 'string') return new Date(`${when.slice(0, 10)}T00:00:00`) < monthStart()
  const utc = new Date(when * 1000)
  return new Date(utc.getUTCFullYear(), utc.getUTCMonth(), utc.getUTCDate()) < monthStart()
}

/**
 * Whether a game can be monitored: coming, or out and on PC with Prowlarr set, to be grabbed
 * once a clean release is listed.
 */
export function gameMonitorable(
  released: number | null,
  platforms: string[],
  prowlarrReady: boolean,
): boolean {
  return !outBeforeMonth(released) || (prowlarrReady && platforms.includes('PC'))
}

/** Whether a day, YYYY-MM-DD, is today or ahead. Undated never is. */
export function ahead(day: string | null): boolean {
  return day !== null && day.slice(0, 10) >= isoDay(new Date())
}

/** A local calendar day as YYYY-MM-DD. */
/** A YYYY-MM-DD as the local calendar day it names. */
export function localDay(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function isoDay(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const INPUT = 'border-line bg-base'

/**
 * Every control in a page header, and any small action that looks like one: one height, one
 * type size. Active carries the accent.
 */
export function controlClass(active = false) {
  return cn(
    'inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs transition-colors disabled:pointer-events-none disabled:opacity-40',
    active
      ? 'border-accent/60 bg-accent/12 text-accent'
      : 'border-line bg-surface text-ink-dim hover:border-line-strong hover:text-ink',
  )
}
