import { describe, expect, it } from 'vitest';

import type { Vocabulary, VocabTerm } from '../../api/types';
import { fieldSpec } from '../../test/fixtures';
import {
  changedValues,
  createTermFields,
  editableTermFields,
  identityFields,
  isFixedTerm,
  replacementCodes,
  splitValidationErrors,
  withAttribute,
} from './term-form';

const fields = [
  fieldSpec('vocabulary', 'string', { create_only: true, in_create: true }),
  fieldSpec('code', 'string', { create_only: true, in_create: true }),
  fieldSpec('label_en', 'string', { in_create: true }),
  fieldSpec('active', 'bool'),
  fieldSpec('attributes', 'json'),
  fieldSpec('updated_at', 'datetime', { editable: false, system: true }),
];

const term = (id: string, code: string, overrides: Partial<VocabTerm> = {}): VocabTerm => ({
  id,
  code,
  label_en: code.toUpperCase(),
  label_uk: null,
  definition: null,
  include_note: null,
  exclude_note: null,
  examples: null,
  sort_order: null,
  active: true,
  replaced_by: null,
  attributes: {},
  version: 1,
  usage_count: 0,
  open_comments: 0,
  ...overrides,
});

const vocabulary = (fixed: boolean): Vocabulary => ({
  name: 'example_vocabulary',
  label: 'Example vocabulary',
  description: null,
  multi: false,
  fixed_codes: fixed,
  terms: [
    term('voc_1', 'a'),
    term('voc_2', 'b', { active: false, replaced_by: 'a' }),
    term('voc_3', 'c', { attributes: { fixed: true } }),
  ],
});

describe('term forms', () => {
  it('separates the identity from the generically edited fields', () => {
    expect(identityFields(fields).map((field) => field.name)).toEqual(['vocabulary', 'code']);
    expect(editableTermFields(fields).map((field) => field.name)).toEqual(['label_en', 'active']);
    expect(createTermFields(fields).map((field) => field.name)).toEqual(['label_en']);
  });

  it('sends only values that differ from the base, comparing structures by value', () => {
    const base = { label_en: 'A', active: true, attributes: { counts_as_modification: true, fixed: false } };
    const reordered = { fixed: false, counts_as_modification: true };
    expect(changedValues(base, { label_en: 'A', active: true, attributes: reordered })).toEqual({});
    const toggled = withAttribute(base.attributes, 'counts_as_modification', false);
    expect(changedValues(base, { label_en: 'A2', active: true, attributes: toggled })).toEqual({
      label_en: 'A2',
      attributes: { counts_as_modification: false, fixed: false },
    });
  });

  it('knows fixed codes and the codes a term can be replaced by', () => {
    const open = vocabulary(false);
    expect(isFixedTerm(open, { fixed: true })).toBe(true);
    expect(isFixedTerm(open, {})).toBe(false);
    expect(isFixedTerm(vocabulary(true), {})).toBe(true);
    expect(replacementCodes(open, 'a').map((candidate) => candidate.code)).toEqual(['c']);
  });

  it('maps server validation paths to fields by their last segment', () => {
    const details = { 'changes.label_en': ['Required'], replaced_by: ['Must be active'], note: ['Too long'] };
    expect(splitValidationErrors(details, ['label_en', 'replaced_by'])).toEqual({
      byField: { label_en: 'Required', replaced_by: 'Must be active' },
      other: ['note: Too long'],
    });
  });
});
