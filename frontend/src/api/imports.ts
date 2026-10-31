// Imports (docs/API.md §7.9): preview and dry run write nothing; the run
// writes on channel `import` and is stored with its result.
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { canonicalQuery, type SearchRecord } from '../lib/query-string';
import type {
  ImportDryRunRequest,
  ImportListResponse,
  ImportPreview,
  ImportPreviewRequest,
  ImportRun,
  ImportRunRequest,
  ImportRunResponse,
  Plan,
} from './acquisition-types';
import { apiGet, apiWrite } from './client';
import { keysAfterImport, queryKeys, useMutationWithKeys } from './queries';

/** The import history, newest first: `page, page_size`. */
export function useImports(search: SearchRecord) {
  const qs = canonicalQuery(search);
  return useQuery({
    queryKey: queryKeys.importList(qs),
    queryFn: ({ signal }) => apiGet<ImportListResponse>('/api/imports', qs, signal),
    placeholderData: keepPreviousData,
  });
}

/** One stored import with its errors and conflicts (loaded when a history row expands). */
export function useImport(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.importRun(id),
    queryFn: ({ signal }) => apiGet<{ import: ImportRun }>(`/api/imports/${encodeURIComponent(id)}`, '', signal),
    enabled,
  });
}

/** POST /api/imports/preview: writes nothing. */
export function usePreviewImport() {
  return useMutationWithKeys(
    (body: ImportPreviewRequest) => apiWrite<ImportPreview>('POST', '/api/imports/preview', body),
    null,
  );
}

/** POST /api/imports/dry-run: the plan; writes nothing. */
export function useDryRunImport() {
  return useMutationWithKeys(
    (body: ImportDryRunRequest) => apiWrite<{ plan: Plan }>('POST', '/api/imports/dry-run', body),
    null,
  );
}

/** POST /api/imports: writes row by row and stores the import run. */
export function useRunImport() {
  return useMutationWithKeys(
    (body: ImportRunRequest) => apiWrite<ImportRunResponse>('POST', '/api/imports', body),
    (body) => keysAfterImport(body.entity_type),
  );
}
