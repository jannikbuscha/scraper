// Footer pagination of the feed and trash pages: page numbers with first and
// last, page size 25 / 50 / 100 / 200 and the row range, kept in the URL
// (`page`, `page_size`) like the tables. A page past the end of a list that has
// rows (after its last rows were decided, undeleted or deleted, or from an old
// link) has its own empty state, `FeedPastEnd`, and keeps the page links.
import { Button, EmptyState, Group, Pagination, Select, Text } from '@mantine/core';
import { IconFileOff } from '@tabler/icons-react';

import type { SetSearchOptions, SearchUpdate } from '../../hooks/useUrlSearch';
import { getPage, getPageSize, PAGE_SIZES, withPage, withPageSize, type SearchRecord } from '../../lib/query-string';

const count = new Intl.NumberFormat('en-US');

const CONTROL_LABELS = { first: 'First page', previous: 'Previous page', next: 'Next page', last: 'Last page' } as const;

interface FeedPaginationProps {
  total: number;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

/** The number of pages of `total` rows at the URL's page size (at least 1). */
export const pageCount = (total: number, search: SearchRecord): number => Math.max(1, Math.ceil(total / getPageSize(search)));

export function FeedPagination({ total, search, setSearch }: FeedPaginationProps) {
  const page = getPage(search);
  const pageSize = getPageSize(search);
  const pages = pageCount(total, search);
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);
  // A page size from a shared URL stays selectable.
  const sizes = [...new Set<number>([...PAGE_SIZES, pageSize])].sort((a, b) => a - b);

  return (
    <Group gap="sm" justify="flex-end" wrap="wrap">
      <Text size="sm" c="dimmed">
        {first > total
          ? `${count.format(total)} in total`
          : `${count.format(first)}–${count.format(last)} of ${count.format(total)}`}
      </Text>
      {/* Past the end the links stay, with no page marked current, so the way back is in the footer too. */}
      {(pages > 1 || page > pages) && (
        <nav aria-label="Pages">
          <Pagination
            size="sm"
            total={pages}
            value={page}
            withEdges
            onChange={(next) => {
              setSearch((previous) => withPage(previous, next));
            }}
            getControlProps={(control) => ({ 'aria-label': CONTROL_LABELS[control] })}
            getItemProps={(item) => ({ 'aria-label': `Page ${item}` })}
          />
        </nav>
      )}
      <Group gap={6} wrap="nowrap">
        <Select
          size="xs"
          w={80}
          aria-label="Rows per page"
          data={sizes.map(String)}
          value={String(pageSize)}
          allowDeselect={false}
          onChange={(value) => {
            if (value) setSearch((previous) => withPageSize(previous, Number(value)));
          }}
          comboboxProps={{ withinPortal: true }}
        />
        <Text size="sm" c="dimmed">
          per page
        </Text>
      </Group>
    </Group>
  );
}

/**
 * The body of a list page past its end (docs/UI.md §3, §5): the list is not
 * empty, so this says where its rows are instead of showing the list's empty
 * state ("No open proposals", "No runs yet"), and leads to the last page.
 */
export function FeedPastEnd({ total, search, setSearch }: FeedPaginationProps) {
  const pages = pageCount(total, search);
  return (
    <EmptyState
      icon={<IconFileOff size={28} />}
      title="This page is past the end of the list"
      description={`${count.format(total)} in total; the last page is page ${count.format(pages)}.`}
    >
      <EmptyState.Actions>
        <Button
          variant="light"
          onClick={() => {
            setSearch((previous) => withPage(previous, pages));
          }}
        >
          Go to the last page
        </Button>
      </EmptyState.Actions>
    </EmptyState>
  );
}
