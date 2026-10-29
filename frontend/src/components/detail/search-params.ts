// Detail-page state in the URL (docs/UI.md §1.2, §2): `tab=details|history`,
// the history compare selection `from`/`to`, `comments=open`, `thread=<id>`
// and `edit=1`.
import type { SearchRecord } from '../../lib/query-string';

export type DetailTab = 'details' | 'history';

export const detailTab = (search: SearchRecord): DetailTab => (search.tab === 'history' ? 'history' : 'details');

/** Sets (string) or removes (null) parameters; returns a new record. */
export function patchSearch(search: SearchRecord, patch: Readonly<Record<string, string | null>>): SearchRecord {
  const next: SearchRecord = Object.fromEntries(Object.entries(search).filter(([key]) => !(key in patch)));
  for (const [key, value] of Object.entries(patch)) if (value !== null) next[key] = value;
  return next;
}

const versionParam = (value: string | undefined): number | null =>
  value !== undefined && /^\d+$/.test(value) ? Number(value) : null;

/** The picked versions of the compare mode (at most two, older first). */
export function compareSelection(search: SearchRecord): number[] {
  const picked = [versionParam(search.from), versionParam(search.to)].filter((v): v is number => v !== null);
  return [...new Set(picked)].sort((a, b) => a - b);
}

/** Writes the compare selection as `from` (older) and `to` (newer). */
export function withCompareSelection(search: SearchRecord, versions: readonly number[]): SearchRecord {
  const [from, to] = [...new Set(versions)].sort((a, b) => a - b);
  return patchSearch(search, {
    tab: 'history',
    from: from === undefined ? null : String(from),
    to: to === undefined ? null : String(to),
  });
}
