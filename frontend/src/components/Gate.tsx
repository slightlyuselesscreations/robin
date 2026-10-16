import type { LucideIcon } from 'lucide-react'

import { Notice, Page, PageHeader } from '@/components/Page'
import type { Category, Settings } from '@/lib/api'
import { CATEGORY, useSettings } from '@/lib/categories'
import { say } from '@/lib/say'

/**
 * A page that needs a source or an integration. While it is unset the page says so, naming
 * where it is set through `say`, and asks nothing of the API, so an unset service is never an error.
 */
export function Gate({
  title,
  icon,
  ready,
  off,
  children,
}: {
  /** The page's own title and icon, so its header reads as it will once it is set. */
  title: string
  icon: LucideIcon
  ready: (settings: Settings) => boolean
  off: string
  children: React.ReactNode
}) {
  const { data } = useSettings()
  if (!data) return null
  if (ready(data)) return children
  return (
    <Page>
      <PageHeader title={title} icon={icon} />
      <Notice>{say(off)}</Notice>
    </Page>
  )
}

/** A category's page, shown once its data source is set. */
export function CategoryGate({
  category,
  children,
}: {
  category: Category
  children: React.ReactNode
}) {
  const { label, icon, ready, off } = CATEGORY[category]
  return (
    <Gate title={label} icon={icon} ready={ready} off={off}>
      {children}
    </Gate>
  )
}
