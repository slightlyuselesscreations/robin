import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  type ReleaseType,
  type Reminder,
  type ScreenDetail,
  type ScreenKind,
  type Settings,
  api,
  errorText,
} from '@/lib/api'
import { askArrRemove, heldOf, useLibrary } from '@/lib/arr'
import { useSettings } from '@/lib/categories'
import { calendarDay } from '@/lib/items'
import { outBeforeMonth } from '@/lib/utils'

/** What a film's reminder can be for: one release type, or both. */
export type ReminderChoice = ReleaseType | 'both'

const CHOICE_LABEL: Record<ReminderChoice, string> = {
  theatrical: 'Cinema only',
  digital: 'Digital only',
  both: 'Cinema and digital',
}

/**
 * The choices a film offers, each with the release types it sets. One the region has no date
 * for is offered disabled, and both needs both.
 */
/**
 * Whether a title has something ahead to monitor: a film a release dated in the region, a show
 * a season premiere dated or a first episode from this month on.
 */
export function screenMonitorable(title: ScreenDetail): boolean {
  if (title.kind === 'movie') return title.releases.length > 0
  if (title.next_episode) return title.next_episode.episode === 1
  return !outBeforeMonth(title.date)
}

export function reminderChoices(
  releases: ScreenDetail['releases'],
): { value: ReminderChoice; label: string; types: ReleaseType[]; disabled: boolean }[] {
  const dated = new Map(releases.map((r) => [r.type, r]))
  const one = (type: ReleaseType) => {
    const release = dated.get(type)
    const where = release?.platform ? `${release.platform.name}, ` : ''
    return {
      value: type,
      label: release
        ? `${CHOICE_LABEL[type]} · ${where}${calendarDay(release.date)}`
        : CHOICE_LABEL[type],
      types: [type],
      disabled: !release,
    }
  }
  return [
    one('theatrical'),
    one('digital'),
    {
      value: 'both',
      label: CHOICE_LABEL.both,
      types: ['theatrical', 'digital'],
      disabled: !(dated.has('theatrical') && dated.has('digital')),
    },
  ]
}

/** The release types a pick sets. Picking the choice already checked removes it. */
export function typesFor(
  choices: ReturnType<typeof reminderChoices>,
  current: ReminderChoice | null,
  value: string,
): ReleaseType[] {
  if (value === current) return []
  return choices.find((c) => c.value === value)?.types ?? []
}

/** The choice the reminders already set make, or null with none. */
export function currentChoice(mine: Reminder[]): ReminderChoice | null {
  const types = new Set(mine.map((r) => r.release_type))
  if (types.has('theatrical') && types.has('digital')) return 'both'
  if (types.has('theatrical')) return 'theatrical'
  if (types.has('digital')) return 'digital'
  return null
}

/**
 * The notices one item has set, and changing them, for every category whose Monitor is a
 * notice. `ready` is false while the category's notifications are off, and nothing offers
 * Monitor then. `apply` leaves exactly what was picked set and says whether anything is.
 */
export function useNoticeSet<Row, Pick>({
  ready: isReady,
  queryKey,
  list,
  of,
  apply,
  also = [],
  stopped,
}: {
  ready: (settings: Settings) => boolean
  queryKey: string
  list: () => Promise<Row[]>
  of: (rows: Row[]) => Row[]
  apply: (mine: Row[], pick: Pick) => Promise<boolean>
  /** Other queries a change can move, as Monitor adding a title to Radarr or Sonarr. */
  also?: string[]
  /** Run once nothing is set any more, with the rows that were. */
  stopped?: (mine: Row[]) => void
}) {
  const queryClient = useQueryClient()
  const settings = useSettings()
  const ready = settings.data ? isReady(settings.data) : false
  const rows = useQuery({ queryKey: [queryKey], queryFn: list, enabled: ready })
  const mine = of(rows.data ?? [])
  const choose = useMutation({
    mutationFn: (pick: Pick) => apply(mine, pick),
    onSuccess: (set) => {
      toast.success(set ? 'Monitoring' : 'Stopped monitoring')
      if (!set) stopped?.(mine)
    },
    onError: (error: unknown) =>
      toast.error('Could not change the reminder', {
        description: errorText(error),
      }),
    onSettled: () => {
      for (const key of [queryKey, ...also]) void queryClient.invalidateQueries({ queryKey: [key] })
    },
  })
  return { ready, mine, choose }
}

/**
 * The reminders set on one movie or show. `choose` leaves exactly these release types
 * reminded: a show takes `[undefined]`, its one reminder, and `[]` removes everything.
 */
export function useReminders(kind: ScreenKind, id: number) {
  const inLibrary = useLibrary()
  return useNoticeSet<Reminder, (ReleaseType | undefined)[]>({
    ready: (s) => s.screen_notices_ready,
    queryKey: 'screen-reminders',
    also: ['arr-library', 'arr-calendar'],
    list: api.reminders,
    of: (rows) => rows.filter((r) => r.kind === kind && r.tmdb_id === id),
    // Radarr or Sonarr holding it is asked about, never followed without a word.
    stopped: ([was]) =>
      askArrRemove(was ? heldOf(inLibrary, [{ kind, id, title: was.title }]) : []),
    apply: async (mine, types) => {
      const wanted = new Set(types.map((t) => t ?? ''))
      for (const reminder of mine) {
        if (!wanted.has(reminder.release_type)) await api.removeReminder(reminder.id)
      }
      const have = new Set(mine.map((r) => r.release_type as string))
      for (const type of types) {
        if (!have.has(type ?? '')) await api.remind({ kind, tmdb_id: id, release_type: type })
      }
      return types.length > 0
    },
  })
}
