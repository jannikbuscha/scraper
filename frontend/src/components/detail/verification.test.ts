import { describe, expect, it } from 'vitest';

import type { ConflictPayload, JsonObject, RevisionSummary } from '../../api/types';
import { exampleItem, fieldSpec } from '../../test/fixtures';
import { isVerifiable, verifyConflictDecision } from './verification';

const revision = (version: number, author: string, changed: string[]): RevisionSummary => ({
  id: version,
  version,
  at: `2026-01-0${version}T10:00:00.000000Z`,
  author,
  channel: 'ui',
  action: 'update',
  note: null,
  changed_fields: changed,
  restored_from: null,
  restored_from_version: null,
  batch_id: null,
});

function verifyConflict(base: JsonObject | null, current: JsonObject, intervening: RevisionSummary[]): ConflictPayload {
  return {
    action: 'verify',
    entity_type: 'project',
    entity_id: 'prj_EXAMPLE',
    base_version: 2,
    current_version: 2 + intervening.length,
    base,
    current,
    base_state: { deleted_at: null, deleted_by: null },
    current_state: { deleted_at: null, deleted_by: null },
    changed_since_base: [],
    your_changes: {},
    conflicting_fields: [],
    meta_changed_since_base: {},
    intervening,
    refs: {},
  };
}

describe('field verification', () => {
  it('offers verification for stored fields with a value, not for the record status', () => {
    const item = exampleItem('prj_EXAMPLE', { name_en: 'Example', name_uk: null, verification_status: 'unverified' });
    expect(isVerifiable(fieldSpec('name_en', 'string'), item)).toBe(true);
    expect(isVerifiable(fieldSpec('name_uk', 'string'), item)).toBe(false);
    expect(isVerifiable(fieldSpec('verification_status', 'vocab'), item)).toBe(false);
    expect(isVerifiable(fieldSpec('period', 'vocab', { derived: true }), item)).toBe(false);
    expect(isVerifiable(fieldSpec('canonical_url', 'url', { system: true }), item)).toBe(false);
    // Evidence cannot be the subject of evidence, so its own fields are not field-verified.
    const evidence = exampleItem('evd_EXAMPLE', { quote: 'An example quote' }, { type: 'evidence' });
    expect(isVerifiable(fieldSpec('quote', 'text'), evidence)).toBe(false);
  });

  it('retries once with the current version when the field value did not change', () => {
    const payload = verifyConflict({ name_en: 'Example', notes: 'a' }, { name_en: 'Example', notes: 'b' }, [
      revision(3, 'Example Colleague', ['notes']),
    ]);
    expect(verifyConflictDecision(payload, 'name_en')).toEqual({ kind: 'retry', version: 3 });
  });

  it('asks before verifying a value that changed, naming who changed it', () => {
    const payload = verifyConflict({ name_en: 'Old name' }, { name_en: 'New name' }, [
      revision(3, 'First Colleague', ['name_en']),
      revision(4, 'Second Colleague', ['notes']),
    ]);
    expect(verifyConflictDecision(payload, 'name_en')).toEqual({
      kind: 'ask',
      version: 4,
      from: 'Old name',
      to: 'New name',
      by: 'First Colleague',
      at: '2026-01-03T10:00:00.000000Z',
      verification: null,
      note: null,
    });
  });

  it('asks instead of retrying when a colleague changed the verification of the field', () => {
    const dispute = { ...revision(3, 'Example Colleague', ['name_en']), action: 'verify' as const, note: 'Example reason' };
    const payload = {
      ...verifyConflict({ name_en: 'Example' }, { name_en: 'Example' }, [dispute]),
      meta_changed_since_base: { name_en: { verified: ['unverified', 'disputed'] as [string, string] } },
    };
    expect(verifyConflictDecision(payload, 'name_en')).toEqual({
      kind: 'ask',
      version: 3,
      from: 'Example',
      to: 'Example',
      by: 'Example Colleague',
      at: '2026-01-03T10:00:00.000000Z',
      verification: ['unverified', 'disputed'],
      note: 'Example reason',
    });
  });

  it('asks when the field was verified again with other evidence (no status change)', () => {
    const reverified = { ...revision(3, 'Example Colleague', ['name_en']), action: 'verify' as const };
    const payload = verifyConflict({ name_en: 'Example' }, { name_en: 'Example' }, [reverified]);
    const decision = verifyConflictDecision(payload, 'name_en');
    expect(decision).toMatchObject({ kind: 'ask', version: 3, by: 'Example Colleague', verification: null });
  });

  it('asks when the base snapshot is unknown, and reloads when the row was deleted', () => {
    expect(verifyConflictDecision(verifyConflict(null, { name_en: 'Example' }, []), 'name_en').kind).toBe('ask');
    const deleted = {
      ...verifyConflict({ name_en: 'Example' }, { name_en: 'Example' }, []),
      current_state: { deleted_at: '2026-01-05T10:00:00.000000Z', deleted_by: 'Example Colleague' },
    };
    expect(verifyConflictDecision(deleted, 'name_en')).toEqual({ kind: 'stale' });
  });
});
