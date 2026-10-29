// Undelete a deleted comment thread with a note (docs/UI.md §5); its replies
// reappear with it (docs/DATA_MODEL.md §6.6).
import { Alert, Button, Group, Modal, Text } from '@mantine/core';
import { IconRefresh } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { queryKeys, useUndeleteComment } from '../../api/queries';
import type { Comment } from '../../api/types';
import { notifySuccess } from '../feedback';
import { UndeleteForm } from './UndeleteForm';

interface UndeleteCommentModalProps {
  comment: Comment | null;
  maxNoteChars: number;
  onClose: () => void;
}

export function UndeleteCommentModal({ comment, maxNoteChars, onClose }: UndeleteCommentModalProps) {
  return (
    <Modal opened={comment !== null} onClose={onClose} title="Undelete comment">
      {comment && <UndeleteCommentBody comment={comment} maxNoteChars={maxNoteChars} onDone={onClose} />}
    </Modal>
  );
}

interface UndeleteCommentBodyProps {
  comment: Comment;
  maxNoteChars: number;
  onDone: () => void;
}

function UndeleteCommentBody({ comment, maxNoteChars, onDone }: UndeleteCommentBodyProps) {
  const client = useQueryClient();
  const undelete = useUndeleteComment();
  const [stale, setStale] = useState(false);

  if (stale) {
    return (
      <Alert color="yellow" variant="light" title="Changed in the meantime">
        <Group justify="space-between" align="center" wrap="nowrap">
          <Text size="sm">This comment was changed by someone else, e.g. already undeleted.</Text>
          <Button
            variant="light"
            color="yellow"
            leftSection={<IconRefresh size={14} />}
            onClick={() => {
              void client.invalidateQueries({ queryKey: queryKeys.comments });
              onDone();
            }}
          >
            Reload
          </Button>
        </Group>
      </Alert>
    );
  }

  return (
    <UndeleteForm
      label={`Comment on ${comment.subject_label}`}
      version={comment.version}
      maxNoteChars={maxNoteChars}
      submit={async (expectedVersion, note) => {
        await undelete.mutateAsync({ id: comment.id, expected_version: expectedVersion, note });
        notifySuccess(`Undeleted the comment on “${comment.subject_label}”.`);
        onDone();
      }}
      onStale={() => {
        setStale(true);
      }}
      onCancel={onDone}
    />
  );
}
