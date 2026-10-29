import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ExternalLink } from './ExternalLink';

const renderLink = (url: string) =>
  render(
    <MantineProvider env="test">
      <ExternalLink url={url}>Example source</ExternalLink>
    </MantineProvider>,
  );

describe('ExternalLink', () => {
  it('links http(s) URLs in a new tab without opener or referrer and shows the punycode host', () => {
    renderLink('https://приклад.укр/page');
    const link = screen.getByRole('link', { name: 'Example source' });
    expect(link).toHaveAttribute('href', 'https://xn--80aikifvh.xn--j1amh/page');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow');
    expect(screen.getByText('xn--80aikifvh.xn--j1amh')).toBeInTheDocument();
  });

  it.each([
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'java\tscript:alert(1)',
    'https://user:secret@example.org/',
    '//example.org/',
  ])('renders %j as plain text', (url) => {
    const { container } = renderLink(url);
    expect(screen.queryByRole('link')).toBeNull();
    expect(container.querySelector('[href]')).toBeNull();
    expect(screen.getByText('Example source')).toBeInTheDocument();
  });
});
