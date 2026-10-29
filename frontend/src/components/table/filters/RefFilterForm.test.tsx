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

  it('keeps "has any value" (empty:false) when applied unchanged, and can write it', async () => {
    mockApi(() => undefined);
    const onApply = vi.fn();
    const { user } = renderRoute(() => <RefFilterForm field={projectField} raw="empty:false" onApply={onApply} />, {
      url: '/',
      path: '/',
    });
    const condition = await screen.findByRole('combobox', { name: 'Condition' });
    expect(condition).toHaveValue('any');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenLastCalledWith('empty:false');

    // Switching to "is any of" without values removes the filter, as before.
    await user.selectOptions(condition, 'in');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenLastCalledWith(null);
    // ... and "has any value" can be chosen in the form.
    await user.selectOptions(condition, 'any');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenLastCalledWith('empty:false');
  });

  it('keeps an "is empty" filter as its equivalent ~empty selection', async () => {
    mockApi(() => undefined);
    const onApply = vi.fn();
    const { user } = renderRoute(() => <RefFilterForm field={projectField} raw="empty:true" onApply={onApply} />, {
      url: '/',
      path: '/',
    });
    expect(await screen.findByRole('checkbox', { name: '(empty)' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenLastCalledWith('in:~empty');
  });
});
