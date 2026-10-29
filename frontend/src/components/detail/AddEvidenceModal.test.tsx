import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { EntityTypeMeta, Item, Meta } from '../../api/types';
import { setAuthor } from '../../lib/author';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { exampleItem, exampleMeta, fieldSpec } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { AddEvidenceModal } from './AddEvidenceModal';
import type { VerificationBase } from './FieldVerificationMenu';

const evidenceMeta: EntityTypeMeta = {
  label: 'Evidence',
  label_plural: 'Evidence',
  prefix: 'evd',
  table_view: false,
  default_sort: '-created_at',
  constraints: [],
  fields: [
    fieldSpec('url', 'url', { label: 'URL' }),
    fieldSpec('retrieved_at', 'datetime', { label: 'Retrieved at' }),
    fieldSpec('quote', 'text', { label: 'Quote' }),
    fieldSpec('locator', 'string', { label: 'Locator' }),
    fieldSpec('description', 'text', { label: 'Description' }),
  ],
  quick_filters: [],
};

const meta: Meta = { ...exampleMeta, entity_types: { ...exampleMeta.entity_types, evidence: evidenceMeta } };
const subject = exampleItem('prj_EXAMPLE', { name_en: 'Example project' });
const nameField = fieldSpec('name_en', 'string', { label: 'Name (EN)' });
const noop = () => undefined;
/** The base captured when the verification menu opened. */
const target = { field: nameField, base: { version: 1, value: 'Example project' } };

/** The record on the "server"; the form reads it again right before posting. */
let server: Item;

function mockEvidenceApi() {
  return mockApi((url, init) => {
    if (url.pathname === '/api/meta') return meta;
    if (url.pathname === '/api/entities/project/prj_EXAMPLE') return { item: server };
    if (url.pathname === '/api/entities/evidence' && init?.method === 'POST') {
      return { item: exampleItem('evd_NEW', {}, { type: 'evidence' }), revision_id: 1, warnings: [] };
    }
    return undefined;
  });
}

const evidencePosts = (fetchMock: ReturnType<typeof mockEvidenceApi>) =>
  callsTo(fetchMock, '/api/entities/evidence').filter((call) => call.init?.method === 'POST');

describe('AddEvidenceModal', () => {
  beforeEach(() => {
    setAuthor('Example Person');
    server = subject;
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it('requires the verbatim quote that a verified field needs (CODEBOOK §2.3)', async () => {
    const fetchMock = mockEvidenceApi();
    const created: string[] = [];
    const Page = () => (
      <AddEvidenceModal subject={subject} target={target} onClose={noop} onCreated={(item) => created.push(item.id)} />
    );
    const { user } = renderRoute(Page, { url: '/projects', path: '/projects' });

    await user.type(await screen.findByRole('textbox', { name: /URL/ }), 'https://example.org/source');
    await user.click(screen.getByRole('button', { name: 'Add evidence and mark verified' }));
    // Without a quote nothing is sent: the server would refuse the verification.
    expect(await screen.findByText('Required.')).toBeInTheDocument();
    expect(callsTo(fetchMock, '/api/entities/evidence')).toHaveLength(0);

    await user.type(screen.getByRole('textbox', { name: /Quote/ }), 'An example quote');
    await user.click(screen.getByRole('button', { name: 'Add evidence and mark verified' }));
    await waitFor(() => {
      expect(created).toEqual(['evd_NEW']);
    });
    const [call] = callsTo(fetchMock, '/api/entities/evidence');
    expect(jsonBody(call?.init)).toMatchObject({
      data: {
        subject_id: 'prj_EXAMPLE',
        target: 'field:name_en',
        url: 'https://example.org/source',
        quote: 'An example quote',
      },
    });
  });

  it('reads the record again and asks before storing evidence for a value that changed meanwhile', async () => {
    const fetchMock = mockEvidenceApi();
    const created: { id: string; base: VerificationBase }[] = [];
    const Page = () => (
      <AddEvidenceModal
        subject={subject}
        target={target}
        onClose={noop}
        onCreated={(item, _field, base) => created.push({ id: item.id, base })}
      />
    );
    const { user } = renderRoute(Page, { url: '/projects', path: '/projects' });
    // The form shows the value the evidence is for: the one seen when the menu opened.
    const shown = await screen.findByRole('group', { name: 'The value this evidence supports' });
    expect(shown).toHaveTextContent('Example project');
    await user.type(await screen.findByRole('textbox', { name: /URL/ }), 'https://example.org/source');
    await user.type(screen.getByRole('textbox', { name: /Quote/ }), 'Example project');

    // A colleague renamed the project while the quote was being copied.
    server = exampleItem(
      'prj_EXAMPLE',
      { name_en: 'Renamed by a colleague' },
      {
        version: 2,
        field_meta: {
          name_en: {
            src: 'manual:Example Colleague',
            by: 'Example Colleague',
            at: '2026-01-02T09:30:00.000000Z',
            locked: true,
            verified: 'unverified',
            evidence_id: null,
            restored_from_version: null,
          },
        },
      },
    );
    await user.click(screen.getByRole('button', { name: 'Add evidence and mark verified' }));

    const question = await screen.findByRole('alert', { name: 'The value changed meanwhile' });
    expect(within(question).getByText('Example Colleague')).toBeInTheDocument();
    expect(within(question).getByText('Renamed by a colleague')).toBeInTheDocument();
    // Nothing is stored before the user decides: no evidence with a wrong value snapshot.
    expect(evidencePosts(fetchMock)).toHaveLength(0);

    await user.click(within(question).getByRole('button', { name: 'Add evidence for the new value' }));
    await waitFor(() => {
      expect(created).toEqual([{ id: 'evd_NEW', base: { version: 2, value: 'Renamed by a colleague' } }]);
    });
    expect(evidencePosts(fetchMock)).toHaveLength(1);
  });

  it('stores the evidence and passes the base on when the value is unchanged', async () => {
    const fetchMock = mockEvidenceApi();
    const created: { id: string; base: VerificationBase }[] = [];
    // Another field changed meanwhile: the value of this one did not.
    server = exampleItem('prj_EXAMPLE', { name_en: 'Example project', notes: 'Changed elsewhere' }, { version: 2 });
    const Page = () => (
      <AddEvidenceModal
        subject={subject}
        target={target}
        onClose={noop}
        onCreated={(item, _field, base) => created.push({ id: item.id, base })}
      />
    );
    const { user } = renderRoute(Page, { url: '/projects', path: '/projects' });
    await user.type(await screen.findByRole('textbox', { name: /URL/ }), 'https://example.org/source');
    await user.type(screen.getByRole('textbox', { name: /Quote/ }), 'Example project');
    await user.click(screen.getByRole('button', { name: 'Add evidence and mark verified' }));

    // The verification is sent with the base version (1): the verifier's 409 rules decide.
    await waitFor(() => {
      expect(created).toEqual([{ id: 'evd_NEW', base: { version: 1, value: 'Example project' } }]);
    });
    expect(evidencePosts(fetchMock)).toHaveLength(1);
    expect(screen.queryByRole('alert', { name: 'The value changed meanwhile' })).toBeNull();
  });
});
