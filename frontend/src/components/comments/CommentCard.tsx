// One comment (docs/UI.md §4.3): author and time, field chip and status for
// roots, the sanitised body, the "edited" label (opens the revision history)
// and the actions reply, edit, resolve/reopen, delete/undelete.
import { Badge, Button, Group, Stack, Text } from '@mantine/core';
import { useState } from 'react';

import { isConflictError } from '../../api/client';
import type { Comment } from '../../api/types';
import { notifyError } from '../feedback';
import { Timestamp } from '../Timestamp';
import { WriteButton } from '../WriteButton';
import { CommentActionModal, useCommentAction, type CommentActionRequest } from './CommentActionModal';
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
  const [request, setRequest] = useState<CommentActionRequest | null>(null);
  const isRoot = comment.parent_id === null;
  const deleted = comment.deleted_at !== null;

  // Resolve and reopen are idempotent and need no confirmation; a 409 is
  // shown like delete (docs/UI.md §1.3).
  const setStatus = async (action: 'resolve' | 'reopen') => {
    try {
      await run(action, comment.id, comment.version, null);
    } catch (error) {
      if (isConflictError(error)) setRequest({ action, conflict: error.payload });
      else notifyError(error, `Could not ${action} the thread`);
    }
  };

  return (
    <Stack gap={4} className={deleted ? classes.deleted : undefined}>
      <Group gap={6} wrap="wrap">
        <Text span size="sm" fw={600}>
          <bdi>{comment.created_by}</bdi>
        </Text>
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
      {isRoot && comment.status === 'resolved' && comment.resolved_by && (
        <Text size="xs" c="dimmed">
          Resolved by <bdi>{comment.resolved_by}</bdi> at <Timestamp value={comment.resolved_at} />
        </Text>
      )}
      {deleted && (
        <Text size="xs" c="dimmed">
          Deleted by <bdi>{comment.deleted_by ?? 'unknown'}</bdi> at <Timestamp value={comment.deleted_at} />
        </Text>
      )}
      {!editing && (
        <Group gap={4}>
          {onReply && !deleted && (
            <WriteButton variant="subtle" size="compact-xs" aria-label="Reply to thread" onClick={onReply}>
              Reply
            </WriteButton>
          )}
          {!deleted && (
            <WriteButton
              variant="subtle"
              size="compact-xs"
              aria-label="Edit comment"
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit
            </WriteButton>
          )}
          {isRoot && !deleted && (
            <WriteButton
              variant="subtle"
              size="compact-xs"
              loading={pending}
              aria-label={comment.status === 'resolved' ? 'Reopen thread' : 'Resolve thread'}
              onClick={() => void setStatus(comment.status === 'resolved' ? 'reopen' : 'resolve')}
            >
              {comment.status === 'resolved' ? 'Reopen' : 'Resolve'}
            </WriteButton>
          )}
          <WriteButton
            variant="subtle"
            size="compact-xs"
            color={deleted ? undefined : 'red'}
            aria-label={deleted ? 'Undelete comment' : 'Delete comment'}
            onClick={() => {
              setRequest({ action: deleted ? 'undelete' : 'delete', conflict: null });
            }}
          >
            {deleted ? 'Undelete' : 'Delete'}
          </WriteButton>
        </Group>
      )}
      <CommentActionModal
        comment={comment}
        request={request}
        maxNoteChars={maxNoteChars}
        onClose={() => {
          setRequest(null);
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
