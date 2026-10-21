import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Clip, Notice } from '@/components/Page'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { type Release, api, errorText, leech, releaseAge, releaseSize } from '@/lib/api'
import { cn, controlClass } from '@/lib/utils'

/**
 * A game searched for on the chosen indexers, stacked over the game dialog so it scrolls on
 * its own. Each release can be grabbed, which monitors the game when it is not.
 */
export function IndexerSearch({
  igdbId,
  gameName,
  open,
  onClose,
}: {
  igdbId: number
  gameName: string
  open: boolean
  onClose: () => void
}) {
  const search = useQuery({
    queryKey: ['indexer-search', igdbId],
    queryFn: () => api.searchIndexers(igdbId),
    enabled: open,
    // Every call fans out to every indexer, so it is not repeated on a whim.
    staleTime: 5 * 60_000,
    retry: false,
  })

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent className="flex max-h-[88dvh] w-[94vw] flex-col gap-0 overflow-hidden border-line bg-surface p-0 sm:max-w-5xl">
        <div className="flex shrink-0 items-baseline gap-3 border-b border-line px-5 py-4">
          <DialogTitle className="text-base font-semibold text-ink">{gameName}</DialogTitle>
          {search.data ? (
            <span className="text-2xs text-ink-faint">
              {search.data.releases.length} for {search.data.term}
            </span>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {search.isPending ? (
            <p className="flex items-center justify-center gap-2 px-5 py-16 text-sm text-ink-dim">
              <Spinner className="size-4" />
              Asking every indexer
            </p>
          ) : search.isError ? (
            <div className="p-5">
              <Notice tone="bad">{errorText(search.error, 'Search failed')}</Notice>
            </div>
          ) : search.data.releases.length === 0 ? (
            <div className="p-5">
              <Notice>Nothing on your indexers yet.</Notice>
            </div>
          ) : (
            <ReleaseTable igdbId={igdbId} releases={search.data.releases} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ReleaseTable({ igdbId, releases }: { igdbId: number; releases: Release[] }) {
  return (
    <table className="w-full border-collapse text-2xs">
      <thead className="sticky top-0 bg-surface text-ink-faint">
        <tr className="border-b border-line text-left">
          <th className="w-full px-5 py-2 font-medium">Release</th>
          <th className="px-2 py-2 font-medium">Indexer</th>
          <th className="px-2 py-2 text-right font-medium">Size</th>
          <th className="px-2 py-2 text-right font-medium">Age</th>
          <th className="px-2 py-2 text-right font-medium">S / L</th>
          <th className="px-5 py-2" />
        </tr>
      </thead>
      <tbody>
        {releases.map((release) => {
          const flag = leech(release.flags)
          return (
            <tr
              key={`${release.indexer_id}:${release.guid}`}
              className="border-b border-line/60 hover:bg-raised"
            >
              <td className="w-full max-w-0 px-5 py-2">
                <div className="flex items-center gap-2">
                  <Clip className="font-mono text-ink">{release.title}</Clip>
                  {flag ? (
                    <span
                      className={cn(
                        'shrink-0 rounded-sm px-1.5 py-0.5 text-2xs font-medium',
                        flag.className,
                      )}
                    >
                      {flag.label}
                    </span>
                  ) : null}
                </div>
              </td>
              <td className="px-2 py-2 whitespace-nowrap text-ink-dim">
                {release.info_url ? (
                  <a
                    href={release.info_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 hover:text-accent"
                  >
                    {release.indexer}
                    <ExternalLink className="size-3" />
                  </a>
                ) : (
                  release.indexer
                )}
              </td>
              <td className="px-2 py-2 text-right whitespace-nowrap text-ink-dim">
                {releaseSize(release.size)}
              </td>
              <td className="px-2 py-2 text-right whitespace-nowrap text-ink-faint">
                {releaseAge(release.age)}
              </td>
              <td className="px-2 py-2 text-right whitespace-nowrap">
                <span className={release.seeders > 0 ? 'text-good' : 'text-bad'}>
                  {release.seeders}
                </span>
                <span className="text-ink-faint"> / {release.leechers}</span>
              </td>
              <td className="px-5 py-2 text-right">
                <GrabButton igdbId={igdbId} release={release} />
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Grabs one release, once, as a monitored game's grab is sent. */
function GrabButton({ igdbId, release }: { igdbId: number; release: Release }) {
  const queryClient = useQueryClient()
  const [sent, setSent] = useState(false)
  const grab = useMutation({
    mutationFn: () => api.grab(igdbId, release.guid),
    onSuccess: () => {
      setSent(true)
      toast.success('Grabbed', { description: release.title })
      void queryClient.invalidateQueries({ queryKey: ['monitored'] })
    },
    onError: (error: unknown) => toast.error(errorText(error, 'Could not grab that release')),
  })
  return (
    <button
      type="button"
      onClick={() => grab.mutate()}
      disabled={grab.isPending || sent}
      className={cn(controlClass(), 'h-6 px-2 text-2xs')}
    >
      {grab.isPending ? <Spinner className="size-3" /> : <Download className="size-3" />}
      {sent ? 'Sent' : 'Grab'}
    </button>
  )
}
