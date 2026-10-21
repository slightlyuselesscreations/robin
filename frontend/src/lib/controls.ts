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
  /** One of `keys` shows something other than the page's default. */
  differs: (keys: string[]) => boolean
  /** Make what the controls show now the page's default. */
  save: () => void
  saving: boolean
  /** Return every control to the page's default. */
  reset: () => void
}

/**
 * The display mode, type, order and filters of one page. Each reads from the address, then the
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
  const differs = (names: string[]) =>
    keys.some((key) => names.includes(key) && values[key] !== defaults[key])

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
    changed: differs(keys),
    differs,
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

/** The controls a grid sets in its header, beside `Options` rather than in it. */
export const HEADER_CONTROLS = ['type', 'order']

/**
 * What a grid is ordered by, named the same on every page. Each page offers the ones its source
 * can order by, in the header beside its Type.
 */
export const ORDERS = {
  popularity: { value: 'popularity', label: 'By popularity' },
  date: { value: 'date', label: 'By date' },
  publisher: { value: 'publisher', label: 'By publisher' },
  title: { value: 'title', label: 'By title' },
} as const

/** One of `offered` read from a control, its first when it is not one. */
export function pickOf<T extends string>(value: string, offered: readonly { value: T }[]): T {
  return offered.find((o) => o.value === value)?.value ?? offered[0].value
}

/**
 * A filter's pick while Settings still leaves it, else empty, which is all of it. Kept as it is
 * while the options are still on their way, so a page does not ask twice.
 */
export function narrowed(value: string, options: { value: string }[] | undefined): string {
  return !options || options.some((o) => o.value === value) ? value : ''
}
