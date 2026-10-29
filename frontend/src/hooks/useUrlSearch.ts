// The current route's search params as a flat string record, and a setter
// that navigates within the current route (docs/UI.md §1.2).
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useCallback, useMemo } from 'react';

import type { SearchRecord } from '../lib/query-string';

export type SearchUpdate = SearchRecord | ((previous: SearchRecord) => SearchRecord);

export interface SetSearchOptions {
  /** Replace the history entry (e.g. while typing) instead of pushing one. */
  replace?: boolean;
}

/** The router's loose search type allows undefined values; drop them. */
function compact(search: Record<string, string | undefined>): SearchRecord {
  const out: SearchRecord = {};
  for (const [key, value] of Object.entries(search)) if (value !== undefined) out[key] = value;
  return out;
}

export function useUrlSearch(): [SearchRecord, (update: SearchUpdate, options?: SetSearchOptions) => void] {
  const raw = useSearch({ strict: false });
  const search = useMemo(() => compact(raw), [raw]);
  const navigate = useNavigate();
  const setSearch = useCallback(
    (update: SearchUpdate, options: SetSearchOptions = {}) => {
      void navigate({
        to: '.',
        search: (previous) => (typeof update === 'function' ? update(compact(previous)) : update),
        replace: options.replace ?? false,
      });
    },
    [navigate],
  );
  return [search, setSearch];
}
