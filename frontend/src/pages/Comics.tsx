import { useQuery } from '@tanstack/react-query'
import { BookOpen, Library, Newspaper } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { ComicDialog } from '@/components/ComicDialog'
import { ComicMenu, SeriesMenu } from '@/components/ItemMenus'
import { GridLoading, Items } from '@/components/MediaCard'
import {
  Control,
  KeptSelect,
  Notice,
  Options,
  Page,
  PageHeader,
  PanelBody,
  Section,
  Sections,
  Segmented,
  ViewSwitch,
} from '@/components/Page'
import { SeriesDialog } from '@/components/SeriesDialog'
import { type Comic, api, errorText } from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { ANY, KEPT, asView, usePageControls } from '@/lib/controls'
import { comicItem, comicMonitorOf, seriesItem } from '@/lib/items'
import { useComic } from '@/lib/monitor'
import { useDialogParam, withParam } from '@/lib/params'

type Source = 'comicvine' | 'suwayomi'

const SOURCES: { value: Source; label: string }[] = [
  { value: 'comicvine', label: 'Comic Vine' },
  { value: 'suwayomi', label: 'Suwayomi' },
]

/**
 * Every issue of the current week from Comic Vine, the first of a series tagged #1. With
 * Suwayomi set, the panel switches to the series its source updated last, the open one
 * `?series=<suwayomi id>`.
 *
 * The source, the publisher and the open issue are search parameters, so back and forward
 * step through what was looked at.
 */
export function Comics() {
  const [params] = useSearchParams()
  const controls = usePageControls('comics', {
    view: 'cover',
    source: 'comicvine',
    publisher: KEPT,
  })
  const view = asView(controls.values.view, 'cover')

  const issues = useQuery({
    queryKey: ['comic-issues'],
    queryFn: api.comicIssues,
    staleTime: 60 * 60_000,
    retry: false,
  })

  const suwayomi = useSettings().data?.suwayomi_ready ?? false
  const source: Source =
    suwayomi && controls.values.source === 'suwayomi' ? 'suwayomi' : 'comicvine'
  const latest = useQuery({
    queryKey: ['comic-latest'],
    queryFn: api.latestComics,
    enabled: suwayomi,
    staleTime: 15 * 60_000,
    retry: false,
  })
  const [openSeriesId, closeSeries] = useDialogParam('series')
  const openSeries = latest.data?.find((s) => String(s.id) === openSeriesId) ?? null

  const monitored = useQuery({ queryKey: ['comics-monitored'], queryFn: api.monitoredComics })
  const monitorOf = (comic: Comic) => comicMonitorOf(monitored.data, comic)

  // The publishers this week has, for the page's pick. Any while nothing is picked.
  const publishers = [
    ...new Map(
      (issues.data?.issues ?? [])
        .filter((c) => c.publisher_id !== null)
        .map((c) => [String(c.publisher_id), c.publisher]),
    ),
  ].sort((a, b) => a[1].localeCompare(b[1]))
  const picked = controls.values.publisher
  const shown = (comic: Comic) =>
    picked === KEPT || picked === ANY || String(comic.publisher_id) === picked

  const every = issues.data?.issues.filter(shown) ?? []
  const week = issues.data?.week
  const openId = params.get('comic')
  const listed = every.find((c) => c.id === openId)
  // An issue this page does not list, such as one a favourite has coming, is read on its own.
  const fetched = useComic(listed || issues.isPending ? null : openId)
  const open = listed ?? fetched.data ?? null
  const [, close] = useDialogParam('comic')

  const pending = <GridLoading />

  return (
    <Page>
      <PageHeader title="Comics" icon={BookOpen}>
        <Options controls={controls}>
          <ViewSwitch value={view} onChange={(next) => controls.set({ view: next })} />
          {publishers.length > 1 ? (
            <Control label="Publisher">
              <KeptSelect
                value={picked}
                kept={[]}
                any="Any publisher"
                options={publishers.map(([value, label]) => ({ value, label }))}
                onChange={(next) => controls.set({ publisher: next })}
              />
            </Control>
          ) : null}
        </Options>
      </PageHeader>

      <Sections>
        <Section
          title={source === 'suwayomi' ? 'Suwayomi' : 'Comic Vine'}
          icon={source === 'suwayomi' ? Library : Newspaper}
          count={
            source === 'suwayomi' ? latest.data?.length : issues.data ? every.length : undefined
          }
          action={
            suwayomi ? (
              <Segmented
                label="Source"
                options={SOURCES}
                value={source}
                onChange={(next) => controls.set({ source: next })}
              />
            ) : null
          }
        >
          {source === 'suwayomi' ? (
            latest.isPending ? (
              pending
            ) : latest.isError ? (
              <Notice tone="bad">{errorText(latest.error, 'Suwayomi is unreachable')}</Notice>
            ) : (
              <Items
                view={view}
                items={latest.data.map((s) => ({
                  ...seriesItem(s, withParam(params, 'series', s.id)),
                  menu: <SeriesMenu series={s} />,
                }))}
              />
            )
          ) : issues.isPending ? (
            pending
          ) : issues.isError ? (
            <Notice tone="bad">{errorText(issues.error, 'Comic Vine is unreachable')}</Notice>
          ) : every.length === 0 ? (
            <PanelBody className="text-xs text-ink-faint">No new issues this week.</PanelBody>
          ) : (
            <Items
              view={view}
              metaLabel="Release"
              items={every.map((comic) => ({
                ...comicItem(comic, withParam(params, 'comic', comic.id), monitorOf(comic), week),
                menu: <ComicMenu comic={comic} week={week} />,
              }))}
            />
          )}
        </Section>
      </Sections>

      <ComicDialog
        comic={open}
        week={(listed ? week : open?.date) ?? undefined}
        monitor={open ? monitorOf(open) : null}
        onClose={close}
      />
      <SeriesDialog series={openSeries} onClose={closeSeries} />
    </Page>
  )
}
