import { useEffect } from 'react'

/** Within this many pixels of the end, the next page is asked for. */
const AHEAD = 600

/**
 * Asks for an infinite query's next page before the reader reaches the end of the last, so
 * scrolling stays continuous. A page filtered down short asks at once, since it would never
 * scroll at all.
 */
export function useScrollPaging(query: {
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => unknown
}) {
  const fetchNext = query.fetchNextPage
  const canFetch = query.hasNextPage && !query.isFetchingNextPage
  useEffect(() => {
    if (!canFetch) return
    const check = () => {
      const doc = document.documentElement
      if (doc.scrollHeight - window.scrollY - window.innerHeight < AHEAD) void fetchNext()
    }
    check()
    window.addEventListener('scroll', check, { passive: true })
    window.addEventListener('resize', check)
    return () => {
      window.removeEventListener('scroll', check)
      window.removeEventListener('resize', check)
    }
  }, [canFetch, fetchNext])
}
