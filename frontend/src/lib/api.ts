import type { QueryClient } from '@tanstack/react-query'

/** A game's status as the API reports it. `tracking` is a notified game still searched for. */
export type MonitorStatus = 'monitored' | 'notified' | 'tracking' | 'matched'

/** The kinds of thing Robin tracks, each with its own page, settings tab and notices. */
export type Category = 'games' | 'comics' | 'screens' | 'books'

/** What Robin is doing with an item, the same words in every category. */
export type State = 'waiting' | 'tracking' | 'found' | 'error'

export const STATE_LABEL: Record<State, string> = {
  waiting: 'Waiting',
  tracking: 'Tracking',
  found: 'Notified',
  error: 'Error',
}

/** How a game's stored status reads as a state. */
export const GAME_STATE: Record<MonitorStatus, State> = {
  monitored: 'waiting',
  notified: 'found',
  tracking: 'tracking',
  matched: 'found',
}

/** How a comic series' stored status reads as a state. */
export const COMIC_STATE: Record<'monitored' | 'added', State> = {
  monitored: 'waiting',
  added: 'found',
}

/** How a Screens or a Books reminder's stored status reads as a state. */
export const REMINDER_STATE: Record<'waiting' | 'sent', State> = {
  waiting: 'waiting',
  sent: 'found',
}

export type Game = {
  igdb_id: number
  name: string
  slug: string | null
  summary: string | null
  first_release_date: number | null
  release_label: string | null
  release_status: string | null
  cover_image_id: string | null
  artwork_image_id: string | null
  platforms: string[]
  /** The platform families it is only on, `GAME_PLATFORMS` values, when two or fewer. */
  exclusive: string[]
  genres: string[]
  rating: number | null
  /** IGDB rating volume plus anticipation. Settles two games that share a name. */
  popularity: number
  url: string | null
  extra?: GameExtra
  request_status: MonitorStatus | null
  /** The favourite company that made or publishes it, by name. */
  favourite?: string | null
}

/** A grab as qBittorrent has it. `state` is qBittorrent's own, progress 0 to 1. */
export type Download = { state: string; progress: number; eta: number }

export type MonitoredGame = {
  id: number
  igdb_id: number
  game_name: string
  status: MonitorStatus
  /** The release grabbed, once ever, and when. */
  matched_release: string | null
  matched_at: string | null
  /** When the last notice of the games schedule went out. A grab may still follow. */
  notified_at: string | null
  /** The grab in qBittorrent now, on the monitored list only. Null when it holds none. */
  download?: Download | null
  /** When qBittorrent had the grab complete. */
  downloaded_at: string | null
  /** A matched release PreDB could not vouch for, waiting for the user to confirm or reject. */
  review_release: string | null
  /** Why the last grab failed, while the game still waits. */
  error: string | null
  /** Cleared from the Notified panel on Monitored. Everywhere else it still reads as found. */
  cleared_at: string | null
  created_at: string
  cover_image_id: string | null
  first_release_date: number | null
  release_label: string | null
  release_status: string | null
  /** The platform families it is only on, as JSON. */
  exclusive_json: string
}

export type Theme =
  | 'european'
  | 'american'
  | 'pink'
  | 'siberian'
  | 'rufous'
  | 'flame'
  | 'red-capped'
  | 'white-throated'
  | 'black'
/** Dark, light, or whichever the system is set to. */
export type Scheme = 'dark' | 'light' | 'system'

export type Settings = {
  twitch_client_id: string
  has_twitch_client_secret: boolean
  prowlarr_url: string
  has_prowlarr_api_key: boolean
  /** Which Prowlarr indexers are searched, monitored games included. Empty means all of them. */
  prowlarr_indexer_ids: number[]
  /** Release groups outside the scene, grabbed without asking PreDB. */
  p2p_groups: string[]
  /** Home panels in order. Empty means the default layout. */
  home_layout: HomePanel[]
  /** What each page's controls start at, by page and then control. Missing takes the page's own. */
  page_defaults: Record<string, Record<string, string>>
  /** The robin Robin is coloured as. */
  theme: Theme
  scheme: Scheme
  /** Where monitored comic series are looked for. */
  suwayomi_url: string
  suwayomi_source_id: string
  /** Where matched games download. The username is empty when qBittorrent needs no sign in. */
  qbittorrent_url: string
  has_qbittorrent_api_key: boolean
  /** The category Home lists downloads from, and every grab is filed under. */
  qbittorrent_category: string
  /** Whether a monitored game grabs only a release its tracker marks freeleech. */
  freeleech_only: boolean
  has_tmdb_token: boolean
  /** Decides release dates and streaming services, a two letter country code. */
  tmdb_region: string
  /** What titles and overviews are written in, such as en-US. */
  tmdb_language: string
  /**
   * What Screens hides, everywhere Robin suggests a title. A title carrying a hidden genre or
   * language is left out unless it carries a genre of its kind always shown.
   */
  tmdb_hidden_languages: string[]
  tmdb_hidden_movie_genres: number[]
  tmdb_hidden_tv_genres: number[]
  tmdb_hidden_release_types: ReleaseType[]
  tmdb_shown_movie_genres: number[]
  tmdb_shown_tv_genres: number[]
  tmdb_ready: boolean
  screen_notices_ready: boolean
  /** Where a film or show is added. A profile of 0 and an empty root are the app's first. */
  radarr_url: string
  has_radarr_api_key: boolean
  radarr_profile_id: number
  radarr_root: string
  /** Whether monitoring a film adds it. */
  radarr_add: boolean
  sonarr_url: string
  has_sonarr_api_key: boolean
  sonarr_profile_id: number
  sonarr_root: string
  sonarr_add: boolean
  has_hardcover_token: boolean
  has_metron_token: boolean
  /** What Books hides: literary types, categories and genre slugs, then genres always shown. */
  books_hidden_literary_types: number[]
  books_hidden_categories: number[]
  books_hidden_genres: string[]
  books_shown_genres: string[]
  hardcover_ready: boolean
  books_notices_ready: boolean
  /** The `GAME_PLATFORMS` families hidden: a game on none other is left out. */
  games_hidden_platforms: string[]
  /** When each category's dated notices go, the day before first and always there. */
  games_schedule: Notice[]
  comics_schedule: Notice[]
  screen_schedule: Notice[]
  books_schedule: Notice[]
  /** The Metron publishers the weekly #1s digest names, every one while empty. */
  comics_digest_publishers: { id: number; name: string }[]
  /** Quiet hours, [start, end] in server local hours, empty for none. */
  games_quiet: number[]
  comics_quiet: number[]
  screen_quiet: number[]
  books_quiet: number[]
  /** Where notifications go. Secrets come back blank, named in `saved`. */
  notify_destinations: Destination[]
  /** Whether each category sends notifications. */
  games_notify: boolean
  comics_notify: boolean
  screen_notify: boolean
  books_notify: boolean
  /** Whether a favourite's new releases are announced. */
  games_favourites: boolean
  screen_favourites: boolean
  books_favourites: boolean
  comics_favourites: boolean
  /** Whether a favourite's new releases are monitored on their own. */
  games_favourites_monitor: boolean
  screen_favourites_monitor: boolean
  books_favourites_monitor: boolean
  comics_favourites_monitor: boolean
  igdb_ready: boolean
  comics_ready: boolean
  prowlarr_ready: boolean
  qbittorrent_ready: boolean
  radarr_ready: boolean
  sonarr_ready: boolean
  suwayomi_ready: boolean
  notify_ready: boolean
  has_backup_passphrase: boolean
  backups: boolean
  backup_hour: number
  backup_keep: number
  backups_ready: boolean
}

/** A notification destination: a service from `NotifyService`, its values by field, and the
 * place a category sends to where it differs from its own. */
export type Destination = {
  id: string
  service: string
  values: Record<string, string>
  /** The secrets kept, each sent back blank. */
  saved: string[]
  places: Partial<Record<Category, string>>
  /** The categories whose place is a secret kept. */
  saved_places: Category[]
}

export type NotifyField = {
  key: string
  label: string
  example: string
  secret: boolean
  optional: boolean
}

/** A service the picker offers. `place` is the field a category can change. */
export type NotifyService = {
  key: string
  label: string
  fields: NotifyField[]
  place: string | null
}

/** One notice of a schedule: this many days before the date, at this server local hour. */
export type Notice = { days: number; hour: number }

/** One indexer result, as Prowlarr lists it, without what carries Prowlarr's key. */
export type Release = {
  guid: string
  indexer_id: number
  indexer: string
  title: string
  size: number
  seeders: number
  leechers: number
  /** Whole days. */
  age: number
  info_url: string | null
  /** Indexer flags, lower cased: freeleech, halfleech, internal, scene. */
  flags: string[]
}

export type DiscoverPage = {
  games: Game[]
  next_offset: number | null
}

/** A series on the configured Suwayomi source. Details arrive once it is opened. */
export type Series = {
  id: number
  title: string
  inLibrary: boolean
  thumbnailUrl: string | null
  /** The series in Suwayomi itself. */
  url: string
  description?: string | null
  author?: string | null
  artist?: string | null
  genre?: string[]
  status?: string | null
  /** How many issues the source has to download, once the series is read in full. */
  issues?: number | null
}

/** An issue as Metron lists it. */
export type Comic = {
  id: string
  title: string
  url: string
  publisher: string
  /** Metron's ids for its publisher and its series, null for a series monitored from LOCG.
   * The publisher is null too until Robin has read it. */
  publisher_id: number | null
  series_id: number | null
  /** Its number in the series, as Metron writes it, null for a series monitored from LOCG. */
  number: string | null
  /** Its store date, a Wednesday. */
  date: string | null
  cover: string | null
  /** Its series on Metron. */
  series_url: string | null
  /** The issue page, present once Robin has read it. */
  detail: ComicDetail | null
  /** The favourite it comes from: its series, publisher, or a writer or artist. */
  favourite?: string | null
}

/** Every issue of the current week, of every publisher. */
export type ComicIssues = {
  week: string
  /** Null for the week the first of this month falls in, the earliest listed. */
  previous: string | null
  next: string
  issues: Comic[]
}

/** What an issue on Metron says beyond the listing. */
export type ComicDetail = {
  /** The issue's own title, where it has one. */
  name: string | null
  synopsis: string
  cover_date: string | null
  /** Names by role, in the order Metron lists them. */
  creators: Record<string, string[]>
  /** The same with the id each opens as a favourite by. */
  people: Record<string, Ref[]>
  /** Its publisher, which a list names only once Robin has read it. */
  publisher: Ref | null
  /** Its series' name. */
  series: string | null
  story_arcs: string[]
  characters: string[]
  teams: string[]
  /** Characters who first appear in it. */
  first_appearances: string[]
  variants: number
}

/** A series monitored from its #1, waiting for the Suwayomi source or already in the library. */
export type MonitoredComic = {
  id: number
  /** The issue it was monitored from, a Metron id, or a LOCG one for older rows. */
  issue_id: string
  /** Its series on Metron, null for one monitored from LOCG. */
  series_id: number | null
  /** Its next issue from today, while Metron dates one. */
  next: { id: string; title: string; date: string | null } | null
  title: string
  series: string
  year: number
  publisher: string
  url: string
  cover: string | null
  status: 'monitored' | 'added'
  suwayomi_id: number | null
  /** Issues on the source when the series was added. Zero means none was out yet. */
  issues: number | null
  added_at: string | null
  /** Cleared from the Notified panel on Monitored. Everywhere else it still reads as found. */
  cleared_at: string | null
  created_at: string
}

export type ReleaseType = 'theatrical' | 'digital'

/** The service a digital release is on. */
export type Platform = { name: string }

/** A Remind me on a film's release of one type, or on a show's season premieres. */
export type Reminder = {
  id: number
  kind: ScreenKind
  tmdb_id: number
  /** Empty for a show. */
  release_type: ReleaseType | ''
  title: string
  poster: string | null
  /** YYYY-MM-DD, as last read: the film's release of its type, a show's next episode. */
  date: string | null
  /** The platform a digital release is on, as last read. */
  platform: string | null
  /** A film's is sent once. A show's stays waiting for its next premiere. */
  status: 'waiting' | 'sent'
  notified_for: string | null
  sent_at: string | null
  cleared_at: string | null
  created_at: string
}

/** A book's place in its series. */
export type BookSeries = {
  id: number
  name: string
  position: number | null
  /** Books in the series, companions left out. */
  count: number | null
}

/** One upcoming book as Hardcover lists it. */
export type Book = {
  id: number
  title: string
  subtitle: string
  /** YYYY-MM-DD, its first publication anywhere. */
  date: string | null
  cover: string | null
  overview: string
  authors: string[]
  genres: string[]
  series: BookSeries | null
  pages: number | null
  rating: number | null
  /** Hardcover users who shelved it. */
  readers: number
  hardcover: string
  /** The favourite author or series it comes from, by name. */
  favourite?: string | null
}

/** A book's detail names its authors with their ids, to open each as a favourite. */
export type BookDetail = Book & { headline: string; author_refs: Ref[] }

export type BookPage = { books: Book[]; page: number; more: boolean }

/** Monitor on a book: a notice ahead of its release. A series is followed by favouriting it. */
export type BookReminder = {
  id: number
  kind: 'book'
  hardcover_id: number
  /** The book, which the dialog opens. */
  book_id: number
  title: string
  cover: string | null
  /** YYYY-MM-DD, as last read. */
  date: string | null
  /** Sent once. */
  status: 'waiting' | 'sent'
  notified_for: string | null
  sent_at: string | null
  cleared_at: string | null
  created_at: string
}

/** Each narrows what Settings leaves, empty for all of it. */
export type BookFilters = {
  kind: '' | 'fiction' | 'nonfiction'
  /** One genre slug. */
  genre: string
  /** Most anticipated first, or soonest first. */
  sort: 'popularity' | 'date'
}

/** Each narrows what Settings leaves, empty for all of it. */
export type GameFilters = {
  type: 'upcoming' | 'out'
  platform: string
  /** One genre, by name. */
  genre: string
  /** Soonest first, or most anticipated first. */
  sort: 'date' | 'popularity'
}

export type GameExtra = {
  storyline?: string | null
  developers?: Ref[]
  publishers?: Ref[]
  themes?: string[]
  game_modes?: string[]
  player_perspectives?: string[]
  engines?: string[]
  franchises?: Ref[]
  /** Its series, which IGDB calls collections. */
  collections?: Ref[]
  critic_rating?: number | null
  critic_rating_count?: number | null
  rating_count?: number | null
  screenshots?: string[]
  trailer?: { name: string; url: string } | null
}

export type NamedThing = {
  id: number
  name: string
  identifier?: string
  type?: string
  enabled?: boolean
}
/**
 * One Home panel as saved. `beside` puts it in the row of the panel before it, `size` is its
 * share of that row's width in percent. Either is null when the default applies.
 */
export type HomePanel = {
  id: string
  hidden: boolean
  beside?: boolean | null
  size?: number | null
}

export type Check = { ok: boolean; detail: string }

/** One service, asked directly. `error` says why when it is faulty. */
export type ServiceHealth = {
  state: 'healthy' | 'faulty' | 'unset'
  error: string
  /** When a data source Robin paused is asked again, while it is paused. */
  until: string | null
}

export type Health = {
  igdb: ServiceHealth
  tmdb: ServiceHealth
  hardcover: ServiceHealth
  metron: ServiceHealth
  prowlarr: ServiceHealth
  predb: ServiceHealth
  suwayomi: ServiceHealth
  qbittorrent: ServiceHealth
  radarr: ServiceHealth
  sonarr: ServiceHealth
  notify: ServiceHealth
  backups: ServiceHealth
}

/** A torrent qBittorrent is downloading. Speeds are bytes a second, progress 0 to 1. */
export type Torrent = {
  hash: string
  name: string
  progress: number
  dlspeed: number
  upspeed: number
  eta: number
  size: number
  state: string
}

/** Every service Robin talks to, in the order they are listed wherever health shows. */
/** The platform families Games lists, as Settings keeps them and the page picks one. */
export const GAME_PLATFORMS = [
  { value: 'pc', label: 'PC' },
  { value: 'playstation', label: 'PlayStation' },
  { value: 'xbox', label: 'Xbox' },
  { value: 'nintendo', label: 'Nintendo' },
]

// Every service Health reports, or this does not compile, so a new one reaches Home and setup.
export const SERVICE_LABELS = {
  igdb: 'IGDB',
  tmdb: 'TMDB',
  hardcover: 'Hardcover',
  metron: 'Metron',
  prowlarr: 'Prowlarr',
  predb: 'PreDB',
  suwayomi: 'Suwayomi',
  qbittorrent: 'qBittorrent',
  radarr: 'Radarr',
  sonarr: 'Sonarr',
  notify: 'Notifications',
  backups: 'Backups',
} satisfies Record<keyof Health, string>

export const SERVICES = (Object.keys(SERVICE_LABELS) as (keyof Health)[]).map((key) => ({
  key,
  label: SERVICE_LABELS[key],
}))

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

/**
 * What a failure says: the service's or Robin's own words, or `fallback` when the request
 * never got an answer.
 */
export function errorText(error: unknown, fallback?: string): string | undefined {
  return error instanceof ApiError ? error.message : fallback
}

/** Which screen the app shows: sign in, a new password, setup, or the app itself. */
export type Me = {
  signed_in: boolean
  username: string
  /** The password is the one printed at start, told before sign in. */
  one_time: boolean
  /** The setup step to open at, '' for the first, null once setup is done. */
  setup: string | null
  totp: boolean
  /** Whether any passkey exists, told before sign in. */
  passkeys: boolean
  /** The version running, told once signed in. */
  version: string
}

/** A Robin released on GitHub that is newer than the one running. */
export type Update = {
  version: string
  /** The release notes, plain lines. */
  notes: string
  url: string
  published: string
}

/** A backup on the data volume, `version` the Robin that wrote it. */
export type Backup = { name: string; size: number; version: string; created: string }

export type Passkey = { id: string; label: string; created_at: string; last_used_at: string | null }

/** WebAuthn needs a secure context, HTTPS or localhost, and the browser's JSON helpers. */
export const passkeysSupported =
  window.isSecureContext &&
  typeof PublicKeyCredential !== 'undefined' &&
  'parseRequestOptionsFromJSON' in PublicKeyCredential

/** The browser hands back null when no credential came of it. */
function credential(value: Credential | null): unknown {
  if (!(value instanceof PublicKeyCredential)) throw new ApiError(0, 'No passkey was used')
  return value.toJSON()
}

/** Dismissing the browser's passkey prompt is a choice, not a failure to report. */
export function cancelled(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'NotAllowedError'
}

export type TotpSetup = { secret: string; uri: string; qr: string }

/** Fired when a session has ended under a running app. The gate listens for it. */
export const SIGNED_OUT = 'robin:signed-out'

/** A data source asked Robin to slow down. The event's detail is a `Paused`. */
export const PAUSED = 'robin:paused'

export type Paused = { source: string; until: string; message: string }

/**
 * A page was answered with what Robin kept past its lifetime while its source is asked again.
 * The event's detail is a `Stale`, the answer it got.
 */
export const STALE = 'robin:stale'

export type Stale = { path: string; body: unknown }

/** A moment later today as a clock time, any other day with its date. */
export function clockTime(iso: string): string {
  const when = new Date(iso)
  const today = when.toDateString() === new Date().toDateString()
  return when.toLocaleString(undefined, {
    ...(today ? {} : { day: 'numeric', month: 'short' }),
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Drop everything the session could read, then ask the backend which screen applies. */
export function signedOut(client: QueryClient) {
  client.setQueryData<Me>(['me'], (me) => me && { ...me, signed_in: false, username: '' })
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' })
  void client.invalidateQueries({ queryKey: ['me'] })
}

async function request<T>(path: string, init?: RequestInit, fresh = false): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    // The backend refuses any write without X-Robin, which a cross site form cannot send.
    headers: {
      'X-Robin': '1',
      ...(fresh ? { 'X-Robin-Fresh': '1' } : {}),
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
    },
  })
  // A wrong password is a 401 too, and is the sign in form's to show.
  if (resp.status === 401 && !path.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event(SIGNED_OUT))
  }
  if (!resp.ok) {
    let detail = `Request failed with ${resp.status}`
    try {
      const body = await resp.json()
      if (typeof body?.detail === 'string') detail = body.detail
      // A paused source says until when, and the app says it once wherever you are.
      if (resp.status === 429 && typeof body?.paused_until === 'string') {
        detail = `${detail}, paused until ${clockTime(body.paused_until)}`
        const paused: Paused = { source: body.source, until: body.paused_until, message: detail }
        window.dispatchEvent(new CustomEvent(PAUSED, { detail: paused }))
      }
    } catch {
      // Non JSON error body, keep the generic message.
    }
    throw new ApiError(resp.status, detail)
  }
  // A 204 carries nothing to parse. Callers that expect nothing ask for void.
  if (resp.status === 204) return undefined as T
  const body: unknown = await resp.json()
  if (resp.headers.get('X-Robin-Stale')) {
    window.dispatchEvent(new CustomEvent<Stale>(STALE, { detail: { path, body } }))
  }
  return body as T
}

/** What `path` answers once its source has been asked again, waiting for it. */
export const latest = (path: string) => request<unknown>(path, undefined, true)

const post = <T = void>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export type ScreenKind = 'movie' | 'tv'

/** Radarr or Sonarr, the library a title is in. */
export type Library = 'radarr' | 'sonarr'

export const LIBRARY_NAME: Record<Library, string> = { radarr: 'Radarr', sonarr: 'Sonarr' }

/** A film's cinema or digital release in Radarr, or a season premiere in Sonarr. */
export type ArrRelease = {
  category: 'screens'
  key: string
  title: string
  image: string | null
  /** YYYY-MM-DD. */
  date: string
  to: string
  /** Cinema or Digital for a film, Series for a show. */
  tag: string
  library: Library
}

/** One upcoming movie or show as TMDB lists it. A returning show is dated by its next episode. */
export type ScreenTitle = {
  id: number
  kind: ScreenKind
  title: string
  original_title: string
  /** YYYY-MM-DD: the release in the region, or the next episode of a returning show. */
  date: string | null
  poster: string | null
  backdrop: string | null
  overview: string
  genre_ids: number[]
  language: string
  rating: number
  votes: number
  popularity: number
  next_episode: { season: number; episode: number; name: string; date: string } | null
  /** Cinema or Digital: the kind of release a film is dated by. */
  release: string | null
  /** Where a digital release is out, named in place of the tag. */
  platform: Platform | null
  /** The favourite person, studio or network it comes from, by name. */
  favourite?: string | null
}

export type ScreenPage = { titles: ScreenTitle[]; page: number; total_pages: number }

export type ScreenDetail = ScreenTitle & {
  tagline: string
  genres: string[]
  status: string
  runtime: number | null
  certification: string | null
  /** Directors of a film, creators of a show. */
  makers: Ref[]
  cast: Ref[]
  /** Studios of a film, networks of a show. */
  companies: Ref[]
  seasons: number | null
  /** A film's kept release types with a date in the region from today. */
  releases: { type: ReleaseType; tag: string; date: string; platform: Platform | null }[]
  /** A film's release types it can be monitored for, dated or still awaited in the region. */
  open_releases: ReleaseType[]
  /** Whether it has anything ahead to monitor, as the server decides. */
  monitorable: boolean
  trailer: string | null
  watch: { stream: string[]; rent: string[]; buy: string[]; link: string | null }
  imdb: string | null
  tmdb: string
  homepage: string | null
}

/** Each narrows what Settings leaves, empty for all of it. */
export type ScreenFilters = {
  /** One original language, by code. */
  language: string
  /** One release type of a film. */
  release: ReleaseType | ''
  /** One genre, by name, since movies and shows number theirs apart. */
  genre: string
  /** Most anticipated first, or soonest first. */
  sort: 'popularity' | 'date'
}

/** The categories with favourites, and what each can favourite. */
export type FavouriteCategory = 'games' | 'comics' | 'screens' | 'books'
export type FavouriteKind =
  | 'company'
  | 'franchise'
  | 'collection'
  | 'person'
  | 'studio'
  | 'network'
  | 'author'
  | 'series'
  | 'publisher'

/** Something a dialog names that releases come from, with the id it opens as a favourite by. */
export type Ref = { id: number; name: string }

/** Something releases come from, as its source names it, starred or not. */
export type Role = 'developer' | 'publisher'

export type Entity = {
  category: FavouriteCategory
  kind: FavouriteKind
  id: number
  name: string
  image: string | null
  /** What it is, one line: Developer and Publisher, Actor, Network, Author of 12 books. */
  meta: string
  /** A company's roles, so a search can ask for developers or publishers alone. */
  roles?: Role[]
  /** Its page on the source. */
  url: string | null
  /** Every source id it covers, its own among them: TMDB lists one studio under several. */
  ids: number[]
}

/** A starred entity, as Robin keeps it. */
/**
 * What a countdown to an item needs: the dialog parameter that opens it, `game=12`, and its
 * release day, YYYY-MM-DD, null while it has none, which is said rather than counted down.
 */
export type CountdownTarget = {
  category: Category
  target: string
  title: string
  image: string | null
  /** What the item is tagged with, as Home shows it beside its category. */
  tag?: string | null
  date: string | null
}

/** A countdown kept for Home, dated again from its category as its release moves. */
export type Countdown = CountdownTarget & { id: number; date: string }

/** One line Robin logged. `source` is the logger, `robin.grabs`, or `httpx` for a request out. */
export type LogLine = {
  id: number
  at: string
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical'
  source: string
  message: string
}

/** Always hide or always show, as a genre filter is. */
export type MakerMode = 'hide' | 'show'

/** What releases come from, always hidden or always shown, as a favourite is kept. */
export type MakerFilter = Favourite & { mode: MakerMode }

export type Favourite = {
  id: number
  category: FavouriteCategory
  kind: FavouriteKind
  source_id: number
  /** Every source id it covers, `source_id` among them. */
  ids: number[]
  name: string
  image: string | null
  created_at: string
}

/** A favourite's dated release, for Home. `to` is its dialog parameter, `game=12`. */
export type FavouriteRelease = {
  category: FavouriteCategory
  key: string
  title: string
  image: string | null
  /** YYYY-MM-DD. */
  date: string
  to: string
  tag: string | null
  favourite: string
}

/** One entity with what it has coming, in its category's own shape. */
export type FavouriteDetail = {
  entity: Entity
  favourite: Favourite | null
  releases: (Game | ScreenTitle | Book)[]
}

export const api = {
  me: () => request<Me>('/api/auth/me'),
  claim: (username: string, password: string) => post('/api/auth/claim', { username, password }),
  setupStep: (step: string | null) =>
    request<void>('/api/auth/setup', { method: 'PUT', body: JSON.stringify({ step }) }),
  login: (username: string, password: string, code: string) =>
    post<{ needs_code: boolean }>('/api/auth/login', { username, password, code }),
  logout: () => post('/api/auth/logout'),
  signOutEverywhere: () => post('/api/auth/sign-out-everywhere'),
  changePassword: (current: string, next: string) =>
    post('/api/auth/password', { current, new: next }),
  totpSetup: (password: string) => post<TotpSetup>('/api/auth/totp/setup', { password }),
  totpEnable: (code: string) => post('/api/auth/totp/enable', { code }),
  totpDisable: (password: string) => post('/api/auth/totp/disable', { password }),
  passkeys: () => request<Passkey[]>('/api/auth/passkeys'),
  removePasskey: (id: string) =>
    request<void>(`/api/auth/passkeys/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  addPasskey: async (label: string, password: string) => {
    const options = await post<PublicKeyCredentialCreationOptionsJSON>(
      '/api/auth/passkeys/register/options',
      { password },
    )
    const made = await navigator.credentials.create({
      publicKey: PublicKeyCredential.parseCreationOptionsFromJSON(options),
    })
    return post<Passkey>('/api/auth/passkeys/register', { credential: credential(made), label })
  },
  passkeyLogin: async () => {
    const options = await post<PublicKeyCredentialRequestOptionsJSON>(
      '/api/auth/passkeys/login/options',
    )
    const used = await navigator.credentials.get({
      publicKey: PublicKeyCredential.parseRequestOptionsFromJSON(options),
    })
    return post('/api/auth/passkeys/login', { credential: credential(used) })
  },
  discover: (limit: number, offset: number, filters: GameFilters) => {
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
      type: filters.type,
      genre: filters.genre,
      sort: filters.sort,
    })
    if (filters.platform) query.set('platform', filters.platform)
    return request<DiscoverPage>(`/api/games/discover?${query}`)
  },
  gameGenres: () => request<string[]>('/api/games/genres'),
  search: (q: string, limit = 24) =>
    request<Game[]>(`/api/games/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  game: (id: number) => request<Game>(`/api/games/${id}`),
  monitored: () => request<MonitoredGame[]>('/api/monitored'),
  screen: (kind: ScreenKind | 'all', filters: ScreenFilters, page: number) => {
    const query = new URLSearchParams({
      page: String(page),
      language: filters.language,
      release: filters.release,
      genre: filters.genre,
      sort: filters.sort,
    })
    return request<ScreenPage>(`/api/screens/${kind}/discover?${query}`)
  },
  searchScreens: (q: string) =>
    request<ScreenTitle[]>(`/api/screens/search?q=${encodeURIComponent(q)}`),
  screenTitle: (kind: ScreenKind, id: number) =>
    request<ScreenDetail>(`/api/screens/${kind}/${id}`),
  screenGenres: (kind: ScreenKind) =>
    request<{ id: number; name: string }[]>(`/api/screens/${kind}/genres`),
  screenLanguages: () => request<{ code: string; name: string }[]>('/api/screens/languages'),
  reminders: () => request<Reminder[]>('/api/screens/reminders'),
  remind: (body: { kind: ScreenKind; tmdb_id: number; release_type?: ReleaseType }) =>
    post<Reminder>('/api/screens/reminders', body),
  removeReminder: (id: number) =>
    request<void>(`/api/screens/reminders/${id}`, { method: 'DELETE' }),
  clearSentReminders: () => post('/api/screens/reminders/clear-found'),
  books: (filters: BookFilters, page: number) => {
    const query = new URLSearchParams({
      page: String(page),
      kind: filters.kind,
      genre: filters.genre,
      sort: filters.sort,
    })
    return request<BookPage>(`/api/books/discover?${query}`)
  },
  searchBooks: (q: string) => request<Book[]>(`/api/books/search?q=${encodeURIComponent(q)}`),
  book: (id: number) => request<BookDetail>(`/api/books/${id}`),
  bookGenres: () => request<{ slug: string; name: string }[]>('/api/books/genres'),
  bookReminders: () => request<BookReminder[]>('/api/books/reminders'),
  remindBook: (body: { book_id: number }) => post<BookReminder>('/api/books/reminders', body),
  removeBookReminder: (id: number) =>
    request<void>(`/api/books/reminders/${id}`, { method: 'DELETE' }),
  clearSentBookReminders: () => post('/api/books/reminders/clear-found'),
  bookShelf: (id: number) => request<{ want: boolean }>(`/api/books/${id}/shelf`),
  setBookShelf: (id: number, want: boolean) =>
    request<{ want: boolean }>(`/api/books/${id}/shelf`, {
      method: 'PUT',
      body: JSON.stringify({ want }),
    }),
  favourites: () => request<Favourite[]>('/api/favourites'),
  searchFavourites: (
    category: FavouriteCategory,
    q: string,
    everything = false,
    kind: FavouriteKind | null = null,
  ) =>
    request<Entity[]>(
      `/api/favourites/search?category=${category}&q=${encodeURIComponent(q)}&everything=${everything}${kind ? `&kind=${kind}` : ''}`,
    ),
  favourite: (category: FavouriteCategory, kind: FavouriteKind, id: number) =>
    request<FavouriteDetail>(`/api/favourites/${category}/${kind}/${id}`),
  addFavourite: (category: FavouriteCategory, kind: FavouriteKind, id: number) =>
    post<Favourite>('/api/favourites', { category, kind, id }),
  favouritesComing: () => request<FavouriteRelease[]>('/api/favourites/coming'),
  removeFavourite: (id: number) => request<void>(`/api/favourites/${id}`, { method: 'DELETE' }),
  logs: (after: number) => request<LogLine[]>(`/api/logs?after=${after}`),
  countdowns: () => request<Countdown[]>('/api/countdowns'),
  addCountdown: (target: CountdownTarget) => post<Countdown>('/api/countdowns', target),
  removeCountdown: (id: number) => request<void>(`/api/countdowns/${id}`, { method: 'DELETE' }),
  makerFilters: () => request<MakerFilter[]>('/api/favourites/filters'),
  filterMaker: (mode: MakerMode, category: FavouriteCategory, kind: FavouriteKind, id: number) =>
    post<MakerFilter>('/api/favourites/filters', { mode, category, kind, id }),
  unfilterMaker: (id: number) =>
    request<void>(`/api/favourites/filters/${id}`, { method: 'DELETE' }),
  monitoredComics: () => request<MonitoredComic[]>('/api/comics/monitored'),
  downloads: () => request<Torrent[]>('/api/qbittorrent/downloads'),
  qbittorrentCategories: () => request<string[]>('/api/qbittorrent/categories'),
  arrCalendar: () => request<ArrRelease[]>('/api/arr/calendar'),
  /** Which library holds each title, by `movie-<id>` or `tv-<id>`. */
  arrLibrary: () => request<Record<string, Library>>('/api/arr/library'),
  arrProfiles: (app: Library) =>
    request<{ id: number; name: string }[]>(`/api/arr/${app}/profiles`),
  arrFolders: (app: Library) => request<string[]>(`/api/arr/${app}/folders`),
  arrAdd: (app: Library, tmdbId: number) => post(`/api/arr/${app}`, { tmdb_id: tmdbId }),
  arrRemove: (kind: ScreenKind, tmdbId: number, deleteFiles: boolean) =>
    request<void>(`/api/arr/${kind}/${tmdbId}?delete_files=${deleteFiles}`, { method: 'DELETE' }),
  comicDetail: (comic: Comic) => request<ComicDetail>(`/api/comics/issue/${comic.id}`),
  monitorComic: ({ id, title, url, publisher, cover, series_id }: Comic, week: string) =>
    request<MonitoredComic>('/api/comics/monitored', {
      method: 'POST',
      body: JSON.stringify({ id, title, url, publisher, cover, series_id, week }),
    }),
  comic: (id: string) => request<Comic>(`/api/comics/comic/${id}`),
  comicIssues: (week?: string) =>
    request<ComicIssues>(`/api/comics/issues${week ? `?week=${week}` : ''}`),
  latestComics: () => request<Series[]>('/api/comics/latest'),
  searchComics: (q: string) => request<Series[]>(`/api/comics/search?q=${encodeURIComponent(q)}`),
  series: (id: number) => request<Series>(`/api/comics/series/${id}`),
  addSeries: (id: number) =>
    request<Series>(`/api/comics/series/${id}/library`, { method: 'POST' }),
  clearFoundGames: () => request<void>('/api/monitored/clear-found', { method: 'POST' }),
  clearFoundComics: () => request<void>('/api/comics/monitored/clear-found', { method: 'POST' }),
  stopMonitoringComic: (id: number) =>
    request<void>(`/api/comics/monitored/${id}`, { method: 'DELETE' }),
  monitor: (body: { igdb_id: number }) =>
    request<MonitoredGame>('/api/monitored', { method: 'POST', body: JSON.stringify(body) }),
  confirmRelease: (id: number) =>
    request<MonitoredGame>(`/api/monitored/${id}/confirm`, { method: 'POST' }),
  rejectRelease: (id: number) =>
    request<MonitoredGame>(`/api/monitored/${id}/reject`, { method: 'POST' }),
  stopMonitoring: (id: number) => request<void>(`/api/monitored/${id}`, { method: 'DELETE' }),
  settings: () => request<Settings>('/api/settings'),
  saveSettings: (
    patch: Partial<Settings> & {
      twitch_client_secret?: string
      prowlarr_api_key?: string
    },
  ) => request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(patch) }),
  health: (refresh = false) =>
    request<Health>(`/api/settings/health${refresh ? '?refresh=true' : ''}`),
  testNotify: (destinations: Destination[], category: Category | null = null) =>
    request<Check>('/api/settings/notify-test', {
      method: 'POST',
      body: JSON.stringify({ destinations, category }),
    }),
  notifyServices: () => request<NotifyService[]>('/api/settings/notify-services'),
  prowlarrIndexers: () => request<NamedThing[]>('/api/prowlarr/indexers'),
  update: () => request<Update | null>('/api/update'),
  searchIndexers: (igdbId: number) =>
    request<{ term: string; releases: Release[] }>(`/api/prowlarr/search?igdb_id=${igdbId}`),
  grab: (igdbId: number, guid: string) =>
    post<void>('/api/prowlarr/grab', { igdb_id: igdbId, guid }),
  backups: () => request<Backup[]>('/api/backups'),
  backUp: () => post<Backup>('/api/backups'),
  deleteBackup: (name: string) =>
    request<void>(`/api/backups/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  /** A backup on the volume by `name`, or one uploaded as base64 `data`. */
  restore: (backup: { name: string } | { data: string }, passphrase: string) =>
    post('/api/backups/restore', { ...backup, passphrase }),
}

/** A source's image as Robin serves it from its cache, so the browser never asks the source. */
export function imageSrc(url: string): string {
  return /^https?:\/\//.test(url) ? `/img/remote?url=${encodeURIComponent(url)}` : url
}

export function posterUrl(imageId: string | null, size = 'cover_big'): string | null {
  return imageId ? `/img/${size}/${imageId}.jpg` : null
}

/** What a release costs against a ratio. Nothing while it counts in full. */
export function leech(flags: string[]): { label: string; className: string } | null {
  if (flags.includes('freeleech')) return { label: 'Freeleech', className: 'bg-good/15 text-good' }
  if (flags.includes('neutralleech')) return { label: 'Neutral', className: 'bg-good/15 text-good' }
  if (flags.includes('halfleech')) return { label: '50%', className: 'bg-accent/15 text-accent' }
  return null
}

/** Prowlarr reports age in whole days, so today is anything under one. */
export function releaseAge(days: number): string {
  if (days < 1) return 'today'
  if (days < 30) return `${days}d`
  if (days < 365) return `${Math.round(days / 30)}mo`
  return `${(days / 365).toFixed(1)}y`
}

export function releaseSize(bytes: number): string {
  const gb = bytes / 1e9
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  return bytes >= 1e6
    ? `${Math.round(bytes / 1e6)} MB`
    : `${Math.max(1, Math.round(bytes / 1e3))} KB`
}

/**
 * Only a date IGDB names an actual day for arrives as a timestamp. Anything vaguer arrives as
 * IGDB's own wording, "Q2 2026" or "2026", which is shown instead of TBA even though the game
 * counts as undated for ordering.
 *
 * Dates are UTC, so format them in UTC or a late evening release slips back a day.
 */
export function releaseLabel(timestamp: number | null, fallback?: string | null): string {
  if (!timestamp) return fallback || 'TBA'
  return new Date(timestamp * 1000).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/** How a page of items is laid out. */
export type View = 'list' | 'cover' | 'table'
