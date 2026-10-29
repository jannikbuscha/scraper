// Deleted comment threads (GET /api/comments?deleted=only, docs/API.md
// §3.3), with Undelete. A deleted root hides its thread; the replies return
// with it.
import { EmptyState, Loader, Stack, Text } from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { useState } from 'react';

import { useCommentFeed } from '../../api/queries';
import type { Comment, CommentFeedItem } from '../../api/types';
import { useUrlSearch } from '../../hooks/useUrlSearch';
import { pluralize } from '../../lib/format';
import { commentExcerpt } from '../changes/comment-text';
import { FeedPagination } from '../changes/FeedPagination';
import { pagingParams } from '../changes/feed-query';
import { pageTarget, threadTarget } from '../changes/targets';
import { TargetLink } from '../changes/TargetLink';
import { ErrorAlert } from '../feedback';
import { TrashTable } from './TrashTable';
import { UndeleteCommentModal } from './UndeleteCommentModal';
import { useDeleteInfo } from './useDeleteInfo';

function ThreadLabel({ root, replies }: { root: Comment; replies: number }) {
  return (
    <>
      <TargetLink target={threadTarget(root.subject_type, root.subject_id, root.id)} label={commentExcerpt(root.body_md)} />
      <Text size="xs" c="dimmed">
        on <TargetLink target={pageTarget(root.subject_type, root.subject_id)} label={root.subject_label} />
        {replies > 0 && ` · ${pluralize(replies, 'reply', 'replies')}`}
      </Text>
    </>
  );
}

function TrashThreadRows({ items, onUndelete }: { items: readonly CommentFeedItem[]; onUndelete: (root: Comment) => void }) {
  const info = useDeleteInfo(items.map(({ root }) => root));
  return (
    <TrashTable
      rows={items.map(({ root, reply_count: replies }) => ({
        id: root.id,
        label: `comment on ${root.subject_label}`,
        record: <ThreadLabel root={root} replies={replies} />,
        deletedAt: root.deleted_at,
        info: info?.get(root.id),
        onUndelete: () => {
          onUndelete(root);
        },
      }))}
    />
  );
}

export function TrashCommentList({ maxNoteChars }: { maxNoteChars: number }) {
  const [search, setSearch] = useUrlSearch();
  const feed = useCommentFeed({ ...pagingParams(search), deleted: 'only' });
  const [target, setTarget] = useState<Comment | null>(null);

  if (feed.isError) {
    return <ErrorAlert title="Could not load the deleted comments" error={feed.error} onRetry={() => void feed.refetch()} />;
  }
  if (feed.isPending) return <Loader size="sm" />;
  if (feed.data.total === 0) return <EmptyState icon={<IconTrash size={28} />} title="No deleted comments" />;
  return (
    <Stack gap="sm">
      <div aria-busy={feed.isPlaceholderData}>
        <TrashThreadRows items={feed.data.items} onUndelete={setTarget} />
      </div>
      <FeedPagination total={feed.data.total} search={search} setSearch={setSearch} />
      <UndeleteCommentModal
        comment={target}
        maxNoteChars={maxNoteChars}
        onClose={() => {
          setTarget(null);
        }}
      />
    </Stack>
  );
}
