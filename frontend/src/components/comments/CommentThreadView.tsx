// A comment thread (docs/UI.md §4.3): the root with field chip, status and
// time, its replies below, and the reply composer.
import { Stack } from '@mantine/core';
import { useState } from 'react';

import type { CommentThread } from '../../api/types';
import { CommentCard } from './CommentCard';
import { CommentComposer } from './CommentComposer';
import classes from './comments.module.css';

interface CommentThreadViewProps {
  thread: CommentThread;
  fieldLabel: string | null;
  highlighted: boolean;
  maxChars: number;
  maxNoteChars: number;
}

export const threadElementId = (rootId: string): string => `comment-thread-${rootId}`;

export function CommentThreadView({ thread, fieldLabel, highlighted, maxChars, maxNoteChars }: CommentThreadViewProps) {
  const [replying, setReplying] = useState(false);
  const { root, replies } = thread;
  return (
    <article
      id={threadElementId(root.id)}
      className={classes.thread}
      data-highlighted={highlighted}
      aria-label={`Thread on ${fieldLabel ?? 'the whole record'}`}
    >
      <CommentCard
        comment={root}
        fieldLabel={fieldLabel}
        maxChars={maxChars}
        maxNoteChars={maxNoteChars}
        // Replying to a deleted root is not possible (docs/DATA_MODEL.md §6.6).
        onReply={
          root.deleted_at === null
            ? () => {
                setReplying(true);
              }
            : undefined
        }
      />
      {(replies.length > 0 || replying) && (
        <Stack gap="xs" className={classes.replies}>
          {replies.map((reply) => (
            <CommentCard
              key={reply.id}
              comment={reply}
              fieldLabel={null}
              maxChars={maxChars}
              maxNoteChars={maxNoteChars}
            />
          ))}
          {replying && (
            <CommentComposer
              subjectId={root.subject_id}
              parentId={root.id}
              label="Reply"
              maxChars={maxChars}
              focusKey={0}
              onCancel={() => {
                setReplying(false);
              }}
              onPosted={() => {
                setReplying(false);
              }}
            />
          )}
        </Stack>
      )}
    </article>
  );
}
