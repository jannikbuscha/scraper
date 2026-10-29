import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { mockApi } from '../../../test/api-mock';
import { fieldSpec } from '../../../test/fixtures';
import { renderRoute } from '../../../test/render';
import { RefFilterForm } from './RefFilterForm';

const projectField = fieldSpec('project_id', 'ref', { label: 'Project', ref_types: ['project'], filter: 'ref' });

describe('ref filter form', () => {
  it('closes the value list after a pick, so Apply stays reachable', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/lookup' && url.searchParams.get('q') === 'Example') {
        return {
          items: [
            { id: 'prj_A', type: 'project', label: 'Example project A', deleted: false, context: null },
            { id: 'prj_B', type: 'project', label: 'Example project B', deleted: false, context: null },
          ],
        };
      }
      if (url.pathname === '/api/lookup' && url.searchParams.has('ids')) {
        return { items: [{ id: 'prj_B', type: 'project', label: 'Example project B', deleted: false, context: null }] };
      }
      return undefined;
    });
    const onApply = vi.fn();
    const { user } = renderRoute(() => <RefFilterForm field={projectField} raw={undefined} onApply={onApply} />, {
      url: '/',
      path: '/',
    });

    await user.type(await screen.findByPlaceholderText('Type to search'), 'Example');
    await user.click(await screen.findByRole('option', { name: 'Example project B' }));
    await waitFor(() => {
      expect(screen.queryByRole('listbox')).toBeNull();
    });
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledWith('in:prj_B');
  });
});
