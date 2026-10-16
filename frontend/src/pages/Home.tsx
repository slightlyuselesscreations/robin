import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  CalendarDays,
  CircleCheck,
  Columns2,
  Download,
  EyeOff,
  GripVertical,
  Hourglass,
  House,
  LayoutDashboard,
  type LucideIcon,
  Plus,
  Radio,
  RectangleHorizontal,
  RotateCcw,
  Timer,
} from 'lucide-react'
import { Fragment, useEffect, useState, useSyncExternalStore } from 'react'
import type { Layout } from 'react-resizable-panels'
import { toast } from 'sonner'

import {
  CalendarPanel,
  CountdownsPanel,
  DownloadsPanel,
  FoundPanel,
  HealthPanel,
  HealthRefresh,
  NextUpPanel,
  StatusPanel,
} from '@/components/HomePanels'
import { ControlGroup, Page, PageHeader, Section, Tip } from '@/components/Page'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { type HomePanel, type Settings, api } from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { riseAt } from '@/lib/motion'
import { cn, controlClass } from '@/lib/utils'

/**
 * Every panel Home can show, in the default order. A new panel is an entry here. `beside`
 * puts it in the row of the panel before it by default. `needs` names the integration a panel
 * shows, and the panel is left out entirely while that integration is unset.
 */
const PANELS: {
  id: string
  title: string
  icon: LucideIcon
  beside?: boolean
  needs?: (settings: Settings) => boolean
  body: React.ComponentType
  action?: React.ComponentType
}[] = [
  { id: 'status', title: 'Status this month', icon: LayoutDashboard, body: StatusPanel },
  { id: 'next', title: 'Next up', icon: Timer, body: NextUpPanel },
  { id: 'countdowns', title: 'Countdowns', icon: Hourglass, beside: true, body: CountdownsPanel },
  { id: 'found', title: 'Recently notified', icon: CircleCheck, beside: true, body: FoundPanel },
  { id: 'calendar', title: 'Calendar', icon: CalendarDays, body: CalendarPanel },
  {
    id: 'health',
    title: 'Health',
    icon: Radio,
    beside: true,
    body: HealthPanel,
    action: HealthRefresh,
  },
  {
    id: 'downloads',
    title: 'Downloads',
    icon: Download,
    needs: (s) => s.qbittorrent_ready,
    body: DownloadsPanel,
  },
]

const fresh = (p: (typeof PANELS)[number]): HomePanel => ({
  id: p.id,
  hidden: false,
  beside: p.beside ?? false,
  size: null,
})

const DEFAULT_LAYOUT: HomePanel[] = PANELS.map(fresh)

/**
 * The saved layout made whole: panels it does not know are dropped, panels added since it was
 * saved are appended, shown, and a panel saved before rows existed takes its default row.
 */
function resolve(saved: HomePanel[] | undefined): HomePanel[] {
  const known = (saved ?? [])
    .filter((s) => PANELS.some((p) => p.id === s.id))
    .map((s) => ({ ...s, beside: s.beside ?? PANELS.find((p) => p.id === s.id)!.beside ?? false }))
  const missing = PANELS.filter((p) => !known.some((s) => s.id === p.id)).map(fresh)
  return known.length ? [...known, ...missing] : DEFAULT_LAYOUT
}

/** Panels in rows: each starts one unless it sits beside the panel before. */
function rowsOf(panels: HomePanel[]): HomePanel[][] {
  const rows: HomePanel[][] = []
  for (const panel of panels) {
    if (panel.beside && rows.length) rows.at(-1)!.push(panel)
    else rows.push([panel])
  }
  return rows
}

/** A row's saved split, only when every panel in it has a size and they fill the row. */
function savedSplit(row: HomePanel[]): Layout | undefined {
  const total = row.reduce((sum, p) => sum + (p.size ?? 0), 0)
  if (row.some((p) => !p.size) || Math.abs(total - 100) > 1) return undefined
  return Object.fromEntries(row.map((p) => [p.id, p.size!]))
}

// Rows split across the page from Tailwind's lg breakpoint. Narrower, every panel stacks.
const WIDE = '(min-width: 64rem)'

function useWide(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia(WIDE)
      query.addEventListener('change', notify)
      return () => query.removeEventListener('change', notify)
    },
    () => window.matchMedia(WIDE).matches,
  )
}

// Home rises in on its first visit of the session only, never again on a revisit or a Reload.
let risen = false

export function Home() {
  const queryClient = useQueryClient()
  const settings = useSettings()
  const [rising] = useState(() => !risen)
  useEffect(() => {
    risen = true
  }, [])
  const [editing, setEditing] = useState(false)
  const [dragging, setDragging] = useState<string | null>(null)
  const wide = useWide()
  const layout = resolve(settings.data?.home_layout)

  // Applied at once and saved behind it, so moving a panel never waits on a round trip.
  const save = useMutation({
    mutationFn: (next: HomePanel[]) => api.saveSettings({ home_layout: next }),
    onError: () => toast.error('Could not save the layout'),
  })
  const apply = (next: HomePanel[]) => {
    queryClient.setQueryData(['settings'], (old: Settings | undefined) =>
      old ? { ...old, home_layout: next } : old,
    )
    save.mutate(next)
  }

  const move = (id: string, to: number) => {
    const from = layout.findIndex((p) => p.id === id)
    if (from < 0 || to < 0 || to >= layout.length || from === to) return
    const next = [...layout]
    const [panel] = next.splice(from, 1)
    next.splice(to, 0, panel)
    apply(next)
  }
  const update = (id: string, change: Partial<HomePanel>) =>
    apply(layout.map((p) => (p.id === id ? { ...p, ...change } : p)))
  // Without a size the rows it leaves and joins no longer add up, so both start again from
  // equal widths. Every other row keeps its split.
  const setBeside = (id: string, beside: boolean) => update(id, { beside, size: null })
  const resize = (split: Layout) =>
    apply(
      layout.map((p) =>
        split[p.id] === undefined ? p : { ...p, size: Math.round(split[p.id] * 10) / 10 },
      ),
    )

  // A panel whose integration is unset is neither shown nor offered back.
  const available = layout.filter((p) => {
    const needs = PANELS.find((panel) => panel.id === p.id)?.needs
    return !needs || (settings.data ? needs(settings.data) : false)
  })
  const hidden = available.filter((p) => p.hidden)
  const shown = available.filter((p) => !p.hidden)

  const tile = (entry: HomePanel) => {
    const { id } = entry
    const index = shown.findIndex((p) => p.id === id)
    const panel = PANELS.find((p) => p.id === id)!
    const Body = panel.body
    const Action = panel.action
    // Moves step over hidden panels, so one click always moves a visible place.
    const neighbour = (step: number) => layout.findIndex((p) => p.id === shown[index + step].id)
    return (
      <div
        style={rising ? riseAt(index, 70) : undefined}
        className={cn(
          'flex flex-1 flex-col [&>[data-slot=card]]:flex-1',
          rising && 'rise',
          editing &&
            'cursor-grab rounded-card outline-1 outline-offset-4 outline-line-strong outline-dashed',
          dragging === id && 'opacity-40',
        )}
        draggable={editing}
        onDragStart={(e) => {
          setDragging(id)
          e.dataTransfer.effectAllowed = 'move'
        }}
        onDragEnd={() => setDragging(null)}
        onDragOver={(e) => {
          if (dragging && dragging !== id) e.preventDefault()
        }}
        onDrop={(e) => {
          e.preventDefault()
          if (dragging)
            move(
              dragging,
              layout.findIndex((p) => p.id === id),
            )
          setDragging(null)
        }}
      >
        <Section
          title={panel.title}
          icon={editing ? GripVertical : panel.icon}
          action={
            editing ? (
              <div className="flex items-center gap-1">
                <IconButton
                  label={entry.beside ? 'Start a row of its own' : 'Share the row before'}
                  icon={entry.beside ? RectangleHorizontal : Columns2}
                  disabled={index === 0}
                  onClick={() => setBeside(id, !entry.beside)}
                />
                <IconButton
                  label="Move up"
                  icon={ArrowUp}
                  disabled={index === 0}
                  onClick={() => move(id, neighbour(-1))}
                />
                <IconButton
                  label="Move down"
                  icon={ArrowDown}
                  disabled={index === shown.length - 1}
                  onClick={() => move(id, neighbour(1))}
                />
                <IconButton
                  label="Hide"
                  icon={EyeOff}
                  onClick={() => update(id, { hidden: true })}
                />
              </div>
            ) : Action ? (
              <Action />
            ) : null
          }
        >
          <Body />
        </Section>
      </div>
    )
  }

  return (
    <Page>
      <PageHeader title="Home" icon={House}>
        <ControlGroup>
          {editing ? (
            <button type="button" onClick={() => apply(DEFAULT_LAYOUT)} className={controlClass()}>
              <RotateCcw className="size-3.5" />
              Reset
            </button>
          ) : null}
          <button
            type="button"
            aria-pressed={editing}
            onClick={() => setEditing(!editing)}
            className={controlClass(editing)}
          >
            <LayoutDashboard className="size-3.5" />
            {editing ? 'Done' : 'Customize'}
          </button>
        </ControlGroup>
      </PageHeader>

      {editing && hidden.length ? (
        <div className="mb-6 flex flex-wrap items-center gap-2">
          {hidden.map(({ id }) => {
            const panel = PANELS.find((p) => p.id === id)!
            return (
              <button
                key={id}
                type="button"
                onClick={() => update(id, { hidden: false })}
                className={controlClass()}
              >
                <Plus className="size-3.5" />
                {panel.title}
              </button>
            )
          })}
        </div>
      ) : null}

      {/* Rows wait for the saved layout. A row takes its split only when it first mounts, so
          one drawn from the default layout would keep equal widths after the saved one came. */}
      {settings.data ? (
        <div className="flex flex-col gap-6">
          {wide
            ? rowsOf(shown).map((row) =>
                row.length === 1 ? (
                  <Fragment key={row[0].id}>{tile(row[0])}</Fragment>
                ) : (
                  // Keyed by its members, so a row that changes starts from its saved split.
                  <ResizablePanelGroup
                    key={row.map((p) => p.id).join('+')}
                    orientation="horizontal"
                    defaultLayout={savedSplit(row)}
                    onLayoutChanged={(split, meta) => {
                      if (meta.isUserInteraction) resize(meta.requestedLayout ?? split)
                    }}
                    // The library clips the group and sizes it to its parent. Rows take the
                    // height of their tallest panel instead, and dashed edit outlines show.
                    style={{ height: 'auto', overflow: 'visible' }}
                  >
                    {row.map((entry, i) => (
                      <Fragment key={entry.id}>
                        {i ? (
                          <ResizableHandle
                            withHandle
                            className="w-6 bg-transparent [&>div]:opacity-0 [&>div]:transition-opacity hover:[&>div]:opacity-100 focus-visible:[&>div]:opacity-100"
                          />
                        ) : null}
                        <ResizablePanel
                          id={entry.id}
                          minSize="20"
                          className="flex flex-col"
                          style={{ overflow: 'visible' }}
                        >
                          {tile(entry)}
                        </ResizablePanel>
                      </Fragment>
                    ))}
                  </ResizablePanelGroup>
                ),
              )
            : shown.map((entry) => <Fragment key={entry.id}>{tile(entry)}</Fragment>)}
        </div>
      ) : null}
    </Page>
  )
}

function IconButton({
  label,
  icon: Icon,
  disabled = false,
  onClick,
}: {
  label: string
  icon: LucideIcon
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <Tip content={label}>
      <button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
        className={cn(controlClass(), 'h-6 px-1.5')}
      >
        <Icon className="size-3" />
      </button>
    </Tip>
  )
}
