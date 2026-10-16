import { Link } from 'react-router-dom'

import { CATEGORIES } from '@/lib/categories'

type Place = { label: string; to: string }

/**
 * Every place in Robin a hint can send the user to, by the name `say` reads between braces.
 * A service, a source or a field is not a place, and stays plain text.
 */
const PLACES: Record<string, Place | undefined> = {
  settings: { label: 'Settings', to: '/settings' },
  general: { label: 'General', to: '/settings' },
  monitored: { label: 'Monitored', to: '/monitored' },
  favourites: { label: 'Favourites', to: '/favourites' },
  ...Object.fromEntries(
    CATEGORIES.map((c) => [`settings-${c.key}`, { label: `${c.label} settings`, to: c.settings }]),
  ),
}

/**
 * Helper text, with each `{place}` it names in accent capitals and linking there:
 * `say('Add a destination under {general} first')`. Every hint, note, tooltip and notice that sends the
 * user somewhere in Robin goes through it. A name `PLACES` does not hold stays as written.
 */
export function say(text: string): React.ReactNode {
  return text.split(/(\{[a-z-]+\})/).map((part, i) => {
    const place = part.startsWith('{') ? PLACES[part.slice(1, -1)] : undefined
    if (!place) return part
    return (
      <Link
        key={i}
        to={place.to}
        className="font-medium tracking-wide text-accent uppercase hover:text-accent-hi"
      >
        {place.label}
      </Link>
    )
  })
}
