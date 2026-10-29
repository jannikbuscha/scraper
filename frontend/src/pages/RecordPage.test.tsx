import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { Comment, EntityTypeMeta, Item, Meta } from '../api/types';
import { callsTo, jsonBody, mockApi } from '../test/api-mock';
import { exampleItem, exampleMeta, exampleVocabularies, fieldSpec, listResponse, projectMeta } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { EntityDetailPage } from './EntityDetailPage';
import { RecordPage } from './RecordPage';

// Synthetic metadata and values; nothing here describes the real portfolio.
const evidenceMeta: EntityTypeMeta = {
  label: 'Evidence',
  label_plural: 'Evidence',
  prefix: 'evd',
  table_view: false,
  default_sort: '-created_at',
  constraints: [{ one_of_required: ['document_id', 'url'] }],
  fields: [
    fieldSpec('subject_id', 'ref', { label: 'Subject', ref_types: ['project'], create_only: true, in_list: true }),
    fieldSpec('target', 'string', { label: 'Target', create_only: true, in_list: true }),
    fieldSpec('url', 'url', { label: 'URL', group: 'basics' }),
    fieldSpec('quote', 'text', { label: 'Quote' }),
    fieldSpec('verification_status', 'vocab', {
      label: 'Verification status',
      vocabulary: 'verification_status',
      required: true,
      default: 'unverified',
    }),
    fieldSpec('version', 'int', { label: 'Version', group: 'system', editable: false, system: true }),
  ],
  quick_filters: [],
};

const meta: Meta = {
  ...exampleMeta,
  groups: [...exampleMeta.groups, { key: 'sources', label: 'Sources & Evidence' }],
  entity_types: { project: projectMeta, evidence: evidenceMeta },
};

const EVIDENCE_ID = 'evd_EXAMPLE';
const EVIDENCE_PATH = `/api/entities/evidence/${EVIDENCE_ID}`;
const SUBJECT = { id: 'prj_EXAMPLE', type: 'project' as const, label: 'Example project', deleted: false };

/** The evidence row on the "server"; tests change it. */
let evidence: Item;
/** Queued responses per write path; without one, a write succeeds. */
let responses: Record<string, (() => Response)[]>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const thread: Comment = {
  id: 'cmt_EXAMPLE',
  subject_id: EVIDENCE_ID,
  subject_type: 'evidence',
  subject_label: 'Name (EN) · Example project',
  field: null,
  parent_id: null,
  body_md: 'Is this quote complete?',
  body_html: '<p>Is this quote complete?</p>',
  status: 'open',
  resolved_by: null,
  resolved_at: null,
  created_at: '2026-01-02T10:00:00.000000Z',
  created_by: 'user',
  updated_at: '2026-01-02T10:00:00.000000Z',
  updated_by: 'user',
  version: 1,
  edited: false,
  deleted_at: null,
  deleted_by: null,
};

function mockRecordApi() {
  return mockApi((url, init) => {
    const write = init?.method && init.method !== 'GET' ? responses[url.pathname]?.shift() : undefined;
    if (write) return write();
    if (url.pathname === '/api/meta') return meta;
    if (url.pathname === EVIDENCE_PATH) {
      if (init?.method === 'PATCH') {
        evidence = { ...evidence, version: evidence.version + 1 };
        return { item: evidence, changed: true, revision_id: 10, warnings: [] };
      }
      return { item: evidence };
    }
    if (url.pathname === `${EVIDENCE_PATH}/revisions`) return { items: [], total: 0, page: 1, page_size: 50, refs: {} };
    if (url.pathname === '/api/comments') return { threads: [{ root: thread, replies: [] }] };
    if (url.pathname === '/api/entities/project/prj_EXAMPLE') {
      return { item: exampleItem('prj_EXAMPLE', { name_en: 'Example project' }) };
    }
    if (url.pathname === '/api/entities/evidence') return listResponse([evidence]);
    if (/^\/api\/entities\/[a-z_]+$/.test(url.pathname)) return listResponse([]);
    return undefined;
  });
}

beforeEach(() => {
  responses = {};
  evidence = exampleItem(
    EVIDENCE_ID,
    {
      subject_id: SUBJECT.id,
      target: 'field:name_en',
      url: 'https://example.org/source',
      quote: 'Example project',
      verification_status: 'unverified',
    },
    { type: 'evidence', label: 'Name (EN) · Example project', refs: { subject_id: SUBJECT }, derived: null },
  );
});

const EvidencePage = () => <RecordPage id={EVIDENCE_ID} />;

describe('the generic record page', () => {
  it('shows an evidence row with its subject, actions, history and comments', async () => {
    mockRecordApi();
    const { user } = renderRoute(EvidencePage, {
      url: `/records/${EVIDENCE_ID}?comments=open`,
      path: '/records/$id',
      vocabularies: exampleVocabularies,
    });

    expect(await screen.findByRole('heading', { name: 'Name (EN) · Example project', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled();
    // The subject it supports is linked; evidence fields are not field-verified themselves.
    const related = screen.getByRole('region', { name: 'Related records' });
    expect(within(related).getByRole('link', { name: 'Example project' })).toHaveAttribute('href', '/projects/prj_EXAMPLE');
    expect(screen.queryByRole('button', { name: /^Verification of/ })).toBeNull();
    // Comments on the evidence open here (a thread link from the Comments page lands on this page).
    const panel = await screen.findByRole('complementary', { name: 'Comments' });
    expect(await within(panel).findByText('Is this quote complete?')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'History' }));
    expect(await screen.findByText(/0 revisions/)).toBeInTheDocument();
  });

  it('edits a wrong quote through the usual edit form', async () => {
    const fetchMock = mockRecordApi();
    const { user } = renderRoute(EvidencePage, { url: `/records/${EVIDENCE_ID}`, path: '/records/$id' });
    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    const quote = await screen.findByRole('textbox', { name: 'Quote' });
    await user.clear(quote);
    await user.type(quote, 'Example project (corrected)');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(
        callsTo(fetchMock, EVIDENCE_PATH)
          .filter((call) => call.init?.method === 'PATCH')
          .map((call) => jsonBody(call.init)),
      ).toEqual([{ changes: { quote: 'Example project (corrected)' }, note: null }]);
    });
  });

  it('explains why evidence that a verification rests on cannot be deleted, without a cascade', async () => {
    const fetchMock = mockRecordApi();
    responses[`${EVIDENCE_PATH}/delete`] = [
      () =>
        json(
          { error: { code: 'has_dependents', message: 'A field verification rests on it.', details: { field_verification: 1 } } },
          409,
        ),
    ];
    const { user } = renderRoute(EvidencePage, { url: `/records/${EVIDENCE_ID}`, path: '/records/$id' });
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete record' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await within(dialog).findByText('A verified field rests on this evidence')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Example project' })).toBeInTheDocument();
    // No "Delete with dependents": a cascade would be refused as well.
    expect(within(dialog).queryByRole('button', { name: /^Delete/ })).toBeNull();
    expect(callsTo(fetchMock, `${EVIDENCE_PATH}/delete`)).toHaveLength(1);
  });
});

describe('related evidence on a detail page', () => {
  it('links each evidence row to its record page', async () => {
    mockRecordApi();
    const ProjectPage = () => <EntityDetailPage type="project" id="prj_EXAMPLE" />;
    renderRoute(ProjectPage, { url: '/projects/prj_EXAMPLE', path: '/projects/$id' });
    const section = await screen.findByRole('region', { name: 'Evidence' });
    expect(await within(section).findByRole('link', { name: 'Name (EN) · Example project' })).toHaveAttribute(
      'href',
      `/records/${EVIDENCE_ID}`,
    );
  });
});
