// How an `update_field` proposal changes a value (docs/UI.md §8.2): a text
// version, URLs added to an add-only list, list items added and removed, a
// word diff for long texts, or old against new. Plain data; the components
// render it as React elements.
import type { FieldSpec, JsonValue } from '../../api/types';
import { listDiff, shouldWordDiff, valuesEqual } from '../../lib/diff';
import { asString, asStringArray } from '../../lib/format';

/** URL lists that collectors only add to (docs/DATA_MODEL.md §15.5). */
export const ADD_ONLY_URL_LISTS: ReadonlySet<string> = new Set(['ministry_urls', 'official_urls', 'urls', 'archive_urls']);

/** The field of a text-version proposal (docs/DATA_MODEL.md §15.6). */
export const TEXT_VERSION_FIELD = 'text_hash';

export interface ListItemChange {
  value: JsonValue;
  change: 'kept' | 'added' | 'removed';
}

export type ValueChange =
  | { kind: 'text-version' }
  /** `added`: the proposed URLs the current list lacks. */
  | { kind: 'add-only'; current: string[]; added: string[] }
  | { kind: 'list'; items: ListItemChange[]; reordered: boolean }
  | { kind: 'word-diff'; oldText: string | null; newText: string | null }
  | { kind: 'plain' };

/** A URL compared like the server's canonical form, roughly: no fragment, no trailing slash, lower-case host. */
function urlKey(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.hash = '';
    const text = parsed.toString();
    return parsed.pathname === '/' && !parsed.search ? text : text.replace(/\/$/, '');
  } catch {
    return url;
  }
}

/** The proposed URLs that are not in the current list yet (by canonical URL). */
export function urlsToAdd(current: readonly string[], proposed: readonly string[]): string[] {
  const known = new Set(current.map(urlKey));
  const added: string[] = [];
  for (const url of proposed) {
    const key = urlKey(url);
    if (!known.has(key)) {
      known.add(key);
      added.push(url);
    }
  }
  return added;
}

export function valueChange(field: FieldSpec | undefined, name: string, current: JsonValue, proposed: JsonValue): ValueChange {
  if (name === TEXT_VERSION_FIELD) return { kind: 'text-version' };
  if (ADD_ONLY_URL_LISTS.has(name)) {
    const list = asStringArray(current);
    return { kind: 'add-only', current: list, added: urlsToAdd(list, asStringArray(proposed)) };
  }
  if (Array.isArray(current) || Array.isArray(proposed)) {
    const before = Array.isArray(current) ? current : [];
    const after = Array.isArray(proposed) ? proposed : [];
    const { removed, reordered } = listDiff(before, after);
    const items: ListItemChange[] = [
      ...after.map((value) => ({ value, change: before.some((entry) => valuesEqual(entry, value)) ? 'kept' : 'added' }) as const),
      ...removed.map((value) => ({ value, change: 'removed' }) as const),
    ];
    return { kind: 'list', items, reordered };
  }
  if (shouldWordDiff(field, current, proposed)) {
    return { kind: 'word-diff', oldText: asString(current), newText: asString(proposed) };
  }
  return { kind: 'plain' };
}

/**
 * The value accepting writes: for an add-only URL list the current list with
 * the new URLs appended (URLs a person added meanwhile are kept), else the
 * proposed value (docs/DATA_MODEL.md §16.4).
 */
export function acceptedValue(name: string, current: JsonValue, proposed: JsonValue): JsonValue {
  if (!ADD_ONLY_URL_LISTS.has(name)) return proposed;
  const list = asStringArray(current);
  return [...list, ...urlsToAdd(list, asStringArray(proposed))];
}

export interface QuoteSegment {
  text: string;
  hit: boolean;
}

/** The quote split around the matched alias (case-insensitive substring), for highlighting. */
export function highlightAlias(quote: string, alias: string | null): QuoteSegment[] {
  if (!alias) return [{ text: quote, hit: false }];
  const haystack = quote.toLocaleLowerCase();
  const needle = alias.toLocaleLowerCase();
  if (needle === '' || haystack.length !== quote.length) return [{ text: quote, hit: false }];
  const segments: QuoteSegment[] = [];
  let position = 0;
  for (let index = haystack.indexOf(needle); index >= 0; index = haystack.indexOf(needle, index + needle.length)) {
    if (index > position) segments.push({ text: quote.slice(position, index), hit: false });
    segments.push({ text: quote.slice(index, index + needle.length), hit: true });
    position = index + needle.length;
  }
  if (position < quote.length) segments.push({ text: quote.slice(position), hit: false });
  return segments.length > 0 ? segments : [{ text: quote, hit: false }];
}
