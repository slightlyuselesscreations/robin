import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, RefreshCw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { Artwork, FavouriteStar, TitleText } from '@/components/MediaCard'
import { Clip, HealthWord, Notice, PanelBody, PanelEmpty, StateIcon, Tip } from '@/components/Page'
import { Calendar } from '@/components/ui/calendar'
import { Progress } from '@/components/ui/progress'
import { Spinner } from '@/components/ui/spinner'
import { SERVICES, STATE_LABEL, type Torrent, api, releaseSize, errorText } from '@/lib/api'
import { CATEGORY } from '@/lib/categories'
import {
  type CategoryKey,
  type Tracked,
  useOverviewLoading,
  useTracked,
  useTrackedCategories,
  useUpcoming,
} from '@/lib/tracked'
import { useCountdowns } from '@/lib/countdowns'
import { cn, controlClass, monthStart } from '@/lib/utils'

// Every panel here that lists what Robin watches reads `useTracked`, or `useUpcoming` for what
// comes out, never a category's own list, so a category added to `TRACKED` reaches all of them.

const DAY = 86_400_000

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString()

/** Whole days from today to a release day, negative once it is past. */
function daysTo(day: Date): number {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((day.getTime() - today.getTime()) / DAY)
}

/** Days to a release in words. Past ones count back. */
function countdown(days: number): string {
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  if (days === -1) return 'Yesterday'
  return days > 0 ? `${days} days` : `${-days} days ago`
}

/** The line under a title: its category, then what kind of release it is. */
function Kind({ category, tag }: { category: CategoryKey; tag?: string | null }) {
  return (
    <span className="text-2xs font-semibold text-accent uppercase">
      {[CATEGORY[category].label, tag].filter(Boolean).join(' - ')}
    </span>
  )
}

/**
 * One line of every Home list, the same in each panel: cover, glyph, title with its category
 * and tag under it, then the release date, left out where the list already names the day, and
 * the days to it.
 */
function Row({ item, dated = true }: { item: Tracked; dated?: boolean }) {
  const days = item.release ? daysTo(item.release) : null
  return (
    <li>
      <Link
        to={item.to}
        className="group flex items-center gap-3 px-4 py-2 transition-colors hover:bg-raised/50 focus-visible:outline-accent"
      >
        <Artwork image={item.image} shape={item.shape} className="w-8 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {item.state ? <StateIcon state={item.state} /> : null}
            <TitleText library={item.library} className="text-sm font-medium text-ink">
              {item.title}
            </TitleText>
            {item.favourite ? <FavouriteStar name={item.favourite} /> : null}
          </div>
          <Kind category={item.category} tag={item.tag} />
        </div>
        {dated && item.releaseText ? (
          <Clip className="hidden max-w-[40%] font-mono text-2xs text-ink-faint sm:block">
            {item.releaseText}
          </Clip>
        ) : null}
        {days === null ? null : (
          <span
            className={cn(
              'shrink-0 text-xs font-medium',
              days >= 0 ? 'text-accent' : 'text-ink-dim',
            )}
          >
            {countdown(days)}
          </span>
        )}
      </Link>
    </li>
  )
}

// ------------------------------------------------------------------ status

/**
 * The tile width from which each count is labelled, by how many counts the tile holds, so a
 * label shows only where every one of them fits on the line. Written out whole for Tailwind.
 */
const LABELLED: Record<number, string> = {
  2: '@2xs:inline',
  3: '@sm:inline',
  4: '@lg:inline',
}

/** What a panel shows while what it reads is on its way. */
function PanelLoading() {
  return (
    <PanelBody className="flex justify-center">
      <Spinner className="size-8 text-ink-dim" />
    </PanelBody>
  )
}

/** One tile per category shown, counting what comes out this month and what is tracked now. */
export function StatusPanel() {
  const now = new Date()
  // Released or due this calendar month, whatever its state, and everything still tracked,
  // whenever it came out. Undated items are left out.
  const items = useTracked().filter(
    (i) =>
      i.state === 'tracking' ||
      (i.release &&
        i.release.getFullYear() === now.getFullYear() &&
        i.release.getMonth() === now.getMonth()),
  )
  const categories = useTrackedCategories()
  const loading = useOverviewLoading()
  if (loading) return <PanelLoading />
  if (!categories.length) {
    return (
      <PanelEmpty>Nothing is set up yet. Each category appears once its source is set.</PanelEmpty>
    )
  }
  const tiles = categories.map(({ key, to, icon, label }) => ({
    to,
    icon,
    title: label,
    counts: (['waiting', 'tracking', 'found', 'error'] as const)
      .map((state) => ({
        state,
        n: items.filter((i) => i.category === key && i.state === state).length,
      }))
      .filter((c) => c.n > 0 || c.state === 'waiting' || c.state === 'found'),
  }))
  return (
    <PanelBody className="grid gap-3 sm:grid-cols-[repeat(auto-fit,minmax(16rem,1fr))]">
      {tiles.map(({ to, icon: Icon, title, counts }) => (
        <Link
          key={title}
          to={to}
          className="group @container flex items-center gap-4 rounded-md border border-line bg-base/40 px-4 py-3 transition-colors hover:border-line-strong"
        >
          <Icon className="size-4 shrink-0 text-ink-faint group-hover:text-accent" />
          <span className="text-sm font-medium text-ink">{title}</span>
          <span className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-4 gap-y-1">
            {counts.map((c) => (
              <span key={c.state} className="flex items-center gap-1.5 text-xs text-ink-dim">
                <StateIcon state={c.state} />
                <span className="text-lg font-semibold text-ink">{c.n}</span>
                <span className={cn('hidden', LABELLED[counts.length])}>
                  {STATE_LABEL[c.state]}
                </span>
              </span>
            ))}
          </span>
        </Link>
      ))}
    </PanelBody>
  )
}

// ------------------------------------------------------------------ next up

const NEXT_UP_DAYS = 60

/**
 * Everything monitored and still waiting that comes out in the next two months, soonest first.
 * A show is dated by its next season premiere only.
 */
export function NextUpPanel() {
  const items = useUpcoming()
  const loading = useOverviewLoading(true)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const soon = items
    .filter(
      (i) =>
        i.state === 'waiting' &&
        i.release &&
        i.release >= today &&
        i.release.getTime() - today.getTime() <= NEXT_UP_DAYS * DAY,
    )
    .sort((a, b) => a.release!.getTime() - b.release!.getTime())
    .slice(0, ROWS)

  if (loading) return <PanelLoading />
  if (!soon.length) {
    return <PanelEmpty>Nothing out in the next 60 days.</PanelEmpty>
  }
  return (
    <ul className="divide-y divide-line">
      {soon.map((item) => (
        <Row key={item.key} item={item} />
      ))}
    </ul>
  )
}

/** Five rows, the most a Home list shows, so panels side by side stay one height. */
const ROWS = 5

// ------------------------------------------------------------------ countdowns

/** Now, once a second, for every timer on screen. */
function useNow(): number {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [])
  return now
}

/** Days, hours, minutes and seconds to local midnight of a release day, Out from then. */
function timer(day: string, now: number): string {
  const [y, m, d] = day.split('-').map(Number)
  const left = (new Date(y, m - 1, d).getTime() - now) / 1000
  if (left <= 0) return 'Out'
  const pad = (n: number) => String(Math.floor(n)).padStart(2, '0')
  return `${Math.floor(left / 86_400)}d ${pad((left % 86_400) / 3600)}:${pad((left % 3600) / 60)}:${pad(left % 60)}`
}

/** What a dialog's Countdown added, soonest first, ticking to the release day. */
export function CountdownsPanel() {
  const queryClient = useQueryClient()
  const countdowns = useCountdowns()
  const now = useNow()
  const remove = useMutation({
    mutationFn: api.removeCountdown,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['countdowns'] }),
  })

  if (countdowns.isPending) return <PanelLoading />
  if (countdowns.isError) {
    return (
      <PanelBody>
        <Notice tone="bad">{errorText(countdowns.error, 'Could not load countdowns')}</Notice>
      </PanelBody>
    )
  }
  if (!countdowns.data.length) {
    return <PanelEmpty>No countdowns.</PanelEmpty>
  }
  return (
    <ul className="divide-y divide-line">
      {countdowns.data.map((c) => (
        <li key={c.id} className="flex items-center hover:bg-raised/50">
          <Link
            to={`?${c.target}`}
            className="flex min-w-0 flex-1 items-center gap-3 py-2 pl-4 focus-visible:outline-accent"
          >
            <Artwork
              image={c.image}
              shape={c.category === 'games' ? 'poster' : 'cover'}
              className="w-8 shrink-0"
            />
            <div className="min-w-0 flex-1">
              <Clip className="text-sm font-medium text-ink">{c.title}</Clip>
              <Kind category={c.category} tag={c.tag} />
            </div>
            <span className="shrink-0 font-mono text-xs font-medium text-accent tabular-nums">
              {timer(c.date, now)}
            </span>
          </Link>
          <Tip content="Remove">
            <button
              type="button"
              aria-label={`Remove the countdown to ${c.title}`}
              onClick={() => remove.mutate(c.id)}
              disabled={remove.isPending}
              className="mx-2 rounded-sm p-1.5 text-ink-faint hover:text-bad focus-visible:outline-accent"
            >
              <X className="size-3.5" />
            </button>
          </Tip>
        </li>
      ))}
    </ul>
  )
}

// ------------------------------------------------------------------ downloads

/** qBittorrent counts speed in bytes a second. */
function speed(bytes: number): string {
  return bytes < 1e6 ? `${Math.round(bytes / 1e3)} kB/s` : `${(bytes / 1e6).toFixed(1)} MB/s`
}

/** qBittorrent reports an unknown time left as 8640000, a hundred days. */
function timeLeft(seconds: number): string | null {
  if (seconds <= 0 || seconds >= 8_640_000) return null
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h`
  return `${Math.round(seconds / 86_400)} d`
}

/** Live while the panel is on screen, every few seconds. */
const TORRENT_POLL = 3_000

/** Everything qBittorrent is downloading in the category set in Settings, monitored or not. */
export function DownloadsPanel() {
  const downloads = useQuery({
    queryKey: ['downloads'],
    queryFn: api.downloads,
    refetchInterval: TORRENT_POLL,
    retry: false,
  })

  if (downloads.isPending) return <PanelLoading />
  if (downloads.isError)
    return (
      <PanelBody>
        <Notice tone="bad">{errorText(downloads.error, 'qBittorrent is unreachable')}</Notice>
      </PanelBody>
    )
  if (!downloads.data.length) return <PanelEmpty>Nothing downloading.</PanelEmpty>
  return (
    <ul className="divide-y divide-line">
      {downloads.data.map((torrent) => (
        <Download key={torrent.hash} torrent={torrent} />
      ))}
    </ul>
  )
}

/** One torrent: its name, how far along it is, and how fast it moves each way. */
function Download({ torrent }: { torrent: Torrent }) {
  const percent = Math.floor(torrent.progress * 100)
  const left = timeLeft(torrent.eta)
  return (
    <li className="space-y-1.5 px-4 py-2.5">
      <div className="flex items-baseline gap-3">
        <Clip className="min-w-0 flex-1 font-mono text-xs text-ink">{torrent.name}</Clip>
        <span className="shrink-0 text-2xs text-ink-faint tabular-nums">
          {releaseSize(torrent.size)}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Progress value={percent} aria-label={`Downloaded ${percent}%`} className="h-1.5 flex-1" />
        <span className="flex shrink-0 items-center gap-2.5 text-2xs text-ink-faint tabular-nums">
          <span className="text-ink-dim">{percent}%</span>
          <span className="flex items-center gap-0.5">
            <ArrowDown className="size-3" />
            {speed(torrent.dlspeed)}
          </span>
          <span className="flex items-center gap-0.5">
            <ArrowUp className="size-3" />
            {speed(torrent.upspeed)}
          </span>
          {left ? <span>{left} left</span> : null}
        </span>
      </div>
    </li>
  )
}

// ------------------------------------------------------------------ recently notified

export function FoundPanel() {
  const loading = useOverviewLoading()
  const found = useTracked()
    .filter((i) => i.foundAt)
    .sort((a, b) => b.foundAt!.localeCompare(a.foundAt!))
    .slice(0, ROWS)

  if (loading) return <PanelLoading />
  if (!found.length) return <PanelEmpty>Nothing notified yet.</PanelEmpty>
  return (
    <ul className="divide-y divide-line">
      {found.map((item) => (
        <Row key={item.key} item={item} />
      ))}
    </ul>
  )
}

// ------------------------------------------------------------------ calendar

/**
 * A month with the release day of everything tracked or coming from a favourite marked in
 * accent, and the days things were found marked green. Picking a day lists what comes out on it.
 * It starts at this month, nothing before it is shown.
 */
export function CalendarPanel() {
  const items = useUpcoming()
  const loading = useOverviewLoading(true)
  const [day, setDay] = useState<Date | undefined>(new Date())

  const releases = items.filter((i) => i.release)
  const found = items.filter((i) => i.foundAt).map((i) => new Date(i.foundAt!))

  const onDay = day ? releases.filter((i) => sameDay(i.release!, day)).slice(0, ROWS) : []

  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <PanelBody className="flex justify-center">
        <Calendar
          mode="single"
          selected={day}
          onSelect={setDay}
          startMonth={monthStart()}
          disabled={{ before: monthStart() }}
          className="bg-transparent p-0"
          modifiers={{ release: releases.map((i) => i.release!), found }}
          modifiersClassNames={{
            release:
              'relative after:absolute after:bottom-1 after:left-1/2 after:size-1 after:-translate-x-1/2 after:rounded-full after:bg-accent',
            found: '[&_button]:text-good',
          }}
        />
      </PanelBody>
      <div className="min-w-0 flex-1 border-line sm:border-l">
        <p className="px-4 pt-4 pb-2 text-2xs font-semibold tracking-wider text-ink-faint uppercase">
          {day
            ? day.toLocaleDateString(undefined, { day: 'numeric', month: 'long' })
            : 'Pick a day'}
        </p>
        {loading ? (
          <PanelLoading />
        ) : onDay.length ? (
          <ul className="divide-y divide-line">
            {onDay.map((item) => (
              <Row key={item.key} item={item} dated={false} />
            ))}
          </ul>
        ) : (
          <PanelEmpty className="pt-0">Nothing out that day.</PanelEmpty>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ health

export function HealthPanel() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api.health(),
    staleTime: 60_000,
  })
  if (health.isPending) return <PanelLoading />
  if (health.isError) return <Notice tone="bad">Could not read the services</Notice>
  return (
    <ul className="divide-y divide-line">
      {SERVICES.map(({ key, label }) => (
        <li key={key} className="flex items-center gap-3 px-4 py-2.5 text-sm">
          <span className="w-20 shrink-0 font-medium text-ink">{label}</span>
          <HealthWord health={health.data[key]} />
        </li>
      ))}
    </ul>
  )
}

/** Asks every service again rather than reading the one minute cache. */
export function HealthRefresh() {
  const queryClient = useQueryClient()
  const refresh = useMutation({
    mutationFn: () => api.health(true),
    onSuccess: (report) => queryClient.setQueryData(['health'], report),
  })
  return (
    <Tip content="Check again">
      <button
        type="button"
        aria-label="Check again"
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        className={cn(controlClass(), 'h-6 px-1.5')}
      >
        {refresh.isPending ? <Spinner className="size-3" /> : <RefreshCw className="size-3" />}
      </button>
    </Tip>
  )
}
