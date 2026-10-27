import { type UseQueryOptions, useQueries, useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'

import {
  type BookReminder,
  type Library,
  type Origin,
  COMIC_STATE,
  type Category as CategoryKey,
  GAME_STATE,
  type MonitoredComic,
  type MonitoredGame,
  REMINDER_STATE,
  type Reminder,
  type State,
  api,
  posterUrl,
  releaseLabel,
} from '@/lib/api'
import { CATEGORY, useShown } from '@/lib/categories'
import { libraryOf, useArrReady, useLibrary } from '@/lib/arr'
import {
  type Shape,
  calendarDay,
  comicCover,
  comicOpens,
  comicTag,
  monitoredGameTags,
  oneUndated,
  reminderKindTag,
} from '@/lib/items'
import { localDay, monthStart } from '@/lib/utils'

/**
 * One thing Robin watches, in any category, as every overview reads it. Home's panels read
 * only this, so a category listed in `TRACKED` shows up in all of them. Every field is
 * required: a category without one sets it null rather than leaving it out.
 */
export type Tracked = {
  key: string
  category: CategoryKey
  /** Null for a favourite's release nobody monitors. */
  state: State | null
  /** The favourite it comes from, by name. Null where none is. */
  favourite: string | null
  /** Why Robin monitors it. Null for your own Monitor, and for what nobody monitors. */
  origin: Origin | null
  /** The Radarr or Sonarr library holding it. Null where none does. */
  library: Library | null
  title: string
  image: string | null
  shape: Shape
  /** What kind of release it is, shown beside its category: the platforms a game is only on,
   * Cinema, Digital or Series, a comic's publisher. Null where it has none. */
  tag: string | null
  /** Its dialog, as a search parameter, so it opens over the page that lists it. */
  to: string
  /** The day it comes out, at local midnight. Null while undated. */
  release: Date | null
  /** That day as a list shows it. */
  releaseText: string | null
  /** When it was notified, set once its state is tracking or found. */
  foundAt: string | null
  /** When it was monitored. Null for a favourite's release. */
  createdAt: string | null
}

/** Something monitored, with its state and the day it was monitored. */
export type Watched = Tracked & { state: State; createdAt: string }

export type { CategoryKey }

type Category = {
  key: CategoryKey
  label: string
  icon: LucideIcon
  /** Monitored, filtered to this category. */
  to: string
  /** Shares its key with the category's own monitored query, so nothing is fetched twice. */
  query: UseQueryOptions<unknown, Error, Watched[]>
}

/** A monitored list read as tracked rows. `select` only ever sees what `queryFn` returned. */
function query<T>(
  queryKey: string[],
  queryFn: () => Promise<T[]>,
  track: (row: T) => Watched,
  merge: (rows: T[]) => T[] = (rows) => rows,
): Category['query'] {
  return { queryKey, queryFn, select: (rows) => merge(rows as T[]).map(track) }
}

/** A release timestamp as the calendar day it names, which IGDB states in UTC. */
function utcDay(timestamp: number): Date {
  const utc = new Date(timestamp * 1000)
  return new Date(utc.getUTCFullYear(), utc.getUTCMonth(), utc.getUTCDate())
}

function game(g: MonitoredGame): Watched {
  const state = GAME_STATE[g.status]
  return {
    key: `game:${g.id}`,
    category: 'games',
    state,
    favourite: g.favourite,
    origin: g.origin,
    library: null,
    title: g.game_name,
    image: posterUrl(g.cover_image_id),
    shape: 'poster',
    tag: monitoredGameTags(g),
    to: `?game=${g.igdb_id}`,
    release: g.first_release_date ? utcDay(g.first_release_date) : null,
    releaseText: releaseLabel(g.first_release_date, g.release_label),
    foundAt: state === 'found' || state === 'tracking' ? (g.matched_at ?? g.notified_at) : null,
    createdAt: g.created_at,
  }
}

/**
 * A series is dated by its next issue, while Metron dates one, and opens on it. One Suwayomi
 * tracks is announced issue by issue as Suwayomi lists them, so it is undated and opens where
 * it was monitored from.
 */
function comic(c: MonitoredComic): Watched {
  const state = COMIC_STATE[c.status]
  const opens = comicOpens(c)
  return {
    key: `comic:${c.id}`,
    category: 'comics',
    state,
    favourite: c.favourite,
    origin: c.origin,
    library: null,
    title: c.series,
    image: comicCover(c.cover),
    shape: 'cover',
    tag: comicTag(c),
    to: state === 'tracking' ? `?${opens.param}=${opens.id}` : `?comic=${c.next?.id ?? c.issue_id}`,
    release: state !== 'tracking' && c.next?.date ? localDay(c.next.date) : null,
    releaseText: null,
    foundAt: state === 'found' || state === 'tracking' ? c.added_at : null,
    createdAt: c.created_at,
  }
}

/** A notice set ahead of a date, dated by what it waits for. Screens and Books share it. */
function notice(
  category: 'screens' | 'books',
  r: Pick<
    Reminder,
    'id' | 'status' | 'title' | 'date' | 'sent_at' | 'created_at' | 'origin' | 'favourite'
  >,
  image: string | null,
  tag: string | null,
  to: string,
): Watched {
  const state = REMINDER_STATE[r.status]
  return {
    key: `${category}:${r.id}`,
    category,
    state,
    favourite: r.favourite,
    origin: r.origin,
    library: null,
    title: r.title,
    image,
    shape: 'cover',
    tag,
    to,
    release: r.date ? localDay(r.date) : null,
    releaseText: calendarDay(r.date),
    foundAt: state === 'found' ? r.sent_at : null,
    createdAt: r.created_at,
  }
}

/** A film's reminder is dated by the release it is for, a show's by its next premiere. */
const reminder = (r: Reminder) =>
  notice('screens', r, r.poster, reminderKindTag(r), `?title=${r.kind}-${r.tmdb_id}`)

/** A book's reminder is dated by its release. It does not know whether the book is in a series. */
const bookReminder = (r: BookReminder) => notice('books', r, r.cover, null, `?book=${r.book_id}`)

function tracked(key: CategoryKey, query: Category['query']): Category {
  const { label, icon } = CATEGORY[key]
  return { key, label, icon, to: `/monitored?type=${key}`, query }
}

/** Every category Robin watches, in the order overviews show them. */
export const TRACKED: Category[] = [
  tracked('games', query(['monitored'], api.monitored, game)),
  tracked('comics', query(['comics-monitored'], api.monitoredComics, comic)),
  tracked('screens', query(['screen-reminders'], api.reminders, reminder, oneUndated)),
  tracked('books', query(['book-reminders'], api.bookReminders, bookReminder)),
]

/** The categories shown, the only ones any overview lists. */
export function useTrackedCategories(): Category[] {
  const shown = useShown()
  return TRACKED.filter((c) => shown(c.key))
}

/**
 * Undated, out from the first of this month on, or still tracked. Nothing else older reaches an
 * overview.
 */
const current = (t: Tracked) => t.state === 'tracking' || !t.release || t.release >= monthStart()

/**
 * Everything monitored across every category shown, out this month or later or still tracked.
 * The app already polls the lists behind it.
 */
export function useTracked(): Watched[] {
  const inLibrary = useLibrary()
  const watched = useQueries({
    queries: useTrackedCategories().map((c) => c.query),
    combine: (results) => results.flatMap((r) => (r.data as Watched[] | undefined) ?? []),
  })
  return watched
    .filter(current)
    .map((w) => (w.category === 'screens' ? { ...w, library: libraryOf(inLibrary, w.to) } : w))
}

/** Whether what `useTracked` reads, and with `upcoming` what `useUpcoming` reads, is still on its
 * way, so a panel does not read as empty before it is. */
export function useOverviewLoading(upcoming = false): boolean {
  const arr = useArrReady()
  const tracked = useQueries({
    queries: useTrackedCategories().map((c) => c.query),
    combine: (results) => results.some((r) => r.isLoading),
  })
  const coming = useQuery({
    queryKey: ['favourites-coming'],
    queryFn: api.favouritesComing,
    enabled: upcoming,
  })
  const calendar = useQuery({
    queryKey: ['arr-calendar'],
    queryFn: api.arrCalendar,
    enabled: upcoming && (arr.radarr || arr.sonarr),
  })
  return tracked || coming.isLoading || calendar.isLoading
}

/**
 * Everything monitored, then every dated release from a favourite, each title once, then what
 * Radarr and Sonarr have dated. A release already monitored keeps its own row, named with the
 * favourite it comes from.
 */
export function useUpcoming(): Tracked[] {
  const watched = useTracked()
  const shown = useShown()
  const inLibrary = useLibrary()
  const arr = useArrReady()
  const coming = useQuery({ queryKey: ['favourites-coming'], queryFn: api.favouritesComing })
  const calendar = useQuery({
    queryKey: ['arr-calendar'],
    queryFn: api.arrCalendar,
    enabled: arr.radarr || arr.sonarr,
  })
  const releases = (coming.data ?? []).filter((r) => shown(r.category))
  const from = new Map(releases.map((r) => [`?${r.to}`, r.favourite]))
  const monitored = new Set(watched.map((w) => w.to))
  const listed = new Set([...monitored, ...releases.map((r) => `?${r.to}`)])
  const dated = (calendar.data ?? []).filter((r) => shown(r.category) && !listed.has(`?${r.to}`))
  const upcoming: Tracked[] = [
    ...watched.map((w) => ({ ...w, favourite: w.favourite ?? from.get(w.to) ?? null })),
    ...releases
      .filter((r) => !monitored.has(`?${r.to}`))
      .map((r): Tracked => ({
        key: `favourite:${r.category}:${r.key}`,
        category: r.category,
        state: null,
        favourite: r.favourite,
        origin: null,
        library: r.category === 'screens' ? libraryOf(inLibrary, r.to) : null,
        title: r.title,
        image: r.image,
        shape: r.category === 'games' ? 'poster' : 'cover',
        tag: r.tag,
        to: `?${r.to}`,
        release: localDay(r.date),
        releaseText: calendarDay(r.date),
        foundAt: null,
        createdAt: null,
      })),
    ...dated.map((r): Tracked => ({
      key: `arr:${r.key}`,
      category: r.category,
      state: null,
      favourite: null,
      origin: null,
      library: r.library,
      title: r.title,
      image: r.image,
      shape: 'cover',
      tag: r.tag,
      to: `?${r.to}`,
      release: localDay(r.date),
      releaseText: calendarDay(r.date),
      foundAt: null,
      createdAt: null,
    })),
  ]
  return upcoming.filter(current)
}
