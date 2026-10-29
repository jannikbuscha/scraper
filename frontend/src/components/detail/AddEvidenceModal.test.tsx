import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { EntityTypeMeta, Meta } from '../../api/types';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { exampleItem, exampleMeta, fieldSpec } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { AddEvidenceModal } from './AddEvidenceModal';

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

function mockEvidenceApi() {
  return mockApi((url, init) => {
    if (url.pathname === '/api/meta') return meta;
    if (url.pathname === '/api/entities/evidence' && init?.method === 'POST') {
      return { item: exampleItem('evd_NEW', {}, { type: 'evidence' }), revision_id: 1, warnings: [] };
    }
    return undefined;
  });
}

describe('AddEvidenceModal', () => {
  it('shows the supported value and requires the verbatim quote that a verified field needs (CODEBOOK §2.3)', async () => {
    const fetchMock = mockEvidenceApi();
    const created: string[] = [];
    const Page = () => (
      <AddEvidenceModal subject={subject} field={nameField} onClose={noop} onCreated={(item) => created.push(item.id)} />
    );
    const { user } = renderRoute(Page, { url: '/projects', path: '/projects' });
    const shown = await screen.findByRole('group', { name: 'The value this evidence supports' });
    expect(shown).toHaveTextContent('Example project');

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
});
