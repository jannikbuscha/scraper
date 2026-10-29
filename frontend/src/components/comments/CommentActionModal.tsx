// Delete, undelete, resolve and reopen of a comment (docs/UI.md §4.3).
// Delete and undelete are confirmed with an optional note; resolve and reopen
// are sent directly and come here only after a 409. A conflict lists the
// intervening revisions; the action is resent with the current version only
// on confirm (docs/UI.md §1.3).
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState } from 'react';

import { isApiError, isConflictError } from '../../api/client';
import { useDeleteComment, useReopenComment, useResolveComment, useUndeleteComment } from '../../api/queries';
import type { Comment, ConflictPayload } from '../../api/types';
import { ChangedMeanwhileAlert } from '../history/ChangedMeanwhileAlert';
import { errorMessage } from '../feedback';
import { CommentChangedNotice } from './CommentChangedNotice';

export type CommentAction = 'delete' | 'undelete' | 'resolve' | 'reopen';

const VERBS: Record<CommentAction, string> = {
  delete: 'Delete',
  undelete: 'Undelete',
  resolve: 'Resolve',
  reopen: 'Reopen',
};

/** Runs an action on a comment with the given version. */
export function useCommentAction() {
  const remove = useDeleteComment();
  const undelete = useUndeleteComment();
  const resolve = useResolveComment();
  const reopen = useReopenComment();
  const run = async (action: CommentAction, id: string, version: number, note: string | null): Promise<void> => {
    if (action === 'delete') await remove.mutateAsync({ id, expected_version: version, note });
    else if (action === 'undelete') await undelete.mutateAsync({ id, expected_version: version, note });
    else if (action === 'resolve') await resolve.mutateAsync({ id, expected_version: version });
    else await reopen.mutateAsync({ id, expected_version: version });
  };
  const pending = remove.isPending || undelete.isPending || resolve.isPending || reopen.isPending;
  return { run, pending };
}

export interface CommentActionRequest {
  action: CommentAction;
  /** Set when a first attempt was refused with a conflict. */
  conflict: ConflictPayload | null;
}

interface CommentActionModalProps {
  comment: Comment;
  request: CommentActionRequest | null;
  maxNoteChars: number;
  onClose: () => void;
}

export function CommentActionModal({ comment, request, maxNoteChars, onClose }: CommentActionModalProps) {
  const title = request ? `${VERBS[request.action]} comment` : 'Comment';
  return (
    <Modal opened={request !== null} onClose={onClose} title={title}>
      {request && <ActionForm comment={comment} request={request} maxNoteChars={maxNoteChars} onDone={onClose} />}
    </Modal>
  );
}

function ActionForm({
  comment,
  request,
  maxNoteChars,
  onDone,
}: {
  comment: Comment;
  request: CommentActionRequest;
  maxNoteChars: number;
  onDone: () => void;
}) {
  const { run, pending } = useCommentAction();
  const [conflict, setConflict] = useState<ConflictPayload | null>(request.conflict);
  const [version, setVersion] = useState(request.conflict?.current_version ?? comment.version);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const { action } = request;
  const withNote = action === 'delete' || action === 'undelete';

  const submit = async () => {
    setError(null);
    try {
      await run(action, comment.id, version, withNote ? note.trim() || null : null);
      onDone();
    } catch (failure) {
      if (isConflictError(failure)) {
        setConflict(failure.payload);
        setVersion(failure.payload.current_version);
      } else if (isApiError(failure, 'invalid_state') || isApiError(failure, 'entity_deleted')) setStale(true);
      else setError(errorMessage(failure));
    }
  };

  if (stale) return <CommentChangedNotice comment={comment} onReloaded={onDone} />;

  return (
    <Stack gap="sm">
      {action === 'delete' && (
        <Text size="sm">
          {comment.parent_id === null
            ? 'Delete this thread? Its replies are hidden with it and come back on undelete.'
            : 'Delete this reply?'}{' '}
          Deleted comments can be shown with “Show deleted” and undeleted.
        </Text>
      )}
      {action === 'undelete' && <Text size="sm">Undelete this comment?</Text>}
      {conflict && (
        <ChangedMeanwhileAlert
          revisions={conflict.intervening}
          question={`${VERBS[action]} it anyway?`}
          fieldLabels={{ body_md: 'Text', status: 'Status', deleted: 'Deleted' }}
        />
      )}
      {withNote && (
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
      )}
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
          {conflict ? `${VERBS[action]} anyway` : VERBS[action]}
        </Button>
      </Group>
    </Stack>
  );
}
