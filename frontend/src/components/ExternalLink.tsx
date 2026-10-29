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
}

export function ExternalLink({ url, children }: ExternalLinkProps) {
  const host = urlHost(url);
  return (
    <span className={classes.root}>
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
