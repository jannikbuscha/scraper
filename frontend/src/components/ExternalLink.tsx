// The only component that builds an href from data (docs/UI.md §1.4): an
// http(s) URL without userinfo becomes a link that opens in a new tab and
// shows its punycode host; anything else is rendered as plain text.
import { Anchor, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import { safeExternalUrl } from '../lib/urls';
import classes from './ExternalLink.module.css';

interface ExternalLinkProps {
  /** The URL from data. */
  url: string;
  /** Link text; defaults to the URL itself. */
  children?: ReactNode;
}

export function ExternalLink({ url, children }: ExternalLinkProps) {
  const safe = safeExternalUrl(url);
  const text = <bdi className={classes.text}>{children ?? url}</bdi>;
  if (!safe) return text;
  return (
    <span className={classes.root}>
      <Anchor href={safe.href} target="_blank" rel="noopener noreferrer nofollow" className={classes.link}>
        {text}
      </Anchor>
      <Text span size="xs" c="dimmed" className={classes.host}>
        {safe.host}
      </Text>
    </span>
  );
}
