import { cn } from '@/lib/utils'

/**
 * The loading mark: a robin in flight, wings beating. Drawn in the current text colour so it
 * reads inside a filled button as well as on the page. The motion lives in `index.css`.
 */
function Spinner({ className, ...props }: React.ComponentProps<'svg'>) {
  return (
    <svg
      role="status"
      aria-label="Loading"
      viewBox="0 0 24 24"
      fill="currentColor"
      className={cn('robin-loader size-4 shrink-0', className)}
      {...props}
    >
      <path d="M2.5 13.6 7.8 12.4C10.6 10.4 13.6 10.3 16.2 11.4 18.6 12.4 19.3 14.6 17.6 16.2 15.6 18 11.6 18.3 7.8 16.4Z" />
      <circle cx="17.8" cy="10.4" r="3.1" />
      <path d="M20.7 9.6 23.4 10.5 20.7 11.3Z" />
      <path className="robin-wing" d="M13.6 12.4 6.4 4.6C9.6 5 13.2 7.6 15.6 11.6Z" />
    </svg>
  )
}

export { Spinner }
