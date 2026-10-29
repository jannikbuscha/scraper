// Editing a comment (docs/UI.md §4.3): the text starts from the comment's
// body; Save sends it with `note: null`.
import { Alert, Button, Group, Stack, Textarea } from '@mantine/core';
import { useState } from 'react';

import { useEditComment } from '../../api/queries';
import type { Comment } from '../../api/types';
import { errorMessage } from '../feedback';

interface CommentEditorProps {
  comment: Comment;
  maxChars: number;
  onDone: () => void;
}

export function CommentEditor({ comment, maxChars, onDone }: CommentEditorProps) {
  const edit = useEditComment();
  const [text, setText] = useState(comment.body_md);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    try {
      await edit.mutateAsync({ id: comment.id, body_md: text, note: null });
      onDone();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };

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
        <Button
          loading={edit.isPending}
          disabled={text.trim() === '' || text === comment.body_md}
          onClick={() => void save()}
        >
          Save
        </Button>
      </Group>
    </Stack>
  );
}
