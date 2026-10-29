import { describe, expect, it } from 'vitest';

import type { FieldSpec, RevisionDiff } from '../api/types';
import {
  fieldDiffRows,
  isDiffEmpty,
  listDiff,
  metaDiffRows,
  shouldWordDiff,
  stateDiffRows,
  valuesEqual,
  wordDiff,
} from './diff';

const join = (segments: ReturnType<typeof wordDiff>, kind: 'equal' | 'added' | 'removed') =>
  segments
    .filter((s) => s.kind === kind)
    .map((s) => s.text.trim())
    .join('|');

describe('wordDiff', () => {
  it('marks changed words in Latin text', () => {
    const segments = wordDiff('The service was launched in spring.', 'The service was expanded in spring.');
    expect(join(segments, 'removed')).toBe('launched');
    expect(join(segments, 'added')).toBe('expanded');
  });

  it('diffs Ukrainian text by words, not characters', () => {
    const segments = wordDiff('Мінцифри запустили нову послугу', 'Мінцифри оновили нову послугу');
    expect(join(segments, 'removed')).toBe('запустили');
    expect(join(segments, 'added')).toBe('оновили');
  });

  it('treats null as empty text and reproduces both sides', () => {
    const segments = wordDiff(null, 'New text');
    expect(segments).toEqual([{ text: 'New text', kind: 'added' }]);
    const both = wordDiff('a b c', 'a x c');
    expect(both.filter((s) => s.kind !== 'added').map((s) => s.text).join('')).toBe('a b c');
    expect(both.filter((s) => s.kind !== 'removed').map((s) => s.text).join('')).toBe('a x c');
  });
});

describe('shouldWordDiff', () => {
  const textField = { type: 'text' } as FieldSpec;
  const stringField = { type: 'string' } as FieldSpec;

  it('uses word diffs for text fields and long strings only', () => {
    expect(shouldWordDiff(textField, 'a', 'b')).toBe(true);
    expect(shouldWordDiff(stringField, 'short', 'other')).toBe(false);
    expect(shouldWordDiff(stringField, 'x'.repeat(81), null)).toBe(true);
    expect(shouldWordDiff(textField, ['a'], ['b'])).toBe(false);
  });
});

describe('valuesEqual and listDiff', () => {
  it('compares JSON deeply, ignoring object key order', () => {
    expect(valuesEqual({ a: 1, b: [1, { c: null }] }, { b: [1, { c: null }], a: 1 })).toBe(true);
    expect(valuesEqual(['a', 'b'], ['b', 'a'])).toBe(false);
    expect(valuesEqual(null, false)).toBe(false);
    expect(valuesEqual(0, 0)).toBe(true);
  });

  it('reports added, removed and reordered list elements', () => {
    expect(listDiff(['app', 'web'], ['web', 'app', 'api'])).toEqual({ added: ['api'], removed: [], reordered: true });
    expect(listDiff(['app', 'web'], ['app'])).toEqual({ added: [], removed: ['web'], reordered: false });
  });
});

describe('diff rows', () => {
  const diff: RevisionDiff = {
    fields: { status: ['planned', 'active'], name_en: ['Old', 'New'], extra: [null, 1] },
    meta: { name_en: { by: ['seed', 'user'], verified: ['unverified', 'verified'], evidence_id: [null, 'evd_1'] } },
    state: { deleted_at: [null, '2026-10-28T17:00:00.000000Z'] },
  };

  it('orders field and meta rows by registry order, unknown fields last', () => {
    expect(fieldDiffRows(diff, ['name_en', 'status']).map((row) => row.field)).toEqual(['name_en', 'status', 'extra']);
    expect(metaDiffRows(diff)).toEqual([
      { field: 'name_en', key: 'verified', oldValue: 'unverified', newValue: 'verified' },
      { field: 'name_en', key: 'evidence_id', oldValue: null, newValue: 'evd_1' },
    ]);
    expect(stateDiffRows(diff)).toEqual([{ key: 'deleted_at', oldValue: null, newValue: '2026-10-28T17:00:00.000000Z' }]);
  });

  it('leaves out attribution that names the one user: resolved_by and the provenance by', () => {
    const comment: RevisionDiff = {
      fields: { status: ['open', 'resolved'], resolved_by: [null, 'user'], resolved_at: [null, '2026-10-28T17:00:00.000000Z'] },
    };
    expect(fieldDiffRows(comment).map((row) => row.field)).toEqual(['resolved_at', 'status']);
    expect(metaDiffRows(diff).map((row) => row.key)).not.toContain('by');
  });

  it('detects empty diffs', () => {
    expect(isDiffEmpty({})).toBe(true);
    expect(isDiffEmpty(diff)).toBe(false);
  });
});
