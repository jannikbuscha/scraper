import { describe, expect, it } from 'vitest';

import type { EntityTypeMeta } from '../../api/types';
import { exampleItem, fieldSpec } from '../../test/fixtures';
import {
  changedValues,
  editableFields,
  editErrors,
  hasEditErrors,
  serviceSubtree,
  sessionFromResolution,
  startEditSession,
} from './edit-session';

const typeMeta: EntityTypeMeta = {
  label: 'Project',
  label_plural: 'Projects',
  prefix: 'prj',
  table_view: true,
  default_sort: 'name_en',
  constraints: [{ one_of_required: ['name_en', 'name_uk'] }],
  fields: [
    fieldSpec('name_en', 'string', { label: 'Name (EN)' }),
    fieldSpec('name_uk', 'string', { label: 'Name (UK)' }),
    fieldSpec('official_urls', 'url_list', { label: 'Official URLs' }),
    fieldSpec('in_paper_scope', 'bool', { label: 'In paper scope', required: true }),
    fieldSpec('scope_note', 'text', { label: 'Scope note' }),
    fieldSpec('verification_status', 'vocab', {
      label: 'Verification',
      vocabulary: 'verification_status',
      required: true,
    }),
    fieldSpec('canonical_url', 'url', { label: 'Canonical URL', system: true, editable: false }),
    fieldSpec('period', 'vocab', { label: 'Period', derived: true, editable: false }),
    fieldSpec('links', 'doc_links', { label: 'Links' }),
  ],
  quick_filters: [],
};

const makeItem = () =>
  exampleItem(
    'prj_EXAMPLE',
    {
      name_en: 'Example project',
      name_uk: null,
      official_urls: ['https://example.org/'],
      in_paper_scope: false,
      scope_note: 'Example reason.',
      verification_status: 'unverified',
      canonical_url: null,
      links: [],
    },
    { version: 7 },
  );
const item = makeItem();

describe('edit session', () => {
  it('freezes a copy of the fields and the version when editing starts', () => {
    const cached = makeItem();
    const session = startEditSession(cached);
    expect(session.base).toEqual({ fields: cached.fields, version: 7 });
    cached.fields.name_en = 'Changed in the cache';
    expect(session.base.fields.name_en).toBe('Example project');
    expect(session.values.name_en).toBe('Example project');
  });

  it('edits only stored, editable, non-structural fields', () => {
    expect(editableFields(typeMeta).map((field) => field.name)).toEqual([
      'name_en',
      'name_uk',
      'official_urls',
      'in_paper_scope',
      'scope_note',
      'verification_status',
    ]);
  });

  it('sends only the values that differ from the base, list order included', () => {
    const session = startEditSession(item);
    const fields = editableFields(typeMeta);
    expect(changedValues(session, fields)).toEqual({});

    session.values = { ...session.values, name_uk: 'Приклад', official_urls: ['https://example.org/'] };
    expect(changedValues(session, fields)).toEqual({ name_uk: 'Приклад' });

    session.values = { ...session.values, official_urls: ['https://example.org/', 'https://example.net/'] };
    expect(changedValues(session, fields)).toEqual({
      name_uk: 'Приклад',
      official_urls: ['https://example.org/', 'https://example.net/'],
    });
  });

  it('asks for a new scope note when the scope changes and for a note when verifying', () => {
    const session = startEditSession(item);
    session.values = { ...session.values, in_paper_scope: true };
    let changes = changedValues(session, editableFields(typeMeta));
    expect(editErrors(session, typeMeta, changes, '').scopeNote).not.toBeNull();

    session.values = { ...session.values, scope_note: 'Example reason for the new scope.' };
    changes = changedValues(session, editableFields(typeMeta));
    expect(editErrors(session, typeMeta, changes, '').scopeNote).toBeNull();

    session.values = { ...session.values, verification_status: 'verified' };
    changes = changedValues(session, editableFields(typeMeta));
    expect(editErrors(session, typeMeta, changes, ' ').note).not.toBeNull();
    expect(hasEditErrors(editErrors(session, typeMeta, changes, 'Checked the example source'))).toBe(false);
  });

  it('checks the "one of" constraint and the format of changed values', () => {
    const session = startEditSession(item);
    session.values = { ...session.values, name_en: '  ', official_urls: ['javascript:alert(1)'] };
    const errors = editErrors(session, typeMeta, changedValues(session, editableFields(typeMeta)), '');
    expect(errors.fields.name_en).toMatch(/at least one of Name \(EN\) or Name \(UK\)/);
    expect(errors.fields.official_urls).toMatch(/http/);
  });

  it('continues after a conflict from the current state with the chosen values', () => {
    const session = sessionFromResolution({
      base: { fields: { ...item.fields, name_en: 'Their name' }, version: 8 },
      changes: { scope_note: 'My reason.' },
    });
    expect(session.base.version).toBe(8);
    expect(changedValues(session, editableFields(typeMeta))).toEqual({ scope_note: 'My reason.' });
  });

  it('excludes the service itself and all its descendants from the parent picker', () => {
    const service = (id: string, parent: string | null) => exampleItem(id, { parent_service_id: parent });
    const services = [
      service('svc_ROOT', null),
      service('svc_CHILD', 'svc_ROOT'),
      service('svc_GRANDCHILD', 'svc_CHILD'),
      service('svc_SIBLING', null),
      service('svc_NEPHEW', 'svc_SIBLING'),
    ];
    expect(serviceSubtree('svc_ROOT', services)).toEqual(['svc_ROOT', 'svc_CHILD', 'svc_GRANDCHILD']);
    expect(serviceSubtree('svc_NEPHEW', services)).toEqual(['svc_NEPHEW']);
  });
});
