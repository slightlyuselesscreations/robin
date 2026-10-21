import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { LibraryBig } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { BookMenu } from '@/components/ItemMenus'
import { Items, Skeletons } from '@/components/MediaCard'
import {
  Control,
  FilterSelect,
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
import { HEADER_CONTROLS, ORDERS, asView, narrowed, pickOf, usePageControls } from '@/lib/controls'
import { bookItem, bookRemindersOf } from '@/lib/items'
import { useScrollPaging } from '@/lib/paging'
import { withParam } from '@/lib/params'

/** Pages hold forty books. Past this many a scroll is not looking for anything. */
const MAX_PAGES = 10

/** The literary types, by Hardcover's id, which Settings hides by. */
const TYPES = [
  { value: 'all', label: 'All', id: 0 },
  { value: 'fiction', label: 'Fiction', id: 1 },
  { value: 'nonfiction', label: 'Nonfiction', id: 2 },
] as const

const ORDER = [ORDERS.popularity, ORDERS.date]

/**
 * Every control as it starts on a bare `/books`, before the defaults saved for the page. A
 * filter is empty for all of what Settings leaves.
 */
const BUILTIN = { view: 'cover', type: 'all', order: 'popularity', genre: '' }

/**
 * Upcoming books from Hardcover, most anticipated first. Literary types, categories and genres
 * are hidden in Settings, and the type and the filters in Options narrow what is left.
 */
export function Books() {
  const [params] = useSearchParams()
  const controls = usePageControls('books', BUILTIN)
  const { values } = controls
  const view = asView(values.view, 'cover')
  const settings = useSettings()
  const hiddenTypes = settings.data?.books_hidden_literary_types ?? []
  const hiddenGenres = settings.data?.books_hidden_genres ?? []
  const hidden = [
    hiddenTypes,
    hiddenGenres,
    settings.data?.books_hidden_categories,
    settings.data?.books_shown_genres,
  ]
  // All, then each literary type Settings leaves, offered only while there is more than one.
  const left = TYPES.filter((t) => t.id === 0 || !hiddenTypes.includes(t.id))
  const types = left.length > 2 ? left : []
  const type = types.length ? pickOf(values.type, types) : 'all'

  const set = (changes: Partial<typeof BUILTIN>) => controls.set({ ...changes, book: null })

  const genres = useQuery({
    queryKey: ['book-genres'],
    queryFn: api.bookGenres,
    staleTime: Infinity,
  })
  const genreOptions = genres.data
    ?.filter((g) => !hiddenGenres.includes(g.slug))
    .map((g) => ({ value: g.slug, label: g.name }))
  const filters: BookFilters = {
    kind: type === 'all' ? '' : type,
    genre: narrowed(values.genre, genreOptions),
    sort: pickOf(values.order, ORDER),
  }

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
        {types.length ? (
          <Segmented
            label="Type"
            options={types}
            value={type}
            onChange={(next) => set({ type: next })}
          />
        ) : null}
        <Segmented
          label="Order"
          options={ORDER}
          value={pickOf(values.order, ORDER)}
          onChange={(order) => set({ order })}
        />
        <Options controls={controls} header={HEADER_CONTROLS}>
          <ViewSwitch value={view} onChange={(next) => set({ view: next })} />
          <Control label="Genre">
            <FilterSelect
              value={filters.genre}
              all="All genres"
              options={genreOptions ?? []}
              onChange={(genre) => set({ genre })}
            />
          </Control>
        </Options>
      </PageHeader>

      {books.isPending ? (
        <Skeletons shape="cover" count={18} />
      ) : books.isError ? (
        <Notice tone="bad">{errorText(books.error, 'Hardcover is unreachable')}</Notice>
      ) : list.length === 0 ? (
        <Notice>Nothing coming.</Notice>
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
