import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, House, LogOut, type LucideIcon, ScrollText, Settings2, Star } from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'

import { SearchBar } from '@/components/SearchBar'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar'
import { type Settings, api, signedOut } from '@/lib/api'
import { CATEGORIES, useSettings } from '@/lib/categories'
import { logo, useTheme } from '@/lib/theme'

type Entry = {
  to: string
  label: string
  icon: LucideIcon
  /** Active only on this exact path, not on the pages under it. */
  end: boolean
  /** The integration it needs. The entry is left out while that is unset. */
  needs?: (settings: Settings) => boolean
}

/** Home, then one entry per category, then what spans every category. */
const GROUPS: Entry[][] = [
  [{ to: '/', label: 'Home', icon: House, end: true }],
  CATEGORIES.map((c) => ({
    to: c.to,
    label: c.label,
    icon: c.icon,
    end: false,
    needs: c.ready,
  })),
  [
    { to: '/monitored', label: 'Monitored', icon: Eye, end: false },
    { to: '/favourites', label: 'Favourites', icon: Star, end: false },
    { to: '/logs', label: 'Logs', icon: ScrollText, end: false },
    { to: '/settings', label: 'Settings', icon: Settings2, end: false },
  ],
]

function isActive(pathname: string, entry: Entry): boolean {
  return entry.end ? pathname === entry.to : pathname.startsWith(entry.to)
}

/** The active entry keeps its icon in accent, the one mark of where you are. */
const ACTIVE = 'data-[active=true]:font-medium data-[active=true]:[&>svg]:text-accent'

function Links() {
  const { pathname } = useLocation()
  const { isMobile, setOpenMobile } = useSidebar()
  // On a phone the sidebar is a sheet over the page, so following a link closes it.
  const close = () => (isMobile ? setOpenMobile(false) : undefined)
  const settings = useSettings()
  const shown = (entry: Entry) =>
    !entry.needs || (settings.data ? entry.needs(settings.data) : false)

  // A group with nothing shown, the categories before any is set up, is left out whole.
  const groups = GROUPS.map((group) => group.filter(shown)).filter((group) => group.length)
  return groups.map((group, g) => (
    <div key={g}>
      {/* The separator forces full width under its margin, which made the sidebar scroll. */}
      {g > 0 ? <SidebarSeparator className="data-[orientation=horizontal]:w-auto" /> : null}
      <SidebarGroup>
        <SidebarGroupContent>
          <SidebarMenu>
            {group.map((entry) => {
              return (
                <SidebarMenuItem key={entry.to}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(pathname, entry)}
                    tooltip={entry.label}
                    className={ACTIVE}
                  >
                    <NavLink to={entry.to} end={entry.end} onClick={close}>
                      <entry.icon />
                      <span>{entry.label}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )
            })}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </div>
  ))
}

function SignOut() {
  const client = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  if (!me.data) return null
  return (
    <SidebarFooter>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            tooltip="Sign out"
            className="text-ink-dim"
            onClick={() => void api.logout().finally(() => signedOut(client))}
          >
            <LogOut className="size-4 text-ink-faint" />
            <span>Sign out</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      <p className="px-2 font-mono text-2xs text-ink-faint group-data-[collapsible=icon]:hidden">
        v{me.data.version}
      </p>
    </SidebarFooter>
  )
}

/**
 * The app frame: the shadcn sidebar, collapsible to its icons on a wide screen and a sheet on
 * a phone, then the page with the search bar above it. Only the trigger in the header hides
 * it, there is no rail to drag. Whether it is collapsed is kept in a cookie by the provider.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  const { theme } = useTheme()
  return (
    <SidebarProvider>
      <Sidebar collapsible="icon" className="shadow-raised">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton asChild size="lg" tooltip="Robin" className="h-16">
                <NavLink to="/">
                  <img
                    src={logo(theme)}
                    alt=""
                    className="size-12 shrink-0 group-data-[collapsible=icon]:size-8"
                  />
                  <span className="flex flex-col items-start gap-0.5">
                    <span className="text-xl leading-none font-semibold tracking-tight text-ink">
                      Robin
                    </span>
                    <span className="rounded-sm bg-accent/12 px-1.5 py-px text-2xs font-semibold tracking-wider text-accent">
                      CHIRP ♫
                    </span>
                  </span>
                </NavLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent className="overflow-x-hidden">
          <Links />
        </SidebarContent>
        <SignOut />
      </Sidebar>

      <SidebarInset className="min-w-0 bg-base">
        <header className="sticky top-0 z-30 border-b border-line bg-base/85 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
            <SidebarTrigger className="text-ink-dim hover:text-ink" />
            <SearchBar />
          </div>
        </header>
        <main className="pb-10">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}
