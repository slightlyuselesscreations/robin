import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { CalendarDays, Gamepad2 } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { GameMenu } from '@/components/ItemMenus'
import { Items, Skeletons } from '@/components/MediaCard'
import {
  Control,
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
import { GAME_PLATFORMS, type Game, api, errorText } from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { KEPT, asView, usePageControls } from '@/lib/controls'
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
 * Upcoming games from IGDB, soonest first, a section per release month. From January adds the
 * games out this year, to be monitored and grabbed.
 */
export function Games() {
  const [params] = useSearchParams()
  const controls = usePageControls('games', { view: 'cover', platform: KEPT, from: 'tomorrow' })
  const released = controls.values.from === 'january'
  const view = asView(controls.values.view, 'cover')
  const hidden = useSettings().data?.games_hidden_platforms ?? []
  // The page narrows what Settings leaves shown.
  const platforms = GAME_PLATFORMS.filter((p) => !hidden.includes(p.value))
  const platform = platforms.find((p) => p.value === controls.values.platform)?.value ?? ''
  const monitored = useQuery({ queryKey: ['monitored'], queryFn: api.monitored })
  const byGame = new Map(monitored.data?.map((m) => [m.igdb_id, m]))

  const games = useInfiniteQuery({
    queryKey: ['games', platform, released, hidden],
    queryFn: ({ pageParam }) => api.discover(PAGE_SIZE, pageParam, platform, released),
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

  return (
    <Page>
      <PageHeader title="Games" icon={Gamepad2}>
        <Options controls={controls}>
          <ViewSwitch value={view} onChange={(next) => controls.set({ view: next })} />
          {platforms.length > 1 ? (
            <Control label="Platform">
              <Segmented
                label="Platform"
                options={[{ value: KEPT, label: 'All' }, ...platforms]}
                value={platform || KEPT}
                onChange={(next) => controls.set({ platform: next })}
              />
            </Control>
          ) : null}
          <Control label="From">
            <Segmented
              label="From"
              options={[
                { value: 'tomorrow', label: 'Tomorrow' },
                { value: 'january', label: 'January' },
              ]}
              value={released ? 'january' : 'tomorrow'}
              onChange={(from) => controls.set({ from })}
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
            {byMonth(list).map(({ month, games: inMonth }) => (
              <Section key={month} title={month} icon={CalendarDays} count={inMonth.length}>
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
