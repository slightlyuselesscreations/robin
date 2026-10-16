import { REGEXP_ONLY_DIGITS } from 'input-otp'

import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp'

const SLOTS = [0, 1, 2, 3, 4, 5]

/** Six digits from an authenticator app. The id lands on the real input, for its label. */
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
    <InputOTP
      id={id}
      maxLength={SLOTS.length}
      pattern={REGEXP_ONLY_DIGITS}
      value={value}
      onChange={onChange}
      autoComplete="one-time-code"
      autoFocus={autoFocus}
    >
      <InputOTPGroup>
        {SLOTS.map((index) => (
          <InputOTPSlot key={index} index={index} />
        ))}
      </InputOTPGroup>
    </InputOTP>
  )
}
