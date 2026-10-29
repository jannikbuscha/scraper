// One comment (docs/UI.md §4.3): time, field chip and status for roots, the
// rendered body, the "edited" label (opens the revision history) and the
// actions reply, edit, resolve/reopen, delete/undelete.
import { Badge, Button, Group, Stack, Text } from '@mantine/core';
import { useState } from 'react';

import type { Comment } from '../../api/types';
import { notifyError } from '../feedback';
import { Timestamp } from '../Timestamp';
import { CommentActionModal, useCommentAction, type CommentDeletion } from './CommentActionModal';
import { CommentBody } from './CommentBody';
import { CommentEditor } from './CommentEditor';
import { CommentHistoryModal } from './CommentHistoryModal';
import classes from './comments.module.css';

interface CommentCardProps {
  comment: Comment;
  /** Label of the root's field (null: the whole record). */
  fieldLabel: string | null;
  maxChars: number;
  maxNoteChars: number;
  /** Starts a reply (roots that are not deleted). */
  onReply?: (() => void) | undefined;
}

export function CommentCard({ comment, fieldLabel, maxChars, maxNoteChars, onReply }: CommentCardProps) {
  const { run, pending } = useCommentAction();
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState(false);
  const [deletion, setDeletion] = useState<CommentDeletion | null>(null);
  const isRoot = comment.parent_id === null;
  const deleted = comment.deleted_at !== null;

  // Resolve and reopen need no confirmation.
  const setStatus = async (action: 'resolve' | 'reopen') => {
    try {
      await run(action, comment.id, null);
    } catch (error) {
      notifyError(error, `Could not ${action} the thread`);
    }
  };

  return (
    <Stack gap={4} className={deleted ? classes.deleted : undefined}>
      <Group gap={6} wrap="wrap">
        <Text span size="xs" c="dimmed">
          <Timestamp value={comment.created_at} />
        </Text>
        {isRoot && (
          <Badge size="xs" variant="outline" color="gray">
            {fieldLabel ?? 'whole record'}
          </Badge>
        )}
        {isRoot && comment.status && (
          <Badge size="xs" variant="light" color={comment.status === 'open' ? 'yellow' : 'green'}>
            {comment.status}
          </Badge>
        )}
        {deleted && (
          <Badge size="xs" color="red" variant="light">
            deleted
          </Badge>
        )}
        {comment.edited && (
          <Button
            variant="subtle"
            size="compact-xs"
            color="gray"
            aria-label="edited: show the comment history"
            onClick={() => {
              setHistory(true);
            }}
          >
            edited
          </Button>
        )}
      </Group>
      {editing ? (
        <CommentEditor
          comment={comment}
          maxChars={maxChars}
          onDone={() => {
            setEditing(false);
          }}
        />
      ) : (
        <CommentBody html={comment.body_html} />
      )}
      {isRoot && comment.status === 'resolved' && comment.resolved_at && (
        <Text size="xs" c="dimmed">
          Resolved at <Timestamp value={comment.resolved_at} />
        </Text>
      )}
      {deleted && (
        <Text size="xs" c="dimmed">
          Deleted at <Timestamp value={comment.deleted_at} />
        </Text>
      )}
      {!editing && (
        <Group gap={4}>
          {onReply && !deleted && (
            <Button variant="subtle" size="compact-xs" aria-label="Reply to thread" onClick={onReply}>
              Reply
            </Button>
          )}
          {!deleted && (
            <Button
              variant="subtle"
              size="compact-xs"
              aria-label="Edit comment"
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit
            </Button>
          )}
          {isRoot && !deleted && (
            <Button
              variant="subtle"
              size="compact-xs"
              loading={pending}
              aria-label={comment.status === 'resolved' ? 'Reopen thread' : 'Resolve thread'}
              onClick={() => void setStatus(comment.status === 'resolved' ? 'reopen' : 'resolve')}
            >
              {comment.status === 'resolved' ? 'Reopen' : 'Resolve'}
            </Button>
          )}
          <Button
            variant="subtle"
            size="compact-xs"
            color={deleted ? undefined : 'red'}
            aria-label={deleted ? 'Undelete comment' : 'Delete comment'}
            onClick={() => {
              setDeletion(deleted ? 'undelete' : 'delete');
            }}
          >
            {deleted ? 'Undelete' : 'Delete'}
          </Button>
        </Group>
      )}
      <CommentActionModal
        comment={comment}
        action={deletion}
        maxNoteChars={maxNoteChars}
        onClose={() => {
          setDeletion(null);
        }}
      />
      <CommentHistoryModal
        comment={comment}
        opened={history}
        maxNoteChars={maxNoteChars}
        onClose={() => {
          setHistory(false);
        }}
      />
    </Stack>
  );
}
