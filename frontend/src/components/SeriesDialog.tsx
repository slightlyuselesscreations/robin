import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'

import {
  Actions,
  Fact,
  Facts,
  MediaBanner,
  MediaBody,
  MediaDialog,
  MediaFooter,
  MediaHead,
  MonitorButton,
  Summary,
} from '@/components/MediaDialog'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { COMIC_STATE, STATE_LABEL, type Series, api } from '@/lib/api'
import { useAddSeries, useComicMonitor } from '@/lib/monitor'
import { useDialogParam } from '@/lib/params'

/**
 * A series on the Suwayomi source, `?series=<suwayomi id>`, as the source lists it in `listed`
 * or read on its own. Adding it to the library monitors it, and stopping takes it out again.
 */
export function SeriesDialog({ listed }: { listed?: Series[] }) {
  const [id, close] = useDialogParam('series')
  const seriesId = id && /^\d+$/.test(id) ? Number(id) : null
  return (
    <MediaDialog open={seriesId !== null} onClose={close}>
      {seriesId === null ? null : (
        <Body id={seriesId} listed={listed?.find((s) => s.id === seriesId)} onClose={close} />
      )}
    </MediaDialog>
  )
}

/** The series dialog for an address that opens one, away from the Comics page. */
export function AnySeriesDialog() {
  return <SeriesDialog />
}

/** The library series in Suwayomi itself. */
export function OpenInSuwayomi({ href }: { href: string }) {
  return (
    <Button variant="ghost" asChild className="gap-2 text-ink-dim hover:text-accent">
      <a href={href} target="_blank" rel="noreferrer">
        <ExternalLink className="size-4" />
        Open in Suwayomi
      </a>
    </Button>
  )
}

function Body({ id, listed, onClose }: { id: number; listed?: Series; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ['series', id],
    queryFn: () => api.series(id),
    initialData: listed,
    // The listing carries no description, so it is only a placeholder for the real answer.
    initialDataUpdatedAt: 0,
    retry: false,
  })
  const monitored = useQuery({ queryKey: ['comics-monitored'], queryFn: api.monitoredComics })
  const row = monitored.data?.find((r) => r.suwayomi_id === id) ?? null

  const add = useAddSeries()
  const { stop } = useComicMonitor(onClose)

  const series = detail.data
  if (!series) {
    return (
      <MediaBody>
        <div className="flex justify-center py-10">
          <Spinner className="size-5 text-ink-dim" />
        </div>
      </MediaBody>
    )
  }
  const state = row ? COMIC_STATE[row.status] : series.inLibrary ? 'tracking' : null
  return (
    <>
      <MediaBanner image={series.thumbnailUrl} cover />
      <MediaBody>
        <MediaHead
          art={series.thumbnailUrl}
          shape="cover"
          title={series.title}
          meta={[
            series.issues === undefined || series.issues === null
              ? null
              : `${series.issues} ${series.issues === 1 ? 'issue' : 'issues'} to download`,
            series.status !== 'UNKNOWN' &&
              series.status &&
              series.status.charAt(0) + series.status.slice(1).toLowerCase(),
          ]}
        >
          <Facts>
            <Fact label="Writer" value={series.author ? [series.author] : null} />
            <Fact label="Artist" value={series.artist ? [series.artist] : null} />
            <Fact label="Genre" value={series.genre} />
          </Facts>
        </MediaHead>

        {series.description ? <Summary>{series.description}</Summary> : null}

        <MediaFooter
          status={
            state ? { state, text: STATE_LABEL[state], origin: row ? row.origin : undefined } : null
          }
        >
          <Actions>
            <MonitorButton
              monitored={series.inLibrary || row !== null}
              pending={add.isPending || stop.isPending}
              onMonitor={() => add.mutate(id)}
              onStop={row ? () => stop.mutate(row) : undefined}
            />
            {series.inLibrary ? <OpenInSuwayomi href={series.url} /> : null}
          </Actions>
        </MediaFooter>
      </MediaBody>
    </>
  )
}
