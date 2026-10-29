// Notice for 409 `entity_deleted` and `invalid_state` on a comment action
// (docs/UI.md §1.3): who changed the comment last and when (read fresh from
// the server), with Reload; nothing is retried.
import { Alert, Button, Group, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { IconRefresh } from '@tabler/icons-react';

import { queryKeys, useComment } from '../../api/queries';
import type { Comment } from '../../api/types';
import { Timestamp } from '../Timestamp';

interface CommentChangedNoticeProps {
  comment: Comment;
  /** Called after the comments were reloaded, e.g. to close a dialog. */
  onReloaded: () => void;
}

export function CommentChangedNotice({ comment, onReloaded }: CommentChangedNoticeProps) {
  const client = useQueryClient();
  const current = useComment(comment.id);
  const fresh = current.data?.comment;
  let text;
  if (fresh?.deleted_at) {
    text = (
      <>
        Deleted by <bdi>{fresh.deleted_by ?? 'unknown'}</bdi> at <Timestamp value={fresh.deleted_at} />.
      </>
    );
  } else if (fresh) {
    text = (
      <>
        Changed by <bdi>{fresh.updated_by}</bdi> at <Timestamp value={fresh.updated_at} />.
      </>
    );
  } else {
    text = current.isError ? 'This comment was changed in the meantime.' : 'Loading the current state…';
  }
  return (
    <Alert color="yellow" variant="light" title="Changed in the meantime">
      <Group justify="space-between" align="center" wrap="nowrap">
        <Text size="sm">{text}</Text>
        <Button
          variant="light"
          color="yellow"
          leftSection={<IconRefresh size={14} />}
          onClick={() => {
            void client.invalidateQueries({ queryKey: queryKeys.commentsOf(comment.subject_id) });
            void client.invalidateQueries({ queryKey: [...queryKeys.comments, 'comment', comment.id] });
            onReloaded();
          }}
        >
          Reload
        </Button>
      </Group>
    </Alert>
  );
}
