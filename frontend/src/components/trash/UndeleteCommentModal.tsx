// Undelete a deleted comment thread with a note (docs/UI.md §5); its replies
// reappear with it (docs/DATA_MODEL.md §6.6).
import { Modal } from '@mantine/core';

import { useUndeleteComment } from '../../api/queries';
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
  const undelete = useUndeleteComment();
  return (
    <UndeleteForm
      label={`Comment on ${comment.subject_label}`}
      maxNoteChars={maxNoteChars}
      submit={async (note) => {
        await undelete.mutateAsync({ id: comment.id, note });
        notifySuccess(`Undeleted the comment on “${comment.subject_label}”.`);
        onDone();
      }}
      onCancel={onDone}
    />
  );
}
