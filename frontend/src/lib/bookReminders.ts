import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { type Book, type BookReminder, api, errorText } from '@/lib/api'
import { bookRemindersOf } from '@/lib/items'
import { useNoticeSet } from '@/lib/reminders'

/**
 * The reminder on one book, and setting or removing it. `ready` is false while Books
 * notifications are off, and nothing offers Monitor then. A series is followed by favouriting
 * it instead.
 */
export function useBookReminders(book: Pick<Book, 'id'>) {
  return useNoticeSet<BookReminder, boolean>({
    ready: (s) => s.books_notices_ready,
    queryKey: 'book-reminders',
    list: api.bookReminders,
    of: (rows) => bookRemindersOf(book, rows),
    apply: async (mine, on) => {
      if (on && !mine.length) await api.remindBook({ book_id: book.id })
      if (!on) for (const reminder of mine) await api.removeBookReminder(reminder.id)
      return on
    },
  })
}

/** Whether the book is on the user's Want to Read shelf on Hardcover, and changing that. */
export function useShelf(id: number, enabled = true) {
  const queryClient = useQueryClient()
  const shelf = useQuery({
    queryKey: ['book-shelf', id],
    queryFn: () => api.bookShelf(id),
    enabled,
  })
  const set = useMutation({
    mutationFn: (want: boolean) => api.setBookShelf(id, want),
    onSuccess: (result) => {
      queryClient.setQueryData(['book-shelf', id], result)
      toast.success(result.want ? 'Added to Want to Read' : 'Taken off Want to Read')
    },
    onError: (error: unknown) =>
      toast.error('Could not change the shelf', {
        description: errorText(error),
      }),
  })
  return { want: shelf.data?.want ?? false, loaded: shelf.isSuccess, set }
}
