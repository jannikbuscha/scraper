// GET /api/lookup (docs/API.md §3.1): label search for pickers and the global
// search, and labels for IDs taken from a shared URL.
import { keepPreviousData, useQueries, useQuery } from '@tanstack/react-query';

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

/**
 * IDs per `?ids=` request. An ID takes about 33 characters of the URL, so the
 * 500 records of an import plan would make a URL of about 16 kB, longer than
 * many proxies accept (nginx's default limit is 8 kB); longer lists are looked
 * up in several requests.
 */
export const LOOKUP_IDS_PER_REQUEST = 100;

/** Labels for IDs (deleted ones included, unknown ones omitted). */
export function useLookupIds(ids: readonly string[]) {
  const unique = [...new Set(ids.filter((id) => id !== '' && id !== EMPTY_TOKEN))].sort();
  const chunks: string[][] = [];
  for (let start = 0; start < unique.length; start += LOOKUP_IDS_PER_REQUEST) {
    chunks.push(unique.slice(start, start + LOOKUP_IDS_PER_REQUEST));
  }
  return useQueries({
    queries: chunks.map((chunk) => {
      const qs = canonicalQuery({ ids: chunk.join(',') });
      return {
        queryKey: queryKeys.lookup(qs),
        queryFn: ({ signal }: { signal: AbortSignal }) => apiGet<LookupResponse>('/api/lookup', qs, signal),
        staleTime: 60_000,
      };
    }),
    combine: (results) => ({
      byId: new Map<string, LookupItem>(results.flatMap((result) => result.data?.items ?? []).map((item) => [item.id, item])),
      isPending: results.some((result) => result.isPending),
      isError: results.some((result) => result.isError),
    }),
  });
}
