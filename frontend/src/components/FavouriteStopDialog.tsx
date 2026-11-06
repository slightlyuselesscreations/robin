import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { StarOff, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Spinner } from '@/components/ui/spinner'
import { LIBRARY_NAME, api, errorText } from '@/lib/api'
import { STOP_FAVOURITE, type StopAsk } from '@/lib/favourites'

const HOLD_FILES: string[] = Object.values(LIBRARY_NAME)

/**
 * Unstarring, asked every time before anything goes, from anywhere, so it is mounted once beside
 * the app: everything the favourite put in Robin and in each integration goes with it, or stays.
 * What you monitored yourself is never listed.
 */
export function FavouriteStopDialog() {
  const queryClient = useQueryClient()
  const [ask, setAsk] = useState<StopAsk | null>(null)
  const [deleteFiles, setDeleteFiles] = useState(false)

  useEffect(() => {
    const listen = (event: Event) => {
      setAsk((event as CustomEvent<StopAsk>).detail)
      setDeleteFiles(false)
    }
    window.addEventListener(STOP_FAVOURITE, listen)
    return () => window.removeEventListener(STOP_FAVOURITE, listen)
  }, [])

  const reach = useQuery({
    queryKey: ['favourite-reach', ask?.id],
    queryFn: () => api.favouriteReach(ask!.id),
    enabled: ask !== null,
    gcTime: 0,
  })
  const titles = reach.data?.titles ?? []
  const unread = reach.data?.unread ?? []
  const holdsFiles = titles.some((t) => t.places.some((p) => HOLD_FILES.includes(p)))

  const remove = useMutation({
    mutationFn: async ({ id, everything }: { id: number; everything: boolean }) => {
      const done = everything ? await api.stopFavourite(id, deleteFiles) : null
      await api.removeFavourite(id)
      return done
    },
    onSuccess: (done) => {
      if (done?.failed) toast.error(`Could not remove ${done.failed}`)
      else toast.success('Removed from favourites')
      ask?.then?.()
    },
    onError: (error: unknown) =>
      toast.error('Could not change the favourite', { description: errorText(error) }),
    onSettled: () => {
      void queryClient.invalidateQueries()
      setAsk(null)
    },
  })

  return (
    <Dialog
      open={ask !== null}
      onOpenChange={(open) => (open || remove.isPending ? null : setAsk(null))}
    >
      <DialogContent className="border-line bg-surface sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Remove {ask?.name} from favourites?</DialogTitle>
        </DialogHeader>
        {reach.isPending ? (
          <Spinner className="size-5 text-ink-dim" />
        ) : titles.length ? (
          <ul className="max-h-60 space-y-1 overflow-y-auto text-sm">
            {titles.map((t) => (
              <li key={`${t.category}-${t.key}`} className="flex justify-between gap-3">
                <span className="truncate text-ink">{t.title}</span>
                <span className="shrink-0 text-xs text-ink-faint">{t.places.join(', ')}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {unread.length ? (
          <p className="text-xs text-bad">Could not read {unread.join(' and ')}</p>
        ) : null}
        {holdsFiles ? (
          <Label className="flex items-center gap-2 text-sm text-ink-dim">
            <Checkbox checked={deleteFiles} onCheckedChange={(on) => setDeleteFiles(on === true)} />
            Delete files too
          </Label>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setAsk(null)} disabled={remove.isPending}>
            Cancel
          </Button>
          {titles.length ? (
            <Button
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => ask && remove.mutate({ id: ask.id, everything: false })}
              className="gap-2"
            >
              <StarOff className="size-4" />
              Favourite only
            </Button>
          ) : null}
          <Button
            variant="destructive"
            disabled={remove.isPending || reach.isPending}
            onClick={() => ask && remove.mutate({ id: ask.id, everything: titles.length > 0 })}
            className="gap-2"
          >
            {remove.isPending ? <Spinner className="size-4" /> : <Trash2 className="size-4" />}
            {titles.length ? 'Remove everything' : 'Remove'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
