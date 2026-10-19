import { Hourglass, SquareArrowOutUpRight, Star } from 'lucide-react'
import { useAddCountdown } from '@/lib/countdowns'
import { type ReactElement, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Clip, FlyingLogo, Robin, StatusGlyph, Tip } from '@/components/Page'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { LIBRARY_CLASS } from '@/lib/arr'
import { LIBRARY_NAME, type Library, type View, imageSrc } from '@/lib/api'
import type { Item, PlatformTag, Shape } from '@/lib/items'
import { riseAt } from '@/lib/motion'
import { useUpdated } from '@/lib/outdated'
import { ahead, cn } from '@/lib/utils'

const ASPECT: Record<Shape, string> = { poster: 'aspect-[3/4]', cover: 'aspect-[2/3]' }

/**
 * Artwork in its category shape, and nothing on it: covers stay clean. The edge is drawn by
 * an overlay, because an inset ring on the box itself paints under the image.
 */
export function Artwork({
  image,
  shape,
  settled = false,
  className,
}: {
  image: string | null
  shape: Shape
  settled?: boolean
  className?: string
}) {
  // An image that fails to load, as a slow Suwayomi's covers do, shows the robin instead.
  const [failed, setFailed] = useState<string | null>(null)
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-card bg-raised transition-opacity',
        'after:pointer-events-none after:absolute after:inset-0 after:rounded-card after:ring-1 after:ring-ink/6 after:ring-inset',
        settled && 'opacity-40 group-hover:opacity-100 group-focus-visible:opacity-100',
        ASPECT[shape],
        className,
      )}
    >
      {image && failed !== image ? (
        <img
          src={imageSrc(image)}
          alt=""
          loading="lazy"
          onError={() => setFailed(image)}
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-ink-faint">
          <Robin className="w-1/2 max-w-24 opacity-50" />
        </div>
      )}
    </div>
  )
}

/**
 * A right click on an item: open it, then whatever its category offers. The menu's own items
 * are mounted only while it is open.
 */
function ItemMenu({ item, children }: { item: Item; children: React.ReactElement }) {
  const navigate = useNavigate()
  const countdown = useAddCountdown()
  const counted = item.countdown && ahead(item.countdown.date) ? item.countdown : null
  if (!item.menu && !counted) return children
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent className="min-w-52">
        <ContextMenuItem onSelect={() => void navigate(item.to)}>
          <SquareArrowOutUpRight />
          Open
        </ContextMenuItem>
        {counted ? (
          <ContextMenuItem onSelect={() => countdown.mutate(counted)}>
            <Hourglass />
            Countdown
          </ContextMenuItem>
        ) : null}
        <ContextMenuSeparator className="last:hidden" />
        {item.menu}
      </ContextMenuContent>
    </ContextMenu>
  )
}

/** The favourite an item comes from: a star right of its name, naming it on hover. */
export function FavouriteStar({ name }: { name: string }) {
  return (
    <Tip content={`Favourite: ${name}`}>
      <Star aria-label={`Favourite: ${name}`} className="size-3.5 shrink-0 fill-star text-star" />
    </Tip>
  )
}

/** The status glyph, then the title, then the favourite star, on one line. */
/** A title, in the colour of the Radarr or Sonarr library holding it. */
export function TitleText({
  library,
  className,
  children,
}: {
  library: Library | null
  className?: string
  children: React.ReactNode
}) {
  return (
    <Clip className={className}>
      {/* On the text alone, so it wins over the ink colour the line is given. */}
      {library ? <span className={LIBRARY_CLASS[library]}>{children}</span> : children}
      {library ? <span className="sr-only">, in {LIBRARY_NAME[library]}</span> : null}
    </Clip>
  )
}

function Title({ item, className }: { item: Item; className?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      {item.status ? <StatusGlyph status={item.status} /> : null}
      <TitleText
        library={item.library}
        className={cn('leading-tight font-medium text-ink', className)}
      >
        {item.title}
      </TitleText>
      {item.favourite ? <FavouriteStar name={item.favourite} /> : null}
    </div>
  )
}

/**
 * The release tag. A film's digital release, or a show, names its platform instead, cut to
 * fit. A film's tooltip carries the whole name and the date, a show's the whole name only
 * once it is cut. A tag with a `tip` says it on hover, a book's series and its place in it.
 */
export function ReleaseTag({
  tag,
  tip,
  platform,
  className,
}: {
  tag?: string | null
  tip?: string | null
  platform?: PlatformTag | null
  className?: string
}) {
  const style = 'min-w-0 truncate font-semibold uppercase text-accent'
  if (platform && !platform.detail)
    return <Clip className={cn(style, 'max-w-28 shrink-[4]', className)}>{platform.name}</Clip>
  if (platform)
    return (
      <Tip
        content={
          <>
            <span className="block font-medium">{platform.name}</span>
            {platform.detail ? <span className="block text-ink-dim">{platform.detail}</span> : null}
          </>
        }
      >
        <span className={cn(style, 'max-w-28 shrink-[4]', className)}>{platform.name}</span>
      </Tip>
    )
  if (!tag) return null
  const shown = <span className={cn(style, className)}>{tag}</span>
  return tip ? <Tip content={tip}>{shown}</Tip> : shown
}

/** The meta line, with the release tag held against its far end. */
function Meta({ item, className }: { item: Item; className?: string }) {
  if (!item.meta && !item.tag && !item.platform) return null
  return (
    <div className={cn('flex items-baseline gap-3 text-2xs text-ink-faint', className)}>
      {/* A date is whole, the tag gives way first. */}
      {item.meta ? (
        <Clip className={cn((item.tag || item.platform) && 'shrink-0')}>{item.meta}</Clip>
      ) : null}
      <ReleaseTag tag={item.tag} tip={item.tagTip} platform={item.platform} className="ml-auto" />
    </div>
  )
}

/** Each field as one line of label and value, for a compact card. */
function FieldLines({ item }: { item: Item }) {
  return item.fields?.map((field) =>
    field.value ? (
      <Clip key={field.label} className="text-2xs text-ink-faint">
        {field.label}{' '}
        <span className={cn('text-ink-dim', toneClass(field.tone))}>{field.value}</span>
      </Clip>
    ) : null,
  )
}

const toneClass = (tone?: 'good' | 'bad') =>
  tone === 'good' ? 'text-good' : tone === 'bad' ? 'text-bad' : undefined

/** Hands `children` the class that rings the item when Reload brought it in new or changed. */
function Updated({ item, children }: { item: Item; children: (ring?: string) => ReactElement }) {
  return children(useUpdated(item))
}

export function MediaCard({
  item,
  compact = false,
  i = 0,
}: {
  item: Item
  compact?: boolean
  /** Its place in the wave its grid rises in as it is first drawn. */
  i?: number
}) {
  const ring = useUpdated(item)
  return (
    <ItemMenu item={item}>
      <Link
        to={item.to}
        className={cn('group block rounded-card focus-visible:outline-accent', ring)}
      >
        {/* Apart from the link, whose own animation is the glow Reload rings it with. */}
        <div className="rise" style={riseAt(i, 20)}>
          <Artwork image={item.image} shape={item.shape} settled={item.settled} />
          <div className="mt-2 space-y-0.5">
            <Title item={item} className="text-sm" />
            <Meta item={item} />
            {compact ? <FieldLines item={item} /> : null}
          </div>
        </div>
      </Link>
    </ItemMenu>
  )
}

export function MediaGrid({
  compact = false,
  children,
}: {
  compact?: boolean
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'grid gap-3 p-4 sm:gap-4',
        compact
          ? 'grid-cols-[repeat(auto-fill,minmax(96px,1fr))]'
          : 'grid-cols-[repeat(auto-fill,minmax(130px,1fr))]',
      )}
    >
      {children}
    </div>
  )
}

/** A compact row: a small cover, then title, meta and every field on one line. */
function CompactList({ items }: { items: Item[] }) {
  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <Updated key={item.key} item={item}>
          {(ring) => (
            <li className={cn('flex items-center', ring)}>
              <ItemMenu item={item}>
                <Link
                  to={item.to}
                  className="group flex min-w-0 flex-1 items-center gap-3 px-4 py-2 transition-colors hover:bg-raised/50 focus-visible:outline-accent"
                >
                  <Artwork image={item.image} shape={item.shape} className="w-8 shrink-0" />
                  <div className="flex min-w-0 flex-1 items-baseline gap-4">
                    <div className="w-64 max-w-[40%] shrink-0">
                      <Title item={item} className="text-sm" />
                    </div>
                    <Meta item={item} className="min-w-0 flex-1 font-mono" />
                    {item.fields?.map((field) =>
                      field.value ? (
                        <span key={field.label} className="shrink-0 text-2xs text-ink-faint">
                          {field.label}{' '}
                          <span className={cn('text-ink-dim', toneClass(field.tone))}>
                            {field.value}
                          </span>
                        </span>
                      ) : null,
                    )}
                  </div>
                </Link>
              </ItemMenu>
              {item.action ? <div className="shrink-0 pr-2">{item.action}</div> : null}
            </li>
          )}
        </Updated>
      ))}
    </ul>
  )
}

function MediaList({ items }: { items: Item[] }) {
  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <Updated key={item.key} item={item}>
          {(ring) => (
            <li className={ring}>
              <ItemMenu item={item}>
                <Link
                  to={item.to}
                  className="group flex gap-4 px-4 py-3 transition-colors hover:bg-raised/50 focus-visible:outline-accent"
                >
                  <Artwork
                    image={item.image}
                    shape={item.shape}
                    settled={item.settled}
                    className="w-16 shrink-0 self-start"
                  />
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="space-y-0.5">
                      <Title item={item} className="text-base" />
                      <Meta item={item} className="text-xs" />
                    </div>
                    {item.fields?.some((f) => f.value) ? (
                      <dl className="space-y-1">
                        {item.fields.map((field) =>
                          field.value ? (
                            <div key={field.label} className="flex gap-3 text-xs">
                              <dt className="w-20 shrink-0 text-ink-faint">{field.label}</dt>
                              <dd className="min-w-0 flex-1">
                                <Clip
                                  className={cn(
                                    'text-ink-dim',
                                    field.mono && 'font-mono text-2xs leading-5',
                                    field.tone === 'good' && 'text-good',
                                    field.tone === 'bad' && 'text-bad',
                                  )}
                                >
                                  {field.value}
                                </Clip>
                              </dd>
                            </div>
                          ) : null,
                        )}
                      </dl>
                    ) : null}
                  </div>
                </Link>
              </ItemMenu>
            </li>
          )}
        </Updated>
      ))}
    </ul>
  )
}

function MediaTable({ items, metaLabel }: { items: Item[]; metaLabel?: string }) {
  const columns = items[0]?.fields?.map((field) => field.label) ?? []
  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow className="border-line hover:bg-transparent">
          <TableHead className="w-full px-4 text-ink-faint">Title</TableHead>
          {metaLabel ? <TableHead className="px-3 text-ink-faint">{metaLabel}</TableHead> : null}
          {columns.map((label) => (
            <TableHead key={label} className="px-3 text-ink-faint last:pr-4">
              {label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <Updated key={item.key} item={item}>
            {(ring) => (
              <ItemMenu item={item}>
                <TableRow className={cn('border-line/60 hover:bg-raised/50', ring)}>
                  <TableCell className="max-w-0 px-4">
                    <div className="flex items-center gap-1.5">
                      {item.status ? <StatusGlyph status={item.status} /> : null}
                      <Link to={item.to} className="min-w-0 text-ink hover:text-accent">
                        <TitleText library={item.library}>{item.title}</TitleText>
                      </Link>
                      {item.favourite ? <FavouriteStar name={item.favourite} /> : null}
                    </div>
                  </TableCell>
                  {metaLabel ? (
                    <TableCell className="max-w-64 px-3 text-ink-dim">
                      <div className="flex items-baseline gap-3">
                        <Clip>{item.meta}</Clip>
                        <ReleaseTag
                          tag={item.tag}
                          tip={item.tagTip}
                          platform={item.platform}
                          className="ml-auto"
                        />
                      </div>
                    </TableCell>
                  ) : null}
                  {item.fields?.map((field) => (
                    <TableCell
                      key={field.label}
                      className={cn(
                        'max-w-64 px-3 text-ink-dim last:pr-4',
                        field.mono && 'font-mono text-2xs',
                        field.tone === 'good' && 'text-good',
                        field.tone === 'bad' && 'text-bad',
                      )}
                    >
                      <Clip>{field.value ?? '-'}</Clip>
                    </TableCell>
                  ))}
                </TableRow>
              </ItemMenu>
            )}
          </Updated>
        ))}
      </TableBody>
    </Table>
  )
}

/**
 * Items in the chosen view, meant to sit inside a `Section` panel. `compact` is for a panel of
 * items that are done with: smaller, and every view shows the same few facts, title, meta and
 * fields, each on one line.
 */
export function Items({
  items,
  view,
  metaLabel,
  compact = false,
}: {
  items: Item[]
  view: View
  /** The table column the meta line goes in. Without one the table has no such column. */
  metaLabel?: string
  compact?: boolean
}) {
  if (view === 'list') return compact ? <CompactList items={items} /> : <MediaList items={items} />
  if (view === 'table') return <MediaTable items={items} metaLabel={metaLabel} />
  return (
    <MediaGrid compact={compact}>
      {/* The wave starts over every 24 cards, so a page appended below rises at once. */}
      {items.map((item, i) => (
        <MediaCard key={item.key} item={item} compact={compact} i={i % 24} />
      ))}
    </MediaGrid>
  )
}

/** The robin in flight over a grid on its way. */
export function GridLoading() {
  return (
    <div className="flex items-center justify-center gap-2.5 px-4 py-3 text-xs text-ink-faint">
      <FlyingLogo small />
      The grid is loading, please keep flying
    </div>
  )
}

export function Skeletons({ shape, count }: { shape: Shape; count: number }) {
  return (
    <div className="rounded-card border border-line bg-surface shadow-raised">
      <GridLoading />
      <MediaGrid>
        {Array.from({ length: count }, (_, i) => (
          <div key={i}>
            <Skeleton className={cn('rounded-card bg-raised', ASPECT[shape])} />
            <Skeleton className="mt-2 h-3 w-4/5 rounded-sm bg-raised" />
            <Skeleton className="mt-1.5 h-2.5 w-8 rounded-sm bg-raised" />
          </div>
        ))}
      </MediaGrid>
    </div>
  )
}
