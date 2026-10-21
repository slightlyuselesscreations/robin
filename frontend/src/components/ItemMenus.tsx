import { useQuery } from '@tanstack/react-query'
import {
  BookmarkCheck,
  BookmarkPlus,
  Check,
  CirclePlus,
  ExternalLink,
  Eye,
  EyeOff,
  Star,
  StarOff,
  TriangleAlert,
} from 'lucide-react'

import {
  ContextMenuItem,
  ContextMenuRadioGroup,
  ContextMenuRadioItem,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from '@/components/ui/context-menu'
import { Spinner } from '@/components/ui/spinner'
import {
  type BookDetail,
  type Comic,
  type Entity,
  type ScreenKind,
  type Series,
  api,
  errorText,
} from '@/lib/api'
import { useArrAdd } from '@/lib/arr'
import { useBookReminders, useShelf } from '@/lib/bookReminders'
import { SOURCE, useFavourite, useMakerFilter } from '@/lib/favourites'
import { comicMonitorOf, fromComicVine } from '@/lib/items'
import { useAddSeries, useComicMonitor, useGameMonitor } from '@/lib/monitor'
import { currentChoice, reminderChoices, typesFor, useReminders } from '@/lib/reminders'
import { useSettings } from '@/lib/categories'
import { gameMonitorable, outBeforeMonth } from '@/lib/utils'

/*
 * What a right click on an item offers beyond opening it, one menu per category. Each reads
 * what it needs when the menu opens, so a list of hundreds asks nothing until one is used.
 */

/** A link out of Robin, opened in a new tab. */
function OutItem({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <ContextMenuItem asChild>
      <a href={href} target="_blank" rel="noreferrer">
        <ExternalLink />
        {children}
      </a>
    </ContextMenuItem>
  )
}

/** Monitor a game with the generated patterns, or stop monitoring it. */
export function GameMenu({
  igdbId,
  released,
  platforms = [],
  url,
}: {
  igdbId: number
  /** Its release timestamp and platforms: one out offers Monitor only to be grabbed. */
  released: number | null
  platforms?: string[]
  url?: string | null
}) {
  const monitored = useQuery({ queryKey: ['monitored'], queryFn: api.monitored })
  const entry = monitored.data?.find((row) => row.igdb_id === igdbId)
  const { start, stop } = useGameMonitor()
  const prowlarrReady = useSettings().data?.prowlarr_ready ?? false
  return (
    <>
      {entry ? (
        <ContextMenuItem variant="destructive" onSelect={() => stop.mutate(entry)}>
          <EyeOff />
          Stop monitoring
        </ContextMenuItem>
      ) : !gameMonitorable(released, platforms, prowlarrReady) ? null : (
        <ContextMenuItem
          disabled={!monitored.isSuccess}
          onSelect={() => start.mutate({ igdb_id: igdbId })}
        >
          <Eye />
          Monitor
        </ContextMenuItem>
      )}
      {url ? <OutItem href={url}>IGDB</OutItem> : null}
    </>
  )
}

/** Monitor the series a #1 starts, or stop monitoring it. `week` is unknown once monitored. */
export function ComicMenu({ comic, week }: { comic: Comic; week?: string }) {
  const monitored = useQuery({ queryKey: ['comics-monitored'], queryFn: api.monitoredComics })
  const monitor = comicMonitorOf(monitored.data, comic)
  const { start, stop } = useComicMonitor()
  return (
    <>
      {monitor ? (
        <ContextMenuItem variant="destructive" onSelect={() => stop.mutate(monitor)}>
          <EyeOff />
          Stop monitoring
        </ContextMenuItem>
      ) : week ? (
        <ContextMenuItem
          disabled={!monitored.isSuccess}
          onSelect={() => start.mutate({ comic, week })}
        >
          <Eye />
          Monitor
        </ContextMenuItem>
      ) : null}
      <OutItem href={comic.url}>
        {fromComicVine(comic) ? 'Comic Vine' : 'League of Comic Geeks'}
      </OutItem>
    </>
  )
}

/** Add a series the Suwayomi source lists to the library. */
export function SeriesMenu({ series }: { series: Series }) {
  const add = useAddSeries()
  return series.inLibrary ? null : (
    <ContextMenuItem onSelect={() => add.mutate(series.id)}>
      <Eye />
      Monitor
    </ContextMenuItem>
  )
}

/**
 * Monitor a title, which is a reminder, or stop. A film's is picked from a submenu, cinema
 * only, digital only or both. A show's covers every season premiere. Left out while Screens notifications are
 * off.
 */
export function ScreenMenu({ kind, id }: { kind: ScreenKind; id: number }) {
  const { ready, mine, choose } = useReminders(kind, id)
  const arr = useArrAdd(kind, id)
  const detail = useQuery({
    queryKey: ['screen-title', kind, id],
    queryFn: () => api.screenTitle(kind, id),
    enabled: ready,
    staleTime: 60 * 60_000,
  })
  const set = mine.length > 0
  const choices = reminderChoices(detail.data ?? { releases: [], open_releases: [] })
  // Hidden once the title is read and has nothing ahead, which a film out already never has.
  const offered = set || !detail.data || detail.data.monitorable
  return (
    <>
      {ready && kind === 'movie' && offered ? (
        <ContextMenuSub>
          <ContextMenuSubTrigger className="gap-2">
            <Eye />
            Monitor
          </ContextMenuSubTrigger>
          <ContextMenuSubContent className="min-w-64">
            {detail.isPending ? (
              <ContextMenuItem disabled>
                <Spinner />
                Reading releases
              </ContextMenuItem>
            ) : (
              <ContextMenuRadioGroup
                value={currentChoice(mine) ?? ''}
                onValueChange={(value) =>
                  choose.mutate(typesFor(choices, currentChoice(mine), value))
                }
              >
                {choices.map((choice) => (
                  <ContextMenuRadioItem
                    key={choice.value}
                    value={choice.value}
                    disabled={choice.disabled}
                  >
                    {choice.label}
                  </ContextMenuRadioItem>
                ))}
              </ContextMenuRadioGroup>
            )}
          </ContextMenuSubContent>
        </ContextMenuSub>
      ) : null}
      {ready && kind === 'tv' && !set && detail.data?.monitorable ? (
        <ContextMenuItem onSelect={() => choose.mutate([undefined])}>
          <Eye />
          Monitor
        </ContextMenuItem>
      ) : null}
      {ready && set ? (
        <ContextMenuItem variant="destructive" onSelect={() => choose.mutate([])}>
          <EyeOff />
          Stop monitoring
        </ContextMenuItem>
      ) : null}
      {arr.offered ? (
        <ContextMenuItem onSelect={() => arr.add.mutate()}>
          <CirclePlus />
          {arr.label}
        </ContextMenuItem>
      ) : null}
      <OutItem href={`https://www.themoviedb.org/${kind}/${id}`}>TMDB</OutItem>
    </>
  )
}

/**
 * Monitor a book, which is a reminder, or stop, and shelve it as Want to Read on Hardcover. The
 * book is read when the menu opens, for its page on Hardcover.
 */
export function BookMenu({ id }: { id: number }) {
  const detail = useQuery({
    queryKey: ['book', id],
    queryFn: () => api.book(id),
    staleTime: 60 * 60_000,
  })
  if (!detail.data)
    return (
      <>
        <ContextMenuItem disabled>
          {detail.isError ? <TriangleAlert className="text-bad" /> : <Spinner />}
          {detail.isError
            ? errorText(detail.error, 'Hardcover is unreachable')
            : 'Reading the book'}
        </ContextMenuItem>
        <OutItem href={`https://hardcover.app/books/${id}`}>Hardcover</OutItem>
      </>
    )
  return <BookMenuFor book={detail.data} />
}

function BookMenuFor({ book }: { book: BookDetail }) {
  const { ready, mine, choose } = useBookReminders(book)
  const shelf = useShelf(book.id)
  const set = mine.length > 0
  return (
    <>
      {ready && !set && !outBeforeMonth(book.date) ? (
        <ContextMenuItem onSelect={() => choose.mutate(true)}>
          <Eye />
          Monitor
        </ContextMenuItem>
      ) : null}
      {ready && set ? (
        <ContextMenuItem variant="destructive" onSelect={() => choose.mutate(false)}>
          <EyeOff />
          Stop monitoring
        </ContextMenuItem>
      ) : null}
      <ContextMenuItem
        disabled={!shelf.loaded || shelf.set.isPending}
        onSelect={() => shelf.set.mutate(!shelf.want)}
      >
        {shelf.want ? <BookmarkCheck /> : <BookmarkPlus />}
        {shelf.want ? 'Take off Want to Read' : 'Want to Read'}
      </ContextMenuItem>
      <OutItem href={book.hardcover}>Hardcover</OutItem>
    </>
  )
}

/** Star a developer, person, studio, network, author or series, or unstar it. */
export function FavouriteMenu({
  entity,
}: {
  entity: Pick<Entity, 'category' | 'kind' | 'id' | 'url'>
}) {
  const { favourite, loaded, toggle } = useFavourite(entity)
  const filter = useMakerFilter(entity)
  return (
    <>
      <ContextMenuItem
        variant={favourite ? 'destructive' : 'default'}
        disabled={!loaded || toggle.isPending}
        onSelect={() => toggle.mutate()}
      >
        {favourite ? <StarOff /> : <Star />}
        {favourite ? 'Remove from favourites' : 'Add to favourites'}
      </ContextMenuItem>
      {(['hide', 'show'] as const).map((mode) => (
        <ContextMenuItem
          key={mode}
          disabled={!filter.loaded || filter.set.isPending}
          onSelect={() => filter.set.mutate(mode)}
          className={filter.mode === mode ? 'text-accent' : undefined}
        >
          {filter.mode === mode ? <Check /> : mode === 'hide' ? <EyeOff /> : <Eye />}
          {mode === 'hide' ? 'Always hide' : 'Always show'}
        </ContextMenuItem>
      ))}
      {entity.url ? <OutItem href={entity.url}>{SOURCE[entity.category]}</OutItem> : null}
    </>
  )
}
