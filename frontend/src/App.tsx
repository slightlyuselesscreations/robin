import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { Suspense, lazy, useEffect, useRef } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import { toast } from 'sonner'

import { ArrRemoveDialog } from '@/components/ArrRemoveDialog'
import { BookDialog } from '@/components/BookDialog'
import { AnyComicDialog } from '@/components/ComicDialog'
import { AnySeriesDialog } from '@/components/SeriesDialog'
import { GameDialog } from '@/components/GameDialog'
import { FavouriteDialog } from '@/components/FavouriteDialog'
import { CategoryGate } from '@/components/Gate'
import { Shell } from '@/components/Nav'
import { Notice, Page } from '@/components/Page'
import { ScreenDialog } from '@/components/ScreenDialog'
import { Toaster } from '@/components/ui/sonner'
import { Spinner } from '@/components/ui/spinner'
import { TooltipProvider } from '@/components/ui/tooltip'
import {
  ApiError,
  PAUSED,
  type Paused,
  STALE,
  type ScreenKind,
  type Stale,
  api,
  latest,
} from '@/lib/api'
import { CATEGORIES, useShown } from '@/lib/categories'
import { parseFavouriteParam } from '@/lib/favourites'
import { markReload } from '@/lib/outdated'
import { useDialogParam, useDialogTrail } from '@/lib/params'
import { Books } from '@/pages/Books'
import { Comics } from '@/pages/Comics'
import { Favourites } from '@/pages/Favourites'
import { Logs } from '@/pages/Logs'
import { Games } from '@/pages/Games'
import { Monitored } from '@/pages/Monitored'
import { Screen } from '@/pages/Screen'
import { Search } from '@/pages/Search'
import { SettingsPage, Setup } from '@/pages/SettingsPage'
import { AuthGate } from '@/pages/SignIn'

// Home carries the charts and the calendar, so it loads on its own and the rest stays light.
const Home = lazy(() => import('@/pages/Home').then((m) => ({ default: m.Home })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // Once, and only when the failure might pass. Unset, refused or paused is final.
      retry: (failures, error) =>
        failures < 1 && !(error instanceof ApiError && error.status < 500),
    },
  },
})

const STATUS_BEARING = ['games', 'search', 'game']

/**
 * Polls the monitored list, since the backend grabs a game on its own, and refreshes the cards
 * once a status changes, since their badges ride on cached listings.
 */
function MatchWatcher() {
  const client = useQueryClient()
  const monitored = useQuery({
    queryKey: ['monitored'],
    queryFn: api.monitored,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
    enabled: useShown()('games'),
  })
  const signature = monitored.data?.map((row) => `${row.id}:${row.status}`).join()
  const previous = useRef(signature)

  useEffect(() => {
    if (previous.current !== undefined && previous.current !== signature) {
      void client.invalidateQueries({
        predicate: (query) => STATUS_BEARING.includes(String(query.queryKey[0])),
      })
    }
    previous.current = signature
  }, [client, signature])

  return null
}

/**
 * One toast when a data source asks Robin to slow down, however many requests it turned away.
 * The page that asked shows the same words where its content would be.
 */
function PauseAlerts() {
  const seen = useRef(new Set<string>())
  useEffect(() => {
    const onPaused = (event: Event) => {
      const { source, until, message } = (event as CustomEvent<Paused>).detail
      const key = `${source}:${until}`
      if (seen.current.has(key)) return
      seen.current.add(key)
      toast.error(message, { description: 'Robin asks it again once the pause is over.' })
    }
    window.addEventListener(PAUSED, onPaused)
    return () => window.removeEventListener(PAUSED, onPaused)
  }, [])
  return null
}

const PAGES: Record<string, string> = {
  ...Object.fromEntries(CATEGORIES.map((c) => [c.to, c.label])),
  '/monitored': 'Monitored',
  '/favourites': 'Favourites',
  '/search': 'Search',
  '/settings': 'Settings',
}

const pageName = (pathname: string) =>
  pathname === '/'
    ? 'Home'
    : (Object.entries(PAGES).find(([to]) => pathname.startsWith(to))?.[1] ?? 'Page')

const OUTDATED = 'outdated'

/**
 * A page answered with what Robin kept past its lifetime asks once more for each answer,
 * waiting for its source. When that comes back different, one toast offers it, until the page
 * is left.
 */
function StaleAlerts() {
  const client = useQueryClient()
  const { pathname } = useLocation()
  useEffect(() => {
    const asked = new Set<string>()
    let left = false
    const reload = () => {
      markReload()
      void client.invalidateQueries({
        predicate: (query) => !['me', 'settings'].includes(String(query.queryKey[0])),
      })
    }
    const onStale = (event: Event) => {
      const { path, body } = (event as CustomEvent<Stale>).detail
      if (asked.has(path)) return
      asked.add(path)
      latest(path)
        .then((answer) => {
          if (left || JSON.stringify(answer) === JSON.stringify(body)) return
          toast(`${pageName(pathname)} data outdated`, {
            id: OUTDATED,
            description: 'Reload the page to see the latest changes',
            duration: Infinity,
            closeButton: true,
            action: { label: 'Reload', onClick: reload },
          })
        })
        // The page keeps what it has, and a paused source has its own toast.
        .catch(() => undefined)
    }
    window.addEventListener(STALE, onStale)
    return () => {
      left = true
      window.removeEventListener(STALE, onStale)
      toast.dismiss(OUTDATED)
    }
  }, [client, pathname])
  return null
}

const asId = (raw: string | null) => (raw && /^\d+$/.test(raw) ? Number(raw) : null)

/** A game, `?game=<igdb id>`, opened over whichever page links it. */
function SelectedGame() {
  const [raw, close] = useDialogParam('game')
  return <GameDialog igdbId={asId(raw)} onClose={close} />
}

/** A movie or show, `?title=movie-<id>` or `tv-<id>`, opened over whichever page links it. */
function SelectedTitle() {
  const [raw, close] = useDialogParam('title')
  const [kind, id] = (raw ?? '').split('-')
  const open =
    (kind === 'movie' || kind === 'tv') && Number(id) > 0
      ? { kind: kind as ScreenKind, id: Number(id) }
      : null
  return <ScreenDialog open={open} onClose={close} />
}

/** A book, `?book=<hardcover id>`, opened over whichever page links it. */
function SelectedBook() {
  const [raw, close] = useDialogParam('book')
  return <BookDialog id={asId(raw)} onClose={close} />
}

/** A developer, person, studio, network, author or series, `?favourite=screens-network-213`. */
function SelectedFavourite() {
  const shown = useShown()
  const [raw, close] = useDialogParam('favourite')
  const open = parseFavouriteParam(raw)
  return <FavouriteDialog open={open && shown(open.category) ? open : null} onClose={close} />
}

/**
 * The dialogs of every category shown, each opened by its own search parameter. On the Comics
 * page `?comic=` names an issue that page opens itself.
 */
function Dialogs() {
  const shown = useShown()
  const { pathname } = useLocation()
  useDialogTrail()
  return (
    <>
      {shown('games') ? <SelectedGame /> : null}
      {shown('comics') && !pathname.startsWith('/comics') ? <AnyComicDialog /> : null}
      {shown('comics') && !pathname.startsWith('/comics') ? <AnySeriesDialog /> : null}
      {shown('screens') ? <SelectedTitle /> : null}
      {shown('books') ? <SelectedBook /> : null}
      <SelectedFavourite />
    </>
  )
}

/** A fresh install walks through setup once before anything else. */
function SetupGate({ children }: { children: React.ReactNode }) {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  if (me.data?.setup == null) return children
  return <Setup step={me.data.setup} />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AuthGate>
          <BrowserRouter>
            <SetupGate>
              <Shell>
                <Routes>
                  <Route
                    path="/"
                    element={
                      <Suspense fallback={<Spinner className="m-10 size-8 text-ink-dim" />}>
                        <Home />
                      </Suspense>
                    }
                  />
                  <Route
                    path="/games"
                    element={
                      <CategoryGate category="games">
                        <Games />
                      </CategoryGate>
                    }
                  />
                  <Route
                    path="/comics"
                    element={
                      <CategoryGate category="comics">
                        <Comics />
                      </CategoryGate>
                    }
                  />
                  <Route
                    path="/screens"
                    element={
                      <CategoryGate category="screens">
                        <Screen />
                      </CategoryGate>
                    }
                  />
                  <Route
                    path="/books"
                    element={
                      <CategoryGate category="books">
                        <Books />
                      </CategoryGate>
                    }
                  />
                  <Route path="/search" element={<Search />} />
                  <Route path="/monitored" element={<Monitored />} />
                  <Route path="/favourites" element={<Favourites />} />
                  <Route path="/logs" element={<Logs />} />
                  <Route path="/settings/:tab?" element={<SettingsPage />} />
                  <Route
                    path="*"
                    element={
                      <Page>
                        <Notice>Nothing here.</Notice>
                      </Page>
                    }
                  />
                </Routes>
              </Shell>
              <Dialogs />
              <MatchWatcher />
              <PauseAlerts />
              <StaleAlerts />
              <ArrRemoveDialog />
            </SetupGate>
            <Toaster position="bottom-right" />
          </BrowserRouter>
        </AuthGate>
      </TooltipProvider>
    </QueryClientProvider>
  )
}
