import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { theme } from '../../theme';
import { CommentBody } from './CommentBody';

describe('CommentBody', () => {
  it('renders the server-rendered body_html', () => {
    render(
      <MantineProvider theme={theme} env="test">
        <div data-testid="comment">
          <CommentBody html={'<p><strong>Example</strong> comment with <a href="https://example.org/page">a link</a></p><ul><li>item</li></ul>'} />
        </div>
      </MantineProvider>,
    );
    const container = screen.getByTestId('comment');
    expect(container.querySelector('strong')?.textContent).toBe('Example');
    expect(container.querySelector('li')?.textContent).toBe('item');
    expect(screen.getByRole('link', { name: 'a link' })).toHaveAttribute('href', 'https://example.org/page');
  });
});
