import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { type CountdownTarget, api, errorText } from '@/lib/api'
import { isoDay } from '@/lib/utils'

export function useCountdowns() {
  return useQuery({ queryKey: ['countdowns'], queryFn: api.countdowns })
}

/**
 * Counting down to an item on Home. One with no release day, or out already, is refused with
 * a toast saying so, and the API is not asked.
 */
export function useAddCountdown() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (target: CountdownTarget) => {
      if (!target.date) throw new Error('No release date')
      if (target.date < isoDay(new Date())) throw new Error('Already out')
      return api.addCountdown(target)
    },
    onSuccess: (made) => toast.success(`Counting down to ${made.title}`),
    onError: (error: unknown) =>
      toast.error('Cannot count down', {
        description: errorText(error) ?? (error instanceof Error ? error.message : undefined),
      }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['countdowns'] }),
  })
}
