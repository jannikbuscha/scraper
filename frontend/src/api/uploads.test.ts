import { describe, expect, it } from 'vitest';

import { callsTo, mockApi } from '../test/api-mock';
import type { UploadResponse } from './acquisition-types';
import { ApiError } from './client';
import { uploadFile } from './uploads';

const RESPONSE: UploadResponse = {
  upload: {
    id: 'raw_EXAMPLE',
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
    filename: 'example page.html',
    sha256: 'abc',
    size: 30,
  },
  suggested: { title: 'Example title', language: 'en', publisher: null, extraction_method: 'html', char_count: 12, warnings: [] },
};

describe('uploadFile', () => {
  it('sends the raw file as the body and its name in the query', async () => {
    const fetchMock = mockApi((url) => (url.pathname === '/api/uploads' ? RESPONSE : undefined));
    const file = new File(['<p>Example page</p>'], 'example page.html', { type: 'text/html' });

    await expect(uploadFile(file)).resolves.toEqual(RESPONSE);

    const [call] = callsTo(fetchMock, '/api/uploads');
    expect(call?.url.searchParams.get('filename')).toBe('example page.html');
    expect(call?.init?.method).toBe('POST');
    // The File itself, never JSON or multipart.
    expect(call?.init?.body).toBe(file);
    expect(new Headers(call?.init?.headers).get('Content-Type')).toBeNull();
  });

  it('reports the server error envelope as ApiError', async () => {
    mockApi(
      () =>
        new Response(JSON.stringify({ error: { code: 'validation_error', message: 'Empty', details: { body: ['empty'] } } }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    const error: unknown = await uploadFile(new File([''], 'empty.txt')).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, code: 'validation_error' });
  });
});
