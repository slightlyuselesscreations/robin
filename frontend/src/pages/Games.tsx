import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { CalendarDays, Gamepad2 } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { GameMenu } from '@/components/ItemMenus'
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
  ViewSwitch,
} from '@/components/Page'
import { GAME_PLATFORMS, type Game, type GameFilters, api, errorText } from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { HEADER_CONTROLS, ORDERS, asView, narrowed, pickOf, usePageControls } from '@/lib/controls'
import { gameItem } from '@/lib/items'
import { useScrollPaging } from '@/lib/paging'
import { withParam } from '@/lib/params'

const PAGE_SIZE = 36

/** Stops a long scroll from walking the whole popularity ranking. */
const MAX_PAGES = 14

function monthOf(game: Game): string {
  if (!game.first_release_date) return 'TBA'
  return new Date(game.first_release_date * 1000).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/** Runs of games sharing a release month, in the order the backend already sorted them. */
function byMonth(games: Game[]): { month: string; games: Game[] }[] {
  const groups: { month: string; games: Game[] }[] = []
  for (const game of games) {
    const month = monthOf(game)
    const last = groups.at(-1)
    if (last?.month === month) last.games.push(game)
    else groups.push({ month, games: [game] })
  }
  return groups
}

/**
 * Upcoming is what comes out from the first of this month on, undated games last. Out is what
 * came out since the first of January, to be monitored and grabbed.
 */
const TYPES = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'out', label: 'Out' },
] as const

const ORDER = [ORDERS.date, ORDERS.popularity]

/**
 * Every control as it starts on a bare `/games`, before the defaults saved for the page. A
 * filter is empty for all of what Settings leaves.
 */
const BUILTIN = {
  view: 'cover',
  type: 'upcoming',
  order: 'date',
  platform: '',
  genre: '',
}

/**
 * Games from IGDB, soonest first, a section per release month, or most anticipated first in
 * one. Platforms are hidden in Settings, and the filters in Options narrow what is left.
 */
export function Games() {
  const [params] = useSearchParams()
  const controls = usePageControls('games', BUILTIN)
  const { values } = controls
  const view = asView(values.view, 'cover')
  const hidden = useSettings().data?.games_hidden_platforms ?? []
  const platformOptions = GAME_PLATFORMS.filter((p) => !hidden.includes(p.value))
  const genres = useQuery({
    queryKey: ['game-genres'],
    queryFn: api.gameGenres,
    staleTime: Infinity,
  })
  const genreOptions = genres.data?.map((name) => ({ value: name, label: name }))
  const order = pickOf(values.order, ORDER)
  const filters: GameFilters = {
    type: pickOf(values.type, TYPES),
    platform: narrowed(values.platform, platformOptions),
    genre: narrowed(values.genre, genreOptions),
    sort: order,
  }
  const monitored = useQuery({ queryKey: ['monitored'], queryFn: api.monitored })
  const byGame = new Map(monitored.data?.map((m) => [m.igdb_id, m]))

  const set = (changes: Partial<typeof BUILTIN>) => controls.set({ ...changes, game: null })

  const games = useInfiniteQuery({
    queryKey: ['games', filters, hidden],
    queryFn: ({ pageParam }) => api.discover(PAGE_SIZE, pageParam, filters),
    initialPageParam: 0,
    // The backend reports where to continue, because a page filtered down to a handful of
    // games is not the end of the list.
    getNextPageParam: (lastPage, allPages) =>
      allPages.length >= MAX_PAGES ? undefined : (lastPage.next_offset ?? undefined),
    staleTime: 5 * 60_000,
    // A change of controls keeps the current list, dimmed, until the new one is in.
    placeholderData: keepPreviousData,
  })

  useScrollPaging(games)

  const list = games.data?.pages.flatMap((page) => page.games) ?? []
  const withGame = (id: number) => withParam(params, 'game', id)
  // Release months only read as sections while the list runs in release order.
  const sections = order === 'date' ? byMonth(list) : [{ month: 'Most anticipated', games: list }]

  return (
    <Page>
      <PageHeader title="Games" icon={Gamepad2}>
        <Segmented
          label="Type"
          options={[...TYPES]}
          value={filters.type}
          onChange={(type) => set({ type })}
        />
        <Segmented
          label="Order"
          options={ORDER}
          value={order}
          onChange={(next) => set({ order: next })}
        />
        <Options controls={controls} header={HEADER_CONTROLS}>
          <ViewSwitch value={view} onChange={(next) => set({ view: next })} />
          {platformOptions.length > 1 ? (
            <Control label="Platform">
              <FilterSelect
                value={filters.platform}
                all="All platforms"
                options={platformOptions}
                onChange={(platform) => set({ platform })}
              />
            </Control>
          ) : null}
          <Control label="Genre">
            <FilterSelect
              value={filters.genre}
              all="All genres"
              options={genreOptions ?? []}
              onChange={(genre) => set({ genre })}
            />
          </Control>
        </Options>
      </PageHeader>

      {games.isPending ? (
        <Skeletons shape="poster" count={18} />
      ) : games.isError ? (
        <Notice tone="bad">{errorText(games.error, 'IGDB is unreachable')}</Notice>
      ) : list.length === 0 ? (
        <Notice>Nothing to show right now.</Notice>
      ) : (
        <>
          <Sections dimmed={games.isPlaceholderData}>
            {sections.map(({ month, games: inMonth }) => (
              <Section
                key={month}
                title={month}
                icon={order === 'date' ? CalendarDays : Gamepad2}
                count={inMonth.length}
              >
                <Items
                  view={view}
                  metaLabel="Release"
                  items={inMonth.map((game) => ({
                    ...gameItem(game, withGame(game.igdb_id), byGame.get(game.igdb_id)),
                    menu: (
                      <GameMenu
                        igdbId={game.igdb_id}
                        released={game.first_release_date}
                        platforms={game.platforms}
                        url={game.url}
                      />
                    ),
                  }))}
                />
              </Section>
            ))}
          </Sections>

          <NextPage loading={games.isFetchingNextPage} />
        </>
      )}
    </Page>
  )
}
