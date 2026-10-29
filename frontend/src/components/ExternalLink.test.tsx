import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ExternalLink } from './ExternalLink';

describe('ExternalLink', () => {
  it('opens the URL in a new tab and shows its host', () => {
    render(
      <MantineProvider env="test">
        <ExternalLink url="https://example.org/page">Example source</ExternalLink>
      </MantineProvider>,
    );
    const link = screen.getByRole('link', { name: 'Example source' });
    expect(link).toHaveAttribute('href', 'https://example.org/page');
    expect(link).toHaveAttribute('target', '_blank');
    expect(screen.getByText('example.org')).toBeInTheDocument();
  });
});
