import { screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import type { RefLabel } from '../../../api/types';
import { mockApi, requestsTo } from '../../../test/api-mock';
import { renderRoute } from '../../../test/render';
import { RefSelect } from './RefSelect';

const stored: RefLabel = { id: 'prj_A', type: 'project', label: 'Example project A', deleted: false };

function Picker({ initial }: { initial: string }) {
  const [value, setValue] = useState<string | null>(initial);
  return <RefSelect label="Project" types={['project']} value={value} onChange={setValue} currentRef={stored} />;
}

describe('RefSelect', () => {
  it('labels the stored value from currentRef without a lookup', async () => {
    const fetchMock = mockApi(() => undefined);
    renderRoute(() => <Picker initial="prj_A" />, { url: '/', path: '/' });
    expect(await screen.findByDisplayValue('Example project A')).toBeInTheDocument();
    // No label lookup by ID is needed for the stored value.
    expect(requestsTo(fetchMock, '/api/lookup').filter((url) => url.searchParams.has('ids'))).toHaveLength(0);
  });

  it('does not show the old label for another picked row', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/lookup' && url.searchParams.get('q') === 'Example') {
        return {
          items: [
            { id: 'prj_A', type: 'project', label: 'Example project A', deleted: false, context: null },
            { id: 'prj_B', type: 'project', label: 'Example project B', deleted: false, context: null },
          ],
        };
      }
      if (url.pathname === '/api/lookup' && url.searchParams.get('ids') === 'prj_B') {
        return { items: [{ id: 'prj_B', type: 'project', label: 'Example project B', deleted: false, context: null }] };
      }
      return undefined;
    });
    const { user } = renderRoute(() => <Picker initial="prj_A" />, { url: '/', path: '/' });
    const input = await screen.findByRole('combobox', { name: 'Project' });
    await user.clear(input);
    await user.type(input, 'Example');
    await user.click(await screen.findByRole('option', { name: 'Example project B' }));
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Project' })).toHaveValue('Example project B');
    });
  });
});
