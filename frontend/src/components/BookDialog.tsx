import { useQuery } from '@tanstack/react-query'
import { BookmarkCheck, BookmarkPlus } from 'lucide-react'

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
import { Spinner } from '@/components/ui/spinner'
import { type BookDetail, REMINDER_STATE, STATE_LABEL, api, errorText } from '@/lib/api'
import { useBookReminders, useShelf } from '@/lib/bookReminders'
import { calendarDay, seriesLabel } from '@/lib/items'
import { outBeforeMonth } from '@/lib/utils'

/** One book, opened from any page by `?book=<hardcover id>`. */
export function BookDialog({ id, onClose }: { id: number | null; onClose: () => void }) {
  return (
    <MediaDialog open={id !== null} onClose={onClose}>
      {id !== null ? <Body id={id} /> : null}
    </MediaDialog>
  )
}

function Body({ id }: { id: number }) {
  const detail = useQuery({
    queryKey: ['book', id],
    queryFn: () => api.book(id),
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
        <Notice tone="bad">{errorText(detail.error, 'Hardcover is unreachable')}</Notice>
      </div>
    )
  return <Detail book={detail.data} />
}

function Detail({ book }: { book: BookDetail }) {
  return (
    <>
      <MediaBanner image={book.cover} cover />
      <MediaBody>
        <MediaHead
          art={book.cover}
          shape="cover"
          title={book.title}
          meta={[
            calendarDay(book.date),
            book.pages ? `${book.pages} pages` : null,
            book.rating ? `${book.rating} on Hardcover` : null,
            book.readers ? `${book.readers} readers` : null,
          ]}
        >
          {book.subtitle ? <p className="text-xs text-ink-faint">{book.subtitle}</p> : null}
          <Facts>
            <FavouriteFact label="Author" category="books" kind="author" refs={book.author_refs} />
            <FavouriteFact
              label="Series"
              category="books"
              kind="series"
              refs={
                book.series
                  ? [{ id: book.series.id, name: seriesLabel(book.series) ?? book.series.name }]
                  : null
              }
            />
            <Fact label="Genres" value={book.genres} />
          </Facts>
          <Links>
            <OutLink href={book.hardcover}>Hardcover</OutLink>
          </Links>
        </MediaHead>
        {book.headline ? (
          <p className="shrink-0 text-sm text-ink-dim italic">{book.headline}</p>
        ) : null}
        {book.overview ? <Summary>{book.overview}</Summary> : null}
        <Footer book={book} />
      </MediaBody>
    </>
  )
}

/**
 * Monitoring a book is a reminder on the Books topic ahead of its date. Its series is followed
 * by favouriting the series. Want to Read shelves the book on Hardcover and is apart from
 * monitoring.
 */
function Footer({ book }: { book: BookDetail }) {
  const { ready, mine, choose } = useBookReminders(book)
  const shelf = useShelf(book.id)
  const [shown] = mine

  return (
    <MediaFooter
      status={
        shown
          ? {
              state: REMINDER_STATE[shown.status],
              text: STATE_LABEL[REMINDER_STATE[shown.status]],
            }
          : null
      }
    >
      <Actions>
        {ready && (mine.length > 0 || !outBeforeMonth(book.date)) ? (
          <MonitorButton
            monitored={mine.length > 0}
            pending={choose.isPending}
            onMonitor={() => choose.mutate(true)}
            onStop={() => choose.mutate(false)}
          />
        ) : null}
        <Button
          variant="ghost"
          onClick={() => shelf.set.mutate(!shelf.want)}
          disabled={!shelf.loaded || shelf.set.isPending}
          className="gap-2 text-ink-dim hover:text-accent"
        >
          {shelf.set.isPending ? (
            <Spinner className="size-4" />
          ) : shelf.want ? (
            <BookmarkCheck className="size-4" />
          ) : (
            <BookmarkPlus className="size-4" />
          )}
          {shelf.want ? 'On Want to Read' : 'Want to Read'}
        </Button>
        <CountdownButton
          target={{
            category: 'books',
            target: `book=${book.id}`,
            title: book.title,
            image: book.cover,
            date: book.date,
          }}
        />
      </Actions>
    </MediaFooter>
  )
}
