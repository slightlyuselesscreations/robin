import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Clapperboard, Film, Tv } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { ScreenMenu } from '@/components/ItemMenus'
import { Items, Skeletons } from '@/components/MediaCard'
import {
  Control,
  FilterSelect,
  NextPage,
  Notice,
  Options,
  Page,
  PageHeader,
  Section,
  Sections,
  Segmented,
  SourceCredit,
  ViewSwitch,
} from '@/components/Page'
import {
  type ReleaseType,
  type ScreenFilters,
  type ScreenKind,
  type ScreenTitle,
  api,
  errorText,
} from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { HEADER_CONTROLS, ORDERS, asView, narrowed, pickOf, usePageControls } from '@/lib/controls'
import { useLibrary } from '@/lib/arr'
import { screenItem } from '@/lib/items'
import { useScrollPaging } from '@/lib/paging'
import { withParam } from '@/lib/params'

/** TMDB pages hold twenty titles. Past this many a scroll is not looking for anything. */
const MAX_PAGES = 15

const TYPES = [
  { value: 'all', label: 'All', icon: Clapperboard },
  { value: 'movie', label: 'Movies', icon: Film },
  { value: 'tv', label: 'TV', icon: Tv },
] as const

const ORDER = [ORDERS.popularity, ORDERS.date]

const RELEASES: { value: ReleaseType; label: string }[] = [
  { value: 'theatrical', label: 'Cinema' },
  { value: 'digital', label: 'Digital' },
]

/**
 * Every control as it starts on a bare `/screens`, before the defaults saved for the page. Each
 * is a search parameter, so back and forward step through what was looked at and a filtered
 * view can be bookmarked. A filter is empty for all of what Settings leaves.
 */
const BUILTIN = {
  view: 'cover',
  type: 'all',
  order: 'popularity',
  genre: '',
  language: '',
  release: '',
}

/**
 * Upcoming movies and TV from TMDB, most anticipated first. Genres, original languages and
 * release types are hidden in Settings, and the filters in Options narrow what is left.
 */
export function Screen() {
  const [params] = useSearchParams()
  const controls = usePageControls('screens', BUILTIN)
  const { values } = controls
  const view = asView(values.view, 'cover')
  const type: ScreenKind | 'all' = pickOf(values.type, TYPES)
  const settings = useSettings()
  const hiddenLanguages = settings.data?.tmdb_hidden_languages ?? []
  const hiddenReleases = settings.data?.tmdb_hidden_release_types ?? []
  const hiddenMovieGenres = settings.data?.tmdb_hidden_movie_genres ?? []
  const hiddenTvGenres = settings.data?.tmdb_hidden_tv_genres ?? []
  const hidden = [
    hiddenLanguages,
    hiddenReleases,
    hiddenMovieGenres,
    hiddenTvGenres,
    settings.data?.tmdb_shown_movie_genres,
    settings.data?.tmdb_shown_tv_genres,
  ]

  const set = (changes: Partial<typeof BUILTIN>) => controls.set({ ...changes, title: null })

  const languages = useQuery({
    queryKey: ['screen-languages'],
    queryFn: api.screenLanguages,
    staleTime: Infinity,
  })
  const movieGenres = useQuery({
    queryKey: ['screen-genres', 'movie'],
    queryFn: () => api.screenGenres('movie'),
    enabled: type !== 'tv',
    staleTime: Infinity,
  })
  const tvGenres = useQuery({
    queryKey: ['screen-genres', 'tv'],
    queryFn: () => api.screenGenres('tv'),
    enabled: type !== 'movie',
    staleTime: Infinity,
  })
  const reminders = useQuery({ queryKey: ['screen-reminders'], queryFn: api.reminders })
  const remindersOf = (title: ScreenTitle) =>
    (reminders.data ?? []).filter((r) => r.kind === title.kind && r.tmdb_id === title.id)
  // Movies and shows number their genres apart, so each title is named from its own kind.
  const genreNames = {
    movie: new Map(movieGenres.data?.map((g) => [g.id, g.name])),
    tv: new Map(tvGenres.data?.map((g) => [g.id, g.name])),
  }

  // What Settings leaves of each list, for the filters to narrow. A genre is offered by name,
  // movies and shows numbering theirs apart, and for All from either.
  const genreOptions =
    (type !== 'tv' && !movieGenres.data) || (type !== 'movie' && !tvGenres.data)
      ? undefined
      : [
          ...new Set([
            ...(type === 'tv' ? [] : (movieGenres.data ?? []))
              .filter((g) => !hiddenMovieGenres.includes(g.id))
              .map((g) => g.name),
            ...(type === 'movie' ? [] : (tvGenres.data ?? []))
              .filter((g) => !hiddenTvGenres.includes(g.id))
              .map((g) => g.name),
          ]),
        ]
          .sort()
          .map((name) => ({ value: name, label: name }))
  const languageOptions = languages.data
    ?.filter((l) => !hiddenLanguages.includes(l.code))
    .map((l) => ({ value: l.code, label: l.name }))
  const releaseOptions = RELEASES.filter((r) => !hiddenReleases.includes(r.value))

  const filters: ScreenFilters = {
    genre: narrowed(values.genre, genreOptions),
    language: narrowed(values.language, languageOptions),
    release:
      type === 'tv' ? '' : (releaseOptions.find((r) => r.value === values.release)?.value ?? ''),
    sort: pickOf(values.order, ORDER),
  }

  const titles = useInfiniteQuery({
    queryKey: ['screen', type, filters, hidden],
    queryFn: ({ pageParam }) => api.screen(type, filters, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last, all) =>
      all.length >= MAX_PAGES || last.page >= last.total_pages ? undefined : last.page + 1,
    staleTime: 10 * 60_000,
    // A change of controls keeps the current list, dimmed, until the new one is in.
    placeholderData: keepPreviousData,
  })

  useScrollPaging(titles)

  // A title can come back on two pages when TMDB's ranking shifts between them. A movie and a
  // show can share an id.
  const seen = new Set<string>()
  const list = (titles.data?.pages.flatMap((p) => p.titles) ?? []).filter((t) => {
    const key = `${t.kind}-${t.id}`
    return !seen.has(key) && seen.add(key)
  })
  const inLibrary = useLibrary()
  const link = (title: ScreenTitle) => withParam(params, 'title', `${title.kind}-${title.id}`)
  const items = (run: ScreenTitle[]) =>
    run.map((t) => ({
      ...screenItem(t, link(t), genreNames[t.kind], remindersOf(t), inLibrary(`${t.kind}-${t.id}`)),
      menu: <ScreenMenu kind={t.kind} id={t.id} />,
    }))

  return (
    <Page>
      <PageHeader title="Screens" icon={Clapperboard}>
        <Segmented
          label="Type"
          options={[...TYPES]}
          value={type}
          onChange={(next) => set({ type: next })}
        />
        <Segmented
          label="Order"
          options={ORDER}
          value={pickOf(values.order, ORDER)}
          onChange={(order) => set({ order })}
        />
        <Options controls={controls} header={HEADER_CONTROLS}>
          <ViewSwitch value={view} onChange={(next) => set({ view: next })} />
          <Control label="Genre">
            <FilterSelect
              value={filters.genre}
              all="All genres"
              options={genreOptions ?? []}
              onChange={(genre) => set({ genre })}
            />
          </Control>
          <Control label="Language">
            <FilterSelect
              value={filters.language}
              all="All languages"
              options={languageOptions ?? []}
              onChange={(language) => set({ language })}
            />
          </Control>
          {type !== 'tv' && releaseOptions.length > 1 ? (
            <Control label="Release">
              <FilterSelect
                value={filters.release}
                all="All releases"
                options={releaseOptions}
                onChange={(next) => set({ release: next })}
              />
            </Control>
          ) : null}
        </Options>
      </PageHeader>

      {titles.isPending ? (
        <Skeletons shape="cover" count={18} />
      ) : titles.isError ? (
        <Notice tone="bad">{errorText(titles.error, 'TMDB is unreachable')}</Notice>
      ) : list.length === 0 ? (
        titles.hasNextPage ? (
          <NextPage loading />
        ) : (
          <Notice>Nothing coming.</Notice>
        )
      ) : (
        <>
          <Sections dimmed={titles.isPlaceholderData}>
            <Section
              title={type === 'movie' ? 'Movies' : type === 'tv' ? 'Shows' : 'TMDB'}
              icon={type === 'movie' ? Film : type === 'tv' ? Tv : Clapperboard}
              count={list.length}
              note={filters.sort === 'date' ? 'Soonest first' : 'Most anticipated first'}
            >
              <Items view={view} metaLabel="Release" items={items(list)} />
            </Section>
          </Sections>

          <NextPage loading={titles.isFetchingNextPage} />
        </>
      )}

      <SourceCredit
        name="TMDB"
        href="https://www.themoviedb.org"
        terms="This product uses the TMDB API but is not endorsed or certified by TMDB."
      />
    </Page>
  )
}
