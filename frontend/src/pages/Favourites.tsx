import { Star } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { FavouriteMenu } from '@/components/ItemMenus'
import { Items } from '@/components/MediaCard'
import {
  Control,
  Group,
  Notice,
  Options,
  Page,
  PageHeader,
  Section,
  Sections,
  Segmented,
  ViewSwitch,
} from '@/components/Page'
import { Spinner } from '@/components/ui/spinner'
import type { Favourite, FavouriteCategory } from '@/lib/api'
import { CATEGORY, useShown } from '@/lib/categories'
import { asView, usePageControls } from '@/lib/controls'
import { KINDS, KIND_ICON, KIND_LABEL, favouriteParam, useFavourites } from '@/lib/favourites'
import { favouriteItem } from '@/lib/items'
import { withParam } from '@/lib/params'

/** Every favourite, a group per category and a panel per kind. The filter is `?type=`. */
export function Favourites() {
  const [params] = useSearchParams()
  const favourites = useFavourites()
  const shown = useShown()
  const controls = usePageControls('favourites', { view: 'cover', type: 'all' })
  const view = asView(controls.values.view, 'cover')

  const categories = (Object.keys(KINDS) as FavouriteCategory[]).filter(shown)
  const of = (category: FavouriteCategory) =>
    (favourites.data ?? []).filter((f) => f.category === category)
  const only = categories.find((c) => c === controls.values.type) ?? null
  const listed = categories.filter((c) => (only ? c === only : of(c).length > 0))

  const item = (f: Favourite) => {
    const entity = { category: f.category, kind: f.kind, id: f.source_id, url: null }
    return {
      ...favouriteItem(f, withParam(params, 'favourite', favouriteParam(entity))),
      menu: <FavouriteMenu entity={entity} />,
    }
  }

  return (
    <Page>
      <PageHeader title="Favourites" icon={Star}>
        <Options controls={controls}>
          <ViewSwitch value={view} onChange={(next) => controls.set({ view: next })} />
          <Control label="Category">
            <Segmented
              label="Category"
              options={[
                { value: 'all', label: 'All', count: favourites.data?.length ?? 0 },
                ...categories.map((c) => ({
                  value: c,
                  label: CATEGORY[c].label,
                  icon: CATEGORY[c].icon,
                  count: of(c).length,
                })),
              ]}
              value={only ?? 'all'}
              onChange={(type) => controls.set({ type })}
            />
          </Control>
        </Options>
      </PageHeader>

      {favourites.isPending ? (
        <Spinner className="m-10 size-8 text-ink-dim" />
      ) : listed.every((c) => !of(c).length) ? (
        <Notice>No favourites yet.</Notice>
      ) : (
        <div className="space-y-12">
          {listed.map((category) => (
            <Group
              key={category}
              title={CATEGORY[category].label}
              icon={CATEGORY[category].icon}
              count={of(category).length}
            >
              <Sections>
                {KINDS[category].map((kind) => {
                  const items = of(category).filter((f) => f.kind === kind)
                  return items.length ? (
                    <Section
                      key={kind}
                      title={KIND_LABEL[kind]}
                      icon={KIND_ICON[kind]}
                      count={items.length}
                    >
                      <Items items={items.map(item)} view={view} />
                    </Section>
                  ) : null
                })}
              </Sections>
            </Group>
          ))}
        </div>
      )}
    </Page>
  )
}
