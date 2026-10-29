// Comments (docs/UI.md §5): all comment threads with filters in the URL. A
// thread opens on its subject's page with the comments panel open.
import { Button, EmptyState, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { IconFilterOff, IconMessages } from '@tabler/icons-react';

import { useCommentFeed, useMeta } from '../api/queries';
import type { Meta } from '../api/types';
import { CommentFeedFilters } from '../components/changes/CommentFeedFilters';
import { CommentFeedTable } from '../components/changes/CommentFeedTable';
import { FeedPagination } from '../components/changes/FeedPagination';
import { clearFilterParams, commentFeedRequest, hasCommentFilters } from '../components/changes/feed-query';
import { ErrorAlert } from '../components/feedback';
import { useUrlSearch } from '../hooks/useUrlSearch';

const count = new Intl.NumberFormat('en-US');

export function CommentsPage() {
  useDocumentTitle('Comments · MDT Portfolio');
  const meta = useMeta();
  if (meta.isPending) return <Loader size="sm" />;
  if (meta.isError) {
    return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  }
  return <CommentsScreen meta={meta.data} />;
}

function CommentsScreen({ meta }: { meta: Meta }) {
  const [search, setSearch] = useUrlSearch();
  const feed = useCommentFeed(commentFeedRequest(search));

  let body;
  if (feed.isError) {
    body = <ErrorAlert title="Could not load the comments" error={feed.error} onRetry={() => void feed.refetch()} />;
  } else if (feed.isPending) {
    body = <Loader size="sm" />;
  } else if (feed.data.items.length === 0) {
    body = hasCommentFilters(search) ? (
      <EmptyState icon={<IconFilterOff size={28} />} title="No threads match the filters">
        <EmptyState.Actions>
          <Button
            variant="light"
            onClick={() => {
              setSearch((previous) => clearFilterParams(previous));
            }}
          >
            Clear filters
          </Button>
        </EmptyState.Actions>
      </EmptyState>
    ) : (
      <EmptyState
        icon={<IconMessages size={28} />}
        title="No comments yet"
        description="Comments are written on the detail pages and on the Codebook page."
      />
    );
  } else {
    body = <CommentFeedTable items={feed.data.items} meta={meta} />;
  }

  return (
    <Stack gap="sm">
      <Group gap="xs" align="baseline">
        <Title order={1}>Comments</Title>
        <Text c="dimmed" size="sm" aria-live="polite">
          {feed.data ? `${count.format(feed.data.total)} ${feed.data.total === 1 ? 'thread' : 'threads'}` : ''}
        </Text>
      </Group>
      <CommentFeedFilters meta={meta} search={search} setSearch={setSearch} />
      <div aria-busy={feed.isPlaceholderData}>{body}</div>
      {feed.data && feed.data.total > 0 && <FeedPagination total={feed.data.total} search={search} setSearch={setSearch} />}
    </Stack>
  );
}
