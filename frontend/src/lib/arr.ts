import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { LIBRARY_NAME, type Library, type ScreenKind, api, errorText } from '@/lib/api'
import { useSettings } from '@/lib/categories'

/** The colour a title in that library is drawn in, written out whole for Tailwind to find. */
export const LIBRARY_CLASS: Record<Library, string> = {
  radarr: 'text-radarr',
  sonarr: 'text-sonarr',
}

export const appFor = (kind: ScreenKind): Library => (kind === 'movie' ? 'radarr' : 'sonarr')

/** Whether Radarr, or Sonarr, is set. */
export function useArrReady(): Record<Library, boolean> {
  const s = useSettings().data
  return { radarr: Boolean(s?.radarr_ready), sonarr: Boolean(s?.sonarr_ready) }
}

/** The library holding a title, by its dialog address `movie-<id>` or `tv-<id>`. */
export function useLibrary(): (title: string) => Library | null {
  const ready = useArrReady()
  const held = useQuery({
    queryKey: ['arr-library'],
    queryFn: api.arrLibrary,
    enabled: ready.radarr || ready.sonarr,
  })
  return (title) => held.data?.[title] ?? null
}

/** The library holding a title, by the `?title=movie-<id>` a row opens. */
export const libraryOf = (inLibrary: (title: string) => Library | null, to: string) =>
  inLibrary(to.replace(/^\??title=/, ''))

/** A title Radarr or Sonarr holds, as removing it from there names it. */
export type Held = { kind: ScreenKind; id: number; title: string; library: Library }

/** Fired to ask whether to remove titles from Radarr or Sonarr too. The detail is `Held[]`. */
export const ARR_REMOVE = 'robin:arr-remove'

/** Ask, through `ArrRemoveDialog`, whether to remove these from Radarr or Sonarr as well. */
export function askArrRemove(titles: Held[]) {
  if (titles.length) window.dispatchEvent(new CustomEvent(ARR_REMOVE, { detail: titles }))
}

/** The titles of `listed` a library holds, for `askArrRemove`. */
export function heldOf(
  inLibrary: (title: string) => Library | null,
  listed: { kind: ScreenKind; id: number; title: string }[],
): Held[] {
  return listed.flatMap((t) => {
    const library = inLibrary(`${t.kind}-${t.id}`)
    return library ? [{ ...t, library }] : []
  })
}

/** Removing titles from the library holding each, their files on disk too with `deleteFiles`. */
export function useArrRemove() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ titles, deleteFiles }: { titles: Held[]; deleteFiles: boolean }) => {
      const done = await Promise.allSettled(
        titles.map((t) => api.arrRemove(t.kind, t.id, deleteFiles)),
      )
      const failed = done.filter((d) => d.status === 'rejected')
      if (failed.length) throw (failed[0] as PromiseRejectedResult).reason
      return titles
    },
    onSuccess: (titles) =>
      toast.success(
        titles.length === 1 ? `Removed ${titles[0].title}` : `Removed ${titles.length}`,
      ),
    onError: (error: unknown) => toast.error('Could not remove', { description: errorText(error) }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['arr-library'] })
      void queryClient.invalidateQueries({ queryKey: ['arr-calendar'] })
    },
  })
}

/**
 * Adding a film to Radarr or a show to Sonarr. `offered` while that app is set and its library
 * does not hold the title yet.
 */
export function useArrAdd(kind: ScreenKind, id: number) {
  const queryClient = useQueryClient()
  const app = appFor(kind)
  const ready = useArrReady()[app]
  const inLibrary = useLibrary()
  const add = useMutation({
    mutationFn: () => api.arrAdd(app, id),
    onSuccess: () => toast.success(`Added to ${LIBRARY_NAME[app]}`),
    onError: (error: unknown) =>
      toast.error(`Could not add to ${LIBRARY_NAME[app]}`, { description: errorText(error) }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['arr-library'] })
      void queryClient.invalidateQueries({ queryKey: ['arr-calendar'] })
    },
  })
  return {
    offered: ready && inLibrary(`${kind}-${id}`) === null,
    label: `Add to ${LIBRARY_NAME[app]}`,
    library: inLibrary(`${kind}-${id}`),
    add,
  }
}
