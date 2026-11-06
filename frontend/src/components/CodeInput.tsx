import { Input } from '@/components/ui/input'
import { INPUT, cn } from '@/lib/utils'

/** Six digits from an authenticator app. */
export function CodeInput({
  id,
  value,
  onChange,
  autoFocus,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  autoFocus?: boolean
}) {
  return (
    <Input
      id={id}
      inputMode="numeric"
      autoComplete="one-time-code"
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, 6))}
      autoFocus={autoFocus}
      className={cn(INPUT, 'font-mono tracking-widest')}
    />
  )
}
