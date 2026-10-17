import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  Clock,
  LayoutGrid,
  List,
  type LucideIcon,
  Radar,
  RotateCcw,
  Save,
  SlidersHorizontal,
  Table,
  TriangleAlert,
} from 'lucide-react'

import { Children, Fragment, createContext, useContext, useRef, useState } from 'react'

import { Alert, AlertTitle } from '@/components/ui/alert'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { FieldDescription, FieldLabel, Field as UiField } from '@/components/ui/field'
import { Separator } from '@/components/ui/separator'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Spinner } from '@/components/ui/spinner'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { STATE_LABEL, type ServiceHealth, type State, type View, clockTime } from '@/lib/api'
import { ANY, type Controls, KEPT, type PageControls } from '@/lib/controls'
import type { Status } from '@/lib/items'
import { logo } from '@/lib/theme'
import { cn, controlClass } from '@/lib/utils'

/**
 * The page template every route uses: a header with the title on the left and the controls on
 * the right, then sections.
 */
export function Page({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-6 sm:px-6">{children}</div>
}

/** The icon and the title, nothing above or beside it. */
export function PageHeader({
  title,
  icon: Icon,
  children,
}: {
  title: string
  /** The same icon the page has in the menu. */
  icon: LucideIcon
  /**
   * What stays in the header, laid out on the right: navigation and actions, then the page's
   * `Options` last. Each child is one group and a separator falls between groups. Controls
   * that belong together sit in one `ControlGroup`.
   */
  children?: React.ReactNode
}) {
  const groups = Children.toArray(children)
  return (
    <header className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-3">
      <h1 className="flex min-w-0 grow items-center gap-2.5 text-xl font-semibold tracking-tight text-ink">
        <Icon className="size-5 shrink-0 text-ink-faint" />
        <Clip>{title}</Clip>
      </h1>
      {groups.length ? (
        <div className="ml-auto flex items-center gap-2">
          {groups.map((group, i) => (
            <Fragment key={i}>
              {i ? (
                <Separator
                  orientation="vertical"
                  className="mx-1 data-[orientation=vertical]:h-5"
                />
              ) : null}
              {group}
            </Fragment>
          ))}
        </div>
      ) : null}
    </header>
  )
}

/** Header controls that make one group, with no separator between them. */
export function ControlGroup({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center gap-2">{children}</div>
}

/** Inside `Options`, where a `Segmented` is drawn as the menu's radio items. */
const InOptions = createContext(false)

/**
 * A page's display mode, kind and filters, in that order, behind one button that is the last
 * thing in its header, so the header keeps to one line on any screen. They drop below it in a
 * menu, each under its name, as the search bar's category picker does. The button carries the
 * accent while any of them differs from the page's default. Each child is one `Control`.
 */
export function Options({
  controls,
  children,
}: {
  controls: PageControls<Controls>
  children: React.ReactNode
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label="Options" className={controlClass(controls.changed)}>
          <SlidersHorizontal className="size-3.5" />
          <span className="hidden sm:inline">Options</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <InOptions.Provider value>{children}</InOptions.Provider>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={controls.reset} disabled={!controls.changed}>
          <RotateCcw />
          Reset
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={controls.save} disabled={!controls.changed || controls.saving}>
          {controls.saving ? <Spinner /> : <Save />}
          Save as default
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** One control in `Options`, under its name. */
export function Control({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <DropdownMenuGroup>
      <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
        {label}
      </DropdownMenuLabel>
      {children}
    </DropdownMenuGroup>
  )
}

/** A block above sections, used only where one page holds several categories. */
export function Group({
  title,
  icon: Icon,
  count,
  children,
}: {
  title: string
  icon: LucideIcon
  count?: number
  children: React.ReactNode
}) {
  return (
    <section>
      <div className="mb-4 flex items-center gap-2.5">
        <Icon className="size-4 text-ink-faint" />
        <h2 className="text-lg font-semibold tracking-tight text-ink">{title}</h2>
        {count !== undefined ? (
          <span className="text-sm font-medium text-accent">{count}</span>
        ) : null}
      </div>
      {children}
    </section>
  )
}

/**
 * A run of items under one heading, a month, a publisher, a status, on its own raised panel.
 * The body carries no padding: grids pad themselves, lists and tables run edge to edge, and
 * anything else goes in `PanelBody`.
 */
export function Section({
  title,
  icon: Icon,
  count,
  note,
  action,
  children,
}: {
  title: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  count?: number
  /** How to read the whole panel, set right in its header in faint ink. */
  note?: React.ReactNode
  /** A control acting on the whole panel, set right in its header. */
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Card className="gap-0 bg-surface py-0">
      <CardHeader className="flex items-center gap-2.5 border-b border-line bg-raised/40 px-4 py-2.5 [.border-b]:pb-2.5">
        {Icon ? <Icon className="size-3.5 shrink-0 text-accent" /> : null}
        <CardTitle className="text-xs font-semibold tracking-wider text-ink-dim uppercase">
          <h3>{title}</h3>
        </CardTitle>
        {count !== undefined ? (
          <span className="text-xs font-medium text-accent">{count}</span>
        ) : null}
        {note ? (
          <span className="ml-auto min-w-0 text-2xs text-ink-faint">
            <Clip>{note}</Clip>
          </span>
        ) : null}
        {action ? <div className={cn(!note && 'ml-auto')}>{action}</div> : null}
      </CardHeader>
      {children}
    </Card>
  )
}

export function PanelBody({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return <div className={cn('p-4', className)}>{children}</div>
}

/**
 * The robin of the logo in one colour, `currentColor`, standing in wherever data is missing:
 * a cover with no art, a list with nothing in it. The back sits back, the breast and bill
 * lead, the eye cut out of the breast.
 */
export function Robin({ className }: { className?: string }) {
  return (
    <svg viewBox="18 14 100 100" fill="currentColor" aria-hidden className={className}>
      <circle cx="64" cy="64" r="38" opacity=".45" />
      {/* The breast is where a circle on it meets the body's. */}
      <path
        fillRule="evenodd"
        d="M96.31 44.01A31 31 0 1 0 72.27 101.09A38 38 0 0 0 96.31 44.01ZM82.5 51a4.5 4.5 0 1 0 9 0a4.5 4.5 0 1 0-9 0Z"
      />
      <path d="m100 53 10 3.5-10 3z" />
    </svg>
  )
}

/** A panel with nothing to show: the robin and a line saying so. */
export function PanelEmpty({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <PanelBody className={cn('flex items-center gap-3 text-xs text-ink-faint', className)}>
      <Robin className="size-6 shrink-0 opacity-60" />
      {children}
    </PanelBody>
  )
}

/** Vertical rhythm between section panels. */
/** `dimmed` while the page's controls changed and what they ask for is still on its way. */
export function Sections({
  dimmed = false,
  children,
}: {
  dimmed?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={cn('space-y-6 transition-opacity', dimmed && 'opacity-50')}>{children}</div>
  )
}

/** Empty states and failures, in place of the content they stand for. */
export function Notice({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'bad'
  children: React.ReactNode
}) {
  if (tone === 'bad') {
    return (
      <Alert variant="destructive" className="rounded-card border-bad/30 bg-bad/8 text-bad">
        <TriangleAlert />
        <AlertTitle className="line-clamp-none">{children}</AlertTitle>
      </Alert>
    )
  }
  return (
    <Empty className="rounded-card border border-line bg-surface shadow-raised md:p-10">
      <EmptyHeader>
        <EmptyMedia variant="icon" className="size-12 bg-raised text-ink-faint">
          <Robin className="size-7!" />
        </EmptyMedia>
        <EmptyTitle className="text-sm font-medium text-ink-dim">{children}</EmptyTitle>
      </EmptyHeader>
    </Empty>
  )
}

export type Option<T extends string> = {
  value: T
  label: string
  icon?: React.ComponentType<{ className?: string }>
  count?: number
}

/**
 * One choice out of a few: a display mode, a filter. A Radix toggle group, so arrow keys move
 * between the options. Clicking the active option again would clear it, which is ignored.
 * Inside `Options` it is the menu's radio items instead.
 */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: Option<T>[]
  value: T
  onChange: (value: T) => void
}) {
  if (useContext(InOptions)) {
    return (
      <DropdownMenuRadioGroup
        aria-label={label}
        value={value}
        onValueChange={(next) => onChange(next as T)}
      >
        {options.map((option) => (
          <DropdownMenuRadioItem key={option.value} value={option.value}>
            {option.icon ? <option.icon /> : null}
            {option.label}
            {option.count !== undefined ? (
              <span className="ml-auto text-xs text-ink-faint">{option.count}</span>
            ) : null}
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
    )
  }
  return (
    <ToggleGroup
      type="single"
      spacing={1}
      className="flex-wrap"
      aria-label={label}
      value={value}
      onValueChange={(next) => (next ? onChange(next as T) : undefined)}
    >
      {options.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={option.value}
          className={controlClass(value === option.value)}
        >
          {option.icon ? <option.icon className="size-3.5" /> : null}
          <span>{option.label}</span>
          {option.count !== undefined ? (
            <span className="text-ink-faint">{option.count}</span>
          ) : null}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

const VIEWS: Option<View>[] = [
  { value: 'list', label: 'List', icon: List },
  { value: 'cover', label: 'Covers', icon: LayoutGrid },
  { value: 'table', label: 'Table', icon: Table },
]

/** The display mode control, the first in the `Options` of every item page. */
export function ViewSwitch({ value, onChange }: { value: View; onChange: (view: View) => void }) {
  return (
    <Control label="Layout">
      <Segmented label="Layout" options={VIEWS} value={value} onChange={onChange} />
    </Control>
  )
}

const STATES: Record<State, { icon: LucideIcon; color: string }> = {
  waiting: { icon: Clock, color: 'text-wait' },
  tracking: { icon: Radar, color: 'text-track' },
  found: { icon: CircleCheck, color: 'text-good' },
  error: { icon: CircleAlert, color: 'text-bad' },
}

/** The device's main pointer cannot hover: a phone or a tablet, where a tap stands in. */
const touchFirst = () => window.matchMedia('(hover: none)').matches

/**
 * A tooltip that a tap opens too, since a touch screen has no hover. The tap opens it and does
 * nothing else, so a cut title on a card shows itself rather than opening the card. A tap
 * anywhere else, or a scroll, closes it. `when` decides whether there is anything to show.
 */
export function Tip({
  content,
  when,
  className,
  children,
}: {
  content: React.ReactNode
  when?: () => boolean
  className?: string
  /** The trigger, a single element that takes a ref. */
  children: React.ReactElement
}) {
  const [open, setOpen] = useState(false)
  const shows = () => (when ? when() : true)
  return (
    <Tooltip open={open} onOpenChange={(next) => setOpen(next && shows())}>
      <TooltipTrigger
        asChild
        onClick={(event) => {
          if (!touchFirst() || !shows()) return
          // Also keeps Radix from closing it again on the same click.
          event.preventDefault()
          event.stopPropagation()
          setOpen(true)
        }}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent className={className}>{content}</TooltipContent>
    </Tooltip>
  )
}

/**
 * The one way a state is shown: a semaphore glyph, amber waiting, green found, red error.
 * Hovering it names the state and whatever else is known.
 */
export function StatusGlyph({ status, className }: { status: Status; className?: string }) {
  const { icon: Icon, color } = STATES[status.state]
  const label = STATE_LABEL[status.state]
  const detail = status.detail?.filter(Boolean)
  return (
    <Tip
      content={
        <>
          <p className={cn('font-medium', color)}>{label}</p>
          {detail?.map((line) => (
            <p key={String(line)} className="text-ink-dim">
              {line}
            </p>
          ))}
        </>
      }
    >
      <span
        role="img"
        aria-label={label}
        className={cn('inline-flex shrink-0 cursor-default', color, className)}
      >
        <Icon className="size-3.5" strokeWidth={2.25} />
      </span>
    </Tip>
  )
}

/**
 * One line of text that never wraps. When it does not fit it is cut, and hovering it shows the
 * whole of it in a tooltip, so every row of text keeps to one line.
 */
export function Clip({
  children,
  full,
  className,
}: {
  children: React.ReactNode
  /** What the tooltip shows, when the visible text is not the whole of it. */
  full?: React.ReactNode
  className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  // Only a line that is actually cut gets a tooltip, measured when the pointer or tap arrives.
  const cut = () => {
    const el = ref.current
    return el !== null && el.scrollWidth > el.clientWidth
  }
  return (
    <Tip content={full ?? children} when={cut} className="max-w-md break-words">
      <span ref={ref} className={cn('block min-w-0 truncate', className)}>
        {children}
      </span>
    </Tip>
  )
}

export function Field({
  id,
  label,
  hint,
  action,
  children,
}: {
  /** The control the label names. */
  id?: string
  label: string
  hint?: string
  /** A control acting on the whole field, set right of its label. */
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <UiField className="gap-1.5">
      <div className="flex min-h-6 items-center justify-between gap-3">
        <FieldLabel htmlFor={id} className="text-xs font-normal text-ink-dim">
          {label}
        </FieldLabel>
        {action}
      </div>
      {children}
      {hint ? (
        <FieldDescription className="text-2xs text-ink-faint">
          <Clip>{hint}</Clip>
        </FieldDescription>
      ) : null}
    </UiField>
  )
}

/**
 * How one service is doing, in the same words for every service: Healthy, Faulty with the
 * error it gave, or Not set up.
 */
export function HealthWord({ health }: { health: ServiceHealth }) {
  if (health.state === 'unset') {
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-xs text-ink-faint">
        <CircleDashed className="size-3.5 shrink-0" />
        <span className="shrink-0">Not set up</span>
        {health.error ? <Clip className="text-ink-dim">{health.error}</Clip> : null}
      </span>
    )
  }
  const healthy = health.state === 'healthy'
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-xs">
      <StateIcon state={healthy ? 'found' : 'error'} />
      <span className={cn('shrink-0 font-medium', healthy ? 'text-good' : 'text-bad')}>
        {healthy ? 'Healthy' : 'Faulty'}
      </span>
      {health.error ? (
        <Clip className="text-ink-dim">
          {health.until ? `${health.error}, paused until ${clockTime(health.until)}` : health.error}
        </Clip>
      ) : null}
    </span>
  )
}

/** A state spelled out next to its glyph, for counts and status lines. */
export function StateIcon({ state, className }: { state: State; className?: string }) {
  const { icon: Icon, color } = STATES[state]
  return <Icon className={cn('size-3.5 shrink-0', color, className)} strokeWidth={2.25} />
}

/**
 * A pick out of a long list that Settings narrows, in `Options`: a submenu naming what is
 * picked, holding what Settings leaves, named in full, then any value, then each one. With
 * nothing hidden, Settings already means any, so it is not offered twice.
 */
export function KeptSelect({
  value,
  kept,
  any,
  options,
  onChange,
}: {
  value: string
  /** What Settings leaves, as `filtered` names it, empty when it hides nothing. */
  kept: string[]
  /** What any value is called, such as Any genre. */
  any: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  const current = value || (kept.length ? KEPT : ANY)
  const named =
    current === KEPT
      ? kept.join(', ')
      : current === ANY
        ? any
        : (options.find((o) => o.value === current)?.label ?? current)
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <span className="min-w-0 truncate">{named}</span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="max-h-80 w-56 overflow-y-auto">
        <DropdownMenuRadioGroup
          value={current}
          onValueChange={(next) => onChange(next === ANY && !kept.length ? KEPT : next)}
        >
          {kept.length ? (
            <DropdownMenuRadioItem value={KEPT}>{kept.join(', ')}</DropdownMenuRadioItem>
          ) : null}
          <DropdownMenuRadioItem value={ANY}>{any}</DropdownMenuRadioItem>
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  )
}

/** Below an infinite list, the robin in flight while the next page is on its way. */
export function NextPage({ loading }: { loading: boolean }) {
  return (
    <div className="flex h-16 items-center justify-center">
      {loading ? <Spinner className="size-8 text-ink-dim" /> : null}
    </div>
  )
}

/** The attribution a data source asks for, under the list it gave. */
export function SourceCredit({
  name,
  href,
  terms,
}: {
  name: string
  href: string
  /** Anything more the source asks to be said. */
  terms?: string
}) {
  return (
    <p className="mt-4 text-center text-2xs text-ink-faint">
      Data from{' '}
      <a href={href} target="_blank" rel="noreferrer" className="text-ink-dim hover:text-accent">
        {name}
      </a>
      .{terms ? ` ${terms}` : ''}
    </p>
  )
}

// The wind the robin flies through: top, length against its box, delay and duration. Clouds
// drift slower, and start partway across, a negative delay, so the sky is never empty.
const STREAKS = [
  { top: '20%', width: '28%', delay: 0, duration: 1.1, front: false },
  { top: '38%', width: '40%', delay: 0.45, duration: 0.9, front: false },
  { top: '56%', width: '22%', delay: 0.8, duration: 1.2, front: true },
  { top: '72%', width: '34%', delay: 0.2, duration: 1, front: false },
  { top: '30%', width: '17%', delay: 1, duration: 0.8, front: true },
]
const CLOUDS = [
  { top: '4%', width: '30%', delay: -1, duration: 6, front: false },
  { top: '58%', width: '20%', delay: -4, duration: 4.5, front: false },
  { top: '26%', width: '12%', delay: -2.5, duration: 3.5, front: false },
  { top: '74%', width: '16%', delay: -0.5, duration: 3, front: true },
]

/** A cloud of three puffs on a flat base, in the current colour. */
function Cloud({ className, style }: { className: string; style: React.CSSProperties }) {
  return (
    <svg viewBox="0 0 64 32" className={className} style={style}>
      <circle cx="18" cy="20" r="10" fill="currentColor" />
      <circle cx="32" cy="14" r="13" fill="currentColor" />
      <circle cx="47" cy="20" r="10" fill="currentColor" />
      <rect x="18" y="20" width="29" height="10" fill="currentColor" />
    </svg>
  )
}

/**
 * The logo in flight, streaks of wind and clouds passing behind and across it. `small` sits in a
 * line, streaks alone.
 */
export function FlyingLogo({ small = false }: { small?: boolean }) {
  const place = (top: string, width: string, delay: number, duration: number) =>
    ({ top, width, animationDelay: `${delay}s`, '--d': duration }) as React.CSSProperties
  const sky = (front: boolean) => [
    ...(small ? [] : CLOUDS)
      .filter((c) => c.front === front)
      .map(({ top, width, delay, duration }) => (
        <Cloud
          key={`cloud-${top}`}
          className={cn(
            'flight-streak absolute',
            front ? 'text-ink-faint/25' : 'text-ink-faint/15',
          )}
          style={place(top, width, delay, duration)}
        />
      )),
    ...STREAKS.filter((s) => s.front === front).map(({ top, width, delay, duration }) => (
      <span
        key={top}
        className={cn(
          'flight-streak absolute rounded-full',
          small ? 'h-1' : 'h-2',
          front ? 'bg-accent/50' : 'bg-ink-faint/30',
        )}
        style={place(top, width, delay, duration)}
      />
    )),
  ]
  const wind = 'pointer-events-none absolute inset-0 overflow-hidden flight-wind'
  return (
    <div
      aria-hidden
      className={cn(
        'relative flex shrink-0 items-center justify-center',
        small ? 'h-8 w-20' : 'h-36 w-72',
      )}
      style={{ '--wind': small ? '5rem' : '18rem' } as React.CSSProperties}
    >
      <div className={wind}>{sky(false)}</div>
      {/* Positioned, so it paints over the wind behind it and under the wind in front. */}
      <img
        src={logo(document.documentElement.dataset.theme)}
        alt=""
        className={cn('flight relative', small ? 'size-6' : 'size-24')}
      />
      <div className={wind}>{sky(true)}</div>
    </div>
  )
}
