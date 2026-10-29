// Diff helpers for history views and the restore preview (docs/UI.md §4.2).
// Results are plain data; components render them as React elements.
import { diffWords } from 'diff';

import type { FieldSpec, JsonValue, RevisionDiff } from '../api/types';

export interface DiffSegment {
  text: string;
  kind: 'equal' | 'added' | 'removed';
}

// The default jsdiff tokenizer splits Cyrillic into single characters;
// Intl.Segmenter gives real word boundaries for Ukrainian text.
const wordSegmenter =
  typeof Intl.Segmenter === 'function' ? new Intl.Segmenter(undefined, { granularity: 'word' }) : undefined;

/** Word-level diff of two texts (null counts as empty). */
export function wordDiff(oldText: string | null, newText: string | null): DiffSegment[] {
  const changes = diffWords(oldText ?? '', newText ?? '', wordSegmenter ? { intlSegmenter: wordSegmenter } : {});
  return changes
    .filter((change) => change.value !== '')
    .map((change) => ({
      text: change.value,
      kind: change.added ? 'added' : change.removed ? 'removed' : 'equal',
    }));
}

const LONG_TEXT = 80;

/** Long texts get a word-level diff instead of old → new side by side. */
export function shouldWordDiff(field: FieldSpec | undefined, oldValue: JsonValue, newValue: JsonValue): boolean {
  const isText = (v: JsonValue) => v === null || typeof v === 'string';
  if (!isText(oldValue) || !isText(newValue)) return false;
  if (field?.type === 'text') return true;
  return Math.max(oldValue?.length ?? 0, newValue?.length ?? 0) > LONG_TEXT;
}

/** Deep equality of JSON values; object key order is irrelevant, list order matters. */
export function valuesEqual(a: JsonValue | undefined, b: JsonValue | undefined): boolean {
  if (a === b) return true;
  if (a === undefined || b === undefined || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => valuesEqual(v, b[i]));
  }
  if (typeof a === 'object' && typeof b === 'object') {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every((key) => valuesEqual(a[key], b[key]));
  }
  return false;
}

export interface ListDiff {
  added: JsonValue[];
  removed: JsonValue[];
  /** Same elements, different order (the first element is the main value). */
  reordered: boolean;
}

export function listDiff(oldList: readonly JsonValue[], newList: readonly JsonValue[]): ListDiff {
  const contains = (list: readonly JsonValue[], value: JsonValue) => list.some((entry) => valuesEqual(entry, value));
  const added = newList.filter((value) => !contains(oldList, value));
  const removed = oldList.filter((value) => !contains(newList, value));
  const keptOld = oldList.filter((value) => contains(newList, value));
  const keptNew = newList.filter((value) => contains(oldList, value));
  return { added, removed, reordered: !valuesEqual([...keptOld], [...keptNew]) };
}

export interface FieldDiffRow {
  field: string;
  oldValue: JsonValue;
  newValue: JsonValue;
}

export interface MetaDiffRow {
  field: string;
  key: string;
  oldValue: JsonValue;
  newValue: JsonValue;
}

export interface StateDiffRow {
  key: string;
  oldValue: JsonValue;
  newValue: JsonValue;
}

function orderBy(order: readonly string[]): (a: string, b: string) => number {
  const rank = (name: string) => {
    const index = order.indexOf(name);
    return index < 0 ? order.length : index;
  };
  return (a, b) => rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0);
}

/**
 * Attribution that names the app's one user is not shown (docs/UI.md §4.2): a
 * comment's `resolved_by` (its time is) and the provenance `by` (its `src` is).
 */
export const HIDDEN_FIELDS: ReadonlySet<string> = new Set(['resolved_by']);
const HIDDEN_META_KEYS: ReadonlySet<string> = new Set(['by']);

/** Field changes in registry order (fields unknown to the registry last). */
export function fieldDiffRows(diff: RevisionDiff, order: readonly string[] = []): FieldDiffRow[] {
  const fields = diff.fields ?? {};
  return Object.keys(fields)
    .filter((field) => !HIDDEN_FIELDS.has(field))
    .sort(orderBy(order))
    .flatMap((field) => {
      const pair = fields[field];
      return pair ? [{ field, oldValue: pair[0], newValue: pair[1] }] : [];
    });
}

export function metaDiffRows(diff: RevisionDiff, order: readonly string[] = []): MetaDiffRow[] {
  const meta = diff.meta ?? {};
  return Object.keys(meta)
    .sort(orderBy(order))
    .flatMap((field) =>
      Object.entries(meta[field] ?? {})
        .filter(([key]) => !HIDDEN_META_KEYS.has(key))
        .map(([key, pair]) => ({ field, key, oldValue: pair[0], newValue: pair[1] })),
    );
}

export function stateDiffRows(diff: RevisionDiff): StateDiffRow[] {
  return Object.entries(diff.state ?? {}).map(([key, pair]) => ({ key, oldValue: pair[0], newValue: pair[1] }));
}

export const isDiffEmpty = (diff: RevisionDiff): boolean =>
  fieldDiffRows(diff).length === 0 && metaDiffRows(diff).length === 0 && stateDiffRows(diff).length === 0;
