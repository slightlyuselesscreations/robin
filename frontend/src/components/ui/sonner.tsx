import { CircleCheckIcon, OctagonXIcon, TriangleAlertIcon } from 'lucide-react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'

import { Spinner } from '@/components/ui/spinner'
import { useTheme } from '@/lib/theme'

// Sonner colours its descriptions and buttons by its own theme, so it follows Robin's scheme.
const Toaster = ({ ...props }: ToasterProps) => {
  const { scheme } = useTheme()
  return (
    <Sonner
      theme={scheme}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Spinner className="size-4" />,
      }}
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
          '--border-radius': 'var(--radius)',
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
