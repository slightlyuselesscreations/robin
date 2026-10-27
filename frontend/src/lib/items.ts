import type { ReactNode } from 'react'

import {
  type Book,
  type BookReminder,
  COMIC_STATE,
  type Comic,
  type CountdownTarget,
  type Entity,
  type Favourite,
  GAME_PLATFORMS,
  GAME_STATE,
  type Game,
  type MonitorStatus,
  type MonitoredComic,
  type MonitoredGame,
  type Platform,
  REMINDER_STATE,
  type Reminder,
  type ScreenKind,
  type ScreenTitle,
  type Library,
  type Series,
  type State,
  posterUrl,
  releaseLabel,
} from '@/lib/api'
import { isoDay } from '@/lib/utils'

export type Status = {
  state: State
  /** Lines shown under the word when the glyph is hovered. */
  detail?: (string | null | undefined | false)[]
}

/** Artwork shape per category: a game poster is 3:4, a comic cover 2:3. */
export type Shape = 'poster' | 'cover'

/**
 * One item of any category, as every view reads it. A category writes an adapter that maps
 * its rows onto this, and the views never learn what a game or a comic is.
 */
export type Item = {
  key: string
  to: string
  image: string | null
  shape: Shape
  title: string
  /** The line under the title: a release date, the writers. */
  meta?: string | null
  /** The kind of release the date is for, set right of it: the one or two platforms a game is
   * only on and EA for one in Early Access, Cinema or Digital for a film. Series for a
   * book in one. A #1's publisher. */
  tag?: string | null
  /** What hovering the tag says, where the tag alone does not say it all. */
  tagTip?: string | null
  /** The platform a digital release or a show is on, named in place of the tag. */
  platform?: PlatformTag | null
  status?: Status | null
  /** Already handed off. The artwork fades back so what is still open leads. */
  settled?: boolean
  /** The favourite it comes from, by name, starred after the title. */
  favourite?: string | null
  /** The Radarr or Sonarr library holding it, its title in that app's colour. */
  library: Library | null
  /** What counting down to it needs, its date null while it has none. Null for what has no
   *  release of its own, a favourite or a series on a source. */
  countdown: CountdownTarget | null
  /** What a right click offers beyond opening it, as context menu items. */
  menu?: ReactNode
  /** A control at the far end of a compact row, apart from the link that opens it. */
  action?: ReactNode
  /** Rows in the list view and columns in the table. A null value is left out of a row. */
  fields?: { label: string; value: string | null; mono?: boolean; tone?: 'good' | 'bad' }[]
}

/** A moment as its local day, YYYY-MM-DD, the one form a date takes when it is not written out. */
export const day = (iso: string | null) => (iso ? isoDay(new Date(iso)) : null)

/** EA for a game in Early Access. */
export const gameTag = (status: string | null) => (status === 'Early Access' ? 'EA' : null)

/** Each platform family as a game's tag names it. */
const PLATFORM_TAGS: Record<string, string> = {
  pc: 'PC',
  playstation: 'PS',
  xbox: 'X',
  nintendo: 'N',
}

/** The platforms a game is only on, when two or fewer, then EA for one in Early Access. */
function gameTags(game: Pick<Game, 'exclusive' | 'release_status'>): string | null {
  const only = GAME_PLATFORMS.filter((p) => game.exclusive?.includes(p.value)).map(
    (p) => PLATFORM_TAGS[p.value],
  )
  return [...only, gameTag(game.release_status)].filter(Boolean).join(' · ') || null
}

/** `gameTags` for a row of the monitored list, which carries its platforms as JSON. */
export const monitoredGameTags = (entry: MonitoredGame): string | null =>
  gameTags({
    exclusive: JSON.parse(entry.exclusive_json) as string[],
    release_status: entry.release_status,
  })

/**
 * Where a grabbed game's download is, in qBittorrent's words made plain. Null until grabbed,
 * and once it is downloaded, when the release grabbed says enough.
 */
export function downloadStage(entry: MonitoredGame): string | null {
  if (entry.status !== 'matched' || entry.downloaded_at) return null
  const download = entry.download
  if (!download) return 'Sent to the download client'
  const done = `${Math.floor(download.progress * 100)}%`
  if (download.progress >= 1) return 'Downloaded'
  if (download.state === 'error' || download.state === 'missingFiles')
    return 'Failed in qBittorrent'
  if (/^(stopped|paused)DL$/.test(download.state)) return `Paused at ${done}`
  if (download.state === 'stalledDL') return `Stalled at ${done}`
  if (download.state === 'downloading' || download.state === 'forcedDL')
    return `Downloading ${done}`
  return 'Queued in qBittorrent'
}

/** What is known about a monitored game, for the glyph's hover. */
export function gameStatus(status: MonitorStatus, entry?: MonitoredGame | null): Status {
  const state = GAME_STATE[status]
  if (!entry) return { state }
  if (state === 'found' || state === 'tracking') {
    return {
      state,
      detail: [
        entry.matched_release,
        downloadStage(entry),
        entry.review_release && `Confirm ${entry.review_release}`,
        entry.error,
        `Notified ${day(entry.matched_at ?? entry.notified_at)}`,
      ],
    }
  }
  return {
    state,
    detail: [
      entry.review_release && `Confirm ${entry.review_release}`,
      entry.error,
      `Monitored ${day(entry.created_at)}`,
    ],
  }
}

export function comicStatus(entry: MonitoredComic): Status {
  const state = COMIC_STATE[entry.status]
  return state === 'waiting'
    ? { state, detail: [entry.suwayomi ? 'Not on the source yet, looked for hourly' : null] }
    : {
        state,
        detail: [
          entry.added_at
            ? `In the Suwayomi library since ${day(entry.added_at)}`
            : 'In the Suwayomi library',
          entry.issues === 0 && 'Added before its first issue was out',
        ],
      }
}

/**
 * Where a monitored series opens: the issue it was monitored from, or its series on Suwayomi
 * for one taken in from the library.
 */
export function comicOpens(entry: MonitoredComic): { param: 'comic' | 'series'; id: string } {
  return entry.issue_id.startsWith('suwayomi-') && entry.suwayomi_id !== null
    ? { param: 'series', id: String(entry.suwayomi_id) }
    : { param: 'comic', id: entry.issue_id }
}

/** A countdown to a game, dated by the UTC day IGDB names for its release. */
export function gameCountdown(
  igdbId: number,
  title: string,
  cover: string | null,
  released: number | null,
): CountdownTarget {
  const date = released ? new Date(released * 1000).toISOString().slice(0, 10) : null
  return { category: 'games', target: `game=${igdbId}`, title, image: posterUrl(cover), date }
}

/** A game as IGDB lists it. `monitor` adds what Robin knows about it to the glyph. */
export function gameItem(game: Game, to: string, monitor?: MonitoredGame | null): Item {
  const status = game.request_status
  return {
    key: String(game.igdb_id),
    to,
    image: posterUrl(game.cover_image_id),
    shape: 'poster',
    library: null,
    title: game.name,
    meta: releaseLabel(game.first_release_date, game.release_label),
    tag: gameTags(game),
    status: status ? gameStatus(status, monitor) : null,
    settled: Boolean(status),
    favourite: game.favourite ?? null,
    countdown: gameCountdown(game.igdb_id, game.name, game.cover_image_id, game.first_release_date),
    fields: [
      { label: 'Genres', value: game.genres?.join(', ') || null },
      { label: 'Platforms', value: game.platforms?.join(', ') || null },
    ],
  }
}

/** A row of the monitored list. Nothing fades there, every item on it is monitored. */
export function monitoredGameItem(entry: MonitoredGame, to: string): Item {
  return {
    key: `game:${entry.id}`,
    to,
    image: posterUrl(entry.cover_image_id),
    shape: 'poster',
    library: null,
    title: entry.game_name,
    meta: releaseLabel(entry.first_release_date, entry.release_label),
    tag: monitoredGameTags(entry),
    status: gameStatus(entry.status, entry),
    countdown: gameCountdown(
      entry.igdb_id,
      entry.game_name,
      entry.cover_image_id,
      entry.first_release_date,
    ),
    fields: [
      { label: 'Release', value: entry.matched_release, mono: true, tone: 'good' },
      { label: 'Download', value: downloadStage(entry) },
      { label: 'Confirm', value: entry.review_release, mono: true },
      { label: 'Error', value: entry.error, tone: 'bad' },
      { label: 'Since', value: day(entry.matched_at || entry.created_at) },
    ],
  }
}

/** A game in the Notified panel: the release Robin grabbed, and where its download is. */
export function foundGameItem(entry: MonitoredGame, to: string): Item {
  return {
    key: `game:${entry.id}`,
    to,
    image: posterUrl(entry.cover_image_id),
    shape: 'poster',
    library: null,
    title: entry.game_name,
    meta: entry.matched_release,
    status: gameStatus(entry.status, entry),
    countdown: gameCountdown(
      entry.igdb_id,
      entry.game_name,
      entry.cover_image_id,
      entry.first_release_date,
    ),
    fields: [
      { label: 'Download', value: downloadStage(entry) },
      { label: 'Notified', value: day(entry.matched_at ?? entry.notified_at) },
    ],
  }
}

/** The #1 a series was monitored from, as the Comics page lists it. */
export function asComic(entry: MonitoredComic): Comic {
  return {
    id: entry.issue_id,
    title: entry.title,
    url: entry.url,
    publisher: entry.publisher,
    publisher_id: null,
    series_id: entry.series_id,
    number: null,
    date: null,
    cover: entry.cover,
    series_url: null,
    detail: null,
  }
}

/** A comic in the Notified panel says only which series it is. */
export function foundComicItem(entry: MonitoredComic, to: string): Item {
  return {
    key: `comic:${entry.id}`,
    to,
    image: comicCover(entry.cover),
    shape: 'cover',
    library: null,
    title: entry.series,
    status: comicStatus(entry),
    countdown: {
      category: 'comics',
      target: `comic=${entry.issue_id}`,
      title: entry.series,
      image: entry.cover,
      date: null,
    },
    fields: [],
  }
}

/** A series as the Suwayomi source lists it. */
export function seriesItem(series: Series, to: string): Item {
  return {
    key: `series:${series.id}`,
    to,
    image: series.thumbnailUrl,
    shape: 'cover',
    library: null,
    title: series.title,
    // A series whose source has its first issue alone, as a Metron #1 is tagged.
    tag: series.issues === 1 ? '#1' : null,
    status: series.inLibrary ? { state: 'found', detail: ['In the Suwayomi library'] } : null,
    settled: series.inLibrary,
    countdown: null,
    fields: [],
  }
}

/**
 * The first issue of a series #1, ahead so a long publisher is cut rather than it. "DC Comics"
 * is DC, "Boom! Studios" BOOM!.
 */
export function comicTag(comic: { number?: string | null; publisher: string }): string | null {
  return (
    [comic.number === '1' ? '#1' : null, comic.publisher.split(' ')[0]]
      .filter(Boolean)
      .join(' · ') || null
  )
}

/** A #1 as the week lists it. `monitor` is its series, when that is monitored. */
export function comicItem(
  comic: Comic,
  to: string,
  monitor?: MonitoredComic | null,
  week?: string,
): Item {
  const creators = comic.detail?.creators
  const out = comic.date ?? week ?? null
  return {
    key: comic.id,
    to,
    image: comicCover(comic.cover),
    shape: 'cover',
    library: null,
    title: comic.title,
    favourite: comic.favourite ?? null,
    meta: calendarDay(out) ?? 'No date',
    tag: comicTag(comic),
    tagTip: comic.publisher || null,
    status: monitor ? comicStatus(monitor) : null,
    settled: Boolean(monitor),
    countdown: {
      category: 'comics',
      target: `comic=${comic.id}`,
      title: comic.title,
      image: comic.cover,
      tag: comicTag(comic),
      date: out,
    },
    fields: [
      { label: 'Writer', value: creators?.Writer?.join(', ') || null },
      { label: 'Artist', value: creators?.Artist?.join(', ') || null },
    ],
  }
}

export function monitoredComicItem(entry: MonitoredComic, to: string): Item {
  return {
    key: `comic:${entry.id}`,
    to,
    image: comicCover(entry.cover),
    shape: 'cover',
    library: null,
    title: entry.series,
    meta: String(entry.year),
    status: comicStatus(entry),
    countdown: {
      category: 'comics',
      target: `comic=${entry.issue_id}`,
      title: entry.series,
      image: entry.cover,
      date: null,
    },
    fields: [
      { label: 'From', value: entry.title },
      { label: 'Publisher', value: entry.publisher || null },
      { label: 'Since', value: day(entry.added_at || entry.created_at) },
    ],
  }
}

/** LOCG's cover at the size a card draws, for a series monitored from LOCG. Metron has one size. */
export function comicCover(cover: string | null): string | null {
  return cover?.replace('/large-', '/medium-') ?? null
}

/** Whether a comic is on Metron, where it opens, and not monitored from LOCG. */
export function fromMetron(comic: { url: string }): boolean {
  return comic.url.startsWith('https://metron.cloud/')
}

/** Whether a comic is an issue Metron has, whose details can be read, and not only its series. */
export function metronIssue(comic: { url: string }): boolean {
  return comic.url.startsWith('https://metron.cloud/issue/')
}

/** "30 Oct 2026" from a YYYY-MM-DD, read as a calendar day rather than a UTC instant. */
export function calendarDay(iso: string | null): string | null {
  if (!iso) return null
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * A movie or show as TMDB lists it. `genres` names the ids TMDB gives, `reminders` are the
 * ones set on this title, which give it its state the way a monitored game has one.
 */
export function screenItem(
  title: ScreenTitle,
  to: string,
  genres: Map<number, string>,
  reminders: Reminder[],
  library: Library | null,
): Item {
  const next = title.next_episode
  // A reminder still waiting outranks one already sent, as a film can have one of each.
  const lead = reminders.find((r) => r.status === 'waiting') ?? reminders[0]
  return {
    key: `${title.kind}:${title.id}`,
    to,
    image: title.poster,
    shape: 'cover',
    library,
    title: title.title,
    meta: next
      ? `S${next.season} E${next.episode} · ${calendarDay(next.date)}`
      : (calendarDay(title.date) ?? 'No date'),
    tag: title.release,
    platform: platformTag(title.platform, title.date, title.kind),
    status: lead
      ? {
          state: REMINDER_STATE[lead.status],
          detail: reminders.map((r) =>
            r.kind === 'tv'
              ? 'Reminder for each season premiere'
              : `${REMINDER_TAGS[r.release_type]} reminder ${r.status === 'sent' ? 'sent' : 'set'}`,
          ),
        }
      : null,
    settled: lead !== undefined,
    favourite: title.favourite ?? null,
    countdown: {
      category: 'screens',
      target: `title=${title.kind}-${title.id}`,
      title: title.title,
      image: title.poster,
      date: title.next_episode?.date ?? title.date,
    },
    fields: [
      {
        label: 'Genres',
        value:
          title.genre_ids
            .map((id) => genres.get(id))
            .filter(Boolean)
            .join(', ') || null,
      },
    ],
  }
}

const REMINDER_TAGS: Record<string, string> = {
  theatrical: 'Cinema',
  digital: 'Digital',
}

/** A platform as a release tag shows it, with what its tooltip says. */
export type PlatformTag = Platform & { detail: string | null }

/**
 * A film's digital release, or the network a show airs on. A network is only its name, the
 * date beside it already says when.
 */
export function platformTag(
  platform: Platform | null,
  date: string | null,
  kind: ScreenKind,
): PlatformTag | null {
  if (!platform) return null
  if (kind === 'tv') return { ...platform, detail: null }
  const when = calendarDay(date)
  return { ...platform, detail: when ? `Digital release on ${when}` : 'Digital release' }
}

/** What a reminder is for where there is no room for its platform: Cinema, Digital or Series. */
export const reminderKindTag = (entry: Reminder): string | null =>
  entry.kind === 'tv' ? 'Series' : (REMINDER_TAGS[entry.release_type] ?? null)

/** A film reminder's release type, or the platform it is on. A show's names its network. */
export function reminderTag(entry: Reminder): Required<Pick<Item, 'tag' | 'platform'>> {
  return {
    tag: REMINDER_TAGS[entry.release_type] ?? null,
    platform: platformTag(entry.platform ? { name: entry.platform } : null, entry.date, entry.kind),
  }
}

export function reminderStatus(entry: Reminder): Status {
  return noticeStatus(entry, entry.kind === 'tv' ? 'Each season premiere' : null)
}

/**
 * A notice's state: when it was sent, or for one that keeps following, what it follows and
 * when it last sent. Screens and Books share it.
 */
function noticeStatus(
  entry: Pick<Reminder, 'status' | 'sent_at'>,
  following: string | null,
): Status {
  const state = REMINDER_STATE[entry.status]
  return state === 'found'
    ? { state, detail: [`Sent ${day(entry.sent_at)}`] }
    : {
        state,
        detail: [following, following && entry.sent_at ? `Last sent ${day(entry.sent_at)}` : null],
      }
}

/** A Remind me on Monitored, dated by the release it is for. */
export function reminderItem(entry: Reminder, to: string, library: Library | null): Item {
  return {
    key: `reminder:${entry.id}`,
    to,
    image: entry.poster,
    shape: 'cover',
    library,
    title: entry.title,
    meta: calendarDay(entry.date) ?? 'No date',
    ...reminderTag(entry),
    status: reminderStatus(entry),
    countdown: {
      category: 'screens',
      target: `title=${entry.kind}-${entry.tmdb_id}`,
      title: entry.title,
      image: entry.poster,
      date: entry.date,
    },
    fields: [
      { label: 'Kind', value: entry.kind === 'movie' ? 'Movie' : 'Show' },
      { label: 'Since', value: day(entry.created_at) },
    ],
  }
}

/** A reminder in the Notified panel says which release it was for. */
export function foundReminderItem(entry: Reminder, to: string, library: Library | null): Item {
  return {
    key: `reminder:${entry.id}`,
    to,
    image: entry.poster,
    shape: 'cover',
    library,
    title: entry.title,
    meta: calendarDay(entry.date),
    ...reminderTag(entry),
    status: reminderStatus(entry),
    countdown: {
      category: 'screens',
      target: `title=${entry.kind}-${entry.tmdb_id}`,
      title: entry.title,
      image: entry.poster,
      date: entry.date,
    },
    fields: [],
  }
}

/** The reminder that gives a book its state. */
export function bookRemindersOf(book: Pick<Book, 'id'>, reminders: BookReminder[]): BookReminder[] {
  return reminders.filter((r) => r.hardcover_id === book.id)
}

/** "Harry Potter 1/7", the series and where the book stands in it. */
export function seriesLabel(series: Book['series']): string | null {
  if (!series) return null
  if (series.position === null) return series.name
  return `${series.name} ${series.position}${series.count ? `/${series.count}` : ''}`
}

/** A book as Hardcover lists it. `reminders` are the ones set on it. */
export function bookItem(book: Book, to: string, reminders: BookReminder[] = []): Item {
  const lead = reminders.find((r) => r.status === 'waiting') ?? reminders[0]
  return {
    key: `book:${book.id}`,
    to,
    image: book.cover,
    shape: 'cover',
    library: null,
    title: book.title,
    meta: calendarDay(book.date) ?? 'No date',
    tag: book.series ? 'Series' : null,
    tagTip: seriesLabel(book.series),
    platform: null,
    status: lead
      ? {
          state: REMINDER_STATE[lead.status],
          detail: [`Reminder ${lead.status === 'sent' ? 'sent' : 'set'}`],
        }
      : null,
    settled: lead !== undefined,
    favourite: book.favourite ?? null,
    countdown: {
      category: 'books',
      target: `book=${book.id}`,
      title: book.title,
      image: book.cover,
      date: book.date,
    },
    fields: [
      { label: 'Author', value: book.authors.join(', ') || null },
      { label: 'Series', value: seriesLabel(book.series) },
    ],
  }
}

export function bookReminderStatus(entry: BookReminder): Status {
  return noticeStatus(entry, null)
}

/** A Monitor on Monitored, dated by the release it is for. */
export function bookReminderItem(entry: BookReminder, to: string): Item {
  return {
    key: `book-reminder:${entry.id}`,
    to,
    image: entry.cover,
    shape: 'cover',
    library: null,
    title: entry.title,
    meta: calendarDay(entry.date) ?? 'No date',
    tag: null,
    platform: null,
    status: bookReminderStatus(entry),
    countdown: {
      category: 'books',
      target: `book=${entry.book_id}`,
      title: entry.title,
      image: entry.cover,
      date: entry.date,
    },
    fields: [{ label: 'Since', value: day(entry.created_at) }],
  }
}

/** A book reminder in the Notified panel. */
export function foundBookReminderItem(entry: BookReminder, to: string): Item {
  return {
    key: `book-reminder:${entry.id}`,
    to,
    image: entry.cover,
    shape: 'cover',
    library: null,
    title: entry.title,
    meta: calendarDay(entry.date),
    tag: null,
    platform: null,
    status: bookReminderStatus(entry),
    countdown: {
      category: 'books',
      target: `book=${entry.book_id}`,
      title: entry.title,
      image: entry.cover,
      date: entry.date,
    },
    fields: [],
  }
}

/** Something releases come from, as a search finds it. `starred` draws its star. */
export function entityItem(entity: Entity, to: string, starred: boolean): Item {
  return {
    key: `${entity.category}:${entity.kind}:${entity.id}`,
    to,
    image: entity.image,
    shape: 'cover',
    library: null,
    title: entity.name,
    meta: entity.meta,
    tag: null,
    platform: null,
    favourite: starred ? entity.name : null,
    countdown: null,
    fields: [],
  }
}

/** A favourite as Monitored lists it. */
export function favouriteItem(favourite: Favourite, to: string): Item {
  return {
    key: `favourite:${favourite.id}`,
    to,
    image: favourite.image,
    shape: 'cover',
    library: null,
    title: favourite.name,
    meta: [
      `Since ${day(favourite.created_at)}`,
      favourite.monitored ? `${favourite.monitored} monitored` : null,
    ]
      .filter(Boolean)
      .join(' · '),
    tag: null,
    platform: null,
    favourite: favourite.name,
    countdown: null,
    fields: [],
  }
}

/** The monitored series an issue is of, by its series, or by the issue for a row from LOCG. */
export function comicMonitorOf(
  rows: MonitoredComic[] | undefined,
  comic: Pick<Comic, 'id' | 'series_id'>,
): MonitoredComic | null {
  return (
    rows?.find(
      (m) =>
        m.issue_id === comic.id || (comic.series_id !== null && m.series_id === comic.series_id),
    ) ?? null
  )
}
