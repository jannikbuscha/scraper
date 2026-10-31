// Fetch wrapper for /api (docs/UI.md §1.6, docs/API.md §1): JSON in and out,
// one error envelope.
import type { FetchFailedReason, MergeConflict, UnavailableReason } from './acquisition-types';
import {
  ENTITY_TYPES,
  type HasDependentsDetails,
  type JsonValue,
  type ReferenceDeletedDetails,
  type UniqueViolationDetails,
  type ValidationErrorDetails,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: JsonValue;

  /** `status` 0 marks client-side errors (no response). */
  constructor(status: number, code: string, message: string, details: JsonValue = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export const isApiError = (error: unknown, code?: string): error is ApiError =>
  error instanceof ApiError && (code === undefined || error.code === code);

// ---------------------------------------------------------------------------
// Typed access to error details (shapes from docs/API.md §1.2)
// ---------------------------------------------------------------------------

type JsonRecord = Record<string, JsonValue>;

const isRecord = (value: unknown): value is JsonRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export function validationErrors(error: unknown): ValidationErrorDetails | null {
  if (!isApiError(error, 'validation_error') || !isRecord(error.details)) return null;
  const result: ValidationErrorDetails = {};
  for (const [path, messages] of Object.entries(error.details)) {
    if (Array.isArray(messages)) result[path] = messages.filter((m): m is string => typeof m === 'string');
  }
  return result;
}

export function uniqueViolation(error: unknown): UniqueViolationDetails | null {
  if (!isApiError(error, 'unique_violation') || !isRecord(error.details)) return null;
  const { field, existing } = error.details;
  if (typeof field !== 'string' || !isRecord(existing)) return null;
  const { id, label, deleted } = existing;
  if (typeof id !== 'string') return null;
  return { field, existing: { id, label: typeof label === 'string' ? label : id, deleted: deleted === true } };
}

export function referenceDeleted(error: unknown): ReferenceDeletedDetails | null {
  if (!isApiError(error, 'reference_deleted') || !isRecord(error.details)) return null;
  const { field, id, type, label } = error.details;
  const entityType = ENTITY_TYPES.find((candidate) => candidate === type);
  if (typeof field !== 'string' || typeof id !== 'string' || entityType === undefined) return null;
  return { field, id, type: entityType, label: typeof label === 'string' ? label : id };
}

export function hasDependents(error: unknown): HasDependentsDetails | null {
  if (!isApiError(error, 'has_dependents') || !isRecord(error.details)) return null;
  const result: HasDependentsDetails = {};
  for (const [type, count] of Object.entries(error.details)) if (typeof count === 'number') result[type] = count;
  return result;
}

/** `409 invalid_state {state}`, e.g. a proposal that is no longer open or a run that has finished. */
export function invalidState(error: unknown): string | null {
  if (!isApiError(error, 'invalid_state') || !isRecord(error.details)) return null;
  return typeof error.details.state === 'string' ? error.details.state : null;
}

/** `409 run_in_progress {run_id}` (Phase 2): another collector run is running. */
export function runInProgress(error: unknown): { runId: string | null } | null {
  if (!isApiError(error, 'run_in_progress')) return null;
  const runId = isRecord(error.details) ? error.details.run_id : null;
  return { runId: typeof runId === 'string' ? runId : null };
}

/** `409 collector_unavailable {reason}` (Phase 2). */
export function collectorUnavailable(error: unknown): { reason: UnavailableReason | null } | null {
  if (!isApiError(error, 'collector_unavailable')) return null;
  const reason = isRecord(error.details) ? error.details.reason : null;
  return { reason: reason === 'disabled' || reason === 'contact_email_missing' ? reason : null };
}

/** `409 merge_conflict {conflicts}` (Phase 2, docs/DATA_MODEL.md §18). */
export function mergeConflicts(error: unknown): MergeConflict[] | null {
  if (!isApiError(error, 'merge_conflict') || !isRecord(error.details)) return null;
  const { conflicts } = error.details;
  if (!Array.isArray(conflicts)) return [];
  return conflicts.filter(isRecord).map((conflict) => ({
    kind: typeof conflict.kind === 'string' ? conflict.kind : '',
    id: typeof conflict.id === 'string' ? conflict.id : '',
    label: typeof conflict.label === 'string' ? conflict.label : '',
    message: typeof conflict.message === 'string' ? conflict.message : '',
  }));
}

const FETCH_FAILED_REASONS: readonly FetchFailedReason[] = [
  'robots_disallowed',
  'robots_unavailable',
  'blocked',
  'throttled',
  'http_error',
  'network_error',
  'too_large',
];

/** `502 fetch_failed {reason, status}` (Phase 2, manual fetches). */
export function fetchFailed(error: unknown): { reason: FetchFailedReason | null; status: number | null } | null {
  if (!isApiError(error, 'fetch_failed')) return null;
  const details = isRecord(error.details) ? error.details : {};
  const reason = FETCH_FAILED_REASONS.find((candidate) => candidate === details.reason) ?? null;
  return { reason, status: typeof details.status === 'number' ? details.status : null };
}

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

async function errorFromResponse(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON (e.g. a proxy error page).
  }
  const error = isRecord(body) ? body.error : undefined;
  if (isRecord(error) && typeof error.code === 'string') {
    const message = typeof error.message === 'string' ? error.message : response.statusText;
    return new ApiError(response.status, error.code, message, error.details ?? null);
  }
  return new ApiError(response.status, `http_${response.status}`, response.statusText || 'The request failed.');
}

export type WriteMethod = 'POST' | 'PATCH';

interface FetchOptions {
  method?: 'GET' | WriteMethod;
  body?: unknown;
  signal?: AbortSignal | undefined;
}

/**
 * Sends a request as given and returns the successful response; failures
 * throw ApiError. Uploads (api/uploads.ts) send their raw body through it.
 */
export async function sendRequest(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'network_error', 'The server could not be reached.');
  }
  if (!response.ok) throw await errorFromResponse(response);
  return response;
}

/** Sends a request and returns the successful response; failures throw ApiError. */
export async function fetchApi(path: string, options: FetchOptions = {}): Promise<Response> {
  const method = options.method ?? 'GET';
  const headers = new Headers({ Accept: 'application/json' });
  let body: string | undefined;
  if (method !== 'GET') {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(options.body ?? {});
  }
  return sendRequest(path, { method, headers, body, signal: options.signal });
}

async function json<T>(response: Response): Promise<T> {
  const data: unknown = await response.json();
  return data as T;
}

/** GET `path` with an optional canonical query string (without `?`). */
export async function apiGet<T>(path: string, query = '', signal?: AbortSignal): Promise<T> {
  return json<T>(await fetchApi(query ? `${path}?${query}` : path, { signal }));
}

export async function apiWrite<T>(method: WriteMethod, path: string, body: unknown): Promise<T> {
  return json<T>(await fetchApi(path, { method, body }));
}
