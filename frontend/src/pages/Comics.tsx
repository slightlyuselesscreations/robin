import { useQuery } from '@tanstack/react-query'
import { BookOpen, CalendarDays, ChevronLeft, ChevronRight, Library, Newspaper } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ComicDialog } from '@/components/ComicDialog'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ComicMenu, SeriesMenu } from '@/components/ItemMenus'
import { GridLoading, Items } from '@/components/MediaCard'
import {
  Control,
  ControlGroup,
  FilterSelect,
  Notice,
  Options,
  Page,
  PageHeader,
  Section,
  Sections,
  Segmented,
  Tip,
  ViewSwitch,
} from '@/components/Page'
import { SeriesDialog } from '@/components/SeriesDialog'
import { type Comic, api, errorText } from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { HEADER_CONTROLS, ORDERS, asView, narrowed, pickOf, usePageControls } from '@/lib/controls'
import { comicItem, comicMonitorOf, seriesItem } from '@/lib/items'
import { useComic } from '@/lib/monitor'
import { useDialogParam, withParam } from '@/lib/params'
import { cn, controlClass, isoDay, localDay, monthStart } from '@/lib/utils'

type Source = 'metron' | 'suwayomi'

const SOURCES: { value: Source; label: string }[] = [
  { value: 'metron', label: 'Metron' },
  { value: 'suwayomi', label: 'Suwayomi' },
]

/** #1s are the first issue of a series, or on Suwayomi a series with one issue alone. */
const TYPES = [
  { value: 'all', label: 'All' },
  { value: 'first', label: '#1s' },
] as const

/** On Suwayomi, where a series names no publisher, Publisher keeps the source's own order. */
const ORDER = [ORDERS.publisher, ORDERS.title]

const byTitle = (a: { title: string }, b: { title: string }) => a.title.localeCompare(b.title)

const WEEK = /^\d{4}-\d{2}-\d{2}$/

// The Metron ids of the publishers with a panel of their own, in order: Marvel, DC, Image.
const PANELS = [1, 2, 4]

/**
 * A panel for each publisher of `PANELS` with issues this week, then Other for every other,
 * each in the order the issues are already sorted. `named` says the panel names the publisher.
 */
function byPublisher(
  comics: Comic[],
): { key: string; title: string; named: boolean; comics: Comic[] }[] {
  const own = PANELS.map((id) => comics.filter((c) => c.publisher_id === id))
    .filter((found) => found.length > 0)
    .map((found) => ({
      key: String(found[0].publisher_id),
      title: found[0].publisher,
      named: true,
      comics: found,
    }))
  const other = comics.filter((c) => c.publisher_id === null || !PANELS.includes(c.publisher_id))
  return other.length
    ? [...own, { key: 'other', title: 'Other', named: false, comics: other }]
    : own
}

/**
 * Every issue of a week from Metron, this week first, the first of a series tagged #1. With
 * Suwayomi set, the panel switches to the series its source updated last, the open one
 * `?series=<suwayomi id>`.
 *
 * The week, the source, the type, the order, the publisher and the open issue are search
 * parameters, so back and forward step through what was looked at. Without a week the backend
 * answers for the current one.
 */
/** The week shown, by the Monday it starts on, picked from a calendar that starts on Monday. */
function WeekPicker({ week, onPick }: { week?: string; onPick: (week: string) => void }) {
  const [open, setOpen] = useState(false)
  const day = week ? localDay(week) : undefined
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Week"
          className={cn(controlClass(), 'text-ink tabular-nums')}
        >
          {week ?? ''}
          <CalendarDays className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-auto p-0">
        <Calendar
          mode="single"
          selected={day}
          defaultMonth={day}
          startMonth={monthStart()}
          disabled={{ before: monthStart() }}
          onSelect={(picked) => {
            if (!picked) return
            onPick(isoDay(picked))
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

export function Comics() {
  const [params] = useSearchParams()
  const controls = usePageControls('comics', {
    view: 'cover',
    source: 'metron',
    type: 'all',
    order: 'publisher',
    publisher: '',
  })
  const { values } = controls
  const view = asView(values.view, 'cover')
  const firsts = pickOf(values.type, TYPES) === 'first'
  const order = pickOf(values.order, ORDER)

  const raw = params.get('week')
  const asked = raw && WEEK.test(raw) ? raw : undefined
  const issues = useQuery({
    queryKey: ['comic-issues', asked ?? 'current'],
    queryFn: () => api.comicIssues(asked),
    staleTime: 60 * 60_000,
    // Publishers and credits fill in as Robin reads them, one issue every few seconds.
    refetchInterval: (query) => (query.state.data?.reading ? 15_000 : false),
    retry: false,
  })

  const suwayomi = useSettings().data?.suwayomi_ready ?? false
  const source: Source = suwayomi && controls.values.source === 'suwayomi' ? 'suwayomi' : 'metron'
  const latest = useQuery({
    queryKey: ['comic-latest'],
    queryFn: api.latestComics,
    enabled: suwayomi,
    staleTime: 15 * 60_000,
    retry: false,
  })

  const monitored = useQuery({ queryKey: ['comics-monitored'], queryFn: api.monitoredComics })
  const monitorOf = (comic: Comic) => comicMonitorOf(monitored.data, comic)

  // The publishers this week has, what Settings leaves of them, for the page to narrow to one.
  const publishers = [
    ...new Map(
      (issues.data?.issues ?? [])
        .filter((c) => c.publisher_id !== null)
        .map((c) => [String(c.publisher_id), c.publisher]),
    ),
  ]
    .sort((a, b) => a[1].localeCompare(b[1]))
    .map(([value, label]) => ({ value, label }))
  const picked = narrowed(values.publisher, issues.data ? publishers : undefined)
  const shown = (comic: Comic) =>
    (!picked || String(comic.publisher_id) === picked) && (!firsts || comic.number === '1')

  // An issue whose publisher is still being read goes last.
  const every = (issues.data?.issues.filter(shown) ?? []).sort((a, b) =>
    order === 'title'
      ? byTitle(a, b)
      : Number(!a.publisher) - Number(!b.publisher) ||
        a.publisher.localeCompare(b.publisher) ||
        byTitle(a, b),
  )
  // Publishers only read as panels while the week runs in publisher order.
  const panels =
    source === 'metron' && order === 'publisher' && every.length > 0 ? byPublisher(every) : null
  const series = (latest.data ?? []).filter((s) => !firsts || s.issues === 1)
  if (order === 'title') series.sort(byTitle)
  const week = issues.data?.week
  const go = (to: string | null) => controls.set({ week: to, comic: null })
  const weekControls = (
    <ControlGroup>
      {asked ? (
        <button type="button" onClick={() => go(null)} className={controlClass()}>
          This week
        </button>
      ) : null}
      <div className="flex items-center gap-1">
        <Tip content="Previous week">
          <button
            type="button"
            aria-label="Previous week"
            onClick={() => issues.data?.previous && go(issues.data.previous)}
            disabled={!issues.data?.previous}
            className={cn(controlClass(), 'px-1.5')}
          >
            <ChevronLeft className="size-3.5" />
          </button>
        </Tip>
        <WeekPicker week={week ?? asked} onPick={go} />
        <Tip content="Next week">
          <button
            type="button"
            aria-label="Next week"
            onClick={() => issues.data && go(issues.data.next)}
            disabled={!issues.data}
            className={cn(controlClass(), 'px-1.5')}
          >
            <ChevronRight className="size-3.5" />
          </button>
        </Tip>
      </div>
    </ControlGroup>
  )
  const openId = params.get('comic')
  const listed = every.find((c) => c.id === openId)
  // An issue this page does not list, such as one a favourite has coming, is read on its own.
  const fetched = useComic(listed || issues.isPending ? null : openId)
  const open = listed ?? fetched.data ?? null
  const [, close] = useDialogParam('comic')

  const pending = <GridLoading />
  // A publisher's own panel names it already, so its cards are tagged #1 alone.
  const listedItem = (comic: Comic, named = false) => ({
    ...comicItem(comic, withParam(params, 'comic', comic.id), monitorOf(comic), week),
    ...(named ? { tag: comic.number === '1' ? '#1' : null, tagTip: null } : {}),
    menu: <ComicMenu comic={comic} week={week} />,
  })
  const panelControls = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {source === 'metron' ? weekControls : null}
      {suwayomi ? (
        <Segmented
          label="Source"
          options={SOURCES}
          value={source}
          onChange={(next) => controls.set({ source: next })}
        />
      ) : null}
    </div>
  )

  return (
    <Page>
      <PageHeader title="Comics" icon={BookOpen}>
        <Segmented
          label="Type"
          options={[...TYPES]}
          value={firsts ? 'first' : 'all'}
          onChange={(type) => controls.set({ type })}
        />
        <Segmented
          label="Order"
          options={ORDER}
          value={order}
          onChange={(next) => controls.set({ order: next })}
        />
        <Options controls={controls} header={[...HEADER_CONTROLS, 'source']}>
          <ViewSwitch value={view} onChange={(next) => controls.set({ view: next })} />
          {source === 'metron' && publishers.length > 1 ? (
            <Control label="Publisher">
              <FilterSelect
                value={picked}
                all="All publishers"
                options={publishers}
                onChange={(publisher) => controls.set({ publisher })}
              />
            </Control>
          ) : null}
        </Options>
      </PageHeader>

      <Sections>
        {panels ? (
          panels.map(({ key, title, named, comics: published }, i) => (
            <Section
              key={key}
              title={title}
              icon={Newspaper}
              count={published.length}
              action={i === 0 ? panelControls : undefined}
            >
              <Items
                view={view}
                metaLabel="Release"
                items={published.map((comic) => listedItem(comic, named))}
              />
            </Section>
          ))
        ) : (
          <Section
            title={source === 'suwayomi' ? 'Suwayomi' : 'Metron'}
            icon={source === 'suwayomi' ? Library : Newspaper}
            count={
              source === 'suwayomi'
                ? latest.data
                  ? series.length
                  : undefined
                : issues.data
                  ? every.length
                  : undefined
            }
            action={panelControls}
          >
            {source === 'suwayomi' ? (
              latest.isPending ? (
                pending
              ) : latest.isError ? (
                <Notice tone="bad">{errorText(latest.error, 'Suwayomi is unreachable')}</Notice>
              ) : (
                <Items
                  view={view}
                  items={series.map((s) => ({
                    ...seriesItem(s, withParam(params, 'series', s.id)),
                    menu: <SeriesMenu series={s} />,
                  }))}
                />
              )
            ) : issues.isPending ? (
              pending
            ) : issues.isError ? (
              <Notice tone="bad">{errorText(issues.error, 'Metron is unreachable')}</Notice>
            ) : every.length === 0 ? (
              <Notice>No issues this week.</Notice>
            ) : (
              <Items
                view={view}
                metaLabel="Release"
                items={every.map((comic) => listedItem(comic))}
              />
            )}
          </Section>
        )}
      </Sections>

      <ComicDialog
        comic={open}
        week={(listed ? week : open?.date) ?? undefined}
        monitor={open ? monitorOf(open) : null}
        onClose={close}
      />
      <SeriesDialog listed={latest.data} />
    </Page>
  )
}
