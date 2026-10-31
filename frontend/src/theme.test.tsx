import { Button, MantineProvider, Modal } from '@mantine/core';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DIALOG_CLOSE_LABEL, theme } from './theme';

describe('theme', () => {
  it('names the header close button of every dialog, apart from a footer "Close" button', async () => {
    const onClose = vi.fn();
    render(
      <MantineProvider theme={theme} env="test">
        <Modal opened onClose={onClose} title="Example dialog">
          <Button>Close</Button>
        </Modal>
      </MantineProvider>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Example dialog' });
    // Mantine renders the header button as a bare icon: without the theme's label it has no name.
    const headerClose = within(dialog).getByRole('button', { name: DIALOG_CLOSE_LABEL });
    expect(within(dialog).getByRole('button', { name: 'Close' })).not.toBe(headerClose);
    await userEvent.click(headerClose);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
