import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Clapperboard, Film, Tv } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { ScreenMenu } from '@/components/ItemMenus'
import { Items, Skeletons } from '@/components/MediaCard'
import {
  Control,
  KeptSelect,
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
import { ANY, KEPT, WINDOWS, asView, usePageControls, windowDays } from '@/lib/controls'
import { useLibrary } from '@/lib/arr'
import { screenItem } from '@/lib/items'
import { useScrollPaging } from '@/lib/paging'
import { filtered } from '@/lib/utils'
import { withParam } from '@/lib/params'

/** TMDB pages hold twenty titles. Past this many a scroll is not looking for anything. */
const MAX_PAGES = 15

const RELEASES: { value: ReleaseType; label: string }[] = [
  { value: 'theatrical', label: 'Cinema' },
  { value: 'digital', label: 'Digital' },
]

/**
 * Every control as it starts on a bare `/screens`, before the defaults saved for the page. Each
 * is a search parameter, so back and forward step through what was looked at and a filtered
 * view can be bookmarked.
 */
const BUILTIN = { view: 'cover', kind: 'all', release: ANY, lang: KEPT, days: '90' }

/** The controls as TMDB is asked, anything no longer offered taking its built in default. */
function readFilters(values: typeof BUILTIN): {
  kind: ScreenKind | 'all'
  filters: ScreenFilters
} {
  const kind = values.kind === 'movie' || values.kind === 'tv' ? values.kind : 'all'
  return {
    kind,
    filters: {
      days: windowDays(values.days, BUILTIN.days),
      language: values.lang === KEPT ? '' : values.lang,
      release: kind === 'tv' ? '' : (RELEASES.find((r) => r.value === values.release)?.value ?? ''),
    },
  }
}

/**
 * Upcoming movies and TV from TMDB, most anticipated first. Genres, original languages and
 * release types are hidden in Settings, the header narrows what is left and picks the rest.
 */
export function Screen() {
  const [params] = useSearchParams()
  const controls = usePageControls('screens', BUILTIN)
  const view = asView(controls.values.view, 'cover')
  const { kind, filters } = readFilters(controls.values)
  const settings = useSettings()
  const hiddenLanguages = settings.data?.tmdb_hidden_languages ?? []
  const hiddenReleases = settings.data?.tmdb_hidden_release_types ?? []
  // The page narrows what Settings leaves shown.
  const releases = RELEASES.filter((r) => !hiddenReleases.includes(r.value))
  const hidden = [
    hiddenLanguages,
    hiddenReleases,
    settings.data?.tmdb_hidden_movie_genres,
    settings.data?.tmdb_hidden_tv_genres,
    settings.data?.tmdb_shown_movie_genres,
    settings.data?.tmdb_shown_tv_genres,
  ]

  const set = (changes: Partial<typeof BUILTIN>) => controls.set({ ...changes, title: null })

  const movieGenres = useQuery({
    queryKey: ['screen-genres', 'movie'],
    queryFn: () => api.screenGenres('movie'),
    enabled: kind !== 'tv',
    staleTime: Infinity,
  })
  const tvGenres = useQuery({
    queryKey: ['screen-genres', 'tv'],
    queryFn: () => api.screenGenres('tv'),
    enabled: kind !== 'movie',
    staleTime: Infinity,
  })
  const reminders = useQuery({ queryKey: ['screen-reminders'], queryFn: api.reminders })
  const remindersOf = (title: ScreenTitle) =>
    (reminders.data ?? []).filter((r) => r.kind === title.kind && r.tmdb_id === title.id)
  const languages = useQuery({
    queryKey: ['screen-languages'],
    queryFn: api.screenLanguages,
    staleTime: Infinity,
  })
  // Movies and shows number their genres apart, so each title is named from its own kind.
  const genreNames = {
    movie: new Map(movieGenres.data?.map((g) => [g.id, g.name])),
    tv: new Map(tvGenres.data?.map((g) => [g.id, g.name])),
  }
  const languageName = (code: string) => languages.data?.find((l) => l.code === code)?.name ?? code

  const titles = useInfiniteQuery({
    queryKey: ['screen', kind, filters, hidden],
    queryFn: ({ pageParam }) => api.screen(kind, filters, pageParam),
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
        <Options controls={controls}>
          <ViewSwitch value={view} onChange={(next) => set({ view: next })} />
          <Control label="Kind">
            <Segmented
              label="Kind"
              options={[
                { value: 'all', label: 'All', icon: Clapperboard },
                { value: 'movie', label: 'Movies', icon: Film },
                { value: 'tv', label: 'TV', icon: Tv },
              ]}
              value={kind}
              onChange={(next) => set({ kind: next })}
            />
          </Control>
          {kind !== 'tv' && releases.length > 1 ? (
            <Control label="Release">
              <Segmented
                label="Release"
                options={[{ value: ANY, label: 'Any' }, ...releases]}
                value={filters.release || ANY}
                onChange={(release) => set({ release })}
              />
            </Control>
          ) : null}
          <Control label="Language">
            <KeptSelect
              value={filters.language}
              kept={filtered(languages.data ?? [], hiddenLanguages, (l) => l.code, languageName)}
              any="Any language"
              options={(languages.data ?? [])
                .filter((l) => !hiddenLanguages.includes(l.code))
                .map((l) => ({ value: l.code, label: l.name }))}
              onChange={(lang) => set({ lang })}
            />
          </Control>
          <Control label="Window">
            <Segmented
              label="Window"
              options={WINDOWS}
              value={String(filters.days)}
              onChange={(days) => set({ days })}
            />
          </Control>
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
          <Notice>Nothing coming in this window.</Notice>
        )
      ) : (
        <>
          <Sections dimmed={titles.isPlaceholderData}>
            <Section
              title={kind === 'movie' ? 'Movies' : kind === 'tv' ? 'Shows' : 'TMDB'}
              icon={kind === 'movie' ? Film : kind === 'tv' ? Tv : Clapperboard}
              count={list.length}
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
