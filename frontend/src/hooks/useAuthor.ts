import { createContext, useContext, useSyncExternalStore } from 'react';

import { readStoredAuthor, subscribeAuthor } from '../lib/author';

/** The current author name (localStorage "mdt.author"), or null if unset. */
export function useAuthor(): string | null {
  return useSyncExternalStore(subscribeAuthor, readStoredAuthor, () => null);
}

/** Opens the "Who are you?" modal; provided by the app layout. */
export const AuthorModalContext = createContext<() => void>(() => undefined);

export const useOpenAuthorModal = (): (() => void) => useContext(AuthorModalContext);
