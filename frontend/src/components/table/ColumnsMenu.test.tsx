import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { EntityTypeMeta, Meta } from '../../api/types';
import { EntityTablePage } from '../../pages/EntityTablePage';
import { mockApi, requestsTo } from '../../test/api-mock';
import { exampleItem, exampleMeta, fieldSpec, listResponse } from '../../test/fixtures';
import { renderRoute } from '../../test/render';

// A synthetic document type: the extracted text is virtual and detail-only, so
// list rows never contain it and the export refuses it (docs/API.md §2, §5).
const documentMeta: EntityTypeMeta = {
  label: 'Document',
  label_plural: 'Documents',
  prefix: 'doc',
  table_view: true,
  default_sort: 'title',
  constraints: [],
  fields: [
    fieldSpec('title', 'string', { label: 'Title', filter: 'text', sortable: true, in_list: true }),
    fieldSpec('publisher', 'string', { label: 'Publisher', filter: 'text', in_list: true }),
    fieldSpec('doc_type', 'string', { label: 'Document type', filter: 'text' }),
    fieldSpec('text', 'text', { label: 'Text', group: 'sources', virtual: true, exportable: false }),
  ],
  quick_filters: [],
};

const meta: Meta = { ...exampleMeta, entity_types: { document: documentMeta } };

const rows = [
  exampleItem('doc_A', { title: 'Example document A', publisher: 'Example publisher', doc_type: 'note' }, { type: 'document' }),
];

function mockDocumentsApi() {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return meta;
    if (url.pathname === '/api/entities/saved_view') return listResponse([]);
    if (url.pathname === '/api/entities/document') return listResponse(rows);
    if (url.pathname === '/api/entities/document/export') {
      return new Response('id,title\r\n', {
        headers: { 'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename="document-export.csv"' },
      });
    }
    return undefined;
  });
}

const DocumentsPage = () => <EntityTablePage type="document" />;

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:example');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('columns and export of a table', () => {
  it('offers only columns with a value per row; a detail-only field from the URL is ignored', async () => {
    mockDocumentsApi();
    const { user } = renderRoute(DocumentsPage, { url: '/documents?cols=title,text', path: '/documents' });

    await screen.findByText('Example document A');
    expect(screen.getByRole('columnheader', { name: /Title/ })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /^Text/ })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Columns' }));
    const sources = screen.queryByRole('group', { name: 'Sources & Evidence' });
    expect(sources).toBeNull();
    expect(screen.queryByRole('checkbox', { name: 'Text' })).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Document type' })).not.toBeChecked();
  });

  it('exports the record ID and the columns the table shows after a column was ticked', async () => {
    const fetchMock = mockDocumentsApi();
    const { user, router } = renderRoute(DocumentsPage, { url: '/documents', path: '/documents' });
    await screen.findByText('Example document A');

    await user.click(screen.getByRole('button', { name: 'Columns' }));
    await user.click(screen.getByRole('checkbox', { name: 'Document type' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ cols: 'title,publisher,doc_type' });
    });

    await user.click(screen.getByRole('button', { name: 'Export' }));
    await user.click(await screen.findByRole('menuitem', { name: /CSV/ }));
    await waitFor(() => {
      expect(requestsTo(fetchMock, '/api/entities/document/export')).toHaveLength(1);
    });
    const [request] = requestsTo(fetchMock, '/api/entities/document/export');
    expect(request?.searchParams.get('cols')).toBe('id,title,publisher,doc_type');
    expect(request?.searchParams.get('format')).toBe('csv');
  });

  it('exports the default columns of the table with the ID when the URL names only unknown columns', async () => {
    const fetchMock = mockDocumentsApi();
    const { user } = renderRoute(DocumentsPage, { url: '/documents?cols=bogus', path: '/documents' });
    const table = await screen.findByRole('table');
    expect(within(table).getByRole('columnheader', { name: /Publisher/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Export' }));
    await user.click(await screen.findByRole('menuitem', { name: /XLSX/ }));
    await waitFor(() => {
      expect(requestsTo(fetchMock, '/api/entities/document/export')).toHaveLength(1);
    });
    expect(requestsTo(fetchMock, '/api/entities/document/export')[0]?.searchParams.get('cols')).toBe('id,title,publisher');
  });
});
