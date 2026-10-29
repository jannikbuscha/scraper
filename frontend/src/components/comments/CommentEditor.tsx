// Editing a comment (docs/UI.md §4.3). On 409 a two-way dialog shows theirs
// against yours as a word diff; yours is resent with the current version only
// on confirm (docs/UI.md §1.3).
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState } from 'react';

import { isApiError, isConflictError } from '../../api/client';
import { useEditComment } from '../../api/queries';
import type { Comment, ConflictPayload } from '../../api/types';
import { asString } from '../../lib/format';
import { errorMessage } from '../feedback';
import { InterveningRevisions } from '../history/InterveningRevisions';
import { WordDiff } from '../history/WordDiff';
import { WriteButton } from '../WriteButton';
import { CommentChangedNotice } from './CommentChangedNotice';

interface CommentEditorProps {
  comment: Comment;
  maxChars: number;
  onDone: () => void;
}

export function CommentEditor({ comment, maxChars, onDone }: CommentEditorProps) {
  const edit = useEditComment();
  const [text, setText] = useState(comment.body_md);
  const [conflict, setConflict] = useState<ConflictPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);

  const save = async (version: number) => {
    setError(null);
    try {
      await edit.mutateAsync({ id: comment.id, expected_version: version, body_md: text, note: null });
      setConflict(null);
      onDone();
    } catch (failure) {
      if (isConflictError(failure) && failure.payload.current_state.deleted_at === null) setConflict(failure.payload);
      else if (isConflictError(failure) || isApiError(failure, 'entity_deleted')) {
        setConflict(null);
        setStale(true);
      } else setError(errorMessage(failure));
    }
  };

  const theirs = conflict ? asString(conflict.current.body_md ?? null) : null;
  if (stale) return <CommentChangedNotice comment={comment} onReloaded={onDone} />;

  return (
    <Stack gap={6}>
      <Textarea
        label="Edit comment"
        autosize
        minRows={2}
        maxRows={12}
        maxLength={maxChars}
        value={text}
        onChange={(event) => {
          setText(event.currentTarget.value);
        }}
        data-autofocus
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
        <WriteButton
          loading={edit.isPending}
          disabled={text.trim() === '' || text === comment.body_md}
          onClick={() => void save(comment.version)}
        >
          Save
        </WriteButton>
      </Group>
      <Modal
        opened={conflict !== null}
        onClose={() => {
          setConflict(null);
        }}
        title="The comment was changed meanwhile"
        size="lg"
      >
        {conflict && (
          <Stack gap="sm">
            <InterveningRevisions revisions={conflict.intervening} />
            <Text size="sm">Their current text compared with yours (removed: only theirs; added: only yours):</Text>
            <WordDiff oldText={theirs} newText={text} />
            <Group justify="flex-end" gap="xs">
              <Button
                variant="default"
                onClick={() => {
                  setConflict(null);
                  onDone();
                }}
              >
                Discard my edit
              </Button>
              <Button loading={edit.isPending} onClick={() => void save(conflict.current_version)}>
                Save my version
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
