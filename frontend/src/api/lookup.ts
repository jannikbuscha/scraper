// GET /api/lookup (docs/API.md §3.1): label search for pickers and the global
// search, and labels for IDs taken from a shared URL.
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { canonicalQuery, EMPTY_TOKEN, type SearchRecord } from '../lib/query-string';
import { apiGet } from './client';
import { queryKeys } from './queries';
import type { LookupItem, LookupResponse, RecordType } from './types';

export interface LookupSearch {
  q: string;
  types: readonly RecordType[];
  limit?: number;
  /** Optional per-type `f.` filters, e.g. `{'f.project_id': 'in:prj_…'}`. */
  filters?: SearchRecord;
}

export function lookupSearchQuery({ q, types, limit = 20, filters = {} }: LookupSearch): string {
  return canonicalQuery({ ...filters, q: q.trim(), types: types.join(','), limit: String(limit) });
}

/** Searches labels; idle until `q` has at least `minChars` characters. */
export function useLookupSearch(search: LookupSearch, minChars = 1) {
  const qs = lookupSearchQuery(search);
  return useQuery({
    queryKey: queryKeys.lookup(qs),
    queryFn: ({ signal }) => apiGet<LookupResponse>('/api/lookup', qs, signal),
    enabled: search.q.trim().length >= minChars && search.types.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

/** Labels for IDs (deleted ones included, unknown ones omitted). */
export function useLookupIds(ids: readonly string[]) {
  const unique = [...new Set(ids.filter((id) => id !== '' && id !== EMPTY_TOKEN))].sort();
  const qs = canonicalQuery({ ids: unique.join(',') });
  const query = useQuery({
    queryKey: queryKeys.lookup(qs),
    queryFn: ({ signal }) => apiGet<LookupResponse>('/api/lookup', qs, signal),
    enabled: unique.length > 0,
    staleTime: 60_000,
  });
  const byId = new Map<string, LookupItem>((query.data?.items ?? []).map((item) => [item.id, item]));
  return { ...query, byId };
}
