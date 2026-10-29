// Delete and undelete of a comment (docs/UI.md §4.3), confirmed with an
// optional note; resolve and reopen are sent directly (useCommentAction).
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState } from 'react';

import { useDeleteComment, useReopenComment, useResolveComment, useUndeleteComment } from '../../api/queries';
import type { Comment } from '../../api/types';
import { errorMessage } from '../feedback';

type CommentAction = 'delete' | 'undelete' | 'resolve' | 'reopen';

/** Runs an action on a comment. */
export function useCommentAction() {
  const remove = useDeleteComment();
  const undelete = useUndeleteComment();
  const resolve = useResolveComment();
  const reopen = useReopenComment();
  const run = async (action: CommentAction, id: string, note: string | null): Promise<void> => {
    if (action === 'delete') await remove.mutateAsync({ id, note });
    else if (action === 'undelete') await undelete.mutateAsync({ id, note });
    else if (action === 'resolve') await resolve.mutateAsync({ id });
    else await reopen.mutateAsync({ id });
  };
  const pending = remove.isPending || undelete.isPending || resolve.isPending || reopen.isPending;
  return { run, pending };
}

export type CommentDeletion = 'delete' | 'undelete';

interface CommentActionModalProps {
  comment: Comment;
  /** The confirmed action; the dialog is open while set. */
  action: CommentDeletion | null;
  maxNoteChars: number;
  onClose: () => void;
}

export function CommentActionModal({ comment, action, maxNoteChars, onClose }: CommentActionModalProps) {
  const title = action === 'undelete' ? 'Undelete comment' : 'Delete comment';
  return (
    <Modal opened={action !== null} onClose={onClose} title={title}>
      {action && <ActionForm comment={comment} action={action} maxNoteChars={maxNoteChars} onDone={onClose} />}
    </Modal>
  );
}

function ActionForm({
  comment,
  action,
  maxNoteChars,
  onDone,
}: {
  comment: Comment;
  action: CommentDeletion;
  maxNoteChars: number;
  onDone: () => void;
}) {
  const { run, pending } = useCommentAction();
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      await run(action, comment.id, note.trim() || null);
      onDone();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };

  return (
    <Stack gap="sm">
      {action === 'delete' ? (
        <Text size="sm">
          {comment.parent_id === null
            ? 'Delete this thread? Its replies are hidden with it and come back on undelete.'
            : 'Delete this reply?'}{' '}
          Deleted comments can be shown with “Show deleted” and undeleted.
        </Text>
      ) : (
        <Text size="sm">Undelete this comment?</Text>
      )}
      <Textarea
        label="Note (optional)"
        autosize
        minRows={2}
        maxLength={maxNoteChars}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onDone}>
          Cancel
        </Button>
        <Button color={action === 'delete' ? 'red' : undefined} loading={pending} onClick={() => void submit()}>
          {action === 'delete' ? 'Delete' : 'Undelete'}
        </Button>
      </Group>
    </Stack>
  );
}
