import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ExternalLink } from './ExternalLink';
import classes from './ExternalLink.module.css';

// CSS module classes are typed as possibly missing; a missing one fails the assertions.
const ROOT_CLASS = classes.root ?? 'missing-root-class';
const WRAP_CLASS = classes.wrap ?? 'missing-wrap-class';

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
    // Outside tables a long text is cut off with an ellipsis.
    expect(link.parentElement).toHaveClass(ROOT_CLASS);
    expect(link.parentElement).not.toHaveClass(WRAP_CLASS);
  });

  it('wraps in table cells, so a long URL keeps its whole text and does not widen the table', () => {
    const url = `https://example.org/${'synthetic'.repeat(26)}`;
    render(
      <MantineProvider env="test">
        <ExternalLink url={url} wrap />
      </MantineProvider>,
    );
    const link = screen.getByRole('link', { name: url });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.parentElement).toHaveClass(ROOT_CLASS, WRAP_CLASS);
    expect(screen.getByText('example.org')).toBeInTheDocument();
  });
});
