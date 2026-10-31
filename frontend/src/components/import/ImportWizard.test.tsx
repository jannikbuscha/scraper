import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ImportPreview, ImportRunResponse, Plan, UploadResponse } from '../../api/acquisition-types';
import { p2Meta } from '../../test/acquisition-fixtures';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { renderRoute } from '../../test/render';
import { ImportWizard } from './ImportWizard';

const UPLOAD: UploadResponse = {
  upload: {
    id: 'raw_CSV',
    run_id: null,
    source_id: 'manual',
    via: 'upload',
    url: null,
    final_url: null,
    redirects: [],
    http_status: null,
    fetched_at: '2026-01-01T00:00:00.000000Z',
    headers: {},
    content_type: 'text/csv',
    filename: 'example.csv',
    sha256: 'abc',
    size: 30,
  },
  suggested: { title: null, language: null, publisher: null, extraction_method: 'none', char_count: 0, warnings: [] },
};

const PREVIEW: ImportPreview = {
  sheets: null,
  columns: ['slug', 'notes'],
  preview: [['example-a', 'Example note']],
  suggested_mapping: { slug: 'slug' },
  importable_fields: ['slug', 'name_en', 'notes'],
  key_fields: ['id', 'slug'],
};

const PLAN: Plan = {
  stats: { rows: 1, create: 0, update: 1, unchanged: 0, conflicts: 0, errors: 0 },
  rows: [{ row: 2, action: 'update', id: 'prj_A', changes: { notes: [null, 'Example note'] }, conflicts: [], errors: {} }],
};

const RESULT: ImportRunResponse = {
  import: {
    id: 'imp_EXAMPLE',
    upload_id: 'raw_CSV',
    filename: 'example.csv',
    file_label: 'example.csv#abc',
    entity_type: 'project',
    sheet: null,
    status: 'done',
    mapping: { slug: 'slug', notes: 'notes' },
    key_field: 'slug',
    note: null,
    stats: PLAN.stats,
    errors: [],
    error: null,
    created_at: '2026-01-01T00:00:00.000000Z',
    finished_at: '2026-01-01T00:00:01.000000Z',
  },
  result: PLAN,
};

describe('import workflow (docs/UI.md §8.5)', () => {
  it('uploads, previews, dry-runs with the current mapping and runs after confirmation', async () => {
    const fetchMock = mockApi((url) => {
      if (url.pathname === '/api/uploads') return UPLOAD;
      if (url.pathname === '/api/imports/preview') return PREVIEW;
      if (url.pathname === '/api/imports/dry-run') return { plan: PLAN };
      if (url.pathname === '/api/imports') return RESULT;
      return undefined;
    });
    const Page = () => <ImportWizard meta={p2Meta} />;
    const { user } = renderRoute(Page, { url: '/import', path: '/import' });

    await user.click(await screen.findByRole('combobox', { name: 'Record type' }));
    await user.click(await screen.findByRole('option', { name: 'Projects' }));
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('no file input');
    await user.upload(input, new File(['slug,notes\nexample-a,Example note\n'], 'example.csv', { type: 'text/csv' }));

    // The suggestion maps slug; the key defaults to the mapped natural key.
    const notes = await screen.findByRole('combobox', { name: 'Field for column notes' });
    expect(screen.getByRole('combobox', { name: 'Field for column slug' })).toHaveValue('Slug');
    expect(screen.getByRole('combobox', { name: 'Key' })).toHaveValue('Slug');
    expect(screen.getByRole('button', { name: 'Run import' })).toBeDisabled();

    await user.click(notes);
    await user.click(await screen.findByRole('option', { name: 'notes' }));
    await user.click(screen.getByRole('button', { name: 'Dry run' }));
    expect(await screen.findByLabelText('Update: 1')).toBeInTheDocument();
    expect(jsonBody(callsTo(fetchMock, '/api/imports/dry-run')[0]?.init)).toEqual({
      upload_id: 'raw_CSV',
      entity_type: 'project',
      sheet: null,
      mapping: { slug: 'slug', notes: 'notes' },
      key_field: 'slug',
    });

    await user.click(screen.getByRole('button', { name: 'Run import' }));
    const confirm = within(await screen.findByRole('dialog', { name: 'Run the import' }));
    await user.click(confirm.getByRole('button', { name: 'Import 1 rows' }));
    const result = await screen.findByRole('region', { name: 'Import result' });
    expect(within(result).getByRole('link', { name: 'Show changes' })).toHaveAttribute('href', '/changes?batch_id=imp_EXAMPLE');
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/imports')).toHaveLength(1);
    });
    expect(jsonBody(callsTo(fetchMock, '/api/imports')[0]?.init)).toMatchObject({ mapping: { slug: 'slug', notes: 'notes' }, key_field: 'slug', note: null });
  });

  it('asks for a new dry run after the mapping changes', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/uploads') return UPLOAD;
      if (url.pathname === '/api/imports/preview') return PREVIEW;
      if (url.pathname === '/api/imports/dry-run') return { plan: PLAN };
      return undefined;
    });
    const Page = () => <ImportWizard meta={p2Meta} />;
    const { user } = renderRoute(Page, { url: '/import', path: '/import' });
    await user.click(await screen.findByRole('combobox', { name: 'Record type' }));
    await user.click(await screen.findByRole('option', { name: 'Projects' }));
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('no file input');
    await user.upload(input, new File(['slug\nexample-a\n'], 'example.csv', { type: 'text/csv' }));
    await user.click(await screen.findByRole('button', { name: 'Dry run' }));
    await screen.findByLabelText('Update: 1');
    expect(screen.getByRole('button', { name: 'Run import' })).toBeEnabled();

    await user.click(screen.getByRole('combobox', { name: 'Field for column notes' }));
    await user.click(await screen.findByRole('option', { name: 'notes' }));
    expect(screen.getByRole('button', { name: 'Run import' })).toBeDisabled();
    expect(screen.getByText(/The mapping changed since this dry run/)).toBeInTheDocument();
  });
});
