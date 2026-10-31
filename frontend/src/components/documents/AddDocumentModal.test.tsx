import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { UploadResponse } from '../../api/acquisition-types';
import { exampleRun } from '../../test/acquisition-fixtures';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { exampleItem, exampleMeta, fieldSpec } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { ApiError } from '../../api/client';
import { AddDocumentModal, fetchProblem, parseCaptureUrl } from './AddDocumentModal';

const META = {
  ...exampleMeta,
  entity_types: {
    document: {
      label: 'Document',
      label_plural: 'Documents',
      prefix: 'doc',
      table_view: true,
      default_sort: '-published',
      constraints: [],
      quick_filters: [],
      fields: [
        fieldSpec('title', 'string', { label: 'Title', required: true, in_create: true }),
        fieldSpec('url', 'url', { label: 'URL', in_create: true }),
        fieldSpec('retrieved_at', 'datetime', { label: 'Retrieved at', in_create: true }),
        fieldSpec('publisher', 'string', { label: 'Publisher', in_create: true }),
      ],
    },
  },
};

const UPLOAD: UploadResponse = {
  upload: {
    id: 'raw_UPLOAD',
    run_id: null,
    source_id: 'manual',
    via: 'upload',
    url: null,
    final_url: null,
    redirects: [],
    http_status: null,
    fetched_at: '2026-01-01T00:00:00.000000Z',
    headers: {},
    content_type: 'text/html',
    filename: 'example.html',
    sha256: 'abc',
    size: 64,
  },
  suggested: {
    title: 'Example page title',
    language: null,
    publisher: null,
    extraction_method: 'html',
    char_count: 40,
    warnings: [{ code: 'no_text_layer', message: 'Example warning', field: null }],
  },
};

describe('adding a document (docs/UI.md §8.6)', () => {
  it('uploads the file, prefills the suggestion, creates the document and offers Tag now', async () => {
    const fetchMock = mockApi((url) => {
      if (url.pathname === '/api/meta') return META;
      if (url.pathname === '/api/uploads') return UPLOAD;
      if (url.pathname === '/api/documents/manual') {
        return { item: exampleItem('doc_NEW', { title: 'Example page title' }, { type: 'document', label: 'Example page title' }), revision_id: 1, warnings: [] };
      }
      if (url.pathname === '/api/runs') return { run: exampleRun({ id: 'run_TAG', collector: 'tagger' }) };
      if (url.pathname === '/api/runs/run_TAG') return { run: exampleRun({ id: 'run_TAG', collector: 'tagger', status: 'succeeded' }) };
      return undefined;
    });
    const Page = () => <AddDocumentModal opened onClose={vi.fn()} />;
    const { user } = renderRoute(Page, { url: '/documents', path: '/documents' });
    const dialog = within(await screen.findByRole('dialog'));

    await dialog.findByRole('tab', { name: 'Upload file' });
    const file = new File(['<title>Example page title</title>'], 'example.html', { type: 'text/html' });
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('no file input');
    await user.upload(input, file);

    const [uploadCall] = callsTo(fetchMock, '/api/uploads');
    expect(uploadCall?.url.searchParams.get('filename')).toBe('example.html');
    expect(uploadCall?.init?.body).toBe(file);

    const title = await dialog.findByRole('textbox', { name: /Title/ });
    expect(title).toHaveValue('Example page title');
    expect(dialog.getByText('Example warning')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/documents/manual')).toHaveLength(1);
    });
    // Without a source URL no retrieval time is sent.
    expect(jsonBody(callsTo(fetchMock, '/api/documents/manual')[0]?.init)).toEqual({
      snapshot_id: 'raw_UPLOAD',
      title: 'Example page title',
      note: null,
    });

    await user.click(await dialog.findByRole('button', { name: 'Tag now' }));
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/runs')).toHaveLength(1);
    });
    expect(jsonBody(callsTo(fetchMock, '/api/runs')[0]?.init)).toEqual({ collector: 'tagger', params: { document_ids: ['doc_NEW'] } });
    expect(await dialog.findByRole('link', { name: 'Tagging run' })).toBeInTheDocument();
    expect(dialog.getByRole('button', { name: 'Open' })).toBeInTheDocument();
  });

  it('explains failed fetches and reads Wayback capture URLs', () => {
    expect(parseCaptureUrl('https://web.archive.org/web/20200102030405id_/https://example.org/page')).toEqual({
      timestamp: '20200102030405',
      original: 'https://example.org/page',
    });
    expect(parseCaptureUrl('https://example.org/page')).toBeNull();
    const blocked = new ApiError(502, 'fetch_failed', 'Failed', { reason: 'blocked', status: 403 });
    const { container } = render(<>{fetchProblem(blocked)}</>);
    expect(container).toHaveTextContent('blocked, HTTP 403');
    expect(container).toHaveTextContent('archived copy');
    const contact = new ApiError(409, 'collector_unavailable', 'No', { reason: 'contact_email_missing' });
    expect(render(<>{fetchProblem(contact)}</>).container).toHaveTextContent('CONTACT_EMAIL');
  });
});
