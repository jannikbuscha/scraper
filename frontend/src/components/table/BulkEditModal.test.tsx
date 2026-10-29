import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { BulkRequest, BulkResult, Vocabulary } from '../../api/types';
import { EntityTablePage } from '../../pages/EntityTablePage';
import { jsonBody, mockApi } from '../../test/api-mock';
import { exampleItem, exampleMeta, exampleVocabularies, listResponse } from '../../test/fixtures';
import { renderRoute } from '../../test/render';

const result = (id: string, status: BulkResult['status'], extra: Partial<BulkResult> = {}): BulkResult => ({
  id,
  status,
  version: null,
  error: null,
  ...extra,
});

/** Bulk responses, in request order. */
let bulkResponses: BulkResult[][];
let bulkBodies: BulkRequest[];

function mockProjectsApi() {
  return mockApi((url, init) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/entities/saved_view') return listResponse([]);
    if (url.pathname === '/api/entities/project') {
      return listResponse([
        exampleItem('prj_A', { name_en: 'Example project A', paper_cluster: 'cluster_a' }, { version: 3 }),
        exampleItem('prj_B', { name_en: 'Example project B', paper_cluster: null }, { version: 7 }),
      ]);
    }
    if (url.pathname === '/api/entities/project/bulk' && init?.method === 'POST') {
      bulkBodies.push(jsonBody(init) as BulkRequest);
      return { batch_id: `batch_${bulkBodies.length}`, results: bulkResponses.shift() ?? [] };
    }
    return undefined;
  });
}

const ProjectsPage = () => <EntityTablePage type="project" />;

async function selectBothRows(user: ReturnType<typeof renderRoute>['user']) {
  await user.click(await screen.findByRole('checkbox', { name: 'Select Example project A' }));
  await user.click(screen.getByRole('checkbox', { name: 'Select Example project B' }));
  expect(screen.getByText('2 selected')).toBeInTheDocument();
}

describe('bulk edit', () => {
  beforeEach(() => {
    bulkResponses = [];
    bulkBodies = [];
  });

  it('sends the selected IDs and shows the result per row', async () => {
    mockProjectsApi();
    const { user } = renderRoute(ProjectsPage, { url: '/projects', path: '/projects', vocabularies: exampleVocabularies });
    await selectBothRows(user);
    await user.click(screen.getByRole('button', { name: 'Bulk edit…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Bulk edit · 2 projects' });

    await user.click(within(dialog).getByRole('combobox', { name: 'Field' }));
    await user.click(await screen.findByRole('option', { name: 'Paper cluster' }));
    await user.click(within(dialog).getByRole('combobox', { name: 'New value' }));
    await user.click(await screen.findByRole('option', { name: /Example cluster B/ }));

    bulkResponses.push([
      result('prj_A', 'updated', { version: 4 }),
      result('prj_B', 'error', { error: { code: 'validation_error', message: 'Example refusal.' } }),
    ]);
    await user.click(within(dialog).getByRole('button', { name: 'Apply' }));

    await within(dialog).findByText('Updated: 1');
    expect(bulkBodies[0]).toEqual({ ids: ['prj_A', 'prj_B'], set: { paper_cluster: 'cluster_b' }, note: null });
    expect(within(dialog).getByText('Error: 1')).toBeInTheDocument();
    expect(within(dialog).getByText(/Example refusal\./)).toHaveTextContent('Example project B: Example refusal.');
  });

  it('requires a note to mark rows verified', async () => {
    mockProjectsApi();
    const { user } = renderRoute(ProjectsPage, { url: '/projects', path: '/projects', vocabularies: exampleVocabularies });
    await selectBothRows(user);
    await user.click(screen.getByRole('button', { name: 'Mark verified…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Mark verified · 2 projects' });

    await user.click(within(dialog).getByRole('button', { name: 'Mark verified' }));
    expect(within(dialog).getByText('Setting verified or disputed needs a note.')).toBeInTheDocument();
    expect(bulkBodies).toHaveLength(0);

    bulkResponses.push([result('prj_A', 'updated', { version: 4 }), result('prj_B', 'unchanged', { version: 7 })]);
    await user.type(within(dialog).getByRole('textbox', { name: /Change note/ }), 'Checked against the example source');
    await user.click(within(dialog).getByRole('button', { name: 'Mark verified' }));

    await within(dialog).findByText('Unchanged: 1');
    expect(bulkBodies[0]).toEqual({
      ids: ['prj_A', 'prj_B'],
      set: { verification_status: 'verified' },
      note: 'Checked against the example source',
    });
  });

  it('offers the inactive codes the selected rows carry for removal, but not for adding', async () => {
    // Example domain B was deactivated; both rows still carry it.
    const vocabularies: Vocabulary[] = exampleVocabularies.map((vocabulary) =>
      vocabulary.name === 'example_domain'
        ? {
            ...vocabulary,
            terms: vocabulary.terms.map((term) => (term.code === 'domain_b' ? { ...term, active: false } : term)),
          }
        : vocabulary,
    );
    mockApi((url, init) => {
      if (url.pathname === '/api/meta') return exampleMeta;
      if (url.pathname === '/api/entities/saved_view') return listResponse([]);
      if (url.pathname === '/api/entities/project') {
        return listResponse([
          exampleItem('prj_A', { name_en: 'Example project A', policy_domains: ['domain_a', 'domain_b'] }),
          exampleItem('prj_B', { name_en: 'Example project B', policy_domains: ['domain_b'] }),
        ]);
      }
      if (url.pathname === '/api/entities/project/bulk' && init?.method === 'POST') {
        bulkBodies.push(jsonBody(init) as BulkRequest);
        return { batch_id: 'batch_1', results: [result('prj_A', 'updated'), result('prj_B', 'updated')] };
      }
      return undefined;
    });
    const { user } = renderRoute(ProjectsPage, { url: '/projects', path: '/projects', vocabularies });
    await selectBothRows(user);
    await user.click(screen.getByRole('button', { name: 'Bulk edit…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Bulk edit · 2 projects' });
    await user.click(within(dialog).getByRole('combobox', { name: 'Field' }));
    await user.click(await screen.findByRole('option', { name: 'Policy domains' }));

    // Add: active codes only.
    await user.click(within(dialog).getByText('Add'));
    await user.click(within(dialog).getByRole('combobox', { name: 'Values to add' }));
    expect(await screen.findByRole('option', { name: /Example domain A/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Example domain B/ })).toBeNull();

    // Remove: the deactivated code the rows carry is offered and can be removed.
    await user.click(within(dialog).getByText('Remove'));
    await user.click(within(dialog).getByRole('combobox', { name: 'Values to remove' }));
    await user.click(await screen.findByRole('option', { name: /Example domain B \(inactive\)/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Apply' }));
    await waitFor(() => {
      expect(bulkBodies).toHaveLength(1);
    });
    expect(bulkBodies[0]).toEqual({ ids: ['prj_A', 'prj_B'], remove: { policy_domains: ['domain_b'] }, note: null });
  });
});
