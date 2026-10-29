// TanStack Query hooks, query keys (docs/UI.md §6) and the invalidation rules
// after writes. Writes never retry; conflicts surface as ConflictError.
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from '@tanstack/react-query';

import { canonicalQuery, type SearchRecord } from '../lib/query-string';
import { apiGet, apiWrite } from './client';
import type {
  BulkRequest,
  BulkResponse,
  ChangeFeedResponse,
  CommentFeedResponse,
  CommentNoteRequest,
  CommentResponse,
  CommentStatusResponse,
  CommentThreadsQuery,
  CommentThreadsResponse,
  CommentVersionRequest,
  CreateCommentRequest,
  CreateRequest,
  CreateResponse,
  DeleteRequest,
  DeleteResponse,
  DiffResponse,
  EditCommentRequest,
  EntityType,
  FacetsResponse,
  ItemResponse,
  ListResponse,
  Meta,
  PatchRequest,
  PatchResponse,
  RecordType,
  RestoreCommentRequest,
  RestorePreviewResponse,
  RestoreRequest,
  RestoreResponse,
  RevisionAuthorsResponse,
  RevisionByIdResponse,
  RevisionListResponse,
  RevisionResponse,
  StatsResponse,
  UndeleteRequest,
  UndeleteResponse,
  VerifyFieldRequest,
  VerifyFieldResponse,
  VocabResponse,
} from './types';

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const queryKeys = {
  meta: ['meta'] as const,
  vocab: ['vocab'] as const,
  stats: ['stats'] as const,
  lists: ['list'] as const,
  listsOf: (type: EntityType) => ['list', type] as const,
  /** `qs`: canonical list query without `cols` and detail-page parameters. */
  list: (type: EntityType, qs: string) => ['list', type, qs] as const,
  facets: ['facets'] as const,
  facetsOf: (type: EntityType) => ['facets', type] as const,
  /** `qs`: additionally without `f.<field>`, `page`, `page_size`, `sort`. */
  facet: (type: EntityType, field: string, qs: string) => ['facets', type, field, qs] as const,
  items: ['item'] as const,
  itemsOf: (type: EntityType) => ['item', type] as const,
  item: (type: EntityType, id: string) => ['item', type, id] as const,
  revisionsOf: (type: RecordType) => ['revisions', type] as const,
  /** Entity and comment histories share this prefix (type `comment`). */
  revisions: (type: RecordType, id: string) => ['revisions', type, id] as const,
  comments: ['comments'] as const,
  commentsOf: (subjectId: string) => ['comments', subjectId] as const,
  changes: ['changes'] as const,
  changeFeed: (qs: string) => ['changes', qs] as const,
  lookups: ['lookup'] as const,
  lookup: (qs: string) => ['lookup', qs] as const,
};

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const entityPath = (type: EntityType, id?: string): string =>
  id === undefined ? `/api/entities/${type}` : `/api/entities/${type}/${encodeURIComponent(id)}`;

/** Base path of a record that has a history (entities and comments). */
const recordPath = (type: RecordType, id: string): string =>
  type === 'comment' ? `/api/comments/${encodeURIComponent(id)}` : entityPath(type, id);

const queryOf = (params: Record<string, string | number | null | undefined>): string =>
  canonicalQuery(
    Object.fromEntries(
      Object.entries(params).flatMap(([key, value]) =>
        value === null || value === undefined || value === '' ? [] : [[key, String(value)]],
      ),
    ),
  );

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

const SLOW_CHANGING = 5 * 60_000;

export function useMeta() {
  return useQuery({
    queryKey: queryKeys.meta,
    queryFn: ({ signal }) => apiGet<Meta>('/api/meta', '', signal),
    staleTime: SLOW_CHANGING,
  });
}

export function useVocab() {
  return useQuery({
    queryKey: queryKeys.vocab,
    queryFn: ({ signal }) => apiGet<VocabResponse>('/api/vocab', '', signal),
    staleTime: SLOW_CHANGING,
  });
}

export function useStats() {
  return useQuery({
    queryKey: queryKeys.stats,
    queryFn: ({ signal }) => apiGet<StatsResponse>('/api/stats', '', signal),
  });
}

interface ListOptions {
  enabled?: boolean;
  /** Keep showing the previous page while the next one loads (tables). */
  keepPrevious?: boolean;
}

/** `qs` is the canonical list query (lib/query-string listQueryString). */
export function useEntityList(type: EntityType, qs: string, options: ListOptions = {}) {
  return useQuery({
    queryKey: queryKeys.list(type, qs),
    queryFn: ({ signal }) => apiGet<ListResponse>(entityPath(type), qs, signal),
    enabled: options.enabled ?? true,
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
  });
}

/** Facet counts; `qs` from facetQueryString. Loaded lazily (`enabled` when a popover opens). */
export function useFacets(type: EntityType, field: string, qs: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.facet(type, field, qs),
    queryFn: ({ signal }) =>
      apiGet<FacetsResponse>(`${entityPath(type)}/facets`, canonicalQuery({ ...Object.fromEntries(new URLSearchParams(qs)), field }), signal),
    enabled,
  });
}

interface EntityOptions {
  enabled?: boolean;
  /** `'always'` refetches on mount even if the cache looks fresh (e.g. after a 409). */
  refetchOnMount?: boolean | 'always';
}

export function useEntity(type: EntityType, id: string, options: EntityOptions = {}) {
  return useQuery({
    queryKey: queryKeys.item(type, id),
    queryFn: ({ signal }) => apiGet<ItemResponse>(entityPath(type, id), '', signal),
    enabled: options.enabled ?? true,
    refetchOnMount: options.refetchOnMount ?? true,
  });
}

export function useRevisions(type: RecordType, id: string, page = 1, pageSize = 50) {
  return useQuery({
    queryKey: [...queryKeys.revisions(type, id), 'page', page, pageSize],
    queryFn: ({ signal }) =>
      apiGet<RevisionListResponse>(`${recordPath(type, id)}/revisions`, queryOf({ page, page_size: pageSize }), signal),
  });
}

export function useRevision(type: RecordType, id: string, version: number | null) {
  return useQuery({
    queryKey: [...queryKeys.revisions(type, id), 'version', version],
    queryFn: ({ signal }) => apiGet<RevisionResponse>(`${recordPath(type, id)}/revisions/${version ?? 0}`, '', signal),
    enabled: version !== null,
  });
}

/** Diff between two versions; `from` is the older side, 0 = before creation. */
export function useDiff(type: RecordType, id: string, from: number | null, to: number | null) {
  return useQuery({
    queryKey: [...queryKeys.revisions(type, id), 'diff', from, to],
    queryFn: ({ signal }) => apiGet<DiffResponse>(`${recordPath(type, id)}/diff`, queryOf({ from, to }), signal),
    enabled: from !== null && to !== null,
  });
}

export function useCommentThreads(subjectId: string, query: CommentThreadsQuery = {}) {
  const qs = queryOf({ subject_id: subjectId, status: query.status, field: query.field, deleted: query.deleted });
  return useQuery({
    queryKey: [...queryKeys.commentsOf(subjectId), qs],
    queryFn: ({ signal }) => apiGet<CommentThreadsResponse>('/api/comments', qs, signal),
  });
}

/** Thread feed without subject (CommentsPage, trash): `status, entity_type, author, q, deleted, page, page_size`. */
export function useCommentFeed(search: SearchRecord) {
  const qs = canonicalQuery(search);
  return useQuery({
    queryKey: [...queryKeys.comments, 'feed', qs],
    queryFn: ({ signal }) => apiGet<CommentFeedResponse>('/api/comments', qs, signal),
    placeholderData: keepPreviousData,
  });
}

export function useComment(id: string) {
  return useQuery({
    queryKey: [...queryKeys.comments, 'comment', id],
    queryFn: ({ signal }) => apiGet<CommentResponse>(recordPath('comment', id), '', signal),
  });
}

/** Recent changes: `author, entity_type, channel, action, since, until, entity_id, batch_id, page, page_size`. */
export function useChangeFeed(search: SearchRecord, options: ListOptions = {}) {
  const qs = canonicalQuery(search);
  return useQuery({
    queryKey: queryKeys.changeFeed(qs),
    queryFn: ({ signal }) => apiGet<ChangeFeedResponse>('/api/revisions', qs, signal),
    enabled: options.enabled ?? true,
    placeholderData: (options.keepPrevious ?? true) ? keepPreviousData : undefined,
  });
}

export function useRevisionById(revisionId: number | null) {
  return useQuery({
    queryKey: [...queryKeys.changes, 'revision', revisionId],
    queryFn: ({ signal }) => apiGet<RevisionByIdResponse>(`/api/revisions/${revisionId ?? 0}`, '', signal),
    enabled: revisionId !== null,
    staleTime: Infinity,
  });
}

export function useRevisionAuthors() {
  return useQuery({
    queryKey: [...queryKeys.changes, 'authors'],
    queryFn: ({ signal }) => apiGet<RevisionAuthorsResponse>('/api/revisions/authors', '', signal),
  });
}

/** Saved views of one table type, by name. */
export function useSavedViews(entityType: EntityType) {
  return useEntityList('saved_view', canonicalQuery({ 'f.entity_type': `eq:${entityType}`, sort: 'name', page_size: '500' }));
}

// ---------------------------------------------------------------------------
// Invalidation after writes (docs/UI.md §6)
// ---------------------------------------------------------------------------

export interface WriteScope {
  type: RecordType;
  id?: string | undefined;
  /** A cascading delete or undelete touches dependent rows of other types. */
  cascade?: boolean | undefined;
  /** For comments: the subject whose counts changed. */
  subject?: { type: RecordType; id: string } | undefined;
}

/** Query-key prefixes to invalidate after a successful write. */
export function keysAfterWrite(scope: WriteScope): QueryKey[] {
  const keys: QueryKey[] = [queryKeys.stats, queryKeys.changes, queryKeys.lookups];
  const { type, id, subject } = scope;

  if (type === 'comment') {
    keys.push(queryKeys.comments);
    if (id) keys.push(queryKeys.revisions('comment', id));
    if (subject && subject.type !== 'comment') {
      keys.push(queryKeys.item(subject.type, subject.id), queryKeys.listsOf(subject.type));
      if (subject.type === 'vocabulary_term') keys.push(queryKeys.vocab);
    }
    return keys;
  }

  keys.push(queryKeys.listsOf(type), queryKeys.facetsOf(type));
  keys.push(id ? queryKeys.item(type, id) : queryKeys.itemsOf(type));
  keys.push(id ? queryKeys.revisions(type, id) : queryKeys.revisionsOf(type));

  // Events and the focal organisation's participations feed the derived
  // values of projects and services (docs/DATA_MODEL.md §8.1).
  if (type === 'event' || type === 'participation') {
    for (const derivedType of ['project', 'service'] as const) {
      keys.push(queryKeys.itemsOf(derivedType), queryKeys.listsOf(derivedType), queryKeys.facetsOf(derivedType));
    }
  }
  if (type === 'vocabulary_term') {
    keys.push(queryKeys.vocab, queryKeys.meta, queryKeys.lists, queryKeys.facets, queryKeys.items);
  }
  if (scope.cascade) keys.push(queryKeys.lists, queryKeys.facets, queryKeys.items);
  return keys;
}

export async function invalidateAfterWrite(client: QueryClient, scope: WriteScope): Promise<void> {
  await Promise.all(keysAfterWrite(scope).map((queryKey) => client.invalidateQueries({ queryKey })));
}

function useWrite<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
  scope: ((variables: TVariables, result: TResult) => WriteScope) | null,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (result, variables) => (scope ? invalidateAfterWrite(client, scope(variables, result)) : undefined),
  });
}

// ---------------------------------------------------------------------------
// Entity writes (docs/API.md §3.2)
// ---------------------------------------------------------------------------

export type WithId<T> = T & { id: string };

export function useCreateEntity(type: EntityType) {
  return useWrite(
    (body: CreateRequest) => apiWrite<CreateResponse>('POST', entityPath(type), body),
    (_body, result) => ({ type, id: result.item.id }),
  );
}

export function usePatchEntity(type: EntityType) {
  return useWrite(
    ({ id, ...body }: WithId<PatchRequest>) => apiWrite<PatchResponse>('PATCH', entityPath(type, id), body),
    ({ id }) => ({ type, id }),
  );
}

export function useDeleteEntity(type: EntityType) {
  return useWrite(
    ({ id, ...body }: WithId<DeleteRequest>) => apiWrite<DeleteResponse>('POST', `${entityPath(type, id)}/delete`, body),
    ({ id, cascade }) => ({ type, id, cascade }),
  );
}

export function useUndeleteEntity(type: EntityType) {
  return useWrite(
    ({ id, ...body }: WithId<UndeleteRequest>) =>
      apiWrite<UndeleteResponse>('POST', `${entityPath(type, id)}/undelete`, body),
    ({ id, cascade }) => ({ type, id, cascade }),
  );
}

export function useVerifyField(type: EntityType) {
  return useWrite(
    ({ id, ...body }: WithId<VerifyFieldRequest>) =>
      apiWrite<VerifyFieldResponse>('POST', `${entityPath(type, id)}/verify-field`, body),
    ({ id }) => ({ type, id }),
  );
}

/** Restore preview (`dry_run: true`): computes the changes, writes nothing. */
export function useRestorePreview(type: EntityType) {
  return useWrite(
    ({ id, ...body }: WithId<Omit<RestoreRequest, 'dry_run' | 'note'>>) =>
      apiWrite<RestorePreviewResponse>('POST', `${entityPath(type, id)}/restore`, { ...body, dry_run: true }),
    null,
  );
}

export function useRestoreEntity(type: EntityType) {
  return useWrite(
    ({ id, ...body }: WithId<Omit<RestoreRequest, 'dry_run'>>) =>
      apiWrite<RestoreResponse>('POST', `${entityPath(type, id)}/restore`, { ...body, dry_run: false }),
    ({ id }) => ({ type, id }),
  );
}

/** Bulk edit: per-row results; rows of the type are invalidated as a whole. */
export function useBulkEdit(type: EntityType) {
  return useWrite(
    (body: BulkRequest) => apiWrite<BulkResponse>('POST', `${entityPath(type)}/bulk`, body),
    () => ({ type }),
  );
}

// ---------------------------------------------------------------------------
// Comment writes (docs/API.md §3.3)
// ---------------------------------------------------------------------------

const commentScope = (commentId: string, subjectId: string, subjectType: RecordType | null): WriteScope => ({
  type: 'comment',
  id: commentId,
  subject: subjectType ? { type: subjectType, id: subjectId } : undefined,
});

/**
 * `subjectType` comes from the server response (`comment.subject_type`), so
 * callers only pass IDs.
 */
export function useCreateComment() {
  return useWrite(
    (body: CreateCommentRequest) => apiWrite<CommentResponse>('POST', '/api/comments', body),
    (_body, { comment }) => commentScope(comment.id, comment.subject_id, comment.subject_type),
  );
}

export function useEditComment() {
  return useWrite(
    ({ id, ...body }: WithId<EditCommentRequest>) => apiWrite<CommentResponse>('PATCH', recordPath('comment', id), body),
    (_vars, { comment }) => commentScope(comment.id, comment.subject_id, comment.subject_type),
  );
}

function useCommentStatus(action: 'resolve' | 'reopen') {
  return useWrite(
    ({ id, ...body }: WithId<CommentVersionRequest>) =>
      apiWrite<CommentStatusResponse>('POST', `${recordPath('comment', id)}/${action}`, body),
    (_vars, { comment }) => commentScope(comment.id, comment.subject_id, comment.subject_type),
  );
}

export const useResolveComment = () => useCommentStatus('resolve');
export const useReopenComment = () => useCommentStatus('reopen');

function useCommentDeletion(action: 'delete' | 'undelete') {
  return useWrite(
    ({ id, ...body }: WithId<CommentNoteRequest>) =>
      apiWrite<CommentResponse>('POST', `${recordPath('comment', id)}/${action}`, body),
    (_vars, { comment }) => commentScope(comment.id, comment.subject_id, comment.subject_type),
  );
}

export const useDeleteComment = () => useCommentDeletion('delete');
export const useUndeleteComment = () => useCommentDeletion('undelete');

export function useRestoreComment() {
  return useWrite(
    ({ id, ...body }: WithId<RestoreCommentRequest>) =>
      apiWrite<CommentResponse>('POST', `${recordPath('comment', id)}/restore`, body),
    (_vars, { comment }) => commentScope(comment.id, comment.subject_id, comment.subject_type),
  );
}
