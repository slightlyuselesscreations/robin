import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bell,
  Blocks,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  BookOpen,
  Clapperboard,
  Database,
  Download,
  Film,
  Fingerprint,
  Gamepad2,
  Library,
  LibraryBig,
  Eye,
  EyeOff,
  Languages,
  ListFilter,
  type LucideIcon,
  LogOut,
  Newspaper,
  Palette,
  PlugZap,
  Plus,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  Trash2,
  Tv,
  UserRound,
  X,
} from 'lucide-react'
import { createContext, useContext, useEffect, useState } from 'react'
import { NavLink, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { CodeInput } from '@/components/CodeInput'
import { ReleaseTag } from '@/components/MediaCard'
import {
  Clip,
  Field,
  Group,
  HealthWord,
  Page,
  PageHeader,
  PanelBody,
  Section,
  Segmented,
} from '@/components/Page'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  type Category,
  api,
  type FavouriteCategory,
  type FavouriteKind,
  type MakerMode,
  GAME_PLATFORMS,
  type Health,
  LIBRARY_NAME,
  type Library as Arr,
  type Me,
  type Notice,
  SERVICE_LABELS,
  SERVICES,
  type ServiceHealth,
  type NamedThing,
  type Destination,
  type NotifyService,
  type Settings,
  cancelled,
  passkeysSupported,
  signedOut,
  errorText,
  releaseSize,
} from '@/lib/api'
import { useSettings } from '@/lib/categories'
import { riseAt } from '@/lib/motion'
import { KINDS, KIND_LABEL, useMakerFilters } from '@/lib/favourites'
import { say } from '@/lib/say'
import { SCHEMES, THEMES, logo, useTheme } from '@/lib/theme'
import { day } from '@/lib/items'
import { INPUT, cn, controlClass } from '@/lib/utils'

// Reported by the API but not editable: a secret reduced to a boolean, or a readiness flag.
// Everything else in the settings payload is a form field.
const REPORTED_ONLY = [
  'has_twitch_client_secret',
  'has_prowlarr_api_key',
  'has_qbittorrent_api_key',
  'has_radarr_api_key',
  'has_sonarr_api_key',
  'radarr_ready',
  'sonarr_ready',
  'igdb_ready',
  'comics_ready',
  'prowlarr_ready',
  'qbittorrent_ready',
  'suwayomi_ready',
  'notify_ready',
  'has_tmdb_token',
  'tmdb_ready',
  'screen_notices_ready',
  'has_hardcover_token',
  'has_metron_token',
  'hardcover_ready',
  'books_notices_ready',
  'has_backup_passphrase',
  'backups_ready',
] as const satisfies readonly (keyof Settings)[]

// Saved the moment they change, so Save never sends back what was seeded.
const SAVED_APART = ['theme', 'scheme'] as const satisfies readonly (keyof Settings)[]

/**
 * General holds what every category shares. Each category then has its own tab, and a new
 * category is a new entry here plus its sections.
 */
/** One per category, or this does not compile. Settings and setup both read it. */
const CATEGORY_TABS = {
  games: { label: 'Games', icon: Gamepad2, Body: GamesTab },
  comics: { label: 'Comics', icon: BookOpen, Body: ComicsTab },
  screens: { label: 'Screens', icon: Clapperboard, Body: ScreensTab },
  books: { label: 'Books', icon: LibraryBig, Body: BooksTab },
} satisfies Record<
  Category,
  { label: string; icon: LucideIcon; Body: React.ComponentType<TabProps & { stored: Settings }> }
>

const TABS: { slug: string; label: string; icon: LucideIcon }[] = [
  { slug: '', label: 'General', icon: Settings2 },
  ...Object.entries(CATEGORY_TABS).map(([slug, tab]) => ({ slug, ...tab })),
]

type Form = Partial<Settings> & {
  twitch_client_secret?: string
  prowlarr_api_key?: string
  qbittorrent_api_key?: string
  tmdb_token?: string
  hardcover_token?: string
  metron_token?: string
  radarr_api_key?: string
  sonarr_api_key?: string
  backup_passphrase?: string
}

/** What of the stored settings the form edits. Everything editable is taken by difference rather
 * than named, so a new setting cannot be left out of the form and silently read as blank. */
function editable(stored: Settings): Form {
  const form: Partial<Settings> = { ...stored }
  for (const key of [...REPORTED_ONLY, ...SAVED_APART]) delete form[key]
  return form
}

/** The settings form, seeded once the stored settings arrive. Adjusted during render rather
 * than in an effect so the inputs never flash empty. */
function useSettingsForm() {
  const settings = useSettings()
  const [form, setForm] = useState<Form>({})
  const [seeded, setSeeded] = useState(false)
  if (settings.data && !seeded) {
    setSeeded(true)
    setForm(editable(settings.data))
  }
  return { settings, form, setForm }
}

export function SettingsPage() {
  const { tab = '' } = useParams()
  const queryClient = useQueryClient()
  const { settings, form, setForm } = useSettingsForm()
  const [report, setReport] = useState<Health | null>(null)

  const save = useMutation({
    mutationFn: () => api.saveSettings(form),
    onSuccess: () => {
      toast.success('Settings saved')
      void queryClient.invalidateQueries()
    },
    onError: (error: unknown) =>
      toast.error('Could not save', {
        description: errorText(error, 'Unknown error'),
      }),
  })

  // The same check Home shows, asked fresh, so the two never disagree.
  const test = useMutation({
    mutationFn: () => api.health(true),
    onSuccess: (result) => {
      setReport(result)
      queryClient.setQueryData(['health'], result)
    },
    onError: () => toast.error('Connection test failed to run'),
  })

  const current = TABS.find((t) => t.slug === tab) ?? TABS[0]
  // A tab slides in from the side it sits on, against the one left.
  const at = TABS.indexOf(current)
  const [was, setWas] = useState({ at, back: false })
  if (was.at !== at) setWas({ at, back: at < was.at })
  const Body = current.slug ? CATEGORY_TABS[current.slug as Category].Body : GeneralTab
  // A category whose source is unset asks for it alone, as setup does, before the rest.
  const source = current.slug ? SOURCES[current.slug as Category] : null

  return (
    <Page>
      <PageHeader title="Settings" icon={Settings2}>
        <nav className="flex items-center gap-1" aria-label="Settings">
          {TABS.map(({ slug, label, icon: Icon }) => (
            <NavLink
              key={slug}
              to={slug ? `/settings/${slug}` : '/settings'}
              end
              aria-label={label}
              className={({ isActive }) => controlClass(isActive)}
            >
              <Icon className="size-3.5" />
              <span className="hidden sm:inline">{label}</span>
            </NavLink>
          ))}
        </nav>
      </PageHeader>

      {settings.data && source && !settings.data[source.ready] ? (
        <div className="flex flex-col items-center pt-6">
          <StepFrame
            key={current.slug}
            title={SOURCES[current.slug as Category].question}
            width="max-w-md"
            back={was.back}
          >
            <SourceStep
              category={current.slug as Category}
              form={form}
              setForm={setForm}
              stored={settings.data}
            />
          </StepFrame>
          <Button className="mt-8" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? <Spinner className="size-4" /> : <Save className="size-4" />}
            Save
          </Button>
        </div>
      ) : settings.data ? (
        <div key={current.slug} data-back={was.back || undefined} className="slide-in space-y-8">
          <Body form={form} setForm={setForm} stored={settings.data} />

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? <Spinner className="size-4" /> : <Save className="size-4" />}
              Save
            </Button>
            <Button variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
              {test.isPending ? <Spinner className="size-4" /> : <PlugZap className="size-4" />}
              Test all connections
            </Button>
          </div>

          {report ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
              {SERVICES.map(({ key, label }) => (
                <Result key={key} label={label} health={report[key]} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </Page>
  )
}

type TabProps = {
  form: Form
  setForm: (form: Form) => void
}

/** The settings whose value is a `T`, so a map of them reads and writes without casts. */
type KeyOf<T> = { [K in keyof Settings]: Settings[K] extends T ? K : never }[keyof Settings]

/**
 * A tab's panels under one heading, always in the same order: General for how the category
 * behaves, Sources for where its data comes from, Integrations for the services it drives.
 */
function SettingsGroup({
  title,
  icon,
  needs,
  children,
}: {
  title: string
  icon: LucideIcon
  /** The source the panels need, named while it is unset in place of the panels. */
  needs?: string | null
  children: React.ReactNode
}) {
  return (
    <Group title={title} icon={icon}>
      {needs ? (
        <p className="text-xs text-ink-faint">Set {needs} under Sources first.</p>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-2 2xl:grid-cols-3">{children}</div>
      )}
    </Group>
  )
}

/** Where a source's key is made, in its panel's header. */
function KeyLink({ href }: { href: string }) {
  return (
    <>
      Get the API key{' '}
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-ink-dim underline underline-offset-2 hover:text-accent"
      >
        here
      </a>
    </>
  )
}

/** A secret is never sent back, only whether one is stored. */
type Secret =
  | 'twitch_client_secret'
  | 'prowlarr_api_key'
  | 'qbittorrent_api_key'
  | 'tmdb_token'
  | 'hardcover_token'
  | 'metron_token'
  | 'radarr_api_key'
  | 'sonarr_api_key'
  | 'backup_passphrase'

/**
 * A key Robin keeps and never shows again. Saved once it is, otherwise `hint` says where to
 * get one. Typing replaces it, leaving it empty keeps what is saved.
 */
function SecretField({
  name,
  label,
  hint = 'Not set',
  form,
  setForm,
  stored,
  children,
}: TabProps & {
  name: Secret
  label: string
  hint?: string
  stored: Settings
  children?: React.ReactNode
}) {
  const saved = stored[`has_${name}`]
  return (
    <Field label={label} hint={saved ? 'Saved' : hint}>
      <Input
        type="password"
        value={form[name] ?? ''}
        onChange={(e) => setForm({ ...form, [name]: e.target.value.trim() })}
        placeholder={saved ? 'Saved, type to replace' : ''}
        autoComplete="off"
        className={INPUT}
      />
      {children}
    </Field>
  )
}

/** Only what every category shares: the theme, the account, and where notifications go. */
function GeneralTab(props: StoredProps) {
  const integrations = integrationsOf(null)
  return (
    <>
      <SettingsGroup title="Appearance" icon={Palette}>
        <ThemePanel />
      </SettingsGroup>
      <SettingsGroup title="Notifications" icon={Bell}>
        <DestinationsPanel {...props} />
      </SettingsGroup>
      <SettingsGroup title="Security" icon={ShieldCheck}>
        <AccountPanel />
        <TwoFactorPanel />
        {passkeysSupported ? <PasskeysPanel /> : null}
      </SettingsGroup>
      <SettingsGroup title="Backups" icon={Database}>
        <BackupsPanel {...props} />
      </SettingsGroup>
      {integrations.length ? (
        <SettingsGroup title="Integrations" icon={Blocks}>
          {integrations.map(([key, { Panel }]) => (
            <Panel key={key} {...props} />
          ))}
        </SettingsGroup>
      ) : null}
    </>
  )
}

/** The backups on the data volume, newest first. Picked from in setup, else each downloads or
 * deletes from its row. */
function BackupList({ onPick, picked }: { onPick?: (name: string) => void; picked?: string }) {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ['backups'], queryFn: api.backups })
  // A delete asks once more, on the same button.
  const [armed, setArmed] = useState<string | null>(null)
  const remove = useMutation({
    mutationFn: api.deleteBackup,
    onSuccess: () => {
      setArmed(null)
      void client.invalidateQueries({ queryKey: ['backups'] })
    },
    onError: failed,
  })

  // Setup picks from the list, and a fresh install has none to pick.
  if (!list.data?.length)
    return onPick ? null : <p className="text-xs text-ink-faint">No backups yet</p>
  return (
    <ul className="divide-y divide-line rounded-md border border-line">
      {list.data.map((backup) => (
        <li key={backup.name} className="flex items-center gap-3 py-2 pr-1.5 pl-3">
          <button
            type="button"
            disabled={!onPick}
            onClick={() => onPick?.(backup.name)}
            aria-pressed={onPick ? picked === backup.name : undefined}
            className="min-w-0 flex-1 rounded-sm text-left focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          >
            <Clip className={cn('block text-sm text-ink', picked === backup.name && 'text-accent')}>
              {new Date(backup.created).toLocaleString()}
            </Clip>
            <Clip className="block text-2xs text-ink-faint">
              {releaseSize(backup.size)}, Robin {backup.version}
            </Clip>
          </button>
          {onPick ? null : (
            <>
              <Button variant="ghost" size="icon-sm" aria-label="Download" asChild>
                <a href={`/api/backups/${encodeURIComponent(backup.name)}`} download>
                  <Download className="size-4" />
                </a>
              </Button>
              {armed === backup.name ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => remove.mutate(backup.name)}
                  disabled={remove.isPending}
                  className="text-bad"
                >
                  Delete
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete"
                  onClick={() => setArmed(backup.name)}
                  className="text-ink-faint hover:text-bad"
                >
                  <Trash2 className="size-4" />
                </Button>
              )}
            </>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Sealed with the passphrase, written to the data volume daily while on. */
function BackupsPanel({ form, setForm, stored }: StoredProps) {
  const client = useQueryClient()
  const health = useQuery({ queryKey: ['health'], queryFn: () => api.health() })
  const changed = () => {
    void client.invalidateQueries({ queryKey: ['backups'] })
    void client.invalidateQueries({ queryKey: ['health'] })
  }
  const now = useMutation({
    mutationFn: api.backUp,
    onSuccess: () => {
      toast.success('Backed up')
      changed()
    },
    onError: (error: unknown) => {
      failed(error)
      changed()
    },
  })
  const fault = health.data?.backups.state === 'faulty' ? health.data.backups.error : null

  return (
    <Panel title="Backups" icon={Database}>
      <SecretField
        name="backup_passphrase"
        label="Passphrase"
        hint="Not set, nothing is backed up"
        form={form}
        setForm={setForm}
        stored={stored}
      />
      <Field id="backups-daily" label="Daily">
        <div className="flex flex-wrap items-center gap-3">
          <Toggle
            id="backups-daily"
            on={form.backups ?? false}
            onChange={(on) => setForm({ ...form, backups: on })}
          />
          <HourSelect
            label="Hour"
            value={form.backup_hour ?? 3}
            onChange={(hour) => setForm({ ...form, backup_hour: hour })}
          />
        </div>
      </Field>
      <Field id="backup-keep" label="Keep">
        <Input
          id="backup-keep"
          type="number"
          min={1}
          max={100}
          value={form.backup_keep ?? 7}
          onChange={(e) =>
            setForm({ ...form, backup_keep: Math.min(100, Math.max(1, Number(e.target.value))) })
          }
          className={cn(INPUT, 'w-24')}
        />
      </Field>
      {fault ? <p className="text-xs text-bad">{fault}</p> : null}
      <BackupList />
      <div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => now.mutate()}
          disabled={now.isPending || !stored.backups_ready}
        >
          {now.isPending ? <Spinner className="size-3.5" /> : <Database className="size-3.5" />}
          Back up now
        </Button>
      </div>
    </Panel>
  )
}

/** A file as base64, without the data URL in front. */
const base64 = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the file'))
    reader.readAsDataURL(file)
  })

/**
 * Setup's first step: a backup on the data volume or one uploaded, and its passphrase. A
 * restore signs out, and the backup's account signs in from then on.
 */
function RestoreStep() {
  const client = useQueryClient()
  const [picked, setPicked] = useState<string | undefined>()
  const [file, setFile] = useState<File | null>(null)
  const [passphrase, setPassphrase] = useState('')
  const restore = useMutation({
    mutationFn: async () =>
      api.restore(file ? { data: await base64(file) } : { name: picked ?? '' }, passphrase),
    onSuccess: () => {
      toast.success('Restored')
      signedOut(client)
    },
    onError: failed,
  })

  return (
    <Rise i={0}>
      <Panel title="Backup" icon={Database}>
        <BackupList
          picked={file ? undefined : picked}
          onPick={(name) => {
            setPicked(name)
            setFile(null)
          }}
        />
        <Field id="backup-file" label="Upload">
          <Input
            id="backup-file"
            type="file"
            accept=".robin"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className={INPUT}
          />
        </Field>
        <Field id="backup-passphrase" label="Passphrase">
          <Input
            id="backup-passphrase"
            type="password"
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            autoComplete="off"
            className={INPUT}
          />
        </Field>
        <div>
          <Button
            onClick={() => restore.mutate()}
            disabled={restore.isPending || !(file || picked) || !passphrase}
          >
            {restore.isPending ? <Spinner className="size-4" /> : <Database className="size-4" />}
            Restore
          </Button>
        </div>
      </Panel>
    </Rise>
  )
}

const SERVICES_LINK = 'https://appriseit.com/services/'

/** What the picker offers, from the server, which builds every address from them. */
function useNotifyServices() {
  return useQuery({
    queryKey: ['notify-services'],
    queryFn: api.notifyServices,
    staleTime: Infinity,
  })
}

/** Setup's notifications step listens for a test that arrived, which lets it move on. */
const Proven = createContext<(() => void) | null>(null)

const newId = () => Math.random().toString(36).slice(2, 10)

/**
 * Where notifications go: a list of destinations, each a service from the picker with its
 * fields filled in with an example to replace, and a test that sends to it as the form holds it.
 * The last one cannot be removed.
 */
function DestinationsPanel({ form, setForm }: StoredProps) {
  const services = useNotifyServices()
  const destinations = form.notify_destinations ?? []
  const set = (next: Destination[]) => setForm({ ...form, notify_destinations: next })
  const add = (key: string) => {
    const service = services.data?.find((s) => s.key === key)
    if (!service) return
    const values = Object.fromEntries(
      service.fields.filter((f) => !f.secret).map((f) => [f.key, f.example]),
    )
    set([
      ...destinations,
      { id: newId(), service: key, values, saved: [], places: {}, saved_places: [] },
    ])
  }

  return (
    <Panel
      title="Destinations"
      icon={Bell}
      note={
        <a
          href={SERVICES_LINK}
          target="_blank"
          rel="noreferrer"
          className="text-ink-dim underline underline-offset-2 hover:text-accent"
        >
          Supported services
        </a>
      }
    >
      {destinations.map((destination, index) => (
        <DestinationFields
          key={destination.id}
          destination={destination}
          service={services.data?.find((s) => s.key === destination.service)}
          removable={destinations.length > 1}
          onChange={(next) => set(destinations.map((d, i) => (i === index ? next : d)))}
          onRemove={() => set(destinations.filter((_, i) => i !== index))}
        />
      ))}
      <Select value="" onValueChange={add}>
        <SelectTrigger
          size="sm"
          aria-label="Add destination"
          className="border-line bg-base text-xs"
        >
          <Plus className="size-3.5" />
          <SelectValue placeholder="Add destination" />
        </SelectTrigger>
        <SelectContent>
          {services.data?.map((service) => (
            <SelectItem key={service.key} value={service.key}>
              {service.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Panel>
  )
}

function DestinationFields({
  destination,
  service,
  removable,
  onChange,
  onRemove,
}: {
  destination: Destination
  service: NotifyService | undefined
  removable: boolean
  onChange: (next: Destination) => void
  onRemove: () => void
}) {
  const prove = useContext(Proven)
  const test = useMutation({
    mutationFn: () => api.testNotify([destination]),
    onSuccess: (result) => {
      if (result.ok) {
        toast.success('Notification sent', { description: result.detail })
        prove?.()
      } else {
        toast.error('Not delivered', { description: result.detail })
      }
    },
    onError: (error: unknown) =>
      toast.error('Not delivered', { description: errorText(error, 'Unknown error') }),
  })
  if (!service) return null

  return (
    <div className="space-y-4 rounded-card border border-line p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-ink">{service.label}</span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() => test.mutate()}
            disabled={test.isPending}
          >
            {test.isPending ? <Spinner className="size-3.5" /> : <Bell className="size-3.5" />}
            Send a test
          </Button>
          {removable ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Remove"
              onClick={onRemove}
              className="text-ink-faint hover:text-bad"
            >
              <Trash2 className="size-3.5" />
            </Button>
          ) : null}
        </div>
      </div>
      {service.fields.map((field) => {
        const saved = destination.saved.includes(field.key)
        return (
          <Field
            key={field.key}
            label={field.label}
            hint={saved ? 'Saved' : field.optional ? 'Optional' : undefined}
          >
            <Input
              type={field.secret ? 'password' : 'text'}
              value={destination.values[field.key] ?? ''}
              onChange={(e) =>
                onChange({
                  ...destination,
                  values: { ...destination.values, [field.key]: e.target.value },
                })
              }
              placeholder={saved ? 'Saved, type to replace' : field.example}
              autoComplete="off"
              className={INPUT}
            />
          </Field>
        )
      })}
    </div>
  )
}

/**
 * Where on each destination a category's notifications land, for a service that has a place
 * such as an ntfy topic or a Telegram chat. Empty is the destination's own.
 */
function CategoryPlaces({ category, form, setForm }: TabProps & { category: Category }) {
  const services = useNotifyServices()
  const destinations = form.notify_destinations ?? []
  const set = (index: number, next: Destination) =>
    setForm({
      ...form,
      notify_destinations: destinations.map((d, i) => (i === index ? next : d)),
    })

  return destinations.map((destination, index) => {
    const service = services.data?.find((s) => s.key === destination.service)
    const field = service?.fields.find((f) => f.key === service.place)
    if (!service || !field) return null
    const saved = destination.saved_places.includes(category)
    const place = (value: string | null) => {
      const places = { ...destination.places }
      if (value === null || (value === '' && !saved)) delete places[category]
      else places[category] = value
      set(index, {
        ...destination,
        places,
        saved_places:
          value === null
            ? destination.saved_places.filter((c) => c !== category)
            : destination.saved_places,
      })
    }
    return (
      <Field
        key={destination.id}
        label={`${service.label} ${field.label.toLowerCase()}`}
        hint={saved ? 'Saved' : undefined}
      >
        <div className="flex items-center gap-1">
          <Input
            type={field.secret ? 'password' : 'text'}
            value={destination.places[category] ?? ''}
            onChange={(e) => place(e.target.value)}
            placeholder={
              saved
                ? 'Saved, type to replace'
                : field.secret
                  ? 'Default'
                  : destination.values[field.key] || 'Default'
            }
            autoComplete="off"
            className={INPUT}
          />
          {saved ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Use default"
              onClick={() => place(null)}
              className="text-ink-faint hover:text-bad"
            >
              <X className="size-3.5" />
            </Button>
          ) : null}
        </div>
      </Field>
    )
  })
}

/** The robin Robin is coloured as, and whether it is dark, light or the system's. */
function ThemePanel() {
  const { theme, scheme, set } = useTheme()
  return (
    <Panel title="Theme" icon={Palette}>
      <Field label="Species">
        <Segmented
          label="Species"
          options={THEMES}
          value={theme}
          onChange={(next) => set({ theme: next })}
        />
      </Field>
      <Field label="Mode">
        <Segmented
          label="Mode"
          options={SCHEMES}
          value={scheme}
          onChange={(next) => set({ scheme: next })}
        />
      </Field>
    </Panel>
  )
}

/** Every species side by side, each card in its own theme's accent, then the mode, for setup. */
function SpeciesPicker() {
  const { theme, scheme, set } = useTheme()
  return (
    <div className="flex flex-col items-center gap-8">
      <div className="flex w-full flex-wrap justify-center gap-3">
        {THEMES.map(({ value, label }, i) => (
          <button
            key={value}
            type="button"
            data-theme={value}
            aria-pressed={value === theme}
            onClick={() => set({ theme: value })}
            style={{ '--i': i } as React.CSSProperties}
            className={cn(
              'rise group flex w-36 flex-col items-center gap-2.5 rounded-card border p-4 sm:w-40 text-center text-xs shadow-raised transition-[color,border-color,background-color,translate] hover:-translate-y-0.5',
              value === theme
                ? 'border-accent bg-raised text-ink'
                : 'border-line bg-surface text-ink-dim hover:border-line-strong hover:text-ink',
            )}
          >
            <img
              src={logo(value)}
              alt=""
              className="size-14 transition-transform duration-300 group-hover:scale-110 group-aria-pressed:scale-110"
            />
            {label}
            <span className="h-1 w-8 rounded-full bg-(--brand)" />
          </button>
        ))}
      </div>
      <Segmented
        label="Mode"
        options={SCHEMES}
        value={scheme}
        onChange={(next) => set({ scheme: next })}
      />
    </div>
  )
}

const failed = (error: unknown) => toast.error(errorText(error, 'Something went wrong'))

/** The password, and ending every session at once. */
function AccountPanel() {
  const client = useQueryClient()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      toast.success('Password changed')
      setCurrent('')
      setNext('')
    },
    onError: failed,
  })
  const everywhere = useMutation({
    mutationFn: api.signOutEverywhere,
    onSuccess: () => signedOut(client),
    onError: failed,
  })

  return (
    <Panel title="Account" icon={UserRound}>
      <Field id="current-password" label="Current password">
        <Input
          id="current-password"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          className={INPUT}
        />
      </Field>

      <Field id="new-password" label="New password" hint="At least 8 characters.">
        <Input
          id="new-password"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          className={INPUT}
        />
      </Field>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => change.mutate()}
          disabled={change.isPending || !current || next.length < 8}
        >
          {change.isPending ? <Spinner className="size-3.5" /> : <Save className="size-3.5" />}
          Change password
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => everywhere.mutate()}
          disabled={everywhere.isPending}
        >
          {everywhere.isPending ? (
            <Spinner className="size-3.5" />
          ) : (
            <LogOut className="size-3.5" />
          )}
          Sign out everywhere
        </Button>
      </div>
    </Panel>
  )
}

/** TOTP. A secret is only kept once a code from it proves the app has it. */
function TwoFactorPanel() {
  const client = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')

  const done = (message: string) => {
    toast.success(message)
    setCode('')
    setPassword('')
    setup.reset()
    void client.invalidateQueries({ queryKey: ['me'] })
  }
  const setup = useMutation({ mutationFn: () => api.totpSetup(password), onError: failed })
  const enable = useMutation({
    mutationFn: () => api.totpEnable(code),
    onSuccess: () => done('Two factor is on'),
    onError: failed,
  })
  const disable = useMutation({
    mutationFn: () => api.totpDisable(password),
    onSuccess: () => done('Two factor is off'),
    onError: failed,
  })

  if (me.data?.totp) {
    return (
      <Panel title="Two factor" icon={ShieldCheck}>
        <PasswordAgain id="totp-password" value={password} onChange={setPassword} />
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => disable.mutate()}
            disabled={disable.isPending || !password}
          >
            {disable.isPending ? (
              <Spinner className="size-3.5" />
            ) : (
              <ShieldCheck className="size-3.5" />
            )}
            Turn off
          </Button>
        </div>
      </Panel>
    )
  }

  return (
    <Panel title="Two factor" icon={ShieldCheck}>
      {setup.data ? (
        <>
          <img
            src={setup.data.qr}
            alt="QR code for your authenticator app"
            className="size-40 rounded-sm"
          />
          <Field label="Or enter this key">
            <Clip className="font-mono text-2xs text-ink-dim">{setup.data.secret}</Clip>
          </Field>
          <Field id="totp-code" label="Code from the app">
            <CodeInput id="totp-code" value={code} onChange={setCode} />
          </Field>
          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => enable.mutate()}
              disabled={enable.isPending || code.length < 6}
            >
              {enable.isPending ? (
                <Spinner className="size-3.5" />
              ) : (
                <ShieldCheck className="size-3.5" />
              )}
              Turn on
            </Button>
          </div>
        </>
      ) : (
        <>
          <PasswordAgain id="totp-password" value={password} onChange={setPassword} />
          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setup.mutate()}
              disabled={setup.isPending || !password}
            >
              {setup.isPending ? (
                <Spinner className="size-3.5" />
              ) : (
                <ShieldCheck className="size-3.5" />
              )}
              Set up an authenticator app
            </Button>
          </div>
        </>
      )}
    </Panel>
  )
}

/** The current password, asked again before anything that changes how Robin is entered. */
function PasswordAgain({
  id,
  value,
  onChange,
}: {
  id: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <Field id={id} label="Password">
      <Input
        id={id}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="current-password"
        className={INPUT}
      />
    </Field>
  )
}

/** Absent outside a secure context, where the browser makes no passkeys. */
function PasskeysPanel() {
  const client = useQueryClient()
  const passkeys = useQuery({ queryKey: ['passkeys'], queryFn: api.passkeys })
  const [label, setLabel] = useState('')
  const [password, setPassword] = useState('')

  const changed = (message: string) => {
    toast.success(message)
    void client.invalidateQueries({ queryKey: ['passkeys'] })
    void client.invalidateQueries({ queryKey: ['me'] })
  }
  const add = useMutation({
    mutationFn: () => api.addPasskey(label.trim() || 'Passkey', password),
    onSuccess: () => {
      setLabel('')
      setPassword('')
      changed('Passkey added')
    },
    onError: (error: unknown) => {
      if (!cancelled(error)) failed(error)
    },
  })
  const remove = useMutation({
    mutationFn: api.removePasskey,
    onSuccess: () => changed('Passkey removed'),
    onError: failed,
  })

  return (
    <Panel title="Passkeys" icon={Fingerprint}>
      {passkeys.data?.length ? (
        <ul className="divide-y divide-line rounded-md border border-line">
          {passkeys.data.map((passkey) => (
            <li key={passkey.id} className="flex items-center gap-3 py-2 pr-1.5 pl-3">
              <div className="min-w-0 flex-1">
                <Clip className="block text-sm text-ink">{passkey.label}</Clip>
                <Clip className="block text-2xs text-ink-faint">
                  {[
                    `Added ${day(passkey.created_at)}`,
                    passkey.last_used_at && `used ${day(passkey.last_used_at)}`,
                  ]
                    .filter(Boolean)
                    .join(', ')}
                </Clip>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Remove ${passkey.label}`}
                onClick={() => remove.mutate(passkey.id)}
                disabled={remove.isPending}
                className="text-ink-faint hover:text-bad"
              >
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <Field id="passkey-label" label="Name">
        <Input
          id="passkey-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Passkey"
          maxLength={64}
          className={INPUT}
        />
      </Field>

      <PasswordAgain id="passkey-password" value={password} onChange={setPassword} />

      <div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => add.mutate()}
          disabled={add.isPending || !password}
        >
          {add.isPending ? <Spinner className="size-3.5" /> : <Fingerprint className="size-3.5" />}
          Add passkey
        </Button>
      </div>
    </Panel>
  )
}

function GamesTab({ form, setForm, stored }: TabProps & { stored: Settings }) {
  return (
    <>
      <SettingsGroup title="Filters" icon={ListFilter}>
        <Panel
          title="Always hide"
          icon={EyeOff}
          note={
            <>
              Select what you <Lit>never want to show</Lit>
            </>
          }
        >
          <Field label="Platforms">
            <FilterSelect
              unreachable={null}
              options={GAME_PLATFORMS}
              selected={form.games_hidden_platforms ?? []}
              onChange={(games_hidden_platforms) => setForm({ ...form, games_hidden_platforms })}
            />
          </Field>
          <MakerFields category="games" mode="hide" />
        </Panel>

        <Panel
          title="Always show"
          icon={Eye}
          note={
            <>
              Select what you <Lit>always</Lit> want to show{' '}
              <Lit>when it is paired to something you hide</Lit>
            </>
          }
        >
          <MakerFields category="games" mode="show" />
        </Panel>
      </SettingsGroup>

      <SettingsGroup title="General" icon={SlidersHorizontal}>
        <NotificationsPanel category="games" form={form} setForm={setForm} stored={stored} />
        <FavouritesPanel category="games" form={form} setForm={setForm} />
      </SettingsGroup>

      <SourceGroups category="games" form={form} setForm={setForm} stored={stored} />
    </>
  )
}

type StoredProps = TabProps & { stored: Settings }

/**
 * Each category's source, in its tab's Sources group and as its own step of setup. `key` is its
 * entry in Health, `ready` its readiness, `question` its step's title, `data` what is missing
 * while it is unset.
 */
const SOURCES = {
  games: {
    key: 'igdb',
    ready: 'igdb_ready',
    question: 'Are you a gamer?',
    data: 'game',
    Panel: IgdbPanel,
  },
  comics: {
    key: 'metron',
    ready: 'comics_ready',
    question: 'Are you a comic book reader?',
    data: 'comic',
    Panel: MetronPanel,
  },
  screens: {
    key: 'tmdb',
    ready: 'tmdb_ready',
    question: 'Are you a cinephile?',
    data: 'film and show',
    Panel: TmdbPanel,
  },
  books: {
    key: 'hardcover',
    ready: 'hardcover_ready',
    question: 'Are you an avid reader?',
    data: 'book',
    Panel: HardcoverPanel,
  },
} as const satisfies Record<
  Category,
  {
    key: keyof Health
    ready: KeyOf<boolean>
    question: string
    data: string
    Panel: React.ComponentType<StoredProps>
  }
>

/**
 * Every integration Health checks, or this does not compile, each in the tab of the category
 * it serves, General's for none, and all together in setup. PreDB is keyless, nothing to set,
 * and qBittorrent is part of Prowlarr's panel.
 */
const INTEGRATIONS = {
  prowlarr: { category: 'games', Panel: ProwlarrPanel },
  suwayomi: { category: 'comics', Panel: SuwayomiPanel },
  radarr: { category: 'screens', Panel: (props) => <ArrPanel app="radarr" {...props} /> },
  sonarr: { category: 'screens', Panel: (props) => <ArrPanel app="sonarr" {...props} /> },
} as const satisfies Record<
  Exclude<
    keyof Health,
    (typeof SOURCES)[Category]['key'] | 'predb' | 'qbittorrent' | 'notify' | 'backups'
  >,
  { category: Category | null; Panel: React.ComponentType<StoredProps> }
>

type IntegrationKey = keyof typeof INTEGRATIONS

const integrationsOf = (category: Category | null) =>
  (Object.keys(INTEGRATIONS) as IntegrationKey[])
    .filter((key) => INTEGRATIONS[key].category === category)
    .map((key) => [key, INTEGRATIONS[key]] as const)

/** A category's source, then what it drives once that is set. */
function SourceGroups({ category, ...props }: StoredProps & { category: Category }) {
  const { Panel: Source, ready } = SOURCES[category]
  const integrations = integrationsOf(category)
  return (
    <>
      <SettingsGroup title="Sources" icon={Database}>
        <Source {...props} />
      </SettingsGroup>
      {integrations.length ? (
        <SettingsGroup
          title="Integrations"
          icon={Blocks}
          needs={props.stored[ready] ? null : SERVICE_LABELS[SOURCES[category].key]}
        >
          {integrations.map(([key, { Panel }]) => (
            <Panel key={key} {...props} />
          ))}
        </SettingsGroup>
      ) : null}
    </>
  )
}

function IgdbPanel({ form, setForm, stored }: StoredProps) {
  return (
    <Panel title="IGDB" icon={Gamepad2} note={<KeyLink href="https://api-docs.igdb.com" />}>
      <Field label="Twitch client id">
        <Input
          value={form.twitch_client_id ?? ''}
          onChange={(e) => setForm({ ...form, twitch_client_id: e.target.value })}
          className={INPUT}
        />
      </Field>

      <SecretField
        name="twitch_client_secret"
        label="Twitch client secret"
        form={form}
        setForm={setForm}
        stored={stored}
      />
    </Panel>
  )
}

function MetronPanel({ form, setForm, stored }: StoredProps) {
  return (
    <Panel
      title="Metron"
      icon={BookOpen}
      note={<KeyLink href="https://metron.cloud/accounts/profile/" />}
    >
      <SecretField
        name="metron_token"
        label="API key"
        form={form}
        setForm={setForm}
        stored={stored}
      />
    </Panel>
  )
}

function HardcoverPanel({ form, setForm, stored }: StoredProps) {
  return (
    <Panel title="Hardcover" icon={LibraryBig} note={<KeyLink href={HARDCOVER_NEW_KEY} />}>
      <SecretField
        name="hardcover_token"
        label="API key"
        form={form}
        setForm={setForm}
        stored={stored}
      />
    </Panel>
  )
}

/** qBittorrent, optional within Prowlarr: with it Robin follows each grab to downloaded. */
function QbittorrentFields({ form, setForm, stored }: StoredProps) {
  const categories = useQuery({
    queryKey: ['qbittorrent-categories'],
    queryFn: api.qbittorrentCategories,
    retry: false,
    enabled: stored.qbittorrent_ready,
  })
  // The one kept may be one qBittorrent does not have yet. It makes it on the first grab.
  const category = form.qbittorrent_category || 'games'
  const categoryOptions = [...new Set([category, ...(categories.data ?? [])])]

  return (
    <div className="space-y-5 border-t border-line pt-5">
      <div className="space-y-1">
        <div className="flex items-center gap-2 text-xs font-semibold tracking-wider text-ink-dim uppercase">
          <Download className="size-3.5 text-accent" />
          qBittorrent
          <ReleaseTag tag="Optional" />
        </div>
        <p className="text-xs text-ink-faint">
          Optionally track downloads in a Home panel, and get "download complete" notifications.
        </p>
      </div>
      <Field label="WebUI URL">
        <Input
          value={form.qbittorrent_url ?? ''}
          onChange={(e) => setForm({ ...form, qbittorrent_url: e.target.value })}
          placeholder="http://qbittorrent:8080"
          className={INPUT}
        />
      </Field>

      <SecretField
        name="qbittorrent_api_key"
        label="API key"
        hint="qBittorrent 5.2 or newer. Empty when it needs none."
        form={form}
        setForm={setForm}
        stored={stored}
      />

      <Field label="Category">
        {stored.qbittorrent_ready ? (
          <Select
            value={category}
            onValueChange={(qbittorrent_category) => setForm({ ...form, qbittorrent_category })}
          >
            <SelectTrigger className="w-full border-line bg-base">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {categoryOptions.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            value={form.qbittorrent_category ?? ''}
            onChange={(e) => setForm({ ...form, qbittorrent_category: e.target.value })}
            placeholder="games"
            className={INPUT}
          />
        )}
      </Field>
    </div>
  )
}

function ProwlarrPanel({ form, setForm, stored }: StoredProps) {
  // What Prowlarr holds is asked for, and offered, only once it is set.
  const indexers = useQuery({
    queryKey: ['prowlarr-indexers'],
    queryFn: api.prowlarrIndexers,
    retry: false,
    enabled: stored.prowlarr_ready,
  })
  // Typed as text, so a trailing space survives until the next group is typed.
  const [groups, setGroups] = useState((form.p2p_groups ?? []).join(' '))

  return (
    <Panel title="Prowlarr" icon={Search}>
      <Field label="Instance URL">
        <Input
          value={form.prowlarr_url ?? ''}
          onChange={(e) => setForm({ ...form, prowlarr_url: e.target.value })}
          placeholder="http://prowlarr:9696"
          className={INPUT}
        />
      </Field>

      <SecretField
        name="prowlarr_api_key"
        label="API key"
        form={form}
        setForm={setForm}
        stored={stored}
      />

      {stored.prowlarr_ready ? (
        <Field label="Indexers">
          <IndexerToggles
            items={indexers.data}
            unreachable={indexers.isError ? 'Prowlarr unreachable.' : null}
            selected={form.prowlarr_indexer_ids ?? []}
            onChange={(prowlarr_indexer_ids) => setForm({ ...form, prowlarr_indexer_ids })}
          />
        </Field>
      ) : (
        <NotYet label="Indexers" />
      )}

      <Field label="Freeleech only">
        <Toggle
          id="freeleech-only"
          on={form.freeleech_only ?? true}
          onChange={(freeleech_only) => setForm({ ...form, freeleech_only })}
        />
      </Field>

      <Field label="Extra release groups to follow" hint="Separate them with spaces.">
        <Input
          value={groups}
          onChange={(e) => {
            setGroups(e.target.value)
            setForm({ ...form, p2p_groups: e.target.value.split(/[\s,]+/).filter(Boolean) })
          }}
          spellCheck={false}
          className={INPUT}
        />
      </Field>

      <QbittorrentFields form={form} setForm={setForm} stored={stored} />
    </Panel>
  )
}

function SuwayomiPanel({ form, setForm }: StoredProps) {
  return (
    <Panel title="Suwayomi" icon={Library}>
      <Field label="Instance URL">
        <Input
          value={form.suwayomi_url ?? ''}
          onChange={(e) => setForm({ ...form, suwayomi_url: e.target.value })}
          placeholder="http://suwayomi:4567"
          className={INPUT}
        />
      </Field>

      <Field label="Extension source ID">
        <Input
          value={form.suwayomi_source_id ?? ''}
          onChange={(e) => setForm({ ...form, suwayomi_source_id: e.target.value.trim() })}
          placeholder="7185601298150078890"
          inputMode="numeric"
          className={INPUT}
        />
      </Field>
    </Panel>
  )
}

/** TMDB, the source of the Screens page, and where you are for it. */
function TmdbPanel({ form, setForm, stored }: TabProps & { stored: Settings }) {
  return (
    <Panel
      title="TMDB"
      icon={Clapperboard}
      note={<KeyLink href="https://www.themoviedb.org/settings/api/request" />}
    >
      <SecretField
        name="tmdb_token"
        label="API key"
        form={form}
        setForm={setForm}
        stored={stored}
      />

      <Field label="Region" hint="ISO 3166-1">
        <Input
          value={form.tmdb_region ?? ''}
          onChange={(e) => setForm({ ...form, tmdb_region: e.target.value.trim().toUpperCase() })}
          placeholder="US"
          maxLength={2}
          className={INPUT}
        />
      </Field>

      <Field label="Language" hint="IETF BCP 47">
        <Input
          value={form.tmdb_language ?? ''}
          onChange={(e) => setForm({ ...form, tmdb_language: e.target.value.trim() })}
          placeholder="en-US"
          className={INPUT}
        />
      </Field>
    </Panel>
  )
}

const RELEASE_TYPES: { value: Settings['tmdb_hidden_release_types'][number]; label: string }[] = [
  { value: 'theatrical', label: 'Cinema' },
  { value: 'digital', label: 'Digital' },
]

const hour = (value: number) => `${String(value).padStart(2, '0')}:00`

/** What Screens hides of what TMDB lists, and the genres that bring a title back. */
function ScreensTab({ form, setForm, stored }: TabProps & { stored: Settings }) {
  const ready = stored.tmdb_ready
  const movieGenres = useQuery({
    queryKey: ['screen-genres', 'movie'],
    queryFn: () => api.screenGenres('movie'),
    enabled: ready,
    staleTime: Infinity,
  })
  const tvGenres = useQuery({
    queryKey: ['screen-genres', 'tv'],
    queryFn: () => api.screenGenres('tv'),
    enabled: ready,
    staleTime: Infinity,
  })
  const languages = useQuery({
    queryKey: ['screen-languages'],
    queryFn: api.screenLanguages,
    enabled: ready,
    staleTime: Infinity,
  })
  const unreachable = !ready ? 'Add the TMDB API key first.' : null
  const movieOptions = movieGenres.data?.map((g) => ({ value: String(g.id), label: g.name }))
  const tvOptions = tvGenres.data?.map((g) => ({ value: String(g.id), label: g.name }))
  const ids = (field: keyof Form) => ((form[field] as number[] | undefined) ?? []).map(String)
  const setIds = (field: keyof Form) => (next: string[]) =>
    setForm({ ...form, [field]: next.map(Number) })

  return (
    <>
      <SettingsGroup title="Filters" icon={ListFilter}>
        <Panel
          title="Language"
          icon={Languages}
          note={
            <>
              Select <Lit>only</Lit> the languages <Lit>you want to show</Lit>
            </>
          }
        >
          <Field label="Original languages">
            {unreachable ? (
              <p className="text-xs text-ink-faint">{unreachable}</p>
            ) : (
              <LanguageFilter
                languages={languages.data ?? []}
                hidden={form.tmdb_hidden_languages ?? []}
                onChange={(tmdb_hidden_languages) => setForm({ ...form, tmdb_hidden_languages })}
              />
            )}
          </Field>
        </Panel>

        <Panel
          title="Always hide"
          icon={EyeOff}
          note={
            <>
              Select what you <Lit>never want to show</Lit>
            </>
          }
        >
          <Field label="Movie genres">
            <FilterSelect
              unreachable={unreachable}
              options={movieOptions}
              selected={ids('tmdb_hidden_movie_genres')}
              onChange={setIds('tmdb_hidden_movie_genres')}
            />
          </Field>
          <Field label="TV genres">
            <FilterSelect
              unreachable={unreachable}
              options={tvOptions}
              selected={ids('tmdb_hidden_tv_genres')}
              onChange={setIds('tmdb_hidden_tv_genres')}
            />
          </Field>

          <Field label="Release types">
            <FilterSelect
              unreachable={null}
              options={RELEASE_TYPES}
              selected={form.tmdb_hidden_release_types ?? []}
              onChange={(next) =>
                setForm({
                  ...form,
                  tmdb_hidden_release_types: next as Settings['tmdb_hidden_release_types'],
                })
              }
            />
          </Field>
          <MakerFields category="screens" mode="hide" />
        </Panel>

        <Panel
          title="Always show"
          icon={Eye}
          note={
            <>
              Select what you <Lit>always</Lit> want to show{' '}
              <Lit>when it is paired to something you hide</Lit>
            </>
          }
        >
          <Field label="Movie genres">
            <FilterSelect
              unreachable={unreachable}
              options={movieOptions}
              selected={ids('tmdb_shown_movie_genres')}
              onChange={setIds('tmdb_shown_movie_genres')}
            />
          </Field>
          <Field label="TV genres">
            <FilterSelect
              unreachable={unreachable}
              options={tvOptions}
              selected={ids('tmdb_shown_tv_genres')}
              onChange={setIds('tmdb_shown_tv_genres')}
            />
          </Field>
          <MakerFields category="screens" mode="show" />
        </Panel>
      </SettingsGroup>

      <SettingsGroup title="General" icon={SlidersHorizontal}>
        <NotificationsPanel category="screens" form={form} setForm={setForm} stored={stored} />
        <FavouritesPanel category="screens" form={form} setForm={setForm} />
      </SettingsGroup>

      <SourceGroups category="screens" form={form} setForm={setForm} stored={stored} />
    </>
  )
}

const ARR = {
  radarr: { icon: Film, placeholder: 'http://radarr:7878', added: 'Add monitored movies' },
  sonarr: { icon: Tv, placeholder: 'http://sonarr:8989', added: 'Add monitored shows' },
} as const

/**
 * Radarr or Sonarr: where a title is added, under which quality profile and root folder, and
 * whether monitoring one adds it. A profile of 0 and an empty root are the first it lists.
 */
function ArrPanel({ app, form, setForm, stored }: TabProps & { app: Arr; stored: Settings }) {
  const ready = stored[`${app}_ready`]
  const profiles = useQuery({
    queryKey: ['arr-profiles', app],
    queryFn: () => api.arrProfiles(app),
    retry: false,
    enabled: ready,
  })
  const folders = useQuery({
    queryKey: ['arr-folders', app],
    queryFn: () => api.arrFolders(app),
    retry: false,
    enabled: ready,
  })
  const set = (patch: Form) => setForm({ ...form, ...patch })
  const profile = form[`${app}_profile_id`] || profiles.data?.[0]?.id
  const root = form[`${app}_root`] || folders.data?.[0]
  const { icon, placeholder, added } = ARR[app]

  return (
    <Panel title={LIBRARY_NAME[app]} icon={icon}>
      <Field label="Instance URL">
        <Input
          value={form[`${app}_url`] ?? ''}
          onChange={(e) => set({ [`${app}_url`]: e.target.value })}
          placeholder={placeholder}
          className={INPUT}
        />
      </Field>

      <SecretField
        name={`${app}_api_key`}
        label="API key"
        form={form}
        setForm={setForm}
        stored={stored}
      />

      {ready ? (
        <>
          <Field label="Quality profile">
            <Select
              value={profile ? String(profile) : undefined}
              onValueChange={(id) => set({ [`${app}_profile_id`]: Number(id) })}
              disabled={!profiles.data?.length}
            >
              <SelectTrigger className="w-full border-line bg-base">
                <SelectValue
                  placeholder={profiles.isError ? `${LIBRARY_NAME[app]} unreachable.` : undefined}
                />
              </SelectTrigger>
              <SelectContent>
                {profiles.data?.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Root folder">
            <Select
              value={root}
              onValueChange={(path) => set({ [`${app}_root`]: path })}
              disabled={!folders.data?.length}
            >
              <SelectTrigger className="w-full border-line bg-base">
                <SelectValue
                  placeholder={folders.isError ? `${LIBRARY_NAME[app]} unreachable.` : undefined}
                />
              </SelectTrigger>
              <SelectContent>
                {folders.data?.map((path) => (
                  <SelectItem key={path} value={path}>
                    {path}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label={added}>
            <Toggle
              id={`${app}-add`}
              on={form[`${app}_add`] ?? false}
              onChange={(on) => set({ [`${app}_add`]: on })}
            />
          </Field>
        </>
      ) : (
        <NotYet label="Quality profile and root folder" />
      )}
    </Panel>
  )
}

/** Hardcover, the source of the Books page, what it hides, and where notices go. */
function BooksTab({ form, setForm, stored }: TabProps & { stored: Settings }) {
  const ready = stored.hardcover_ready
  const genres = useQuery({
    queryKey: ['book-genres'],
    queryFn: api.bookGenres,
    enabled: ready,
    staleTime: Infinity,
  })
  const categories = (form.books_hidden_categories ?? []).map(String)
  const types = (form.books_hidden_literary_types ?? []).map(String)
  const unreachable = !ready ? 'Add the Hardcover API key first.' : null
  const genreOptions = (genres.data ?? []).map((g) => ({ value: g.slug, label: g.name }))

  return (
    <>
      <SettingsGroup title="Filters" icon={ListFilter}>
        <Panel
          title="Always hide"
          icon={EyeOff}
          note={
            <>
              Select what you <Lit>never want to show</Lit>
            </>
          }
        >
          <Field label="Kind">
            <FilterSelect
              unreachable={null}
              options={LITERARY_TYPES}
              selected={types}
              onChange={(next) =>
                setForm({ ...form, books_hidden_literary_types: next.map(Number) })
              }
            />
          </Field>

          <Field
            label="Categories"
            action={
              <SelectAll
                options={BOOK_CATEGORIES.map((c) => c.value)}
                selected={categories}
                onChange={(next) => setForm({ ...form, books_hidden_categories: next.map(Number) })}
              />
            }
          >
            <FilterSelect
              unreachable={null}
              options={BOOK_CATEGORIES}
              selected={categories}
              onChange={(next) => setForm({ ...form, books_hidden_categories: next.map(Number) })}
            />
          </Field>

          <Field label="Genres">
            <FilterSelect
              unreachable={unreachable}
              options={genreOptions}
              selected={form.books_hidden_genres ?? []}
              onChange={(books_hidden_genres) => setForm({ ...form, books_hidden_genres })}
            />
          </Field>
          <MakerFields category="books" mode="hide" />
        </Panel>

        <Panel
          title="Always show"
          icon={Eye}
          note={
            <>
              Select what you <Lit>always</Lit> want to show{' '}
              <Lit>when it is paired to something you hide</Lit>
            </>
          }
        >
          <Field label="Genres">
            <FilterSelect
              unreachable={unreachable}
              options={genreOptions}
              selected={form.books_shown_genres ?? []}
              onChange={(books_shown_genres) => setForm({ ...form, books_shown_genres })}
            />
          </Field>
          <MakerFields category="books" mode="show" />
        </Panel>
      </SettingsGroup>

      <SettingsGroup title="General" icon={SlidersHorizontal}>
        <NotificationsPanel category="books" form={form} setForm={setForm} stored={stored} />
        <FavouritesPanel category="books" form={form} setForm={setForm} />
      </SettingsGroup>

      <SourceGroups category="books" form={form} setForm={setForm} stored={stored} />
    </>
  )
}

/** Opens Hardcover's new key form with the scopes Robin uses already ticked. */
const HARDCOVER_NEW_KEY =
  'https://hardcover.app/account/api/keys/new?scope=read:catalog+read:me+read:library+write:library'

const LITERARY_TYPES = [
  { value: '1', label: 'Fiction' },
  { value: '2', label: 'Nonfiction' },
]

// Hardcover's book categories, by id.
const BOOK_CATEGORIES = [
  { value: '1', label: 'Book' },
  { value: '2', label: 'Novella' },
  { value: '3', label: 'Short story' },
  { value: '4', label: 'Graphic novel' },
  { value: '5', label: 'Fan fiction' },
  { value: '6', label: 'Research paper' },
  { value: '7', label: 'Poetry' },
  { value: '8', label: 'Collection' },
  { value: '9', label: 'Web novel' },
  { value: '10', label: 'Light novel' },
]

/** Selects every option at once, or clears them once all are selected. */
function SelectAll({
  options,
  selected,
  onChange,
}: {
  options: string[] | undefined
  selected: string[]
  onChange: (next: string[]) => void
}) {
  if (!options?.length) return null
  const all = options.every((option) => selected.includes(option))
  return (
    <button
      type="button"
      onClick={() => onChange(all ? [] : options)}
      className={cn(controlClass(), 'h-6 px-2 text-2xs')}
    >
      {all ? <X className="size-3" /> : <CheckCheck className="size-3" />}
      {all ? 'Clear' : 'Select all'}
    </button>
  )
}

/**
 * The languages to see, every one while none is picked. Kept as the ones hidden, every other,
 * which is what the rest of Robin reads.
 */
function LanguageFilter({
  languages,
  hidden,
  onChange,
}: {
  languages: { code: string; name: string }[]
  hidden: string[]
  onChange: (hidden: string[]) => void
}) {
  const all = languages.map((l) => l.code)
  const shown = hidden.length ? all.filter((code) => !hidden.includes(code)) : []
  return (
    <FilterSelect
      unreachable={null}
      options={languages.map((l) => ({ value: l.code, label: l.name }))}
      selected={shown}
      onChange={(next) => onChange(next.length ? all.filter((code) => !next.includes(code)) : [])}
    />
  )
}

/**
 * What releases come from, always hidden or always shown as `mode` says, a field per kind of
 * the category: what is in it lit, a click taking it off, and a search of the source to add.
 * A pick is kept at once, as from a favourite's dialog.
 */
function MakerFields({ category, mode }: { category: FavouriteCategory; mode: MakerMode }) {
  const queryClient = useQueryClient()
  const makers = (useMakerFilters().data ?? []).filter(
    (m) => m.category === category && m.mode === mode,
  )
  const change = useMutation({
    mutationFn: async (pick: { kind: FavouriteKind; id: number } | { remove: number }) => {
      if ('remove' in pick) await api.unfilterMaker(pick.remove)
      else await api.filterMaker(mode, category, pick.kind, pick.id)
    },
    onError: failed,
    onSettled: () => void queryClient.invalidateQueries(),
  })
  return KINDS[category].map((kind) => {
    const picked = makers.filter((m) => m.kind === kind)
    return (
      <Field key={kind} label={KIND_LABEL[kind]}>
        <div className="flex flex-wrap items-center gap-2">
          {picked.map((maker) => (
            <button
              key={maker.id}
              type="button"
              disabled={change.isPending}
              onClick={() => change.mutate({ remove: maker.id })}
              className={controlClass(true)}
            >
              {maker.name}
              <X className="size-3" />
            </button>
          ))}
          <MakerSearch
            category={category}
            kind={kind}
            picked={picked.map((m) => m.source_id)}
            onPick={({ id }) => change.mutate({ kind, id })}
          />
        </div>
      </Field>
    )
  })
}

/**
 * The source searched for one kind of maker, in a popover that stays open while picks are made.
 * It asks once typing pauses, and offers makers whatever filters already hold them.
 */
function MakerSearch({
  category,
  kind,
  picked,
  onPick,
}: {
  category: FavouriteCategory
  kind: FavouriteKind
  picked: number[]
  onPick: (entity: { id: number; name: string }) => void
}) {
  const [term, setTerm] = useState('')
  const [asked, setAsked] = useState('')
  useEffect(() => {
    const wait = setTimeout(() => setAsked(term.trim()), 350)
    return () => clearTimeout(wait)
  }, [term])
  const found = useQuery({
    queryKey: ['maker-search', category, asked, kind],
    queryFn: () => api.searchFavourites(category, asked, true, kind),
    enabled: asked.length >= 2,
    staleTime: 10 * 60_000,
  })
  const listed = (found.data ?? []).filter((e) => e.kind === kind)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className={controlClass()}>
          <Plus className="size-3.5" />
          Select
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Search" value={term} onValueChange={setTerm} />
          <CommandList>
            {found.isFetching ? (
              <div className="flex justify-center py-4">
                <Spinner className="size-4 text-ink-dim" />
              </div>
            ) : asked.length >= 2 ? (
              <CommandEmpty>Nothing matches.</CommandEmpty>
            ) : null}
            <CommandGroup>
              {listed.map((entity) => (
                <CommandItem
                  key={entity.id}
                  value={String(entity.id)}
                  onSelect={() => (picked.includes(entity.id) ? null : onPick(entity))}
                >
                  <Check
                    className={cn(
                      'size-3.5',
                      picked.includes(entity.id) ? 'text-accent' : 'invisible',
                    )}
                  />
                  <span className="min-w-0 truncate">{entity.name}</span>
                  <span className="ml-auto shrink-0 text-2xs text-ink-faint">{entity.meta}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

/** Words in a panel's note that carry its rule, in accent. */
function Lit({ children }: { children: React.ReactNode }) {
  return <span className="font-medium text-accent">{children}</span>
}

/**
 * Some of a list, searched for in a popover that stays open while values are ticked. What is
 * picked is on beside it, a click taking it off.
 */
function FilterSelect({
  options,
  unreachable,
  selected,
  onChange,
}: {
  options: { value: string; label: string }[] | undefined
  unreachable: string | null
  selected: string[]
  onChange: (next: string[]) => void
}) {
  if (unreachable) return <p className="text-xs text-ink-faint">{unreachable}</p>
  const named = (value: string) => options?.find((o) => o.value === value)?.label ?? value
  const toggle = (value: string) =>
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value])
  return (
    <div className="flex flex-wrap items-center gap-2">
      {selected.map((value) => (
        <button
          key={value}
          type="button"
          onClick={() => toggle(value)}
          className={controlClass(true)}
        >
          {named(value)}
          <X className="size-3" />
        </button>
      ))}
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" className={controlClass()}>
            <Plus className="size-3.5" />
            Select
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-64 p-0">
          <Command>
            <CommandInput placeholder="Search" />
            <CommandList>
              <CommandEmpty>Nothing matches.</CommandEmpty>
              <CommandGroup>
                {options?.map((option) => (
                  <CommandItem
                    key={option.value}
                    value={option.label}
                    onSelect={() => toggle(option.value)}
                  >
                    <Check
                      className={cn(
                        'size-3.5',
                        selected.includes(option.value) ? 'text-accent' : 'invisible',
                      )}
                    />
                    {option.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  )
}

function ComicsTab({ form, setForm, stored }: TabProps & { stored: Settings }) {
  return (
    <>
      <SettingsGroup title="Filters" icon={ListFilter}>
        <Panel
          title="Always hide"
          icon={EyeOff}
          note={
            <>
              Select what you <Lit>never want to show</Lit>
            </>
          }
        >
          <MakerFields category="comics" mode="hide" />
        </Panel>

        <Panel
          title="Always show"
          icon={Eye}
          note={
            <>
              Select what you <Lit>always</Lit> want to show{' '}
              <Lit>when it is paired to something you hide</Lit>
            </>
          }
        >
          <MakerFields category="comics" mode="show" />
        </Panel>
      </SettingsGroup>

      <SettingsGroup title="General" icon={SlidersHorizontal}>
        <NotificationsPanel category="comics" form={form} setForm={setForm} stored={stored} />
        <Panel
          title="Weekly digest"
          icon={Newspaper}
          note={
            <>
              Select the publishers whose #1s it names, <Lit>every one</Lit> while none is selected
            </>
          }
        >
          <Field label="Publishers">
            <DigestPublishers
              picked={form.comics_digest_publishers ?? []}
              onChange={(comics_digest_publishers) =>
                setForm({ ...form, comics_digest_publishers })
              }
            />
          </Field>
        </Panel>
        <FavouritesPanel category="comics" form={form} setForm={setForm} />
      </SettingsGroup>

      <SourceGroups category="comics" form={form} setForm={setForm} stored={stored} />
    </>
  )
}

/** Metron publishers, searched as a favourite's are, kept with their names. */
function DigestPublishers({
  picked,
  onChange,
}: {
  picked: { id: number; name: string }[]
  onChange: (next: { id: number; name: string }[]) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {picked.map((publisher) => (
        <button
          key={publisher.id}
          type="button"
          onClick={() => onChange(picked.filter((p) => p.id !== publisher.id))}
          className={controlClass(true)}
        >
          {publisher.name}
          <X className="size-3" />
        </button>
      ))}
      <MakerSearch
        category="comics"
        kind="publisher"
        picked={picked.map((p) => p.id)}
        onPick={({ id, name }) => onChange([...picked, { id, name }])}
      />
    </div>
  )
}

/** Each category's notifications, as Settings names them. */
const NOTICE_FIELDS = {
  games: { on: 'games_notify', schedule: 'games_schedule', quiet: 'games_quiet' },
  comics: { on: 'comics_notify', schedule: 'comics_schedule', quiet: 'comics_quiet' },
  screens: { on: 'screen_notify', schedule: 'screen_schedule', quiet: 'screen_quiet' },
  books: { on: 'books_notify', schedule: 'books_schedule', quiet: 'books_quiet' },
} as const satisfies Record<
  Category,
  { on: KeyOf<boolean>; schedule: KeyOf<Notice[]>; quiet: KeyOf<number[]> }
>

/**
 * A category's notifications, the same panel in every tab: its switch, where on each
 * destination they land, when a dated one goes out, its quiet hours, and a test sent there.
 * Destinations are set under General.
 */
function NotificationsPanel({
  category,
  form,
  setForm,
  stored,
}: TabProps & { category: Category; stored: Settings }) {
  const fields = NOTICE_FIELDS[category]
  const destinations = form.notify_destinations ?? []
  const test = useMutation({
    mutationFn: () => api.testNotify(destinations, category),
    onSuccess: (result) =>
      result.ok
        ? toast.success('Notification sent', { description: result.detail })
        : toast.error('Not delivered', { description: result.detail }),
    onError: (error: unknown) =>
      toast.error('Not delivered', { description: errorText(error, 'Unknown error') }),
  })
  const on = form[fields.on] ?? true

  return (
    <Panel
      title="Notifications"
      icon={Bell}
      note={stored.notify_ready ? 'Server time' : say('Add a destination under {general} first')}
    >
      <Field label="Send">
        <Toggle
          id={`${category}-notify`}
          on={on}
          onChange={(next) => setForm({ ...form, [fields.on]: next })}
        />
      </Field>

      <CategoryPlaces category={category} form={form} setForm={setForm} />

      <Field label="Schedule">
        <ScheduleRows
          value={form[fields.schedule] ?? []}
          onChange={(next) => setForm({ ...form, [fields.schedule]: next })}
        />
      </Field>

      <Field label="Quiet hours">
        <QuietHours
          id={`${category}-quiet`}
          value={form[fields.quiet] ?? []}
          onChange={(next) => setForm({ ...form, [fields.quiet]: next })}
        />
      </Field>

      <div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => test.mutate()}
          disabled={test.isPending || !destinations.length || !on}
        >
          {test.isPending ? <Spinner className="size-3.5" /> : <Bell className="size-3.5" />}
          Send a test
        </Button>
      </div>
    </Panel>
  )
}

const HOURS = Array.from({ length: 24 }, (_, value) => value)

// The most notices a schedule holds, and how far ahead one goes, as the API allows.
const MOST_NOTICES = 10
const MOST_DAYS = 30

function HourSelect({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (value: number) => void
}) {
  return (
    <Select value={String(value)} onValueChange={(next) => onChange(Number(next))}>
      <SelectTrigger
        size="sm"
        aria-label={label}
        className="border-line bg-base text-xs tabular-nums data-[size=sm]:h-7"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {HOURS.map((value) => (
          <SelectItem key={value} value={String(value)}>
            {hour(value)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/**
 * When a dated notice goes out, as a calendar sets its notifications: the day before, always
 * there and first, then any added, each some days or weeks before at an hour.
 */
function ScheduleRows({
  value,
  onChange,
}: {
  value: Notice[]
  onChange: (next: Notice[]) => void
}) {
  const at = value.findIndex((notice) => notice.days === 1)
  const rows =
    at < 0 ? [{ days: 1, hour: 9 }, ...value] : [value[at], ...value.filter((_, i) => i !== at)]
  const set = (index: number, next: Notice) =>
    onChange(rows.map((row, i) => (i === index ? next : row)))

  return (
    <div className="space-y-2">
      {rows.map((row, index) => {
        const weeks = row.days > 0 && row.days % 7 === 0
        const unit = weeks ? 7 : 1
        const count = row.days / unit
        return (
          <div key={index} className="flex flex-wrap items-center gap-2 text-xs text-ink-dim">
            {index === 0 ? (
              <span className="text-ink">1 day before</span>
            ) : (
              <>
                <Input
                  type="number"
                  aria-label="How many"
                  min={0}
                  max={MOST_DAYS / unit}
                  value={count}
                  onChange={(e) =>
                    set(index, {
                      ...row,
                      days: Math.min(MOST_DAYS, Math.max(0, Number(e.target.value) || 0) * unit),
                    })
                  }
                  className={cn(INPUT, 'h-7 w-16 text-xs tabular-nums')}
                />
                <Select
                  value={weeks ? 'weeks' : 'days'}
                  onValueChange={(next) =>
                    set(index, {
                      ...row,
                      days: Math.min(MOST_DAYS, count * (next === 'weeks' ? 7 : 1)),
                    })
                  }
                >
                  <SelectTrigger
                    size="sm"
                    aria-label="Unit"
                    className="border-line bg-base text-xs data-[size=sm]:h-7"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="days">{count === 1 ? 'day' : 'days'}</SelectItem>
                    <SelectItem value="weeks">{count === 1 ? 'week' : 'weeks'}</SelectItem>
                  </SelectContent>
                </Select>
                <span>before</span>
              </>
            )}
            <span>at</span>
            <HourSelect
              label="Hour"
              value={row.hour}
              onChange={(hour) => set(index, { ...row, hour })}
            />
            {index > 0 ? (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Remove"
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
                className="text-ink-faint hover:text-bad"
              >
                <X className="size-3.5" />
              </Button>
            ) : null}
          </div>
        )
      })}
      <button
        type="button"
        onClick={() => onChange([...rows, { days: 7, hour: rows[0].hour }])}
        disabled={rows.length >= MOST_NOTICES}
        className={controlClass()}
      >
        <Plus className="size-3.5" />
        Add notification
      </button>
    </div>
  )
}

/** Hours a notice is held back, delivered when they end. Empty is none. */
function QuietHours({
  id,
  value,
  onChange,
}: {
  id: string
  value: number[]
  onChange: (next: number[]) => void
}) {
  const on = value.length === 2
  return (
    <div className="flex flex-wrap items-center gap-2.5 text-xs text-ink-dim">
      <Switch id={id} checked={on} onCheckedChange={(next) => onChange(next ? [22, 7] : [])} />
      {on ? (
        <>
          <span>From</span>
          <HourSelect
            label="Start"
            value={value[0]}
            onChange={(start) => onChange([start, value[1]])}
          />
          <span>to</span>
          <HourSelect label="End" value={value[1]} onChange={(end) => onChange([value[0], end])} />
        </>
      ) : (
        <Label htmlFor={id} className="text-xs font-normal text-ink-dim">
          Disabled
        </Label>
      )}
    </div>
  )
}

/** How a category treats a favourite's new releases, as Settings names the switches. */
const FAVOURITE_FIELDS = {
  games: { announce: 'games_favourites', monitor: 'games_favourites_monitor' },
  comics: { announce: 'comics_favourites', monitor: 'comics_favourites_monitor' },
  screens: { announce: 'screen_favourites', monitor: 'screen_favourites_monitor' },
  books: { announce: 'books_favourites', monitor: 'books_favourites_monitor' },
} as const satisfies Record<
  FavouriteCategory,
  { announce: KeyOf<boolean>; monitor: KeyOf<boolean> }
>

function FavouritesPanel({ category, form, setForm }: TabProps & { category: FavouriteCategory }) {
  const fields = FAVOURITE_FIELDS[category]
  return (
    <Panel title="Favourites" icon={Star}>
      <Field label="Automatically announce">
        <Toggle
          id={`${category}-favourites-announce`}
          on={form[fields.announce] ?? true}
          onChange={(on) => setForm({ ...form, [fields.announce]: on })}
        />
      </Field>
      <Field label="Automatically monitor">
        <Toggle
          id={`${category}-favourites-monitor`}
          on={form[fields.monitor] ?? false}
          onChange={(on) => setForm({ ...form, [fields.monitor]: on })}
        />
      </Field>
    </Panel>
  )
}

/** Setup tags every panel Optional, since Robin runs without any of them. */
const OptionalPanels = createContext(false)

function Panel({
  title,
  icon,
  note,
  children,
}: {
  title: string
  icon: LucideIcon
  note?: React.ReactNode
  children: React.ReactNode
}) {
  const optional = useContext(OptionalPanels)
  return (
    <Section
      title={
        optional ? (
          <>
            {title}
            <ReleaseTag tag="Optional" className="ml-2" />
          </>
        ) : (
          title
        )
      }
      icon={icon}
      note={note}
    >
      <PanelBody className="space-y-5">{children}</PanelBody>
    </Section>
  )
}

function Toggle({
  id,
  on,
  onChange,
}: {
  id: string
  on: boolean
  onChange: (on: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Switch id={id} checked={on} onCheckedChange={onChange} />
      <Label htmlFor={id} className="text-xs font-normal text-ink-dim">
        {on ? 'Enabled' : 'Disabled'}
      </Label>
    </div>
  )
}

/** Pick some of a list of indexers, or none of them to mean all. */
function IndexerToggles({
  items,
  unreachable,
  selected,
  onChange,
}: {
  items: NamedThing[] | undefined
  unreachable: string | null
  selected: number[]
  onChange: (next: number[]) => void
}) {
  if (unreachable) return <p className="text-xs text-ink-faint">{unreachable}</p>

  return (
    <ToggleGroup
      type="multiple"
      spacing={2}
      className="flex-wrap"
      value={selected.map(String)}
      onValueChange={(next) => onChange(next.map(Number))}
    >
      {items?.map((indexer) => (
        <ToggleGroupItem
          key={indexer.id}
          value={String(indexer.id)}
          className={controlClass(selected.includes(indexer.id))}
        >
          {indexer.name}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

function Result({ label, health }: { label: string; health: ServiceHealth }) {
  const faulty = health.state === 'faulty'
  return (
    <Alert
      variant={faulty ? 'destructive' : 'default'}
      className={cn('rounded-card border-line bg-surface shadow-raised', faulty && 'border-bad/40')}
    >
      <AlertTitle>{label}</AlertTitle>
      <AlertDescription>
        <HealthWord health={health} />
      </AlertDescription>
    </Alert>
  )
}
/**
 * Every integration whose category's source is set, under its category, as the health check
 * shows it. A card opens the integration's panel, and saving it checks it again.
 */
function SetupIntegrations(props: StoredProps) {
  const client = useQueryClient()
  const [open, setOpen] = useState<IntegrationKey | null>(null)
  const health = useQuery({
    queryKey: ['health', 'setup'],
    queryFn: () => api.health(true),
    staleTime: 0,
  })
  const save = useMutation({
    mutationFn: () => api.saveSettings(props.form),
    onSuccess: async () => {
      setOpen(null)
      await client.invalidateQueries({ queryKey: ['settings'] })
      await health.refetch()
    },
    onError: (error: unknown) =>
      toast.error('Could not save', { description: errorText(error, 'Unknown error') }),
  })
  const groups = (Object.keys(SOURCES) as Category[])
    .filter((category) => props.stored[SOURCES[category].ready])
    .map((category) => ({
      key: category,
      ...CATEGORY_TABS[category],
      entries: integrationsOf(category),
    }))
    .filter((group) => group.entries.length)
  const Open = open ? INTEGRATIONS[open].Panel : null
  let i = 0

  if (!health.data) return <Spinner className="mx-auto size-8 text-ink-dim" />
  return (
    <div className="space-y-10">
      {groups.map(({ key, label: title, icon: Icon, entries }) => (
        <section key={key}>
          <Rise i={i++} className="mb-4 flex items-center justify-center gap-2.5">
            <Icon className="size-4 text-ink-faint" />
            <h2 className="text-lg font-semibold tracking-tight text-ink">{title}</h2>
          </Rise>
          <div className="flex flex-wrap justify-center gap-3">
            {entries.map(([name]) => (
              <Rise key={name} i={i++} className="sm:max-w-72">
                <button
                  type="button"
                  onClick={() => setOpen(name)}
                  className="block w-full rounded-card text-left transition-transform hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                >
                  <Result label={SERVICE_LABELS[name]} health={health.data[name]} />
                </button>
              </Rise>
            ))}
          </div>
        </section>
      ))}
      <Dialog open={open !== null} onOpenChange={(next) => (next ? null : setOpen(null))}>
        <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto border-0 bg-transparent p-0 shadow-none sm:max-w-md">
          <DialogTitle className="sr-only">{open ? SERVICE_LABELS[open] : ''}</DialogTitle>
          {Open ? <Open {...props} /> : null}
          {open ? <TestRow service={open} form={props.form} /> : null}
          <div className="flex justify-center">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? <Spinner className="size-4" /> : <Save className="size-4" />}
              Save
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/**
 * A pick that only appears once its service is set, named until then, so it is not missed. In
 * setup, whose integrations alone set `OptionalPanels`, a test sets it.
 */
function NotYet({ label }: { label: string }) {
  const setup = useContext(OptionalPanels)
  return (
    <Field label={label}>
      <p className="text-xs text-ink-faint">{setup ? 'Test to pick' : 'Save to pick'}</p>
    </Field>
  )
}

/**
 * Save what was entered and check `service` at once, so what appears once it is set appears
 * where it was entered. The result is setup's health check too.
 */
function TestRow({ service, form }: { service: keyof Health; form: Form }) {
  const client = useQueryClient()
  const test = useMutation({
    mutationFn: async () => {
      await api.saveSettings(form)
      await client.invalidateQueries({ queryKey: ['settings'] })
      return api.health(true)
    },
    onSuccess: (health) => client.setQueryData(['health', 'setup'], health),
    onError: failed,
  })
  return (
    <div className="flex flex-wrap items-center justify-center gap-3">
      <Button variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
        {test.isPending ? <Spinner className="size-4" /> : <PlugZap className="size-4" />}
        Test
      </Button>
      {test.data ? <HealthWord health={test.data[service]} /> : null}
    </div>
  )
}

/** A category's source on its own, and what is missing without it. */
function SourceStep({ category, ...props }: StoredProps & { category: Category }) {
  const { Panel: Source, data, key } = SOURCES[category]
  return (
    <>
      <Rise i={0}>
        <Source {...props} />
      </Rise>
      <p className="mt-4 text-center text-xs text-ink-faint">
        If you do not set this up, you will not get {data} data
      </p>
      <div className="mt-6">
        <TestRow service={key} form={props.form} />
      </div>
    </>
  )
}

/** A setup step: its title over its body, slid in from the side it was moved to. */
function StepFrame({
  title,
  width,
  back = false,
  children,
}: {
  title: string
  width: string
  back?: boolean
  children: React.ReactNode
}) {
  return (
    <div data-back={back || undefined} className={cn('slide-in w-full', width)}>
      <h1 className="mb-8 text-center text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      {children}
    </div>
  )
}

/** Rises into place after the `i` before it. */
function Rise({
  i,
  className = 'max-w-md',
  children,
}: {
  i: number
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn('rise w-full', className)} style={riseAt(i)}>
      {children}
    </div>
  )
}

type Step = {
  slug: string
  label: string
  title: string
  icon: LucideIcon
  width: string
  Body: React.ComponentType<StoredProps>
}

/** Required: setup moves past it only once a test from it arrived. */
const NOTIFICATIONS: Step = {
  slug: 'notifications',
  label: 'Notifications',
  title: 'Where do you want to be notified?',
  icon: Bell,
  width: 'max-w-md',
  Body: DestinationsPanel,
}

// Where an install that finished setup without a destination opens, that step alone.
const NOTIFICATIONS_ONLY = 'notifications-only'

const SETUP: Step[] = [
  {
    slug: 'restore',
    label: 'Restore',
    title: 'Hatched a new Robin?',
    icon: Database,
    width: 'max-w-md',
    Body: RestoreStep,
  },
  {
    slug: 'species',
    label: 'Species',
    title: 'Pick your Robin species',
    icon: Palette,
    width: 'max-w-4xl',
    Body: SpeciesPicker,
  },
  NOTIFICATIONS,
  ...(Object.keys(SOURCES) as Category[]).map((category) => {
    const { label, icon } = CATEGORY_TABS[category]
    const Body = (props: StoredProps) => <SourceStep category={category} {...props} />
    const title = SOURCES[category].question
    return { slug: category, label, title, icon, width: 'max-w-md', Body }
  }),
  {
    slug: 'integrations',
    label: 'Integrations',
    title: 'Integrations',
    icon: Blocks,
    width: 'max-w-5xl',
    Body: SetupIntegrations,
  },
]

/**
 * Shown once on a fresh install after the one-time password is replaced. The step is kept on
 * the account, so a reload opens where it was left. Moving on saves what was entered, Skip
 * drops it. Nothing moves past Notifications, Skip and Finish later included, until a test
 * from it arrived.
 */
export function Setup({ step }: { step: string }) {
  const client = useQueryClient()
  const { theme } = useTheme()
  const { settings, form, setForm } = useSettingsForm()
  // Which way the last move went, so the step slides in from that side.
  const [back, setBack] = useState(false)
  const [proven, setProven] = useState(false)
  const steps = step === NOTIFICATIONS_ONLY ? [NOTIFICATIONS] : SETUP
  const at = Math.max(
    0,
    steps.findIndex((s) => s.slug === step),
  )
  const current = steps[at]
  const last = at === steps.length - 1
  // Short of a test that arrived, nothing past Notifications opens.
  const gate = steps.indexOf(NOTIFICATIONS)
  const held = !proven && at <= gate
  const blocked = (to: number | null) => held && (to === null || to > gate)
  const go = useMutation({
    mutationFn: async ({ to, keep }: { to: number | null; keep: boolean }) => {
      const stored = settings.data
      if (keep && stored && JSON.stringify(form) !== JSON.stringify(editable(stored))) {
        await api.saveSettings(form)
      }
      await api.setupStep(to === null ? null : steps[to].slug)
    },
    onSuccess: (_, { to, keep }) => {
      if (!keep && settings.data) setForm(editable(settings.data))
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'me' })
      client.setQueryData<Me>(
        ['me'],
        (me) => me && { ...me, setup: to === null ? null : steps[to].slug },
      )
    },
    onError: (error: unknown) =>
      toast.error('Could not save', { description: errorText(error, 'Unknown error') }),
  })
  const move = (to: number | null, keep = true) => {
    setBack(to !== null && to < at)
    go.mutate({ to, keep })
  }

  const { Body } = current
  const body = settings.data ? <Body form={form} setForm={setForm} stored={settings.data} /> : null

  return (
    <div className="flex min-h-svh flex-col items-center bg-base px-4 py-10 sm:py-14">
      <header className="rise flex flex-col items-center gap-3">
        <img key={theme} src={logo(theme)} alt="" className="pop size-16" />
        <span className="text-2xl font-semibold tracking-tight text-ink">Robin</span>
      </header>

      <nav
        className={cn('mt-8 flex flex-wrap justify-center gap-1', steps.length === 1 && 'hidden')}
        aria-label="Setup"
      >
        {steps.map(({ slug, label, icon: Icon }, i) => (
          <button
            key={slug}
            type="button"
            aria-label={label}
            aria-current={i === at ? 'step' : undefined}
            onClick={() => move(i)}
            disabled={go.isPending || blocked(i)}
            className={controlClass(i === at)}
          >
            <Icon className="size-3.5" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </nav>
      {steps.length > 1 ? (
        <div className="mt-4 h-0.5 w-full max-w-md overflow-hidden rounded-full bg-line">
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
            style={{ width: `${(at / (steps.length - 1)) * 100}%` }}
          />
        </div>
      ) : null}

      <main className="mt-10 flex w-full justify-center">
        <StepFrame key={current.slug} title={current.title} width={current.width} back={back}>
          <OptionalPanels.Provider value={current.slug === 'integrations'}>
            <Proven.Provider value={() => setProven(true)}>{body}</Proven.Provider>
          </OptionalPanels.Provider>
        </StepFrame>
      </main>

      <footer className="mt-10 flex flex-wrap items-center justify-center gap-3">
        {at > 0 ? (
          <Button variant="outline" onClick={() => move(at - 1)} disabled={go.isPending}>
            <ChevronLeft className="size-4" />
            Back
          </Button>
        ) : null}
        {last || current === NOTIFICATIONS ? null : (
          <Button
            variant="ghost"
            onClick={() => move(at + 1, false)}
            disabled={go.isPending || blocked(at + 1)}
          >
            Skip
          </Button>
        )}
        <Button
          onClick={() => move(last ? null : at + 1)}
          disabled={go.isPending || blocked(last ? null : at + 1)}
        >
          {go.isPending ? <Spinner className="size-4" /> : <ChevronRight className="size-4" />}
          {last ? 'Open Robin' : 'Next'}
        </Button>
      </footer>
      {last || held ? null : (
        <Button
          variant="link"
          size="sm"
          className="mt-3 text-ink-faint"
          onClick={() => move(null)}
          disabled={go.isPending}
        >
          Finish later
        </Button>
      )}
    </div>
  )
}
