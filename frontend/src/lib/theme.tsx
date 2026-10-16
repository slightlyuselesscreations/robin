import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Monitor, Moon, Sun } from 'lucide-react'
import { useEffect } from 'react'
import { toast } from 'sonner'

import { type Option } from '@/components/Page'
import { api, type Scheme, type Settings, type Theme } from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { cn } from '@/lib/utils'

/** The logo drawn as a theme's species. Anything else, a value kept from before, is European. */
export const logo = (theme: string | undefined) =>
  `/robin-${THEMES.some((t) => t.value === theme) ? theme : 'european'}.svg`

// Larger than the icon a control gives it, so the bird can be seen before it is picked.
const species = (theme: Theme) =>
  function Species({ className }: { className?: string }) {
    return <img src={logo(theme)} alt="" className={cn(className, 'size-5')} />
  }

export const THEMES: Option<Theme>[] = [
  { value: 'european', label: 'European robin', icon: species('european') },
  { value: 'american', label: 'American robin', icon: species('american') },
  { value: 'pink', label: 'Pink robin', icon: species('pink') },
  { value: 'siberian', label: 'Siberian blue robin', icon: species('siberian') },
  { value: 'rufous', label: 'Rufous-backed robin', icon: species('rufous') },
  { value: 'flame', label: 'Flame robin', icon: species('flame') },
  { value: 'red-capped', label: 'Red-capped robin', icon: species('red-capped') },
  { value: 'white-throated', label: 'White-throated robin', icon: species('white-throated') },
  { value: 'black', label: 'Black robin', icon: species('black') },
]

export const SCHEMES: Option<Scheme>[] = [
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'system', label: 'System', icon: Monitor },
]

// Read by the script in index.html before the first paint, and on the sign in screen.
const KEPT = 'robin-theme'

/**
 * The theme as saved, applied to <html> and kept in this browser for its next first paint.
 * Until the settings arrive it is what <html> already carries. A change applies at once and is
 * saved behind it.
 */
export function useTheme() {
  const client = useQueryClient()
  const settings = useSettings().data
  const root = document.documentElement
  const theme = settings?.theme ?? (root.dataset.theme as Theme)
  const scheme = settings?.scheme ?? (root.dataset.scheme as Scheme)

  useEffect(() => {
    Object.assign(document.documentElement.dataset, { theme, scheme })
    document.querySelector<HTMLLinkElement>('link[rel=icon]')?.setAttribute('href', logo(theme))
    try {
      localStorage.setItem(KEPT, JSON.stringify({ theme, scheme }))
    } catch {
      // Storage refused: the next load paints the default until the settings arrive.
    }
  }, [theme, scheme])

  const save = useMutation({
    mutationFn: (patch: Pick<Partial<Settings>, 'theme' | 'scheme'>) => api.saveSettings(patch),
    onError: () => {
      toast.error('Could not save the theme')
      void client.invalidateQueries({ queryKey: ['settings'] })
    },
  })
  const set = (patch: Pick<Partial<Settings>, 'theme' | 'scheme'>) => {
    client.setQueryData(['settings'], (old: Settings | undefined) =>
      old ? { ...old, ...patch } : old,
    )
    save.mutate(patch)
  }

  return { theme, scheme, set }
}
