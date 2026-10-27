import {
  ArrowLeft,
  ChevronDown,
  ExternalLink,
  Hourglass,
  Eye,
  EyeOff,
  SquareArrowOutUpRight,
  Star,
} from 'lucide-react'
import { Fragment, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { Artwork, TitleText } from '@/components/MediaCard'
import { Clip, StateIcon } from '@/components/Page'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import { Dialog, DialogClose, DialogContent, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { Spinner } from '@/components/ui/spinner'
import { FavouriteMenu } from '@/components/ItemMenus'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type {
  CountdownTarget,
  Entity,
  FavouriteCategory,
  FavouriteKind,
  Library,
  MakerMode,
  Origin,
  Ref,
  State,
} from '@/lib/api'
import { LIBRARY_NAME, imageSrc } from '@/lib/api'
import { favouriteParam, useFavourite, useFavourites, useMakerFilter } from '@/lib/favourites'
import type { Shape } from '@/lib/items'
import { useDialogBack, withParam } from '@/lib/params'
import { useAddCountdown } from '@/lib/countdowns'
import { usePop } from '@/lib/motion'
import { ahead, cn } from '@/lib/utils'

/**
 * The dialog an item opens in, for every category. Top to bottom: a banner, the head (art,
 * title, meta line, facts, links), a summary, anything the category adds, then the footer
 * with the status line and the actions.
 *
 * From a tablet up everything is sized to the viewport so the dialog never scrolls. The head
 * and the footer are fixed. The banner, the summary and the extras shrink or drop out as the
 * window gets shorter, driven by min-height media queries. A phone's width wraps the chips and
 * the facts onto lines those queries cannot foresee, so there the dialog stacks at natural
 * height and scrolls instead, with the summary whole and every extra shown.
 *
 * Opened from another dialog, a Back above everything else returns to it.
 */
export function MediaDialog({
  open,
  onClose,
  children,
}: {
  open: boolean
  onClose: () => void
  children: React.ReactNode
}) {
  const back = useDialogBack()
  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent
        showCloseButton
        className="block max-h-[94dvh] w-[96vw] gap-0 overflow-y-auto overscroll-contain border-line bg-surface p-0 sm:flex sm:max-w-4xl sm:flex-col sm:overflow-hidden lg:max-w-6xl 2xl:max-w-7xl"
      >
        {back ? (
          <div className="shrink-0 px-5 pt-4 sm:px-6">
            <button
              type="button"
              onClick={back}
              className="inline-flex items-center gap-1.5 text-xs text-ink-dim hover:text-ink focus-visible:outline-accent"
            >
              <ArrowLeft className="size-3.5" />
              Back
            </button>
          </div>
        ) : null}
        {children}
      </DialogContent>
    </Dialog>
  )
}

/**
 * `cover` is for art that is a portrait cover rather than a wide backdrop: the banner runs
 * taller and shows the top of the cover, where the title and the figure usually are.
 */
export function MediaBanner({ image, cover = false }: { image: string | null; cover?: boolean }) {
  return (
    <div
      className={cn(
        'relative shrink-0 overflow-hidden',
        cover
          ? 'h-24 max-sm:h-32 sm:vh760:h-36 sm:vh900:h-48 sm:vh1050:h-64'
          : 'h-16 max-sm:h-24 sm:vh760:h-28 sm:vh900:h-36 sm:vh1050:h-48',
      )}
    >
      {image ? (
        <img
          src={imageSrc(image)}
          alt=""
          className={cn(
            'h-full w-full object-cover',
            cover ? 'scale-105 object-[center_20%] opacity-50 blur-[2px]' : 'opacity-45',
          )}
        />
      ) : (
        <div className="h-full w-full bg-raised" />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-surface to-transparent" />
    </div>
  )
}

export function MediaBody({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-4 p-5 sm:min-h-0 sm:flex-1 sm:overflow-hidden sm:p-6">
      {children}
    </div>
  )
}

export function MediaHead({
  art,
  artLarge,
  shape,
  title,
  library = null,
  meta,
  children,
}: {
  art: string | null
  /** The cover at full size, shown when the art is clicked. */
  artLarge?: string | null
  shape: Shape
  title: string
  /** The Radarr or Sonarr library holding it, which colours the title. */
  library?: Library | null
  /** One line of facts joined with a middle dot. Empty parts are dropped. */
  meta: React.ReactNode[]
  children?: React.ReactNode
}) {
  const [zoomed, setZoomed] = useState(false)
  const parts = meta.filter(Boolean)
  return (
    <div className="flex shrink-0 gap-4 sm:gap-6">
      <div className="hidden w-28 shrink-0 vh620:block vh900:w-40">
        {art ? (
          <button
            type="button"
            aria-label={`Enlarge the cover of ${title}`}
            onClick={() => setZoomed(true)}
            className="block w-full cursor-zoom-in rounded-card focus-visible:outline-accent"
          >
            <Artwork image={art} shape={shape} />
          </button>
        ) : (
          <Artwork image={null} shape={shape} />
        )}
      </div>

      <div className="min-w-0 flex-1 space-y-2.5">
        <DialogTitle className="text-xl leading-tight font-semibold tracking-tight sm:text-2xl vh900:text-3xl">
          <TitleText library={library}>{title}</TitleText>
        </DialogTitle>
        {parts.length ? (
          <Clip className="text-sm text-ink-dim">
            {parts.map((part, i) => (
              <Fragment key={i}>
                {i ? ' · ' : null}
                {part}
              </Fragment>
            ))}
          </Clip>
        ) : null}
        {children}
      </div>

      <ImageZoom
        src={zoomed ? (artLarge ?? art) : null}
        alt={`${title} cover`}
        onClose={() => setZoomed(false)}
      />
    </div>
  )
}

/**
 * An image at the size of the window, stacked on top of the dialog. Radix dismisses the upper
 * layer first, so escape and a click outside close the image and leave the dialog open.
 */
export function ImageZoom({
  src,
  alt,
  onClose,
}: {
  src: string | null
  alt: string
  onClose: () => void
}) {
  return (
    <Dialog open={src !== null} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent
        showCloseButton={false}
        className="w-[94vw] max-w-[94vw] border-none bg-transparent p-0 shadow-none sm:max-w-[94vw]"
      >
        <DialogTitle className="sr-only">{alt}</DialogTitle>
        <DialogClose asChild>
          <button type="button" className="cursor-zoom-out" aria-label="Close">
            <img
              src={src ? imageSrc(src) : undefined}
              alt={alt}
              className="mx-auto max-h-[90dvh] max-w-full rounded-card border border-line"
            />
          </button>
        </DialogClose>
      </DialogContent>
    </Dialog>
  )
}

export function Facts({ children }: { children: React.ReactNode }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2 sm:text-sm">
      {children}
    </dl>
  )
}

export function Fact({ label, value }: { label: string; value?: string[] | null }) {
  if (!value?.length) return null
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-accent">{label}</dt>
      <dd className="min-w-0 flex-1">
        <Clip className="text-ink-dim">{value.join(', ')}</Clip>
      </dd>
    </div>
  )
}

/**
 * A fact naming what releases come from: developers, a cast, authors. Each name opens its
 * favourite's dialog in place of this one, and its star adds or removes it, beside Always hide
 * and Always show, lit while it is.
 * A favourite's star is always shown, any other's only while the name is hovered or focused.
 * A right click offers the favourite's own menu.
 */
export function FavouriteFact({
  label,
  category,
  kind,
  refs,
}: {
  label: string
  category: FavouriteCategory
  kind: FavouriteKind
  refs?: Ref[] | null
}) {
  if (!refs?.length) return null
  // Cut like any other line, but with no tooltip of its own: hovering a name opens its card.
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-accent">{label}</dt>
      {/* Relative so the keyboard only buttons after each name, absolute, stay in its clip. */}
      <dd className="relative min-w-0 flex-1 truncate text-ink-dim">
        {refs.map((ref, i) => (
          <Fragment key={ref.id}>
            {i > 0 ? ', ' : null}
            <FavouriteName entity={{ category, kind, id: ref.id }} name={ref.name} />
          </Fragment>
        ))}
      </dd>
    </div>
  )
}

/** Dialogs that name an item, closed when a favourite opens so only one is ever up. */
const ITEM_PARAMS = ['game', 'title', 'book', 'comic']

function FavouriteName({
  entity,
  name,
}: {
  entity: Pick<Entity, 'category' | 'kind' | 'id'>
  name: string
}) {
  const [params] = useSearchParams()
  const { favourite, loaded, toggle } = useFavourite(entity)
  const popped = usePop(favourite, toggle.isPending)
  const filter = useMakerFilter(entity)
  const navigate = useNavigate()
  const next = new URLSearchParams(params)
  for (const key of ITEM_PARAMS) next.delete(key)
  const to = withParam(next, 'favourite', favouriteParam(entity))
  const star = (props: { className?: string }) => (
    <button
      type="button"
      aria-label={favourite ? `Remove ${name} from favourites` : `Add ${name} to favourites`}
      disabled={!loaded || toggle.isPending}
      onClick={() => toggle.mutate()}
      className={cn('inline-flex items-center gap-1.5 focus-visible:outline-none', props.className)}
    >
      <Star
        key={popped.key}
        className={cn('size-3.5 text-star', favourite && 'fill-star', popped.className)}
      />
      Favourite
    </button>
  )
  const filtering = (mode: MakerMode, props: { className?: string }) => (
    <button
      key={mode}
      type="button"
      aria-pressed={filter.mode === mode}
      disabled={!filter.loaded || filter.set.isPending}
      onClick={() => filter.set.mutate(mode)}
      className={cn(
        'inline-flex items-center gap-1.5 focus-visible:outline-none',
        filter.mode === mode && 'text-accent',
        props.className,
      )}
    >
      {mode === 'hide' ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      {mode === 'hide' ? 'Always hide' : 'Always show'}
    </button>
  )
  return (
    <>
      <ContextMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <ContextMenuTrigger asChild>
              <Link
                to={to}
                className="hover:text-ink focus-visible:text-ink focus-visible:outline-none"
              >
                {name}
                {favourite ? (
                  <Star
                    aria-hidden
                    className="ml-1 inline size-3.5 fill-star align-[-0.125em] text-star"
                  />
                ) : null}
              </Link>
            </ContextMenuTrigger>
          </TooltipTrigger>
          <TooltipContent className="flex flex-col divide-y divide-line p-0">
            {star({ className: 'px-2.5 py-1.5 hover:bg-accent-bg' })}
            {filtering('hide', { className: 'px-2.5 py-1.5 hover:bg-accent-bg' })}
            {filtering('show', { className: 'px-2.5 py-1.5 hover:bg-accent-bg' })}
          </TooltipContent>
        </Tooltip>
        <ContextMenuContent className="min-w-52">
          <ContextMenuItem onSelect={() => void navigate(to)}>
            <SquareArrowOutUpRight />
            Open
          </ContextMenuItem>
          <ContextMenuSeparator />
          <FavouriteMenu entity={{ ...entity, url: null }} />
        </ContextMenuContent>
      </ContextMenu>
      {/* A tooltip is out of reach of the keyboard, so the same action follows the name. */}
      {star({
        className:
          'sr-only text-xs focus-visible:not-sr-only focus-visible:ml-1 focus-visible:text-ink',
      })}
      {(['hide', 'show'] as const).map((mode) =>
        filtering(mode, {
          className:
            'sr-only text-xs focus-visible:not-sr-only focus-visible:ml-1 focus-visible:text-ink',
        }),
      )}
    </>
  )
}

export function Links({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-3">{children}</div>
}

/** `accent` is for the one link that leads to where the item now lives. */
export function OutLink({
  href,
  accent = false,
  children,
}: {
  href: string
  accent?: boolean
  children: React.ReactNode
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn(
        'inline-flex items-center gap-1 text-2xs',
        accent ? 'text-accent hover:text-accent-hi' : 'text-ink-faint hover:text-accent',
      )}
    >
      {children} <ExternalLink className="size-3" />
    </a>
  )
}

/** The summary gives way first as the window gets shorter. */
export function Summary({ children }: { children: React.ReactNode }) {
  return (
    <p className="shrink-0 text-base leading-relaxed text-ink-dim sm:line-clamp-2 sm:vh700:line-clamp-3 sm:vh900:line-clamp-5">
      {children}
    </p>
  )
}

export function MediaFooter({
  status,
  children,
}: {
  /** What Robin is doing with this item, one line above the actions, and why it monitors it. */
  status?: { state: State; text: React.ReactNode; origin?: Origin | null } | null
  children: React.ReactNode
}) {
  return (
    <div className="mt-auto shrink-0 space-y-3 border-t border-line pt-4">
      {status ? (
        <p
          className={cn(
            'flex min-w-0 items-center gap-2 text-xs whitespace-nowrap',
            status.state === 'found' ? 'text-good' : 'text-ink-dim',
          )}
        >
          <StateIcon state={status.state} />
          {status.text}
          {status.origin !== undefined ? <OriginNote origin={status.origin} /> : null}
        </p>
      ) : null}
      {children}
    </div>
  )
}

/** Why Robin monitors an item: your own Monitor, a favourite, opening it while it is one, or the
 * library holding it. */
function OriginNote({ origin }: { origin: Origin | null }) {
  const [params] = useSearchParams()
  const favourites = useFavourites()
  if (origin === null) return <span className="text-ink-faint">· by you</span>
  if (origin.kind !== 'favourite') {
    const app = origin.kind === 'suwayomi' ? 'Suwayomi' : LIBRARY_NAME[origin.kind]
    return <span className="text-ink-faint">· via {app}</span>
  }
  const star = favourites.data?.find((f) => f.id === origin.id)
  const name = (
    <>
      <Star className="size-3 fill-star text-star" />
      {origin.name ?? 'a favourite'}
    </>
  )
  const next = new URLSearchParams(params)
  for (const key of ITEM_PARAMS) next.delete(key)
  return (
    <span className="flex min-w-0 items-center gap-1 text-ink-faint">
      · from
      {star ? (
        <Link
          to={withParam(next, 'favourite', favouriteParam({ ...star, id: star.source_id }))}
          className="inline-flex min-w-0 items-center gap-1 text-ink-dim hover:text-ink"
        >
          {name}
        </Link>
      ) : (
        name
      )}
    </span>
  )
}

/** The action row. `MonitorButton` leads, anything a category adds follows as a ghost. */
export function Actions({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-3">{children}</div>
}

/**
 * Counting down to the item on Home, in every dialog's actions, while its release day is
 * today or ahead.
 */
export function CountdownButton({ target }: { target: CountdownTarget }) {
  const add = useAddCountdown()
  if (!ahead(target.date)) return null
  return (
    <Button
      variant="ghost"
      onClick={() => add.mutate(target)}
      disabled={add.isPending}
      className="gap-2 text-ink-dim hover:text-accent"
    >
      {add.isPending ? <Spinner className="size-4" /> : <Hourglass className="size-4" />}
      Countdown
    </Button>
  )
}

/**
 * Every dialog's main action, the same in every category: Monitor, then Stop monitoring once
 * the item is. Without `onStop` a monitored item offers nothing here. `choices` are radio
 * items picking what is monitored, attached to the button as a split button's menu.
 */
export function MonitorButton({
  monitored,
  pending = false,
  disabled = false,
  onMonitor,
  onStop,
  choices,
}: {
  monitored: boolean
  pending?: boolean
  disabled?: boolean
  onMonitor: () => void
  onStop?: () => void
  choices?: React.ReactNode
}) {
  const popped = usePop(monitored, pending)
  if (monitored && !onStop) return null
  const button = monitored ? (
    <Button
      variant="outline"
      onClick={onStop}
      disabled={pending || disabled}
      className="gap-2 border-line text-ink-dim hover:text-bad"
    >
      {pending ? (
        <Spinner className="size-4" />
      ) : (
        <EyeOff key={popped.key} className={cn('size-4', popped.className)} />
      )}
      Stop monitoring
    </Button>
  ) : (
    <Button onClick={onMonitor} disabled={pending || disabled} className="gap-2">
      {pending ? (
        <Spinner className="size-4" />
      ) : (
        <Eye key={popped.key} className={cn('size-4', popped.className)} />
      )}
      Monitor
    </Button>
  )
  if (!choices) return button
  return (
    <ButtonGroup>
      {button}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant={monitored ? 'outline' : 'default'}
            size="icon"
            disabled={pending}
            aria-label="Choose what to monitor"
            className={monitored ? 'border-line text-ink-dim' : undefined}
          >
            <ChevronDown className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-64">
          {choices}
        </DropdownMenuContent>
      </DropdownMenu>
    </ButtonGroup>
  )
}
