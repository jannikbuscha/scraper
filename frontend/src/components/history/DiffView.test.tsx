import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { mockApi } from '../../test/api-mock';
import { renderRoute } from '../../test/render';
import { DiffView } from './DiffView';

describe('DiffView', () => {
  it('names the survivor of a merge revision by its label (docs/UI.md §8.7)', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/lookup' && url.searchParams.get('ids') === 'prj_SURVIVOR') {
        return { items: [{ id: 'prj_SURVIVOR', type: 'project', label: 'Example survivor', deleted: false, context: null }] };
      }
      return undefined;
    });
    const Page = () => <DiffView diff={{ state: { merged_into: [null, 'prj_SURVIVOR'] } }} />;
    renderRoute(Page, { url: '/projects/prj_A', path: '/projects/$id' });
    expect(await screen.findByRole('link', { name: 'Example survivor' })).toHaveAttribute('href', '/projects/prj_SURVIVOR');
  });
});
