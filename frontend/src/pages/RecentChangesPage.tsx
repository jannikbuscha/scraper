// Recent changes (docs/UI.md §5): the global revision feed with filters in
// the URL, rows grouped by local day, each expandable to its diff.
import { Button, EmptyState, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { IconFilterOff, IconHistory } from '@tabler/icons-react';

import { useChangeFeed, useMeta } from '../api/queries';
import type { Meta } from '../api/types';
import { ChangeFeedFilters } from '../components/changes/ChangeFeedFilters';
import { ChangeFeedTable } from '../components/changes/ChangeFeedTable';
import { FeedPagination } from '../components/changes/FeedPagination';
import { changeFeedRequest, clearFilterParams, hasChangeFilters, withParam } from '../components/changes/feed-query';
import { ErrorAlert } from '../components/feedback';
import { useUrlSearch } from '../hooks/useUrlSearch';

const count = new Intl.NumberFormat('en-US');

export function RecentChangesPage() {
  useDocumentTitle('Recent changes · MDT Portfolio');
  const meta = useMeta();
  if (meta.isPending) return <Loader size="sm" />;
  if (meta.isError) {
    return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  }
  return <RecentChangesScreen meta={meta.data} />;
}

function RecentChangesScreen({ meta }: { meta: Meta }) {
  const [search, setSearch] = useUrlSearch();
  const feed = useChangeFeed(changeFeedRequest(search));
  const filtered = hasChangeFilters(search);

  let body;
  if (feed.isError) {
    body = <ErrorAlert title="Could not load the changes" error={feed.error} onRetry={() => void feed.refetch()} />;
  } else if (feed.isPending) {
    body = <Loader size="sm" />;
  } else if (feed.data.items.length === 0) {
    body = filtered ? (
      <EmptyState icon={<IconFilterOff size={28} />} title="No changes match the filters">
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
      <EmptyState icon={<IconHistory size={28} />} title="No changes recorded yet" />
    );
  } else {
    body = (
      <ChangeFeedTable
        items={feed.data.items}
        meta={meta}
        batchFilter={search.batch_id}
        onShowBatch={(batchId) => {
          setSearch((previous) => withParam(previous, 'batch_id', batchId));
        }}
      />
    );
  }

  return (
    <Stack gap="sm">
      <Group gap="xs" align="baseline">
        <Title order={1}>Recent changes</Title>
        <Text c="dimmed" size="sm" aria-live="polite">
          {feed.data ? `${count.format(feed.data.total)} ${feed.data.total === 1 ? 'revision' : 'revisions'}` : ''}
        </Text>
      </Group>
      <ChangeFeedFilters meta={meta} search={search} setSearch={setSearch} />
      <div aria-busy={feed.isPlaceholderData}>{body}</div>
      {feed.data && feed.data.total > 0 && <FeedPagination total={feed.data.total} search={search} setSearch={setSearch} />}
    </Stack>
  );
}
