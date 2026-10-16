import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, PlayCircle, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  Actions,
  CountdownButton,
  Fact,
  Facts,
  FavouriteFact,
  Links,
  MediaBanner,
  MediaBody,
  ImageZoom,
  MediaDialog,
  MediaFooter,
  MediaHead,
  MonitorButton,
  OutLink,
  Summary,
} from '@/components/MediaDialog'
import { Clip, Notice } from '@/components/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { GAME_STATE, STATE_LABEL, api, posterUrl, releaseLabel, errorText } from '@/lib/api'
import { downloadStage, gameCountdown } from '@/lib/items'
import { useGameMonitor } from '@/lib/monitor'
import { controlClass, outBeforeMonth } from '@/lib/utils'

/** The screenshots are the extra this category adds, and the first thing to drop out. */
export function GameDialog({ igdbId, onClose }: { igdbId: number | null; onClose: () => void }) {
  return (
    <MediaDialog open={igdbId !== null} onClose={onClose}>
      {igdbId === null ? null : <Body igdbId={igdbId} onClose={onClose} />}
    </MediaDialog>
  )
}

function Body({ igdbId, onClose }: { igdbId: number; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [zoomed, setZoomed] = useState<string | null>(null)

  const game = useQuery({ queryKey: ['game', igdbId], queryFn: () => api.game(igdbId) })
  const monitored = useQuery({ queryKey: ['monitored'], queryFn: api.monitored })

  const entry = monitored.data?.find((row) => row.igdb_id === igdbId)

  const { start, stop: remove } = useGameMonitor(onClose)

  // A release PreDB could not vouch for waits for one of these.
  const confirm = useMutation({
    mutationFn: () => api.confirmRelease(entry!.id),
    onSuccess: (found) => {
      toast.success(`Grabbed ${found.matched_release}`)
      void queryClient.invalidateQueries()
    },
    onError: (error: unknown) => toast.error(errorText(error, 'Could not grab it')),
  })
  const reject = useMutation({
    mutationFn: () => api.rejectRelease(entry!.id),
    onSuccess: () => {
      toast.success('Rejected')
      void queryClient.invalidateQueries()
    },
    onError: (error: unknown) => toast.error(errorText(error, 'Could not reject it')),
  })

  if (game.isPending) {
    return (
      <div className="flex h-72 items-center justify-center">
        <Spinner className="size-8 text-ink-dim" />
      </div>
    )
  }

  if (game.isError || !game.data) {
    return (
      <div className="p-6">
        <Notice tone="bad">{errorText(game.error, 'Could not load that game')}</Notice>
      </div>
    )
  }

  const data = game.data
  const extra = data.extra ?? {}
  const shots = (extra.screenshots ?? []).slice(0, 4)
  const busy = start.isPending || remove.isPending || confirm.isPending || reject.isPending

  return (
    <>
      <MediaBanner image={posterUrl(data.artwork_image_id, 'screenshot_huge')} />

      <MediaBody>
        <MediaHead
          art={posterUrl(data.cover_image_id)}
          artLarge={posterUrl(data.cover_image_id, '1080p')}
          shape="poster"
          title={data.name}
          meta={[
            releaseLabel(data.first_release_date, data.release_label),
            data.release_status,
            data.rating ? `${Math.round(data.rating)} user` : null,
            extra.critic_rating ? `${Math.round(extra.critic_rating)} critic` : null,
          ]}
        >
          <div className="flex flex-wrap gap-1.5">
            {[...data.genres, ...(extra.themes ?? [])].slice(0, 6).map((tag) => (
              <Badge
                key={tag}
                variant="outline"
                className="rounded-sm border-line bg-base text-2xs font-normal text-ink-dim"
              >
                {tag}
              </Badge>
            ))}
          </div>

          <Facts>
            <FavouriteFact
              label="Developer"
              category="games"
              kind="company"
              refs={extra.developers}
            />
            <FavouriteFact
              label="Publisher"
              category="games"
              kind="company"
              refs={extra.publishers}
            />
            <FavouriteFact
              label="Franchise"
              category="games"
              kind="franchise"
              refs={extra.franchises}
            />
            <FavouriteFact
              label="Series"
              category="games"
              kind="collection"
              refs={extra.collections}
            />
            <Fact label="Modes" value={extra.game_modes} />
            <Fact label="Perspective" value={extra.player_perspectives} />
            <Fact label="Engine" value={extra.engines} />
            <Fact label="Platforms" value={data.platforms} />
          </Facts>

          <Links>
            {extra.trailer ? (
              <a
                href={extra.trailer.url}
                target="_blank"
                rel="noreferrer"
                className={controlClass()}
              >
                <PlayCircle className="size-3.5" />
                {extra.trailer.name}
              </a>
            ) : null}
            {data.url ? <OutLink href={data.url}>IGDB</OutLink> : null}
          </Links>
        </MediaHead>

        {data.summary ? <Summary>{data.summary}</Summary> : null}

        {shots.length ? (
          <div className="grid shrink-0 grid-cols-2 gap-2 sm:hidden sm:grid-cols-4 sm:vh1100:grid">
            {shots.map((shot, i) => (
              <button
                key={shot}
                type="button"
                aria-label={`Enlarge screenshot ${i + 1}`}
                onClick={() => setZoomed(shot)}
                className="cursor-zoom-in overflow-hidden rounded-sm border border-line bg-base transition-colors hover:border-accent focus-visible:border-accent focus-visible:outline-none"
              >
                <img
                  src={posterUrl(shot, 'screenshot_med')!}
                  alt=""
                  className="aspect-video w-full object-cover"
                />
              </button>
            ))}
          </div>
        ) : null}

        <ImageZoom
          src={zoomed ? posterUrl(zoomed, 'screenshot_huge') : null}
          alt={`${data.name} screenshot`}
          onClose={() => setZoomed(null)}
        />

        <MediaFooter
          status={
            entry
              ? {
                  state: GAME_STATE[entry.status],
                  text:
                    entry.status === 'matched' ? (
                      <>
                        Notified
                        <Clip className="font-mono text-2xs text-ink-dim">
                          {entry.matched_release}
                        </Clip>
                        <span className="shrink-0 text-2xs text-ink-dim">
                          {downloadStage(entry)}
                        </span>
                      </>
                    ) : entry.review_release ? (
                      <>
                        Confirm
                        <Clip className="font-mono text-2xs text-ink-dim">
                          {entry.review_release}
                        </Clip>
                      </>
                    ) : entry.status === 'notified' || entry.status === 'tracking' ? (
                      STATE_LABEL[GAME_STATE[entry.status]]
                    ) : (
                      'Monitoring'
                    ),
                }
              : null
          }
        >
          <Actions>
            {entry || !outBeforeMonth(data.first_release_date) ? (
              <MonitorButton
                monitored={entry !== undefined}
                pending={start.isPending || remove.isPending}
                disabled={busy}
                onMonitor={() => start.mutate({ igdb_id: igdbId })}
                onStop={() => entry && remove.mutate(entry)}
              />
            ) : null}

            {entry?.review_release ? (
              <>
                <Button
                  variant="ghost"
                  onClick={() => confirm.mutate()}
                  disabled={busy}
                  className="gap-2 text-ink-dim hover:text-accent"
                >
                  {confirm.isPending ? (
                    <Spinner className="size-4" />
                  ) : (
                    <Check className="size-4" />
                  )}
                  Grab it
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => reject.mutate()}
                  disabled={busy}
                  className="gap-2 text-ink-dim hover:text-bad"
                >
                  {reject.isPending ? <Spinner className="size-4" /> : <X className="size-4" />}
                  Reject
                </Button>
              </>
            ) : null}
            <CountdownButton
              target={gameCountdown(
                data.igdb_id,
                data.name,
                data.cover_image_id,
                data.first_release_date,
              )}
            />
          </Actions>
        </MediaFooter>
      </MediaBody>
    </>
  )
}
