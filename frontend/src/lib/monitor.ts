import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { type Comic, type MonitoredComic, type MonitoredGame, api, errorText } from '@/lib/api'

/*
 * What Monitor and Stop monitoring do in each category, the same from a dialog and from a
 * right click menu. `done` runs once either has gone through, a dialog closing itself.
 */

const failed = (what: string) => (error: unknown) =>
  toast.error(what, { description: errorText(error) })

/** A game: grabbed through Prowlarr once it is out, when Prowlarr is set. */
export function useGameMonitor(done?: () => void) {
  const queryClient = useQueryClient()
  // A game's state rides on every cached listing, so all of them are read again.
  const settled = () => {
    void queryClient.invalidateQueries()
    done?.()
  }
  const start = useMutation({
    mutationFn: (body: Parameters<typeof api.monitor>[0]) => api.monitor(body),
    onSuccess: (created) => {
      toast.success(`Monitoring ${created.game_name}`)
      settled()
    },
    onError: failed('Could not monitor'),
  })
  const stop = useMutation({
    mutationFn: (entry: MonitoredGame) => api.stopMonitoring(entry.id),
    onSuccess: (_, entry) => {
      toast.success(`Stopped monitoring ${entry.game_name}`)
      settled()
    },
    onError: failed('Could not stop monitoring'),
  })
  return { start, stop }
}

/** A comic series, monitored from its #1 and looked for on Suwayomi. */
export function useComicMonitor(done?: () => void) {
  const queryClient = useQueryClient()
  // The list is set at once, since reading it again waits on Metron for each series' next issue.
  const settled = (edit: (rows: MonitoredComic[]) => MonitoredComic[]) => {
    queryClient.setQueryData<MonitoredComic[]>(['comics-monitored'], (rows) => rows && edit(rows))
    void queryClient.invalidateQueries({ queryKey: ['comics-monitored'] })
  }
  const start = useMutation({
    mutationFn: ({ comic, week, suwayomi }: { comic: Comic; week: string; suwayomi?: boolean }) =>
      api.monitorComic(comic, week, suwayomi),
    onSuccess: (series) => {
      settled((rows) => [...rows.filter((row) => row.id !== series.id), series])
      toast.success(
        series.status !== 'monitored'
          ? `${series.series} is in your library`
          : series.suwayomi
            ? `Waiting for ${series.series} on Suwayomi`
            : `Monitoring ${series.series}`,
      )
    },
    onError: failed('Could not monitor'),
  })
  const stop = useMutation({
    mutationFn: (monitor: MonitoredComic) => api.stopMonitoringComic(monitor.id),
    onSuccess: (_, monitor) => {
      settled((rows) => rows.filter((row) => row.id !== monitor.id))
      toast.success(`Stopped monitoring ${monitor.series}`)
      done?.()
    },
    onError: failed('Could not stop monitoring'),
  })
  return { start, stop }
}

/** A series found on the Suwayomi source, added to its library. */
export function useAddSeries() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.addSeries(id),
    onSuccess: (added, id) => {
      queryClient.setQueryData(['series', id], added)
      void queryClient.invalidateQueries({ queryKey: ['comic-search'] })
      void queryClient.invalidateQueries({ queryKey: ['comic-latest'] })
      void queryClient.invalidateQueries({ queryKey: ['comics-monitored'] })
      toast.success(`${added.title} is in your library`)
    },
    onError: failed('Could not add it'),
  })
}

/** One issue by its id, as a list carries it, read for a dialog opened away from any list. */
export function useComic(id: string | null) {
  return useQuery({
    queryKey: ['comic-issue', id],
    queryFn: () => api.comic(id ?? ''),
    enabled: id !== null && /^\d+$/.test(id),
    staleTime: 60 * 60_000,
    retry: false,
  })
}
