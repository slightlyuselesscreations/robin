import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  Building2,
  Code,
  Megaphone,
  Clapperboard,
  Layers,
  Library,
  type LucideIcon,
  Orbit,
  Tv,
  UserRound,
  VenetianMask,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  type Category,
  type Entity,
  type Favourite,
  type FavouriteCategory,
  type FavouriteKind,
  type MakerFilter,
  type MakerMode,
  type Role,
  type ScreenTitle,
  api,
  errorText,
} from '@/lib/api'
import { askArrRemove, heldOf, useLibrary } from '@/lib/arr'
import { CATEGORY, useSearchable } from '@/lib/categories'

/** What each kind of favourite is called where a list of them is shown. */
export const KIND_LABEL: Record<FavouriteKind, string> = {
  company: 'Developers and publishers',
  franchise: 'Franchises',
  collection: 'Series',
  person: 'People',
  studio: 'Studios',
  network: 'Networks',
  author: 'Authors',
  series: 'Series',
  publisher: 'Publishers',
  character: 'Characters',
  universe: 'Universes',
}

/** The icon each kind of favourite is named with. */
export const KIND_ICON: Record<FavouriteKind, LucideIcon> = {
  company: Building2,
  franchise: Layers,
  collection: Library,
  person: UserRound,
  studio: Clapperboard,
  network: Tv,
  author: BookOpen,
  series: Library,
  publisher: Building2,
  character: VenetianMask,
  universe: Orbit,
}

/** The kinds each category can favourite, in the order they are listed. */
export const KINDS: Record<FavouriteCategory, FavouriteKind[]> = {
  games: ['company', 'franchise', 'collection'],
  comics: ['series', 'person', 'publisher', 'character', 'universe'],
  screens: ['person', 'studio', 'network'],
  books: ['author', 'series'],
}

/** Its own source, for the link out. */
export const SOURCE: Record<FavouriteCategory, string> = {
  games: 'IGDB',
  comics: 'Metron',
  screens: 'TMDB',
  books: 'Hardcover',
}

/**
 * What a search is narrowed to: a category's titles, `?type=games`, or one kind of what they
 * come from, `?type=screens-person`. A company is searched as a developer or as a publisher,
 * `?type=games-developer`, either way the same favourite.
 */
export type SearchScope = {
  value: string
  category: Category
  kind: FavouriteKind | null
  role: Role | null
  label: string
  icon: LucideIcon
}

// A company is one favourite, but a game names its developer and its publisher apart, and so
// does a search.
const ROLES: { role: Role; label: string; icon: LucideIcon }[] = [
  { role: 'developer', label: 'Developers', icon: Code },
  { role: 'publisher', label: 'Publishers', icon: Megaphone },
]

// Two kinds are both called Series on their own. In one list beside each other they say whose.
const SCOPE_LABEL: Partial<Record<FavouriteKind, string>> = {
  collection: 'Game series',
  series: 'Book series',
}

/** Every scope a search can take, each category's titles first, then its kinds. */
export function useSearchScopes(): SearchScope[] {
  return useSearchable().flatMap((category) => [
    {
      value: category,
      category,
      kind: null,
      role: null,
      label: CATEGORY[category].label,
      icon: CATEGORY[category].icon,
    },
    // A comic series is what Comics titles search finds, so it is no scope of its own.
    ...(category in KINDS ? KINDS[category as FavouriteCategory] : [])
      .filter((kind) => !(category === 'comics' && kind === 'series'))
      .flatMap((kind): SearchScope[] =>
        kind === 'company'
          ? ROLES.map(({ role, label, icon }) => ({
              value: `${category}-${role}`,
              category,
              kind,
              role,
              label,
              icon,
            }))
          : [
              {
                value: `${category}-${kind}`,
                category,
                kind,
                role: null,
                label: SCOPE_LABEL[kind] ?? KIND_LABEL[kind],
                icon: KIND_ICON[kind],
              },
            ],
      ),
  ])
}

/** The favourite an entity is, matched on any of the ids it covers. */
export function findFavourite(
  favourites: Favourite[] | undefined,
  entity: Pick<Entity, 'category' | 'kind' | 'id'>,
): Favourite | null {
  return (
    favourites?.find(
      (f) => f.category === entity.category && f.kind === entity.kind && f.ids.includes(entity.id),
    ) ?? null
  )
}

/** A favourite's dialog parameter, `?favourite=screens-network-213`. */
export function favouriteParam(entity: Pick<Entity, 'category' | 'kind' | 'id'>): string {
  return `${entity.category}-${entity.kind}-${entity.id}`
}

export function parseFavouriteParam(
  raw: string | null,
): Pick<Entity, 'category' | 'kind' | 'id'> | null {
  const [category, kind, id] = (raw ?? '').split('-')
  if (!(category in KINDS)) return null
  const kinds: string[] = KINDS[category as FavouriteCategory]
  if (!kinds.includes(kind) || !(Number(id) > 0)) return null
  return { category: category as FavouriteCategory, kind: kind as FavouriteKind, id: Number(id) }
}

export function useFavourites() {
  return useQuery({ queryKey: ['favourites'], queryFn: api.favourites })
}

/**
 * Whether one entity is a favourite, and starring or unstarring it. Every list draws its stars
 * from the server, so a change refreshes whatever is on screen.
 */
export function useFavourite(entity: Pick<Entity, 'category' | 'kind' | 'id'>) {
  const queryClient = useQueryClient()
  const favourites = useFavourites()
  const inLibrary = useLibrary()
  const mine = findFavourite(favourites.data, entity)
  const toggle = useMutation({
    mutationFn: async () => {
      if (mine) {
        await api.removeFavourite(mine.id)
        return false
      }
      await api.addFavourite(entity.category, entity.kind, entity.id)
      return true
    },
    onSuccess: async (on) => {
      toast.success(on ? 'Added to favourites' : 'Removed from favourites')
      if (on || !mine) return
      // What it has coming that Radarr or Sonarr holds is asked about, never left without a word.
      const held =
        entity.category === 'screens'
          ? heldOf(
              inLibrary,
              (await api.favourite(entity.category, entity.kind, entity.id))
                .releases as ScreenTitle[],
            )
          : []
      // Then what Robin monitored from it, after, so one question is up at a time.
      if (mine.monitored) askStopFavourite({ id: mine.id, then: () => askArrRemove(held) })
      else askArrRemove(held)
    },
    onError: (error: unknown) =>
      toast.error('Could not change the favourite', { description: errorText(error) }),
    onSettled: () => void queryClient.invalidateQueries(),
  })
  return { favourite: mine, loaded: favourites.isSuccess, toggle }
}

/** Fired to ask whether to stop what Robin monitored from a favourite just removed. */
export const STOP_FAVOURITE = 'robin:stop-favourite'

export type StopAsk = { id: number; then: () => void }

/** Ask, through `FavouriteStopDialog`, whether to stop what Robin monitored from a favourite. */
export function askStopFavourite(ask: StopAsk) {
  window.dispatchEvent(new CustomEvent(STOP_FAVOURITE, { detail: ask }))
}

/** Every maker hidden, as a favourite is kept. */
/** Every maker always hidden or always shown. */
export function useMakerFilters() {
  return useQuery({ queryKey: ['maker-filters'], queryFn: api.makerFilters })
}

const FILTERED: Record<MakerMode, string> = { hide: 'Always hidden', show: 'Always shown' }

/**
 * Whether one entity is always hidden or always shown, and changing that: `set` puts it in a
 * mode, or takes it out of the one it is in. Hidden, it stops being a favourite.
 */
export function useMakerFilter(entity: Pick<Entity, 'category' | 'kind' | 'id'>) {
  const queryClient = useQueryClient()
  const filters = useMakerFilters()
  const mine = findFavourite(filters.data, entity) as MakerFilter | undefined
  const set = useMutation({
    mutationFn: async (mode: MakerMode) => {
      if (mine?.mode === mode) {
        await api.unfilterMaker(mine.id)
        return null
      }
      await api.filterMaker(mode, entity.category, entity.kind, entity.id)
      return mode
    },
    onSuccess: (mode) => toast.success(mode ? FILTERED[mode] : 'Back to your filters'),
    onError: (error: unknown) =>
      toast.error('Could not change it', { description: errorText(error) }),
    onSettled: () => void queryClient.invalidateQueries(),
  })
  return { mode: mine?.mode ?? null, loaded: filters.isSuccess, set }
}

/**
 * What a category's search found that releases come from, beside its titles, or of one `kind`,
 * which spares a source asked a call per kind.
 */
export function useFavouriteSearch(
  category: FavouriteCategory,
  term: string,
  kind: FavouriteKind | null = null,
) {
  return useQuery({
    queryKey: ['favourite-search', category, term, kind],
    queryFn: () => api.searchFavourites(category, term, false, kind),
    enabled: term.length > 0,
    retry: false,
  })
}
