import { useQuery } from '@tanstack/react-query'
import { Eye, EyeOff, Star, StarOff, Trash2 } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { BookMenu, ComicMenu, FavouriteMenu, GameMenu, ScreenMenu } from '@/components/ItemMenus'
import { Items } from '@/components/MediaCard'
import {
  Actions,
  Links,
  MediaBody,
  MediaDialog,
  MediaFooter,
  MediaHead,
  OutLink,
} from '@/components/MediaDialog'
import { Notice, Section, Sections } from '@/components/Page'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  type Book,
  type Comic,
  type Entity,
  type FavouriteCategory,
  type Game,
  type ScreenTitle,
  type View,
  LIBRARY_NAME,
  api,
  errorText,
} from '@/lib/api'
import {
  KINDS,
  KIND_ICON,
  KIND_LABEL,
  SOURCE,
  favouriteParam,
  findFavourite,
  useFavourite,
  useMakerFilter,
  useFavourites,
} from '@/lib/favourites'
import { askArrRemove, heldOf, useLibrary } from '@/lib/arr'
import {
  type Item,
  bookItem,
  bookRemindersOf,
  comicItem,
  comicMonitorOf,
  entityItem,
  gameItem,
  screenItem,
} from '@/lib/items'
import { withParam } from '@/lib/params'
import { usePop } from '@/lib/motion'
import { cn } from '@/lib/utils'

/**
 * What a search found that releases come from, one panel per kind, each opening its dialog.
 * Shown under the titles a category's search found.
 */
export function FavouriteSections({
  category,
  entities,
  view,
  title,
}: {
  category: FavouriteCategory
  entities: Entity[]
  view: View
  /** In place of each kind's own heading, for a list narrowed to one. */
  title?: string
}) {
  const [params] = useSearchParams()
  const favourites = useFavourites()
  const starred = (e: Entity) => findFavourite(favourites.data, e) !== null
  return KINDS[category].map((kind) => {
    const found = entities.filter((e) => e.kind === kind)
    if (!found.length) return null
    return (
      <Section
        key={kind}
        title={title ?? KIND_LABEL[kind]}
        icon={KIND_ICON[kind]}
        count={found.length}
      >
        <Items
          view={view}
          items={found.map((e) => ({
            ...entityItem(e, withParam(params, 'favourite', favouriteParam(e)), starred(e)),
            menu: <FavouriteMenu entity={e} />,
          }))}
        />
      </Section>
    )
  })
}

/** One favourite, `?favourite=<category>-<kind>-<id>`, with what it has coming. */
export function FavouriteDialog({
  open,
  onClose,
}: {
  open: Pick<Entity, 'category' | 'kind' | 'id'> | null
  onClose: () => void
}) {
  return (
    <MediaDialog open={open !== null} onClose={onClose}>
      {open ? <Body open={open} /> : null}
    </MediaDialog>
  )
}

function Body({ open }: { open: Pick<Entity, 'category' | 'kind' | 'id'> }) {
  const detail = useQuery({
    queryKey: ['favourite', open.category, open.kind, open.id],
    queryFn: () => api.favourite(open.category, open.kind, open.id),
    staleTime: 10 * 60_000,
  })
  const mine = findFavourite(useFavourites().data, open)
  if (detail.isPending)
    return (
      <div className="flex h-72 items-center justify-center">
        <Spinner className="size-8 text-ink-dim" />
      </div>
    )
  if (detail.isError)
    return (
      <div className="p-6">
        <Notice tone="bad">
          {errorText(detail.error, `${SOURCE[open.category]} is unreachable`)}
        </Notice>
      </div>
    )
  const { entity, releases } = detail.data
  return (
    <MediaBody>
      <MediaHead
        art={entity.image}
        shape="cover"
        title={entity.name}
        meta={[entity.meta, mine?.monitored ? `${mine.monitored} monitored` : null]}
      >
        {entity.url ? (
          <Links>
            <OutLink href={entity.url}>{SOURCE[entity.category]}</OutLink>
          </Links>
        ) : null}
      </MediaHead>
      <div className="min-h-0 sm:flex-1 sm:overflow-y-auto">
        {releases.length ? (
          <Sections>
            <Section
              title="Coming"
              count={releases.length}
              action={
                entity.category === 'screens' ? (
                  <RemoveHeld releases={releases as ScreenTitle[]} />
                ) : null
              }
            >
              <Releases category={entity.category} releases={releases} />
            </Section>
          </Sections>
        ) : (
          <Notice>Nothing coming yet.</Notice>
        )}
      </div>
      <Footer entity={entity} />
    </MediaBody>
  )
}

/** What a favourite has coming, as its category lists it. Each opens its own dialog. */
function Releases({
  category,
  releases,
}: {
  category: FavouriteCategory
  releases: (Game | ScreenTitle | Book | Comic)[]
}) {
  const [params] = useSearchParams()
  const comics = useQuery({
    queryKey: ['comics-monitored'],
    queryFn: api.monitoredComics,
    enabled: category === 'comics',
  })
  const screenReminders = useQuery({ queryKey: ['screen-reminders'], queryFn: api.reminders })
  const inLibrary = useLibrary()
  const bookReminders = useQuery({ queryKey: ['book-reminders'], queryFn: api.bookReminders })
  // Opening a release closes this dialog, so the release's own opens alone.
  const open = (key: string, value: string | number) => {
    const next = new URLSearchParams(params)
    next.delete('favourite')
    return withParam(next, key, value)
  }
  let items: Item[]
  if (category === 'games') {
    items = (releases as Game[]).map((g) => ({
      ...gameItem(g, open('game', g.igdb_id)),
      menu: (
        <GameMenu
          igdbId={g.igdb_id}
          released={g.first_release_date}
          platforms={g.platforms}
          url={g.url}
        />
      ),
    }))
  } else if (category === 'comics') {
    items = (releases as Comic[]).map((c) => ({
      ...comicItem(c, open('comic', c.id), comicMonitorOf(comics.data, c), c.date ?? undefined),
      menu: <ComicMenu comic={c} week={c.date ?? undefined} />,
    }))
  } else if (category === 'screens') {
    items = (releases as ScreenTitle[]).map((t) => ({
      ...screenItem(
        t,
        open('title', `${t.kind}-${t.id}`),
        new Map(),
        (screenReminders.data ?? []).filter((r) => r.kind === t.kind && r.tmdb_id === t.id),
        inLibrary(`${t.kind}-${t.id}`),
      ),
      menu: <ScreenMenu kind={t.kind} id={t.id} />,
      action: <RemoveHeld releases={[t]} />,
    }))
  } else {
    items = (releases as Book[]).map((b) => ({
      ...bookItem(b, open('book', b.id), bookRemindersOf(b, bookReminders.data ?? [])),
      menu: <BookMenu id={b.id} />,
    }))
  }
  return <Items view="list" compact metaLabel="Release" items={items} />
}

/**
 * Removing from Radarr or Sonarr what of `releases` either holds: one title on its row, every
 * one of them in the header. Left out while neither holds any.
 */
function RemoveHeld({ releases }: { releases: ScreenTitle[] }) {
  const held = heldOf(useLibrary(), releases)
  if (!held.length) return null
  const apps = [...new Set(held.map((t) => LIBRARY_NAME[t.library]))].join(' and ')
  if (releases.length === 1)
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => askArrRemove(held)}
            aria-label={`Remove from ${apps}`}
            className="size-7 text-ink-faint hover:text-bad"
          >
            <Trash2 className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Remove from {apps}</TooltipContent>
      </Tooltip>
    )
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => askArrRemove(held)}
      className="h-7 gap-1.5 px-2 text-xs text-ink-dim hover:text-bad"
    >
      <Trash2 className="size-3.5" />
      Remove {held.length} from {apps}
    </Button>
  )
}

/**
 * The dialog's main action: star it, or unstar it once it is a favourite. Beside it, always
 * hiding or always showing everything it made, lit while it is.
 */
function Footer({ entity }: { entity: Entity }) {
  const { favourite, loaded, toggle } = useFavourite(entity)
  const popped = usePop(favourite, toggle.isPending)
  const filter = useMakerFilter(entity)
  return (
    <MediaFooter>
      <Actions>
        {favourite ? (
          <Button
            variant="outline"
            onClick={() => toggle.mutate()}
            disabled={toggle.isPending}
            className="gap-2 border-line text-ink-dim hover:text-bad"
          >
            {toggle.isPending ? (
              <Spinner className="size-4" />
            ) : (
              <StarOff key={popped.key} className={cn('size-4', popped.className)} />
            )}
            Remove from favourites
          </Button>
        ) : (
          <Button
            onClick={() => toggle.mutate()}
            disabled={!loaded || toggle.isPending}
            className="gap-2"
          >
            {toggle.isPending ? (
              <Spinner className="size-4" />
            ) : (
              <Star key={popped.key} className={cn('size-4', popped.className)} />
            )}
            Add to favourites
          </Button>
        )}
        {(['hide', 'show'] as const).map((mode) => (
          <Button
            key={mode}
            variant="ghost"
            onClick={() => filter.set.mutate(mode)}
            disabled={!filter.loaded || filter.set.isPending}
            className={cn(
              'gap-2',
              filter.mode === mode ? 'text-accent' : 'text-ink-dim hover:text-ink',
            )}
          >
            {mode === 'hide' ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            {mode === 'hide' ? 'Always hide' : 'Always show'}
          </Button>
        ))}
      </Actions>
    </MediaFooter>
  )
}
