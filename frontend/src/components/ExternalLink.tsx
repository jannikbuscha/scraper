// A link to a stored URL (stored URLs are validated as http(s) by the server):
// it opens in a new tab and shows the URL's host next to the text.
import { Anchor, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import { urlHost } from '../lib/urls';
import classes from './ExternalLink.module.css';

interface ExternalLinkProps {
  /** The URL from data. */
  url: string;
  /** Link text; defaults to the URL itself. */
  children?: ReactNode;
  /**
   * Table cells (docs/UI.md §1.4): the text wraps at any character instead of
   * being cut off with an ellipsis. A cut-off text cannot be shorter than its
   * whole length in a table that sizes its columns by their content, so one
   * long URL would push the other columns aside or off-screen.
   */
  wrap?: boolean;
}

export function ExternalLink({ url, children, wrap = false }: ExternalLinkProps) {
  const host = urlHost(url);
  return (
    <span className={wrap ? `${classes.root} ${classes.wrap}` : classes.root}>
      <Anchor href={url} target="_blank" rel="noopener noreferrer" className={classes.link}>
        <bdi className={classes.text}>{children ?? url}</bdi>
      </Anchor>
      {host && (
        <Text span size="xs" c="dimmed" className={classes.host}>
          {host}
        </Text>
      )}
    </span>
  );
}
