import { describe, expect, it } from 'vitest';

import { fieldSpec } from '../../test/fixtures';
import { createEntityValues, eventValues, fieldUpdateValues, statusValues } from './accept-values';
import { acceptedValue, highlightAlias, urlsToAdd, valueChange } from './proposal-values';

describe('valueChange', () => {
  it('marks added and removed list items', () => {
    const change = valueChange(fieldSpec('channels', 'vocab_list'), 'channels', ['web', 'app'], ['app', 'mobile']);
    expect(change).toEqual({
      kind: 'list',
      items: [
        { value: 'app', change: 'kept' },
        { value: 'mobile', change: 'added' },
        { value: 'web', change: 'removed' },
      ],
      reordered: false,
    });
  });

  it('treats add-only URL lists as additions to the current list', () => {
    const change = valueChange(fieldSpec('official_urls', 'url_list'), 'official_urls', ['https://example.org/a'], [
      'https://example.org/a/',
      'https://example.org/b',
    ]);
    expect(change).toEqual({ kind: 'add-only', current: ['https://example.org/a'], added: ['https://example.org/b'] });
  });

  it('diffs long texts word by word, text versions and short values otherwise', () => {
    expect(valueChange(fieldSpec('description_uk', 'text'), 'description_uk', 'Old example', 'New example')).toEqual({
      kind: 'word-diff',
      oldText: 'Old example',
      newText: 'New example',
    });
    expect(valueChange(undefined, 'text_hash', 'a', 'b')).toEqual({ kind: 'text-version' });
    expect(valueChange(fieldSpec('name_en', 'string'), 'name_en', 'A', 'B')).toEqual({ kind: 'plain' });
  });

  it('accepting an add-only list appends the new URLs to the current list', () => {
    expect(acceptedValue('urls', ['https://example.org/a'], ['https://example.org/b'])).toEqual([
      'https://example.org/a',
      'https://example.org/b',
    ]);
    expect(acceptedValue('name_en', 'A', 'B')).toBe('B');
    expect(urlsToAdd([], ['https://example.org/x', 'https://example.org/x#top'])).toEqual(['https://example.org/x']);
  });

  it('highlights the matched alias case-insensitively', () => {
    expect(highlightAlias('Example Portal launched the example portal', 'example portal')).toEqual([
      { text: 'Example Portal', hit: true },
      { text: ' launched the ', hit: false },
      { text: 'example portal', hit: true },
    ]);
    expect(highlightAlias('No match here', 'absent')).toEqual([{ text: 'No match here', hit: false }]);
  });
});

describe('accept values', () => {
  const fields = [
    fieldSpec('slug', 'slug', { required: true }),
    fieldSpec('name_en', 'string'),
    fieldSpec('name_uk', 'string'),
    fieldSpec('official_urls', 'url_list'),
    fieldSpec('in_paper_scope', 'bool', { default: false }),
    fieldSpec('scope_note', 'text'),
  ];

  it('sends an edited field only when it differs from the prefilled value', () => {
    expect(fieldUpdateValues('name_en', 'Proposed', 'Proposed')).toBeNull();
    expect(fieldUpdateValues('name_en', 'Proposed', ' Proposed ')).toBeNull();
    expect(fieldUpdateValues('name_en', 'Proposed', 'Edited')).toEqual({ name_en: 'Edited' });
    expect(statusValues('discontinued', 'discontinued')).toBeNull();
    expect(statusValues('discontinued', 'suspended')).toEqual({ status: 'suspended' });
  });

  it('sends the changed and added fields of a new record and always the scope of a project', () => {
    const observed = { name_uk: 'Приклад', official_urls: ['https://example.org/'] };
    const form = {
      slug: null,
      name_en: 'Example project',
      name_uk: 'Приклад',
      official_urls: ['https://example.org/'],
      in_paper_scope: false,
      scope_note: 'Example reason',
    };
    expect(createEntityValues('project', fields, observed, form)).toEqual({
      name_en: 'Example project',
      in_paper_scope: false,
      scope_note: 'Example reason',
    });
    expect(createEntityValues('project', fields, observed, { ...form, slug: 'example-project', name_uk: null })).toEqual({
      slug: 'example-project',
      name_en: 'Example project',
      name_uk: null,
      in_paper_scope: false,
      scope_note: 'Example reason',
    });
  });

  it('sends the event fields that differ from the proposed event', () => {
    const proposed = { subject_id: 'prj_A', event_type: 'launch', date: '2001-02', date_basis: 'inferred' };
    expect(eventValues(proposed, { ...proposed, description_en: null })).toBeNull();
    expect(eventValues(proposed, { ...proposed, date: '2001-02-03', description_en: 'Example' })).toEqual({
      date: '2001-02-03',
      description_en: 'Example',
    });
  });
});
