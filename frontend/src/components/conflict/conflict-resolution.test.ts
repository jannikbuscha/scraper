import { describe, expect, it } from 'vitest';

import type { ConflictPayload, JsonObject, RevisionSummary } from '../../api/types';
import { classifyConflict, missingChoices, resolveConflict, verificationResetFields } from './conflict-resolution';

const revision = (version: number, author: string, changed: string[]): RevisionSummary => ({
  id: version * 10,
  version,
  at: '2026-01-02T10:00:00.000000Z',
  author,
  channel: 'ui',
  action: 'update',
  note: null,
  changed_fields: changed,
  restored_from: null,
  restored_from_version: null,
  batch_id: null,
});

/** A patch conflict: `base` at `baseVersion`, `current` one version later. */
function conflict(base: JsonObject, current: JsonObject, yourChanges: JsonObject, baseVersion = 3): ConflictPayload {
  const changed = Object.keys({ ...base, ...current }).filter(
    (field) => JSON.stringify(base[field] ?? null) !== JSON.stringify(current[field] ?? null),
  );
  return {
    action: 'patch',
    entity_type: 'project',
    entity_id: 'prj_EXAMPLE',
    base_version: baseVersion,
    current_version: baseVersion + 1,
    base,
    current,
    base_state: { deleted_at: null, deleted_by: null },
    current_state: { deleted_at: null, deleted_by: null },
    changed_since_base: changed,
    your_changes: yourChanges,
    conflicting_fields: Object.keys(yourChanges).filter(
      (field) =>
        changed.includes(field) && JSON.stringify(yourChanges[field]) !== JSON.stringify(current[field] ?? null),
    ),
    meta_changed_since_base: {},
    intervening: [revision(baseVersion + 1, 'Example Colleague', changed)],
    refs: {},
  };
}

const base: JsonObject = {
  name_en: 'Example project',
  description_en: 'An example description.',
  status: 'active',
  policy_domains: ['domain_a'],
};

describe('conflict resolution payload', () => {
  it('applies the fields only you changed on top of the current state', () => {
    const payload = conflict(base, { ...base, status: 'paused' }, { name_en: 'Example project (renamed)' });

    expect(classifyConflict(payload)).toEqual({
      conflicting: [],
      onlyYours: ['name_en'],
      alreadyCurrent: [],
      onlyTheirs: ['status'],
    });
    const result = resolveConflict(payload, {});
    expect(result).toEqual({
      ok: true,
      resolution: {
        base: { fields: { ...base, status: 'paused' }, version: 4 },
        changes: { name_en: 'Example project (renamed)' },
      },
    });
  });

  it('keeps the fields only they changed and sends nothing for them', () => {
    const current = { ...base, description_en: 'Their new description.', policy_domains: ['domain_b'] };
    const payload = conflict(base, current, {});

    expect(classifyConflict(payload).onlyTheirs).toEqual(['description_en', 'policy_domains']);
    const result = resolveConflict(payload, {});
    expect(result.ok && result.resolution.changes).toEqual({});
    expect(result.ok && result.resolution.base).toEqual({ fields: current, version: 4 });
  });

  it('requires a choice for every conflicting field and applies theirs, yours or a merged value', () => {
    const current = { ...base, name_en: 'Their name', description_en: 'Their description.', status: 'paused' };
    const payload = conflict(base, current, {
      name_en: 'My name',
      description_en: 'My description.',
      status: 'closed',
      policy_domains: ['domain_a', 'domain_b'],
    });

    const classification = classifyConflict(payload);
    expect(classification.conflicting).toEqual(['name_en', 'description_en', 'status']);
    expect(classification.onlyYours).toEqual(['policy_domains']);

    // Nothing is resolved without a choice per conflicting field.
    expect(missingChoices(payload, { name_en: { kind: 'yours' } })).toEqual(['description_en', 'status']);
    expect(resolveConflict(payload, { name_en: { kind: 'yours' } })).toEqual({
      ok: false,
      missing: ['description_en', 'status'],
    });

    const result = resolveConflict(payload, {
      name_en: { kind: 'yours' },
      description_en: { kind: 'merged', value: 'Their description, with my addition.' },
      status: { kind: 'theirs' },
    });
    expect(result).toEqual({
      ok: true,
      resolution: {
        base: { fields: current, version: 4 },
        changes: {
          policy_domains: ['domain_a', 'domain_b'],
          name_en: 'My name',
          description_en: 'Their description, with my addition.',
        },
      },
    });
  });

  it('drops values that already equal the current state', () => {
    const current = { ...base, name_en: 'Same new name', description_en: 'Their description.' };
    const payload = conflict(base, current, { name_en: 'Same new name', description_en: 'Mine.' });

    expect(classifyConflict(payload)).toMatchObject({ conflicting: ['description_en'], alreadyCurrent: ['name_en'] });
    // A merged value identical to theirs is no change either.
    const result = resolveConflict(payload, { description_en: { kind: 'merged', value: 'Their description.' } });
    expect(result.ok && result.resolution.changes).toEqual({});
  });

  it('resolves a repeated conflict against the newer state with the re-sent changes', () => {
    // Round 1: base v3, a colleague changed the status (v4); you changed name and status.
    const v4 = { ...base, status: 'paused' };
    const first = conflict(base, v4, { name_en: 'My name', status: 'closed' });
    const round1 = resolveConflict(first, { status: { kind: 'yours' } });
    if (!round1.ok) throw new Error('round 1 should resolve');
    expect(round1.resolution.base.version).toBe(4);
    expect(round1.resolution.changes).toEqual({ name_en: 'My name', status: 'closed' });

    // Round 2: before the re-sent PATCH arrived, another colleague renamed it (v5).
    const v5 = { ...v4, name_en: 'Another name' };
    const second = conflict(
      round1.resolution.base.fields,
      v5,
      round1.resolution.changes,
      round1.resolution.base.version,
    );
    expect(second.base_version).toBe(4);
    expect(classifyConflict(second)).toEqual({
      conflicting: ['name_en'],
      onlyYours: ['status'],
      alreadyCurrent: [],
      onlyTheirs: [],
    });
    const round2 = resolveConflict(second, { name_en: { kind: 'theirs' } });
    expect(round2).toEqual({
      ok: true,
      resolution: { base: { fields: v5, version: 5 }, changes: { status: 'closed' } },
    });
  });

  it('flags fields whose verification by a colleague would be reset', () => {
    const metaChanged: ConflictPayload['meta_changed_since_base'] = {
      name_en: { verified: ['unverified', 'verified'] },
      status: { verified: ['verified', 'unverified'] },
    };
    const payload = {
      ...conflict(base, { ...base }, { name_en: 'My name', status: 'closed' }),
      meta_changed_since_base: metaChanged,
    };
    expect(verificationResetFields(payload, ['name_en', 'status'])).toEqual(['name_en']);
  });

  it('does not let later edits of the payload leak into the new base', () => {
    const payload = conflict(base, { ...base, status: 'paused' }, {});
    const result = resolveConflict(payload, {});
    if (!result.ok) throw new Error('should resolve');
    payload.current.status = 'mutated';
    expect(result.resolution.base.fields.status).toBe('paused');
  });
});
