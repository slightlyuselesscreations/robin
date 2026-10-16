import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { type Settings, type View, api } from '@/lib/api'
import { useSettings } from '@/lib/categories'

/** A page's controls by name, each value as the address writes it. */
export type Controls = Record<string, string>

export type PageControls<T extends Controls> = {
  /** What each control shows now. */
  values: T
  /**
   * Change controls, and any other search parameter, `null` dropping it. A control set to its
   * default is dropped too, so the address only names what differs.
   */
  set: (changes: Partial<Record<keyof T, string | null>> & Record<string, string | null>) => void
  /** A control shows something other than the page's default. */
  changed: boolean
  /** Make what the controls show now the page's default. */
  save: () => void
  saving: boolean
  /** Return every control to the page's default. */
  reset: () => void
}

/**
 * The display mode, kind and filters of one page. Each reads from the address, then the
 * defaults saved for the page in `page_defaults`, then `builtin`, so back and forward step
 * through what was looked at and a bare link opens the page as it was saved.
 */
export function usePageControls<T extends Controls>(page: string, builtin: T): PageControls<T> {
  const [params, setParams] = useSearchParams()
  const queryClient = useQueryClient()
  const settings = useSettings()
  const keys = Object.keys(builtin) as (keyof T & string)[]
  const saved = settings.data?.page_defaults[page] ?? {}
  const defaults = Object.fromEntries(keys.map((key) => [key, saved[key] ?? builtin[key]])) as T
  const values = Object.fromEntries(keys.map((key) => [key, params.get(key) ?? defaults[key]])) as T
  const changed = keys.some((key) => values[key] !== defaults[key])

  const write = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '' || (key in defaults && defaults[key] === value))
        next.delete(key)
      else next.set(key, value)
    }
    setParams(next)
  }

  const store = useMutation({
    mutationFn: (pageDefaults: Settings['page_defaults']) =>
      api.saveSettings({ page_defaults: pageDefaults }),
    onSuccess: (next) => {
      queryClient.setQueryData(['settings'], next)
      // Every control now matches the saved default, so the address names none of them.
      write(Object.fromEntries(keys.map((key) => [key, null])))
      toast.success('Saved as the default')
    },
    onError: () => toast.error('Could not save the default'),
  })

  return {
    values,
    set: (changes) => write(changes as Record<string, string | null>),
    changed,
    save: () => {
      // Only what differs from the page's own default is kept, so a later change to it applies.
      const own = Object.fromEntries(
        keys.filter((k) => values[k] !== builtin[k]).map((k) => [k, values[k]]),
      )
      const all = { ...settings.data?.page_defaults }
      if (Object.keys(own).length) all[page] = own
      else delete all[page]
      store.mutate(all)
    },
    saving: store.isPending,
    reset: () => write(Object.fromEntries(keys.map((key) => [key, null]))),
  }
}

const VIEWS: readonly View[] = ['list', 'cover', 'table']

/** A display mode read from a control, its fallback when it is not one. */
export function asView(value: string, fallback: View): View {
  return VIEWS.find((view) => view === value) ?? fallback
}

/** How far ahead a page of upcoming items looks. */
export const WINDOWS = [
  { value: '30', label: '30 days' },
  { value: '90', label: '3 months' },
  { value: '180', label: '6 months' },
  { value: '365', label: 'A year' },
]

/** A window as days, anything no longer offered taking `fallback`. */
export function windowDays(value: string, fallback: string): number {
  return Number(WINDOWS.find((w) => w.value === value)?.value ?? fallback)
}

// What Settings keeps and every value, as a picker names them. Radix Select reserves the empty
// string, so neither can be it.
export const KEPT = 'kept'
export const ANY = 'any'
