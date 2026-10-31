import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { copyText } from '../../lib/clipboard';
import { renderRoute } from '../../test/render';
import { CopyLinkButton } from './CopyLinkButton';

const URL_TO_COPY = 'http://mdt.example:8080/projects/prj_EXAMPLE';

/** Simulates the page's context: secure (https, localhost) or plain http on a network address. */
function setContext({ secure, clipboard }: { secure: boolean; clipboard?: { writeText: (text: string) => Promise<void> } }) {
  Object.defineProperty(window, 'isSecureContext', { configurable: true, value: secure });
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: clipboard });
}

function stubExecCommand(result: boolean) {
  const execCommand = vi.fn((command: string) => command === 'copy' && result);
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });
  return execCommand;
}

afterEach(() => {
  setContext({ secure: false });
  vi.restoreAllMocks();
});

describe('copyText', () => {
  it('uses the Clipboard API in a secure context', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    setContext({ secure: true, clipboard: { writeText } });
    const execCommand = stubExecCommand(true);
    await expect(copyText(URL_TO_COPY)).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith(URL_TO_COPY);
    expect(execCommand).not.toHaveBeenCalled();
  });

  it('falls back to copying a selection where there is no Clipboard API (plain http)', async () => {
    setContext({ secure: false });
    const execCommand = stubExecCommand(true);
    await expect(copyText(URL_TO_COPY)).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
    // The helper field is removed again.
    expect(document.querySelector('textarea[aria-hidden="true"][readonly]')).toBeNull();
  });

  it('reports a refused copy', async () => {
    setContext({ secure: false });
    stubExecCommand(false);
    await expect(copyText(URL_TO_COPY)).resolves.toBe(false);
  });
});

describe('Copy link', () => {
  it('confirms a copy on plain http through the fallback', async () => {
    setContext({ secure: false });
    const execCommand = stubExecCommand(true);
    const { user } = renderRoute(() => <CopyLinkButton url={URL_TO_COPY} />, { url: '/', path: '/' });
    await user.click(await screen.findByRole('button', { name: 'Copy link' }));
    expect(await screen.findByText('Copied')).toBeInTheDocument();
    expect(execCommand).toHaveBeenCalledWith('copy');
  });

  it('shows the link for manual copying when the browser refuses, instead of failing silently', async () => {
    setContext({ secure: false });
    stubExecCommand(false);
    const { user } = renderRoute(() => <CopyLinkButton url={URL_TO_COPY} />, { url: '/', path: '/' });
    await user.click(await screen.findByRole('button', { name: 'Copy link' }));
    const dialog = await screen.findByRole('dialog', { name: 'Copy the link' });
    expect(within(dialog).getByRole('textbox', { name: 'Link to this record' })).toHaveValue(URL_TO_COPY);
    await user.click(within(dialog).getByRole('button', { name: 'Close dialog' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Copy the link' })).toBeNull();
    });
  });
});
