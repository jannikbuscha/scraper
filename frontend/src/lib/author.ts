// Author names: attribution, not authentication (docs/UI.md §1.5).
// Validation mirrors the server rules of docs/DATA_MODEL.md §7 so that a name
// accepted here is never refused with 400 author_invalid.

export const AUTHOR_STORAGE_KEY = 'mdt.author';
export const RECENT_AUTHORS_STORAGE_KEY = 'mdt.recent_authors';
const MAX_RECENT_AUTHORS = 8;
const MAX_AUTHOR_LENGTH = 100;

// Python's str.isspace() set, which the server uses to trim and collapse.
const WHITESPACE = '\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const WHITESPACE_RUN = new RegExp(`[${WHITESPACE}]+`, 'gu');
const EDGE_WHITESPACE = new RegExp(`^[${WHITESPACE}]+|[${WHITESPACE}]+$`, 'gu');
// Control, format (incl. bidi and zero-width), private-use, surrogate,
// unassigned, line and paragraph separators.
const FORBIDDEN_CHARACTER = /[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Cn}\p{Zl}\p{Zp}]/u;
const RESERVED_PREFIX = /^[A-Za-z_]+:/;
const RESERVED_NAMES = new Set(['seed', 'system']);

export type AuthorValidation = { ok: true; name: string } | { ok: false; error: string };

/** NFC, trim, collapse runs of whitespace to one space. */
export function normalizeAuthor(raw: string): string {
  return raw.normalize('NFC').replace(EDGE_WHITESPACE, '').replace(WHITESPACE_RUN, ' ');
}

function isReservedName(name: string): boolean {
  // Upper- then lower-casing approximates Unicode case folding (ſ, ligatures).
  const variants = [name.toLowerCase(), name.toUpperCase().toLowerCase()];
  return variants.some((v) => RESERVED_NAMES.has(v)) || RESERVED_PREFIX.test(name);
}

export function validateAuthor(raw: string): AuthorValidation {
  const name = normalizeAuthor(raw);
  if (name === '') return { ok: false, error: 'Enter a name.' };
  if (name.includes(',')) return { ok: false, error: 'A name cannot contain a comma.' };
  if (FORBIDDEN_CHARACTER.test(name)) {
    return { ok: false, error: 'The name contains control, invisible or unassigned characters.' };
  }
  // The server counts code points, not UTF-16 units.
  if (Array.from(name).length > MAX_AUTHOR_LENGTH) {
    return { ok: false, error: `Use at most ${MAX_AUTHOR_LENGTH} characters.` };
  }
  if (isReservedName(name)) {
    return { ok: false, error: 'This name is reserved for automatic channels (e.g. seed, collector:…).' };
  }
  if (encodeAuthorHeader(name) === null) {
    return { ok: false, error: 'The name cannot be encoded.' };
  }
  return { ok: true, name };
}

/** Value of the X-Author header, or null if the name cannot be encoded (lone surrogates). */
export function encodeAuthorHeader(name: string): string | null {
  try {
    return encodeURIComponent(name);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Storage. Reads always validate again: localStorage can hold anything.
// ---------------------------------------------------------------------------

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readItem(key: string): string | null {
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function writeItem(key: string, value: string): void {
  try {
    storage()?.setItem(key, value);
  } catch {
    // Storage full or disabled: the name then lasts for this page view only.
  }
}

export function readStoredAuthor(): string | null {
  const raw = readItem(AUTHOR_STORAGE_KEY);
  if (raw === null) return null;
  const result = validateAuthor(raw);
  return result.ok ? result.name : null;
}

export function readRecentAuthors(): string[] {
  const raw = readItem(RECENT_AUTHORS_STORAGE_KEY);
  if (raw === null) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const names: string[] = [];
  for (const entry of parsed) {
    if (typeof entry !== 'string') continue;
    const result = validateAuthor(entry);
    if (result.ok && !names.includes(result.name)) names.push(result.name);
  }
  return names.slice(0, MAX_RECENT_AUTHORS);
}

// ---------------------------------------------------------------------------
// A minimal external store (for useSyncExternalStore). The snapshot is the
// stored string itself, so no cache can go stale; other tabs notify through
// the `storage` event.
// ---------------------------------------------------------------------------

const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Stores a validated name and remembers it as recently used. */
export function setAuthor(raw: string): AuthorValidation {
  const result = validateAuthor(raw);
  if (!result.ok) return result;
  writeItem(AUTHOR_STORAGE_KEY, result.name);
  const recent = [result.name, ...readRecentAuthors().filter((n) => n !== result.name)];
  writeItem(RECENT_AUTHORS_STORAGE_KEY, JSON.stringify(recent.slice(0, MAX_RECENT_AUTHORS)));
  emit();
  return result;
}

export function subscribeAuthor(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === AUTHOR_STORAGE_KEY) listener();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}
