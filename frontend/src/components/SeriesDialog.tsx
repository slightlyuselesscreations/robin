import { useQuery } from '@tanstack/react-query'

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
  OutLink,
  Summary,
} from '@/components/MediaDialog'
import { type Series, api } from '@/lib/api'
import { useAddSeries } from '@/lib/monitor'

/**
 * A series found by searching the Suwayomi source. Adding it hands it to Suwayomi straight
 * away, there is no #1 to wait for, so Robin keeps no record of it.
 */
export function SeriesDialog({ series, onClose }: { series: Series | null; onClose: () => void }) {
  return (
    <MediaDialog open={series !== null} onClose={onClose}>
      {series === null ? null : <Body listed={series} />}
    </MediaDialog>
  )
}

function Body({ listed }: { listed: Series }) {
  const detail = useQuery({
    queryKey: ['series', listed.id],
    queryFn: () => api.series(listed.id),
    initialData: listed,
    // The listing carries no description, so it is only a placeholder for the real answer.
    initialDataUpdatedAt: 0,
    retry: false,
  })

  const add = useAddSeries()

  const series = detail.data
  return (
    <>
      <MediaBanner image={series.thumbnailUrl} cover />
      <MediaBody>
        <MediaHead
          art={series.thumbnailUrl}
          shape="cover"
          title={series.title}
          meta={[
            series.issues === undefined
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
            series.inLibrary
              ? {
                  state: 'found',
                  text: (
                    <>
                      In the library
                      <OutLink href={series.url} accent>
                        Open in Suwayomi
                      </OutLink>
                    </>
                  ),
                }
              : null
          }
        >
          <Actions>
            <MonitorButton
              monitored={series.inLibrary}
              pending={add.isPending}
              onMonitor={() => add.mutate(listed.id)}
            />
          </Actions>
        </MediaFooter>
      </MediaBody>
    </>
  )
}
