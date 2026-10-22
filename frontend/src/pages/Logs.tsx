import { ArrowDownToLine, ScrollText, TriangleAlert } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import {
  Control,
  ControlGroup,
  Notice,
  Options,
  Page,
  PageHeader,
  Segmented,
} from '@/components/Page'
import { Card } from '@/components/ui/card'
import { type LogLine, api, errorText } from '@/lib/api'
import { usePageControls } from '@/lib/controls'
import { cn, controlClass } from '@/lib/utils'

/** As many lines as the server keeps. */
const KEEP = 5000
const POLL = 2000
/** How close to the bottom still counts as following. */
const NEAR = 40

const TONE: Record<string, string> = {
  critical: 'text-bad',
  error: 'text-bad',
  warning: 'text-wait',
}

/** A logger's name as the page names it: httpx logs every request Robin sends out. */
const sourceName = (source: string) =>
  source === 'httpx' ? 'requests' : source.replace(/^robin\.(routes\.)?/, '')

/**
 * What Robin logged since it started, newest at the bottom, asked for every two seconds from
 * the last line held. Following keeps the bottom in view, and scrolling up stops it.
 */
export function Logs() {
  const controls = usePageControls('logs', { level: 'all', source: 'all' })
  const [lines, setLines] = useState<LogLine[]>([])
  const [error, setError] = useState<unknown>(null)
  const [follow, setFollow] = useState(true)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let last = 0
    let stopped = false
    const poll = async () => {
      if (document.hidden) return
      try {
        const fresh = await api.logs(last)
        setError(null)
        if (stopped || !fresh.length) return
        last = fresh[fresh.length - 1].id
        setLines((held) => [...held, ...fresh].slice(-KEEP))
      } catch (err) {
        setError(err)
      }
    }
    void poll()
    const timer = setInterval(() => void poll(), POLL)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [])

  const sources = [...new Set(lines.map((l) => sourceName(l.source)))].sort()
  const { level, source } = controls.values
  const shown = lines.filter(
    (l) =>
      (level === 'all' || l.level in TONE) && (source === 'all' || sourceName(l.source) === source),
  )

  useLayoutEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [follow, shown.length])

  const onScroll = () => {
    const el = box.current
    if (el) setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < NEAR)
  }

  return (
    <Page>
      <PageHeader title="Logs" icon={ScrollText}>
        <ControlGroup>
          <button
            type="button"
            aria-pressed={follow}
            onClick={() => setFollow(!follow)}
            className={controlClass(follow)}
          >
            <ArrowDownToLine className="size-3.5" />
            <span className="hidden sm:inline">Follow</span>
          </button>
          <button
            type="button"
            aria-pressed={level !== 'all'}
            onClick={() => controls.set({ level: level === 'all' ? 'errors' : 'all' })}
            className={controlClass(level !== 'all')}
          >
            <TriangleAlert className="size-3.5" />
            <span className="hidden sm:inline">Errors</span>
          </button>
        </ControlGroup>
        <Options controls={controls}>
          <Control label="Source">
            <Segmented
              label="Source"
              value={source}
              onChange={(next) => controls.set({ source: next })}
              options={[
                { value: 'all', label: 'All' },
                ...sources.map((s) => ({ value: s, label: s })),
              ]}
            />
          </Control>
        </Options>
      </PageHeader>

      {error && !lines.length ? (
        <Notice tone="bad">{errorText(error, 'Could not read logs')}</Notice>
      ) : (
        <Card className="gap-0 bg-surface py-0">
          <div
            ref={box}
            onScroll={onScroll}
            className="h-[calc(100dvh-12rem)] min-h-64 overflow-y-auto py-2 font-mono text-xs"
          >
            {shown.map((line) => (
              <div
                key={line.id}
                className="flex flex-wrap gap-x-3 px-4 py-0.5 hover:bg-raised/50 sm:flex-nowrap"
              >
                <span className="shrink-0 text-ink-faint tabular-nums">
                  {new Date(line.at).toLocaleTimeString()}
                </span>
                <span
                  className={cn('w-14 shrink-0 uppercase', TONE[line.level] ?? 'text-ink-faint')}
                >
                  {line.level}
                </span>
                <span className="w-20 shrink-0 truncate text-ink-dim">
                  {sourceName(line.source)}
                </span>
                <span className="min-w-0 basis-full break-words whitespace-pre-wrap text-ink sm:basis-auto">
                  {line.message}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </Page>
  )
}
