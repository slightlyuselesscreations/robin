import { Search, X } from 'lucide-react'
import { useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { CATEGORY, useSearchable } from '@/lib/categories'
import { type SearchScope, useSearchScopes } from '@/lib/favourites'

/**
 * Searches a category's titles, or one kind of what they come from, on `/search?q=&type=`.
 * Shown while any category can be searched.
 */
export function SearchBar() {
  return useSearchable().length ? <ScopedSearch /> : null
}

function ScopedSearch() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const searchable = useSearchable()
  const scopes = useSearchScopes()
  const onResults = pathname === '/search'
  const fromUrl = onResults ? (params.get('q') ?? '') : ''
  const typeFromUrl = onResults ? params.get('type') : null

  const [term, setTerm] = useState(fromUrl)
  const [lastFromUrl, setLastFromUrl] = useState(fromUrl)
  const [picked, setPicked] = useState<string | null>(typeFromUrl)
  const [lastType, setLastType] = useState(typeFromUrl)
  const [picking, setPicking] = useState(false)

  // Keep the field and the scope in step with the URL, including back and forward navigation.
  if (fromUrl !== lastFromUrl) {
    setLastFromUrl(fromUrl)
    setTerm(fromUrl)
  }
  if (typeFromUrl !== lastType) {
    setLastType(typeFromUrl)
    if (typeFromUrl) setPicked(typeFromUrl)
  }

  // A pick holds until another is made. Before one, a category's own page scopes the bar to
  // its titles.
  const onPage = searchable.find((c) => pathname.startsWith(CATEGORY[c].to))
  const scope: SearchScope | undefined =
    scopes.find((s) => s.value === picked) ?? scopes.find((s) => s.value === onPage)
  const label = scope ? `Search ${scope.label}` : 'Pick a category to search from'

  return (
    <form
      role="search"
      className="ml-auto flex w-full max-w-md items-center rounded-md shadow-raised"
      onSubmit={(event) => {
        event.preventDefault()
        const trimmed = term.trim()
        if (!trimmed) return
        // Nothing is searched until it is narrowed to a category.
        if (!scope) {
          setPicking(true)
          return
        }
        navigate(`/search?${new URLSearchParams({ q: trimmed, type: scope.value })}`)
      }}
    >
      <Select
        value={scope?.value ?? ''}
        open={picking}
        onOpenChange={setPicking}
        onValueChange={(next) => {
          setPicked(next)
          // On the results page a new scope searches the same term at once.
          if (onResults && term.trim()) {
            navigate(`/search?${new URLSearchParams({ q: term.trim(), type: next })}`)
          }
        }}
      >
        <SelectTrigger
          aria-label="Category"
          className="h-9 shrink-0 rounded-r-none border-line border-r-0 bg-surface text-sm text-ink shadow-none"
        >
          <SelectValue placeholder="Category" />
        </SelectTrigger>
        {/* Dropped below the button, so it neither jumps to the picked item nor scrolls to it. */}
        <SelectContent position="popper" align="start">
          {searchable.map((category) => (
            <SelectGroup key={category}>
              <SelectLabel>{CATEGORY[category].label}</SelectLabel>
              {scopes
                .filter((s) => s.category === category)
                .map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    <s.icon />
                    {s.label}
                  </SelectItem>
                ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>

      <div className="relative flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-faint" />
        <Input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder={label}
          aria-label={label}
          className="h-9 rounded-l-none border-line bg-surface pr-9 pl-9 text-sm shadow-none placeholder:text-ink-faint"
        />
        {term ? (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => {
              setTerm('')
              // Back to the page the search started from, or Home when it was opened directly.
              if (onResults) {
                const opened = (window.history.state as { idx?: number } | null)?.idx ?? 0
                if (opened > 0) navigate(-1)
                else navigate('/')
              }
            }}
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm p-1 text-ink-faint hover:text-ink"
          >
            <X className="size-3.5" />
          </button>
        ) : null}
      </div>
    </form>
  )
}
