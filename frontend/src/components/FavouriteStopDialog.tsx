import { useMutation, useQueryClient } from '@tanstack/react-query'
import { EyeOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { api, errorText } from '@/lib/api'
import { STOP_FAVOURITE, type StopAsk } from '@/lib/favourites'

/**
 * Whether to stop what Robin monitored from a favourite just removed, asked by
 * `askStopFavourite` from anywhere, so it is mounted once beside the app. What you monitored
 * yourself is never touched.
 */
export function FavouriteStopDialog() {
  const queryClient = useQueryClient()
  const [ask, setAsk] = useState<StopAsk | null>(null)

  useEffect(() => {
    const listen = (event: Event) => setAsk((event as CustomEvent<StopAsk>).detail)
    window.addEventListener(STOP_FAVOURITE, listen)
    return () => window.removeEventListener(STOP_FAVOURITE, listen)
  }, [])

  const close = () => {
    ask?.then()
    setAsk(null)
  }
  const stop = useMutation({
    mutationFn: (id: number) => api.stopFavourite(id),
    onSuccess: ({ stopped }) => toast.success(`Stopped ${stopped}`),
    onError: (error: unknown) =>
      toast.error('Could not stop them', { description: errorText(error) }),
    onSettled: () => {
      void queryClient.invalidateQueries()
      close()
    },
  })

  return (
    <Dialog open={ask !== null} onOpenChange={(open) => (open ? null : close())}>
      <DialogContent className="border-line bg-surface sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            Do you also want to stop monitoring this favourite's past items?
          </DialogTitle>
        </DialogHeader>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={close} disabled={stop.isPending}>
            Keep
          </Button>
          <Button
            variant="destructive"
            disabled={stop.isPending}
            onClick={() => ask && stop.mutate(ask.id)}
            className="gap-2"
          >
            {stop.isPending ? <Spinner className="size-4" /> : <EyeOff className="size-4" />}
            Stop monitoring
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
