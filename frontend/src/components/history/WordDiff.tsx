// Word-level diff rendered as React elements (never injected HTML).
import { VisuallyHidden } from '@mantine/core';

import { wordDiff } from '../../lib/diff';
import classes from './history.module.css';

interface WordDiffProps {
  oldText: string | null;
  newText: string | null;
}

export function WordDiff({ oldText, newText }: WordDiffProps) {
  const segments = wordDiff(oldText, newText);
  return (
    <div className={classes.wordDiff}>
      {segments.map((segment, index) => {
        // Segments are a static sequence; their position is their identity.
        const key = `${index}-${segment.kind}`;
        if (segment.kind === 'removed') {
          return (
            <del key={key} className={classes.removed}>
              <VisuallyHidden>[removed: </VisuallyHidden>
              {segment.text}
              <VisuallyHidden>]</VisuallyHidden>
            </del>
          );
        }
        if (segment.kind === 'added') {
          return (
            <ins key={key} className={classes.added}>
              <VisuallyHidden>[added: </VisuallyHidden>
              {segment.text}
              <VisuallyHidden>]</VisuallyHidden>
            </ins>
          );
        }
        return <span key={key}>{segment.text}</span>;
      })}
    </div>
  );
}
