// Manual documents (docs/API.md §7.8): fetch a URL into a snapshot, then
// create the document from an upload or a fetched snapshot.
import type {
  FetchDocumentResponse,
  ManualDocumentRequest,
  ManualDocumentResponse,
} from './acquisition-types';
import { apiWrite } from './client';
import { keysAfterDocumentAdded, useMutationWithKeys } from './queries';

/** POST /api/documents/fetch: stores a snapshot (no curated data yet). */
export function useFetchDocument() {
  return useMutationWithKeys(
    ({ url }: { url: string }) => apiWrite<FetchDocumentResponse>('POST', '/api/documents/fetch', { url }),
    null,
  );
}

/** POST /api/documents/manual: the new document. */
export function useCreateManualDocument() {
  return useMutationWithKeys(
    (body: ManualDocumentRequest) => apiWrite<ManualDocumentResponse>('POST', '/api/documents/manual', body),
    () => keysAfterDocumentAdded(),
  );
}
