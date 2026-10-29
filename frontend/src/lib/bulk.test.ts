import { describe, expect, it } from 'vitest';

import type { BulkResult } from '../api/types';
import { bulkRequest, conflictRetryTargets, countBulkResults, mergeBulkResults, type BulkTarget } from './bulk';

const targets: BulkTarget[] = [
  { id: 'svc_1', label: 'Example service A', version: 3 },
  { id: 'svc_2', label: 'Example service B', version: 7 },
];

const result = (id: string, status: BulkResult['status'], extra: Partial<BulkResult> = {}): BulkResult => ({
  id,
  status,
  version: null,
  current_version: null,
  current_values: null,
  error: null,
  ...extra,
});

describe('bulkRequest', () => {
  it('sends the versions captured when the dialog opened', () => {
    expect(bulkRequest(targets, { field: 'status', op: 'set', value: 'active' }, null)).toEqual({
      items: [
        { id: 'svc_1', expected_version: 3 },
        { id: 'svc_2', expected_version: 7 },
      ],
      set: { status: 'active' },
      note: null,
    });
  });

  it('puts list operations under add or remove', () => {
    expect(bulkRequest(targets.slice(0, 1), { field: 'channels', op: 'add', value: ['app', 'web'] }, 'n')).toEqual({
      items: [{ id: 'svc_1', expected_version: 3 }],
      add: { channels: ['app', 'web'] },
      note: 'n',
    });
    expect(bulkRequest(targets.slice(0, 1), { field: 'channels', op: 'remove', value: ['app'] }, null).remove).toEqual({
      channels: ['app'],
    });
  });

  it('sends values the rules demand alongside the edit', () => {
    const request = bulkRequest(
      targets,
      { field: 'in_paper_scope', op: 'set', value: true, alongside: { scope_note: 'Example reason' } },
      null,
    );
    expect(request.set).toEqual({ in_paper_scope: true, scope_note: 'Example reason' });
  });
});

describe('bulk results', () => {
  it('counts the latest result per row and retries only conflicts with their current versions', () => {
    let results = mergeBulkResults(new Map(), [
      result('svc_1', 'updated', { version: 4 }),
      result('svc_2', 'conflict', { current_version: 9, current_values: { status: 'planned' } }),
    ]);
    expect(countBulkResults(results)).toEqual({ updated: 1, unchanged: 0, conflict: 1, entity_deleted: 0, error: 0 });
    expect(conflictRetryTargets(targets, results)).toEqual([{ id: 'svc_2', label: 'Example service B', version: 9 }]);

    // A repeated conflict on retry carries the newer version again.
    results = mergeBulkResults(results, [result('svc_2', 'conflict', { current_version: 10 })]);
    expect(conflictRetryTargets(targets, results)).toEqual([{ id: 'svc_2', label: 'Example service B', version: 10 }]);

    results = mergeBulkResults(results, [result('svc_2', 'updated', { version: 11 })]);
    expect(countBulkResults(results)).toEqual({ updated: 2, unchanged: 0, conflict: 0, entity_deleted: 0, error: 0 });
    expect(conflictRetryTargets(targets, results)).toEqual([]);
  });
});
