import { describe, expect, it } from 'vitest';

import {
  keysAfterDocumentAdded,
  keysAfterImport,
  keysAfterMerge,
  keysAfterProposalDecision,
  keysAfterRunChange,
  keysAfterRunFinished,
} from './queries';

const has = (keys: readonly (readonly unknown[])[], key: readonly unknown[]) =>
  keys.some((candidate) => JSON.stringify(candidate) === JSON.stringify(key));

describe('Phase 2 invalidation (docs/UI.md §8.8)', () => {
  it('refreshes the inbox and the subject type after a decision', () => {
    const keys = keysAfterProposalDecision({ entityTypes: ['project'], kinds: ['update_field'] });
    for (const key of [['proposals'], ['proposals-summary'], ['stats'], ['changes'], ['list', 'project'], ['facets', 'project'], ['item', 'project']]) {
      expect(has(keys, key)).toBe(true);
    }
    expect(has(keys, ['item', 'service'])).toBe(false);
    expect(has(keys, ['list'])).toBe(false);
  });

  it('refreshes projects and services after an accepted event, all data after a merge-accept', () => {
    const event = keysAfterProposalDecision({ entityTypes: ['event'], kinds: ['create_event'] });
    for (const key of [['item', 'project'], ['list', 'service'], ['facets', 'project'], ['list', 'event']]) {
      expect(has(event, key)).toBe(true);
    }
    const merge = keysAfterProposalDecision({ entityTypes: ['service'], kinds: ['possible_duplicate'] });
    expect(has(merge, ['list'])).toBe(true);
    expect(has(merge, ['item'])).toBe(true);
    const documents = keysAfterProposalDecision({ entityTypes: ['document'], kinds: ['possible_duplicate'] });
    expect(has(documents, ['list'])).toBe(false);
  });

  it('refreshes runs on start and cancel, and all data when a run finishes', () => {
    const change = keysAfterRunChange('run_A');
    for (const key of [['runs'], ['collectors'], ['stats'], ['run', 'run_A']]) expect(has(change, key)).toBe(true);
    const finished = keysAfterRunFinished('run_A');
    for (const key of [['list'], ['item'], ['facets'], ['proposals'], ['proposals-summary'], ['observations'], ['stats'], ['changes']]) {
      expect(has(finished, key)).toBe(true);
    }
  });

  it('refreshes the import type, the merge targets and the documents', () => {
    const imported = keysAfterImport('organization');
    for (const key of [['list', 'organization'], ['item', 'organization'], ['imports'], ['changes'], ['stats']]) {
      expect(has(imported, key)).toBe(true);
    }
    expect(has(keysAfterMerge(), ['list'])).toBe(true);
    const documents = keysAfterDocumentAdded();
    expect(has(documents, ['list', 'document'])).toBe(true);
    expect(has(documents, ['facets', 'document'])).toBe(true);
    expect(has(documents, ['stats'])).toBe(true);
  });
});
