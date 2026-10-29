import { describe, expect, it } from 'vitest';

import type { BulkResult } from '../api/types';
import { bulkRequest, codesInRows, countBulkResults, type BulkTarget } from './bulk';

const targets: BulkTarget[] = [
  { id: 'svc_1', label: 'Example service A' },
  { id: 'svc_2', label: 'Example service B' },
];

const result = (id: string, status: BulkResult['status']): BulkResult => ({ id, status, version: null, error: null });

describe('bulkRequest', () => {
  it('sends the selected IDs with the operation', () => {
    expect(bulkRequest(targets, { field: 'status', op: 'set', value: 'active' }, null)).toEqual({
      ids: ['svc_1', 'svc_2'],
      set: { status: 'active' },
      note: null,
    });
  });

  it('puts list operations under add or remove', () => {
    expect(bulkRequest(targets.slice(0, 1), { field: 'channels', op: 'add', value: ['app', 'web'] }, 'n')).toEqual({
      ids: ['svc_1'],
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
  it('counts the results per status', () => {
    expect(
      countBulkResults([result('svc_1', 'updated'), result('svc_2', 'entity_deleted'), result('svc_3', 'updated')]),
    ).toEqual({ updated: 2, unchanged: 0, entity_deleted: 1, error: 0 });
  });

  it('collects the codes the selected rows carry, for a bulk remove of inactive codes', () => {
    const rows: BulkTarget[] = [
      { id: 'svc_1', label: 'Example service A', values: { channels: ['app', 'old_code'], kind: 'e_service' } },
      { id: 'svc_2', label: 'Example service B', values: { channels: ['old_code', 'chatbot'], kind: null } },
      { id: 'svc_3', label: 'Example service C' },
    ];
    expect(codesInRows(rows, 'channels')).toEqual(['app', 'old_code', 'chatbot']);
    expect(codesInRows(rows, 'kind')).toEqual(['e_service']);
    expect(codesInRows(rows, 'missing')).toEqual([]);
  });
});
