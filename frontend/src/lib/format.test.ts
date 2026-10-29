import { describe, expect, it, vi } from 'vitest';

import type { RefLabel } from '../api/types';
import { exampleItem, exampleVocabularies, fieldSpec } from '../test/fixtures';
import {
  apiTimestamp,
  derivedDetails,
  findRef,
  formatUtcTimestamp,
  formatValueText,
  getFieldValue,
  isEmptyValue,
  localDayEnd,
  localDayStart,
  parseTimestamp,
} from './format';
import { buildVocabIndex } from './vocab';

const vocab = buildVocabIndex(exampleVocabularies);
const exampleRef: RefLabel = { id: 'prj_1', type: 'project', label: 'Example project', deleted: false };

describe('formatValueText', () => {
  it('formats values per field type', () => {
    const cluster = fieldSpec('paper_cluster', 'vocab', { vocabulary: 'example_cluster' });
    expect(formatValueText(cluster, 'cluster_a', { vocab })).toBe('Example cluster A');
    expect(formatValueText(cluster, 'unknown_code', { vocab })).toBe('unknown_code');
    expect(
      formatValueText(fieldSpec('policy_domains', 'vocab_list', { vocabulary: 'example_domain' }), ['domain_b', 'domain_a'], {
        vocab,
      }),
    ).toBe('Example domain B, Example domain A');
    expect(formatValueText(fieldSpec('in_paper_scope', 'bool'), false, { vocab })).toBe('no');
    expect(formatValueText(fieldSpec('launch', 'partial_date'), '2020-06', { vocab })).toBe('2020-06 · month');
    expect(formatValueText(fieldSpec('urls', 'url_list'), ['https://example.org/a', 'https://example.org/b'], { vocab })).toBe(
      'https://example.org/a; https://example.org/b',
    );
    expect(formatValueText(fieldSpec('aliases', 'alias_list'), [{ text: 'Example alias', lang: 'en' }], { vocab })).toBe(
      'Example alias',
    );
    expect(formatValueText(fieldSpec('project_id', 'ref'), 'prj_1', { vocab, refs: { project_id: exampleRef } })).toBe(
      'Example project',
    );
    expect(formatValueText(fieldSpec('version', 'int'), 0, { vocab })).toBe('0');
    expect(formatValueText(fieldSpec('notes', 'text'), null, { vocab })).toBe('—');
  });
});

describe('item values', () => {
  it('treats null, empty text and empty lists as empty, but not false or 0', () => {
    expect([null, undefined, '', []].map((value) => isEmptyValue(value))).toEqual([true, true, true, true]);
    expect([false, 0, ['a']].map((value) => isEmptyValue(value))).toEqual([false, false, false]);
  });

  it('reads stored, system, derived and virtual values from their places in an item', () => {
    const item = exampleItem('prj_1', { name_en: 'Example project' }, { version: 4, virtual: { open_comments: 2 } });
    expect(getFieldValue(item, fieldSpec('name_en', 'string'))).toBe('Example project');
    expect(getFieldValue(item, fieldSpec('version', 'int', { system: true }))).toBe(4);
    expect(getFieldValue(item, fieldSpec('period', 'vocab', { derived: true }))).toBe('period_a');
    expect(getFieldValue(item, fieldSpec('open_comments', 'int', { virtual: true }))).toBe(2);
    expect(getFieldValue(item, fieldSpec('missing', 'string'))).toBeNull();
  });

  it('finds the deciding event of a derived value under its key stem', () => {
    const event: RefLabel = { id: 'evt_1', type: 'event', label: 'Example event', deleted: false };
    const item = exampleItem(
      'prj_1',
      {},
      {
        derived: { war_trajectory: 'example_value', trajectory_reason: 'example_reason', trajectory_event_id: 'evt_1' },
        refs: { 'derived.trajectory_event_id': event },
      },
    );
    expect(derivedDetails(item, 'war_trajectory')).toEqual({
      basis: null,
      reason: 'example_reason',
      decidedBy: event,
      interval: null,
    });
  });

  it('reports the interval over all candidates only where it differs from the displayed value', () => {
    // Synthetic candidates "2022" and "2022-03": the one that ends first is shown,
    // the interval [earliest start, earliest end] decides the period (DATA_MODEL §8.3).
    const several = exampleItem(
      'prj_1',
      {},
      { derived: { launch: '2022-03', launch_precision: 'month', launch_start: '2022-01-01', launch_end: '2022-03-31' } },
    );
    expect(derivedDetails(several, 'launch').interval).toEqual({ start: '2022-01-01', end: '2022-03-31' });
    const single = exampleItem(
      'prj_1',
      {},
      { derived: { launch: '2020-02', launch_precision: 'month', launch_start: '2020-02-01', launch_end: '2020-02-29' } },
    );
    expect(derivedDetails(single, 'launch').interval).toBeNull();
    expect(derivedDetails(single, 'period').interval).toBeNull();
  });

  it('labels refs by ID first, by field name only for the current value', () => {
    expect(findRef({ prj_1: exampleRef }, 'project_id', 'prj_1')).toBe(exampleRef);
    expect(findRef({ project_id: exampleRef }, 'project_id', 'prj_1')).toBe(exampleRef);
    expect(findRef({ project_id: exampleRef }, 'project_id', 'prj_2')).toBeUndefined();
  });
});

describe('timestamps', () => {
  it('parses API timestamps with microseconds and shows them in UTC', () => {
    expect(parseTimestamp('2026-10-28T17:00:00.123456Z')?.toISOString()).toBe('2026-10-28T17:00:00.123Z');
    expect(formatUtcTimestamp('2026-10-28T17:00:00.123456Z')).toBe('2026-10-28 17:00:00 UTC');
    expect(parseTimestamp('not a timestamp')).toBeNull();
    expect(formatUtcTimestamp('not a timestamp')).toBe('not a timestamp');
  });

  it('writes dates in the API timestamp format', () => {
    expect(apiTimestamp(new Date(Date.UTC(2026, 9, 28, 17, 0, 0, 123)))).toBe('2026-10-28T17:00:00.123000Z');
  });

  it('turns a local day into inclusive UTC bounds', () => {
    vi.stubEnv('TZ', 'Europe/Kyiv');
    // UTC+2 on this day (after the end of summer time).
    expect(localDayStart('2026-10-28')).toBe('2026-10-27T22:00:00.000000Z');
    expect(localDayEnd('2026-10-28')).toBe('2026-10-28T21:59:59.999999Z');
    expect(localDayStart('2026-02-30')).toBeNull();
    expect(localDayEnd('')).toBeNull();
  });
});
