import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { MergePreview } from '../../api/acquisition-types';
import { p2Meta, p2Vocabularies } from '../../test/acquisition-fixtures';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { exampleItem } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { buildMergeFields, choicesOf } from './merge-fields';
import { MergeDialog } from './MergeDialog';

const PREVIEW: MergePreview = {
  fields: [
    { name: 'name_en', survivor: 'Example service A', merged: 'Example service B', list: false, default: 'survivor' },
    { name: 'channels', survivor: ['domain_a'], merged: ['domain_b'], list: true, default: 'survivor' },
    { name: 'status', survivor: 'active', merged: 'suspended', list: false, default: 'survivor' },
  ],
  repoint: { event: 2 },
  conflicts: [],
};

function renderDialog(preview: MergePreview = PREVIEW) {
  const onMerged = vi.fn();
  const fetchMock = mockApi((url) => {
    if (url.pathname === '/api/meta') return p2Meta;
    if (url.pathname.endsWith('/merge-preview')) return preview;
    if (url.pathname.endsWith('/merge')) {
      return { item: exampleItem('svc_A', { name_en: 'Example service A' }, { type: 'service' }), merge_id: 'mrg_1', batch_id: 'b', revision_ids: [1] };
    }
    if (url.pathname === '/api/lookup') return { items: [] };
    return undefined;
  });
  const Page = () => (
    <MergeDialog
      type="service"
      opened
      survivor={{ id: 'svc_A', label: 'Example service A' }}
      merged={{ id: 'svc_B', label: 'Example service B' }}
      proposalId="prp_DUP"
      onClose={vi.fn()}
      onMerged={onMerged}
    />
  );
  const rendered = renderRoute(Page, { url: '/review', path: '/review', vocabularies: p2Vocabularies });
  return { ...rendered, fetchMock, onMerged };
}

describe('merge dialog (docs/UI.md §8.7)', () => {
  it('builds `fields` from the choices, with union only for lists', () => {
    expect(choicesOf({ list: false })).toEqual(['survivor', 'merged']);
    expect(choicesOf({ list: true })).toEqual(['survivor', 'merged', 'union']);
    expect(buildMergeFields(PREVIEW.fields, { name_en: 'merged', channels: 'union', status: 'union' })).toEqual({
      name_en: 'merged',
      channels: 'union',
      // union is not a choice for a single value: the default stays.
      status: 'survivor',
    });
  });

  it('sends the chosen value per differing field, the pair and the proposal', async () => {
    const { user, fetchMock, onMerged } = renderDialog();
    const dialog = within(await screen.findByRole('dialog'));
    expect(await dialog.findByText('References that move to the survivor: 2 events. Evidence and comments stay on the merged record.')).toBeInTheDocument();
    await user.click(within(dialog.getByRole('radiogroup', { name: 'Value of Name (EN)' })).getByText('Take other'));
    await user.click(within(dialog.getByRole('radiogroup', { name: 'Value of Channels' })).getByText('Both'));
    await user.click(dialog.getByRole('button', { name: 'Merge' }));
    await waitFor(() => {
      expect(onMerged).toHaveBeenCalled();
    });
    const [call] = callsTo(fetchMock, '/api/entities/service/svc_A/merge');
    expect(jsonBody(call?.init)).toEqual({
      merged_id: 'svc_B',
      fields: { name_en: 'merged', channels: 'union', status: 'survivor' },
      note: null,
      proposal_id: 'prp_DUP',
    });
  });

  it('swaps survivor and merged record, and refuses to merge while there are conflicts', async () => {
    const { user, fetchMock } = renderDialog({
      ...PREVIEW,
      conflicts: [{ kind: 'relation', id: 'rel_1', label: 'Example relation', message: 'A relation links the two records.' }],
    });
    const dialog = within(await screen.findByRole('dialog'));
    expect(await dialog.findByText(/A relation links the two records\./)).toBeInTheDocument();
    expect(dialog.getByRole('button', { name: 'Merge' })).toBeDisabled();
    await user.click(dialog.getByRole('button', { name: 'Swap survivor and merged record' }));
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/entities/service/svc_B/merge-preview')).toHaveLength(1);
    });
    expect(callsTo(fetchMock, '/api/entities/service/svc_B/merge-preview')[0]?.url.searchParams.get('merged_id')).toBe('svc_A');
  });
});
