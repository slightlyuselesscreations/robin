import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { TriangleAlert } from 'lucide-react'

import {
  Actions,
  CountdownButton,
  Fact,
  Facts,
  FavouriteFact,
  ImageZoom,
  Links,
  MediaBanner,
  MediaBody,
  MediaDialog,
  MediaFooter,
  MediaHead,
  MonitorButton,
  OutLink,
  Summary,
} from '@/components/MediaDialog'
import { FlightNotice } from '@/components/MediaCard'
import { Tip } from '@/components/Page'
import {
  COMIC_STATE,
  STATE_LABEL,
  type Comic,
  type MonitoredComic,
  api,
  errorText,
  imageSrc,
} from '@/lib/api'
import { useSettings } from '@/lib/categories'
import {
  asComic,
  calendarDay,
  comicMonitorOf,
  comicTag,
  fromMetron,
  metronIssue,
} from '@/lib/items'
import { useComic, useComicMonitor } from '@/lib/monitor'
import { useDialogParam } from '@/lib/params'

/**
 * Any issue, `?comic=<issue id>`, away from the Comics page, which opens the issues it lists
 * itself: the one a series was monitored from, or any other read from Metron.
 */
export function AnyComicDialog() {
  const [id, close] = useDialogParam('comic')
  const comics = useQuery({ queryKey: ['comics-monitored'], queryFn: api.monitoredComics })
  const row = comics.data?.find((c) => c.issue_id === id) ?? null
  const fetched = useComic(comics.isSuccess && !row ? id : null)
  const comic = row ? asComic(row) : (fetched.data ?? null)
  return (
    <ComicDialog
      comic={comic}
      week={comic?.date ?? undefined}
      monitor={comic ? comicMonitorOf(comics.data, comic) : null}
      onClose={close}
    />
  )
}

// The roles worth a line, in this order. Metron also lists editors.
const ROLES = ['Writer', 'Artist', 'Penciller', 'Inker', 'Colorist', 'Cover Artist', 'Letterer']

/**
 * One issue, laid out like the game dialog. The listing gives the title and the cover at once.
 * The rest is read from Metron when it is opened, and kept until Metron edits the issue. A
 * series monitored from LOCG has nothing more to read.
 */
export function ComicDialog({
  comic,
  week,
  monitor,
  onClose,
}: {
  comic: Comic | null
  /** The week the issue shipped. A monitored series does not keep it. */
  week?: string
  monitor: MonitoredComic | null
  onClose: () => void
}) {
  return (
    <MediaDialog open={comic !== null} onClose={onClose}>
      {comic === null ? null : (
        <Body comic={comic} week={week} monitor={monitor} onClose={onClose} />
      )}
    </MediaDialog>
  )
}

function Body({
  comic,
  week,
  monitor,
  onClose,
}: {
  comic: Comic
  week?: string
  monitor: MonitoredComic | null
  onClose: () => void
}) {
  const settings = useSettings()
  const suwayomi = settings.data?.suwayomi_url
  const out = week ?? comic.date ?? undefined

  const readable = metronIssue(comic)
  const detail = useQuery({
    queryKey: ['comic', comic.id, comic.modified ?? null],
    queryFn: () => api.comicDetail(comic),
    enabled: readable,
    initialData: comic.detail ?? undefined,
    // The backend keeps the issue page, so this tab need not ask again either.
    staleTime: Infinity,
    retry: false,
  })

  const { start, stop } = useComicMonitor(onClose)
  const [zoomed, setZoomed] = useState<{ src: string; name: string } | null>(null)

  const data = detail.data
  const cover = comic.cover
  const busy = start.isPending || stop.isPending

  return (
    <>
      <MediaBanner image={cover} cover />

      <MediaBody>
        <MediaHead
          art={cover}
          shape="cover"
          title={comic.title}
          meta={[
            data?.name,
            comic.publisher,
            out ? `Out ${calendarDay(out)}` : null,
            data?.cover_date ? `Cover date ${calendarDay(data.cover_date)}` : null,
          ]}
        >
          {!readable ? null : data ? (
            <Facts>
              {ROLES.map((role) => (
                <FavouriteFact
                  key={role}
                  label={role}
                  category="comics"
                  kind="person"
                  refs={data.people?.[role]}
                />
              ))}
              <FavouriteFact
                label="Series"
                category="comics"
                kind="series"
                refs={
                  comic.series_id
                    ? [{ id: comic.series_id, name: data.series ?? seriesOf(comic.title) }]
                    : null
                }
              />
              <FavouriteFact
                label="Publisher"
                category="comics"
                kind="publisher"
                refs={
                  comic.publisher_id
                    ? [{ id: comic.publisher_id, name: comic.publisher }]
                    : data.publisher
                      ? [data.publisher]
                      : null
                }
              />
              <Fact label="Imprint" value={data.imprint ? [data.imprint] : null} />
              <Fact label="Story arc" value={data.story_arcs} />
              <Fact label="First appearance" value={data.first_appearances} />
              <Fact label="Characters" value={data.characters} />
              <Fact label="Teams" value={data.teams} />
              <Fact label="Universe" value={data.universes} />
            </Facts>
          ) : detail.isError ? (
            <p className="flex items-center gap-1.5 text-xs text-bad">
              <TriangleAlert className="size-3.5" />
              {errorText(detail.error, 'Could not read the issue')}
            </p>
          ) : (
            <FlightNotice>Loading Metron data, please keep flying...</FlightNotice>
          )}

          <Links>
            <OutLink href={comic.url}>
              {fromMetron(comic) ? 'Metron' : 'League of Comic Geeks'}
            </OutLink>
            {comic.series_url ? <OutLink href={comic.series_url}>Series</OutLink> : null}
          </Links>
        </MediaHead>

        {data?.synopsis ? <Summary>{data.synopsis}</Summary> : null}

        {data?.variants.length ? (
          <div className="grid grid-cols-4 content-start gap-2 sm:min-h-0 sm:flex-1 sm:grid-cols-6 sm:overflow-y-auto">
            {data.variants.map((variant) => (
              <Tip key={variant.image} content={variant.name} when={() => Boolean(variant.name)}>
                <button
                  type="button"
                  aria-label={`Enlarge ${variant.name || 'variant cover'}`}
                  onClick={() => setZoomed({ src: variant.image, name: variant.name })}
                  className="cursor-zoom-in overflow-hidden rounded-sm border border-line bg-base transition-colors hover:border-accent focus-visible:border-accent focus-visible:outline-none"
                >
                  <img
                    src={imageSrc(variant.image)}
                    alt=""
                    loading="lazy"
                    className="aspect-[2/3] w-full object-cover"
                  />
                </button>
              </Tip>
            ))}
          </div>
        ) : null}

        <ImageZoom
          src={zoomed?.src ?? null}
          alt={zoomed?.name || `${comic.title} variant cover`}
          onClose={() => setZoomed(null)}
        />

        <MediaFooter
          status={
            monitor
              ? {
                  state: COMIC_STATE[monitor.status],
                  text: (
                    <>
                      {STATE_LABEL[COMIC_STATE[monitor.status]]}
                      {monitor.status === 'added' && suwayomi && monitor.suwayomi_id ? (
                        <OutLink href={`${suwayomi}/manga/${monitor.suwayomi_id}`} accent>
                          Open in Suwayomi
                        </OutLink>
                      ) : null}
                    </>
                  ),
                }
              : null
          }
        >
          <Actions>
            <MonitorButton
              monitored={monitor !== null}
              pending={busy}
              disabled={!monitor && !out}
              onMonitor={() => out && start.mutate({ comic, week: out })}
              onStop={() => monitor && stop.mutate(monitor)}
            />
            <CountdownButton
              target={{
                category: 'comics',
                target: `comic=${comic.id}`,
                title: comic.title,
                image: comic.cover,
                tag: comicTag(comic),
                date: out ?? null,
              }}
            />
          </Actions>
        </MediaFooter>
      </MediaBody>
    </>
  )
}

/** "Midnight X-Men #3" is of the series "Midnight X-Men". */
function seriesOf(title: string): string {
  return title.replace(/\s*#\S+$/, '')
}
