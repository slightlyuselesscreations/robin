import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { LibraryBig } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { BookMenu } from '@/components/ItemMenus'
import { Items, Skeletons } from '@/components/MediaCard'
import {
  Control,
  KeptSelect,
  NextPage,
  Notice,
  Options,
  Page,
  PageHeader,
  Section,
  Sections,
  Segmented,
  SourceCredit,
  ViewSwitch,
} from '@/components/Page'
import { type Book, type BookFilters, api, errorText } from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { KEPT, WINDOWS, asView, usePageControls, windowDays } from '@/lib/controls'
import { bookItem, bookRemindersOf } from '@/lib/items'
import { useScrollPaging } from '@/lib/paging'
import { filtered } from '@/lib/utils'
import { withParam } from '@/lib/params'

/** Pages hold forty books. Past this many a scroll is not looking for anything. */
const MAX_PAGES = 10

const KINDS = [
  { value: 'fiction', label: 'Fiction', type: 1 },
  { value: 'nonfiction', label: 'Nonfiction', type: 2 },
] as const

/** Every control as it starts on a bare `/books`, before the defaults saved for the page. */
const BUILTIN = { view: 'cover', kind: KEPT, genre: KEPT, days: '90' }

/** The controls as Hardcover is asked, anything no longer offered taking its default. */
function readFilters(values: typeof BUILTIN): BookFilters {
  return {
    days: windowDays(values.days, BUILTIN.days),
    kind: KINDS.find((k) => k.value === values.kind)?.value ?? '',
    genre: values.genre === KEPT ? '' : values.genre,
  }
}

/**
 * Upcoming books from Hardcover, most anticipated first. Literary types, categories and genres
 * are hidden in Settings, the header narrows what is left.
 */
export function Books() {
  const [params] = useSearchParams()
  const controls = usePageControls('books', BUILTIN)
  const view = asView(controls.values.view, 'cover')
  const filters = readFilters(controls.values)
  const settings = useSettings()
  const hiddenTypes = settings.data?.books_hidden_literary_types ?? []
  const hiddenGenres = settings.data?.books_hidden_genres ?? []
  const hidden = [
    hiddenTypes,
    hiddenGenres,
    settings.data?.books_hidden_categories,
    settings.data?.books_shown_genres,
  ]
  // The page narrows what Settings leaves shown.
  const kinds = KINDS.filter((k) => !hiddenTypes.includes(k.type))

  const set = (changes: Partial<typeof BUILTIN>) => controls.set({ ...changes, book: null })

  const genres = useQuery({
    queryKey: ['book-genres'],
    queryFn: api.bookGenres,
    staleTime: Infinity,
  })
  const genreName = (slug: string) => genres.data?.find((g) => g.slug === slug)?.name ?? slug
  const reminders = useQuery({ queryKey: ['book-reminders'], queryFn: api.bookReminders })

  const books = useInfiniteQuery({
    queryKey: ['books', filters, hidden],
    queryFn: ({ pageParam }) => api.books(filters, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last, all) =>
      all.length >= MAX_PAGES || !last.more ? undefined : last.page + 1,
    staleTime: 10 * 60_000,
    // A change of controls keeps the current list, dimmed, until the new one is in.
    placeholderData: keepPreviousData,
  })

  useScrollPaging(books)

  // A book can come back on two pages when its readers change between them.
  const seen = new Set<number>()
  const list = (books.data?.pages.flatMap((p) => p.books) ?? []).filter(
    (b) => !seen.has(b.id) && seen.add(b.id),
  )
  const link = (book: Book) => withParam(params, 'book', book.id)
  const items = list.map((b) => ({
    ...bookItem(b, link(b), bookRemindersOf(b, reminders.data ?? [])),
    menu: <BookMenu id={b.id} />,
  }))

  return (
    <Page>
      <PageHeader title="Books" icon={LibraryBig}>
        <Options controls={controls}>
          <ViewSwitch value={view} onChange={(next) => set({ view: next })} />
          {kinds.length > 1 ? (
            <Control label="Kind">
              <Segmented
                label="Kind"
                options={[{ value: KEPT, label: 'All' }, ...kinds]}
                value={filters.kind || KEPT}
                onChange={(kind) => set({ kind })}
              />
            </Control>
          ) : null}
          <Control label="Genre">
            <KeptSelect
              value={filters.genre}
              kept={filtered(genres.data ?? [], hiddenGenres, (g) => g.slug, genreName)}
              any="Any genre"
              options={(genres.data ?? [])
                .filter((g) => !hiddenGenres.includes(g.slug))
                .map((g) => ({ value: g.slug, label: g.name }))}
              onChange={(next) => set({ genre: next })}
            />
          </Control>
          <Control label="Window">
            <Segmented
              label="Window"
              options={WINDOWS}
              value={String(filters.days)}
              onChange={(days) => set({ days })}
            />
          </Control>
        </Options>
      </PageHeader>

      {books.isPending ? (
        <Skeletons shape="cover" count={18} />
      ) : books.isError ? (
        <Notice tone="bad">{errorText(books.error, 'Hardcover is unreachable')}</Notice>
      ) : list.length === 0 ? (
        <Notice>Nothing coming in this window.</Notice>
      ) : (
        <>
          <Sections dimmed={books.isPlaceholderData}>
            <Section title="Hardcover" icon={LibraryBig} count={list.length}>
              <Items view={view} metaLabel="Release" items={items} />
            </Section>
          </Sections>

          <NextPage loading={books.isFetchingNextPage} />
        </>
      )}

      <SourceCredit name="Hardcover" href="https://hardcover.app" />
    </Page>
  )
}
