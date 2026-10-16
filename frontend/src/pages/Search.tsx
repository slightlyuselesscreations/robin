import { useQuery } from '@tanstack/react-query'
import { Clapperboard, Gamepad2, LibraryBig, Search as SearchIcon } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { FavouriteSections } from '@/components/FavouriteDialog'
import { BookMenu, GameMenu, ScreenMenu } from '@/components/ItemMenus'
import { Items, Skeletons } from '@/components/MediaCard'
import {
  Group,
  Notice,
  Options,
  Page,
  PageHeader,
  Section,
  Sections,
  ViewSwitch,
} from '@/components/Page'
import { type Category, type FavouriteCategory, type View, api, errorText } from '@/lib/api'
import { useLibrary } from '@/lib/arr'
import { CATEGORY } from '@/lib/categories'
import { asView, usePageControls } from '@/lib/controls'
import { type SearchScope, SOURCE, useFavouriteSearch, useSearchScopes } from '@/lib/favourites'
import { type Shape, bookItem, bookRemindersOf, gameItem, screenItem } from '@/lib/items'
import { withParam } from '@/lib/params'

/**
 * One scope searched for `?q=`, the one `?type=` names, picked in the search bar: a category's
 * titles, or one kind of what they come from.
 */
export function Search() {
  const [params] = useSearchParams()
  const term = params.get('q') ?? ''
  const scope = useSearchScopes().find((s) => s.value === params.get('type'))
  const controls = usePageControls('search', { view: 'cover' })
  const view = asView(controls.values.view, 'cover')
  const Results = !scope ? null : scope.kind ? KindResults : RESULTS[scope.category]

  return (
    <Page>
      <PageHeader icon={SearchIcon} title={term ? `Results for ${term}` : 'Search'}>
        <Options controls={controls}>
          <ViewSwitch value={view} onChange={(next) => controls.set({ view: next })} />
        </Options>
      </PageHeader>

      {!Results ? (
        <Notice>Pick a category to search from in the search bar.</Notice>
      ) : term ? (
        <>
          {/* Nothing matching renders nothing, so an empty list means nothing did. */}
          <div className="peer space-y-12">
            <Results term={term} view={view} scope={scope!} />
          </div>
          <div className="hidden peer-empty:block">
            <Notice>Nothing matches that.</Notice>
          </div>
        </>
      ) : (
        <Notice>Type something to search for.</Notice>
      )}
    </Page>
  )
}

type ResultsProps = { term: string; view: View; scope: SearchScope }

/**
 * One category's results under its own heading. Skeletons while the titles load, left out
 * once nothing matched, a notice when its source could not be asked.
 */
function CategoryGroup({
  category,
  shape,
  count,
  pending,
  error,
  children,
}: {
  category: Category
  shape: Shape
  count: number
  pending: boolean
  error: string | null
  children: React.ReactNode
}) {
  if (!pending && !error && count === 0) return null
  return (
    <Group title={CATEGORY[category].label} icon={CATEGORY[category].icon} count={count}>
      {pending ? (
        <Skeletons shape={shape} count={6} />
      ) : error ? (
        <Notice tone="bad">{error}</Notice>
      ) : (
        <Sections>{children}</Sections>
      )}
    </Group>
  )
}

/** What a failed query says, or null. */
const failed = (query: { isError: boolean; error: unknown }, source: string) =>
  query.isError ? (errorText(query.error, `${source} is unreachable`) ?? null) : null

function GameResults({ term, view }: ResultsProps) {
  const [params] = useSearchParams()
  const monitored = useQuery({ queryKey: ['monitored'], queryFn: api.monitored })
  const byGame = new Map(monitored.data?.map((m) => [m.igdb_id, m]))
  const results = useQuery({ queryKey: ['search', term], queryFn: () => api.search(term, 40) })
  const items = (results.data ?? []).map((game) => ({
    ...gameItem(game, withParam(params, 'game', game.igdb_id), byGame.get(game.igdb_id)),
    menu: <GameMenu igdbId={game.igdb_id} released={game.first_release_date} url={game.url} />,
  }))
  return (
    <CategoryGroup
      category="games"
      shape="poster"
      count={items.length}
      pending={results.isPending}
      error={failed(results, 'IGDB')}
    >
      {items.length ? (
        <Section title="Games" icon={Gamepad2} count={items.length}>
          <Items view={view} metaLabel="Release" items={items} />
        </Section>
      ) : null}
    </CategoryGroup>
  )
}

/** Comic series on Comic Vine. Each opens as a favourite, with the issues it has coming. */
function ComicResults({ term, view }: ResultsProps) {
  const found = useFavouriteSearch('comics', term)
  const series = (found.data ?? []).filter((e) => e.kind === 'series')
  return (
    <CategoryGroup
      category="comics"
      shape="cover"
      count={series.length}
      pending={found.isPending}
      error={failed(found, 'Comic Vine')}
    >
      <FavouriteSections category="comics" entities={series} view={view} title="Series" />
    </CategoryGroup>
  )
}

function ScreenResults({ term, view }: ResultsProps) {
  const [params] = useSearchParams()
  const results = useQuery({
    queryKey: ['screen-search', term],
    queryFn: () => api.searchScreens(term),
    retry: false,
  })
  const genres = {
    movie: useQuery({
      queryKey: ['screen-genres', 'movie'],
      queryFn: () => api.screenGenres('movie'),
      staleTime: Infinity,
    }),
    tv: useQuery({
      queryKey: ['screen-genres', 'tv'],
      queryFn: () => api.screenGenres('tv'),
      staleTime: Infinity,
    }),
  }
  const reminders = useQuery({ queryKey: ['screen-reminders'], queryFn: api.reminders })
  const inLibrary = useLibrary()
  const items = (results.data ?? []).map((t) => ({
    ...screenItem(
      t,
      withParam(params, 'title', `${t.kind}-${t.id}`),
      new Map(genres[t.kind].data?.map((g) => [g.id, g.name])),
      (reminders.data ?? []).filter((r) => r.kind === t.kind && r.tmdb_id === t.id),
      inLibrary(`${t.kind}-${t.id}`),
    ),
    menu: <ScreenMenu kind={t.kind} id={t.id} />,
  }))
  return (
    <CategoryGroup
      category="screens"
      shape="cover"
      count={items.length}
      pending={results.isPending}
      error={failed(results, 'TMDB')}
    >
      {items.length ? (
        <Section title="Movies & TV" icon={Clapperboard} count={items.length}>
          <Items view={view} metaLabel="Release" items={items} />
        </Section>
      ) : null}
    </CategoryGroup>
  )
}

function BookResults({ term, view }: ResultsProps) {
  const [params] = useSearchParams()
  const results = useQuery({
    queryKey: ['book-search', term],
    queryFn: () => api.searchBooks(term),
    retry: false,
  })
  const reminders = useQuery({ queryKey: ['book-reminders'], queryFn: api.bookReminders })
  const items = (results.data ?? []).map((b) => ({
    ...bookItem(b, withParam(params, 'book', b.id), bookRemindersOf(b, reminders.data ?? [])),
    menu: <BookMenu id={b.id} />,
  }))
  return (
    <CategoryGroup
      category="books"
      shape="cover"
      count={items.length}
      pending={results.isPending}
      error={failed(results, 'Hardcover')}
    >
      {items.length ? (
        <Section title="Books" icon={LibraryBig} count={items.length}>
          <Items view={view} metaLabel="Release" items={items} />
        </Section>
      ) : null}
    </CategoryGroup>
  )
}

/** One kind of what a category's titles come from, people or studios or authors. */
function KindResults({ term, view, scope }: ResultsProps) {
  const category = scope.category as FavouriteCategory
  const found = useFavouriteSearch(category, term)
  const entities = (found.data ?? []).filter(
    (e) => e.kind === scope.kind && (!scope.role || e.roles?.includes(scope.role)),
  )
  return (
    <CategoryGroup
      category={category}
      shape="cover"
      count={entities.length}
      pending={found.isPending}
      error={failed(found, SOURCE[category])}
    >
      <FavouriteSections category={category} entities={entities} view={view} title={scope.label} />
    </CategoryGroup>
  )
}

/** Each category's titles. */
const RESULTS: Record<Category, (props: ResultsProps) => React.ReactNode> = {
  games: GameResults,
  comics: ComicResults,
  screens: ScreenResults,
  books: BookResults,
}
