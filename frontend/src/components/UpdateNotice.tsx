import { useQuery } from '@tanstack/react-query'
import { ArrowUpCircle, ExternalLink } from 'lucide-react'
import { useState } from 'react'

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { api } from '@/lib/api'
import { cn, controlClass } from '@/lib/utils'

/** The update command on the Docker host, which only pulls. */
const UPDATE = 'docker compose pull && docker compose up -d'

/**
 * Beside the version in the sidebar while GitHub has a newer Robin, opening its release
 * notes and how to update.
 */
export function UpdateNotice() {
  const [open, setOpen] = useState(false)
  const { data: found } = useQuery({
    queryKey: ['update'],
    queryFn: api.update,
    staleTime: 60 * 60_000,
    retry: false,
  })
  if (!found) return null
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 font-mono text-2xs text-accent hover:underline"
      >
        <ArrowUpCircle className="size-3" />v{found.version}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[80dvh] flex-col gap-4 border-line bg-surface sm:max-w-lg">
          <div className="flex items-baseline gap-2">
            <DialogTitle className="text-base font-semibold text-ink">
              Robin {found.version}
            </DialogTitle>
            <span className="text-2xs text-ink-faint">
              {new Date(found.published).toLocaleDateString()}
            </span>
          </div>

          {found.notes ? (
            <div className="min-h-0 overflow-y-auto">
              <Markdown text={found.notes} />
            </div>
          ) : null}

          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-ink">Update on the Docker host</span>
            <code className="rounded-md border border-line bg-base px-3 py-2 font-mono text-xs text-ink">
              {UPDATE}
            </code>
          </div>

          <a
            href={found.url}
            target="_blank"
            rel="noreferrer"
            className={cn(controlClass(), 'self-start')}
          >
            <ExternalLink className="size-3.5" />
            GitHub
          </a>
        </DialogContent>
      </Dialog>
    </>
  )
}

const CODE = 'rounded-sm bg-base px-1 font-mono text-xs text-ink'

/**
 * Release notes as GitHub writes them: headings, lists, paragraphs and fenced code, with inline
 * code, bold and links. Built as elements, never as HTML, so nothing in the notes runs. Anything
 * else reads as its plain text.
 */
function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const code: string[] = []
      while (++i < lines.length && !lines[i].startsWith('```')) code.push(lines[i])
      blocks.push(
        <pre key={i} className="overflow-x-auto rounded-md border border-line bg-base px-3 py-2">
          <code className="font-mono text-xs text-ink">{code.join('\n')}</code>
        </pre>,
      )
    } else if (/^#{1,6} /.test(line)) {
      blocks.push(
        <h3 key={i} className="pt-2 text-xs font-semibold tracking-wider text-ink uppercase">
          {inline(line.replace(/^#+ /, ''))}
        </h3>,
      )
    } else if (/^[-*] /.test(line)) {
      const items: string[] = []
      for (; i < lines.length && /^[-*] /.test(lines[i]); i++) items.push(lines[i].slice(2))
      i--
      blocks.push(
        <ul key={i} className="flex list-disc flex-col gap-1 pl-5">
          {items.map((item, n) => (
            <li key={n}>{inline(item)}</li>
          ))}
        </ul>,
      )
    } else if (line.trim()) {
      blocks.push(<p key={i}>{inline(line)}</p>)
    }
  }
  return <div className="flex flex-col gap-2 text-sm text-ink-dim">{blocks}</div>
}

/** Inline code, bold and http links in one line, the rest as text. */
function inline(text: string): React.ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/).map((part, n) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 1)
      return (
        <code key={n} className={CODE}>
          {part.slice(1, -1)}
        </code>
      )
    if (part.startsWith('**') && part.endsWith('**') && part.length > 3)
      return (
        <strong key={n} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      )
    const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part)
    if (link)
      return (
        <a
          key={n}
          href={link[2]}
          target="_blank"
          rel="noreferrer"
          className="text-accent hover:underline"
        >
          {link[1]}
        </a>
      )
    return part
  })
}
