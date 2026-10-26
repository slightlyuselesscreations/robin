import { useQuery } from '@tanstack/react-query'
import { BookOpen, Clapperboard, Gamepad2, LibraryBig, type LucideIcon } from 'lucide-react'

import { type Category, type Settings, api } from '@/lib/api'

export type CategoryInfo = {
  key: Category
  label: string
  icon: LucideIcon
  /** Its page, and the prefix of every page under it. */
  to: string
  /** Its tab in Settings, where its source is set. */
  settings: string
  /** Whether its data source is set. A category is shown nowhere until it is. */
  ready: (settings: Settings) => boolean
  /** What its pages say while it is not, through `say`. */
  off: string
}

/** Every category, in the order the menu and every overview show them. */
export const CATEGORIES: CategoryInfo[] = [
  {
    key: 'games',
    label: 'Games',
    icon: Gamepad2,
    to: '/games',
    settings: '/settings/games',
    ready: (s) => s.igdb_ready,
    off: 'Games needs IGDB. Add a Twitch client id and secret in {settings-games}.',
  },
  {
    key: 'comics',
    label: 'Comics',
    icon: BookOpen,
    to: '/comics',
    settings: '/settings/comics',
    ready: (s) => s.comics_ready,
    off: 'Comics needs a Metron API key. Add it in {settings-comics}.',
  },
  {
    key: 'screens',
    label: 'Screens',
    icon: Clapperboard,
    to: '/screens',
    settings: '/settings/screens',
    ready: (s) => s.tmdb_ready,
    off: 'Screens needs a TMDB key. Add it in {settings-screens}.',
  },
  {
    key: 'books',
    label: 'Books',
    icon: LibraryBig,
    to: '/books',
    settings: '/settings/books',
    ready: (s) => s.hardcover_ready,
    off: 'Books needs a Hardcover API key. Add it in {settings-books}.',
  },
]

export const CATEGORY: Record<Category, CategoryInfo> = Object.fromEntries(
  CATEGORIES.map((c) => [c.key, c]),
) as Record<Category, CategoryInfo>

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: api.settings })
}

/** Whether a category is shown. None is until the settings have loaded. */
export function useShown(): (category: Category) => boolean {
  const settings = useSettings().data
  return (category) => (settings ? CATEGORY[category].ready(settings) : false)
}

/** What a search can be narrowed to: every category shown, Comics once Suwayomi is set, since
 * it searches that source. */
export function useSearchable(): Category[] {
  const settings = useSettings().data
  return CATEGORIES.filter(
    (c) => settings && c.ready(settings) && (c.key !== 'comics' || settings.suwayomi_ready),
  ).map((c) => c.key)
}
