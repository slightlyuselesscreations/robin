import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Spinner } from '@/components/ui/spinner'
import { LIBRARY_NAME } from '@/lib/api'
import { ARR_REMOVE, type Held, LIBRARY_CLASS, useArrRemove } from '@/lib/arr'
import { cn } from '@/lib/utils'

/**
 * Whether to remove titles from Radarr or Sonarr as well, asked by `askArrRemove` from anywhere,
 * a right click menu included, so it is mounted once beside the app. Files stay unless asked.
 */
export function ArrRemoveDialog() {
  const [titles, setTitles] = useState<Held[]>([])
  const [deleteFiles, setDeleteFiles] = useState(false)
  const remove = useArrRemove()

  useEffect(() => {
    const ask = (event: Event) => {
      setTitles((event as CustomEvent<Held[]>).detail)
      setDeleteFiles(false)
    }
    window.addEventListener(ARR_REMOVE, ask)
    return () => window.removeEventListener(ARR_REMOVE, ask)
  }, [])

  const apps = [...new Set(titles.map((t) => LIBRARY_NAME[t.library]))].join(' and ')
  const close = () => setTitles([])

  return (
    <Dialog open={titles.length > 0} onOpenChange={(open) => (open ? null : close())}>
      <DialogContent className="border-line bg-surface sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Also remove from {apps}?</DialogTitle>
        </DialogHeader>
        <ul className="max-h-60 space-y-1 overflow-y-auto text-sm">
          {titles.map((t) => (
            <li key={`${t.kind}-${t.id}`} className={cn('truncate', LIBRARY_CLASS[t.library])}>
              {t.title}
            </li>
          ))}
        </ul>
        <Label className="flex items-center gap-2 text-sm text-ink-dim">
          <Checkbox checked={deleteFiles} onCheckedChange={(on) => setDeleteFiles(on === true)} />
          Delete files too
        </Label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={close} disabled={remove.isPending}>
            Keep
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => remove.mutate({ titles, deleteFiles }, { onSettled: close })}
            className="gap-2"
          >
            {remove.isPending ? <Spinner className="size-4" /> : <Trash2 className="size-4" />}
            Remove
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
