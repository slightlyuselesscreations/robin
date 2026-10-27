import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { Eraser, Eye } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { BookMenu, ComicMenu, GameMenu, ScreenMenu } from '@/components/ItemMenus'
import { Items } from '@/components/MediaCard'
import {
  Group,
  Notice,
  Options,
  Page,
  PageHeader,
  Section,
  Sections,
  Segmented,
  StateIcon,
  ViewSwitch,
} from '@/components/Page'
import { Spinner } from '@/components/ui/spinner'
import {
  type BookReminder,
  COMIC_STATE,
  GAME_STATE,
  type Library,
  type MonitoredComic,
  type MonitoredGame,
  REMINDER_STATE,
  type Reminder,
  STATE_LABEL,
  type State,
  type View,
  api,
} from '@/lib/api'
import { useLibrary } from '@/lib/arr'
import { asView, usePageControls } from '@/lib/controls'
import {
  type Item,
  asComic,
  bookReminderItem,
  foundBookReminderItem,
  comicOpens,
  foundComicItem,
  foundGameItem,
  foundReminderItem,
  monitoredComicItem,
  monitoredGameItem,
  reminderItem,
} from '@/lib/items'
import { withParam } from '@/lib/params'
import { type CategoryKey, useTrackedCategories } from '@/lib/tracked'
import { cn, controlClass } from '@/lib/utils'

type Category = CategoryKey

type Entry = { state: State; item: Item }
type OpenAt = (key: string, id: string | number) => string
type InLibrary = (title: string) => Library | null

/** What the page does with one category's rows. Its query is the one `TRACKED` names. */
type PageOf = {
  metaLabel: string
  foundMetaLabel?: string
  clearFound: () => Promise<void>
  entries: (rows: unknown[], openAt: OpenAt, inLibrary: InLibrary) => Entry[]
}

/** A cleared row is hidden here only. The rest of the app still shows it as found. A row from a
 * favourite carries its star. */
function page<T extends { cleared_at: string | null; favourite: string | null }>(
  options: Omit<PageOf, 'entries'> & {
    entry: (row: T, openAt: OpenAt, inLibrary: InLibrary) => Entry
  },
): PageOf {
  const { entry, ...rest } = options
  return {
    ...rest,
    entries: (rows, openAt, inLibrary) =>
      (rows as T[])
        .filter((row) => !row.cleared_at)
        .map((row) => {
          const made = entry(row, openAt, inLibrary)
          return { ...made, item: { ...made.item, favourite: row.favourite } }
        }),
  }
}

const PAGE: Record<Category, PageOf> = {
  games: page<MonitoredGame>({
    metaLabel: 'Release',
    foundMetaLabel: 'Release',
    clearFound: api.clearFoundGames,
    entry: (row, openAt) => ({
      state: GAME_STATE[row.status],
      item: {
        ...(GAME_STATE[row.status] === 'found' ? foundGameItem : monitoredGameItem)(
          row,
          openAt('game', row.igdb_id),
        ),
        menu: <GameMenu igdbId={row.igdb_id} released={row.first_release_date} />,
      },
    }),
  }),
  comics: page<MonitoredComic>({
    metaLabel: 'Year',
    clearFound: api.clearFoundComics,
    entry: (row, openAt) => ({
      state: COMIC_STATE[row.status],
      item: {
        ...(row.status === 'added' ? foundComicItem : monitoredComicItem)(
          row,
          openAt(comicOpens(row).param, comicOpens(row).id),
        ),
        menu: <ComicMenu comic={asComic(row)} />,
      },
    }),
  }),
  screens: page<Reminder>({
    metaLabel: 'Release',
    foundMetaLabel: 'Release',
    clearFound: api.clearSentReminders,
    entry: (row, openAt, inLibrary) => ({
      state: REMINDER_STATE[row.status],
      item: {
        ...(row.status === 'sent' ? foundReminderItem : reminderItem)(
          row,
          openAt('title', `${row.kind}-${row.tmdb_id}`),
          inLibrary(`${row.kind}-${row.tmdb_id}`),
        ),
        menu: <ScreenMenu kind={row.kind} id={row.tmdb_id} />,
      },
    }),
  }),
  books: page<BookReminder>({
    metaLabel: 'Release',
    foundMetaLabel: 'Release',
    clearFound: api.clearSentBookReminders,
    entry: (row, openAt) => ({
      state: REMINDER_STATE[row.status],
      item: {
        ...(row.status === 'sent' ? foundBookReminderItem : bookReminderItem)(
          row,
          openAt('book', row.book_id),
        ),
        menu: <BookMenu id={row.book_id} />,
      },
    }),
  }),
}

export function Monitored() {
  const [params] = useSearchParams()
  // Every category shown, in the order the page shows it. The filter is `?type=`.
  const categories = useTrackedCategories().map((c) => ({ ...c, ...PAGE[c.key] }))
  // The same queries the overviews read, without their mapping to tracked rows.
  const lists = useQueries({
    queries: categories.map((c) => ({ queryKey: c.query.queryKey, queryFn: c.query.queryFn })),
  })
  const controls = usePageControls('monitored', { view: 'list', type: 'all' })
  const view = asView(controls.values.view, 'list')
  const only = categories.find((c) => c.key === controls.values.type)?.key ?? null
  const openAt = (key: string, id: string | number) => withParam(params, key, id)
  const inLibrary = useLibrary()

  const byState = Object.fromEntries(
    categories.map((c, i) => [
      c.key,
      c.entries((lists[i]?.data as unknown[]) ?? [], openAt, inLibrary),
    ]),
  ) as Record<Category, Entry[]>
  const counts = Object.fromEntries(
    categories.map((c) => [c.key, byState[c.key].length]),
  ) as Record<Category, number>
  const total = categories.reduce((sum, c) => sum + counts[c.key], 0)

  // Every category when unfiltered, but only those with something in them.
  const shown = categories.filter((c) => (only ? c.key === only : counts[c.key] > 0))
  const loading = lists.some((q) => q.isLoading)

  return (
    <Page>
      <PageHeader title="Monitored" icon={Eye}>
        <Segmented
          label="Category"
          options={[
            { value: 'all', label: 'All', count: total },
            ...categories.map((c) => ({
              value: c.key,
              label: c.label,
              icon: c.icon,
              count: counts[c.key],
            })),
          ]}
          value={only ?? 'all'}
          onChange={(type) => controls.set({ type })}
        />
        <Options controls={controls} header={['type']}>
          <ViewSwitch value={view} onChange={(next) => controls.set({ view: next })} />
        </Options>
      </PageHeader>

      {loading ? (
        <Spinner className="m-10 size-8 text-ink-dim" />
      ) : shown.length === 0 || (only && counts[only] === 0) ? (
        <Notice>Nothing monitored yet.</Notice>
      ) : (
        <div className="space-y-12">
          {shown.map((category) => (
            <Group
              key={category.key}
              title={category.label}
              icon={category.icon}
              count={counts[category.key]}
            >
              <StateSections
                rows={byState[category.key]}
                view={view}
                metaLabel={category.metaLabel}
                foundMetaLabel={category.foundMetaLabel}
                clearFound={category.clearFound}
              />
            </Group>
          ))}
        </div>
      )}
    </Page>
  )
}

/**
 * One panel per state, found first, in the order and words every category shares. Found items
 * are done with, so their panel is compact and can be cleared.
 */
function StateSections({
  rows,
  view,
  metaLabel,
  foundMetaLabel,
  clearFound,
}: {
  rows: { state: State; item: Item }[]
  view: View
  metaLabel: string
  foundMetaLabel?: string
  clearFound: () => Promise<void>
}) {
  return (
    <Sections>
      {(['found', 'tracking', 'waiting', 'error'] as const).map((state) => {
        const items = rows.filter((row) => row.state === state).map((row) => row.item)
        if (!items.length) return null
        const found = state === 'found'
        return (
          <Section
            key={state}
            title={
              <span className="flex items-center gap-1.5">
                <StateIcon state={state} />
                {STATE_LABEL[state]}
              </span>
            }
            count={items.length}
            action={found ? <ClearButton clear={clearFound} /> : null}
          >
            <Items
              items={items}
              view={view}
              metaLabel={found ? foundMetaLabel : metaLabel}
              compact={found}
            />
          </Section>
        )
      })}
    </Sections>
  )
}

/**
 * Takes the found items of one category off this page. They keep their status everywhere
 * else. The first click only arms it, and it
 * disarms itself if the second does not follow.
 */
function ClearButton({ clear }: { clear: () => Promise<void> }) {
  const queryClient = useQueryClient()
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) return
    const timer = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(timer)
  }, [armed])

  const run = useMutation({
    mutationFn: clear,
    onSuccess: () => {
      setArmed(false)
      void queryClient.invalidateQueries()
      toast.success('Notified cleared')
    },
    onError: () => toast.error('Could not clear them'),
  })

  return (
    <button
      type="button"
      onClick={() => (armed ? run.mutate() : setArmed(true))}
      disabled={run.isPending}
      className={cn(
        controlClass(),
        'h-6 px-2 text-2xs',
        armed && 'border-bad/50 text-bad hover:border-bad hover:text-bad',
      )}
    >
      {run.isPending ? <Spinner className="size-3" /> : <Eraser className="size-3" />}
      {armed ? 'Confirm' : 'Clear notified'}
    </button>
  )
}
