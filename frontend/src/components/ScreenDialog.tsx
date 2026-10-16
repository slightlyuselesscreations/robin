import { useQuery } from '@tanstack/react-query'
import { CirclePlus } from 'lucide-react'

import { ReleaseTag } from '@/components/MediaCard'
import {
  Actions,
  CountdownButton,
  Fact,
  Facts,
  FavouriteFact,
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
import { Notice } from '@/components/Page'
import { Button } from '@/components/ui/button'
import { DropdownMenuRadioGroup, DropdownMenuRadioItem } from '@/components/ui/dropdown-menu'
import { Spinner } from '@/components/ui/spinner'
import {
  REMINDER_STATE,
  type Reminder,
  STATE_LABEL,
  type ScreenDetail,
  type ScreenKind,
  api,
  errorText,
} from '@/lib/api'
import { useArrAdd } from '@/lib/arr'
import { calendarDay, platformTag } from '@/lib/items'
import {
  currentChoice,
  reminderChoices,
  screenMonitorable,
  typesFor,
  useReminders,
} from '@/lib/reminders'
import { outBeforeMonth } from '@/lib/utils'

/** One movie or show, opened from the Screens page by `?title=movie-123`. */
export function ScreenDialog({
  open,
  onClose,
}: {
  open: { kind: ScreenKind; id: number } | null
  onClose: () => void
}) {
  return (
    <MediaDialog open={open !== null} onClose={onClose}>
      {open ? <Body kind={open.kind} id={open.id} /> : null}
    </MediaDialog>
  )
}

function Body({ kind, id }: { kind: ScreenKind; id: number }) {
  const detail = useQuery({
    queryKey: ['screen-title', kind, id],
    queryFn: () => api.screenTitle(kind, id),
    staleTime: 60 * 60_000,
  })

  if (detail.isPending)
    return (
      <div className="flex h-72 items-center justify-center">
        <Spinner className="size-8 text-ink-dim" />
      </div>
    )
  if (detail.isError)
    return (
      <div className="p-6">
        <Notice tone="bad">{errorText(detail.error, 'TMDB is unreachable')}</Notice>
      </div>
    )
  return <Detail title={detail.data} />
}

function Detail({ title }: { title: ScreenDetail }) {
  const { library } = useArrAdd(title.kind, title.id)
  const next = title.next_episode
  const when = next
    ? `S${next.season} E${next.episode} on ${calendarDay(next.date)}`
    : calendarDay(title.date)
  return (
    <>
      <MediaBanner image={title.backdrop} />
      <MediaBody>
        <MediaHead
          art={title.poster}
          artLarge={title.poster?.replace('/w342/', '/original/')}
          shape="cover"
          title={title.title}
          library={library}
          meta={[
            when,
            title.platform ? (
              <ReleaseTag
                key="release"
                platform={platformTag(title.platform, title.date, title.kind)}
                className="inline-block align-bottom normal-case"
              />
            ) : (
              title.release
            ),
            title.certification,
            title.runtime ? `${title.runtime} min` : null,
            title.seasons ? `${title.seasons} season${title.seasons === 1 ? '' : 's'}` : null,
            title.status,
          ]}
        >
          {title.original_title && title.original_title !== title.title ? (
            <p className="text-xs text-ink-faint">{title.original_title}</p>
          ) : null}
          <Facts>
            <Fact label="Genres" value={title.genres} />
            <FavouriteFact
              label={title.kind === 'movie' ? 'Director' : 'Created by'}
              category="screens"
              kind="person"
              refs={title.makers}
            />
            <FavouriteFact label="Cast" category="screens" kind="person" refs={title.cast} />
            <FavouriteFact
              label={title.kind === 'movie' ? 'Studios' : 'Network'}
              category="screens"
              kind={title.kind === 'movie' ? 'studio' : 'network'}
              refs={title.companies}
            />
            <Fact label="Stream" value={title.watch.stream} />
            <Fact
              label="Rent or buy"
              value={[...new Set([...title.watch.rent, ...title.watch.buy])]}
            />
          </Facts>
          <Links>
            {title.trailer ? (
              <OutLink href={title.trailer} accent>
                Trailer
              </OutLink>
            ) : null}
            <OutLink href={title.tmdb}>TMDB</OutLink>
            {title.imdb ? <OutLink href={title.imdb}>IMDb</OutLink> : null}
            {title.watch.link ? <OutLink href={title.watch.link}>Where to watch</OutLink> : null}
            {title.homepage ? <OutLink href={title.homepage}>Website</OutLink> : null}
          </Links>
        </MediaHead>
        {title.tagline ? (
          <p className="shrink-0 text-sm text-ink-dim italic">{title.tagline}</p>
        ) : null}
        {title.overview ? <Summary>{title.overview}</Summary> : null}
        <Remind title={title} />
      </MediaBody>
    </>
  )
}

/**
 * Monitoring a title is a reminder, sent on the Screens topic ahead of the date. A film's
 * button monitors every release the region has dated, and its menu picks cinema only, digital
 * only or both. A show's covers every season premiere. Left out while Screens notifications
 * are off.
 */
function Remind({ title }: { title: ScreenDetail }) {
  const { ready, mine, choose } = useReminders(title.kind, title.id)
  const arr = useArrAdd(title.kind, title.id)
  const choices = reminderChoices(title.releases)
  const offered = choices.filter((c) => !c.disabled)
  const current = currentChoice(mine)
  const fallback = offered.find((c) => c.value === 'both') ?? offered[0]
  const tags = new Map(title.releases.map((r) => [r.type, r.platform ? r.platform.name : r.tag]))
  const waiting = mine.filter((r) => r.status === 'waiting')
  const shown: Reminder[] = waiting.length ? waiting : mine
  const busy = choose.isPending
  const set = mine.length > 0

  const monitor = () => choose.mutate(title.kind === 'movie' ? fallback.types : [undefined])

  return (
    <MediaFooter
      status={
        shown.length
          ? {
              state: REMINDER_STATE[shown[0].status],
              text: [
                STATE_LABEL[REMINDER_STATE[shown[0].status]],
                ...shown.map((r) => (r.release_type ? (tags.get(r.release_type) ?? '') : '')),
              ]
                .filter(Boolean)
                .join(' · '),
            }
          : null
      }
    >
      <Actions>
        {!ready ? null : set || screenMonitorable(title) ? (
          <MonitorButton
            monitored={set}
            pending={busy}
            onMonitor={monitor}
            onStop={() => choose.mutate([])}
            choices={
              title.kind === 'movie' ? (
                <DropdownMenuRadioGroup
                  value={current ?? ''}
                  onValueChange={(value) => choose.mutate(typesFor(choices, current, value))}
                >
                  {choices.map((choice) => (
                    <DropdownMenuRadioItem
                      key={choice.value}
                      value={choice.value}
                      disabled={choice.disabled}
                    >
                      {choice.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              ) : undefined
            }
          />
        ) : title.kind === 'movie' && !outBeforeMonth(title.date) ? (
          <span className="text-2xs text-ink-faint">No release dated in your region yet.</span>
        ) : null}
        {arr.offered ? (
          <Button
            variant="ghost"
            onClick={() => arr.add.mutate()}
            disabled={arr.add.isPending}
            className="gap-2 text-ink-dim hover:text-accent"
          >
            {arr.add.isPending ? <Spinner className="size-4" /> : <CirclePlus className="size-4" />}
            {arr.label}
          </Button>
        ) : null}
        <CountdownButton
          target={{
            category: 'screens',
            target: `title=${title.kind}-${title.id}`,
            title: title.title,
            image: title.poster,
            date: title.next_episode?.date ?? title.date,
          }}
        />
      </Actions>
    </MediaFooter>
  )
}
